"""Exact numerical contract in docs/m51-prism-implementation-contract.md."""

import math
from typing import Mapping

import torch
from torch import nn

ENTITY_DIM = 96
ACTION_DIM = 80
HIDDEN_DIM = 128
NUM_BLOCKS = 2
MAX_ENTITIES = 128
MAX_ACTIONS = 4096
OBS_SCHEMA = "prism-observation-v1"
ACTION_SCHEMA = "prism-action-v1"
INPUT_KEYS = ("entities", "actions", "targets", "entity_mask", "action_mask")


def masked_mean(h: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return h.masked_fill(~mask.unsqueeze(-1), 0).sum(1) / mask.sum(1, keepdim=True)


class RelationBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.local = nn.Linear(HIDDEN_DIM, HIDDEN_DIM)
        self.context = nn.Linear(HIDDEN_DIM, HIDDEN_DIM)
        self.norm = nn.LayerNorm(HIDDEN_DIM, eps=1e-5)

    def forward(self, h, mask):
        g = masked_mean(h, mask)
        u = torch.relu(self.local(h) + self.context(g).unsqueeze(1))
        return self.norm(h + u).masked_fill(~mask.unsqueeze(-1), 0)


class PrismModel(nn.Module):
    """forward returns (masked policy logits [B,A], VALUE LOGITS [B])."""

    def __init__(self):
        super().__init__()
        self.encoder = nn.Linear(ENTITY_DIM, HIDDEN_DIM)
        self.blocks = nn.ModuleList([RelationBlock() for _ in range(NUM_BLOCKS)])
        self.action = nn.Linear(ACTION_DIM, HIDDEN_DIM)
        self.target = nn.Linear(HIDDEN_DIM, HIDDEN_DIM)
        self.global_action = nn.Linear(HIDDEN_DIM, HIDDEN_DIM)
        self.key = nn.Linear(HIDDEN_DIM, HIDDEN_DIM)
        self.entity_value = nn.Linear(HIDDEN_DIM, HIDDEN_DIM)
        self.policy_hidden = nn.Linear(3 * HIDDEN_DIM, HIDDEN_DIM)
        self.policy_out = nn.Linear(HIDDEN_DIM, 1)
        self.value_hidden = nn.Linear(HIDDEN_DIM, HIDDEN_DIM)
        self.value_out = nn.Linear(HIDDEN_DIM, 1)

    def forward(self, entities, actions, targets, entity_mask=None, action_mask=None):
        if entities.ndim != 3 or entities.shape[2] != ENTITY_DIM:
            raise ValueError("entities must have shape [B,E,96]")
        if actions.ndim != 3 or actions.shape[2] != ACTION_DIM:
            raise ValueError("actions must have shape [B,A,80]")
        b, e, _ = entities.shape
        if b < 1 or actions.shape[0] != b or not 1 <= e <= MAX_ENTITIES:
            raise ValueError("invalid batch/entity count")
        if not 1 <= actions.shape[1] <= MAX_ACTIONS:
            raise ValueError("invalid action count")
        if entities.dtype != torch.float32 or actions.dtype != torch.float32:
            raise ValueError("Prism requires float32 inputs")
        if targets.shape != actions.shape[:2] or targets.dtype != torch.int64:
            raise ValueError("targets must be int64 [B,A]")
        if entity_mask is None:
            entity_mask = torch.ones((b, e), device=entities.device, dtype=torch.bool)
        if action_mask is None:
            action_mask = torch.ones(actions.shape[:2], device=actions.device, dtype=torch.bool)
        if (entity_mask.shape != entities.shape[:2] or action_mask.shape != actions.shape[:2]
                or entity_mask.dtype != torch.bool or action_mask.dtype != torch.bool):
            raise ValueError("invalid mask shape/dtype")
        if any(t.device != entities.device for t in (actions, targets, entity_mask, action_mask)):
            raise ValueError("all inputs must share a device")
        if not entity_mask.any(1).all() or not action_mask.any(1).all():
            raise ValueError("each state needs an entity and a legal action")
        # Padding is outside the input domain, even if its stored values are NaN.
        entities = entities.masked_fill(~entity_mask.unsqueeze(-1), 0)
        actions = actions.masked_fill(~action_mask.unsqueeze(-1), 0)
        targets = targets.masked_fill(~action_mask, -1)
        if not torch.isfinite(entities).all() or not torch.isfinite(actions).all():
            raise ValueError("nonfinite input")
        if ((targets < -1) | (targets >= e)).any():
            raise ValueError("invalid target index")
        safe_targets = targets.clamp_min(0)
        if ((targets >= 0) & ~entity_mask.gather(1, safe_targets)).any():
            raise ValueError("target refers to a padded entity")

        h = torch.relu(self.encoder(entities))
        for block in self.blocks:
            h = block(h, entity_mask)
        g = masked_mean(h, entity_mask)
        t = h.gather(1, safe_targets.unsqueeze(-1).expand(-1, -1, HIDDEN_DIM))
        t = t.masked_fill((targets < 0).unsqueeze(-1), 0)
        # target(0) deliberately retains the learned bias for no-target actions.
        q = torch.relu(self.action(actions) + self.target(t) + self.global_action(g).unsqueeze(1))
        k, v = self.key(h), self.entity_value(h)
        scores = torch.bmm(q, k.transpose(1, 2)) / math.sqrt(HIDDEN_DIM)
        scores = scores.masked_fill(~entity_mask.unsqueeze(1), -torch.inf)
        r = torch.bmm(torch.softmax(scores, dim=-1), v)
        global_rows = g.unsqueeze(1).expand(-1, actions.shape[1], -1)
        logits = self.policy_out(torch.relu(self.policy_hidden(torch.cat((q, r, global_rows), -1))))
        logits = logits.squeeze(-1).masked_fill(~action_mask, -torch.inf)
        value_logit = self.value_out(torch.relu(self.value_hidden(g))).squeeze(-1)
        if not torch.isfinite(logits[action_mask]).all() or not torch.isfinite(value_logit).all():
            raise ValueError("nonfinite model output")
        return logits, value_logit

    def forward_batch(self, batch: Mapping[str, torch.Tensor]):
        return self(**{key: batch[key] for key in INPUT_KEYS})

    def predict(self, encoded_state):
        return predict(self, encoded_state)


def predict(model: PrismModel, encoded_state: Mapping) -> dict:
    """Single validated EncodedState -> Rust-compatible {logits: list, value: float}."""
    from .data import collate_states

    if not isinstance(encoded_state, Mapping) or set(encoded_state) != {"entities", "actions", "targets"}:
        raise ValueError("EncodedState requires exactly entities/actions/targets")
    batch = collate_states([encoded_state])
    device = next(model.parameters()).device
    batch = {key: value.to(device) for key, value in batch.items()}
    was_training = model.training
    try:
        model.eval()
        with torch.inference_mode(), torch.autocast(device_type=device.type, enabled=False):
            logits, value_logit = model.forward_batch(batch)
            return {"logits": logits[0].cpu().tolist(), "value": value_logit.sigmoid()[0].item()}
    finally:
        model.train(was_training)
