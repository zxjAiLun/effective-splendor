"""M49A-II Efficiency-Q Trainer (Fast Tensor-Cache Implementation).

Uses pre-batched torch tensors for instantaneous target updates and training epochs.
"""

import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class EfficiencyQNet(nn.Module):
    def __init__(self, in_features: int = 428, hidden1: int = 256, hidden2: int = 128):
        super().__init__()
        self.in_features = in_features
        self.fc1 = nn.Linear(in_features, hidden1)
        self.ln1 = nn.LayerNorm(hidden1)
        self.fc2 = nn.Linear(hidden1, hidden2)
        self.fc3 = nn.Linear(hidden2, 1)
        self.act = nn.Softplus()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = F.relu(self.ln1(self.fc1(x)))
        h = F.relu(self.fc2(h))
        out = self.act(self.fc3(h))
        return out.squeeze(-1)


@torch.no_grad()
def compute_targets_from_cache(
    cache: dict[str, torch.Tensor],
    target_net: EfficiencyQNet,
    device: torch.device,
    failure_penalty: float = 100.0,
    sub_batch_size: int = 8192,
) -> torch.Tensor:
    target_net.eval()
    x = cache["x"].to(device)
    step_costs = cache["step_costs"].to(device)
    outcomes = cache["outcomes"].to(device)
    flat_next = cache["flat_next"].to(device)
    offsets = cache["offsets"].to(device)
    running_indices = cache["running_indices"].to(device)

    n = len(x)
    targets = torch.zeros(n, dtype=torch.float32, device=device)

    # 1. Terminal outcomes
    # outcome 0: reached_15 -> v = 0
    mask_win = outcomes == 0
    targets[mask_win] = step_costs[mask_win] + 0.0

    # outcome 1: stalled or turn_cap -> v = failure_penalty
    mask_fail = outcomes == 1
    targets[mask_fail] = step_costs[mask_fail] + failure_penalty

    # 2. Running outcomes: min_{a'} Q_target(o', a')
    if len(running_indices) > 0 and len(flat_next) > 0:
        # Batch forward flat_next through target_net
        all_q = []
        for i in range(0, len(flat_next), sub_batch_size):
            chunk = flat_next[i : i + sub_batch_size]
            all_q.append(target_net(chunk))
        q_flat = torch.cat(all_q, dim=0)

        # Compute min for each slice
        # offsets is (N_running, 2)
        v_nexts = torch.zeros(len(running_indices), dtype=torch.float32, device=device)
        for idx, (start, end) in enumerate(offsets):
            v_nexts[idx] = q_flat[start:end].min()

        targets[running_indices] = step_costs[running_indices] + v_nexts

    return targets


def evaluate_metrics(
    net: EfficiencyQNet,
    x: torch.Tensor,
    targets: torch.Tensor,
    device: torch.device,
    batch_size: int = 2048,
) -> dict[str, float]:
    net.eval()
    x = x.to(device)
    targets = targets.to(device)

    with torch.no_grad():
        preds = []
        for i in range(0, len(x), batch_size):
            bx = x[i : i + batch_size]
            preds.append(net(bx))
        preds = torch.cat(preds, dim=0)

        huber = F.smooth_l1_loss(preds, targets).item()
        mse = F.mse_loss(preds, targets).item()
        mae = F.l1_loss(preds, targets).item()

        preds_np = preds.cpu().numpy()

    return {
        "huber": float(huber),
        "mse": float(mse),
        "mae": float(mae),
        "q_min": float(np.min(preds_np)),
        "q_median": float(np.median(preds_np)),
        "q_p90": float(np.percentile(preds_np, 90)),
        "q_max": float(np.max(preds_np)),
        "q_mean": float(np.mean(preds_np)),
    }


def train_fqi_from_cache(
    train_cache: dict[str, torch.Tensor],
    val_cache: dict[str, torch.Tensor],
    device: torch.device,
    epochs_per_fqi: int = 15,
    fqi_iterations: int = 4,
    batch_size: int = 256,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    seed: int = 49000001,
) -> tuple[EfficiencyQNet, dict[str, Any]]:
    torch.manual_seed(seed)
    np.random.seed(seed % (2**32))

    x_train = train_cache["x"].to(device)
    x_val = val_cache["x"].to(device)
    n_train = len(x_train)
    in_features = x_train.shape[1]

    net = EfficiencyQNet(in_features=in_features).to(device)
    target_net = EfficiencyQNet(in_features=in_features).to(device)
    target_net.load_state_dict(net.state_dict())

    optimizer = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)

    history = []

    for fqi_iter in range(fqi_iterations):
        t0 = time.time()
        # 1. Update targets using target_net
        y_train = compute_targets_from_cache(train_cache, target_net, device)
        y_val = compute_targets_from_cache(val_cache, target_net, device)
        t_target = time.time() - t0

        # 2. Fit network to y_train
        net.train()
        t_train_start = time.time()
        for ep in range(epochs_per_fqi):
            perm = torch.randperm(n_train, device=device)
            for i in range(0, n_train, batch_size):
                idx = perm[i : i + batch_size]
                bx = x_train[idx]
                by = y_train[idx]

                pred = net(bx)
                loss = F.smooth_l1_loss(pred, by)

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                optimizer.step()

        t_train = time.time() - t_train_start

        # 3. Evaluate
        train_m = evaluate_metrics(net, x_train, y_train, device)
        val_m = evaluate_metrics(net, x_val, y_val, device)

        # 4. Polyak or hard target update
        target_net.load_state_dict(net.state_dict())

        rec = {
            "iteration": fqi_iter + 1,
            "target_calc_sec": round(t_target, 2),
            "train_sec": round(t_train, 2),
            "train_huber": train_m["huber"],
            "val_huber": val_m["huber"],
            "val_mae": val_m["mae"],
            "val_q_min": val_m["q_min"],
            "val_q_median": val_m["q_median"],
            "val_q_p90": val_m["q_p90"],
            "val_q_max": val_m["q_max"],
            "val_q_mean": val_m["q_mean"],
        }
        history.append(rec)
        print(f"FQI Iter {fqi_iter+1}/{fqi_iterations} (target {t_target:.1f}s, train {t_train:.1f}s): "
              f"val_huber={rec['val_huber']:.4f}, val_mae={rec['val_mae']:.2f}, "
              f"Q_med={rec['val_q_median']:.1f}, Q_range=[{rec['val_q_min']:.1f}, {rec['val_q_max']:.1f}]")

    return net, {"history": history, "final_val": val_m}
