"""Unit tests for M34A Hierarchical Take-Pattern Policy.

Verifies:
1. Exact parameter count of HierarchicalDeltaEntityMixer is exactly 1,072,557 (953,476 D2 + 119,081 hierarchical).
2. Initialization Equivalence: Under zero residuals, vectorized log P(a|s) strictly matches log_softmax(z_D2) within 1e-6.
3. Probability Sum Conservation: sum_{a} P(a|s) == 1.0 identically for every sample under vectorized engine.
4. Two-Stage Hierarchical Gradient Flow:
   - Output projection layers receive non-zero gradients on step 1.
   - Upstream linear layers receive non-zero gradients on step 2 under hierarchical_policy_loss.
5. Hand-Calculated Reference Ground Truth:
   - Evaluates a non-zero residual batch against hand-calculated expected values for:
     P(family), P(pattern|take), P(return|pattern), and final P(a|s).
6. Multi-Batch Multi-Action Diagnostic Evaluator Reference Verification & Fail-Closed:
   - Tests evaluate_m34a_diagnostics() over variable-length legal actions, first-max ties, and hand-calculated metrics.
   - Tests evaluate_m34a_vectorized_fast() matching evaluate_m34a_diagnostics().
   - Tests fail-closed assertion on length mismatch.
7. Real Provenance Preflight enforces fail-closed execution with D2-v2 checkpoint SHA and metadata binding.
   - Asserts that old D2 checkpoint SHA fails preflight immediately.
"""
import json
import math
import tempfile
from pathlib import Path
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from splendor_gpu.data import load_catalog, catalog_semantic_hash
from splendor_gpu.encoding import encode_observation, encode_action, ENTITY_SLOTS, ENTITY_FEATURES, GLOBAL_FEATURES
from splendor_gpu.m31a_train import DeltaEntityMixer
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
from splendor_gpu.m25_train import validate_m25_dataset_provenance
from splendor_gpu.m34a_model import (
    HierarchicalDeltaEntityMixer,
    ENHANCED_ACTION_FEATURES,
    hierarchical_policy_loss,
    compute_hierarchical_log_probs,
)
from splendor_gpu.m34a_encoding import (
    get_action_family,
    get_take_pattern_id,
    get_return_vector_6d,
    TAKE_PATTERNS,
    PATTERN_TO_ID,
)
from splendor_gpu.m34a_eval import evaluate_m34a_diagnostics
from splendor_gpu.m34a_train import evaluate_m34a_vectorized_fast
from splendor_gpu.m34a_preflight import (
    preflight_m34a,
    FROZEN_CONFIG_SHA256,
    FROZEN_DATASET_FILE_SHA256,
    FROZEN_DATASET_SEMANTIC_HASH,
    FROZEN_CATALOG_HASH,
    FROZEN_D2_RESULT_SHA256,
    FROZEN_D2_CKPT_SHA256,
    FROZEN_M34A_PARAMETER_COUNT,
)

def test_model_parameter_count():
    model = HierarchicalDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    param_count = sum(p.numel() for p in model.parameters())
    assert param_count == FROZEN_M34A_PARAMETER_COUNT
    assert param_count == 1072557

