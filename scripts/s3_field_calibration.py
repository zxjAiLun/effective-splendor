#!/usr/bin/env python3
"""S3 field calibration (contract @ 1c31c40): candidate vs n1 and vs M07.

Seeds 5_800_320..383; 64 blocks x 2 rotations x 2 pairings = 256 matches;
paired-block bootstrap (10k, seed 43_300_301); 95% descriptive + 97.5%
decision CI; frozen reference decision table.
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
OUT_ROOT = REPO / "local-artifacts/s3-field-calibration"
RESULT = REPO / "benchmarks/s3-field-calibration-v1.result.json"

FROZEN_SEEDS = list(range(5_800_320, 5_800_384))
BOOTSTRAP_SEED = 43_300_301
BOOTSTRAP_RESAMPLES = 10_000
CI_LEVELS = {"descriptive_95": 95.0, "decision_97_5": 97.5}

CANDIDATE_ARGS = ["agent-s3-rollout"]
N1_ARGS = ["agent-determinization", "--sample-seed", "20260703", "--sample-count", "4",
           "--max-depth-turns", "1", "--max-nodes", "1"]
M07_ARGS = ["agent-determinization", "--sample-seed", "20260703", "--sample-count", "4",
            "--max-depth-turns", "1", "--max-nodes", "2000"]

PAIRINGS = [
    {"id": "p1_candidate_vs_n1", "primary": ("candidate", CANDIDATE_ARGS),
     "secondary": ("n1", N1_ARGS)},
    {"id": "p2_candidate_vs_m07", "primary": ("candidate", CANDIDATE_ARGS),
     "secondary": ("m07", M07_ARGS)},
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_cmd(kind: str, args: list[str]) -> dict:
    if "agent-determinization" in args:
        return {"program": str(SPLN),
                "args": args + ["--runtime-name", kind, "--runtime-version", "1"]}
    return {"program": str(SPLN), "args": args}


def run_one_match(pairing_id, block_idx, seed, rotation, primary, secondary, work_dir):
    game_id = f"s3f-{pairing_id}-b{block_idx:02d}-s{seed}-r{rotation}"
    mdir = work_dir / f"block-{block_idx:02d}-seed-{seed}" / f"r{rotation}"
    mdir.mkdir(parents=True, exist_ok=True)
    agents = ([agent_cmd(*primary), agent_cmd(*secondary)] if rotation == 0
              else [agent_cmd(*secondary), agent_cmd(*primary)])
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
    winners = res["winners"]
    primary_seat = 0 if rotation == 0 else 1
    if primary_seat in winners and len(winners) == 1:
        score = 10_000
    elif primary_seat in winners:
        score = 5_000
    else:
        score = 0
    return {"game_id": rep["game_id"], "block_idx": block_idx, "rotation": rotation,
            "primary_seat": primary_seat, "score_bps": score,
            "completed_plies": outcome["completed_plies"],
            "replay_final_hash": outcome["replay_final_hash"]}


def main() -> None:
    workers = int(os.environ.get("S3F_WORKERS", "4"))
    print(f"S3 field calibration: 2 pairings x {len(FROZEN_SEEDS)} blocks x 2 rotations "
          f"= 256 matches")

    sys.path.insert(0, str(REPO / "scripts"))
    import s0_seed_registry as reg
    reg.CHECK_SEGMENT = range(5_800_320, 5_800_384)
    if reg.check() != 0:
        print("FAIL: seed segment overlap")
        sys.exit(1)

    summaries = []
    for spec in PAIRINGS:
        work = OUT_ROOT / spec["id"]
        t0 = time.time()
        tasks = [(b, s, r) for b, s in enumerate(FROZEN_SEEDS) for r in (0, 1)]
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(run_one_match, spec["id"], b, s, r, spec["primary"],
                              spec["secondary"], work): (b, r) for b, s, r in tasks}
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
        cis = {}
        for label, level in CI_LEVELS.items():
            alpha = (100.0 - level) / 2.0
            cis[label] = [float(np.percentile(means, alpha)),
                          float(np.percentile(means, 100.0 - alpha))]

        def verd(ci):
            if ci[0] > 5_000:
                return "STRONGER_A"
            if ci[1] < 5_000:
                return "STRONGER_B"
            return "UNRESOLVED"

        summaries.append({
            "pairing_id": spec["id"], "primary": spec["primary"][0],
            "secondary": spec["secondary"][0], "total_matches": 128,
            "wins": wins, "ties": ties, "losses": 128 - wins - ties,
            "center_bps": center,
            "ci_descriptive_95_bps": cis["descriptive_95"],
            "ci_decision_97_5_bps": cis["decision_97_5"],
            "verdict_descriptive_95": verd(cis["descriptive_95"]),
            "verdict_decision_97_5": verd(cis["decision_97_5"]),
            "mean_plies": sum(r["completed_plies"] for r in results.values()) / 128,
            "wall_total_s": round(time.time() - t0, 1),
        })
        print(f"  {spec['id']}: W{wins}-T{ties}-L{128-wins-ties} center {center:.1f} "
              f"[97.5% CI {cis['decision_97_5'][0]:.1f}, {cis['decision_97_5'][1]:.1f}] "
              f"-> {verd(cis['decision_97_5'])} ({summaries[-1]['wall_total_s']}s)",
              flush=True)

    # ---- frozen reference decision table ----
    by = {s["pairing_id"]: s for s in summaries}
    v_n1 = by["p1_candidate_vs_n1"]["verdict_decision_97_5"]
    v_m07 = by["p2_candidate_vs_m07"]["verdict_decision_97_5"]

    if v_n1 == "STRONGER_A" and v_m07 == "STRONGER_A":
        state = "FIELD_TOP_CONFIRMED"
        new_reference = "s3-rollout-candidate"
    elif v_n1 == "STRONGER_B" or v_m07 == "STRONGER_B":
        state = "NONTRANSITIVE_SPLIT_FIELD"
        new_reference = None
    else:
        state = "TOP_FIELD_UNRESOLVED"
        new_reference = None

    result = {
        "format": "effective-splendor-s3-field-calibration-result",
        "version": 1,
        "experiment_id": "s3-field-calibration-v1",
        "design_doc": "docs/s3-field-calibration.md @ 1c31c40 (frozen contract)",
        "contract": {
            "pairings": [p["id"] for p in PAIRINGS],
            "heuristic_rematch": False,
            "candidate_identity": "agent-s3-rollout zero flags (no policy code changes)",
            "frozen_seeds": FROZEN_SEEDS, "rotations": 2, "matches": 256,
            "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                          "unit": "paired seed block"},
            "ci_levels": CI_LEVELS,
            "decision_ci": "decision_97_5 (two-comparison Bonferroni family)",
        },
        "pairings": summaries,
        "decision": {
            "vs_n1": v_n1, "vs_m07": v_m07,
            "state": state,
            "new_primary_development_reference": new_reference,
            "prior_knowledge": {
                "candidate_vs_heuristic": "STRONGER (S3 Stage B: 80-0-48, "
                                          "95% CI [5468.75, 6953.125])",
                "heuristic_vs_n1": "STRONGER (S0)", "heuristic_vs_m07": "STRONGER (S0)",
                "n1_vs_m07": "UNRESOLVED (S0/M42S)",
            },
            "wording_rules": [
                "Transitivity is never assumed (the candidate's rollout opponent "
                "model IS heuristic).",
                "FIELD_TOP_CONFIRMED changes the PRIMARY DEVELOPMENT REFERENCE only — "
                "not the product default, not an automatic promotion.",
                "A genuine cycle (NONTRANSITIVE_SPLIT_FIELD) is a scientific result: "
                "the rollout gain may be opponent/model-specific.",
                "No extra seeds in any outcome.",
            ],
        },
        "splendor_exe_sha256": file_sha256(SPLN),
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nSTATE: {state} (vs n1: {v_n1}; vs M07: {v_m07})")
    if new_reference:
        print(f"NEW PRIMARY DEVELOPMENT REFERENCE: {new_reference}")
    print(f"Result: {RESULT}")


if __name__ == "__main__":
    main()
