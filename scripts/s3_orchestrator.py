#!/usr/bin/env python3
"""S3 Stage-B confirmation Arena (DESIGN_V2 @ 92af7bb; authorized by the
Stage-A re-review of 179db0f).

Candidate vs heuristic only; 64 fresh blocks (5_800_256..319) x 2 rotations
= 128 matches; paired-block bootstrap (10k, seed 43_300_201); 95% two-sided
decision CI (single comparison); verdict table frozen; no extra seeds.
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
OUT_ROOT = REPO / "local-artifacts/s3-arena"
RESULT = REPO / "benchmarks/s3-rollout-candidate-v1.result.json"

FROZEN_SEEDS = list(range(5_800_256, 5_800_320))
BOOTSTRAP_SEED = 43_300_201
BOOTSTRAP_RESAMPLES = 10_000

CANDIDATE_ARGS = ["agent-s3-rollout"]
HEURISTIC_ARGS = ["agent-heuristic", "--seed", "20260812"]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_cmd(args: list[str]) -> dict:
    return {"program": str(SPLN), "args": args}


def run_one_match(block_idx, seed, rotation, work_dir):
    game_id = f"s3b-p1-b{block_idx:02d}-s{seed}-r{rotation}"
    mdir = work_dir / f"block-{block_idx:02d}-seed-{seed}" / f"r{rotation}"
    mdir.mkdir(parents=True, exist_ok=True)
    # rotation 0: candidate seat 0; rotation 1: heuristic seat 0.
    agents = ([agent_cmd(CANDIDATE_ARGS), agent_cmd(HEURISTIC_ARGS)] if rotation == 0
              else [agent_cmd(HEURISTIC_ARGS), agent_cmd(CANDIDATE_ARGS)])
    cfg = {"game_id": game_id, "seed": seed, "handshake_timeout_ms": 10_000,
           "move_timeout_ms": 60_000, "shutdown_grace_ms": 2_000, "agents": agents}
    cfg_path = mdir / "match-config.json"
    rep_path = mdir / "arena-report.json"
    rpl_path = mdir / "match-replay.json"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    if rep_path.is_file() and rpl_path.is_file():
        try:
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            if rep.get("outcome", {}).get("status") == "completed":
                return parse(rep, rotation, block_idx)
        except Exception:
            pass
    t0 = time.perf_counter()
    r = subprocess.run([str(SPLN), "run-match", "--config", str(cfg_path),
                        "--report-out", str(rep_path), "--replay-out", str(rpl_path)],
                       capture_output=True, text=True)
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(f"{game_id}: exit {r.returncode}: {r.stdout[:300]}{r.stderr[:300]}")
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    if rep["outcome"]["status"] != "completed":
        raise RuntimeError(f"{game_id}: {rep['outcome']}")
    out = parse(rep, rotation, block_idx)
    out["wall_s"] = round(wall, 2)
    return out


def parse(rep, rotation, block_idx):
    outcome = rep["outcome"]
    res = outcome["result"]
    candidate_seat = 0 if rotation == 0 else 1
    winners = res["winners"]
    if candidate_seat in winners and len(winners) == 1:
        score = 10_000
    elif candidate_seat in winners:
        score = 5_000
    else:
        score = 0
    return {"game_id": rep["game_id"], "block_idx": block_idx, "rotation": rotation,
            "candidate_seat": candidate_seat, "score_bps": score,
            "completed_plies": outcome["completed_plies"],
            "replay_final_hash": outcome["replay_final_hash"]}


def main() -> None:
    workers = int(os.environ.get("S3B_WORKERS", "4"))
    print(f"S3 Stage-B Arena: candidate vs heuristic, "
          f"{len(FROZEN_SEEDS)} blocks x 2 rotations = 128 matches")

    # registry fail-closed for the fresh segment
    sys.path.insert(0, str(REPO / "scripts"))
    import s0_seed_registry as reg
    reg.S0_SEGMENT = range(5_800_256, 5_800_320)
    if reg.check() != 0:
        print("FAIL: seed segment overlap")
        sys.exit(1)

    work = OUT_ROOT / "p1_candidate_vs_heuristic"
    t0 = time.time()
    tasks = [(b, s, r) for b, s in enumerate(FROZEN_SEEDS) for r in (0, 1)]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one_match, b, s, r, work): (b, r) for b, s, r in tasks}
        for fut in concurrent.futures.as_completed(futs):
            res = fut.result()
            results[(res["block_idx"], res["rotation"])] = res

    blocks = [(results[(b, 0)]["score_bps"] + results[(b, 1)]["score_bps"]) / 2.0
              for b in range(len(FROZEN_SEEDS))]
    wins = sum(1 for r in results.values() if r["score_bps"] == 10_000)
    ties = sum(1 for r in results.values() if r["score_bps"] == 5_000)
    center = sum(blocks) / len(blocks)

    import numpy as np
    rng = np.random.RandomState(BOOTSTRAP_SEED)
    arr = np.array(blocks)
    idx = rng.randint(0, len(arr), size=(BOOTSTRAP_RESAMPLES, len(arr)))
    means = np.mean(arr[idx], axis=1)
    ci95 = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]

    if ci95[0] > 5_000:
        verdict = "CONFIRMED_IMPROVEMENT"
    elif ci95[1] < 5_000:
        verdict = "REFUTED"
    else:
        verdict = "UNRESOLVED"

    summary = {
        "pairing": "candidate_vs_heuristic",
        "total_matches": 128, "wins": wins, "ties": ties,
        "losses": 128 - wins - ties, "center_bps": center,
        "ci_decision_95_bps": ci95, "verdict": verdict,
        "mean_plies": sum(r["completed_plies"] for r in results.values()) / 128,
        "wall_total_s": round(time.time() - t0, 1),
    }
    print(f"  W{wins}-T{ties}-L{128-wins-ties} center {center:.1f} "
          f"[95% CI {ci95[0]:.1f}, {ci95[1]:.1f}] -> {verdict} "
          f"({summary['wall_total_s']}s)")

    result = {
        "format": "effective-splendor-s3-stageb-result",
        "version": 1,
        "experiment_id": "s3-rollout-candidate-v1",
        "design_doc": "docs/s3-heuristic-policy-rollout.md @ 92af7bb (Stage-B contract)",
        "contract": {
            "pairing": "candidate vs heuristic-v1 only",
            "frozen_seeds": FROZEN_SEEDS, "rotations": 2, "matches": 128,
            "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                          "unit": "paired seed block"},
            "decision_ci": "95% two-sided (single comparison)",
            "candidate": "agent-s3-rollout (zero flags; identity frozen)",
        },
        "pairings": [summary],
        "decision": {
            "verdict": verdict,
            "reference_challenge_signal": verdict == "CONFIRMED_IMPROVEMENT",
            "primary_reference_change": False,
            "extra_seeds_authorized": False,
            "wording_rules": [
                "UNRESOLVED means evidence insufficient to separate; NOT equivalence.",
                "A confirmed win sets REFERENCE_CHALLENGE_SIGNAL only; no automatic "
                "reference replacement; a separate field calibration would be designed.",
                "No transitivity claims vs n1/M07 (not measured this round).",
            ],
        },
        "splendor_exe_sha256": file_sha256(SPLN),
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nVERDICT: {verdict}")
    print(f"Result: {RESULT}")


if __name__ == "__main__":
    main()
