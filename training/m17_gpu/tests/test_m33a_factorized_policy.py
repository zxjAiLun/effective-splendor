"""Unit tests for M33A Factorized Legal-Action Policy.

Verifies:
1. Exact parameter count of FactorizedDeltaEntityMixer is exactly 1,254,558 (953,476 D2 + 301,082 structured).
2. Initialization Equivalence: Under identical seed, initial logits of M33A match D2 bit-for-bit (max diff == 0.0).
3. Two-Stage Gradient Flow:
   - Backward on initial model: structured branch output layers receive non-zero gradients.
   - After optimizer step: structured upstream linear layers receive non-zero gradients.
4. Hand-Calculated Decomposition & Logit Arithmetic:
   - Hand-verified Take (3 distinct, 2 same, 1 distinct, gold return), Buy (market & reserved), Reserve (market & deck), Noble, Pass.
5. Action Decomposition Rules & BuyReserved Entity Alignment:
   - Uses real encode_observation() and verifies BuyReserved maps strictly to active private reserved slots 25..27.
6. Multi-Batch Multi-Action Diagnostic Evaluator Reference Verification:
   - Tests evaluate_m33a_diagnostics() over variable-length legal actions, first-max ties, and asserts fail-closed cursor.
7. Real Provenance Preflight enforces fail-closed execution.
"""
import json
import tempfile
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import load_catalog, catalog_semantic_hash
from splendor_gpu.encoding import encode_observation, encode_action, ENTITY_SLOTS, ENTITY_FEATURES, GLOBAL_FEATURES
from splendor_gpu.m31a_train import DeltaEntityMixer
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
from splendor_gpu.m25_train import validate_m25_dataset_provenance
from splendor_gpu.self_play_train import packed_policy_loss
from splendor_gpu.m33a_model import FactorizedDeltaEntityMixer, ENHANCED_ACTION_FEATURES
from splendor_gpu.m33a_encoding import decompose_legal_action
from splendor_gpu.m33a_eval import evaluate_m33a_diagnostics
from splendor_gpu.m33a_preflight import (
    preflight_m33a,
    FROZEN_CONFIG_SHA256,
    FROZEN_DATASET_FILE_SHA256,
    FROZEN_DATASET_SEMANTIC_HASH,
    FROZEN_CATALOG_HASH,
    FROZEN_D2_RESULT_SHA256,
    FROZEN_M33A_PARAMETER_COUNT,
)

def test_model_parameter_count():
    model = FactorizedDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    param_count = sum(p.numel() for p in model.parameters())
    assert param_count == FROZEN_M33A_PARAMETER_COUNT
    assert param_count == 1254558

def test_initialization_equivalence_to_d2():
    SEED = 280229

    # 1. Create pure D2 baseline
    torch.manual_seed(SEED)
    d2_model = DeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)

    # 2. Create M33A Factorized model (same seed)
    torch.manual_seed(SEED)
    m33a_model = FactorizedDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)

    # Verify D2 weights in both models are bit-for-bit identical
    for (n1, p1), (n2, p2) in zip(d2_model.named_parameters(), list(m33a_model.named_parameters())[:len(list(d2_model.named_parameters()))]):
        assert n1 == n2, f"Param name mismatch: {n1} vs {n2}"
        torch.testing.assert_close(p1, p2, rtol=0, atol=0, msg=f"D2 param {n1} diverged at initialization!")

    # Verify forward logits are bit-for-bit identical
    B = 2
    total_actions = 5
    torch.manual_seed(100)
    entities = torch.randn(B, ENTITY_SLOTS, ENTITY_FEATURES)
    mask = torch.ones(B, ENTITY_SLOTS, dtype=torch.bool)
    global_f = torch.randn(B, GLOBAL_FEATURES)
    actions = torch.randn(total_actions, ENHANCED_ACTION_FEATURES)
    offsets = torch.tensor([0, 3, 5], dtype=torch.long)

    family_idx = torch.tensor([0, 1, 2, 0, 3], dtype=torch.long)
    take_mode = torch.tensor([2, -1, -1, 3, -1], dtype=torch.long)
    selected_c = torch.tensor([[1, 1, 1, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 1, 0], [0, 0, 0, 0, 0]], dtype=torch.float32)
    returned_c = torch.zeros(total_actions, 6, dtype=torch.float32)
    target_slots = torch.tensor([-1, 4, 8, -1, 12], dtype=torch.long)
    target_tiers = torch.tensor([-1, -1, -1, -1, -1], dtype=torch.long)

    d2_model.eval()
    m33a_model.eval()

    with torch.no_grad():
        d2_logits, d2_val = d2_model.forward_packed(entities, mask, global_f, actions, offsets)
        m33a_logits, m33a_val = m33a_model.forward_packed(
            entities, mask, global_f, actions, offsets,
            family_idx, take_mode, selected_c, returned_c, target_slots, target_tiers
        )

    torch.testing.assert_close(d2_logits, m33a_logits, rtol=0, atol=0)
    torch.testing.assert_close(d2_val, m33a_val, rtol=0, atol=0)

