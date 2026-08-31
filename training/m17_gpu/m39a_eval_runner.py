"""Frozen M39A G2/G3 Arena evaluation runner.

Executes the frozen evaluation schedules:

- G2: 128 seed blocks (5_000_000..5_000_127) × 2 rotations × 2 arms
  (candidate = cycle-8 argmax, baseline = M25-D2-v2) vs M07 — 512 matches.
- G3: 32 seed blocks (5_100_000..5_100_031) × 2 rotations × 2 arms × 9
  league pairings — 1,152 matches.

Every match is a formal `run-match` (full game; no ply cap). The result is
an evaluation ledger consumed by `m39a_gates.py`. Fail-fast on any abort;
the gates require zero aborts / faults / non-terminations anyway.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from splendor_gpu.m39a_collect import ResidentServer, _write_new_json
from splendor_gpu.m39a_contract import LEAGUE_ORDER, file_sha256

LEDGER_FORMAT = "effective-splendor-m39a-evaluation-ledger"
LEDGER_VERSION = 1
SCORES = {"win": 1.0, "draw": 0.5, "loss": 0.0}


def _agent_for(arm: str, *, server, checkpoint_sha256: str, digest: str, catalog: Path, device: str, sidecar: Path) -> dict[str, Any]:
    if arm == "candidate":
        args = [
            "-m",
            "splendor_gpu.m39a_agent",
            "--checkpoint-sha256",
            checkpoint_sha256,
            "--plan-hash",
            digest,
            "--game-index",
            "0",
            "--sidecar-out",
            str(sidecar),
            "--server-url",
            server.url,
            "--server-ready",
            str(server.ready_file),
            "--action-selection",
            "argmax",
        ]
        return {"program": str(Path(sys.executable).resolve()), "args": args}
    if arm == "baseline":
        return {
            "program": str(Path(sys.executable).resolve()),
            "args": [
                "-m",
                "splendor_gpu.m35a_agent",
                "--model-id",
                "M25-D2-v2",
                "--catalog",
                str(catalog),
                "--device",
                device,
            ],
        }
    raise ValueError(f"unknown arm {arm!r}")


def _opponent_for(pairing: str, *, splendor: Path, catalog: Path, device: str) -> dict[str, Any]:
    if pairing == "M07":
        return {
            "program": str(splendor),
            "args": [
                "agent-determinization",
                "--sample-seed",
                "20260810",
                "--sample-count",
                "4",
                "--max-depth-turns",
                "1",
                "--max-nodes",
                "2000",
            ],
        }
    if pairing in LEAGUE_ORDER:
        return {
            "program": str(Path(sys.executable).resolve()),
            "args": [
                "-m",
                "splendor_gpu.m35a_agent",
                "--model-id",
                pairing,
                "--catalog",
                str(catalog),
                "--device",
                device,
            ],
        }
    raise ValueError(f"unknown pairing {pairing!r}")


def _outcome_for(arm_seat: int, result: dict[str, Any]) -> str:
    """Map a terminal GameResult to the arm's outcome (win/draw/loss)."""
    winners = [int(seat) for seat in result.get("winners", [])]
    if len(winners) == 2:
        return "draw"
    if arm_seat in winners:
        return "win"
    return "loss"


