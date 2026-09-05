"""P0 Contract tests for M42A Visible Action-Entity Relation Tensor Encoder."""

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
def base_obs():
    """Construct a clean 2-player observation for testing."""
    return {
        "viewer": 0,
        "public": {
            "player_count": 2,
            "current_player": 0,
            "phase": "main",
            "market": [
                [0, 1, 2, 3],      # Tier One
                [40, 41, 42, 43],  # Tier Two
                [70, 71, 72, 73],  # Tier Three
            ],
            "nobles": [0, 1, 2],
            "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
            "deck_counts": [36, 26, 16],
            "end_game_triggered": False,
            "turns_remaining_in_final_round": None,
            "consecutive_forced_passes": 0,
            "players": [
                {
                    "id": 0,
                    "tokens": {"white": 2, "blue": 1, "green": 0, "red": 0, "black": 0, "gold": 1},
                    "bonuses": [1, 0, 0, 0, 0],
                    "prestige": 0,
                    "reserved_count": 1,
                    "public_reserved": [4],
                },
                {
                    "id": 1,
                    "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
                    "bonuses": [0, 0, 0, 0, 0],
                    "prestige": 0,
                    "reserved_count": 1,
                    "public_reserved": [None],  # Blind reserve
                },
            ],
        },
        "private": {
            "reserved": [{"card": 4}],
        },
    }


def test_shape_and_zero_slots(catalog, base_obs):
    """Assert shape is (31, 28) and player/padding slots are all zeros."""
    action = {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1}, "return": {}}
    R = compute_action_visible_relation_tensor(base_obs, action, catalog)
    assert R.shape == (31, RELATION_DIM)

    # Slots 17, 18 (players) must be strictly 0
    assert torch.all(R[17] == 0.0)
    assert torch.all(R[18] == 0.0)

    # Slots 28, 29, 30 (padding) must be strictly 0
    assert torch.all(R[28] == 0.0)
    assert torch.all(R[29] == 0.0)
    assert torch.all(R[30] == 0.0)


def test_no_leak_p0_hard_gate(catalog, base_obs):
    """Assert relation tensor is strictly independent of any hidden/unseen elements."""
    action = {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1}, "return": {}}
    R1 = compute_action_visible_relation_tensor(base_obs, action, catalog)

    # 1. Tampering with opponent's blind reserve does not affect relation tensor
    obs_tampered = copy.deepcopy(base_obs)
    obs_tampered["public"]["players"][1]["public_reserved"] = [99]  # hypothetical opponent leak
    R2 = compute_action_visible_relation_tensor(obs_tampered, action, catalog)
    # The opponent's public reserved slot 22 may have a card, but viewer's market/noble/own cards are unaffected
    assert torch.equal(R1[:17], R2[:17])
    assert torch.equal(R1[25:], R2[25:])

    # 2. Blind reserve action: changing hypothetical drawn card never enters relation tensor
    reserve_deck_act = {"type": "reserve_deck", "tier": "One", "return": {}}
    R_res1 = compute_action_visible_relation_tensor(base_obs, reserve_deck_act, catalog)
    # Simulate an observer adding a hidden draw info to private
    obs_with_leak = copy.deepcopy(base_obs)
    obs_with_leak["private"]["drawn_card"] = 88
    R_res2 = compute_action_visible_relation_tensor(obs_with_leak, reserve_deck_act, catalog)
    assert torch.equal(R_res1, R_res2)

    # 3. Determinism
    R_det = compute_action_visible_relation_tensor(base_obs, action, catalog)
    assert torch.equal(R1, R_det)


def test_microfixture_take_tokens(catalog, base_obs):
    """Test take_tokens deficit reductions on market cards."""
    # Viewer has 2 white, 1 blue, 1 white bonus.
    # Take green, red, black.
    action = {"type": "take_tokens", "take": {"green": 1, "red": 1, "black": 1}, "return": {}}
    R = compute_action_visible_relation_tensor(base_obs, action, catalog)

    # No target entity
    assert torch.all(R[:, 2] == 0.0)  # action_targets_entity
    assert torch.all(R[:, 3] == 0.0)  # action_buys_entity
    assert torch.all(R[:, 4] == 0.0)  # action_reserves_entity
    assert torch.all(R[:, 6] == 0.0)  # entity_consumed_or_relocated

    # For every active market card (0..11), check that deficit reduction matches before - after
    for slot in range(12):
        assert torch.allclose(R[slot, 17:22], R[slot, 7:12] - R[slot, 12:17], atol=1e-6)
        assert pytest.approx(R[slot, 24].item(), abs=1e-6) == (R[slot, 22].item() - R[slot, 23].item())


