"""Independent M79 three-actor profile archive.

The archive reads the frozen plan and unchanged bounded_eval raw tree directly.
It verifies the transfer manifest, shard configs/manifests/policies/ledgers,
completed game evidence, actor identities, and strict saved-replay projections.
No owner-authored sidecar or new game is part of the workflow.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts import prism_m79_profile as m79_profile


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "prism-m79-candidate-archive-v1"
INPUT_FORMAT = "prism-m79-verified-archive-input-v1"
IDENTITY_RECEIPT_FORMAT = "prism-m79-identity-receipt-v1"
MODEL_IDS = ("a", "base", "style-reference")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def digest(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_grid(keys: Sequence[tuple[str, str, int, int]]) -> str:
    return hashlib.sha256(canonical([list(key) for key in sorted(keys)])).hexdigest()


def read_json(path: str | Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    with Path(path).open("r", encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON number: {value}")))


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _hex_sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            f"{label} must be a lowercase SHA256")
    return value


def _range(value: Any, label: str) -> range:
    require(isinstance(value, list) and len(value) == 2
            and all(type(x) is int for x in value) and value[1] >= value[0],
            f"invalid {label} range")
    return range(value[0], value[1] + 1)


def expected_grid(plan: Mapping[str, Any]) -> set[tuple[str, str, int, int]]:
    """Build the declared M79 grid from per-opponent ranges and actor cohorts."""
    evaluation = plan["evaluation"]
    seats = evaluation.get("seats", [0, 1])
    require(seats == [0, 1], "M79 archive requires the declared two-seat grid")
    common_models = evaluation["common_actors"]
    require(set(common_models) == set(MODEL_IDS), "common grid must name a, base, and style-reference")
    grid: set[tuple[str, str, int, int]] = set()
    for opponent in evaluation["common_opponents"]:
        for model in common_models:
            grid.update((model, opponent, seed, seat)
                        for seed in _range(evaluation["common_seed_by_opponent"][opponent], opponent)
                        for seat in seats)
    for opponent, limits in evaluation["coverage_seed_by_opponent"].items():
        for model in evaluation["coverage_actors"]:
            grid.update((model, opponent, seed, seat)
                        for seed in _range(limits, opponent) for seat in seats)
    direct = evaluation["direct"]
    grid.update((direct["candidate"], direct["opponent"], seed, seat)
                for seed in _range(direct["seed_range"], "direct") for seat in seats)
    require(len(grid) > 0, "M79 plan declared an empty evaluation grid")
    return grid


def _attempt_key(row: Mapping[str, Any]) -> tuple[str, str, int, int]:
    model, opponent, seed, seat = (row.get("model"), row.get("opponent"), row.get("seed"), row.get("seat"))
    require(isinstance(model, str) and model and isinstance(opponent, str) and opponent
            and type(seed) is int and seed >= 0 and type(seat) is int and seat in (0, 1),
            "attempt row has malformed model/opponent/seed/seat identity")
    return model, opponent, seed, seat


def _status(row: Mapping[str, Any] | None) -> str:
    if row is None:
        return "NOT_RECORDED"
    value = row.get("state", row.get("status"))
    require(isinstance(value, str) and value, "attempt row lacks state/status")
    return value


def _model_shas(plan: Mapping[str, Any], result: Mapping[str, Any] | None) -> dict[str, str | None]:
    assets = plan["assets"]
    candidate_sha = None
    if result is not None:
        candidate_sha = result.get("candidate_sha256", {}).get("a")
        if candidate_sha is not None:
            _hex_sha(candidate_sha, "M79 candidate SHA256")
    return {
        "a": candidate_sha,
        "base": _hex_sha(assets["parent"]["sha256"], "M75 parent SHA256"),
        "style-reference": _hex_sha(assets["style-reference"]["sha256"], "fixed style-reference SHA256"),
    }


def _flatten_profiles(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    require(isinstance(value, Mapping), "profiles_by_game must be an object")
    for game_key, actors in value.items():
        require(isinstance(game_key, str) and game_key and isinstance(actors, list) and len(actors) == 2,
                f"malformed actor profiles for {game_key}")
        require({row.get("seat") for row in actors if isinstance(row, dict)} == {0, 1},
                f"both physical actor profiles are required for {game_key}")
        for row in actors:
            require(isinstance(row, dict) and row.get("game_key") == game_key,
                    f"profile key mismatch for {game_key}")
            flattened.append(row)
    return flattened


def _verify_profile_binding(
    attempts: Mapping[tuple[str, str, int, int], Mapping[str, Any]],
    profiles_by_game: Mapping[str, Any],
    profile_receipt: Mapping[str, Any],
    model_shas: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    require(profile_receipt.get("status") == "PASS", "saved-replay profile receipt is not PASS")
    require(profile_receipt.get("new_games") == 0, "profile stage must not generate games")
    terminal = {key: row for key, row in attempts.items() if _status(row) == "COMPLETED"}
    receipt_rows = profile_receipt.get("replays")
    require(isinstance(receipt_rows, list), "profile receipt must list verified replay identities")
    receipt_by_key = {}
    for row in receipt_rows:
        require(isinstance(row, dict) and isinstance(row.get("game_key"), str),
                "malformed replay verification receipt row")
        key = row["game_key"]
        require(key not in receipt_by_key, f"duplicate replay receipt: {key}")
        require(row.get("rust_verified_terminal") is True, f"replay is not a verified terminal: {key}")
        receipt_by_key[key] = row
    expected_game_keys = {
        f"{model}/{opponent}/seed-{seed}/seat-{seat}"
        for model, opponent, seed, seat in terminal
    }
    require(set(receipt_by_key) == expected_game_keys,
            "profile receipt and completed bounded_eval attempts differ")
    require(profile_receipt.get("games_verified") == len(terminal),
            "profile receipt verified-game count mismatch")
    require(profile_receipt.get("actor_profiles") == 2 * len(terminal),
            "profile receipt actor count mismatch")

    flattened = _flatten_profiles(profiles_by_game)
    require(len(flattened) == 2 * len(terminal), "profile actor count does not match terminal games")
    seen: set[tuple[str, int]] = set()
    for row in flattened:
        game_key, seat = row["game_key"], row["seat"]
        require((game_key, seat) not in seen, f"duplicate replay actor profile: {game_key}/seat-{seat}")
        seen.add((game_key, seat))
        receipt_row = receipt_by_key.get(game_key)
        require(receipt_row is not None and row.get("replay_sha256") == receipt_row.get("replay_sha256"),
                f"profile replay SHA is not receipt-bound: {game_key}")
        matches = [key for key in terminal if
                   f"{key[0]}/{key[1]}/seed-{key[2]}/seat-{key[3]}" == game_key]
        require(len(matches) == 1, f"profile has no unique completed attempt: {game_key}")
        model, opponent, seed, candidate_seat = matches[0]
        require(receipt_row.get("seed") == seed and receipt_row.get("candidate_seat") == candidate_seat,
                f"profile receipt identity mismatch: {game_key}")
        require(row.get("seed") == seed and row.get("candidate_seat") == candidate_seat,
                f"profile actor seed/seat binding mismatch: {game_key}/seat-{seat}")
        expected_model = model if seat == candidate_seat else opponent
        expected_opponent = opponent if seat == candidate_seat else model
        require(row.get("model") == expected_model and row.get("opponent") == expected_opponent,
                f"profile actor/model assignment mismatch: {game_key}/seat-{seat}")
        expected_role = "candidate" if seat == candidate_seat else "opponent"
        require(row.get("candidate_role") == expected_role,
                f"profile candidate role mismatch: {game_key}/seat-{seat}")
        if row.get("round_opponent_id") is not None:
            require(row["round_opponent_id"] == opponent,
                    f"profile evaluation opponent mismatch: {game_key}/seat-{seat}")
        wanted_sha = model_shas.get(expected_model)
        if wanted_sha is not None:
            require(row.get("model_sha256") == wanted_sha,
                    f"profile model SHA drift: {game_key}/seat-{seat}")
        wanted_opponent_sha = model_shas.get(expected_opponent)
        if wanted_opponent_sha is not None:
            require(row.get("opponent_sha256") == wanted_opponent_sha,
                    f"profile opponent SHA drift: {game_key}/seat-{seat}")
    return flattened


def _profile_behavior(rows: list[dict[str, Any]]) -> dict[str, Any]:
    require(bool(rows), "cannot summarize empty model profile")
    temporal = m79_profile.aggregate_profiles(rows)
    games = len(rows)
    counts = Counter(event["printed_vp"] for row in rows for event in row["first_big_purchase_events"])
    total_cards = sum(counts.values())
    low_cards = counts[0] + counts[1]
    big_printed = sum(vp * counts[vp] for vp in (3, 4, 5))
    total_main = sum(row["main_actions"] for row in rows)
    total_vp = sum(row["terminal_vp"] for row in rows)
    noble_games = sum(row["nobles_selected"] > 0 for row in rows)
    return {
        "games": games,
        "cards_by_vp": {str(vp): counts[vp] for vp in range(6)},
        "low_cards_per_game": low_cards / games,
        "low_share": low_cards / total_cards if total_cards else None,
        "big_printed_vp_per_game": big_printed / games,
        "noble_coverage": noble_games / games,
        "vp_per_own_main": total_vp / total_main if total_main else None,
        "first_big_main": temporal["first_big_main"],
        "first_big_games": temporal["first_big_games"],
        "first_big_coverage": temporal["first_big_coverage"],
        "early_low_cards_per_game": temporal["early_low_cards"],
        "early_discount_redemptions_per_game": temporal["early_discount_redemptions"],
        "own_main_12_vp_mean": temporal["own_main_12_vp_mean"],
        "own_main_12_survival_coverage": temporal["own_main_12_survival_coverage"],
        "own_main_12_survival_coverage_games": temporal["own_main_12_survival_coverage_games"],
        "own_main_12_survival_coverage_denominator": temporal["own_main_12_survival_coverage_denominator"],
        "own_main_24_vp_mean": temporal["own_main_24_vp_mean"],
        "own_main_24_survival_coverage": temporal["own_main_24_survival_coverage"],
        "own_main_24_survival_coverage_games": temporal["own_main_24_survival_coverage_games"],
        "own_main_24_survival_coverage_denominator": temporal["own_main_24_survival_coverage_denominator"],
        "temporal_aggregate": temporal,
    }


def _delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    mapping = {
        "low_cards": "low_cards_per_game",
        "low_share": "low_share",
        "big_printed_vp": "big_printed_vp_per_game",
        "first_big_main": "first_big_main",
        "first_big_coverage": "first_big_coverage",
        "early_low_cards": "early_low_cards_per_game",
        "early_discount_redemptions": "early_discount_redemptions_per_game",
        "noble_coverage": "noble_coverage",
        "vp_per_own_main": "vp_per_own_main",
        "own_main_12_vp_mean": "own_main_12_vp_mean",
        "own_main_24_vp_mean": "own_main_24_vp_mean",
    }
    return {key: left.get(value) - right.get(value)
            if type(left.get(value)) in (int, float) and type(right.get(value)) in (int, float)
            else None for key, value in mapping.items()}


def aggregate(
    plan: Mapping[str, Any], result: Mapping[str, Any], attempts: Sequence[Mapping[str, Any]],
    profiles_by_game: Mapping[str, Any], profile_receipt: Mapping[str, Any],
    model_shas: Mapping[str, str | None], policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce dynamic coverage, three-actor common aggregates and two comparisons."""
    expected = expected_grid(plan)
    attempt_map: dict[tuple[str, str, int, int], Mapping[str, Any]] = {}
    for row in attempts:
        key = _attempt_key(row)
        require(key in expected, f"unexpected bounded_eval attempt: {key}")
        require(key not in attempt_map, f"duplicate bounded_eval logical attempt: {key}")
        attempt_map[key] = row
    require(set(model_shas) >= set(MODEL_IDS), "M79 actor identity map is incomplete")
    require(model_shas.get("a") is not None,
            "M79 result has no frozen candidate artifact SHA256")
    flattened = _verify_profile_binding(attempt_map, profiles_by_game, profile_receipt, model_shas)
    profile_map = {(row["game_key"], row["seat"]): row for row in flattened}
    pair_rows = result.get("pairs")
    require(isinstance(pair_rows, list), "M79 result lacks the established pair schema")
    pair_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in pair_rows:
        require(isinstance(row, dict) and isinstance(row.get("candidate"), str)
                and isinstance(row.get("opponent"), str)
                and isinstance(row.get("candidate_metrics"), dict)
                and isinstance(row.get("opponent_metrics"), dict)
                and isinstance(row.get("seats"), list), "malformed M79 pair result")
        key = (row["candidate"], row["opponent"])
        require(key not in pair_map, f"duplicate result pair: {key}")
        pair_map[key] = row

    complete_common: list[str] = []
    excluded: list[dict[str, Any]] = []
    evaluation = plan["evaluation"]
    for opponent in evaluation["common_opponents"]:
        missing = []
        for model in evaluation["common_actors"]:
            for seed in _range(evaluation["common_seed_by_opponent"][opponent], opponent):
                for seat in (0, 1):
                    key = (model, opponent, seed, seat)
                    if key not in attempt_map or _status(attempt_map[key]) != "COMPLETED":
                        missing.append({"model": model, "seed": seed, "seat": seat,
                                        "state": _status(attempt_map.get(key))})
            if (model, opponent) not in pair_map:
                missing.append({"model": model, "result_pair": "NOT_RUN"})
        if not missing:
            complete_common.append(opponent)
        else:
            excluded.append({"opponent": opponent, "reason": "NOT_ALL_THREE_ACTORS_COMPLETE",
                             "missing_or_failed": missing})

    completed_profiles: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, attempt in attempt_map.items():
        if _status(attempt) != "COMPLETED":
            continue
        model, opponent, seed, candidate_seat = key
        game_key = f"{model}/{opponent}/seed-{seed}/seat-{candidate_seat}"
        for actor_seat in (0, 1):
            row = profile_map[(game_key, actor_seat)]
            if actor_seat == candidate_seat:
                require(row["model"] == model, f"candidate profile identity drift: {game_key}")
                completed_profiles[(model, opponent)].append(row)

    per_opponent = []
    for model, opponent in sorted(pair_map):
        profile_rows = completed_profiles.get((model, opponent), [])
        profile_rows = [row for row in profile_rows if row["model"] == model]
        per_opponent.append({
            "model": model, "opponent": opponent,
            "result": pair_map[(model, opponent)],
            "profile": _profile_behavior(profile_rows) if profile_rows else None,
            "profile_status": "PASS" if profile_rows else "NOT_RUN",
        })

    model_profiles: dict[str, dict[str, Any]] = {}
    for model in MODEL_IDS:
        rows = [row for opponent in complete_common
                for row in completed_profiles.get((model, opponent), []) if row["model"] == model]
        by_opponent = {
            opponent: _profile_behavior([row for row in completed_profiles[(model, opponent)]
                                         if row["model"] == model])
            for opponent in complete_common
        }
        model_profiles[model] = {
            "sha256": model_shas[model],
            "status": "DESCRIPTIVE" if rows else "INSUFFICIENT",
            "metrics": _profile_behavior(rows) if rows else None,
            "opponents": complete_common[:],
            "by_opponent": by_opponent,
            "by_opponent_and_seat": [
                {"opponent": opponent, "seat": seat,
                 "metrics": _profile_behavior([row for row in completed_profiles[(model, opponent)]
                                                if row["model"] == model and row["seat"] == seat])}
                for opponent in complete_common for seat in (0, 1)
            ],
        }

    if complete_common:
        parent_comparison = _delta(model_profiles["a"]["metrics"], model_profiles["base"]["metrics"])
        style_comparison = _delta(model_profiles["a"]["metrics"], model_profiles["style-reference"]["metrics"])
        from scripts import prism_style_atlas
        route = prism_style_atlas.classify(style_comparison, policy, matched=True)
        if route.get("level") not in ("INSUFFICIENT", "DESCRIPTIVE"):
            route["level"] = "DESCRIPTIVE"
        route.update({
            "evidence_level": route.pop("level", "INSUFFICIENT"),
            "reference": "style-reference",
            "reference_sha256": model_shas["style-reference"],
            "parent_comparison": "stored separately; never substituted for the fixed style reference",
        })
    else:
        parent_comparison = {key: None for key in _delta({}, {}).keys()}
        style_comparison = {key: None for key in _delta({}, {}).keys()}
        route = {"route": "undetermined", "evidence_level": "INSUFFICIENT",
                 "reason": "NO_COMPLETE_COMMON_OPPONENT_GRID_ACROSS_A_BASE_AND_STYLE_REFERENCE",
                 "reference_sha256": model_shas["style-reference"]}

    status_by_state = Counter(_status(attempt_map.get(key)) for key in expected)
    missing = [{"model": key[0], "opponent": key[1], "seed": key[2], "seat": key[3],
                "state": _status(attempt_map.get(key))}
               for key in sorted(expected) if _status(attempt_map.get(key)) != "COMPLETED"]
    missing_pairs = [list(key) for key in sorted(set((model, opponent) for model, opponent, _, _ in expected)
                                                 - set(pair_map))]
    return {
        "format": FORMAT,
        "status": result.get("execution_status", result.get("status", "RESULT_AVAILABLE")),
        "identity": {
            "candidate": {"model": "a", "label": "M79 c20" if model_shas["a"] else "M79 candidate (NOT_RUN)",
                          "sha256": model_shas["a"],
                          "status": "FROZEN" if model_shas["a"] else "NOT_RUN"},
            "parent": {"model": "base", "label": plan.get("parent_label", "M75 c20"),
                       "sha256": model_shas["base"]},
            "style_reference": {"model": "style-reference", "label": "Balance v0.2.0",
                                 "sha256": model_shas["style-reference"]},
        },
        "competitive": {
            "status": "PASS" if result.get("statistics", {}).get("overall_status") == "PASS" else
                      result.get("statistics", {}).get("overall_status", "SEE_FROZEN_RESULT"),
            "gates": result.get("statistics", result.get("gates", {})),
            "pairs": pair_rows,
            "missing_result_pairs": missing_pairs,
            "dynamic_grid": {
                "planned_logical_attempts": len(expected),
                "recorded_attempts": len(attempt_map),
                "completed_attempts": sum(_status(row) == "COMPLETED" for row in attempt_map.values()),
                "status_counts": dict(status_by_state),
                "nonterminal_or_unrecorded": missing,
            },
        },
        "profile": {
            "evidence_level": "DESCRIPTIVE" if complete_common else "INSUFFICIENT",
            "complete_common_opponents": complete_common,
            "excluded_common_opponents": excluded,
            "models": model_profiles,
            "per_opponent": per_opponent,
            "comparisons": {"candidate_vs_parent": parent_comparison,
                            "candidate_vs_fixed_style_reference": style_comparison},
            "route_recommendation": route,
            "policy_level_ceiling": "DESCRIPTIVE",
        },
        "uses": (["M79 已冻结候选可供下一轮候选评审", "后续评测候选", "描述性行为研究"]
                 if model_shas["a"] else ["NOT_RUN：没有可用M79候选"]),
        "publication": {"published": False, "default_replaced": False, "deployed": False},
        "delivery": {"offline_archive": "PASS", "visual": "PENDING",
                     "all_sync": "PENDING", "new_games_by_archive": 0},
        "statistics": result.get("statistics", {}),
    }


