"""M17 non-Transformer Policy-Value architectures."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import nn

from .encoding import ACTION_FEATURES, ENTITY_FEATURES, ENTITY_SLOTS, GLOBAL_FEATURES


@dataclass(frozen=True)
class ModelSpec:
    architecture: str
    hidden_dim: int
    blocks: int
    dropout: float = 0.0

    def validate(self) -> None:
        if self.architecture not in {"flat_resmlp", "entity_mixer"}:
            raise ValueError(f"unsupported architecture {self.architecture!r}")
        if not 32 <= self.hidden_dim <= 1024:
            raise ValueError("hidden_dim must be in 32..=1024")
        if not 1 <= self.blocks <= 16:
            raise ValueError("blocks must be in 1..=16")
        if not 0.0 <= self.dropout < 0.5:
            raise ValueError("dropout must be in [0, 0.5)")


class ResidualBlock(nn.Module):
    def __init__(self, width: int, dropout: float):
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.body = nn.Sequential(
            nn.Linear(width, width * 2), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(width * 2, width), nn.Dropout(dropout),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return value + self.body(self.norm(value))


class PolicyValueBase(nn.Module):
    def __init__(self, spec: ModelSpec):
        super().__init__()
        spec.validate()
        self.spec = spec
        h = spec.hidden_dim
        self.action_encoder = nn.Sequential(nn.Linear(ACTION_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.policy = nn.Sequential(nn.Linear(h * 3, h), nn.GELU(), nn.Linear(h, 1))
        self.value = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 2), nn.Sigmoid())

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor) -> torch.Tensor:
        raise NotImplementedError

    def forward(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor, actions: torch.Tensor, action_mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        expanded = state.unsqueeze(1).expand(-1, actions.shape[1], -1)
        logits = self.policy(torch.cat([expanded, action, expanded * action], dim=-1)).squeeze(-1)
        logits = logits.masked_fill(~action_mask, torch.finfo(logits.dtype).min)
        return logits, self.value(state)

    def checkpoint_metadata(self) -> dict[str, object]:
        return {"architecture": asdict(self.spec), "entity_slots": ENTITY_SLOTS, "entity_features": ENTITY_FEATURES, "global_features": GLOBAL_FEATURES, "action_features": ACTION_FEATURES, "max_players": 2, "value_order": "viewer_relative"}


class FlatResMLPPolicyValue(PolicyValueBase):
    def __init__(self, spec: ModelSpec):
        super().__init__(spec)
        h = spec.hidden_dim
        self.input = nn.Linear(ENTITY_SLOTS * ENTITY_FEATURES + ENTITY_SLOTS + GLOBAL_FEATURES, h)
        self.blocks = nn.Sequential(*(ResidualBlock(h, spec.dropout) for _ in range(spec.blocks)))
        self.norm = nn.LayerNorm(h)

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor) -> torch.Tensor:
        flat = torch.cat([entities.flatten(1), mask.float(), global_features], dim=-1)
        return self.norm(self.blocks(self.input(flat)))


class EntityMixerPolicyValue(PolicyValueBase):
    def __init__(self, spec: ModelSpec):
        super().__init__(spec)
        h = spec.hidden_dim
        self.entity_encoder = nn.Sequential(nn.Linear(ENTITY_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.entity_gate = nn.Linear(h, 1)
        self.global_encoder = nn.Sequential(nn.Linear(GLOBAL_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.mix = nn.Linear(h * 2, h)
        self.blocks = nn.Sequential(*(ResidualBlock(h, spec.dropout) for _ in range(spec.blocks)))
        self.norm = nn.LayerNorm(h)

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor) -> torch.Tensor:
        encoded = self.entity_encoder(entities)
        gate = self.entity_gate(encoded).squeeze(-1).masked_fill(~mask, torch.finfo(encoded.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        return self.norm(self.blocks(state))


def build_model(spec: ModelSpec) -> PolicyValueBase:
    spec.validate()
    if spec.architecture == "flat_resmlp":
        return FlatResMLPPolicyValue(spec)
    return EntityMixerPolicyValue(spec)