def _run_match(
    *,
    arm: str,
    pairing: str,
    seed: int,
    rotation: int,
    server,
    checkpoint_sha256: str,
    digest: str,
    catalog: Path,
    splendor: Path,
    device: str,
    out_dir: Path,
) -> dict[str, Any]:
    match_dir = out_dir / f"{arm}-{pairing}-{seed}-r{rotation}"
    config_path = match_dir / "arena-config.json"
    report_path = match_dir / "arena-report.json"
    replay_path = match_dir / "replay.json"
    sidecar = match_dir / "eval-sidecar.json"
    if config_path.exists() and not report_path.is_file():
        # config-only: either the runner died before spawning the match
        # (safe to retry) or the match hit the ply-safety limit (no report
        # is ever produced). Retrying is correct for both: a re-run
        # non-terminator re-triggers the limit and is re-recorded as such.
        config_path.unlink()
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return _row_from_report(arm, pairing, seed, rotation, report)

    match_dir.mkdir(parents=True, exist_ok=True)
    arm_agent = _agent_for(
        arm,
        server=server,
        checkpoint_sha256=checkpoint_sha256,
        digest=digest,
        catalog=catalog,
        device=device,
        sidecar=sidecar,
    )
    opponent = _opponent_for(pairing, splendor=splendor, catalog=catalog, device=device)
    # Rotation 0: arm at seat 0; rotation 1: arm at seat 1.
    agents = [arm_agent, opponent] if rotation == 0 else [opponent, arm_agent]
    config = {
        "game_id": f"m39a-eval-{arm}-{pairing}-{seed}-r{rotation}",
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": agents,
    }
    _write_new_json(config_path, config)
    completed = subprocess.run(
        [
            str(splendor),
            "run-match",
            "--config",
            str(config_path),
            "--report-out",
            str(report_path),
            "--replay-out",
            str(replay_path),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=60 * 60,
        check=False,
    )
    if completed.returncode != 0:
        stderr_text = completed.stderr or ""
        if "exceeded ply safety limit" in stderr_text:
            # Deterministic non-termination (the engine's 10,000-ply safety
            # limit fired). This is a *result*, not an infrastructure
            # failure: the row is recorded as an incomplete match with the
            # non-termination flag, and the schedule continues. The frozen
            # gates require zero non-terminations, so this fails the gate —
            # but the full schedule must still be recorded.
            return {
                "arm": arm,
                "pairing": pairing,
                "seed": seed,
                "rotation": rotation,
                "completed": False,
                "candidate_fault": False,
                "deterministic_nontermination": True,
                "outcome": None,
                "aborted_reason": "engine_ply_safety_limit",
            }
        raise RuntimeError(
            f"evaluation {arm}/{pairing}/{seed}/r{rotation} failed "
            f"rc={completed.returncode}: stdout={completed.stdout!r} "
            f"stderr={completed.stderr!r}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return _row_from_report(arm, pairing, seed, rotation, report)


def _row_from_report(
    arm: str, pairing: str, seed: int, rotation: int, report: dict[str, Any]
) -> dict[str, Any]:
    outcome = report.get("outcome", {})
    status = outcome.get("status")
    completed = status == "completed"
    row: dict[str, Any] = {
        "arm": arm,
        "pairing": pairing,
        "seed": seed,
        "rotation": rotation,
        "completed": completed,
        "candidate_fault": False,
        "deterministic_nontermination": False,
        "outcome": None,
    }
    if not completed:
        # Any abort in either arm's process is attributed to the arm's own
        # agent only if the faulting seat is the arm's seat; but for the
        # gate ledger the distinction that matters is abort/fault counts,
        # which fail the gate either way.
        reason = outcome.get("reason")
        row["aborted_reason"] = reason
        if reason == "action_timeout" or reason == "handshake_timeout":
            # Attribute timeouts to the arm's seat when that seat is at
            # fault; otherwise it is the opponent's fault (still recorded).
            fault_seat = outcome.get("seat")
            arm_seat = 0 if rotation == 0 else 1
            row["candidate_fault"] = arm == "candidate" and fault_seat == arm_seat
        return row
    result = outcome.get("result", {})
    arm_seat = 0 if rotation == 0 else 1
    row["outcome"] = _outcome_for(arm_seat, result)
    return row


def run_schedule(
    *,
    gate: str,
    server,
    checkpoint_sha256: str,
    digest: str,
    catalog: Path,
    splendor: Path,
    device: str,
    out_dir: Path,
    workers: int,
) -> list[dict[str, Any]]:
    if gate == "g2":
        jobs = [
            (arm, "M07", seed, rotation)
            for seed in range(5_000_000, 5_000_128)
            for arm in ("candidate", "baseline")
            for rotation in (0, 1)
        ]
    elif gate == "g3":
        jobs = [
            (arm, pairing, seed, rotation)
            for seed in range(5_100_000, 5_100_032)
            for arm in ("candidate", "baseline")
            for pairing in LEAGUE_ORDER
            for rotation in (0, 1)
        ]
    else:
        raise ValueError(f"unknown gate {gate!r}")

    rows: list[dict[str, Any]] = []
    pending: dict[Any, tuple[str, str, int, int]] = {}
    iterator = iter(jobs)
    executor = ThreadPoolExecutor(max_workers=workers)

    def submit_next() -> bool:
        try:
            job = next(iterator)
        except StopIteration:
            return False
        arm, pairing, seed, rotation = job
        future = executor.submit(
            _run_match,
            arm=arm,
            pairing=pairing,
            seed=seed,
            rotation=rotation,
            server=server,
            checkpoint_sha256=checkpoint_sha256,
            digest=digest,
            catalog=catalog,
            splendor=splendor,
            device=device,
            out_dir=out_dir,
        )
        pending[future] = job
        return True

    try:
        for _ in range(workers):
            if not submit_next():
                break
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            failures = [f for f in done if f.exception() is not None]
            if failures:
                failed = failures[0]
                job = pending[failed]
                raise RuntimeError(
                    f"evaluation failed at {job[0]}/{job[1]}/{job[2]}/r{job[3]}: "
                    f"{failed.exception()!r}"
                ) from failed.exception()
            for future in done:
                pending.pop(future)
                row = future.result()
                rows.append(row)
                print(json.dumps(row, separators=(",", ":")), flush=True)
                submit_next()
    except BaseException:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen M39A G2/G3 evaluation")
    parser.add_argument("--gate", choices=["g2", "g3"], required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--splendor", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    from splendor_gpu.m39a_contract import load_plan, plan_hash

    plan = load_plan(args.plan)
    digest = plan_hash(plan)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = out_dir / f"{args.gate}-ledger.json"

    server = ResidentServer(
        checkpoint=args.checkpoint.resolve(),
        checkpoint_sha256=args.checkpoint_sha256,
        plan_hash=digest,
        catalog=args.catalog.resolve(),
        device=args.device,
        ready_file=out_dir / "server-ready.json",
    )
    try:
        rows = run_schedule(
            gate=args.gate,
            server=server,
            checkpoint_sha256=args.checkpoint_sha256,
            digest=digest,
            catalog=args.catalog.resolve(),
            splendor=args.splendor.resolve(),
            device=args.device,
            out_dir=out_dir,
            workers=args.workers,
        )
    finally:
        server.close()

    rows.sort(key=lambda row: (row["arm"], row["pairing"], row["seed"], row["rotation"]))
    ledger = {
        "format": LEDGER_FORMAT,
        "version": LEDGER_VERSION,
        "gate": args.gate,
        "plan_hash": digest,
        "checkpoint_sha256": args.checkpoint_sha256,
        "rows": rows,
    }
    _write_new_json(ledger_path, ledger)
    print(
        json.dumps(
            {
                "status": "ok",
                "ledger": str(ledger_path),
                "ledger_sha256": file_sha256(ledger_path),
                "rows": len(rows),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