def test_microfixture_buy_market(catalog, base_obs):
    """Test buy_market target properties and token tradeoff."""
    # Find a card in market
    card_id = base_obs["public"]["market"][0][0]
    action = {"type": "buy_market", "tier": "One", "slot": 0}
    R = compute_action_visible_relation_tensor(base_obs, action, catalog)

    # Target card is slot 0
    assert R[0, 0] == 1.0  # is_card
    assert R[0, 2] == 1.0  # action_targets_entity
    assert R[0, 3] == 1.0  # action_buys_entity
    assert R[0, 6] == 1.0  # entity_consumed_or_relocated
    assert torch.all(R[0, 12:17] == 0.0)  # after deficit = 0
    assert R[0, 23] == 0.0  # total deficit after = 0
    assert R[0, 26] == 1.0  # feasible_after = 1.0

    # Non-target cards must have action_targets_entity = 0
    assert torch.all(R[1:, 2] == 0.0)


def test_microfixture_reserve_market(catalog, base_obs):
    """Test reserve_market: relocated=1, but post-action deficit is still computed."""
    action = {"type": "reserve_market", "tier": "Two", "slot": 1, "return": {}}
    # Target slot is tier 1 * 4 + 1 = 5
    R = compute_action_visible_relation_tensor(base_obs, action, catalog)

    assert R[5, 0] == 1.0  # is_card
    assert R[5, 2] == 1.0  # action_targets_entity
    assert R[5, 3] == 0.0  # action_buys_entity = 0
    assert R[5, 4] == 1.0  # action_reserves_entity = 1
    assert R[5, 6] == 1.0  # entity_consumed_or_relocated = 1

    # In reserve_market, relocated cards still have deficits computed (not wiped to 0 unless naturally 0)
    card_id = base_obs["public"]["market"][1][1]
    card = catalog["cards"][card_id]
    if sum(card["cost"]) > 0:
        # Should have valid deficit before
        assert R[5, 22] > 0.0


def test_microfixture_buy_reserved(catalog, base_obs):
    """Test buy_reserved targeting slot 25."""
    action = {"type": "buy_reserved", "slot": 0}
    R = compute_action_visible_relation_tensor(base_obs, action, catalog)

    assert R[25, 0] == 1.0  # is_card
    assert R[25, 2] == 1.0  # action_targets_entity
    assert R[25, 3] == 1.0  # action_buys_entity
    assert R[25, 6] == 1.0  # entity_consumed_or_relocated
    assert R[25, 23] == 0.0  # deficit after = 0
    assert R[25, 26] == 1.0  # feasible after = 1.0


def test_microfixture_choose_noble(catalog, base_obs):
    """Test choose_noble targeting slot 12+noble_index."""
    action = {"type": "choose_noble", "noble": 1}
    R = compute_action_visible_relation_tensor(base_obs, action, catalog)

    # noble 1 is at index 1 -> slot 13
    assert R[13, 1] == 1.0  # is_noble
    assert R[13, 2] == 1.0  # action_targets_entity
    assert R[13, 5] == 1.0  # action_claims_entity
    assert R[13, 6] == 1.0  # entity_consumed_or_relocated
    assert R[13, 23] == 0.0  # deficit after = 0
    assert R[13, 26] == 1.0  # feasible after = 1.0


def test_observation_batching(catalog, base_obs):
    """Test computing relation tensors for a list of legal actions."""
    legal_actions = [
        {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1}, "return": {}},
        {"type": "buy_market", "tier": "One", "slot": 0},
        {"type": "reserve_market", "tier": "One", "slot": 1, "return": {}},
    ]
    batch = compute_observation_relation_tensors(base_obs, legal_actions, catalog)
    assert batch.shape == (3, 31, RELATION_DIM)
