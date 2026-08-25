"""Vectorized evaluation on GPU for M31A with zero per-sample CPU-GPU synchronization."""
import torch
import torch.nn as nn
from splendor_gpu.m31a_loss import compute_m31a_loss

@torch.no_grad()
def evaluate_split_vectorized(model: nn.Module, loader, H_val: float, u_ce: float, device: torch.device):
    """Vectorized, exact segmented evaluation accumulating scalar metrics strictly on GPU."""
    model.eval()
    total_ce = torch.zeros((), dtype=torch.float64, device=device)
    total_composite = torch.zeros((), dtype=torch.float64, device=device)
    total_top1 = torch.zeros((), dtype=torch.float64, device=device)
    total_examples = 0

    for batch in loader:
        batch_dev = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
        logits, _ = model.forward_packed(
            batch_dev["entities"],
            batch_dev["entity_mask"],
            batch_dev["global_features"],
            batch_dev["actions"],
            batch_dev["action_offsets"],
        )
        tot_loss, p_ce, _ = compute_m31a_loss(
            logits,
            batch_dev["policy_target"],
            batch_dev["action_offsets"],
            batch_dev["global_top1_idx"],
            batch_dev["global_runner_up_idx"],
            batch_dev["ranking_weights"],
            ranking_lambda=0.5,
        )
        offsets = batch_dev["action_offsets"]
        counts = offsets[1:] - offsets[:-1]
        batch_size = counts.shape[0]
        total_actions = logits.shape[0]
        segment_ids = torch.repeat_interleave(torch.arange(batch_size, device=device), counts)

        # Accumulate CE and composite loss weighted by batch_size
        total_ce += p_ce.to(torch.float64) * batch_size
        total_composite += tot_loss.to(torch.float64) * batch_size

        # Segmented First-Max Argmax Top-1 on GPU
        # 1. Model predicted first-max action
        max_logits = torch.full((batch_size,), -torch.inf, dtype=logits.dtype, device=device)
        max_logits.scatter_reduce_(0, segment_ids, logits, reduce="amax")
        action_indices = torch.arange(total_actions, dtype=torch.int64, device=device)
        is_max_logit = (logits == max_logits[segment_ids])
        logit_cand = torch.where(is_max_logit, action_indices, torch.full_like(action_indices, total_actions + 1))
        first_max_logit_idx = torch.full((batch_size,), total_actions + 1, dtype=torch.int64, device=device)
        first_max_logit_idx.scatter_reduce_(0, segment_ids, logit_cand, reduce="amin")

        # 2. Teacher target first-max action
        targets = batch_dev["policy_target"]
        max_targets = torch.full((batch_size,), -torch.inf, dtype=targets.dtype, device=device)
        max_targets.scatter_reduce_(0, segment_ids, targets, reduce="amax")
        is_max_target = (targets == max_targets[segment_ids])
        target_cand = torch.where(is_max_target, action_indices, torch.full_like(action_indices, total_actions + 1))
        first_max_target_idx = torch.full((batch_size,), total_actions + 1, dtype=torch.int64, device=device)
        first_max_target_idx.scatter_reduce_(0, segment_ids, target_cand, reduce="amin")

        matches = (first_max_logit_idx == first_max_target_idx)
        total_top1 += matches.sum(dtype=torch.float64)
        total_examples += batch_size

    # Single host-device synchronization at the end of the entire evaluation loop
    ce = total_ce.item() / total_examples
    composite_loss = total_composite.item() / total_examples
    top1 = total_top1.item() / total_examples
    excess_ce = ce - H_val
    impr_bps = int(round((u_ce - ce) / u_ce * 10000))

    return {
        "ce": ce,
        "composite_loss": composite_loss,
        "excess_ce": excess_ce,
        "top1": top1,
        "impr_bps": impr_bps,
    }
