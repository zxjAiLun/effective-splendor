"""Deterministic per-cycle PPO trainer for authoritative M39A batches."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn

from .data import catalog_semantic_hash, load_catalog
from .m39a_agent import categorical_index
from .m39a_contract import (
    BATCH_FORMAT,
    BATCH_VERSION,
    LR_WAYPOINTS,
    action_index,
    auxiliary_target,
    decision_seed,
    file_sha256,
    gae_for_trajectory,
    group_records_by_trajectory,
    load_plan,
    plan_hash,
    scheduled_game,
    shuffled_indices,
    standardize_advantages,
)
from .m39a_model import (
    checkpoint_metadata,
    encode_decisions,
    load_m39a_checkpoint,
    move_encoded,
)
from .train import checkpoint_semantic_hash


REPORT_FORMAT = "effective-splendor-m39a-training-report"
REPORT_VERSION = 1


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_torch(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        torch.save(payload, temporary)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def validate_authoritative_batch(
    batch: dict[str, Any],
    *,
    expected_plan_hash: str,
    expected_checkpoint_sha256: str,
    expected_checkpoint_hash: str,
    cycle: int,
) -> list[dict[str, Any]]:
    if batch.get("format") != BATCH_FORMAT or batch.get("version") != BATCH_VERSION:
        raise ValueError("unsupported M39A authoritative batch format/version")
    if batch.get("plan_hash") != expected_plan_hash:
        raise ValueError("authoritative batch plan hash mismatch")
    if batch.get("checkpoint_sha256") != expected_checkpoint_sha256:
        raise ValueError("authoritative batch checkpoint file SHA mismatch")
    if batch.get("checkpoint_hash") != expected_checkpoint_hash:
        raise ValueError("authoritative batch checkpoint semantic hash mismatch")
    if int(batch.get("cycle", 0)) != cycle:
        raise ValueError("authoritative batch cycle mismatch")
    if int(batch.get("checkpoint_cycle", -1)) != cycle - 1:
        raise ValueError("authoritative batch checkpoint_cycle mismatch")
    if int(batch.get("ply_cap", 0)) != 150:
        raise ValueError("authoritative batch ply_cap mismatch")
    mode = batch.get("mode")
    if mode not in {"smoke", "complete_cycle"}:
        raise ValueError("authoritative batch mode is invalid")
    games = batch.get("games")
    if not isinstance(games, list) or not games:
        raise ValueError("authoritative batch games must be non-empty")
    game_bindings: dict[int, dict[str, Any]] = {}
    for game_binding in games:
        game_index = int(game_binding.get("game_index", -1))
        if game_index in game_bindings:
            raise ValueError("duplicate authoritative game binding")
        if scheduled_game(game_index).cycle != cycle:
            raise ValueError("authoritative game binding is outside cycle")
        if int(game_binding.get("training_plies", -1)) != min(
            int(game_binding.get("completed_plies", -1)), 150
        ):
            raise ValueError("authoritative game training ply count is invalid")
        game_bindings[game_index] = game_binding
    if mode == "complete_cycle":
        expected = set(range((cycle - 1) * 512, cycle * 512))
        if set(game_bindings) != expected:
            raise ValueError("complete_cycle batch does not bind exactly 512 scheduled games")
    records = batch.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("authoritative batch records must be non-empty")

    identities: set[tuple[int, int, int]] = set()
    trajectory_results: dict[tuple[int, int], bytes] = {}
    for record in records:
        for key in (
            "game_index",
            "game_id",
            "seat",
            "ply_index",
            "request_id",
            "observation_hash",
            "observation",
            "legal_actions",
            "action",
            "decision_seed",
            "old_log_probability",
            "old_value",
            "result",
            "arena_report_hash",
            "replay_document_hash",
        ):
            if key not in record:
                raise ValueError(f"authoritative record missing {key}")
        game_index = int(record["game_index"])
        seat = int(record["seat"])
        ply = int(record["ply_index"])
        identity = (game_index, seat, ply)
        if identity in identities:
            raise ValueError(f"duplicate authoritative record {identity}")
        identities.add(identity)
        game = scheduled_game(game_index)
        if game.cycle != cycle or seat not in game.learner_seats:
            raise ValueError("record is outside the cycle's frozen learner schedule")
        binding = game_bindings.get(game_index)
        if binding is None or record["game_id"] != binding.get("game_id"):
            raise ValueError("record is not bound to an authoritative game")
        if (
            record["arena_report_hash"] != binding.get("arena_report_hash")
            or record["replay_document_hash"] != binding.get("replay_document_hash")
        ):
            raise ValueError("record artifact hashes differ from game binding")
        if not 0 <= ply < int(binding["training_plies"]):
            raise ValueError("record ply is outside authoritative training prefix")
        request_id = int(record["request_id"])
        if request_id != ply + 1:
            raise ValueError("record request_id must equal ply_index + 1")
        if int(record["decision_seed"]) != decision_seed(game_index, seat, request_id):
            raise ValueError("record decision seed mismatch")
        legal_actions = record["legal_actions"]
        if not isinstance(legal_actions, list) or not legal_actions:
            raise ValueError("record legal_actions must be a non-empty ordered list")
        action_index(legal_actions, record["action"])
        if not math.isfinite(float(record["old_log_probability"])):
            raise ValueError("record old_log_probability is non-finite")
        if not math.isfinite(float(record["old_value"])):
            raise ValueError("record old_value is non-finite")
        old_value_by_player = record.get("old_value_by_player")
        if (
            not isinstance(old_value_by_player, list)
            or len(old_value_by_player) != 2
            or any(not math.isfinite(float(value)) for value in old_value_by_player)
            or not math.isfinite(float(record.get("old_auxiliary_score", math.nan)))
        ):
            raise ValueError("record vector value/auxiliary output is malformed")
        result = record["result"]
        if not isinstance(result, dict) or len(result.get("scores", [])) != 2:
            raise ValueError("record result is not a 1v1 result")
        result_bytes = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        trajectory_key = (game_index, seat)
        previous = trajectory_results.setdefault(trajectory_key, result_bytes)
        if previous != result_bytes:
            raise ValueError("records in one trajectory disagree on final result")
    return records


@torch.no_grad()
def recompute_behaviour(
    model: nn.Module,
    records: Sequence[dict[str, Any]],
    catalog: dict[str, Any],
    device: torch.device,
    *,
    log_probability_threshold: float,
    value_threshold: float,
) -> tuple[list[float], list[float], dict[str, Any]]:
    model.eval()
    recomputed_log_probabilities = []
    recomputed_values = []
    max_log_probability_deviation = 0.0
    max_value_deviation = 0.0
    bit_exact = 0
    benign_drift = 0
    for record in records:
        encoded = move_encoded(
            encode_decisions([record["observation"]], [record["legal_actions"]], catalog),
            device,
        )
        logits, values, auxiliary = model.forward_packed(**encoded)
        if not torch.isfinite(logits).all() or not torch.isfinite(values).all() or not torch.isfinite(auxiliary).all():
            raise ValueError("checkpoint recomputation produced non-finite output")
        expected_index = action_index(record["legal_actions"], record["action"])
        sampled_index, log_probability = categorical_index(logits, int(record["decision_seed"]))
        if sampled_index != expected_index:
            raise ValueError("checkpoint categorical draw does not reproduce recorded action")
        value = float(values[0, 0].item())
        log_deviation = abs(log_probability - float(record["old_log_probability"]))
        value_deviation = abs(value - float(record["old_value"]))
        max_log_probability_deviation = max(max_log_probability_deviation, log_deviation)
        max_value_deviation = max(max_value_deviation, value_deviation)
        if log_deviation == 0.0 and value_deviation == 0.0:
            bit_exact += 1
        elif log_deviation <= log_probability_threshold and value_deviation <= value_threshold:
            benign_drift += 1
        else:
            raise ValueError(
                "behaviour recomputation exceeds frozen drift thresholds: "
                f"logp={log_deviation}, value={value_deviation}"
            )
        recomputed_log_probabilities.append(log_probability)
        recomputed_values.append(value)
    return (
        recomputed_log_probabilities,
        recomputed_values,
        {
            "bit_exact": bit_exact,
            "benign_runtime_drift": benign_drift,
            "max_log_probability_deviation": max_log_probability_deviation,
            "max_value_deviation": max_value_deviation,
        },
    )


def build_advantages(
    records: Sequence[dict[str, Any]],
    old_values: Sequence[float],
    *,
    gamma: float,
    gae_lambda: float,
    epsilon: float,
) -> list[float]:
    if len(records) != len(old_values):
        raise ValueError("records and old_values length mismatch")
    record_index = {id(record): index for index, record in enumerate(records)}
    raw = [0.0] * len(records)
    for (_, seat), trajectory in group_records_by_trajectory(records).items():
        indices = [record_index[id(record)] for record in trajectory]
        result = trajectory[-1]["result"]
        returns = result.get("centered_returns")
        if not isinstance(returns, list) or len(returns) != 2:
            raise ValueError("authoritative result must include centered_returns")
        values = [float(old_values[index]) for index in indices]
        trajectory_advantages = gae_for_trajectory(
            values,
            float(returns[seat]),
            gamma=gamma,
            gae_lambda=gae_lambda,
        )
        for index, advantage in zip(indices, trajectory_advantages):
            raw[index] = advantage
    return standardize_advantages(raw, epsilon=epsilon)


def _packed_policy_terms(
    logits: torch.Tensor,
    offsets: torch.Tensor,
    chosen_indices: Sequence[int],
) -> tuple[torch.Tensor, torch.Tensor]:
    selected = []
    entropies = []
    boundaries = offsets.detach().cpu().tolist()
    for batch_index, chosen in enumerate(chosen_indices):
        start, end = boundaries[batch_index], boundaries[batch_index + 1]
        log_probs = torch.log_softmax(logits[start:end], dim=0)
        probabilities = log_probs.exp()
        selected.append(log_probs[int(chosen)])
        entropies.append(-(probabilities * log_probs).sum())
    return torch.stack(selected), torch.stack(entropies)


def train_cycle(
    *,
    plan: dict[str, Any],
    plan_digest: str,
    batch: dict[str, Any],
    checkpoint_path: Path,
    checkpoint_sha256: str,
    catalog: dict[str, Any],
    catalog_hash: str,
    cycle: int,
    device: torch.device,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model, parent_payload = load_m39a_checkpoint(
        checkpoint_path,
        expected_file_sha256=checkpoint_sha256,
        expected_plan_hash=plan_digest,
        device=device,
    )
    if int(parent_payload["metadata"]["cycle"]) != cycle - 1:
        raise ValueError("parent checkpoint cycle does not precede requested cycle")
    records = validate_authoritative_batch(
        batch,
        expected_plan_hash=plan_digest,
        expected_checkpoint_sha256=checkpoint_sha256,
        expected_checkpoint_hash=parent_payload["checkpoint_hash"],
        cycle=cycle,
    )
    trainer = plan["trainer"]
    old_log_probabilities, old_values, recomputation = recompute_behaviour(
        model,
        records,
        catalog,
        device,
        log_probability_threshold=float(plan["join"]["log_probability_drift_threshold"]),
        value_threshold=float(plan["join"]["value_drift_threshold"]),
    )
    advantages = build_advantages(
        records,
        old_values,
        gamma=float(trainer["gamma"]),
        gae_lambda=float(trainer["gae_lambda"]),
        epsilon=float(trainer["advantage_epsilon"]),
    )

    learning_rate = float(LR_WAYPOINTS[cycle - 1])
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        betas=tuple(float(v) for v in trainer["adamw_betas"]),
        eps=float(trainer["adamw_eps"]),
        weight_decay=float(trainer["weight_decay"]),
        amsgrad=bool(trainer["adamw_amsgrad"]),
        maximize=bool(trainer["adamw_maximize"]),
        foreach=bool(trainer["adamw_foreach"]),
        fused=bool(trainer["adamw_fused"]),
        capturable=bool(trainer["adamw_capturable"]),
        differentiable=bool(trainer["adamw_differentiable"]),
    )
    if parent_payload.get("optimizer_state_dict") is not None:
        optimizer.load_state_dict(parent_payload["optimizer_state_dict"])
        for group in optimizer.param_groups:
            group["lr"] = learning_rate

    model.train()
    history = []
    minibatch_size = int(trainer["minibatch_size"])
    started = time.perf_counter()
    for epoch in range(1, int(trainer["epochs_per_cycle"]) + 1):
        order = shuffled_indices(len(records), cycle, epoch)
        epoch_totals = {"loss": 0.0, "policy": 0.0, "entropy": 0.0, "value": 0.0, "aux": 0.0}
        seen = 0
        for start in range(0, len(order), minibatch_size):
            indices = order[start : start + minibatch_size]
            selected_records = [records[index] for index in indices]
            encoded = move_encoded(
                encode_decisions(
                    [record["observation"] for record in selected_records],
                    [record["legal_actions"] for record in selected_records],
                    catalog,
                ),
                device,
            )
            logits, values, auxiliary = model.forward_packed(**encoded)
            chosen = [
                action_index(record["legal_actions"], record["action"])
                for record in selected_records
            ]
            current_log_probs, entropies = _packed_policy_terms(
                logits, encoded["action_offsets"], chosen
            )
            old_logp = torch.tensor(
                [old_log_probabilities[index] for index in indices],
                dtype=torch.float32,
                device=device,
            )
            advantage = torch.tensor(
                [advantages[index] for index in indices],
                dtype=torch.float32,
                device=device,
            )
            ratios = torch.exp(current_log_probs - old_logp)
            clipped = torch.clamp(
                ratios,
                1.0 - float(trainer["ppo_clip"]),
                1.0 + float(trainer["ppo_clip"]),
            )
            policy_loss = -torch.minimum(ratios * advantage, clipped * advantage).mean()
            entropy_term_negated = -entropies.mean()

            value_targets = []
            auxiliary_targets = []
            for record in selected_records:
                seat = int(record["seat"])
                returns = record["result"]["centered_returns"]
                value_targets.append([float(returns[seat]), float(returns[1 - seat])])
                auxiliary_targets.append(auxiliary_target(record["result"]["scores"], seat))
            value_target = torch.tensor(value_targets, dtype=torch.float32, device=device)
            auxiliary_target_tensor = torch.tensor(
                auxiliary_targets, dtype=torch.float32, device=device
            )
            value_loss = (0.5 * (values - value_target).pow(2).sum(dim=1)).mean()
            auxiliary_loss = (auxiliary - auxiliary_target_tensor).pow(2).mean()
            loss = (
                policy_loss
                + float(trainer["entropy_coefficient"]) * entropy_term_negated
                + float(trainer["value_coefficient"]) * value_loss
                + float(trainer["aux_coefficient"]) * auxiliary_loss
            )
            if not torch.isfinite(loss):
                raise ValueError("M39A training loss became non-finite")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(
                model.parameters(), float(trainer["gradient_clip_norm"])
            )
            optimizer.step()

            count = len(indices)
            seen += count
            for key, value in (
                ("loss", loss),
                ("policy", policy_loss),
                ("entropy", entropies.mean()),
                ("value", value_loss),
                ("aux", auxiliary_loss),
            ):
                epoch_totals[key] += float(value.detach().item()) * count
        history.append(
            {
                "epoch": epoch,
                "examples": seen,
                **{key: value / seen for key, value in epoch_totals.items()},
            }
        )

    state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    metadata = checkpoint_metadata(
        plan_hash=plan_digest,
        cycle=cycle,
        base_checkpoint_sha256=parent_payload["metadata"]["base_checkpoint_sha256"],
        catalog_hash=catalog_hash,
        parent_checkpoint_hash=parent_payload["checkpoint_hash"],
    )
    checkpoint_hash = checkpoint_semantic_hash(metadata, state)
    output_payload = {
        "metadata": metadata,
        "state_dict": state,
        "checkpoint_hash": checkpoint_hash,
        "optimizer_state_dict": optimizer.state_dict(),
    }
    report = {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "cycle": cycle,
        "plan_hash": plan_digest,
        "parent_checkpoint_sha256": checkpoint_sha256,
        "parent_checkpoint_hash": parent_payload["checkpoint_hash"],
        "checkpoint_hash": checkpoint_hash,
        "catalog_hash": catalog_hash,
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "records": len(records),
        "recomputation": recomputation,
        "learning_rate": learning_rate,
        "elapsed_seconds": time.perf_counter() - started,
        "history": history,
    }
    return output_payload, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train one frozen M39A PPO cycle")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--cycle", type=int, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--checkpoint-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    args = parser.parse_args()
    if args.checkpoint_out == args.report_out:
        raise ValueError("checkpoint and report outputs must differ")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    plan = load_plan(args.plan)
    digest = plan_hash(plan)
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    catalog = load_catalog(args.catalog)
    cat_hash = catalog_semantic_hash(catalog)
    if plan["catalog"]["semantic_hash"] != cat_hash:
        raise ValueError("plan catalog hash does not match supplied catalog")
    payload, report = train_cycle(
        plan=plan,
        plan_digest=digest,
        batch=batch,
        checkpoint_path=args.checkpoint,
        checkpoint_sha256=args.checkpoint_sha256,
        catalog=catalog,
        catalog_hash=cat_hash,
        cycle=args.cycle,
        device=torch.device(args.device),
    )
    _atomic_torch(args.checkpoint_out, payload)
    report["checkpoint_file_sha256"] = file_sha256(args.checkpoint_out)
    _atomic_text(
        args.report_out,
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "cycle": args.cycle,
                "checkpoint": str(args.checkpoint_out),
                "checkpoint_hash": payload["checkpoint_hash"],
                "checkpoint_file_sha256": report["checkpoint_file_sha256"],
                "report": str(args.report_out),
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