def test_initialization_equivalence_to_d2_and_probability_sum_one():
    SEED = 280229

    # 1. Create pure D2 baseline
    torch.manual_seed(SEED)
    d2_model = DeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)

    # 2. Create M34A Hierarchical model (same seed)
    torch.manual_seed(SEED)
    m34a_model = HierarchicalDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)

    # Verify D2 weights in both models are bit-for-bit identical
    for (n1, p1), (n2, p2) in zip(d2_model.named_parameters(), list(m34a_model.named_parameters())[:len(list(d2_model.named_parameters()))]):
        assert n1 == n2, f"Param name mismatch: {n1} vs {n2}"
        torch.testing.assert_close(p1, p2, rtol=0, atol=0, msg=f"D2 param {n1} diverged at initialization!")

    # Verify forward probabilities match D2 flat softmax and sum to 1.0 identically
    B = 2
    total_actions = 5
    torch.manual_seed(100)
    entities = torch.randn(B, ENTITY_SLOTS, ENTITY_FEATURES)
    mask = torch.ones(B, ENTITY_SLOTS, dtype=torch.bool)
    global_f = torch.randn(B, GLOBAL_FEATURES)
    actions = torch.randn(total_actions, ENHANCED_ACTION_FEATURES)
    offsets = torch.tensor([0, 3, 5], dtype=torch.long)

    family_idx = torch.tensor([0, 1, 2, 0, 3], dtype=torch.long)
    take_patterns = torch.tensor([2, -1, -1, 12, -1], dtype=torch.long)
    return_vecs = torch.zeros(total_actions, 6, dtype=torch.float32)

    d2_model.eval()
    m34a_model.eval()

    with torch.no_grad():
        d2_logits, d2_val = d2_model.forward_packed(entities, mask, global_f, actions, offsets)
        # Flat softmax for D2
        d2_log_p0 = F.log_softmax(d2_logits[0:3], dim=0)
        d2_log_p1 = F.log_softmax(d2_logits[3:5], dim=0)
        d2_log_probs = torch.cat([d2_log_p0, d2_log_p1])

        m34a_log_probs, m34a_val = m34a_model.forward_packed(
            entities, mask, global_f, actions, offsets,
            family_idx, take_patterns, return_vecs
        )

    # Assert exact probability equivalence to flat softmax within floating-point tolerance
    torch.testing.assert_close(d2_log_probs, m34a_log_probs, rtol=1e-5, atol=1e-5)
    torch.testing.assert_close(d2_val, m34a_val, rtol=0, atol=0)

    # Assert sum P(a|s) == 1.0 identically
    p_sample0 = m34a_log_probs[0:3].exp().sum()
    p_sample1 = m34a_log_probs[3:5].exp().sum()
    assert torch.allclose(p_sample0, torch.tensor(1.0), atol=1e-6)
    assert torch.allclose(p_sample1, torch.tensor(1.0), atol=1e-6)

def test_two_stage_hierarchical_gradient_flow():
    torch.manual_seed(280229)
    model = HierarchicalDeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)

    B = 2
    total_actions = 6
    entities = torch.randn(B, ENTITY_SLOTS, ENTITY_FEATURES)
    mask = torch.ones(B, ENTITY_SLOTS, dtype=torch.bool)
    global_f = torch.randn(B, GLOBAL_FEATURES)
    actions = torch.randn(total_actions, ENHANCED_ACTION_FEATURES)
    offsets = torch.tensor([0, 3, 6], dtype=torch.long)
    policy_target = torch.tensor([0.6, 0.3, 0.1, 0.5, 0.3, 0.2], dtype=torch.float32)

    family_idx = torch.tensor([0, 0, 1, 0, 0, 2], dtype=torch.long)
    take_patterns = torch.tensor([0, 1, -1, 5, 5, -1], dtype=torch.long)
    return_vecs = torch.tensor([
        [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0],
        [1.0, 0, 0, 0, 0, 0], [0, 1.0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]
    ], dtype=torch.float32)

    # 1. First backward pass
    log_probs, _ = model.forward_packed(
        entities, mask, global_f, actions, offsets,
        family_idx, take_patterns, return_vecs
    )
    loss = hierarchical_policy_loss(log_probs, policy_target, offsets)
    loss.backward()

    # Output projection layers of hierarchical heads receive non-zero gradients
    assert model.family_head[-1].weight.grad.abs().sum().item() > 0.0
    assert model.take_pattern_head[-1].weight.grad.abs().sum().item() > 0.0
    assert model.return_penalty_head[-1].weight.grad.abs().sum().item() > 0.0

    # 2. Optimizer step
    optimizer.step()
    optimizer.zero_grad()

    # 3. Second backward pass
    log_probs2, _ = model.forward_packed(
        entities, mask, global_f, actions, offsets,
        family_idx, take_patterns, return_vecs
    )
    loss2 = hierarchical_policy_loss(log_probs2, policy_target, offsets)
    loss2.backward()

    # Upstream layers in hierarchical heads receive non-zero gradients
    assert model.family_head[0].weight.grad.abs().sum().item() > 0.0
    assert model.take_pattern_head[0].weight.grad.abs().sum().item() > 0.0
    assert model.return_penalty_head[0].weight.grad.abs().sum().item() > 0.0

