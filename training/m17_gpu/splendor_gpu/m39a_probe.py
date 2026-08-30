"""Frozen M39A Phase-0 throughput and truncation probe."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .m39a_collect import _m39a_agent, _opponent_agent, _write_new_json, preflight_league
from .m39a_contract import LEAGUE_ORDER, file_sha256, load_plan, plan_hash
from .m39a_model import load_m39a_checkpoint


REPORT_FORMAT = "effective-splendor-m39a-phase0-report"
REPORT_VERSION = 1
RUN_CONTRACT_FORMAT = "effective-splendor-m39a-phase0-run-contract"
RUN_CONTRACT_VERSION = 1
BUCKETS = ("diversified", "m07", "league", "self_play")
BASES = {
    "diversified": 5_200_000,
    "m07": 5_200_096,
    "league": 5_200_192,
    "self_play": 5_200_288,
}
PRODUCTION_COUNTS = {
    "diversified": 512,
    "m07": 1_024,
    "league": 1_024,
    "self_play": 1_536,
}


@dataclass(frozen=True)
class ProbeGame:
    bucket: str
    ordinal: int
    seed: int
    opponent: str
    learner_seats: tuple[int, ...]
    sampling_game_index: int


def probe_game(bucket: str, ordinal: int) -> ProbeGame:
    if bucket not in BUCKETS or not 0 <= ordinal < 96:
        raise ValueError("probe bucket/ordinal outside frozen schedule")
    seed = BASES[bucket] + ordinal
    learner_seat = seed % 2
    if bucket == "diversified":
        opponent = "agent-heuristic" if ordinal % 4 in (0, 1, 2) else "agent-random"
        seats = (learner_seat,)
    elif bucket == "m07":
        opponent, seats = "M07", (learner_seat,)
    elif bucket == "league":
        opponent, seats = LEAGUE_ORDER[ordinal % len(LEAGUE_ORDER)], (learner_seat,)
    else:
        opponent, seats = "M39A", (0, 1)
    bucket_index = BUCKETS.index(bucket)
    return ProbeGame(bucket, ordinal, seed, opponent, seats, 10_000 + bucket_index * 96 + ordinal)


def frozen_probe_schedule() -> list[ProbeGame]:
    return [probe_game(bucket, ordinal) for bucket in BUCKETS for ordinal in range(96)]


def phase0_run_contract(
    *,
    plan_hash_value: str,
    checkpoint: Path,
    checkpoint_sha256: str,
    checkpoint_hash: str,
    catalog: Path,
    splendor: Path,
    device: str,
    workers: int,
) -> dict[str, Any]:
    """Bind a resumable Phase-0 directory to one exact execution environment."""
    return {
        "format": RUN_CONTRACT_FORMAT,
        "version": RUN_CONTRACT_VERSION,
        "plan_hash": plan_hash_value,
        "checkpoint_path": str(checkpoint),
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_hash": checkpoint_hash,
        "catalog_path": str(catalog),
        "catalog_file_sha256": file_sha256(catalog),
        "splendor_program": str(splendor),
        "splendor_file_sha256": file_sha256(splendor),
        "device": device,
        "workers": workers,
    }


def ensure_phase0_run_contract(out_dir: Path, contract: dict[str, Any]) -> Path:
    path = out_dir / "phase0-run-contract.json"
    if path.exists():
        observed = json.loads(path.read_text(encoding="utf-8"))
        if observed != contract:
            raise RuntimeError(
                "Phase 0 resume contract mismatch; use the original executable, "
                "checkpoint, catalog, device, and worker count or choose a new out-dir"
            )
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_new_json(path, contract)
    return path


def run_probe_schedule(
    tasks: list[ProbeGame],
    *,
    workers: int,
    runner: Callable[[ProbeGame], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run a bounded schedule and stop queuing work as soon as one game fails."""
    rows: list[dict[str, Any]] = []
    task_iter = iter(tasks)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    pending: dict[concurrent.futures.Future[dict[str, Any]], ProbeGame] = {}

    def submit_next() -> bool:
        try:
            game = next(task_iter)
        except StopIteration:
            return False
        pending[executor.submit(runner, game)] = game
        return True

    for _ in range(workers):
        if not submit_next():
            break
    try:
        while pending:
            done, _ = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            failures = [future for future in done if future.exception() is not None]
            if failures:
                failed = failures[0]
                game = pending[failed]
                try:
                    failed.result()
                except Exception as error:
                    raise RuntimeError(
                        f"Phase 0 failed at {game.bucket}/{game.ordinal}"
                    ) from error
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


