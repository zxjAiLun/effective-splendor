"""M34A Hierarchical Take-Pattern Policy Model Architecture.

Implements exact hierarchical conditional probability decomposition:
P(a|s) = P(family|s) * P(take_pattern|take, s) * P(return|pattern, s) [for Take actions]
P(a|s) = P(family|s) * P(a|family, s)                                [for Buy, Reserve, Noble, Pass]

Formulation:
1. Baseline D2 policy scorer computes unnormalized action potentials z(a).
2. Base masses at each level are computed via LogSumExp over active subsets:
   - B_f = logsumexp_{a in family f} z(a)
   - B_p = logsumexp_{a in pattern p} z(a)  (for Take actions)
3. Structured residuals are added at each level:
   - Family logits: B_f + family_head(s)[f]
   - Take pattern logits: (B_p - B_0) + take_pattern_head(s)[p]
   - Return / action logits: (z(a) - B_p) - sum_{k=0..5} return_gems[k] * return_penalty_head(s)[k]
   - Non-take action logits within family: z(a) - B_f
4. Normalized conditional log-probabilities are composed:
   - For Take: log P(a|s) = log P(take|s) + log P(pattern|take, s) + log P(a|pattern, s)
   - For Non-take: log P(a|s) = log P(family|s) + log P(a|family, s)

Zero-Residual Invariant:
- When all hierarchical heads are zero-initialized, log P(a|s) strictly equals log_softmax(z(a))
  up to floating-point precision, ensuring bit-for-bit equivalence with D2.
- sum_{a} P(a|s) == 1.0 identically for every sample.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from splendor_gpu.encoding import (
    ENTITY_SLOTS,
    ENTITY_FEATURES,
    GLOBAL_FEATURES,
)
from splendor_gpu.model import ResidualBlock

ENHANCED_ACTION_FEATURES = 36 + 23  # 59

def compute_hierarchical_log_probs(
    z_actions: torch.Tensor,
    action_offsets: torch.Tensor,
    family_indices: torch.Tensor,
    take_pattern_indices: torch.Tensor,
    return_vectors_6d: torch.Tensor,
    family_residuals: torch.Tensor,
    take_pattern_residuals: torch.Tensor,
    return_penalty_weights: torch.Tensor,
) -> torch.Tensor:
    """
    Computes exact normalized hierarchical log-probabilities log P(a|s).
    """
    batch_size = len(action_offsets) - 1
    log_probs = torch.empty_like(z_actions)

    for b in range(batch_size):
        start = action_offsets[b].item()
        end = action_offsets[b + 1].item()
        z_b = z_actions[start:end]
        fam_b = family_indices[start:end]
        pat_b = take_pattern_indices[start:end]
        ret_vec_b = return_vectors_6d[start:end]

        r_fam_b = family_residuals[b]       # (5,)
        r_pat_b = take_pattern_residuals[b] # (30,)
        w_ret_b = return_penalty_weights[b] # (6,)

        # 1. Group by active families in this sample
        unique_fams = torch.unique(fam_b)
        B_f = {}
        r_f = {}
        for f in unique_fams:
            f_item = f.item()
            mask_f = (fam_b == f)
            B_f[f_item] = torch.logsumexp(z_b[mask_f], dim=0)
            r_f[f_item] = r_fam_b[f_item]

        # Normalized log P(family | s)
        logits_fam = torch.stack([B_f[f.item()] + r_f[f.item()] for f in unique_fams])
        log_P_fam_all = F.log_softmax(logits_fam, dim=0)
        log_P_f = {f.item(): log_P_fam_all[i] for i, f in enumerate(unique_fams)}

        # 2. For each active family:
        for f in unique_fams:
            f_item = f.item()
            mask_f = (fam_b == f)
            indices_f = torch.where(mask_f)[0]

            if f_item == 0:  # Take family
                pats_in_take = pat_b[mask_f]
                unique_pats = torch.unique(pats_in_take)
                B_p = {}
                r_p = {}
                for p in unique_pats:
                    p_item = p.item()
                    mask_p = (pat_b == p) & mask_f
                    B_p[p_item] = torch.logsumexp(z_b[mask_p], dim=0)
                    r_p[p_item] = r_pat_b[p_item]

                # Normalized log P(pattern | take, s)
                logits_pat = torch.stack([B_p[p.item()] - B_f[0] + r_p[p.item()] for p in unique_pats])
                log_P_pat_all = F.log_softmax(logits_pat, dim=0)
                log_P_p = {p.item(): log_P_pat_all[i] for i, p in enumerate(unique_pats)}

                # Normalized log P(action | pattern, s)
                for p in unique_pats:
                    p_item = p.item()
                    mask_p = (pat_b == p) & mask_f
                    indices_p = torch.where(mask_p)[0]
                    z_p = z_b[indices_p]
                    ret_vec_p = ret_vec_b[indices_p]
                    r_ret_p = - (ret_vec_p * w_ret_b.unsqueeze(0)).sum(dim=-1)
                    logits_act_p = z_p - B_p[p_item] + r_ret_p
                    log_P_act_p = F.log_softmax(logits_act_p, dim=0)

                    for local_idx, global_local_idx in enumerate(indices_p):
                        log_probs[start + global_local_idx] = log_P_f[0] + log_P_p[p_item] + log_P_act_p[local_idx]
            else:
                # Non-take family (Buy, Reserve, Noble, Pass)
                z_non_take = z_b[indices_f]
                log_P_act_f = F.log_softmax(z_non_take, dim=0)
                for local_idx, global_local_idx in enumerate(indices_f):
                    log_probs[start + global_local_idx] = log_P_f[f_item] + log_P_act_f[local_idx]

    return log_probs

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

        # Baseline D2 unnormalized action potentials z(a)
        act_enc = self.action_encoder(actions)
        inter = torch.cat([state_rep, act_enc, state_rep * act_enc], dim=-1)
        z_actions = self.policy(inter).squeeze(-1)

        # Hierarchical residuals from state
        fam_res = self.family_head(state)           # (B, 5)
        pat_res = self.take_pattern_head(state)     # (B, 30)
        ret_weights = self.return_penalty_head(state)  # (B, 6)

        # Compute exact normalized hierarchical log-probabilities
        log_probs = compute_hierarchical_log_probs(
            z_actions=z_actions,
            action_offsets=action_offsets,
            family_indices=family_indices,
            take_pattern_indices=take_pattern_indices,
            return_vectors_6d=return_vectors_6d,
            family_residuals=fam_res,
            take_pattern_residuals=pat_res,
            return_penalty_weights=ret_weights,
        )

        return log_probs, val

def hierarchical_policy_loss(
    log_probs: torch.Tensor,
    targets: torch.Tensor,
    action_offsets: torch.Tensor,
) -> torch.Tensor:
    """
    Computes exact Cross-Entropy Loss: -sum_{a} q(a) * log P(a|s) averaged over batch.
    """
    batch_size = len(action_offsets) - 1
    sample_losses = []
    for b in range(batch_size):
        start = action_offsets[b].item()
        end = action_offsets[b + 1].item()
        lp = log_probs[start:end]
        q = targets[start:end]
        sample_losses.append(-torch.sum(q * lp))
    return torch.stack(sample_losses).mean()
