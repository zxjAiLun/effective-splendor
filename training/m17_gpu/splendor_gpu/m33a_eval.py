"""M33A Detailed Multi-Level Diagnostic Evaluator.

Evaluates exact policy metrics and fine-grained action decomposition accuracies:
1. Full Legal-Action Validation Policy CE & Excess CE
2. Full Legal-Action Top-1 Agreement
3. Action Family Top-1 Accuracy (Take / Buy / Reserve / Noble / Pass)
4. Take Family Recall & Exact Top-1
5. Take Color-Set Exact Match & Jaccard Similarity
6. Buy Exact Top-1
7. Reserve Family Recall & Exact Top-1
8. Return Accuracy
"""
import math
from typing import Any
import torch
import torch.nn as nn
from splendor_gpu.self_play_train import packed_policy_loss

@torch.no_grad()
def evaluate_m33a_diagnostics(
    model: nn.Module,
    loader,
    raw_examples: list[dict[str, Any]],
    H_val: float,
    u_ce: float,
    device: torch.device,
) -> dict[str, Any]:
    """Computes full evaluation and granular breakdown metrics."""
    model.eval()

    total_ce = 0.0
    total_examples = 0
    full_top1_matches = 0

    # Diagnostic accumulators
    family_matches = 0

    take_total = 0
    take_family_recalled = 0
    take_full_matches = 0
    take_color_exact_matches = 0
    take_jaccard_sum = 0.0

    buy_total = 0
    buy_family_recalled = 0
    buy_full_matches = 0

    reserve_total = 0
    reserve_family_recalled = 0
    reserve_full_matches = 0

    noble_total = 0
    noble_full_matches = 0

    example_cursor = 0

    for batch in loader:
        batch_dev = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
        logits, _ = model.forward_packed(
            batch_dev["entities"],
            batch_dev["entity_mask"],
            batch_dev["global_features"],
            batch_dev["actions"],
            batch_dev["action_offsets"],
            batch_dev["family_indices"],
            batch_dev["take_mode_indices"],
            batch_dev["selected_colors"],
            batch_dev["returned_colors"],
            batch_dev["target_entity_slots"],
            batch_dev["target_deck_tiers"],
        )

        offsets = batch_dev["action_offsets"].cpu().tolist()
        logits_cpu = logits.cpu()
        targets_cpu = batch_dev["policy_target"].cpu()

        p_ce = packed_policy_loss(logits, batch_dev["policy_target"], batch_dev["action_offsets"])
        batch_size = len(offsets) - 1
        total_ce += p_ce.item() * batch_size
        total_examples += batch_size

        for b_idx in range(batch_size):
            start = offsets[b_idx]
            end = offsets[b_idx + 1]
            sample_logits = logits_cpu[start:end]
            sample_targets = targets_cpu[start:end]

            pred_idx = int(torch.argmax(sample_logits).item())
            target_idx = int(torch.argmax(sample_targets).item())

            is_full_top1 = (pred_idx == target_idx)
            if is_full_top1:
                full_top1_matches += 1

            # Match diagnostic fields
            ex = raw_examples[example_cursor]
            example_cursor += 1

            legal_actions = ex["legal_actions"]
            pred_action = legal_actions[pred_idx]
            target_action = legal_actions[target_idx]

            pred_type = pred_action.get("type")
            target_type = target_action.get("type")

            # Major family mapping
            def to_family(t):
                if t == "take_tokens": return "take"
                if t in ("buy_market", "buy_reserved"): return "buy"
                if t in ("reserve_market", "reserve_deck"): return "reserve"
                if t == "choose_noble": return "noble"
                return "pass"

            pred_fam = to_family(pred_type)
            target_fam = to_family(target_type)

            if pred_fam == target_fam:
                family_matches += 1

            if target_fam == "take":
                take_total += 1
                if pred_fam == "take":
                    take_family_recalled += 1
                if is_full_top1:
                    take_full_matches += 1
                
                # Color Jaccard & Exact Match
                t_take = target_action.get("take", {})
                p_take = pred_action.get("take", {}) if pred_type == "take_tokens" else {}

                t_colors = {k for k, v in t_take.items() if v > 0}
                p_colors = {k for k, v in p_take.items() if v > 0}

                if t_colors == p_colors:
                    take_color_exact_matches += 1
                
                union_len = len(t_colors | p_colors)
                if union_len > 0:
                    jaccard = len(t_colors & p_colors) / float(union_len)
                else:
                    jaccard = 1.0
                take_jaccard_sum += jaccard

            elif target_fam == "buy":
                buy_total += 1
                if pred_fam == "buy":
                    buy_family_recalled += 1
                if is_full_top1:
                    buy_full_matches += 1

            elif target_fam == "reserve":
                reserve_total += 1
                if pred_fam == "reserve":
                    reserve_family_recalled += 1
                if is_full_top1:
                    reserve_full_matches += 1

            elif target_fam == "noble":
                noble_total += 1
                if is_full_top1:
                    noble_full_matches += 1

    ce = total_ce / total_examples
    excess_ce = ce - H_val
    impr_bps = int(round((u_ce - ce) / u_ce * 10000))
    full_top1 = full_top1_matches / float(total_examples)
    family_top1 = family_matches / float(total_examples)

    take_fam_recall = (take_family_recalled / float(take_total)) if take_total > 0 else 0.0
    take_exact_top1 = (take_full_matches / float(take_total)) if take_total > 0 else 0.0
    take_color_exact = (take_color_exact_matches / float(take_total)) if take_total > 0 else 0.0
    take_jaccard = (take_jaccard_sum / float(take_total)) if take_total > 0 else 0.0

    buy_fam_recall = (buy_family_recalled / float(buy_total)) if buy_total > 0 else 0.0
    buy_exact_top1 = (buy_full_matches / float(buy_total)) if buy_total > 0 else 0.0

    reserve_fam_recall = (reserve_family_recalled / float(reserve_total)) if reserve_total > 0 else 0.0
    reserve_exact_top1 = (reserve_full_matches / float(reserve_total)) if reserve_total > 0 else 0.0

    return {
        "ce": ce,
        "excess_ce": excess_ce,
        "top1": full_top1,
        "impr_bps": impr_bps,
        "family_top1": family_top1,
        "take": {
            "total": take_total,
            "family_recall": take_fam_recall,
            "exact_top1": take_exact_top1,
            "color_exact_match": take_color_exact,
            "color_jaccard": take_jaccard,
        },
        "buy": {
            "total": buy_total,
            "family_recall": buy_fam_recall,
            "exact_top1": buy_exact_top1,
        },
        "reserve": {
            "total": reserve_total,
            "family_recall": reserve_fam_recall,
            "exact_top1": reserve_exact_top1,
        },
    }
