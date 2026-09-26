"""M50: Dual-Head Policy-Value Network trained on competitive 2-player replays.

Trains a dual-head network on extracted match replay datasets (such as
s4-heuristic-v025-pilot: 34,169 train steps, 8,860 validation steps):
  - Policy Head: scores candidate legal actions via bilinear/dot-product,
    supervised by cross-entropy against heuristic chosen actions.
  - Value Head: predicts actor win probability, supervised by BCE against
    final game outcome.

Pure supervised learning: zero off-policy Bellman propagation instability,
zero deadly triad, strictly convex loss components.
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
DATA_DIR = REPO_ROOT / "local-artifacts" / "m50-pilot-dataset-v1"
RUN_DIR = REPO_ROOT / "local-artifacts" / "m50-replay-run"

OBS_DIM = 368
ACT_DIM = 36


def segmented_logsumexp(x: torch.Tensor, lengths: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Numerically stable logsumexp and amax over variable-length contiguous segments."""
    max_val = torch.segment_reduce(x, reduce="amax", lengths=lengths)
    shifted = x - max_val.repeat_interleave(lengths)
    sum_exp = torch.segment_reduce(torch.exp(shifted), reduce="sum", lengths=lengths)
    logsumexp = max_val + torch.log(sum_exp.clamp(min=1e-8))
    return logsumexp, max_val


