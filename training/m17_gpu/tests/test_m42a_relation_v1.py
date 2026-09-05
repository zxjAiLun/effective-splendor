"""P0 Contract & Numeric Oracle tests for M42A Visible Action-Entity Relation Tensor Encoder."""

from __future__ import annotations

import copy
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import load_catalog
from splendor_gpu.m42a_relation_v1 import (
    RELATION_DIM,
    compute_action_visible_relation_tensor,
    compute_observation_relation_tensors,
)

CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")


@pytest.fixture
def catalog():
    return load_catalog(CATALOG_PATH)


@pytest.fixture
def oracle_setup():
    """Construct an observation and synthetic card for exact hand-calculated deficit testing."""
    # Synthetic custom catalog with known card: cost = [4, 2, 0, 0, 0] (4 white, 2 blue), bonus = green
    test_catalog = {
        "cards": {
            999: {
                "id": 999,
                "tier": "One",
                "bonus": "green",
                "prestige": 1,
                "cost": [4, 2, 0, 0, 0],
            },
            998: {
                "id": 998,
                "tier": "One",
                "bonus": "red",
                "prestige": 0,
                "cost": [0, 1, 0, 0, 0],  # costs 1 blue
            },
        },
        "nobles": {
            100: {
                "id": 100,
                "prestige": 3,
                "requirements": [3, 3, 0, 0, 0],  # 3 white, 3 blue
            }
        },
    }
    # Viewer has: tokens: white=1, blue=1, gold=1; bonuses: white=1
    obs = {
        "viewer": 0,
        "public": {
            "player_count": 2,
            "current_player": 0,
            "phase": "main",
            "market": [
                [999, 998, None, None],
                [None, None, None, None],
                [None, None, None, None],
            ],
            "nobles": [100],
            "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
            "deck_counts": [36, 26, 16],
            "end_game_triggered": False,
            "turns_remaining_in_final_round": None,
            "consecutive_forced_passes": 0,
            "players": [
                {
                    "id": 0,
                    "tokens": {"white": 1, "blue": 1, "green": 0, "red": 0, "black": 0, "gold": 1},
                    "bonuses": [1, 0, 0, 0, 0],
                    "prestige": 0,
                    "reserved_count": 0,
                    "public_reserved": [],
                },
                {
                    "id": 1,
                    "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
                    "bonuses": [0, 0, 0, 0, 0],
                    "prestige": 0,
                    "reserved_count": 0,
                    "public_reserved": [],
                },
            ],
        },
        "private": {
            "reserved": [],
        },
    }
    return obs, test_catalog


def test_hand_calculated_numeric_oracle(oracle_setup):
    """P2-1 Exact hand-calculated numeric oracle for deficits, reductions, and feasibility.

    Card 999: cost = [4 white, 2 blue, 0, 0, 0]
    Viewer: bonuses = [1 white, 0, 0, 0, 0], tokens = [1 white, 1 blue, 0, 0, 0], gold = 1

    Hand calculation BEFORE action:
      white deficit: max(0, 4 - 1 - 1) = 2 -> 2 / 7.0
      blue deficit:  max(0, 2 - 0 - 1) = 1 -> 1 / 7.0
      green/red/black: 0.0
      sum deficits:  3 -> total_deficit_before = 3 / 35.0
      feasible_before: 3 > 1 (gold) -> False (0.0)
    """
    obs, cat = oracle_setup
    # Action: take 1 white, 1 blue
    take_act = {"type": "take_tokens", "take": {"white": 1, "blue": 1}, "return": {}}
    R = compute_action_visible_relation_tensor(obs, take_act, cat)

    # Check slot 0 (card 999) BEFORE values
    assert pytest.approx(R[0, 7].item(), abs=1e-6) == 2.0 / 7.0   # white deficit before
    assert pytest.approx(R[0, 8].item(), abs=1e-6) == 1.0 / 7.0   # blue deficit before
    assert R[0, 9].item() == 0.0
    assert R[0, 10].item() == 0.0
    assert R[0, 11].item() == 0.0
    assert pytest.approx(R[0, 22].item(), abs=1e-6) == 3.0 / 35.0 # total deficit before
    assert R[0, 25].item() == 0.0                                 # feasible_before

    # Hand calculation AFTER action (took 1 white, 1 blue; tokens: white=2, blue=2, gold=1):
    #   white deficit: max(0, 4 - 1 - 2) = 1 -> 1 / 7.0
    #   blue deficit:  max(0, 2 - 0 - 2) = 0 -> 0.0
    #   sum deficits:  1 -> total_deficit_after = 1 / 35.0
    #   feasible_after: 1 <= 1 (gold) -> True (1.0)
    #   deficit reduction: white = (2-1)/7 = 1/7, blue = (1-0)/7 = 1/7, total = (3-1)/35 = 2/35
    #   newly_feasible: True (1.0)
    assert pytest.approx(R[0, 12].item(), abs=1e-6) == 1.0 / 7.0  # white deficit after
    assert pytest.approx(R[0, 13].item(), abs=1e-6) == 0.0        # blue deficit after
    assert pytest.approx(R[0, 23].item(), abs=1e-6) == 1.0 / 35.0 # total deficit after
    assert R[0, 26].item() == 1.0                                 # feasible_after
    assert pytest.approx(R[0, 17].item(), abs=1e-6) == 1.0 / 7.0  # white reduction
    assert pytest.approx(R[0, 18].item(), abs=1e-6) == 1.0 / 7.0  # blue reduction
    assert pytest.approx(R[0, 24].item(), abs=1e-6) == 2.0 / 35.0 # total reduction
    assert R[0, 27].item() == 1.0                                 # newly_feasible