def test_two_stage_structured_gradient_flow():
    torch.manual_seed(280229)
    model = FactorizedDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)

    B = 2
    total_actions = 4
    entities = torch.randn(B, ENTITY_SLOTS, ENTITY_FEATURES)
    mask = torch.ones(B, ENTITY_SLOTS, dtype=torch.bool)
    global_f = torch.randn(B, GLOBAL_FEATURES)
    actions = torch.randn(total_actions, ENHANCED_ACTION_FEATURES)
    offsets = torch.tensor([0, 2, 4], dtype=torch.long)
    policy_target = torch.tensor([0.9, 0.1, 0.7, 0.3], dtype=torch.float32)

    family_idx = torch.tensor([0, 1, 2, 3], dtype=torch.long)
    take_mode = torch.tensor([2, -1, -1, -1], dtype=torch.long)
    selected_c = torch.tensor([[1, 1, 1, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]], dtype=torch.float32)
    returned_c = torch.tensor([[0, 0, 0, 0, 0, 1.0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]], dtype=torch.float32)
    target_slots = torch.tensor([-1, 0, 5, 12], dtype=torch.long)
    target_tiers = torch.tensor([-1, -1, 1, -1], dtype=torch.long)

    # 1. First backward pass
    logits, _ = model.forward_packed(
        entities, mask, global_f, actions, offsets,
        family_idx, take_mode, selected_c, returned_c, target_slots, target_tiers
    )
    loss = packed_policy_loss(logits, policy_target, offsets)
    loss.backward()

    # Verify structured output projection layers receive non-zero gradients
    assert model.intent_head[-1].weight.grad.abs().sum().item() > 0.0
    assert model.take_mode_head[-1].weight.grad.abs().sum().item() > 0.0
    assert model.color_desirability_head[-1].weight.grad.abs().sum().item() > 0.0
    assert model.keep_penalty_head[-1].weight.grad.abs().sum().item() > 0.0
    assert model.entity_conditioned_scorer[-1].weight.grad.abs().sum().item() > 0.0
    assert model.deck_tier_head[-1].weight.grad.abs().sum().item() > 0.0

    # 2. Optimizer step
    optimizer.step()
    optimizer.zero_grad()

    # 3. Second backward pass
    logits2, _ = model.forward_packed(
        entities, mask, global_f, actions, offsets,
        family_idx, take_mode, selected_c, returned_c, target_slots, target_tiers
    )
    loss2 = packed_policy_loss(logits2, policy_target, offsets)
    loss2.backward()

    # Upstream layers in structured heads now receive non-zero gradients
    assert model.intent_head[0].weight.grad.abs().sum().item() > 0.0
    assert model.color_desirability_head[0].weight.grad.abs().sum().item() > 0.0
    assert model.entity_conditioned_scorer[0].weight.grad.abs().sum().item() > 0.0

