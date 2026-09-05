"""P0 Contract tests for M43A Successor Value Model Architecture."""

from __future__ import annotations

from pathlib import Path
import pytest
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m43a_successor_model import (
    M43ASuccessorValueModel,
    M43AValueHead,
    VALUE_HEAD_INIT_SEED,
    build_m43a_model,
)

CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")


@pytest.fixture
def d2_model():
    catalog = load_catalog(CATALOG_PATH)
    model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    return model


def test_d2_initialization_audit(d2_model):
    """P0 Section 12: Audit D2 initialization, assert zero old value/policy tensors imported."""
    model, audit = build_m43a_model(d2_model)

    assert audit["assert_zero_old_value_imported"] is True
    assert audit["assert_zero_policy_action_imported"] is True
    assert audit["imported_encoder_tensor_count"] == 38
    assert audit["excluded_old_d2_value_tensor_count"] == 4

    # Model parameters check: all should be requires_grad=True
    for name, p in model.named_parameters():
        assert p.requires_grad, f"Parameter {name} should be trainable"
        assert not name.startswith("policy"), f"Policy parameter leaked: {name}"
        assert not name.startswith("action_encoder"), f"Action encoder parameter leaked: {name}"

    # Verify encoder parameters match D2 bit-exact
    d2_sd = d2_model.state_dict()
    model_sd = model.state_dict()
    for k in ["entity_encoder.0.weight", "mix.weight", "blocks.0.body.0.weight", "norm.weight"]:
        assert torch.equal(model_sd[k], d2_sd[k]), f"Encoder tensor {k} should match D2 bit-exact"


def test_value_head_seed_and_bounds(d2_model):
    """Verify value head seed determinism and Sigmoid bounds."""
    model1, audit1 = build_m43a_model(d2_model)
    model2, audit2 = build_m43a_model(d2_model)

    assert audit1["fresh_value_head_semantic_sha256"] == audit2["fresh_value_head_semantic_sha256"]

    # Test forward pass bounds
    torch.manual_seed(999)
    entities = torch.randn(4, 31, 32)
    mask = torch.ones(4, 31, dtype=torch.bool)
    mask[:, 28:] = False
    global_features = torch.randn(4, 40)

    out = model1(entities, mask, global_features)
    assert out.shape == (4,)
    assert torch.all(out > 0.0)
    assert torch.all(out < 1.0)
