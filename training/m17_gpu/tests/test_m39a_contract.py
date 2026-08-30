import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from splendor_gpu.m39a_contract import (
    LEAGUE_ORDER,
    SIDECAR_FORMAT,
    SIDECAR_VERSION,
    auxiliary_target,
    cycle_schedule,
    decision_seed,
    gae_for_trajectory,
    load_plan,
    plan_hash,
    shuffled_indices,
    splitmix64,
    standardize_advantages,
    validate_sidecar,
)


PLAN_PATH = Path(__file__).resolve().parent.parent.parent.parent / "benchmarks/m39a-arena-driven-policy-value-rl.plan.json"


def test_plan_and_rng_goldens():
    plan = load_plan(PLAN_PATH)
    assert plan_hash(plan) == "06cbd7b2413b7e640402799ff25c25ae57985ab3ea25b113b3eddf053f2841d6"
    assert splitmix64(0) == 16294208416658607535
    assert decision_seed(0, 0, 1) == 9830301397363971053
    assert shuffled_indices(8, 1, 1) == [7, 2, 4, 6, 1, 3, 5, 0]
    assert sorted(shuffled_indices(10_000, 8, 4)) == list(range(10_000))


def test_cycle_local_schedule_and_round_totals():
    round_games = []
    for cycle in range(1, 9):
        games = cycle_schedule(cycle)
        assert len(games) == 512
        assert Counter(game.bucket for game in games) == {
            "random": 16,
            "heuristic": 48,
            "m07": 128,
            "league": 128,
            "self_play": 192,
        }
        assert sum(len(game.learner_seats) for game in games) == 704
        round_games.extend(games)
    league = Counter(game.opponent for game in round_games if game.bucket == "league")
    assert [league[opponent] for opponent in LEAGUE_ORDER] == [114] * 7 + [113] * 2
    assert len({game.game_index for game in round_games}) == 4096
    assert len({game.seed for game in round_games}) == 2048


def test_gae_is_per_seat_bootstrap_free_and_population_standardized():
    advantages = gae_for_trajectory([0.1, 0.2, 0.3], 1.0)
    assert advantages == pytest.approx([0.82675, 0.765, 0.7])
    standardized = standardize_advantages(advantages)
    assert sum(standardized) == pytest.approx(0.0, abs=1e-12)
    assert sum(value * value for value in standardized) / 3 == pytest.approx(1.0)
    assert standardize_advantages([2.0, 2.0]) == [0.0, 0.0]
    assert auxiliary_target([15, 9], 0) == pytest.approx(0.4)
    assert auxiliary_target([15, 9], 1) == pytest.approx(-0.4)


def _sidecar():
    action = {"type": "pass"}
    return {
        "format": SIDECAR_FORMAT,
        "version": SIDECAR_VERSION,
        "plan_hash": "aa" * 32,
        "checkpoint_sha256": "bb" * 32,
        "game_id": "unit",
        "game_index": 0,
        "seat": 0,
        "records": [
            {
                "seat": 0,
                "ply_index": 0,
                "request_id": 1,
                "decision_seed": decision_seed(0, 0, 1),
                "legal_actions": [action],
                "action": action,
                "old_log_probability": 0.0,
                "old_value": 0.0,
            }
        ],
    }


def test_sidecar_validation_fails_closed():
    sidecar = _sidecar()
    validate_sidecar(sidecar)
    tampered = copy.deepcopy(sidecar)
    tampered["records"][0]["decision_seed"] ^= 1
    with pytest.raises(ValueError, match="decision_seed"):
        validate_sidecar(tampered)
    duplicated = copy.deepcopy(sidecar)
    duplicated["records"].append(copy.deepcopy(duplicated["records"][0]))
    with pytest.raises(ValueError, match="increase"):
        validate_sidecar(duplicated)


def test_plan_rejects_post_hoc_gate_change():
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan["trainer"]["minibatch_size"] = 256
    with pytest.raises(ValueError, match="minibatch_size"):
        plan_hash(plan)
