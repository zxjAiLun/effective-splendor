"""Arena v0.5 M39A stochastic direct-policy agent with trajectory sidecar.

Two execution modes share one protocol/sidecar implementation:

- resident mode (default): load the checkpoint in-process and infer locally.
  Costs a full torch import + CUDA context per game. Kept for evaluation
  gates and single-game audits where per-process isolation matters.
- proxy mode (``--server-url`` + ``--server-ready``): a lightweight
  stdlib-only process that forwards each decision to a resident
  :mod:`m39a_server` and performs categorical sampling locally. The stub
  verifies the server's ready-file identity (checkpoint/plan/catalog hashes)
  before the first inference, and the server echoes that binding on every
  response, so the sidecar provenance fields remain bound to the exact
  checkpoint — identical to resident mode.

Sampling, seed derivation, sidecar writing, and every protocol check run
identically in both modes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from .m39a_contract import SIDECAR_FORMAT, SIDECAR_VERSION, validate_sidecar

PROTOCOL_VERSION = "0.5"
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
AGENT_NAME = "effective-splendor-m39a-policy-value-agent-v1"


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"sidecar output already exists: {path}")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    if temporary.exists():
        raise FileExistsError(f"temporary sidecar already exists: {temporary}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _f32(value: float) -> float:
    """Round to float32, matching the torch f32 pipeline bit-for-bit."""
    return float(__import__("struct").unpack("<f", __import__("struct").pack("<f", value))[0])


def _log_softmax(values: Sequence[float], *, f32: bool = False) -> list[float]:
    if not values:
        raise ValueError("categorical logits must be a non-empty vector")
    floats = [_f32(float(value)) for value in values] if f32 else [float(value) for value in values]
    if not all(math.isfinite(value) for value in floats):
        raise ValueError("categorical logits are non-finite")
    max_value = max(floats)
    exps = [math.exp(value - max_value) for value in floats]
    total = sum(exps)
    if f32:
        # torch f32 log_softmax computes exp/log in f32 arithmetic; emulate by
        # rounding each intermediate to f32. This reproduces the frozen
        # reference to within f32 ulp, keeping drift far below the 1e-6 gate.
        total = _f32(total)
        return [_f32(value - max_value - _f32(math.log(total))) for value in floats]
    return [value - max_value - math.log(total) for value in floats]


def categorical_index(logits, seed: int) -> tuple[int, float]:
    """Frozen SPLITMIX64 categorical draw.

    Accepts either a local torch tensor or the plain list returned by the
    resident server; the log-softmax and cumulative walk are identical pure
    float math in both cases.
    """
    if hasattr(logits, "cpu"):
        values = [float(value) for value in logits.detach().cpu().tolist()]
    else:
        values = [float(value) for value in logits]
    # The frozen reference normalizes in float32 (torch log_softmax on an
    # f32 tensor); server responses already carry f32-rounded logits, and
    # rounding again here makes both paths share the same f32 domain.
    log_probs = _log_softmax(values, f32=True)
    unit = (int(seed) >> 11) * (2.0 ** -53)
    cumulative = 0.0
    chosen = len(log_probs) - 1
    for index, log_probability in enumerate(log_probs):
        cumulative += math.exp(log_probability)
        if unit < cumulative:
            chosen = index
            break
    return chosen, log_probs[chosen]


class ServerProxy:
    """Newline-delimited JSON client for the resident inference server."""

    def __init__(
        self,
        url: str,
        ready_file: Path,
        *,
        expected_plan_hash: str,
        expected_checkpoint_sha256: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        host_part, _, port_text = url.rpartition(":")
        if not host_part or not port_text.isdigit():
            raise ValueError(f"invalid server url {url!r}; expected host:port")
        self._address = (host_part, int(port_text))
        self._timeout = timeout_seconds
        self._socket: socket.socket | None = None
        ready = json.loads(ready_file.read_text(encoding="utf-8"))
        if (
            ready.get("format") != "effective-splendor-m39a-inference-server"
            or int(ready.get("version", 0)) != 1
        ):
            raise ValueError("server ready file is not a v1 m39a inference server")
        for field, expected in (
            ("plan_hash", expected_plan_hash),
            ("checkpoint_sha256", expected_checkpoint_sha256),
        ):
            if ready.get(field) != expected:
                raise ValueError(
                    f"server ready file {field} mismatch: expected {expected!r}, "
                    f"got {ready.get(field)!r}"
                )
        self.identity = {
            "checkpoint_sha256": ready["checkpoint_sha256"],
            "checkpoint_hash": ready["checkpoint_hash"],
            "checkpoint_cycle": int(ready["checkpoint_cycle"]),
            "catalog_hash": ready["catalog_hash"],
        }

    def _connect(self) -> socket.socket:
        if self._socket is None:
            connection = socket.create_connection(self._address, timeout=self._timeout)
            connection.settimeout(self._timeout)
            self._socket = connection
        return self._socket

    def _recv_line(self) -> bytes:
        connection = self._connect()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                raise ConnectionError("server closed the connection")
            total += len(chunk)
            if total > MAX_MESSAGE_BYTES:
                raise ConnectionError("server response exceeds size bound")
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        return b"".join(chunks).split(b"\n", 1)[0]

    def infer(
        self,
        observation: dict[str, Any],
        legal_actions: Sequence[dict[str, Any]],
    ) -> tuple[list[float], list[float], float, list[float], list[float]]:
        request = {"observation": observation, "legal_actions": list(legal_actions)}
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise ValueError("inference request exceeds size bound")
        # One retry on a transient connection break. Inference is a pure
        # function of (observation, legal_actions); a request whose
        # connection died mid-flight produced no state on the server, so a
        # single reconnect-and-resend cannot change semantics. A dead
        # server still fails after the retry, exactly as before.
        try:
            response = self._request(payload)
        except (ConnectionError, OSError):
            self.close()
            response = self._request(payload)
        if response.get("status") != "ok":
            raise RuntimeError(f"server inference failed: {response.get('message')}")
        for field, expected in self.identity.items():
            if response.get(field) != expected:
                raise RuntimeError(f"server response {field} binding mismatch")
        return (
            response["logits"],
            response["values"],
            float(response["auxiliary"]),
            response["log_probabilities"],
            response["probabilities"],
        )

    def _request(self, payload: bytes) -> dict[str, Any]:
        connection = self._connect()
        connection.sendall(payload + b"\n")
        return json.loads(self._recv_line().decode("utf-8"))

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


def frozen_draw(
    probabilities: Sequence[float] | None,
    log_probabilities: Sequence[float] | None,
    logits,
    seed: int,
) -> tuple[int, float]:
    """The frozen SPLITMIX64 categorical draw.

    When torch-computed f32 ``probabilities``/``log_probabilities`` are
    available (resident server responses, or the resident in-process mode),
    the cumulative walk uses them directly so the selection is bit-identical
    to the original frozen implementation
    (``torch.log_softmax(...).exp().cpu().tolist()``). Only when neither is
    supplied does it fall back to ``categorical_index``, which approximates
    the same computation locally.
    """
    if probabilities is not None:
        probs = [float(p) for p in probabilities]
        unit = (int(seed) >> 11) * (2.0 ** -53)
        cumulative = 0.0
        chosen = len(probs) - 1
        for index, probability in enumerate(probs):
            cumulative += probability
            if unit < cumulative:
                chosen = index
                break
        if log_probabilities is not None:
            return chosen, float(log_probabilities[chosen])
        return chosen, math.log(probs[chosen]) if probs[chosen] > 0 else float("-inf")
    return categorical_index(logits, seed)


def run_agent_loop(
    *,
    infer: Callable[
        [dict[str, Any], Sequence[dict[str, Any]]],
        tuple[
            Any,
            Sequence[float],
            float,
            Sequence[float] | None,
            Sequence[float] | None,
        ],
    ],
    checkpoint_hash: str,
    checkpoint_cycle: int,
    checkpoint_sha256: str,
    plan_hash: str,
    game_index: int,
    sidecar_out: Path,
    catalog_hash: str,
    action_selection: str = "categorical",
    input_lines: Sequence[str] | None = None,
    close: Callable[[], None] | None = None,
    agent_name: str = "effective-splendor-m39a-policy-value-agent-v1",
    sidecar_format: str = SIDECAR_FORMAT,
    sidecar_version: int = SIDECAR_VERSION,
    extra_sidecar_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Drive one full Arena game and write the trajectory sidecar.

    ``infer`` maps ``(observation, legal_actions)`` to ``(logits, values,
    auxiliary, log_probabilities, probabilities)``; the last two elements
    are the torch f32 log-softmax outputs when the caller can supply them
    (server responses and the resident in-process mode both do) and
    ``None`` otherwise. Every protocol rule and sidecar field below is
    shared between modes.
    """
    game_id: str | None = None
    seat: int | None = None
    latest_observation: dict[str, Any] | None = None
    latest_hash: str | None = None
    last_request = 0
    records: list[dict[str, Any]] = []
    final_result: dict[str, Any] | None = None
    lines = input_lines if input_lines is not None else sys.stdin

    try:
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            message = json.loads(raw)
            kind = message.get("type")
            if kind == "hello":
                if game_id is not None or message.get("protocol_version") != PROTOCOL_VERSION:
                    raise ValueError("invalid or duplicate server hello")
                game_id = str(message["game_id"])
                _send(
                    {
                        "type": "hello",
                        "protocol_version": PROTOCOL_VERSION,
                        "game_id": game_id,
                        "agent_name": agent_name,
                        "agent_version": checkpoint_hash,
                    }
                )
            elif kind == "game_start":
                if message.get("game_id") != game_id:
                    raise ValueError("game_start game_id mismatch")
                if int(message.get("player_count", 0)) != 2:
                    raise ValueError("M39A is 1v1 only")
                seat = int(message["recipient_player_id"])
                if seat not in (0, 1):
                    raise ValueError("M39A seat must be 0 or 1")
            elif kind == "observation":
                if message.get("game_id") != game_id:
                    raise ValueError("observation game_id mismatch")
                latest_observation = message["observation"]
                latest_hash = str(message["observation_hash"])
            elif kind == "request_action":
                if seat is None or latest_observation is None:
                    raise ValueError("request_action arrived before game_start/observation")
                if message.get("game_id") != game_id or message.get("observation_hash") != latest_hash:
                    raise ValueError("request_action does not bind latest observation")
                request_id = int(message["request_id"])
                if request_id <= last_request:
                    raise ValueError("request_id must increase globally")
                last_request = request_id
                legal_actions = message.get("legal_actions")
                if not isinstance(legal_actions, list) or not legal_actions:
                    raise ValueError("request_action legal_actions must be non-empty")
                logits, values, auxiliary, server_log_probs, server_probs = infer(
                    latest_observation, legal_actions
                )
                from .m39a_contract import decision_seed

                seed = decision_seed(game_index, seat, request_id)
                if action_selection == "categorical":
                    chosen_index, old_log_probability = frozen_draw(
                        server_probs, server_log_probs, logits, seed
                    )
                elif action_selection == "argmax":
                    if server_log_probs is not None:
                        float_logits = [float(value) for value in logits]
                        chosen_index = max(
                            range(len(float_logits)), key=float_logits.__getitem__
                        )
                        old_log_probability = float(server_log_probs[chosen_index])
                    elif hasattr(logits, "argmax"):
                        import torch

                        chosen_index = int(logits.argmax().item())
                        old_log_probability = float(
                            torch.log_softmax(logits.to(dtype=torch.float32), dim=0)[
                                chosen_index
                            ].item()
                        )
                    else:
                        float_logits = [float(value) for value in logits]
                        chosen_index = max(
                            range(len(float_logits)), key=float_logits.__getitem__
                        )
                        old_log_probability = _log_softmax(float_logits)[chosen_index]
                else:
                    raise ValueError(f"unsupported action_selection {action_selection!r}")
                action = legal_actions[chosen_index]
                records.append(
                    {
                        "game_index": game_index,
                        "game_id": game_id,
                        "seat": seat,
                        "ply_index": request_id - 1,
                        "request_id": request_id,
                        "observation_hash": latest_hash,
                        "observation": latest_observation,
                        "legal_actions": legal_actions,
                        "action": action,
                        "decision_seed": seed,
                        "old_log_probability": old_log_probability,
                        "old_value": float(values[0]),
                        "old_value_by_player": [float(value) for value in values],
                        "old_auxiliary_score": float(auxiliary),
                    }
                )
                _send(
                    {
                        "type": "action",
                        "protocol_version": PROTOCOL_VERSION,
                        "game_id": game_id,
                        "request_id": request_id,
                        "action": action,
                    }
                )
            elif kind == "ping":
                _send(
                    {
                        "type": "pong",
                        "protocol_version": PROTOCOL_VERSION,
                        "game_id": game_id,
                    }
                )
            elif kind in {"event", "action_applied"}:
                if message.get("game_id") != game_id:
                    raise ValueError(f"{kind} game_id mismatch")
            elif kind == "game_end":
                if message.get("game_id") != game_id:
                    raise ValueError("game_end game_id mismatch")
                final_result = message["result"]
                break
            elif kind == "game_truncated":
                if message.get("game_id") != game_id:
                    raise ValueError("game_truncated game_id mismatch")
                final_result = {
                    "truncated": True,
                    "completed_plies": int(message["completed_plies"]),
                    "cap_state_hash": str(message["cap_state_hash"]),
                    "cap_scores": [int(score) for score in message["cap_scores"]],
                }
                break
            elif kind == "error":
                raise ValueError(f"server error: {message.get('message')}")
            else:
                raise ValueError(f"unsupported server message type: {kind!r}")
    finally:
        if close is not None:
            close()

    if game_id is None or seat is None or final_result is None:
        raise ValueError("agent stream ended before a completed game_end")

    sidecar = {
        "format": sidecar_format,
        "version": sidecar_version,
        **(extra_sidecar_fields or {}),
        "plan_hash": plan_hash,
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_cycle": checkpoint_cycle,
        "catalog_hash": catalog_hash,
        "game_id": game_id,
        "game_index": game_index,
        "seat": seat,
        "records": records,
        "result": final_result,
    }
    if sidecar["format"] == SIDECAR_FORMAT:
        # The M39A self-check; M40A sidecars (different format identity,
        # extra fields like `arm`) are validated by the authoritative Rust
        # materializer instead.
        validate_sidecar(sidecar)
    _atomic_json(sidecar_out, sidecar)
    return sidecar


