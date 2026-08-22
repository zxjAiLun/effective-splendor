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
    interaction_blocks: int = 0

    def validate(self) -> None:
        if self.architecture not in {"flat_resmlp", "entity_mixer", "contextual_entity_mixer"}:
            raise ValueError(f"unsupported architecture {self.architecture!r}")
        if not 32 <= self.hidden_dim <= 1024:
            raise ValueError("hidden_dim must be in 32..=1024")
        if not 1 <= self.blocks <= 16:
            raise ValueError("blocks must be in 1..=16")
        if not 0.0 <= self.dropout < 0.5:
            raise ValueError("dropout must be in [0, 0.5)")
        if self.architecture == "contextual_entity_mixer":
            if not 1 <= self.interaction_blocks <= 8:
                raise ValueError("contextual interaction_blocks must be in 1..=8")
        elif self.interaction_blocks != 0:
            raise ValueError("interaction_blocks must be zero for non-contextual architectures")


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

    def forward_packed(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
        actions: torch.Tensor,
        action_offsets: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        counts = action_offsets[1:] - action_offsets[:-1]
        expanded = torch.repeat_interleave(state, counts, dim=0)
        logits = self.policy(torch.cat([expanded, action, expanded * action], dim=-1)).squeeze(-1)
        return logits, self.value(state)

    def checkpoint_metadata(self) -> dict[str, object]:
        architecture = asdict(self.spec)
        if self.spec.architecture != "contextual_entity_mixer":
            # Preserve the historical metadata shape for old entity_mixer and
            # flat_resmlp checkpoints while accepting the new optional field.
            architecture.pop("interaction_blocks", None)
        return {"architecture": architecture, "entity_slots": ENTITY_SLOTS, "entity_features": ENTITY_FEATURES, "global_features": GLOBAL_FEATURES, "action_features": ACTION_FEATURES, "max_players": 2, "value_order": "viewer_relative"}


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


class ContextualInteractionBlock(nn.Module):
    """Lightweight masked pairwise interaction, deliberately not attention."""

    def __init__(self, width: int, dropout: float):
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.query = nn.Linear(width, width)
        self.key = nn.Linear(width, width)
        self.value = nn.Linear(width, width)
        self.pair = nn.Sequential(
            nn.Linear(width * 3, width),
            nn.GELU(),
            nn.Linear(width, 1),
        )
        self.residual = nn.Sequential(
            nn.Linear(width * 3, width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width, width),
            nn.Dropout(dropout),
        )
        self.register_buffer(
            "not_self_mask",
            ~torch.eye(ENTITY_SLOTS, dtype=torch.bool).unsqueeze(0),
            persistent=False,
        )

    def forward(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_context: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        normalized = self.norm(entities)
        queries = self.query(normalized)
        keys = self.key(normalized)
        values = self.value(normalized)

        # Factored pair scorer: W_q*q_i + W_k*k_j + W_p*(q_i*k_j) + b
        # mathematically identical to self.pair[0]([q_i, k_j, q_i * k_j])
        w = self.pair[0].weight
        b = self.pair[0].bias
        h = entities.shape[-1]
        proj_q = nn.functional.linear(queries, w[:, 0:h])
        proj_k = nn.functional.linear(keys, w[:, h : 2 * h])
        proj_p = nn.functional.linear(queries.unsqueeze(2) * keys.unsqueeze(1), w[:, 2 * h : 3 * h], b)
        h_pair = proj_q.unsqueeze(2) + proj_k.unsqueeze(1) + proj_p
        interaction = torch.sigmoid(self.pair[2](self.pair[1](h_pair)).squeeze(-1))

        entity_count = entities.shape[1]
        if entity_count == self.not_self_mask.shape[1]:
            not_self = self.not_self_mask
        else:
            not_self = ~torch.eye(entity_count, dtype=torch.bool, device=entities.device).unsqueeze(0)

        pair_mask = mask.unsqueeze(1) & mask.unsqueeze(2) & not_self
        interaction = interaction.masked_fill(~pair_mask, 0.0)
        denominator = interaction.sum(dim=-1, keepdim=True).clamp_min(1e-6)

        # BMM aggregation avoids 4D (B, N, N, H) tensor allocation
        context = torch.bmm(interaction, values) / denominator
        context = context.masked_fill(~mask.unsqueeze(-1), 0.0)

        expanded_global = global_context.unsqueeze(1).expand(-1, entity_count, -1)
        updated = entities + self.residual(torch.cat((entities, context, expanded_global), dim=-1))
        updated = updated.masked_fill(~mask.unsqueeze(-1), 0.0)
        return updated, context


class ContextualEntityMixerPolicyValue(PolicyValueBase):
    def __init__(self, spec: ModelSpec):
        super().__init__(spec)
        if spec.architecture != "contextual_entity_mixer":
            raise ValueError("ContextualEntityMixerPolicyValue requires contextual_entity_mixer")
        h = spec.hidden_dim
        self.entity_encoder = nn.Sequential(nn.Linear(ENTITY_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.entity_gate = nn.Linear(h, 1)
        self.global_encoder = nn.Sequential(nn.Linear(GLOBAL_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.mix = nn.Linear(h * 2, h)
        self.interactions = nn.ModuleList(
            ContextualInteractionBlock(h, spec.dropout)
            for _ in range(spec.interaction_blocks)
        )
        self.blocks = nn.Sequential(*(ResidualBlock(h, spec.dropout) for _ in range(spec.blocks)))
        self.norm = nn.LayerNorm(h)

    def _contextual_entities(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_context: torch.Tensor,
        collect_contexts: bool = False,
    ) -> tuple[torch.Tensor, list[torch.Tensor]]:
        encoded = self.entity_encoder(entities)
        encoded = encoded.masked_fill(~mask.unsqueeze(-1), 0.0)
        contexts: list[torch.Tensor] = []
        for block in self.interactions:
            encoded, context = block(encoded, mask, global_context)
            if collect_contexts:
                contexts.append(context)
        return encoded, contexts

    def contextual_entity_embeddings(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
    ) -> torch.Tensor:
        global_context = self.global_encoder(global_features)
        return self._contextual_entities(entities, mask, global_context)[0]

    def contextual_interaction_contexts(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
    ) -> list[torch.Tensor]:
        global_context = self.global_encoder(global_features)
        return self._contextual_entities(entities, mask, global_context, collect_contexts=True)[1]

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor) -> torch.Tensor:
        global_context = self.global_encoder(global_features)
        encoded, _ = self._contextual_entities(entities, mask, global_context)
        gate = self.entity_gate(encoded).squeeze(-1).masked_fill(~mask, torch.finfo(encoded.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, global_context], dim=-1))
        return self.norm(self.blocks(state))


def build_model(spec: ModelSpec) -> PolicyValueBase:
    spec.validate()
    if spec.architecture == "flat_resmlp":
        return FlatResMLPPolicyValue(spec)
    if spec.architecture == "entity_mixer":
        return EntityMixerPolicyValue(spec)
    return ContextualEntityMixerPolicyValue(spec)
