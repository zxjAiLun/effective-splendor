#!/usr/bin/env python3
"""Run 5,000 games of pure Heuristic v0.2.9 self-play and analyze unified metrics.

All games are run concurrently using the release splendor CLI binary.
Output directory: local-artifacts/m50-v029-selfplay-5k/
Seeds: 9_300_000 .. 9_304_999 (5,000 total)
P0 args: agent-heuristic-v02 --seed 20260926
P1 args: agent-heuristic-v02 --seed 20260927
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
DEFAULT_START_SEED = 9_300_000
DEFAULT_GAME_COUNT = 5_000
DEFAULT_OUT_DIR = ROOT / "local-artifacts" / "m50-v029-selfplay-5k"
BINARY_PATH = ROOT / "target" / "release" / "splendor.exe"

P0_ARGS = ["agent-heuristic-v02", "--seed", "20260926"]
P1_ARGS = ["agent-heuristic-v02", "--seed", "20260927"]


def run_single_game(args: tuple[int, Path, str]) -> dict:
    seed, base_out_dir, binary_str = args
    shard_id = (seed - DEFAULT_START_SEED) // 1000
    shard_dir = base_out_dir / "games" / f"shard-{shard_id:02d}" / f"seed-{seed}"
    shard_dir.mkdir(parents=True, exist_ok=True)

    cfg_file = shard_dir / "match-config.json"
    rep_file = shard_dir / "arena-report.json"
    rpl_file = shard_dir / "match-replay.json"

    match_config = {
        "game_id": f"v029-selfplay-{seed}",
        "seed": seed,
        "agents": [
            {"program": binary_str, "args": P0_ARGS},
            {"program": binary_str, "args": P1_ARGS},
        ],
        "handshake_timeout_ms": 10000,
        "move_timeout_ms": 60000,
        "shutdown_grace_ms": 2000,
    }

    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(match_config, f, indent=2)

    cmd = [
        binary_str,
        "run-match",
        "--config", str(cfg_file),
        "--report-out", str(rep_file),
        "--replay-out", str(rpl_file),
    ]

    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
    wall = time.monotonic() - t0

    if p.returncode != 0:
        raise RuntimeError(f"Game seed {seed} failed with code {p.returncode}: {p.stderr}")

    rel_rpl_path = rpl_file.relative_to(base_out_dir).as_posix()
    return {
        "seed": seed,
        "replay_path": rel_rpl_path,
        "wall_seconds": round(wall, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=DEFAULT_GAME_COUNT)
    parser.add_argument("--start-seed", type=int, default=DEFAULT_START_SEED)
    parser.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 8))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    binary_str = str(BINARY_PATH.resolve())

    print(f"Starting {args.count} games of v0.2.9 self-play with {args.workers} workers...")
    print(f"Seeds: {args.start_seed} .. {args.start_seed + args.count - 1}")
    print(f"Output: {out_dir}")

    tasks = [(seed, out_dir, binary_str) for seed in range(args.start_seed, args.start_seed + args.count)]
    t_start = time.monotonic()
    completed_rows = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_single_game, task): task[0] for task in tasks}
        total = len(futures)
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            seed = futures[fut]
            try:
                res = fut.result()
                completed_rows.append(res)
                done += 1
                if done % 500 == 0 or done == total:
                    elapsed = time.monotonic() - t_start
                    rate = done / max(elapsed, 0.001)
                    print(f"[{done:4d}/{total}] completed in {elapsed:.1f}s ({rate:.1f} games/s)")
            except Exception as e:
                print(f"ERROR on seed {seed}: {e}", file=sys.stderr)
                raise

    total_wall = time.monotonic() - t_start
    print(f"All {len(completed_rows)} games completed in {total_wall:.2f}s ({len(completed_rows)/total_wall:.1f} games/s)!")

    # Sort rows by seed for determinism
    completed_rows.sort(key=lambda x: x["seed"])
    manifest = {
        "format": "effective-splendor-selfplay-manifest-v1",
        "version": 1,
        "agent": "heuristic-v029",
        "total_games": len(completed_rows),
        "start_seed": args.start_seed,
        "p0_args": P0_ARGS,
        "p1_args": P1_ARGS,
        "rows": completed_rows,
        "total_wall_seconds": round(total_wall, 2),
    }

    manifest_file = out_dir / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest: {manifest_file}")

    # Now invoke the Rust unified metrics analyzer
    print("\nRunning Rust unified metrics analyzer across all 5,000 replays...")
    metrics_file = out_dir / "metrics-summary.json"
    cmd_metrics = [
        "cargo", "run", "--release", "-p", "splendor-cli",
        "--example", "s4_batch_metrics", "--",
        str(manifest_file),
        str(metrics_file),
    ]
    t_metrics = time.monotonic()
    p = subprocess.run(cmd_metrics, cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr, file=sys.stderr)
        raise RuntimeError("Failed computing metrics with s4_batch_metrics")

    print(f"Unified metrics computed in {time.monotonic() - t_metrics:.2f}s! Saved to {metrics_file}")
    
    # Print the formatted summary
    with open(metrics_file, "r", encoding="utf-8") as f:
        rep = json.load(f)

    p0 = rep["seat_p0_first"]
    p1 = rep["seat_p1_second"]

    print("\n" + "=" * 65)
    print("       S4.9 v0.2.9 5,000-Game Pure Self-Play Benchmark Report       ")
    print("=" * 65)
    print(f"Total Matches:    {rep['total_games']}")
    print(f"Total Plies:      {rep['total_plies']} (mean {rep['mean_plies']:.2f} plies/game)")
    print(f"Game Turns:       Mean = {rep['mean_turns']:.2f}, Median = {rep['median_turns']:.1f}, Min = {rep['min_turns']}, Max = {rep['max_turns']}, Std = {rep['std_turns']:.2f}")
    print(f"Victory Margin:   Mean = {rep['mean_victory_margin']:.2f} pts (Close games <= 2 pts: {rep['close_games_margin_le_2_percent']:.1f}%)")
    print("-" * 65)
    print(f"Seat 0 (First · P0):")
    print(f"  Win Rate:       {p0['win_rate_percent']:.2f}% ({p0['wins']} W / {p0['ties']} T / {p0['losses']} L)")
    print(f"  Mean Score:     {p0['mean_prestige']:.2f} VP")
    print(f"  VP / Turn:      {p0['vp_per_turn']:.3f} VP/turn")
    print(f"  VP / Ply:       {p0['vp_per_ply']:.3f} VP/ply")
    print(f"  Nobles Claimed: Mean = {p0['mean_nobles']:.2f} ({p0['games_with_nobles_percent']:.1f}% games with >= 1 noble)")
    print(f"  Cards by VP:    0-VP: {p0['mean_cards_by_vp']['0']:.2f}, 1-VP: {p0['mean_cards_by_vp']['1']:.2f}, 2-VP: {p0['mean_cards_by_vp']['2']:.2f}, 3-VP: {p0['mean_cards_by_vp']['3']:.2f}, 4-VP: {p0['mean_cards_by_vp']['4']:.2f}, 5-VP: {p0['mean_cards_by_vp']['5']:.2f}")
    print(f"  Total Bonuses:  {p0['mean_permanent_bonuses']:.2f} discounts at endgame")
    print(f"  Reserves:       Acquired = {p0['mean_reserves_acquired']:.2f}, Bought = {p0['mean_reserves_bought']:.2f}, Stranded = {p0['mean_reserves_stranded']:.2f}")
    print("-" * 65)
    print(f"Seat 1 (Second · P1):")
    print(f"  Win Rate:       {p1['win_rate_percent']:.2f}% ({p1['wins']} W / {p1['ties']} T / {p1['losses']} L)")
    print(f"  Mean Score:     {p1['mean_prestige']:.2f} VP")
    print(f"  VP / Turn:      {p1['vp_per_turn']:.3f} VP/turn")
    print(f"  VP / Ply:       {p1['vp_per_ply']:.3f} VP/ply")
    print(f"  Nobles Claimed: Mean = {p1['mean_nobles']:.2f} ({p1['games_with_nobles_percent']:.1f}% games with >= 1 noble)")
    print(f"  Cards by VP:    0-VP: {p1['mean_cards_by_vp']['0']:.2f}, 1-VP: {p1['mean_cards_by_vp']['1']:.2f}, 2-VP: {p1['mean_cards_by_vp']['2']:.2f}, 3-VP: {p1['mean_cards_by_vp']['3']:.2f}, 4-VP: {p1['mean_cards_by_vp']['4']:.2f}, 5-VP: {p1['mean_cards_by_vp']['5']:.2f}")
    print(f"  Total Bonuses:  {p1['mean_permanent_bonuses']:.2f} discounts at endgame")
    print(f"  Reserves:       Acquired = {p1['mean_reserves_acquired']:.2f}, Bought = {p1['mean_reserves_bought']:.2f}, Stranded = {p1['mean_reserves_stranded']:.2f}")
    print("=" * 65)


if __name__ == "__main__":
    main()
