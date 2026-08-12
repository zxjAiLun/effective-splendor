"""Persistent player-view GPU inference service for Rust neural ISMCTS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import torch

from .agent import load_model
from .data import catalog_semantic_hash, load_catalog
from .encoding import encode_action, encode_observation


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
    model, metadata = load_model(args.checkpoint, args.checkpoint_hash, device)
    catalog = load_catalog(args.catalog)
    if catalog_semantic_hash(catalog) != metadata.get("catalog_hash"):
        raise ValueError("catalog hash does not match checkpoint metadata")
    send({
        "type": "ready",
        "version": 1,
        "model_id": metadata["model_id"],
        "checkpoint_hash": args.checkpoint_hash,
        "value_order": "absolute_seat",
        "device": str(device),
    })

    for raw in sys.stdin:
        request = json.loads(raw)
        if request.get("type") == "shutdown":
            return
        if request.get("type") != "predict" or request.get("version") != 1:
            raise ValueError("unsupported inference request")
        observation = request["observation"]
        legal = request["legal_actions"]
        if not legal:
            raise ValueError("prediction requires legal actions")
        encoded = encode_observation(observation, catalog)
        actions = torch.stack([encode_action(action) for action in legal])
        with torch.inference_mode():
            logits, relative_values = model(
                encoded.entities.unsqueeze(0).to(device),
                encoded.mask.unsqueeze(0).to(device),
                encoded.global_features.unsqueeze(0).to(device),
                actions.unsqueeze(0).to(device),
                torch.ones((1, len(legal)), dtype=torch.bool, device=device),
            )
            probabilities = torch.softmax(logits[0], dim=0).cpu().tolist()
            relative = relative_values[0].cpu().tolist()
        viewer = int(observation["viewer"])
        absolute = [0.0, 0.0]
        absolute[viewer] = float(relative[0])
        absolute[1 - viewer] = float(relative[1])
        send({
            "type": "prediction",
            "version": 1,
            "request_id": request["request_id"],
            "policy": [
                {"action": action, "probability": float(probability)}
                for action, probability in zip(legal, probabilities, strict=True)
            ],
            "value_by_player": absolute,
        })


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
