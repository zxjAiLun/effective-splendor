"""M49A-II Efficiency-Q Trainer with Streaming Rust Bellman Target Builder.

Consumes:
- `current_x.f32`: [N, 428] float32 array (loaded via numpy memmap or torch)
- `compact_transitions.jsonl`: NDJSON of M49ACompactTransitionV1

Each FQI iteration:
1. Exports current target_net weights to a temporary weights.json;
2. Calls Rust CLI `splendor m49a-build-targets` to compute targets.f32 on-demand;
3. Reads targets.f32 into torch.Tensor (size N * 4 bytes);
4. Fits Q-network on (current_x, targets) with Huber loss.
"""

import json
import subprocess
import tempfile
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


def export_net_weights_dict(net: EfficiencyQNet) -> dict[str, Any]:
    state = net.state_dict()
    return {
        "fc1_w": state["fc1.weight"].cpu().numpy().tolist(),
        "fc1_b": state["fc1.bias"].cpu().numpy().tolist(),
        "ln1_w": state["ln1.weight"].cpu().numpy().tolist(),
        "ln1_b": state["ln1.bias"].cpu().numpy().tolist(),
        "fc2_w": state["fc2.weight"].cpu().numpy().tolist(),
        "fc2_b": state["fc2.bias"].cpu().numpy().tolist(),
        "fc3_w": state["fc3.weight"].cpu().numpy().tolist(),
        "fc3_b": state["fc3.bias"].cpu().numpy().tolist(),
    }


def compute_targets_streaming(
    transitions_jsonl: Path,
    target_net: EfficiencyQNet,
    tmp_dir: Path,
    failure_penalty: float = 100.0,
    cargo_bin: str = "splendor",
) -> torch.Tensor:
    """Invokes the streaming Rust target builder on compact transitions."""
    weights_path = tmp_dir / "target_weights.json"
    targets_path = tmp_dir / "targets.f32"

    weights_dict = export_net_weights_dict(target_net)
    with open(weights_path, "w", encoding="utf-8") as f:
        json.dump(weights_dict, f)

    cmd = [
        "cargo",
        "run",
        "-q",
        "-p",
        "splendor-cli",
        "--bin",
        cargo_bin,
        "--",
        "m49a-build-targets",
        "--transitions",
        str(transitions_jsonl),
        "--weights",
        str(weights_path),
        "--out-targets",
        str(targets_path),
        "--failure-penalty",
        str(failure_penalty),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Rust target builder failed: {res.stderr}\n{res.stdout}")

    targets_np = np.fromfile(str(targets_path), dtype=np.float32)
    return torch.from_numpy(targets_np.copy())


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


def train_fqi_streaming(
    train_x_path: Path,
    train_transitions_path: Path,
    val_x_path: Path,
    val_transitions_path: Path,
    device: torch.device,
    epochs_per_fqi: int = 15,
    fqi_iterations: int = 4,
    batch_size: int = 256,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    seed: int = 49000001,
) -> tuple[EfficiencyQNet, dict[str, Any]]:
    """Runs Fitted Q-Iteration using memory-mapped current_x and on-demand streaming Rust targets."""
    torch.manual_seed(seed)
    np.random.seed(seed % (2**32))

    # Load current_x via memmap / fromfile
    train_x_np = np.fromfile(str(train_x_path), dtype=np.float32).reshape(-1, 428)
    val_x_np = np.fromfile(str(val_x_path), dtype=np.float32).reshape(-1, 428)

    x_train = torch.from_numpy(train_x_np).to(device)
    x_val = torch.from_numpy(val_x_np).to(device)
    n_train = len(x_train)
    in_features = x_train.shape[1]

    net = EfficiencyQNet(in_features=in_features).to(device)
    target_net = EfficiencyQNet(in_features=in_features).to(device)
    target_net.load_state_dict(net.state_dict())

    optimizer = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)

    history = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_dir = Path(tmpdir)

        for fqi_iter in range(fqi_iterations):
            t0 = time.time()
            # 1. Update targets using target_net via streaming Rust builder
            y_train = compute_targets_streaming(train_transitions_path, target_net, tmp_dir).to(device)
            y_val = compute_targets_streaming(val_transitions_path, target_net, tmp_dir).to(device)
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

            # 4. Update target network
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