class PolicyValueNet(nn.Module):
    def __init__(self, obs_dim: int = OBS_DIM, act_dim: int = ACT_DIM, hidden_dim: int = 128):
        super().__init__()
        self.hidden_dim = hidden_dim
        # State trunk
        self.state_net = nn.Sequential(
            nn.Linear(obs_dim, 256),
            nn.LayerNorm(256),
            nn.ReLU(),
            nn.Linear(256, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )
        # Value head (win probability)
        self.value_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )
        # Action encoder
        self.action_net = nn.Sequential(
            nn.Linear(act_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )
        # Action prior / bias
        self.action_bias = nn.Linear(act_dim, 1, bias=False)

    def forward(
        self,
        obs: torch.Tensor,
        actions: torch.Tensor,
        parent_idx: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        obs: [B, OBS_DIM]
        actions: [M, ACT_DIM]
        parent_idx: [M] (maps each action to its step in [0..B-1])
        Returns:
          action_logits: [M]
          value_pred: [B] (win probability logits)
        """
        state_h = self.state_net(obs)  # [B, H]
        val_logits = self.value_head(state_h).squeeze(-1)  # [B]

        act_h = self.action_net(actions)  # [M, H]
        state_expanded = state_h[parent_idx]  # [M, H]

        # Bilinear / dot-product scoring
        dot = (state_expanded * act_h).sum(dim=-1) / math.sqrt(self.hidden_dim)  # [M]
        bias = self.action_bias(actions).squeeze(-1)  # [M]
        action_logits = dot + bias

        return action_logits, val_logits


class ReplayDataset:
    def __init__(self, split_dir: Path):
        self.obs = np.memmap(split_dir / "obs.f32", dtype="<f4", mode="r").reshape(-1, OBS_DIM)
        self.offsets = np.fromfile(split_dir / "action_offsets.u64", dtype="<u8")
        self.actions = np.memmap(split_dir / "actions.f32", dtype="<f4", mode="r").reshape(-1, ACT_DIM)
        self.chosen = np.fromfile(split_dir / "chosen_action.u32", dtype="<u4")
        self.values = np.memmap(split_dir / "values.f32", dtype="<f4", mode="r").reshape(-1, 2)
        self.count = len(self.obs)
        assert len(self.offsets) == self.count + 1

    def get_batch(
        self, indices: np.ndarray, device: torch.device
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        batch_size = len(indices)
        batch_obs = torch.from_numpy(np.array(self.obs[indices], copy=True)).to(device)
        batch_won = torch.from_numpy(np.array(self.values[indices, 0], copy=True)).to(device)

        starts = self.offsets[indices]
        ends = self.offsets[indices + 1]
        lengths = (ends - starts).astype(np.int64)

        # Slice actions for this batch
        action_slices = [self.actions[s:e] for s, e in zip(starts, ends)]
        batch_actions_np = np.concatenate(action_slices, axis=0)
        batch_actions = torch.from_numpy(batch_actions_np).to(device)

        lengths_t = torch.from_numpy(lengths).to(device)
        parent_idx = torch.repeat_interleave(
            torch.arange(batch_size, dtype=torch.int64, device=device), lengths_t
        )

        # Compute global chosen action index in batch_actions
        chosen_local = self.chosen[indices]
        cum_lengths = np.zeros(batch_size, dtype=np.int64)
        cum_lengths[1:] = np.cumsum(lengths[:-1])
        chosen_global = torch.from_numpy(cum_lengths + chosen_local).to(device)

        return batch_obs, batch_actions, parent_idx, lengths_t, chosen_global, batch_won


def evaluate(
    model: PolicyValueNet,
    dataset: ReplayDataset,
    device: torch.device,
    batch_size: int = 512,
) -> dict[str, float]:
    model.eval()
    total_steps = dataset.count
    indices = np.arange(total_steps)

    total_loss_pi = 0.0
    total_loss_v = 0.0
    total_top1 = 0.0
    total_val_acc = 0.0

    with torch.no_grad():
        for i in range(0, total_steps, batch_size):
            batch_idx = indices[i : min(i + batch_size, total_steps)]
            obs, actions, parent_idx, lengths, chosen_global, won = dataset.get_batch(batch_idx, device)

            act_logits, val_logits = model(obs, actions, parent_idx)

            logsumexp, max_val = segmented_logsumexp(act_logits, lengths)
            chosen_logits = act_logits[chosen_global]

            loss_pi = (logsumexp - chosen_logits).mean()
            loss_v = F.binary_cross_entropy_with_logits(val_logits, won)

            is_top1 = (chosen_logits >= max_val - 1e-5).float().mean()
            val_pred_win = (val_logits > 0.0).float()
            val_acc = (val_pred_win == (won > 0.5).float()).float().mean()

            b_len = len(batch_idx)
            total_loss_pi += loss_pi.item() * b_len
            total_loss_v += loss_v.item() * b_len
            total_top1 += is_top1.item() * b_len
            total_val_acc += val_acc.item() * b_len

    return {
        "loss_pi": total_loss_pi / total_steps,
        "loss_v": total_loss_v / total_steps,
        "top1_acc": total_top1 / total_steps,
        "val_acc": total_val_acc / total_steps,
    }


def train(
    data_dir: Path = DATA_DIR,
    out_dir: Path = RUN_DIR,
    epochs: int = 15,
    batch_size: int = 256,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    value_weight: float = 0.5,
    seed: int = 50000001,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"M50 Training: device={device}, data={data_dir}")

    train_data = ReplayDataset(data_dir / "train")
    val_data = ReplayDataset(data_dir / "val")
    print(f"Loaded: train={train_data.count} steps, val={val_data.count} steps")

    model = PolicyValueNet(hidden_dim=128).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    # Initial baseline evaluation (epoch 0, untrained)
    val_metrics_0 = evaluate(model, val_data, device)
    print(
        f"Epoch 0 (Untrained Baseline): "
        f"Val Policy Loss={val_metrics_0['loss_pi']:.4f}, Top-1 Acc={val_metrics_0['top1_acc']*100:.2f}% "
        f"(Random={100/30.9:.2f}%), "
        f"Val Value Loss={val_metrics_0['loss_v']:.4f}, Val Acc={val_metrics_0['val_acc']*100:.2f}%"
    )

    history = [
        {
            "epoch": 0,
            "val_loss_pi": val_metrics_0["loss_pi"],
            "val_top1_acc": val_metrics_0["top1_acc"],
            "val_loss_v": val_metrics_0["loss_v"],
            "val_val_acc": val_metrics_0["val_acc"],
        }
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    best_top1 = 0.0
    best_epoch = 0

    t_start = time.perf_counter()
    indices = np.arange(train_data.count)

    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        np.random.shuffle(indices)

        train_loss_pi_sum = 0.0
        train_loss_v_sum = 0.0
        train_top1_sum = 0.0

        for i in range(0, train_data.count, batch_size):
            batch_idx = indices[i : min(i + batch_size, train_data.count)]
            obs, actions, parent_idx, lengths, chosen_global, won = train_data.get_batch(batch_idx, device)

            optimizer.zero_grad()
            act_logits, val_logits = model(obs, actions, parent_idx)

            logsumexp, max_val = segmented_logsumexp(act_logits, lengths)
            chosen_logits = act_logits[chosen_global]

            loss_pi = (logsumexp - chosen_logits).mean()
            loss_v = F.binary_cross_entropy_with_logits(val_logits, won)

            total_loss = loss_pi + value_weight * loss_v
            total_loss.backward()

            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            is_top1 = (chosen_logits >= max_val - 1e-5).float().mean()
            b_len = len(batch_idx)
            train_loss_pi_sum += loss_pi.item() * b_len
            train_loss_v_sum += loss_v.item() * b_len
            train_top1_sum += is_top1.item() * b_len

        scheduler.step()
        epoch_sec = time.perf_counter() - t0

        val_metrics = evaluate(model, val_data, device)

        train_loss_pi = train_loss_pi_sum / train_data.count
        train_loss_v = train_loss_v_sum / train_data.count
        train_top1 = train_top1_sum / train_data.count

        row = {
            "epoch": epoch,
            "train_loss_pi": train_loss_pi,
            "train_loss_v": train_loss_v,
            "train_top1_acc": train_top1,
            "val_loss_pi": val_metrics["loss_pi"],
            "val_loss_v": val_metrics["loss_v"],
            "val_top1_acc": val_metrics["top1_acc"],
            "val_val_acc": val_metrics["val_acc"],
            "epoch_seconds": epoch_sec,
        }
        history.append(row)

        is_best = val_metrics["top1_acc"] > best_top1
        if is_best:
            best_top1 = val_metrics["top1_acc"]
            best_epoch = epoch
            torch.save(model.state_dict(), out_dir / "best_model.pt")

        print(
            f"Epoch {epoch:2d}/{epochs:2d} ({epoch_sec:.2f}s) | "
            f"Train Policy Loss={train_loss_pi:.3f}, Top-1={train_top1*100:.1f}% | "
            f"Val Policy Loss={val_metrics['loss_pi']:.3f}, Top-1={val_metrics['top1_acc']*100:.2f}% | "
            f"Val Value Acc={val_metrics['val_acc']*100:.1f}% {'*' if is_best else ''}"
        )

    total_sec = time.perf_counter() - t_start
    print(f"\nTraining completed in {total_sec:.2f}s. Best Epoch {best_epoch} with Val Top-1: {best_top1*100:.2f}%")

    report = {
        "experiment": "M50 Competitive Replay Policy-Value Training",
        "data_dir": str(data_dir),
        "train_steps": train_data.count,
        "val_steps": val_data.count,
        "epochs": epochs,
        "batch_size": batch_size,
        "device": str(device),
        "total_seconds": total_sec,
        "best_epoch": best_epoch,
        "best_val_top1_acc": best_top1,
        "history": history,
    }

    report_path = out_dir / "training_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main():
    parser = argparse.ArgumentParser(description="M50 Replay Policy-Value Training")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=50000001)
    args = parser.parse_args()

    train(epochs=args.epochs, batch_size=args.batch_size, lr=args.lr, seed=args.seed)


if __name__ == "__main__":
    main()
