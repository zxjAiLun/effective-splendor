"""CUDA FQI trainer using canonical, pre-exported successor feature caches.

The Rust exporter owns game/representation semantics. This module performs the
repeated Bellman min-Q work as batched CUDA linear algebra without reparsing
JSONL or spawning a process per refresh.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from .m49a_trainer import (
    EfficiencyQNet,
    evaluate_metrics,
    export_net_weights_dict,
    hard_update_target_net,
)

OBSERVATION_WIDTH = 368
SUFFIX_WIDTH = 60  # action 36 + action-delta 23 + normalized horizon 1
FAILURE_PENALTY = 100.0


class SuccessorFeatureCache:
    """Memory-mapped split-feature cache with verified, fixed row dimensions."""

    def __init__(self, directory: Path, transition_count: int):
        self.directory = Path(directory)
        self.transition_count = int(transition_count)
        prefix_path = self.directory / "next_obs_prefix.f32"
        suffix_path = self.directory / "next_action_suffix.f32"
        offsets_path = self.directory / "action_offsets.u64"
        expected_prefix_bytes = self.transition_count * OBSERVATION_WIDTH * 4
        if prefix_path.stat().st_size != expected_prefix_bytes:
            raise ValueError(
                f"{prefix_path} has {prefix_path.stat().st_size} bytes; "
                f"expected {expected_prefix_bytes}"
            )
        if suffix_path.stat().st_size % (SUFFIX_WIDTH * 4) != 0:
            raise ValueError(f"{suffix_path} has an invalid suffix feature byte count")
        expected_offsets_bytes = (self.transition_count + 1) * 8
        if offsets_path.stat().st_size != expected_offsets_bytes:
            raise ValueError(
                f"{offsets_path} has {offsets_path.stat().st_size} bytes; "
                f"expected {expected_offsets_bytes}"
            )

        self.successor_count = suffix_path.stat().st_size // (SUFFIX_WIDTH * 4)
        self.prefixes = np.memmap(
            prefix_path,
            dtype="<f4",
            mode="r",
            shape=(self.transition_count, OBSERVATION_WIDTH),
        )
        self.suffixes = np.memmap(
            suffix_path,
            dtype="<f4",
            mode="r",
            shape=(self.successor_count, SUFFIX_WIDTH),
        )
        self.offsets = np.fromfile(offsets_path, dtype="<u8")
        if self.offsets.shape != (self.transition_count + 1,):
            raise ValueError("action offsets have an unexpected shape")
        if int(self.offsets[0]) != 0 or int(self.offsets[-1]) != self.successor_count:
            raise ValueError("action offsets do not cover the successor feature rows")
        if np.any(self.offsets[1:] < self.offsets[:-1]):
            raise ValueError("action offsets are not monotone")
        self.counts = np.diff(self.offsets).astype(np.int64, copy=False)
        self._device_cache: dict[str, tuple[torch.Tensor, torch.Tensor, torch.Tensor]] = {}

    def prepare_cuda(
        self, device: torch.device
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Keep shared prefixes, segment lengths, and row parents resident on GPU."""
        if device.type != "cuda":
            raise ValueError("successor feature cache preparation requires CUDA")
        key = str(device)
        if key not in self._device_cache:
            prefix_host = np.array(
                self.prefixes, dtype=np.float32, copy=True, order="C"
            )
            prefixes = torch.from_numpy(prefix_host).to(device=device)
            counts = torch.as_tensor(self.counts, dtype=torch.int64, device=device)
            transition_ids = torch.repeat_interleave(
                torch.arange(self.transition_count, dtype=torch.int64, device=device),
                counts,
            )
            if transition_ids.numel() != self.successor_count:
                raise ValueError("segment lengths do not cover successor action rows")
            self._device_cache[key] = (prefixes, counts, transition_ids)
        return self._device_cache[key]

    def validate_outcomes(self, outcomes: np.ndarray) -> None:
        if outcomes.shape != (self.transition_count,):
            raise ValueError("outcome vector shape does not match successor cache")
        if not np.all(np.isin(outcomes, [0, 1, 2])):
            raise ValueError("outcomes contain unknown enum values")
        is_running = outcomes == 2
        has_successors = self.counts > 0
        if not np.array_equal(is_running, has_successors):
            bad = np.flatnonzero(is_running != has_successors)[:8].tolist()
            raise ValueError(
                "Running/outcome and successor-action segments disagree at rows "
                f"{bad}"
            )


