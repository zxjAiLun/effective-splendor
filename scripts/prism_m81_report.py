"""M81 raw-evidence, frozen-statistics, and descriptive-profile report stage."""
from __future__ import annotations

from collections import Counter, defaultdict
import html
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAN_REL = Path("benchmarks/m81-anchor-coverage.execution-plan.json")
RESULT_REL = Path("benchmarks/m81-anchor-coverage.result.json")
PROFILE_REL = Path("benchmarks/m81-anchor-coverage.profile.json")
EVIDENCE_REL = Path("docs/prism/m81-anchor-coverage-evidence.md")
READING_REL = Path("docs/prism/m81-anchor-coverage-reading.html")
RECEIPT_REL = Path("benchmarks/m81-anchor-coverage.report-receipt.json")
METHOD_ORDER = ("B-A-targets", "B-A-eight-pool", "B-A-latest-alpha",
                "B-A-latest-balance")
ENDPOINT_ORDER = ("B-A-targets", "B-A-eight-pool", "B-A-latest-alpha",
                  "B-A-latest-balance", "B-base-common", "B-parent",
                  "B-base-heuristic", "B-base-balance", "B-base-released-alpha",
                  "B-base-latest-alpha", "B-base-latest-balance")
COMMON = ("heuristic", "general", "balance", "alpha", "beta", "released-alpha")
EIGHT = COMMON + ("latest-alpha", "latest-balance")
BOOTSTRAP_SAMPLES = 20000
BOOTSTRAP_BATCH = 256
PROFILE_PROJECTOR_SHA256 = "1c605d536a4e2d05be23142ba4115c60c7445ea9400a524ec474cec50995b58f"
PROFILE_SOURCE_SHA256 = {
    "Cargo.lock": "21e68ebdbfddc74215091af4091e387c56b4d9d304e6b1ad2fee3339920b8e96",
    "crates/splendor-cli/examples/prism_building_projection.rs": "ad08c55dd0cf0e22371352614db9104105b62bf92893b07450b4cb5c4ea7817b",
    "crates/splendor-catalog/src/cards.rs": "82d52156abaf8699975e7b99647881437de4b4a683f83caf17b60e558a2fe21b",
    "training/prism_portable/engine/ppo/building.py": "7b57fd996ec497b8e7332e62f8a466e4a4d04f77a883b5c768c3f59b4399d8b8",
}


def _root(root: str | Path | None) -> Path:
    global ROOT
    if root is not None:
        ROOT = Path(root).resolve()
    return ROOT


def _common():
    from training.prism_portable.common import digest, read, write
    return read, write, digest


def _runtime(root: Path):
    sys.path.insert(0, str(root))
    from scripts import prism_m81_run as runtime
    runtime.ROOT = root
    plan, execution = runtime.verify()
    runtime.install_resource_mode()
    from scripts import prism_bounded_eval as bounded
    bounded.ROOT = root
    bounded.legacy.ROOT = root
    remaining = runtime.bounds()
    if not isinstance(remaining, (int, float)) or not math.isfinite(remaining) or remaining <= 0:
        raise ValueError("M81 report requires a finite positive resource watchdog")
    return runtime, plan, execution, bounded


def _identities(shard: dict[str, Any]):
    for seed in shard["seeds"]:
        for seat in (0, 1):
            yield shard["actor"], shard["opponent"], seed, seat


def _missing(actor: str, opponent: str, seed: int, seat: int, shard: str, reason: str):
    return {"candidate": actor, "opponent": opponent, "seed": seed,
            "candidate_seat": seat, "shard": shard, "reason": reason}


