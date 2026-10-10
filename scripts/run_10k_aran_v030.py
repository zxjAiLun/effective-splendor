#!/usr/bin/env python3
"""Run 10,000 games of aran-v0.2 (Pure Greedy) vs v0.3.0 Heuristic on Cloud2.

5,000 paired-seed blocks (10,000 games with strict seat rotation):
  - Seat 0 / Seat 1 alternating
  - Candidate: aran-v0.2 (Mortal Card-Entity SE-ResNet Dueling Q-network)
  - Opponent:  Heuristic v0.3.0 (Winnable noble build bias + trailing reserve penalty)
Seeds: 9_320_000 .. 9_324_999
Output: local-artifacts/aran-v02-vs-v030-10k/
Includes automatic resume support, progress monitoring, and automated dataset extraction.
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

DEFAULT_START_SEED = 9_320_000
DEFAULT_PAIRED_COUNT = 5_000  # 5,000 x 2 = 10,000 games
OPPONENT_ARGS = ["agent-heuristic-v02", "--seed", "20260926"]


def run_single_match(args: tuple[int, int, Path, str, str, str]) -> dict:
    seed, candidate_seat, base_out_dir, cand_bin_str, weights_str, opp_bin_str = args
    shard_id = (seed - DEFAULT_START_SEED) // 250  # 20 shards total
    match_dir = base_out_dir / "games" / f"shard-{shard_id:02d}" / f"seed-{seed}" / f"r{candidate_seat}"
    match_dir.mkdir(parents=True, exist_ok=True)

    cfg_file = match_dir / "match-config.json"
    rep_file = match_dir / "arena-report.json"
    rpl_file = match_dir / "match-replay.json"

    # Fast resume check: if replay and report exist and are non-empty
    if rep_file.exists() and rpl_file.exists() and rep_file.stat().st_size > 100 and rpl_file.stat().st_size > 100:
        try:
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
                "completed_plies": plies,
                "won": won,
                "cand_score": cand_score,
                "opp_score": opp_score,
                "resumed": True,
            }
        except Exception:
            pass  # Re-run corrupted match

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
        "game_id": f"aran02-v030-{seed}-r{candidate_seat}",
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

    if proc.returncode != 0:
        raise RuntimeError(f"Seed {seed}-r{candidate_seat} failed (exit {proc.returncode}): {proc.stderr[:300]}")

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
        "completed_plies": plies,
        "won": won,
        "cand_score": cand_score,
        "opp_score": opp_score,
        "resumed": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Run 10k games of aran-v0.2 vs v0.3.0 Heuristic")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--start-seed", type=int, default=DEFAULT_START_SEED)
    parser.add_argument("--paired-count", type=int, default=DEFAULT_PAIRED_COUNT)
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 2, 4))
    parser.add_argument("--extract-after", action="store_true", default=True)
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    is_windows = sys.platform == "win32"
    ext = ".exe" if is_windows else ""

    cand_exe = repo / "target" / "release" / f"splendor{ext}"
    opp_exe = repo / "target" / "release" / f"splendor{ext}"
    weights_path = repo / "local-artifacts" / "aran-v02" / "aran_v02_weights.json"
    out_dir = repo / "local-artifacts" / "aran-v02-vs-v030-10k"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_matches = args.paired_count * 2
    print(f"=== Starting 10,000 Match Series: aran-v0.2 vs v0.3.0 Heuristic ===")
    print(f"  Seeds:        {args.start_seed} .. {args.start_seed + args.paired_count - 1} ({args.paired_count} pairs x 2 = {total_matches} games)")
    print(f"  Workers:      {args.workers}")
    print(f"  Candidate:    {cand_exe} (aran-v0.2 greedy)")
    print(f"  Opponent:     {opp_exe} (v0.3.0 heuristic)")
    print(f"  Weights:      {weights_path}")
    print(f"  Output Dir:   {out_dir}")
    print("=" * 70)

    tasks = []
    for s in range(args.start_seed, args.start_seed + args.paired_count):
        for candidate_seat in (0, 1):
            tasks.append((s, candidate_seat, out_dir, str(cand_exe), str(weights_path), str(opp_exe)))

    t0 = time.perf_counter()
    results = []
    completed = 0
    resumed_count = 0

    status_file = out_dir / "status.json"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_single_match, t): t for t in tasks}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results.append(res)
            completed += 1
            if res.get("resumed"):
                resumed_count += 1

            if completed % 100 == 0 or completed == total_matches:
                elapsed = time.perf_counter() - t0
                gps = completed / elapsed if elapsed > 0 else 0
                eta = (total_matches - completed) / gps if gps > 0 else 0
                wins = sum(1 for r in results if r["won"] == 1.0)
                ties = sum(1 for r in results if r["won"] == 0.5)
                losses = sum(1 for r in results if r["won"] == 0.0)
                win_pct = (wins + 0.5 * ties) / completed * 100.0

                s0_wins = sum(1 for r in results if r["candidate_seat"] == 0 and r["won"] == 1.0)
                s0_total = sum(1 for r in results if r["candidate_seat"] == 0)
                s0_pct = (s0_wins / s0_total * 100.0) if s0_total > 0 else 0

                s1_wins = sum(1 for r in results if r["candidate_seat"] == 1 and r["won"] == 1.0)
                s1_total = sum(1 for r in results if r["candidate_seat"] == 1)
                s1_pct = (s1_wins / s1_total * 100.0) if s1_total > 0 else 0

                status = {
                    "completed": completed,
                    "total": total_matches,
                    "resumed": resumed_count,
                    "elapsed_sec": round(elapsed, 1),
                    "games_per_sec": round(gps, 2),
                    "eta_sec": round(eta, 0),
                    "wins": wins,
                    "ties": ties,
                    "losses": losses,
                    "win_rate_pct": round(win_pct, 2),
                    "seat0_win_rate_pct": round(s0_pct, 2),
                    "seat1_win_rate_pct": round(s1_pct, 2),
                }
                status_file.write_text(json.dumps(status, indent=2))

                print(
                    f"[{completed:5d}/{total_matches}] ({completed/total_matches*100.0:5.1f}%) | "
                    f"Speed: {gps:4.1f} g/s | ETA: {eta/60:4.1f}m | "
                    f"W-T-L: {wins}-{ties}-{losses} ({win_pct:5.2f}%) | "
                    f"Seat0: {s0_pct:5.2f}% | Seat1: {s1_pct:5.2f}%"
                )
                sys.stdout.flush()

    total_time = time.perf_counter() - t0
    wins = sum(1 for r in results if r["won"] == 1.0)
    ties = sum(1 for r in results if r["won"] == 0.5)
    losses = sum(1 for r in results if r["won"] == 0.0)
    win_pct = (wins + 0.5 * ties) / total_matches * 100.0

    print("\n" + "=" * 70)
    print(f"10,000 Game Series Completed in {total_time/60:.1f} minutes ({total_matches/total_time:.2f} games/s)!")
    print(f"Final Record: {wins} Wins - {ties} Ties - {losses} Losses ({win_pct:.2f}% Win Rate)")
    print("=" * 70 + "\n")

    # Extract dataset if requested
    if args.extract_after:
        dataset_out = out_dir / "dataset"
        print(f"Extracting training dataset to {dataset_out}...")
        replays_dir = out_dir / "games"
        t_ext = time.perf_counter()
        ext_proc = subprocess.run(
            [
                str(cand_exe),
                "m50-extract-replays",
                "--replays-dir", str(replays_dir),
                "--out-dir", str(dataset_out),
                "--val-modulus", "5",
                "--val-remainder", "0",
            ],
            capture_output=True,
            text=True,
        )
        if ext_proc.returncode != 0:
            print(f"Dataset extraction failed: {ext_proc.stderr}")
        else:
            print(ext_proc.stdout)
            print(f"Dataset extracted in {time.perf_counter() - t_ext:.1f}s.")

            # Package dataset into tar.gz
            tar_path = out_dir / "aran_v02_vs_v030_10k_dataset.tar.gz"
            print(f"Packaging dataset into {tar_path}...")
            tar_cmd = ["tar", "-czf", str(tar_path), "-C", str(out_dir), "dataset"]
            subprocess.run(tar_cmd, check=True)
            print(f"Archive ready! Size: {tar_path.stat().st_size / (1024*1024):.1f} MB")


if __name__ == "__main__":
    main()
