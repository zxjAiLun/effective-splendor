"""Offline, identity-bound purchase profile extraction from saved Replay v1 games.

The Rust projector performs the authoritative replay verification and exports
the two actors' own decision observations. This module reuses the M62 building
profile semantics and adds first 4-5 VP purchase timing. It never runs games.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Mapping, Sequence

from training.prism_portable.engine.ppo import building


ROOT = Path(__file__).resolve().parents[1]
REPLAY_FORMAT = "effective-splendor-replay"
PROFILE_FORMAT = "prism-replay-profile-v1"
PROJECTION_FORMAT = "prism-building-projection-v1"
RECEIPT_FORMAT = "prism-replay-profile-verify-receipt-v1"
CONTRACT = "own-Main-12-24-v1"
EARLY_MAIN_WINDOW = 12
REDEMPTION_MAIN_HORIZON = 24
BIG_CARD_MIN_VP = 4
BIG_CARD_MAX_VP = 5
DEFAULT_BATCH_SIZE = 64
MAX_BATCH_SIZE = 256
RUST_PROJECTOR_SOURCE = ROOT / "crates/splendor-cli/examples/prism_building_projection.rs"
CARGO_LOCK_SOURCE = ROOT / "Cargo.lock"
BUILDING_SOURCE = ROOT / "training/prism_portable/engine/ppo/building.py"
CARD_CATALOG_SOURCE = ROOT / "crates/splendor-catalog/src/cards.rs"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_identity() -> dict[str, dict[str, str]]:
    return {
        path.relative_to(ROOT).as_posix(): {"path": str(path), "sha256": _sha256_file(path)}
        for path in (RUST_PROJECTOR_SOURCE, CARGO_LOCK_SOURCE, BUILDING_SOURCE, CARD_CATALOG_SOURCE)
    }


def _lower_sha256(value: Any, label: str) -> str:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{label} must be a lowercase SHA256",
    )
    return value


def _projected_player(projection: Mapping[str, Any], actor: int) -> Mapping[str, Any]:
    players = projection.get("players")
    _require(isinstance(players, list) and len(players) == 2, "Rust projection must contain both actors")
    matches = [player for player in players if isinstance(player, dict) and player.get("actor") == actor]
    _require(len(matches) == 1, f"Rust projection must contain actor {actor} exactly once")
    return matches[0]


def _validated_decisions(replay: Mapping[str, Any], actor: int, player: Mapping[str, Any]) -> list[dict[str, Any]]:
    steps = replay.get("steps")
    decisions = player.get("decisions")
    _require(isinstance(steps, list), "Replay v1 steps must be an array")
    _require(isinstance(decisions, list) and decisions, "Rust projection actor decisions must be nonempty")
    own_steps = [step for step in steps if isinstance(step, dict) and step.get("actor") == actor]
    _require(len(own_steps) == len(decisions), "Rust projection omitted or added actor decisions")
    for step, decision in zip(own_steps, decisions):
        _require(
            isinstance(decision, dict)
            and decision.get("ply") == step.get("ply")
            and decision.get("chosen_action") == step.get("action"),
            "Rust projection ply/action does not match the supplied replay",
        )
    return decisions


def _first_big_purchase(decisions: list[dict[str, Any]]) -> tuple[int | None, list[dict[str, Any]], int]:
    own_main = 0
    purchases: list[dict[str, Any]] = []
    for decision in decisions:
        observation = decision.get("observation")
        action = decision.get("chosen_action")
        _require(isinstance(observation, dict) and isinstance(action, dict), "malformed projected decision")
        public = observation.get("public")
        _require(isinstance(public, dict), "projected public observation missing")
        phase = public.get("phase")
        action_type = action.get("type")
        if action_type == "choose_noble":
            _require(phase == "choose_noble", "noble choice outside ChooseNoble phase")
            continue
        _require(phase == "main", "non-noble actor decision outside Main phase")
        own_main += 1
        if action_type not in ("buy_market", "buy_reserved"):
            continue
        # This shared M62 resolver reads the actual pre-purchase market/reserve
        # card and immutable catalog definition, including printed VP and cost.
        _, (_, _, printed_vp, _) = building._purchase_target(observation, action)
        purchases.append({"own_main": own_main, "printed_vp": printed_vp, "action_type": action_type})
    first = next(
        (event["own_main"] for event in purchases if BIG_CARD_MIN_VP <= event["printed_vp"] <= BIG_CARD_MAX_VP),
        None,
    )
    return first, purchases, own_main


def profile_replay(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    """Profile one actor from a Replay v1 dict carrying its Rust verified projection.

    The batch helper attaches `_prism_profile_projection`, its validated outer
    envelope format, and `_prism_profile_replay_sha256` to a freshly parsed replay dict. A raw replay
    alone lacks the pre-action market and bonus state needed to identify bought
    card IDs and discount use, so it is deliberately rejected.
    """
    _require(isinstance(replay, dict), "replay must be a JSON object")
    _require(type(seat) is int and seat in (0, 1), "seat must be physical actor 0 or 1")
    _require(replay.get("format") == REPLAY_FORMAT and replay.get("version") == 1, "unsupported replay format")
    _require(replay.get("player_count") == 2, "Prism replay profile requires a two-player game")
    projection = replay.get("_prism_profile_projection")
    projection_format = replay.get("_prism_profile_projection_format")
    replay_sha256 = _lower_sha256(replay.get("_prism_profile_replay_sha256"), "bound replay SHA256")
    _require(isinstance(projection, dict), "missing Rust verified projection; call profile_saved_replays first")
    _require(projection_format == PROJECTION_FORMAT, "unsupported or missing Rust projection envelope format")
    _require(projection.get("terminal") is True, "projection is not a verified terminal replay")
    _require(projection.get("replay_sha256") == replay_sha256, "Rust projection replay SHA mismatch")
    _require(projection.get("seed") == replay.get("seed"), "Rust projection seed mismatch")
    _require(projection.get("catalog_fingerprint") == replay.get("ruleset_fingerprint") == building.BASE_CATALOG_FINGERPRINT,
             "Rust projection catalog/ruleset fingerprint mismatch")
    _require(projection.get("result") == replay.get("result"), "Rust projection terminal result mismatch")

    player = _projected_player(projection, seat)
    decisions = _validated_decisions(replay, seat, player)
    building_profile = building.profile_from_own_decisions(
        decisions, seat, building.default_building_config(), terminal=True
    )
    first_big_main, purchase_events, main_actions = _first_big_purchase(decisions)
    _require(main_actions == building_profile["main_actions"], "Main-action count disagrees with M62 building profile")

    observed_early_mains = min(main_actions, EARLY_MAIN_WINDOW)
    observed_redemption_mains = min(main_actions, REDEMPTION_MAIN_HORIZON)
    early_low_cards = building_profile["early_lowvp_buys"]
    # These audit fields make the inherited M62 definition visible: only actual
    # later purchases count; the newly bought card cannot redeem its own bonus.
    return {
        "format": PROFILE_FORMAT,
        "contract": CONTRACT,
        "actor": seat,
        "replay_sha256": replay_sha256,
        "seed": replay["seed"],
        "games": 1,
        "main_actions": main_actions,
        "first_big_main": first_big_main,
        "first_big_main_sum": first_big_main or 0,
        "first_big_games": int(first_big_main is not None),
        "first_big_coverage_games": int(first_big_main is not None),
        "first_big_coverage_denominator": 1,
        "first_big_window_mains": main_actions,
        "first_big_purchase_events": purchase_events,
        "early_low_cards": early_low_cards,
        "early_low_main_observed": observed_early_mains,
        "early_low_window_complete_games": int(main_actions >= EARLY_MAIN_WINDOW),
        "early_low_window_games": 1,
        "early_low_window_coverage_games": int(main_actions >= EARLY_MAIN_WINDOW),
        "early_low_window_main_limit": EARLY_MAIN_WINDOW,
        "early_low_cards_per_observed_main_numerator": early_low_cards,
        "early_low_cards_per_observed_main_denominator": observed_early_mains,
        "early_discount_redemptions": building_profile["building_use_units"],
        "early_discount_redemptions_before_game_cap": building_profile["building_use_units_before_global_cap"],
        "early_discount_observed_applications": building_profile["building_observed_use_units"],
        "early_discount_investments": early_low_cards,
        "early_discount_redeemed_investments": building_profile["redeemed_investments"],
        "early_discount_unredeemed_investments": building_profile["unredeemed_investments"],
        "early_discount_censored_investments": building_profile["censored_investments"],
        "early_discount_unredeemed_censored_investments": building_profile["unredeemed_censored_investments"],
        "early_discount_horizon_observed_mains": observed_redemption_mains,
        "early_discount_horizon_complete_games": int(main_actions >= REDEMPTION_MAIN_HORIZON),
        "early_discount_horizon_games": 1,
        "early_discount_horizon_censored_games": int(main_actions < REDEMPTION_MAIN_HORIZON),
        "early_discount_horizon_main_limit": REDEMPTION_MAIN_HORIZON,
        "early_discount_redemption_rate_numerator": building_profile["redeemed_investments"],
        "early_discount_redemption_rate_denominator": early_low_cards,
        "early_discount_investments_detail": building_profile["investments"],
        "discount_semantics": (
            "Existing prism-building-profile-v1: a later real purchase at own Main <=24 "
            "redeems an earlier <=1 printed-VP purchase when its pre-purchase printed cost "
            "in that bonus colour is >= the investment bonus ordinal; max 3 credits per "
            "investment then max 24 credits per game. This is observed discount application, "
            "not a causal or counterfactual token-savings claim."
        ),
        "shorter_than_12_main": main_actions < EARLY_MAIN_WINDOW,
        "shorter_than_24_main": main_actions < REDEMPTION_MAIN_HORIZON,
    }


def _normalise_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(isinstance(rows, (list, tuple)) and bool(rows), "rows must be a nonempty list")
    normalized: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    seen_keys: set[str] = set()
    for index, row in enumerate(rows):
        _require(isinstance(row, Mapping), f"row {index} must be an object")
        key = row.get("game_key")
        _require(isinstance(key, str) and key, f"row {index} missing game_key")
        _require(key not in seen_keys, f"duplicate game_key: {key}")
        seen_keys.add(key)
        path_value = row.get("replay_path")
        _require(isinstance(path_value, (str, os.PathLike)), f"row {index} missing replay_path")
        path = Path(path_value).expanduser().resolve(strict=True)
        _require(path.is_file(), f"row {index} replay_path is not a file")
        _require(path not in seen_paths, f"duplicate replay path: {path}")
        seen_paths.add(path)
        replay_sha256 = _lower_sha256(row.get("replay_sha256"), f"row {index} replay_sha256")
        actual_sha256 = _sha256_file(path)
        _require(actual_sha256 == replay_sha256, f"row {index} replay file SHA mismatch")
        candidate_seat = row.get("candidate_seat")
        _require(type(candidate_seat) is int and candidate_seat in (0, 1), f"row {index} invalid candidate_seat")
        seed = row.get("seed")
        _require(type(seed) is int and seed >= 0, f"row {index} invalid seed")
        candidate_model = row.get("candidate_model")
        opponent_model = row.get("opponent_model")
        _require(isinstance(candidate_model, str) and candidate_model, f"row {index} missing candidate_model")
        _require(isinstance(opponent_model, str) and opponent_model, f"row {index} missing opponent_model")
        candidate_sha = row.get("candidate_sha256")
        opponent_sha = row.get("opponent_sha256")
        if candidate_sha is not None:
            candidate_sha = _lower_sha256(candidate_sha, f"row {index} candidate_sha256")
        if opponent_sha is not None:
            opponent_sha = _lower_sha256(opponent_sha, f"row {index} opponent_sha256")
        normalized.append({
            **dict(row), "game_key": key, "replay_path": path, "replay_sha256": replay_sha256,
            "candidate_seat": candidate_seat, "seed": seed,
            "candidate_model": candidate_model, "opponent_model": opponent_model,
            "candidate_sha256": candidate_sha, "opponent_sha256": opponent_sha,
        })
    return normalized


def _projector_command(projector: str | os.PathLike[str] | Sequence[str] | None) -> tuple[list[str], dict[str, Any]]:
    source_identity = _source_identity()
    if projector is not None:
        if isinstance(projector, (str, os.PathLike)):
            command = [str(Path(projector).resolve(strict=True))]
        else:
            command = [str(part) for part in projector]
            _require(bool(command), "projector command cannot be empty")
        executable = Path(command[0])
        _require(executable.is_file(), f"Rust projector executable not found: {command[0]}")
        return command, {
            "build": "NOT_RUN_EXTERNAL_PROJECTOR", "path": str(executable),
            "sha256": _sha256_file(executable), "sources": source_identity,
        }

    metadata = subprocess.run(
        ["cargo", "metadata", "--offline", "--no-deps", "--format-version", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    _require(metadata.returncode == 0, f"cargo metadata failed: {metadata.stderr[-3000:]}")
    target_directory = Path(json.loads(metadata.stdout)["target_directory"])
    executable = target_directory / "release" / "examples" / ("prism_building_projection.exe" if os.name == "nt" else "prism_building_projection")
    command = [
        "cargo", "build", "--offline", "--locked", "--release", "--package", "splendor-cli",
        "--example", "prism_building_projection",
    ]
    started = time.monotonic()
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=900, check=False)
    build_receipt = {
        "command": command, "returncode": built.returncode,
        "elapsed_seconds": time.monotonic() - started,
        "stdout_tail": built.stdout[-3000:], "stderr_tail": built.stderr[-5000:],
    }
    _require(built.returncode == 0 and executable.is_file(), "could not build Rust replay projector")
    return [str(executable)], {
        "build": build_receipt, "path": str(executable), "sha256": _sha256_file(executable),
        "sources": source_identity,
    }


def profile_saved_replays(
    rows: Sequence[Mapping[str, Any]],
    *,
    projector: str | os.PathLike[str] | Sequence[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Verify saved replays in bounded Rust batches and profile both actors.

    Each input row contains `game_key`, `replay_path`, `replay_sha256`,
    `candidate_model`, `opponent_model`, `candidate_seat`, and `seed`; exact
    candidate/opponent SHA values are recommended. One Rust process handles a
    batch (64 games by default), never one process per replay.
    """
    _require(type(batch_size) is int and 1 <= batch_size <= MAX_BATCH_SIZE,
             f"batch_size must be in 1..{MAX_BATCH_SIZE}")
    sources = _normalise_rows(rows)
    command_prefix, projector_identity = _projector_command(projector)
    profiles_by_game: dict[str, list[dict[str, Any]]] = {}
    batches: list[dict[str, Any]] = []
    replay_receipts: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="prism-replay-profile-") as temporary:
        stage = Path(temporary)
        for batch_index, first in enumerate(range(0, len(sources), batch_size)):
            batch = sources[first:first + batch_size]
            manifest_path = stage / f"batch-{batch_index:04d}.manifest.json"
            output_path = stage / f"batch-{batch_index:04d}.projection.json"
            manifest = {"rows": [
                {"replay_path": str(row["replay_path"]), "replay_sha256": row["replay_sha256"]}
                for row in batch
            ]}
            manifest_bytes = (json.dumps(manifest, separators=(",", ":")) + "\n").encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            argv = [*command_prefix, str(manifest_path), str(output_path)]
            started = time.monotonic()
            process = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=1800, check=False)
            elapsed = time.monotonic() - started
            _require(process.returncode == 0,
                     f"Rust replay projection batch {batch_index} failed ({process.returncode}): {process.stderr[-5000:]}")
            output_bytes = output_path.read_bytes()
            projection_payload = json.loads(output_bytes)
            _require(projection_payload.get("format") == PROJECTION_FORMAT,
                     f"Rust projector batch {batch_index} returned an unsupported format")
            projected_games = projection_payload.get("games")
            _require(isinstance(projected_games, list) and len(projected_games) == len(batch),
                     f"Rust projector batch {batch_index} game count mismatch")
            batch_receipt = {
                "batch_index": batch_index,
                "projection_format": projection_payload["format"],
                "first_row": first,
                "games": len(batch),
                "actors_profiled": len(batch) * 2,
                "manifest_sha256": _sha256_bytes(manifest_bytes),
                "projection_sha256": _sha256_bytes(output_bytes),
                "projector_sha256": projector_identity["sha256"],
                "elapsed_seconds": elapsed,
                "command": argv,
                "returncode": process.returncode,
                "stdout_tail": process.stdout[-1000:],
            }
            for offset, (row, projection) in enumerate(zip(batch, projected_games)):
                _require(isinstance(projection, dict), f"Rust projector returned malformed game at row {first + offset}")
                _require(projection.get("replay_sha256") == row["replay_sha256"],
                         f"Rust projection SHA mismatch for {row['game_key']}")
                replay_bytes = row["replay_path"].read_bytes()
                replay = json.loads(replay_bytes)
                _require(_sha256_bytes(replay_bytes) == row["replay_sha256"],
                         f"replay changed during profiling: {row['game_key']}")
                _require(replay.get("seed") == row["seed"], f"seed mismatch for {row['game_key']}")
                replay["_prism_profile_projection"] = projection
                # The Rust example defines format on the batch envelope; its
                # per-game objects intentionally contain no format field.
                replay["_prism_profile_projection_format"] = projection_payload["format"]
                replay["_prism_profile_replay_sha256"] = row["replay_sha256"]
                candidate_seat = row["candidate_seat"]
                actor_profiles = []
                for actor in (0, 1):
                    profile = profile_replay(replay, actor)
                    candidate_actor = actor == candidate_seat
                    profile.update({
                        "game_key": row["game_key"],
                        "model": row["candidate_model"] if candidate_actor else row["opponent_model"],
                        "model_sha256": row["candidate_sha256"] if candidate_actor else row["opponent_sha256"],
                        "opponent": row["opponent_model"] if candidate_actor else row["candidate_model"],
                        "opponent_sha256": row["opponent_sha256"] if candidate_actor else row["candidate_sha256"],
                        "seat": actor,
                        "candidate_role": "candidate" if candidate_actor else "opponent",
                        "candidate_seat": candidate_seat,
                        "seed": row["seed"],
                        "round_opponent_id": row.get("opponent"),
                    })
                    actor_profiles.append(profile)
                profiles_by_game[row["game_key"]] = actor_profiles
                replay_receipts.append({
                    "game_key": row["game_key"], "replay_sha256": row["replay_sha256"],
                    "seed": row["seed"], "candidate_seat": candidate_seat,
                    "rust_verified_terminal": projection.get("terminal") is True,
                    "actors_profiled": [0, 1], "source_path": str(row["replay_path"]),
                    "projection_batch": batch_index,
                })
            batches.append(batch_receipt)

    verify_receipt = {
        "format": RECEIPT_FORMAT,
        "status": "PASS",
        "contract": CONTRACT,
        "rust_verification": "strict ReplayV1 re-execution via prism_building_projection",
        "games_requested": len(sources),
        "games_verified": len(replay_receipts),
        "actor_profiles": sum(len(profiles) for profiles in profiles_by_game.values()),
        "unique_replay_sha256": len({row["replay_sha256"] for row in sources}),
        "new_games": 0,
        "batch_size": batch_size,
        "projector": projector_identity,
        "batches": batches,
        "replays": replay_receipts,
    }
    return {"profiles": profiles_by_game, "verify_receipt": verify_receipt}


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    games = len(rows)
    _require(games > 0, "cannot aggregate an empty profile group")
    first_big_games = sum(row["first_big_games"] for row in rows)
    first_big_sum = sum(row["first_big_main_sum"] for row in rows)
    first_big_denominator = sum(row["first_big_games"] for row in rows)
    early_low_total = sum(row["early_low_cards"] for row in rows)
    observed_early_mains = sum(row["early_low_main_observed"] for row in rows)
    early_investments = sum(row["early_discount_investments"] for row in rows)
    redeemed_investments = sum(row["early_discount_redeemed_investments"] for row in rows)
    censored_investments = sum(row["early_discount_censored_investments"] for row in rows)
    horizon_complete = sum(row["early_discount_horizon_complete_games"] for row in rows)
    horizon_observed = sum(row["early_discount_horizon_observed_mains"] for row in rows)
    applied = sum(row["early_discount_redemptions"] for row in rows)
    before_game_cap = sum(row["early_discount_redemptions_before_game_cap"] for row in rows)
    observed_applications = sum(row["early_discount_observed_applications"] for row in rows)
    early_window_complete = sum(row["early_low_window_complete_games"] for row in rows)
    return {
        "games": games,
        "first_big_main": first_big_sum / first_big_denominator if first_big_denominator else None,
        "first_big_main_sum": first_big_sum,
        "first_big_games": first_big_games,
        "first_big_coverage": first_big_games / games,
        "first_big_coverage_games": first_big_games,
        "first_big_coverage_denominator": games,
        "early_low_cards": early_low_total / games,
        "early_low_cards_total": early_low_total,
        "early_low_main_observed": observed_early_mains,
        "early_low_cards_per_observed_main": early_low_total / observed_early_mains if observed_early_mains else None,
        "early_low_window_complete_games": early_window_complete,
        "early_low_window_coverage": early_window_complete / games,
        "early_low_window_games": games,
        "early_low_window_main_limit": EARLY_MAIN_WINDOW,
        "early_discount_redemptions": applied / games,
        "early_discount_redemptions_total": applied,
        "early_discount_redemptions_before_game_cap_total": before_game_cap,
        "early_discount_observed_applications_total": observed_applications,
        "early_discount_investments": early_investments,
        "early_discount_redeemed_investments": redeemed_investments,
        "early_discount_unredeemed_investments": early_investments - redeemed_investments,
        "early_discount_redemption_rate": redeemed_investments / early_investments if early_investments else None,
        "early_discount_censored_investments": censored_investments,
        "early_discount_horizon_observed_mains": horizon_observed,
        "early_discount_horizon_complete_games": horizon_complete,
        "early_discount_horizon_coverage": horizon_complete / games,
        "early_discount_horizon_games": games,
        "early_discount_horizon_censored_games": games - horizon_complete,
        "early_discount_horizon_main_limit": REDEMPTION_MAIN_HORIZON,
        "early_discount_redemption_rate_denominator": early_investments,
        "discount_semantics": rows[0]["discount_semantics"],
    }


