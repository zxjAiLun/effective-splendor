"""M44B Arena Orchestrator: F2 Permanent Engine Attribution.

Executes the frozen 2 pairings across 64 paired seed blocks x 2 seat rotations = 256 physical matches:
  - 1. DROP_CORE_ENGINE vs FULL
  - 2. DROP_NOBLE_PROGRESS vs FULL

All agents use the identical n1 static-successor decision shell (sample_seed=20_260_703, sample_count=4, depth=1, nodes=1).
Evaluates:
  - Bonferroni-adjusted 97.5% two-sided bootstrap CIs (alpha = 0.05/2)
  - BOOTSTRAP_SEED = 44_280_001, 10,000 resamples
  - Decision rules: RESOLVED_SENSITIVE, RESOLVED_HARMFUL_OR_INTERFERING, UNRESOLVED
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SPLN = REPO / "target/release/splendor.exe"
OUT_ROOT = REPO / "local-artifacts/m44b-arena"

# Frozen contract constants
BOOTSTRAP_SEED = 44_280_001
BOOTSTRAP_RESAMPLES = 10_000
SAMPLE_SEED = 20_260_703
SAMPLE_COUNT = 4
DEPTH_TURNS = 1
MAX_NODES = 1
FROZEN_SEEDS = list(range(5_600_000, 5_600_064))  # 64 paired blocks

PAIRING_SPECS = [
    {"id": "drop_core_engine_vs_full", "primary_profile": "drop_core_engine", "secondary_profile": "full"},
    {"id": "drop_noble_progress_vs_full", "primary_profile": "drop_noble_progress", "secondary_profile": "full"},
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_spec(profile: str) -> dict[str, Any]:
    name = f"m44b-{profile.replace('_', '-')}"
    return {
        "program": str(SPLN),
        "args": [
            "agent-determinization",
            "--sample-seed", str(SAMPLE_SEED),
            "--sample-count", str(SAMPLE_COUNT),
            "--max-depth-turns", str(DEPTH_TURNS),
            "--max-nodes", str(MAX_NODES),
            "--attribution-profile", profile,
            "--runtime-name", name,
            "--runtime-version", "1",
        ],
    }


def build_match_config(
    game_id: str,
    seed: int,
    primary_profile: str,
    secondary_profile: str,
    rotation: int,
) -> tuple[dict[str, Any], int]:
    cmd_p = agent_spec(primary_profile)
    cmd_s = agent_spec(secondary_profile)

    if rotation == 0:
        agents = [cmd_p, cmd_s]
        primary_seat = 0
    else:
        agents = [cmd_s, cmd_p]
        primary_seat = 1

    cfg = {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
        "agents": agents,
    }
    return cfg, primary_seat


def run_one_match(
    pairing_id: str,
    block_idx: int,
    seed: int,
    rotation: int,
    primary_profile: str,
    secondary_profile: str,
    work_dir: Path,
) -> dict[str, Any]:
    game_id = f"m44b-{pairing_id}-b{block_idx:02d}-s{seed}-r{rotation}"
    match_dir = work_dir / f"block-{block_idx:02d}-seed-{seed}" / f"r{rotation}"
    match_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = match_dir / "match-config.json"
    rep_path = match_dir / "arena-report.json"
    rpl_path = match_dir / "match-replay.json"

    cfg, primary_seat = build_match_config(game_id, seed, primary_profile, secondary_profile, rotation)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    cmd = [
        str(SPLN), "run-match",
        "--config", str(cfg_path),
        "--report-out", str(rep_path),
        "--replay-out", str(rpl_path),
    ]

    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    wall_duration = time.time() - t0

    if res.returncode != 0:
        raise RuntimeError(f"Match {game_id} failed ({res.returncode}): stderr={res.stderr}")

    report = json.loads(rep_path.read_text(encoding="utf-8"))
    outcome = report.get("outcome", {})
    if outcome.get("status") != "completed":
        raise RuntimeError(f"Match {game_id} non-completed outcome: {outcome}")

    result = outcome["result"]
    winners = result["winners"]
    if primary_seat in winners:
        if len(winners) == 1:
            score = 10_000.0
            won = True
            tied = False
        else:
            score = 5_000.0
            won = False
            tied = True
    else:
        score = 0.0
        won = False
        tied = False

    return {
        "block_idx": block_idx,
        "rotation": rotation,
        "primary_seat": primary_seat,
        "score_bps": score,
        "won": won,
        "tied": tied,
        "lost": not won and not tied,
        "primary_final_score": result["scores"][primary_seat],
        "secondary_final_score": result["scores"][1 - primary_seat],
        "completed_plies": outcome["completed_plies"],
        "wall_duration": wall_duration,
        "replay_path": str(rpl_path),
        "report_path": str(rep_path),
    }


def bootstrap_ci_975(block_scores: list[float], seed: int, resamples: int) -> tuple[float, float]:
    import numpy as np

    rng = np.random.RandomState(seed)
    n = len(block_scores)
    arr = np.array(block_scores, dtype=np.float64)
    idx = rng.randint(0, n, size=(resamples, n))
    sample_means = np.mean(arr[idx], axis=1)
    lower = float(np.percentile(sample_means, 1.25))
    upper = float(np.percentile(sample_means, 98.75))
    return lower, upper


def run_pairing(spec: dict[str, Any], workers: int = 8) -> dict[str, Any]:
    pairing_id = spec["id"]
    work_dir = OUT_ROOT / pairing_id
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n>>> Running Pairing: {pairing_id} (64 blocks x 2 rotations = 128 matches)...", flush=True)
    t0 = time.time()

    tasks = []
    for b_idx, seed in enumerate(FROZEN_SEEDS):
        for rot in (0, 1):
            tasks.append((b_idx, seed, rot))

    results_by_task = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_task = {
            executor.submit(
                run_one_match,
                pairing_id,
                b_idx,
                seed,
                rot,
                spec["primary_profile"],
                spec["secondary_profile"],
                work_dir,
            ): (b_idx, rot)
            for b_idx, seed, rot in tasks
        }
        for future in concurrent.futures.as_completed(future_to_task):
            task_key = future_to_task[future]
            try:
                res = future.result()
                results_by_task[task_key] = res
            except Exception as e:
                print(f"Task {task_key} failed: {e}", flush=True)
                raise e

    block_scores = []
    wins = 0
    ties = 0
    losses = 0
    seat0_scores = []
    seat1_scores = []
    total_plies = []

    for b_idx in range(len(FROZEN_SEEDS)):
        r0 = results_by_task[(b_idx, 0)]
        r1 = results_by_task[(b_idx, 1)]
        blk_score = (r0["score_bps"] + r1["score_bps"]) / 2.0
        block_scores.append(blk_score)

        for r in (r0, r1):
            if r["won"]:
                wins += 1
            elif r["tied"]:
                ties += 1
            else:
                losses += 1
            total_plies.append(r["completed_plies"])

        seat0_scores.append(r0["score_bps"])
        seat1_scores.append(r1["score_bps"])

    center_bps = sum(block_scores) / len(block_scores)
    ci_lower, ci_upper = bootstrap_ci_975(block_scores, BOOTSTRAP_SEED, BOOTSTRAP_RESAMPLES)

    # Decision rule
    if ci_upper < 5000.0:
        verdict = "RESOLVED_SENSITIVE"
    elif ci_lower > 5000.0:
        verdict = "RESOLVED_HARMFUL_OR_INTERFERING"
    else:
        verdict = "UNRESOLVED"

    elapsed = time.time() - t0
    print(
        f"Pairing {pairing_id} finished in {elapsed:.1f}s: "
        f"Score {center_bps:.1f} bps (97.5% CI: [{ci_lower:.1f}, {ci_upper:.1f}]), "
        f"W/T/L: {wins}/{ties}/{losses} -> {verdict}",
        flush=True,
    )

    return {
        "pairing_id": pairing_id,
        "primary_profile": spec["primary_profile"],
        "secondary_profile": spec["secondary_profile"],
        "matches_expected": 128,
        "matches_verified": len(block_scores) * 2,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "center_bps": center_bps,
        "ci_level": "97.5%",
        "bootstrap_ci": [ci_lower, ci_upper],
        "verdict": verdict,
        "seat0_mean_bps": sum(seat0_scores) / len(seat0_scores),
        "seat1_mean_bps": sum(seat1_scores) / len(seat1_scores),
        "mean_completed_plies": sum(total_plies) / len(total_plies),
        "total_elapsed_seconds": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M44B Arena Orchestrator")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    global FROZEN_SEEDS
    if args.smoke:
        print("RUNNING IN SMOKE MODE (1 block)...", flush=True)
        FROZEN_SEEDS = FROZEN_SEEDS[:1]

    print("M44B Arena Orchestrator started.", flush=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    results = []
    for spec in PAIRING_SPECS:
        res = run_pairing(spec, workers=args.workers)
        results.append(res)

    total_time = time.time() - t0
    summary = {
        "format": "effective-splendor-m44b-orchestrator-summary",
        "version": 1,
        "total_pairings": len(results),
        "total_matches": sum(r["matches_verified"] for r in results),
        "total_elapsed_seconds": total_time,
        "pairings": results,
    }

    out_file = OUT_ROOT / "m44b-orchestrator-summary.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nAll 2 pairings completed in {total_time:.1f}s. Summary written to {out_file}.", flush=True)


if __name__ == "__main__":
    main()
