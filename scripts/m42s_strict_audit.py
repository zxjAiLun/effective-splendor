"""M42S Strict Fail-Closed Common-State Action Audit (Repair 1).

Implements:
  - Context identity = (observation_hash, visible_history_hash, information_set_hash)
  - Deterministic replay sorting and sampling
  - Any probe/analyze error -> FAIL CLOSED (no except continue)
  - Every context must have exactly 5 budget results (n1, n50, n200, n500, n2000)
  - Source action reproduction check for matching search agent: source_action_reproduced = N/N
  - Output frozen context identity list + SHA256
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SPLN = REPO / "target/release/splendor.exe"
ARENA_ROOT = REPO / "local-artifacts/m42s-arena"
RESULT_JSON = REPO / "benchmarks/m42s-search-gap-diagnostic-v1.result.json"

M07_SAMPLE_SEED = 20_260_703
M07_SAMPLE_COUNT = 4
M07_DEPTH_TURNS = 1
BUDGETS = [1, 50, 200, 500, 2000]


def run_cmd_fail_closed(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(cmd)}\nstderr={res.stderr}")
    return res.stdout


def main() -> None:
    print("Starting M42S Strict Fail-Closed Common-State Action Audit...", flush=True)
    t0 = time.time()

    # Deterministically sort replay paths from accepted n2000 pairings
    replay_paths = sorted(list((ARENA_ROOT / "n2000_vs_n1").glob("**/match-replay.json")))
    if not replay_paths:
        raise RuntimeError("No n2000_vs_n1 replays found for audit")

    contexts = []
    seen_identities = set()

    # Sample deterministically from first 16 replays, every 4th ply
    for rpl_path in replay_paths[:16]:
        rpl_text = rpl_path.read_text(encoding="utf-8")
        rpl = json.loads(rpl_text)

        # In n2000_vs_n1:
        # If r0: seat 0 is n2000 (even plies).
        # If r1: seat 1 is n2000 (odd plies).
        is_r0 = "/r0/" in str(rpl_path).replace("\\", "/")
        matching_seat = 0 if is_r0 else 1

        for ply in range(0, min(len(rpl["steps"]), 40), 4):
            step = rpl["steps"][ply]
            recorded_actor = step["actor"]
            recorded_action = step["action"]

            # Emit observation via probe-legal
            out = run_cmd_fail_closed([
                str(SPLN), "probe-legal", "--emit-observation",
                "--source-replay", str(rpl_path),
                "--branch-ply", str(ply),
            ])
            doc = json.loads(out)
            obs_hash = doc["observation_hash"]
            state_hash = doc["state_hash"]

            # Check matching actor
            is_matching_source = (recorded_actor == matching_seat)

            # Analyze with n2000 to get authoritative history and info set hashes
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            tmp_path.unlink(missing_ok=True)
            try:
                run_cmd_fail_closed([
                    str(SPLN), "analyze-replay-player-view",
                    "--input", str(rpl_path),
                    "--ply", str(ply),
                    "--sample-seed", str(M07_SAMPLE_SEED),
                    "--sample-count", str(M07_SAMPLE_COUNT),
                    "--max-depth-turns", str(M07_DEPTH_TURNS),
                    "--max-nodes", "2000",
                    "--out", str(tmp_path),
                ])
                analysis_doc = json.loads(tmp_path.read_text(encoding="utf-8"))
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

            source_meta = analysis_doc["source"]
            # Authoritative assertion: probe-legal observation_hash must match analysis source
            if source_meta["observation_hash"] != obs_hash:
                raise RuntimeError(
                    f"Observation hash mismatch in {rpl_path} ply {ply}: "
                    f"probe says {obs_hash}, analysis source says {source_meta['observation_hash']}"
                )

            # Direct authoritative hashes from Rust belief/search pipeline
            history_hash = source_meta["visible_history_hash"]
            info_set_hash = source_meta["information_set_hash"]

            identity_key = f"{obs_hash}:{history_hash}:{info_set_hash}"
            if identity_key not in seen_identities:
                seen_identities.add(identity_key)
                contexts.append({
                    "context_index": len(contexts),
                    "replay_path": str(rpl_path),
                    "ply": ply,
                    "recorded_actor": recorded_actor,
                    "recorded_action": recorded_action,
                    "is_matching_source": is_matching_source,
                    "observation_hash": obs_hash,
                    "state_hash": state_hash,
                    "history_hash": history_hash,
                    "info_set_hash": info_set_hash,
                })
                if len(contexts) >= 100:
                    break
        if len(contexts) >= 100:
            break

    print(f"Collected {len(contexts)} unique strict-identity contexts.", flush=True)

    # Re-run all 5 search budgets on each context
    actions_by_budget = {b: [] for b in BUDGETS}
    nodes_by_budget = {b: [] for b in BUDGETS}
    latencies_by_budget = {b: [] for b in BUDGETS}
    source_reproduction_checks = []

    for c in contexts:
        rpl_path = c["replay_path"]
        ply = c["ply"]
        for b in BUDGETS:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            tmp_path.unlink(missing_ok=True)
            try:
                t0_call = time.time()
                run_cmd_fail_closed([
                    str(SPLN), "analyze-replay-player-view",
                    "--input", str(rpl_path),
                    "--ply", str(ply),
                    "--sample-seed", str(M07_SAMPLE_SEED),
                    "--sample-count", str(M07_SAMPLE_COUNT),
                    "--max-depth-turns", str(M07_DEPTH_TURNS),
                    "--max-nodes", str(b),
                    "--out", str(tmp_path),
                ])
                lat_ms = (time.time() - t0_call) * 1000.0
                doc = json.loads(tmp_path.read_text(encoding="utf-8"))
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

            act = doc["result"]["action"]
            stats = doc["result"]["stats"]
            actions_by_budget[b].append(act)
            nodes_by_budget[b].append(stats["nodes_visited"])
            latencies_by_budget[b].append(lat_ms)

            # Check source action reproduction on n2000
            if b == 2000 and c["is_matching_source"]:
                reproduced = (act == c["recorded_action"])
                if not reproduced:
                    raise RuntimeError(
                        f"Source action reproduction failed at {rpl_path} ply {ply}: "
                        f"recomputed {act} != recorded {c['recorded_action']}"
                    )
                source_reproduction_checks.append(reproduced)

    # Fail closed if any budget result is missing
    n_ctx = len(contexts)
    for b in BUDGETS:
        if len(actions_by_budget[b]) != n_ctx:
            raise RuntimeError(f"Budget {b} produced {len(actions_by_budget[b])} != {n_ctx} results")

    # Pairwise disagreement calculation (fail-closed if length mismatch)
    def compute_disagreement(b1: int, b2: int) -> tuple[int, float]:
        acts1 = actions_by_budget[b1]
        acts2 = actions_by_budget[b2]
        if len(acts1) != n_ctx or len(acts2) != n_ctx:
            raise RuntimeError(f"Length mismatch: {len(acts1)} vs {len(acts2)}")
        diffs = sum(1 for a1, a2 in zip(acts1, acts2) if a1 != a2)
        return diffs, diffs / n_ctx

    disagreements = {}
    for pair in [(1, 50), (50, 200), (200, 500), (500, 2000), (1, 2000)]:
        count, rate = compute_disagreement(pair[0], pair[1])
        disagreements[f"n{pair[0]}_vs_n{pair[1]}"] = {
            "disagreements": count,
            "total_contexts": n_ctx,
            "disagreement_rate": rate,
        }

    # Identical across all 5
    identical_count = sum(
        1 for i in range(n_ctx)
        if len({json.dumps(actions_by_budget[b][i], sort_keys=True) for b in BUDGETS}) == 1
    )

    # Compute stats
    import numpy as np
    compute_stats = {}
    for b in BUDGETS:
        lats = np.array(latencies_by_budget[b])
        nv = np.array(nodes_by_budget[b])
        compute_stats[f"n{b}"] = {
            "offline_analysis_wall_time_p50_ms": float(np.percentile(lats, 50)),
            "offline_analysis_wall_time_p90_ms": float(np.percentile(lats, 90)),
            "offline_analysis_wall_time_mean_ms": float(np.mean(lats)),
            "nodes_visited_mean": float(np.mean(nv)),
            "nodes_visited_p50": float(np.percentile(nv, 50)),
            "nodes_visited_max": float(np.max(nv)),
        }

    # Contexts identity digest
    context_identities_bytes = json.dumps(contexts, sort_keys=True).encode("utf-8")
    contexts_digest = hashlib.sha256(context_identities_bytes).hexdigest()

    audit_summary = {
        "format": "effective-splendor-m42s-strict-common-state-action-audit",
        "version": 1,
        "contexts_count": n_ctx,
        "contexts_identity_sha256": contexts_digest,
        "source_action_reproduction": {
            "matching_source_contexts_checked": len(source_reproduction_checks),
            "matching_source_contexts_reproduced": sum(source_reproduction_checks),
            "reproduction_rate": 1.0 if source_reproduction_checks else None,
            "pass": all(source_reproduction_checks),
        },
        "identical_action_count_all_budgets": identical_count,
        "identical_action_rate_all_budgets": identical_count / n_ctx,
        "disagreement_rates": disagreements,
        "compute_and_offline_analysis_wall_time": compute_stats,
    }

    # Merge into benchmarks result JSON
    if RESULT_JSON.is_file():
        res = json.loads(RESULT_JSON.read_text(encoding="utf-8"))
        res["common_state_action_audit"] = audit_summary
        RESULT_JSON.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"Updated {RESULT_JSON} with strict audit summary.", flush=True)

    print(f"Strict audit complete in {time.time() - t0:.1f}s.")
    print(json.dumps(audit_summary, indent=2))


if __name__ == "__main__":
    main()
