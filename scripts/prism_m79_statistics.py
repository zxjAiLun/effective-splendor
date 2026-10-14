"""Frozen M79 paired-endpoint statistics over canonical completed-game rows.

This module consumes rows only. It does not dispatch games or model inference.
Rows are dictionaries with candidate, opponent, seed, candidate_seat, and
candidate_score (0, 0.5, or 1). Missing rows are retained as missing endpoint
cells; they are never silently removed from a formal endpoint denominator.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
from numbers import Real
from typing import Any, Iterable

import numpy as np


ENDPOINT_ORDER = (
    "common_delta",
    "direct_parent",
    "latest-alpha",
    "latest-balance",
    "heuristic",
    "released-alpha",
)
COMMON_OPPONENTS = (
    "heuristic",
    "general",
    "balance",
    "alpha",
    "beta",
    "released-alpha",
)
COMMON_ACTORS = ("base", "a", "style-reference")
COVERAGE_OPPONENTS = ("latest-alpha", "latest-balance")
SEATS = (0, 1)
BOOTSTRAP_SAMPLES = 20_000
BOOTSTRAP_SEED = 79_029_999
LOWER_QUANTILE = 0.025
ORDINARY_QUANTILES = (0.025, 0.975)
_BATCH_SIZE = 256


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _seed_range(value: Any, label: str) -> tuple[int, int]:
    _require(isinstance(value, (list, tuple)) and len(value) == 2,
             f"invalid seed range: {label}")
    start, end = value
    _require(type(start) is int and type(end) is int and start <= end,
             f"invalid seed range: {label}")
    return start, end


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Check frozen statistical constants and internally consistent grids."""
    _require(isinstance(plan, dict) and plan.get("round") == "M79",
             "expected the M79 execution plan")
    try:
        ev = plan["evaluation"]
        stats = plan["statistics"]
        _require(ev["common_opponents"] == list(COMMON_OPPONENTS),
                 "M79 common-opponent order drift")
        _require(ev["common_actors"] == list(COMMON_ACTORS),
                 "M79 common actors drift")
        _require(ev["coverage_actors"] == ["base", "a"],
                 "M79 coverage actors drift")
        _require(ev["seats"] == [0, 1], "M79 candidate seat grid drift")
        _require(list(ev["common_seed_by_opponent"]) == list(COMMON_OPPONENTS),
                 "M79 common seed grid/order drift")
        _require(list(ev["coverage_seed_by_opponent"]) == list(COVERAGE_OPPONENTS),
                 "M79 coverage seed grid/order drift")
        _require(ev["direct"]["candidate"] == "a", "M79 direct candidate drift")

        common_ranges = {
            opponent: _seed_range(ev["common_seed_by_opponent"][opponent], opponent)
            for opponent in COMMON_OPPONENTS
        }
        coverage_ranges = {
            opponent: _seed_range(ev["coverage_seed_by_opponent"][opponent], opponent)
            for opponent in COVERAGE_OPPONENTS
        }
        direct_range = _seed_range(ev["direct"]["seed_range"], "direct_parent")
        all_seeds: set[int] = set()
        for label, (start, end) in [*common_ranges.items(), *coverage_ranges.items(),
                                    ("direct_parent", direct_range)]:
            seeds = set(range(start, end + 1))
            _require(not all_seeds.intersection(seeds), f"M79 seed-role overlap: {label}")
            all_seeds.update(seeds)

        common_blocks = {end - start + 1 for start, end in common_ranges.values()}
        coverage_blocks = {end - start + 1 for start, end in coverage_ranges.values()}
        _require(len(common_blocks) == 1 and len(coverage_blocks) == 1,
                 "M79 paired bootstrap grids must have equal block counts within each set")
        common_per_actor = 2 * sum(end - start + 1 for start, end in common_ranges.values())
        coverage_per_actor = 2 * sum(end - start + 1 for start, end in coverage_ranges.values())
        direct_games = 2 * (direct_range[1] - direct_range[0] + 1)
        _require(ev["common_games_per_actor"] == common_per_actor,
                 "M79 common game count does not match its seed grid")
        _require(ev["coverage_games_per_actor"] == coverage_per_actor,
                 "M79 coverage game count does not match its seed grid")
        _require(ev["direct"]["logical_attempts"] == direct_games,
                 "M79 direct game count does not match its seed grid")
        _require(ev["logical_attempts"] == (3 * common_per_actor +
                 2 * coverage_per_actor + direct_games),
                 "M79 evaluation total does not match its declared grid")

        _require(stats["bootstrap_samples"] == BOOTSTRAP_SAMPLES,
                 "M79 bootstrap sample count drift")
        _require(stats["bootstrap_seed"] == BOOTSTRAP_SEED,
                 "M79 bootstrap seed drift")
        _require(stats["rng"] == "numpy.random.Generator(numpy.random.PCG64(79029999))",
                 "M79 random generator drift")
        _require(stats["rng_endpoint_order"] == list(ENDPOINT_ORDER),
                 "M79 endpoint RNG order drift")
        _require(stats["quantile_method"] == "numpy.quantile(method=linear)",
                 "M79 quantile method drift")
        _require(stats["ordinary_ci"] == [0.025, 0.975],
                 "M79 ordinary interval drift")
        families = stats["families"]
        _require(families["enhancement"]["endpoints"] == ["common_delta", "direct_parent"]
                 and families["latest_coverage_retention"]["endpoints"] ==
                 ["latest-alpha", "latest-balance"]
                 and families["old_anchor_retention"]["endpoints"] ==
                 ["heuristic", "released-alpha"], "M79 endpoint family drift")
        for family in families.values():
            _require(family["family_alpha"] == 0.05
                     and family["one_sided_lower_quantile"] == LOWER_QUANTILE,
                     "M79 family gate quantile drift")
        _require(stats["enhancement"]["common_delta"] == {
            "point_min": 0.02, "lower_strictly_greater_than": 0},
            "M79 common enhancement gate drift")
        _require(stats["enhancement"]["direct_parent"] == {
            "point_min": 0.52, "lower_strictly_greater_than": 0.5},
            "M79 direct enhancement gate drift")
        _require(stats["retention"] == {
            "common_delta_lower_min": -0.05,
            "direct_parent_lower_min": 0.45,
            "latest_each_delta_lower_min": -0.03,
            "old_anchor_each_delta_lower_min": -0.03,
        }, "M79 retention gate drift")
    except (KeyError, TypeError) as exc:
        raise ValueError(f"invalid M79 statistics plan: {exc}") from exc

    return {
        "evaluation": ev,
        "statistics": stats,
        "common_ranges": common_ranges,
        "coverage_ranges": coverage_ranges,
        "direct_range": direct_range,
    }


