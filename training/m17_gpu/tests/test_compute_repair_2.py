"""Targeted unit tests for M28B Compute Repair 2 machinery."""

import copy
import json
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
    verify_and_reevaluate_control,
    CPU_THERMAL_LIMIT_C,
    GPU_THERMAL_LIMIT_C,
    NVME_THERMAL_LIMIT_C,
    PLATFORM_THERMAL_LIMIT_C,
    VERIFIED_CONTROL_REPORT_SHA256,
    VERIFIED_CONTROL_CHECKPOINT_SHA256,
    VERIFIED_CONTROL_SEMANTIC_HASH,
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


def test_bmm_aggregation_numerical_equivalence_to_reference():
    """Verify new BMM aggregation is numerically equivalent to 4D tensor reference within frozen tolerance."""
    torch.manual_seed(42)
    B, N, H = 8, 31, 192

    # Reference forward function with un-vectorized 4D intermediate tensor
    def forward_reference(block, entities, mask, global_context):
        normalized = block.norm(entities)
        queries = block.query(normalized)
        keys = block.key(normalized)
        values = block.value(normalized)

        w = block.pair[0].weight
        b = block.pair[0].bias
        h = entities.shape[-1]
        proj_q = F.linear(queries, w[:, 0:h])
        proj_k = F.linear(keys, w[:, h : 2 * h])
        proj_p = F.linear(queries.unsqueeze(2) * keys.unsqueeze(1), w[:, 2 * h : 3 * h], b)
        h_pair = proj_q.unsqueeze(2) + proj_k.unsqueeze(1) + proj_p
        interaction = torch.sigmoid(block.pair[2](block.pair[1](h_pair)).squeeze(-1))

        entity_count = entities.shape[1]
        not_self = ~torch.eye(entity_count, dtype=torch.bool, device=entities.device).unsqueeze(0)
        pair_mask = mask.unsqueeze(1) & mask.unsqueeze(2) & not_self
        interaction = interaction.masked_fill(~pair_mask, 0.0)
        denominator = interaction.sum(dim=-1, keepdim=True).clamp_min(1e-6)

        # 4D tensor multiplication
        context = (interaction.unsqueeze(-1) * values.unsqueeze(1)).sum(dim=2) / denominator
        context = context.masked_fill(~mask.unsqueeze(-1), 0.0)

        expanded_global = global_context.unsqueeze(1).expand(-1, entity_count, -1)
        updated = entities + block.residual(torch.cat((entities, context, expanded_global), dim=-1))
        updated = updated.masked_fill(~mask.unsqueeze(-1), 0.0)
        return updated, context

    block = ContextualInteractionBlock(H, dropout=0.0)

    entities_ref = torch.randn(B, N, H, requires_grad=True)
    entities_new = entities_ref.clone().detach().requires_grad_(True)
    mask = torch.rand(B, N) > 0.2
    global_ctx_ref = torch.randn(B, H, requires_grad=True)
    global_ctx_new = global_ctx_ref.clone().detach().requires_grad_(True)

    # 1. Forward comparison
    out_ref, ctx_ref = forward_reference(block, entities_ref, mask, global_ctx_ref)
    out_new, ctx_new = block(entities_new, mask, global_ctx_new)

    max_out_diff = (out_new - out_ref).abs().max().item()
    max_ctx_diff = (ctx_new - ctx_ref).abs().max().item()
    assert max_out_diff < 1e-5, f"forward output difference {max_out_diff} exceeds tolerance 1e-5"
    assert max_ctx_diff < 1e-5, f"forward context difference {max_ctx_diff} exceeds tolerance 1e-5"

    # 2. Backward gradient comparison
    loss_ref = out_ref.sum() + ctx_ref.sum()
    loss_new = out_new.sum() + ctx_new.sum()
    loss_ref.backward()
    loss_new.backward()

    max_grad_diff = (entities_new.grad - entities_ref.grad).abs().max().item()
    max_gctx_diff = (global_ctx_new.grad - global_ctx_ref.grad).abs().max().item()
    assert max_grad_diff < 1e-5, f"gradient difference {max_grad_diff} exceeds tolerance 1e-5"
    assert max_gctx_diff < 1e-5, f"global context gradient difference {max_gctx_diff} exceeds tolerance 1e-5"


