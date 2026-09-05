"""P0 Contract tests for M42A Model Architecture."""

from __future__ import annotations

import copy
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m35a_registry import load_and_validate_checkpoint
from splendor_gpu.m41a_train import M41AArm, M41AQHead
from splendor_gpu.m42a_model import (
    M42AModel,
    M42ARelationResidual,
    RELATION_INIT_SEED,
    create_m42a_paired_arms,
)

CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
RUN = Path("local-artifacts/m41a-run")


@pytest.fixture
def base_arm():
    catalog = load_catalog(CATALOG_PATH)
    d2_model, _ = load_and_validate_checkpoint(
        "M25-D2-v2", catalog_hash=catalog_semantic_hash(catalog),
        device=torch.device("cpu"),
    )
    ckpt = torch.load(RUN / "m41a-F-final.pt", map_location="cpu", weights_only=False)
    q_head = M41AQHead()
    q_head.load_state_dict(ckpt["q_head_state"])
    arm = M41AArm(d2_model, q_head, freeze_encoders=True)
    return arm.eval()


def test_parameter_counts_and_freeze(base_arm):
    """Assert X and R have identical param counts, base is frozen, residual is trainable."""
    arm_X, arm_R = create_m42a_paired_arms(base_arm)

    # Base parameters must be completely frozen
    for name, p in arm_R.base_arm.named_parameters():
        assert not p.requires_grad, f"base parameter {name} should be frozen"

    # Residual parameters must be trainable
    trainable_params_R = [p for p in arm_R.residual.parameters() if p.requires_grad]
    trainable_params_X = [p for p in arm_X.residual.parameters() if p.requires_grad]

    count_R = sum(p.numel() for p in trainable_params_R)
    count_X = sum(p.numel() for p in trainable_params_X)
    assert count_R == count_X == 277314


def test_bit_exact_initialization_equality(base_arm):
    """Assert B == X == R bit-exact before training."""
    arm_X, arm_R = create_m42a_paired_arms(base_arm)
    arm_X.eval()
    arm_R.eval()

    # Synthetic batch: 2 states, 5 total actions
    torch.manual_seed(12345)
    entities = torch.randn(2, 31, 32)
    mask = torch.ones(2, 31, dtype=torch.bool)
    mask[:, 28:] = False
    global_features = torch.randn(2, 40)
    actions = torch.randn(5, 59)
    offsets = torch.tensor([0, 3, 5], dtype=torch.long)
    relations = torch.randn(5, 31, 28)

    with torch.no_grad():
        q_B = base_arm.q_values(entities, mask, global_features, actions, offsets)
        q_X, q_base_X, q_res_X = arm_X(entities, mask, global_features, actions, offsets, relations)
        q_R, q_base_R, q_res_R = arm_R(entities, mask, global_features, actions, offsets, relations)

    # Residual must be exactly 0
    assert torch.equal(q_res_X, torch.zeros_like(q_res_X))
    assert torch.equal(q_res_R, torch.zeros_like(q_res_R))

    # Bit-exact equality across all three
    assert torch.equal(q_B, q_base_X)
    assert torch.equal(q_B, q_base_R)
    assert torch.equal(q_B, q_X)
    assert torch.equal(q_B, q_R)


def test_arm_x_relation_zeroing(base_arm):
    """Assert Arm X is invariant to input relations (always zeroes relations)."""
    arm_X, _ = create_m42a_paired_arms(base_arm)
    arm_X.eval()

    # Artificially modify final layer to make residual active
    arm_X.residual.residual_head[-1].weight.data.fill_(0.01)

    entities = torch.randn(1, 31, 32)
    mask = torch.ones(1, 31, dtype=torch.bool)
    global_features = torch.randn(1, 40)
    actions = torch.randn(3, 59)
    offsets = torch.tensor([0, 3], dtype=torch.long)

    rel_arbitrary = torch.randn(3, 31, 28)
    rel_zeros = torch.zeros(3, 31, 28)

    with torch.no_grad():
        q_arb = arm_X.q_values(entities, mask, global_features, actions, offsets, rel_arbitrary)
        q_zero = arm_X.q_values(entities, mask, global_features, actions, offsets, rel_zeros)

    assert torch.equal(q_arb, q_zero)
