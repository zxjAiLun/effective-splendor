"""M40A formal evaluation statistics: H1, league safeguard, and the two
report-only anchor diagnostics — all frozen by the design (09fd8ec)."""

from __future__ import annotations

import math
from typing import Any

from .m40a_constants import (
    ANCHOR_CRITICAL_DF63,
    H1_CRITICAL_DF127,
    LEAGUE_CRITICAL_DF31,
    LEAGUE_ORDER,
)

SCORES = {"win": 1.0, "draw": 0.5, "loss": 0.0}


def _mean_sample_sd(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        raise ValueError("Student-t requires at least two units")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _require_complete(rows: list[dict[str, Any]], expected: int, label: str) -> None:
    if len(rows) != expected:
        raise ValueError(f"{label}: expected {expected} rows, got {len(rows)}")
    for row in rows:
        if not row.get("completed"):
            raise ValueError(
                f"{label}: incomplete row ({row.get('aborted_reason', 'unknown')}) — "
                "fail closed"
            )
        if row.get("candidate_fault") or row.get("deterministic_nontermination"):
            raise ValueError(f"{label}: fault/non-termination present — fail closed")
        if row.get("outcome") not in SCORES:
            raise ValueError(f"{label}: invalid outcome")


def _block_score(
    rows: list[dict[str, Any]],
    *,
    arm: str,
    pairing: str,
    seed: int,
) -> float:
    """10_000 x mean(two-rotation scores) for one (arm, pairing, seed)."""
    selected = [
        row
        for row in rows
        if row["arm"] == arm
        and row["pairing"] == pairing
        and int(row["seed"]) == seed
    ]
    if len(selected) != 2:
        raise ValueError(
            f"expected 2 rotations for {arm}/{pairing}/{seed}, got {len(selected)}"
        )
    return 10_000.0 * sum(SCORES[str(row["outcome"])] for row in selected) / 2.0


def evaluate_h1(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """H1: B vs A, 128 paired blocks, one-sided 95% Student-t."""
    seeds = range(8_100_000, 8_100_127 + 1)
    _require_complete(rows, 512, "H1")
    deltas = []
    for seed in seeds:
        candidate = _block_score(rows, arm="candidate", pairing="H1", seed=seed)
        baseline = _block_score(rows, arm="baseline", pairing="H1", seed=seed)
        deltas.append(candidate - baseline)
    mean, sample_sd = _mean_sample_sd(deltas)
    lower = mean - H1_CRITICAL_DF127 * sample_sd / math.sqrt(128)
    passed = lower > 0.0
    return {
        "gate": "h1",
        "completed_matches": 256,
        "mean_delta_bps": mean,
        "sample_sd_bps": sample_sd,
        "lower_95_bps": lower,
        "critical_value": H1_CRITICAL_DF127,
        "pass": passed,
        "verdict": "pass" if passed else "fail",
    }


def evaluate_league(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """League safeguard: 32 cross-opponent seed aggregates, one-sided
    95% UPPER bound; FAIL only if upper < 0."""
    seeds = range(8_200_000, 8_200_031 + 1)
    _require_complete(rows, 9 * 32 * 2 * 2, "league")
    aggregates = []
    for seed in seeds:
        deltas = []
        for pairing in LEAGUE_ORDER:
            candidate = _block_score(rows, arm="candidate", pairing=pairing, seed=seed)
            baseline = _block_score(rows, arm="baseline", pairing=pairing, seed=seed)
            deltas.append(candidate - baseline)
        aggregates.append(sum(deltas) / len(LEAGUE_ORDER))
    mean, sample_sd = _mean_sample_sd(aggregates)
    upper = mean + LEAGUE_CRITICAL_DF31 * sample_sd / math.sqrt(32)
    failed = upper < 0.0
    return {
        "gate": "league",
        "completed_matches": 9 * 32 * 2 * 2,
        "mean_delta_bps": mean,
        "sample_sd_bps": sample_sd,
        "upper_95_bps": upper,
        "critical_value": LEAGUE_CRITICAL_DF31,
        "pass": not failed,
        "verdict": "fail" if failed else "pass",
        "note": "no significant evidence B is weaker; not a non-inferiority claim",
    }


def evaluate_anchor(rows: list[dict[str, Any]], gate: str) -> dict[str, Any]:
    """Report-only anchor diagnostic: B vs M07 or B vs D2-v2.

    `delta_i = score_i - 5000`; two-sided 95% interval, df = 63.
    """
    expected_gate = {"m07": "M07", "d2": "D2-v2"}[gate]
    seeds = range(
        8_300_000 if gate == "m07" else 8_400_000,
        (8_300_063 if gate == "m07" else 8_400_063) + 1,
    )
    _require_complete(rows, 128, gate)  # 64 blocks x 2 rotations, candidate only
    deltas = []
    for seed in seeds:
        score = _block_score(rows, arm="candidate", pairing=expected_gate, seed=seed)
        deltas.append(score - 5_000.0)
    mean, sample_sd = _mean_sample_sd(deltas)
    half = ANCHOR_CRITICAL_DF63 * sample_sd / math.sqrt(64)
    return {
        "gate": gate,
        "anchor": expected_gate,
        "completed_matches": 128,
        "mean_delta_bps": mean,
        "ci_low_bps": mean - half,
        "ci_high_bps": mean + half,
        "critical_value": ANCHOR_CRITICAL_DF63,
        "pass": None,
        "verdict": "report-only",
    }


def formal_checkpoint_guard(cycle: int) -> None:
    """Formal gates evaluate the cycle-4 final checkpoints ONLY."""
    if cycle != 4:
        raise ValueError(
            f"formal M40A evaluation requires the cycle-4 final checkpoint, got cycle {cycle}"
        )