def _collect(root: Path, plan: dict[str, Any], bounded):
    from scripts import prism_m81_evaluate as evaluator
    from training.prism_portable.common import digest, read
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    caps: list[dict[str, Any]] = []
    shards: list[dict[str, Any]] = []
    seen = set()
    for spec in evaluator._planned_shards(plan):
        output = root / "evaluation" / spec["label"]
        manifest = output / "manifest.json"
        ledger_path = output / "ledger.json"
        state, entries, reason = "NO_LEDGER_NOT_DISPATCHED", {}, "NO_LEDGER_NOT_DISPATCHED"
        if manifest.exists() and ledger_path.exists():
            validated, policy = bounded.load_bound(output)
            cfg = validated["config"]
            if (list(cfg["seeds"]) != spec["seeds"] or
                    list(cfg["candidates"]) != [spec["actor"]] or
                    list(cfg["opponents"]) != [spec["opponent"]]):
                raise ValueError(f"M81 shard config identity drift: {spec['label']}")
            inspection = bounded.inspect(output)
            ledger = read(ledger_path)
            if ledger.get("manifest_sha256") != digest(manifest):
                raise ValueError(f"M81 ledger manifest binding drift: {spec['label']}")
            state, entries = ledger["execution_state"], ledger.get("entries", {})
            reason = ledger.get("stop_reason", state)
            if state == "FINISHED" and len(entries) != spec["planned_games"]:
                raise ValueError(f"M81 FINISHED shard has missing game entries: {spec['label']}")
            shard_status = inspection
        else:
            shard_status = {"execution_state": state, "planned_games": spec["planned_games"],
                            "completed_games": 0, "truncated_games": 0}
            if output.exists():
                reason = "SHARD_WITHOUT_PUBLISHED_LEDGER"

        for actor, opponent, seed, seat in _identities(spec):
            key = bounded.fixed._game_key(actor, opponent, seed, seat)
            entry = entries.get(key)
            if entry is None:
                miss_reason = ("NOT_DISPATCHED_AFTER_CAP_LIMIT" if reason == "SCIENTIFIC_CAP_BUDGET"
                               else reason if state != "RUNNING" else "RUNNING_LEDGER_ENTRY_MISSING")
                missing.append(_missing(actor, opponent, seed, seat, spec["label"], miss_reason))
                continue
            if entry.get("state") == "DISPATCHED":
                missing.append(_missing(actor, opponent, seed, seat, spec["label"],
                                         "DISPATCHED_WITHOUT_TERMINAL_COMMIT"))
                continue
            if entry.get("kind") == "PLY_CAP_TRUNCATED":
                cap = _missing(actor, opponent, seed, seat, spec["label"], "PLY_CAP_TRUNCATED")
                cap["completed_plies"] = entry.get("metrics", {}).get("completed_plies")
                caps.append(cap)
                missing.append(cap)
                continue
            if entry.get("state") == "RETAINED_FAILURE":
                missing.append(_missing(actor, opponent, seed, seat, spec["label"],
                                         entry.get("kind", "RETAINED_FAILURE")))
                continue
            if entry.get("state") != "COMPLETED":
                raise ValueError(f"unknown M81 ledger row state: {spec['label']}/{key}")
            row = entry["row"]
            identity = (row.get("candidate"), row.get("opponent"), row.get("seed"),
                        row.get("candidate_seat"))
            if identity != (actor, opponent, seed, seat) or identity in seen:
                raise ValueError(f"M81 completed row identity mismatch/duplicate: {identity}")
            seen.add(identity)
            game_dir = output / "games" / actor / opponent / f"seed-{seed}-seat-{seat}"
            replay = game_dir / "replay.json"
            if not replay.is_file():
                raise ValueError(f"M81 completed game has no saved replay: {key}")
            rows.append({**row, "metrics": entry.get("metrics"),
                         "replay_path": str(replay), "replay_sha256": digest(replay),
                         "shard": spec["label"]})
        shards.append({"label": spec["label"], "candidate": spec["actor"],
                       "opponent": spec["opponent"], "seed_start": spec["seed_start"],
                       "seed_end": spec["seed_end"], "state": state,
                       "planned_games": spec["planned_games"],
                       "completed_games": sum(1 for row in rows if row["shard"] == spec["label"]),
                       "truncated_games": sum(1 for row in caps if row["shard"] == spec["label"]),
                       "missing_games": sum(1 for row in missing if row["shard"] == spec["label"]),
                       "stop_reason": reason, "manifest_sha256": digest(manifest) if manifest.exists() else None,
                       "ledger_sha256": digest(ledger_path) if ledger_path.exists() else None,
                       "inspection": shard_status})
    return rows, missing, caps, shards


def _score_map(rows: list[dict[str, Any]]):
    result = {}
    for row in rows:
        score = row.get("candidate_score")
        if type(score) not in (int, float) or score not in (0, 0.5, 1):
            raise ValueError("M81 raw row has invalid half-score")
        key = (row["candidate"], row["opponent"], row["seed"], row["candidate_seat"])
        if key in result:
            raise ValueError(f"duplicate M81 score identity: {key}")
        result[key] = float(score)
    return result


def _pair_blocks(scores, left: str, right: str, opponent: str,
                 seed_range: tuple[int, int]):
    low, high = seed_range
    values = []
    complete = True
    missing_blocks = []
    for seed in range(low, high + 1):
        left_values = [scores.get((left, opponent, seed, seat)) for seat in (0, 1)]
        right_values = [scores.get((right, opponent, seed, seat)) for seat in (0, 1)]
        if any(value is None for value in (*left_values, *right_values)):
            complete = False
            missing_blocks.append(seed)
            continue
        values.append(sum(left_values) / 2 - sum(right_values) / 2)
    return values, complete, missing_blocks


def _absolute_blocks(scores, actor: str, opponent: str, seed_range: tuple[int, int]):
    values = []
    missing_blocks = []
    for seed in range(seed_range[0], seed_range[1] + 1):
        seat_values = [scores.get((actor, opponent, seed, seat)) for seat in (0, 1)]
        if any(value is None for value in seat_values):
            missing_blocks.append(seed)
        else:
            values.append(sum(seat_values) / 2)
    return values, not missing_blocks, missing_blocks


def _group_data(scores, opponents, ranges, left, right):
    groups, details, complete = [], [], True
    planned = observed = 0
    for opponent in opponents:
        limits = ranges[opponent]
        values, ok, missing_blocks = _pair_blocks(scores, left, right, opponent, tuple(limits))
        n = limits[1] - limits[0] + 1
        planned += n
        observed += len(values)
        complete &= ok
        groups.append(values)
        details.append({"opponent": opponent, "planned_seed_blocks": n,
                        "complete_seed_blocks": len(values), "missing_seed_blocks": missing_blocks,
                        "estimate_if_complete": sum(values) / len(values) if values else None})
    return groups, complete, {"planned_seed_blocks": planned, "complete_seed_blocks": observed,
                              "missing_seed_blocks": planned - observed, "by_opponent": details}


