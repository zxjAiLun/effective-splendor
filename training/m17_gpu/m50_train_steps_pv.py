"""M50 Policy-Value-Steps Network: Multi-Task Learning on Competitive Replays.

Trained on 463,354 competitive decision steps with three complementary objectives:
  1. Policy Head: Cross-entropy imitation of expert actions.
  2. Steps-to-15 Head: Smooth L1 regression predicting exact remaining main turns to reach 15 VP.
  3. Value Head: BCE regression predicting ultimate match win probability.

This forces the state representation to directly encode speed/distance to 15 VP,
aligning policy choices with rapid victory while preserving global outcome awareness.
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
DATA_DIR = REPO_ROOT / "local-artifacts" / "m50-steps-dataset-v1"
RUN_DIR = REPO_ROOT / "local-artifacts" / "m50-steps-run"

OBS_DIM = 368
ACT_DIM = 36
STEPS_NORM = 20.0  # normalization factor for steps_to_15


def segmented_logsumexp(x: torch.Tensor, lengths: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    max_val = torch.segment_reduce(x, reduce="amax", lengths=lengths)
    shifted = x - max_val.repeat_interleave(lengths)
    sum_exp = torch.segment_reduce(torch.exp(shifted), reduce="sum", lengths=lengths)
    logsumexp = max_val + torch.log(sum_exp.clamp(min=1e-8))
    return logsumexp, max_val


class PolicyValueStepsNet(nn.Module):
    def __init__(self, obs_dim: int = OBS_DIM, act_dim: int = ACT_DIM, hidden_dim: int = 128):
        super().__init__()
        self.hidden_dim = hidden_dim

        # State representation trunk
        self.state_net = nn.Sequential(
            nn.Linear(obs_dim, 256),
            nn.LayerNorm(256),
            nn.ReLU(),
            nn.Linear(256, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )

        # Head 1: Value Head (Win probability logit)
        self.value_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

        # Head 2: Steps-to-15 Head (Expected main turns to 15 VP)
        self.steps_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

        # Head 3: Policy Head (Candidate action scorer)
        self.action_net = nn.Sequential(
            nn.Linear(act_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
        )
        self.action_bias = nn.Linear(act_dim, 1, bias=False)

    def forward(
        self,
        obs: torch.Tensor,
        actions: torch.Tensor,
        parent_idx: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Returns:
          action_logits: [M]
          val_logits: [B] (win prob logits)
          pred_steps: [B] (predicted main turns to 15, unnormalized)
        """
        state_h = self.state_net(obs)  # [B, H]
        val_logits = self.value_head(state_h).squeeze(-1)  # [B]

        # Steps to 15: softplus ensures strictly non-negative prediction
        pred_steps_norm = F.softplus(self.steps_head(state_h).squeeze(-1))  # [B]
        pred_steps = pred_steps_norm * STEPS_NORM

        act_h = self.action_net(actions)  # [M, H]
        state_expanded = state_h[parent_idx]  # [M, H]

        dot = (state_expanded * act_h).sum(dim=-1) / math.sqrt(self.hidden_dim)  # [M]
        bias = self.action_bias(actions).squeeze(-1)  # [M]
        action_logits = dot + bias

        return action_logits, val_logits, pred_steps