def compute_targets_cuda_cached(
    cache: SuccessorFeatureCache,
    target_net: EfficiencyQNet,
    step_costs: torch.Tensor,
    outcomes: torch.Tensor,
    device: torch.device,
    action_batch_size: int = 131072,
) -> torch.Tensor:
    """Compute y=c+V(o') by batched CUDA forward passes and segment-min.

    The shared observation projection is evaluated once per transition. The
    action/delta/horizon suffix is then projected in large batches and combined
    with its transition's prefix projection. This is mathematically the same
    MLP and Bellman rule, but CUDA/TF32 accumulation is intentionally not
    bit-identical to the historical scalar CPU implementation.
    """
    if device.type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("CUDA target builder requires an available CUDA device")
    if cache.transition_count != len(step_costs) or len(outcomes) != len(step_costs):
        raise ValueError("cache, cost, and outcome row counts differ")
    if action_batch_size <= 0:
        raise ValueError("action_batch_size must be positive")

    target_net.eval()
    outcomes = outcomes.to(device=device, dtype=torch.uint8)
    step_costs = step_costs.to(device=device, dtype=torch.float32)
    prefix, counts, transition_ids = cache.prepare_cuda(device)
    is_running = outcomes == 2
    if not torch.equal(counts > 0, is_running):
        raise ValueError("Running outcomes and successor segments disagree")

    with torch.no_grad():
        fc1 = target_net.fc1
        prefix_projection = F.linear(
            prefix, fc1.weight[:, :OBSERVATION_WIDTH], fc1.bias
        )
        q_values = torch.empty(cache.successor_count, dtype=torch.float32, device=device)

        suffix_weight = fc1.weight[:, OBSERVATION_WIDTH:]
        for start in range(0, cache.successor_count, action_batch_size):
            end = min(start + action_batch_size, cache.successor_count)
            suffix_host = np.array(
                cache.suffixes[start:end], dtype=np.float32, copy=True, order="C"
            )
            suffix = torch.from_numpy(suffix_host).to(device=device)
            del suffix_host
            parent = transition_ids[start:end]

            hidden = F.linear(suffix, suffix_weight, None)
            hidden.add_(prefix_projection.index_select(0, parent))
            hidden = F.relu(target_net.ln1(hidden))
            hidden = F.relu(target_net.fc2(hidden))
            q = F.softplus(target_net.fc3(hidden).squeeze(-1))
            q_values[start:end].copy_(q)

        min_next = torch.segment_reduce(q_values, reduce="min", lengths=counts)
        v_next = torch.where(
            outcomes == 0,
            torch.zeros_like(step_costs),
            torch.where(
                outcomes == 1,
                torch.full_like(step_costs, FAILURE_PENALTY),
                min_next,
            ),
        )
        targets = step_costs + v_next
        if not torch.isfinite(targets).all().item():
            raise FloatingPointError("CUDA Bellman target contains non-finite values")
        if torch.cuda.is_available():
            torch.cuda.synchronize(device)
    return targets


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    temp.replace(path)


