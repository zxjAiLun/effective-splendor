"""M31A Objective-v2: Canonical Soft-Target Cross-Entropy + Weighted Pairwise Logistic Ranking Loss."""
import torch
import torch.nn as nn
import torch.nn.functional as F

def extract_ranking_pair_info(micros: list[int]):
    """Extract top-1 and runner-up action indices and normalized margin weight from policy target micros.

    Rules:
    1. If top-1 is not unique (multiple actions share max micros), no pair is created (w=0, top1=-1, runner_up=-1).
    2. Positive is unique top-1.
    3. Negative is runner-up (highest non-top1 target micros, first-max tie breaking).
    4. Weight w = (top1_micros - runner_up_micros) / 900_000.0.
    """
    if len(micros) < 2:
        return -1, -1, 0.0

    max_val = max(micros)
    top1_indices = [i for i, v in enumerate(micros) if v == max_val]

    # Rule 1: Exclude top-1 ties
    if len(top1_indices) > 1:
        return -1, -1, 0.0

    top1_idx = top1_indices[0]

    # Rule 3: Find runner-up (highest non-top1 action, first-max)
    runner_up_val = max(v for i, v in enumerate(micros) if i != top1_idx)
    runner_up_idx = next(i for i, v in enumerate(micros) if i != top1_idx and v == runner_up_val)

    # Rule 4: Normalized advantage margin weight
    weight = (max_val - runner_up_val) / 900000.0
    return top1_idx, runner_up_idx, float(weight)

def compute_canonical_ce_and_ranking_loss(
    logits: torch.Tensor,
    policy_targets: torch.Tensor,
    action_offsets: torch.Tensor,
    ranking_pairs: torch.Tensor,  # Shape (B, 3): [top1_local_idx, runner_up_local_idx, weight]
    ranking_weight: float = 0.5,
):
    """Compute canonical soft-CE loss and batch-normalized weighted pairwise logistic ranking loss.

    Args:
        logits: Flat (total_actions,) logits tensor.
        policy_targets: Flat (total_actions,) canonical floored soft target probabilities.
        action_offsets: (B + 1,) offsets marking start/end of actions for each sample in batch.
        ranking_pairs: (B, 3) float tensor [top1_idx, runner_up_idx, weight].
        ranking_weight: Scaling factor lambda for ranking loss (default 0.5).

    Returns:
        total_loss, ce_loss, ranking_loss
    """
    num_samples = len(action_offsets) - 1
    ce_losses = []
    ranking_loss_terms = []
    weight_terms = []

    for i in range(num_samples):
        s, e = action_offsets[i].item(), action_offsets[i + 1].item()
        l = logits[s:e]
        t = policy_targets[s:e]

        # Canonical Soft Cross-Entropy
        log_p = F.log_softmax(l, dim=0)
        ce_losses.append(-(t * log_p).sum())

        # Pairwise Ranking
        top1_idx = int(ranking_pairs[i, 0].item())
        runner_up_idx = int(ranking_pairs[i, 1].item())
        w = ranking_pairs[i, 2]

        if top1_idx >= 0 and runner_up_idx >= 0 and w > 0:
            logit_diff = l[top1_idx] - l[runner_up_idx]
            pair_loss = w * F.softplus(-logit_diff)
            ranking_loss_terms.append(pair_loss)
            weight_terms.append(w)

    mean_ce = torch.stack(ce_losses).mean()

    if len(ranking_loss_terms) > 0:
        total_weight = torch.stack(weight_terms).sum()
        if total_weight > 0:
            mean_ranking = torch.stack(ranking_loss_terms).sum() / total_weight
        else:
            mean_ranking = logits.new_zeros(())
    else:
        mean_ranking = logits.new_zeros(())

    total_loss = mean_ce + ranking_weight * mean_ranking
    return total_loss, mean_ce, mean_ranking