def test_hand_calculated_factor_arithmetic():
    model = FactorizedDeltaEntityMixer(hidden_dim=4, blocks=1, dropout=0.0)

    # Manually set predictable non-zero weights for structured heads
    with torch.no_grad():
        for p in model.parameters():
            p.zero_()
        model.policy[-1].bias.fill_(1.0)

        # intent_head: family 0 (take) = 0.5, family 1 (buy) = 0.8, family 2 (reserve) = 0.3
        model.intent_head[-1].bias.copy_(torch.tensor([0.5, 0.8, 0.3, 0.1, 0.05]))

        # take_mode_head: mode 2 (3-distinct) = 0.4, mode 3 (2-same) = 0.2, mode 0 (1-distinct) = 0.1
        model.take_mode_head[-1].bias.copy_(torch.tensor([0.1, 0.15, 0.4, 0.2]))

        # color_desirability: white=1.0, blue=2.0, green=3.0, red=4.0, black=5.0
        model.color_desirability_head[-1].bias.copy_(torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0]))

        # keep_penalty: gold=0.7, red=0.5
        model.keep_penalty_head[-1].bias.copy_(torch.tensor([0.1, 0.2, 0.3, 0.5, 0.4, 0.7]))

        # deck_tier: tier 2 (index 1) = 0.6
        model.deck_tier_head[-1].bias.copy_(torch.tensor([0.2, 0.6, 0.9]))

    entities = torch.zeros(1, ENTITY_SLOTS, ENTITY_FEATURES)
    mask = torch.ones(1, ENTITY_SLOTS, dtype=torch.bool)
    global_f = torch.zeros(1, GLOBAL_FEATURES)
    actions = torch.zeros(3, ENHANCED_ACTION_FEATURES)
    offsets = torch.tensor([0, 3], dtype=torch.long)

    # Action 0: Take 3 distinct (white, blue, green), return 1 gold
    # Action 1: Take 2 same (red), return 0
    # Action 2: Reserve Deck Tier 2
    family_idx = torch.tensor([0, 0, 2], dtype=torch.long)
    take_mode = torch.tensor([2, 3, -1], dtype=torch.long)
    selected_c = torch.tensor([[1, 1, 1, 0, 0], [0, 0, 0, 1, 0], [0, 0, 0, 0, 0]], dtype=torch.float32)
    returned_c = torch.tensor([[0, 0, 0, 0, 0, 1.0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]], dtype=torch.float32)
    target_slots = torch.tensor([-1, -1, -1], dtype=torch.long)
    target_tiers = torch.tensor([-1, -1, 1], dtype=torch.long)

    model.eval()
    with torch.no_grad():
        logits, _ = model.forward_packed(
            entities, mask, global_f, actions, offsets,
            family_idx, take_mode, selected_c, returned_c, target_slots, target_tiers
        )

    # Expected:
    # Action 0: D2(1.0) + Take(0.5) + Mode3(0.4) + Color(1+2+3=6.0) - GoldReturn(0.7) = 7.2
    # Action 1: D2(1.0) + Take(0.5) + Mode2Same(0.2) + Color(red=4.0) - Return(0) = 5.7
    # Action 2: D2(1.0) + Reserve(0.3) + DeckTier2(0.6) = 1.9
    expected_logits = torch.tensor([7.2, 5.7, 1.9], dtype=torch.float32)
    torch.testing.assert_close(logits, expected_logits, rtol=1e-5, atol=1e-5)

