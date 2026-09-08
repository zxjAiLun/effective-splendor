#!/usr/bin/env python3
"""S1 Phase A feasibility probe (frozen contract in docs/s1-search-horizon-validation.md V2).

Steps:
1. Extract eligible contexts from ALL 384 S0 verified replays via
   analyze-replay-determinization (Phase::Main, >=2 legal actions, non-terminal),
   identity = (observation_hash, visible_history_hash, information_set_hash),
   dedupe, select first 200 by SHA256("43_000_001" || identity) ascending.
2. For each selected context and each probe config (d2-n2000, d2-n10000),
   run `splendor s1-probe` (live fixed-seed policy, in-process timing,
   depth diagnostics).
3. Feasibility per config: completion >= 80% (completed_depth==2 AND
   stop_reason==DepthLimitReached, over non-terminal continuations) AND
   p95 in-process decide <= 2.0 s. Report mean/p50/p90/p95/max.
4. Selection: both pass -> n2000; only n10000 -> n10000; neither ->
   COMPUTE_INFEASIBLE.

Output: benchmarks/s1-feasibility-probe-v1.result.json with the full
200-identity manifest, per-config histograms and timing percentiles,
consistency assertions, and the frozen verdict.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPLN = REPO / "target/release/splendor.exe"
OUT_ROOT = REPO / "local-artifacts/s1-feasibility"
RESULT_PATH = REPO / "benchmarks/s1-feasibility-probe-v1.result.json"

S0_ROOT = REPO / "local-artifacts/s0-baseline-calibration"
SELECTION_SEED = "43_000_001"
PROBE_CONFIGS = {"d2-n2000": 2000, "d2-n10000": 10000}
SAMPLE_SEED = 20260703
SAMPLE_COUNT = 4
DEPTH_TURNS = 2
COMPLETION_GATE = 0.80
COST_GATE_S = 2.0
TARGET_CONTEXTS = 200


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def extract_contexts() -> list[dict]:
    """Run the analysis command over all 384 S0 replays (cheap: n1 config)
    and collect eligible contexts."""
    print("Extracting eligible contexts from 384 S0 replays (d1-n1 analysis)...")
    contexts: dict[tuple[str, str, str], dict] = {}
    replays = sorted(S0_ROOT.glob("*/block-*/r*/match-replay.json"))
    if len(replays) != 384:
        fail(f"expected 384 S0 replays, found {len(replays)}")
    tmp = OUT_ROOT / "analysis"
    tmp.mkdir(parents=True, exist_ok=True)
    for idx, rpl in enumerate(replays):
        out = tmp / f"{rpl.parent.parent.parent.name}-{rpl.parent.parent.name}-{rpl.parent.name}.json"
        if not out.exists():
            r = subprocess.run(
                [str(SPLN), "analyze-replay-determinization", "--input", str(rpl),
                 "--out", str(out), "--sample-seed", "20260703",
                 "--sample-count", "4", "--max-depth-turns", "1", "--max-nodes", "1"],
                capture_output=True, text=True)
            if r.returncode != 0:
                fail(f"analysis failed {rpl}: {r.stderr[:300]}")
        d = json.loads(out.read_text(encoding="utf-8"))
        for f in d["frames"]:
            pv = f["player_view"]
            if pv["public"]["phase"] != "main":
                continue
            if len(f["legal_actions"]) < 2:
                continue
            if pv["public"]["phase"] == "game_over":
                continue
            ident = (f["observation_hash"], f["visible_history_hash"],
                     f["information_set_hash"])
            if ident in contexts:
                continue
            contexts[ident] = {
                "identity": {
                    "observation_hash": ident[0],
                    "visible_history_hash": ident[1],
                    "information_set_hash": ident[2],
                },
                "source_replay": str(rpl),
                "ply": f["ply"],
                "legal_actions": len(f["legal_actions"]),
            }
        if (idx + 1) % 48 == 0:
            print(f"  {idx+1}/384 replays, {len(contexts)} unique contexts", flush=True)
    return list(contexts.values())


def select_200(contexts: list[dict]) -> list[dict]:
    for c in contexts:
        ident = c["identity"]
        key = f"{SELECTION_SEED}|{ident['observation_hash']}|{ident['visible_history_hash']}|{ident['information_set_hash']}"
        c["_sort_key"] = hashlib.sha256(key.encode()).hexdigest()
    contexts.sort(key=lambda c: c["_sort_key"])
    selected = contexts[:TARGET_CONTEXTS]
    for c in selected:
        del c["_sort_key"]
    return selected


def run_probe(contexts: list[dict], nodes: int) -> dict:
    tag = f"d2-n{nodes}"
    stats_dir = OUT_ROOT / f"probe-{tag}"
    stats_dir.mkdir(parents=True, exist_ok=True)
    stats_file = stats_dir / "probe.ndjson"
    if stats_file.exists():
        stats_file.unlink()
    rows = []
    t0 = time.time()
    for i, c in enumerate(contexts):
        r = subprocess.run(
            [str(SPLN), "s1-probe", "--input", c["source_replay"],
             "--ply", str(c["ply"]),
             "--sample-seed", str(SAMPLE_SEED), "--sample-count", str(SAMPLE_COUNT),
             "--max-depth-turns", str(DEPTH_TURNS), "--max-nodes", str(nodes),
             "--stats-out", str(stats_file)],
            capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"probe failed {c['source_replay']} ply {c['ply']}: {r.stderr[:300]}")
        if (i + 1) % 25 == 0:
            print(f"  [{tag}] {i+1}/{len(contexts)} ({time.time()-t0:.0f}s)", flush=True)
    for line in stats_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return {"tag": tag, "rows": rows, "wall_s": round(time.time() - t0, 1)}


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def summarize(probe: dict) -> dict:
    rows = probe["rows"]
    if len(rows) != TARGET_CONTEXTS:
        fail(f"{probe['tag']}: {len(rows)} telemetry rows != {TARGET_CONTEXTS}")
    # aggregate histograms
    hist = {}
    stop = {"depth_limit_reached": 0, "node_budget_reached": 0}
    for r in rows:
        d = r.get("depth_diagnostics")
        if d is None:
            fail(f"{probe['tag']}: row without depth_diagnostics")
        for depth, count in enumerate(d["depth_histogram"]):
            hist[depth] = hist.get(depth, 0) + count
        stop["depth_limit_reached"] += d["stop_depth_limit_reached"]
        stop["node_budget_reached"] += d["stop_node_budget_reached"]
    total_cont = sum(hist.values())
    # consistency assertions
    if total_cont != stop["depth_limit_reached"] + stop["node_budget_reached"]:
        fail(f"{probe['tag']}: histogram/stop totals disagree")
    for r in rows:
        d = r["depth_diagnostics"]
        if d["depth_histogram"][-1] != d["stop_depth_limit_reached"]:
            fail(f"{probe['tag']}: top-depth bin != DepthLimitReached count")
    if len(hist) == 3:
        completed = hist.get(2, 0)
    else:
        fail(f"{probe['tag']}: unexpected histogram depth {max(hist)}")
    completion = completed / total_cont if total_cont else 0.0
    micros = sorted(r["decide_micros"] for r in rows)
    secs = [m / 1e6 for m in micros]
    return {
        "config": probe["tag"],
        "decisions": len(rows),
        "nonterminal_continuations": total_cont,
        "depth_histogram": {str(k): v for k, v in sorted(hist.items())},
        "stop_reasons": stop,
        "completed_depth2": completed,
        "completion_rate": round(completion, 6),
        "decide_seconds": {
            "mean": round(sum(secs) / len(secs), 4),
            "p50": round(percentile(secs, 0.50), 4),
            "p90": round(percentile(secs, 0.90), 4),
            "p95": round(percentile(secs, 0.95), 4),
            "max": round(secs[-1], 4),
        },
        "wall_total_s": probe["wall_s"],
        "completion_gate_pass": completion >= COMPLETION_GATE,
        "cost_gate_pass": percentile(secs, 0.95) <= COST_GATE_S,
    }


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    contexts = extract_contexts()
    print(f"eligible unique contexts: {len(contexts)}")
    selected = select_200(contexts)
    print(f"selected 200 (seed {SELECTION_SEED}, SHA256 ascending)")

    summaries = {}
    for tag, nodes in PROBE_CONFIGS.items():
        print(f"probing {tag}...")
        probe = run_probe(selected, nodes)
        summaries[tag] = summarize(probe)

    # selection rule
    feasible = [t for t, s in summaries.items() if s["completion_gate_pass"] and s["cost_gate_pass"]]
    if len(feasible) == 2:
        selected_cfg = "d2-n2000"  # cheaper
    elif len(feasible) == 1:
        selected_cfg = feasible[0]
    else:
        selected_cfg = None

    verdict = "FEASIBLE" if selected_cfg else "COMPUTE_INFEASIBLE"
    result = {
        "format": "effective-splendor-s1-feasibility-result",
        "version": 1,
        "experiment_id": "s1-feasibility-probe-v1",
        "design_doc": "docs/s1-search-horizon-validation.md @ 1f557e0 (DESIGN_V2 APPROVED/FROZEN)",
        "contract": {
            "selection_seed": SELECTION_SEED,
            "target_contexts": TARGET_CONTEXTS,
            "sample_seed": SAMPLE_SEED, "sample_count": SAMPLE_COUNT,
            "depth_turns": DEPTH_TURNS,
            "probe_configs": PROBE_CONFIGS,
            "completion_gate": COMPLETION_GATE,
            "cost_gate_p95_seconds": COST_GATE_S,
            "completion_definition": "completed_depth_turns == 2 AND stop_reason == DepthLimitReached",
            "eligible_context": "Phase::Main, >=2 legal actions, non-terminal, identity-triple dedupe",
        },
        "manifest": [
            {"identity": c["identity"], "source_replay": c["source_replay"],
             "ply": c["ply"], "legal_actions": c["legal_actions"]}
            for c in selected
        ],
        "probe_results": summaries,
        "feasible_configs": feasible,
        "selected_arena_config": selected_cfg,
        "verdict": verdict,
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nverdict: {verdict}; selected: {selected_cfg}")
    for tag, s in summaries.items():
        print(f"  {tag}: completion {s['completion_rate']:.4f} (gate {COMPLETION_GATE}), "
              f"p95 {s['decide_seconds']['p95']}s (gate {COST_GATE_S}s), "
              f"pass=({s['completion_gate_pass']}, {s['cost_gate_pass']})")
    print(f"result: {RESULT_PATH}")


if __name__ == "__main__":
    main()
