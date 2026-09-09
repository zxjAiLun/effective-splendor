#!/usr/bin/env python3
"""S3 Operational Profile final audit: fail-closed recheck.

Checks:
- Gate 1: Action parity smoke test (bit-identical replays and telemetry)
- Gate 2: 128/128 match configs, reports, replays verified, decision sums == plies
- Gate 3: Zero move timeouts, zero process errors, max latency << 60s
- Recomputation: full recalculation of all percentiles, path rates, multiples
- Binary SHA256 match
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
ROOT = REPO / "local-artifacts/s3-operational-profile"
RESULT = REPO / "benchmarks/s3-operational-profile-v1.result.json"

FROZEN_SEEDS = list(range(5_800_384, 5_800_448))


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    print("S3 Operational Profile: running fail-closed audit...")

    if not RESULT.is_file():
        fail(f"Result artifact missing: {RESULT}")
    result = json.loads(RESULT.read_text(encoding="utf-8"))

    # 1. Binary identity
    current_bin_hash = hashlib.sha256(SPLN.read_bytes()).hexdigest()
    if result["splendor_exe_sha256"] != current_bin_hash:
        fail(f"Binary SHA256 mismatch: {result['splendor_exe_sha256']} != {current_bin_hash}")
    print("  Binary SHA256 match PASS")

    # 2. Gate 1: Profile wrapper action parity
    print("  Checking Gate 1: Action parity...")
    r_smoke = subprocess.run([sys.executable, str(REPO / "scripts/s3_profile_parity_smoke.py")],
                             capture_output=True, text=True)
    if r_smoke.returncode != 0:
        fail(f"Action parity smoke test failed: {r_smoke.stderr}")
    print("  Gate 1 Action Parity PASS (100% bit-identical replays and valid telemetry)")

    # 3. Gate 2 & 3: Match level verification
    print("  Checking Gate 2 & Gate 3: 128/128 live matches...")
    manifest = json.loads((ROOT / "matches-manifest.json").read_text(encoding="utf-8"))
    if len(manifest["matches"]) != 128:
        fail(f"Expected 128 matches in manifest, got {len(manifest['matches'])}")

    s3_micros = []
    heur_micros = []
    s3_paths = {
        "heuristic_equivalent_fast_path": 0,
        "rollout_comparison": 0,
        "ply_cap_fallback": 0,
    }
    s3_overrides = 0
    total_plies = 0

    for b, seed in enumerate(FROZEN_SEEDS):
        for rot in (0, 1):
            game_id = f"s3op-b{b:02d}-s{seed}-r{rot}"
            mdir = ROOT / "matches" / f"block-{b:02d}-seed-{seed}" / f"r{rot}"
            rep_path = mdir / "arena-report.json"
            rpl_path = mdir / "match-replay.json"
            cfg_path = mdir / "match-config.json"
            s3_path = mdir / "s3-stats.jsonl"
            heur_path = mdir / "heur-stats.jsonl"

            if not (rep_path.is_file() and rpl_path.is_file() and cfg_path.is_file() and s3_path.is_file() and heur_path.is_file()):
                fail(f"{game_id}: missing artifact files in {mdir}")

            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if cfg["seed"] != seed:
                fail(f"{game_id}: seed mismatch {cfg['seed']} != {seed}")
            if cfg["game_id"] != game_id:
                fail(f"{game_id}: game_id mismatch in config")

            # Check agent args
            if rot == 0:
                if cfg["agents"][0]["args"] != ["agent-s3-rollout-profile", "--stats-out", str(s3_path)]:
                    fail(f"{game_id}: rotation 0 seat 0 args mismatch")
                if cfg["agents"][1]["args"] != ["agent-heuristic-profile", "--stats-out", str(heur_path), "--seed", "20260812"]:
                    fail(f"{game_id}: rotation 0 seat 1 args mismatch")
            else:
                if cfg["agents"][0]["args"] != ["agent-heuristic-profile", "--stats-out", str(heur_path), "--seed", "20260812"]:
                    fail(f"{game_id}: rotation 1 seat 0 args mismatch")
                if cfg["agents"][1]["args"] != ["agent-s3-rollout-profile", "--stats-out", str(s3_path)]:
                    fail(f"{game_id}: rotation 1 seat 1 args mismatch")

            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            if rep["outcome"]["status"] != "completed":
                fail(f"{game_id}: status not completed: {rep['outcome']['status']}")

            plies = rep["outcome"]["completed_plies"]
            total_plies += plies

            # verify replay
            v = subprocess.run([str(SPLN), "verify-replay", "--input", str(rpl_path)],
                               capture_output=True, text=True)
            if v.returncode != 0:
                fail(f"{game_id}: replay verification failed: {v.stderr}")

            # read S3 records
            s3_lines = [json.loads(l) for l in s3_path.read_text(encoding="utf-8").strip().split("\n")]
            for r in s3_lines:
                if r["game_id"] != game_id:
                    fail(f"{game_id}: S3 telemetry game_id mismatch")
                if r["seat"] != (0 if rot == 0 else 1):
                    fail(f"{game_id}: S3 telemetry seat mismatch")
                if r["path"] not in s3_paths:
                    fail(f"{game_id}: unknown S3 path {r['path']}")
                if not isinstance(r["override"], bool):
                    fail(f"{game_id}: override not bool")
                if r["decide_micros"] >= 60_000_000:
                    fail(f"{game_id}: decision exceeded 60s timeout: {r['decide_micros']} us")
                s3_micros.append(r["decide_micros"])
                s3_paths[r["path"]] += 1
                if r["override"]:
                    s3_overrides += 1

            # read Heuristic records
            heur_lines = [json.loads(l) for l in heur_path.read_text(encoding="utf-8").strip().split("\n")]
            for r in heur_lines:
                if r["game_id"] != game_id:
                    fail(f"{game_id}: Heuristic telemetry game_id mismatch")
                if r["seat"] != (1 if rot == 0 else 0):
                    fail(f"{game_id}: Heuristic telemetry seat mismatch")
                if r["path"] != "heuristic_eval":
                    fail(f"{game_id}: Heuristic telemetry unexpected path {r['path']}")
                if r["override"] is not False:
                    fail(f"{game_id}: Heuristic telemetry override must be false")
                heur_micros.append(r["decide_micros"])

            if len(s3_lines) + len(heur_lines) != plies:
                fail(f"{game_id}: decisions sum {len(s3_lines) + len(heur_lines)} != completed plies {plies}")

    print(f"  Gate 2 & Gate 3 PASS (128/128 completed matches, verified replays, 0 timeouts/errors)")

    # 4. Statistical recomputations
    print("  Recomputing metrics and asserting exact match with result artifact...")
    s3_arr_ms = np.array(s3_micros, dtype=float) / 1000.0
    heur_arr_ms = np.array(heur_micros, dtype=float) / 1000.0
    total_s3 = len(s3_micros)
    total_heur = len(heur_micros)

    def stats_dict(arr: np.ndarray, count: int) -> dict:
        return {
            "decisions_count": count,
            "mean_ms": round(float(np.mean(arr)), 4),
            "p50_ms": round(float(np.percentile(arr, 50)), 4),
            "p90_ms": round(float(np.percentile(arr, 90)), 4),
            "p95_ms": round(float(np.percentile(arr, 95)), 4),
            "p99_ms": round(float(np.percentile(arr, 99)), 4),
            "max_ms": round(float(np.max(arr)), 4),
            "total_decide_wall_s": round(float(np.sum(arr)) / 1000.0, 4),
        }

    s3_calc = stats_dict(s3_arr_ms, total_s3)
    heur_calc = stats_dict(heur_arr_ms, total_heur)

    if s3_calc != result["candidate_profile"]:
        fail(f"S3 profile mismatch:\nCalculated: {s3_calc}\nRecorded:   {result['candidate_profile']}")
    if heur_calc != result["baseline_profile"]:
        fail(f"Heuristic profile mismatch:\nCalculated: {heur_calc}\nRecorded:   {result['baseline_profile']}")

    calc_breakdown = {
        "fast_path_heuristic_equivalent_count": s3_paths["heuristic_equivalent_fast_path"],
        "fast_path_heuristic_equivalent_rate": round(s3_paths["heuristic_equivalent_fast_path"] / total_s3, 4),
        "rollout_comparison_count": s3_paths["rollout_comparison"],
        "rollout_comparison_rate": round(s3_paths["rollout_comparison"] / total_s3, 4),
        "ply_cap_fallback_count": s3_paths["ply_cap_fallback"],
        "ply_cap_fallback_rate": round(s3_paths["ply_cap_fallback"] / total_s3, 4),
        "overrides_count": s3_overrides,
        "overrides_overall_rate": round(s3_overrides / total_s3, 4),
        "overrides_of_comparisons_rate": round(s3_overrides / s3_paths["rollout_comparison"], 4) if s3_paths["rollout_comparison"] > 0 else 0.0,
    }
    if calc_breakdown != result["candidate_paths"]:
        fail(f"Candidate paths mismatch:\nCalculated: {calc_breakdown}\nRecorded:   {result['candidate_paths']}")

    print("  Recomputed statistics match result artifact 100%!")
    print(f"\nS3 OPERATIONAL PROFILE AUDIT: ALL CHECKS PASS")
    print(f"  Matches: 128/128 completed")
    print(f"  Decisions: S3 {total_s3}, Heuristic {total_heur} (total {total_plies})")
    print(f"  S3 Latency: median {s3_calc['p50_ms']} ms, p95 {s3_calc['p95_ms']} ms, max {s3_calc['max_ms']} ms")
    print(f"  Heuristic Latency: median {heur_calc['p50_ms']} ms, p95 {heur_calc['p95_ms']} ms, max {heur_calc['max_ms']} ms")
    print(f"  S3 Rollout Trigger Rate: {calc_breakdown['rollout_comparison_rate'] * 100.0:.2f}%")
    print(f"  S3 Override Rate: {calc_breakdown['overrides_overall_rate'] * 100.0:.2f}%")
    print(f"  Watchdog Headroom: {round(60_000.0 / s3_calc['max_ms'], 1)}x vs 60s limit")


if __name__ == "__main__":
    main()
