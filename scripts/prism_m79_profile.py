"""M79 saved-replay profiles with own-Main 12/24 score snapshots.

This module is isolated from the frozen M75 profiler. It invokes the same
strict Rust ReplayV1 projector, then applies the existing M75 profile checks
and adds post-action public-prestige snapshots at own Main 12 and 24. It never
starts a game or performs model inference.
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

from scripts import prism_replay_profile as legacy


ROOT = Path(__file__).resolve().parents[1]
PROFILE_FORMAT = "prism-m79-replay-profile-v1"
RECEIPT_FORMAT = "prism-m79-replay-profile-receipt-v1"
SNAPSHOT_MAINS = (12, 24)
DEFAULT_BATCH_SIZE = legacy.DEFAULT_BATCH_SIZE
MAX_BATCH_SIZE = legacy.MAX_BATCH_SIZE


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_prestige(decision: Mapping[str, Any], actor: int) -> int:
    observation = decision.get("observation")
    _require(isinstance(observation, dict), "verified observation is missing")
    viewer = decision.get("actor")
    _require(type(viewer) is int and viewer in (0, 1), "verified observation actor is invalid")
    _require(observation.get("viewer") == viewer, "verified observation viewer mismatch")
    public = observation.get("public")
    _require(isinstance(public, dict) and public.get("current_player") == viewer,
             "verified public actor mismatch")
    players = public.get("players")
    _require(isinstance(players, list) and len(players) == 2, "verified public players missing")
    own = players[actor]
    _require(isinstance(own, dict) and own.get("id") == actor,
             "verified public player identity mismatch")
    prestige = own.get("prestige")
    _require(type(prestige) is int and prestige >= 0, "verified public prestige must be a nonnegative integer")
    return prestige


def _verified_decisions_by_ply(replay: Mapping[str, Any], projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Join both actor projections to replay steps after the legacy checks."""
    decisions: list[dict[str, Any]] = []
    for actor in (0, 1):
        player = legacy._projected_player(projection, actor)
        actor_decisions = legacy._validated_decisions(replay, actor, player)
        for decision in actor_decisions:
            _require(type(decision.get("ply")) is int, "verified decision ply must be an integer")
            decisions.append({"actor": actor, **decision})
    decisions.sort(key=lambda row: row["ply"])
    steps = replay.get("steps")
    _require(isinstance(steps, list) and len(decisions) == len(steps),
             "verified projection does not cover every replay decision")
    _require([row["ply"] for row in decisions] == [step.get("ply") for step in steps],
             "verified projection ply order differs from replay")
    return decisions


def snapshot_verified_main_scores(
    replay: Mapping[str, Any], projection: Mapping[str, Any], actor: int, main_actions: int
) -> dict[str, Any]:
    """Return the score immediately after own Main 12/24, with explicit censoring.

    A snapshot uses the next strictly projected public observation after the
    counted Main action. If that action is followed by this actor's noble-choice
    phase, the choice is included before reading the score. At terminal, the
    replay's verified terminal score is used. A game ending before a horizon is
    NOT_MEASURED and remains in that horizon's coverage denominator.
    """
    _require(type(actor) is int and actor in (0, 1), "actor must be seat 0 or 1")
    _require(type(main_actions) is int and main_actions >= 0, "main_actions must be nonnegative")
    decisions = _verified_decisions_by_ply(replay, projection)
    final_result = replay.get("result")
    _require(isinstance(final_result, dict), "verified terminal result is missing")
    final_scores = final_result.get("scores")
    _require(isinstance(final_scores, list) and len(final_scores) == 2
             and all(type(score) is int and score >= 0 for score in final_scores),
             "verified terminal scores are malformed")

    snapshots: dict[str, Any] = {}
    own_main = 0
    for index, decision in enumerate(decisions):
        if decision["actor"] != actor:
            continue
        action = decision.get("chosen_action")
        observation = decision.get("observation")
        _require(isinstance(action, dict) and isinstance(observation, dict),
                 "verified decision is malformed")
        action_type = action.get("type")
        phase = observation.get("public", {}).get("phase")
        if action_type == "choose_noble":
            _require(phase == "choose_noble", "noble choice outside verified noble phase")
            continue
        _require(phase == "main", "non-noble actor action outside verified Main phase")
        own_main += 1
        if own_main not in SNAPSHOT_MAINS:
            continue

        next_index = index + 1
        if next_index < len(decisions):
            next_row = decisions[next_index]
            next_action = next_row.get("chosen_action")
            if (next_row["actor"] == actor and isinstance(next_action, dict)
                    and next_action.get("type") == "choose_noble"):
                next_index += 1
        if next_index < len(decisions):
            score = _public_prestige(decisions[next_index], actor)
            source = "next_verified_public_observation_after_main_action"
        else:
            score = final_scores[actor]
            source = "verified_terminal_result"
        snapshots[str(own_main)] = {
            "main_action": own_main,
            "vp": score,
            "status": "MEASURED",
            "source": source,
        }

    _require(own_main == main_actions, "snapshot Main count disagrees with validated building profile")
    for horizon in SNAPSHOT_MAINS:
        key = str(horizon)
        if key not in snapshots:
            _require(main_actions < horizon, "reached score horizon has no verified snapshot")
            snapshots[key] = {
                "main_action": horizon,
                "vp": None,
                "status": "NOT_MEASURED",
                "reason": "TERMINAL_BEFORE_WINDOW",
            }
    return snapshots


