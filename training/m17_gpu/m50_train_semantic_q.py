"""M50 Semantic Q-Network Training: ZERO Policy Cross-Entropy Imitation.

Input:
  obs: 368-dim state
  actions: 48-dim semantic action features (deficit reduction, purchase readiness, noble alignment, etc.)

Objective:
  Predict Q_steps(s, a) = Expected remaining turns to 15 VP.
  Loss:
    1. Smooth L1 calibration on chosen winning actions: Q(s, a*) ~ y_steps
    2. Ranking margin loss: Q(s, a) >= Q(s, a*) for unchosen actions (they should not take fewer steps)
    3. State-level win probability BCE
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
DATA_DIR = REPO_ROOT / "local-artifacts" / "m50-semantic-dataset-v1"
RUN_DIR = REPO_ROOT / "local-artifacts" / "m50-semantic-q-run"

OBS_DIM = 368
ACT_DIM = 48
STEPS_NORM = 20.0


class SemanticQStepsNet(nn.Module):
    def __init__(self, obs_dim: int = OBS_DIM, act_dim: int = ACT_DIM, hidden_dim: int = 256):
        super().__init__()
        self.hidden_dim = hidden_dim

        # State representation trunk (368 -> 512 -> 256)
        self.state_net = nn.Sequential(
            nn.Linear(obs_dim, 512),
            nn.LayerNorm(512),
            nn.ReLU(),
            nn.Linear(512, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )

        # Action semantic encoder (48 -> 128 -> 256)
        self.action_net = nn.Sequential(
            nn.Linear(act_dim, 128),
            nn.LayerNorm(128),
            nn.ReLU(),
            nn.Linear(128, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )

        # Joint Q-head: takes [state_h, act_h, act_raw] -> Q_steps(s, a)
        self.q_head = nn.Sequential(
            nn.Linear(hidden_dim * 2 + act_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

        # State Value Head (Win probability logit)
        self.val_head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 1),
        )

    def forward(
        self,
        obs: torch.Tensor,
        actions: torch.Tensor,
        parent_idx: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        obs: [B, 368]
        actions: [M, 48]
        parent_idx: [M]
        Returns:
          q_steps: [M] (predicted remaining turns to 15 VP)
          val_logits: [B] (win prob logits)
        """
        state_h = self.state_net(obs)  # [B, H]
        val_logits = self.val_head(state_h).squeeze(-1)  # [B]

        act_h = self.action_net(actions)  # [M, H]
        state_expanded = state_h[parent_idx]  # [M, H]

        joint = torch.cat([state_expanded, act_h, actions], dim=-1)  # [M, 2H + 48]
        q_steps_norm = F.softplus(self.q_head(joint).squeeze(-1))
        q_steps = q_steps_norm * STEPS_NORM

        return q_steps, val_logits


class SemanticDataset:
    def __init__(self, split_dir: Path):
        self.obs = np.memmap(split_dir / "obs.f32", dtype="<f4", mode="r").reshape(-1, OBS_DIM)
        self.actions = np.memmap(split_dir / "actions.f32", dtype="<f4", mode="r").reshape(-1, ACT_DIM)
        self.action_offsets = np.memmap(split_dir / "action_offsets.u64", dtype="<u8", mode="r")
        self.chosen_actions = np.memmap(split_dir / "chosen_action.u32", dtype="<u4", mode="r")
        self.values = np.memmap(split_dir / "values.f32", dtype="<f4", mode="r").reshape(-1, 3)

        self.count = len(self.obs)
        assert len(self.action_offsets) == self.count + 1

    def get_batch(
        self, indices: np.ndarray, device: torch.device
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, list[int], torch.Tensor, torch.Tensor, torch.Tensor]:
        batch_obs = torch.from_numpy(np.array(self.obs[indices], copy=True)).to(device)
        batch_won = torch.from_numpy(np.array(self.values[indices, 0], copy=True)).to(device)
        batch_steps = torch.from_numpy(np.array(self.values[indices, 2], copy=True)).to(device)

        actions_list = []
        parent_idx_list = []
        lengths = []
        chosen_global = []

        total_actions_so_far = 0
        for local_b_idx, i in enumerate(indices):
            start = self.action_offsets[i]
            end = self.action_offsets[i + 1]
            act_slice = np.array(self.actions[start:end], copy=True)
            k = len(act_slice)

            actions_list.append(act_slice)
            parent_idx_list.append(np.full(k, local_b_idx, dtype=np.int64))
            lengths.append(k)

            c = self.chosen_actions[i]
            chosen_global.append(total_actions_so_far + c)
            total_actions_so_far += k

        flat_actions = torch.from_numpy(np.concatenate(actions_list, axis=0)).to(device)
        flat_parents = torch.from_numpy(np.concatenate(parent_idx_list, axis=0)).to(device)
        chosen_indices = torch.tensor(chosen_global, dtype=torch.long, device=device)

        return batch_obs, flat_actions, flat_parents, lengths, chosen_indices, batch_won, batch_steps


