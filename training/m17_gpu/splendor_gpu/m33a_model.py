"""M33A Factorized Legal-Action Policy Model.

Preserves exact D2 backbone and D2 policy scorer while adding a structured factor branch.
All final output projections in the structured branch are strictly ZERO-INITIALIZED, ensuring
M33A initial logits == D2 initial logits bit-for-bit.

Structured Factor Scorers:
1. Intent Head (Family): Linear(h, 5) -> [take, buy, reserve, choose_noble, pass]
2. Take Mode Head: Linear(h, 4) -> [1-distinct, 2-distinct, 3-distinct, 2-same]
3. Color Desirability Head: Linear(h, 5) -> [d_white, d_blue, d_green, d_red, d_black]
4. Return Keep Penalty Head: Linear(h, 6) -> [k_white, k_blue, k_green, k_red, k_black, k_gold]
5. Target Entity Conditioned Scorer:
   - Evaluates all 31 entity slots conditioned on state: [state, entity, state * entity] (dim h * 3) -> Linear -> Linear -> (dim 3):
     * channel 0: card_buy_value (used for market / private reserved buy)
     * channel 1: card_reserve_value (used for market card reserve)
     * channel 2: noble_value (used for choose_noble)
6. Reserve Deck Tier Scorer: Linear(h, 3) -> [tier_1, tier_2, tier_3]
"""
import torch
import torch.nn as nn
from splendor_gpu.encoding import ENTITY_SLOTS, ENTITY_FEATURES, GLOBAL_FEATURES
from splendor_gpu.model import ResidualBlock

ENHANCED_ACTION_FEATURES = 36 + 23  # 59

