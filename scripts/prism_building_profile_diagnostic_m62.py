"""Read-only descriptive diagnostics for saved M62 building profiles.

This tool validates the frozen profile arithmetic and aggregates existing
development/acceptance profiles. It does not replay games or alter gates.
"""
import argparse
import hashlib
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path

ANCHORS = ("heuristic-v031", "prism-v01", "prism-general-v011")
CANDIDATES = ("base", "control", "beta")
ARMS = ("control", "beta")
GLOBAL_CAP = 24
PER_INVESTMENT_CAP = 3
SCOPE_PATH = Path("local-artifacts/prism/m62-building-research-2026-10-04/scope.json")
BUILDING_STYLE_CONTRACT = {
    "format": "prism-building-style-v1", "early_window_main_actions": 12,
    "redemption_horizon_main_actions": 24, "early_max_printed_vp": 1,
    "per_investment_use_cap": 3, "global_use_cap": 24,
    "short_game_padding": "none",
    "phase_semantics": "choose_noble-belongs-to-preceding-main",
    "terminal_only": True,
    "style_reward_input": "player-visible-own-purchases-and-prepurchase-bonuses",
    "diagnostic_early_bonus_padding": "held-at-terminal",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite_number(value, name, minimum=None):
    require(type(value) in (int, float) and math.isfinite(value), f"invalid {name}")
    if minimum is not None:
        require(value >= minimum, f"invalid {name}")
    return float(value)


def same_number(actual, expected, name):
    finite_number(actual, name)
    require(math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=1e-12),
            f"{name} does not match recomputed value")


def validate_profile(profile):
    require(isinstance(profile, dict), "profile must be an object")
    investments = profile.get("investments")
    require(isinstance(investments, list), "profile investments must be a list")
    main_actions = profile.get("main_actions")
    require(type(main_actions) is int and main_actions >= 1, "invalid profile main_actions")
    observed = capped = redeemed = unredeemed = censored = unredeemed_censored = full3 = 0
    for inv in investments:
        require(isinstance(inv, dict), "investment must be an object")
        uses = inv.get("use_main_actions")
        require(isinstance(uses, list), "investment use_main_actions must be a list")
        require(all(type(x) is int and 1 <= x <= main_actions for x in uses), "invalid real use Main")
        require(uses == sorted(uses) and len(set(uses)) == len(uses), "duplicate/unsorted investment uses")
        acquired = inv.get("acquired_main")
        require(type(acquired) is int and 1 <= acquired <= 12, "invalid investment acquisition Main")
        require(all(x > acquired for x in uses), "investment credited on/before acquisition")
        obs = len(uses)
        cap = min(obs, PER_INVESTMENT_CAP)
        same_number(inv.get("observed_uses"), obs, "investment observed_uses")
        same_number(inv.get("credited_uses"), cap, "investment credited_uses")
        require(inv.get("unredeemed") is (obs == 0), "investment redemption flag mismatch")
        expected_censored = main_actions < 24 and obs < PER_INVESTMENT_CAP
        require(inv.get("censored") is expected_censored, "investment censor flag mismatch")
        observed += obs
        capped += cap
        redeemed += obs > 0
        unredeemed += obs == 0
        censored += expected_censored
        unredeemed_censored += obs == 0 and expected_censored
        full3 += obs >= PER_INVESTMENT_CAP

    credited = min(capped, GLOBAL_CAP)
    same_number(profile.get("building_observed_use_units"), observed, "building_observed_use_units")
    same_number(profile.get("building_use_units_before_global_cap"), capped,
                "building_use_units_before_global_cap")
    same_number(profile.get("building_use_units"), credited, "building_use_units")
    same_number(profile.get("building_utility"), credited / GLOBAL_CAP, "building_utility")
    same_number(profile.get("early_lowvp_buys"), len(investments), "early_lowvp_buys")
    same_number(profile.get("redeemed_investments"), redeemed, "redeemed_investments")
    same_number(profile.get("unredeemed_investments"), unredeemed, "unredeemed_investments")
    same_number(profile.get("censored_investments"), censored, "censored_investments")
    same_number(profile.get("unredeemed_censored_investments"), unredeemed_censored,
                "unredeemed_censored_investments")
    auc = finite_number(profile.get("early_bonus_auc12"), "early_bonus_auc12", 0)
    late_vp = finite_number(profile.get("late_vp_bought_main13to24"),
                            "late_vp_bought_main13to24", 0)
    return {"profile": profile, "utility": credited / GLOBAL_CAP, "investment_count": len(investments),
            "observed_units": observed, "per_investment_loss": observed - capped,
            "global_cap_loss": capped - credited, "full3": full3, "redeemed": redeemed,
            "unredeemed": unredeemed, "censored": censored,
            "unredeemed_censored": unredeemed_censored, "auc": auc, "late_vp": late_vp,
            "main_actions": main_actions, "investments": investments}


