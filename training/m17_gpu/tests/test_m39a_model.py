from pathlib import Path

import pytest
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.m39a_contract import load_plan, plan_hash
from splendor_gpu.m39a_model import (
    M39APolicyValue,
    build_initial_checkpoint,
    encode_decisions,
    initialize_new_heads,
    load_d2_actor,
)


PLAN_PATH = Path("benchmarks/m39a-arena-driven-policy-value-rl.plan.json")
FIXTURE = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")


def test_architecture_and_private_generator_initialization():
    torch.manual_seed(1)
    left = M39APolicyValue()
    initialize_new_heads(left)
    torch.manual_seed(999)
    right = M39APolicyValue()
    initialize_new_heads(right)
    assert sum(parameter.numel() for parameter in left.parameters()) == 953_669
    for name in (
        "value.0.weight",
        "value.0.bias",
        "value.2.weight",
        "value.2.bias",
        "auxiliary_score_head.weight",
        "auxiliary_score_head.bias",
    ):
        assert torch.equal(left.state_dict()[name], right.state_dict()[name])
    assert torch.count_nonzero(left.value[0].bias) == 0
    assert torch.count_nonzero(left.value[2].bias) == 0
    assert torch.count_nonzero(left.auxiliary_score_head.bias) == 0


def test_packed_forward_shapes_from_tracked_fixture():
    payload = __import__("json").loads(FIXTURE.read_text(encoding="utf-8"))
    frame = payload["frames"][0]
    catalog = load_catalog(FIXTURE)
    encoded = encode_decisions(
        [frame["player_view"]],
        [frame["legal_actions"]],
        catalog,
    )
    model = M39APolicyValue().eval()
    logits, values, auxiliary = model.forward_packed(**encoded)
    assert logits.shape == (len(frame["legal_actions"]),)
    assert values.shape == (1, 2)
    assert auxiliary.shape == (1,)
    assert torch.isfinite(logits).all()
    assert torch.isfinite(values).all()


def test_real_d2_actor_load_is_strict_when_local_checkpoint_exists():
    plan = load_plan(PLAN_PATH)
    base = Path(plan["initialization"]["checkpoint_path"])
    if not base.exists():
        pytest.skip("local D2-v2 checkpoint is intentionally not tracked")
    model, _ = load_d2_actor(base, plan["initialization"]["checkpoint_file_sha256"])
    raw = torch.load(base, map_location="cpu", weights_only=False)["state_dict"]
    for name, tensor in raw.items():
        if not name.startswith("value."):
            assert torch.equal(model.state_dict()[name], tensor)
    catalog = load_catalog(FIXTURE)
    initial = build_initial_checkpoint(
        base_checkpoint=base,
        expected_base_sha256=plan["initialization"]["checkpoint_file_sha256"],
        plan_hash=plan_hash(plan),
        catalog_hash=catalog_semantic_hash(catalog),
    )
    assert initial["metadata"]["cycle"] == 0
    assert initial["metadata"]["base_value_head_loaded"] is False
    assert len(initial["checkpoint_hash"]) == 64
