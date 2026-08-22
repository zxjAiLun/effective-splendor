"""Targeted unit tests verifying exact numerical equivalence and safety controls for M28B compute repair."""

import time
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from splendor_gpu.encoding import ACTION_FEATURES, ENTITY_FEATURES, GLOBAL_FEATURES
from splendor_gpu.model import ContextualInteractionBlock, ModelSpec, build_model
from splendor_gpu.self_play_train import collate, evaluate, packed_policy_loss, policy_loss
from splendor_gpu.encoded_cache import collate_packed
from splendor_gpu.interaction_train import (
    BackgroundThermalGuard,
    ThermalSafetyAbort,
    ThermalTelemetryUnavailable,
    require_fail_closed_cooldown,
)
from torch.utils.data import DataLoader


def test_factored_pair_scorer_exact_equivalence():
    torch.manual_seed(42)
    B, N, H = 4, 31, 192

    block = ContextualInteractionBlock(H, dropout=0.0)
    entities = torch.randn(B, N, H, requires_grad=True)
    mask = torch.rand(B, N) > 0.3
    global_ctx = torch.randn(B, H, requires_grad=True)

    normalized = block.norm(entities)
    queries = block.query(normalized)
    keys = block.key(normalized)
    values = block.value(normalized)

    pair_features = torch.cat(
        (
            queries.unsqueeze(2).expand(-1, -1, entities.shape[1], -1),
            keys.unsqueeze(1).expand(-1, entities.shape[1], -1, -1),
            queries.unsqueeze(2) * keys.unsqueeze(1),
        ),
        dim=-1,
    )
    ref_interaction = torch.sigmoid(block.pair(pair_features).squeeze(-1))

    out, ctx = block(entities, mask, global_ctx)

    w = block.pair[0].weight
    b = block.pair[0].bias
    proj_q = F.linear(queries, w[:, 0:H])
    proj_k = F.linear(keys, w[:, H : 2 * H])
    proj_p = F.linear(queries.unsqueeze(2) * keys.unsqueeze(1), w[:, 2 * H : 3 * H], b)
    h_pair = proj_q.unsqueeze(2) + proj_k.unsqueeze(1) + proj_p
    factored_interaction = torch.sigmoid(block.pair[2](block.pair[1](h_pair)).squeeze(-1))

    assert torch.allclose(ref_interaction, factored_interaction, atol=1e-6)

    loss = out.sum() + ctx.sum()
    loss.backward()
    assert entities.grad is not None
    assert global_ctx.grad is not None


def test_packed_vs_padded_policy_loss_and_gradients():
    torch.manual_seed(100)
    B = 4
    counts = [5, 23, 11, 40]
    total_actions = sum(counts)
    offsets = torch.zeros(B + 1, dtype=torch.int64)
    offsets[1:] = torch.tensor(counts, dtype=torch.int64).cumsum(dim=0)

    max_c = max(counts)
    padded_logits = torch.randn(B, max_c, requires_grad=True)
    padded_targets = torch.zeros(B, max_c)
    padded_mask = torch.zeros(B, max_c, dtype=torch.bool)
    
    packed_logits_data = []
    packed_targets_data = []

    for i, c in enumerate(counts):
        t = F.softmax(torch.randn(c), dim=-1)
        padded_targets[i, :c] = t
        padded_mask[i, :c] = True
        packed_targets_data.append(t)
        packed_logits_data.append(padded_logits[i, :c])

    packed_targets = torch.cat(packed_targets_data, dim=0)
    packed_logits = torch.cat(packed_logits_data, dim=0).detach().clone().requires_grad_(True)

    padded_masked_logits = padded_logits.masked_fill(~padded_mask, -1e9)
    loss_padded = policy_loss(padded_masked_logits, padded_targets)
    loss_packed = packed_policy_loss(packed_logits, packed_targets, offsets)

    assert torch.allclose(loss_padded, loss_packed, atol=1e-6)

    loss_padded.backward()
    loss_packed.backward()

    padded_grads_flat = []
    for i, c in enumerate(counts):
        padded_grads_flat.append(padded_logits.grad[i, :c])
    padded_grads_flat = torch.cat(padded_grads_flat, dim=0)

    assert torch.allclose(padded_grads_flat, packed_logits.grad, atol=1e-6)


