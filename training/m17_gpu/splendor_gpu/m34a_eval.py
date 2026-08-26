"""M34A Detailed Evaluation and Diagnostic Suite for Hierarchical Policy.

Computes exact Cross-Entropy, Excess CE, Improvement BPS, Top-1 accuracy,
and family/pattern breakdown matching D2 evaluation protocol.
Uses hierarchical_policy_loss for unified metrics.
"""
from typing import Any
import torch
import torch.nn as nn
from splendor_gpu.m34a_encoding import get_take_pattern_id
from splendor_gpu.m34a_model import hierarchical_policy_loss

@torch.no_grad()
def evaluate_m34a_diagnostics(
    model: nn.Module,
    loader,
    raw_examples: list[dict[str, Any]],
    H_val: float,
    u_ce: float,
    device: torch.device,
) -> dict[str, Any]:
    """
    Evaluates policy metrics, including hierarchical breakdown.
    Ensures fail-closed alignment with raw_examples order.
    """
    model.eval()
    total_examples = 0
    total_ce = 0.0
    total_top1_matches = 0
    total_family_matches = 0

    # Family-specific metrics
    take_total = 0
    take_fam_recalled = 0
    take_exact_matches = 0
    take_pattern_exact_matches = 0
    take_cond_return_total = 0
    take_cond_return_matches = 0

    buy_total = 0
    buy_fam_recalled = 0
    buy_exact_matches = 0

    reserve_total = 0
    reserve_fam_recalled = 0
    reserve_exact_matches = 0

    example_cursor = 0

    for batch in loader:
        batch_dev = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
        log_probs, _ = model.forward_packed(
            batch_dev["entities"],
            batch_dev["entity_mask"],
            batch_dev["global_features"],
            batch_dev["actions"],
            batch_dev["action_offsets"],
            batch_dev["family_indices"],
            batch_dev["take_pattern_indices"],
            batch_dev["return_vectors_6d"],
        )

        n = int(batch_dev["entities"].shape[0])
        p_loss = hierarchical_policy_loss(log_probs, batch_dev["policy_target"], batch_dev["action_offsets"])
        total_examples += n
        total_ce += p_loss.item() * n

        offsets = batch_dev["action_offsets"].cpu().tolist()
        log_probs_cpu = log_probs.cpu()
        targets_cpu = batch_dev["policy_target"].cpu()

        batch_size = len(offsets) - 1
        for i in range(batch_size):
            start = offsets[i]
            end = offsets[i + 1]
            s_log = log_probs_cpu[start:end]
            s_tar = targets_cpu[start:end]

            # Fail-closed assertion on index cursor
            if example_cursor >= len(raw_examples):
                raise AssertionError(f"Evaluator sample count mismatch: raw_examples has {len(raw_examples)}, cursor reached {example_cursor}")

            raw_ex = raw_examples[example_cursor]
            example_cursor += 1

            # Exact first-max tie resolution
            pred_max = s_log.max()
            pred_idx = int(torch.where(s_log == pred_max)[0][0].item())

            target_max = s_tar.max()
            target_idx = int(torch.where(s_tar == target_max)[0][0].item())

            if pred_idx == target_idx:
                total_top1_matches += 1

            pred_action = raw_ex["legal_actions"][pred_idx]
            target_action = raw_ex["legal_actions"][target_idx]

            pred_type = pred_action.get("type")
            target_type = target_action.get("type")

            # Family match
            is_family_match = (
                (target_type == "take_tokens" and pred_type == "take_tokens")
                or (target_type in ("buy_market", "buy_reserved") and pred_type in ("buy_market", "buy_reserved"))
                or (target_type in ("reserve_market", "reserve_deck") and pred_type in ("reserve_market", "reserve_deck"))
                or (target_type == "choose_noble" and pred_type == "choose_noble")
                or (target_type == "pass" and pred_type == "pass")
            )
            if is_family_match:
                total_family_matches += 1

            # Breakdown: Take Tokens
            if target_type == "take_tokens":
                take_total += 1
                if pred_type == "take_tokens":
                    take_fam_recalled += 1
                if pred_idx == target_idx:
                    take_exact_matches += 1

                t_pat = get_take_pattern_id(target_action)
                p_pat = get_take_pattern_id(pred_action) if pred_type == "take_tokens" else -1

                if t_pat >= 0 and t_pat == p_pat:
                    take_pattern_exact_matches += 1
                    t_ret = target_action.get("return", {})
                    if any(v > 0 for v in t_ret.values()):
                        take_cond_return_total += 1
                        if t_ret == pred_action.get("return", {}):
                            take_cond_return_matches += 1

            # Breakdown: Buy Actions
            elif target_type in ("buy_market", "buy_reserved"):
                buy_total += 1
                if pred_type in ("buy_market", "buy_reserved"):
                    buy_fam_recalled += 1
                if pred_idx == target_idx:
                    buy_exact_matches += 1

            # Breakdown: Reserve Actions
            elif target_type in ("reserve_market", "reserve_deck"):
                reserve_total += 1
                if pred_type in ("reserve_market", "reserve_deck"):
                    reserve_fam_recalled += 1
                if pred_idx == target_idx:
                    reserve_exact_matches += 1

    if example_cursor != len(raw_examples):
        raise AssertionError(f"Evaluator sample count mismatch: raw_examples has {len(raw_examples)}, but processed {example_cursor}")

    ce = total_ce / total_examples
    top1 = total_top1_matches / float(total_examples)
    excess_ce = ce - H_val
    impr_bps = int(round((u_ce - ce) / u_ce * 10000))

    return {
        "ce": ce,
        "excess_ce": excess_ce,
        "top1": top1,
        "impr_bps": impr_bps,
        "family_top1": total_family_matches / float(total_examples),
        "take": {
            "total": take_total,
            "family_recall": take_fam_recalled / float(take_total) if take_total > 0 else 0.0,
            "exact_top1": take_exact_matches / float(take_total) if take_total > 0 else 0.0,
            "pattern_exact_top1": take_pattern_exact_matches / float(take_total) if take_total > 0 else 0.0,
            "cond_return_total": take_cond_return_total,
            "cond_return_accuracy": take_cond_return_matches / float(take_cond_return_total) if take_cond_return_total > 0 else 0.0,
        },
        "buy": {
            "total": buy_total,
            "family_recall": buy_fam_recalled / float(buy_total) if buy_total > 0 else 0.0,
            "exact_top1": buy_exact_matches / float(buy_total) if buy_total > 0 else 0.0,
        },
        "reserve": {
            "total": reserve_total,
            "family_recall": reserve_fam_recalled / float(reserve_total) if reserve_total > 0 else 0.0,
            "exact_top1": reserve_exact_matches / float(reserve_total) if reserve_total > 0 else 0.0,
        },
    }
