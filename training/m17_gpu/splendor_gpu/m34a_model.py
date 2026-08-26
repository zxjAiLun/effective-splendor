"""M34A Hierarchical Take-Pattern Policy Model Architecture.

Implements exact hierarchical conditional probability decomposition:
P(a|s) = P(family|s) * P(take_pattern|take, s) * P(return|pattern, s) [for Take actions]
P(a|s) = P(family|s) * P(a|family, s)                                [for Buy, Reserve, Noble, Pass]

Formulation:
1. Baseline D2 policy scorer computes unnormalized action potentials z(a).
2. Base masses at each level are computed via vectorized grouped logsumexp:
   - B_f = logsumexp_{a in family f} z(a)
   - B_p = logsumexp_{a in pattern p} z(a)  (for Take actions)
3. Structured residuals are added at each level:
   - Family logits: B_f + family_head(s)[f]
   - Take pattern logits: (B_p - B_take) + take_pattern_head(s)[p]
   - Return / action logits: (z(a) - B_p) - sum_{k=0..5} return_gems[k] * return_penalty_head(s)[k]
   - Non-take action logits within family: z(a) - B_f
4. Normalized conditional log-probabilities are composed:
   - For Take: log P(a|s) = log P(take|s) + log P(pattern|take, s) + log P(a|pattern, s)
   - For Non-take: log P(a|s) = log P(family|s) + log P(a|family, s)

Invariants:
- Fully vectorized via CUDA/CPU scatter operations (zero CPU sync / .item() in forward path).
- When all hierarchical heads are zero-initialized, log P(a|s) strictly equals log_softmax(z(a)).
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

def grouped_logsumexp(
    z: torch.Tensor,
    group_id: torch.Tensor,
    num_groups: int,
    mask: torch.Tensor = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Computes logsumexp for each group in 0..num_groups-1 fully vectorized on CUDA/CPU.
    Returns:
      group_lse: Tensor of shape (num_groups,)
      active_mask: Tensor of shape (num_groups,) bool indicating which groups have >=1 element
    """
    device = z.device
    dtype = z.dtype

    if mask is not None:
        z_valid = z[mask]
        group_valid = group_id[mask]
    else:
        z_valid = z
        group_valid = group_id

    active_mask = torch.zeros(num_groups, dtype=torch.bool, device=device)
    if group_valid.numel() > 0:
        active_mask.scatter_(0, group_valid, True)

    group_max = torch.full((num_groups,), -float("inf"), dtype=dtype, device=device)
    if group_valid.numel() > 0:
        group_max.scatter_reduce_(0, group_valid, z_valid, reduce="amax", include_self=False)

    group_sum_exp = torch.zeros(num_groups, dtype=dtype, device=device)
    if group_valid.numel() > 0:
        group_max_per_item = group_max[group_valid]
        exp_shifted = torch.exp(z_valid - group_max_per_item)
        group_sum_exp.scatter_add_(0, group_valid, exp_shifted)

    group_lse = torch.full((num_groups,), -float("inf"), dtype=dtype, device=device)
    group_lse[active_mask] = group_max[active_mask] + torch.log(group_sum_exp[active_mask])

    return group_lse, active_mask