def main() -> None:
    parser = argparse.ArgumentParser(description="M39A Arena policy/value agent")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--game-index", type=int, required=True)
    parser.add_argument("--sidecar-out", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument(
        "--action-selection", choices=["categorical", "argmax"], default="categorical"
    )
    parser.add_argument(
        "--server-url",
        help="proxy mode: host:port of a resident m39a_server instead of a local model",
    )
    parser.add_argument(
        "--server-ready",
        type=Path,
        help="proxy mode: ready file of the resident server, verifying its identity",
    )
    args = parser.parse_args()

    if args.server_url is not None:
        if args.server_ready is None:
            raise ValueError("--server-url requires --server-ready")
        proxy = ServerProxy(
            args.server_url,
            args.server_ready,
            expected_plan_hash=args.plan_hash,
            expected_checkpoint_sha256=args.checkpoint_sha256,
        )
        run_agent_loop(
            infer=proxy.infer,
            checkpoint_hash=proxy.identity["checkpoint_hash"],
            checkpoint_cycle=proxy.identity["checkpoint_cycle"],
            checkpoint_sha256=proxy.identity["checkpoint_sha256"],
            plan_hash=args.plan_hash,
            game_index=args.game_index,
            sidecar_out=args.sidecar_out,
            catalog_hash=proxy.identity["catalog_hash"],
            action_selection=args.action_selection,
            close=proxy.close,
        )
        return

    if args.checkpoint is None or args.catalog is None:
        raise ValueError("resident mode requires --checkpoint and --catalog")

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

    import torch

    from .data import catalog_semantic_hash, load_catalog
    from .m39a_model import infer_decision, load_m39a_checkpoint

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_num_threads(1)
    device = torch.device(args.device)
    model, checkpoint_payload = load_m39a_checkpoint(
        args.checkpoint,
        expected_file_sha256=args.checkpoint_sha256,
        expected_plan_hash=args.plan_hash,
        device=device,
    )
    catalog = load_catalog(args.catalog)
    cat_hash = catalog_semantic_hash(catalog)
    if checkpoint_payload["metadata"].get("catalog_hash") != cat_hash:
        raise ValueError("checkpoint catalog hash does not match supplied catalog")

    def infer(observation, legal_actions):
        logits, values, auxiliary = infer_decision(
            model, observation, legal_actions, catalog, device
        )
        log_probs = torch.log_softmax(logits.to(dtype=torch.float32), dim=0)
        probabilities = log_probs.exp()
        return (
            logits,
            [float(value) for value in values.cpu().tolist()],
            float(auxiliary.item()),
            [float(lp) for lp in log_probs.cpu().tolist()],
            [float(p) for p in probabilities.cpu().tolist()],
        )

    run_agent_loop(
        infer=infer,
        checkpoint_hash=str(checkpoint_payload["checkpoint_hash"]),
        checkpoint_cycle=int(checkpoint_payload["metadata"]["cycle"]),
        checkpoint_sha256=args.checkpoint_sha256,
        plan_hash=args.plan_hash,
        game_index=args.game_index,
        sidecar_out=args.sidecar_out,
        catalog_hash=cat_hash,
        action_selection=args.action_selection,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