def _legal_grid(plan_data: dict[str, Any]) -> dict[tuple[str, str], tuple[int, int]]:
    result: dict[tuple[str, str], tuple[int, int]] = {}
    for opponent, limits in plan_data["common_ranges"].items():
        for actor in COMMON_ACTORS:
            result[(actor, opponent)] = limits
    for opponent, limits in plan_data["coverage_ranges"].items():
        for actor in ("base", "a"):
            result[(actor, opponent)] = limits
    result[("a", "parent")] = plan_data["direct_range"]
    return result


def _validated_rows(rows: Iterable[dict[str, Any]], plan_data: dict[str, Any]):
    legal = _legal_grid(plan_data)
    scores: dict[tuple[str, str, int], list[float | None]] = {}
    descriptives: dict[tuple[str, str], list[list[float]]] = defaultdict(
        lambda: [[], []])
    for index, row in enumerate(rows):
        _require(isinstance(row, dict), f"row {index} must be an object")
        missing = {"candidate", "opponent", "seed", "candidate_seat", "candidate_score"} - row.keys()
        _require(not missing, f"row {index} missing canonical fields: {sorted(missing)}")
        candidate, opponent = row["candidate"], row["opponent"]
        _require(isinstance(candidate, str) and isinstance(opponent, str)
                 and (candidate, opponent) in legal,
                 f"row {index} has illegal candidate/opponent identity")
        seed, seat = row["seed"], row["candidate_seat"]
        _require(type(seed) is int, f"row {index} seed must be an integer")
        start, end = legal[(candidate, opponent)]
        _require(start <= seed <= end, f"row {index} seed is outside declared identity grid")
        _require(type(seat) is int and seat in SEATS,
                 f"row {index} candidate_seat must be 0 or 1")
        value = row["candidate_score"]
        _require(isinstance(value, Real) and not isinstance(value, bool)
                 and math.isfinite(float(value)) and float(value) in (0.0, 0.5, 1.0),
                 f"row {index} candidate_score must be 0, 0.5, or 1")
        key = (candidate, opponent, seed)
        if key not in scores:
            scores[key] = [None, None]
        _require(scores[key][seat] is None,
                 f"duplicate candidate/opponent/seed/seat row: {candidate}/{opponent}/{seed}/{seat}")
        scores[key][seat] = float(value)
        descriptives[(candidate, opponent)][seat].append(float(value))
    return scores, descriptives, legal