def _endpoint_builders(scores, plan):
    e = plan["evaluation"]
    ranges = e["seed_by_opponent"]
    direct_range = tuple(e["direct_parent"]["seed_range"])
    specs = {}

    def grouped(name, opponents, lowq, kind="delta"):
        groups, complete, coverage = _group_data(scores, opponents, ranges, "B", "A" if kind == "delta" else "base")
        if kind == "absolute":
            # _group_data's paired helper is intentionally not used for the direct
            # parent endpoint; it has its own larger 512-seed cohort below.
            raise AssertionError("absolute endpoint construction error")
        specs[name] = {"groups": groups, "complete": complete, "coverage": coverage,
                       "lower_quantile": lowq, "kind": "grouped"}

    stat = plan["statistics"]
    method = stat["method_screen"]
    target_opponents = method["primary"]["targets"]
    grouped("B-A-targets", target_opponents, method["primary"]["lower_quantile"])
    grouped("B-A-eight-pool", list(EIGHT), method["retention_family"]["one_sided_lower_quantile"])
    for opponent in ("latest-alpha", "latest-balance"):
        grouped("B-A-" + opponent, [opponent], method["retention_family"]["one_sided_lower_quantile"])

    # Base comparisons are B minus M75. Every opponent resamples its own seed
    # blocks; opponent means then receive equal weight.
    groups, complete, coverage = _group_data(scores, COMMON, ranges, "B", "base")
    specs["B-base-common"] = {"groups": groups, "complete": complete, "coverage": coverage,
                               "lower_quantile": stat["mainline_candidate"]["enhancement_family"]["lower_quantile"],
                               "kind": "grouped"}
    direct, direct_complete, direct_missing = _absolute_blocks(scores, "B", "parent", direct_range)
    specs["B-parent"] = {"groups": [direct], "complete": direct_complete,
                         "coverage": {"planned_seed_blocks": len(range(*_inclusive(direct_range))),
                                      "complete_seed_blocks": len(direct),
                                      "missing_seed_blocks": len(direct_missing),
                                      "missing_seeds": direct_missing},
                         "lower_quantile": stat["mainline_candidate"]["enhancement_family"]["lower_quantile"],
                         "kind": "scalar_absolute"}
    for opponent in ("heuristic", "balance", "released-alpha", "latest-alpha", "latest-balance"):
        lowq = (stat["mainline_candidate"]["anchor_family"]["lower_quantile"]
                if opponent in stat["mainline_candidate"]["anchor_family"]["opponents"] else
                stat["mainline_candidate"]["coverage_family"]["lower_quantile"])
        groups, complete, coverage = _group_data(scores, [opponent], ranges, "B", "base")
        specs["B-base-" + opponent] = {"groups": groups, "complete": complete,
                                     "coverage": coverage, "lower_quantile": lowq,
                                     "kind": "grouped"}
    return specs


def _inclusive(limits):
    return limits[0], limits[1] + 1


def _bootstrap_grouped(rng, groups):
    import numpy as np
    n = len(groups[0])
    samples = np.empty(BOOTSTRAP_SAMPLES, dtype=np.float64)
    arrays = [np.asarray(group, dtype=np.float64) for group in groups]
    for start in range(0, BOOTSTRAP_SAMPLES, BOOTSTRAP_BATCH):
        size = min(BOOTSTRAP_BATCH, BOOTSTRAP_SAMPLES - start)
        index = rng.integers(0, n, size=(size, len(arrays), n), dtype=np.int64)
        means = np.empty((size, len(arrays)), dtype=np.float64)
        for i, values in enumerate(arrays):
            means[:, i] = values[index[:, i, :]].mean(axis=1)
        samples[start:start + size] = means.mean(axis=1)
    return samples


def _consume_incomplete(rng, spec):
    import numpy as np
    blocks = max((len(group) for group in spec["groups"]), default=1)
    # Draw the frozen planned shape so later endpoints retain a stable PCG64 stream.
    if spec["kind"] == "scalar_absolute":
        blocks = max(1, spec["coverage"]["planned_seed_blocks"])
        for start in range(0, BOOTSTRAP_SAMPLES, BOOTSTRAP_BATCH):
            size = min(BOOTSTRAP_BATCH, BOOTSTRAP_SAMPLES - start)
            rng.integers(0, blocks, size=(size, blocks), dtype=np.int64)
        return
    planned = max((row["planned_seed_blocks"] for row in spec["coverage"].get("by_opponent", [])), default=blocks)
    groups = max(1, len(spec["groups"]))
    for start in range(0, BOOTSTRAP_SAMPLES, BOOTSTRAP_BATCH):
        size = min(BOOTSTRAP_BATCH, BOOTSTRAP_SAMPLES - start)
        rng.integers(0, planned, size=(size, groups, planned), dtype=np.int64)


