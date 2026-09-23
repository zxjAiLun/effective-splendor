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

import agent as agent_module
import transport

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
    # The trace binding is the directory name, which the local viewer resolves
    # inside one fixed root. It is an identifier, never a path.
    run_trace_id = out.name
    # Secret stays in local file/env. No key, secret path or API response in config.
    python = {"program": sys.executable, "args": ["-u", str(ROOT / "jev/agent.py")]}
    heuristic = {"program": str(binary), "args": ["agent-heuristic", "--seed", str(args.seed + 1)]}
    agents = [python, heuristic] if args.jev_seat == 0 else [heuristic, python]
    config = {"game_id": f"jev-v1-{args.seed}-seat{args.jev_seat}", "run_trace_id": run_trace_id,
              "seed": args.seed,
              "handshake_timeout_ms": 15000, "move_timeout_ms": 45000, "shutdown_grace_ms": 2000,
              "agents": agents}
    atomic_json(out / "config.json", config)
    sources = [ROOT / "jev" / name for name in ("agent.py", "runtime.py", "transport.py", "match.py", "catalog.json")]
    sources += [ROOT / "crates/splendor-cli/src/agent_terms_command.rs", ROOT / "crates/splendor-agent/src/heuristic.rs"]
    atomic_json(out / "manifest.json", {
        "schema_version": 1, "agent_version": AGENT_VERSION,
        # The identity the experiment actually pins, read from the agent rather
        # than restated here. A manifest claiming the floating alias while the
        # code pins a concrete model would detach the record from the run.
        "requested_model": agent_module.MODEL,
        "expected_model": agent_module.EXPECTED_MODEL,
        "max_request_bytes": transport.MAX_REQUEST_BYTES,
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
    write_trace_summary(out)
    return result.returncode


def write_trace_summary(out: Path) -> None:
    """Join the agent journal to the verified game document, honestly.

    The summary is a projection for the local viewer: it states which game
    document it was bound to, which plies carry a Jev decision, and which do
    not. A missing or partial journal stays visible as missing; it is never
    filled in with reconstructed prompts, and a run without a verified replay or
    prefix is recorded as traceable-but-not-playable.
    """
    import trace as trace_reader

    info = trace_reader.read_run(out.name, out.parent)
    decisions = trace_reader.index_by_ply(info["events"])
    replay_path = out / "replay.json"
    prefix_path = out / "prefix.json"
    if replay_path.is_file():
        document, kind = replay_path, "completed_replay"
    elif prefix_path.is_file():
        document, kind = prefix_path, "truncated_prefix"
    else:
        document, kind = None, "unavailable"
    game_plies = None
    if document is not None:
        try:
            parsed = json.loads(document.read_text(encoding="utf-8"))
            game_plies = len(parsed.get("steps", []))
        except (ValueError, OSError):
            game_plies = None
    summaries = {}
    ambiguous = []
    for ply, entries in sorted(decisions.items()):
        if len(entries) > 1:
            ambiguous.append({"ply": ply, "count": len(entries)})
        summaries[str(ply)] = trace_reader.summarize(entries[-1])
    atomic_json(out / "trace-summary.json", {
        "schema_version": 1, "run_id": out.name, "game_document": kind,
        "game_plies": game_plies, "journal_decisions": len(decisions),
        "ambiguous_plies": ambiguous,
        "decisions": summaries,
        "metrics": info["metrics"],
        "journal_recorded": (out / "metrics.jsonl").is_file(),
    })


if __name__ == "__main__":
    sys.exit(main())
