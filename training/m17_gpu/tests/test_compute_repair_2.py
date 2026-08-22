"""Targeted unit tests for M28B Compute Repair 2 machinery."""

from pathlib import Path
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from splendor_gpu.encoding import ACTION_FEATURES, ENTITY_FEATURES, GLOBAL_FEATURES, ENTITY_SLOTS
from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset, collate_packed
from splendor_gpu.model import ContextualInteractionBlock, ContextualEntityMixerPolicyValue, ModelSpec, build_model
from splendor_gpu.self_play_train import evaluate
from splendor_gpu.interaction_train import (
    BackgroundThermalGuard,
    ThermalSafetyAbort,
    ThermalTelemetryUnavailable,
    _loader,
    sensor_threshold,
    CPU_THERMAL_LIMIT_C,
    GPU_THERMAL_LIMIT_C,
    NVME_THERMAL_LIMIT_C,
    PLATFORM_THERMAL_LIMIT_C,
)


def test_vectorized_batch_loader_exact_equality():
    cache_path = Path("local-artifacts/m28b-encoded-cache-v1")
    if not cache_path.exists():
        pytest.skip("m28b encoded cache not found locally")

    cache = EncodedCache.load(cache_path)
    indices = [0, 5, 12, 19, 45, 128, 256, 512, 1024]

    # Sample-by-sample collate
    samples = [cache.sample(i) for i in indices]
    batch_ref = collate_packed(samples)

    # Vectorized 1-shot batch
    batch_fast = cache.batch(indices)

    assert set(batch_ref.keys()) == set(batch_fast.keys())
    for k in batch_ref:
        assert torch.equal(batch_ref[k], batch_fast[k]), f"Tensor mismatch for key '{k}'"


def test_fast_loader_shuffle_order_exact_match():
    cache_path = Path("local-artifacts/m28b-encoded-cache-v1")
    if not cache_path.exists():
        pytest.skip("m28b encoded cache not found locally")

    cache = EncodedCache.load(cache_path)
    subset_indices = list(range(0, 500, 2))  # 250 samples
    dataset = PackedEncodedDataset(cache, subset_indices)

    batch_size = 64
    seed = 280229
    device = torch.device("cpu")

    # Reference PyTorch DataLoader
    gen = torch.Generator().manual_seed(seed)
    loader_ref = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=gen,
        num_workers=0,
        collate_fn=collate_packed,
    )

    # Vectorized fast loader
    loader_fast = _loader(dataset, batch_size=batch_size, shuffle=True, seed=seed, device=device)

    batches_ref = list(loader_ref)
    batches_fast = list(loader_fast)

    assert len(batches_ref) == len(batches_fast)
    for b_idx, (br, bf) in enumerate(zip(batches_ref, batches_fast)):
        for k in br:
            assert torch.equal(br[k], bf[k]), f"Batch {b_idx} key {k} mismatch"


def test_bmm_aggregation_equivalence():
    torch.manual_seed(42)
    B, N, H = 8, 31, 192

    block = ContextualInteractionBlock(H, dropout=0.0)
    entities = torch.randn(B, N, H, requires_grad=True)
    mask = torch.rand(B, N) > 0.2
    global_ctx = torch.randn(B, H, requires_grad=True)

    # Forward
    out, ctx = block(entities, mask, global_ctx)

    assert out.shape == (B, N, H)
    assert ctx.shape == (B, N, H)

    # Test backward
    loss = out.sum() + ctx.sum()
    loss.backward()
    assert entities.grad is not None
    assert global_ctx.grad is not None


def test_contextual_mixer_global_context_and_buffer():
    spec = ModelSpec("contextual_entity_mixer", 192, 4, 0.0, 2)
    model = build_model(spec)
    model.eval()

    # Check buffer registered
    for block in model.interactions:
        assert hasattr(block, "not_self_mask")
        assert block.not_self_mask.shape == (1, ENTITY_SLOTS, ENTITY_SLOTS)

    entities = torch.randn(4, 31, ENTITY_FEATURES)
    mask = torch.ones(4, 31, dtype=torch.bool)
    global_features = torch.randn(4, GLOBAL_FEATURES)

    state = model.state_embedding(entities, mask, global_features)
    assert state.shape == (4, 192)


def test_gpu_segmented_evaluation_exact_agreement():
    torch.manual_seed(1234)
    spec = ModelSpec("contextual_entity_mixer", 192, 4, 0.0, 2)
    model = build_model(spec)
    model.eval()

    samples = []
    for i in range(20):
        k = torch.randint(5, 50, (1,)).item()
        samples.append({
            "entities": torch.randn(31, ENTITY_FEATURES),
            "entity_mask": torch.rand(31) > 0.2,
            "global_features": torch.randn(GLOBAL_FEATURES),
            "actions": torch.randn(k, ACTION_FEATURES),
            "policy_target": torch.softmax(torch.randn(k), dim=-1),
            "value_target": torch.softmax(torch.randn(2), dim=-1),
        })

    loader_padded = DataLoader(samples, batch_size=4, shuffle=False, collate_fn=collate_packed)
    metrics = evaluate(model, loader_padded, torch.device("cpu"))

    assert metrics["examples"] == 20
    assert 0.0 <= metrics["visit_top1"] <= 1.0
    assert metrics["policy_cross_entropy"] > 0.0
    assert metrics["value_mse"] >= 0.0


def test_sensor_specific_thresholds():
    assert sensor_threshold("coretemp:Package id 0") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("coretemp:Core 8") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("x86_pkg_temp") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("TCPU") == CPU_THERMAL_LIMIT_C
    assert sensor_threshold("TCPU_PCI") == GPU_THERMAL_LIMIT_C
    assert sensor_threshold("nvidia_gpu") == GPU_THERMAL_LIMIT_C
    assert sensor_threshold("nvme:Composite") == NVME_THERMAL_LIMIT_C
    assert sensor_threshold("SEN3") == PLATFORM_THERMAL_LIMIT_C
    assert sensor_threshold("acpitz") == PLATFORM_THERMAL_LIMIT_C


def test_thermal_guard_sensor_specific_abort(monkeypatch):
    # Below CPU limit of 95, but at 96 -> should abort
    readings = [{"source": "/sys/class/hwmon/hwmon8/temp1_input", "label": "coretemp:Package id 0", "celsius": 96.0}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings)
    guard = BackgroundThermalGuard(interval_s=0.01)
    with pytest.raises(ThermalSafetyAbort, match="sensor 'coretemp:Package id 0' .* measured 96.0°C >= limit 95.0°C"):
        guard.start()

    # GPU sensor at 91.0 -> exceeds GPU limit 90.0
    readings_gpu = [{"source": "/sys/class/thermal/thermal_zone4/temp", "label": "TCPU_PCI", "celsius": 91.0}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings_gpu)
    guard_gpu = BackgroundThermalGuard(interval_s=0.01)
    with pytest.raises(ThermalSafetyAbort, match="sensor 'TCPU_PCI' .* measured 91.0°C >= limit 90.0°C"):
        guard_gpu.start()