def _actor_values(scores, actor: str, opponent: str, seed: int) -> list[float | None]:
    return scores.get((actor, opponent, seed), [None, None])


def _delta_pair_data(scores, opponent: str, limits: tuple[int, int]):
    start, end = limits
    deltas: list[float | None] = []
    lower: list[float] = []
    upper: list[float] = []
    candidate_means: list[float | None] = []
    observed_rows = 0
    complete_blocks = 0
    for seed in range(start, end + 1):
        candidate = _actor_values(scores, "a", opponent, seed)
        base = _actor_values(scores, "base", opponent, seed)
        observed_rows += sum(value is not None for value in candidate + base)
        c_obs = [value for value in candidate if value is not None]
        b_obs = [value for value in base if value is not None]
        candidate_means.append(sum(c_obs) / 2 if len(c_obs) == 2 else None)
        if len(c_obs) == 2 and len(b_obs) == 2:
            deltas.append(sum(c_obs) / 2 - sum(b_obs) / 2)
            complete_blocks += 1
        else:
            deltas.append(None)

        # Missing game scores are bounded at 0/1; each environment seed first
        # averages its two seats, preserving the frozen paired-block unit.
        c_min = (sum(c_obs) + 0.0 * (2 - len(c_obs))) / 2
        c_max = (sum(c_obs) + 1.0 * (2 - len(c_obs))) / 2
        b_min = (sum(b_obs) + 0.0 * (2 - len(b_obs))) / 2
        b_max = (sum(b_obs) + 1.0 * (2 - len(b_obs))) / 2
        lower.append(c_min - b_max)
        upper.append(c_max - b_min)
    return {
        "deltas": deltas,
        "candidate_means": candidate_means,
        "lower": lower,
        "upper": upper,
        "observed_rows": observed_rows,
        "planned_rows": 4 * (end - start + 1),
        "complete_blocks": complete_blocks,
        "planned_blocks": end - start + 1,
    }


def _direct_data(scores, limits: tuple[int, int]):
    start, end = limits
    values: list[float | None] = []
    lower: list[float] = []
    upper: list[float] = []
    observed_rows = 0
    complete_blocks = 0
    for seed in range(start, end + 1):
        seats = _actor_values(scores, "a", "parent", seed)
        observed = [value for value in seats if value is not None]
        observed_rows += len(observed)
        values.append(sum(observed) / 2 if len(observed) == 2 else None)
        complete_blocks += len(observed) == 2
        lower.append(sum(observed) / 2)
        upper.append((sum(observed) + (2 - len(observed))) / 2)
    return {
        "values": values,
        "lower": lower,
        "upper": upper,
        "observed_rows": observed_rows,
        "planned_rows": 2 * (end - start + 1),
        "complete_blocks": complete_blocks,
        "planned_blocks": end - start + 1,
    }