def evaluate(
    model: SemanticQStepsNet,
    dataset: SemanticDataset,
    device: torch.device,
    batch_size: int = 512,
) -> dict[str, float]:
    model.eval()
    total = dataset.count
    indices = np.arange(total)

    total_q_mae = 0.0
    total_val_acc = 0.0
    total_top1 = 0.0

    with torch.no_grad():
        for i in range(0, total, batch_size):
            b_idx = indices[i : min(i + batch_size, total)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = dataset.get_batch(b_idx, device)

            q_steps, val_logits = model(obs, actions, parent_idx)
            chosen_q = q_steps[chosen_global]

            mae = (chosen_q - steps_15).abs().mean()
            val_acc = ((val_logits > 0.0) == (won > 0.5)).float().mean()

            # Check if chosen action had the minimum predicted steps in each decision!
            start = 0
            correct = 0
            for b_i, k in enumerate(lengths):
                end = start + k
                sub_q = q_steps[start:end]
                c_idx = chosen_global[b_i] - start
                if sub_q[c_idx] <= sub_q.min() + 1e-4:
                    correct += 1
                start = end

            b_len = len(b_idx)
            total_q_mae += mae.item() * b_len
            total_val_acc += val_acc.item() * b_len
            total_top1 += correct

    return {
        "q_mae": total_q_mae / total,
        "val_acc": total_val_acc / total,
        "min_step_top1": total_top1 / total,
    }


def train_semantic_q(
    data_dir: Path = DATA_DIR,
    out_dir: Path = RUN_DIR,
    hidden_dim: int = 256,
    epochs: int = 10,
    batch_size: int = 256,
    lr: float = 3e-4,
    seed: int = 50000001,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"M50 Semantic Q-Network Training: device={device}, hidden_dim={hidden_dim}, act_dim={ACT_DIM}")
    print("ZERO Policy Cross-Entropy Imitation. Pure physical Steps Regression + Action Margin Ranking.")

    train_data = SemanticDataset(data_dir / "train")
    val_data = SemanticDataset(data_dir / "val")
    print(f"Loaded: train={train_data.count} steps, val={val_data.count} steps")

    model = SemanticQStepsNet(hidden_dim=hidden_dim).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    out_dir.mkdir(parents=True, exist_ok=True)

    val_0 = evaluate(model, val_data, device)
    print(f"Epoch 0 (Untrained Baseline): Val Q MAE={val_0['q_mae']:.2f} turns, Min-Step Top-1={val_0['min_step_top1']*100:.2f}%")

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
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = train_data.get_batch(b_idx, device)

            optimizer.zero_grad()
            q_steps, val_logits = model(obs, actions, parent_idx)

            chosen_q = q_steps[chosen_global]

            # 1. Direct Q-calibration loss on winning action
            loss_calib = F.smooth_l1_loss(chosen_q / STEPS_NORM, steps_15 / STEPS_NORM)

            # 2. Margin Ranking loss: other actions shouldn't take fewer steps than the winning action!
            # q_other >= q_chosen - 0.05
            chosen_expanded = chosen_q[parent_idx]
            margin_violation = F.relu((chosen_expanded - q_steps) / STEPS_NORM + 0.02)
            loss_margin = margin_violation.mean()

            # 3. Value loss: BCE
            loss_v = F.binary_cross_entropy_with_logits(val_logits, won)

            total_loss = loss_calib + 0.5 * loss_margin + 0.2 * loss_v
            total_loss.backward()

            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            mae = (chosen_q - steps_15).abs().mean()
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
            "val_mae": val_metrics["q_mae"],
            "val_min_step_top1": val_metrics["min_step_top1"],
            "epoch_seconds": epoch_sec,
        }
        history.append(row)

        is_best = val_metrics["q_mae"] < best_mae
        if is_best:
            best_mae = val_metrics["q_mae"]
            best_epoch = epoch
            torch.save(model.state_dict(), out_dir / "best_model.pt")

        torch.save(model.state_dict(), out_dir / "latest_model.pt")

        print(
            f"Epoch {epoch:2d}/{epochs:2d} ({epoch_sec:.2f}s) | "
            f"Q-Steps MAE: Train={train_mae:.2f} turns, Val={val_metrics['q_mae']:.2f} turns | "
            f"Min-Step Match={val_metrics['min_step_top1']*100:.1f}% {'*' if is_best else ''}"
        )

    total_sec = time.perf_counter() - t_start
    print(f"\nTraining complete in {total_sec:.2f}s. Best Epoch {best_epoch} with Val Q MAE: {best_mae:.2f} turns")

    # Export weights JSON for Rust agent
    ckpt = torch.load(out_dir / "best_model.pt", weights_only=True)
    weights_json = {k: v.cpu().numpy().tolist() for k, v in ckpt.items()}
    with open(out_dir / "semantic_q_weights.json", "w", encoding="utf-8") as f:
        json.dump(weights_json, f)
    print(f"Exported {out_dir / 'semantic_q_weights.json'}")

    return history


def main():
    parser = argparse.ArgumentParser(description="M50 Semantic Q Training")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--out-dir", type=str, default=str(RUN_DIR))
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()

    train_semantic_q(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out_dir),
        hidden_dim=args.hidden_dim,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