def _statistics(rows, plan):
    import numpy as np
    scores = _score_map(rows)
    specs = _endpoint_builders(scores, plan)
    rng = np.random.Generator(np.random.PCG64(plan["statistics"]["bootstrap_seed"]))
    endpoints = {}
    for name in ENDPOINT_ORDER:
        spec = specs[name]
        groups = spec["groups"]
        complete = bool(spec["complete"] and groups and all(groups))
        estimate = (sum(sum(group) / len(group) for group in groups) / len(groups)
                    if complete else None)
        diagnostic = (sum(sum(group) / len(group) for group in groups if group) /
                      sum(bool(group) for group in groups) if any(groups) else None)
        interval = None
        if complete:
            sample = _bootstrap_grouped(rng, groups)
            lo, hi = np.quantile(sample, [0.025, 0.975], method="linear")
            lower = float(np.quantile(sample, spec["lower_quantile"], method="linear"))
            interval = {"ordinary_95": [float(lo), float(hi)],
                        "family_one_sided_lower": lower,
                        "lower_quantile": spec["lower_quantile"],
                        "samples": BOOTSTRAP_SAMPLES, "generator": "PCG64"}
        else:
            _consume_incomplete(rng, spec)
        endpoints[name] = {"name": name, "status": "COMPLETE" if complete else "INCOMPLETE",
                           "estimate": estimate, "interval": interval,
                           "diagnostic_completed_only": diagnostic,
                           "coverage": spec["coverage"], "gates": {}}

    def set_gate(name, gate, passed):
        endpoint = endpoints[name]
        endpoint["gates"][gate] = ("INCOMPLETE" if endpoint["status"] != "COMPLETE"
                                    else "PASS" if passed else "FAIL")

    ms = plan["statistics"]["method_screen"]
    target = endpoints["B-A-targets"]
    set_gate("B-A-targets", "target_gain", target["estimate"] is not None and
             target["estimate"] >= ms["primary"]["point_min"] and
             target["interval"]["family_one_sided_lower"] > ms["primary"]["lower_strictly_greater_than"]
             if target["status"] == "COMPLETE" else None)
    limits = dict(zip(ms["retention_family"]["endpoints"], ms["retention_family"]["lower_min"]))
    for name, minimum in limits.items():
        endpoint = endpoints[name]
        set_gate(name, "method_retention", endpoint["interval"]["family_one_sided_lower"] >= minimum
                 if endpoint["status"] == "COMPLETE" else None)
    method_state = _family_state([endpoints[name]["gates"].get(
        "target_gain" if name == "B-A-targets" else "method_retention") for name in METHOD_ORDER])

    main = plan["statistics"]["mainline_candidate"]
    common = endpoints["B-base-common"]
    set_gate("B-base-common", "enhancement", common["estimate"] is not None and
             common["estimate"] >= main["enhancement_family"]["common_delta_point_min"] and
             common["interval"]["family_one_sided_lower"] > main["enhancement_family"]["common_delta_lower_gt"]
             if common["status"] == "COMPLETE" else None)
    set_gate("B-base-common", "retention", common["interval"]["family_one_sided_lower"] >=
             main["additional_retention"]["common_delta_lower_min"]
             if common["status"] == "COMPLETE" else None)
    direct = endpoints["B-parent"]
    set_gate("B-parent", "enhancement", direct["estimate"] is not None and
             direct["estimate"] >= main["enhancement_family"]["direct_parent_point_min"] and
             direct["interval"]["family_one_sided_lower"] > main["enhancement_family"]["direct_parent_lower_gt"]
             if direct["status"] == "COMPLETE" else None)
    set_gate("B-parent", "retention", direct["interval"]["family_one_sided_lower"] >=
             main["additional_retention"]["direct_parent_lower_min"]
             if direct["status"] == "COMPLETE" else None)
    for opponent in main["anchor_family"]["opponents"]:
        name = "B-base-" + opponent
        endpoint = endpoints[name]
        set_gate(name, "anchor_retention", endpoint["interval"]["family_one_sided_lower"] >=
                 main["anchor_family"]["each_delta_lower_min"]
                 if endpoint["status"] == "COMPLETE" else None)
    for opponent in ("latest-alpha", "latest-balance"):
        name = "B-base-" + opponent
        endpoint = endpoints[name]
        set_gate(name, "coverage_retention", endpoint["interval"]["family_one_sided_lower"] >=
                 main["coverage_family"]["latest_each_delta_lower_min"]
                 if endpoint["status"] == "COMPLETE" else None)
    candidate_names = [name for name in ENDPOINT_ORDER
                       if name == "B-parent" or name.startswith("B-base-")]
    candidate_state = _family_state([status for name in candidate_names
                                     for status in endpoints[name]["gates"].values()])
    return {"format": "prism-m81-statistics-v1", "round": "M81",
            "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": plan["statistics"]["bootstrap_seed"],
                          "generator": "PCG64", "quantiles": "linear",
                          "ordinary_ci": [0.025, 0.975],
                          "unit": plan["statistics"]["unit"],
                          "endpoint_order": list(ENDPOINT_ORDER)},
            "method_screen": {"status": method_state, "endpoints": list(METHOD_ORDER),
                              "interpretation": "single paired training-seed pilot; not a recipe robustness estimate"},
            "mainline_candidate": {"status": candidate_state,
                                   "eligible_for_next_mainline_recommendation": candidate_state == "PASS" if candidate_state != "INCOMPLETE" else None,
                                   "endpoints": [name for name in ENDPOINT_ORDER if name.startswith("B-base") or name == "B-parent"],
                                   "interpretation": "recommendation only; no release, default replacement, or deployment authorization"},
            "endpoints": endpoints}


