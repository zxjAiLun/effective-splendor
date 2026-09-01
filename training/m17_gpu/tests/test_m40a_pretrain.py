from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splendor_gpu.m40a_constants import (
    AUX_FAMILY_COEFFICIENT,
    PRETRAIN_BATCH,
    PRETRAIN_EPOCHS,
    PRETRAIN_LR,
    PRETRAIN_SHUFFLE_SEED,
)
from splendor_gpu.m40a_model import (
    M40AModel,
    copy_head_state,
    initialize_predictive_heads,
    load_head_state,
)
from splendor_gpu.m40a_pretrain import (
    _splitmix64_permutation,
    pretrain,
    sanity_metrics,
)


def _synthetic_record(game_index: int, seat: int, ply_index: int) -> dict:
    """A minimal record with the m40a_labels payload the enriched
    materializer emits. Prestige climbs to a self win."""
    window = ply_index + 10
    trajectory = []
    self_vp = 0
    opp_vp = 0
    for ply in range(ply_index, window):
        if ply % 2 == seat and ply > ply_index:
            self_vp = min(15, self_vp + 5)
        if ply % 2 == (1 - seat):
            opp_vp = min(15, opp_vp + 1)
        trajectory.append([self_vp, opp_vp])
    scores = [15, 3] if seat == 0 else [3, 15]
    centered = [1.0, -1.0] if seat == 0 else [-1.0, 1.0]
    return {
        "game_index": game_index,
        "seat": seat,
        "ply_index": ply_index,
        "result": {
            "scores": scores,
            "centered_returns": centered,
            "truncated": False,
        },
        "m40a_labels": {
            "prestige_after_ply": trajectory,
            "window_plies": window,
            "truncated": False,
        },
        # The forward path needs observation/legal_actions; the pretrain
        # smoke tests that touch the network use the real fixture records
        # instead. These synthetic records only exercise label handling.
        "observation": None,
        "legal_actions": None,
    }


def test_splitmix64_permutation_is_deterministic_and_complete() -> None:
    first = _splitmix64_permutation(100, (PRETRAIN_SHUFFLE_SEED << 8) ^ 1)
    second = _splitmix64_permutation(100, (PRETRAIN_SHUFFLE_SEED << 8) ^ 1)
    assert first == second
    assert sorted(first) == list(range(100))
    # Different epochs permute differently.
    other = _splitmix64_permutation(100, (PRETRAIN_SHUFFLE_SEED << 8) ^ 2)
    assert first != other


def test_pretrain_freezes_trunk_and_policy(tmp_path: Path) -> None:
    """Pretraining must only update the heads; trunk/policy stay frozen."""
    pytest.importorskip("splendor_gpu.data")
    import json

    fixture_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    frame = fixture["frames"][0]
    record = {
        "game_index": 0,
        "seat": 0,
        "ply_index": 0,
        "result": {
            "scores": [18, 0],
            "centered_returns": [1.0, -1.0],
            "truncated": False,
        },
        "m40a_labels": {
            "prestige_after_ply": [[0, 0], [2, 0], [2, 1], [4, 1]],
            "window_plies": 4,
            "truncated": False,
        },
        "observation": frame["player_view"],
        "legal_actions": frame["legal_actions"],
    }

    model = M40AModel()
    initialize_predictive_heads(model)
    trunk_before = {
        name: tensor.clone()
        for name, tensor in model.state_dict().items()
        if not name.startswith("heads.")
    }
    policy_before = model.policy.state_dict()

    model.to("cpu")
    report = pretrain(
        model=model,
        records=[record] * 8,
        device=torch.device("cpu"),
        report_path=tmp_path / "report.json",
    )
    assert report["epochs"] == PRETRAIN_EPOCHS

    trunk_after = {
        name: tensor
        for name, tensor in model.state_dict().items()
        if not name.startswith("heads.")
    }
    for name in trunk_before:
        assert torch.equal(trunk_before[name], trunk_after[name]), name
    for name in policy_before:
        assert torch.equal(policy_before[name], model.policy.state_dict()[name])


def test_arms_differ_only_after_pretraining(tmp_path: Path) -> None:
    """The A/B fork: identical copied head state; after B's pretraining
    (on data), B's heads differ from A's while trunks remain equal."""
    import json

    fixture_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    frame = fixture["frames"][0]
    record = {
        "game_index": 0,
        "seat": 0,
        "ply_index": 0,
        "result": {
            "scores": [18, 0],
            "centered_returns": [1.0, -1.0],
            "truncated": False,
        },
        "m40a_labels": {
            "prestige_after_ply": [[0, 0], [2, 0], [2, 1], [4, 1]],
            "window_plies": 4,
            "truncated": False,
        },
        "observation": frame["player_view"],
        "legal_actions": frame["legal_actions"],
    }

    import copy

    source = M40AModel()
    initialize_predictive_heads(source)
    state = copy_head_state(source)

    # The arms fork from ONE source: identical trunks (deep copy) and
    # identical heads (the copied state_dict).
    arm_a = copy.deepcopy(source)
    arm_b = copy.deepcopy(source)
    load_head_state(arm_a, state)
    load_head_state(arm_b, state)

    arm_b.train()  # pretrain mutates heads
    pretrain(
        model=arm_b,
        records=[record] * 16,
        device=torch.device("cpu"),
        report_path=tmp_path / "b-report.json",
    )

    # Trunks identical (untouched in both)
    for (name, a), (_, b) in zip(
        arm_a.state_dict().items(), arm_b.state_dict().items()
    ):
        if name.startswith("heads."):
            continue
        assert torch.equal(a, b), name
    # Heads differ (B was trained)
    differing = [
        name
        for (name, a), (_, b) in zip(
            arm_a.heads.state_dict().items(), arm_b.heads.state_dict().items()
        )
        if not torch.equal(a, b)
    ]
    assert differing, "B's pretraining must have changed at least one head"


def test_sanity_metrics_report_only_shape(tmp_path: Path) -> None:
    import json

    fixture_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    frame = fixture["frames"][0]
    record = {
        "game_index": 0,
        "seat": 0,
        "ply_index": 0,
        "result": {
            "scores": [18, 0],
            "centered_returns": [1.0, -1.0],
            "truncated": False,
        },
        "m40a_labels": {
            "prestige_after_ply": [[0, 0], [2, 0]],
            "window_plies": 2,
            "truncated": False,
        },
        "observation": frame["player_view"],
        "legal_actions": frame["legal_actions"],
    }
    model = M40AModel()
    initialize_predictive_heads(model)
    metrics = sanity_metrics(
        model=model,
        validation_records=[record] * 4,
        device=torch.device("cpu"),
    )
    assert metrics["validation_truncated_games"] == 0
    assert metrics["outcome_brier_multiclass"] is not None
    assert metrics["value_mse_completed"] is not None
    # The truncated column is N/A with 0 games
    assert metrics["value_mse_truncated"] == "N/A (0 validation games)"
