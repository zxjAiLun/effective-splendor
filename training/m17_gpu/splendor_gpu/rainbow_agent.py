"""Strict Arena agent for an M18B distributional Q checkpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import torch

from .data import catalog_semantic_hash, load_catalog
from .encoding import encode_action, encode_observation
from .rainbow import load_rainbow_model

PROTOCOL_VERSION = "0.5"


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-hash", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    args = parser.parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    device = torch.device(args.device)
    model, metadata = load_rainbow_model(args.checkpoint, args.checkpoint_hash, device)
    catalog = load_catalog(args.catalog)
    if catalog_semantic_hash(catalog) != metadata["catalog_hash"]:
        raise ValueError("catalog hash mismatch")
    game_id = None; observation = None; observation_hash = None; last_request = 0
    for raw in sys.stdin:
        message = json.loads(raw); kind = message.get("type")
        if kind == "hello":
            if game_id is not None or message.get("protocol_version") != PROTOCOL_VERSION:
                raise ValueError("invalid hello")
            game_id = message["game_id"]
            send({"type": "hello", "protocol_version": PROTOCOL_VERSION, "game_id": game_id, "agent_name": "effective-splendor-rainbow-agent-v1", "agent_version": metadata["model_id"]})
        elif kind == "observation":
            observation, observation_hash = message["observation"], message["observation_hash"]
        elif kind == "request_action":
            if observation is None or message.get("observation_hash") != observation_hash:
                raise ValueError("request not bound to observation")
            request_id = int(message["request_id"])
            if request_id <= last_request: raise ValueError("request_id must increase")
            last_request = request_id; legal = message["legal_actions"]
            encoded = encode_observation(observation, catalog)
            actions = torch.stack([encode_action(action) for action in legal])
            with torch.inference_mode():
                logits = model(encoded.entities.unsqueeze(0).to(device), encoded.mask.unsqueeze(0).to(device), encoded.global_features.unsqueeze(0).to(device), actions.unsqueeze(0).to(device), torch.ones((1, len(legal)), dtype=torch.bool, device=device))
                chosen = int(model.expected_q(logits)[0].argmax().item())
            send({"type": "action", "protocol_version": PROTOCOL_VERSION, "game_id": game_id, "request_id": request_id, "action": legal[chosen]})
        elif kind == "ping":
            send({"type": "pong", "protocol_version": PROTOCOL_VERSION, "game_id": game_id})
        elif kind == "game_end": return
        elif kind == "error": raise ValueError(message.get("message", "server error"))


if __name__ == "__main__":
    try: main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n"); sys.stderr.flush(); raise SystemExit(1)
