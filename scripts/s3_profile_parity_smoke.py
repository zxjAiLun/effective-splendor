#!/usr/bin/env python3
"""Targeted action-parity smoke test for S3 and heuristic profiling wrappers.

Runs pairs of matches on identical seeds (42, 100, 2026):
  Pair A: production agent-s3-rollout vs production agent-heuristic
  Pair B: profiled agent-s3-rollout-profile vs profiled agent-heuristic-profile

Verifies:
  - 100% replay final hash identity between production and profiled matches.
  - Replay ply-by-ply action sequence equality.
  - Both replays pass verify-replay.
  - Telemetry JSONL files contain valid schema lines matching exact decision counts.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
SMOKE_DIR = REPO / "local-artifacts/s3-profile-smoke"

TEST_SEEDS = [42, 100, 2026]


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def run_match(cfg: dict, mdir: Path) -> tuple[dict, dict]:
    import shutil
    if mdir.exists():
        shutil.rmtree(mdir)
    mdir.mkdir(parents=True, exist_ok=True)
    cfg_path = mdir / "match-config.json"
    rep_path = mdir / "report.json"
    rpl_path = mdir / "replay.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

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
    if r.returncode != 0:
        fail(f"run-match exit {r.returncode}: stderr={r.stderr[:500]}")

    v = subprocess.run(
        [str(SPLN), "verify-replay", "--input", str(rpl_path)],
        capture_output=True,
        text=True,
    )
    if v.returncode != 0:
        fail(f"verify-replay failed: {v.stderr[:500]}")

    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    rpl = json.loads(rpl_path.read_text(encoding="utf-8"))
    return rep, rpl


def main() -> None:
    if not SPLN.is_file():
        fail(f"splendor binary not found at {SPLN}")

    print(f"Running action parity smoke tests across {len(TEST_SEEDS)} seeds...")

    for seed in TEST_SEEDS:
        print(f"\n--- Testing seed {seed} ---")
        # 1. Production match
        prod_dir = SMOKE_DIR / f"seed-{seed}" / "production"
        prod_cfg = {
            "game_id": f"smoke-prod-s{seed}",
            "seed": seed,
            "handshake_timeout_ms": 10_000,
            "move_timeout_ms": 60_000,
            "shutdown_grace_ms": 2_000,
            "agents": [
                {"program": str(SPLN), "args": ["agent-s3-rollout"]},
                {"program": str(SPLN), "args": ["agent-heuristic", "--seed", "20260812"]},
            ],
        }
        prod_rep, prod_rpl = run_match(prod_cfg, prod_dir)
        prod_hash = prod_rep["outcome"]["replay_final_hash"]
        prod_plies = prod_rep["outcome"]["completed_plies"]
        print(f"  Production match: completed {prod_plies} plies, final hash {prod_hash[:16]}...")

        # 2. Profiled match
        prof_dir = SMOKE_DIR / f"seed-{seed}" / "profiled"
        s3_stats = prof_dir / "s3-stats.jsonl"
        heur_stats = prof_dir / "heur-stats.jsonl"
        prof_cfg = {
            "game_id": f"smoke-prof-s{seed}",
            "seed": seed,
            "handshake_timeout_ms": 10_000,
            "move_timeout_ms": 60_000,
            "shutdown_grace_ms": 2_000,
            "agents": [
                {"program": str(SPLN), "args": ["agent-s3-rollout-profile", "--stats-out", str(s3_stats)]},
                {"program": str(SPLN), "args": ["agent-heuristic-profile", "--stats-out", str(heur_stats), "--seed", "20260812"]},
            ],
        }
        prof_rep, prof_rpl = run_match(prof_cfg, prof_dir)
        prof_hash = prof_rep["outcome"]["replay_final_hash"]
        prof_plies = prof_rep["outcome"]["completed_plies"]
        print(f"  Profiled match:   completed {prof_plies} plies, final hash {prof_hash[:16]}...")

        # 3. Action parity check
        if prod_hash != prof_hash:
            fail(f"Replay final hash mismatch for seed {seed}: {prod_hash} != {prof_hash}")
        if prod_plies != prof_plies:
            fail(f"Ply count mismatch for seed {seed}: {prod_plies} != {prof_plies}")

        prod_actions = [step["action"] for step in prod_rpl["steps"]]
        prof_actions = [step["action"] for step in prof_rpl["steps"]]
        if prod_actions != prof_actions:
            fail(f"Action sequence mismatch for seed {seed}")
        print("  Replay parity: 100% BIT-IDENTICAL")

        # 4. Telemetry validation
        if not s3_stats.is_file():
            fail(f"s3 stats file not created: {s3_stats}")
        if not heur_stats.is_file():
            fail(f"heuristic stats file not created: {heur_stats}")

        s3_lines = [json.loads(line) for line in s3_stats.read_text(encoding="utf-8").strip().split("\n")]
        heur_lines = [json.loads(line) for line in heur_stats.read_text(encoding="utf-8").strip().split("\n")]

        for rec in s3_lines:
            assert rec["game_id"] == f"smoke-prof-s{seed}"
            assert rec["seat"] == 0
            assert isinstance(rec["decide_micros"], int) and rec["decide_micros"] >= 0
            assert rec["path"] in ("heuristic_equivalent_fast_path", "rollout_comparison", "ply_cap_fallback")
            assert isinstance(rec["override"], bool)

        for rec in heur_lines:
            assert rec["game_id"] == f"smoke-prof-s{seed}"
            assert rec["seat"] == 1
            assert isinstance(rec["decide_micros"], int) and rec["decide_micros"] >= 0
            assert rec["path"] == "heuristic_eval"
            assert rec["override"] is False

        total_decisions = len(s3_lines) + len(heur_lines)
        if total_decisions != prof_plies:
            fail(f"Decision count mismatch: {total_decisions} telemetry records != {prof_plies} plies")

        print(f"  Telemetry verified: S3 {len(s3_lines)} decisions, Heuristic {len(heur_lines)} decisions (sum={total_decisions} == plies={prof_plies})")

    print("\nPARITY SMOKE PASS: 100% action parity, valid telemetry schemas and decision counts across all smoke seeds!")


if __name__ == "__main__":
    main()
