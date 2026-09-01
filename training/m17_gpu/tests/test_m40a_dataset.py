from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splendor_gpu.m40a_constants import (
    ANCHOR_CRITICAL_DF63,
    AUX_FAMILY_COEFFICIENT,
    AUX_COEFFICIENT_BUDGET,
    COMPLETED_GAMES,
    DESIGN_SHA,
    H1_CRITICAL_DF127,
    LEAGUE_CRITICAL_DF31,
    LR_WAYPOINTS,
    PRETRAIN_EPOCHS,
    PRETRAIN_LR,
    SPLIT_STRIDE,
    TIMING_HORIZONS,
    TRAINING_COMPLETED_GAMES,
    TRAINING_TOTAL_GAMES,
    TRAINING_TRUNCATED_GAMES,
    VALIDATION_COMPLETED_GAMES,
    VP_MAX,
)
from splendor_gpu.m40a_dataset import (
    LabelError,
    _bankers_round,
    final_vp_labels,
    frozen_split,
    outcome_label,
    split_manifest_hash,
    timing_labels,
    value_target,
    vp_difference_label,
)
from splendor_gpu.m40a_model import (
    M40AModel,
    copy_head_state,
    initialize_predictive_heads,
    load_head_state,
    normalized_vp_difference,
    outcome_value,
)


# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------


def test_frozen_constants_match_design() -> None:
    assert DESIGN_SHA == "09fd8ec"
    assert PRETRAIN_LR == 3e-4
    assert PRETRAIN_EPOCHS == 16
    assert TIMING_HORIZONS == (2, 4, 8)
    assert VP_MAX == 30
    assert SPLIT_STRIDE == 5
    assert abs(AUX_FAMILY_COEFFICIENT - 1.0 / 12.0) < 1e-12
    assert abs(AUX_FAMILY_COEFFICIENT * 3 - AUX_COEFFICIENT_BUDGET) < 1e-12
    assert LR_WAYPOINTS == [1.0e-04, 7.75e-05, 3.25e-05, 1.0e-05]


def test_frozen_statistical_constants_scipy() -> None:
    scipy = pytest.importorskip("scipy.stats")
    assert format(scipy.t.ppf(0.95, 127), ".12f") == "1.656940343542"
    assert format(scipy.t.ppf(0.95, 31), ".12f") == "1.695518782546"
    assert format(scipy.t.ppf(0.975, 63), ".12f") == "1.998340542521"
    assert H1_CRITICAL_DF127 == 1.656940343542
    assert LEAGUE_CRITICAL_DF31 == 1.695518782546
    assert ANCHOR_CRITICAL_DF63 == 1.998340542521


# ---------------------------------------------------------------------------
# Label derivation (synthetic records)
# ---------------------------------------------------------------------------


def _record(
    *,
    game_index: int = 0,
    seat: int = 0,
    ply_index: int = 0,
    scores: list[int] | None = None,
    truncated: bool = False,
    centered: list[float] | None = None,
    prestige_after_ply: list[list[int]] | None = None,
    window_plies: int | None = None,
    ranks: list[int] | None = None,
) -> dict:
    if scores is None:
        scores = [15, 10]
    if centered is None:
        # Centered returns are the AUTHORITATIVE outcome (rank-based in
        # the referee); equal scores with a rank tiebreak are NOT a draw.
        if ranks is None:
            # Default: the higher score wins the rank (synthetic games
            # have no tiebreak); equal scores default to an equal rank.
            if scores[0] > scores[1]:
                ranks = [0, 1]
            elif scores[0] < scores[1]:
                ranks = [1, 0]
            else:
                ranks = [0, 0]
        if ranks[0] < ranks[1]:
            centered = [1.0, -1.0]
        elif ranks[0] > ranks[1]:
            centered = [-1.0, 1.0]
        else:
            centered = [0.0, 0.0]
    if ranks is None:
        ranks = [0, 1] if centered[0] > 0 else ([1, 0] if centered[0] < 0 else [0, 0])
    if prestige_after_ply is None:
        prestige_after_ply = []
    if window_plies is None:
        window_plies = ply_index + len(prestige_after_ply)
    return {
        "game_index": game_index,
        "seat": seat,
        "ply_index": ply_index,
        "result": {
            "scores": scores,
            "centered_returns": centered,
            "truncated": truncated,
            "source_terminal_result": None
            if truncated
            else {
                "scores": scores,
                "ranks": ranks,
                "winners": [index for index, rank in enumerate(ranks) if rank == 0],
                "reason": "prestige_threshold",
            },
        },
        "m40a_labels": {
            "prestige_after_ply": prestige_after_ply,
            "window_plies": window_plies,
            "truncated": truncated,
        },
    }


