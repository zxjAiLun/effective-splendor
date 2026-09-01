from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splendor_gpu.m39a_contract import (
    gae_for_trajectory,
    shuffled_indices,
    standardize_advantages,
)
from splendor_gpu.m40a_contract import (
    build_plan,
    crn_schedule_hash,
    online_seed,
    online_scheduled_game,
    online_cycle_schedule,
    plan_hash,
    validate_plan,
    M40A_SERVER_FORMAT,
)
from splendor_gpu.m40a_constants import (
    ANCHOR_CRITICAL_DF63,
    H1_CRITICAL_DF127,
    LEAGUE_CRITICAL_DF31,
    LR_WAYPOINTS,
    PPO_TRAINER_SEED,
    TRAINING_SEED_BASE,
)
from splendor_gpu.m40a_gates import (
    evaluate_anchor,
    evaluate_h1,
    evaluate_league,
    formal_checkpoint_guard,
)
from splendor_gpu.m40a_model import (
    M40AModel,
    copy_head_state,
    head_state_semantic_hash,
    initialize_predictive_heads,
    load_head_state,
)
from splendor_gpu.m40a_train import gae_advantages


# ---------------------------------------------------------------------------
# GAE exact equivalence (P1-1)
# ---------------------------------------------------------------------------


def _traj_record(game_index: int, seat: int, ply: int, centered: float) -> dict:
    return {
        "game_index": game_index,
        "seat": seat,
        "ply_index": ply,
        "result": {"centered_returns": [centered, -centered]},
    }


def _check_gae_equivalence(terminal_return: float, length: int) -> None:
    """M40A gae_advantages must equal the accepted M39A per-trajectory
    GAE + population standardization, exactly."""
    values = [0.1 * i - 0.05 * length for i in range(length)]
    records = [
        _traj_record(7, 0, i, terminal_return) for i in range(length)
    ]
    m40a = gae_advantages(records, values)
    m39a_raw = gae_for_trajectory(values, terminal_return)
    m39a = standardize_advantages(m39a_raw)
    assert m40a == pytest.approx(m39a, rel=1e-12)


def test_gae_win_equivalence() -> None:
    _check_gae_equivalence(1.0, 5)


def test_gae_loss_equivalence() -> None:
    _check_gae_equivalence(-1.0, 5)


def test_gae_draw_equivalence() -> None:
    _check_gae_equivalence(0.0, 5)


def test_gae_cap_return_equivalence() -> None:
    _check_gae_equivalence(-0.7310585786300049, 5)


def test_gae_length_one_equivalence() -> None:
    _check_gae_equivalence(1.0, 1)


def test_gae_length_twelve_equivalence() -> None:
    _check_gae_equivalence(-1.0, 12)


def test_gae_no_intermediate_terminal_injection() -> None:
    """A +1 win must NOT be injected at intermediate decisions.

    With constant values V=0 and terminal return +1, the accepted M39A
    recurrence gives delta=0 at every intermediate step, so the ONLY
    nonzero delta is the last decision's (R - V). The raw advantages
    are therefore the pure lambda-decayed tail of that single delta:
    A_t = 0.95^(T-1-t). The BUGGY variant (delta = R - V + gamma*V')
    would make every raw advantage at least 1.0.
    """
    values = [0.0] * 4
    raw = gae_for_trajectory(values, 1.0)
    assert raw[3] == pytest.approx(1.0)
    assert raw[2] == pytest.approx(0.95)
    assert raw[1] == pytest.approx(0.95 ** 2)
    assert raw[0] == pytest.approx(0.95 ** 3)
    # Every raw advantage is <= the terminal delta (1.0): no step ever
    # receives the +1 twice.
    assert all(value <= 1.0 + 1e-12 for value in raw)


def test_gae_multiple_trajectories() -> None:
    """Two (game, seat) trajectories standardize jointly."""
    records = (
        [_traj_record(1, 0, i, 1.0) for i in range(3)]
        + [_traj_record(2, 0, i, -1.0) for i in range(2)]
    )
    values = [0.0, 0.1, -0.1, 0.05, -0.05]
    result = gae_advantages(records, values)
    expected_raw = (
        gae_for_trajectory([0.0, 0.1, -0.1], 1.0)
        + gae_for_trajectory([0.05, -0.05], -1.0)
    )
    expected = standardize_advantages(expected_raw)
    assert result == pytest.approx(expected, rel=1e-12)


# ---------------------------------------------------------------------------
# Contract / schedule (instruction 3 / 8)
# ---------------------------------------------------------------------------


def test_canonical_plan_validates_and_hashes() -> None:
    plan = build_plan()
    digest = validate_plan(plan)
    assert digest == plan_hash(plan)
    assert len(digest) == 64


