"""B-round real-inference runner: fixed anchors, frozen schedule, no league writes.

This is the Stage B harness authorized by the owner. It is deliberately separate
from `match.py` (which is a single-opponent smoke) and from every league command:

* no Studio League database, Elo, or registry is opened or written;
* the schedule (opponent, seed, seat) is frozen in a manifest before game 1 and
  is never re-derived after seeing results;
* every game gets its own output directory with config, manifest, report,
  replay, journal and a per-game summary;
* the API credential is read from the ignored local file by the agent at request
  time and is never placed in argv, config, log, or artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

from match import run_arena
from runtime import AGENT_VERSION, atomic_json

import agent as agent_module
import transport

ROOT = Path(__file__).resolve().parents[1]

# The anchors named in the owner's brief: one per strength tier of the existing
# pool, so the report can separate "beats the weak reference" from "loses to
# search" instead of collapsing everything into one overall win rate.
#
# `--seed` is required by agent-heuristic and agent-random and is pinned here so
# the opponent is a fixed, reproducible opponent rather than a per-run draw.
ANCHORS = {
    "s3-rollout": ["agent-s3-rollout"],
    "heuristic": ["agent-heuristic", "--seed", "20260812"],
    "determinization-n2000": ["agent-determinization", "--sample-seed", "20260810",
                              "--sample-count", "4", "--max-depth-turns", "1", "--max-nodes", "2000"],
    "random": ["agent-random", "--seed", "20260811"],
}


def schedule(anchors: list[str], games_per_anchor: int) -> list[dict]:
    """A fixed, seat-balanced schedule, frozen before the first game runs.

    Seats alternate per game and the starting seat rotates per anchor, so the
    20-game total is exactly 10 first / 10 second. Seed is derived from the
    anchor index and game index only - never from an observed result.
    """
    games = []
    for anchor_index, anchor in enumerate(anchors):
        for game_index in range(games_per_anchor):
            jev_seat = (game_index + anchor_index) % 2
            games.append({
                "anchor": anchor,
                "game_index": game_index,
                "jev_seat": jev_seat,
                "seed": 20261000 + anchor_index * 100 + game_index,
            })
    return games


def require_b2_policy() -> None:
    # This archived harness labels its evidence B/B2. Never silently relabel a
    # facts-only run as the frozen heuristic-conditioned experiment.
    if AGENT_VERSION != "0.3.0":
        raise ValueError("B2 batch runner requires archived v0.3.0; current policy is not B2. "
                         "Use match.py only with a newly approved single-game budget.")


def one_game(game: dict, out: Path, binary: Path, timeout: int, max_calls: int) -> dict:
    require_b2_policy()
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["JEV_METRICS_FILE"] = str(out / "metrics.json")
    env["JEV_SPLENDOR_BINARY"] = str(binary)
    env["JEV_MAX_API_CALLS"] = str(max_calls)
    run_trace_id = out.name
    python = {"program": sys.executable, "args": ["-u", str(ROOT / "jev/agent.py")]}
    opponent = {"program": str(binary), "args": ANCHORS[game["anchor"]]}
    agents = [python, opponent] if game["jev_seat"] == 0 else [opponent, python]
    config = {
        "game_id": f"jevB-{game['anchor']}-{game['game_index']}",
        "run_trace_id": run_trace_id,
        "seed": game["seed"],
        "handshake_timeout_ms": 15000,
        "move_timeout_ms": 45000,
        "shutdown_grace_ms": 2000,
        "agents": agents,
    }
    atomic_json(out / "config.json", config)
    sources = [ROOT / "jev" / name for name in
               ("agent.py", "runtime.py", "transport.py", "match.py", "run_batch.py", "catalog.json")]
    sources += [ROOT / "crates/splendor-cli/src/agent_terms_command.rs",
                ROOT / "crates/splendor-agent/src/heuristic.rs"]
    atomic_json(out / "manifest.json", {
        "schema_version": 1,
        "round": "B2",
        "agent_version": AGENT_VERSION,
        # Read from the agent so a manifest can never claim a model the code
        # does not request.
        "requested_model": agent_module.MODEL,
        "expected_model": agent_module.EXPECTED_MODEL,
        "max_request_bytes": transport.MAX_REQUEST_BYTES,
        "anchor": game["anchor"],
        "anchor_command": ANCHORS[game["anchor"]],
        "jev_seat": game["jev_seat"],
        "seed": game["seed"],
        "max_api_calls": max_calls,
        "max_attempts_per_stage": 2,
        "arena_config": config,
        "source_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sources},
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256((out / "config.json").read_bytes()).hexdigest(),
        "league_writes": False,
    })
    started = time.monotonic()
    cmd = [str(binary), "run-match", "--config", str(out / "config.json"),
           "--report-out", str(out / "report.json"), "--replay-out", str(out / "replay.json")]
    status, exit_code, stdout = "exited", None, ""
    try:
        result = run_arena(cmd, cwd=ROOT, env=env, timeout=timeout)
        exit_code, stdout = result.returncode, result.stdout or ""
        if result.stderr:
            (out / "arena-stderr.txt").write_text(result.stderr, encoding="utf-8")
    except Exception as error:  # noqa: BLE001 - a crashed game must not abort the batch silently
        status = "runner_error"
        (out / "runner-error.txt").write_text(f"{type(error).__name__}", encoding="utf-8")
    elapsed = time.monotonic() - started
    atomic_json(out / "runner-status.json", {"status": status, "exit_code": exit_code,
                                             "elapsed_seconds": round(elapsed, 3)})

    # Per-game facts are read back from the real artifacts; nothing is inferred.
    summary = {"anchor": game["anchor"], "game_index": game["game_index"], "seed": game["seed"],
               "jev_seat": game["jev_seat"], "status": status, "exit_code": exit_code,
               "elapsed_seconds": round(elapsed, 3), "out_dir": out.name}
    metrics_path = out / "metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        summary["api_calls"] = metrics.get("api_calls")
        summary["input_tokens"] = metrics.get("input_tokens")
        summary["output_tokens"] = metrics.get("output_tokens")
        summary["unknown_usage_attempts"] = metrics.get("unknown_usage_attempts")
        summary["model_versions"] = metrics.get("model_versions")
        summary["requested_model"] = metrics.get("requested_model")
        summary["status_agent"] = metrics.get("status")
        summary["error_code"] = metrics.get("error_code")
        summary["decisions"] = metrics.get("decisions")
    report_path = out / "report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        outcome = report.get("outcome", {})
        summary["outcome_status"] = outcome.get("status")
        if outcome.get("status") == "completed":
            result_block = outcome.get("result", {})
            summary["scores"] = result_block.get("scores")
            summary["winners"] = result_block.get("winners")
            summary["reason"] = result_block.get("reason")
            wins = result_block.get("winners") or []
            summary["jev_won"] = game["jev_seat"] in wins
            summary["match_plies"] = outcome.get("plies")
    replay_path = out / "replay.json"
    if replay_path.is_file():
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        summary["replay_steps"] = len(replay.get("steps", []))
    atomic_json(out / "game-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--games-per-anchor", type=int, default=5)
    parser.add_argument("--anchors", default=",".join(ANCHORS))
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--max-calls-per-game", type=int, default=100)
    parser.add_argument("--only", type=int, help="Run just this 0-based schedule index (for staged smoke)")
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    try:
        require_b2_policy()
    except ValueError as error:
        parser.error(str(error))
    suffix = ".exe" if os.name == "nt" else ""
    binary = args.binary or next((p for p in (ROOT / f"target/release/splendor{suffix}",
                                              ROOT / f"target/debug/splendor{suffix}") if p.exists()), None)
    if binary is None or not binary.is_file():
        parser.error("build the binary first")
    binary = binary.resolve()
    anchors = [a.strip() for a in args.anchors.split(",") if a.strip()]
    for anchor in anchors:
        if anchor not in ANCHORS:
            parser.error(f"unknown anchor {anchor!r}")
    games = schedule(anchors, args.games_per_anchor)
    args.batch_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.batch_dir / "schedule.json"
    if args.only is None:
        if manifest_path.exists():
            # The frozen schedule is written once and then read back, so a rerun
            # cannot quietly choose different opponents or seeds.
            frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
            if frozen["games"] != games:
                parser.error("frozen schedule does not match; refusing to rerun with new matchups")
        else:
            atomic_json(manifest_path, {
                "schema_version": 1, "round": "B", "frozen_at_epoch": int(time.time()),
                "agent_version": AGENT_VERSION, "requested_model": agent_module.MODEL,
                "expected_model": agent_module.EXPECTED_MODEL,
                "max_request_bytes": transport.MAX_REQUEST_BYTES,
                "games_per_anchor": args.games_per_anchor,
                "max_calls_per_game": args.max_calls_per_game,
                "league_writes": False, "game_count": len(games),
                "first_seats": sum(1 for g in games if g["jev_seat"] == 0),
                "second_seats": sum(1 for g in games if g["jev_seat"] == 1),
                "games": games,
            })

    selected = games if args.only is None else [games[args.only]]
    results = []
    for game in selected:
        index = games.index(game)
        label = f"{index:02d}-{game['anchor']}-s{game['jev_seat']}-{game['seed']}"
        out = args.batch_dir / label
        if out.exists():
            print(f"[{label}] already exists; skipping", file=sys.stderr)
            continue
        print(f"[{label}] start", file=sys.stderr)
        try:
            summary = one_game(game, out, binary, args.timeout, args.max_calls_per_game)
        except Exception as error:  # noqa: BLE001
            summary = {"anchor": game["anchor"], "game_index": game["game_index"],
                       "seed": game["seed"], "jev_seat": game["jev_seat"],
                       "status": "batch_error", "error": type(error).__name__, "out_dir": out.name}
            atomic_json(out / "game-summary.json", summary)
        results.append(summary)
        print(f"[{label}] calls={summary.get('api_calls')} "
              f"in={summary.get('input_tokens')} out={summary.get('output_tokens')} "
              f"won={summary.get('jev_won')} outcome={summary.get('outcome_status')}"
              f"/{summary.get('status_agent')} {summary.get('elapsed_seconds')}s", file=sys.stderr)
    if args.only is None:
        atomic_json(args.batch_dir / "batch-summary.json", {"games": results})
        print(json.dumps({"games": len(results), "batch_dir": str(args.batch_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
