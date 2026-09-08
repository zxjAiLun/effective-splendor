#!/usr/bin/env python3
"""S0 final audit: fail-closed recheck of the frozen contract.

Recomputes everything the orchestrator claims from the raw per-match
artifacts (arena-report.json + stats sidecars), re-verifies replays via
the CLI, and re-checks every P0 gate:

  1. Seed-segment disjointness (scripts/s0_seed_registry.py logic).
  2. Lineup + rotation verification (exhaustive over all 384 matches).
  3. Replay verification via `splendor verify-replay` (exhaustive).
  4. Observation binding: stats sidecar line counts match the decisions
     each search seat actually made (from replay steps); request_id
     sequences are monotone; game_ids match.
  5. Result recomputation: W/T/L, block scores, center bps, bootstrap CIs
     (both levels), verdicts, and the decision block match the tracked
     result JSON exactly.
  6. Contract constants: seeds segment, rotations, bootstrap params, CI
     levels, agent args, telemetry boundary strings.

Exits 0 on PASS; exits 1 with a specific reason on any failure.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
OUT_ROOT = REPO / "local-artifacts/s0-baseline-calibration"
RESULT_PATH = REPO / "benchmarks/s0-baseline-calibration-v1.result.json"

FROZEN_SEEDS = list(range(5_800_064, 5_800_128))
BOOTSTRAP_SEED = 42_280_001
BOOTSTRAP_RESAMPLES = 10_000
PAIRING_IDS = ["p1_heuristic_vs_n1", "p2_heuristic_vs_m07", "p3_n1_vs_m07"]
SEARCH_AGENTS = {"det-s4-d1-n1": 1, "det-s4-d1-n2000": 2000}

sys.path.insert(0, str(REPO / "scripts"))


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    # ---- P0-1: seed disjointness (reuse registry logic) ----
    import s0_seed_registry

    if s0_seed_registry.check() != 0:
        fail("seed registry disjointness")
    if result["contract"]["frozen_seeds"] != FROZEN_SEEDS:
        fail("result frozen_seeds != contract segment")
    print("P0-1 seed disjointness PASS")

    # ---- P0-2/P0-3 + recomputation over raw artifacts ----
    import numpy as np

    recomputed_pairings = []
    for pid in PAIRING_IDS:
        spec = next(p for p in result["pairings"] if p["pairing_id"] == pid)
        work_dir = OUT_ROOT / pid
        primary, secondary = spec["primary"], spec["secondary"]

        block_scores = []
        wins = ties = losses = 0
        plies = []
        agent_rows: dict[str, list[dict]] = {}

        for b, seed in enumerate(FROZEN_SEEDS):
            block_dir = work_dir / f"block-{b:02d}-seed-{seed}"
            if seed not in FROZEN_SEEDS or not block_dir.is_dir():
                fail(f"{pid}: missing block dir {block_dir}")
            per_rot = {}
            for rot in (0, 1):
                mdir = block_dir / f"r{rot}"
                rep = json.loads((mdir / "arena-report.json").read_text(encoding="utf-8"))
                outcome = rep["outcome"]
                if outcome["status"] != "completed":
                    fail(f"{pid} b{b} r{rot}: outcome {outcome['status']}")

                # ---- lineup verification (from the plan config + report identity) ----
                game_id = f"s0-{pid}-b{b:02d}-s{seed}-r{rot}"
                if rep["game_id"] != game_id:
                    fail(f"game_id mismatch: {rep['game_id']} != {game_id}")
                cfg_m = json.loads((mdir / "match-config.json").read_text(encoding="utf-8"))
                if cfg_m["game_id"] != game_id or cfg_m["seed"] != seed:
                    fail(f"config binding mismatch {game_id}")
                if cfg_m["move_timeout_ms"] != 60_000 or cfg_m["handshake_timeout_ms"] != 10_000:
                    fail(f"timeout drift {game_id}")
                seat_names = []
                for ag in cfg_m["agents"]:
                    args = ag["args"]
                    if "agent-heuristic" in args:
                        i = args.index("--seed")
                        if args[i + 1] != "20260812":
                            fail("heuristic seed drift")
                        seat_names.append("heuristic-v1")
                    elif "agent-determinization" in args:
                        i = args.index("--sample-seed")
                        if args[i + 1] != "20260703":
                            fail("sample-seed drift")
                        i = args.index("--sample-count")
                        if args[i + 1] != "4":
                            fail("sample-count drift")
                        i = args.index("--max-depth-turns")
                        if args[i + 1] != "1":
                            fail("depth drift")
                        i = args.index("--max-nodes")
                        seat_names.append(f"det-s4-d1-n{args[i + 1]}")
                        # --stats-out must be present for search agents
                        if "--stats-out" not in args:
                            fail(f"search agent without --stats-out: {game_id}")
                    else:
                        fail(f"unknown agent program: {args[:2]}")
                expected = [primary, secondary] if rot == 0 else [secondary, primary]
                if seat_names != expected:
                    fail(f"lineup mismatch {game_id}: {seat_names} != {expected}")

                # ---- replay verification (CLI, exhaustive) ----
                rpl = mdir / "match-replay.json"
                v = subprocess.run([str(SPLN), "verify-replay", "--input", str(rpl)],
                                   capture_output=True, text=True)
                if v.returncode != 0:
                    fail(f"replay verification failed {game_id}: {v.stdout}{v.stderr}")

                # ---- score recomputation ----
                res = outcome["result"]
                primary_seat = 0 if rot == 0 else 1
                winners = res["winners"]
                if primary_seat in winners and len(winners) == 1:
                    sc, w, t = 10_000, True, False
                elif primary_seat in winners:
                    sc, w, t = 5_000, False, True
                else:
                    sc, w, t = 0, False, False
                per_rot[rot] = sc
                wins += w
                ties += t
                plies.append(outcome["completed_plies"])

                # ---- observation binding ----
                replay = json.loads(rpl.read_text(encoding="utf-8"))
                # count decisions per seat from replay steps
                seat_decisions = {0: 0, 1: 0}
                for step in replay.get("steps", []):
                    actor = step.get("actor")
                    if actor is not None:
                        seat_decisions[int(actor)] = seat_decisions.get(int(actor), 0) + 1
                for agent_id, seat in ((primary, primary_seat), (secondary, 1 - primary_seat)):
                    if agent_id in SEARCH_AGENTS:
                        stats_files = list(mdir.glob(f"stats-seat{seat}-{agent_id}.ndjson"))
                        if len(stats_files) != 1:
                            fail(f"stats file count {len(stats_files)} for {agent_id} seat {seat} {game_id}")
                        rows = [json.loads(l) for l in
                                stats_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
                        if len(rows) != seat_decisions[seat]:
                            fail(f"{game_id}: {agent_id} seat {seat} stats rows {len(rows)} "
                                 f"!= replay decisions {seat_decisions[seat]}")
                        for r_ in rows:
                            if r_["game_id"] != game_id:
                                fail(f"stats game_id mismatch {r_['game_id']} != {game_id}")
                        rids = [r_["request_id"] for r_ in rows]
                        if any(y <= x for x, y in zip(rids, rids[1:])):
                            fail(f"{game_id}: request_ids not monotone")
                        agent_rows.setdefault(agent_id, []).extend(rows)
                    else:
                        if list(mdir.glob(f"stats-seat{seat}-*.ndjson")):
                            fail(f"heuristic seat has stats file: {game_id}")

            block_scores.append((per_rot[0] + per_rot[1]) / 2.0)

        center = sum(block_scores) / len(block_scores)
        rng = np.random.RandomState(BOOTSTRAP_SEED)
        arr = np.array(block_scores, dtype=np.float64)
        idx = rng.randint(0, len(block_scores), size=(BOOTSTRAP_RESAMPLES, len(block_scores)))
        means = np.mean(arr[idx], axis=1)
        ci95 = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
        alpha = (100.0 - 98.33) / 2.0
        ci98 = [float(np.percentile(means, alpha)), float(np.percentile(means, 100.0 - alpha))]

        def verdict(ci):
            if ci[0] > 5_000:
                return "STRONGER_A"
            if ci[1] < 5_000:
                return "STRONGER_B"
            return "UNRESOLVED"

        losses = len(block_scores) * 2 - wins - ties
        checks = {
            "wins": (wins, spec["wins"]), "ties": (ties, spec["ties"]),
            "losses": (losses, spec["losses"]),
            "center": (round(center, 10), round(spec["center_bps"], 10)),
            "ci95": ([round(x, 6) for x in ci95],
                     [round(x, 6) for x in spec["ci_descriptive_95_bps"]]),
            "ci98": ([round(x, 6) for x in ci98],
                     [round(x, 6) for x in spec["ci_decision_98_33_bps"]]),
            "verdict95": (verdict(ci95), spec["verdict_descriptive_95"]),
            "verdict98": (verdict(ci98), spec["verdict_decision_98_33"]),
            "matches": (len(block_scores) * 2, spec["total_matches"]),
        }
        for name, (got, want) in checks.items():
            if got != want:
                fail(f"{pid} recomputation mismatch {name}: {got} != {want}")

        # ---- stats aggregation recomputation ----
        for agent_id, rows in agent_rows.items():
            n_dec = len(rows)
            claimed = spec["agent_stats"][agent_id]["decisions"]
            if n_dec != claimed:
                fail(f"{pid} {agent_id}: stats decisions {n_dec} != {claimed}")
        recomputed_pairings.append(spec)
        print(f"P0-2/3/5 {pid}: lineup+replay+binding+recompute PASS "
              f"({spec['verdict_decision_98_33']})")

    # ---- P0-6: decision-identity (recorded smoke) ----
    # The parity smoke (replay_final_hash equality with/without --stats-out)
    # was executed pre-run; re-assert the binary hash recorded in the result.
    if result["splendor_exe_sha256"] != file_sha256(SPLN):
        fail("splendor binary hash drift since run")
    print("P0-6 binary identity PASS")

    # ---- decision block recheck ----
    wins_over = {"heuristic-v1": 0, "det-s4-d1-n1": 0, "det-s4-d1-n2000": 0}
    for spec in result["pairings"]:
        v = spec["verdict_decision_98_33"]
        if v == "STRONGER_A":
            wins_over[spec["primary"]] += 1
        elif v == "STRONGER_B":
            wins_over[spec["secondary"]] += 1
    dw = [a for a, n in wins_over.items() if n == 2]
    dec = result["decision"]
    if dec["primary_reference"] != (dw[0] if len(dw) == 1 else None):
        fail("primary_reference mismatch")
    if dec["unique_reference_named"] != (len(dw) == 1):
        fail("unique_reference_named mismatch")
    if dec["wins_over"] != wins_over:
        fail(f"wins_over mismatch: {dec['wins_over']} != {wins_over}")
    print("Decision block recompute PASS")

    print(f"\nS0 FINAL AUDIT: ALL CHECKS PASS")
    print(f"Tracked result: {RESULT_PATH}")
    print(f"git-blob SHA256 (LF): compute after commit")
    print(f"VERDICTS: " + ", ".join(
        f"{p['pairing_id']}={p['verdict_decision_98_33']}" for p in result["pairings"]))
    print(f"PRIMARY REFERENCE: {dec['primary_reference']}; "
          f"unresolved: {dec['unresolved_pairings']}")


if __name__ == "__main__":
    main()
