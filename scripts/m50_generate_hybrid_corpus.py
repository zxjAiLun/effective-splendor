#!/usr/bin/env python3
"""Generate hybrid training corpus for aran-v0.1:
Part 1: 2,000 games of aran-v0 self-play (seeds 9_312_000 .. 9_312_999)
Part 2: 2,000 games of aran-v0 vs v0.2.9 co-evolution (seeds 9_313_000 .. 9_313_999)
Both in pure greedy mode across 16 concurrent workers.
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
CANDIDATE_EXE = ROOT / "target" / "release" / "splendor.exe"
ARAN_V0_WEIGHTS = ROOT / "local-artifacts" / "aran-v0" / "aran_v0_weights.json"
V029_EXE = ROOT / "local-artifacts" / "s4-heuristic-v029-pilot" / "splendor-candidate.exe"
OPPONENT_ARGS = ["agent-heuristic-v02", "--seed", "20260926"]

BASE_OUT_DIR = ROOT / "local-artifacts" / "aran-v01-corpus"


def run_one_game(task: tuple) -> dict:
    mode, seed, cand_seat, out_dir, cand_bin_str, weights_str, opp_bin_str = task
    shard_id = (seed % 1000) // 250
    game_dir = out_dir / f"shard-{shard_id:02d}" / f"seed-{seed}" / f"r{cand_seat}"
    game_dir.mkdir(parents=True, exist_ok=True)

    cfg_file = game_dir / "match-config.json"
    rep_file = game_dir / "arena-report.json"
    rpl_file = game_dir / "match-replay.json"

    agent_aran = {
        "program": cand_bin_str,
        "args": ["agent-m50-policy", "--weights", weights_str, "--mode", "greedy"],
    }

    if mode == "selfplay":
        agents = [agent_aran, agent_aran]
        label = f"aran-sp-{seed}-r{cand_seat}"
    else:
        agent_opp = {
            "program": opp_bin_str,
            "args": OPPONENT_ARGS,
        }
        agents = [agent_aran, agent_opp] if cand_seat == 0 else [agent_opp, agent_aran]
        label = f"aran-opp-{seed}-r{cand_seat}"

    match_config = {
        "game_id": label,
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
    wall_sec = time.perf_counter() - t0

    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed (code {proc.returncode}): {proc.stderr[:300]}")

    with open(rep_file, "r", encoding="utf-8") as f:
        rep = json.load(f)

    res = rep["outcome"]["result"]
    scores = res["scores"]
    winners = res["winners"]
    cand_seat_u8 = cand_seat

    cand_won = 1.0 if (len(winners) == 1 and winners[0] == cand_seat_u8) else (0.5 if len(winners) > 1 else 0.0)

    return {
        "mode": mode,
        "seed": seed,
        "cand_seat": cand_seat,
        "won": cand_won,
        "scores": scores,
        "wall_sec": wall_sec,
    }


def generate_batch(mode: str, seed_start: int, count: int, out_dir: Path, weights_path: Path, opp_bin: Path, workers: int = 16):
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n{'='*70}\nGenerating {mode.upper()}: seeds {seed_start}..{seed_start + count - 1} ({count * 2} games)\nWorkers: {workers} | Weights: {weights_path.name} | Opponent: {opp_bin.name}\nTarget Dir: {out_dir}\n{'='*70}")

    tasks = []
    for seed in range(seed_start, seed_start + count):
        for s in (0, 1):
            tasks.append((mode, seed, s, out_dir, str(CANDIDATE_EXE), str(weights_path), str(opp_bin)))

    t_start = time.perf_counter()
    completed = 0
    total = len(tasks)
    won_count = 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_one_game, t): t for t in tasks}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            completed += 1
            won_count += res["won"]
            if completed % 100 == 0 or completed == total:
                elapsed = time.perf_counter() - t_start
                gps = completed / elapsed
                pct = (won_count / completed) * 100.0 if mode != "selfplay" else 50.0
                print(f"[{completed:4d}/{total}] Finished | Speed: {gps:.1f} games/s | Win%: {pct:.1f}%")

    total_sec = time.perf_counter() - t_start
    print(f"{mode.upper()} complete in {total_sec:.2f}s ({completed / total_sec:.1f} games/s)\n")


def main():
    parser = argparse.ArgumentParser(description="Generate Hybrid Training Corpus for aran")
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 16, 16))
    parser.add_argument("--weights", type=str, default=str(ARAN_V0_WEIGHTS))
    parser.add_argument("--opp-bin", type=str, default=str(V029_EXE))
    parser.add_argument("--out-dir", type=str, default=str(BASE_OUT_DIR))
    parser.add_argument("--selfplay-start", type=int, default=9_312_000)
    parser.add_argument("--coev-start", type=int, default=9_313_000)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--skip-selfplay", action="store_true")
    parser.add_argument("--skip-coev", action="store_true")
    args = parser.parse_args()

    out_base = Path(args.out_dir)
    out_base.mkdir(parents=True, exist_ok=True)
    weights_path = Path(args.weights)
    opp_bin = Path(args.opp_bin)

    if not args.skip_selfplay:
        generate_batch(
            mode="selfplay",
            seed_start=args.selfplay_start,
            count=args.count,
            out_dir=out_base / "selfplay",
            weights_path=weights_path,
            opp_bin=opp_bin,
            workers=args.workers,
        )

    if not args.skip_coev:
        generate_batch(
            mode="coev",
            seed_start=args.coev_start,
            count=args.count,
            out_dir=out_base / "coev",
            weights_path=weights_path,
            opp_bin=opp_bin,
            workers=args.workers,
        )

    print("All matches generated successfully!")


if __name__ == "__main__":
    main()