def _interval(bootstrap: np.ndarray) -> dict[str, Any]:
    lower, upper = np.quantile(bootstrap, ORDINARY_QUANTILES, method="linear")
    return {
        "ordinary_95": {"lower": float(lower), "upper": float(upper)},
        "family_one_sided_lower": float(lower),
        "lower_quantile": LOWER_QUANTILE,
        "samples": BOOTSTRAP_SAMPLES,
    }


def _bootstrap_common(rng: np.random.Generator, groups: list[np.ndarray]) -> np.ndarray:
    blocks = len(groups[0])
    result = np.empty(BOOTSTRAP_SAMPLES, dtype=np.float64)
    for start in range(0, BOOTSTRAP_SAMPLES, _BATCH_SIZE):
        size = min(_BATCH_SIZE, BOOTSTRAP_SAMPLES - start)
        # C-order draw order is replicate, then opponent, then sampled block.
        indices = rng.integers(0, blocks, size=(size, len(groups), blocks), dtype=np.int64)
        means = np.empty((size, len(groups)), dtype=np.float64)
        for opponent_index, values in enumerate(groups):
            means[:, opponent_index] = values[indices[:, opponent_index, :]].mean(axis=1)
        result[start:start + size] = means.mean(axis=1)
    return result


def _bootstrap_scalar(rng: np.random.Generator, values: np.ndarray) -> np.ndarray:
    blocks = len(values)
    result = np.empty(BOOTSTRAP_SAMPLES, dtype=np.float64)
    for start in range(0, BOOTSTRAP_SAMPLES, _BATCH_SIZE):
        size = min(_BATCH_SIZE, BOOTSTRAP_SAMPLES - start)
        indices = rng.integers(0, blocks, size=(size, blocks), dtype=np.int64)
        result[start:start + size] = values[indices].mean(axis=1)
    return result


def _consume_incomplete(rng: np.random.Generator, *, common: bool,
                        blocks: int, opponents: int = 1) -> None:
    """Advance the frozen stream as if this endpoint had a full grid."""
    for start in range(0, BOOTSTRAP_SAMPLES, _BATCH_SIZE):
        size = min(_BATCH_SIZE, BOOTSTRAP_SAMPLES - start)
        shape = ((size, opponents, blocks) if common else (size, blocks))
        rng.integers(0, blocks, size=shape, dtype=np.int64)


def _gate(complete: bool, passed: bool | None) -> str:
    if not complete:
        return "INCOMPLETE"
    return "PASS" if passed else "FAIL"


