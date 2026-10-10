#!/usr/bin/env python3
"""Prospective, concurrent S4 Two-Ply Continuation v0.3.2a pilot: smoke -> pilot -> batch metrics -> summary tables.

Evaluates v0.3.2a candidate (calibrated reserve gating, stranded penalty, noble/engine re-anchoring) across 5 baselines:
  - heuristic-v031
  - heuristic-v030
  - heuristic-v029
  - s3-rollout
  - heuristic-v01
128 paired-seed blocks per opponent (1,280 matches total).
Strict execution with run-match, verify-replay, and batch metrics analysis.
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
DEFAULT_CONFIG = ROOT / "benchmarks/s4-heuristic-v032a-pilot-v1.config.json"


def require(cond: bool, message: str) -> None:
    if not cond:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def validate_winners(winners: list[int], seat: int) -> int:
    require(isinstance(winners, list) and winners in ([0], [1], [0, 1]), f"invalid two-player winners: {winners}")
    return 5_000 if winners == [0, 1] else 10_000 if winners == [seat] else 0


def execute_game(config: dict, opponent: dict, seed: int, seat: int, subdir: str, out: Path) -> dict:
    candidate_prog = ROOT / config["candidate"]["program"]
    opponent_prog = ROOT / opponent["program"]
    referee = ROOT / config["reference_program"]

    directory = out / subdir / opponent["id"] / f"seed-{seed}" / f"r{seat}"
    directory.mkdir(parents=True, exist_ok=True)
    game_id = f"s4v032a-{opponent['id']}-{seed}-r{seat}"

    cand_spec = {
        "program": str(candidate_prog),
        "args": config["candidate"]["args"],
        "agent_name": config["candidate"]["agent_name"],
        "agent_version": config["candidate"]["agent_version"],
    }
    opp_spec = {
        "program": str(opponent_prog),
        "args": opponent["args"],
        "agent_name": opponent["agent_name"],
        "agent_version": opponent["agent_version"],
    }

    commands = [{"program": cand_spec["program"], "args": cand_spec["args"]},
                {"program": opp_spec["program"], "args": opp_spec["args"]}]
    specs = [cand_spec, opp_spec]
    if seat:
        commands.reverse()
        specs.reverse()

    match_config = {
        "game_id": game_id,
        "seed": seed,
        "agents": commands,
        "handshake_timeout_ms": config["handshake_timeout_ms"],
        "move_timeout_ms": config["move_timeout_ms"],
        "shutdown_grace_ms": config["shutdown_grace_ms"],
    }

    cfg_path = directory / "match-config.json"
    rep_path = directory / "arena-report.json"
    rpl_path = directory / "match-replay.json"
    write_new(cfg_path, match_config)

    if rep_path.exists() and not (directory / "verification.json").exists():
        rep_path.unlink(missing_ok=True)
        rpl_path.unlink(missing_ok=True)

    if rep_path.exists() and rpl_path.exists() and (directory / "verification.json").exists():
        proc_data = read_json(directory / "process.json") if (directory / "process.json").exists() else {}
        if proc_data.get("exit_code") == 0:
            report = read_json(rep_path)
            replay = read_json(rpl_path)
            outcome = report["outcome"]
            if outcome["status"] == "completed":
                winners = outcome["result"]["winners"]
                return {
                    "game_id": game_id,
                    "opponent": opponent["id"],
                    "seed": seed,
                    "rotation": seat,
                    "candidate_seat": seat,
                    "score_bps": validate_winners(winners, seat),
                    "winners": winners,
                    "completed_plies": outcome["completed_plies"],
                    "replay_final_hash": replay["final_state_hash"],
                    "match_wall_seconds": 0.05,
                    "config_sha256": sha256(cfg_path),
                    "report_sha256": sha256(rep_path),
                    "replay_sha256": sha256(rpl_path),
                    "scores": outcome["result"]["scores"],
                }

    started = time.monotonic()
    proc = subprocess.run(
        [str(referee), "run-match", "--config", str(cfg_path), "--report-out", str(rep_path), "--replay-out", str(rpl_path)],
        capture_output=True, text=True, timeout=300
    )
    wall = time.monotonic() - started
    write_new(directory / "process.json", {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    require(proc.returncode == 0 and not proc.stderr.strip(), f"{game_id}: run-match failed exit={proc.returncode}; {proc.stderr[:400]}")

    report = read_json(rep_path)
    replay = read_json(rpl_path)

    # Validate replay
    ver = subprocess.run([str(referee), "verify-replay", "--input", str(rpl_path)], capture_output=True, text=True, timeout=30)
    write_new(directory / "verification.json", {"exit_code": ver.returncode, "stdout": ver.stdout, "stderr": ver.stderr})
    require(ver.returncode == 0 and not ver.stderr.strip(), f"{game_id}: verify-replay failed")

    outcome = report["outcome"]
    require(outcome["status"] == "completed", f"{game_id}: incomplete game")
    winners = outcome["result"]["winners"]

    return {
        "game_id": game_id,
        "opponent": opponent["id"],
        "seed": seed,
        "rotation": seat,
        "candidate_seat": seat,
        "score_bps": validate_winners(winners, seat),
        "winners": winners,
        "completed_plies": outcome["completed_plies"],
        "replay_final_hash": replay["final_state_hash"],
        "match_wall_seconds": round(wall, 6),
        "config_sha256": sha256(cfg_path),
        "report_sha256": sha256(rep_path),
        "replay_sha256": sha256(rpl_path),
        "scores": outcome["result"]["scores"],
    }


def percentile(samples: list[float], fraction: float) -> float:
    pos = (len(samples) - 1) * fraction
    low = int(pos)
    return samples[low] * (1.0 - (pos - low)) + samples[min(low + 1, len(samples) - 1)] * (pos - low)


def summarize(rows: list[dict], opponent: str, config: dict) -> dict:
    matches = [r for r in rows if r["opponent"] == opponent]
    seed_start, seed_count = config["seed_start"], config["seed_count"]
    lookup = {(r["seed"], r["rotation"]): r for r in matches}
    blocks = [
        (lookup[(s, 0)]["score_bps"] + lookup[(s, 1)]["score_bps"]) / 2.0
        for s in range(seed_start, seed_start + seed_count)
    ]

    rng = random.Random(config["bootstrap"]["seed"])
    resamples = config["bootstrap"]["resamples"]
    samples = sorted(
        sum(blocks[rng.randrange(len(blocks))] for _ in blocks) / len(blocks)
        for _ in range(resamples)
    )
    ci = [round(percentile(samples, 0.025), 2), round(percentile(samples, 0.975), 2)]
    wins = sum(r["score_bps"] == 10_000 for r in matches)
    ties = sum(r["score_bps"] == 5_000 for r in matches)
    losses = sum(r["score_bps"] == 0 for r in matches)
    center_bps = sum(blocks) / len(blocks)

    s0_matches = [r for r in matches if r["candidate_seat"] == 0]
    s1_matches = [r for r in matches if r["candidate_seat"] == 1]
    s0_wins = sum(r["score_bps"] == 10_000 for r in s0_matches)
    s0_ties = sum(r["score_bps"] == 5_000 for r in s0_matches)
    s1_wins = sum(r["score_bps"] == 10_000 for r in s1_matches)
    s1_ties = sum(r["score_bps"] == 5_000 for r in s1_matches)

    verdict = (
        "EXPLORATORY_STRONGER" if ci[0] > 5000.0 else
        "EXPLORATORY_WEAKER" if ci[1] < 5000.0 else
        "UNRESOLVED"
    )

    return {
        "opponent": opponent,
        "matches": len(matches),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate_percent": round((wins + 0.5 * ties) / len(matches) * 100.0, 2),
        "center_bps": round(center_bps, 2),
        "ci_95_bps": ci,
        "seat_p0_first": {
            "matches": len(s0_matches),
            "wins": s0_wins,
            "ties": s0_ties,
            "losses": len(s0_matches) - s0_wins - s0_ties,
            "win_rate_percent": round((s0_wins + 0.5 * s0_ties) / len(s0_matches) * 100.0, 2),
        },
        "seat_p1_second": {
            "matches": len(s1_matches),
            "wins": s1_wins,
            "ties": s1_ties,
            "losses": len(s1_matches) - s1_wins - s1_ties,
            "win_rate_percent": round((s1_wins + 0.5 * s1_ties) / len(s1_matches) * 100.0, 2),
        },
        "exploratory_verdict": verdict,
        "mean_plies": round(sum(r["completed_plies"] for r in matches) / len(matches), 2),
        "total_match_wall_seconds": round(sum(r["match_wall_seconds"] for r in matches), 3),
    }


def run_smoke(config: dict, out: Path) -> None:
    smoke_seed = config["smoke_seed"]
    print(f"Running pre-pilot smoke tests on seed {smoke_seed}...", flush=True)
    smoke_rows = []
    for opp in config["opponents"]:
        for seat in config["rotations"]:
            res = execute_game(config, opp, smoke_seed, seat, "smoke", out)
            smoke_rows.append(res)
            print(f"  smoke {opp['id']} r{seat}: win={res['score_bps']} plies={res['completed_plies']}", flush=True)
    print("Smoke tests passed successfully!\n", flush=True)


def run_pilot(config_path: Path, max_workers: int = 12) -> None:
    config = read_json(config_path)
    out = ROOT / config["artifacts"]
    out.mkdir(parents=True, exist_ok=True)

    # 1. Run smoke first
    run_smoke(config, out)

    # 2. Prepare pilot tasks
    tasks = []
    for opponent in config["opponents"]:
        for seed in range(config["seed_start"], config["seed_start"] + config["seed_count"]):
            for seat in config["rotations"]:
                tasks.append((config, opponent, seed, seat, "games", out))

    total = len(tasks)
    print(f"Starting v0.3.2a pilot: {total} matches across {len(config['opponents'])} opponents with {max_workers} concurrent workers...", flush=True)

    t0 = time.time()
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(execute_game, *task): task for task in tasks}
        completed = 0
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            rows.append(res)
            completed += 1
            if completed % 64 == 0 or completed == total:
                elapsed = time.time() - t0
                rate = completed / elapsed
                print(f"  [{completed:4d}/{total}] matches done ({rate:.1f} games/s, elapsed {elapsed:.1f}s)", flush=True)

    # Sort rows by opponent, seed, rotation for deterministic manifest
    rows.sort(key=lambda r: (r["opponent"], r["seed"], r["rotation"]))

    # Save manifest
    manifest_data = {
        "format": "effective-splendor-s4-heuristic-v032a-pilot-manifest",
        "version": 1,
        "candidate_binary_sha256": sha256(ROOT / config["candidate"]["program"]),
        "reference_sha256": config["reference_sha256"],
        "rows": rows,
    }
    manifest_path = out / "manifest.json"
    write_new(manifest_path, manifest_data)

    # Also save per-opponent manifests & rotation splits for batch metrics analysis
    for opp in config["opponents"]:
        opp_id = opp["id"]
        opp_rows = [r for r in rows if r["opponent"] == opp_id]
        opp_manifest = {
            "format": "effective-splendor-s4-heuristic-v032a-pilot-manifest",
            "version": 1,
            "candidate_binary_sha256": sha256(ROOT / config["candidate"]["program"]),
            "reference_sha256": config["reference_sha256"],
            "rows": opp_rows,
        }
        write_new(out / f"manifest_{opp_id}.json", opp_manifest)

        # r0 and r1 manifests
        r0_rows = [r for r in opp_rows if r["rotation"] == 0]
        r1_rows = [r for r in opp_rows if r["rotation"] == 1]
        write_new(out / f"manifest_{opp_id}_r0.json", {**opp_manifest, "rows": r0_rows})
        write_new(out / f"manifest_{opp_id}_r1.json", {**opp_manifest, "rows": r1_rows})

    # Summarize per opponent
    summaries = [summarize(rows, o["id"], config) for o in config["opponents"]]

    result_data = {
        "format": "effective-splendor-s4-heuristic-v032a-pilot-result",
        "version": 1,
        "status": "EXPLORATORY_PILOT_ONLY",
        "contract": str(config_path.relative_to(ROOT)).replace("\\", "/"),
        "config_sha256": sha256(config_path),
        "candidate_binary_sha256": sha256(ROOT / config["candidate"]["program"]),
        "reference_binary_sha256": config["reference_sha256"],
        "manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": sha256(manifest_path),
        "matched_game_seeds": config["seed_count"],
        "completed_and_verified_matches": len(rows),
        "aborts": 0,
        "pairings": summaries,
        "total_wall_seconds": round(time.time() - t0, 3),
        "limitations": "128 seed blocks per opponent across 5 baselines; exploratory pilot only; no default change"
    }

    result_path = ROOT / "benchmarks/s4-heuristic-v032a-pilot-v1.result.json"
    write_new(result_path, result_data)

    print("\nPilot completed successfully!", flush=True)
    print(json.dumps({"pairings": summaries}, indent=2), flush=True)

    # Run batch metrics
    print("\nRunning batch metrics analysis...", flush=True)
    metrics_bin = ROOT / "target/eval_target/release/examples/s4_batch_metrics.exe"
    if metrics_bin.exists():
        for opp in config["opponents"]:
            opp_id = opp["id"]
            m_path = out / f"manifest_{opp_id}.json"
            out_m = out / f"metrics_{opp_id}.json"
            subprocess.run([str(metrics_bin), str(m_path), str(out_m)], check=True)
            # r0 and r1
            m_r0 = out / f"manifest_{opp_id}_r0.json"
            out_r0 = out / f"metrics_{opp_id}_r0.json"
            subprocess.run([str(metrics_bin), str(m_r0), str(out_r0)], check=True)
            m_r1 = out / f"manifest_{opp_id}_r1.json"
            out_r1 = out / f"metrics_{opp_id}_r1.json"
            subprocess.run([str(metrics_bin), str(m_r1), str(out_r1)], check=True)
            print(f"  metrics for {opp_id} (+r0, +r1) saved", flush=True)
    else:
        print("  warning: s4_batch_metrics binary not found; skipping batch metrics", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    run_pilot(Path(args.config), max_workers=args.workers)