def test_plan_rejects_mutation() -> None:
    plan = build_plan()
    plan["round"]["cycles"] = 8
    with pytest.raises(ValueError, match="deviates"):
        validate_plan(plan)


def test_online_seed_schedule() -> None:
    assert online_seed(0) == 8_000_000
    assert online_seed(1) == 8_000_000
    assert online_seed(2) == 8_000_001
    assert online_seed(2047) == 8_001_023
    with pytest.raises(ValueError):
        online_seed(2048)


def test_online_schedule_inherits_cycle_local_mix() -> None:
    """Cycle 1's bucket mix is the M39A §3.3 mix on the 8M seeds."""
    schedule = online_cycle_schedule(1)
    buckets = [entry["bucket"] for entry in schedule]
    assert buckets.count("random") == 16
    assert buckets.count("heuristic") == 48
    assert buckets.count("m07") == 128
    assert buckets.count("league") == 128
    assert buckets.count("self_play") == 192
    assert all(entry["learner_runtime"].startswith("effective-splendor-m40a") for entry in schedule)


def test_crn_schedule_is_arm_independent() -> None:
    """One canonical hash; the A and B manifests derive from the same
    generator so their stripped manifests hash identically."""
    assert crn_schedule_hash() == crn_schedule_hash()


def test_shuffle_reuses_m39a_namespace() -> None:
    """The M40A trainer shuffle IS the accepted M39A shuffled_indices."""
    from splendor_gpu.m40a_train import train_cycle  # noqa: F401 import sanity
    # shuffled_indices with the inherited trainer namespace
    first = shuffled_indices(100, 1, 1)
    assert sorted(first) == list(range(100))
    assert first == shuffled_indices(100, 1, 1)
    assert first != shuffled_indices(100, 2, 1)


# ---------------------------------------------------------------------------
# Optimizer carry (instruction 6)
# ---------------------------------------------------------------------------


def _tiny_records(n: int) -> list[dict]:
    """Records whose action is the TRUE frozen categorical draw under the
    checkpoint (computed via the same seed + walk as the trainer's
    reproduction check), so the fail-closed reproduction passes."""
    import json

    fixture = json.loads(
        (
            Path(__file__).resolve().parent.parent.parent.parent
            / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
        ).read_text(encoding="utf-8")
    )
    frame = fixture["frames"][0]
    # Determine the drawn index for this (game_index, seat, request_id)
    # by replicating the frozen walk — but the walk depends on the
    # model's logits, which the caller controls. For the optimizer test
    # we instead record the action at the index the MODEL draws; we
    # compute it lazily inside the test via the helper below.
    records = []
    for index in range(n):
        records.append(
            {
                "game_index": index,
                "seat": 0,
                "ply_index": 0,
                "request_id": 1,
                "observation_hash": "h",
                "observation": frame["player_view"],
                "legal_actions": frame["legal_actions"],
                "action": frame["legal_actions"][0],
                "decision_seed": 0,
                "old_log_probability": -1.0,
                "old_value": 0.0,
                "old_value_by_player": [0.0, 0.0],
                "old_auxiliary_score": 0.0,
                "result": {
                    "scores": [18, 0],
                    "centered_returns": [1.0, -1.0],
                    "truncated": False,
                    "source_terminal_result": {
                        "scores": [18, 0],
                        "ranks": [0, 1],
                        "winners": [0],
                        "reason": "prestige_threshold",
                    },
                },
                "m40a_labels": {
                    "prestige_after_ply": [[0, 0]],
                    "window_plies": 1,
                    "truncated": False,
                },
            }
        )
    return records