def _family_state(states):
    if any(state == "INCOMPLETE" for state in states):
        return "INCOMPLETE"
    return "PASS" if states and all(state == "PASS" for state in states) else "FAIL"


def _descriptives(rows, plan):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["candidate"], row["opponent"])].append(row)
    result = []
    e = plan["evaluation"]
    expected = {(actor, opponent, 512) for actor in e["actors"] for opponent in e["opponents"]}
    expected.update((actor, "parent", e["direct_parent"]["games_per_actor"])
                    for actor in e["direct_parent"]["actors"])
    for actor, opponent, planned in sorted(expected):
        values = grouped.get((actor, opponent), [])
        by_seat = {}
        for seat in (0, 1):
            part = [row for row in values if row["candidate_seat"] == seat]
            counts = Counter(float(row["candidate_score"]) for row in part)
            n = len(part)
            by_seat[str(seat)] = {"games": n, "wins": counts[1.0], "draws": counts[0.5],
                                  "losses": counts[0.0],
                                  "half_score": (counts[1.0] + .5 * counts[.5]) / n if n else None}
        counts = Counter(float(row["candidate_score"]) for row in values)
        n = len(values)
        result.append({"candidate": actor, "opponent": opponent, "planned_games": planned,
                       "observed_games": n, "status": "COMPLETE" if n == planned else "INCOMPLETE",
                       "wins": counts[1.0], "draws": counts[.5], "losses": counts[0.0],
                       "half_score": (counts[1.0] + .5 * counts[.5]) / n if n else None,
                       "by_candidate_seat": by_seat})
    return result


def _profile(root: Path, plan, rows):
    replay_rows = []
    assets = plan["assets"]
    for row in rows:
        actor, opponent = row["candidate"], row["opponent"]
        candidate_sha = (assets["parent"]["sha256"] if actor == "base" else None)
        if actor in ("A", "B"):
            path = root / f"campaigns/{actor}/cycle-20-export/weights.json"
            if path.exists():
                from training.prism_portable.common import digest
                candidate_sha = digest(path)
        opponent_sha = (assets["parent"]["sha256"] if opponent == "parent" else
                        None if opponent == "heuristic" else assets[opponent]["sha256"])
        replay_rows.append({"game_key": "|".join(str(row[k]) for k in
                              ("candidate", "opponent", "seed", "candidate_seat")),
                            "replay_path": row["replay_path"],
                            "replay_sha256": row["replay_sha256"],
                            "candidate_model": actor, "opponent_model": opponent,
                            "candidate_sha256": candidate_sha, "opponent_sha256": opponent_sha,
                            "candidate_seat": row["candidate_seat"], "seed": row["seed"],
                            "opponent": opponent})
    if not replay_rows:
        return {"status": "NOT_RUN", "reason": "no completed terminal replays are available",
                "legal_purchase_opportunities": "NOT_MEASURED",
                "first_divergence": "NOT_MEASURED", "main12_main24": "NOT_MEASURED"}
    from scripts import prism_replay_profile as replay_profile
    bindings = _profile_source_bindings(root)
    replay_profile.ROOT = root
    profiled = replay_profile.profile_saved_replays(
        replay_rows, projector=bindings["projector"]["path"], batch_size=256)
    candidate_profiles = [profile for group in profiled["profiles"].values()
                          for profile in group if profile["candidate_role"] == "candidate"]
    aggregate = replay_profile.aggregate_profiles(candidate_profiles) if candidate_profiles else None
    # VP/Main uses the exact terminal points and Rust-verified own-Main counts.
    by_actor_opponent = defaultdict(lambda: {"points": 0, "main_actions": 0, "games": 0})
    row_by_key = {"|".join(str(row[k]) for k in
                          ("candidate", "opponent", "seed", "candidate_seat")): row for row in rows}
    for profile in candidate_profiles:
        raw = row_by_key[profile["game_key"]]
        bucket = by_actor_opponent[(raw["candidate"], raw["opponent"])]
        bucket["points"] += raw["candidate_points"]
        bucket["main_actions"] += profile["main_actions"]
        bucket["games"] += 1
    vp_main = [{"candidate": actor, "opponent": opponent, **values,
                "vp_per_main": values["points"] / values["main_actions"] if values["main_actions"] else None}
               for (actor, opponent), values in sorted(by_actor_opponent.items())]
    return {"status": "PASS_RUST_REPLAY_VERIFIED" if profiled["verify_receipt"]["status"] == "PASS" else "FAIL",
            "source_bindings": bindings,
            "verify_receipt": profiled["verify_receipt"], "aggregate": aggregate,
            "candidate_profiles": candidate_profiles, "vp_per_main": vp_main,
            "measured": ["first 4-5 VP purchase Main and coverage", "0-1 VP purchases",
                         "own Main counts", "early discount investment/redemption through Main 24",
                         "VP/Main from terminal score and Rust-verified own Main"],
            "not_measured": {"legal_purchase_opportunities": "NOT_MEASURED by prism_replay_profile",
                             "first_divergence": "NOT_MEASURED; no matched replay-difference projector",
                             "token_choice_composition": "NOT_MEASURED as a cross-model behavioral endpoint",
                             "noble_coverage": "NOT_MEASURED by this projector",
                             "Main12/Main24 fixed-time score trajectory": "NOT_MEASURED"}}