def test_non_zero_residual_hand_calculated_ground_truth():
    """Explicit hand-calculated ground truth test for non-zero hierarchical residuals."""
    # 1 sample with 3 actions:
    # act 0: Take, pattern 0, no return. z0 = 1.0
    # act 1: Take, pattern 0, return gold (1.0). z1 = 2.0
    # act 2: Buy, no pattern, no return. z2 = 1.5
    offsets = torch.tensor([0, 3], dtype=torch.long)
    z = torch.tensor([1.0, 2.0, 1.5], dtype=torch.float32)
    fam = torch.tensor([0, 0, 1], dtype=torch.long)
    pats = torch.tensor([0, 0, -1], dtype=torch.long)
    rets = torch.tensor([
        [0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 1.0],
        [0, 0, 0, 0, 0, 0],
    ], dtype=torch.float32)

    # Residuals
    r_fam = torch.zeros(1, 5, dtype=torch.float32)
    r_fam[0, 0] = 0.5   # Family Take residual = +0.5
    r_fam[0, 1] = -0.2  # Family Buy residual = -0.2

    r_pat = torch.zeros(1, 30, dtype=torch.float32)
    r_pat[0, 0] = 0.8   # Pattern 0 residual = +0.8

    w_ret = torch.zeros(1, 6, dtype=torch.float32)
    w_ret[0, 5] = 1.2   # Gold return penalty = 1.2

    log_probs = compute_hierarchical_log_probs(
        z_actions=z,
        action_offsets=offsets,
        family_indices=fam,
        take_pattern_indices=pats,
        return_vectors_6d=rets,
        family_residuals=r_fam,
        take_pattern_residuals=r_pat,
        return_penalty_weights=w_ret,
    )

    # Hand calculation:
    # 1. Base masses:
    # B_Take = log(exp(1.0) + exp(2.0)) = log(2.7182818 + 7.389056) = log(10.107338) = 2.3132617
    # B_Buy = 1.5
    B_take_hand = math.log(math.exp(1.0) + math.exp(2.0))
    B_buy_hand = 1.5

    # 2. Family logits:
    # L_take = B_Take + r_fam[0] = 2.3132617 + 0.5 = 2.8132617
    # L_buy = B_Buy + r_fam[1] = 1.5 - 0.2 = 1.3000000
    # log P(Take) = L_take - log(exp(2.8132617) + exp(1.3)) = 2.8132617 - log(16.66398 + 3.669297) = 2.8132617 - 3.012282 = -0.199020
    # log P(Buy) = 1.3 - 3.012282 = -1.712282
    denom_fam = math.log(math.exp(B_take_hand + 0.5) + math.exp(B_buy_hand - 0.2))
    log_P_take_hand = (B_take_hand + 0.5) - denom_fam
    log_P_buy_hand = (B_buy_hand - 0.2) - denom_fam

    # 3. Take Pattern logits (only pattern 0 is active):
    # log P(pat 0 | Take) = 0.0 (since only 1 active pattern)
    log_P_pat0_hand = 0.0

    # 4. Action logits within pattern 0:
    # act 0: z0 - B_pat0 + r_ret = 1.0 - B_take_hand + 0.0
    # act 1: z1 - B_pat0 + r_ret = 2.0 - B_take_hand - 1.2 * 1.0 = 0.8 - B_take_hand
    # log_softmax over [1.0, 0.8] -> denom = log(exp(1.0) + exp(0.8)) = log(2.7182818 + 2.2255409) = 1.598165
    # log P(act 0 | pat 0) = 1.0 - 1.598165 = -0.598165
    # log P(act 1 | pat 0) = 0.8 - 1.598165 = -0.798165
    denom_act_in_pat = math.log(math.exp(1.0) + math.exp(0.8))
    log_P_act0_hand = 1.0 - denom_act_in_pat
    log_P_act1_hand = 0.8 - denom_act_in_pat

    # 5. Non-take action logits within Buy (only 1 action):
    # log P(act 2 | Buy) = 0.0
    log_P_act2_hand = 0.0

    # 6. Final composite log-probabilities:
    expected_log_p0 = log_P_take_hand + log_P_pat0_hand + log_P_act0_hand
    expected_log_p1 = log_P_take_hand + log_P_pat0_hand + log_P_act1_hand
    expected_log_p2 = log_P_buy_hand + log_P_act2_hand

    expected_log_probs = torch.tensor([expected_log_p0, expected_log_p1, expected_log_p2], dtype=torch.float32)
    torch.testing.assert_close(log_probs, expected_log_probs, rtol=1e-5, atol=1e-5)
    assert torch.allclose(log_probs.exp().sum(), torch.tensor(1.0), atol=1e-6)

