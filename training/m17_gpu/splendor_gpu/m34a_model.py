"""M34A Hierarchical Take-Pattern Policy Model Architecture.

Implements exact hierarchical probability decomposition:
P(a|s) = P(family|s) * P(take_pattern|take, s) * P(return|pattern, s) [for Take actions]
P(a|s) = P(family|s) * P(a|family, s)                                [for Buy, Reserve, Noble, Pass]

Logit computation:
1. Family Logits: L_family(s) in R^5 from state embedding.
2. Take Pattern Logits: L_pattern(s) in R^30 from state embedding.
3. Return Logits: L_return(s, a) = - sum_{k=0..5} returned_gems[k] * w_return[k](s)
4. Non-Take Action Logits: L_non_take(s, a) from D2 Action Scorer MLP(s, a).

Zero-Initialization Guarantee:
- Structured hierarchical heads are zero-initialized after D2 backbone construction,
  ensuring perfect initial bit-for-bit equivalence with D2.
"""
import torch
import torch.nn as nn
from splendor_gpu.encoding import (
    ENTITY_SLOTS,
    ENTITY_FEATURES,
    GLOBAL_FEATURES,
)
from splendor_gpu.model import ResidualBlock

ENHANCED_ACTION_FEATURES = 36 + 23  # 59

class HierarchicalDeltaEntityMixer(nn.Module):
    def __init__(self, hidden_dim: int = 192, blocks: int = 4, dropout: float = 0.0):
        super().__init__()
        h = hidden_dim
        self.hidden_dim = h

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
        # 2. M34A Hierarchical Heads (Constructed AFTER D2 to protect RNG)
        # -------------------------------------------------------------
        # Family Head: 5 classes (Take, Buy, Reserve, Noble, Pass)
        self.family_head = nn.Sequential(
            nn.Linear(h, h),
            nn.GELU(),
            nn.Linear(h, 5),
        )

        # Take Pattern Head: 30 classes (all valid 3-distinct, 2-same, 2-distinct, 1-distinct)
        self.take_pattern_head = nn.Sequential(
            nn.Linear(h, h),
            nn.GELU(),
            nn.Linear(h, 30),
        )

        # Return Penalty Head: 6 dims (white, blue, green, red, black, gold)
        self.return_penalty_head = nn.Sequential(
            nn.Linear(h, h),
            nn.GELU(),
            nn.Linear(h, 6),
        )

        # Zero-initialize output layers of hierarchical heads
        nn.init.zeros_(self.family_head[-1].weight)
        nn.init.zeros_(self.family_head[-1].bias)
        nn.init.zeros_(self.take_pattern_head[-1].weight)
        nn.init.zeros_(self.take_pattern_head[-1].bias)
        nn.init.zeros_(self.return_penalty_head[-1].weight)
        nn.init.zeros_(self.return_penalty_head[-1].bias)

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor):
        encoded = self.entity_encoder(entities)
        gate = self.entity_gate(encoded).squeeze(-1).masked_fill(~mask, torch.finfo(encoded.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        return self.norm(self.blocks(state))

    def forward_packed(
        self,
        entities: torch.Tensor,
        entity_mask: torch.Tensor,
        global_features: torch.Tensor,
        actions: torch.Tensor,
        action_offsets: torch.Tensor,
        family_indices: torch.Tensor,
        take_pattern_indices: torch.Tensor,
        return_vectors_6d: torch.Tensor,
    ):
        state = self.state_embedding(entities, entity_mask, global_features)
        val = self.value(state)

        counts = action_offsets[1:] - action_offsets[:-1]
        state_rep = torch.repeat_interleave(state, counts, dim=0)

        # 1. Baseline D2 action features and logits
        act_enc = self.action_encoder(actions)
        inter = torch.cat([state_rep, act_enc, state_rep * act_enc], dim=-1)
        d2_logits = self.policy(inter).squeeze(-1)

        # 2. Hierarchical component logits
        fam_logits = self.family_head(state)           # (B, 5)
        pat_logits = self.take_pattern_head(state)     # (B, 30)
        ret_weights = self.return_penalty_head(state)  # (B, 6)

        fam_logits_rep = torch.repeat_interleave(fam_logits, counts, dim=0)     # (total_actions, 5)
        pat_logits_rep = torch.repeat_interleave(pat_logits, counts, dim=0)     # (total_actions, 30)
        ret_weights_rep = torch.repeat_interleave(ret_weights, counts, dim=0)   # (total_actions, 6)

        # 3. Assemble Hierarchical Log-Probabilities per sample
        is_take = (family_indices == 0)
        take_pat_clamped = take_pattern_indices.clamp(min=0)
        pat_scores = pat_logits_rep.gather(dim=1, index=take_pat_clamped.unsqueeze(1)).squeeze(1)
        ret_penalties = (return_vectors_6d * ret_weights_rep).sum(dim=1)

        # Gather family score
        fam_scores = fam_logits_rep.gather(dim=1, index=family_indices.unsqueeze(1)).squeeze(1)

        hierarchical_take_scores = pat_scores - ret_penalties
        final_logits = d2_logits + fam_scores + torch.where(is_take, hierarchical_take_scores, torch.zeros_like(d2_logits))

        return final_logits, val