def _profile_source_bindings(root: Path, projector_path: str | Path | None = None):
    """Verify the frozen projector and Rust/profile sources before projection."""
    from training.prism_portable.common import digest
    sources = {}
    for relative, expected in PROFILE_SOURCE_SHA256.items():
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"frozen replay-profile source missing: {relative}")
        actual = digest(path)
        if actual != expected:
            raise ValueError(f"frozen replay-profile source drift: {relative}")
        sources[relative] = {"path": str(path), "sha256": actual}
    projector = Path(projector_path) if projector_path is not None else root / "bin/prism_building_projection"
    if not projector.is_absolute():
        projector = root / projector
    projector = projector.resolve(strict=True)
    actual = digest(projector)
    if actual != PROFILE_PROJECTOR_SHA256:
        raise ValueError("frozen prism_building_projection binary SHA256 drift")
    return {"projector": {"path": str(projector), "sha256": actual,
                          "expected_sha256": PROFILE_PROJECTOR_SHA256},
            "sources": sources,
            "binding_policy": "frozen in M81 report module source before evaluation; external projector mode; no cargo build"}


def _json_frozen(path: Path, value: Any, read, write):
    if path.exists():
        if read(path) != value:
            raise ValueError(f"report artifact already exists with different contents: {path}")
    else:
        write(path, value)


def _fmt(value, digits=3):
    return "NOT_MEASURED" if value is None else f"{100 * value:.{digits}f}%"