def read_json_bytes(data):
    return json.loads(data.decode("utf-8"))


def read_json(path):
    path = Path(path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def load_profiles(data):
    require(isinstance(data, dict) and isinstance(data.get("games"), list),
            "expected building-metrics object with games list")
    rows = []
    seen = set()
    for game in data["games"]:
        require(isinstance(game, dict), "game row must be an object")
        candidate, opponent = game.get("candidate"), game.get("opponent")
        seed, seat, profiles = game.get("seed"), game.get("candidate_seat"), game.get("profiles")
        require(candidate in CANDIDATES and isinstance(opponent, str) and opponent,
                "invalid candidate/opponent identity")
        require(type(seed) is int and type(seat) is int and seat in (0, 1), "invalid seed/candidate_seat")
        require(isinstance(profiles, list) and len(profiles) == 2, "profiles must contain physical seats 0 and 1")
        key = (candidate, opponent, seed, seat)
        require(key not in seen, "duplicate candidate/opponent/seed/seat row")
        seen.add(key)
        checked = [validate_profile(p) for p in profiles]
        rows.append({"candidate": candidate, "opponent": opponent, "seed": seed,
                     "candidate_seat": seat, "profiles": checked,
                     "candidate_profile": checked[seat], "opponent_profile": checked[1 - seat]})
    require(rows, "empty games list")
    return rows


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def correlation(xs, ys):
    if len(xs) < 2 or len(ys) != len(xs):
        return None
    mx, my = math.fsum(xs) / len(xs), math.fsum(ys) / len(ys)
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    vx, vy = math.fsum(x * x for x in dx), math.fsum(y * y for y in dy)
    if vx <= 1e-30 or vy <= 1e-30:
        return None
    return math.fsum(x * y for x, y in zip(dx, dy)) / math.sqrt(vx * vy)


def distribution(values):
    mean = math.fsum(values) / len(values) if values else None
    return {"n": len(values), "mean": mean,
            "std": math.sqrt(math.fsum((x - mean) ** 2 for x in values) / len(values)) if values else None,
            "quantile_definition": "nearest-rank: sorted[ceil(p*n)-1], 1-based",
            "min": min(values) if values else None, "p10": percentile(values, .10),
            "median": percentile(values, .50), "p90": percentile(values, .90),
            "max": max(values) if values else None}


def summarize(records):
    require(records, "cannot summarize empty group")
    ps = [r["profile"] for r in records]
    utilities = [p["utility"] for p in records]
    investments = [inv for p in ps for inv in p["investments"]]
    use_counts = [len(inv["use_main_actions"]) for inv in investments]
    first_times = [inv["use_main_actions"][0] for inv in investments if inv["use_main_actions"]]
    third_times = [inv["use_main_actions"][2] for inv in investments if len(inv["use_main_actions"]) >= 3]
    first_delays = [inv["use_main_actions"][0] - inv["acquired_main"] for inv in investments if inv["use_main_actions"]]
    third_delays = [inv["use_main_actions"][2] - inv["acquired_main"] for inv in investments if len(inv["use_main_actions"]) >= 3]
    total_i = len(investments)
    observed = sum(p["observed_units"] for p in records)
    precap = sum(p["profile"]["building_use_units_before_global_cap"] for p in records)
    credited = sum(p["profile"]["building_use_units"] for p in records)
    aucs, late, mains = [p["auc"] for p in records], [p["late_vp"] for p in records], [p["main_actions"] for p in records]
    return {"games": len(records), "utility": distribution(utilities),
            "utility_zero_games": sum(x == 0 for x in utilities),
            "utility_globalcap24_games": sum(p["profile"]["building_use_units_before_global_cap"] >= GLOBAL_CAP for p in records),
            "investment_count": total_i, "mean_investments_per_game": total_i / len(records),
            "raw_use_units": observed, "capped_before_global_units": precap,
            "credited_units": credited, "per_investment_cap_loss_units": observed - precap,
            "global_cap_loss_units": precap - credited,
            "investments_with_3plus_uses": sum(n >= 3 for n in use_counts),
            "investment_3plus_use_rate": sum(n >= 3 for n in use_counts) / total_i if total_i else None,
            "redeemed_investments": sum(bool(n) for n in use_counts),
            "redemption_rate_by_total_investments": sum(bool(n) for n in use_counts) / total_i if total_i else None,
            "censored_investments": sum(p["censored"] for p in records),
            "censored_rate_by_total_investments": sum(p["censored"] for p in records) / total_i if total_i else None,
            "first_use_main": distribution(first_times), "third_use_main": distribution(third_times),
            "first_use_delay_main": distribution(first_delays), "third_use_delay_main": distribution(third_delays),
            "correlations": {"utility_vs_investment_count": correlation(utilities, [p["investment_count"] for p in records]),
                             "utility_vs_auc12": correlation(utilities, aucs),
                             "utility_vs_late_vp_main13to24": correlation(utilities, late),
                             "utility_vs_main_actions": correlation(utilities, mains)}}


def aggregate(rows):
    grouped = defaultdict(list)
    for row in rows:
        for role in ("candidate", "opponent"):
            identity = row[role] if role == "candidate" else row["opponent"]
            grouped[(row["stage"], row["candidate"], row["opponent"], role, identity)].append(row[role + "_profile"])
            if role == "candidate" and row["opponent"] in ANCHORS:
                grouped[(row["stage"], row["candidate"], "COMMON_ANCHORS", role, identity)].append(row[role + "_profile"])
            if role == "opponent" and row["opponent"] in ANCHORS:
                grouped[(row["stage"], row["candidate"], "COMMON_ANCHORS", role, identity)].append(row[role + "_profile"])
    return [{"stage": k[0], "candidate": k[1], "opponent_group": k[2], "role": k[3], "model": k[4],
             "summary": summarize(v)} for k, v in sorted(grouped.items())]


def matched_differences(rows):
    keyed = {}
    for row in rows:
        if row["candidate"] in ARMS and row["opponent"] in ANCHORS:
            key = (row["stage"], row["opponent"], row["seed"], row["candidate_seat"])
            keyed.setdefault(key, {})[row["candidate"]] = row
    metrics = ("utility", "investment_count", "auc", "late_vp", "main_actions")
    result = []
    for stage in sorted({k[0] for k in keyed}):
        for key, arms in keyed.items():
            if key[0] == stage and set(arms) != set(ARMS):
                raise ValueError(f"unmatched control/beta profile key: {key}")
        complete = [(k, v) for k, v in keyed.items() if k[0] == stage]
        groups = [(anchor, [v for k, v in complete if k[1] == anchor]) for anchor in ANCHORS]
        groups.append(("COMMON_ANCHORS", [v for _, v in complete]))
        for opponent_group, matched in groups:
            if not matched:
                continue
            for role in ("candidate_profile", "opponent_profile"):
                record = {"stage": stage, "opponent_group": opponent_group, "role": role,
                          "matched_seed_seat_rows": len(matched), "mean_beta_minus_control": {}}
                for metric in metrics:
                    vals = []
                    for pair in matched:
                        b, c = pair["beta"][role], pair["control"][role]
                        vals.append(b[metric] - c[metric])
                    record["mean_beta_minus_control"][metric] = math.fsum(vals) / len(vals)
                result.append(record)
    return result


def build_report(inputs, scope_path=SCOPE_PATH):
    scope_path = Path(scope_path)
    scope_bytes = scope_path.read_bytes()
    scope = read_json_bytes(scope_bytes)
    require(scope.get("format") == "m62-building-research-scope-v1" and
            scope.get("status") == "AUTHORIZED_BEFORE_DIAGNOSTIC", "scope authorization missing/invalid")
    input_records = {}
    rows = []
    for stage, path in inputs.items():
        path = Path(path)
        raw = path.read_bytes()
        decoded = gzip.decompress(raw) if path.suffix.lower() == ".gz" else raw
        data = read_json_bytes(decoded)
        validate_metrics_document(data)
        input_records[stage] = {"path": str(path), "compressed_or_input_bytes": len(raw),
                                "input_sha256": hashlib.sha256(raw).hexdigest(),
                                "uncompressed_bytes": len(decoded),
                                "uncompressed_sha256": hashlib.sha256(decoded).hexdigest(),
                                "games": len(data["games"]), "profiles": 2 * len(data["games"])}
        for row in load_profiles(data):
            row["stage"] = stage
            rows.append(row)
    pins = scope.get("input_pins", {})
    result_path = Path("local-artifacts/prism/building-beta-m62/evaluation/result.json")
    frozen_result = read_json(result_path)
    require(hashlib.sha256(result_path.read_bytes()).hexdigest() == pins.get(str(result_path).replace("\\", "/")),
            "frozen M62 result SHA differs from authorized scope pin")
    for stage, record in input_records.items():
        expected = frozen_result.get(stage, {}).get("building_metrics_sha256")
        require(expected == record["uncompressed_sha256"],
                f"{stage} building-metrics SHA differs from frozen result")
    source_path = Path(__file__).resolve()
    return {"format": "m62-building-profile-diagnostic-v1", "status": "DESCRIPTIVE_DIAGNOSTIC_ONLY",
            "scope": str(scope_path), "scope_sha256": hashlib.sha256(scope_bytes).hexdigest(),
            "script_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "frozen_result": {"path": str(result_path),
                              "sha256": hashlib.sha256(result_path.read_bytes()).hexdigest()},
            "inputs": input_records,
            "coverage": {stage: {"games": record["games"], "profiles": record["profiles"]}
                         for stage, record in input_records.items()},
            "new_games": 0, "optimizer_updates": 0,
            "gate_reopened": False, "anchors": list(ANCHORS), "groups": aggregate(rows),
            "matched_control_beta_differences": matched_differences(rows)}


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_metrics_document(data):
    require(data.get("format") == "m62-building-replay-metrics-v1" and
            data.get("status") == "VERIFIED_OFFLINE_VISIBLE_BUILDING_PROFILES" and
            data.get("new_games") == 0 and data.get("all_players") is True,
            "building metrics format/status/scope mismatch")
    require(data.get("style_contract") == BUILDING_STYLE_CONTRACT,
            "building metrics style contract differs from frozen v1")
    require(data.get("style_contract_sha256") == canonical_hash(BUILDING_STYLE_CONTRACT),
            "building metrics style contract hash mismatch")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--scope", type=Path, default=SCOPE_PATH)
    parser.add_argument("--output", required=True, type=Path, help="must be a new output path")
    args = parser.parse_args(argv)
    inputs = {k: v for k, v in (("development", args.development), ("acceptance", args.acceptance)) if v}
    require(inputs, "provide --development and/or --acceptance")
    require(not args.output.exists(), "refuse to overwrite diagnostic output")
    report = build_report(inputs, args.scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "groups": len(report["groups"]),
                      "matched_rows": sum(x["matched_seed_seat_rows"] for x in report["matched_control_beta_differences"]),
                      "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
