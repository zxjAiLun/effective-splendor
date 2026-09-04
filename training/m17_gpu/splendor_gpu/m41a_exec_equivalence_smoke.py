"""Equivalence smoke: run-branch with the RESIDENT proxy config vs the
original in-process agent config on the SAME pilot branch — the two
resulting branch replays must be canonically identical."""
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
WORK = REPO / "local-artifacts/m41a-exec-test"


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


def config(game_id: str, agents: list) -> dict:
    return {
        "game_id": game_id, "seed": 0,
        "handshake_timeout_ms": 10_000, "move_timeout_ms": 60_000,
        "shutdown_grace_ms": 2_000, "agents": agents,
    }


def canonical(replay_path: Path) -> str:
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    replay.pop("engine_version", None)
    return hashlib.sha256(json.dumps(replay, sort_keys=True).encode()).hexdigest()


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(D2.read_bytes()).hexdigest()

    # resident server
    ready = WORK / "server-ready.json"
    if ready.exists():
        ready.unlink()
    server = subprocess.Popen(
        [sys.executable, "-m", "splendor_gpu.m41a_server",
         "--checkpoint-sha256", sha, "--catalog", str(CATALOG),
         "--device", "cuda", "--ready-file", str(ready)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=REPO,
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
    print("server ready:", url, flush=True)

    # branch at the FIRST action of game-0000 (a guaranteed legal, diverging
    # action exists in the legal set; use the source's own action AND a
    # different one for stronger coverage)
    gdir = PILOT / "game-0000"
    source_replay = json.loads((gdir / "replay.json").read_text(encoding="utf-8"))
    probe = json.loads(subprocess.run(
        [str(SPLN), "probe-legal", "--source-replay", str(gdir / "replay.json"),
         "--branch-ply", "14"], capture_output=True, text=True, check=True).stdout)
    legal = probe["legal_actions"]
    source_action = source_replay["steps"][14]["action"]
    other_action = next(a for a in legal if a != source_action)

    try:
        for name, action in (("source", source_action), ("other", other_action)):
            forced = WORK / f"forced-{name}.json"
            forced.write_text(json.dumps(action), encoding="utf-8")
            results = {}
            for executor, agents in (
                ("old", [agent_inprocess(), agent_inprocess()]),
                ("new", [agent_proxy(url, ready, sha), agent_proxy(url, ready, sha)]),
            ):
                bdir = WORK / f"branch-{name}-{executor}"
                if bdir.exists():
                    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(bdir)], check=False)
                bdir.mkdir(parents=True)
                cfg = WORK / f"config-{name}-{executor}.json"
                cfg.write_text(json.dumps(config(f"m41a-exec-test-{name}-{executor}", agents)), encoding="utf-8")
                started = time.perf_counter()
                out = subprocess.run(
                    [str(SPLN), "run-branch",
                     "--source-replay", str(gdir / "replay.json"),
                     "--branch-ply", "14", "--forced-action", str(forced),
                     "--config", str(cfg), "--ply-cap", "150",
                     "--report-out", str(bdir / "report.json"),
                     "--replay-out", str(bdir / "replay.json")],
                    capture_output=True, text=True, timeout=600,
                )
                elapsed = time.perf_counter() - started
                if out.returncode != 0:
                    raise RuntimeError(f"{executor} branch failed: {out.stderr[:300]}")
                results[executor] = (canonical(bdir / "replay.json"), elapsed)
                print(json.dumps({"branch": name, "executor": executor,
                                  "elapsed_s": round(elapsed, 2)}), flush=True)
            old_h, old_t = results["old"]
            new_h, new_t = results["new"]
            verdict = "IDENTICAL" if old_h == new_h else "DIVERGED"
            print(json.dumps({"branch": name, "equivalence": verdict,
                              "speedup": round(old_t / new_t, 2) if new_t > 0 else None}), flush=True)
            assert old_h == new_h, f"equivalence FAILED for branch {name}"
    finally:
        server.terminate()
        server.wait(timeout=15)
    print("EQUIVALENCE SMOKE PASS")


if __name__ == "__main__":
    main()
