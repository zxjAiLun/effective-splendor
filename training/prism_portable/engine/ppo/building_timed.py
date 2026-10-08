"""Timed building style based only on real, eligible discount uses.

The original v1 building profile remains the evidence source. This format adds
one target that discounts later uses by their own Main-action time.
"""
import math

from ..io import canonical_hash
from .building import (
    BASE_CATALOG_FINGERPRINT,
    default_building_config,
    profile_from_own_decisions as profile_v1_from_own_decisions,
    validate_building_config,
)
from .contract import exact


def default_timed_building_config():
    return {
        "format": "prism-building-timed-style-v1",
        "base_contract": default_building_config(),
        "weighting_formula": "w(t)=(25-t)/24; t is 1-based own Main action",
        "weighted_uses_per_investment": 3,
        "weighted_global_use_cap": 24,
        "target_field": "time_weighted_utility",
    }


def validate_timed_building_config(value):
    expected = default_timed_building_config()
    exact(value, expected, "timed building style contract")
    if any(type(value[k]) is not type(v) or value[k] != v for k, v in expected.items()):
        raise ValueError("unsupported timed building utility semantics")
    validate_building_config(value["base_contract"])
    return value


def _timed_utility(base_profile, config):
    validate_timed_building_config(config)
    if base_profile.get("format") != "prism-building-profile-v1":
        raise ValueError("timed building requires the original v1 profile evidence")
    main_actions = base_profile.get("main_actions")
    if type(main_actions) is not int or not 0 <= main_actions <= 256:
        raise ValueError("timed building source profile has invalid Main-action count")
    investments = base_profile.get("investments")
    if not isinstance(investments, list):
        raise ValueError("timed building source profile investments must be a list")
    horizon = config["base_contract"]["redemption_horizon_main_actions"]
    per_cap = config["weighted_uses_per_investment"]
    weighted_before_global_cap = 0.0
    per_investment_weighted = []
    observed_total = credited_total = 0
    for investment in investments:
        if not isinstance(investment, dict):
            raise ValueError("timed building investment must be an object")
        acquired = investment["acquired_main"]
        uses = investment["use_main_actions"]
        if type(acquired) is not int or not 1 <= acquired <= main_actions:
            raise ValueError("timed building investment acquisition is outside own Main actions")
        if not isinstance(uses, list) or any(type(t) is not int for t in uses):
            raise ValueError("timed building use times must be integer Main actions")
        if uses != sorted(set(uses)):
            raise ValueError("timed building use times must be strictly increasing")
        if type(investment.get("observed_uses")) is not int or type(investment.get("credited_uses")) is not int:
            raise ValueError("timed building use counts must be integers")
        if len(uses) != investment["observed_uses"] or min(len(uses), per_cap) != investment["credited_uses"]:
            raise ValueError("timed building source profile investment conservation mismatch")
        if any(type(t) is not int or t <= acquired or t > min(main_actions, horizon) for t in uses):
            raise ValueError("timed building use is outside its real post-acquisition horizon")
        value = math.fsum((25 - t) / 24 for t in uses[:per_cap])
        value = min(float(per_cap), value)
        per_investment_weighted.append(value)
        weighted_before_global_cap += value
        observed_total += investment["observed_uses"]
        credited_total += investment["credited_uses"]
    if "building_observed_use_units" in base_profile and base_profile["building_observed_use_units"] != observed_total:
        raise ValueError("timed building source profile observed-use total mismatch")
    if "building_use_units" in base_profile and base_profile["building_use_units"] != min(credited_total, 24):
        raise ValueError("timed building source profile capped-use total mismatch")
    credited = min(weighted_before_global_cap, float(config["weighted_global_use_cap"]))
    return {
        "time_weighted_investment_use_units": per_investment_weighted,
        "time_weighted_use_units_before_global_cap": weighted_before_global_cap,
        "time_weighted_use_units": credited,
        "time_weighted_utility": credited / config["weighted_global_use_cap"],
    }


def profile_from_own_decisions(decisions, actor, config, *, terminal):
    validate_timed_building_config(config)
    base = profile_v1_from_own_decisions(decisions, actor, config["base_contract"], terminal=terminal)
    return dict(base, format="prism-building-timed-profile-v1", building_v1_profile=base,
                **_timed_utility(base, config))


def extract_timed_building_profile(game, config):
    validate_timed_building_config(config)
    if game.get("catalog_fingerprint") != BASE_CATALOG_FINGERPRINT:
        raise ValueError("timed building game public catalog fingerprint mismatch")
    profile = profile_from_own_decisions(game["decisions"], game["actor"], config,
                                         terminal=game.get("terminal"))
    return dict(profile, job_id=game["job_id"], actor=game["actor"],
                replay_sha256=game["replay_sha256"], sidecar_sha256=game["sidecar_sha256"])


def extract_timed_building_targets(games, config):
    validate_timed_building_config(config)
    if not isinstance(games, list) or not games:
        raise ValueError("nonempty timed building terminal games required")
    profiles = [extract_timed_building_profile(game, config) for game in games]
    targets = {(p["job_id"], p["actor"]): p["time_weighted_utility"] for p in profiles}
    if len(targets) != len(games):
        raise ValueError("duplicate timed building style actor coverage")
    n = len(profiles)
    total_investments = sum(p["early_lowvp_buys"] for p in profiles)
    summary = {
        "format": "prism-building-timed-targets-v1",
        "style_contract_sha256": canonical_hash(config),
        "games": profiles,
        "mean_time_weighted_utility": math.fsum(p["time_weighted_utility"] for p in profiles) / n,
        "mean_time_weighted_use_units": math.fsum(p["time_weighted_use_units"] for p in profiles) / n,
        "mean_time_weighted_use_units_before_global_cap":
            math.fsum(p["time_weighted_use_units_before_global_cap"] for p in profiles) / n,
        "mean_building_utility": math.fsum(p["building_utility"] for p in profiles) / n,
        "mean_early_bonus_auc12": math.fsum(p["early_bonus_auc12"] for p in profiles) / n,
        "mean_building_observed_use_units":
            math.fsum(p["building_observed_use_units"] for p in profiles) / n,
        "mean_building_use_units_before_global_cap":
            math.fsum(p["building_use_units_before_global_cap"] for p in profiles) / n,
        "investment_redemption_rate":
            sum(p["redeemed_investments"] for p in profiles) / total_investments if total_investments else None,
        "short_game_fraction": sum(p["shorter_than_early_window"] for p in profiles) / n,
        "redemption_horizon_censored_fraction":
            sum(p["redemption_horizon_censored"] for p in profiles) / n,
    }
    return targets, summary