def _run_one(
    game: ProbeGame,
    *,
    checkpoint: Path,
    checkpoint_sha256: str,
    digest: str,
    catalog: Path,
    splendor: Path,
    splendor_file_sha256: str,
    out_dir: Path,
    device: str,
) -> dict[str, Any]:
    game_dir = out_dir / game.bucket / f"game-{game.ordinal:03d}"
    config_path = game_dir / "arena-config.json"
    report_path = game_dir / "arena-report.json"
    replay_path = game_dir / "replay.json"
    sidecars = {seat: game_dir / f"seat-{seat}.sidecar.json" for seat in game.learner_seats}
    expected = [config_path, report_path, replay_path, *sidecars.values()]
    present = [path.exists() for path in expected]
    if any(present) and not all(present):
        raise RuntimeError(f"partial probe artifacts at {game_dir}")
    timing_path = game_dir / "timing.json"
    if all(present):
        if not timing_path.is_file():
            raise RuntimeError(f"completed probe lacks timing artifact at {game_dir}")
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
        if timing.get("splendor_program") != str(splendor) or timing.get(
            "splendor_file_sha256"
        ) != splendor_file_sha256:
            raise RuntimeError(f"probe executable binding mismatch at {game_dir}")
        elapsed_seconds = float(timing["elapsed_seconds"])
    else:
        game_dir.mkdir(parents=True, exist_ok=True)
        agents = []
        for seat in (0, 1):
            if seat in game.learner_seats:
                agents.append(
                    _m39a_agent(
                        checkpoint=checkpoint,
                        checkpoint_sha256=checkpoint_sha256,
                        digest=digest,
                        game_index=game.sampling_game_index,
                        sidecar=sidecars[seat],
                        catalog=catalog,
                        device=device,
                    )
                )
            else:
                agents.append(
                    _opponent_agent(
                        game.opponent,
                        splendor=splendor,
                        catalog=catalog,
                        action_seed=20_261_000 + game.sampling_game_index,
                        device=device,
                    )
                )
        _write_new_json(
            config_path,
            {
                "game_id": f"m39a-phase0-{game.bucket}-{game.ordinal:03d}",
                "seed": game.seed,
                "handshake_timeout_ms": 10_000,
                "move_timeout_ms": 30_000,
                "shutdown_grace_ms": 2_000,
                "agents": agents,
            },
        )
        started = time.perf_counter()
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
        elapsed_seconds = time.perf_counter() - started
        if completed.returncode != 0:
            raise RuntimeError(
                f"probe {game.bucket}/{game.ordinal} failed rc={completed.returncode}: "
                f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
            )
        _write_new_json(
            timing_path,
            {
                "elapsed_seconds": elapsed_seconds,
                "splendor_program": str(splendor),
                "splendor_file_sha256": splendor_file_sha256,
            },
        )
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    completed_plies = len(replay["steps"])
    return {
        "bucket": game.bucket,
        "ordinal": game.ordinal,
        "seed": game.seed,
        "opponent": game.opponent,
        "learner_seats": list(game.learner_seats),
        "warmup": game.ordinal < 32,
        "elapsed_seconds": elapsed_seconds,
        "completed_plies": completed_plies,
        "truncated": completed_plies > 150,
    }


def _clopper_pearson_upper(successes: int, trials: int, confidence: float = 0.95) -> float:
    if successes == trials:
        return 1.0
    try:
        from scipy.stats import beta
    except ImportError as error:  # pragma: no cover - environment contract
        raise RuntimeError("scipy is required for the frozen Clopper-Pearson report") from error
    return float(beta.ppf(confidence, successes + 1, trials - successes))