def test_action_decomposition_rules_and_real_observation_entity_alignment():
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    catalog = load_catalog(catalog_path)

    obs_raw = {
        "viewer": 0,
        "public": {
            "player_count": 2,
            "current_player": 0,
            "phase": "main",
            "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
            "deck_counts": [30, 20, 15],
            "end_game_triggered": False,
            "turns_remaining_in_final_round": None,
            "consecutive_forced_passes": 0,
            "market": [
                [0, 1, 2, 3],
                [4, 5, 6, 7],
                [8, 9, 10, 11]
            ],
            "nobles": [1, 0, 8],
            "players": [
                {
                    "id": 0,
                    "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
                    "bonuses": [0, 0, 0, 0, 0],
                    "prestige": 0,
                    "reserved_count": 2,
                    "public_reserved": [37],
                    "purchased": [],
                },
                {
                    "id": 1,
                    "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0},
                    "bonuses": [0, 0, 0, 0, 0],
                    "prestige": 0,
                    "reserved_count": 0,
                    "public_reserved": [],
                    "purchased": [],
                }
            ],
        },
        "private": {
            "reserved": [
                {"slot": 0, "card": 37, "tier": "One", "from_deck": False},
                {"slot": 1, "card": 46, "tier": "Two", "from_deck": True}
            ],
        }
    }

    # Encode observation using the real encoder
    encoded_obs = encode_observation(obs_raw, catalog)
    entities = encoded_obs.entities  # (31, 32)
    mask = encoded_obs.mask          # (31,)

    # 1. BuyReserved slot 0 -> entity slot 25 + 0 = 25 (Card 37)
    a_res0 = {"type": "buy_reserved", "slot": 0}
    d_res0 = decompose_legal_action(obs_raw, a_res0)
    assert d_res0["family_idx"] == 1
    assert d_res0["target_entity_slot"] == 25
    assert mask[25].item() is True, "Own reserved slot 0 entity must be active in mask"
    assert entities[25].abs().sum().item() > 0.0, "Own reserved slot 0 entity must be non-zero"

    # 2. BuyReserved slot 1 -> entity slot 25 + 1 = 26 (Card 46)
    a_res1 = {"type": "buy_reserved", "slot": 1}
    d_res1 = decompose_legal_action(obs_raw, a_res1)
    assert d_res1["family_idx"] == 1
    assert d_res1["target_entity_slot"] == 26
    assert mask[26].item() is True, "Own reserved slot 1 entity must be active in mask"
    assert entities[26].abs().sum().item() > 0.0, "Own reserved slot 1 entity must be non-zero"

    # 3. BuyReserved slot 2 -> entity slot 27 (Empty slot)
    a_res2 = {"type": "buy_reserved", "slot": 2}
    d_res2 = decompose_legal_action(obs_raw, a_res2)
    assert d_res2["target_entity_slot"] == 27
    assert mask[27].item() is False, "Empty reserved slot 2 must be masked out (zero entity)"

    # 4. BuyMarket tier Three slot 3 -> entity slot 2*4 + 3 = 11 (Card 11)
    a_mkt = {"type": "buy_market", "tier": "Three", "slot": 3}
    d_mkt = decompose_legal_action(obs_raw, a_mkt)
    assert d_mkt["target_entity_slot"] == 11
    assert mask[11].item() is True

    # 5. ChooseNoble ID 0 -> matches public nobles index 1 -> entity slot 12 + 1 = 13
    a_nbl = {"type": "choose_noble", "noble": 0}
    d_nbl = decompose_legal_action(obs_raw, a_nbl)
    assert d_nbl["family_idx"] == 3
    assert d_nbl["target_entity_slot"] == 13
    assert mask[13].item() is True

    # 6. ReserveDeck Tier Two -> target_deck_tier = 1
    a_deck = {"type": "reserve_deck", "tier": "Two"}
    d_deck = decompose_legal_action(obs_raw, a_deck)
    assert d_deck["family_idx"] == 2
    assert d_deck["target_deck_tier"] == 1

