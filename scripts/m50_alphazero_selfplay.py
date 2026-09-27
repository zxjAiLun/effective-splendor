#!/usr/bin/env python3
"""Run M50 Neural MCTS Self-Play (AlphaZero Loop - Generation 1).

Generates 2,000 games of self-play between M50 neural agents (256-dim model,
32 IS-MCTS simulations, max-depth 6) on fresh seeds 9_305_000 .. 9_306_999.
Output directory: local-artifacts/m50-selfplay-gen1/
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
DEFAULT_START_SEED = 9_305_000
DEFAULT_GAME_COUNT = 2_000
DEFAULT_OUT_DIR = ROOT / "local-artifacts" / "m50-selfplay-gen1"
BINARY_PATH = ROOT / "target" / "release" / "splendor.exe"
WEIGHTS_PATH = ROOT / "local-artifacts" / "m50-v029-dim256-run" / "m50_steps_weights.json"


def run_single_game(args: tuple[int, Path, str, str, int, int]) -> dict:
    seed, base_out_dir, binary_str, weights_str, sims, depth = args
    shard_id = (seed - DEFAULT_START_SEED) // 1000
    shard_dir = base_out_dir / "games" / f"shard-{shard_id:02d}" / f"seed-{seed}"
    shard_dir.mkdir(parents=True, exist_ok=True)

    cfg_file = shard_dir / "match-config.json"
    rep_file = shard_dir / "arena-report.json"
    rpl_file = shard_dir / "match-replay.json"

    p0_args = [
        "agent-m50-policy",
        "--weights", weights_str,
        "--mode", "ismcts",
        "--simulations", str(sims),
        "--max-depth", str(depth),
        "--seed", str(seed * 2 + 1),
    ]
    p1_args = [
        "agent-m50-policy",
        "--weights", weights_str,
        "--mode", "ismcts",
        "--simulations", str(sims),
        "--max-depth", str(depth),
        "--seed", str(seed * 2 + 2),
    ]

    match_config = {
        "game_id": f"m50-selfplay-gen1-{seed}",
        "seed": seed,
        "agents": [
            {"program": binary_str, "args": p0_args},
            {"program": binary_str, "args": p1_args},
        ],
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
            binary_str,
            "run-match",
            "--config", str(cfg_file),
            "--report-out", str(rep_file),
            "--replay-out", str(rpl_file),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    wall = time.perf_counter() - t0

    if proc.returncode != 0:
        raise RuntimeError(f"Seed {seed} failed with code {proc.returncode}: {proc.stderr[:400]}")

    with open(rep_file, "r", encoding="utf-8") as f:
        rep = json.load(f)

    res = rep["outcome"]["result"]
    return {
        "seed": seed,
        "replay_path": f"games/shard-{shard_id:02d}/seed-{seed}/match-replay.json",
        "completed_plies": rep["outcome"]["completed_plies"],
        "winners": res["winners"],
        "scores": res["scores"],
        "wall_seconds": wall,
    }


def main():
    parser = argparse.ArgumentParser(description="M50 Neural Self-Play Generator")
    parser.add_argument("--start-seed", type=int, default=DEFAULT_START_SEED)
    parser.add_argument("--count", type=int, default=DEFAULT_GAME_COUNT)
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 8, 16))
    parser.add_argument("--sims", type=int, default=32)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--weights", type=str, default=str(WEIGHTS_PATH))
    parser.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    weights_path = Path(args.weights)

    print(f"M50 Neural IS-MCTS Self-Play:")
    print(f"  Seeds:       {args.start_seed} .. {args.start_seed + args.count - 1} ({args.count} games)")
    print(f"  Weights:     {weights_path}")
    print(f"  Simulations: {args.sims}, Depth: {args.depth}")
    print(f"  Workers:     {args.workers}")
    print(f"  Output:      {out_dir}")

    tasks = [
        (s, out_dir, str(BINARY_PATH), str(weights_path), args.sims, args.depth)
        for s in range(args.start_seed, args.start_seed + args.count)
    ]

    t0 = time.perf_counter()
    results = []
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_single_game, t): t[0] for t in tasks}
        for future in concurrent.futures.as_completed(futures):
            seed = futures[future]
            try:
                res = future.result()
                results.append(res)
                completed += 1
                if completed % 100 == 0 or completed == args.count:
                    elapsed = time.perf_counter() - t0
                    gps = completed / elapsed
                    eta = (args.count - completed) / gps if gps > 0 else 0
                    p0_w = sum(1 for r in results if r["winners"] == [0])
                    p1_w = sum(1 for r in results if r["winners"] == [1])
                    ties = sum(1 for r in results if len(r["winners"]) > 1)
                    print(
                        f"[{completed:4d}/{args.count}] Speed: {gps:.1f} games/s | ETA: {eta:.0f}s | "
                        f"P0 wins: {p0_w} ({p0_w/completed*100:.1f}%), P1 wins: {p1_w} ({p1_w/completed*100:.1f}%), ties: {ties}"
                    )
            except Exception as e:
                print(f"Error on seed {seed}: {e}", file=sys.stderr)
                sys.exit(1)

    total_time = time.perf_counter() - t0
    print(f"\nAll {args.count} games finished in {total_time:.2f}s ({args.count / total_time:.1f} games/s)!")

    # Write manifest
    manifest = {
        "format": "m50-alphazero-selfplay-v1",
        "version": 1,
        "total_games": len(results),
        "seed_range": [args.start_seed, args.start_seed + args.count - 1],
        "simulations": args.sims,
        "max_depth": args.depth,
        "weights_path": str(weights_path),
        "total_wall_seconds": total_time,
        "rows": results,
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written to {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
