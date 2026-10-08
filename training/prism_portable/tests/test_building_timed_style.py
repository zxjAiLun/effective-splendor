"""Boundary and synthetic transaction tests for timed building style."""
import copy

import pytest

from training.prism_portable.engine.export import export_weights
from training.prism_portable.engine.io import sha256_file
from training.prism_portable.engine.model import PrismModel
from training.prism_portable.engine.ppo.building import BASE_CATALOG_FINGERPRINT
from training.prism_portable.engine.ppo.building_timed import (
    default_timed_building_config, extract_timed_building_profile,
    profile_from_own_decisions, validate_timed_building_config, _timed_utility,
)
from training.prism_portable.engine.ppo.coordinator import Run
from training.prism_portable.engine.ppo.style import extract_style_targets, validate_style_config
from training.prism_portable.tests.test_building_style import projected
from training.prism.tests.ppo_support import game, run_config, schedule


def timed(events, config=None):
    config = config or default_timed_building_config()
    return extract_timed_building_profile(projected(events), config)


def test_timed_contract_is_strict_and_v1_dispatch_is_unchanged():
    config = default_timed_building_config()
    assert validate_style_config(config) is config
    broken = copy.deepcopy(config)
    broken["weighting_formula"] = "later is better"
    with pytest.raises(ValueError):
        validate_timed_building_config(broken)
    v1 = {"format": "prism-building-style-v1", "early_window_main_actions": 12,
          "redemption_horizon_main_actions": 24, "early_max_printed_vp": 1,
          "per_investment_use_cap": 3, "global_use_cap": 24, "short_game_padding": "none",
          "phase_semantics": "choose_noble-belongs-to-preceding-main", "terminal_only": True,
          "style_reward_input": "player-visible-own-purchases-and-prepurchase-bonuses",
          "diagnostic_early_bonus_padding": "held-at-terminal"}
    assert validate_style_config(v1) is v1


def test_purchase_does_not_redeem_its_own_new_bonus():
    p = timed([0])
    assert p["building_utility"] == 0
    assert p["time_weighted_utility"] == 0
    assert p["investments"][0]["use_main_actions"] == []


def test_same_use_count_at_earlier_main_gets_higher_timed_reward():
    early = timed([0, 42])  # One eligible use at own Main 2.
    late = timed(["take_tokens"] * 10 + [0] + ["take_tokens"] * 10 + [42])
    assert len(early["investments"][0]["use_main_actions"]) == 1
    assert len(late["investments"][0]["use_main_actions"]) == 1
    assert early["building_utility"] == late["building_utility"] == 1 / 24
    assert early["time_weighted_utility"] == pytest.approx((25 - 2) / 24 / 24)
    assert late["time_weighted_utility"] == pytest.approx((25 - 22) / 24 / 24)
    assert early["time_weighted_utility"] > late["time_weighted_utility"]


def test_ordinal_still_requires_enough_printed_cost_for_that_investment():
    p = timed([42, 0, 4])
    investment = p["investments"][0]
    assert investment["bonus_ordinal"] == 2
    assert investment["use_main_actions"] == []
    assert p["time_weighted_utility"] == 0


def test_choose_noble_does_not_advance_weighted_main_time():
    p = timed(["take_tokens"] * 10 + [0, "choose_noble", 42])
    assert p["main_actions"] == 12 and p["decision_actions"] == 13
    assert p["investments"][0]["use_main_actions"] == [12]
    assert p["time_weighted_utility"] == pytest.approx((25 - 12) / 24 / 24)


def test_short_game_has_no_timed_reward_padding():
    p = timed([0])
    assert p["main_actions"] == 1
    assert p["time_weighted_utility"] == 0
    assert p["early_bonus_auc12"] == 1.0  # descriptive v1 padding is retained


def test_per_investment_cap_preserves_v1_profile_and_timed_uses_first_three():
    p = timed([0, 42, 45, 67, 87])
    assert p["building_observed_use_units"] == 4
    assert p["building_use_units"] == 3
    assert p["building_v1_profile"]["format"] == "prism-building-profile-v1"
    assert p["building_v1_profile"]["investments"] == p["investments"]
    assert p["time_weighted_use_units"] == pytest.approx(sum((25 - t) / 24 for t in (2, 3, 4)))
    assert p["time_weighted_use_units"] < p["building_use_units"]
    assert p["investments"][0]["use_main_actions"] == [2, 3, 4, 5]


