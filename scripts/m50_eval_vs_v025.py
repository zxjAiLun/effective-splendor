#!/usr/bin/env python3
"""M50: Head-to-Head Arena Evaluation against v0.2.5 Heuristic.

Runs 64 paired-seed blocks (128 games) with strict seat rotation:
  - Candidate: M50 Policy Network (splendor-cli-m50-policy 0.1.0)
  - Opponent: Frozen v0.2.5 Heuristic (splendor-cli-heuristic-v02 0.2.5)
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
CANDIDATE_WEIGHTS = ROOT / "local-artifacts" / "m50-replay-run" / "m50_policy_weights.json"

OPPONENT_EXE = ROOT / "local-artifacts" / "s4-heuristic-v025-pilot" / "splendor-candidate.exe"
OPPONENT_ARGS = ["agent-heuristic-v02", "--seed", "20260926"]

OUT_DIR = ROOT / "local-artifacts" / "m50-eval-v025"
SEED_START = 9_260_000
SEED_COUNT = 64


def percentile(samples: list[float], fraction: float) -> float:
    pos = (len(samples) - 1) * fraction
    low = int(pos)
    return samples[low] * (1 - (pos - low)) + samples[min(low + 1, len(samples) - 1)] * (pos - low)


def run_one_match(seed: int, rotation: int, candidate_seat: int) -> dict:
    match_dir = OUT_DIR / f"seed-{seed}" / f"r{candidate_seat}"
    match_dir.mkdir(parents=True, exist_ok=True)
    game_id = f"m50-v025-{seed}-r{candidate_seat}"

    cand_agent = {
        "program": str(CANDIDATE_EXE),
        "args": ["agent-m50-policy", "--weights", str(CANDIDATE_WEIGHTS)],
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

    # Clean existing
    if rep_path.exists():
        rep_path.unlink()
    if rpl_path.exists():
        rpl_path.unlink()

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
        timeout=120,
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


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"M50 vs v0.2.5 Evaluation Series ({SEED_COUNT} paired blocks = {SEED_COUNT * 2} games)")
    print(f"Candidate: M50 Policy Network ({CANDIDATE_WEIGHTS})")
    print(f"Opponent:  v0.2.5 Heuristic ({OPPONENT_EXE})")

    t_start = time.perf_counter()
    rows = []

    for idx, seed in enumerate(range(SEED_START, SEED_START + SEED_COUNT)):
        # Both rotations
        r0 = run_one_match(seed, 0, candidate_seat=0)
        r1 = run_one_match(seed, 1, candidate_seat=1)
        rows.extend([r0, r1])

        pair_won = (r0["won"] + r1["won"]) / 2.0
        if (idx + 1) % 8 == 0 or idx == SEED_COUNT - 1:
            tot_games = len(rows)
            tot_wins = sum(r["won"] == 1.0 for r in rows)
            tot_ties = sum(r["won"] == 0.5 for r in rows)
            tot_losses = sum(r["won"] == 0.0 for r in rows)
            win_pct = (tot_wins + 0.5 * tot_ties) / tot_games * 100.0
            print(
                f"[{idx+1:2d}/{SEED_COUNT}] Games: {tot_games:3d} | "
                f"W-T-L: {tot_wins}-{tot_ties}-{tot_losses} ({win_pct:.1f}%) | "
                f"Last pair seed {seed}: {pair_won*100:.0f}%"
            )

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

    # Paired-block bootstrap CI
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
        "evaluation": "M50 Policy Network vs v0.2.5 Heuristic",
        "total_games": total_games,
        "paired_blocks": SEED_COUNT,
        "seed_range": [SEED_START, SEED_START + SEED_COUNT - 1],
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

    sum_path = OUT_DIR / "summary.json"
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("FINAL EVALUATION RESULTS:")
    print(f"  Matches:     {total_games} ({SEED_COUNT} paired blocks)")
    print(f"  W - T - L:   {wins} - {ties} - {losses}")
    print(f"  Win Rate:    {summary['win_rate_pct']:.2f}% (Center BPS: {center_bps:.1f})")
    print(f"  95% CI:      [{ci_95_bps[0]:.1f}, {ci_95_bps[1]:.1f}] BPS")
    print(f"  Seat 0 Win:  {summary['win_rate_seat0_pct']:.2f}%")
    print(f"  Seat 1 Win:  {summary['win_rate_seat1_pct']:.2f}%")
    print(f"  Mean Score:  M50 {mean_cand_score:.2f} vs v0.2.5 {mean_opp_score:.2f}")
    print(f"  Mean Plies:  {mean_plies:.1f}")
    print(f"  Total Time:  {total_sec:.2f}s ({total_sec / total_games:.3f}s / game)")
    print("=" * 60)


if __name__ == "__main__":
    main()