class StepsReplayDataset:
    def __init__(self, split_dir: Path):
        self.obs = np.memmap(split_dir / "obs.f32", dtype="<f4", mode="r").reshape(-1, OBS_DIM)
        self.offsets = np.fromfile(split_dir / "action_offsets.u64", dtype="<u8")
        self.actions = np.memmap(split_dir / "actions.f32", dtype="<f4", mode="r").reshape(-1, ACT_DIM)
        self.chosen = np.fromfile(split_dir / "chosen_action.u32", dtype="<u4")
        self.values = np.memmap(split_dir / "values.f32", dtype="<f4", mode="r").reshape(-1, 3)
        self.count = len(self.obs)
        assert len(self.offsets) == self.count + 1

    def get_batch(
        self, indices: np.ndarray, device: torch.device
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        batch_size = len(indices)
        batch_obs = torch.from_numpy(np.array(self.obs[indices], copy=True)).to(device)
        batch_won = torch.from_numpy(np.array(self.values[indices, 0], copy=True)).to(device)
        batch_steps = torch.from_numpy(np.array(self.values[indices, 2], copy=True)).to(device)

        starts = self.offsets[indices]
        ends = self.offsets[indices + 1]
        lengths = (ends - starts).astype(np.int64)

        action_slices = [self.actions[s:e] for s, e in zip(starts, ends)]
        batch_actions_np = np.concatenate(action_slices, axis=0)
        batch_actions = torch.from_numpy(batch_actions_np).to(device)

        lengths_t = torch.from_numpy(lengths).to(device)
        parent_idx = torch.repeat_interleave(
            torch.arange(batch_size, dtype=torch.int64, device=device), lengths_t
        )

        chosen_local = self.chosen[indices]
        cum_lengths = np.zeros(batch_size, dtype=np.int64)
        cum_lengths[1:] = np.cumsum(lengths[:-1])
        chosen_global = torch.from_numpy(cum_lengths + chosen_local).to(device)

        return batch_obs, batch_actions, parent_idx, lengths_t, chosen_global, batch_won, batch_steps


def evaluate(
    model: PolicyValueStepsNet,
    dataset: StepsReplayDataset,
    device: torch.device,
    batch_size: int = 512,
    max_eval_steps: int = 20000,
) -> dict[str, float]:
    model.eval()
    total_eval = min(dataset.count, max_eval_steps)
    indices = np.arange(total_eval)

    total_loss_pi = 0.0
    total_loss_v = 0.0
    total_steps_mae = 0.0
    total_top1 = 0.0
    total_val_acc = 0.0

    with torch.no_grad():
        for i in range(0, total_eval, batch_size):
            batch_idx = indices[i : min(i + batch_size, total_eval)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = dataset.get_batch(batch_idx, device)

            act_logits, val_logits, pred_steps = model(obs, actions, parent_idx)

            logsumexp, max_val = segmented_logsumexp(act_logits, lengths)
            chosen_logits = act_logits[chosen_global]

            loss_pi = (logsumexp - chosen_logits).mean()
            loss_v = F.binary_cross_entropy_with_logits(val_logits, won)
            steps_mae = (pred_steps - steps_15).abs().mean()

            is_top1 = (chosen_logits >= max_val - 1e-5).float().mean()
            val_pred_win = (val_logits > 0.0).float()
            val_acc = (val_pred_win == (won > 0.5).float()).float().mean()

            b_len = len(batch_idx)
            total_loss_pi += loss_pi.item() * b_len
            total_loss_v += loss_v.item() * b_len
            total_steps_mae += steps_mae.item() * b_len
            total_top1 += is_top1.item() * b_len
            total_val_acc += val_acc.item() * b_len

    return {
        "loss_pi": total_loss_pi / total_eval,
        "loss_v": total_loss_v / total_eval,
        "steps_mae": total_steps_mae / total_eval,
        "top1_acc": total_top1 / total_eval,
        "val_acc": total_val_acc / total_eval,
    }


def train_steps_network(
    data_dir: Path = DATA_DIR,
    out_dir: Path = RUN_DIR,
    pretrained_backbone: Path | None = None,
    epochs: int = 10,
    batch_size: int = 512,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    steps_weight: float = 1.0,
    value_weight: float = 0.5,
    seed: int = 50000001,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"M50 Steps Network Training: device={device}, data={data_dir}")

    train_data = StepsReplayDataset(data_dir / "train")
    val_data = StepsReplayDataset(data_dir / "val")
    print(f"Loaded: train={train_data.count} steps, val={val_data.count} steps")

    model = PolicyValueStepsNet(hidden_dim=128).to(device)

    # Transfer state_net, action_net, and value_head from existing model if provided
    if pretrained_backbone and pretrained_backbone.exists():
        ckpt = torch.load(pretrained_backbone, weights_only=True)
        model_dict = model.state_dict()
        transferred = 0
        for k, v in ckpt.items():
            if k in model_dict and model_dict[k].shape == v.shape:
                model_dict[k] = v
                transferred += 1
        model.load_state_dict(model_dict)
        print(f"Transferred {transferred} tensor weights from pretrained {pretrained_backbone}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    out_dir.mkdir(parents=True, exist_ok=True)
    best_top1 = 0.0
    best_epoch = 0
    history = []

    t_start = time.perf_counter()
    indices = np.arange(train_data.count)

    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        np.random.shuffle(indices)

        train_loss_pi_sum = 0.0
        train_loss_steps_sum = 0.0
        train_steps_mae_sum = 0.0
        train_top1_sum = 0.0

        for i in range(0, train_data.count, batch_size):
            batch_idx = indices[i : min(i + batch_size, train_data.count)]
            obs, actions, parent_idx, lengths, chosen_global, won, steps_15 = train_data.get_batch(batch_idx, device)

            optimizer.zero_grad()
            act_logits, val_logits, pred_steps = model(obs, actions, parent_idx)

            logsumexp, max_val = segmented_logsumexp(act_logits, lengths)
            chosen_logits = act_logits[chosen_global]

            # 1. Policy loss: Cross Entropy
            loss_pi = (logsumexp - chosen_logits).mean()

            # 2. Value loss: BCE
            loss_v = F.binary_cross_entropy_with_logits(val_logits, won)

            # 3. Steps-to-15 loss: Smooth L1 on normalized steps
            pred_steps_norm = pred_steps / STEPS_NORM
            target_steps_norm = steps_15 / STEPS_NORM
            loss_steps = F.smooth_l1_loss(pred_steps_norm, target_steps_norm)

            total_loss = loss_pi + steps_weight * loss_steps + value_weight * loss_v
            total_loss.backward()

            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            is_top1 = (chosen_logits >= max_val - 1e-5).float().mean()
            steps_mae = (pred_steps - steps_15).abs().mean()

            b_len = len(batch_idx)
            train_loss_pi_sum += loss_pi.item() * b_len
            train_loss_steps_sum += loss_steps.item() * b_len
            train_steps_mae_sum += steps_mae.item() * b_len
            train_top1_sum += is_top1.item() * b_len

        scheduler.step()
        epoch_sec = time.perf_counter() - t0

        val_metrics = evaluate(model, val_data, device)

        train_loss_pi = train_loss_pi_sum / train_data.count
        train_steps_mae = train_steps_mae_sum / train_data.count
        train_top1 = train_top1_sum / train_data.count

        row = {
            "epoch": epoch,
            "train_loss_pi": train_loss_pi,
            "train_steps_mae": train_steps_mae,
            "train_top1_acc": train_top1,
            "val_loss_pi": val_metrics["loss_pi"],
            "val_steps_mae": val_metrics["steps_mae"],
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
            f"Policy Top-1: Train={train_top1*100:.1f}%, Val={val_metrics['top1_acc']*100:.2f}% | "
            f"Steps-to-15 MAE: Train={train_steps_mae:.2f} turns, Val={val_metrics['steps_mae']:.2f} turns | "
            f"Val Win Acc={val_metrics['val_acc']*100:.1f}% {'*' if is_best else ''}"
        )

    total_sec = time.perf_counter() - t_start
    print(f"\nTraining complete in {total_sec:.2f}s. Best Epoch {best_epoch} with Val Top-1: {best_top1*100:.2f}%")

    # Export weights JSON for Rust agent
    ckpt = torch.load(out_dir / "best_model.pt", weights_only=True)
    weights_json = {k: v.cpu().numpy().tolist() for k, v in ckpt.items()}
    with open(out_dir / "m50_steps_weights.json", "w", encoding="utf-8") as f:
        json.dump(weights_json, f)
    print(f"Exported {out_dir / 'm50_steps_weights.json'}")

    report = {
        "experiment": "M50 Multi-Task Policy-Value-Steps Network",
        "data_dir": str(data_dir),
        "train_steps": train_data.count,
        "val_steps": val_data.count,
        "epochs": epochs,
        "batch_size": batch_size,
        "steps_weight": steps_weight,
        "value_weight": value_weight,
        "total_seconds": total_sec,
        "best_epoch": best_epoch,
        "best_val_top1_acc": best_top1,
        "history": history,
    }

    with open(out_dir / "training_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main():
    parser = argparse.ArgumentParser(description="M50 Policy-Value-Steps Network Training")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    parser.add_argument("--out-dir", type=str, default=str(RUN_DIR))
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--pretrained", type=str, default="local-artifacts/m50-large-run/best_model.pt")
    args = parser.parse_args()

    train_steps_network(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out_dir),
        pretrained_backbone=Path(args.pretrained) if args.pretrained else None,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
