"""M41A lightweight branch-continuation proxy agent.

A torch-free stdio agent implementing the exact M35A/D2-v2 agent
protocol: it owns the LiveBeliefTracker state machine and the argmax
selection, and forwards the deterministic forward pass to the resident
inference server (`m41a_server.py`). Per-branch spawn cost is a bare
Python start (no torch import, no checkpoint load, no CUDA context) —
the authorized executor optimization; trajectory equivalence vs the
in-process agent is enforced by the bitwise equivalence gate.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "0.5"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
SERVER_FORMAT = "effective-splendor-m41a-inference-server"


class ResidentClient:
    """Full-identity-bound resident client: the ready file's identity is
    checked at construction (including host/port consistency with the
    CLI url) and EVERY response re-validates the same identity — a
    response from a different server (or a re-bound ready file) fails
    closed mid-match rather than silently proceeding."""

    def __init__(self, url: str, ready_file: Path, expected_sha: str) -> None:
        ready = json.loads(ready_file.read_text(encoding="utf-8"))
        if ready.get("format") != SERVER_FORMAT:
            raise ValueError("ready file is not an M41A inference server")
        host, _, port_text = url.rpartition(":")
        if not host or not port_text.isdigit():
            raise ValueError(f"invalid server url {url!r}")
        # URL must match the ready file's bound endpoint exactly.
        if host != ready.get("host") or int(port_text) != int(ready.get("port", -1)):
            raise ValueError(
                f"--server-url {url!r} does not match the ready file's "
                f"endpoint {ready.get('host')}:{ready.get('port')}"
            )
        if ready.get("checkpoint_sha256") != expected_sha:
            raise ValueError("server checkpoint SHA mismatch")
        self._identity = {
            "model_id": ready.get("model_id"),
            "checkpoint_sha256": ready.get("checkpoint_sha256"),
            "checkpoint_semantic_sha256": ready.get("checkpoint_semantic_sha256"),
            "catalog_hash": ready.get("catalog_hash"),
            "server_source_sha256": ready.get("server_source_sha256"),
        }
        self._socket = socket.create_connection((host, int(port_text)), timeout=120)

    def infer(self, observation: dict, legal_actions: list) -> list[float]:
        request = {"observation": observation, "legal_actions": legal_actions}
        self._socket.sendall(
            json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        chunks = []
        total = 0
        while True:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ConnectionError("server closed mid-response")
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ConnectionError("response exceeds size bound")
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        line = b"".join(chunks).split(b"\n", 1)[0]
        response = json.loads(line.decode("utf-8"))
        if response.get("status") != "ok":
            raise RuntimeError(f"server error: {response.get('message')}")
        # EVERY response re-validates the identity (echoed by the server).
        for field, expected in self._identity.items():
            if response.get(field) != expected:
                raise ValueError(
                    f"server response identity mismatch on {field!r}: "
                    f"{response.get(field)!r} != {expected!r}"
                )
        return response["scores"]

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="M41A resident-proxy agent (D2-v2)")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--server-ready", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    args = parser.parse_args()

    client = ResidentClient(args.server_url, args.server_ready, args.checkpoint_sha256)
    game_id: str | None = None
    seat = 0
    latest_observation: dict | None = None
    latest_hash: str | None = None
    last_request = 0

    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            message = json.loads(raw)
            kind = message.get("type")

            if kind == "hello":
                if game_id is not None or message.get("protocol_version") != PROTOCOL_VERSION:
                    raise ValueError("invalid or duplicate server hello")
                game_id = str(message["game_id"])
                send({
                    "type": "hello",
                    "protocol_version": PROTOCOL_VERSION,
                    "game_id": game_id,
                    "agent_name": "effective-splendor-m35a-direct-agent-v1",
                    "agent_version": "M25-D2-v2",
                })
            elif kind == "game_start":
                if message.get("game_id") != game_id:
                    raise ValueError("game_start game_id mismatch")
                seat = int(message.get("recipient_player_id", message.get("seat", 0)))
            elif kind in ("event", "action_applied", "observation"):
                if message.get("game_id") != game_id:
                    raise ValueError(f"{kind} game_id mismatch")
                if kind == "observation":
                    latest_observation = message["observation"]
                    latest_hash = str(message["observation_hash"])
            elif kind == "request_action":
                if latest_observation is None or message.get("observation_hash") != latest_hash:
                    raise ValueError("request_action does not bind latest observation")
                request_id = int(message["request_id"])
                if request_id <= last_request:
                    raise ValueError("request_id must increase")
                last_request = request_id
                legal = message["legal_actions"]
                if not isinstance(legal, list) or not legal:
                    raise ValueError("empty legal_actions")
                # D2-v2 has NO belief-feature dependence (59-dim delta
                # path): the forward depends only on (observation,
                # legal_actions), so the resident forward is exact.
                scores = client.infer(latest_observation, legal)
                chosen = max(range(len(scores)), key=scores.__getitem__)
                send({
                    "type": "action",
                    "protocol_version": PROTOCOL_VERSION,
                    "game_id": game_id,
                    "request_id": request_id,
                    "action": legal[chosen],
                })
            elif kind == "ping":
                send({
                    "type": "pong",
                    "protocol_version": PROTOCOL_VERSION,
                    "game_id": game_id,
                })
            elif kind in ("game_end", "game_truncated"):
                if message.get("game_id") != game_id:
                    raise ValueError(f"{kind} game_id mismatch")
                return
            elif kind == "error":
                raise ValueError(f"server error: {message.get('message')}")
            else:
                raise ValueError(f"unsupported server message type: {kind!r}")
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