def test_evaluate_packed_and_padded_exact_agreement():
    torch.manual_seed(200)
    spec = ModelSpec("contextual_entity_mixer", 192, 4, 0.0, 2)
    model = build_model(spec)
    model.eval()

    samples = []
    for i in range(16):
        k = torch.randint(5, 50, (1,)).item()
        samples.append({
            "entities": torch.randn(31, ENTITY_FEATURES),
            "entity_mask": torch.rand(31) > 0.2,
            "global_features": torch.randn(GLOBAL_FEATURES),
            "actions": torch.randn(k, ACTION_FEATURES),
            "policy_target": torch.softmax(torch.randn(k), dim=-1),
            "value_target": torch.softmax(torch.randn(2), dim=-1),
        })

    padded_loader = DataLoader(samples, batch_size=4, shuffle=False, collate_fn=collate)
    packed_loader = DataLoader(samples, batch_size=4, shuffle=False, collate_fn=collate_packed)

    metrics_padded = evaluate(model, padded_loader, torch.device("cpu"))
    metrics_packed = evaluate(model, packed_loader, torch.device("cpu"))

    for k in metrics_padded:
        assert metrics_padded[k] == pytest.approx(metrics_packed[k], abs=1e-5)


def test_evaluate_respects_abort_check():
    spec = ModelSpec("contextual_entity_mixer", 192, 4, 0.0, 2)
    model = build_model(spec)
    model.eval()

    samples = [{
        "entities": torch.randn(31, ENTITY_FEATURES),
        "entity_mask": torch.rand(31) > 0.2,
        "global_features": torch.randn(GLOBAL_FEATURES),
        "actions": torch.randn(10, ACTION_FEATURES),
        "policy_target": torch.softmax(torch.randn(10), dim=-1),
        "value_target": torch.softmax(torch.randn(2), dim=-1),
    } for _ in range(8)]
    loader = DataLoader(samples, batch_size=2, shuffle=False, collate_fn=collate_packed)

    calls = [0]
    def failing_check():
        calls[0] += 1
        if calls[0] >= 2:
            raise RuntimeError("evaluation aborted by thermal check")

    with pytest.raises(RuntimeError, match="evaluation aborted by thermal check"):
        evaluate(model, loader, torch.device("cpu"), abort_check=failing_check)
    assert calls[0] == 2


def test_thermal_guard_synchronous_startup_rejection(monkeypatch):
    readings = [{"source": "test", "label": "TCPU", "celsius": 89.0}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings)
    guard = BackgroundThermalGuard(limit_c=85.0, interval_s=0.01)
    with pytest.raises(ThermalSafetyAbort, match="host thermal safety abort at guard_startup"):
        guard.start()


def test_thermal_guard_fail_closed_on_missing_sensors(monkeypatch):
    # Pass startup
    state = {"readings": [{"source": "test", "label": "TCPU", "celsius": 50.0}]}
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: state["readings"])
    guard = BackgroundThermalGuard(limit_c=85.0, interval_s=0.01)
    guard.start()

    # Drop sensors during loop
    state["readings"] = []
    time.sleep(0.05)
    with pytest.raises(ThermalTelemetryUnavailable, match="no .*thermal sensor available"):
        guard.check()
    guard.stop()


def test_thermal_guard_aborts_at_or_above_limit(monkeypatch):
    # Pass startup
    state = {"readings": [{"source": "test", "label": "TCPU", "celsius": 50.0}]}
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: state["readings"])
    guard = BackgroundThermalGuard(limit_c=85.0, interval_s=0.01)
    guard.start()

    # Temperature spike during loop
    state["readings"] = [{"source": "test", "label": "TCPU", "celsius": 85.0}]
    time.sleep(0.05)
    with pytest.raises(ThermalSafetyAbort, match="training_loop"):
        guard.check()
    guard.stop()


def test_cooldown_fail_closed_on_timeout(monkeypatch):
    readings = [{"source": "test", "label": "TCPU", "celsius": 70.0}]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: readings)
    with pytest.raises(ThermalSafetyAbort, match="cooldown_timeout"):
        require_fail_closed_cooldown(target_c=65.0, timeout_s=0.01)


def test_cooldown_fail_closed_on_missing_sensors(monkeypatch):
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: [])
    with pytest.raises(ThermalTelemetryUnavailable):
        require_fail_closed_cooldown(target_c=65.0, timeout_s=0.01)
