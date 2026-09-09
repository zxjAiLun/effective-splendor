#!/usr/bin/env python3
"""S3 Stage-B final audit: fail-closed recheck.

- seed registry disjointness for 5_800_256..319
- lineup/rotation from match configs (candidate = zero-flag agent-s3-rollout;
  heuristic = exact frozen args)
- 128/128 replays verified via verify-replay
- recomputation of W/T/L, block scores, center, 95% CI, verdict
- decision block consistency
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
ARENA = REPO / "local-artifacts/s3-arena/p1_candidate_vs_heuristic"
RESULT = REPO / "benchmarks/s3-rollout-candidate-v1.result.json"

FROZEN_SEEDS = list(range(5_800_256, 5_800_320))
BOOTSTRAP_SEED = 43_300_201
BOOTSTRAP_RESAMPLES = 10_000
HEURISTIC_OK = ["agent-heuristic", "--seed", "20260812"]


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))

    sys.path.insert(0, str(REPO / "scripts"))
    import s0_seed_registry as reg
    reg.S0_SEGMENT = range(5_800_256, 5_800_320)
    if reg.check() != 0:
        fail("seed overlap")
    if result["contract"]["frozen_seeds"] != FROZEN_SEEDS:
        fail("result seeds != contract")
    print("seed disjointness PASS")

    blocks = {}
    wins = ties = 0
    plies = []
    for b, seed in enumerate(FROZEN_SEEDS):
        for rot in (0, 1):
            mdir = ARENA / f"block-{b:02d}-seed-{seed}" / f"r{rot}"
            rep = json.loads((mdir / "arena-report.json").read_text(encoding="utf-8"))
            if rep["outcome"]["status"] != "completed":
                fail(f"b{b} r{rot}: not completed")
            game_id = f"s3b-p1-b{b:02d}-s{seed}-r{rot}"
            if rep["game_id"] != game_id:
                fail(f"game_id mismatch: {rep['game_id']} != {game_id}")
            cfgm = json.loads((mdir / "match-config.json").read_text(encoding="utf-8"))
            if cfgm["seed"] != seed:
                fail(f"seed binding {game_id}")
            seats = []
            for ag in cfgm["agents"]:
                args = ag["args"]
                if "agent-s3-rollout" in args:
                    if args != ["agent-s3-rollout"]:
                        fail(f"candidate args drift: {args}")
                    seats.append("candidate")
                elif "agent-heuristic" in args:
                    if args != HEURISTIC_OK:
                        fail(f"heuristic args drift: {args}")
                    seats.append("heuristic")
                else:
                    fail(f"unknown agent: {args[:2]}")
            expected = (["candidate", "heuristic"] if rot == 0
                        else ["heuristic", "candidate"])
            if seats != expected:
                fail(f"lineup mismatch {game_id}: {seats} != {expected}")
            rpl = mdir / "match-replay.json"
            v = subprocess.run([str(SPLN), "verify-replay", "--input", str(rpl)],
                               capture_output=True, text=True)
            if v.returncode != 0:
                fail(f"replay verification failed {game_id}")
            res = rep["outcome"]["result"]
            candidate_seat = 0 if rot == 0 else 1
            if candidate_seat in res["winners"] and len(res["winners"]) == 1:
                score = 10_000
            elif candidate_seat in res["winners"]:
                score = 5_000
            else:
                score = 0
            blocks[(b, rot)] = score
            wins += score == 10_000
            ties += score == 5_000
            plies.append(rep["outcome"]["completed_plies"])

    import numpy as np
    block_scores = [(blocks[(b, 0)] + blocks[(b, 1)]) / 2.0 for b in range(64)]
    center = sum(block_scores) / 64
    rng = np.random.RandomState(BOOTSTRAP_SEED)
    arr = np.array(block_scores)
    idx = rng.randint(0, 64, size=(BOOTSTRAP_RESAMPLES, 64))
    means = np.mean(arr[idx], axis=1)
    ci95 = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
    losses = 128 - wins - ties
    spec = result["pairings"][0]
    checks = {
        "wins": (wins, spec["wins"]), "ties": (ties, spec["ties"]),
        "losses": (losses, spec["losses"]),
        "center": (round(center, 10), round(spec["center_bps"], 10)),
        "ci95": ([round(x, 6) for x in ci95],
                 [round(x, 6) for x in spec["ci_decision_95_bps"]]),
    }
    for name, (got, want) in checks.items():
        if got != want:
            fail(f"recompute mismatch {name}: {got} != {want}")

    if ci95[0] > 5_000:
        expected_verdict = "CONFIRMED_IMPROVEMENT"
    elif ci95[1] < 5_000:
        expected_verdict = "REFUTED"
    else:
        expected_verdict = "UNRESOLVED"
    if result["decision"]["verdict"] != expected_verdict:
        fail(f"verdict mismatch: {result['decision']['verdict']} != {expected_verdict}")
    if result["decision"]["reference_challenge_signal"] != (expected_verdict == "CONFIRMED_IMPROVEMENT"):
        fail("reference_challenge_signal mismatch")
    if result["decision"]["primary_reference_change"] is not False:
        fail("primary_reference_change must be false")

    if result["splendor_exe_sha256"] != hashlib.sha256(SPLN.read_bytes()).hexdigest():
        fail("binary hash drift")

    print(f"lineup+replay+recompute PASS ({expected_verdict})")
    print(f"\nS3 STAGE-B FINAL AUDIT: ALL CHECKS PASS")
    print(f"VERDICT: {expected_verdict} (W{wins}-T{ties}-L{losses}, "
          f"center {center:.1f}, 95% CI [{ci95[0]:.1f}, {ci95[1]:.1f}])")


if __name__ == "__main__":
    main()