def test_global_timed_cap_and_all_original_descriptions_survive():
    early = [24, 25, 26, 32, 33, 34, 8, 9, 10, 16, 17, 18]
    p = timed(early + list(range(70, 82)))
    assert p["building_use_units_before_global_cap"] == 36
    assert p["building_use_units"] == 24
    assert p["time_weighted_use_units"] == min(p["time_weighted_use_units_before_global_cap"], 24)
    assert p["time_weighted_utility"] == p["time_weighted_use_units"] / 24
    assert p["time_weighted_use_units"] <= 24
    assert p["early_bonus_auc12"] == 6.5
    assert len(p["after_main_bonuses"]) == p["main_actions"]


def test_timed_global_cap_is_applied_after_weighted_uses():
    source = {"format": "prism-building-profile-v1", "main_actions": 24,
              "investments": [{"acquired_main": 1, "observed_uses": 3, "credited_uses": 3,
                               "use_main_actions": [2, 3, 4]} for _ in range(12)]}
    result = _timed_utility(source, default_timed_building_config())
    assert result["time_weighted_use_units_before_global_cap"] == pytest.approx(12 * (23 + 22 + 21) / 24)
    assert result["time_weighted_use_units"] == 24
    assert result["time_weighted_utility"] == 1


def test_extractor_dispatch_returns_timed_target_and_preserves_v1_metrics():
    g = projected([0, 42])
    targets, summary = extract_style_targets([g], default_timed_building_config())
    assert targets[("fixture", 0)] == pytest.approx((25 - 2) / 24 / 24)
    assert summary["format"] == "prism-building-timed-targets-v1"
    assert summary["mean_building_utility"] == 1 / 24
    assert summary["mean_early_bonus_auc12"] > 0
    assert summary["style_contract_sha256"]


def test_coordinator_seal_emits_timed_target_and_metrics(tmp_path):
    weights = tmp_path / "weights.json"
    export_weights(PrismModel(), weights, BASE_CATALOG_FINGERPRINT)
    cfg = run_config(sha256_file(weights))
    cfg.update(format="prism-ppo-run-v3", arena_contract_sha256="0" * 64,
               catalog_fingerprint=BASE_CATALOG_FINGERPRINT, style=default_timed_building_config())
    cfg["ppo"].update(style_beta=0.3, style_value_weight=0.5)
    run = Run.create(tmp_path / "run", cfg, weights)
    snapshot = run.begin_cycle(schedule())
    behavior = run._behavior_cache[snapshot["snapshot_sha256"]]
    shard = game(behavior, count=2, actions=1)
    visible = projected([0, 42])
    for row, projection in zip(shard["decisions"], visible["decisions"]):
        row.update(observation=copy.deepcopy(projection["observation"]),
                   visible_history=copy.deepcopy(projection.get("visible_history", [])),
                   legal_actions=[copy.deepcopy(projection["chosen_action"])],
                   chosen_action=copy.deepcopy(projection["chosen_action"]))
    with run._transaction():
        run.state["jobs"][shard["job_id"]] = {"status": "COMPLETE", "attempt": 1,
                                               "artifact": run.store.put_json(shard)}
        run.state["decisions"] = 2
        run._commit()
    run.seal()
    batch = run.store.get_json(run.state["batch"])
    assert all(row["style_return"] == pytest.approx((25 - 2) / 24 / 24) for row in batch["rows"])
    metrics = [row for row in run.state["metrics"] if row["event"] == "style_extracted"]
    assert len(metrics) == 1
    assert metrics[0]["mean_time_weighted_utility"] == pytest.approx((25 - 2) / 24 / 24)
    assert metrics[0]["mean_building_utility"] == pytest.approx(1 / 24)
    assert metrics[0]["mean_early_bonus_auc12"] > 0