def not_run_card(plan: Mapping[str, Any], plan_sha256: str, reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create an identity-bound NOT_RUN record without inventing an M79 checkpoint."""
    shas = _model_shas(plan, None)
    planned = expected_grid(plan)
    identity = {
        "candidate": {"model": "a", "label": "M79 candidate (NOT_RUN)", "sha256": None,
                      "status": "NOT_RUN", "planned_checkpoint_rule": plan["training"]["candidate"],
                      "reason": reason},
        "parent": {"model": "base", "label": plan.get("parent_label", "M75 c20"),
                   "sha256": shas["base"], "status": "IDENTITY_FROM_FROZEN_PLAN"},
        "style_reference": {"model": "style-reference", "label": "Balance v0.2.0",
                             "sha256": shas["style-reference"], "status": "IDENTITY_FROM_FROZEN_PLAN"},
    }
    card = {
        "format": FORMAT,
        "status": "NOT_RUN",
        "identity": identity,
        "competitive": {"status": "NOT_RUN", "gates": {}, "pairs": [],
                         "dynamic_grid": {"planned_logical_attempts": len(planned),
                                          "recorded_attempts": 0, "completed_attempts": 0,
                                          "status_counts": {"NOT_RUN": len(planned)},
                                          "nonterminal_or_unrecorded": []}},
        "profile": {"evidence_level": "NOT_RUN", "complete_common_opponents": [],
                    "excluded_common_opponents": [
                        {"opponent": opponent, "reason": "M79_RESULT_NOT_RUN"}
                        for opponent in plan["evaluation"]["common_opponents"]
                    ], "models": {model: {"sha256": shas[model], "status": "NOT_RUN", "metrics": None}
                                  for model in MODEL_IDS},
                    "per_opponent": [],
                    "comparisons": {"candidate_vs_parent": None,
                                    "candidate_vs_fixed_style_reference": None},
                    "route_recommendation": {"route": "undetermined", "evidence_level": "NOT_RUN",
                                              "reason": "NO_M79_C20_OR_EVALUATION_RESULT"},
                    "policy_level_ceiling": "DESCRIPTIVE"},
        "uses": ["NOT_RUN：没有可用M79候选供后续评测或路线归档"],
        "publication": {"published": False, "default_replaced": False, "deployed": False},
        "delivery": {"offline_archive": "PASS", "visual": "PENDING",
                     "all_sync": "PENDING", "new_games_by_archive": 0,
                     "blocking_reason": reason},
        "statistics": {"status": "NOT_RUN", "planned_logical_attempts": len(planned),
                       "completed_attempts": 0, "reason": reason},
    }
    receipt = {"format": "prism-m79-archive-receipt-v1", "status": "NOT_RUN",
               "plan_sha256": plan_sha256, "result_status": "NOT_RUN",
               "candidate_sha256": None, "new_games": 0, "visual": "PENDING"}
    return card, receipt


def _validate_input_receipt(
    plan: Mapping[str, Any], result: Mapping[str, Any], verified: Mapping[str, Any],
    plan_sha256: str, result_sha256: str, evaluation_plan_sha256: str,
    transfer_manifest_sha256: str,
) -> tuple[dict[str, str | None], dict[str, Any], list[dict[str, Any]]]:
    require(verified.get("format") == INPUT_FORMAT, "unsupported M79 verified-input bundle")
    receipt = verified.get("identity_receipt")
    require(isinstance(receipt, dict) and receipt.get("format") == IDENTITY_RECEIPT_FORMAT
            and receipt.get("status") == "PASS", "M79 identity receipt is missing or not PASS")
    for key, expected in (("plan_sha256", plan_sha256), ("result_sha256", result_sha256),
                          ("evaluation_plan_sha256", evaluation_plan_sha256),
                          ("transfer_manifest_sha256", transfer_manifest_sha256)):
        require(receipt.get(key) == expected, f"M79 identity receipt {key} mismatch")
    require(receipt.get("evaluation_integrity_status") == "PASS"
            and receipt.get("transfer_integrity_status") == "PASS",
            "bounded_eval tree or transfer integrity receipt is not PASS")
    expected = expected_grid(plan)
    require(receipt.get("expected_grid_sha256") == canonical_grid(sorted(expected)),
            "identity receipt expected grid mismatch")
    model_shas = _model_shas(plan, result)
    require(model_shas["a"] is not None,
            "M79 result lacks candidate_sha256.a; cannot bind a candidate artifact")
    receipt_shas = receipt.get("model_sha256")
    require(isinstance(receipt_shas, dict)
            and all(receipt_shas.get(key) == value for key, value in model_shas.items()),
            "M79 actor identity receipt mismatch")
    require(receipt.get("mode") == plan["evaluation"]["mode"], "M79 evaluation mode drift")
    _hex_sha(receipt.get("rules_sha256"), "rules SHA256")
    attempts = verified.get("attempts")
    require(isinstance(attempts, list), "verified-input bundle lacks bounded_eval attempts")
    observed_keys = [_attempt_key(row) for row in attempts]
    require(len(observed_keys) == len(set(observed_keys)), "duplicate verified attempt identities")
    require(receipt.get("observed_grid_sha256") == canonical_grid(observed_keys),
            "identity receipt observed grid mismatch")
    profile_receipt = verified.get("profile_receipt")
    require(isinstance(profile_receipt, dict)
            and profile_receipt.get("format") == m79_profile.RECEIPT_FORMAT,
            "M79 saved-replay profile receipt missing or unsupported")
    profile_model_shas = {**model_shas, **receipt_shas}
    flattened = _verify_profile_binding(attempts={key: row for key, row in zip(observed_keys, attempts)},
                                        profiles_by_game=verified.get("profiles_by_game", {}),
                                        profile_receipt=profile_receipt, model_shas=profile_model_shas)
    require(receipt.get("profile_receipt_sha256") == hashlib.sha256(canonical(profile_receipt)).hexdigest(),
            "M79 identity receipt is not bound to the replay-profile receipt")
    require(receipt.get("candidate_sha256") == result.get("candidate_sha256", {}).get("a"),
            "M79 candidate result identity mismatch")
    return model_shas, profile_receipt, flattened


def extract(
    plan: Mapping[str, Any], result: Mapping[str, Any], verified: Mapping[str, Any],
    *, plan_sha256: str, result_sha256: str, evaluation_plan_sha256: str,
    transfer_manifest_sha256: str, policy: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract from explicitly identity-verified bounded_eval and replay inputs."""
    model_shas, profile_receipt, _ = _validate_input_receipt(
        plan, result, verified, plan_sha256, result_sha256,
        evaluation_plan_sha256, transfer_manifest_sha256,
    )
    style_plan = plan["style"]
    require(policy.get("reference_sha256") == model_shas["style-reference"],
            "fixed style policy/reference identity mismatch")
    ceiling = style_plan.get("level_ceiling")
    require(isinstance(ceiling, str) and ceiling.split(";", 1)[0].strip() == "DESCRIPTIVE",
            "M79 style evidence ceiling drift")
    statistics = aggregate(plan, result, verified["attempts"], verified["profiles_by_game"],
                           profile_receipt, model_shas, policy)
    statistics["identity_receipt"] = verified["identity_receipt"]
    card = {
        **statistics,
        "status": result.get("execution_status", result.get("status", "RESULT_AVAILABLE")),
        "lineage": {"parent": statistics["identity"]["parent"],
                    "initialization": plan["training"]["initialization"],
                    "training_seed_count": plan["training"]["training_seed_count"],
                    "training_target": "competitive outcome; style_beta=0; style_value_weight=0"},
        "uses": (["M79 已冻结候选可供下一轮候选评审", "后续评测候选", "描述性行为研究"]
                 if model_shas["a"] else ["NOT_RUN：没有可用M79候选"]),
        "publication": {"published": False, "default_replaced": False, "deployed": False},
        "delivery": {"offline_archive": "PASS", "visual": "PENDING", "all_sync": "PENDING",
                     "new_games_by_archive": 0},
    }
    card["identity"]["plan_sha256"] = plan_sha256
    receipt = {
        "format": "prism-m79-archive-receipt-v1", "status": "PASS_OFFLINE_ARCHIVE",
        "plan_sha256": plan_sha256, "result_sha256": result_sha256,
        "evaluation_plan_sha256": evaluation_plan_sha256,
        "transfer_manifest_sha256": transfer_manifest_sha256,
        "candidate_sha256": model_shas["a"], "profile_receipt_sha256": hashlib.sha256(canonical(profile_receipt)).hexdigest(),
        "completed_replays_verified": profile_receipt["games_verified"],
        "new_games": 0, "visual": "PENDING",
    }
    return card, receipt


def render(card: Mapping[str, Any], prefix: str | Path) -> tuple[Path, Path]:
    """Write plain Markdown and responsive HTML; visual verification stays pending."""
    prefix = Path(prefix)
    identity = card["identity"]
    candidate = identity["candidate"]
    parent = identity["parent"]
    style = identity["style_reference"]
    route = card["profile"]["route_recommendation"]
    dynamic = card["competitive"]["dynamic_grid"]
    metrics = card["profile"]["models"]
    sections = [
        f"# {candidate['label']} · M79 产物归档",
        "",
        f"状态：{card['status']}。候选身份：{candidate.get('status', 'FROZEN')}；SHA：{candidate.get('sha256') or 'NOT_RUN'}。",
        f"父代：{parent['label']}，SHA256 `{parent['sha256']}`。",
        f"固定风格参照：{style['label']}，SHA256 `{style['sha256']}`。",
        "",
        "## 竞技结果",
        "",
        f"{card['competitive']['status']}；计划 {dynamic['planned_logical_attempts']} 局，记录 {dynamic['recorded_attempts']} 项，完成 {dynamic['completed_attempts']} 局。",
        f"未完成或未记录项：{len(dynamic['nonterminal_or_unrecorded'])}；原始配对门见 JSON / statistics 文件。",
        "",
        "## 画像与路线",
        "",
        f"完整三模型共同对手：{', '.join(card['profile']['complete_common_opponents']) or '无'}。",
        f"路线建议：{route.get('route', 'undetermined')}；证据等级 {route.get('evidence_level', 'INSUFFICIENT')}；上限 DESCRIPTIVE。",
        "父代比较与固定 Balance v0.2.0 比较分别保存，不互相替代。",
        "",
        "| 模型 | 局数 | Main 12 VP | Main 12 覆盖 | Main 24 VP | Main 24 覆盖 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in MODEL_IDS:
        row = metrics[model]
        metric = row.get("metrics")
        if not metric:
            sections.append(f"| {model} | NOT_RUN | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED |")
            continue
        sections.append(
            f"| {model} | {metric['games']} | {metric['own_main_12_vp_mean']} | "
            f"{metric['own_main_12_survival_coverage']:.1%} "
            f"({metric['own_main_12_survival_coverage_games']}/{metric['own_main_12_survival_coverage_denominator']}) | "
            f"{metric['own_main_24_vp_mean']} | {metric['own_main_24_survival_coverage']:.1%} "
            f"({metric['own_main_24_survival_coverage_games']}/{metric['own_main_24_survival_coverage_denominator']}) |"
        )
    sections += [
        "",
        "未到 Main 12/24 的短局保留在覆盖分母中，快照为 NOT_MEASURED。贵族选择不增加本人 Main；时点快照取已验证行动后的公开观察或终局分数。",
        "",
        "## 发布与交付",
        "",
        "未发布、未默认替换、未部署。视觉验收 PENDING，等待最终产物与回执绑定。",
    ]
    md = prefix.with_suffix(".md")
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("\n".join(sections) + "\n", encoding="utf-8")

    esc = html.escape
    model_rows = []
    for model in MODEL_IDS:
        row = metrics[model]
        metric = row.get("metrics")
        if not metric:
            values = ("NOT_RUN", "NOT_MEASURED", "NOT_MEASURED", "NOT_MEASURED", "NOT_MEASURED")
        else:
            values = (
                str(metric["games"]), str(metric["own_main_12_vp_mean"]),
                f"{metric['own_main_12_survival_coverage']:.1%} ({metric['own_main_12_survival_coverage_games']}/{metric['own_main_12_survival_coverage_denominator']})",
                str(metric["own_main_24_vp_mean"]),
                f"{metric['own_main_24_survival_coverage']:.1%} ({metric['own_main_24_survival_coverage_games']}/{metric['own_main_24_survival_coverage_denominator']})",
            )
        model_rows.append("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in (model, *values)) + "</tr>")
    html_path = prefix.with_suffix(".html")
    document = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M79 候选归档</title>
<style>body{{margin:0;background:#f3f6fb;color:#1d2b3a;font:16px/1.65 system-ui,sans-serif}}main{{max-width:1080px;margin:28px auto;padding:20px}}section{{background:white;border:1px solid #dce4ef;border-radius:14px;padding:22px;margin:18px 0}}h1{{font-size:30px}}h2{{font-size:21px}}.sha{{overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace}}.status{{border-left:4px solid #bd7d22;padding-left:14px}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:700px;font-variant-numeric:tabular-nums}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #e0e7f0}}th{{background:#edf2f8}}@media(max-width:600px){{main{{padding:12px;margin:0}}section{{padding:15px}}h1{{font-size:25px}}}}</style>
<main><h1>M79 · 候选产物归档</h1><section class="status"><p>状态：{esc(str(card['status']))}；候选 SHA：{esc(str(candidate.get('sha256') or 'NOT_RUN'))}</p><p>竞技：{esc(str(card['competitive']['status']))}；{dynamic['completed_attempts']}/{dynamic['planned_logical_attempts']} 局完成。</p><p>路线：{esc(str(route.get('route', 'undetermined')))} · {esc(str(route.get('evidence_level', 'INSUFFICIENT')))} · 上限 DESCRIPTIVE</p></section>
<section><h2>模型身份</h2><p>候选：{esc(str(candidate.get('label')))} · {esc(str(candidate.get('status', 'FROZEN')))}</p><p class="sha">候选 SHA256 {esc(str(candidate.get('sha256') or 'NOT_RUN'))}</p><p>父代：{esc(str(parent['label']))}</p><p class="sha">{esc(str(parent['sha256']))}</p><p>固定参照：{esc(str(style['label']))}</p><p class="sha">{esc(str(style['sha256']))}</p></section>
<section><h2>三模型共同画像</h2><p>完整共同对手：{esc(', '.join(card['profile']['complete_common_opponents']) or '无')}。短局留在覆盖分母中，未到窗口记为 NOT_MEASURED。</p><div class="scroll"><table><thead><tr><th>模型</th><th>局数</th><th>Main 12 VP</th><th>Main 12 覆盖</th><th>Main 24 VP</th><th>Main 24 覆盖</th></tr></thead><tbody>{''.join(model_rows)}</tbody></table></div></section>
<section><h2>交付状态</h2><p>未发布 · 未默认替换 · 未部署 · 视觉验收 PENDING</p><p>原始有界评测结果及失败账本按输入 SHA 和回执引用。</p></section></main></html>"""
    html_path.write_text(document, encoding="utf-8")
    return md, html_path


def _write_outputs(card: dict[str, Any], receipt: dict[str, Any], prefix: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    require("m75" not in str(prefix).lower(), "M79 archive output path cannot target M75 artifacts")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    statistics_path = prefix.with_suffix(".statistics.json")
    md_path, html_path = render(card, prefix)
    write_json(statistics_path, card.get("statistics", {}))
    json_path = prefix.with_suffix(".json")
    write_json(json_path, card)
    receipt["outputs"] = {path.name: digest(path) for path in (json_path, md_path, html_path, statistics_path)}
    receipt["visual"] = "PENDING"
    receipt_path = prefix.with_suffix(".receipt.json")
    write_json(receipt_path, receipt)
    return card, receipt


def _under(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), f"raw evidence path escapes root: {relative}")
    return path


def _transfer_members(raw_root: Path) -> dict[str, str]:
    payload = read_json(raw_root / "transfer-manifest.json")
    if isinstance(payload, dict) and isinstance(payload.get("members"), dict):
        payload = payload["members"]
    require(isinstance(payload, dict), "M79 transfer manifest must map paths to SHA256 values")
    members: dict[str, str] = {}
    for relative, value in payload.items():
        require(isinstance(relative, str) and relative and "\\" not in relative,
                "transfer manifest has an invalid relative path")
        expected = value.get("sha256") if isinstance(value, dict) else value
        expected = _hex_sha(expected, f"transfer SHA256 for {relative}")
        path = _under(raw_root, relative)
        require(path.is_file() and digest(path) == expected, f"transferred file missing or changed: {relative}")
        members[relative] = expected
    return members


def _require_transferred(raw_root: Path, members: Mapping[str, str], path: Path) -> str:
    relative = path.resolve().relative_to(raw_root.resolve()).as_posix()
    require(relative in members and digest(path) == members[relative],
            f"raw evidence is not bound by transfer-manifest.json: {relative}")
    return relative


def _plan_style_policy(plan: Mapping[str, Any]) -> dict[str, Any]:
    style = plan["style"]
    ceiling = style.get("level_ceiling")
    require(isinstance(ceiling, str) and ceiling.split(";", 1)[0].strip() == "DESCRIPTIVE",
            "M79 style evidence ceiling drift")
    path = _under(ROOT, style["policy_path"])
    require(path.is_file() and digest(path) == style["policy_sha256"], "fixed M79 style policy SHA drift")
    policy = read_json(path)
    require(policy.get("reference_sha256") == plan["assets"]["style-reference"]["sha256"],
            "fixed style policy/reference identity mismatch")
    return policy


def _candidate_from_raw(raw_root: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    """Return a verified frozen candidate identity when its registry and bytes exist."""
    registry_path = raw_root / "candidate-registry.json"
    completion_path = raw_root / "campaigns/a/worker-completion.json"
    candidate_path = raw_root / "campaigns/a/cycle-20-export/weights.json"
    audit_path = raw_root / "audits/a/audit.json"
    if registry_path.is_file():
        registry = read_json(registry_path)
        row = registry.get("models", {}).get("a", {})
        candidate_path = _candidate_path(raw_root, row.get("path"), candidate_path)
    else:
        registry, row = {}, {}
    completion = read_json(completion_path) if completion_path.is_file() else {}
    reported_sha = row.get("sha256") or completion.get("weights_sha256")
    actual_sha = digest(candidate_path) if candidate_path.is_file() else None
    if actual_sha and reported_sha:
        require(actual_sha == reported_sha, "M79 candidate weight SHA differs from its registry/completion")
    verified_sha = actual_sha if actual_sha == reported_sha and reported_sha else None
    audit = read_json(audit_path) if audit_path.is_file() else {}
    frozen = bool(
        verified_sha and registry.get("status") == "FROZEN_FINAL_C20_BEFORE_EVALUATION"
        and audit.get("status") == "PASS_TRAINING_ARTIFACT_AUDIT"
        and audit.get("weights_sha256") == verified_sha
        and row.get("audit_sha256") == digest(audit_path)
        and registry.get("parent_sha256") == plan["assets"]["parent"]["sha256"]
    )
    if frozen:
        status, label = "FROZEN", "M79 c20"
    elif verified_sha:
        status, label = "ARTIFACT_PRESENT_AUDIT_PENDING", "M79 candidate artifact (not frozen)"
    else:
        status, label = "NOT_RUN", "M79 candidate (NOT_RUN)"
    return {
        "model": "a", "label": label, "sha256": verified_sha, "status": status,
        "reported_sha256": reported_sha if verified_sha is None else None,
        "path": str(candidate_path) if candidate_path.is_file() else None,
        "training_state": completion.get("status", "IN_PROGRESS" if not completion else "UNKNOWN"),
    }


def _candidate_path(raw_root: Path, declared: Any, fallback: Path) -> Path:
    if not isinstance(declared, str) or not declared:
        return fallback
    normalized = declared.replace("\\", "/")
    marker = "campaigns/"
    if marker in normalized:
        normalized = normalized[normalized.index(marker):]
    candidate = Path(normalized)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve()
            candidate.relative_to(raw_root.resolve())
            return candidate
        except ValueError:
            return fallback
    try:
        resolved = (raw_root / candidate).resolve()
        resolved.relative_to(raw_root.resolve())
        return resolved
    except ValueError:
        return fallback


def _execution_snapshot(raw_root: Path, plan: Mapping[str, Any], result_path: Path) -> dict[str, Any]:
    def optional(path: Path) -> Any:
        return read_json(path) if path.is_file() else None

    pipeline_status_path = raw_root / "pipeline/status.json"
    pipeline_completion_path = raw_root / "pipeline/completion.json"
    progress_path = raw_root / "campaigns/a/control/live-progress.json"
    worker_path = raw_root / "campaigns/a/worker-completion.json"
    pipeline_status = optional(pipeline_status_path)
    pipeline_completion = optional(pipeline_completion_path)
    progress = optional(progress_path)
    worker = optional(worker_path)
    stages = {}
    for stage in ("train", "audit", "candidates", "curve", "evaluate", "report"):
        value = optional(raw_root / f"pipeline/{stage}.completion.json")
        stages[stage] = value.get("status", "NOT_RECORDED") if isinstance(value, dict) else "NOT_RECORDED"

    expected_count = len(expected_grid(plan))
    ledger_count = entry_count = completed_count = 0
    running_ledger = False
    for shard in _raw_shards(raw_root):
        ledger_path = raw_root / "evaluation" / shard["label"] / "ledger.json"
        if not ledger_path.is_file():
            continue
        ledger_count += 1
        ledger = read_json(ledger_path)
        entries = ledger.get("entries", {})
        require(isinstance(entries, dict), f"invalid M79 shard ledger: {shard['label']}")
        entry_count += len(entries)
        completed_count += sum(entry.get("state") == "COMPLETED" for entry in entries.values())
        running_ledger |= ledger.get("execution_state") == "RUNNING"

    if pipeline_completion:
        state, source = pipeline_completion.get("state", "COMPLETED"), "pipeline/completion.json"
    elif pipeline_status:
        state, source = pipeline_status.get("state", "UNKNOWN"), "pipeline/status.json"
        if pipeline_status.get("phase"):
            state = f"{state}:{pipeline_status['phase']}"
    elif worker:
        state, source = "TRAINING_COMPLETE", "campaigns/a/worker-completion.json"
    elif progress:
        state, source = "TRAINING_IN_PROGRESS_AS_RECORDED", "campaigns/a/control/live-progress.json"
    elif ledger_count:
        state = "EVALUATION_IN_PROGRESS_AS_RECORDED" if running_ledger else "EVALUATION_INCOMPLETE"
        source = "evaluation/*/ledger.json"
    elif _raw_shards(raw_root):
        state, source = "EVALUATION_PREPARED", "evaluation-plan.json"
    else:
        state, source = "UNKNOWN", None

    if not ledger_count:
        evaluation_state = "NOT_RUN"
    elif running_ledger:
        evaluation_state = "IN_PROGRESS_AS_RECORDED"
    elif entry_count < expected_count:
        evaluation_state = "INCOMPLETE"
    elif completed_count < expected_count:
        evaluation_state = "COMPLETE_WITH_RETAINED_FAILURES"
    else:
        evaluation_state = "COMPLETE"

    observed = [value for value in (pipeline_status, pipeline_completion, progress, worker) if isinstance(value, dict)]
    latest = max(observed, key=lambda item: item.get("observed_at", item.get("finished_at", 0)), default={})
    return {
        "state": state,
        "state_source": source,
        "observation_state": "STORED_EVIDENCE_ONLY" if observed else "NOT_OBSERVED",
        "observed_at": latest.get("observed_at", latest.get("finished_at")),
        "node": latest.get("node"), "pid": latest.get("pid"),
        "create_time": latest.get("create_time"),
        "execution_sha256": latest.get("execution_sha256"),
        "result_path": str(result_path),
        "result_sha256": digest(result_path) if result_path.is_file() else None,
        "training": {
            "state": "COMPLETE" if worker else "IN_PROGRESS_AS_RECORDED" if progress else "UNKNOWN",
            "worker_completion": worker,
            "live_progress": progress,
            "pipeline_stage": stages["train"],
        },
        "independent_evaluation": {
            "state": evaluation_state, "ledger_shards": ledger_count,
            "recorded_attempts": entry_count, "completed_attempts": completed_count,
            "planned_attempts": expected_count,
            "pipeline_stage": stages["evaluate"],
        },
        "pipeline_stages": stages,
    }


def _raw_shards(raw_root: Path) -> list[dict[str, Any]]:
    path = raw_root / "evaluation-plan.json"
    if not path.is_file():
        return []
    plan = read_json(path)
    if plan.get("format") != "prism-m79-bounded-shards-v1":
        return []
    shards = plan.get("shards", [])
    return shards if isinstance(shards, list) else []


def _shard_identities(config: Mapping[str, Any]) -> set[tuple[str, str, int, int]]:
    return {(model, opponent, seed, seat)
            for model in config["candidates"] for opponent in config["opponents"]
            for seed in config["seeds"] for seat in (0, 1)}


def _actor_sha(descriptor: Mapping[str, Any]) -> str:
    files = descriptor.get("files", [])
    sha = files[0].get("sha256") if files else descriptor.get("sha256")
    return _hex_sha(sha, "configured actor SHA256")


def _read_raw_inputs(
    plan: Mapping[str, Any], raw_root: Path, result: Mapping[str, Any],
    plan_sha: str, result_sha: str, evaluation_plan_path: Path, transfer_path: Path,
) -> dict[str, Any]:
    expected = expected_grid(plan)
    evaluation_plan = read_json(evaluation_plan_path)
    require(evaluation_plan.get("format") == "prism-m79-bounded-shards-v1"
            and evaluation_plan.get("plan_sha256") == plan_sha,
            "M79 evaluation-plan does not bind the frozen execution plan")
    members = _transfer_members(raw_root)
    _require_transferred(raw_root, members, evaluation_plan_path)
    _require_transferred(raw_root, members, transfer_path) if "transfer-manifest.json" in members else None

    registry_path = raw_root / "candidate-registry.json"
    require(registry_path.is_file(), "M79 candidate registry is missing from raw root")
    _require_transferred(raw_root, members, registry_path)
    registry = read_json(registry_path)
    require(evaluation_plan.get("candidate_registry_sha256") == digest(registry_path),
            "M79 evaluation-plan candidate registry SHA mismatch")
    candidate = _candidate_from_raw(raw_root, plan)
    require(candidate["status"] == "FROZEN" and candidate["sha256"],
            "M79 c20 weights and audit are not verified in raw root")
    _require_transferred(raw_root, members, Path(candidate["path"]))
    require(result.get("candidate_sha256", {}).get("a") == candidate["sha256"],
            "M79 result and frozen candidate SHA differ")

    audit_path = raw_root / "audits/a/audit.json"
    require(audit_path.is_file(), "M79 final candidate audit is missing")
    _require_transferred(raw_root, members, audit_path)
    expected_shards = evaluation_plan.get("shards")
    require(isinstance(expected_shards, list), "M79 evaluation-plan shards missing")

    attempts: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    canonical_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    attempt_keys: set[tuple[str, str, int, int]] = set()
    rules_sha = None
    actor_shas: dict[str, str] = {"a": candidate["sha256"],
                                  "base": plan["assets"]["parent"]["sha256"],
                                  "style-reference": plan["assets"]["style-reference"]["sha256"]}

    for shard in expected_shards:
        label = shard.get("label")
        require(isinstance(label, str) and label, "M79 shard label missing")
        directory = _under(raw_root, f"evaluation/{label}")
        if not directory.is_dir():
            continue
        config_path, manifest_path, policy_path, ledger_path = (
            directory / name for name in ("config.json", "manifest.json", "policy.json", "ledger.json"))
        require(config_path.is_file() and manifest_path.is_file() and policy_path.is_file(),
                f"prepared M79 shard lacks config/manifest/policy: {label}")
        for path in (config_path, manifest_path, policy_path):
            _require_transferred(raw_root, members, path)
        config, manifest, policy = map(read_json, (config_path, manifest_path, policy_path))
        require(digest(manifest_path) == shard.get("manifest_sha256"), f"M79 shard manifest SHA mismatch: {label}")
        require(manifest.get("config_sha256") == hashlib.sha256(canonical(config)).hexdigest()
                and manifest.get("policy_sha256") == hashlib.sha256(canonical(policy)).hexdigest(),
                f"M79 shard config/policy binding mismatch: {label}")
        engine_sha = _hex_sha(config.get("engine", {}).get("sha256"), "M79 rules engine SHA256")
        rules_sha = rules_sha or engine_sha
        require(engine_sha == rules_sha, "M79 shards mix rule-engine identities")
        require(config.get("format") == "prism-ppo-fixed-eval-v1"
                and config.get("action_seed") == plan["evaluation"]["action_seed"],
                f"M79 shard mode/action seed drift: {label}")
        require(policy.get("automatic_game_retries") == 0
                and policy.get("ply_cap") == plan["evaluation"]["ply_cap"],
                f"M79 shard policy drift: {label}")
        keys = _shard_identities(config)
        require(keys and keys <= expected and not keys & seen, f"unexpected/duplicate M79 shard grid: {label}")
        require(shard.get("planned_games") == len(keys), f"M79 shard planned count mismatch: {label}")
        require(len(config["candidates"]) == 1 and len(config["opponents"]) == 1,
                f"M79 shard must bind one candidate/opponent: {label}")
        model, descriptor = next(iter(config["candidates"].items()))
        opponent, opponent_descriptor = next(iter(config["opponents"].items()))
        require(label == f"{model}-{opponent}-{min(seed for _, _, seed, _ in keys)}",
                f"M79 shard label does not match its frozen identity: {label}")
        require(descriptor.get("args", [None])[0] == "agent-prism"
                and opponent_descriptor.get("args", [None])[0] in ("agent-prism", "agent-heuristic-v02"),
                f"M79 shard is not both-greedy: {label}")
        expected_model_sha = actor_shas.get(model)
        configured_model_sha = _actor_sha(descriptor)
        require(expected_model_sha is not None and configured_model_sha == expected_model_sha,
                f"M79 candidate actor SHA drift: {label}")
        opponent_sha = _actor_sha(opponent_descriptor)
        expected_opponent_sha = plan["assets"].get(opponent, {}).get("sha256")
        if expected_opponent_sha:
            require(opponent_sha == expected_opponent_sha, f"M79 opponent SHA drift: {label}")
        elif opponent_descriptor.get("args", [None])[0] == "agent-heuristic-v02":
            require(opponent_sha == engine_sha, f"M79 heuristic engine SHA drift: {label}")
        else:
            raise ValueError(f"M79 opponent identity is not in frozen plan assets: {opponent}")
        previous = actor_shas.setdefault(opponent, opponent_sha)
        require(previous == opponent_sha, f"M79 opponent SHA changed across shards: {opponent}")
        seen.update(keys)

        if not ledger_path.is_file():
            continue
        _require_transferred(raw_root, members, ledger_path)
        ledger = read_json(ledger_path)
        require(ledger.get("manifest_sha256") == digest(manifest_path), f"M79 ledger manifest mismatch: {label}")
        entries = ledger.get("entries")
        require(isinstance(entries, dict), f"M79 ledger entries missing: {label}")
        for entry_key, entry in entries.items():
            parts = entry_key.split("/")
            require(len(parts) == 4 and parts[2].startswith("seed-") and parts[3].startswith("seat-"),
                    f"malformed M79 ledger key: {entry_key}")
            key = (parts[0], parts[1], int(parts[2][5:]), int(parts[3][5:]))
            require(key in keys and key not in attempt_keys,
                    f"unexpected or duplicate M79 ledger attempt: {entry_key}")
            attempt_keys.add(key)
            state = entry.get("state")
            require(state in ("COMPLETED", "RETAINED_FAILURE", "DISPATCHED"),
                    f"unknown M79 ledger state {state}: {entry_key}")
            attempt = {"model": key[0], "opponent": key[1], "seed": key[2], "seat": key[3], "state": state}
            if state != "COMPLETED":
                if entry.get("kind"):
                    attempt["kind"] = entry["kind"]
                attempts.append(attempt)
                continue

            row = entry.get("row")
            require(isinstance(row, dict)
                    and (row.get("candidate"), row.get("opponent"), row.get("seed"), row.get("candidate_seat")) == key,
                    f"M79 completed row identity mismatch: {entry_key}")
            evidence = entry.get("evidence_sha256")
            require(isinstance(evidence, dict) and evidence, f"M79 completed attempt lacks evidence hashes: {entry_key}")
            game_dir = directory / "games" / key[0] / key[1] / f"seed-{key[2]}-seat-{key[3]}"
            actual_evidence = {}
            for evidence_path in game_dir.rglob("*"):
                if evidence_path.is_file():
                    relative = evidence_path.relative_to(game_dir).as_posix()
                    actual_evidence[relative] = digest(evidence_path)
                    _require_transferred(raw_root, members, evidence_path)
            require(actual_evidence == evidence, f"M79 game evidence differs from ledger: {entry_key}")
            replay_path = game_dir / "replay.json"
            replay_sha = evidence.get("replay.json")
            require(replay_path.is_file() and replay_sha, f"M79 completed replay missing: {entry_key}")
            replay = read_json(replay_path)
            report = read_json(game_dir / "report.json")
            require(replay.get("seed") == key[2]
                    and report.get("outcome", {}).get("status") == "completed"
                    and report.get("outcome", {}).get("result") == replay.get("result"),
                    f"M79 replay/report terminal identity mismatch: {entry_key}")
            ranks = replay.get("result", {}).get("ranks")
            require(isinstance(ranks, list) and len(ranks) == 2, f"M79 replay ranks missing: {entry_key}")
            score = 0.5 if ranks[key[3]] == ranks[1 - key[3]] else float(ranks[key[3]] < ranks[1 - key[3]])
            require(row.get("candidate_score") == score, f"M79 ledger score differs from replay: {entry_key}")
            attempts.append(attempt)
            canonical_rows.append({"candidate": key[0], "opponent": key[1], "seed": key[2],
                                   "candidate_seat": key[3], "candidate_score": score})
            profile_rows.append({
                "game_key": f"{key[0]}/{key[1]}/seed-{key[2]}/seat-{key[3]}",
                "replay_path": replay_path, "replay_sha256": replay_sha,
                "candidate_model": key[0], "opponent_model": key[1],
                "candidate_seat": key[3], "seed": key[2],
                "candidate_sha256": expected_model_sha, "opponent_sha256": opponent_sha,
                "opponent": key[1],
            })

    require(rules_sha is not None, "no transferred M79 shard config is available for rule identity")
    if result.get("pairs") is not None:
        require(isinstance(result["pairs"], list), "M79 result pair schema is malformed")
    profile_result = (m79_profile.profile_saved_replays(profile_rows)
                      if profile_rows else {
                          "profiles": {}, "verify_receipt": {
                              "format": m79_profile.RECEIPT_FORMAT, "status": "PASS",
                              "games_requested": 0, "games_verified": 0, "actor_profiles": 0,
                              "new_games": 0, "replays": [],
                          }})
    profile_receipt = profile_result["verify_receipt"]
    verified = {
        "format": INPUT_FORMAT,
        "attempts": attempts,
        "profiles_by_game": profile_result["profiles"],
        "profile_receipt": profile_receipt,
        "identity_receipt": {
            "format": IDENTITY_RECEIPT_FORMAT, "status": "PASS",
            "plan_sha256": plan_sha, "result_sha256": result_sha,
            "evaluation_plan_sha256": digest(evaluation_plan_path),
            "transfer_manifest_sha256": digest(transfer_path),
            "evaluation_integrity_status": "PASS", "transfer_integrity_status": "PASS",
            "expected_grid_sha256": canonical_grid(sorted(expected)),
            "observed_grid_sha256": canonical_grid([_attempt_key(row) for row in attempts]),
            "model_sha256": actor_shas,
            "rules_sha256": rules_sha, "mode": plan["evaluation"]["mode"],
            "candidate_sha256": candidate["sha256"],
            "profile_receipt_sha256": hashlib.sha256(canonical(profile_receipt)).hexdigest(),
        },
    }
    return {"verified": verified, "canonical_rows": canonical_rows, "candidate": candidate,
            "members": members, "registry": registry}


def _metric_counts(rows: Sequence[Mapping[str, Any]], candidate_side: bool = True) -> dict[str, Any]:
    scores = [row["candidate_score"] if candidate_side else 1.0 - row["candidate_score"]
              for row in rows]
    games = len(scores)
    wins = sum(score == 1 for score in scores)
    ties = sum(score == 0.5 for score in scores)
    losses = sum(score == 0 for score in scores)
    return {"games": games, "wins": wins, "ties": ties, "losses": losses,
            "win_rate_percent": 100 * wins / games if games else None,
            "score_rate": sum(scores) / games if games else None}


def _derived_pairs(plan: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    expected = expected_grid(plan)
    identities = sorted({(model, opponent) for model, opponent, _, _ in expected})
    pairs = []
    for model, opponent in identities:
        planned = sum(key[:2] == (model, opponent) for key in expected)
        selected = [row for row in rows if (row["candidate"], row["opponent"]) == (model, opponent)]
        seats = []
        for seat in (0, 1):
            subset = [row for row in selected if row["candidate_seat"] == seat]
            if subset:
                seats.append({"candidate_seat": seat,
                              "candidate": _metric_counts(subset),
                              "opponent": _metric_counts(subset, False),
                              "games": len(subset)})
        pairs.append({
            "candidate": model, "opponent": opponent,
            "candidate_metrics": _metric_counts(selected) if selected else None,
            "opponent_metrics": _metric_counts(selected, False) if selected else None,
            "seats": seats, "planned_games": planned, "completed_games": len(selected),
            "missing_games": planned - len(selected),
            "status": "COMPLETE" if len(selected) == planned else "INCOMPLETE",
            "source": "DERIVED_FROM_BOUNDED_EVAL_LEDGER_ROWS",
        })
    return pairs


def _check_result_pairs(result: Mapping[str, Any], plan: Mapping[str, Any],
                        rows: Sequence[Mapping[str, Any]]) -> None:
    pairs = result.get("pairs")
    require(isinstance(pairs, list), "M79 result lacks the established pair schema")
    expected = {(model, opponent) for model, opponent, _, _ in expected_grid(plan)}
    pair_map = {}
    for pair in pairs:
        require(isinstance(pair, dict) and isinstance(pair.get("candidate"), str)
                and isinstance(pair.get("opponent"), str)
                and isinstance(pair.get("candidate_metrics"), (dict, type(None)))
                and isinstance(pair.get("opponent_metrics"), (dict, type(None)))
                and isinstance(pair.get("seats"), list), "malformed M79 result pair")
        key = (pair["candidate"], pair["opponent"])
        require(key in expected and key not in pair_map, f"unexpected/duplicate M79 result pair: {key}")
        pair_map[key] = pair
    require(set(pair_map) == expected, "M79 result pairs do not cover the frozen pair grid")

    def check_counts(metrics: Any, subset: Sequence[Mapping[str, Any]], label: str) -> None:
        if not subset:
            return
        if not isinstance(metrics, dict) or not {"wins", "ties", "losses"} <= metrics.keys():
            return
        expected_metrics = _metric_counts(subset)
        require((metrics["wins"], metrics["ties"], metrics["losses"]) ==
                (expected_metrics["wins"], expected_metrics["ties"], expected_metrics["losses"]),
                f"M79 result W/D/L differs from ledger rows: {label}")

    for key, pair in pair_map.items():
        subset = [row for row in rows if (row["candidate"], row["opponent"]) == key]
        check_counts(pair["candidate_metrics"], subset, str(key))
        for seat_row in pair["seats"]:
            seat = seat_row.get("candidate_seat")
            require(type(seat) is int and seat in (0, 1), f"invalid result seat row: {key}")
            check_counts(seat_row.get("candidate"),
                         [row for row in subset if row["candidate_seat"] == seat],
                         f"{key}/seat-{seat}")


def _missing_result_build(plan: Mapping[str, Any], plan_sha: str, result_path: Path,
                          raw_root: Path, output_prefix: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    reason = "M79 result file is absent; candidate, execution, and evaluation are reported from saved evidence"
    card, receipt = not_run_card(plan, plan_sha, reason)
    snapshot = _execution_snapshot(raw_root, plan, result_path)
    candidate = _candidate_from_raw(raw_root, plan)
    card["status"] = snapshot["state"]
    card["execution"] = snapshot
    card["identity"]["plan_sha256"] = plan_sha
    card["identity"]["candidate"].update(candidate)
    if candidate["status"] == "FROZEN":
        card["uses"] = ["已冻结 M79 c20 候选评审", "后续独立评测", "描述性行为研究"]
    evaluation = snapshot["independent_evaluation"]
    card["competitive"]["status"] = evaluation["state"]
    card["competitive"]["dynamic_grid"].update({
        "recorded_attempts": evaluation["recorded_attempts"],
        "completed_attempts": evaluation["completed_attempts"],
        "status_counts": {evaluation["state"]: evaluation["recorded_attempts"]},
    })
    card["delivery"]["blocking_reason"] = reason
    receipt.update({"execution_state": snapshot["state"], "result_path": str(result_path),
                    "candidate_sha256": candidate["sha256"],
                    "independent_evaluation_state": evaluation["state"]})
    return _write_outputs(card, receipt, output_prefix)


def build(
    plan_path: str | Path, result_path: str | Path, raw_root: str | Path,
    output_prefix: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build directly from the frozen M79 plan and bounded_eval raw tree.

    A result-adjacent verified-input cache is generated from raw evidence when
    absent or stale. Owners never need to author it. `raw_root` remains read-only.
    """
    plan_path, result_path, raw_root, output_prefix = map(Path, (plan_path, result_path, raw_root, output_prefix))
    plan = read_json(plan_path)
    require(plan.get("round") == "M79", "archive requires the frozen M79 execution plan")
    plan_sha = digest(plan_path)
    evaluation_plan_path = raw_root / "evaluation-plan.json"
    transfer_path = raw_root / "transfer-manifest.json"
    has_result = result_path.is_file()
    if not has_result:
        snapshot = _execution_snapshot(raw_root, plan, result_path)
        if snapshot["independent_evaluation"]["ledger_shards"] == 0:
            return _missing_result_build(plan, plan_sha, result_path, raw_root, output_prefix)
        candidate = _candidate_from_raw(raw_root, plan)
        if candidate["status"] != "FROZEN":
            return _missing_result_build(plan, plan_sha, result_path, raw_root, output_prefix)
        result = {"candidate_sha256": {"a": candidate["sha256"]}, "pairs": []}
        result_sha = hashlib.sha256(canonical(result)).hexdigest()
    else:
        result = read_json(result_path)
        result_sha = digest(result_path)
    require(evaluation_plan_path.is_file() and transfer_path.is_file(),
            "M79 bounded_eval evaluation-plan or transfer manifest is missing")
    produced = _read_raw_inputs(plan, raw_root, result, plan_sha, result_sha,
                                evaluation_plan_path, transfer_path)

    from scripts import prism_m79_statistics
    computed_statistics = prism_m79_statistics.analyze(plan, produced["canonical_rows"])
    if has_result:
        frozen_statistics = result.get("statistics")
    else:
        frozen_statistics = None
        result = {
            "format": "prism-m79-mainline-result-derived-v1",
            "status": "RESULTS_DERIVED_FROM_RAW_LEDGERS",
            "execution_status": "RESULTS_DERIVED_FROM_RAW_LEDGERS",
            "candidate_sha256": {
                "a": produced["candidate"]["sha256"],
                "base": plan["assets"]["parent"]["sha256"],
                "style-reference": plan["assets"]["style-reference"]["sha256"],
            },
            "pairs": _derived_pairs(plan, produced["canonical_rows"]),
            "result_source": "bounded_eval raw ledgers; no report result file was present",
        }
        result_sha = hashlib.sha256(canonical(result)).hexdigest()
        produced["verified"]["identity_receipt"]["result_sha256"] = result_sha
    if frozen_statistics is not None:
        require(canonical(frozen_statistics) == canonical(computed_statistics),
                "M79 frozen result statistics do not reproduce from raw ledgers")
    result = dict(result)
    result["statistics"] = computed_statistics
    _check_result_pairs(result, plan, produced["canonical_rows"])
    require(result.get("candidate_sha256", {}).get("a") == produced["candidate"]["sha256"],
            "M79 result lacks the verified c20 artifact identity")
    policy = _plan_style_policy(plan)
    verified = produced["verified"]
    card, receipt = extract(
        plan, result, verified, plan_sha256=plan_sha, result_sha256=result_sha,
        evaluation_plan_sha256=digest(evaluation_plan_path),
        transfer_manifest_sha256=digest(transfer_path), policy=policy,
    )
    card["execution"] = _execution_snapshot(raw_root, plan, result_path)
    card["execution"].update({"state": result.get("dispatch_state", result.get("status", card["execution"]["state"])),
                              "result_source": str(result_path) if has_result else "DERIVED_FROM_RAW_BOUNDED_EVAL",
                              "derived_result_sha256": result_sha if not has_result else None})
    receipt.update({"result_path": str(result_path), "raw_root": str(raw_root),
                    "candidate_registry_sha256": digest(raw_root / "candidate-registry.json"),
                    "candidate_audit_sha256": digest(raw_root / "audits/a/audit.json")})
    cache_path = output_prefix.with_suffix(".verified-input-cache.json")
    write_json(cache_path, verified)
    receipt["generated_binding_cache"] = {"path": str(cache_path), "sha256": digest(cache_path)}
    return _write_outputs(card, receipt, output_prefix)
