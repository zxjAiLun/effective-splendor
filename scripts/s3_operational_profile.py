#!/usr/bin/env python3
"""S3 Operational Profile: executes 128 live matches between S3-profile and Heuristic-profile.

Contract: docs/s3-operational-profile.md @ 48e7553
- Seeds: 5_800_384..5_800_447 (64 blocks x 2 rotations = 128 matches)
- Pairing: S3 (agent-s3-rollout-profile) vs Heuristic (agent-heuristic-profile --seed 20260812)
- Telemetry: per-match JSONL sidecars for both agents
- Verification: 100% completed matches, 0 timeouts/errors, verify-replay passes.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
OUT_ROOT = REPO / "local-artifacts/s3-operational-profile"

FROZEN_SEEDS = list(range(5_800_384, 5_800_448))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_one_match(block_idx: int, seed: int, rotation: int, work_dir: Path) -> dict:
    game_id = f"s3op-b{block_idx:02d}-s{seed}-r{rotation}"
    mdir = work_dir / f"block-{block_idx:02d}-seed-{seed}" / f"r{rotation}"
    mdir.mkdir(parents=True, exist_ok=True)

    s3_stats = mdir / "s3-stats.jsonl"
    heur_stats = mdir / "heur-stats.jsonl"
    cfg_path = mdir / "match-config.json"
    rep_path = mdir / "arena-report.json"
    rpl_path = mdir / "match-replay.json"

    s3_agent = {
        "program": str(SPLN),
        "args": ["agent-s3-rollout-profile", "--stats-out", str(s3_stats)],
    }
    heur_agent = {
        "program": str(SPLN),
        "args": ["agent-heuristic-profile", "--stats-out", str(heur_stats), "--seed", "20260812"],
    }

    agents = [s3_agent, heur_agent] if rotation == 0 else [heur_agent, s3_agent]
    s3_seat = 0 if rotation == 0 else 1
    heur_seat = 1 if rotation == 0 else 0

    cfg = {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
        "agents": agents,
    }
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # If already completed validly, reuse
    if rep_path.is_file() and rpl_path.is_file() and s3_stats.is_file() and heur_stats.is_file():
        try:
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            if rep.get("outcome", {}).get("status") == "completed":
                return {
                    "game_id": game_id,
                    "block_idx": block_idx,
                    "seed": seed,
                    "rotation": rotation,
                    "s3_seat": s3_seat,
                    "heur_seat": heur_seat,
                    "completed_plies": rep["outcome"]["completed_plies"],
                    "replay_final_hash": rep["outcome"]["replay_final_hash"],
                    "s3_stats_path": str(s3_stats),
                    "heur_stats_path": str(heur_stats),
                    "wall_s": 0.0,
                }
        except Exception:
            pass

    # Clear stats files if retrying to avoid append duplicates
    if s3_stats.exists():
        s3_stats.unlink()
    if heur_stats.exists():
        heur_stats.unlink()

    t0 = time.perf_counter()
    r = subprocess.run(
        [
            str(SPLN), "run-match",
            "--config", str(cfg_path),
            "--report-out", str(rep_path),
            "--replay-out", str(rpl_path),
        ],
        capture_output=True,
        text=True,
    )
    wall = time.perf_counter() - t0

    if r.returncode != 0:
        raise RuntimeError(f"{game_id}: exit {r.returncode}: stdout={r.stdout[:300]} stderr={r.stderr[:300]}")

    v = subprocess.run(
        [str(SPLN), "verify-replay", "--input", str(rpl_path)],
        capture_output=True,
        text=True,
    )
    if v.returncode != 0:
        raise RuntimeError(f"{game_id}: verify-replay failed: {v.stderr[:300]}")

    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    outcome = rep["outcome"]
    if outcome["status"] != "completed":
        raise RuntimeError(f"{game_id}: outcome not completed: {outcome}")

    return {
        "game_id": game_id,
        "block_idx": block_idx,
        "seed": seed,
        "rotation": rotation,
        "s3_seat": s3_seat,
        "heur_seat": heur_seat,
        "completed_plies": outcome["completed_plies"],
        "replay_final_hash": outcome["replay_final_hash"],
        "s3_stats_path": str(s3_stats),
        "heur_stats_path": str(heur_stats),
        "wall_s": round(wall, 3),
    }


def main() -> None:
    workers = int(os.environ.get("S3OP_WORKERS", "4"))
    print(f"S3 Operational Profile: 64 blocks x 2 rotations = {len(FROZEN_SEEDS) * 2} live matches")

    # Check seed disjointness
    sys.path.insert(0, str(REPO / "scripts"))
    import s0_seed_registry as reg
    reg.CHECK_SEGMENT = range(5_800_384, 5_800_448)
    if reg.check() != 0:
        print("FAIL: seed segment overlap in registry")
        sys.exit(1)

    t_start = time.time()
    work = OUT_ROOT / "matches"
    work.mkdir(parents=True, exist_ok=True)

    tasks = [(b, s, r) for b, s in enumerate(FROZEN_SEEDS) for r in (0, 1)]
    matches = {}

    print(f"Launching {len(tasks)} matches across {workers} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(run_one_match, b, s, r, work): (b, s, r)
            for b, s, r in tasks
        }
        done_count = 0
        for fut in concurrent.futures.as_completed(futs):
            res = fut.result()
            matches[(res["block_idx"], res["rotation"])] = res
            done_count += 1
            if done_count % 16 == 0 or done_count == len(tasks):
                elapsed = time.time() - t_start
                print(f"  Completed {done_count}/{len(tasks)} matches ({elapsed:.1f}s wall)...", flush=True)

    wall_total = time.time() - t_start
    print(f"\nAll {len(matches)} matches completed successfully in {wall_total:.1f}s wall!")

    # Save match index manifest
    manifest_path = OUT_ROOT / "matches-manifest.json"
    manifest = {
        "seeds": FROZEN_SEEDS,
        "total_matches": len(matches),
        "wall_total_s": round(wall_total, 2),
        "splendor_exe_sha256": file_sha256(SPLN),
        "matches": [matches[(b, r)] for b in range(len(FROZEN_SEEDS)) for r in (0, 1)],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