def test_tradeoff_negative_deficit_reduction(oracle_setup):
    """Buying Card 998 spends the 1 blue token, increasing Card 999's blue deficit."""
    obs, cat = oracle_setup
    # Card 998 costs 1 blue. Viewer has 1 blue. Buying it spends the blue token.
    buy_act = {"type": "buy_market", "tier": "One", "slot": 1}
    R = compute_action_visible_relation_tensor(obs, buy_act, cat)

    # For Card 999 (slot 0):
    # Before: blue token = 1 -> blue deficit = 1/7
    # After: blue token = 0 -> blue deficit = 2/7
    # Deficit reduction on blue should be negative: (1 - 2) / 7 = -1/7
    assert pytest.approx(R[0, 8].item(), abs=1e-6) == 1.0 / 7.0
    assert pytest.approx(R[0, 13].item(), abs=1e-6) == 2.0 / 7.0
    assert pytest.approx(R[0, 18].item(), abs=1e-6) == -1.0 / 7.0


def test_reserve_deck_exact_fixture(oracle_setup):
    """P2-1 Test reserve_deck exact behavior: gains gold, updates feasibility without targeting cards."""
    obs, cat = oracle_setup
    # Card 999 has total deficit 3. Viewer has 1 gold.
    # reserve_deck gives +1 gold (bank has gold > 0). New gold = 2.
    # Total deficit remains 3. Since 3 > 2, still not feasible.
    act = {"type": "reserve_deck", "tier": "One", "return": {}}
    R = compute_action_visible_relation_tensor(obs, act, cat)

    # No card is targeted or consumed
    assert torch.all(R[:, 2] == 0.0)  # action_targets_entity
    assert torch.all(R[:, 3] == 0.0)  # action_buys_entity
    assert torch.all(R[:, 4] == 0.0)  # action_reserves_entity
    assert torch.all(R[:, 6] == 0.0)  # entity_consumed_or_relocated

    # Deficits before and after are identical because tokens did not change
    assert torch.equal(R[0, 7:12], R[0, 12:17])
    assert R[0, 22] == R[0, 23]
    assert torch.all(R[0, 17:22] == 0.0)
    assert R[0, 24] == 0.0
    assert R[0, 25] == 0.0  # feasible_before
    assert R[0, 26] == 0.0  # feasible_after


def test_pass_exact_fixture(oracle_setup):
    """P2-1 Test pass action: bit-exact before == after, all reductions zero."""
    obs, cat = oracle_setup
    act = {"type": "pass"}
    R = compute_action_visible_relation_tensor(obs, act, cat)

    # All targets are zero
    assert torch.all(R[:, 2:7] == 0.0)

    # For card 999 (slot 0)
    assert torch.equal(R[0, 7:12], R[0, 12:17])
    assert R[0, 22] == R[0, 23]
    assert torch.all(R[0, 17:22] == 0.0)
    assert R[0, 24] == 0.0
    assert R[0, 25] == R[0, 26]
    assert R[0, 27] == 0.0


def test_player_view_boundary_and_determinism(catalog, oracle_setup):
    """P2-1 Strict player-view boundary test:
    Verify that relation computation is a pure, deterministic function of
    (Observation, Action, Catalog) and does not rely on global/hidden state."""
    obs, cat = oracle_setup
    act = {"type": "take_tokens", "take": {"white": 1, "blue": 1}, "return": {}}

    R1 = compute_action_visible_relation_tensor(obs, act, cat)
    R2 = compute_action_visible_relation_tensor(copy.deepcopy(obs), copy.deepcopy(act), cat)

    # Determinism
    assert torch.equal(R1, R2)

    # Shape and padding invariants
    assert R1.shape == (31, RELATION_DIM)
    assert torch.all(R1[17] == 0.0)  # player 0
    assert torch.all(R1[18] == 0.0)  # player 1
    assert torch.all(R1[28:] == 0.0)  # padding slots 28..30
