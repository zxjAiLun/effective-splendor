"""Strict Arena NDJSON agent backed by an M17 checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import torch

from .data import catalog_semantic_hash, load_catalog
from .encoding import encode_action, encode_observation
from .model import ModelSpec, build_model
from .train import checkpoint_semantic_hash

PROTOCOL_VERSION = "0.5"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def load_model(path: Path, required_hash: str, device: torch.device):
    if len(required_hash) != 64 or any(c not in "0123456789abcdef" for c in required_hash):
        raise ValueError("checkpoint hash must be 64 lowercase hex characters")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    metadata = payload["metadata"]
    if metadata.get("format") != "effective-splendor-gpu-checkpoint" or metadata.get("version") != 1:
        raise ValueError("unsupported checkpoint format/version")
    actual = checkpoint_semantic_hash(metadata, payload["state_dict"])
    if actual != required_hash:
        raise ValueError(f"checkpoint hash mismatch: expected {required_hash}, got {actual}")
    spec = ModelSpec(**metadata["architecture"])
    model = build_model(spec)
    model.load_state_dict(payload["state_dict"], strict=True)
    model.to(device).eval()
    if metadata.get("value_order") != "viewer_relative":
        raise ValueError("checkpoint value_order is not viewer_relative")
    return model, metadata


def run(model, metadata: dict[str, Any], catalog: dict[str, Any], device: torch.device) -> None:
    game_id: str | None = None
    latest_observation: dict[str, Any] | None = None
    latest_hash: str | None = None
    last_request = 0
    for raw in sys.stdin:
        message = json.loads(raw)
        kind = message.get("type")
        if kind == "hello":
            if game_id is not None or message.get("protocol_version") != PROTOCOL_VERSION:
                raise ValueError("invalid or duplicate server hello")
            game_id = message["game_id"]
            send({"type": "hello", "protocol_version": PROTOCOL_VERSION, "game_id": game_id, "agent_name": "effective-splendor-gpu-agent-v1", "agent_version": metadata["model_id"]})
        elif kind == "observation":
            if message.get("game_id") != game_id: raise ValueError("observation game_id mismatch")
            latest_observation, latest_hash = message["observation"], message["observation_hash"]
        elif kind == "request_action":
            if latest_observation is None or message.get("observation_hash") != latest_hash:
                raise ValueError("request_action does not bind latest observation")
            request_id = int(message["request_id"])
            if request_id <= last_request: raise ValueError("request_id must increase")
            last_request = request_id
            legal = message["legal_actions"]
            if not legal: raise ValueError("empty legal_actions")
            encoded = encode_observation(latest_observation, catalog)
            actions = torch.stack([encode_action(action) for action in legal])
            with torch.inference_mode():
                logits, _ = model(encoded.entities.unsqueeze(0).to(device), encoded.mask.unsqueeze(0).to(device), encoded.global_features.unsqueeze(0).to(device), actions.unsqueeze(0).to(device), torch.ones((1, len(legal)), dtype=torch.bool, device=device))
            chosen = int(logits[0].argmax().item())
            send({"type": "action", "protocol_version": PROTOCOL_VERSION, "game_id": game_id, "request_id": request_id, "action": legal[chosen]})
        elif kind == "ping":
            send({"type": "pong", "protocol_version": PROTOCOL_VERSION, "game_id": game_id})
        elif kind == "game_end":
            return
        elif kind == "error":
            raise ValueError(f"server error: {message.get('message')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-hash", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available(): raise RuntimeError("CUDA requested but unavailable")
    device = torch.device(args.device)
    model, metadata = load_model(args.checkpoint, args.checkpoint_hash, device)
    catalog = load_catalog(args.catalog)
    if catalog_semantic_hash(catalog) != metadata.get("catalog_hash"):
        raise ValueError("catalog hash does not match checkpoint metadata")
    run(model, metadata, catalog, device)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
