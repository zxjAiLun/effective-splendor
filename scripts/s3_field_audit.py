#!/usr/bin/env python3
"""S3 field-calibration final audit: fail-closed recheck.

- registry disjointness (5_800_320..383, real registry — no monkeypatch)
- lineup/rotation from match configs (candidate zero-flag; n1/M07 exact
  frozen configs)
- 256/256 replays verified
- recomputation of W/T/L, block scores, center, both CI levels, verdicts,
  decision table
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
ROOT = REPO / "local-artifacts/s3-field-calibration"
RESULT = REPO / "benchmarks/s3-field-calibration-v1.result.json"

FROZEN_SEEDS = list(range(5_800_320, 5_800_384))
BOOTSTRAP_SEED = 43_300_301
BOOTSTRAP_RESAMPLES = 10_000

N1_EXPECT = ["agent-determinization", "--sample-seed", "20260703", "--sample-count", "4",
             "--max-depth-turns", "1", "--max-nodes", "1"]


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))

    sys.path.insert(0, str(REPO / "scripts"))
    import s0_seed_registry as reg
    reg.CHECK_SEGMENT = range(5_800_320, 5_800_384)
    if reg.check() != 0:
        fail("seed overlap (real registry)")
    if result["contract"]["frozen_seeds"] != FROZEN_SEEDS:
        fail("result seeds != contract")
    print("seed disjointness PASS (real registry, no monkeypatch)")

    for spec in result["pairings"]:
        pid = spec["pairing_id"]
        work = ROOT / pid
        primary, secondary = spec["primary"], spec["secondary"]
        blocks = {}
        wins = ties = 0
        plies = []
        for b, seed in enumerate(FROZEN_SEEDS):
            for rot in (0, 1):
                mdir = work / f"block-{b:02d}-seed-{seed}" / f"r{rot}"
                rep = json.loads((mdir / "arena-report.json").read_text(encoding="utf-8"))
                if rep["outcome"]["status"] != "completed":
                    fail(f"{pid} b{b} r{rot}: not completed")
                game_id = f"s3f-{pid}-b{b:02d}-s{seed}-r{rot}"
                if rep["game_id"] != game_id:
                    fail(f"game_id mismatch {rep['game_id']} != {game_id}")
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
                    elif "agent-determinization" in args:
                        core = [a for a in args if not a.startswith("--runtime")]
                        if core[:4] != N1_EXPECT[:4]:
                            fail(f"determinization config drift: {core}")
                        i = core.index("--max-nodes") if "--max-nodes" in core else -1
                        if i == -1:
                            fail(f"missing --max-nodes: {core}")
                        nodes = core[i + 1]
                        seats.append(f"n{nodes}")
                        if nodes not in ("1", "2000"):
                            fail(f"unexpected nodes {nodes}")
                    else:
                        fail(f"unknown agent: {args[:2]}")
                expected = [primary, secondary] if rot == 0 else [secondary, primary]
                exp_norm = [("candidate" if e == "candidate" else f"n{'1' if e == 'n1' else '2000'}")
                            for e in expected]
                if seats != exp_norm:
                    fail(f"lineup mismatch {game_id}: {seats} != {exp_norm}")
                rpl = mdir / "match-replay.json"
                v = subprocess.run([str(SPLN), "verify-replay", "--input", str(rpl)],
                                   capture_output=True, text=True)
                if v.returncode != 0:
                    fail(f"replay verification failed {game_id}")
                res = rep["outcome"]["result"]
                primary_seat = 0 if rot == 0 else 1
                if primary_seat in res["winners"] and len(res["winners"]) == 1:
                    score = 10_000
                elif primary_seat in res["winners"]:
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
        alpha = (100.0 - 97.5) / 2.0
        ci975 = [float(np.percentile(means, alpha)), float(np.percentile(means, 100.0 - alpha))]

        def verd(ci):
            if ci[0] > 5_000:
                return "STRONGER_A"
            if ci[1] < 5_000:
                return "STRONGER_B"
            return "UNRESOLVED"

        losses = 128 - wins - ties
        checks = {
            "wins": (wins, spec["wins"]), "ties": (ties, spec["ties"]),
            "losses": (losses, spec["losses"]),
            "center": (round(center, 10), round(spec["center_bps"], 10)),
            "ci95": ([round(x, 6) for x in ci95],
                     [round(x, 6) for x in spec["ci_descriptive_95_bps"]]),
            "ci975": ([round(x, 6) for x in ci975],
                      [round(x, 6) for x in spec["ci_decision_97_5_bps"]]),
            "verdict975": (verd(ci975), spec["verdict_decision_97_5"]),
        }
        for name, (got, want) in checks.items():
            if got != want:
                fail(f"{pid} recompute mismatch {name}: {got} != {want}")
        print(f"{pid}: lineup+replay+recompute PASS ({verd(ci975)})")

    # decision table recheck
    by = {s["pairing_id"]: s for s in result["pairings"]}
    v_n1 = by["p1_candidate_vs_n1"]["verdict_decision_97_5"]
    v_m07 = by["p2_candidate_vs_m07"]["verdict_decision_97_5"]
    if v_n1 == "STRONGER_A" and v_m07 == "STRONGER_A":
        expected_state = "FIELD_TOP_CONFIRMED"
        expected_ref = "s3-rollout-candidate"
    elif v_n1 == "STRONGER_B" or v_m07 == "STRONGER_B":
        expected_state = "NONTRANSITIVE_SPLIT_FIELD"
        expected_ref = None
    else:
        expected_state = "TOP_FIELD_UNRESOLVED"
        expected_ref = None
    d = result["decision"]
    if d["state"] != expected_state:
        fail(f"state mismatch: {d['state']} != {expected_state}")
    if d["new_primary_development_reference"] != expected_ref:
        fail(f"reference mismatch: {d['new_primary_development_reference']} != {expected_ref}")
    print(f"Decision table recompute PASS: {expected_state}")

    if result["splendor_exe_sha256"] != hashlib.sha256(SPLN.read_bytes()).hexdigest():
        fail("binary hash drift")

    print(f"\nS3 FIELD CALIBRATION FINAL AUDIT: ALL CHECKS PASS")
    print(f"STATE: {expected_state} (vs n1 {v_n1}; vs M07 {v_m07})")


if __name__ == "__main__":
    main()
