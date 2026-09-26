#!/usr/bin/env python3
"""Summarize a verified S4 replay-economics diagnostic, not counterfactual outcomes.

The Rust extractor validates whole replays and candidate argmax membership.
This script derives descriptive reserve lifecycle, resource use, and the SAME
score-readiness opportunity metric for pre/post-pilot diagnostics. No games,
policy selection, weights, or benchmark outcomes are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def economy(games: list[dict], candidate: bool) -> dict:
    actions, finals, lives = [], [], []
    first_buys = []
    for game in games:
        seat = game["rotation"] if candidate else 1 - game["rotation"]
        player_actions = [a for a in game["actions"] if a["actor"] == seat]
        actions.extend(player_actions)
        final = game["final_players"][seat]
        finals.append(final)
        buys = [a for a in player_actions if a["kind"].startswith("buy_")]
        if buys:
            first_buys.append(buys[0]["main_turn"])
        active: dict[int, dict] = {}
        for a in player_actions:
            if a["kind"] == "reserve_market":
                card = a["card"]
                require(card["id"] not in active, "reserved twice without buying")
                life = {"card": card["id"], "tier": card["tier"], "vp": card["vp"],
                        "gap_at_acquisition": card["gap"], "acquired_turn": a["main_turn"],
                        "bought": False}
                active[card["id"]] = life
                lives.append(life)
            elif a["kind"] == "buy_reserved" and a["card"]["id"] in active:
                life = active.pop(a["card"]["id"])
                life.update(bought=True, holding_turns=a["main_turn"] - life["acquired_turn"])
        for life in active.values():
            require(life["card"] in final["reserved"], "unclosed lifecycle missing at end")
            life["holding_turns"] = final["main_turns"] - life["acquired_turn"]
    reserves = [a for a in actions if a["kind"].startswith("reserve_")]
    buys = [a for a in actions if a["kind"].startswith("buy_")]
    gold_received = sum(a["gold_after"] - a["gold_before"] for a in reserves)
    gold_spent = sum(a["gold_before"] - a["gold_after"] for a in buys)
    return {
        "action_counts": dict(sorted(Counter(a["kind"] for a in actions).items())),
        "card_vp_total": sum(p["card_vp"] for p in finals),
        "nobles_total": sum(len(p["nobles"]) for p in finals),
        "main_turns_mean": mean(p["main_turns"] for p in finals),
        "first_purchase_main_turn_mean": mean(first_buys) if first_buys else None,
        "unbought_reserves_total": sum(len(p["reserved"]) for p in finals),
        "unbought_reserves_mean": mean(len(p["reserved"]) for p in finals),
        "reserves_with_positive_net_gold": sum(a["gold_after"] > a["gold_before"] for a in reserves),
        "net_gold_from_reserves": gold_received,
        "gold_spent_on_purchases": gold_spent,
        "visible_reserve_lifecycles": {
            "acquired": len(lives), "bought": sum(r["bought"] for r in lives),
            "acquisition_gap_median": median(r["gap_at_acquisition"] for r in lives) if lives else None,
            "bought_hold_turns_median": median(r["holding_turns"] for r in lives if r["bought"]) if any(r["bought"] for r in lives) else None,
            "unbought_hold_turns_median": median(r["holding_turns"] for r in lives if not r["bought"]) if any(not r["bought"] for r in lives) else None,
            "note": "unbought lifetimes are right-censored; not evidence that the reserve action was wasteful",
        },
    }


def is_opportunity(decision: dict) -> bool:
    take = decision["best_ready_take"]
    return (decision["phase"] == "Score" and not decision["end_game_triggered"]
            and take is not None and take["ready_vp"] >= 3)


def is_missed(decision: dict) -> bool:
    return (is_opportunity(decision)
            and decision["chosen"]["kind"] in ("take", "reserve_market", "reserve_deck")
            and decision["chosen_ready_vp"] < decision["best_ready_take"]["ready_vp"])


def summarize(data: dict) -> dict:
    require(data["format"] == "s4-replay-economics-diagnostic-v1", "unknown schema")
    games = data["games"]
    keys = {(g["opponent"], g["seed"], g["rotation"]) for g in games}
    require(len(keys) == len(games) > 0, "empty or duplicate games")
    pairings = []
    for opponent in sorted({g["opponent"] for g in games}):
        subset = [g for g in games if g["opponent"] == opponent]
        decisions = [d for g in subset for d in g["decisions"]]
        opportunities = [d for d in decisions if is_opportunity(d)]
        missed = [d for d in decisions if is_missed(d)]
        chosen_new_term = [d for d in decisions if d["chosen"]["terms"].get("scoring_readiness", 0) > 0]
        cases = []
        for game in sorted(subset, key=lambda g: (g["seed"], g["rotation"])):
            for d in game["decisions"]:
                if is_missed(d) and len(cases) < 2:
                    cases.append({"seed": game["seed"], "rotation": game["rotation"],
                                  "decision": d})
        pairings.append({
            "opponent": opponent, "games": len(subset), "decisions": len(decisions),
            "phase_counts": dict(sorted(Counter(d["phase"] for d in decisions).items())),
            "candidate": economy(subset, True), "opponent_economy": economy(subset, False),
            "scoring_readiness": {
                "score_nonfinal_decisions": sum(d["phase"] == "Score" and not d["end_game_triggered"] for d in decisions),
                "three_plus_vp_take_opportunities": len(opportunities),
                "nonbuy_choices_preparing_lower_vp": len(missed),
                "lower_vp_choice_kind": dict(sorted(Counter(d["chosen"]["kind"] for d in missed).items())),
                "held_card_improves_beyond_actual_in_missed": sum(d["best_ready_take"]["held_ready_vp"] > d["chosen_ready_vp"] for d in missed),
                "chosen_readiness_term_nonzero": len(chosen_new_term),
            },
            "additive_1200_term_removal": {
                "three_vp_chosen_strictly_loses_argmax": sum(d["remove_three_vp_changes_chosen_argmax"] for d in decisions),
                "reserved_chosen_strictly_loses_argmax": sum(d["remove_reserved_bonus_changes_chosen_argmax"] for d in decisions),
                "note": "same-root term-only diagnostic, not whole-policy ablation or trajectory effect",
            },
            "examples_first_two_by_seed_rotation_ply": cases,
        })
    return {"format": "s4-economics-summary-v1", "scorer_version": data["scorer_version"],
            "games": len(games), "decisions": sum(len(g["decisions"]) for g in games),
            "manifest_sha256": data["manifest_sha256"], "pairings": pairings,
            "semantics": "descriptive observed trajectories; readiness means legal affordability if board persists, not guaranteed next-turn availability or better play; no counterfactual wins"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    result = summarize(json.loads(raw))
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    result["summary_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"{result['scorer_version']}: {result['games']} games, {result['decisions']} candidate decisions")
    for pairing in result["pairings"]:
        readiness = pairing["scoring_readiness"]
        print(pairing["opponent"], "economy:", json.dumps(pairing["candidate"], ensure_ascii=False))
        print("  readiness:", readiness, "1200-removal:", pairing["additive_1200_term_removal"])


if __name__ == "__main__":
    main()
