"""M40A B-arm offline predictive pretraining — the frozen executor.

Trains ONLY the prediction heads (trunk + policy frozen), for exactly 16
epochs, on the frozen split, with the frozen optimizer/shuffle/clip
constants. Emits the report-only sanity metrics (multiclass Outcome
Brier + V MSE/RMSE split by completed/truncated).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import torch
from torch import nn

from .m39a_contract import file_sha256
from .m40a_dataset import _labels_for_batch
from .m40a_constants import (
    AUX_FAMILY_COEFFICIENT,
    DESIGN_SHA,
    PRETRAIN_BATCH,
    PRETRAIN_EPOCHS,
    PRETRAIN_GRAD_CLIP,
    PRETRAIN_LR,
    PRETRAIN_SHUFFLE_SEED,
    PRETRAIN_WEIGHT_DECAY,
    TIMING_HORIZONS,
    VP_BINS,
)
from .m40a_model import M40AModel, outcome_value


def _splitmix64_permutation(length: int, key: int) -> list[int]:
    """Deterministic index permutation keyed on (namespace, epoch).

    Same construction family as the M39A trainer's deterministic total
    order: sort indices by the SPLITMIX64 digest of (key, index).
    """
    import struct

    def splitmix64(z: int) -> int:
        z = (z + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z ^= z >> 30
        z = (z * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z ^= z >> 27
        z = (z * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        z ^= z >> 31
        return z

    keyed = sorted(
        range(length),
        key=lambda index: splitmix64((key << 32) ^ index) ^ (index << 1),
    )
    return keyed


def _forward_heads(
    model: M40AModel,
    records: list[dict[str, Any]],
    device: torch.device,
) -> dict[str, torch.Tensor]:
    """Encode the batch observations and run the head block."""
    from .m39a_model import encode_decisions, move_encoded

    observations = [record["observation"] for record in records]
    legal_sets = [record["legal_actions"] for record in records]
    encoded = move_encoded(encode_decisions(observations, legal_sets, _catalog()), device)
    state = model.state_embedding(
        encoded["entities"], encoded["mask"], encoded["global_features"]
    )
    return model.heads(state)


_CATALOG_CACHE: dict[str, Any] | None = None


def _catalog() -> dict[str, Any]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        from .data import load_catalog

        _CATALOG_CACHE = load_catalog(
            Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
        )
    return _CATALOG_CACHE


def pretrain(
    *,
    model: M40AModel,
    records: list[dict[str, Any]],
    device: torch.device,
    report_path: Path,
) -> dict[str, Any]:
    """Run the frozen 16-epoch head-only pretraining on `records`
    (the TRAIN split). Writes the report-only sanity metrics."""
    labels_all = _labels_for_batch(records)

    # Frozen optimizer over the head parameters ONLY.
    trainable = list(model.heads.parameters())
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    for parameter in trainable:
        parameter.requires_grad_(True)

    optimizer = torch.optim.AdamW(
        trainable,
        lr=PRETRAIN_LR,
        betas=(0.9, 0.999),
        eps=1e-8,
        weight_decay=PRETRAIN_WEIGHT_DECAY,
        amsgrad=False,
        foreach=False,
        fused=False,
        maximize=False,
        capturable=False,
        differentiable=False,
    )

    started = time.perf_counter()
    history: list[dict[str, float]] = []
    count = len(records)
    for epoch in range(1, PRETRAIN_EPOCHS + 1):
        order = _splitmix64_permutation(count, (PRETRAIN_SHUFFLE_SEED << 8) ^ epoch)
        totals = {
            "loss": 0.0,
            "outcome_ce": 0.0,
            "vp_dist_ce": 0.0,
            "vp_diff_mse": 0.0,
            "timing_bce": 0.0,
            "value_mse": 0.0,
        }
        batches = 0
        for start in range(0, count, PRETRAIN_BATCH):
            indices = order[start : start + PRETRAIN_BATCH]
            batch_records = [records[i] for i in indices]
            batch_labels = {
                family: [labels_all[family][i] for i in indices]
                for family in labels_all
            }
            outputs = _forward_heads(model, batch_records, device)

            # --- Outcome CE (completed only), family mean. ---
            outcome_indices = [
                i for i, label in enumerate(batch_labels["outcome"]) if label is not None
            ]
            outcome_ce = torch.zeros((), device=device)
            if outcome_indices:
                logits = outputs["outcome"][outcome_indices]
                targets = torch.tensor(
                    [batch_labels["outcome"][i] for i in outcome_indices],
                    dtype=torch.long,
                    device=device,
                )
                outcome_ce = nn.functional.cross_entropy(
                    logits.to(dtype=torch.float32), targets
                )

            # --- VP distribution CE (completed only), both heads, mean. ---
            vp_indices = [
                i for i, label in enumerate(batch_labels["vp_self"]) if label is not None
            ]
            vp_ce = torch.zeros((), device=device)
            if vp_indices:
                self_logits = outputs["final_vp_self"][vp_indices].to(dtype=torch.float32)
                opp_logits = outputs["final_vp_opp"][vp_indices].to(dtype=torch.float32)
                self_targets = torch.tensor(
                    [batch_labels["vp_self"][i] for i in vp_indices],
                    dtype=torch.long,
                    device=device,
                )
                opp_targets = torch.tensor(
                    [batch_labels["vp_opp"][i] for i in vp_indices],
                    dtype=torch.long,
                    device=device,
                )
                vp_ce = 0.5 * (
                    nn.functional.cross_entropy(self_logits, self_targets)
                    + nn.functional.cross_entropy(opp_logits, opp_targets)
                )

            # --- VP difference MSE (completed only), mean. ---
            diff_indices = [
                i for i, label in enumerate(batch_labels["vp_diff"]) if label is not None
            ]
            diff_mse = torch.zeros((), device=device)
            if diff_indices:
                predictions = outputs["vp_difference"][diff_indices].to(dtype=torch.float32)
                targets = torch.tensor(
                    [batch_labels["vp_diff"][i] for i in diff_indices],
                    dtype=torch.float32,
                    device=device,
                )
                diff_mse = nn.functional.mse_loss(predictions, targets)

            # --- Timing BCE (completed only), all 6 outputs, mean. ---
            timing_indices = [
                i for i, label in enumerate(batch_labels["timing"]) if label is not None
            ]
            timing_bce = torch.zeros((), device=device)
            if timing_indices:
                logits = outputs["timing"][timing_indices].to(dtype=torch.float32)
                targets = torch.tensor(
                    [batch_labels["timing"][i] for i in timing_indices],
                    dtype=torch.float32,
                    device=device,
                )
                timing_bce = nn.functional.binary_cross_entropy_with_logits(
                    logits, targets
                )

            # --- Value MSE (all records: completed centered return,
            #     truncated cap-return), mean. ---
            value_predictions = outcome_value(outputs["outcome"]).to(dtype=torch.float32)
            value_targets = torch.tensor(
                batch_labels["value"], dtype=torch.float32, device=device
            )
            value_mse = nn.functional.mse_loss(value_predictions, value_targets)

            loss = (
                outcome_ce
                + vp_ce
                + diff_mse
                + timing_bce
                + value_mse
            )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(trainable, PRETRAIN_GRAD_CLIP)
            optimizer.step()

            totals["loss"] += float(loss.item())
            totals["outcome_ce"] += float(outcome_ce.item())
            totals["vp_dist_ce"] += float(vp_ce.item())
            totals["vp_diff_mse"] += float(diff_mse.item())
            totals["timing_bce"] += float(timing_bce.item())
            totals["value_mse"] += float(value_mse.item())
            batches += 1

        history.append({key: value / batches for key, value in totals.items()})

    # Sanity metrics on the validation split (report-only).
    report = {
        "format": "effective-splendor-m40a-pretrain-report",
        "version": 1,
        "design_sha": DESIGN_SHA,
        "epochs": PRETRAIN_EPOCHS,
        "records": count,
        "elapsed_seconds": time.perf_counter() - started,
        "history": history,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def sanity_metrics(
    *,
    model: M40AModel,
    validation_records: list[dict[str, Any]],
    device: torch.device,
) -> dict[str, Any]:
    """Report-only held-out metrics: multiclass Outcome Brier (headline)
    + V MSE/RMSE split by completed/truncated."""
    model.eval()
    with torch.no_grad():
        outputs = _forward_heads(model, validation_records, device)
        labels = _labels_for_batch(validation_records)
        completed = [
            i for i, label in enumerate(labels["outcome"]) if label is not None
        ]
        truncated = [
            i for i, label in enumerate(labels["outcome"]) if label is None
        ]

        brier = None
        if completed:
            logits = outputs["outcome"][completed].to(dtype=torch.float32)
            probabilities = torch.softmax(logits, dim=-1)
            targets = torch.zeros_like(probabilities)
            for row, index in enumerate(completed):
                targets[row, labels["outcome"][index]] = 1.0
            brier = float(
                ((probabilities - targets) ** 2).sum(dim=-1).mean().item()
            )

        values = outcome_value(outputs["outcome"]).to(dtype=torch.float32)

        def _mse_rmse(indices: list[int]) -> tuple[float | None, float | None]:
            if not indices:
                return None, None
            predictions = values[indices]
            targets = torch.tensor(
                [labels["value"][i] for i in indices],
                dtype=torch.float32,
                device=device,
            )
            mse = float(nn.functional.mse_loss(predictions, targets).item())
            return mse, math.sqrt(mse)

        completed_mse, completed_rmse = _mse_rmse(completed)
        # The truncated column is N/A with 0 validation games per the
        # frozen truncation rule — never computed from training data.
        truncated_mse = "N/A (0 validation games)" if not truncated else None
        truncated_rmse = "N/A (0 validation games)" if not truncated else None
        if truncated:
            truncated_mse, truncated_rmse = _mse_rmse(truncated)

    return {
        "validation_records": len(validation_records),
        "validation_completed_games_records": len(completed),
        "validation_truncated_games_records": len(truncated),
        "outcome_brier_multiclass": brier,
        "value_mse_completed": completed_mse,
        "value_rmse_completed": completed_rmse,
        "value_mse_truncated": truncated_mse,
        "value_rmse_truncated": truncated_rmse,
        "validation_truncated_games": 1 if truncated else 0,
    }
