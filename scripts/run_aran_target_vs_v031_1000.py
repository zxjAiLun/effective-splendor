#!/usr/bin/env python3
"""Run 1,000 games of aran (target-binding 72-dim) vs Heuristic v0.3.1.

500 paired-seed blocks (1,000 games with strict seat rotation):
  - Seat 0 / Seat 1 alternating
  - Candidate: aran-reserve-target-binding-v1 (56+16=72 dim semantic target binding)
  - Opponent:  Heuristic v0.3.1 (Splendor candidate v0.3.1)
Seeds: 9_330_000 .. 9_330_499
Output: local-artifacts/aran-target-binding-vs-v031-1000/
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_START_SEED = 9_330_000
DEFAULT_PAIRED_COUNT = 500  # 500 x 2 = 1,000 games

CAND_EXE = ROOT / "local-artifacts" / "aran-reserve-target-binding-v1" / "build" / "release" / "splendor.exe"
CAND_WEIGHTS = ROOT / "local-artifacts" / "aran-reserve-target-binding-v1" / "run" / "mortal_actor_critic_weights.json"
OPP_EXE = ROOT / "local-artifacts" / "s4-heuristic-v031-pilot" / "splendor-candidate.exe"
OPP_ARGS = ["agent-heuristic-v02", "--seed", "20260926"]
METRICS_EXE = ROOT / "local-artifacts" / "aran-reserve-target-binding-v1" / "provenance" / "s4_batch_metrics.exe"
DEFAULT_OUT_DIR = ROOT / "local-artifacts" / "aran-target-binding-vs-v031-1000"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def percentile(samples: list[float], fraction: float) -> float:
    pos = (len(samples) - 1) * fraction
    low = int(pos)
    return samples[low] * (1 - (pos - low)) + samples[min(low + 1, len(samples) - 1)] * (pos - low)


def run_single_match(args: tuple) -> dict:
    seed, cand_seat, out_dir = args
    match_dir = out_dir / "games" / f"seed-{seed}" / f"r{cand_seat}"
    match_dir.mkdir(parents=True, exist_ok=True)

    cfg_file = match_dir / "match-config.json"
    rep_file = match_dir / "arena-report.json"
    rpl_file = match_dir / "match-replay.json"

    # Fast resume check
    if rep_file.exists() and rpl_file.exists() and rep_file.stat().st_size > 100 and rpl_file.stat().st_size > 100:
        try:
            with open(rep_file, "r", encoding="utf-8") as f:
                rep = json.load(f)
            res = rep["outcome"]["result"]
            winners = res["winners"]
            scores = res["scores"]
            plies = rep["outcome"]["completed_plies"]
            cand_score = scores[cand_seat]
            opp_score = scores[1 - cand_seat]
            won = 1.0 if winners == [cand_seat] else 0.5 if len(winners) > 1 and cand_seat in winners else 0.0
            return {
                "seed": seed,
                "candidate_seat": cand_seat,
                "completed_plies": plies,
                "won": won,
                "cand_score": cand_score,
                "opp_score": opp_score,
                "rel_path": f"games/seed-{seed}/r{cand_seat}/match-replay.json",
                "resumed": True,
            }
        except Exception:
            pass

    cand_agent = {
        "program": str(CAND_EXE),
        "args": ["agent-m50-policy", "--weights", str(CAND_WEIGHTS), "--mode", "greedy"],
    }
    opp_agent = {
        "program": str(OPP_EXE),
        "args": OPP_ARGS,
    }

    agents = [cand_agent, opp_agent] if cand_seat == 0 else [opp_agent, cand_agent]
    match_config = {
        "game_id": f"aran-tb-v031-{seed}-r{cand_seat}",
        "seed": seed,
        "agents": agents,
        "handshake_timeout_ms": 10000,
        "move_timeout_ms": 60000,
        "shutdown_grace_ms": 2000,
    }

    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(match_config, f, indent=2)

    cmd = [
        str(CAND_EXE),
        "run-match",
        "--config",
        str(cfg_file),
        "--report-out",
        str(rep_file),
        "--replay-out",
        str(rpl_file),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"Match failed for seed {seed} r{cand_seat}: {proc.stderr[:400]}")

    with open(rep_file, "r", encoding="utf-8") as f:
        rep = json.load(f)

    res = rep["outcome"]["result"]
    winners = res["winners"]
    scores = res["scores"]
    plies = rep["outcome"]["completed_plies"]
    cand_score = scores[cand_seat]
    opp_score = scores[1 - cand_seat]
    won = 1.0 if winners == [cand_seat] else 0.5 if len(winners) > 1 and cand_seat in winners else 0.0

    return {
        "seed": seed,
        "candidate_seat": cand_seat,
        "completed_plies": plies,
        "won": won,
        "cand_score": cand_score,
        "opp_score": opp_score,
        "rel_path": f"games/seed-{seed}/r{cand_seat}/match-replay.json",
        "resumed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-seed", type=int, default=DEFAULT_START_SEED)
    parser.add_argument("--count", type=int, default=DEFAULT_PAIRED_COUNT)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Starting 1,000-Game Arena: Aran Target-Binding (72-dim) vs Heuristic v0.3.1 ===")
    print(f"Seeds: {args.start_seed} .. {args.start_seed + args.count - 1} ({args.count} paired seeds = {args.count * 2} games)")
    print(f"Candidate: {CAND_EXE}")
    print(f"Candidate Weights: {CAND_WEIGHTS}")
    print(f"Opponent: {OPP_EXE} ({OPP_ARGS})")
    print(f"Workers: {args.workers}")
    print(f"Output: {out_dir}")

    tasks = []
    for seed in range(args.start_seed, args.start_seed + args.count):
        for seat in (0, 1):
            tasks.append((seed, seat, out_dir))

    t0 = time.perf_counter()
    results = []
    completed = 0
    total = len(tasks)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(run_single_match, task): task for task in tasks}
        for future in concurrent.futures.as_completed(future_map):
            res = future.result()
            results.append(res)
            completed += 1
            if completed % 100 == 0 or completed == total:
                elapsed = time.perf_counter() - t0
                rate = completed / elapsed
                print(f"Progress: {completed}/{total} matches completed ({rate:.1f} games/s, elapsed: {elapsed:.1f}s)")

    # Sort results deterministically by seed, candidate_seat
    results.sort(key=lambda r: (r["seed"], r["candidate_seat"]))
    elapsed_total = time.perf_counter() - t0

    # Basic stats
    wins = sum(1 for r in results if r["won"] == 1.0)
    ties = sum(1 for r in results if r["won"] == 0.5)
    losses = sum(1 for r in results if r["won"] == 0.0)
    score_rate = (wins + 0.5 * ties) / total * 100.0
    win_rate = wins / total * 100.0

    # Seat stats
    p0_results = [r for r in results if r["candidate_seat"] == 0]
    p1_results = [r for r in results if r["candidate_seat"] == 1]
    p0_wins = sum(1 for r in p0_results if r["won"] == 1.0)
    p0_ties = sum(1 for r in p0_results if r["won"] == 0.5)
    p0_losses = sum(1 for r in p0_results if r["won"] == 0.0)
    p0_score_rate = (p0_wins + 0.5 * p0_ties) / len(p0_results) * 100.0
    p0_win_rate = p0_wins / len(p0_results) * 100.0

    p1_wins = sum(1 for r in p1_results if r["won"] == 1.0)
    p1_ties = sum(1 for r in p1_results if r["won"] == 0.5)
    p1_losses = sum(1 for r in p1_results if r["won"] == 0.0)
    p1_score_rate = (p1_wins + 0.5 * p1_ties) / len(p1_results) * 100.0
    p1_win_rate = p1_wins / len(p1_results) * 100.0

    # Paired Bootstrap CI (10,000 resamples)
    blocks = []
    for i in range(args.count):
        r0 = results[2 * i]
        r1 = results[2 * i + 1]
        assert r0["seed"] == r1["seed"]
        blocks.append((r0["won"] + r1["won"]) / 2.0)

    rng = random.Random(92552026)
    boot_means = []
    n_blocks = len(blocks)
    for _ in range(10000):
        sample = sum(rng.choice(blocks) for _ in range(n_blocks)) / n_blocks
        boot_means.append(sample * 100.0)
    boot_means.sort()
    ci_lo = percentile(boot_means, 0.025)
    ci_hi = percentile(boot_means, 0.975)

    mean_cand_score = sum(r["cand_score"] for r in results) / total
    mean_opp_score = sum(r["opp_score"] for r in results) / total
    mean_plies = sum(r["completed_plies"] for r in results) / total

    print(f"\n{'='*70}")
    print(f"Results for Aran Target-Binding (72-dim) vs Heuristic v0.3.1 (1,000 games):")
    print(f"  Record (W - T - L):       {wins} - {ties} - {losses}")
    print(f"  Score Rate:              {score_rate:.2f}% (Win Rate: {win_rate:.2f}%)")
    print(f"  95% Bootstrap CI:        [{ci_lo:.2f}%, {ci_hi:.2f}%]")
    print(f"  Seat 0 (First):          {p0_wins}-{p0_ties}-{p0_losses} | Score Rate: {p0_score_rate:.2f}% (Win: {p0_win_rate:.2f}%)")
    print(f"  Seat 1 (Second):         {p1_wins}-{p1_ties}-{p1_losses} | Score Rate: {p1_score_rate:.2f}% (Win: {p1_win_rate:.2f}%)")
    print(f"  Mean Score:              Aran {mean_cand_score:.2f} vs v0.3.1 {mean_opp_score:.2f} ({mean_cand_score - mean_opp_score:+.2f})")
    print(f"  Mean Completed Plies:    {mean_plies:.2f}")
    print(f"  Total Time:              {elapsed_total:.2f}s ({elapsed_total / total:.3f}s / game)")
    print(f"{'='*70}\n")

    # Generate Manifests for s4_batch_metrics
    manifest_all = {"rows": [{"replay_path": r["rel_path"]} for r in results]}
    manifest_r0 = {"rows": [{"replay_path": r["rel_path"]} for r in p0_results]}
    manifest_r1 = {"rows": [{"replay_path": r["rel_path"]} for r in p1_results]}

    write_json(out_dir / "manifest-all.json", manifest_all)
    write_json(out_dir / "manifest-r0.json", manifest_r0)
    write_json(out_dir / "manifest-r1.json", manifest_r1)

    print("Running s4_batch_metrics on all / r0 / r1...")
    metrics_all_path = out_dir / "metrics-all.json"
    metrics_r0_path = out_dir / "metrics-r0.json"
    metrics_r1_path = out_dir / "metrics-r1.json"

    for mf, target in [
        (out_dir / "manifest-all.json", metrics_all_path),
        (out_dir / "manifest-r0.json", metrics_r0_path),
        (out_dir / "manifest-r1.json", metrics_r1_path),
    ]:
        cmd = [str(METRICS_EXE), str(mf), str(target)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            print(f"Warning: metrics failed for {mf}: {p.stderr}")

    raw = {}
    if metrics_all_path.exists() and metrics_r0_path.exists() and metrics_r1_path.exists():
        raw["all"] = json.loads(metrics_all_path.read_text(encoding="utf-8"))
        raw["r0"] = json.loads(metrics_r0_path.read_text(encoding="utf-8"))
        raw["r1"] = json.loads(metrics_r1_path.read_text(encoding="utf-8"))

        def player(first: dict, second: dict) -> dict:
            n0, n1 = raw["r0"]["total_games"], raw["r1"]["total_games"]
            tot = n0 + n1
            merged = {key: first[key] + second[key] for key in ("wins", "ties", "losses", "games_with_nobles")}
            for key in ("mean_prestige", "mean_nobles", "mean_permanent_bonuses", "mean_reserves_acquired",
                        "mean_reserves_bought", "mean_reserves_stranded"):
                merged[key] = (first[key] * n0 + second[key] * n1) / tot
            for key in ("mean_cards_by_vp", "mean_bonuses_by_color"):
                merged[key] = {name: (first[key].get(name, 0) * n0 + second[key].get(name, 0) * n1) / tot
                               for name in sorted(set(first[key]) | set(second[key]))}
            counts = {name: first["action_distribution"].get(name, 0) + second["action_distribution"].get(name, 0)
                      for name in sorted(set(first["action_distribution"]) | set(second["action_distribution"]))}
            merged["action_distribution"] = counts
            total_act = sum(counts.values())
            merged["action_percentages"] = {name: (value / total_act * 100 if total_act else 0) for name, value in counts.items()}
            merged["total_games"] = tot
            merged["score_rate"] = (merged["wins"] + 0.5 * merged["ties"]) / tot
            merged["pure_win_rate"] = merged["wins"] / tot
            prestige = merged["mean_prestige"] * tot
            merged["vp_per_turn"] = prestige / (raw["r0"]["mean_turns"] * n0 + raw["r1"]["mean_turns"] * n1)
            merged["vp_per_ply"] = prestige / (raw["r0"]["total_plies"] + raw["r1"]["total_plies"])
            acquired = merged["mean_reserves_acquired"]
            merged["reserve_redemption_rate"] = (merged["mean_reserves_bought"] / acquired * 100) if acquired else None
            return merged

        cand_player = player(raw["r0"]["seat_p0_first"], raw["r1"]["seat_p1_second"])
        opp_player = player(raw["r0"]["seat_p1_second"], raw["r1"]["seat_p0_first"])
        unified_summary = {
            "format": raw["all"]["format"],
            "total_games": total,
            "seed_start": args.start_seed,
            "seed_count": args.count,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "score_rate_percent": score_rate,
            "win_rate_percent": win_rate,
            "ci95_percent": [ci_lo, ci_hi],
            "p0_score_rate_percent": p0_score_rate,
            "p1_score_rate_percent": p1_score_rate,
            "candidate": cand_player,
            "opponent": opp_player,
            "unified_batch_metrics": raw["all"],
            "total_wall_seconds": elapsed_total,
        }
        write_json(out_dir / "unified-summary.json", unified_summary)
        print(f"Saved unified-summary.json")

    summary = {
        "candidate": "aran-reserve-target-binding-v1 (72-dim)",
        "opponent": "heuristic-v031",
        "total_games": total,
        "seed_start": args.start_seed,
        "seed_count": args.count,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "score_rate_pct": score_rate,
        "win_rate_pct": win_rate,
        "ci95_pct": [ci_lo, ci_hi],
        "p0": {"wins": p0_wins, "ties": p0_ties, "losses": p0_losses, "score_rate_pct": p0_score_rate, "win_rate_pct": p0_win_rate},
        "p1": {"wins": p1_wins, "ties": p1_ties, "losses": p1_losses, "score_rate_pct": p1_score_rate, "win_rate_pct": p1_win_rate},
        "mean_cand_score": mean_cand_score,
        "mean_opp_score": mean_opp_score,
        "mean_plies": mean_plies,
        "total_wall_seconds": elapsed_total,
    }
    write_json(out_dir / "summary.json", summary)
    print(f"Saved summary.json")


if __name__ == "__main__":
    main()
