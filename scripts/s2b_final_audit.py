#!/usr/bin/env python3
"""S2b final audit: fail-closed recheck of the DESIGN_V2 contract.

Re-verifies: lineup/rotation from match configs; all 256 replays via
verify-replay; recomputation of W/T/L, block scores, center, both CI
levels, verdicts, and the decision table; the scope parity (exhaustive
re-run); the P1 identity cross-check; the fresh-seed disjointness.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
ARENA_ROOT = REPO / "local-artifacts/s2b-arena"
RESULT = REPO / "benchmarks/s2b-n1-buy-overlay-v1.result.json"
SCOPE_RESULT = REPO / "benchmarks/s2b-scope-v1.result.json"

FROZEN_SEEDS = list(range(5_800_192, 5_800_256))
BOOTSTRAP_SEED = 43_200_001
BOOTSTRAP_RESAMPLES = 10_000

N1_ARGS_SET = {"agent-determinization", "--sample-seed", "20260703", "--sample-count", "4",
               "--max-depth-turns", "1", "--max-nodes", "1"}
HEURISTIC_OK = ["agent-heuristic", "--seed", "20260812"]


def act_key(a):
    return json.dumps(a, sort_keys=True)


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))

    # ---- fresh-seed disjointness ----
    sys.path.insert(0, str(REPO / "scripts"))
    import s0_seed_registry as reg
    reg.S0_SEGMENT = range(5_800_192, 5_800_256)
    if reg.check() != 0:
        fail("seed segment overlap")
    if result["contract"]["frozen_seeds"] != FROZEN_SEEDS:
        fail("result seeds != contract")
    print("seed disjointness PASS")

    # ---- per-pairing recheck ----
    for spec in result["pairings"]:
        pid = spec["pairing_id"]
        work = ARENA_ROOT / pid
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
                game_id = f"s2b-{pid}-b{b:02d}-s{seed}-r{rot}"
                if rep["game_id"] != game_id:
                    fail(f"game_id mismatch {rep['game_id']} != {game_id}")
                cfgm = json.loads((mdir / "match-config.json").read_text(encoding="utf-8"))
                if cfgm["seed"] != seed or cfgm["game_id"] != game_id:
                    fail(f"config binding {game_id}")
                # lineup verification
                seats = []
                for ag in cfgm["agents"]:
                    args = ag["args"]
                    if "agent-heuristic" in args:
                        # Strict seed binding: the heuristic seat must carry
                        # exactly the frozen args (agent-heuristic --seed
                        # 20260812), nothing more. The earlier two-tier
                        # check was too loose (any seed value passed).
                        if args != HEURISTIC_OK:
                            fail(f"heuristic args drift: {args}")
                        seats.append("heuristic")
                    elif "agent-determinization" in args:
                        core = [a for a in args if a in N1_ARGS_SET or a.startswith("--runtime")]
                        has_overlay = "--heuristic-buy-overlay" in args
                        is_n1 = all(x in args for x in
                                    ["20260703", "4", "1", "1"]) and not has_overlay
                        is_overlay = all(x in args for x in
                                         ["20260703", "4", "1", "1"]) and has_overlay
                        # precise: check positional values
                        i = args.index("--max-nodes")
                        n1_exact = (args[args.index("--sample-seed") + 1] == "20260703"
                                    and args[args.index("--sample-count") + 1] == "4"
                                    and args[args.index("--max-depth-turns") + 1] == "1"
                                    and args[i + 1] == "1")
                        if has_overlay:
                            if not n1_exact:
                                fail(f"overlay on non-n1 config: {game_id}")
                            seats.append("overlay")
                        elif n1_exact:
                            seats.append("n1")
                        else:
                            fail(f"unknown determinization config: {args}")
                        _ = (is_n1, is_overlay, core)
                    else:
                        fail(f"unknown agent: {args[:2]}")
                expected = [primary, secondary] if rot == 0 else [secondary, primary]
                if seats != expected:
                    fail(f"lineup mismatch {game_id}: {seats} != {expected}")
                # replay verification
                rpl = mdir / "match-replay.json"
                v = subprocess.run([str(SPLN), "verify-replay", "--input", str(rpl)],
                                   capture_output=True, text=True)
                if v.returncode != 0:
                    fail(f"replay verification failed {game_id}")
                # score recomputation
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
        # recompute stats
        import numpy as np
        block_scores = [(blocks[(b, 0)] + blocks[(b, 1)]) / 2.0 for b in range(64)]
        center = sum(block_scores) / 64
        rng = np.random.RandomState(BOOTSTRAP_SEED)
        arr = np.array(block_scores)
        idx = rng.randint(0, 64, size=(BOOTSTRAP_RESAMPLES, 64))
        means = np.mean(arr[idx], axis=1)
        ci95 = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
        ci975 = [float(np.percentile(means, 1.25)), float(np.percentile(means, 98.75))]
        losses = 128 - wins - ties

        def verd(ci):
            if ci[0] > 5_000:
                return "STRONGER_A"
            if ci[1] < 5_000:
                return "STRONGER_B"
            return "UNRESOLVED"

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

    # ---- decision table recheck ----
    by = {s["pairing_id"]: s for s in result["pairings"]}
    v_n1 = by["p1_overlay_vs_n1"]["verdict_decision_97_5"]
    v_h = by["p2_overlay_vs_heuristic"]["verdict_decision_97_5"]
    if v_n1 == "STRONGER_A":
        expected = ("CARRIER_IMPROVEMENT_CONFIRMED"
                    if v_h in ("STRONGER_A", "UNRESOLVED") else "CARRIER_GAIN_ONLY")
    elif v_n1 == "UNRESOLVED":
        expected = "UNRESOLVED"
    else:
        expected = "REFUTED"
    if result["decision"]["verdict"] != expected:
        fail(f"decision mismatch: {result['decision']['verdict']} != {expected}")
    if result["decision"]["reference_challenge_signal"] != (v_h == "STRONGER_A"):
        fail("reference_challenge_signal mismatch")
    if result["decision"]["primary_reference_change"] is not False:
        fail("primary_reference_change must be false")
    print(f"Decision table recompute PASS: {expected}")

    # ---- scope re-run (exhaustive parity + cross-check) ----
    scope = json.loads(SCOPE_RESULT.read_text(encoding="utf-8"))
    r = subprocess.run([sys.executable, str(REPO / "scripts/s2b_scope.py")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"scope re-run failed: {r.stdout[-400:]}{r.stderr[-400:]}")
    scope2 = json.loads(SCOPE_RESULT.read_text(encoding="utf-8"))
    if scope2["trigger_stats"] != scope["trigger_stats"]:
        fail("scope re-run drift")
    if not scope2["p1_identity_cross_check"]["sets_equal"]:
        fail("P1 identity cross-check failed on re-run")
    print("Scope exhaustive parity + P1 cross-check re-run PASS")

    # ---- binary identity ----
    if result["splendor_exe_sha256"] != hashlib.sha256(SPLN.read_bytes()).hexdigest():
        fail("binary hash drift")
    print("Binary identity PASS")

    print(f"\nS2B FINAL AUDIT: ALL CHECKS PASS")
    print(f"VERDICT: {result['decision']['verdict']} "
          f"(vs n1 {v_n1}; vs heuristic {v_h})")


if __name__ == "__main__":
    main()
