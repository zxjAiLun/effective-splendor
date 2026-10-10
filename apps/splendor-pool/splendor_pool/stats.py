"""Tactical metrics extraction and accumulation for Splendor matches."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MatchPlayerStats:
    """Tactical stats for one player in a single match."""
    seat: int
    score: int
    won: float  # 1.0, 0.5, 0.0
    plies: int
    turns: int
    vp_per_turn: float
    vp_per_ply: float
    purchased_cards: int
    reserves_acquired: int
    reserves_bought: int
    reserves_stranded: int
    nobles: int
    actions: dict[str, int] = field(default_factory=dict)


def extract_match_stats(report_data: dict[str, Any], replay_data: dict[str, Any]) -> tuple[MatchPlayerStats, MatchPlayerStats]:
    """Extract tactical statistics for both Seat 0 and Seat 1 from report and replay."""
    outcome = report_data.get("outcome", {})
    result = outcome.get("result", {})
    scores = result.get("scores", [0, 0])
    winners = result.get("winners", [])
    completed_plies = outcome.get("completed_plies", len(replay_data.get("steps", [])))
    turns = (completed_plies + 1) // 2

    # Win status:
    # winners == [0] -> 0 wins
    # winners == [1] -> 1 wins
    # len(winners) > 1 or 0 in winners and 1 in winners -> tie
    if winners == [0]:
        won_0, won_1 = 1.0, 0.0
    elif winners == [1]:
        won_0, won_1 = 0.0, 1.0
    else:
        won_0, won_1 = 0.5, 0.5

    # Parse actions from replay steps
    steps = replay_data.get("steps", [])
    actions_0: dict[str, int] = {}
    actions_1: dict[str, int] = {}
    cards_0 = 0
    cards_1 = 0
    res_acq_0 = 0
    res_acq_1 = 0
    res_bought_0 = 0
    res_bought_1 = 0
    nobles_0 = 0
    nobles_1 = 0

    for step in steps:
        actor = step.get("actor", 0)
        action = step.get("action", {})
        act_type = action.get("type", "unknown")

        target_actions = actions_0 if actor == 0 else actions_1
        target_actions[act_type] = target_actions.get(act_type, 0) + 1

        if act_type == "buy_market":
            if actor == 0:
                cards_0 += 1
            else:
                cards_1 += 1
        elif act_type == "buy_reserved":
            if actor == 0:
                cards_0 += 1
                res_bought_0 += 1
            else:
                cards_1 += 1
                res_bought_1 += 1
        elif act_type in ("reserve_market", "reserve_deck"):
            if actor == 0:
                res_acq_0 += 1
            else:
                res_acq_1 += 1
        elif act_type == "choose_noble":
            if actor == 0:
                nobles_0 += 1
            else:
                nobles_1 += 1

    # Approximate noble count if choose_noble wasn't explicitly logged
    # (in standard Splendor, if a player scores > card prestige or gets nobles)
    score_0 = scores[0] if len(scores) > 0 else 0
    score_1 = scores[1] if len(scores) > 1 else 0

    vp_per_turn_0 = round(score_0 / max(turns, 1), 3)
    vp_per_turn_1 = round(score_1 / max(turns, 1), 3)
    vp_per_ply_0 = round(score_0 / max(completed_plies, 1), 3)
    vp_per_ply_1 = round(score_1 / max(completed_plies, 1), 3)

    p0 = MatchPlayerStats(
        seat=0,
        score=score_0,
        won=won_0,
        plies=completed_plies,
        turns=turns,
        vp_per_turn=vp_per_turn_0,
        vp_per_ply=vp_per_ply_0,
        purchased_cards=cards_0,
        reserves_acquired=res_acq_0,
        reserves_bought=res_bought_0,
        reserves_stranded=max(0, res_acq_0 - res_bought_0),
        nobles=nobles_0,
        actions=actions_0,
    )

    p1 = MatchPlayerStats(
        seat=1,
        score=score_1,
        won=won_1,
        plies=completed_plies,
        turns=turns,
        vp_per_turn=vp_per_turn_1,
        vp_per_ply=vp_per_ply_1,
        purchased_cards=cards_1,
        reserves_acquired=res_acq_1,
        reserves_bought=res_bought_1,
        reserves_stranded=max(0, res_acq_1 - res_bought_1),
        nobles=nobles_1,
        actions=actions_1,
    )

    return p0, p1


def accumulate_model_stats(
    current_stats: dict[str, Any],
    match_stat: MatchPlayerStats,
    opponent_name: str,
    opp_score: int,
) -> dict[str, Any]:
    """Merge a single match's tactical statistics into the cumulative model stats."""
    s = dict(current_stats) if current_stats else {}

    games = s.get("games", 0) + 1
    s["games"] = games

    total_score = s.get("total_score", 0) + match_stat.score
    s["total_score"] = total_score
    s["avg_score"] = round(total_score / games, 2)

    total_margin = s.get("total_margin", 0) + (match_stat.score - opp_score)
    s["total_margin"] = total_margin
    s["avg_margin"] = round(total_margin / games, 2)

    total_turns = s.get("total_turns", 0) + match_stat.turns
    s["total_turns"] = total_turns
    s["avg_turns"] = round(total_turns / games, 2)

    total_plies = s.get("total_plies", 0) + match_stat.plies
    s["total_plies"] = total_plies
    s["avg_plies"] = round(total_plies / games, 2)

    s["avg_vp_turn"] = round(total_score / max(total_turns, 1), 3)
    s["avg_vp_ply"] = round(total_score / max(total_plies, 1), 3)

    # Seat stats
    if match_stat.seat == 0:
        s["seat0_games"] = s.get("seat0_games", 0) + 1
        s["seat0_points"] = s.get("seat0_points", 0.0) + match_stat.won
    else:
        s["seat1_games"] = s.get("seat1_games", 0) + 1
        s["seat1_points"] = s.get("seat1_points", 0.0) + match_stat.won

    s["seat0_win_rate_pct"] = round(
        (s.get("seat0_points", 0.0) / max(s.get("seat0_games", 1), 1)) * 100.0, 1
    )
    s["seat1_win_rate_pct"] = round(
        (s.get("seat1_points", 0.0) / max(s.get("seat1_games", 1), 1)) * 100.0, 1
    )

    # Tactical totals
    s["total_cards"] = s.get("total_cards", 0) + match_stat.purchased_cards
    s["avg_cards"] = round(s["total_cards"] / games, 2)

    s["total_reserves_acquired"] = s.get("total_reserves_acquired", 0) + match_stat.reserves_acquired
    s["total_reserves_bought"] = s.get("total_reserves_bought", 0) + match_stat.reserves_bought
    s["total_reserves_stranded"] = s.get("total_reserves_stranded", 0) + match_stat.reserves_stranded
    s["avg_reserves_acquired"] = round(s["total_reserves_acquired"] / games, 2)
    s["avg_reserves_bought"] = round(s["total_reserves_bought"] / games, 2)
    s["avg_reserves_stranded"] = round(s["total_reserves_stranded"] / games, 2)
    s["reserves_redemption_rate_pct"] = round(
        (s["total_reserves_bought"] / max(s["total_reserves_acquired"], 1)) * 100.0, 1
    )

    s["total_nobles"] = s.get("total_nobles", 0) + match_stat.nobles
    s["avg_nobles"] = round(s["total_nobles"] / games, 2)

    # Head-to-head records
    h2h = s.get("head_to_head", {})
    opp_entry = h2h.get(opponent_name, {"games": 0, "wins": 0, "ties": 0, "losses": 0, "score_diff": 0})
    opp_entry["games"] += 1
    if match_stat.won == 1.0:
        opp_entry["wins"] += 1
    elif match_stat.won == 0.5:
        opp_entry["ties"] += 1
    else:
        opp_entry["losses"] += 1
    opp_entry["score_diff"] += (match_stat.score - opp_score)
    opp_entry["win_rate_pct"] = round(
        (opp_entry["wins"] + 0.5 * opp_entry["ties"]) / opp_entry["games"] * 100.0, 1
    )
    h2h[opponent_name] = opp_entry
    s["head_to_head"] = h2h

    return s