def summarize(rows: list[dict[str, Any]], workers: int) -> dict[str, Any]:
    if len(rows) != 384:
        raise ValueError("Phase 0 requires exactly 384 realized games")
    bucket_reports: dict[str, Any] = {}
    aggregate_truncated = 0
    projection_seconds = 0.0
    for bucket in BUCKETS:
        selected = sorted(
            (row for row in rows if row["bucket"] == bucket),
            key=lambda row: int(row["ordinal"]),
        )
        if len(selected) != 96:
            raise ValueError(f"bucket {bucket} does not contain 96 games")
        timed = [row for row in selected if not row["warmup"]]
        if len(timed) != 64:
            raise ValueError(f"bucket {bucket} does not contain 64 timed games")
        truncations = sum(bool(row["truncated"]) for row in selected)
        aggregate_truncated += truncations
        mean_seconds = sum(float(row["elapsed_seconds"]) for row in timed) / len(timed)
        projection_seconds += PRODUCTION_COUNTS[bucket] * mean_seconds
        strata: dict[str, dict[str, int]] = {}
        for row in selected:
            stratum = str(row["opponent"])
            item = strata.setdefault(stratum, {"games": 0, "truncated": 0})
            item["games"] += 1
            item["truncated"] += int(bool(row["truncated"]))
        bucket_reports[bucket] = {
            "games": 96,
            "timed_games": 64,
            "mean_timed_seconds": mean_seconds,
            "truncated": truncations,
            "clopper_pearson_95_upper": _clopper_pearson_upper(truncations, 96),
            "bucket_fail": truncations >= 4,
            "sub_strata": strata,
        }
    projected_hours = projection_seconds / 3600.0 / workers
    g0_pass = projected_hours <= 72.0
    g0b_pass = aggregate_truncated < 9 and all(
        not report["bucket_fail"] for report in bucket_reports.values()
    )
    return {
        "workers": workers,
        "bucket_reports": bucket_reports,
        "aggregate_truncated": aggregate_truncated,
        "aggregate_fail": aggregate_truncated >= 9,
        "projected_parallel_hours": projected_hours,
        "g0_pass": g0_pass,
        "g0b_pass": g0b_pass,
        "verdict": "pass" if g0_pass and g0b_pass else "fail",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen M39A Phase 0")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--checkpoint-hash", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--splendor", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.device != "cuda":
        raise ValueError("formal Phase 0 requires cuda")
    if args.workers < 1:
        raise ValueError("workers must be positive")
    plan = load_plan(args.plan)
    digest = plan_hash(plan)
    _, payload = load_m39a_checkpoint(
        args.checkpoint,
        expected_file_sha256=args.checkpoint_sha256,
        expected_plan_hash=digest,
        device="cpu",
    )
    if payload["checkpoint_hash"] != args.checkpoint_hash or int(payload["metadata"]["cycle"]) != 0:
        raise ValueError("Phase 0 must use the bound cycle-0 checkpoint")
    preflight_league()
    out_dir = args.out_dir.resolve()
    checkpoint = args.checkpoint.resolve()
    catalog = args.catalog.resolve()
    splendor = args.splendor.resolve()
    if not catalog.is_file():
        raise ValueError(f"catalog does not exist: {catalog}")
    if not splendor.is_file():
        raise ValueError(f"splendor executable does not exist: {splendor}")
    run_contract = phase0_run_contract(
        plan_hash_value=digest,
        checkpoint=checkpoint,
        checkpoint_sha256=args.checkpoint_sha256,
        checkpoint_hash=args.checkpoint_hash,
        catalog=catalog,
        splendor=splendor,
        device=args.device,
        workers=args.workers,
    )
    run_contract_path = ensure_phase0_run_contract(out_dir, run_contract)
    splendor_file_sha256 = str(run_contract["splendor_file_sha256"])
    tasks = frozen_probe_schedule()
    rows = run_probe_schedule(
        tasks,
        workers=args.workers,
        runner=lambda game: _run_one(
            game,
            checkpoint=checkpoint,
            checkpoint_sha256=args.checkpoint_sha256,
            digest=digest,
            catalog=catalog,
            splendor=splendor,
            splendor_file_sha256=splendor_file_sha256,
            out_dir=out_dir,
            device=args.device,
        ),
    )
    rows.sort(key=lambda row: (BUCKETS.index(row["bucket"]), row["ordinal"]))
    summary = summarize(rows, args.workers)
    report = {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "plan_hash": digest,
        "checkpoint_sha256": args.checkpoint_sha256,
        "checkpoint_hash": args.checkpoint_hash,
        "run_contract": str(run_contract_path),
        "run_contract_sha256": file_sha256(run_contract_path),
        "splendor_program": str(splendor),
        "splendor_file_sha256": splendor_file_sha256,
        "device": args.device,
        "rows": rows,
        **summary,
    }
    report_path = out_dir / "phase0-report.json"
    _write_new_json(report_path, report)
    print(
        json.dumps(
            {
                "status": "ok",
                "report": str(report_path),
                "report_sha256": file_sha256(report_path),
                "verdict": report["verdict"],
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