def compute_hierarchical_log_probs(
    z_actions: torch.Tensor,
    action_offsets: torch.Tensor,
    family_indices: torch.Tensor,
    take_pattern_indices: torch.Tensor,
    return_vectors_6d: torch.Tensor,
    family_residuals: torch.Tensor,        # (B, 5)
    take_pattern_residuals: torch.Tensor,  # (B, 30)
    return_penalty_weights: torch.Tensor,  # (B, 6)
) -> torch.Tensor:
    """
    Computes exact normalized hierarchical log-probabilities log P(a|s) fully vectorized.
    """
    B = len(action_offsets) - 1
    device = z_actions.device
    total_actions = z_actions.shape[0]

    # Sample ID per action
    counts = action_offsets[1:] - action_offsets[:-1]
    sample_id = torch.repeat_interleave(torch.arange(B, device=device), counts)

    # Group IDs
    fam_group_id = sample_id * 5 + family_indices
    take_mask = (family_indices == 0)
    pat_group_id = torch.zeros(total_actions, dtype=torch.long, device=device)
    pat_group_id[take_mask] = sample_id[take_mask] * 30 + take_pattern_indices[take_mask]

    # 1. Base mass per family group: B_f = logsumexp_{a in family}(z(a))
    B_f, active_fam = grouped_logsumexp(z_actions, fam_group_id, num_groups=B * 5)

    # Family residual flat: (B * 5)
    r_fam_flat = family_residuals.view(-1)
    fam_logits = B_f + r_fam_flat  # (B * 5)

    # Normalize family logits per sample: log P(family | s)
    fam_sample_id = torch.repeat_interleave(torch.arange(B, device=device), 5)
    sample_fam_lse, _ = grouped_logsumexp(fam_logits, fam_sample_id, num_groups=B, mask=active_fam)
    log_P_fam_group = fam_logits - sample_fam_lse[fam_sample_id]
    log_P_fam_per_action = log_P_fam_group[fam_group_id]

    # 2. Take Pattern conditional probability: log P(pattern | take, s)
    # Base mass per take pattern: B_p = logsumexp_{a in pattern}(z(a))
    B_p, active_pat = grouped_logsumexp(z_actions, pat_group_id, num_groups=B * 30, mask=take_mask)
    # Take family base mass per sample: B_take = B_f[sample_id * 5 + 0]
    B_take_sample = B_f[torch.arange(B, device=device) * 5 + 0]  # (B,)
    pat_sample_id = torch.repeat_interleave(torch.arange(B, device=device), 30)
    B_take_per_pat = B_take_sample[pat_sample_id]

    r_pat_flat = take_pattern_residuals.view(-1)
    pat_logits = (B_p - B_take_per_pat) + r_pat_flat

    # Normalize pattern logits per sample across active patterns within Take
    sample_pat_lse, _ = grouped_logsumexp(pat_logits, pat_sample_id, num_groups=B, mask=active_pat)
    log_P_pat_group = pat_logits - sample_pat_lse[pat_sample_id]
    log_P_pat_per_action = torch.zeros(total_actions, dtype=z_actions.dtype, device=device)
    log_P_pat_per_action[take_mask] = log_P_pat_group[pat_group_id[take_mask]]

    # 3. Action conditional probability:
    # For Take actions: log P(action | pattern, s) = z(a) - B_p - return_penalty - logsumexp_within_pattern
    w_ret_per_action = return_penalty_weights[sample_id]  # (N, 6)
    r_ret = - (return_vectors_6d * w_ret_per_action).sum(dim=-1)  # (N,)
    act_in_pat_logits = z_actions - B_p[pat_group_id] + r_ret

    # Logsumexp over actions in same pattern group
    pat_act_lse, _ = grouped_logsumexp(act_in_pat_logits, pat_group_id, num_groups=B * 30, mask=take_mask)
    log_P_act_in_pat = act_in_pat_logits - pat_act_lse[pat_group_id]

    # For Non-Take actions: log P(action | family, s) = z(a) - B_f
    log_P_act_in_fam = z_actions - B_f[fam_group_id]

    # 4. Total Log-Probability log P(a|s)
    log_probs = torch.empty_like(z_actions)
    log_probs[take_mask] = log_P_fam_per_action[take_mask] + log_P_pat_per_action[take_mask] + log_P_act_in_pat[take_mask]
    non_take_mask = ~take_mask
    log_probs[non_take_mask] = log_P_fam_per_action[non_take_mask] + log_P_act_in_fam[non_take_mask]

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

        # Compute exact normalized hierarchical log-probabilities (fully vectorized)
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
    Fully vectorized across the entire packed batch.
    """
    batch_size = len(action_offsets) - 1
    return -(targets * log_probs).sum() / float(batch_size)