class FactorizedDeltaEntityMixer(nn.Module):
    """Canonical D2 Architecture with zero-initialized Factorized Action-Decomposition branch."""
    def __init__(self, hidden_dim: int = 192, blocks: int = 4, dropout: float = 0.0):
        super().__init__()
        h = hidden_dim

        # -------------------------------------------------------------
        # 1. Exact D2 Backbone & Policy/Value Scorer (Identical construction order)
        # -------------------------------------------------------------
        self.entity_encoder = nn.Sequential(nn.Linear(ENTITY_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.entity_gate = nn.Linear(h, 1)
        self.global_encoder = nn.Sequential(nn.Linear(GLOBAL_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.mix = nn.Linear(h * 2, h)
        self.blocks = nn.Sequential(*(ResidualBlock(h, dropout) for _ in range(blocks)))
        self.norm = nn.LayerNorm(h)

        self.action_encoder = nn.Sequential(nn.Linear(ENHANCED_ACTION_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.policy = nn.Sequential(nn.Linear(h * 3, h), nn.GELU(), nn.Linear(h, 1))
        self.value = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 2), nn.Sigmoid())

        # -------------------------------------------------------------
        # 2. Structured Factor Branch (Created AFTER D2 to preserve RNG state)
        # -------------------------------------------------------------
        # Family & Mode Intent Heads
        self.intent_head = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 5))
        self.take_mode_head = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 4))

        # Color & Return Heads
        self.color_desirability_head = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 5))
        self.keep_penalty_head = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 6))

        # State-Conditioned Entity Scorer: [state, entity, state * entity] -> 3 channels (buy, reserve, noble)
        self.entity_conditioned_scorer = nn.Sequential(
            nn.Linear(h * 3, h),
            nn.GELU(),
            nn.Linear(h, 3),
        )

        # Deck Tier Scorer (for reserve_deck)
        self.deck_tier_head = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 3))

        # -------------------------------------------------------------
        # 3. ZERO-INITIALIZE all structured output projection layers
        # -------------------------------------------------------------
        nn.init.zeros_(self.intent_head[-1].weight)
        nn.init.zeros_(self.intent_head[-1].bias)

        nn.init.zeros_(self.take_mode_head[-1].weight)
        nn.init.zeros_(self.take_mode_head[-1].bias)

        nn.init.zeros_(self.color_desirability_head[-1].weight)
        nn.init.zeros_(self.color_desirability_head[-1].bias)

        nn.init.zeros_(self.keep_penalty_head[-1].weight)
        nn.init.zeros_(self.keep_penalty_head[-1].bias)

        nn.init.zeros_(self.entity_conditioned_scorer[-1].weight)
        nn.init.zeros_(self.entity_conditioned_scorer[-1].bias)

        nn.init.zeros_(self.deck_tier_head[-1].weight)
        nn.init.zeros_(self.deck_tier_head[-1].bias)

    def state_embedding_and_entities(self, entities, mask, global_features):
        """Returns normalized state embedding and encoded entity representations."""
        encoded_entities = self.entity_encoder(entities)
        gate = self.entity_gate(encoded_entities).squeeze(-1).masked_fill(~mask, torch.finfo(encoded_entities.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded_entities * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        norm_state = self.norm(self.blocks(state))
        return norm_state, encoded_entities

    def compute_structured_factors(self, state, encoded_entities, entity_mask):
        """Computes all semantic factor tensors for a batch of states."""
        # state: (B, h), encoded_entities: (B, 31, h), entity_mask: (B, 31)
        B, num_entities, h = encoded_entities.shape

        # 1. Intents & Modes
        family_scores = self.intent_head(state)        # (B, 5)
        take_mode_scores = self.take_mode_head(state)  # (B, 4)

        # 2. Colors & Returns
        color_d = self.color_desirability_head(state)  # (B, 5)
        keep_p = self.keep_penalty_head(state)         # (B, 6)

        # 3. State-Conditioned Entity Scores: [state_expanded, entities, state_expanded * entities]
        state_expanded = state.unsqueeze(1).expand(-1, num_entities, -1)
        entity_inter = torch.cat([state_expanded, encoded_entities, state_expanded * encoded_entities], dim=-1)
        entity_scores = self.entity_conditioned_scorer(entity_inter)  # (B, 31, 3)

        # Mask invalid entity slots to zero
        entity_scores = entity_scores * entity_mask.unsqueeze(-1).to(entity_scores.dtype)

        # 4. Deck Tier Scores
        deck_tier_scores = self.deck_tier_head(state)  # (B, 3)

        return {
            "family_scores": family_scores,
            "take_mode_scores": take_mode_scores,
            "color_d": color_d,
            "keep_p": keep_p,
            "entity_scores": entity_scores,
            "deck_tier_scores": deck_tier_scores,
        }

    def forward_packed(
        self,
        entities,
        mask,
        global_features,
        actions,
        action_offsets,
        family_indices,
        take_mode_indices,
        selected_colors,
        returned_colors,
        target_entity_slots,
        target_deck_tiers,
    ):
        """Packed forward pass computing exact D2 residual + structured factor sum."""
        state, encoded_entities = self.state_embedding_and_entities(entities, mask, global_features)

        # 1. D2 Action Scorer Path
        action_emb = self.action_encoder(actions)
        counts = action_offsets[1:] - action_offsets[:-1]
        state_expanded = torch.repeat_interleave(state, counts, dim=0)
        d2_logits = self.policy(torch.cat([state_expanded, action_emb, state_expanded * action_emb], dim=-1)).squeeze(-1)

        # 2. Structured Factor Computation
        factors = self.compute_structured_factors(state, encoded_entities, mask)
        
        batch_size = state.shape[0]
        segment_ids = torch.repeat_interleave(torch.arange(batch_size, device=state.device), counts)

        # A. Family intent score
        # family_indices: (total_actions,), range 0..4
        family_score_table = factors["family_scores"]  # (B, 5)
        fam_scores = family_score_table[segment_ids, family_indices]

        # B. Take mode score (0..3, or -1 if not take)
        take_mode_table = factors["take_mode_scores"]  # (B, 4)
        is_take_mode = (take_mode_indices >= 0)
        safe_mode_idx = torch.clamp(take_mode_indices, min=0)
        mode_scores = torch.where(
            is_take_mode,
            take_mode_table[segment_ids, safe_mode_idx],
            torch.zeros_like(fam_scores),
        )

        # C. Color desirability score (selected_colors: (total_actions, 5))
        color_d_table = factors["color_d"]  # (B, 5)
        action_color_d = color_d_table[segment_ids]  # (total_actions, 5)
        color_scores = (selected_colors * action_color_d).sum(dim=-1)

        # D. Return penalty score (returned_colors: (total_actions, 6))
        keep_p_table = factors["keep_p"]  # (B, 6)
        action_keep_p = keep_p_table[segment_ids]  # (total_actions, 6)
        return_scores = -(returned_colors * action_keep_p).sum(dim=-1)

        # E. Target Entity score (buy / reserve / noble)
        # target_entity_slots: (total_actions,), range 0..30 or -1
        # family_indices: 1 (buy) -> channel 0, 2 (reserve) -> channel 1, 3 (noble) -> channel 2
        entity_score_table = factors["entity_scores"]  # (B, 31, 3)
        is_entity_target = (target_entity_slots >= 0)
        safe_slot_idx = torch.clamp(target_entity_slots, min=0)

        # Select entity channel based on family
        channel_idx = torch.where(
            family_indices == 1,
            torch.zeros_like(family_indices),
            torch.where(
                family_indices == 2,
                torch.ones_like(family_indices),
                torch.full_like(family_indices, 2),
            ),
        )

        target_entity_scores = torch.where(
            is_entity_target,
            entity_score_table[segment_ids, safe_slot_idx, channel_idx],
            torch.zeros_like(fam_scores),
        )

        # F. Deck Tier score (for reserve_deck)
        deck_tier_table = factors["deck_tier_scores"]  # (B, 3)
        is_deck_tier = (target_deck_tiers >= 0)
        safe_tier_idx = torch.clamp(target_deck_tiers, min=0)
        deck_tier_scores = torch.where(
            is_deck_tier,
            deck_tier_table[segment_ids, safe_tier_idx],
            torch.zeros_like(fam_scores),
        )

        # Total Structured Score
        structured_score = (
            fam_scores
            + mode_scores
            + color_scores
            + return_scores
            + target_entity_scores
            + deck_tier_scores
        )

        final_logits = d2_logits + structured_score
        return final_logits, self.value(state)