def _endpoint_result(name: str, data: dict[str, Any], *, estimate: float | None,
                     completed_only: float | None, lower_bound: float, upper_bound: float,
                     interval: dict[str, Any] | None, complete: bool,
                     per_opponent: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    planned = data["planned_rows"]
    observed = data["observed_rows"]
    completeness = {
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "planned_rows": planned,
        "observed_rows": observed,
        "missing_rows": planned - observed,
        "planned_seed_blocks": data["planned_blocks"],
        "complete_paired_seed_blocks": data["complete_blocks"],
    }
    if per_opponent is not None:
        completeness["by_opponent"] = per_opponent
    return {
        "name": name,
        "status": completeness["status"],
        "completeness": completeness,
        "estimate": estimate,
        "interval": interval,
        "diagnostic_completed_only": {
            "estimate": completed_only,
            "basis": "complete paired seed blocks only; descriptive and never a formal gate",
        },
        "worst_best_point_bounds": {
            "worst": lower_bound,
            "best": upper_bound,
            "basis": "missing game half-scores assigned 0/1 after averaging the two seats per seed",
        },
        "gates": {},
    }


def _comparison_completeness(opponent: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "opponent": opponent,
        "planned_rows": data["planned_rows"],
        "observed_rows": data["observed_rows"],
        "missing_rows": data["planned_rows"] - data["observed_rows"],
        "planned_seed_blocks": data["planned_blocks"],
        "complete_paired_seed_blocks": data["complete_blocks"],
    }


def _make_common_endpoint(scores, plan_data):
    by_opponent = []
    groups: list[np.ndarray] = []
    lower_means = []
    upper_means = []
    complete_only_means = []
    planned_rows = observed_rows = planned_blocks = complete_blocks = 0
    all_complete = True
    for opponent in COMMON_OPPONENTS:
        limits = plan_data["common_ranges"][opponent]
        data = _delta_pair_data(scores, opponent, limits)
        blocks = data["planned_blocks"]
        valid = [value for value in data["deltas"] if value is not None]
        complete = len(valid) == blocks
        all_complete &= complete
        by_opponent.append(_comparison_completeness(opponent, data))
        planned_rows += data["planned_rows"]
        observed_rows += data["observed_rows"]
        planned_blocks += blocks
        complete_blocks += data["complete_blocks"]
        if complete:
            groups.append(np.asarray(data["deltas"], dtype=np.float64))
        else:
            # Keep six-opponent equal weighting for diagnostic point bounds.
            groups.append(np.asarray([value if value is not None else 0.0
                                      for value in data["deltas"]], dtype=np.float64))
        lower_means.append(float(np.mean(data["lower"])))
        upper_means.append(float(np.mean(data["upper"])))
        complete_only_means.append(float(np.mean(valid)) if valid else None)

    diagnostic = (float(np.mean(complete_only_means))
                  if all(value is not None for value in complete_only_means) else None)
    complete = all_complete
    result_data = {
        "planned_rows": planned_rows,
        "observed_rows": observed_rows,
        "planned_blocks": planned_blocks,
        "complete_blocks": complete_blocks,
    }
    result = _endpoint_result(
        "common_delta", result_data,
        estimate=diagnostic if complete else None,
        completed_only=diagnostic,
        lower_bound=float(np.mean(lower_means)),
        upper_bound=float(np.mean(upper_means)),
        interval=None,
        complete=complete,
        per_opponent=by_opponent,
    )
    return result, groups, complete


def _make_delta_endpoint(name, opponent, scores, limits):
    data = _delta_pair_data(scores, opponent, limits)
    valid = [value for value in data["deltas"] if value is not None]
    complete = len(valid) == data["planned_blocks"]
    result = _endpoint_result(
        name, data,
        estimate=float(np.mean(valid)) if complete else None,
        completed_only=float(np.mean(valid)) if valid else None,
        lower_bound=float(np.mean(data["lower"])),
        upper_bound=float(np.mean(data["upper"])),
        interval=None,
        complete=complete,
    )
    return result, np.asarray(valid, dtype=np.float64), data["planned_blocks"], complete


def _make_direct_endpoint(scores, limits):
    data = _direct_data(scores, limits)
    valid = [value for value in data["values"] if value is not None]
    complete = len(valid) == data["planned_blocks"]
    result = _endpoint_result(
        "direct_parent", data,
        estimate=float(np.mean(valid)) if complete else None,
        completed_only=float(np.mean(valid)) if valid else None,
        lower_bound=float(np.mean(data["lower"])),
        upper_bound=float(np.mean(data["upper"])),
        interval=None,
        complete=complete,
    )
    return result, np.asarray(valid, dtype=np.float64), data["planned_blocks"], complete


def _decision_status(states: list[str]) -> str:
    if any(state == "INCOMPLETE" for state in states):
        return "INCOMPLETE"
    return "PASS" if all(state == "PASS" for state in states) else "FAIL"


def _set_endpoint_gates(endpoints, plan_data):
    stats = plan_data["statistics"]
    common = endpoints["common_delta"]
    direct = endpoints["direct_parent"]
    for endpoint in (common, direct):
        complete = endpoint["status"] == "COMPLETE"
        lower = (endpoint["interval"]["family_one_sided_lower"]
                 if complete else None)
        point = endpoint["estimate"]
        if endpoint["name"] == "common_delta":
            spec = stats["enhancement"]["common_delta"]
            endpoint["gates"]["enhancement"] = _gate(
                complete, point >= spec["point_min"] and
                lower > spec["lower_strictly_greater_than"] if complete else None)
            threshold = stats["retention"]["common_delta_lower_min"]
        else:
            spec = stats["enhancement"]["direct_parent"]
            endpoint["gates"]["enhancement"] = _gate(
                complete, point >= spec["point_min"] and
                lower > spec["lower_strictly_greater_than"] if complete else None)
            threshold = stats["retention"]["direct_parent_lower_min"]
        endpoint["gates"]["retention"] = _gate(
            complete, lower >= threshold if complete else None)

    for name, threshold in [
        ("latest-alpha", stats["retention"]["latest_each_delta_lower_min"]),
        ("latest-balance", stats["retention"]["latest_each_delta_lower_min"]),
        ("heuristic", stats["retention"]["old_anchor_each_delta_lower_min"]),
        ("released-alpha", stats["retention"]["old_anchor_each_delta_lower_min"]),
    ]:
        endpoint = endpoints[name]
        complete = endpoint["status"] == "COMPLETE"
        lower = endpoint["interval"]["family_one_sided_lower"] if complete else None
        endpoint["gates"]["retention"] = _gate(
            complete, lower >= threshold if complete else None)


def _grid_completeness(plan_data, scores):
    records = []
    legal = _legal_grid(plan_data)
    for (actor, opponent), (start, end) in legal.items():
        planned = (end - start + 1) * 2
        observed = sum(value is not None
                       for seed in range(start, end + 1)
                       for value in _actor_values(scores, actor, opponent, seed))
        records.append({
            "candidate": actor,
            "opponent": opponent,
            "role": "descriptive_reference_only" if actor == "style-reference"
                    else ("direct_parent" if opponent == "parent" else "competitive_or_coverage"),
            "planned_rows": planned,
            "observed_rows": observed,
            "missing_rows": planned - observed,
            "status": "COMPLETE" if observed == planned else "INCOMPLETE",
        })
    return records


def _wdl(values: list[float]) -> dict[str, Any]:
    counts = Counter(values)
    games = len(values)
    return {
        "games": games,
        "wins": counts[1.0],
        "draws": counts[0.5],
        "losses": counts[0.0],
        "win_rate": counts[1.0] / games if games else None,
        "half_score": (counts[1.0] + 0.5 * counts[0.5]) / games if games else None,
    }


def _opponent_descriptives(descriptives, legal):
    output = []
    for (candidate, opponent), limits in legal.items():
        groups = descriptives.get((candidate, opponent), [[], []])
        start, end = limits
        planned = 2 * (end - start + 1)
        all_values = groups[0] + groups[1]
        output.append({
            "candidate": candidate,
            "opponent": opponent,
            "role": "descriptive_reference_only" if candidate == "style-reference"
                    else ("direct_parent" if opponent == "parent" else "competitive_or_coverage"),
            "planned_games": planned,
            "observed_games": len(all_values),
            "status": "COMPLETE" if len(all_values) == planned else "INCOMPLETE",
            "overall": _wdl(all_values),
            "by_candidate_seat": {
                str(seat): _wdl(groups[seat]) for seat in SEATS
            },
            "scope": "descriptive W/D/L; excluded from paired endpoint gates",
        })
    return output


def analyze(plan: dict[str, Any], rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Calculate the six frozen M79 endpoints and independent opponent W/D/L.

    Incomplete endpoints have ``estimate`` and ``interval`` set to ``None``;
    completed-only values are explicitly diagnostic. Their formal gates stay
    INCOMPLETE. Missing-score 0/1 bounds are points only, never imputed results.
    """
    plan_data = _validate_plan(plan)
    scores, descriptives, legal = _validated_rows(rows, plan_data)

    endpoints: dict[str, dict[str, Any]] = {}
    bootstrap_specs: dict[str, tuple[str, Any, bool, int]] = {}
    common, common_groups, common_complete = _make_common_endpoint(scores, plan_data)
    endpoints["common_delta"] = common
    common_blocks = plan_data["common_ranges"][COMMON_OPPONENTS[0]][1] - \
        plan_data["common_ranges"][COMMON_OPPONENTS[0]][0] + 1
    bootstrap_specs["common_delta"] = ("common", common_groups, common_complete, common_blocks)

    direct, direct_values, direct_blocks, direct_complete = _make_direct_endpoint(
        scores, plan_data["direct_range"])
    endpoints["direct_parent"] = direct
    bootstrap_specs["direct_parent"] = ("scalar", direct_values, direct_complete, direct_blocks)

    for opponent in ("latest-alpha", "latest-balance", "heuristic", "released-alpha"):
        limits = (plan_data["coverage_ranges"][opponent]
                  if opponent in plan_data["coverage_ranges"]
                  else plan_data["common_ranges"][opponent])
        endpoint, values, blocks, complete = _make_delta_endpoint(
            opponent, opponent, scores, limits)
        endpoints[opponent] = endpoint
        bootstrap_specs[opponent] = ("scalar", values, complete, blocks)

    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    for name in ENDPOINT_ORDER:
        kind, data, complete, blocks = bootstrap_specs[name]
        if complete:
            distribution = (_bootstrap_common(rng, data) if kind == "common"
                            else _bootstrap_scalar(rng, data))
            endpoints[name]["interval"] = _interval(distribution)
        else:
            _consume_incomplete(rng, common=(kind == "common"), blocks=blocks,
                                opponents=len(COMMON_OPPONENTS) if kind == "common" else 1)

    _set_endpoint_gates(endpoints, plan_data)

    enhancement_status = _decision_status([
        endpoints["common_delta"]["gates"]["enhancement"],
        endpoints["direct_parent"]["gates"]["enhancement"],
    ])
    latest_status = _decision_status([
        endpoints[name]["gates"]["retention"] for name in ("latest-alpha", "latest-balance")
    ])
    old_status = _decision_status([
        endpoints[name]["gates"]["retention"] for name in ("heuristic", "released-alpha")
    ])
    retention_status = _decision_status([
        endpoints[name]["gates"]["retention"] for name in ENDPOINT_ORDER
    ])
    recommendation = _decision_status([enhancement_status, latest_status, old_status,
                                        retention_status])
    failed = [name for name, endpoint in endpoints.items()
              if "FAIL" in endpoint["gates"].values()]
    incomplete = [name for name, endpoint in endpoints.items()
                  if endpoint["status"] == "INCOMPLETE"]

    return {
        "format": "prism-m79-statistics-v1",
        "round": "M79",
        "bootstrap": {
            "samples": BOOTSTRAP_SAMPLES,
            "seed": BOOTSTRAP_SEED,
            "generator": "PCG64",
            "endpoint_order": list(ENDPOINT_ORDER),
            "quantile_method": "linear",
            "ordinary_interval": [0.025, 0.975],
            "family_one_sided_lower_quantile": LOWER_QUANTILE,
            "common_resampling": "per replicate, each common opponent in declared order; draw paired seed blocks with replacement and average opponent means equally",
        },
        "endpoints": endpoints,
        "families": {
            "enhancement": {"status": enhancement_status,
                            "endpoints": ["common_delta", "direct_parent"]},
            "latest_coverage_retention": {"status": latest_status,
                                           "endpoints": ["latest-alpha", "latest-balance"]},
            "old_anchor_retention": {"status": old_status,
                                      "endpoints": ["heuristic", "released-alpha"]},
        },
        "retention": {
            "status": retention_status,
            "endpoints": list(ENDPOINT_ORDER),
        },
        "mainline_recommendation": {
            "status": recommendation,
            "eligible": True if recommendation == "PASS" else False if recommendation == "FAIL" else None,
            "failed_endpoints": failed,
            "incomplete_endpoints": incomplete,
            "meaning": "PASS recommends the candidate as the next mainline parent only; it does not authorize release, default replacement, or deployment",
        },
        "grid_completeness": _grid_completeness(plan_data, scores),
        "opponent_descriptives": _opponent_descriptives(descriptives, legal),
    }