def train_fqi_cuda_cached(
    *,
    train_x_path: Path,
    train_cache: SuccessorFeatureCache,
    train_costs_path: Path,
    train_outcomes_path: Path,
    val_x_path: Path,
    val_cache: SuccessorFeatureCache,
    val_costs_path: Path,
    val_outcomes_path: Path,
    device: torch.device,
    fqi_iterations: int = 80,
    epochs_per_fqi: int = 8,
    hard_target_refresh_epochs: int = 4,
    batch_size: int = 256,
    action_batch_size: int = 131072,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    seed: int = 49000001,
    checkpoint_dir: Path,
    checkpoint_every: int = 10,
    progress_path: Path | None = None,
) -> tuple[EfficiencyQNet, dict[str, Any]]:
    if device.type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("fast FQI trainer requires CUDA")
    if fqi_iterations <= 0 or epochs_per_fqi <= 0:
        raise ValueError("FQI iterations and epochs per block must be positive")
    if hard_target_refresh_epochs <= 0 or epochs_per_fqi % hard_target_refresh_epochs:
        raise ValueError("hard target refresh interval must divide epochs_per_fqi")
    if batch_size <= 0 or checkpoint_every <= 0:
        raise ValueError("batch_size and checkpoint_every must be positive")

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed % (2**32))

    train_x_np = np.fromfile(train_x_path, dtype=np.float32)
    val_x_np = np.fromfile(val_x_path, dtype=np.float32)
    if train_x_np.size % 428 or val_x_np.size % 428:
        raise ValueError("current_x files are not divisible into 428-d rows")
    x_train = torch.from_numpy(train_x_np.reshape(-1, 428).copy()).to(device)
    x_val = torch.from_numpy(val_x_np.reshape(-1, 428).copy()).to(device)
    if len(x_train) != train_cache.transition_count:
        raise ValueError("train_x rows differ from train successor-cache rows")
    if len(x_val) != val_cache.transition_count:
        raise ValueError("val_x rows differ from validation successor-cache rows")

    train_costs = np.fromfile(train_costs_path, dtype=np.float32)
    val_costs = np.fromfile(val_costs_path, dtype=np.float32)
    train_outcomes_np = np.fromfile(train_outcomes_path, dtype=np.uint8)
    val_outcomes_np = np.fromfile(val_outcomes_path, dtype=np.uint8)
    if train_costs.shape != (len(x_train),) or val_costs.shape != (len(x_val),):
        raise ValueError("step-cost vector shape differs from current_x")
    train_cache.validate_outcomes(train_outcomes_np)
    val_cache.validate_outcomes(val_outcomes_np)
    train_costs_t = torch.from_numpy(train_costs.copy()).to(device)
    val_costs_t = torch.from_numpy(val_costs.copy()).to(device)
    train_outcomes_t = torch.from_numpy(train_outcomes_np.copy()).to(device)
    val_outcomes_t = torch.from_numpy(val_outcomes_np.copy()).to(device)

    net = EfficiencyQNet(in_features=428).to(device)
    target_net = EfficiencyQNet(in_features=428).to(device)
    hard_update_target_net(target_net, net)
    optimizer = torch.optim.AdamW(
        net.parameters(), lr=lr, weight_decay=weight_decay, fused=True
    )
    history: list[dict[str, Any]] = []
    checkpoint_dir = Path(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    if progress_path is not None:
        _atomic_json(Path(progress_path), {"completed_blocks": 0, "history": history})

    for iteration in range(fqi_iterations):
        target_seconds = 0.0
        train_seconds = 0.0
        y_train: torch.Tensor | None = None
        y_val: torch.Tensor | None = None
        for segment_start in range(0, epochs_per_fqi, hard_target_refresh_epochs):
            segment_end = min(segment_start + hard_target_refresh_epochs, epochs_per_fqi)
            start_time = time.perf_counter()
            y_train = compute_targets_cuda_cached(
                train_cache,
                target_net,
                train_costs_t,
                train_outcomes_t,
                device,
                action_batch_size,
            )
            y_val = compute_targets_cuda_cached(
                val_cache,
                target_net,
                val_costs_t,
                val_outcomes_t,
                device,
                action_batch_size,
            )
            target_seconds += time.perf_counter() - start_time

            net.train()
            start_time = time.perf_counter()
            for _epoch in range(segment_start, segment_end):
                permutation = torch.randperm(len(x_train), device=device)
                for start in range(0, len(x_train), batch_size):
                    idx = permutation[start : start + batch_size]
                    prediction = net(x_train[idx])
                    loss = F.smooth_l1_loss(prediction, y_train[idx])
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                    optimizer.step()
            torch.cuda.synchronize(device)
            train_seconds += time.perf_counter() - start_time
            hard_update_target_net(target_net, net)

        assert y_train is not None and y_val is not None
        train_metrics = evaluate_metrics(net, x_train, y_train, device)
        val_metrics = evaluate_metrics(net, x_val, y_val, device)
        row = {
            "iteration": iteration + 1,
            "target_calc_sec": round(target_seconds, 3),
            "train_sec": round(train_seconds, 3),
            "train_huber": train_metrics["huber"],
            "val_huber": val_metrics["huber"],
            "val_mae": val_metrics["mae"],
            "val_q_min": val_metrics["q_min"],
            "val_q_median": val_metrics["q_median"],
            "val_q_p90": val_metrics["q_p90"],
            "val_q_max": val_metrics["q_max"],
            "val_q_mean": val_metrics["q_mean"],
        }
        history.append(row)
        print(
            f"GPU FQI {iteration + 1}/{fqi_iterations} "
            f"(targets {target_seconds:.2f}s, train {train_seconds:.2f}s): "
            f"val_huber={row['val_huber']:.4f}, val_mae={row['val_mae']:.3f}, "
            f"Q_med={row['val_q_median']:.2f}, "
            f"Q_range=[{row['val_q_min']:.2f}, {row['val_q_max']:.2f}]",
            flush=True,
        )

        if (iteration + 1) % checkpoint_every == 0 or iteration + 1 == fqi_iterations:
            checkpoint = checkpoint_dir / f"weights_iter{iteration + 1:03d}.json"
            _atomic_json(checkpoint, export_net_weights_dict(net))
        if progress_path is not None:
            _atomic_json(
                Path(progress_path),
                {"completed_blocks": iteration + 1, "history": history},
            )

    config = {
        "target_update": "hard",
        "hard_target_refresh_epochs": hard_target_refresh_epochs,
        "fqi_iterations": fqi_iterations,
        "epochs_per_fqi": epochs_per_fqi,
        "batch_size": batch_size,
        "action_batch_size": action_batch_size,
        "lr": lr,
        "weight_decay": weight_decay,
        "failure_penalty": FAILURE_PENALTY,
        "seed": seed,
        "device": str(device),
        "cuda_tf32": bool(torch.backends.cuda.matmul.allow_tf32),
        "optimizer_fused": True,
        "target_builder_runtime": "precomputed_split_cache_cuda",
    }
    report = {"history": history, "final_val": val_metrics, "config": config}
    return net, report
