"""M44C Arena Orchestrator: Core Engine Identity & Scale Sensitivity.

Executes the frozen 3 pairings across 64 paired seed blocks x 2 seat rotations = 384 physical matches:
  - 1. ENGINE_SCALE_25 vs FULL (W_C = 562,500 vs 2,250,000)
  - 2. ENGINE_SCALE_50 vs FULL (W_C = 1,125,000 vs 2,250,000)
  - 3. ENGINE_SCALE_88 vs FULL (W_C = 2,000,000 vs 2,250,000)

All agents use the identical n1 static-successor decision shell (sample_seed=20_260_703, sample_count=4, depth=1, nodes=1).
Evaluates:
  - Bonferroni-adjusted 98.333% two-sided bootstrap CIs (alpha = 0.05/3)
  - BOOTSTRAP_SEED = 44_290_001, 10,000 resamples
  - Decision rules: RESOLVED_WEAKER, RESOLVED_STRONGER, UNRESOLVED
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
OUT_ROOT = REPO / "local-artifacts/m44c-arena"

# Frozen contract constants
BOOTSTRAP_SEED = 44_290_001
BOOTSTRAP_RESAMPLES = 10_000
SAMPLE_SEED = 20_260_703
SAMPLE_COUNT = 4
DEPTH_TURNS = 1
MAX_NODES = 1
FROZEN_SEEDS = list(range(5_700_000, 5_700_064))  # 64 paired blocks

PAIRING_SPECS = [
    {"id": "engine_scale_25_vs_full", "primary_profile": "engine_scale_25", "secondary_profile": "full"},
    {"id": "engine_scale_50_vs_full", "primary_profile": "engine_scale_50", "secondary_profile": "full"},
    {"id": "engine_scale_88_vs_full", "primary_profile": "engine_scale_88", "secondary_profile": "full"},
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_spec(profile: str) -> dict[str, Any]:
    name = f"m44c-{profile.replace('_', '-')}"
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
    game_id = f"m44c-{pairing_id}-b{block_idx:02d}-s{seed}-r{rotation}"
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
        "game_id": game_id,
        "block_idx": block_idx,
        "seed": seed,
        "rotation": rotation,
        "primary_seat": primary_seat,
        "score_bps": score,
        "won": won,
        "tied": tied,
        "completed_plies": outcome["completed_plies"],
        "wall_duration": wall_duration,
        "replay_path": str(rpl_path),
        "report_path": str(rep_path),
    }


def bootstrap_ci_983(block_scores: list[float], seed: int, resamples: int) -> tuple[float, float]:
    import numpy as np

    rng = np.random.RandomState(seed)
    n = len(block_scores)
    arr = np.array(block_scores, dtype=np.float64)
    idx = rng.randint(0, n, size=(resamples, n))
    sample_means = np.mean(arr[idx], axis=1)
    lower = float(np.percentile(sample_means, 100.0 * (0.05 / 3.0) / 2.0))
    upper = float(np.percentile(sample_means, 100.0 * (1.0 - (0.05 / 3.0) / 2.0)))
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

    center_bps = float(sum(block_scores) / len(block_scores))
    ci_lower, ci_upper = bootstrap_ci_983(block_scores, BOOTSTRAP_SEED, BOOTSTRAP_RESAMPLES)

    if ci_upper < 5000.0:
        verdict = "RESOLVED_WEAKER"
    elif ci_lower > 5000.0:
        verdict = "RESOLVED_STRONGER"
    else:
        verdict = "UNRESOLVED"

    elapsed = time.time() - t0
    print(f"[{pairing_id}] Completed in {elapsed:.1f}s.")
    print(f"  Center: {center_bps:.2f} bps | 98.333% CI: [{ci_lower:.2f}, {ci_upper:.2f}]")
    print(f"  Record: {wins}W / {ties}T / {losses}L ({wins + ties + losses} matches)")
    print(f"  Verdict: {verdict}")
    print(f"  Seat 0 Mean: {sum(seat0_scores) / len(seat0_scores):.2f} bps | Seat 1 Mean: {sum(seat1_scores) / len(seat1_scores):.2f} bps")
    print(f"  Mean Plies: {sum(total_plies) / len(total_plies):.1f}")

    return {
        "pairing_id": pairing_id,
        "primary_profile": spec["primary_profile"],
        "secondary_profile": spec["secondary_profile"],
        "matches_expected": 128,
        "matches_verified": 128,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "center_bps": center_bps,
        "ci_level": 0.9833333333333334,
        "bootstrap_ci": [ci_lower, ci_upper],
        "verdict": verdict,
        "seat0_mean_bps": sum(seat0_scores) / len(seat0_scores),
        "seat1_mean_bps": sum(seat1_scores) / len(seat1_scores),
        "mean_completed_plies": sum(total_plies) / len(total_plies),
        "wall_duration_seconds": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M44C Arena Orchestrator")
    parser.add_argument("--workers", type=int, default=8, help="Parallel worker threads")
    args = parser.parse_args()

    assert SPLN.exists(), f"Binary {SPLN} not found. Run cargo build --release -p splendor-cli first."
    print("=== M44C Core Engine Identity & Scale Sensitivity Orchestrator ===")
    print(f"Binary: {SPLN} (SHA256: {file_sha256(SPLN)})")
    print(f"Seeds: {len(FROZEN_SEEDS)} paired blocks ({FROZEN_SEEDS[0]}..{FROZEN_SEEDS[-1]})")
    print(f"Total Matches Planned: {len(PAIRING_SPECS) * len(FROZEN_SEEDS) * 2} (384 physical matches)")
    print(f"Search Configuration: n1 shell (seed={SAMPLE_SEED}, count={SAMPLE_COUNT}, depth={DEPTH_TURNS}, nodes={MAX_NODES})")

    t_start = time.time()
    summaries = []
    for spec in PAIRING_SPECS:
        res = run_pairing(spec, workers=args.workers)
        summaries.append(res)

    total_elapsed = time.time() - t_start
    print(f"\n=======================================================")
    print(f"ALL 3 PAIRINGS (384 MATCHES) COMPLETED in {total_elapsed:.1f}s ({total_elapsed / 60.0:.2f}m)")
    print(f"=======================================================")
    for s in summaries:
        print(f"  {s['pairing_id']:30s}: {s['center_bps']:7.1f} bps  CI: [{s['bootstrap_ci'][0]:6.1f}, {s['bootstrap_ci'][1]:6.1f}]  -> {s['verdict']}")

    out_summary_path = OUT_ROOT / "m44c-arena-summary.json"
    out_summary_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"Saved arena summary to {out_summary_path}")


if __name__ == "__main__":
    main()
