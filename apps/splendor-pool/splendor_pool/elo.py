"""Elo rating system for 1v1 Splendor matches."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EloResult:
    elo_before_a: float
    elo_before_b: float
    score_a: float  # 1.0 for win, 0.5 for tie, 0.0 for loss
    score_b: float
    expected_a: float
    expected_b: float
    delta_a: float
    delta_b: float
    elo_after_a: float
    elo_after_b: float


def calculate_expected(rating_a: float, rating_b: float) -> float:
    """Calculate expected score for player A against player B."""
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def compute_elo_update(
    rating_a: float,
    rating_b: float,
    score_a: float,
    k_factor: float = 32.0,
) -> EloResult:
    """Compute new Elo ratings for two players after a match.
    
    score_a: 1.0 (A wins), 0.5 (draw/tie), 0.0 (B wins).
    """
    if score_a not in (0.0, 0.5, 1.0):
        # Clamp or handle continuous score if applicable
        if score_a > 1.0:
            score_a = 1.0
        elif score_a < 0.0:
            score_a = 0.0

    score_b = 1.0 - score_a
    exp_a = calculate_expected(rating_a, rating_b)
    exp_b = 1.0 - exp_a

    delta_a = round(k_factor * (score_a - exp_a), 2)
    delta_b = round(k_factor * (score_b - exp_b), 2)

    return EloResult(
        elo_before_a=rating_a,
        elo_before_b=rating_b,
        score_a=score_a,
        score_b=score_b,
        expected_a=round(exp_a, 4),
        expected_b=round(exp_b, 4),
        delta_a=delta_a,
        delta_b=delta_b,
        elo_after_a=round(rating_a + delta_a, 2),
        elo_after_b=round(rating_b + delta_b, 2),
    )
