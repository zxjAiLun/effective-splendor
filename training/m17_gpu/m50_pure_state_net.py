"""M50 Pure State-Distance & Value Network: ZERO Policy Imitation.

Completely eliminates the policy imitation head (no C(5,3) action encoding,
no cross-entropy imitation of heuristic choices). Instead, the network operates
strictly as a board-state physicist:

  Input: 368-dim board state (bank tokens, player tokens, permanent discounts,
         market cards, nobles, reserved cards).
  Output:
    1. pred_steps: Predicted remaining main turns to reach >= 15 VP.
    2. win_prob:   Predicted match win probability from this state.

Loss: Pure Smooth L1 on remaining steps to 15 + BCE on match outcome.
Decision: For each legal action a in A(s), simulate s' = state.apply(a).
          Pick a* = argmin_a pred_steps(s')!
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

REPO_ROOT = Path("E:/AUbuntuProject/project/splendor")
DATA_DIR = REPO_ROOT / "local-artifacts" / "m50-v029-dataset-v1"
RUN_DIR = REPO_ROOT / "local-artifacts" / "m50-pure-state-run"

OBS_DIM = 368
STEPS_NORM = 20.0


class PureStateDistanceNet(nn.Module):
    def __init__(self, obs_dim: int = OBS_DIM, hidden_dim: int = 256):
        super().__init__()
        self.hidden_dim = hidden_dim

        # State representation trunk (368 -> 512 -> 256)
        mid_dim = 512
        self.state_net = nn.Sequential(
            nn.Linear(obs_dim, mid_dim),
            nn.LayerNorm(mid_dim),
            nn.ReLU(),
            nn.Linear(mid_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )

        # Head 1: Steps-to-15 Head (Expected main turns to 15 VP)
        self.steps_head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
        )

        # Head 2: Value Head (Win probability logit)
        self.value_head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
        )

    def forward(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        obs: [B, 368]
        Returns:
          pred_steps: [B] (strictly non-negative predicted main turns to 15 VP)
          val_logits: [B] (win probability logits)
        """
        state_h = self.state_net(obs)
        pred_steps_norm = F.softplus(self.steps_head(state_h).squeeze(-1))
        pred_steps = pred_steps_norm * STEPS_NORM
        val_logits = self.value_head(state_h).squeeze(-1)
        return pred_steps, val_logits


class StateDataset:
    def __init__(self, split_dir: Path):
        self.obs = np.memmap(split_dir / "obs.f32", dtype="<f4", mode="r").reshape(-1, OBS_DIM)
        self.values = np.memmap(split_dir / "values.f32", dtype="<f4", mode="r").reshape(-1, 3)
        self.count = len(self.obs)

    def get_batch(self, indices: np.ndarray, device: torch.device) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        batch_obs = torch.from_numpy(np.array(self.obs[indices], copy=True)).to(device)
        batch_won = torch.from_numpy(np.array(self.values[indices, 0], copy=True)).to(device)
        batch_steps = torch.from_numpy(np.array(self.values[indices, 2], copy=True)).to(device)
        return batch_obs, batch_won, batch_steps


def evaluate(
    model: PureStateDistanceNet,
    dataset: StateDataset,
    device: torch.device,
    batch_size: int = 1024,
) -> dict[str, float]:
    model.eval()
    total = dataset.count
    indices = np.arange(total)

    total_steps_loss = 0.0
    total_steps_mae = 0.0
    total_val_loss = 0.0
    total_val_acc = 0.0

    with torch.no_grad():
        for i in range(0, total, batch_size):
            b_idx = indices[i : min(i + batch_size, total)]
            obs, won, steps_15 = dataset.get_batch(b_idx, device)

            pred_steps, val_logits = model(obs)

            loss_steps = F.smooth_l1_loss(pred_steps / STEPS_NORM, steps_15 / STEPS_NORM)
            loss_val = F.binary_cross_entropy_with_logits(val_logits, won)

            mae = (pred_steps - steps_15).abs().mean()
            val_acc = ((val_logits > 0.0) == (won > 0.5)).float().mean()

            b_len = len(b_idx)
            total_steps_loss += loss_steps.item() * b_len
            total_steps_mae += mae.item() * b_len
            total_val_loss += loss_val.item() * b_len
            total_val_acc += val_acc.item() * b_len

    return {
        "steps_loss": total_steps_loss / total,
        "steps_mae": total_steps_mae / total,
        "val_loss": total_val_loss / total,
        "val_acc": total_val_acc / total,
    }


