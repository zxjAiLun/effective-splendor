"""M41A executor-optimization equivalence gate + runtime measurement.

Frozen pilot branch subset (per the authorized review): for each of the
first 32 pilot states, FOUR branches — the source action, the first
legal action, the middle legal action, and the last legal action.

OLD executor : run-branch + in-process m35a agents (per-branch torch).
NEW executor : run-branches (state-batch) + resident server/proxy.

Gate: for every (state, action): canonical branch replay identity must
be BITWISE IDENTICAL between executors (determinism makes this exact;
any divergence is a STOP).

Also measures the runtime decomposition: per-state wall time under the
new executor, per-branch effective wall time, and corpus projection.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "training/m17_gpu"))
os.environ["PYTHONPATH"] = str(REPO / "training/m17_gpu")

SPLN = REPO / "target/release/splendor.exe"
CATALOG = REPO / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
D2 = REPO / "local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"
PILOT = REPO / "local-artifacts/m41a-p0-pilot"
WORK = REPO / "local-artifacts/m41a-exec-equiv"
NUM_STATES = 32
PLY_CAP = 150


def canonical(replay_path: Path) -> str:
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay.pop("engine_version", None)
    return hashlib.sha256(json.dumps(replay, sort_keys=True).encode()).hexdigest()


def agent_inprocess() -> dict:
    return {
        "program": sys.executable,
        "args": ["-m", "splendor_gpu.m35a_agent", "--model-id", "M25-D2-v2",
                 "--catalog", str(CATALOG), "--device", "cuda"],
    }


def agent_proxy(url: str, ready: Path, sha: str) -> dict:
    return {
        "program": sys.executable,
        "args": [str(REPO / "training/m17_gpu/m41a_proxy_agent.py"),
                 "--server-url", url, "--server-ready", str(ready),
                 "--checkpoint-sha256", sha],
    }


def config(agents: list) -> dict:
    return {
        "game_id": "m41a-exec-equiv", "seed": 0,
        "handshake_timeout_ms": 10_000, "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000, "agents": agents,
    }


def select_states() -> list[dict]:
    states = []
    for ordinal in range(NUM_STATES):
        gdir = PILOT / f"game-{ordinal:04d}"
        replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
        steps = replay["steps"]
        seat = ordinal % 2
        plies = [s["ply"] for s in steps if s["actor"] == seat]
        n = len(plies)
        idxs = sorted({min(n - 1, int(round(q * (n - 1)))) for q in (0.25, 0.5, 0.75)})
        ply = plies[idxs[1]]  # the 50% state of the formal rule
        states.append({
            "game_ordinal": ordinal, "game_dir": str(gdir), "ply": ply,
            "seat": seat,
            "source_action": steps[ply]["action"],
        })
    return states


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(D2.read_bytes()).hexdigest()

    ready = WORK / "server-ready.json"
    if ready.exists():
        ready.unlink()
    server = subprocess.Popen(
        [sys.executable, "-m", "splendor_gpu.m41a_server",
         "--checkpoint-sha256", sha, "--catalog", str(CATALOG),
         "--device", "cuda", "--ready-file", str(ready)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO,
    )
    deadline = time.time() + 180
    while not ready.is_file():
        if server.poll() is not None:
            raise RuntimeError("server died: " + server.stderr.read()[:300])
        if time.time() > deadline:
            raise RuntimeError("server timeout")
        time.sleep(0.2)
    doc = json.loads(ready.read_text(encoding="utf-8"))
    url = f"{doc['host']}:{doc['port']}"
    print(json.dumps({"server": url}), flush=True)

    old_cfg = WORK / "config-old.json"
    old_cfg.write_text(json.dumps(config([agent_inprocess(), agent_inprocess()])), encoding="utf-8")
    new_cfg = WORK / "config-new.json"
    new_cfg.write_text(json.dumps(config([agent_proxy(url, ready, sha), agent_proxy(url, ready, sha)])), encoding="utf-8")

    states = select_states()
    comparisons = 0
    mismatches = []
    state_times = []
    branch_counts = []

    try:
        for state in states:
            gdir = Path(state["game_dir"])
            src = gdir / "replay.json"
            probe = json.loads(subprocess.run(
                [str(SPLN), "probe-legal", "--source-replay", str(src),
                 "--branch-ply", str(state["ply"])],
                capture_output=True, text=True, check=True).stdout)
            legal = probe["legal_actions"]
            chosen_indices = sorted({
                0,
                legal.index(state["source_action"]) if state["source_action"] in legal else 0,
                len(legal) // 2,
                len(legal) - 1,
            })

            # --- NEW executor: ONE state-batch run over ALL actions ---
            ndir = WORK / f"s{state['game_ordinal']:04d}-new"
            if ndir.exists():
                subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(ndir)], check=False)
            started = time.perf_counter()
            out = subprocess.run(
                [str(SPLN), "run-branches",
                 "--source-replay", str(src), "--branch-ply", str(state["ply"]),
                 "--config", str(new_cfg), "--ply-cap", str(PLY_CAP),
                 "--out-dir", str(ndir)],
                capture_output=True, text=True, timeout=3600,
            )
            state_elapsed = time.perf_counter() - started
            if out.returncode != 0:
                raise RuntimeError(f"run-branches failed: {out.stderr[:400]}")
            state_times.append(state_elapsed)
            branch_counts.append(len(legal))

            # --- OLD executor: the SAME chosen actions via run-branch ---
            for action_index in chosen_indices:
                action = legal[action_index]
                odir = WORK / f"s{state['game_ordinal']:04d}-a{action_index:03d}-old"
                if odir.exists():
                    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(odir)], check=False)
                odir.mkdir(parents=True)
                forced = odir / "forced.json"
                forced.write_text(json.dumps(action), encoding="utf-8")
                out = subprocess.run(
                    [str(SPLN), "run-branch",
                     "--source-replay", str(src), "--branch-ply", str(state["ply"]),
                     "--forced-action", str(forced), "--config", str(old_cfg),
                     "--ply-cap", str(PLY_CAP),
                     "--report-out", str(odir / "report.json"),
                     "--replay-out", str(odir / "replay.json")],
                    capture_output=True, text=True, timeout=3600,
                )
                if out.returncode != 0:
                    raise RuntimeError(f"old run-branch failed: {out.stderr[:400]}")
                old_h = canonical(odir / "replay.json")
                new_h = canonical(ndir / f"action-{action_index:03}" / "replay.json")
                comparisons += 1
                if old_h != new_h:
                    mismatches.append({
                        "game": state["game_ordinal"], "ply": state["ply"],
                        "action_index": action_index,
                    })
            print(json.dumps({
                "state": state["game_ordinal"], "ply": state["ply"],
                "legal": len(legal), "compared": len(chosen_indices),
                "state_wall_s": round(state_elapsed, 2),
            }), flush=True)
    finally:
        server.terminate()
        server.wait(timeout=15)

    per_branch = [t / max(1, c) for t, c in zip(state_times, branch_counts)]
    per_branch.sort()
    summary = {
        "phase": "executor-equivalence",
        "states": len(states),
        "comparisons": comparisons,
        "mismatches": mismatches,
        "gate": "PASS" if not mismatches else "FAIL",
        "runtime_new_executor": {
            "state_wall_p50_s": sorted(state_times)[len(state_times) // 2],
            "branch_effective_p50_s": per_branch[len(per_branch) // 2],
            "branch_effective_p90_s": per_branch[int(len(per_branch) * 0.9)],
            "mean_legal_per_state": sum(branch_counts) / len(branch_counts),
        },
        "corpus_projection_new": {
            "hours_per_100_games": sum(t for t, c in zip(state_times, branch_counts))
            / sum(branch_counts)
            * (sum(branch_counts) / len(branch_counts)) * 3  # 3 states/game
            * 100 / 3600,
        },
    }
    out_path = WORK / "equivalence-summary.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    assert not mismatches, f"EQUIVALENCE FAILED: {mismatches[:5]}"
    print("EQUIVALENCE GATE PASS")


if __name__ == "__main__":
    main()
