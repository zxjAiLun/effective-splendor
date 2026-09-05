"""M43A: Successor Value Model Trainer.

Trains M43ASuccessorValueModel to evaluate post-action player-view successor states V(o')
using terminal win/loss targets y in {0, 1} with hierarchical MSE loss.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import torch
import torch.nn as nn

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m41a_helpers import _splitmix64_mix, EPOCH_KEY_MIX, ORDINAL_KEY_MIX
from splendor_gpu.m43a_successor_dataset import load_successor_split
from splendor_gpu.m43a_successor_model import (
    M43ASuccessorValueModel,
    VALUE_HEAD_INIT_SEED,
    build_m43a_model,
)

CATALOG_PATH = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
RUN_ROOT = REPO / "local-artifacts/m43a-run"

# Frozen contract parameters
TRAINER_SEED = 43_261_002
EPOCHS = 32
BATCH_GAMES = 32
LR = 1e-4
WEIGHT_DECAY = 1e-4
BETAS = (0.9, 0.999)
EPS = 1e-8
GRAD_CLIP = 1.0
BSS_THRESHOLD = 0.05


def m43a_epoch_game_order(num_games: int, epoch: int) -> list[int]:
    """SplitMix64 deterministic game shuffle for M43A using TRAINER_SEED = 43_261_002."""
    def key_fn(g: int) -> int:
        mixed = (
            TRAINER_SEED
            ^ ((epoch * EPOCH_KEY_MIX) & 0xFFFFFFFFFFFFFFFF)
            ^ ((g * ORDINAL_KEY_MIX) & 0xFFFFFFFFFFFFFFFF)
        )
        return _splitmix64_mix(mixed & 0xFFFFFFFFFFFFFFFF)

    return sorted(range(num_games), key=lambda g: (key_fn(g), g))


def pack_successor_batch(batch_games: list[dict[str, Any]], device: torch.device):
    """Pack batch of games into successor observation tensors and hierarchical boundaries."""
    entities_list = []
    masks_list = []
    globals_list = []
    targets_list = []
    offsets = [0]
    game_boundaries = []

    for game in batch_games:
        state_start = len(offsets) - 1
        for state in game["states"]:
            entities_list.append(state["entities"])
            masks_list.append(state["mask"])
            globals_list.append(state["global_features"])
            targets_list.append(state["targets"])
            offsets.append(offsets[-1] + state["entities"].shape[0])
        state_end = len(offsets) - 1
        game_boundaries.append((state_start, state_end))

    entities = torch.cat(entities_list, dim=0).to(device)
    mask = torch.cat(masks_list, dim=0).to(device)
    global_features = torch.cat(globals_list, dim=0).to(device)
    targets = torch.cat(targets_list, dim=0).to(device)
    offsets_t = torch.tensor(offsets, dtype=torch.long, device=device)

    return entities, mask, global_features, targets, offsets_t, game_boundaries


def hierarchical_brier_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    offsets: torch.Tensor,
    game_boundaries: list[tuple[int, int]],
) -> torch.Tensor:
    """Hierarchical Brier / MSE loss: branch -> state mean -> game mean -> batch mean."""
    boundaries = offsets.detach().cpu().tolist()
    game_losses = []
    for state_start, state_end in game_boundaries:
        state_losses = []
        for s in range(state_start, state_end):
            a0, a1 = boundaries[s], boundaries[s + 1]
            p_state = predictions[a0:a1]
            y_state = targets[a0:a1]
            # State MSE
            mse_state = torch.mean((p_state - y_state) ** 2)
            state_losses.append(mse_state)
        game_losses.append(torch.stack(state_losses).mean())
    return torch.stack(game_losses).mean()


def evaluate_split(
    model: M43ASuccessorValueModel | None,
    constant_val: float | None,
    games: list[dict[str, Any]],
    device: torch.device,
) -> tuple[float, list[float], list[float]]:
    """Evaluate hierarchical Brier loss and extract predictions on a split."""
    total_preds = []
    total_targets = []
    batch_losses = []

    with torch.no_grad():
        for b_idx in range(0, len(games), BATCH_GAMES):
            batch = games[b_idx : b_idx + BATCH_GAMES]
            entities, mask, global_features, targets, offsets, boundaries = pack_successor_batch(
                batch, device
            )
            if model is not None:
                preds = model(entities, mask, global_features)
            else:
                preds = torch.full_like(targets, constant_val)

            loss = hierarchical_brier_loss(preds, targets, offsets, boundaries)
            batch_losses.append(loss.item())
            total_preds.extend(preds.detach().cpu().tolist())
            total_targets.extend(targets.detach().cpu().tolist())

    mean_loss = sum(batch_losses) / len(batch_losses)
    return mean_loss, total_preds, total_targets


def compute_p1_diagnostics(
    preds: list[float],
    targets: list[float],
    val_brier: float,
    const_brier: float,
) -> dict[str, Any]:
    bss = 1.0 - (val_brier / const_brier) if const_brier > 0 else 0.0
    arr_p = np.array(preds)
    arr_y = np.array(targets)

    pos_mask = arr_y == 1.0
    neg_mask = arr_y == 0.0

    mean_pos = float(np.mean(arr_p[pos_mask])) if np.any(pos_mask) else 0.0
    mean_neg = float(np.mean(arr_p[neg_mask])) if np.any(neg_mask) else 0.0

    # Diagnostic ROC-AUC via rank sum / Mann-Whitney
    auc = None
    if np.any(pos_mask) and np.any(neg_mask):
        n_pos = np.sum(pos_mask)
        n_neg = np.sum(neg_mask)
        ranks = np.argsort(np.argsort(arr_p))
        sum_pos_ranks = np.sum(ranks[pos_mask])
        u_val = sum_pos_ranks - n_pos * (n_pos - 1) / 2.0
        auc = float(u_val / (n_pos * n_neg))

    return {
        "validation_brier": val_brier,
        "constant_brier": const_brier,
        "brier_skill_score": bss,
        "bss_pass": bss >= BSS_THRESHOLD,
        "prediction_mean": float(np.mean(arr_p)),
        "prediction_std": float(np.std(arr_p)),
        "prediction_p05": float(np.percentile(arr_p, 5)),
        "prediction_p50": float(np.percentile(arr_p, 50)),
        "prediction_p95": float(np.percentile(arr_p, 95)),
        "positive_target_mean_prediction": mean_pos,
        "negative_target_mean_prediction": mean_neg,
        "roc_auc_diagnostic": auc,
    }


def train_m43a(device: torch.device) -> dict[str, Any]:
    print(f"M43A Training Pipeline initialized on {device}.", flush=True)
    catalog = load_catalog(CATALOG_PATH)

    # 1. Load data
    train_games = load_successor_split("train", catalog)
    val_games = load_successor_split("validation", catalog)

    # 2. Compute constant baseline
    all_train_targets = []
    for g in train_games:
        for s in g["states"]:
            all_train_targets.extend(s["targets"].tolist())
    p_train = sum(all_train_targets) / len(all_train_targets)
    print(f"Train targets count: {len(all_train_targets)}, prevalence (p_train): {p_train:.4f}", flush=True)

    val_const_brier, _, val_targets = evaluate_split(None, p_train, val_games, device)
    print(f"Constant baseline validation Brier: {val_const_brier:.6f}", flush=True)

    # 3. Build model with D2 initialization audit
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    model, init_audit = build_m43a_model(d2_model)
    model = model.to(device)

    # Initial parameter snapshots for parameter delta tracking
    init_state_encoder = {
        k: v.detach().cpu().clone()
        for k, v in model.named_parameters()
        if not k.startswith("value_head.")
    }
    init_value_head = {
        k: v.detach().cpu().clone()
        for k, v in model.named_parameters()
        if k.startswith("value_head.")
    }

    # 4. Setup AdamW
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(
        trainable_params,
        lr=LR,
        betas=BETAS,
        eps=EPS,
        weight_decay=WEIGHT_DECAY,
        amsgrad=False,
        foreach=False,
        fused=False,
    )

    best_epoch = None
    best_val_brier = float("inf")
    best_checkpoint_state = None
    best_diagnostics = None
    history = []

    t_train_start = time.time()
    num_games = len(train_games)

    for epoch in range(1, EPOCHS + 1):
        model.train()
        t_ep_start = time.time()
        order = m43a_epoch_game_order(num_games, epoch)
        shuffled_games = [train_games[i] for i in order]

        batch_losses = []
        for b_idx in range(0, num_games, BATCH_GAMES):
            batch = shuffled_games[b_idx : b_idx + BATCH_GAMES]
            entities, mask, global_features, targets, offsets, boundaries = pack_successor_batch(
                batch, device
            )

            optimizer.zero_grad()
            preds = model(entities, mask, global_features)
            loss = hierarchical_brier_loss(preds, targets, offsets, boundaries)
            loss.backward()
            nn.utils.clip_grad_norm_(trainable_params, GRAD_CLIP)
            optimizer.step()
            batch_losses.append(loss.item())

        train_loss = sum(batch_losses) / len(batch_losses)

        # Validation evaluation
        model.eval()
        val_loss, val_preds, val_targets = evaluate_split(model, None, val_games, device)
        diag = compute_p1_diagnostics(val_preds, val_targets, val_loss, val_const_brier)

        is_best = val_loss < best_val_brier
        if is_best:
            best_val_brier = val_loss
            best_epoch = epoch
            best_checkpoint_state = copy.deepcopy(model.state_dict())
            best_diagnostics = diag

        history.append({
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "bss": diag["brier_skill_score"],
            "is_best": is_best,
            "elapsed_seconds": time.time() - t_ep_start,
        })

        print(
            f"Epoch {epoch:02d}/{EPOCHS} - Train MSE: {train_loss:.6f} - Val MSE: {val_loss:.6f} "
            f"- BSS: {diag['brier_skill_score']:+.4f} "
            f"{'* BEST *' if is_best else ''} ({time.time() - t_ep_start:.2f}s)",
            flush=True,
        )

    total_training_seconds = time.time() - t_train_start
    print(f"\nTraining complete in {total_training_seconds:.1f}s. Best epoch: {best_epoch} (Val MSE: {best_val_brier:.6f}).", flush=True)

    # Compute parameter deltas on best model
    model.load_state_dict(best_checkpoint_state)
    encoder_delta_sq = 0.0
    for k, v_init in init_state_encoder.items():
        v_final = model.state_dict()[k].detach().cpu()
        encoder_delta_sq += float(torch.sum((v_final - v_init) ** 2))
    encoder_l2_delta = float(encoder_delta_sq ** 0.5)

    vh_delta_sq = 0.0
    for k, v_init in init_value_head.items():
        v_final = model.state_dict()[k].detach().cpu()
        vh_delta_sq += float(torch.sum((v_final - v_init) ** 2))
    vh_l2_delta = float(vh_delta_sq ** 0.5)

    # Save best checkpoint
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    ckpt_path = RUN_ROOT / "m43a-successor-value-best.pt"
    ckpt_payload = {
        "milestone": "M43A",
        "best_epoch": best_epoch,
        "state_dict": model.state_dict(),
        "d2_checkpoint_file_sha256": hashlib.sha256(
            Path("local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt").read_bytes()
        ).hexdigest(),
        "value_head_init_seed": VALUE_HEAD_INIT_SEED,
        "trainer_seed": TRAINER_SEED,
        "p1_diagnostics": best_diagnostics,
        "encoder_l2_delta": encoder_l2_delta,
        "value_head_l2_delta": vh_l2_delta,
    }
    torch.save(ckpt_payload, ckpt_path)
    file_sha = hashlib.sha256(ckpt_path.read_bytes()).hexdigest()
    print(f"Saved best checkpoint to {ckpt_path} (SHA-256: {file_sha}).", flush=True)

    training_report = {
        "init_audit": init_audit,
        "best_epoch": best_epoch,
        "best_val_brier": best_val_brier,
        "best_diagnostics": best_diagnostics,
        "encoder_l2_delta": encoder_l2_delta,
        "value_head_l2_delta": vh_l2_delta,
        "checkpoint_file_sha256": file_sha,
        "checkpoint_path": str(ckpt_path),
        "history": history,
    }

    report_path = RUN_ROOT / "m43a-training-report.json"
    report_path.write_text(json.dumps(training_report, indent=2), encoding="utf-8")
    print(f"Training report written to {report_path}.", flush=True)

    # Check P1 Gate
    p1_pass = best_diagnostics["bss_pass"]
    print(f"\n=======================================================", flush=True)
    print(f"P1 VALUE-LEARNING GATE: {'PASS' if p1_pass else 'FAIL'}", flush=True)
    print(f"  Validation Brier: {best_diagnostics['validation_brier']:.6f}", flush=True)
    print(f"  Constant Brier:   {best_diagnostics['constant_brier']:.6f}", flush=True)
    print(f"  BSS:              {best_diagnostics['brier_skill_score']:+.4f} (gate >= +0.05)", flush=True)
    print(f"  ROC-AUC:          {best_diagnostics['roc_auc_diagnostic']:.4f}", flush=True)
    print(f"=======================================================", flush=True)

    return training_report


if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_m43a(device)
