from __future__ import annotations

import pytest

from splendor_gpu.m39a_contract import LEAGUE_ORDER
import threading
import time
from pathlib import Path

from splendor_gpu.m39a_probe import (
    BUCKETS,
    ensure_phase0_run_contract,
    frozen_probe_schedule,
    phase0_run_contract,
    probe_game,
    run_probe_schedule,
    summarize,
)


def test_frozen_probe_schedule_has_exact_assignments() -> None:
    schedule = frozen_probe_schedule()
    assert len(schedule) == 384
    assert len({game.seed for game in schedule}) == 384
    diversified = [game for game in schedule if game.bucket == "diversified"]
    assert sum(game.opponent == "agent-heuristic" for game in diversified) == 72
    assert sum(game.opponent == "agent-random" for game in diversified) == 24
    warmup = diversified[:32]
    assert sum(game.opponent == "agent-heuristic" for game in warmup) == 24
    assert sum(game.opponent == "agent-random" for game in warmup) == 8
    league = [game for game in schedule if game.bucket == "league"]
    counts = {opponent: 0 for opponent in LEAGUE_ORDER}
    for game in league:
        counts[game.opponent] += 1
    assert list(counts.values()) == [11, 11, 11, 11, 11, 11, 10, 10, 10]
    assert all(game.learner_seats == (game.seed % 2,) for game in schedule[:288])
    assert all(game.learner_seats == (0, 1) for game in schedule[288:])


def test_phase0_summary_applies_frozen_gates_and_projection() -> None:
    rows = []
    for game in frozen_probe_schedule():
        rows.append(
            {
                "bucket": game.bucket,
                "ordinal": game.ordinal,
                "opponent": game.opponent,
                "warmup": game.ordinal < 32,
                "elapsed_seconds": 10.0,
                "truncated": False,
            }
        )
    result = summarize(rows, workers=2)
    assert result["g0_pass"]
    assert result["g0b_pass"]
    assert result["verdict"] == "pass"
    assert result["projected_parallel_hours"] == pytest.approx(
        (512 + 1024 + 1024 + 1536) * 10 / 3600 / 2
    )
    for bucket in BUCKETS:
        assert result["bucket_reports"][bucket]["timed_games"] == 64

    for row in rows[:4]:
        row["truncated"] = True
    failed = summarize(rows, workers=2)
    assert not failed["g0b_pass"]
    assert failed["bucket_reports"]["diversified"]["bucket_fail"]
    assert failed["verdict"] == "fail"


def test_phase0_run_contract_binds_executable_and_resume(tmp_path: Path) -> None:
    checkpoint = tmp_path / "cycle-0.pt"
    catalog = tmp_path / "catalog.json"
    splendor = tmp_path / "splendor.exe"
    checkpoint.write_bytes(b"checkpoint")
    catalog.write_bytes(b"catalog")
    splendor.write_bytes(b"release-binary")
    contract = phase0_run_contract(
        plan_hash_value="plan",
        checkpoint=checkpoint.resolve(),
        checkpoint_sha256="checkpoint-file",
        checkpoint_hash="checkpoint-semantic",
        catalog=catalog.resolve(),
        splendor=splendor.resolve(),
        device="cuda",
        workers=4,
    )
    path = ensure_phase0_run_contract(tmp_path / "run", contract)
    assert ensure_phase0_run_contract(tmp_path / "run", contract) == path
    assert contract["splendor_program"] == str(splendor.resolve())

    changed = dict(contract)
    changed["workers"] = 2
    with pytest.raises(RuntimeError, match="resume contract mismatch"):
        ensure_phase0_run_contract(tmp_path / "run", changed)

    splendor.write_bytes(b"different-binary")
    changed_binary = phase0_run_contract(
        plan_hash_value="plan",
        checkpoint=checkpoint.resolve(),
        checkpoint_sha256="checkpoint-file",
        checkpoint_hash="checkpoint-semantic",
        catalog=catalog.resolve(),
        splendor=splendor.resolve(),
        device="cuda",
        workers=4,
    )
    with pytest.raises(RuntimeError, match="resume contract mismatch"):
        ensure_phase0_run_contract(tmp_path / "run", changed_binary)


def test_probe_schedule_stops_queueing_after_first_failure() -> None:
    tasks = [probe_game("diversified", ordinal) for ordinal in range(8)]
    second_started = threading.Event()
    started: list[int] = []
    lock = threading.Lock()

    def runner(game):
        with lock:
            started.append(game.ordinal)
        if game.ordinal == 0:
            assert second_started.wait(timeout=1.0)
            raise ValueError("deliberate failure")
        if game.ordinal == 1:
            second_started.set()
            time.sleep(0.05)
        return {"ordinal": game.ordinal}

    with pytest.raises(RuntimeError, match="diversified/0"):
        run_probe_schedule(tasks, workers=2, runner=runner)
    assert sorted(started) == [0, 1]
