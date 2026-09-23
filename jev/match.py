"""Run an unrated Jev vs heuristic arena match (no league/registry writes)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    out = (args.out_dir or ROOT / "local-artifacts/jev" / f"{int(time.time())}-seat{args.jev_seat}").resolve()
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
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    cmd = [str(binary), "run-rollout" if args.max_plies else "run-match", "--config", str(out / "config.json"),
           "--report-out", str(out / "report.json"), "--replay-out", str(out / "replay.json")]
    if args.max_plies:
        cmd += ["--max-plies", str(args.max_plies), "--prefix-out", str(out / "prefix.json")]
    try:
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        print("arena timed out; no match result. inspect local output directory", file=sys.stderr)
        return 1
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
