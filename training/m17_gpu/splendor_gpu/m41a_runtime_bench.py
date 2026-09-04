"""M41A formal-distribution runtime benchmark (Executor Repair 1).

Runs the NEW executor (run-branches + resident D2) over the EXISTING
32 pilot source games at the FORMAL 3-state rule (25/50/75 quantiles of
the selected seat) — 96 state-batch executions, all legal actions —
and reports per-quantile and combined timing:

    per quantile (25/50/75): state wall mean/p50/p90, continuation
    plies mean, branches mean
    combined: seconds/game, hours/100 games, projected corpora

This is pure performance validation; no science gates re-run here.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
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
WORK = REPO / "local-artifacts/m41a-runtime-bench"
PLY_CAP = 150
NUM_GAMES = 32


def agent_proxy(url: str, ready: Path, sha: str) -> dict:
    return {
        "program": sys.executable,
        "args": [str(REPO / "training/m17_gpu/m41a_proxy_agent.py"),
                 "--server-url", url, "--server-ready", str(ready),
                 "--checkpoint-sha256", sha],
    }


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
    print(json.dumps({"server": url, "semantic": doc["checkpoint_semantic_sha256"][:16]}), flush=True)

    config = WORK / "config.json"
    config.write_text(json.dumps({
        "game_id": "m41a-runtime-bench", "seed": 0,
        "handshake_timeout_ms": 10_000, "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000,
        "agents": [agent_proxy(url, ready, sha), agent_proxy(url, ready, sha)],
    }), encoding="utf-8")

    records = []  # (game, quantile_label, wall_s, plies, branches)
    try:
        for ordinal in range(NUM_GAMES):
            gdir = PILOT / f"game-{ordinal:04d}"
            replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
            steps = replay["steps"]
            seat = ordinal % 2
            plies = [s["ply"] for s in steps if s["actor"] == seat]
            n = len(plies)
            idxs = sorted({min(n - 1, int(round(q * (n - 1)))) for q in (0.25, 0.5, 0.75)})
            selected = [plies[i] for i in idxs][:3]
            labels = ("25%", "50%", "75%")
            for ply, label in zip(selected, labels):
                sdir = WORK / f"g{ordinal:04d}-p{ply:04d}"
                if sdir.exists():
                    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(sdir)], check=False)
                started = time.perf_counter()
                out = subprocess.run(
                    [str(SPLN), "run-branches",
                     "--source-replay", str(gdir / "replay.json"),
                     "--branch-ply", str(ply), "--config", str(config),
                     "--ply-cap", str(PLY_CAP), "--out-dir", str(sdir)],
                    capture_output=True, text=True, timeout=3600,
                )
                wall = time.perf_counter() - started
                if out.returncode != 0:
                    raise RuntimeError(f"g{ordinal} {label}: {out.stderr[:300]}")
                # branch count from the manifest; continuation plies from
                # the first action's replay
                manifest = json.loads((sdir / "state-manifest.json").read_text(encoding="utf-8"))
                branches = manifest["legal_set_size"]
                first_replay = json.loads((sdir / "action-000" / "replay.json").read_text(encoding="utf-8"))
                plies_ran = len(first_replay["steps"]) - ply - 1
                records.append({
                    "game": ordinal, "quantile": label, "wall_s": wall,
                    "continuation_plies": plies_ran, "branches": branches,
                })
                print(json.dumps({"game": ordinal, "q": label,
                                  "wall_s": round(wall, 2), "plies": plies_ran,
                                  "branches": branches}), flush=True)
    finally:
        server.terminate()
        server.wait(timeout=15)

    # ---- Aggregation ----
    def stats_for(label: str) -> dict:
        rows = [r for r in records if r["quantile"] == label]
        walls = sorted(r["wall_s"] for r in rows)
        return {
            "states": len(rows),
            "wall_mean_s": statistics.mean(walls),
            "wall_p50_s": walls[len(walls) // 2],
            "wall_p90_s": walls[int(len(walls) * 0.9)],
            "continuation_plies_mean": statistics.mean(r["continuation_plies"] for r in rows),
            "branches_mean": statistics.mean(r["branches"] for r in rows),
        }

    combined = {
        "states": len(records),
        "total_wall_s": sum(r["wall_s"] for r in records),
        "per_game_s": sum(r["wall_s"] for r in records) / NUM_GAMES,
        "branches_total": sum(r["branches"] for r in records),
        "branches_per_game": sum(r["branches"] for r in records) / NUM_GAMES,
    }
    hours_per_100 = combined["per_game_s"] * 100 / 3600

    summary = {
        "phase": "formal-distribution-runtime-benchmark",
        "executor": "run-branches + resident D2 (v2 provenance)",
        "games": NUM_GAMES,
        "quantiles": {label: stats_for(label) for label in ("25%", "50%", "75%")},
        "combined": combined,
        "projection": {
            "hours_per_100_games": hours_per_100,
            # planning corpus sizes (per the P2 phased proposal direction)
            "hours_560_games": hours_per_100 * 5.6,
            # worst-case full formal pool at design ceiling: train/val/cal
            # planning + 512 formal
            "hours_planning_plus_512": hours_per_100 * (5.6 + 5.12),
        },
    }
    (WORK / "runtime-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