def test_outcome_label_completed() -> None:
    assert outcome_label(_record(scores=[15, 10], seat=0)) == "win"
    assert outcome_label(_record(scores=[10, 15], seat=0)) == "loss"
    # Equal scores default to an equal-rank draw in _record; the
    # tiebreak cases have their own dedicated tests below.
    assert outcome_label(_record(scores=[12, 12], ranks=[0, 0], seat=0)) == "draw"
    assert outcome_label(_record(scores=[10, 15], seat=1)) == "win"



def test_outcome_label_uses_authoritative_centered_return_not_vp() -> None:
    """Equal VP with a rank tiebreak is a WIN/LOSS, not a draw: the
    outcome label must read the referee's centered return, which is
    rank-derived, and never compare final VP."""
    # Equal scores 12:12, viewer rank better -> win
    record = _record(scores=[12, 12], ranks=[0, 1], seat=0)
    assert outcome_label(record) == "win"
    # Equal scores, opponent rank better -> loss
    record = _record(scores=[12, 12], ranks=[1, 0], seat=0)
    assert outcome_label(record) == "loss"
    # True equal-rank -> draw
    record = _record(scores=[12, 12], ranks=[0, 0], seat=0)
    assert outcome_label(record) == "draw"
    # Seat 1 mirror: viewer rank better -> win
    record = _record(scores=[12, 12], ranks=[1, 0], seat=1)
    assert outcome_label(record) == "win"


def test_outcome_and_value_target_cannot_disagree() -> None:
    """The Outcome class expectation and the value target come from the
    same authoritative centered return: win <=> +1, draw <=> 0,
    loss <=> -1."""
    for centered, seat in [([1.0, -1.0], 0), ([-1.0, 1.0], 0), ([0.0, 0.0], 0), ([1.0, -1.0], 1)]:
        record = _record(centered=centered, seat=seat)
        label = outcome_label(record)
        target = value_target(record)
        expected = {"win": 1.0, "draw": 0.0, "loss": -1.0}[label]
        assert target == expected


def test_outcome_label_fails_closed_on_corrupted_centered_return() -> None:
    record = _record(centered=[0.5, -0.5])
    with pytest.raises(LabelError, match="fail closed"):
        outcome_label(record)


def test_outcome_label_fails_closed_on_rank_disagreement() -> None:
    """centered return says win but the ranks say loss -> corrupted."""
    record = _record(
        scores=[15, 10],
        centered=[1.0, -1.0],
        ranks=[1, 0],  # inverted vs the centered return
    )
    with pytest.raises(LabelError, match="corrupted"):
        outcome_label(record)


def test_outcome_label_truncated_is_none() -> None:
    record = _record(truncated=True, centered=[-0.4, -0.6])
    assert outcome_label(record) is None
    assert final_vp_labels(record) is None
    assert vp_difference_label(record) is None
    assert timing_labels(record) is None


def test_final_vp_label_fail_closed_above_30() -> None:
    with pytest.raises(LabelError, match="fail closed"):
        final_vp_labels(_record(scores=[31, 10]))


def test_vp_difference_label_uses_m39a_normalization() -> None:
    # clamp((self - opp)/15, -1, +1)
    assert vp_difference_label(_record(scores=[15, 0])) == 1.0
    assert vp_difference_label(_record(scores=[0, 15])) == -1.0
    assert vp_difference_label(_record(scores=[12, 12])) == 0.0
    assert abs(vp_difference_label(_record(scores=[20, 5])) - 1.0) < 1e-12
    assert normalized_vp_difference(22, 10) == pytest.approx(12 / 15)


def test_value_target_uses_cap_return_for_truncated() -> None:
    record = _record(truncated=True, centered=[-0.7310585786300049, -0.2689414213699951])
    assert value_target(record) == pytest.approx(-0.7310585786300049)


# ---------------------------------------------------------------------------
# Timing semantics (the frozen off-by-one + three mandatory cases)
# ---------------------------------------------------------------------------


def test_timing_pending_decision_is_turn_one_current_action_finish() -> None:
    """Finish ON the tagged decision: the tagged pending decision is
    own-turn #1, so all horizons (2/4/8) are true for self."""
    # Seat 0, ply 0; seat 0 acts on even plies. The tagged decision (ply
    # 0) crosses 15 VP: prestige_after_ply[0] (after ply 0) shows it.
    record = _record(
        seat=0,
        ply_index=0,
        scores=[15, 0],
        prestige_after_ply=[[15, 0], [15, 0], [15, 0], [15, 0]],
        window_plies=4,
    )
    labels = timing_labels(record)
    # self flags for 2/4/8 all true (finish on turn #1 <= every horizon)
    assert labels[0] is True
    assert labels[1] is True
    assert labels[2] is True
    # opponent never finishes
    assert labels[3] is False
    assert labels[4] is False
    assert labels[5] is False


