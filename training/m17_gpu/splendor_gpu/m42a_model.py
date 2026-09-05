"""M42A model architecture: Visible Action-Entity Relation Residual Probe.

Frozen Baseline B (D2-v2 + M41A QHead) + relation-conditioned entity residual head.
Zero-initialized residual projection guarantees bit-exact equality B == X == R at init.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

from .m31a_train import DeltaEntityMixer
from .m41a_train import M41AArm, M41AQHead

RELATION_INIT_SEED = 42_261_001
RELATION_DIM = 28
PAIR_INPUT_DIM = 640  # 192 (entity) + 192 (action) + 192 (entity * action) + 64 (rel_emb)
RESIDUAL_HEAD_INPUT_DIM = 576  # 192 (context) + 192 (action) + 192 (context * action)


class M42ARelationResidual(nn.Module):
    """The trainable relation residual modules for M42A."""

    def __init__(self) -> None:
        super().__init__()
        self.relation_encoder = nn.Sequential(
            nn.Linear(RELATION_DIM, 64),
            nn.GELU(),
            nn.Linear(64, 64),
        )
        self.pair_encoder = nn.Sequential(
            nn.Linear(PAIR_INPUT_DIM, 192),
            nn.GELU(),
            nn.Linear(192, 192),
        )
        self.entity_gate = nn.Linear(192, 1)
        self.residual_head = nn.Sequential(
            nn.Linear(RESIDUAL_HEAD_INPUT_DIM, 192),
            nn.GELU(),
            nn.Linear(192, 1),
        )
        # Frozen contract: residual head's final projection is zero-initialized
        final_layer = self.residual_head[-1]
        nn.init.zeros_(final_layer.weight)
        nn.init.zeros_(final_layer.bias)

    def forward(
        self,
        encoded_entities: torch.Tensor,
        mask: torch.Tensor,
        action_emb: torch.Tensor,
        counts: torch.Tensor,
        relations: torch.Tensor,
    ) -> torch.Tensor:
        """Compute the scalar residual score for each action.
        
        Args:
            encoded_entities: (B_states, 31, 192)
            mask: (B_states, 31)
            action_emb: (N_actions, 192)
            counts: (B_states,) number of actions per state
            relations: (N_actions, 31, 28)
            
        Returns:
            f_residual: (N_actions,)
        """
        # Expand entities and mask to match actions
        exp_entities = torch.repeat_interleave(encoded_entities, counts, dim=0)  # (N, 31, 192)
        exp_mask = torch.repeat_interleave(mask, counts, dim=0)  # (N, 31)

        # 1. Relation embedding
        rel_emb = self.relation_encoder(relations)  # (N, 31, 64)

        # 2. Pair representation
        exp_a = action_emb.unsqueeze(1).expand(-1, 31, -1)  # (N, 31, 192)
        pair_input = torch.cat([exp_entities, exp_a, exp_entities * exp_a, rel_emb], dim=-1)  # (N, 31, 640)
        pair_h = self.pair_encoder(pair_input)  # (N, 31, 192)

        # 3. Action-conditioned entity gating
        gate_logits = self.entity_gate(pair_h).squeeze(-1).masked_fill(
            ~exp_mask, torch.finfo(pair_h.dtype).min
        )
        gate_weights = torch.softmax(gate_logits, dim=-1).unsqueeze(-1)  # (N, 31, 1)
        context = (pair_h * gate_weights).sum(dim=1)  # (N, 192)

        # 4. Residual head
        z_res = torch.cat([context, action_emb, context * action_emb], dim=-1)  # (N, 576)
        return self.residual_head(z_res).squeeze(-1)  # (N,)


class M42AModel(nn.Module):
    """Full M42A Model: frozen base arm B + trainable relation residual."""

    def __init__(
        self,
        base_arm: M41AArm,
        residual: M42ARelationResidual,
        *,
        arm_type: str = "R",
    ) -> None:
        super().__init__()
        if arm_type not in ("X", "R"):
            raise ValueError(f"arm_type must be 'X' or 'R', got {arm_type!r}")
        self.arm_type = arm_type
        self.base_arm = base_arm
        self.residual = residual

        # Strict contract: freeze ALL base arm parameters
        for p in self.base_arm.parameters():
            p.requires_grad_(False)
        for p in self.residual.parameters():
            p.requires_grad_(True)

    def forward(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
        actions: torch.Tensor,
        offsets: torch.Tensor,
        relations: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Compute full Q values.

        Returns (q_total, q_base, q_residual).
        """
        counts = offsets[1:] - offsets[:-1]

        # 1. Base forward pass (with intermediate encoded entities)
        encoded_entities = self.base_arm.entity_encoder(entities)  # (B, 31, 192)
        gate = self.base_arm.entity_gate(encoded_entities).squeeze(-1).masked_fill(
            ~mask, torch.finfo(encoded_entities.dtype).min
        )
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded_entities * weights).sum(dim=1)
        state = self.base_arm.mix(torch.cat([pooled, self.base_arm.global_encoder(global_features)], dim=-1))
        s_emb = self.base_arm.norm(self.base_arm.blocks(state))  # (B, 192)

        action_emb = self.base_arm.action_encoder(actions)  # (N, 192)
        exp_s = torch.repeat_interleave(s_emb, counts, dim=0)  # (N, 192)
        z_base = torch.cat([exp_s, action_emb, exp_s * action_emb], dim=-1)  # (N, 576)
        q_base = self.base_arm.q_head(z_base)  # (N,)

        # 2. Residual forward pass
        rel_in = relations
        if self.arm_type == "X":
            rel_in = torch.zeros_like(relations)

        q_res = self.residual(encoded_entities, mask, action_emb, counts, rel_in)
        q_total = q_base + q_res
        return q_total, q_base, q_res

    def q_values(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
        actions: torch.Tensor,
        offsets: torch.Tensor,
        relations: torch.Tensor,
    ) -> torch.Tensor:
        q_total, _, _ = self.forward(entities, mask, global_features, actions, offsets, relations)
        return q_total


def create_m42a_paired_arms(
    base_arm: M41AArm,
) -> tuple[M42AModel, M42AModel]:
    """Create paired arms X and R from a SINGLE frozen initialization draw."""
    torch.manual_seed(RELATION_INIT_SEED)
    residual_R = M42ARelationResidual()
    residual_X = copy.deepcopy(residual_R)

    # Base arm is frozen and shared (or deepcopied)
    arm_X = M42AModel(copy.deepcopy(base_arm), residual_X, arm_type="X")
    arm_R = M42AModel(copy.deepcopy(base_arm), residual_R, arm_type="R")
    return arm_X, arm_R
