"""Arena v0.5 M39A stochastic direct-policy agent with trajectory sidecar."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import torch

from .data import catalog_semantic_hash, load_catalog
from .m39a_contract import (
    SIDECAR_FORMAT,
    SIDECAR_VERSION,
    decision_seed,
    validate_sidecar,
)
from .m39a_model import infer_decision, load_m39a_checkpoint


PROTOCOL_VERSION = "0.5"


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def categorical_index(logits: torch.Tensor, seed: int) -> tuple[int, float]:
    if logits.ndim != 1 or logits.numel() == 0:
        raise ValueError("categorical logits must be a non-empty vector")
    log_probs = torch.log_softmax(logits.to(dtype=torch.float32), dim=0)
    if not torch.isfinite(log_probs).all():
        raise ValueError("categorical log-probabilities are non-finite")
    probabilities = log_probs.exp().cpu().tolist()
    unit = (int(seed) >> 11) * (2.0 ** -53)
    cumulative = 0.0
    chosen = len(probabilities) - 1
    for index, probability in enumerate(probabilities):
        cumulative += float(probability)
        if unit < cumulative:
            chosen = index
            break
    return chosen, float(log_probs[chosen].item())


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


def run_agent_loop(
    *,
    model: torch.nn.Module,
    checkpoint_payload: dict[str, Any],
    checkpoint_sha256: str,
    plan_hash: str,
    game_index: int,
    sidecar_out: Path,
    catalog: dict[str, Any],
    catalog_hash: str,
    device: torch.device,
    action_selection: str = "categorical",
    input_lines: Sequence[str] | None = None,
) -> dict[str, Any]:
    game_id: str | None = None
    seat: int | None = None
    latest_observation: dict[str, Any] | None = None
    latest_hash: str | None = None
    last_request = 0
    records: list[dict[str, Any]] = []
    final_result: dict[str, Any] | None = None
    lines = input_lines if input_lines is not None else sys.stdin

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
                    "agent_name": "effective-splendor-m39a-policy-value-agent-v1",
                    "agent_version": str(checkpoint_payload["checkpoint_hash"]),
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
            logits, values, auxiliary = infer_decision(
                model,
                latest_observation,
                legal_actions,
                catalog,
                device,
            )
            seed = decision_seed(game_index, seat, request_id)
            if action_selection == "categorical":
                chosen_index, old_log_probability = categorical_index(logits, seed)
            elif action_selection == "argmax":
                chosen_index = int(logits.argmax().item())
                old_log_probability = float(
                    torch.log_softmax(logits.to(dtype=torch.float32), dim=0)[
                        chosen_index
                    ].item()
                )
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
                    "old_value": float(values[0].item()),
                    "old_value_by_player": [float(value) for value in values.cpu().tolist()],
                    "old_auxiliary_score": float(auxiliary.item()),
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
        elif kind == "error":
            raise ValueError(f"server error: {message.get('message')}")
        else:
            raise ValueError(f"unsupported server message type: {kind!r}")

    if game_id is None or seat is None or final_result is None:
        raise ValueError("agent stream ended before a completed game_end")
    sidecar = {
        "format": SIDECAR_FORMAT,
        "version": SIDECAR_VERSION,
        "plan_hash": plan_hash,
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_hash": checkpoint_payload["checkpoint_hash"],
        "checkpoint_cycle": checkpoint_payload["metadata"]["cycle"],
        "catalog_hash": catalog_hash,
        "game_id": game_id,
        "game_index": game_index,
        "seat": seat,
        "records": records,
        "result": final_result,
    }
    validate_sidecar(sidecar)
    _atomic_json(sidecar_out, sidecar)
    return sidecar


def main() -> None:
    parser = argparse.ArgumentParser(description="M39A Arena policy/value agent")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--game-index", type=int, required=True)
    parser.add_argument("--sidecar-out", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument(
        "--action-selection", choices=["categorical", "argmax"], default="categorical"
    )
    args = parser.parse_args()

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
    run_agent_loop(
        model=model,
        checkpoint_payload=checkpoint_payload,
        checkpoint_sha256=args.checkpoint_sha256,
        plan_hash=args.plan_hash,
        game_index=args.game_index,
        sidecar_out=args.sidecar_out,
        catalog=catalog,
        catalog_hash=cat_hash,
        device=device,
        action_selection=args.action_selection,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