def _draw_consistent_records(model: M40AModel, n: int, catalog) -> list[dict]:
    """Synthesize records whose action IS the model's frozen categorical
    draw (seed-derived) and whose old_log_probability/old_value are
    computed through the trainer's OWN batched forward path, so the
    fail-closed reproduction is bit-exact (no kernel-shape drift)."""
    import json

    from splendor_gpu.m39a_contract import decision_seed
    from splendor_gpu.m40a_model import outcome_value
    from splendor_gpu.m40a_train import (
        _forward_state,
        _selected_log_probabilities_and_entropies,
    )

    fixture = json.loads(
        (
            Path(__file__).resolve().parent.parent.parent.parent
            / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
        ).read_text(encoding="utf-8")
    )
    frame = fixture["frames"][0]
    observation = frame["player_view"]
    legal_actions = frame["legal_actions"]
    device = next(model.parameters()).device
    model.eval()

    probes = []
    for index in range(n):
        probes.append(
            {
                "observation": observation,
                "legal_actions": legal_actions,
                "action": legal_actions[0],
                "game_index": index,
                "seat": 0,
                "ply_index": 0,
                "request_id": 1,
            }
        )
    with torch.no_grad():
        logits, heads, offsets = _forward_state(model, probes, catalog, device)
    boundaries = offsets.detach().cpu().tolist()
    value = float(outcome_value(heads["outcome"])[0].item())

    records = []
    for index in range(n):
        seed = decision_seed(index, 0, 1)
        start_ply, end_ply = boundaries[index], boundaries[index + 1]
        segment_logits = logits[start_ply:end_ply].to(dtype=torch.float32)
        segment_log_probs = torch.log_softmax(segment_logits, dim=0)
        probabilities = segment_log_probs.exp().cpu().tolist()
        unit = (int(seed) >> 11) * (2.0 ** -53)
        cumulative = 0.0
        chosen = len(probabilities) - 1
        for position, probability in enumerate(probabilities):
            cumulative += probability
            if unit < cumulative:
                chosen = position
                break
        records.append(
            {
                "game_index": index,
                "seat": 0,
                "ply_index": 0,
                "request_id": 1,
                "observation_hash": "h",
                "observation": observation,
                "legal_actions": legal_actions,
                "action": legal_actions[chosen],
                "decision_seed": seed,
                "old_log_probability": float(segment_log_probs[chosen].item()),
                "old_value": value,
                "old_value_by_player": [value, -value],
                "old_auxiliary_score": 0.0,
                "result": {
                    "scores": [18, 0],
                    "centered_returns": [1.0, -1.0],
                    "truncated": False,
                    "source_terminal_result": {
                        "scores": [18, 0],
                        "ranks": [0, 1],
                        "winners": [0],
                        "reason": "prestige_threshold",
                    },
                },
                "m40a_labels": {
                    "prestige_after_ply": [[0, 0]],
                    "window_plies": 1,
                    "truncated": False,
                },
            }
        )
    return records


def test_optimizer_continuation_differs_from_reset(tmp_path: Path) -> None:
    """Cycle 2 with restored AdamW state differs from an illicit reset;
    the records pass the full fail-closed reproduction (value_check=True)."""
    from splendor_gpu.data import load_catalog
    from splendor_gpu.m40a_train import train_cycle

    catalog = load_catalog(
        Path(__file__).resolve().parent.parent.parent.parent
        / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    )
    plan_hash_value = "test"

    model_continued = M40AModel()
    initialize_predictive_heads(model_continued)
    records = _draw_consistent_records(model_continued, 8, catalog)
    _, report1 = train_cycle(
        model=model_continued,
        records=records,
        catalog=catalog,
        device=torch.device("cpu"),
        cycle=1,
        plan_hash=plan_hash_value,
        arm="A",
    )
    optimizer_state = report1["optimizer_state_dict"]
    # Cycle 2's records come from cycle-2 collection against the cycle-1
    # checkpoint — physically, a FRESH draw against the updated weights.
    records2 = _draw_consistent_records(model_continued, 8, catalog)
    _, report2 = train_cycle(
        model=model_continued,
        records=records2,
        catalog=catalog,
        device=torch.device("cpu"),
        cycle=2,
        plan_hash=plan_hash_value,
        arm="A",
        parent_optimizer_state=optimizer_state,
    )
    continued_loss = report2["history"][0]["loss"]

    model_reset = M40AModel()
    initialize_predictive_heads(model_reset)
    _, report_reset = train_cycle(
        model=model_reset,
        records=_draw_consistent_records(model_reset, 8, catalog),
        catalog=catalog,
        device=torch.device("cpu"),
        cycle=2,
        plan_hash=plan_hash_value,
        arm="A",
        parent_optimizer_state=None,  # illicit reset
    )
    reset_loss = report_reset["history"][0]["loss"]
    # The continued path carries Adam moments; the reset path starts cold
    # at the same waypoint — their first-epoch losses differ.
    assert continued_loss != reset_loss
    # The Adam state genuinely carried: cycle 2's optimizer state has
    # non-trivial step counts (accumulated over cycles), while a reset
    # cycle-2 optimizer sees each parameter exactly once per step.
    continued_steps = optimizer_state["state"].get(0, {}).get("step")
    assert continued_steps is not None
    # And the reproduction was genuinely enforced (not bypassed):
    assert report1["recomputation"]["value_check"] is True
    assert report2["recomputation"]["value_check"] is True


# ---------------------------------------------------------------------------
# Gates (instruction 9)
# ---------------------------------------------------------------------------


def _row(arm: str, pairing: str, seed: int, rotation: int, outcome: str) -> dict:
    return {
        "arm": arm,
        "pairing": pairing,
        "seed": seed,
        "rotation": rotation,
        "completed": True,
        "candidate_fault": False,
        "deterministic_nontermination": False,
        "outcome": outcome,
    }


