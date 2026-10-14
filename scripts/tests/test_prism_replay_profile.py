"""Targeted tests for saved replay profiles; no game generation is used."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import prism_replay_profile as profile
from training.prism_portable.engine.ppo import building


SAMPLE_ROOT_ENV = "PRISM_REPLAY_PROFILE_SAMPLE_ROOT"


def _observation(purchased: list[int], bonuses: list[int], *, phase: str = "main",
                 market_card: int | None = None, reserved: list[dict] | None = None) -> dict:
    market = [[None] * 4 for _ in range(3)]
    if market_card is not None:
        tier = building.CARD_CATALOG[market_card][0]
        market[building.TIERS.index(tier)][0] = market_card
    return {
        "viewer": 0,
        "ruleset_fingerprint": building.BASE_CATALOG_FINGERPRINT,
        "public": {
            "current_player": 0,
            "phase": phase,
            "market": market,
            "players": [
                {"id": 0, "bonuses": bonuses[:], "purchased": purchased[:]},
                {"id": 1},
            ],
        },
        "private": {"reserved": list(reserved or [])},
    }


def _decisions(main_actions: list[tuple[str, int | None]], *, noble_after: set[int] = frozenset()) -> list[dict]:
    """Create visible decision rows for the M62 profile contract, without claiming replay verification."""
    purchased: list[int] = []
    bonuses = [0] * 5
    reserved: list[dict] = []
    decisions: list[dict] = []
    for own_main, (kind, card_id) in enumerate(main_actions, start=1):
        card = building.CARD_CATALOG[card_id] if card_id is not None else None
        observation = _observation(
            purchased, bonuses,
            market_card=card_id if kind in ("buy_market", "reserve_market") else None,
            reserved=reserved,
        )
        if kind == "buy_market":
            action = {"type": kind, "tier": card[0], "slot": 0}
        elif kind == "reserve_market":
            action = {"type": kind, "tier": card[0], "slot": 0}
        elif kind == "buy_reserved":
            action = {"type": kind, "slot": 0}
        else:
            action = {"type": kind}
        decisions.append({"ply": len(decisions), "observation": observation, "chosen_action": action})

        if kind == "buy_market":
            purchased.append(card_id)
            bonuses[card[1]] += 1
        elif kind == "reserve_market":
            reserved = [{"slot": 0, "card": card_id, "tier": card[0], "from_deck": False}]
        elif kind == "buy_reserved":
            reserved_card = reserved[0]["card"]
            reserved_def = building.CARD_CATALOG[reserved_card]
            purchased.append(reserved_card)
            bonuses[reserved_def[1]] += 1
            reserved = []

        if own_main in noble_after:
            noble_observation = _observation(purchased, bonuses, phase="choose_noble", reserved=reserved)
            decisions.append({
                "ply": len(decisions),
                "observation": noble_observation,
                "chosen_action": {"type": "choose_noble", "noble": 0},
            })
    return decisions


def _low_cards_for_colours(colours: tuple[int, ...], count_each: int) -> list[int]:
    result = []
    for colour in colours:
        matches = [
            card_id for card_id, card in enumerate(building.CARD_CATALOG)
            if card[0] == "One" and card[1] == colour and card[2] <= 1
        ]
        assert len(matches) >= count_each
        result.extend(matches[:count_each])
    return result


def _full_rows(decisions: list[dict]) -> list[dict]:
    rows = []
    for decision in decisions:
        rows.append({"observation": decision["observation"], "chosen_action": decision["chosen_action"]})
    return rows


def test_building_profile_caps_each_investment_at_three_and_accepts_reserved_purchase() -> None:
    investment = next(
        i for i, card in enumerate(building.CARD_CATALOG)
        if card[0] == "One" and card[1] == 1 and card[2] == 0
    )
    qualifying = [
        i for i, card in enumerate(building.CARD_CATALOG)
        if card[0] in ("Two", "Three") and card[3][1] >= 1
    ][:4]
    actions: list[tuple[str, int | None]] = [("buy_market", investment)]
    actions.extend(("take_tokens", None) for _ in range(11))
    actions.append(("reserve_market", qualifying[0]))
    actions.append(("buy_reserved", None))
    actions.extend(("buy_market", card_id) for card_id in qualifying[1:])
    actions.extend(("take_tokens", None) for _ in range(24 - len(actions)))
    decisions = _decisions(actions)

    result = building.profile_from_own_decisions(
        _full_rows(decisions), 0, building.default_building_config(), terminal=True
    )
    assert result["main_actions"] == 24
    assert result["early_lowvp_buys"] == 1
    assert result["building_observed_use_units"] == 4
    assert result["building_use_units_before_global_cap"] == 3
    assert result["building_use_units"] == 3


def test_building_profile_applies_game_cap_after_per_investment_caps() -> None:
    investments = _low_cards_for_colours((0, 1, 2), 3)
    # Twelve distinct later purchases, with at least three qualifying purchases
    # for each of the three investment colours at ordinal <= 3.
    later_cards = [70, 72, 73, 74, 76, 78, 79, 81, 82, 84, 86, 88]
    assert len(set(later_cards)) == 12
    assert all(building.CARD_CATALOG[i][0] in ("Two", "Three") for i in later_cards)
    assert all(sum(building.CARD_CATALOG[i][3][c] >= 3 for i in later_cards) >= 3 for c in (0, 1, 2))
    actions = [("buy_market", card_id) for card_id in investments]
    actions.extend(("take_tokens", None) for _ in range(3))
    actions.extend(("buy_market", card_id) for card_id in later_cards)
    assert len(actions) == 24
    result = building.profile_from_own_decisions(
        _full_rows(_decisions(actions)), 0, building.default_building_config(), terminal=True
    )
    assert result["early_lowvp_buys"] == 9
    assert result["building_observed_use_units"] >= 27
    assert result["building_use_units_before_global_cap"] == 27
    assert result["building_use_units"] == 24


def test_building_profile_marks_unredeemed_investment_censored_before_main24() -> None:
    investment = _low_cards_for_colours((1,), 1)[0]
    actions = [("buy_market", investment)]
    actions.extend(("take_tokens", None) for _ in range(19))
    result = building.profile_from_own_decisions(
        _full_rows(_decisions(actions)), 0, building.default_building_config(), terminal=True
    )
    assert result["main_actions"] == 20
    assert result["redemption_horizon_censored"] is True
    assert result["unredeemed_investments"] == 1
    assert result["unredeemed_censored_investments"] == 1
    assert result["censored_investments"] == 1


def test_first_big_timing_counts_market_and_reserved_buys_but_not_noble_choice() -> None:
    low = _low_cards_for_colours((0,), 1)[0]
    big_market = next(i for i, card in enumerate(building.CARD_CATALOG) if card[2] == 4)
    big_reserved = next(i for i, card in enumerate(building.CARD_CATALOG) if card[2] == 5)
    actions = [("take_tokens", None) for _ in range(11)]
    actions.append(("buy_market", low))
    actions.append(("buy_market", big_market))
    actions.append(("reserve_market", big_reserved))
    actions.append(("buy_reserved", None))
    decisions = _decisions(actions, noble_after={12})
    first_big, purchases, main_actions = profile._first_big_purchase(decisions)
    building_result = building.profile_from_own_decisions(
        _full_rows(decisions), 0, building.default_building_config(), terminal=True
    )
    assert first_big == 13
    assert [event["action_type"] for event in purchases if event["printed_vp"] >= 4] == [
        "buy_market", "buy_reserved"
    ]
    assert main_actions == 15
    assert building_result["main_actions"] == 15


def _sample_rows(sample_root: Path) -> list[dict]:
    rows = []
    candidate_sha = "eaa1331b29599f239299b5a9037100ae042c6021b2195df3f675c2eb5bd62bf5"
    opponent_sha = "d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9"
    for artifact_id, model, model_sha in (
        ("a-alpha-13013000", "M75 c20", candidate_sha),
        ("base-alpha-13013000", "Balance v0.2.3", "e16bfe0d30168d6ef7ceb067ca4357900f1c09e09d35f5759832dd3d6a9258ad"),
    ):
        root = sample_root / artifact_id
        ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
        for seat in (0, 1):
            key = f"{'a' if artifact_id.startswith('a-') else 'base'}/alpha/seed-13013000/seat-{seat}"
            entry = ledger["entries"][key]
            assert entry["state"] == "COMPLETED"
            rel = Path("games") / ("a" if artifact_id.startswith("a-") else "base") / "alpha" / f"seed-13013000-seat-{seat}" / "replay.json"
            rows.append({
                "game_key": f"{model}/alpha/13013000/seat-{seat}",
                "replay_path": root / rel,
                "replay_sha256": entry["evidence_sha256"]["replay.json"],
                "candidate_model": model,
                "opponent_model": "alpha",
                "candidate_sha256": model_sha,
                "opponent_sha256": opponent_sha,
                "candidate_seat": seat,
                "seed": 13013000,
            })
    return rows


def test_real_m75_projection_envelope_and_candidate_parent_sample() -> None:
    sample_root_text = os.environ.get(SAMPLE_ROOT_ENV)
    if not sample_root_text:
        pytest.skip(f"set {SAMPLE_ROOT_ENV} to the extracted M75 raw evaluation directory")
    sample_root = Path(sample_root_text)
    assert sample_root.is_dir()
    rows = _sample_rows(sample_root)
    output = profile.profile_saved_replays(rows, batch_size=4)
    receipt = output["verify_receipt"]
    assert receipt["status"] == "PASS"
    assert receipt["games_verified"] == 4
    assert receipt["actor_profiles"] == 8
    assert receipt["new_games"] == 0
    assert receipt["projector"]["build"]["returncode"] == 0
    assert receipt["projector"]["build"]["command"][-2:] == ["--example", "prism_building_projection"]
    assert set(receipt["projector"]["sources"]) == {
        "crates/splendor-cli/examples/prism_building_projection.rs",
        "Cargo.lock",
        "training/prism_portable/engine/ppo/building.py",
        "crates/splendor-catalog/src/cards.rs",
    }
    for batch in receipt["batches"]:
        assert batch["projection_format"] == profile.PROJECTION_FORMAT
    flattened = [actor for actors in output["profiles"].values() for actor in actors]
    candidate_parent_profiles = [
        p for p in flattened if p["model"] in {"M75 c20", "Balance v0.2.3"}
    ]
    assert len(candidate_parent_profiles) == 4
    assert {p["model"] for p in candidate_parent_profiles} == {"M75 c20", "Balance v0.2.3"}
    assert {p["seat"] for p in candidate_parent_profiles} == {0, 1}
    aggregate = profile.aggregate_profiles(flattened)
    assert aggregate["unique_replays"] == 4
    assert aggregate["actor_profile_rows"] == 8
