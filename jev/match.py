"""Run an unrated Jev vs heuristic arena match (no league/registry writes)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from runtime import AGENT_VERSION, atomic_json

ROOT = Path(__file__).resolve().parents[1]


def run_arena(command, *, cwd, env, timeout=3600):
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", **options) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--jev-seat", type=int, choices=(0, 1), default=0)
    parser.add_argument("--binary", type=Path, help="Path to built splendor binary")
    parser.add_argument("--out-dir", type=Path, help="New local-only output directory")
    parser.add_argument("--max-plies", type=int, help="Truncated smoke only; no match winner")
    args = parser.parse_args()
    if not (0 <= args.seed < 2**64 - 1) or (args.max_plies is not None and args.max_plies < 1):
        parser.error("seed must be u64 and max-plies positive")
    suffix = ".exe" if os.name == "nt" else ""
    binary = args.binary or next((p for p in (ROOT / f"target/release/splendor{suffix}", ROOT / f"target/debug/splendor{suffix}") if p.exists()), None)
    if binary is None or not binary.is_file():
        parser.error("build binary first (cargo build -p splendor-cli --release)")
    binary = binary.resolve()
    out = (args.out_dir or ROOT / "local-artifacts/jev" / f"{int(time.time())}-seat{args.jev_seat}-{uuid.uuid4().hex[:8]}").resolve()
    if out.exists():
        parser.error(f"output directory already exists: {out}")
    out.mkdir(parents=True)
    env = os.environ.copy()
    env["JEV_METRICS_FILE"] = str(out / "metrics.json")
    env["JEV_SPLENDOR_BINARY"] = str(binary)
    # Secret stays in local file/env. No key, secret path or API response in config.
    python = {"program": sys.executable, "args": ["-u", str(ROOT / "jev/agent.py")]}
    heuristic = {"program": str(binary), "args": ["agent-heuristic", "--seed", str(args.seed + 1)]}
    agents = [python, heuristic] if args.jev_seat == 0 else [heuristic, python]
    config = {"game_id": f"jev-v1-{args.seed}-seat{args.jev_seat}", "seed": args.seed,
              "handshake_timeout_ms": 15000, "move_timeout_ms": 45000, "shutdown_grace_ms": 2000,
              "agents": agents}
    atomic_json(out / "config.json", config)
    sources = [ROOT / "jev" / name for name in ("agent.py", "runtime.py", "transport.py", "match.py", "catalog.json")]
    sources += [ROOT / "crates/splendor-cli/src/agent_terms_command.rs", ROOT / "crates/splendor-agent/src/heuristic.rs"]
    atomic_json(out / "manifest.json", {
        "schema_version": 1, "agent_version": AGENT_VERSION, "requested_model": "jev-latest",
        "max_api_calls": int(env.get("JEV_MAX_API_CALLS", "100")), "max_attempts_per_stage": 2,
        "max_plies": args.max_plies, "arena_config": config,
        "source_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256((out / "config.json").read_bytes()).hexdigest(),
    })
    cmd = [str(binary), "run-rollout" if args.max_plies else "run-match", "--config", str(out / "config.json"),
           "--report-out", str(out / "report.json"), "--replay-out", str(out / "replay.json")]
    if args.max_plies:
        cmd += ["--max-plies", str(args.max_plies), "--prefix-out", str(out / "prefix.json")]
    try:
        result = run_arena(cmd, cwd=ROOT, env=env, timeout=3600)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        # The flushed agent journal remains usable even when the whole tree is killed.
        atomic_json(out / "runner-status.json", {"status": "interrupted", "result_known": False})
        print("arena interrupted; inspect local journal (no match result claimed)", file=sys.stderr)
        return 1
    atomic_json(out / "runner-status.json", {"status": "exited", "exit_code": result.returncode})
    # The arena's stdout is a single compact outcome JSON, never echo arbitrary stderr.
    print(json.dumps({"arena_exit_code": result.returncode, "out_dir": str(out),
                      "outcome": json.loads(result.stdout) if result.stdout.strip().startswith("{") else None},
                     ensure_ascii=False))
    if result.stderr:
        (out / "arena-stderr.txt").write_text(result.stderr, encoding="utf-8")
        print("arena diagnostics stored locally (not displayed)", file=sys.stderr)
    if result.returncode == 0 and (out / "replay.json").exists():
        check = subprocess.run([str(binary), "verify-replay", "--input", str(out / "replay.json")],
                               cwd=ROOT, capture_output=True, text=True)
        print(f"verify-replay exit={check.returncode}")
        if check.returncode:
            return 1
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