def test_timing_next_own_turn_finish() -> None:
    """Finish on the next own decision: within k=2 but not within a
    hypothetical k=1. Seat 0 tagged at ply 0; next own decision is ply 2
    (relative index 2 in the payload)."""
    record = _record(
        seat=0,
        ply_index=0,
        scores=[15, 0],
        # after ply0: 12; after ply1: 12; after ply2 (own): 15
        prestige_after_ply=[[12, 0], [12, 0], [15, 0], [15, 0], [15, 0]],
        window_plies=5,
    )
    labels = timing_labels(record)
    # self@2 true (finish on own decision #2), self@4/8 true (earlier
    # finish implies within-later-horizon too)
    assert labels[0] is True
    assert labels[1] is True


def test_timing_opponent_next_turn_finish() -> None:
    """The opponent's pending decision (one ply after the tagged one) is
    their turn #1. Seat 0 tagged at ply 0; opponent acts at ply 1 and
    finishes there: opp@2/4/8 all true."""
    record = _record(
        seat=0,
        ply_index=0,
        scores=[10, 15],
        # after ply0: [10, 12]; after ply1 (opponent): [10, 15]
        prestige_after_ply=[[10, 12], [10, 15], [10, 15], [10, 15]],
        window_plies=4,
    )
    labels = timing_labels(record)
    assert labels[3] is True  # opp within 2
    assert labels[4] is True  # opp within 4
    assert labels[5] is True  # opp within 8
    # self never finishes
    assert labels[0] is False


def _timing_record(seat: int, finish_own_decision: int, opp_finish: int | None = None) -> dict:
    """Build a record whose SELF first reaches 15 VP on own decision
    `finish_own_decision` (1-based, pending = #1), and whose OPPONENT
    first reaches 15 on opponent decision `opp_finish` (None = never).

    The window is long enough for 12 own decisions; prestige stays
    below 15 until the finishing decision and stays at 15 after.
    """
    ply_index = 0
    window = 40
    prestige = []
    self_vp = 0
    opp_vp = 0
    self_decision = 0
    opp_decision = 0
    for ply in range(ply_index, window):
        if ply % 2 == seat:
            self_decision += 1
            if self_decision == finish_own_decision:
                self_vp = 15
        else:
            opp_decision += 1
            if opp_finish is not None and opp_decision == opp_finish:
                opp_vp = 15
        prestige.append([self_vp, opp_vp] if seat == 0 else [opp_vp, self_vp])
    final = [15, 0] if seat == 0 else [0, 15]
    return _record(
        seat=seat,
        ply_index=ply_index,
        scores=final,
        prestige_after_ply=prestige,
        window_plies=window,
    )


def test_timing_self_finishes_on_decision_3() -> None:
    """Eventual self winner finishing on own decision #3: within 4 and 8
    but NOT within 2 — the final VP must not leak into the horizon."""
    labels = timing_labels(_timing_record(seat=0, finish_own_decision=3))
    assert labels[0] is False  # self@2
    assert labels[1] is True   # self@4
    assert labels[2] is True   # self@8
    assert labels[3:6] == [False] * 3


def test_timing_self_finishes_on_decision_9() -> None:
    """Eventual self winner finishing on own decision #9: NO horizon is
    true — the strict ordinal rule kills the final-score fallback."""
    labels = timing_labels(_timing_record(seat=0, finish_own_decision=9))
    assert labels[0] is False
    assert labels[1] is False
    assert labels[2] is False


def test_timing_opponent_finishes_on_decision_3() -> None:
    labels = timing_labels(_timing_record(seat=0, finish_own_decision=20, opp_finish=3))
    assert labels[3] is False  # opp@2
    assert labels[4] is True   # opp@4
    assert labels[5] is True   # opp@8
    assert labels[0:3] == [False] * 3


def test_timing_opponent_finishes_on_decision_9() -> None:
    labels = timing_labels(_timing_record(seat=0, finish_own_decision=20, opp_finish=9))
    assert labels[3] is False
    assert labels[4] is False
    assert labels[5] is False


def test_timing_seat1_self_finishes_on_decision_9() -> None:
    """Seat-1 records must orient the viewer-relative payload correctly
    (this is the Python-side counterpart of the Rust seat-orientation
    fix: prestige_after_ply[*][0] is always the RECORD seat's)."""
    labels = timing_labels(_timing_record(seat=1, finish_own_decision=9))
    assert labels[0:3] == [False] * 3


