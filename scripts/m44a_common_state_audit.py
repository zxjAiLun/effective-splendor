"""M44A Post-Hoc Common-State Action Audit and Family Margin Decomposition.

Evaluates up to 200 unique decision contexts across 10 evaluator profiles:
  - FULL (control)
  - DROP_SCORE, DROP_ENGINE, DROP_LIQUIDITY, DROP_CONVERTIBILITY, ZERO_PROGRESS
  - ONLY_SCORE, ONLY_ENGINE, ONLY_LIQUIDITY, ONLY_CONVERTIBILITY

Decomposes the exact action margin a* (best) vs b* (runner-up) into:
  FULL margin = terminal margin + F1 margin + F2 margin + F3 margin + F4 margin
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
SPLN = REPO / "target/release/splendor.exe"
ARENA_ROOT = REPO / "local-artifacts/m44a-arena"
OUT_ROOT = REPO / "local-artifacts/m44a-arena"

SAMPLE_SEED = 20_260_703
SAMPLE_COUNT = 4
DEPTH_TURNS = 1
MAX_NODES = 1

PROFILES = [
    "full",
    "drop_score",
    "drop_engine",
    "drop_liquidity",
    "drop_convertibility",
    "zero_progress",
    "only_score",
    "only_engine",
    "only_liquidity",
    "only_convertibility",
]


def run_cmd_fail_closed(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(cmd)}\nstderr={res.stderr}")
    return res.stdout


def analyze_context(rpl_path: Path, ply: int, profile: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    tmp_path.unlink(missing_ok=True)
    try:
        run_cmd_fail_closed([
            str(SPLN), "analyze-replay-player-view",
            "--input", str(rpl_path),
            "--ply", str(ply),
            "--sample-seed", str(SAMPLE_SEED),
            "--sample-count", str(SAMPLE_COUNT),
            "--max-depth-turns", str(DEPTH_TURNS),
            "--max-nodes", str(MAX_NODES),
            "--attribution-profile", profile,
            "--out", str(tmp_path),
        ])
        doc = json.loads(tmp_path.read_text(encoding="utf-8"))
        return doc
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="M44A Post-Hoc Common-State Action Audit")
    parser.add_argument("--max-contexts", type=int, default=200)
    args = parser.parse_args()

    print("M44A Common-State Action Audit started...", flush=True)
    t0 = time.time()

    # Find replays in deterministic order
    replay_paths = sorted(list(ARENA_ROOT.glob("**/match-replay.json")))
    if not replay_paths:
        raise RuntimeError("No match-replay.json files found in ARENA_ROOT")

    contexts = []
    seen_identities = set()

    print(f"Scanning replays for up to {args.max_contexts} unique decision contexts...", flush=True)
    for rpl_path in replay_paths:
        rpl = json.loads(rpl_path.read_text(encoding="utf-8"))
        steps = rpl.get("steps", [])
        # Sample across plies
        for ply in range(0, min(len(steps), 50), 3):
            step = steps[ply]
            recorded_actor = step["actor"]
            recorded_action = step["action"]

            # Analyze with FULL to extract authoritative identity hashes
            try:
                full_doc = analyze_context(rpl_path, ply, "full")
            except Exception as e:
                raise RuntimeError(f"Analysis failed on {rpl_path} ply {ply}: {e}")

            source = full_doc["source"]
            obs_hash = source["observation_hash"]
            hist_hash = source["visible_history_hash"]
            info_hash = source["information_set_hash"]

            triple_key = f"{obs_hash}:{hist_hash}:{info_hash}"
            if triple_key not in seen_identities:
                seen_identities.add(triple_key)
                contexts.append({
                    "context_idx": len(contexts),
                    "replay_path": str(rpl_path),
                    "ply": ply,
                    "recorded_actor": recorded_actor,
                    "recorded_action": recorded_action,
                    "observation_hash": obs_hash,
                    "visible_history_hash": hist_hash,
                    "information_set_hash": info_hash,
                    "full_doc": full_doc,
                })
                if len(contexts) >= args.max_contexts:
                    break
        if len(contexts) >= args.max_contexts:
            break

    n_ctx = len(contexts)
    print(f"Collected {n_ctx} unique authoritative decision contexts in {time.time() - t0:.1f}s.", flush=True)

    # 2. Evaluate all 10 profiles on every context
    t_eval = time.time()
    results_by_profile = {p: [] for p in PROFILES}
    source_reproduction_checks = []

    for c in contexts:
        rpl_path = Path(c["replay_path"])
        ply = c["ply"]
        # Determine source agent profile from replay path
        # Directory structure: pairing_id / block-xx / rX
        # r0: seat 0 is primary, seat 1 is secondary
        # r1: seat 0 is secondary, seat 1 is primary
        is_r0 = "/r0/" in str(rpl_path).replace("\\", "/")
        actor = c["recorded_actor"]

        parts = str(rpl_path).replace("\\", "/").split("/")
        pairing_id = [p for p in parts if "_vs_full" in p][0]

        if is_r0:
            agent_seat0 = pairing_id.replace("_vs_full", "")
            agent_seat1 = "full"
        else:
            agent_seat0 = "full"
            agent_seat1 = pairing_id.replace("_vs_full", "")

        recorded_profile = agent_seat0 if actor == 0 else agent_seat1

        for p in PROFILES:
            if p == "full":
                doc = c["full_doc"]
            else:
                doc = analyze_context(rpl_path, ply, p)
            results_by_profile[p].append(doc)

            # Check source action reproduction if profile matches recorded agent
            if p == recorded_profile:
                reproduced = (doc["result"]["action"] == c["recorded_action"])
                if not reproduced:
                    raise RuntimeError(
                        f"Source action reproduction failed on {rpl_path} ply {ply} profile {p}: "
                        f"recomputed {doc['result']['action']} != recorded {c['recorded_action']}"
                    )
                source_reproduction_checks.append(reproduced)

    print(f"Evaluated all 10 profiles on {n_ctx} contexts in {time.time() - t_eval:.1f}s.", flush=True)
    assert len(source_reproduction_checks) == n_ctx, f"expected {n_ctx} checks, got {len(source_reproduction_checks)}"
    assert all(source_reproduction_checks), "All source actions must reproduce exactly"

    # 3. Disagreement rates relative to FULL
    disagreement_rates = {}
    winner_change_rates = {}

    for p in ["drop_score", "drop_engine", "drop_liquidity", "drop_convertibility", "zero_progress"]:
        diffs = sum(
            1 for i in range(n_ctx)
            if results_by_profile[p][i]["result"]["action"] != results_by_profile["full"][i]["result"]["action"]
        )
        rate = diffs / n_ctx
        disagreement_rates[f"{p}_vs_full"] = rate
        winner_change_rates[f"dropping_{p.replace('drop_', '')}_changes_action_rate"] = rate

    for p in ["only_score", "only_engine", "only_liquidity", "only_convertibility"]:
        agreed = sum(
            1 for i in range(n_ctx)
            if results_by_profile[p][i]["result"]["action"] == results_by_profile["full"][i]["result"]["action"]
        )
        disagreement_rates[f"{p}_agreement_with_full"] = agreed / n_ctx

    # 4. Family Margin Decomposition (Section 25)
    margin_decompositions = {
        "f1_score": [],
        "f2_engine": [],
        "f3_liquidity": [],
        "f4_convertibility": [],
        "terminal": [],
        "full": [],
    }

    legal_counts = []
    terminal_child_contexts = 0

    for i in range(n_ctx):
        full_res = results_by_profile["full"][i]["result"]
        aggs = full_res["action_aggregates"]
        root_player = full_res["root_player"]
        n_actions = len(aggs)
        legal_counts.append(n_actions)

        # Check if any child was terminal
        if results_by_profile["full"][i]["result"]["stats"]["terminal_children"] > 0:
            terminal_child_contexts += 1

        if n_actions < 2:
            continue

        # Sort actions by FULL utility
        sorted_indices = sorted(
            range(n_actions),
            key=lambda idx: (aggs[idx]["utility_sum_by_player"][root_player], -idx),
            reverse=True,
        )
        best_idx = sorted_indices[0]
        runner_up_idx = sorted_indices[1]

        best_action = aggs[best_idx]["action"]
        runner_up_action = aggs[runner_up_idx]["action"]

        # Helper to get utility of an action under a profile
        def get_action_utility(p_name: str, action: Any) -> int:
            p_aggs = results_by_profile[p_name][i]["result"]["action_aggregates"]
            for agg in p_aggs:
                if agg["action"] == action:
                    return agg["utility_sum_by_player"][root_player]
            raise ValueError(f"Action not found in {p_name}")

        u_full_best = get_action_utility("full", best_action)
        u_full_run = get_action_utility("full", runner_up_action)
        margin_full = u_full_best - u_full_run

        u_zero_best = get_action_utility("zero_progress", best_action)
        u_zero_run = get_action_utility("zero_progress", runner_up_action)
        margin_term = u_zero_best - u_zero_run

        u_f1_best = get_action_utility("only_score", best_action)
        u_f1_run = get_action_utility("only_score", runner_up_action)
        margin_f1 = u_f1_best - u_f1_run

        u_f2_best = get_action_utility("only_engine", best_action)
        u_f2_run = get_action_utility("only_engine", runner_up_action)
        margin_f2 = u_f2_best - u_f2_run

        u_f3_best = get_action_utility("only_liquidity", best_action)
        u_f3_run = get_action_utility("only_liquidity", runner_up_action)
        margin_f3 = u_f3_best - u_f3_run

        u_f4_best = get_action_utility("only_convertibility", best_action)
        u_f4_run = get_action_utility("only_convertibility", runner_up_action)
        margin_f4 = u_f4_best - u_f4_run

        # Exact integer identity check: FULL margin == term + f1 + f2 + f3 + f4
        expected_sum = margin_term + margin_f1 + margin_f2 + margin_f3 + margin_f4
        if margin_full != expected_sum:
            raise RuntimeError(
                f"Margin linearity identity broken at context {i}: "
                f"full={margin_full} != sum={expected_sum} "
                f"(term={margin_term}, f1={margin_f1}, f2={margin_f2}, f3={margin_f3}, f4={margin_f4})"
            )

        margin_decompositions["full"].append(margin_full)
        margin_decompositions["terminal"].append(margin_term)
        margin_decompositions["f1_score"].append(margin_f1)
        margin_decompositions["f2_engine"].append(margin_f2)
        margin_decompositions["f3_liquidity"].append(margin_f3)
        margin_decompositions["f4_convertibility"].append(margin_f4)

    # Compute statistics per family
    family_margin_stats = {}
    for fam, vals in margin_decompositions.items():
        arr = np.array(vals, dtype=np.float64)
        abs_arr = np.abs(arr)
        family_margin_stats[fam] = {
            "mean_margin": float(np.mean(arr)),
            "median_margin": float(np.median(arr)),
            "mean_abs_contribution": float(np.mean(abs_arr)),
            "p90_abs_contribution": float(np.percentile(abs_arr, 90)),
            "positive_sign_rate": float(np.mean(arr > 0)),
            "zero_rate": float(np.mean(arr == 0)),
        }

    # Contexts identity digest & sample composition (Repair 1)
    EXPECTED_CANONICAL_IDENTITIES_SHA = "122f3d825bdabb59604552ea00383d5db0886f66bd4019a75ce1932b5ebb53ad"

    identity_records = [
        {
            "context_idx": c["context_idx"],
            "ply": c["ply"],
            "recorded_actor": c["recorded_actor"],
            "observation_hash": c["observation_hash"],
            "visible_history_hash": c["visible_history_hash"],
            "information_set_hash": c["information_set_hash"],
        }
        for c in contexts
    ]
    canonical_identities_sha = hashlib.sha256(
        json.dumps(identity_records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    if canonical_identities_sha != EXPECTED_CANONICAL_IDENTITIES_SHA:
        raise RuntimeError(
            f"Context identity digest mismatch: expected {EXPECTED_CANONICAL_IDENTITIES_SHA}, "
            f"got {canonical_identities_sha}"
        )

    # Sample composition metrics
    contexts_by_pairing = {}
    contexts_by_profile = {}
    distinct_replays = set()

    for c in contexts:
        r_path = c["replay_path"].replace("\\", "/")
        distinct_replays.add(r_path)
        parts = r_path.split("/")
        pairing_id = [p for p in parts if "_vs_full" in p][0]
        contexts_by_pairing[pairing_id] = contexts_by_pairing.get(pairing_id, 0) + 1

        is_r0 = "/r0/" in r_path
        actor = c["recorded_actor"]
        if is_r0:
            agent_seat0 = pairing_id.replace("_vs_full", "")
            agent_seat1 = "full"
        else:
            agent_seat0 = "full"
            agent_seat1 = pairing_id.replace("_vs_full", "")
        rec_prof = agent_seat0 if actor == 0 else agent_seat1
        contexts_by_profile[rec_prof] = contexts_by_profile.get(rec_prof, 0) + 1

    audit_summary = {
        "format": "effective-splendor-m44a-common-state-audit",
        "version": 1,
        "audited_contexts_count": n_ctx,
        "canonical_contexts_identity_sha256": canonical_identities_sha,
        "sample_composition": {
            "total_contexts": n_ctx,
            "contributing_replays_count": len(distinct_replays),
            "contexts_by_pairing": contexts_by_pairing,
            "contexts_by_recorded_profile": contexts_by_profile,
        },
        "source_action_reproduction": {
            "matching_source_checks": len(source_reproduction_checks),
            "reproduced": sum(source_reproduction_checks),
            "reproduction_rate": 1.0,
            "pass": True,
        },
        "disagreement_rates_vs_full": disagreement_rates,
        "winner_change_rates": winner_change_rates,
        "family_margin_decomposition": family_margin_stats,
        "legal_actions_distribution": {
            "mean": float(np.mean(legal_counts)),
            "min": int(np.min(legal_counts)),
            "max": int(np.max(legal_counts)),
            "median": float(np.median(legal_counts)),
        },
        "fraction_contexts_with_terminal_child": terminal_child_contexts / n_ctx,
    }

    out_file = OUT_ROOT / "m44a-common-state-audit.json"
    out_file.write_text(json.dumps(audit_summary, indent=2), encoding="utf-8")
    print(f"Common-state audit finished in {time.time() - t0:.1f}s. Summary written to {out_file}.", flush=True)
    print(json.dumps(audit_summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
