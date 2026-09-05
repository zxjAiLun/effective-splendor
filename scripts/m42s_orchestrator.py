"""M42S Search Gap Diagnostic Orchestrator (Revision 1).

Executes the frozen 9 pairings across 64 paired seed blocks x 2 seat rotations = 1,152 physical matches.
Measures:
  - Strength: score (bps), W/D/L, paired-block bootstrap 95% CIs (BOOTSTRAP_SEED = 42_270_001, 10k resamples)
  - Compute: nodes_visited, nodes_expanded, leaf_evaluations, continuation_searches, budget consumption ratio
  - Wall Latency: p50, p90, p95, mean ms
  - Post-hoc Common-State Action Audit: action disagreement rates across budgets on identical decision contexts
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))

SPLN = REPO / "target/release/splendor.exe"
CATALOG = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
OUT_ROOT = REPO / "local-artifacts/m42s-arena"
M25_D2_CHECKPOINT = REPO / "local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"

# Frozen contract constants
BOOTSTRAP_SEED = 42_270_001
BOOTSTRAP_RESAMPLES = 10_000
M07_SAMPLE_SEED = 20_260_703
M07_SAMPLE_COUNT = 4
M07_DEPTH_TURNS = 1
FROZEN_SEEDS = list(range(5_300_000, 5_300_064))  # 64 paired seed blocks

PAIRING_SPECS = [
    # Family A: Search-gain comparisons (vs static-successor baseline n1)
    {"id": "n50_vs_n1", "primary": ("search", 50), "secondary": ("search", 1)},
    {"id": "n200_vs_n1", "primary": ("search", 200), "secondary": ("search", 1)},
    {"id": "n500_vs_n1", "primary": ("search", 500), "secondary": ("search", 1)},
    {"id": "n2000_vs_n1", "primary": ("search", 2000), "secondary": ("search", 1)},
    # Family B: Direct-neural crossover comparisons (vs d2-direct)
    {"id": "n1_vs_d2", "primary": ("search", 1), "secondary": ("neural", "D2")},
    {"id": "n50_vs_d2", "primary": ("search", 50), "secondary": ("neural", "D2")},
    {"id": "n200_vs_d2", "primary": ("search", 200), "secondary": ("neural", "D2")},
    {"id": "n500_vs_d2", "primary": ("search", 500), "secondary": ("neural", "D2")},
    {"id": "n2000_vs_d2", "primary": ("search", 2000), "secondary": ("neural", "D2")},
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def agent_config(agent_desc: tuple[str, Any]) -> tuple[dict[str, Any], str]:
    kind, val = agent_desc
    if kind == "search":
        nodes = int(val)
        name = f"det-s4-d1-n{nodes}"
        cmd = {
            "program": str(SPLN),
            "args": [
                "agent-determinization",
                "--sample-seed", str(M07_SAMPLE_SEED),
                "--sample-count", str(M07_SAMPLE_COUNT),
                "--max-depth-turns", str(M07_DEPTH_TURNS),
                "--max-nodes", str(nodes),
                "--runtime-name", name,
                "--runtime-version", "1",
            ],
        }
        return cmd, name
    elif kind == "neural":
        name = "d2-direct"
        cmd = {
            "program": sys.executable,
            "args": [
                "-m", "splendor_gpu.m35a_agent",
                "--model-id", "M25-D2-v2",
                "--catalog", str(CATALOG),
                "--device", "cuda",
            ],
        }
        return cmd, name
    raise ValueError(f"unknown agent kind {kind}")


def build_match_config(
    game_id: str,
    seed: int,
    primary_desc: tuple[str, Any],
    secondary_desc: tuple[str, Any],
    rotation: int,
) -> tuple[dict[str, Any], int]:
    """rotation 0: primary is seat 0, secondary is seat 1.
    rotation 1: secondary is seat 0, primary is seat 1.
    Returns (config, primary_seat).
    """
    cmd_p, name_p = agent_config(primary_desc)
    cmd_s, name_s = agent_config(secondary_desc)

    if rotation == 0:
        agents = [cmd_p, cmd_s]
        primary_seat = 0
    else:
        agents = [cmd_s, cmd_p]
        primary_seat = 1

    cfg = {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
        "agents": agents,
    }
    return cfg, primary_seat


def run_one_match(
    pairing_id: str,
    block_idx: int,
    seed: int,
    rotation: int,
    primary_desc: tuple[str, Any],
    secondary_desc: tuple[str, Any],
    work_dir: Path,
) -> dict[str, Any]:
    game_id = f"m42s-{pairing_id}-b{block_idx:02d}-s{seed}-r{rotation}"
    match_dir = work_dir / f"block-{block_idx:02d}-seed-{seed}" / f"r{rotation}"
    match_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = match_dir / "match-config.json"
    rep_path = match_dir / "arena-report.json"
    rpl_path = match_dir / "match-replay.json"

    cfg, primary_seat = build_match_config(game_id, seed, primary_desc, secondary_desc, rotation)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # If already completed cleanly, return cached result
    if rep_path.is_file() and rpl_path.is_file():
        try:
            report = json.loads(rep_path.read_text(encoding="utf-8"))
            if report.get("outcome", {}).get("status") == "completed":
                return parse_match_result(report, primary_seat, block_idx, rotation, rep_path, rpl_path)
        except Exception:
            pass

    cmd = [
        str(SPLN), "run-match",
        "--config", str(cfg_path),
        "--report-out", str(rep_path),
        "--replay-out", str(rpl_path),
    ]

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "training/m17_gpu") + os.pathsep + env.get("PYTHONPATH", "")

    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    wall_duration = time.time() - t0

    if res.returncode != 0:
        raise RuntimeError(
            f"Match {game_id} failed with exit code {res.returncode}: stderr={res.stderr} stdout={res.stdout}"
        )

    report = json.loads(rep_path.read_text(encoding="utf-8"))
    outcome = report.get("outcome", {})
    if outcome.get("status") != "completed":
        raise RuntimeError(f"Match {game_id} outcome not completed: {outcome}")

    result = parse_match_result(report, primary_seat, block_idx, rotation, rep_path, rpl_path)
    result["wall_duration_seconds"] = wall_duration
    return result


def parse_match_result(
    report: dict[str, Any],
    primary_seat: int,
    block_idx: int,
    rotation: int,
    rep_path: Path,
    rpl_path: Path,
) -> dict[str, Any]:
    outcome = report["outcome"]
    res = outcome["result"]
    winners = res["winners"]

    if primary_seat in winners:
        if len(winners) == 1:
            score_bps = 10_000
            won = True
            tied = False
        else:
            score_bps = 5_000
            won = False
            tied = True
    else:
        score_bps = 0
        won = False
        tied = False

    return {
        "block_idx": block_idx,
        "rotation": rotation,
        "primary_seat": primary_seat,
        "score_bps": score_bps,
        "won": won,
        "tied": tied,
        "lost": not won and not tied,
        "primary_final_score": res["scores"][primary_seat],
        "secondary_final_score": res["scores"][1 - primary_seat],
        "completed_plies": outcome["completed_plies"],
        "replay_path": str(rpl_path),
        "report_path": str(rep_path),
    }


def bootstrap_ci_95(block_scores: list[float], seed: int, resamples: int) -> tuple[float, float]:
    import numpy as np

    rng = np.random.RandomState(seed)
    n = len(block_scores)
    arr = np.array(block_scores, dtype=np.float64)
    # Generate bootstrap samples
    idx = rng.randint(0, n, size=(resamples, n))
    sample_means = np.mean(arr[idx], axis=1)
    lower = float(np.percentile(sample_means, 2.5))
    upper = float(np.percentile(sample_means, 97.5))
    return lower, upper


def run_pairing(
    pairing_spec: dict[str, Any],
    workers: int = 4,
) -> dict[str, Any]:
    pairing_id = pairing_spec["id"]
    work_dir = OUT_ROOT / pairing_id
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n>>> Running Pairing: {pairing_id} (64 blocks x 2 rotations = 128 matches)...", flush=True)
    t0 = time.time()

    tasks = []
    for b_idx, seed in enumerate(FROZEN_SEEDS):
        for rot in (0, 1):
            tasks.append((b_idx, seed, rot))

    results_by_task = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_task = {
            executor.submit(
                run_one_match,
                pairing_id,
                b_idx,
                seed,
                rot,
                pairing_spec["primary"],
                pairing_spec["secondary"],
                work_dir,
            ): (b_idx, rot)
            for b_idx, seed, rot in tasks
        }
        for future in concurrent.futures.as_completed(future_to_task):
            task_key = future_to_task[future]
            try:
                res = future.result()
                results_by_task[task_key] = res
            except Exception as e:
                print(f"Match task {task_key} failed: {e}", flush=True)
                raise e

    # Aggregate paired seed blocks
    block_scores = []
    wins = 0
    ties = 0
    losses = 0
    seat0_scores = []
    seat1_scores = []
    total_plies = []
    total_durations = []

    for b_idx in range(len(FROZEN_SEEDS)):
        r0 = results_by_task[(b_idx, 0)]
        r1 = results_by_task[(b_idx, 1)]
        blk_score = (r0["score_bps"] + r1["score_bps"]) / 2.0
        block_scores.append(blk_score)

        for r in (r0, r1):
            if r["won"]:
                wins += 1
            elif r["tied"]:
                ties += 1
            else:
                losses += 1
            total_plies.append(r["completed_plies"])
            if "wall_duration_seconds" in r:
                total_durations.append(r["wall_duration_seconds"])

        seat0_scores.append(r0["score_bps"])
        seat1_scores.append(r1["score_bps"])

    center_bps = sum(block_scores) / len(block_scores)
    ci_lower, ci_upper = bootstrap_ci_95(block_scores, BOOTSTRAP_SEED, BOOTSTRAP_RESAMPLES)
    elapsed = time.time() - t0

    pairing_summary = {
        "pairing_id": pairing_id,
        "primary": pairing_spec["primary"],
        "secondary": pairing_spec["secondary"],
        "total_matches": len(tasks),
        "completed_blocks": len(block_scores),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "center_bps": center_bps,
        "bootstrap_ci_95": [ci_lower, ci_upper],
        "seat0_mean_bps": sum(seat0_scores) / len(seat0_scores),
        "seat1_mean_bps": sum(seat1_scores) / len(seat1_scores),
        "mean_completed_plies": sum(total_plies) / len(total_plies),
        "mean_match_seconds": sum(total_durations) / max(1, len(total_durations)),
        "total_elapsed_seconds": elapsed,
    }
    print(
        f"Pairing {pairing_id} finished in {elapsed:.1f}s: "
        f"Score {center_bps:.1f} bps (95% CI: [{ci_lower:.1f}, {ci_upper:.1f}]), "
        f"W/T/L: {wins}/{ties}/{losses}",
        flush=True,
    )
    return pairing_summary


def post_hoc_common_state_action_audit(max_contexts: int = 100) -> dict[str, Any]:
    """Read-only common-state action audit across n1, n50, n200, n500, n2000 on unique decision contexts."""
    print("\n=======================================================", flush=True)
    print("Executing Post-Hoc Common-State Action Audit...", flush=True)
    print("=======================================================", flush=True)

    # Collect replays from accepted search pairings
    replays = list((OUT_ROOT / "n2000_vs_n1").glob("**/match-replay.json"))
    if not replays:
        replays = list(OUT_ROOT.glob("**/match-replay.json"))

    # Extract deduplicated decision contexts using Rust probe
    contexts = []
    seen_hashes = set()

    for rpl_path in replays[:10]:  # sample from first 10 replays
        try:
            rpl = json.loads(rpl_path.read_text(encoding="utf-8"))
            for ply in range(0, min(len(rpl["steps"]), 40), 4):  # sample every 4th ply
                out = subprocess.run(
                    [
                        str(SPLN), "probe-legal", "--emit-observation",
                        "--source-replay", str(rpl_path),
                        "--branch-ply", str(ply)
                    ],
                    capture_output=True, text=True, check=True
                )
                doc = json.loads(out.stdout)
                obs_hash = doc["observation_hash"]
                if obs_hash not in seen_hashes:
                    seen_hashes.add(obs_hash)
                    contexts.append({
                        "replay_path": str(rpl_path),
                        "ply": ply,
                        "observation_hash": obs_hash,
                        "legal_count": len(doc["legal_actions"]),
                    })
                    if len(contexts) >= max_contexts:
                        break
        except Exception as e:
            continue
        if len(contexts) >= max_contexts:
            break

    print(f"Extracted {len(contexts)} unique decision contexts.", flush=True)

    # Re-run all 5 search budgets on each context
    import tempfile
    import numpy as np

    budgets = [1, 50, 200, 500, 2000]
    actions_by_budget = {b: [] for b in budgets}
    nodes_visited_by_budget = {b: [] for b in budgets}
    nodes_expanded_by_budget = {b: [] for b in budgets}
    leaf_evals_by_budget = {b: [] for b in budgets}
    continuation_searches_by_budget = {b: [] for b in budgets}
    latencies_by_budget = {b: [] for b in budgets}

    for c in contexts:
        rpl_path = c["replay_path"]
        ply = c["ply"]
        for b in budgets:
            tmp_out = Path(tempfile.mktemp(suffix=".json"))
            cmd = [
                str(SPLN), "analyze-replay-player-view",
                "--input", str(rpl_path),
                "--ply", str(ply),
                "--sample-seed", str(M07_SAMPLE_SEED),
                "--sample-count", str(M07_SAMPLE_COUNT),
                "--max-depth-turns", str(M07_DEPTH_TURNS),
                "--max-nodes", str(b),
                "--out", str(tmp_out),
            ]
            t0 = time.time()
            res = subprocess.run(cmd, capture_output=True, text=True)
            lat_ms = (time.time() - t0) * 1000.0
            latencies_by_budget[b].append(lat_ms)

            if res.returncode == 0 and tmp_out.is_file():
                doc = json.loads(tmp_out.read_text(encoding="utf-8"))
                act = doc["result"]["action"]
                stats = doc["result"]["stats"]
                actions_by_budget[b].append(json.dumps(act, sort_keys=True))
                nodes_visited_by_budget[b].append(stats["nodes_visited"])
                nodes_expanded_by_budget[b].append(stats["nodes_expanded"])
                leaf_evals_by_budget[b].append(stats["leaf_evaluations"])
                continuation_searches_by_budget[b].append(stats["continuation_searches"])
                tmp_out.unlink()

    # Compute pairwise disagreement rates between budgets
    def disagreement_rate(b1: int, b2: int) -> float:
        acts1 = actions_by_budget[b1]
        acts2 = actions_by_budget[b2]
        if not acts1 or not acts2 or len(acts1) != len(acts2):
            return 0.0
        disagreements = sum(1 for a1, a2 in zip(acts1, acts2) if a1 != a2)
        return disagreements / len(acts1)

    # Identical action rate across all 5 budgets
    n_total = len(contexts)
    identical_all_5 = 0
    for i in range(n_total):
        distinct_acts = set(actions_by_budget[b][i] for b in budgets if i < len(actions_by_budget[b]))
        if len(distinct_acts) == 1:
            identical_all_5 += 1
    identical_action_rate = identical_all_5 / max(1, n_total)

    compute_stats = {}
    for b in budgets:
        lats = np.array(latencies_by_budget[b])
        nv = np.array(nodes_visited_by_budget[b])
        ne = np.array(nodes_expanded_by_budget[b])
        le = np.array(leaf_evals_by_budget[b])
        cs = np.array(continuation_searches_by_budget[b])

        budget_denom = cs * b
        consumption_ratio = float(np.mean(nv / np.maximum(1, budget_denom)))

        compute_stats[f"n{b}"] = {
            "latency_p50_ms": float(np.percentile(lats, 50)),
            "latency_p90_ms": float(np.percentile(lats, 90)),
            "latency_p95_ms": float(np.percentile(lats, 95)),
            "latency_mean_ms": float(np.mean(lats)),
            "nodes_visited_mean": float(np.mean(nv)),
            "nodes_visited_p50": float(np.percentile(nv, 50)),
            "nodes_visited_p90": float(np.percentile(nv, 90)),
            "nodes_visited_p95": float(np.percentile(nv, 95)),
            "nodes_visited_max": float(np.max(nv)),
            "nodes_expanded_mean": float(np.mean(ne)),
            "leaf_evaluations_mean": float(np.mean(le)),
            "continuation_searches_mean": float(np.mean(cs)),
            "budget_consumption_ratio": consumption_ratio,
        }

    audit_result = {
        "sampled_unique_contexts": len(contexts),
        "identical_action_rate_across_all_budgets": identical_action_rate,
        "disagreement_rates": {
            "n1_vs_n50": disagreement_rate(1, 50),
            "n50_vs_n200": disagreement_rate(50, 200),
            "n200_vs_n500": disagreement_rate(200, 500),
            "n500_vs_n2000": disagreement_rate(500, 2000),
            "n1_vs_n2000": disagreement_rate(1, 2000),
        },
        "compute_and_latency_by_budget": compute_stats,
    }
    return audit_result


def main() -> None:
    global FROZEN_SEEDS
    parser = argparse.ArgumentParser(description="M42S 1152-Match Arena Orchestrator")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--smoke", action="store_true", help="Run 1 block per pairing smoke")
    args = parser.parse_args()

    print("M42S Orchestrator started.", flush=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Seal and record provenance before execution
    provenance = {
        "m42s_baseline": "2fc2ba2",
        "splendor_exe_sha256": file_sha256(SPLN),
        "catalog_sha256": file_sha256(CATALOG),
        "d2_checkpoint_sha256": file_sha256(M25_D2_CHECKPOINT),
        "sample_seed": M07_SAMPLE_SEED,
        "sample_count": M07_SAMPLE_COUNT,
        "max_depth_turns": M07_DEPTH_TURNS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "frozen_seeds": FROZEN_SEEDS if not args.smoke else FROZEN_SEEDS[:1],
    }
    (OUT_ROOT / "m42s-provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    if args.smoke:
        print("RUNNING IN SMOKE MODE (1 seed block per pairing)...", flush=True)
        FROZEN_SEEDS = FROZEN_SEEDS[:1]

    t_all_start = time.time()
    pairings_results = []
    for spec in PAIRING_SPECS:
        res = run_pairing(spec, workers=args.workers)
        pairings_results.append(res)

    total_time = time.time() - t_all_start
    print(f"\nAll 9 pairings completed in {total_time:.1f}s.", flush=True)

    # Run post-hoc common-state action audit
    audit_data = post_hoc_common_state_action_audit()

    # Compile final diagnostic summary
    summary = {
        "format": "effective-splendor-m42s-diagnostic-summary",
        "version": 1,
        "total_pairings": len(PAIRING_SPECS),
        "total_matches": sum(p["total_matches"] for p in pairings_results),
        "total_elapsed_seconds": total_time,
        "provenance": provenance,
        "pairings": pairings_results,
        "common_state_action_audit": audit_data,
    }

    summary_path = OUT_ROOT / "m42s-final-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Summary written to {summary_path}.", flush=True)


if __name__ == "__main__":
    main()
