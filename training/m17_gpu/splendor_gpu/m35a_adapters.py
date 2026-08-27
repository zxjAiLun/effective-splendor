"""Model Adapters for M35A Direct Policy Retrospective Arena."""

from __future__ import annotations

from typing import Any
import torch
import torch.nn as nn

from splendor_gpu.data import load_catalog
from splendor_gpu.encoding import encode_action, encode_observation
from splendor_gpu.m25_delta_v2 import encode_action_delta_v2
from splendor_gpu.m33a_encoding import decompose_legal_action
from splendor_gpu.m34a_encoding import (
    get_action_family,
    get_take_pattern_id,
    get_return_vector_6d,
)
from splendor_gpu.m35a_belief import LiveBeliefTracker
from splendor_gpu.m35a_registry import ModelRegistryEntry


@torch.no_grad()
def score_model_actions(
    model: nn.Module,
    entry: ModelRegistryEntry,
    observation: dict[str, Any],
    legal_actions: list[dict[str, Any]],
    belief_tracker: LiveBeliefTracker,
    catalog: dict[str, Any],
    device: torch.device,
) -> torch.Tensor:
    """Scores legal actions using the exact architecture and feature pipeline specified by entry.

    Returns a 1D float Tensor of length len(legal_actions) representing action scores
    (logits or normalized log-probs).
    """
    model.eval()
    num_legal = len(legal_actions)
    if num_legal == 0:
        raise ValueError("Cannot score empty legal actions")

    # 1. Observation encoding
    encoded_obs = encode_observation(observation, catalog)
    entities = encoded_obs.entities.unsqueeze(0).to(device)  # (1, 31, 32)
    mask = encoded_obs.mask.unsqueeze(0).to(device)          # (1, 31)

    # 2. Global features preparation (40 dims vs 252 dims for M32A)
    if entry.global_feature_dim == 252:
        belief_features = belief_tracker.project_features(observation, catalog)
        belief_tensor = torch.tensor(belief_features, dtype=torch.float32)
        global_features = torch.cat([encoded_obs.global_features, belief_tensor], dim=-1).unsqueeze(0).to(device)
    else:
        global_features = encoded_obs.global_features.unsqueeze(0).to(device)

    # 3. Action feature encoding (36 dims vs 59 dims)
    if entry.action_feature_dim == 36:
        # Base 36-dim encoding (M24-S2, M28A, M28B)
        actions_tensor = torch.stack([encode_action(a) for a in legal_actions]).to(device)
    elif entry.action_feature_dim == 59:
        # 59-dim delta encoding (M25-D2-v2, M29A-v2, M31A, M32A, M33A, M34A)
        actions_list = []
        for a in legal_actions:
            base_act = encode_action(a).tolist()
            delta_act = encode_action_delta_v2(observation, a, catalog)
            actions_list.append(base_act + delta_act)
        actions_tensor = torch.tensor(actions_list, dtype=torch.float32, device=device)
    else:
        raise ValueError(f"Unsupported action feature dimension: {entry.action_feature_dim}")

    # 4. Model Forward & Output Semantics Dispatch
    if entry.output_semantics == "hierarchical_log_probs":
        # M34A Hierarchical model
        family_indices = [get_action_family(a) for a in legal_actions]
        take_pattern_indices = [get_take_pattern_id(a) for a in legal_actions]
        return_vectors_6d = [get_return_vector_6d(a) for a in legal_actions]

        fam_t = torch.tensor(family_indices, dtype=torch.long, device=device)
        pat_t = torch.tensor(take_pattern_indices, dtype=torch.long, device=device)
        ret_t = torch.tensor(return_vectors_6d, dtype=torch.float32, device=device)
        offsets = torch.tensor([0, num_legal], dtype=torch.long, device=device)

        log_probs, _ = model.forward_packed(
            entities=entities,
            entity_mask=mask,
            global_features=global_features,
            actions=actions_tensor,
            action_offsets=offsets,
            family_indices=fam_t,
            take_pattern_indices=pat_t,
            return_vectors_6d=ret_t,
        )
        return log_probs

    elif entry.output_semantics == "composite_residual_logits":
        # M33A Factorized model
        family_indices = []
        take_mode_indices = []
        selected_colors = []
        returned_colors = []
        target_entity_slots = []
        target_deck_tiers = []

        for a in legal_actions:
            decomp = decompose_legal_action(observation, a)
            family_indices.append(decomp["family_idx"])
            take_mode_indices.append(decomp["take_mode_idx"])
            selected_colors.append(decomp["selected_colors"])
            returned_colors.append(decomp["returned_colors"])
            target_entity_slots.append(decomp["target_entity_slot"])
            target_deck_tiers.append(decomp["target_deck_tier"])

        fam_t = torch.tensor(family_indices, dtype=torch.long, device=device)
        mode_t = torch.tensor(take_mode_indices, dtype=torch.long, device=device)
        sel_t = torch.tensor(selected_colors, dtype=torch.float32, device=device)
        ret_t = torch.tensor(returned_colors, dtype=torch.float32, device=device)
        ent_t = torch.tensor(target_entity_slots, dtype=torch.long, device=device)
        tier_t = torch.tensor(target_deck_tiers, dtype=torch.long, device=device)
        offsets = torch.tensor([0, num_legal], dtype=torch.long, device=device)

        logits, _ = model.forward_packed(
            entities=entities,
            mask=mask,
            global_features=global_features,
            actions=actions_tensor,
            action_offsets=offsets,
            family_indices=fam_t,
            take_mode_indices=mode_t,
            selected_colors=sel_t,
            returned_colors=ret_t,
            target_entity_slots=ent_t,
            target_deck_tiers=tier_t,
        )
        return logits

    elif entry.output_semantics == "flat_logits":
        # Standard models: M24-S2, M25-D2-v2, M28A, M28B, M29A-v2, M31A, M32A
        if hasattr(model, "forward_packed"):
            offsets = torch.tensor([0, num_legal], dtype=torch.long, device=device)
            logits, _ = model.forward_packed(
                entities=entities,
                mask=mask,
                global_features=global_features,
                actions=actions_tensor,
                action_offsets=offsets,
            )
            return logits
        else:
            # PolicyValueBase (M24-S2, M28A, M28B)
            action_mask = torch.ones((1, num_legal), dtype=torch.bool, device=device)
            logits, _ = model(
                entities=entities,
                mask=mask,
                global_features=global_features,
                actions=actions_tensor.unsqueeze(0),
                action_mask=action_mask,
            )
            return logits[0]
    else:
        raise ValueError(f"Unknown output semantics: {entry.output_semantics}")