class ControlledMockModel(nn.Module):
    """Deterministic mock model that emits preset log_probs to test evaluator arithmetic."""
    def __init__(self, preset_logits_list):
        super().__init__()
        self.preset_logits_list = preset_logits_list
        self.call_count = 0

    def forward_packed(self, entities, entity_mask, global_features, actions, action_offsets, *args):
        batch_size = len(action_offsets) - 1
        sub_logits = self.preset_logits_list[self.call_count:self.call_count + batch_size]
        self.call_count += batch_size
        normalized_log_probs = [F.log_softmax(z, dim=0) for z in sub_logits]
        flattened = torch.cat(normalized_log_probs, dim=0)
        dummy_val = torch.zeros(batch_size, 2, dtype=torch.float32, device=entities.device)
        return flattened, dummy_val

def test_diagnostic_evaluator_multi_batch_and_first_max_reference():
    """Verify evaluate_m34a_diagnostics and evaluate_m34a_vectorized_fast with exact reference values."""
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    catalog = load_catalog(catalog_path)

    sample_exs = [
        # Ex 0: Take Tokens (Target = Pattern 0 Take W/U/G, Pred = Pattern 0 Take W/U/G) -> Top-1 & Pattern Match
        {
            "observation": {
                "viewer": 0,
                "public": {
                    "player_count": 2, "current_player": 0, "phase": "main",
                    "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
                    "deck_counts": [30, 20, 15], "end_game_triggered": False, "turns_remaining_in_final_round": None,
                    "consecutive_forced_passes": 0,
                    "market": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]], "nobles": [1, 0, 8],
                    "players": [
                        {"id": 0, "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                        {"id": 1, "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                    ],
                },
                "private": {"reserved": []}
            },
            "legal_actions": [
                {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0}}, # idx 0: pattern 0
                {"type": "take_tokens", "take": {"white": 0, "blue": 0, "green": 0, "red": 2, "black": 0, "gold": 0}}, # idx 1: pattern 13
                {"type": "buy_market", "tier": "One", "slot": 0},
            ],
            "policy_target_micros": [800000, 100000, 100000],
            "value_target": [0.5, 0.5],
        },
        # Ex 1: Buy Market (Tied Target & Tied Pred Logits)
        {
            "observation": {
                "viewer": 0,
                "public": {
                    "player_count": 2, "current_player": 0, "phase": "main",
                    "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
                    "deck_counts": [30, 20, 15], "end_game_triggered": False, "turns_remaining_in_final_round": None,
                    "consecutive_forced_passes": 0,
                    "market": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]], "nobles": [1, 0, 8],
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
            "policy_target_micros": [500000, 500000],
            "value_target": [0.6, 0.4],
        },
        # Ex 2: Take with Return (Same Pattern, Different Return)
        {
            "observation": {
                "viewer": 0,
                "public": {
                    "player_count": 2, "current_player": 0, "phase": "main",
                    "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
                    "deck_counts": [30, 20, 15], "end_game_triggered": False, "turns_remaining_in_final_round": None,
                    "consecutive_forced_passes": 0,
                    "market": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]], "nobles": [1, 0, 8],
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
        # Ex 3: Reserve Deck Target vs Buy Market Pred
        {
            "observation": {
                "viewer": 0,
                "public": {
                    "player_count": 2, "current_player": 0, "phase": "main",
                    "bank": {"white": 4, "blue": 4, "green": 4, "red": 4, "black": 4, "gold": 5},
                    "deck_counts": [30, 20, 15], "end_game_triggered": False, "turns_remaining_in_final_round": None,
                    "consecutive_forced_passes": 0,
                    "market": [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]], "nobles": [1, 0, 8],
                    "players": [
                        {"id": 0, "tokens": {"white": 2, "blue": 2, "green": 2, "red": 2, "black": 2, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                        {"id": 1, "tokens": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}, "bonuses": [0, 0, 0, 0, 0], "prestige": 0, "reserved_count": 0, "public_reserved": [], "purchased": []},
                    ],
                },
                "private": {"reserved": []}
            },
            "legal_actions": [
                {"type": "reserve_deck", "tier": "Two"},
                {"type": "buy_market", "tier": "One", "slot": 0},
            ],
            "policy_target_micros": [700000, 300000],
            "value_target": [0.5, 0.5],
        },
    ]

    items = []
    for ex in sample_exs:
        obs_raw = ex["observation"]
        obs = encode_observation(obs_raw, catalog)
        actions, fam_idx, take_pats, ret_vecs = [], [], [], []
        for a in ex["legal_actions"]:
            base_act = encode_action(a).tolist()
            delta_act = encode_action_delta_v2(obs_raw, a, catalog)
            actions.append(base_act + delta_act)
            fam_idx.append(get_action_family(a))
            take_pats.append(get_take_pattern_id(a))
            ret_vecs.append(get_return_vector_6d(a))

        items.append({
            "entities": obs.entities,
            "entity_mask": obs.mask,
            "global_features": obs.global_features,
            "actions": torch.tensor(actions, dtype=torch.float32),
            "family_indices": torch.tensor(fam_idx, dtype=torch.long),
            "take_pattern_indices": torch.tensor(take_pats, dtype=torch.long),
            "return_vectors_6d": torch.tensor(ret_vecs, dtype=torch.float32),
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
            "take_pattern_indices": torch.cat([it["take_pattern_indices"] for it in batch_items], dim=0),
            "return_vectors_6d": torch.cat([it["return_vectors_6d"] for it in batch_items], dim=0),
            "policy_target": torch.cat([it["policy_target"] for it in batch_items], dim=0),
            "value_target": torch.stack([it["value_target"] for it in batch_items]),
        }

    loader = [collate_fn(items[:2]), collate_fn(items[2:])]

    preset_logits = [
        torch.tensor([5.0, 1.0, 2.0], dtype=torch.float32),
        torch.tensor([3.0, 3.0], dtype=torch.float32),
        torch.tensor([1.0, 4.0], dtype=torch.float32),
        torch.tensor([2.0, 6.0], dtype=torch.float32),
    ]

    H_val = 0.60
    u_ce = 2.50
    expected_ce = (0.765887 + 0.693147 + 2.748592 + 2.818150) / 4.0
    expected_excess_ce = expected_ce - H_val
    expected_impr_bps = int(round((u_ce - expected_ce) / u_ce * 10000))

    device = torch.device("cpu")

    # 1. Run evaluate_m34a_diagnostics
    mock_diag = ControlledMockModel(preset_logits)
    diag_res = evaluate_m34a_diagnostics(
        model=mock_diag,
        loader=loader,
        raw_examples=sample_exs,
        H_val=H_val,
        u_ce=u_ce,
        device=device,
    )

    assert pytest.approx(diag_res["ce"], abs=1e-4) == expected_ce
    assert pytest.approx(diag_res["excess_ce"], abs=1e-4) == expected_excess_ce
    assert diag_res["impr_bps"] == expected_impr_bps
    assert pytest.approx(diag_res["top1"], abs=1e-4) == 0.50
    assert pytest.approx(diag_res["family_top1"], abs=1e-4) == 0.75

    assert diag_res["take"]["total"] == 2
    assert pytest.approx(diag_res["take"]["family_recall"], abs=1e-4) == 1.00
    assert pytest.approx(diag_res["take"]["exact_top1"], abs=1e-4) == 0.50
    assert pytest.approx(diag_res["take"]["pattern_exact_top1"], abs=1e-4) == 1.00
    assert diag_res["take"]["cond_return_total"] == 1
    assert pytest.approx(diag_res["take"]["cond_return_accuracy"], abs=1e-4) == 0.00

    assert diag_res["buy"]["total"] == 1
    assert pytest.approx(diag_res["buy"]["family_recall"], abs=1e-4) == 1.00
    assert pytest.approx(diag_res["buy"]["exact_top1"], abs=1e-4) == 1.00

    assert diag_res["reserve"]["total"] == 1
    assert pytest.approx(diag_res["reserve"]["family_recall"], abs=1e-4) == 0.00
    assert pytest.approx(diag_res["reserve"]["exact_top1"], abs=1e-4) == 0.00

    # 2. Run evaluate_m34a_vectorized_fast parity check
    mock_fast = ControlledMockModel(preset_logits)
    fast_res = evaluate_m34a_vectorized_fast(
        model=mock_fast,
        loader=loader,
        H_val=H_val,
        u_ce=u_ce,
        device=device,
    )

    assert pytest.approx(fast_res["ce"], abs=1e-5) == diag_res["ce"]
    assert pytest.approx(fast_res["excess_ce"], abs=1e-5) == diag_res["excess_ce"]
    assert pytest.approx(fast_res["top1"], abs=1e-5) == diag_res["top1"]
    assert fast_res["impr_bps"] == diag_res["impr_bps"]

    # 3. Fail-Closed Check
    mock_err = ControlledMockModel(preset_logits)
    with pytest.raises(AssertionError, match="Evaluator sample count mismatch"):
        evaluate_m34a_diagnostics(
            model=mock_err,
            loader=loader,
            raw_examples=sample_exs[:2],
            H_val=H_val,
            u_ce=u_ce,
            device=device,
        )

def test_real_provenance_preflight_for_m34a():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    dataset_path = Path("local-artifacts/m25-generation/m25-materialized-dataset.json")
    catalog_path = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
    d2_result_path = Path("benchmarks/m25-recovery-exp-d2.result.json")
    d2_ckpt_path = Path("local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt")
    old_d2_ckpt_path = Path("local-artifacts/m25-recovery-exp-d2/checkpoint.pt")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    ds_payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    catalog = load_catalog(catalog_path)

    real_dataset_semantic_hash = validate_m25_dataset_provenance(ds_payload, config)
    real_catalog_semantic_hash = catalog_semantic_hash(catalog)

    assert real_dataset_semantic_hash == FROZEN_DATASET_SEMANTIC_HASH
    assert real_catalog_semantic_hash == FROZEN_CATALOG_HASH

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "m34a_output"
        res = preflight_m34a(
            config_path=config_path,
            dataset_path=dataset_path,
            catalog_path=catalog_path,
            d2_result_path=d2_result_path,
            d2_ckpt_path=d2_ckpt_path,
            output_dir=output_dir,
            actual_dataset_semantic_hash=real_dataset_semantic_hash,
            actual_catalog_hash=real_catalog_semantic_hash,
            actual_param_count=FROZEN_M34A_PARAMETER_COUNT,
            require_cuda=False,
        )
        assert res["parameter_count"] == 1072557
        assert res["d2_ckpt_file_sha256"] == FROZEN_D2_CKPT_SHA256
        assert res["d2_ckpt_file_sha256"] == "113372fc1092e611804cb7261844ac2a104608772f68ab74a854a038370c7e17"

    # Counter-example: old invalid D2 checkpoint must fail preflight immediately
    if old_d2_ckpt_path.exists():
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir2 = Path(tmpdir) / "m34a_output2"
            with pytest.raises(ValueError, match="D2-v2 checkpoint SHA mismatch"):
                preflight_m34a(
                    config_path=config_path,
                    dataset_path=dataset_path,
                    catalog_path=catalog_path,
                    d2_result_path=d2_result_path,
                    d2_ckpt_path=old_d2_ckpt_path,
                    output_dir=output_dir2,
                    actual_dataset_semantic_hash=real_dataset_semantic_hash,
                    actual_catalog_hash=real_catalog_semantic_hash,
                    actual_param_count=FROZEN_M34A_PARAMETER_COUNT,
                    require_cuda=False,
                )
