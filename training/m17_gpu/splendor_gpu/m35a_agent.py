"""Strict Arena NDJSON direct-policy agent for M35A Retrospective Evaluation."""

from __future__ import annotations

import os
# Pin threads immediately before importing torch
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import torch
torch.set_num_threads(1)
torch.set_num_interop_threads(1)

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_adapters import score_model_actions
from splendor_gpu.m35a_belief import LiveBeliefTracker
from splendor_gpu.m35a_registry import (
    REGISTRY,
    load_and_validate_checkpoint,
    ModelRegistryEntry,
)

PROTOCOL_VERSION = "0.5"


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run_agent_loop(
    model: torch.nn.Module,
    entry: ModelRegistryEntry,
    catalog: dict[str, Any],
    device: torch.device,
) -> None:
    game_id: str | None = None
    seat: int = 0
    belief_tracker = LiveBeliefTracker(viewer=0, player_count=2)
    latest_observation: dict[str, Any] | None = None
    latest_hash: str | None = None
    last_request = 0

    for raw in sys.stdin:
        raw_str = raw.strip()
        if not raw_str:
            continue
        message = json.loads(raw_str)
        kind = message.get("type")

        if kind == "hello":
            if game_id is not None or message.get("protocol_version") != PROTOCOL_VERSION:
                raise ValueError("invalid or duplicate server hello")
            game_id = message["game_id"]
            send({
                "type": "hello",
                "protocol_version": PROTOCOL_VERSION,
                "game_id": game_id,
                "agent_name": "effective-splendor-m35a-direct-agent-v1",
                "agent_version": entry.model_id,
            })

        elif kind == "game_start":
            if message.get("game_id") != game_id:
                raise ValueError("game_start game_id mismatch")
            seat = int(message.get("recipient_player_id", message.get("seat", 0)))
            pcount = int(message.get("player_count", 2))
            belief_tracker.reset(viewer=seat, player_count=pcount)

        elif kind == "event":
            if message.get("game_id") != game_id:
                raise ValueError("event game_id mismatch")
            evt = message.get("event")
            if evt:
                belief_tracker.handle_event(evt)

        elif kind == "action_applied":
            if message.get("game_id") != game_id:
                raise ValueError("action_applied game_id mismatch")

        elif kind == "observation":
            if message.get("game_id") != game_id:
                raise ValueError("observation game_id mismatch")
            latest_observation = message["observation"]
            latest_hash = message["observation_hash"]

        elif kind == "request_action":
            if latest_observation is None or message.get("observation_hash") != latest_hash:
                raise ValueError("request_action does not bind latest observation")
            request_id = int(message["request_id"])
            if request_id <= last_request:
                raise ValueError("request_id must increase")
            last_request = request_id

            legal = message["legal_actions"]
            if not legal:
                raise ValueError("empty legal_actions")

            # Score actions using model adapter
            scores = score_model_actions(
                model=model,
                entry=entry,
                observation=latest_observation,
                legal_actions=legal,
                belief_tracker=belief_tracker,
                catalog=catalog,
                device=device,
            )

            chosen_idx = int(scores.argmax().item())
            send({
                "type": "action",
                "protocol_version": PROTOCOL_VERSION,
                "game_id": game_id,
                "request_id": request_id,
                "action": legal[chosen_idx],
            })

        elif kind == "ping":
            send({
                "type": "pong",
                "protocol_version": PROTOCOL_VERSION,
                "game_id": game_id,
            })

        elif kind == "game_end":
            return

        elif kind == "error":
            raise ValueError(f"server error: {message.get('message')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="M35A Arena Direct Policy Agent")
    parser.add_argument("--model-id", required=True, choices=list(REGISTRY.keys()))
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    device = torch.device(args.device)

    catalog = load_catalog(args.catalog)
    cat_hash = catalog_semantic_hash(catalog)

    model, entry = load_and_validate_checkpoint(
        model_id=args.model_id,
        catalog_hash=cat_hash,
        device=device,
    )

    run_agent_loop(model, entry, catalog, device)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
