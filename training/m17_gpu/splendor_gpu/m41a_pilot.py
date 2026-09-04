"""M41A P0 pilot driver: the preflight round on the 9_1xx namespace.

Executes the frozen P0 order (design §7):
    H0 determinism -> H0b source-action reproduction -> discrimination
    density -> runtime -> freeze-list raw data.

NO training, NO formal corpus, NO 9_0xx seeds. Pilot games never enter
any formal split.

Phases:
  source  : PILOT_GAMES fresh D2/D2 capped source games (run-rollout).
  states  : per game, STATES_PER_GAME acting decisions of the selected
            seat (ordinal mod 2) at ~25/50/75/90% quantiles.
  H0      : every branch of the FIRST 8 states re-executed twice; the
            two runs' canonical replay identity must be identical.
  H0b     : at every state, the branch forced to the source's own
            action must reproduce the source game exactly (suffix
            actions, terminal/cap status, acting-seat return, final
            state hash).
  branches: every legal action of every state is branched once (for
            H0/H0b states this includes those runs).
  metrics : discrimination density, legal-set sizes, tie density,
            best-vs-second / best-vs-D2 gaps, terminal/cap rates,
            branch wall-times, corpus projections.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splendor_gpu.m41a_helpers import PILOT_SEED_BASE

REPO = Path(__file__).resolve().parent.parent.parent.parent
SPLN = REPO / "target" / "release" / "splendor.exe"
CATALOG = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
PY = sys.executable

PILOT_GAMES = 32
STATES_PER_GAME = 4
H0_RECHECK_STATES = 8
PLY_CAP = 150


def agent_cmd() -> dict[str, Any]:
    return {
        "program": PY,
        "args": [
            "-m", "splendor_gpu.m35a_agent",
            "--model-id", "M25-D2-v2",
            "--catalog", str(CATALOG),
            "--device", "cuda",
        ],
    }


def base_config(game_id: str, seed: int) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
        "agents": [agent_cmd(), agent_cmd()],
    }


def run_json(args: list[str]) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(M41A_PY_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(args, capture_output=True, text=True, timeout=3600, check=False, env=env)


M41A_PY_ROOT = REPO / "training/m17_gpu"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def cap_return(scores: list[int], viewer: int) -> float:
    d = scores[viewer] - scores[1 - viewer]
    return -0.5 + 0.5 * math.tanh(d / 4.0)


def branch_return(report: dict[str, Any], viewer: int) -> float:
    outcome = report["outcome"]
    if outcome["status"] == "completed":
        winners = outcome["result"]["winners"]
        if len(winners) == 2:
            return 0.0
        return 1.0 if viewer in winners else -1.0
    return cap_return(outcome["cap_scores"], viewer)


def phase_sources(out_dir: Path) -> list[Path]:
    games = []
    for ordinal in range(PILOT_GAMES):
        gdir = out_dir / f"game-{ordinal:04d}"
        report_path = gdir / "arena-report.json"
        if not report_path.is_file():
            cfg_path = gdir / "source-config.json"
            write_json(cfg_path, base_config(f"m41a-pilot-source-{ordinal:04d}", PILOT_SEED_BASE + ordinal))
            out = run_json([
                str(SPLN), "run-rollout", "--max-plies", str(PLY_CAP),
                "--config", str(cfg_path),
                "--report-out", str(report_path),
                "--replay-out", str(gdir / "replay.json"),
                "--prefix-out", str(gdir / "rollout-prefix.json"),
            ])
            if out.returncode != 0:
                raise RuntimeError(f"source {ordinal} rc={out.returncode}: {out.stderr[:300]}")
            print(json.dumps({"source": ordinal, "status": "ok"}), flush=True)
        games.append(gdir)
    return games


def select_states(game_dirs: list[Path]) -> list[dict[str, Any]]:
    states = []
    for ordinal, gdir in enumerate(game_dirs):
        replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
        steps = replay["steps"]
        seat = ordinal % 2
        plies = [s["ply"] for s in steps if s["actor"] == seat]
        if not plies:
            continue
        n = len(plies)
        idxs = sorted({min(n - 1, int(round(q * (n - 1)))) for q in (0.25, 0.5, 0.75, 0.9)})
        for ply in [plies[i] for i in idxs][:STATES_PER_GAME]:
            states.append({
                "game_ordinal": ordinal,
                "game_dir": str(gdir),
                "seat": seat,
                "ply": ply,
                "source_action": steps[ply]["action"],
            })
    return states


def probe_legal(state: dict[str, Any]) -> dict[str, Any]:
    out = run_json([
        str(SPLN), "probe-legal",
        "--source-replay", str(Path(state["game_dir"]) / "replay.json"),
        "--branch-ply", str(state["ply"]),
    ])
    if out.returncode != 0:
        raise RuntimeError(f"probe-legal failed: {out.stderr[:300]}")
    return json.loads(out.stdout)


def run_branch(state: dict[str, Any], action: dict[str, Any], out_path: Path,
               tag: str) -> tuple[dict[str, Any], float]:
    """Execute one branch (resume-aware: an existing complete report +
    replay pair is reused without re-execution). Returns
    (report, elapsed_seconds; elapsed=0 on resume)."""
    report_path = out_path.parent / f"{out_path.stem}-report.json"
    if report_path.is_file() and out_path.is_file():
        # Resume: the artifact pair is complete; trust and reuse (the
        # pilot is not a provenance-gated formal product; H0 re-runs
        # provide the determinism evidence).
        return json.loads(report_path.read_text(encoding="utf-8")), 0.0
    forced_path = out_path.parent / f"{out_path.stem}-forced.json"
    write_json(forced_path, action)
    config_path = Path(state["game_dir"]) / "branch-config.json"
    started = time.perf_counter()
    out = run_json([
        str(SPLN), "run-branch",
        "--source-replay", str(Path(state["game_dir"]) / "replay.json"),
        "--branch-ply", str(state["ply"]),
        "--forced-action", str(forced_path),
        "--config", str(config_path),
        "--ply-cap", str(PLY_CAP),
        "--report-out", str(report_path),
        "--replay-out", str(out_path),
    ])
    elapsed = time.perf_counter() - started
    if out.returncode != 0:
        raise RuntimeError(f"branch {tag} rc={out.returncode}: {out.stderr[:300]}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return report, elapsed


def canonical_branch_identity(replay_path: Path) -> str:
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay.pop("engine_version", None)  # constant for one executor build
    return hashlib.sha256(json.dumps(replay, sort_keys=True).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="M41A P0 pilot driver")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: list[float] = []

    print(json.dumps({"phase": "source-generation", "games": PILOT_GAMES}), flush=True)
    game_dirs = phase_sources(out_dir)
    states = select_states(game_dirs)
    print(json.dumps({"phase": "states-selected", "count": len(states)}), flush=True)

    # Branch configs (one per game dir, reused).
    for ordinal in range(PILOT_GAMES):
        write_json(
            out_dir / f"game-{ordinal:04d}" / "branch-config.json",
            base_config(f"m41a-pilot-branch-{ordinal:04d}", PILOT_SEED_BASE + ordinal),
        )

    h0_results: list[dict[str, Any]] = []
    h0b_results: list[dict[str, Any]] = []
    branch_records: list[dict[str, Any]] = []
    probe_records: list[dict[str, Any]] = []

    for state_index, state in enumerate(states):
        gdir = Path(state["game_dir"])
        bdir = gdir / f"branch-ply{state['ply']:04d}"
        bdir.mkdir(parents=True, exist_ok=True)
        probe = probe_legal(state)
        legal = probe["legal_actions"]
        probe_records.append({
            "game": state["game_ordinal"], "ply": state["ply"],
            "seat": state["seat"], "legal_count": len(legal),
            "state_hash": probe["state_hash"],
        })

        # --- H0b: forced = source action must reproduce the source game.
        # (Writes directly into the state branch dir as replay.json /
        # replay-report.json; the a### subdirs hold the other actions.)
        h0b_replay_path = bdir / "replay.json"
        report, elapsed = run_branch(state, state["source_action"], h0b_replay_path, f"h0b/{state_index}")
        if elapsed > 0:
            timings.append(elapsed)
        source_replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
        branch_replay = json.loads(h0b_replay_path.read_text(encoding="utf-8"))
        suffix_match = (
            branch_replay["steps"][state["ply"]:] == source_replay["steps"][state["ply"]:]
        )
        outcome_match = (
            branch_replay["result"] == source_replay["result"]
            and branch_replay["final_state_hash"] == source_replay["final_state_hash"]
        )
        source_report = json.loads((gdir / "arena-report.json").read_text(encoding="utf-8"))
        src_return = branch_return(source_report, state["seat"])
        h0b_return = branch_return(report, state["seat"])
        h0b_results.append({
            "game": state["game_ordinal"], "ply": state["ply"],
            "suffix_match": suffix_match,
            "outcome_match": outcome_match,
            "return_match": abs(src_return - h0b_return) < 1e-12,
            "pass": suffix_match and outcome_match and abs(src_return - h0b_return) < 1e-12,
        })

        # --- Every legal action branched once (recorded for metrics).
        # The h0b branch above IS the source action's branch: locate it
        # among the legal set by identity and reuse its result.
        source_action_index = next(
            (i for i, a in enumerate(legal) if a == state["source_action"]), None
        )
        state_returns: dict[int, float] = {}
        for action_index, action in enumerate(legal):
            if action_index == source_action_index:
                rep, elapsed2, r = report, 0.0, h0b_return
            else:
                adir = bdir / f"a{action_index:03d}"
                rep, elapsed2 = run_branch(state, action, adir / "replay.json", f"s{state_index}/a{action_index}")
                if elapsed2 > 0:
                    timings.append(elapsed2)
                r = branch_return(rep, state["seat"])
            state_returns[action_index] = r
            branch_records.append({
                "game": state["game_ordinal"], "ply": state["ply"],
                "action_index": action_index, "return": r,
                "truncated": rep["outcome"]["status"] == "truncated",
            })

        # --- H0: re-execute two branches of the first H0_RECHECK_STATES twice.
        if state_index < H0_RECHECK_STATES:
            for action_index in (0, len(legal) // 2):
                a1 = bdir / f"a{action_index:03d}" / "replay.json"
                a2 = bdir / f"a{action_index:03d}-rerun" / "replay.json"
                _, _ = run_branch(state, legal[action_index], a2, f"h0/{state_index}/{action_index}")
                h0_results.append({
                    "game": state["game_ordinal"], "ply": state["ply"],
                    "action_index": action_index,
                    "identical": canonical_branch_identity(a1) == canonical_branch_identity(a2),
                })

    # ---------------- Metrics ----------------
    h0_pass = all(r["identical"] for r in h0_results) and h0_results
    h0b_pass = all(r["pass"] for r in h0b_results) and h0b_results

    by_state: dict[tuple[int, int], list[float]] = {}
    truncated_count = 0
    for rec in branch_records:
        key = (rec["game"], rec["ply"])
        by_state.setdefault(key, []).append(rec["return"])
        truncated_count += rec["truncated"]

    discriminated = [vals for vals in by_state.values() if len(set(vals)) >= 2]
    discriminated_strict = [vals for vals in by_state.values() if max(vals) > min(vals)]

    gaps_best_second = []
    gaps_best_d2 = []
    tie_densities = []
    # D2 returns: read the h0b branch reports. The h0b branch writes
    # directly into the state's branch directory as replay.json /
    # replay-report.json (the a### subdirectories hold the other actions).
    d2_actions: dict[tuple[int, int], float] = {}
    for state in states:
        key = (state["game_ordinal"], state["ply"])
        report_path = (
            Path(state["game_dir"]) / f"branch-ply{state['ply']:04d}"
            / "replay-report.json"
        )
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        d2_actions[key] = branch_return(rep, state["seat"])

    for state in states:
        key = (state["game_ordinal"], state["ply"])
        vals = by_state[key]
        best = max(vals)
        second = sorted(vals)[-2] if len(vals) >= 2 else best
        gaps_best_second.append(best - second)
        tie_densities.append(sum(1 for v in vals if v == best) / len(vals))
        gaps_best_d2.append(best - d2_actions[key])

    total_branches = len(branch_records)
    p50 = statistics.median(timings) if timings else 0.0
    p90 = sorted(timings)[int(len(timings) * 0.9)] if timings else 0.0

    summary = {
        "phase": "P0-pilot-summary",
        "states": len(states),
        "total_branches": total_branches,
        "H0": {
            "checks": len(h0_results),
            "pass": bool(h0_pass),
            "results": h0_results,
        },
        "H0b": {
            "checks": len(h0b_results),
            "pass": bool(h0b_pass),
            "results": h0b_results,
        },
        "discrimination": {
            "states_total": len(by_state),
            "states_ge2_distinct": len(discriminated),
            "states_best_gt_worst": len(discriminated_strict),
            "fraction_ge2_distinct": len(discriminated) / len(by_state),
            "fraction_best_gt_worst": len(discriminated_strict) / len(by_state),
        },
        "legal_set": {
            "mean": statistics.mean(p["legal_count"] for p in probe_records),
            "median": statistics.median(p["legal_count"] for p in probe_records),
            "min": min(p["legal_count"] for p in probe_records),
            "max": max(p["legal_count"] for p in probe_records),
        },
        "gaps": {
            "best_vs_second_mean": statistics.mean(gaps_best_second),
            "best_vs_second_median": statistics.median(gaps_best_second),
            "best_vs_d2_mean": statistics.mean(gaps_best_d2),
            "best_vs_d2_median": statistics.median(gaps_best_d2),
            "best_vs_d2_nonzero": sum(1 for g in gaps_best_d2 if g > 1e-12),
        },
        "tie_density_mean": statistics.mean(tie_densities),
        "truncated_branches": truncated_count,
        "truncated_fraction": truncated_count / total_branches,
        "runtime": {
            "branch_wall_p50_s": p50,
            "branch_wall_p90_s": p90,
            "mean_legal_per_state": statistics.mean(p["legal_count"] for p in probe_records),
            "states_per_game": STATES_PER_GAME,
        },
    }

    # Corpus projection: N games * states/game * mean legal * p50.
    summary["corpus_projection"] = {
        "per_100_games_branches": 100 * STATES_PER_GAME * summary["legal_set"]["mean"],
        "per_100_games_hours_at_p50": 100 * STATES_PER_GAME * summary["legal_set"]["mean"] * p50 / 3600,
    }

    write_json(out_dir / "p0-summary.json", summary)
    print(json.dumps(summary, indent=2))
    print(json.dumps({"status": "P0-pilot-complete"}), flush=True)


if __name__ == "__main__":
    main()