def profile_replay(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    """Profile one actor after the legacy strict-projection checks."""
    profile = legacy.profile_replay(replay, seat)
    projection = replay["_prism_profile_projection"]
    snapshots = snapshot_verified_main_scores(replay, projection, seat, profile["main_actions"])
    noble_count = sum(
        1 for decision in legacy._validated_decisions(
            replay, seat, legacy._projected_player(projection, seat)
        )
        if decision["chosen_action"].get("type") == "choose_noble"
    )
    result = {
        **profile,
        "format": PROFILE_FORMAT,
        "own_main_score_snapshots": snapshots,
        "own_main_12_vp": snapshots["12"]["vp"],
        "own_main_12_observed": int(snapshots["12"]["status"] == "MEASURED"),
        "own_main_12_survived": int(profile["main_actions"] >= 12),
        "own_main_12_survival_denominator": 1,
        "own_main_24_vp": snapshots["24"]["vp"],
        "own_main_24_observed": int(snapshots["24"]["status"] == "MEASURED"),
        "own_main_24_survived": int(profile["main_actions"] >= 24),
        "own_main_24_survival_denominator": 1,
        "nobles_selected": noble_count,
        "terminal_vp": replay["result"]["scores"][seat],
    }
    return result


def _temporal_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    _require(bool(rows), "cannot aggregate an empty M79 profile group")
    games = len(rows)
    summary: dict[str, Any] = {"games": games}
    for horizon in SNAPSHOT_MAINS:
        prefix = f"own_main_{horizon}"
        survived = sum(row[f"{prefix}_survived"] for row in rows)
        observed_rows = [row for row in rows if row[f"{prefix}_observed"] == 1]
        score_sum = sum(row[f"{prefix}_vp"] for row in observed_rows)
        _require(survived == len(observed_rows), f"Main {horizon} survival and snapshot counts disagree")
        summary.update({
            f"{prefix}_vp_sum": score_sum,
            f"{prefix}_vp_mean": score_sum / len(observed_rows) if observed_rows else None,
            f"{prefix}_snapshot_games": len(observed_rows),
            f"{prefix}_survival_coverage_games": survived,
            f"{prefix}_survival_coverage_denominator": games,
            f"{prefix}_survival_coverage": survived / games,
        })
    return summary


def aggregate_profiles(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate inherited metrics and M79 snapshots with visible denominators."""
    _require(isinstance(profiles, list) and bool(profiles), "profiles must be a nonempty list")
    seen: set[tuple[str, int]] = set()
    for index, profile in enumerate(profiles):
        _require(isinstance(profile, dict) and profile.get("format") == PROFILE_FORMAT,
                 f"profile {index} is not an M79 profile")
        game_key = profile.get("game_key")
        seat = profile.get("seat")
        _require(isinstance(game_key, str) and game_key, f"profile {index} lacks game_key")
        _require(type(seat) is int and seat in (0, 1), f"profile {index} has invalid seat")
        identity = (game_key, seat)
        _require(identity not in seen, f"duplicate profile actor: {game_key}/seat-{seat}")
        seen.add(identity)
        for horizon in SNAPSHOT_MAINS:
            prefix = f"own_main_{horizon}"
            _require(type(profile.get(f"{prefix}_survived")) is int
                     and profile[f"{prefix}_survived"] in (0, 1), f"profile {index} has invalid survival flag")
            _require(type(profile.get(f"{prefix}_observed")) is int
                     and profile[f"{prefix}_observed"] in (0, 1), f"profile {index} has invalid observed flag")
            score = profile.get(f"{prefix}_vp")
            if profile[f"{prefix}_observed"]:
                _require(type(score) is int and score >= 0 and profile[f"{prefix}_survived"] == 1,
                         f"profile {index} has invalid measured Main {horizon} score")
            else:
                _require(score is None and profile[f"{prefix}_survived"] == 0,
                         f"profile {index} must retain censored Main {horizon} as NOT_MEASURED")

    inherited = legacy.aggregate_profiles([
        {**profile, "format": legacy.PROFILE_FORMAT} for profile in profiles
    ])
    overall = _temporal_summary(profiles)
    inherited.update({key: value for key, value in overall.items() if key != "games"})

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in profiles:
        key = (row["model"], row.get("model_sha256"), row["opponent"],
               row.get("opponent_sha256"), row["seat"])
        grouped.setdefault(key, []).append(row)
    groups = []
    by_identity = {}
    for key in sorted(grouped, key=lambda value: tuple("" if item is None else str(item) for item in value)):
        model, model_sha, opponent, opponent_sha, seat = key
        group = next(item for item in inherited["groups"] if (
            item["model"], item.get("model_sha256"), item["opponent"],
            item.get("opponent_sha256"), item["seat"]
        ) == key)
        group.update(_temporal_summary(grouped[key]))
        groups.append(group)
        identity = json.dumps(list(key), ensure_ascii=False, separators=(",", ":"))
        by_identity[identity] = group
    inherited["groups"] = groups
    inherited["by_model_opponent_seat"] = by_identity
    inherited["format"] = "prism-m79-replay-profile-aggregate-v1"
    return inherited


def profile_saved_replays(
    rows: Sequence[Mapping[str, Any]],
    *,
    projector: str | os.PathLike[str] | Sequence[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Strictly project saved games and return both actors' enriched profiles.

    The row keys follow `prism_replay_profile.profile_saved_replays`: game_key,
    replay_path, replay_sha256, candidate_model, opponent_model,
    candidate_seat, seed, with optional SHA identities and opponent label.
    """
    _require(type(batch_size) is int and 1 <= batch_size <= MAX_BATCH_SIZE,
             f"batch_size must be in 1..{MAX_BATCH_SIZE}")
    sources = legacy._normalise_rows(rows)
    command_prefix, projector_identity = legacy._projector_command(projector)
    profiles_by_game: dict[str, list[dict[str, Any]]] = {}
    batches: list[dict[str, Any]] = []
    replay_receipts: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="prism-m79-profile-") as temporary:
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
            payload = json.loads(output_bytes)
            _require(payload.get("format") == legacy.PROJECTION_FORMAT,
                     f"Rust projector batch {batch_index} returned an unsupported format")
            projections = payload.get("games")
            _require(isinstance(projections, list) and len(projections) == len(batch),
                     f"Rust projector batch {batch_index} game count mismatch")
            batch_receipt = {
                "batch_index": batch_index,
                "projection_format": payload["format"],
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
            for offset, (row, projection) in enumerate(zip(batch, projections)):
                _require(isinstance(projection, dict), f"Rust projection row {first + offset} is malformed")
                _require(projection.get("replay_sha256") == row["replay_sha256"],
                         f"Rust projection replay SHA mismatch for {row['game_key']}")
                replay_bytes = row["replay_path"].read_bytes()
                _require(_sha256_bytes(replay_bytes) == row["replay_sha256"],
                         f"replay changed during profiling: {row['game_key']}")
                replay = json.loads(replay_bytes)
                _require(replay.get("seed") == row["seed"], f"seed mismatch for {row['game_key']}")
                replay["_prism_profile_projection"] = projection
                replay["_prism_profile_projection_format"] = payload["format"]
                replay["_prism_profile_replay_sha256"] = row["replay_sha256"]
                actor_profiles = []
                for actor in (0, 1):
                    profile = profile_replay(replay, actor)
                    candidate_actor = actor == row["candidate_seat"]
                    profile.update({
                        "game_key": row["game_key"],
                        "model": row["candidate_model"] if candidate_actor else row["opponent_model"],
                        "model_sha256": row["candidate_sha256"] if candidate_actor else row["opponent_sha256"],
                        "opponent": row["opponent_model"] if candidate_actor else row["candidate_model"],
                        "opponent_sha256": row["opponent_sha256"] if candidate_actor else row["candidate_sha256"],
                        "seat": actor,
                        "candidate_role": "candidate" if candidate_actor else "opponent",
                        "candidate_seat": row["candidate_seat"],
                        "seed": row["seed"],
                        "round_opponent_id": row.get("opponent"),
                    })
                    actor_profiles.append(profile)
                profiles_by_game[row["game_key"]] = actor_profiles
                replay_receipts.append({
                    "game_key": row["game_key"], "replay_sha256": row["replay_sha256"],
                    "seed": row["seed"], "candidate_seat": row["candidate_seat"],
                    "rust_verified_terminal": projection.get("terminal") is True,
                    "actors_profiled": [0, 1], "source_path": str(row["replay_path"]),
                    "projection_batch": batch_index,
                })
            batches.append(batch_receipt)

    sources_for_receipt = dict(projector_identity.get("sources", {}))
    for path in (Path(__file__), Path(legacy.__file__)):
        sources_for_receipt[path.relative_to(ROOT).as_posix()] = {
            "path": str(path), "sha256": _sha256_file(path),
        }
    verify_receipt = {
        "format": RECEIPT_FORMAT,
        "status": "PASS",
        "contract": "strict ReplayV1 projection; own-Main 12/24 post-action prestige snapshots",
        "rust_verification": "strict ReplayV1 re-execution via prism_building_projection",
        "games_requested": len(sources),
        "games_verified": len(replay_receipts),
        "actor_profiles": sum(len(items) for items in profiles_by_game.values()),
        "unique_replay_sha256": len({row["replay_sha256"] for row in sources}),
        "new_games": 0,
        "batch_size": batch_size,
        "projector": {**projector_identity, "sources": sources_for_receipt},
        "batches": batches,
        "replays": replay_receipts,
    }
    return {"profiles": profiles_by_game, "verify_receipt": verify_receipt}
