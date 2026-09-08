#!/usr/bin/env python3
"""S0 orchestrator: baseline calibration (Heuristic / n1 / M07).

Executes the frozen S0 DESIGN_V2 contract (docs/s0-baseline-calibration.md,
commit 825f042):

  3 pairings x 64 seeds (5_800_064..5_800_127) x 2 seat rotations = 384 matches
  paired-block bootstrap (10,000 resamples, seed 42_280_001)
  95% descriptive CI + 98.33% joint-decision CI (Bonferroni, 3 comparisons)
  agent-owned per-decision stats via --stats-out (search seats)
  result JSON -> benchmarks/s0-baseline-calibration-v1.result.json

Telemetry boundary (frozen): wall_ms per match (orchestrator subprocess
timing), decide_micros per search decision (agent-measured, excludes
transport), RootDeterminizationStatsV1 counters, terminal_child_ratio,
descriptive budget consumption. NO new search-side statistics.

Decision logic (frozen): STRONGER_X per pairing via the 98.33% CI;
reference naming only for a beats-both agent; UNRESOLVED keeps both
agents in the must-not-regress set; no equivalence wording.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
OUT_ROOT = REPO / "local-artifacts/s0-baseline-calibration"
RESULT_PATH = REPO / "benchmarks/s0-baseline-calibration-v1.result.json"

# ---- frozen contract constants ----
BOOTSTRAP_SEED = 42_280_001
BOOTSTRAP_RESAMPLES = 10_000
SAMPLE_SEED = 20_260_703  # == 20260703
SAMPLE_COUNT = 4
DEPTH_TURNS = 1
FROZEN_SEEDS = list(range(5_800_064, 5_800_128))  # 64 blocks
CI_LEVELS = {"descriptive_95": 95.0, "decision_98_33": 98.33}

AGENTS = {
    "heuristic-v1": ["agent-heuristic", "--seed", "20260812"],
    "det-s4-d1-n1": [
        "agent-determinization",
        "--sample-seed", str(SAMPLE_SEED),
        "--sample-count", str(SAMPLE_COUNT),
        "--max-depth-turns", str(DEPTH_TURNS),
        "--max-nodes", "1",
    ],
    "det-s4-d1-n2000": [
        "agent-determinization",
        "--sample-seed", str(SAMPLE_SEED),
        "--sample-count", str(SAMPLE_COUNT),
        "--max-depth-turns", str(DEPTH_TURNS),
        "--max-nodes", "2000",
    ],
}

# P1: heuristic vs n1 (never measured); P2: heuristic vs M07 (strong prior,
# different historical sample seed); P3: n1 vs M07 (M42S UNRESOLVED).
PAIRINGS = [
    {"id": "p1_heuristic_vs_n1", "primary": "heuristic-v1", "secondary": "det-s4-d1-n1"},
    {"id": "p2_heuristic_vs_m07", "primary": "heuristic-v1", "secondary": "det-s4-d1-n2000"},
    {"id": "p3_n1_vs_m07", "primary": "det-s4-d1-n1", "secondary": "det-s4-d1-n2000"},
]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_match_config(game_id: str, seed: int, primary: str, secondary: str, rotation: int,
                       stats_paths: dict[str, Path]):
    def agent_cmd(agent_id: str) -> dict:
        base = AGENTS[agent_id]
        args = list(base)
        if agent_id.startswith("det-") and agent_id in stats_paths:
            args += ["--stats-out", str(stats_paths[agent_id])]
        return {"program": str(SPLN), "args": args}

    if rotation == 0:
        agents = [agent_cmd(primary), agent_cmd(secondary)]
    else:
        agents = [agent_cmd(secondary), agent_cmd(primary)]
    return {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
        "agents": agents,
    }


def run_one_match(pairing_id: str, block_idx: int, seed: int, rotation: int,
                  primary: str, secondary: str, work_dir: Path) -> dict:
    game_id = f"s0-{pairing_id}-b{block_idx:02d}-s{seed}-r{rotation}"
    match_dir = work_dir / f"block-{block_idx:02d}-seed-{seed}" / f"r{rotation}"
    match_dir.mkdir(parents=True, exist_ok=True)
    stats_paths = {
        primary: match_dir / f"stats-seat{'0' if rotation == 0 else '1'}-{primary}.ndjson",
        secondary: match_dir / f"stats-seat{'1' if rotation == 0 else '0'}-{secondary}.ndjson",
    }
    # Only search agents get a stats path.
    stats_paths = {k: v for k, v in stats_paths.items() if k.startswith("det-")}
    for p in stats_paths.values():
        if p.exists():
            p.unlink()  # append-mode agent must start clean per match

    cfg = build_match_config(game_id, seed, primary, secondary, rotation, stats_paths)
    cfg_path = match_dir / "match-config.json"
    rep_path = match_dir / "arena-report.json"
    rpl_path = match_dir / "match-replay.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    if rep_path.is_file() and rpl_path.is_file():
        try:
            report = json.loads(rep_path.read_text(encoding="utf-8"))
            if report.get("outcome", {}).get("status") == "completed":
                return parse_match_result(report, primary, secondary, rotation,
                                          block_idx, rep_path, rpl_path, stats_paths,
                                          wall_s=None)
        except Exception:
            pass

    t0 = time.perf_counter()
    res = subprocess.run(
        [str(SPLN), "run-match", "--config", str(cfg_path),
         "--report-out", str(rep_path), "--replay-out", str(rpl_path)],
        capture_output=True, text=True,
    )
    wall_s = time.perf_counter() - t0
    if res.returncode != 0:
        raise RuntimeError(f"Match {game_id} exit {res.returncode}: {res.stderr[:2000]}")
    report = json.loads(rep_path.read_text(encoding="utf-8"))
    outcome = report.get("outcome", {})
    if outcome.get("status") != "completed":
        raise RuntimeError(f"Match {game_id} not completed: {outcome}")
    result = parse_match_result(report, primary, secondary, rotation, block_idx,
                                rep_path, rpl_path, stats_paths, wall_s=wall_s)
    return result


def parse_match_result(report: dict, primary: str, secondary: str, rotation: int,
                       block_idx: int, rep_path: Path, rpl_path: Path,
                       stats_paths: dict[str, Path], wall_s: float | None) -> dict:
    outcome = report["outcome"]
    res = outcome["result"]
    winners = res["winners"]
    # primary's seat: rotation 0 -> seat 0; rotation 1 -> seat 1.
    primary_seat = 0 if rotation == 0 else 1
    scores = res["scores"]
    if primary_seat in winners and len(winners) == 1:
        score_bps, won, tied = 10_000, True, False
    elif primary_seat in winners:
        score_bps, won, tied = 5_000, False, True
    else:
        score_bps, won, tied = 0, False, False

    # collect stats observations for search agents
    stats_obs: dict[str, list[dict]] = {}
    for agent_id, p in stats_paths.items():
        rows = []
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        stats_obs[agent_id] = rows

    return {
        "game_id": report["game_id"],
        "block_idx": block_idx,
        "rotation": rotation,
        "primary": primary,
        "secondary": secondary,
        "primary_seat": primary_seat,
        "score_bps": score_bps,
        "won": won,
        "tied": tied,
        "primary_final_score": scores[primary_seat],
        "secondary_final_score": scores[1 - primary_seat],
        "completed_plies": outcome["completed_plies"],
        "replay_final_hash": outcome["replay_final_hash"],
        "replay_path": str(rpl_path),
        "report_path": str(rep_path),
        "report_sha256": file_sha256(rep_path),
        "wall_s": wall_s,
        "stats": stats_obs,
    }


def bootstrap_cis(block_scores: list[float], seed: int, resamples: int) -> dict[str, list[float]]:
    import numpy as np

    rng = np.random.RandomState(seed)
    n = len(block_scores)
    arr = np.array(block_scores, dtype=np.float64)
    idx = rng.randint(0, n, size=(resamples, n))
    means = np.mean(arr[idx], axis=1)
    out = {}
    for label, level in CI_LEVELS.items():
        alpha = (100.0 - level) / 2.0
        out[label] = [float(np.percentile(means, alpha)),
                      float(np.percentile(means, 100.0 - alpha))]
    return out


def aggregate_stats(rows: list[dict]) -> dict:
    if not rows:
        return {"decisions": 0}
    micros = sorted(r["decide_micros"] for r in rows)
    cont = sum(r["stats"]["continuation_searches"] for r in rows)
    term = sum(r["stats"]["terminal_children"] for r in rows)
    nodes = sum(r["stats"]["nodes_visited"] for r in rows)
    # max_nodes is per-continuation; recover from pairing spec at call site if
    # needed for budget_consumption — pass it in via rows[0]... simpler: compute
    # ratios that don't need max_nodes here, and per-pairing consumption with
    # the known constant in the caller.
    def pct(q):
        k = min(len(micros) - 1, max(0, int(round(q * (len(micros) - 1)))))
        return micros[k]
    return {
        "decisions": len(rows),
        "decide_micros_mean": round(sum(micros) / len(micros), 1),
        "decide_micros_p50": pct(0.50),
        "decide_micros_p90": pct(0.90),
        "decide_micros_p95": pct(0.95),
        "decide_micros_max": micros[-1],
        "continuation_searches_total": cont,
        "terminal_children_total": term,
        "terminal_child_ratio": round(term / (cont + term), 6) if (cont + term) else None,
        "nodes_visited_total": nodes,
        "leaf_evaluations_total": sum(r["stats"]["leaf_evaluations"] for r in rows),
        "nodes_expanded_total": sum(r["stats"]["nodes_expanded"] for r in rows),
    }


def verdict_for(ci: list[float]) -> str:
    lower, upper = ci
    if lower > 5_000:
        return "STRONGER_A"
    if upper < 5_000:
        return "STRONGER_B"
    return "UNRESOLVED"


def run_pairing(spec: dict, workers: int) -> dict:
    pairing_id = spec["id"]
    primary, secondary = spec["primary"], spec["secondary"]
    work_dir = OUT_ROOT / pairing_id
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f">>> {pairing_id}: {primary} vs {secondary} (128 matches)...", flush=True)
    t0 = time.time()

    tasks = [(b, s, r) for b, s in enumerate(FROZEN_SEEDS) for r in (0, 1)]
    results: dict[tuple, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(run_one_match, pairing_id, b, s, r, primary, secondary, work_dir): (b, r)
            for b, s, r in tasks
        }
        for fut in concurrent.futures.as_completed(futs):
            key = futs[fut]
            results[key] = fut.result()

    block_scores = []
    wins = ties = losses = 0
    plies = []
    walls = []
    for b in range(len(FROZEN_SEEDS)):
        r0, r1 = results[(b, 0)], results[(b, 1)]
        block_scores.append((r0["score_bps"] + r1["score_bps"]) / 2.0)
    for r in results.values():
        wins += r["won"]
        ties += r["tied"]
        plies.append(r["completed_plies"])
        if r["wall_s"] is not None:
            walls.append(r["wall_s"])

    center = sum(block_scores) / len(block_scores)
    cis = bootstrap_cis(block_scores, BOOTSTRAP_SEED, BOOTSTRAP_RESAMPLES)
    verdict98 = verdict_for(cis["decision_98_33"])
    verdict95 = verdict_for(cis["descriptive_95"])

    # per-agent stats aggregation across all matches
    agent_rows: dict[str, list[dict]] = {primary: [], secondary: []}
    for r in results.values():
        for agent_id, rows in r["stats"].items():
            agent_rows.setdefault(agent_id, []).extend(rows)
    stats_summary = {}
    max_nodes = {"det-s4-d1-n1": 1, "det-s4-d1-n2000": 2000}
    for agent_id, rows in agent_rows.items():
        s = aggregate_stats(rows)
        if rows and agent_id in max_nodes:
            cont = s["continuation_searches_total"]
            if cont:
                s["budget_consumption_descriptive"] = round(
                    s["nodes_visited_total"] / (cont * max_nodes[agent_id]), 6)
        stats_summary[agent_id] = s

    elapsed = time.time() - t0
    summary = {
        "pairing_id": pairing_id,
        "primary": primary,
        "secondary": secondary,
        "total_matches": len(tasks),
        "wins": wins, "ties": ties, "losses": len(tasks) - wins - ties,
        "center_bps": center,
        "ci_descriptive_95_bps": cis["descriptive_95"],
        "ci_decision_98_33_bps": cis["decision_98_33"],
        "verdict_descriptive_95": verdict95,
        "verdict_decision_98_33": verdict98,
        "seat_scores_bps": {
            "r0": sum(results[(b, 0)]["score_bps"] for b in range(len(FROZEN_SEEDS))) / len(FROZEN_SEEDS),
            "r1": sum(results[(b, 1)]["score_bps"] for b in range(len(FROZEN_SEEDS))) / len(FROZEN_SEEDS),
        },
        "mean_plies": statistics.mean(plies),
        "wall_total_s": round(elapsed, 1),
        "agent_stats": stats_summary,
    }
    print(f"    {pairing_id}: W{wins}-T{ties}-L{summary['losses']} center {center:.1f} bps "
          f"[98.33% CI {cis['decision_98_33'][0]:.1f}, {cis['decision_98_33'][1]:.1f}] "
          f"-> {verdict98} ({elapsed:.0f}s)", flush=True)
    return summary


def decide_reference(pairing_summaries: list[dict]) -> dict:
    """Frozen decision logic (98.33% verdicts only)."""
    verdicts = {p["pairing_id"]: p["verdict_decision_98_33"] for p in pairing_summaries}
    # pairwise wins count per agent
    wins_over = {"heuristic-v1": 0, "det-s4-d1-n1": 0, "det-s4-d1-n2000": 0}
    for p in pairing_summaries:
        v = p["verdict_decision_98_33"]
        if v == "STRONGER_A":
            wins_over[p["primary"]] += 1
        elif v == "STRONGER_B":
            wins_over[p["secondary"]] += 1
    double_winner = [a for a, n in wins_over.items() if n == 2]
    unresolved_pairings = [pid for pid, v in verdicts.items() if v == "UNRESOLVED"]

    decision = {
        "pairwise_verdicts": verdicts,
        "wins_over": wins_over,
        "primary_reference": double_winner[0] if len(double_winner) == 1 else None,
        "unique_reference_named": len(double_winner) == 1,
        "unresolved_pairings": unresolved_pairings,
        "must_not_regress_set": ["heuristic-v1", "det-s4-d1-n1", "det-s4-d1-n2000"],
        "wording_rules": [
            "UNRESOLVED means evidence insufficient to separate; it does NOT mean equivalent.",
            "Equivalence/equality wording (e.g. 'n1 ~ M07') is forbidden; only 'unresolved at this budget'.",
            "A cheap development baseline may be selected only as an explicit cost choice with the strength gap unresolved.",
            "All outcomes passed the same validity gates; contradictions add diagnostics, not acceptance thresholds.",
        ],
    }
    return decision


def main() -> None:
    workers = int(os.environ.get("S0_WORKERS", "4"))
    print(f"S0 baseline calibration: {len(PAIRINGS)} pairings x {len(FROZEN_SEEDS)} seeds x 2 rotations")
    print(f"splendor binary: {SPLN} (sha256 {file_sha256(SPLN)[:16]}...)")

    t0 = time.time()
    pairing_summaries = [run_pairing(spec, workers) for spec in PAIRINGS]
    elapsed = time.time() - t0

    decision = decide_reference(pairing_summaries)
    result = {
        "format": "effective-splendor-s0-result",
        "version": 1,
        "experiment_id": "s0-baseline-calibration-v1",
        "design_doc": "docs/s0-baseline-calibration.md @ 825f042 (DESIGN_V2 APPROVED/FROZEN)",
        "contract": {
            "frozen_seeds": FROZEN_SEEDS,
            "rotations": 2,
            "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED,
                          "unit": "paired seed block"},
            "ci_levels": CI_LEVELS,
            "decision_ci": "decision_98_33 (Bonferroni for 3 comparisons)",
            "agents": AGENTS,
            "sample_seed": SAMPLE_SEED,
            "telemetry_boundary": "wall_s per match (orchestrator); decide_micros per search decision "
                                   "(agent-measured, in-process, excludes transport); "
                                   "RootDeterminizationStatsV1 counters; terminal_child_ratio "
                                   "(terminal root children share, NOT budget fallback); "
                                   "descriptive budget consumption. No completed-depth, no stop_reason.",
        },
        "pairings": pairing_summaries,
        "decision": decision,
        "wall_total_s": round(elapsed, 1),
        "splendor_exe_sha256": file_sha256(SPLN),
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"\nResult written: {RESULT_PATH}")
    print(f"Decision: primary_reference={decision['primary_reference']} "
          f"(unique={decision['unique_reference_named']}); "
          f"unresolved pairings={decision['unresolved_pairings']}")
    print(f"Total wall: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