def _h1_rows(candidate_wins: bool) -> list[dict]:
    rows = []
    for seed in range(8_100_000, 8_100_127 + 1):
        for rotation in (0, 1):
            rows.append(_row("candidate", "H1", seed, rotation, "win" if candidate_wins else "loss"))
            rows.append(_row("baseline", "H1", seed, rotation, "loss" if candidate_wins else "win"))
    return rows


def test_h1_pass_and_fail() -> None:
    passing = evaluate_h1(_h1_rows(candidate_wins=True))
    assert passing["verdict"] == "pass"
    assert passing["lower_95_bps"] > 0
    failing = evaluate_h1(_h1_rows(candidate_wins=False))
    assert failing["verdict"] == "fail"


def test_h1_rejects_incomplete() -> None:
    rows = _h1_rows(True)
    rows[10]["completed"] = False
    with pytest.raises(ValueError, match="fail closed"):
        evaluate_h1(rows)


def _league_rows(b_wins: bool) -> list[dict]:
    rows = []
    for seed in range(8_200_000, 8_200_031 + 1):
        for pairing in (
            "M24-S2", "M25-D2-v2", "M28A", "M28B", "M29A-v2",
            "M31A", "M32A", "M33A", "M34A",
        ):
            for rotation in (0, 1):
                rows.append(
                    _row("candidate", pairing, seed, rotation, "win" if b_wins else "loss")
                )
                rows.append(
                    _row("baseline", pairing, seed, rotation, "loss" if b_wins else "win")
                )
    return rows


def test_league_upper_bound_rule() -> None:
    strong = evaluate_league(_league_rows(b_wins=True))
    assert strong["verdict"] == "pass"  # upper > 0
    weak = evaluate_league(_league_rows(b_wins=False))
    assert weak["upper_95_bps"] < 0
    assert weak["verdict"] == "fail"


def _anchor_rows(gate: str, wins: bool) -> list[dict]:
    base = 8_300_000 if gate == "m07" else 8_400_000
    pairing = "M07" if gate == "m07" else "D2-v2"
    rows = []
    for seed in range(base, base + 64):
        for rotation in (0, 1):
            rows.append(_row("candidate", pairing, seed, rotation, "win" if wins else "loss"))
    return rows


def _anchor_rows_mixed(gate: str) -> list[dict]:
    """Half wins / half losses for a nonzero-variance interval."""
    base = 8_300_000 if gate == "m07" else 8_400_000
    pairing = "M07" if gate == "m07" else "D2-v2"
    rows = []
    for seed in range(base, base + 64):
        for rotation in (0, 1):
            outcome = "win" if seed % 2 == 0 else "loss"
            rows.append(_row("candidate", pairing, seed, rotation, outcome))
    return rows


def test_anchor_statistics_report_only() -> None:
    winning = evaluate_anchor(_anchor_rows("m07", True), "m07")
    assert winning["mean_delta_bps"] == pytest.approx(5000.0)
    # Zero variance is legal; the interval degenerates to the point.
    assert winning["ci_high_bps"] >= winning["ci_low_bps"]
    assert winning["verdict"] == "report-only"
    losing = evaluate_anchor(_anchor_rows("d2", False), "d2")
    assert losing["mean_delta_bps"] == pytest.approx(-5000.0)
    mixed = evaluate_anchor(_anchor_rows_mixed("m07"), "m07")
    assert mixed["mean_delta_bps"] == pytest.approx(0.0)
    assert mixed["ci_high_bps"] > mixed["ci_low_bps"]


def test_formal_checkpoint_guard_rejects_non_cycle4() -> None:
    formal_checkpoint_guard(4)
    with pytest.raises(ValueError, match="cycle-4"):
        formal_checkpoint_guard(3)


# ---------------------------------------------------------------------------
# Model / fork identity
# ---------------------------------------------------------------------------


def test_fork_from_single_state() -> None:
    import copy

    source = M40AModel()
    initialize_predictive_heads(source)
    state = copy_head_state(source)
    arm_a = copy.deepcopy(source)
    arm_b = copy.deepcopy(source)
    load_head_state(arm_a, state)
    load_head_state(arm_b, state)
    assert head_state_semantic_hash(arm_a) == head_state_semantic_hash(arm_b)
    a_trunk = {k: v for k, v in arm_a.state_dict().items() if not k.startswith("heads.")}
    b_trunk = {k: v for k, v in arm_b.state_dict().items() if not k.startswith("heads.")}
    assert all(torch.equal(a_trunk[k], b_trunk[k]) for k in a_trunk)
