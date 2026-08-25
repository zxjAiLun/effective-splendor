"""M31A Objective-v2: Canonical Soft-Target Cross-Entropy + Vectorized Weighted Pairwise Logistic Ranking Loss."""
import torch
import torch.nn as nn
import torch.nn.functional as F
from splendor_gpu.self_play_train import packed_policy_loss

def extract_ranking_pair_info(micros: list[int]) -> tuple[int, int, float]:
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

def compute_vectorized_ranking_loss(
    logits: torch.Tensor,
    global_top1_idx: torch.Tensor,
    global_runner_up_idx: torch.Tensor,
    ranking_weights: torch.Tensor,
) -> torch.Tensor:
    """Vectorized, exact GPU pairwise logistic ranking loss across global indices with zero CPU-GPU sync."""
    top1_logits = logits[global_top1_idx]
    runner_up_logits = logits[global_runner_up_idx]
    diff = top1_logits - runner_up_logits
    pair_losses = F.softplus(-diff) * ranking_weights
    total_weight = ranking_weights.sum()
    return torch.where(
        total_weight > 0,
        pair_losses.sum() / total_weight.clamp(min=1e-8),
        logits.new_zeros(()),
    )

def compute_m31a_loss(
    logits: torch.Tensor,
    targets: torch.Tensor,
    offsets: torch.Tensor,
    global_top1_idx: torch.Tensor,
    global_runner_up_idx: torch.Tensor,
    ranking_weights: torch.Tensor,
    ranking_lambda: float = 0.5,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Fully vectorized on-GPU M31A composite loss with zero CPU-GPU synchronization.

    Args:
        logits: Flat (total_actions,) logits tensor on device.
        targets: Flat (total_actions,) canonical floored soft target probabilities on device.
        offsets: (B + 1,) action offsets on device.
        global_top1_idx: (B,) global indices for positive top-1 actions on device.
        global_runner_up_idx: (B,) global indices for negative runner-up actions on device.
        ranking_weights: (B,) margin weights on device.
        ranking_lambda: Composite loss scaling factor (default 0.5).

    Returns:
        total_loss, ce_loss, ranking_loss
    """
    ce_loss = packed_policy_loss(logits, targets, offsets)
    if ranking_lambda > 0:
        ranking_loss = compute_vectorized_ranking_loss(
            logits, global_top1_idx, global_runner_up_idx, ranking_weights
        )
    else:
        ranking_loss = logits.new_zeros(())
    total_loss = ce_loss + ranking_lambda * ranking_loss
    return total_loss, ce_loss, ranking_loss