def test_timing_early_game_eventual_winner_not_positive() -> None:
    """An early-game record from an eventual winner must not become
    positive merely because final VP >= 15: with the finish on decision
    #12, every horizon is false even though the record's seat won."""
    labels = timing_labels(_timing_record(seat=0, finish_own_decision=12))
    assert labels == [False] * 6


def test_timing_no_finish_all_false() -> None:
    record = _record(
        seat=0,
        ply_index=0,
        scores=[8, 7],
        prestige_after_ply=[[4, 0], [4, 2], [6, 2], [6, 3], [8, 3], [8, 7]],
        window_plies=6,
    )
    labels = timing_labels(record)
    assert labels == [False] * 6


# ---------------------------------------------------------------------------
# The frozen split
# ---------------------------------------------------------------------------


def test_bankers_rounding() -> None:
    assert _bankers_round(2.5) == 2
    assert _bankers_round(3.5) == 4
    assert _bankers_round(0.20 * 16) == 3   # 3.2 -> 3
    assert _bankers_round(0.20 * 48) == 10  # 9.6 -> 10
    assert _bankers_round(0.20 * 128) == 26  # 25.6 -> 26


def test_frozen_split_exact_cardinalities() -> None:
    """The frozen split over the real 4,096-game index space yields the
    frozen cardinalities: 823 validation completed, 3,272 train completed
    + the forced truncated game (3,273 total train), 0 validation
    truncated."""
    game_indices = list(range(4096))
    split = frozen_split(game_indices, {2785})
    assert len(split["validation"]) == VALIDATION_COMPLETED_GAMES == 823
    assert len(split["train"]) == TRAINING_TOTAL_GAMES == 3273
    assert 2785 in split["train"]
    assert 2785 not in split["validation"]
    # No leakage
    assert not (set(split["train"]) & set(split["validation"]))
    assert set(split["train"]) | set(split["validation"]) == set(range(4096))


def test_frozen_split_is_deterministic() -> None:
    first = frozen_split(list(range(4096)), {2785})
    second = frozen_split(list(range(4096)), {2785})
    assert first == second
    assert split_manifest_hash(first) == split_manifest_hash(second)


def test_frozen_split_rejects_wrong_truncation_set() -> None:
    with pytest.raises(LabelError, match="single truncated game"):
        frozen_split(list(range(4096)), set())


# ---------------------------------------------------------------------------
# Model / arm construction
# ---------------------------------------------------------------------------


def test_head_initialization_is_reproducible() -> None:
    model_a = M40AModel()
    model_b = M40AModel()
    initialize_predictive_heads(model_a)
    initialize_predictive_heads(model_b)
    for (name_a, param_a), (_, param_b) in zip(
        model_a.heads.state_dict().items(), model_b.heads.state_dict().items()
    ):
        assert torch.equal(param_a, param_b), name_a


def test_state_dict_copy_forks_identical_arms() -> None:
    """A is created from a copied head state_dict; the arms are identical
    before B's pretraining — the only difference B ever gets."""
    source = M40AModel()
    initialize_predictive_heads(source)
    state = copy_head_state(source)

    arm_a = M40AModel()
    load_head_state(arm_a, state)
    arm_b = M40AModel()
    load_head_state(arm_b, state)
    for param_a, param_b in zip(
        arm_a.heads.parameters(), arm_b.heads.parameters()
    ):
        assert torch.equal(param_a, param_b)


def test_outcome_value_definition() -> None:
    # outcome alphabet: [p_loss, p_draw, p_win]
    logits = torch.tensor([[-2.0, 0.0, 2.0], [0.0, 5.0, 0.0]])
    values = outcome_value(logits)
    assert values[0] > 0  # p_win > p_loss
    assert values[1] == pytest.approx(0.0, abs=1e-6)


def test_head_output_shapes() -> None:
    model = M40AModel()
    model.eval()
    from splendor_gpu.data import load_catalog

    catalog = load_catalog(
        Path(__file__).resolve().parent.parent.parent.parent
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    )
    fixture = json.loads(
        (
            Path(__file__).resolve().parent.parent.parent.parent
            / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
        ).read_text(encoding="utf-8")
    )
    frame = fixture["frames"][0]
    from splendor_gpu.m39a_model import encode_decisions

    encoded = encode_decisions(
        [frame["player_view"]], [frame["legal_actions"]], catalog
    )
    with torch.no_grad():
        logits, outputs = model.forward_packed(**encoded)
    assert logits.shape == (len(frame["legal_actions"]),)
    assert outputs["outcome"].shape == (1, 3)
    assert outputs["final_vp_self"].shape == (1, 31)
    assert outputs["final_vp_opp"].shape == (1, 31)
    assert outputs["vp_difference"].shape == (1,)
    assert outputs["timing"].shape == (1, 6)
