#!/usr/bin/env python3
"""Run 2,000 games of M50 (Pure Greedy, zero search) vs v0.2.9 Champion Heuristic.

Generates 1,000 paired-seed blocks (2,000 games with strict seat rotation):
  - Candidate: M50 Neural Policy (Pure Greedy, 256-dim model, zero search)
  - Opponent:  Frozen v0.2.9 Champion Heuristic (splendor-candidate.exe in s4-heuristic-v029-pilot)
Output directory: local-artifacts/m50-vs-v029-coev-2k/
Seeds: 9_309_000 .. 9_309_999 (1,000 paired blocks x 2 rotations = 2,000 matches)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START_SEED = 9_309_000
DEFAULT_PAIRED_COUNT = 1_000  # 1,000 x 2 = 2,000 matches
DEFAULT_OUT_DIR = ROOT / "local-artifacts" / "m50-vs-v029-coev-2k"
CANDIDATE_EXE = ROOT / "target" / "release" / "splendor.exe"
CANDIDATE_WEIGHTS = ROOT / "local-artifacts" / "m50-v029-dim256-fixed-run" / "m50_steps_weights.json"
OPPONENT_EXE = ROOT / "local-artifacts" / "s4-heuristic-v029-pilot" / "splendor-candidate.exe"
OPPONENT_ARGS = ["agent-heuristic-v02", "--seed", "20260926"]


def run_single_match(args: tuple[int, int, Path, str, str, str]) -> dict:
    seed, candidate_seat, base_out_dir, cand_bin_str, weights_str, opp_bin_str = args
    shard_id = (seed - DEFAULT_START_SEED) // 250
    shard_dir = base_out_dir / "games" / f"shard-{shard_id:02d}" / f"seed-{seed}" / f"r{candidate_seat}"
    shard_dir.mkdir(parents=True, exist_ok=True)

    cfg_file = shard_dir / "match-config.json"
    rep_file = shard_dir / "arena-report.json"
    rpl_file = shard_dir / "match-replay.json"

    cand_agent = {
        "program": cand_bin_str,
        "args": ["agent-m50-policy", "--weights", weights_str, "--mode", "greedy"],
    }
    opp_agent = {
        "program": opp_bin_str,
        "args": OPPONENT_ARGS,
    }

    agents = [cand_agent, opp_agent] if candidate_seat == 0 else [opp_agent, cand_agent]
    match_config = {
        "game_id": f"m50-coev-v029-{seed}-r{candidate_seat}",
        "seed": seed,
        "agents": agents,
        "handshake_timeout_ms": 10000,
        "move_timeout_ms": 60000,
        "shutdown_grace_ms": 2000,
    }

    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(match_config, f, indent=2)

    if rep_file.exists(): rep_file.unlink()
    if rpl_file.exists(): rpl_file.unlink()

    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            cand_bin_str,
            "run-match",
            "--config", str(cfg_file),
            "--report-out", str(rep_file),
            "--replay-out", str(rpl_file),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    wall = time.perf_counter() - t0

    if proc.returncode != 0:
        raise RuntimeError(f"Seed {seed}-r{candidate_seat} failed: {proc.stderr[:400]}")

    with open(rep_file, "r", encoding="utf-8") as f:
        rep = json.load(f)

    res = rep["outcome"]["result"]
    winners = res["winners"]
    scores = res["scores"]
    plies = rep["outcome"]["completed_plies"]

    cand_score = scores[candidate_seat]
    opp_score = scores[1 - candidate_seat]

    won = 1.0 if winners == [candidate_seat] else 0.5 if len(winners) > 1 and candidate_seat in winners else 0.0

    return {
        "seed": seed,
        "candidate_seat": candidate_seat,
        "replay_path": f"games/shard-{shard_id:02d}/seed-{seed}/r{candidate_seat}/match-replay.json",
        "completed_plies": plies,
        "winners": winners,
        "won": won,
        "cand_score": cand_score,
        "opp_score": opp_score,
        "wall_seconds": wall,
    }


def main():
    parser = argparse.ArgumentParser(description="M50 vs v0.2.9 Co-Evolution Match Generator")
    parser.add_argument("--start-seed", type=int, default=DEFAULT_START_SEED)
    parser.add_argument("--paired-count", type=int, default=DEFAULT_PAIRED_COUNT)
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 8, 16))
    parser.add_argument("--weights", type=str, default=str(CANDIDATE_WEIGHTS))
    parser.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    weights_path = Path(args.weights)
    total_matches = args.paired_count * 2

    print(f"M50 (Pure Greedy) vs v0.2.9 Co-Evolution Generation:")
    print(f"  Paired Seeds: {args.start_seed} .. {args.start_seed + args.paired_count - 1} ({args.paired_count} pairs = {total_matches} games)")
    print(f"  Weights:      {weights_path}")
    print(f"  Workers:      {args.workers}")
    print(f"  Output:       {out_dir}")

    tasks = []
    for s in range(args.start_seed, args.start_seed + args.paired_count):
        for candidate_seat in (0, 1):
            tasks.append((s, candidate_seat, out_dir, str(CANDIDATE_EXE), str(weights_path), str(OPPONENT_EXE)))

    t0 = time.perf_counter()
    results = []
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_single_match, t): t for t in tasks}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results.append(res)
            completed += 1
            if completed % 100 == 0 or completed == total_matches:
                elapsed = time.perf_counter() - t0
                gps = completed / elapsed
                eta = (total_matches - completed) / gps if gps > 0 else 0
                wins = sum(1 for r in results if r["won"] == 1.0)
                ties = sum(1 for r in results if r["won"] == 0.5)
                losses = sum(1 for r in results if r["won"] == 0.0)
                win_pct = (wins + 0.5 * ties) / completed * 100.0
                print(
                    f"[{completed:4d}/{total_matches}] Speed: {gps:.1f} games/s | ETA: {eta:.0f}s | "
                    f"M50 W-T-L: {wins}-{ties}-{losses} ({win_pct:.1f}%)"
                )

    total_time = time.perf_counter() - t0
    wins = sum(1 for r in results if r["won"] == 1.0)
    ties = sum(1 for r in results if r["won"] == 0.5)
    losses = sum(1 for r in results if r["won"] == 0.0)
    win_pct = (wins + 0.5 * ties) / total_matches * 100.0

    print(f"\nAll {total_matches} games finished in {total_time:.2f}s ({total_matches / total_time:.1f} games/s)!")
    print(f"Final M50 Pure Greedy Record vs v0.2.9: {wins} W - {ties} T - {losses} L ({win_pct:.2f}% win rate)")

    # Sort results deterministically by seed and candidate_seat
    results.sort(key=lambda r: (r["seed"], r["candidate_seat"]))

    manifest = {
        "format": "m50-coev-selfplay-v1",
        "version": 1,
        "total_games": len(results),
        "seed_range": [args.start_seed, args.start_seed + args.paired_count - 1],
        "candidate": "m50-policy-greedy",
        "candidate_weights": str(weights_path),
        "opponent": "heuristic-v029",
        "opponent_exe": str(OPPONENT_EXE),
        "total_wall_seconds": total_time,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate_pct": win_pct,
        "rows": results,
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written to {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
