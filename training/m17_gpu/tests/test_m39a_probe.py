from __future__ import annotations

import pytest

from splendor_gpu.m39a_contract import LEAGUE_ORDER
from splendor_gpu.m39a_probe import BUCKETS, frozen_probe_schedule, summarize


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