def aggregate_profiles(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts first, preserving model/opponent/physical-seat groups."""
    _require(isinstance(profiles, list) and bool(profiles), "profiles must be a nonempty list")
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for index, profile in enumerate(profiles):
        _require(isinstance(profile, dict) and profile.get("format") == PROFILE_FORMAT,
                 f"profile {index} has unsupported format")
        _require(isinstance(profile.get("model"), str) and profile["model"], f"profile {index} missing model identity")
        _require(isinstance(profile.get("opponent"), str) and profile["opponent"], f"profile {index} missing opponent identity")
        seat = profile.get("seat")
        _require(type(seat) is int and seat in (0, 1), f"profile {index} has invalid physical seat")
        key = (profile["model"], profile.get("model_sha256"), profile["opponent"],
               profile.get("opponent_sha256"), seat)
        grouped.setdefault(key, []).append(profile)

    groups = []
    by_identity: dict[str, dict[str, Any]] = {}
    for key in sorted(grouped, key=lambda value: tuple("" if item is None else str(item) for item in value)):
        model, model_sha, opponent, opponent_sha, seat = key
        summary = _summary(grouped[key])
        group = {"model": model, "model_sha256": model_sha, "opponent": opponent,
                 "opponent_sha256": opponent_sha, "seat": seat, **summary}
        groups.append(group)
        identity_key = json.dumps([model, model_sha, opponent, opponent_sha, seat], ensure_ascii=False, separators=(",", ":"))
        by_identity[identity_key] = group

    total = _summary(profiles)
    return {
        "format": "prism-replay-profile-aggregate-v1",
        "contract": CONTRACT,
        **total,
        "by_model_opponent_seat": by_identity,
        "groups": groups,
        "actor_profile_rows": len(profiles),
        "unique_replays": len({profile["replay_sha256"] for profile in profiles}),
        "aggregation": "integer counts and observed denominators are summed before means and rates are calculated",
    }