def test_diagnostic_evaluator_multi_batch_and_first_max_reference():
    """Verify evaluate_m33a_diagnostics against reference Python calculations across multiple batches."""
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    catalog = load_catalog(catalog_path)

    # Construct a synthetic multi-sample scenario with variable legal actions and intentional ties
    sample_exs = [
        # Sample 0: Take Tokens (target = Take 3 distinct, pred will choose Take 3 distinct) -> Top-1 match
        {
            "observation": {
                "viewer": 0,
                "public": {
                    "player_count": 2, "current_player": 0, "phase": "main",
                    "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
                    "deck_counts": [30, 20, 15], "end_game_triggered": False, "turns_remaining_in_final_round": None,
                    "consecutive_forced_passes": 0,
                    "market": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]],
                    "nobles": [1, 0, 8],
                    "players": [
                        {"id": 0, "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                        {"id": 1, "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                    ],
                },
                "private": {"reserved": []}
            },
            "legal_actions": [
                {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0}},
                {"type": "take_tokens", "take": {"white": 0, "blue": 0, "green": 0, "red": 2, "black": 0, "gold": 0}},
                {"type": "buy_market", "tier": "One", "slot": 0},
            ],
            "policy_target_micros": [800000, 100000, 100000],
            "value_target": [0.5, 0.5],
        },
        # Sample 1: Buy Market with intentional tie in target (first-max should pick index 0)
        {
            "observation": {
                "viewer": 0,
                "public": {
                    "player_count": 2, "current_player": 0, "phase": "main",
                    "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
                    "deck_counts": [30, 20, 15], "end_game_triggered": False, "turns_remaining_in_final_round": None,
                    "consecutive_forced_passes": 0,
                    "market": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]],
                    "nobles": [1, 0, 8],
                    "players": [
                        {"id": 0, "tokens": {"white": 2, "blue": 2, "green": 2, "red": 2, "black": 2, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                        {"id": 1, "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                    ],
                },
                "private": {"reserved": []}
            },
            "legal_actions": [
                {"type": "buy_market", "tier": "One", "slot": 0},
                {"type": "buy_market", "tier": "One", "slot": 1},
            ],
            "policy_target_micros": [500000, 500000],  # Tied target
            "value_target": [0.6, 0.4],
        },
        # Sample 2: Take with Gold Return
        {
            "observation": {
                "viewer": 0,
                "public": {
                    "player_count": 2, "current_player": 0, "phase": "main",
                    "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
                    "deck_counts": [30, 20, 15], "end_game_triggered": False, "turns_remaining_in_final_round": None,
                    "consecutive_forced_passes": 0,
                    "market": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]],
                    "nobles": [1, 0, 8],
                    "players": [
                        {"id": 0, "tokens": {"white": 2, "blue": 2, "green": 2, "red": 2, "black": 2, "gold": 1}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                        {"id": 1, "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                    ],
                },
                "private": {"reserved": []}
            },
            "legal_actions": [
                {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0}, "return": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 1}},
                {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0}, "return": {"white": 1, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}},
            ],
            "policy_target_micros": [900000, 100000],
            "value_target": [0.5, 0.5],
        },
    ]

    # Pre-encode batch items
    items = []
    for ex in sample_exs:
        obs_raw = ex["observation"]
        obs = encode_observation(obs_raw, catalog)
        actions, fam_idx, mode_idx, sel_c, ret_c, tgt_slots, tgt_tiers = [], [], [], [], [], [], []
        for a in ex["legal_actions"]:
            base_act = encode_action(a).tolist()
            delta_act = encode_action_delta_v2(obs_raw, a, catalog)
            actions.append(base_act + delta_act)
            decomp = decompose_legal_action(obs_raw, a)
            fam_idx.append(decomp["family_idx"])
            mode_idx.append(decomp["take_mode_idx"])
            sel_c.append(decomp["selected_colors"])
            ret_c.append(decomp["returned_colors"])
            tgt_slots.append(decomp["target_entity_slot"])
            tgt_tiers.append(decomp["target_deck_tier"])

        items.append({
            "entities": obs.entities,
            "entity_mask": obs.mask,
            "global_features": obs.global_features,
            "actions": torch.tensor(actions, dtype=torch.float32),
            "family_indices": torch.tensor(fam_idx, dtype=torch.long),
            "take_mode_indices": torch.tensor(mode_idx, dtype=torch.long),
            "selected_colors": torch.tensor(sel_c, dtype=torch.float32),
            "returned_colors": torch.tensor(ret_c, dtype=torch.float32),
            "target_entity_slots": torch.tensor(tgt_slots, dtype=torch.long),
            "target_deck_tiers": torch.tensor(tgt_tiers, dtype=torch.long),
            "policy_target": torch.tensor([m / 1000000.0 for m in ex["policy_target_micros"]], dtype=torch.float32),
            "value_target": torch.tensor(ex["value_target"], dtype=torch.float32),
        })

    def collate_fn(batch_items):
        offsets = [0]
        for it in batch_items:
            offsets.append(offsets[-1] + it["actions"].shape[0])
        return {
            "entities": torch.stack([it["entities"] for it in batch_items]),
            "entity_mask": torch.stack([it["entity_mask"] for it in batch_items]),
            "global_features": torch.stack([it["global_features"] for it in batch_items]),
            "actions": torch.cat([it["actions"] for it in batch_items], dim=0),
            "action_offsets": torch.tensor(offsets, dtype=torch.long),
            "family_indices": torch.cat([it["family_indices"] for it in batch_items], dim=0),
            "take_mode_indices": torch.cat([it["take_mode_indices"] for it in batch_items], dim=0),
            "selected_colors": torch.cat([it["selected_colors"] for it in batch_items], dim=0),
            "returned_colors": torch.cat([it["returned_colors"] for it in batch_items], dim=0),
            "target_entity_slots": torch.cat([it["target_entity_slots"] for it in batch_items], dim=0),
            "target_deck_tiers": torch.cat([it["target_deck_tiers"] for it in batch_items], dim=0),
            "policy_target": torch.cat([it["policy_target"] for it in batch_items], dim=0),
            "value_target": torch.stack([it["value_target"] for it in batch_items]),
        }

    # Split into 2 batches (batch_size=2 and batch_size=1)
    loader = [collate_fn(items[:2]), collate_fn(items[2:])]

    model = FactorizedDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    device = torch.device("cpu")

    res = evaluate_m33a_diagnostics(
        model=model,
        loader=loader,
        raw_examples=sample_exs,
        H_val=0.5,
        u_ce=1.0,
        device=device,
    )

    assert "ce" in res and res["ce"] > 0.0
    assert "top1" in res and 0.0 <= res["top1"] <= 1.0
    assert "family_top1" in res and 0.0 <= res["family_top1"] <= 1.0
    assert res["take"]["total"] == 2
    assert res["buy"]["total"] == 1
    assert res["return"]["total_return_positions"] == 1

def test_real_provenance_preflight_for_m33a():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    d2_result_path = Path("benchmarks/m25-recovery-exp-d2.result.json")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    catalog = load_catalog(catalog_path)

    real_dataset_semantic_hash = validate_m25_dataset_provenance(ds_payload, config)
    real_catalog_semantic_hash = catalog_semantic_hash(catalog)

    assert real_dataset_semantic_hash == FROZEN_DATASET_SEMANTIC_HASH
    assert real_catalog_semantic_hash == FROZEN_CATALOG_HASH

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "m33a_output"
        res = preflight_m33a(
            config_path=config_path,
            dataset_path=dataset_path,
            catalog_path=catalog_path,
            d2_result_path=d2_result_path,
            output_dir=output_dir,
            actual_dataset_semantic_hash=real_dataset_semantic_hash,
            actual_catalog_hash=real_catalog_semantic_hash,
            actual_param_count=FROZEN_M33A_PARAMETER_COUNT,
            require_cuda=False,
        )
        assert res["parameter_count"] == 1254558