def _markdown(result):
    lines = ["# M81 Anchor Coverage Evaluation", "",
             f"**Evaluation state:** {result['evaluation_state']}  ",
             f"**Terminal games:** {result['grid']['completed_games']}/{result['grid']['planned_games']}; "
             f"**missing:** {result['grid']['missing_games']}; **ply-cap truncations:** {result['grid']['truncated_games']}", "",
             f"**Evaluation CPU:** {result['resource_budget'].get('spent_cpu_seconds')} / "
             f"{result['resource_budget'].get('budget_cpu_seconds')} seconds; "
             f"unresolved reservations: {len(result['resource_budget'].get('reservations', {}))}.", "",
             "## Findings", "",
             f"- Coverage method screen: **{result['statistics']['method_screen']['status']}**.",
             f"- B mainline recommendation gates: **{result['statistics']['mainline_candidate']['status']}**.",
             "- One paired training seed only; game-level intervals do not estimate recipe robustness across training seeds.",
             "- A PASS is a next-mainline recommendation only. It does not authorize release, default replacement, or deployment.", "",
             "## Frozen statistical endpoints", "",
             "| Endpoint | Status | Estimate | Ordinary 95% CI | Family lower bound | Gates |",
             "| --- | --- | ---: | --- | ---: | --- |"]
    for name in ENDPOINT_ORDER:
        ep = result["statistics"]["endpoints"][name]
        ci = ep["interval"]["ordinary_95"] if ep["interval"] else None
        ci_text = f"[{_fmt(ci[0])}, {_fmt(ci[1])}]" if ci else "NOT_MEASURED (incomplete)"
        low = ep["interval"]["family_one_sided_lower"] if ep["interval"] else None
        gates = ", ".join(f"{k}={v}" for k, v in ep["gates"].items()) or "NOT_RUN"
        lines.append(f"| {name} | {ep['status']} | {_fmt(ep['estimate'])} | {ci_text} | {_fmt(low)} | {gates} |")
    lines += ["", "## Actor versus opponent results", "",
              "| Actor | Opponent | Games / planned | W / D / L | Half score | Seat 0 | Seat 1 | State |",
              "| --- | --- | ---: | --- | ---: | --- | --- | --- |"]
    for pair in result["pairs"]:
        s0, s1 = pair["by_candidate_seat"]["0"], pair["by_candidate_seat"]["1"]
        lines.append(f"| {pair['candidate']} | {pair['opponent']} | {pair['observed_games']}/{pair['planned_games']} | "
                     f"{pair['wins']}/{pair['draws']}/{pair['losses']} | {_fmt(pair['half_score'])} | "
                     f"{s0['wins']}/{s0['draws']}/{s0['losses']} | {s1['wins']}/{s1['draws']}/{s1['losses']} | {pair['status']} |")
    lines += ["", "## Behavior profile", "",
              f"Rust replay profile state: **{result['profile']['status']}**.",
              "Purchase opportunities, first divergence, token-choice composition, noble coverage, and fixed Main 12/24 scores are NOT_MEASURED by this profile pipeline.",
              "The measured first-large-card timing includes its purchase-game coverage; early low-VP buys and discount redemption include observed denominators.", "",
              "| Candidate | Opponent | Seat | Games | First 4–5 VP purchase Main | Purchase coverage | 0–1 VP buys/game | Discount redemption rate |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for group in (result["profile"].get("aggregate") or {}).get("groups", []):
        lines.append(f"| {group['model']} | {group['opponent']} | {group['seat']} | {group['games']} | "
                     f"{group.get('first_big_main') if group.get('first_big_main') is not None else 'NOT_MEASURED'} | "
                     f"{_fmt(group.get('first_big_coverage'))} | {group.get('early_low_cards', 'NOT_MEASURED')} | "
                     f"{_fmt(group.get('early_discount_redemption_rate'))} |")
    lines += ["", "### VP per own Main", "", "| Candidate | Opponent | Games | Points | Own Main actions | VP/Main |",
              "| --- | --- | ---: | ---: | ---: | ---: |"]
    for group in result["profile"].get("vp_per_main", []):
        lines.append(f"| {group['candidate']} | {group['opponent']} | {group['games']} | {group['points']} | "
                     f"{group['main_actions']} | {group['vp_per_main'] if group['vp_per_main'] is not None else 'NOT_MEASURED'} |")
    lines += ["", "## Shard ledger and missing identities", "",
              "| Shard | State | Complete | Truncated | Missing | Reason |",
              "| --- | --- | ---: | ---: | ---: | --- |"]
    for shard in result["shards"]:
        lines.append(f"| {shard['label']} | {shard['state']} | {shard['completed_games']} | {shard['truncated_games']} | "
                     f"{shard['missing_games']} | {shard['stop_reason']} |")
    lines += ["", "Missing identities keep their original seed and seat. They receive no fabricated outcome.", "",
              "## Source and result identity", "",
              f"Plan SHA256: `{result['plan']['sha256']}`  ",
              f"Execution receipt SHA256: `{result['source_hashes']['execution']}`  ",
              f"Completed row count: {len(result['rows'])}  ",
              f"Profile receipt: `{result['profile'].get('verify_receipt', {}).get('status', result['profile']['status'])}`"]
    if result["missing"]:
        lines += ["", "### Missing rows", "", "| Actor | Opponent | Seed | Seat | Shard | Reason |",
                  "| --- | --- | ---: | ---: | --- | --- |"]
        for row in result["missing"]:
            lines.append(f"| {row['candidate']} | {row['opponent']} | {row['seed']} | {row['candidate_seat']} | {row['shard']} | {row['reason']} |")
    return "\n".join(lines) + "\n"


def _html(result):
    rows = []
    for name in ENDPOINT_ORDER:
        ep = result["statistics"]["endpoints"][name]
        ci = ep["interval"]["ordinary_95"] if ep["interval"] else None
        rows.append("<tr><td>" + html.escape(name) + "</td><td>" + ep["status"] +
                    "</td><td>" + _fmt(ep["estimate"]) + "</td><td>" +
                    (f"[{_fmt(ci[0])}, {_fmt(ci[1])}]" if ci else "NOT_MEASURED") +
                    "</td><td>" + html.escape(json.dumps(ep["gates"], sort_keys=True)) + "</td></tr>")
    pair_rows = []
    for pair in result["pairs"]:
        pair_rows.append("<tr><td>" + html.escape(pair["candidate"]) + "</td><td>" +
                         html.escape(pair["opponent"]) + f"</td><td>{pair['observed_games']}/{pair['planned_games']}</td><td>"+
                         f"{pair['wins']}/{pair['draws']}/{pair['losses']}</td><td>{_fmt(pair['half_score'])}</td></tr>")
    profile_rows = []
    for group in (result["profile"].get("aggregate") or {}).get("groups", []):
        timing = group.get("first_big_main")
        profile_rows.append("<tr><td>" + html.escape(group["model"]) + "</td><td>" +
                            html.escape(group["opponent"]) + f"</td><td>{group['seat']}</td><td>{group['games']}</td><td>"+
                            (str(timing) if timing is not None else "NOT_MEASURED") + "</td><td>"+
                            _fmt(group.get("first_big_coverage")) + "</td><td>"+
                            str(group.get("early_low_cards", "NOT_MEASURED")) + "</td><td>"+
                            _fmt(group.get("early_discount_redemption_rate")) + "</td></tr>")
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>M81 Anchor Coverage</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1200px;margin:28px auto;padding:0 18px;color:#18283a;background:#f5f7fa}"
            ".card{background:#fff;border:1px solid #dce3eb;border-radius:12px;padding:18px;margin:16px 0} .scroll{overflow:auto}table{border-collapse:collapse;width:100%;min-width:720px}"
            "td,th{text-align:left;padding:9px 11px;border-bottom:1px solid #e2e7ed}th{background:#edf2f7}code{overflow-wrap:anywhere}"
            "@media(max-width:600px){body{margin:0;padding:12px}.card{padding:12px}}</style><h1>M81 Anchor Coverage</h1>"
            f"<section class='card'><p>Evaluation: <b>{html.escape(result['evaluation_state'])}</b>; terminal games "
            f"{result['grid']['completed_games']}/{result['grid']['planned_games']}; missing {result['grid']['missing_games']}.</p>"
            f"<p>Coverage method screen: <b>{result['statistics']['method_screen']['status']}</b>. B mainline gates: "
            f"<b>{result['statistics']['mainline_candidate']['status']}</b>.</p><p>One paired training seed. "
            "A PASS is a next-mainline recommendation only.</p></section><section class='card'><h2>Frozen endpoints</h2><div class='scroll'><table><thead><tr><th>Endpoint</th><th>State</th><th>Estimate</th><th>Ordinary 95% CI</th><th>Gates</th></tr></thead><tbody>"+
            "".join(rows)+"</tbody></table></div></section><section class='card'><h2>Actor results</h2><div class='scroll'><table><thead><tr><th>Actor</th><th>Opponent</th><th>Games</th><th>W/D/L</th><th>Half score</th></tr></thead><tbody>"+
            "".join(pair_rows)+"</tbody></table></div><h3>Rust-verified behavior profile</h3><div class='scroll'><table><thead><tr><th>Candidate</th><th>Opponent</th><th>Seat</th><th>Games</th><th>First big-card Main</th><th>Coverage</th><th>Low-VP buys/game</th><th>Discount redemption</th></tr></thead><tbody>"+
            "".join(profile_rows)+"</tbody></table></div><p>Behavior profile: "+html.escape(result["profile"]["status"])+
            ". Legal purchase opportunities, first divergence, token-choice composition, noble coverage and fixed Main 12/24 scores are NOT_MEASURED.</p></section></html>")


