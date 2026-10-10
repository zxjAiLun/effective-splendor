#!/usr/bin/env python3
"""Prospective battle evaluation: Heuristic v0.3.0 vs aran-v0.2 (Mortal SE-ResNet Dueling).

128 paired-seed blocks (256 matches) over seeds 9_316_000 .. 9_316_127.
Strict execution with run-match, verify-replay, and batch metrics analysis.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "local-artifacts/s4-v030-vs-aran-v02"
CANDIDATE_EXE = ROOT / "local-artifacts/s4-heuristic-v030-pilot/splendor-candidate.exe"
REFEREE_EXE = ROOT / "local-artifacts/s4-heuristic-v029-pilot/splendor-candidate.exe"
ARAN_WEIGHTS = ROOT / "local-artifacts/aran-v02/aran_v02_weights.json"

SEED_START = 9_316_000
SEED_COUNT = 128
ROTATIONS = [0, 1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def validate_winners(winners: list[int], seat: int) -> int:
    return 5_000 if winners == [0, 1] else 10_000 if winners == [seat] else 0


def execute_game(seed: int, seat: int) -> dict:
    directory = OUT_DIR / "games" / f"seed-{seed}" / f"r{seat}"
    directory.mkdir(parents=True, exist_ok=True)
    game_id = f"s4v030-aranv02-{seed}-r{seat}"

    cand_spec = {
        "program": str(CANDIDATE_EXE),
        "args": ["agent-heuristic-v02", "--seed", "20260926"],
        "agent_name": "splendor-cli-heuristic-v02",
        "agent_version": "0.2.9",
    }
    aran_spec = {
        "program": str(CANDIDATE_EXE),
        "args": ["agent-m50-policy", "--weights", str(ARAN_WEIGHTS), "--mode", "greedy"],
        "agent_name": "splendor-cli-m50-policy",
        "agent_version": "0.3.0",
    }

    commands = [{"program": cand_spec["program"], "args": cand_spec["args"]},
                {"program": aran_spec["program"], "args": aran_spec["args"]}]
    if seat == 1:
        commands.reverse()

    match_config = {
        "game_id": game_id,
        "seed": seed,
        "agents": commands,
        "handshake_timeout_ms": 15_000,
        "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
    }

    cfg_path = directory / "match-config.json"
    rep_path = directory / "arena-report.json"
    rpl_path = directory / "match-replay.json"
    write_new(cfg_path, match_config)

    started = time.monotonic()
    proc = subprocess.run(
        [str(REFEREE_EXE), "run-match", "--config", str(cfg_path), "--report-out", str(rep_path), "--replay-out", str(rpl_path)],
        capture_output=True, text=True, timeout=300
    )
    wall = time.monotonic() - started
    write_new(directory / "process.json", {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    assert proc.returncode == 0 and not proc.stderr.strip(), f"{game_id}: run-match failed {proc.stderr[:400]}"

    report = json.loads(rep_path.read_text(encoding="utf-8"))
    replay = json.loads(rpl_path.read_text(encoding="utf-8"))

    ver = subprocess.run([str(REFEREE_EXE), "verify-replay", "--input", str(rpl_path)], capture_output=True, text=True, timeout=30)
    write_new(directory / "verification.json", {"exit_code": ver.returncode, "stdout": ver.stdout, "stderr": ver.stderr})
    assert ver.returncode == 0 and not ver.stderr.strip(), f"{game_id}: verify-replay failed"

    outcome = report["outcome"]
    winners = outcome["result"]["winners"]

    return {
        "game_id": game_id,
        "opponent": "aran-v02",
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


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = [(s, rot) for s in range(SEED_START, SEED_START + SEED_COUNT) for rot in ROTATIONS]
    total = len(tasks)
    print(f"Starting battle: v0.3.0 vs aran-v0.2 ({total} matches, 10 workers)...", flush=True)

    t0 = time.time()
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(execute_game, s, rot): (s, rot) for s, rot in tasks}
        completed = 0
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            rows.append(res)
            completed += 1
            if completed % 32 == 0 or completed == total:
                elapsed = time.time() - t0
                print(f"  [{completed:3d}/{total}] done ({completed/elapsed:.1f} games/s, {elapsed:.1f}s)", flush=True)

    rows.sort(key=lambda r: (r["seed"], r["rotation"]))

    manifest = {
        "format": "effective-splendor-s4-v030-vs-aran-v02-manifest",
        "version": 1,
        "candidate_binary_sha256": sha256(CANDIDATE_EXE),
        "aran_weights_sha256": sha256(ARAN_WEIGHTS),
        "rows": rows,
    }
    manifest_path = OUT_DIR / "manifest.json"
    write_new(manifest_path, manifest)

    # Bootstrap CI
    lookup = {(r["seed"], r["rotation"]): r for r in rows}
    blocks = [
        (lookup[(s, 0)]["score_bps"] + lookup[(s, 1)]["score_bps"]) / 2.0
        for s in range(SEED_START, SEED_START + SEED_COUNT)
    ]
    rng = random.Random(93162026)
    samples = sorted(
        sum(blocks[rng.randrange(len(blocks))] for _ in blocks) / len(blocks)
        for _ in range(10_000)
    )
    ci = [round(percentile(samples, 0.025), 2), round(percentile(samples, 0.975), 2)]
    wins = sum(r["score_bps"] == 10_000 for r in rows)
    ties = sum(r["score_bps"] == 5_000 for r in rows)
    losses = sum(r["score_bps"] == 0 for r in rows)

    s0_matches = [r for r in rows if r["candidate_seat"] == 0]
    s1_matches = [r for r in rows if r["candidate_seat"] == 1]
    s0_wins = sum(r["score_bps"] == 10_000 for r in s0_matches)
    s0_ties = sum(r["score_bps"] == 5_000 for r in s0_matches)
    s1_wins = sum(r["score_bps"] == 10_000 for r in s1_matches)
    s1_ties = sum(r["score_bps"] == 5_000 for r in s1_matches)

    summary = {
        "opponent": "aran-v02",
        "matches": len(rows),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate_percent": round((wins + 0.5 * ties) / len(rows) * 100.0, 2),
        "center_bps": round(sum(blocks) / len(blocks), 2),
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
        "mean_plies": round(sum(r["completed_plies"] for r in rows) / len(rows), 2),
        "total_wall_seconds": round(time.time() - t0, 3),
    }
    write_new(OUT_DIR / "summary.json", summary)
    print("\nBattle completed!", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