def train_pure_state_network(
    data_dir: Path = DATA_DIR,
    out_dir: Path = RUN_DIR,
    hidden_dim: int = 256,
    epochs: int = 15,
    batch_size: int = 512,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    seed: int = 50000001,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"M50 Pure State Network Training: device={device}, hidden_dim={hidden_dim}")
    print("NO Policy Imitation Head. Pure distance regression to 15 VP + outcome value.")

    train_data = StateDataset(data_dir / "train")
    val_data = StateDataset(data_dir / "val")
    print(f"Loaded: train={train_data.count} states, val={val_data.count} states")

    model = PureStateDistanceNet(hidden_dim=hidden_dim).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    out_dir.mkdir(parents=True, exist_ok=True)

    val_0 = evaluate(model, val_data, device)
    print(f"Epoch 0 (Untrained Baseline): Val Steps MAE={val_0['steps_mae']:.2f} turns, Val Win Acc={val_0['val_acc']*100:.2f}%")

    best_mae = 999.0
    best_epoch = 1
    history = []

    t_start = time.perf_counter()
    indices = np.arange(train_data.count)

    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        np.random.shuffle(indices)

        train_loss_sum = 0.0
        train_mae_sum = 0.0

        for i in range(0, train_data.count, batch_size):
            b_idx = indices[i : min(i + batch_size, train_data.count)]
            obs, won, steps_15 = train_data.get_batch(b_idx, device)

            optimizer.zero_grad()
            pred_steps, val_logits = model(obs)

            loss_steps = F.smooth_l1_loss(pred_steps / STEPS_NORM, steps_15 / STEPS_NORM)
            loss_val = F.binary_cross_entropy_with_logits(val_logits, won)

            total_loss = loss_steps + 0.5 * loss_val
            total_loss.backward()

            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            mae = (pred_steps - steps_15).abs().mean()
            b_len = len(b_idx)
            train_loss_sum += total_loss.item() * b_len
            train_mae_sum += mae.item() * b_len

        scheduler.step()
        epoch_sec = time.perf_counter() - t0

        val_metrics = evaluate(model, val_data, device)
        train_mae = train_mae_sum / train_data.count

        row = {
            "epoch": epoch,
            "train_mae": train_mae,
            "val_mae": val_metrics["steps_mae"],
            "val_acc": val_metrics["val_acc"],
            "epoch_seconds": epoch_sec,
        }
        history.append(row)

        is_best = val_metrics["steps_mae"] < best_mae
        if is_best:
            best_mae = val_metrics["steps_mae"]
            best_epoch = epoch
            torch.save(model.state_dict(), out_dir / "best_model.pt")

        torch.save(model.state_dict(), out_dir / "latest_model.pt")

        print(
            f"Epoch {epoch:2d}/{epochs:2d} ({epoch_sec:.2f}s) | "
            f"Steps-to-15 MAE: Train={train_mae:.2f} turns, Val={val_metrics['steps_mae']:.2f} turns | "
            f"Val Win Acc={val_metrics['val_acc']*100:.1f}% {'*' if is_best else ''}"
        )

    total_sec = time.perf_counter() - t_start
    print(f"\nTraining complete in {total_sec:.2f}s. Best Epoch {best_epoch} with Val Steps MAE: {best_mae:.2f} turns")

    # Export weights JSON for Rust agent
    ckpt = torch.load(out_dir / "best_model.pt", weights_only=True)
    weights_json = {k: v.cpu().numpy().tolist() for k, v in ckpt.items()}
    with open(out_dir / "pure_state_weights.json", "w", encoding="utf-8") as f:
        json.dump(weights_json, f)
    print(f"Exported {out_dir / 'pure_state_weights.json'}")

    report = {
        "experiment": "M50 Pure State-Distance & Value Network (Zero Policy Imitation)",
        "data_dir": str(data_dir),
        "train_samples": train_data.count,
        "val_samples": val_data.count,
        "epochs": epochs,
        "batch_size": batch_size,
        "total_seconds": total_sec,
        "best_epoch": best_epoch,
        "best_val_mae": best_mae,
        "history": history,
    }

    with open(out_dir / "training_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main():
    parser = argparse.ArgumentParser(description="M50 Pure State-Distance Network Training")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--out-dir", type=str, default=str(RUN_DIR))
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    train_pure_state_network(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out_dir),
        hidden_dim=args.hidden_dim,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
