#!/usr/bin/env python3
"""S2b confirmation Arena (DESIGN_V2 @ ff7a4f1): overlay vs n1 and overlay vs
heuristic, 64 fresh seeds (5_800_192..255) x 2 rotations x 2 pairings = 256
matches; paired-block bootstrap (10k, seed 43_200_001); 95% descriptive +
97.5% decision CIs; frozen decision table.
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
OUT_ROOT = REPO / "local-artifacts/s2b-arena"
RESULT = REPO / "benchmarks/s2b-n1-buy-overlay-v1.result.json"

FROZEN_SEEDS = list(range(5_800_192, 5_800_256))  # 64 blocks
BOOTSTRAP_SEED = 43_200_001
BOOTSTRAP_RESAMPLES = 10_000
CI_LEVELS = {"descriptive_95": 95.0, "decision_97_5": 97.5}

N1_ARGS = ["agent-determinization", "--sample-seed", "20260703", "--sample-count", "4",
           "--max-depth-turns", "1", "--max-nodes", "1"]
OVERLAY_ARGS = N1_ARGS + ["--heuristic-buy-overlay"]
HEURISTIC_ARGS = ["agent-heuristic", "--seed", "20260812"]

PAIRINGS = [
    {"id": "p1_overlay_vs_n1", "primary": ("overlay", OVERLAY_ARGS),
     "secondary": ("n1", N1_ARGS)},
    {"id": "p2_overlay_vs_heuristic", "primary": ("overlay", OVERLAY_ARGS),
     "secondary": ("heuristic", HEURISTIC_ARGS)},
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_cmd(kind: str, args: list[str]) -> dict:
    # Runtime-name flags exist only on agent-determinization; heuristic has
    # no such flags (its identity is name+seed bound).
    if "agent-determinization" in args:
        return {"program": str(SPLN),
                "args": args + ["--runtime-name", kind, "--runtime-version", "1"]}
    return {"program": str(SPLN), "args": args}


def run_one_match(pairing_id, block_idx, seed, rotation, primary, secondary, work_dir):
    game_id = f"s2b-{pairing_id}-b{block_idx:02d}-s{seed}-r{rotation}"
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
                return parse(rep, 0 if rotation == 0 else 1, block_idx, rotation)
        except Exception:
            pass
    t0 = time.perf_counter()
    r = subprocess.run([str(SPLN), "run-match", "--config", str(cfg_path),
                        "--report-out", str(rep_path), "--replay-out", str(rpl_path)],
                       capture_output=True, text=True)
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(f"{game_id}: exit {r.returncode}: {r.stderr[:1500]}")
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    if rep["outcome"]["status"] != "completed":
        raise RuntimeError(f"{game_id}: {rep['outcome']}")
    out = parse(rep, 0 if rotation == 0 else 1, block_idx, rotation)
    out["wall_s"] = wall
    return out


def parse(rep, primary_seat, block_idx, rotation):
    outcome = rep["outcome"]
    res = outcome["result"]
    winners = res["winners"]
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


def bootstrap(block_scores):
    import numpy as np
    rng = np.random.RandomState(BOOTSTRAP_SEED)
    arr = np.array(block_scores, dtype=np.float64)
    idx = rng.randint(0, len(arr), size=(BOOTSTRAP_RESAMPLES, len(arr)))
    means = np.mean(arr[idx], axis=1)
    out = {}
    for label, level in CI_LEVELS.items():
        alpha = (100.0 - level) / 2.0
        out[label] = [float(np.percentile(means, alpha)),
                      float(np.percentile(means, 100.0 - alpha))]
    return out


def verdict(ci):
    if ci[0] > 5_000:
        return "STRONGER_A"
    if ci[1] < 5_000:
        return "STRONGER_B"
    return "UNRESOLVED"


def main() -> None:
    workers = int(os.environ.get("S2B_WORKERS", "4"))
    print(f"S2b Arena: 2 pairings x {len(FROZEN_SEEDS)} seeds x 2 rotations = 256 matches")

    # seed registry extension check
    sys.path.insert(0, str(REPO / "scripts"))
    import s0_seed_registry as reg
    reg.S0_SEGMENT = range(5_800_192, 5_800_256)
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
        cis = bootstrap(blocks)
        v95 = verdict(cis["descriptive_95"])
        v975 = verdict(cis["decision_97_5"])
        summaries.append({
            "pairing_id": spec["id"],
            "primary": spec["primary"][0], "secondary": spec["secondary"][0],
            "total_matches": len(tasks), "wins": wins, "ties": ties,
            "losses": len(tasks) - wins - ties, "center_bps": center,
            "ci_descriptive_95_bps": cis["descriptive_95"],
            "ci_decision_97_5_bps": cis["decision_97_5"],
            "verdict_descriptive_95": v95, "verdict_decision_97_5": v975,
            "mean_plies": sum(r["completed_plies"] for r in results.values()) / len(results),
            "wall_total_s": round(time.time() - t0, 1),
        })
        print(f"  {spec['id']}: W{wins}-T{ties}-L{len(tasks)-wins-ties} center {center:.1f} "
              f"[97.5% CI {cis['decision_97_5'][0]:.1f}, {cis['decision_97_5'][1]:.1f}] "
              f"-> {v975} ({summaries[-1]['wall_total_s']}s)", flush=True)

    # ---- frozen decision table ----
    by_id = {s["pairing_id"]: s for s in summaries}
    v_n1 = by_id["p1_overlay_vs_n1"]["verdict_decision_97_5"]
    v_h = by_id["p2_overlay_vs_heuristic"]["verdict_decision_97_5"]

    if v_n1 == "STRONGER_A":
        if v_h in ("STRONGER_A", "UNRESOLVED"):
            verdict_str = "CARRIER_IMPROVEMENT_CONFIRMED"
        else:
            verdict_str = "CARRIER_GAIN_ONLY"
    elif v_n1 == "UNRESOLVED":
        verdict_str = "UNRESOLVED"
    else:
        verdict_str = "REFUTED"
    reference_challenge = v_h == "STRONGER_A"

    result = {
        "format": "effective-splendor-s2b-result",
        "version": 1,
        "experiment_id": "s2b-n1-buy-overlay-v1",
        "design_doc": "docs/s2b-n1-buy-overlay.md @ ff7a4f1 (DESIGN_V2 APPROVED/FROZEN)",
        "contract": {
            "frozen_seeds": FROZEN_SEEDS, "rotations": 2,
            "pairings": [p["id"] for p in PAIRINGS],
            "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                          "unit": "paired seed block"},
            "ci_levels": CI_LEVELS,
            "decision_ci": "decision_97_5 (Bonferroni for 2 comparisons)",
            "candidate": "exact n1 args + --heuristic-buy-overlay (fail-closed identity)",
        },
        "pairings": summaries,
        "decision": {
            "vs_n1": v_n1, "vs_heuristic": v_h,
            "verdict": verdict_str,
            "reference_challenge_signal": reference_challenge,
            "primary_reference_change": False,
            "wording_rules": [
                "UNRESOLVED means evidence insufficient to separate; NOT equivalence.",
                "No outcome changes the primary reference or promotion state.",
                "CARRIER_GAIN_ONLY is a valuable engineering result, never conflated with REFUTED.",
            ],
        },
        "splendor_exe_sha256": file_sha256(SPLN),
    }
    RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nVERDICT: {verdict_str} (vs n1: {v_n1}; vs heuristic: {v_h}; "
          f"reference_challenge_signal: {reference_challenge})")
    print(f"Result: {RESULT}")


if __name__ == "__main__":
    main()
