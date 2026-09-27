#!/usr/bin/env python3
"""M50 Simulation Scaling: Head-to-Head Evaluation with 64 and 128 IS-MCTS Simulations.

Evaluates M50 Neural IS-MCTS against the frozen v0.2.5 Heuristic across the
same 64 paired-seed blocks (128 games) with strict seat rotation:
  1. 64 simulations per decision
  2. 128 simulations per decision
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("E:/AUbuntuProject/project/splendor")
CANDIDATE_EXE = ROOT / "target" / "release" / "splendor.exe"
CANDIDATE_WEIGHTS = ROOT / "local-artifacts" / "m50-large-run" / "m50_large_policy_weights.json"

OPPONENT_EXE = ROOT / "local-artifacts" / "s4-heuristic-v025-pilot" / "splendor-candidate.exe"
OPPONENT_ARGS = ["agent-heuristic-v02", "--seed", "20260926"]

SEED_START = 9_260_000
SEED_COUNT = 64


def percentile(samples: list[float], fraction: float) -> float:
    pos = (len(samples) - 1) * fraction
    low = int(pos)
    return samples[low] * (1 - (pos - low)) + samples[min(low + 1, len(samples) - 1)] * (pos - low)


def run_one_match(seed: int, candidate_seat: int, sims: int, out_dir: Path, label: str) -> dict:
    match_dir = out_dir / f"seed-{seed}" / f"r{candidate_seat}"
    match_dir.mkdir(parents=True, exist_ok=True)
    game_id = f"{label}-{seed}-r{candidate_seat}"

    cand_agent = {
        "program": str(CANDIDATE_EXE),
        "args": [
            "agent-m50-policy",
            "--weights", str(CANDIDATE_WEIGHTS),
            "--mode", "ismcts",
            "--simulations", str(sims),
        ],
    }
    opp_agent = {
        "program": str(OPPONENT_EXE),
        "args": OPPONENT_ARGS,
    }

    agents = [cand_agent, opp_agent] if candidate_seat == 0 else [opp_agent, cand_agent]
    cfg = {
        "game_id": game_id,
        "seed": seed,
        "agents": agents,
        "handshake_timeout_ms": 10000,
        "move_timeout_ms": 60000,
        "shutdown_grace_ms": 2000,
    }

    cfg_path = match_dir / "match-config.json"
    rep_path = match_dir / "arena-report.json"
    rpl_path = match_dir / "match-replay.json"

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    if rep_path.exists(): rep_path.unlink()
    if rpl_path.exists(): rpl_path.unlink()

    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            str(CANDIDATE_EXE),
            "run-match",
            "--config", str(cfg_path),
            "--report-out", str(rep_path),
            "--replay-out", str(rpl_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    wall_sec = time.perf_counter() - t0

    if proc.returncode != 0:
        raise RuntimeError(f"{game_id} failed: {proc.stderr[:400]}")

    with open(rep_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    outcome = report["outcome"]
    res = outcome["result"]
    winners = res["winners"]
    scores = res["scores"]

    cand_score = scores[candidate_seat]
    opp_score = scores[1 - candidate_seat]

    if winners == [candidate_seat]:
        won = 1.0
        score_bps = 10000
    elif len(winners) > 1 and candidate_seat in winners:
        won = 0.5
        score_bps = 5000
    else:
        won = 0.0
        score_bps = 0

    return {
        "game_id": game_id,
        "seed": seed,
        "candidate_seat": candidate_seat,
        "won": won,
        "score_bps": score_bps,
        "cand_score": cand_score,
        "opp_score": opp_score,
        "plies": outcome["completed_plies"],
        "wall_sec": wall_sec,
    }


def run_sim_series(sims: int, out_dir: Path, label: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n{'='*60}\nStarting Series: {label} (Simulations = {sims})\n{'='*60}")

    t_start = time.perf_counter()
    rows = []

    for idx, seed in enumerate(range(SEED_START, SEED_START + SEED_COUNT)):
        r0 = run_one_match(seed, 0, sims, out_dir, label)
        r1 = run_one_match(seed, 1, sims, out_dir, label)
        rows.extend([r0, r1])

        pair_won = (r0["won"] + r1["won"]) / 2.0
        if (idx + 1) % 16 == 0 or idx == SEED_COUNT - 1:
            tot = len(rows)
            w = sum(r["won"] == 1.0 for r in rows)
            t = sum(r["won"] == 0.5 for r in rows)
            l = sum(r["won"] == 0.0 for r in rows)
            pct = (w + 0.5 * t) / tot * 100.0
            print(f"[{idx+1:2d}/{SEED_COUNT}] Games: {tot:3d} | W-T-L: {w}-{t}-{l} ({pct:.1f}%) | Pair {seed}: {pair_won*100:.0f}%")

    total_sec = time.perf_counter() - t_start
    total_games = len(rows)

    wins = sum(r["won"] == 1.0 for r in rows)
    ties = sum(r["won"] == 0.5 for r in rows)
    losses = sum(r["won"] == 0.0 for r in rows)

    seat0_games = [r for r in rows if r["candidate_seat"] == 0]
    seat1_games = [r for r in rows if r["candidate_seat"] == 1]

    win_rate_seat0 = sum(r["won"] for r in seat0_games) / len(seat0_games)
    win_rate_seat1 = sum(r["won"] for r in seat1_games) / len(seat1_games)

    mean_cand_score = sum(r["cand_score"] for r in rows) / total_games
    mean_opp_score = sum(r["opp_score"] for r in rows) / total_games
    mean_plies = sum(r["plies"] for r in rows) / total_games

    blocks = []
    for seed in range(SEED_START, SEED_START + SEED_COUNT):
        b0 = next(r for r in rows if r["seed"] == seed and r["candidate_seat"] == 0)
        b1 = next(r for r in rows if r["seed"] == seed and r["candidate_seat"] == 1)
        blocks.append((b0["score_bps"] + b1["score_bps"]) / 2.0)

    center_bps = sum(blocks) / len(blocks)
    rng = random.Random(92552026)
    samples = sorted(
        sum(blocks[rng.randrange(len(blocks))] for _ in blocks) / len(blocks)
        for _ in range(10000)
    )
    ci_95_bps = [percentile(samples, 0.025), percentile(samples, 0.975)]

    summary = {
        "series": label,
        "simulations": sims,
        "total_games": total_games,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate_pct": (wins + 0.5 * ties) / total_games * 100.0,
        "center_bps": center_bps,
        "ci_95_bps": ci_95_bps,
        "win_rate_seat0_pct": win_rate_seat0 * 100.0,
        "win_rate_seat1_pct": win_rate_seat1 * 100.0,
        "mean_cand_score": mean_cand_score,
        "mean_opp_score": mean_opp_score,
        "mean_plies": mean_plies,
        "total_wall_seconds": total_sec,
    }

    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nFinal Results for {label}:")
    print(f"  W - T - L:   {wins} - {ties} - {losses} | Win Rate: {summary['win_rate_pct']:.2f}%")
    print(f"  95% CI:      [{ci_95_bps[0]:.1f}, {ci_95_bps[1]:.1f}] BPS")
    print(f"  Seat 0:      {summary['win_rate_seat0_pct']:.2f}% | Seat 1: {summary['win_rate_seat1_pct']:.2f}%")
    print(f"  Mean Score:  {mean_cand_score:.2f} vs {mean_opp_score:.2f}")
    print(f"  Total Time:  {total_sec:.2f}s ({total_sec / total_games:.3f}s / game)")
    return summary


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target in ("64", "all"):
        run_sim_series(
            sims=64,
            out_dir=ROOT / "local-artifacts" / "m50-ismcts64-eval-v025",
            label="m50-ismcts-sim64",
        )

    if target in ("128", "all"):
        run_sim_series(
            sims=128,
            out_dir=ROOT / "local-artifacts" / "m50-ismcts128-eval-v025",
            label="m50-ismcts-sim128",
        )


if __name__ == "__main__":
    main()