def report(root: str | Path | None = None) -> dict[str, Any]:
    """Build the final immutable raw result, replay profile, Markdown and reading HTML."""
    root_path = _root(root)
    runtime, plan, execution, bounded = _runtime(root_path)
    read, write, digest = _common()
    rows, missing, caps, shards = _collect(root_path, plan, bounded)
    eval_plan_path = root_path / "evaluation-plan.json"
    eval_plan_record = read(eval_plan_path) if eval_plan_path.exists() else {}
    profile_binding_error = None
    try:
        current_bindings = _profile_source_bindings(root_path)
        if eval_plan_record.get("profile_source_bindings") != current_bindings:
            raise ValueError("projector/source binding differs from the pre-evaluation frozen grid")
    except Exception as exc:
        current_bindings = "NOT_VERIFIED"
        profile_binding_error = f"{type(exc).__name__}: {exc}"
    planned = plan["evaluation"]["total_games"]
    stats = _statistics(rows, plan)
    try:
        if profile_binding_error:
            raise ValueError(profile_binding_error)
        profile = _profile(root_path, plan, rows)
    except Exception as exc:
        profile = {"status": "FAILED_RETAINED_EVIDENCE",
                   "error": f"{type(exc).__name__}: {exc}",
                   "legal_purchase_opportunities": "NOT_MEASURED",
                   "first_divergence": "NOT_MEASURED",
                   "source_bindings": "NOT_VERIFIED"}
    completed = len(rows)
    if completed > planned or completed + len(missing) != planned:
        raise ValueError("M81 result identity accounting does not reconcile to the frozen grid")
    complete = completed == planned and not missing and all(
        shard["state"] == "FINISHED" for shard in shards)
    resource_path = root_path / "evaluation/resource-budget.json"
    resource_budget = read(resource_path) if resource_path.exists() else {
        "budget_cpu_seconds": plan["resources"]["evaluation_cpu_seconds"],
        "spent_cpu_seconds": sum(float(shard.get("inspection", {}).get("consumed_cpu_seconds", 0.0))
                                  for shard in shards),
        "reservations": {}, "state": "DERIVED_FROM_SHARD_LEDGERS"}
    result = {"format": "prism-m81-anchor-coverage-result-v1", "round": "M81",
              "evaluation_state": "COMPLETE" if complete else "INCOMPLETE",
              "plan": {"path": PLAN_REL.as_posix(), "sha256": digest(root_path / PLAN_REL)},
              "source_hashes": {"execution": digest(root_path / "execution.json"),
                                "evaluator": digest(root_path / "scripts/prism_m81_evaluate.py"),
                                "reporter": digest(root_path / "scripts/prism_m81_report.py")},
              "grid": {"planned_games": planned, "completed_games": completed,
                       "missing_games": len(missing), "truncated_games": len(caps),
                       "actor_opponent_seat_rows": completed},
              "resource_budget": resource_budget,
              "profile_source_bindings": current_bindings,
              "statistics": stats, "pairs": _descriptives(rows, plan),
              "profile": profile, "shards": shards, "missing": missing, "caps": caps,
              "rows": rows, "observed_at": time.time(),
              "claim_boundary": "single paired training seed; no recipe robustness claim; no release/default/deployment authorization"}
    profile_path = root_path / PROFILE_REL
    _json_frozen(profile_path, profile, read, write)
    result["profile_file"] = {"path": PROFILE_REL.as_posix(), "sha256": digest(profile_path)}
    _json_frozen(root_path / RESULT_REL, result, read, write)
    md_path = root_path / EVIDENCE_REL
    html_path = root_path / READING_REL
    md = _markdown(result)
    page = _html(result)
    if md_path.exists() and md_path.read_text(encoding="utf-8") != md:
        raise ValueError(f"report already exists with different contents: {md_path}")
    if html_path.exists() and html_path.read_text(encoding="utf-8") != page:
        raise ValueError(f"reading page already exists with different contents: {html_path}")
    if not md_path.exists():
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md, encoding="utf-8")
    if not html_path.exists():
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(page, encoding="utf-8")
    receipt = {"format": "prism-m81-report-receipt-v1",
               "status": "PASS" if complete and profile["status"] == "PASS_RUST_REPLAY_VERIFIED" else "INCOMPLETE",
               "evaluation_state": result["evaluation_state"],
               "files": {path.as_posix(): digest(root_path / path)
                         for path in (PROFILE_REL, RESULT_REL, EVIDENCE_REL, READING_REL)},
               "rows": completed, "missing": len(missing), "profile_state": profile["status"],
               "evaluation_cpu_budget": resource_budget,
               "observed_at": time.time()}
    _json_frozen(root_path / RECEIPT_REL, receipt, read, write)
    return receipt
