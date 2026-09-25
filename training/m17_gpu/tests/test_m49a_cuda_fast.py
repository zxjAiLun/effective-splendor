"""CUDA tests for cached successor features and the fast FQI update path."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from splendor_gpu.m49a_cuda_trainer import (
    SuccessorFeatureCache,
    compute_targets_cuda_cached,
    train_fqi_cuda_cached,
)
from splendor_gpu.m49a_trainer import EfficiencyQNet

pytestmark = pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA device required")


def _write_cache(directory, prefixes: np.ndarray, suffixes: np.ndarray, counts: list[int]):
    directory.mkdir(parents=True)
    prefixes.astype("<f4").tofile(directory / "next_obs_prefix.f32")
    suffixes.astype("<f4").tofile(directory / "next_action_suffix.f32")
    offsets = np.concatenate(([0], np.cumsum(counts))).astype("<u8")
    offsets.tofile(directory / "action_offsets.u64")
    return SuccessorFeatureCache(directory, len(counts))


def test_cuda_cached_targets_match_full_batch_mlp_and_terminal_rules(tmp_path):
    torch.manual_seed(1234)
    rng = np.random.default_rng(1234)
    n = 4
    counts = [0, 0, 2, 1]
    prefixes = rng.normal(size=(n, 368)).astype(np.float32)
    suffixes = rng.normal(size=(sum(counts), 60)).astype(np.float32)
    cache = _write_cache(tmp_path / "cache", prefixes, suffixes, counts)
    outcomes_np = np.array([0, 1, 2, 2], dtype=np.uint8)
    cache.validate_outcomes(outcomes_np)

    device = torch.device("cuda:0")
    model = EfficiencyQNet().to(device).eval()
    costs = torch.tensor([1.0, 1.0, 1.0, 0.0], device=device)
    outcomes = torch.as_tensor(outcomes_np, device=device)
    previous_tf32 = torch.backends.cuda.matmul.allow_tf32
    torch.backends.cuda.matmul.allow_tf32 = False
    try:
        actual = compute_targets_cuda_cached(
            cache, model, costs, outcomes, device, action_batch_size=2
        )
        parent_ids = torch.repeat_interleave(
            torch.arange(n, device=device), torch.tensor(counts, device=device)
        )
        prefix_t = torch.as_tensor(prefixes, device=device)
        suffix_t = torch.as_tensor(suffixes, device=device)
        full_x = torch.cat((prefix_t[parent_ids], suffix_t), dim=1)
        q = model(full_x)
        min_next = torch.segment_reduce(
            q, reduce="min", lengths=torch.tensor(counts, dtype=torch.int64, device=device)
        )
        expected_v = torch.where(
            outcomes == 0,
            torch.zeros_like(costs),
            torch.where(outcomes == 1, torch.full_like(costs, 100.0), min_next),
        )
        expected = costs + expected_v
        assert torch.allclose(actual, expected, rtol=1e-5, atol=1e-5)
        assert actual[0].item() == 1.0
        assert actual[1].item() == 101.0
    finally:
        torch.backends.cuda.matmul.allow_tf32 = previous_tf32


def test_cuda_fqi_smoke_writes_online_checkpoint(tmp_path):
    rng = np.random.default_rng(17)
    train_n, val_n = 12, 5
    train_x = rng.normal(size=(train_n, 428)).astype(np.float32)
    val_x = rng.normal(size=(val_n, 428)).astype(np.float32)
    train_x_path, val_x_path = tmp_path / "train_x.f32", tmp_path / "val_x.f32"
    train_x.tofile(train_x_path)
    val_x.tofile(val_x_path)
    train_costs_path, val_costs_path = tmp_path / "train_costs.f32", tmp_path / "val_costs.f32"
    np.ones(train_n, dtype=np.float32).tofile(train_costs_path)
    np.ones(val_n, dtype=np.float32).tofile(val_costs_path)
    train_outcomes_path = tmp_path / "train_outcomes.u8"
    val_outcomes_path = tmp_path / "val_outcomes.u8"
    np.full(train_n, 2, dtype=np.uint8).tofile(train_outcomes_path)
    np.full(val_n, 2, dtype=np.uint8).tofile(val_outcomes_path)
    train_cache = _write_cache(
        tmp_path / "train_cache",
        rng.normal(size=(train_n, 368)).astype(np.float32),
        rng.normal(size=(train_n * 2, 60)).astype(np.float32),
        [2] * train_n,
    )
    val_cache = _write_cache(
        tmp_path / "val_cache",
        rng.normal(size=(val_n, 368)).astype(np.float32),
        rng.normal(size=(val_n * 2, 60)).astype(np.float32),
        [2] * val_n,
    )

    checkpoint_dir = tmp_path / "checkpoints"
    model, report = train_fqi_cuda_cached(
        train_x_path=train_x_path,
        train_cache=train_cache,
        train_costs_path=train_costs_path,
        train_outcomes_path=train_outcomes_path,
        val_x_path=val_x_path,
        val_cache=val_cache,
        val_costs_path=val_costs_path,
        val_outcomes_path=val_outcomes_path,
        device=torch.device("cuda:0"),
        fqi_iterations=1,
        epochs_per_fqi=2,
        hard_target_refresh_epochs=1,
        batch_size=4,
        action_batch_size=8,
        lr=1e-3,
        weight_decay=1e-4,
        seed=91,
        checkpoint_dir=checkpoint_dir,
        checkpoint_every=1,
        progress_path=tmp_path / "progress.json",
    )
    assert len(report["history"]) == 1
    assert report["config"]["device"] == "cuda:0"
    assert (checkpoint_dir / "weights_iter001.json").is_file()
    assert model(torch.from_numpy(train_x[:2]).to("cuda:0")).shape == (2,)
    assert (tmp_path / "progress.json").is_file()