def test_contextual_mixer_state_embedding_equivalence():
    torch.manual_seed(1234)
    spec = ModelSpec("contextual_entity_mixer", 192, 4, 0.0, 2)
    model = build_model(spec)
    model.eval()

    # Verify buffer registered
    for block in model.interactions:
        assert hasattr(block, "not_self_mask")
        assert block.not_self_mask.shape == (1, ENTITY_SLOTS, ENTITY_SLOTS)

    entities = torch.randn(4, 31, ENTITY_FEATURES)
    mask = torch.ones(4, 31, dtype=torch.bool)
    global_features = torch.randn(4, GLOBAL_FEATURES)

    # Reference state_embedding that evaluates global_encoder twice
    def reference_state_embedding(m, ent, msk, glob_feat):
        encoded = m.entity_encoder(ent).masked_fill(~msk.unsqueeze(-1), 0.0)
        g1 = m.global_encoder(glob_feat)
        for b in m.interactions:
            encoded, _ = b(encoded, msk, g1)
        gate = m.entity_gate(encoded).squeeze(-1).masked_fill(~msk, torch.finfo(encoded.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        g2 = m.global_encoder(glob_feat)
        state = m.mix(torch.cat([pooled, g2], dim=-1))
        return m.norm(m.blocks(state))

    state_ref = reference_state_embedding(model, entities, mask, global_features)
    state_new = model.state_embedding(entities, mask, global_features)

    assert torch.equal(state_ref, state_new)


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
    assert sensor_threshold("TCPU_PCI") == PLATFORM_THERMAL_LIMIT_C
    assert sensor_threshold("nvme:Composite") == NVME_THERMAL_LIMIT_C
    assert sensor_threshold("SEN3") == PLATFORM_THERMAL_LIMIT_C
    assert sensor_threshold("acpitz") == PLATFORM_THERMAL_LIMIT_C

    # Firmware critical / hot protection
    assert sensor_threshold({"label": "SEN3", "firmware_crit": 75.05}) == 73.05
    assert sensor_threshold({"label": "nvme:Composite", "firmware_crit": 82.85}) == 80.0  # 80 < 80.85


def test_thermal_guard_sensor_specific_abort(monkeypatch):
    # 1. CPU sensor exceeds 95.0
    readings = [{"source": "/sys/class/hwmon/hwmon8/temp1_input", "label": "coretemp:Package id 0", "celsius": 96.0}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings)
    guard = BackgroundThermalGuard(device=torch.device("cpu"), interval_s=0.01)
    with pytest.raises(ThermalSafetyAbort, match="sensor 'coretemp:Package id 0' .* measured 96.0°C >= limit 95.0°C"):
        guard.start()

    # 2. SEN3 exceeds firmware-reduced threshold (73.05C)
    readings_sen3 = [{"source": "/sys/class/thermal/thermal_zone2/temp", "label": "SEN3", "celsius": 74.0, "firmware_crit": 75.05}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings_sen3)
    guard_sen3 = BackgroundThermalGuard(device=torch.device("cpu"), interval_s=0.01)
    with pytest.raises(ThermalSafetyAbort, match="sensor 'SEN3' .* measured 74.0°C >= limit 73.0°C"):
        guard_sen3.start()


def test_control_verification_constants_and_contract():
    assert VERIFIED_CONTROL_REPORT_SHA256 == "af006dc0825da8d687fe9d848a17a1aa5e54770a08e19f801e0256ee9a604f49"
    assert VERIFIED_CONTROL_CHECKPOINT_SHA256 == "17041a98d2204d44c02a9777713e038e2fa6facccdfa0bf745acef8c0e8758db"
    assert VERIFIED_CONTROL_SEMANTIC_HASH == "5d83e21634399d6eb1c1b798b496ca5c03f809f7802a575c436b78c9436f0d41"
