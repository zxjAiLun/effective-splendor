"""M39A GPU policy/value model, initialization, and checkpoint contract."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Sequence

# This must be set before torch initializes cuBLAS.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn

from .encoding import encode_action, encode_observation
from .m25_delta_v2 import encode_action_delta_v2
from .m31a_train import DeltaEntityMixer
from .m39a_contract import HEAD_INIT_SEED, file_sha256
from .train import checkpoint_semantic_hash


CHECKPOINT_FORMAT = "effective-splendor-m39a-checkpoint"
CHECKPOINT_VERSION = 1
MODEL_ID = "m39a-delta-entity-mixer-ppo-v1"
HIDDEN_DIM = 192


class M39APolicyValue(DeltaEntityMixer):
    """D2-v2 actor/trunk with fresh linear two-player critic and VP head."""

    def __init__(self) -> None:
        super().__init__(hidden_dim=HIDDEN_DIM, blocks=4, dropout=0.0)
        self.value = nn.Sequential(
            nn.Linear(HIDDEN_DIM, HIDDEN_DIM),
            nn.GELU(),
            nn.Linear(HIDDEN_DIM, 2),
        )
        self.auxiliary_score_head = nn.Linear(HIDDEN_DIM, 1)

    def forward_packed(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
        actions: torch.Tensor,
        action_offsets: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        counts = action_offsets[1:] - action_offsets[:-1]
        expanded = torch.repeat_interleave(state, counts, dim=0)
        logits = self.policy(
            torch.cat([expanded, action, expanded * action], dim=-1)
        ).squeeze(-1)
        return logits, self.value(state), self.auxiliary_score_head(state).squeeze(-1)


def _init_linear(linear: nn.Linear, generator: torch.Generator) -> None:
    nn.init.kaiming_uniform_(
        linear.weight,
        a=math.sqrt(5),
        mode="fan_in",
        nonlinearity="leaky_relu",
        generator=generator,
    )
    if linear.bias is not None:
        nn.init.zeros_(linear.bias)


def initialize_new_heads(model: M39APolicyValue, seed: int = HEAD_INIT_SEED) -> None:
    """Overwrite all constructor draws in the frozen critic-then-aux order."""

    if next(model.parameters()).device.type != "cpu":
        raise ValueError("new heads must be initialized on CPU before device transfer")
    generator = torch.Generator(device="cpu").manual_seed(int(seed))
    _init_linear(model.value[0], generator)
    _init_linear(model.value[2], generator)
    _init_linear(model.auxiliary_score_head, generator)


def load_d2_actor(
    base_checkpoint: Path,
    expected_file_sha256: str,
) -> tuple[M39APolicyValue, dict[str, Any]]:
    actual_sha = file_sha256(base_checkpoint)
    if actual_sha != expected_file_sha256:
        raise ValueError(
            f"D2-v2 checkpoint SHA mismatch: expected {expected_file_sha256}, got {actual_sha}"
        )
    payload = torch.load(base_checkpoint, map_location="cpu", weights_only=False)
    state = payload.get("state_dict")
    metadata = payload.get("metadata")
    if not isinstance(state, dict) or not isinstance(metadata, dict):
        raise ValueError("invalid D2-v2 checkpoint payload")

    model = M39APolicyValue()
    actor_state = {key: value for key, value in state.items() if not key.startswith("value.")}
    result = model.load_state_dict(actor_state, strict=False)
    expected_missing = {
        "value.0.weight",
        "value.0.bias",
        "value.2.weight",
        "value.2.bias",
        "auxiliary_score_head.weight",
        "auxiliary_score_head.bias",
    }
    if set(result.missing_keys) != expected_missing or result.unexpected_keys:
        raise ValueError(
            "D2-v2 actor load did not produce exactly the frozen new-head missing keys"
        )
    initialize_new_heads(model)
    return model, metadata


def checkpoint_metadata(
    *,
    plan_hash: str,
    cycle: int,
    base_checkpoint_sha256: str,
    catalog_hash: str,
    parent_checkpoint_hash: str | None,
) -> dict[str, Any]:
    return {
        "format": CHECKPOINT_FORMAT,
        "version": CHECKPOINT_VERSION,
        "model_id": MODEL_ID,
        "architecture": "d2_v2_actor_fresh_linear_critic_aux",
        "value_semantics": "centered_outcome_viewer_relative",
        "value_output_shape": 2,
        "value_activation": "linear",
        "base_value_head_loaded": False,
        "head_init_seed": HEAD_INIT_SEED,
        "plan_hash": plan_hash,
        "cycle": cycle,
        "base_checkpoint_sha256": base_checkpoint_sha256,
        "parent_checkpoint_hash": parent_checkpoint_hash,
        "catalog_hash": catalog_hash,
        "parameter_count": 953_669,
    }


def build_initial_checkpoint(
    *,
    base_checkpoint: Path,
    expected_base_sha256: str,
    plan_hash: str,
    catalog_hash: str,
) -> dict[str, Any]:
    model, _ = load_d2_actor(base_checkpoint, expected_base_sha256)
    metadata = checkpoint_metadata(
        plan_hash=plan_hash,
        cycle=0,
        base_checkpoint_sha256=expected_base_sha256,
        catalog_hash=catalog_hash,
        parent_checkpoint_hash=None,
    )
    state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    return {
        "metadata": metadata,
        "state_dict": state,
        "checkpoint_hash": checkpoint_semantic_hash(metadata, state),
        "optimizer_state_dict": None,
    }


def load_m39a_checkpoint(
    path: Path,
    *,
    expected_file_sha256: str | None = None,
    expected_plan_hash: str | None = None,
    device: torch.device | str = "cpu",
) -> tuple[M39APolicyValue, dict[str, Any]]:
    if expected_file_sha256 is not None:
        actual_file_hash = file_sha256(path)
        if actual_file_hash != expected_file_sha256:
            raise ValueError(
                f"M39A checkpoint file SHA mismatch: expected {expected_file_sha256}, got {actual_file_hash}"
            )
    payload = torch.load(path, map_location="cpu", weights_only=False)
    metadata = payload.get("metadata")
    state = payload.get("state_dict")
    if not isinstance(metadata, dict) or not isinstance(state, dict):
        raise ValueError("invalid M39A checkpoint payload")
    if metadata.get("format") != CHECKPOINT_FORMAT or metadata.get("version") != CHECKPOINT_VERSION:
        raise ValueError("unsupported M39A checkpoint format/version")
    if expected_plan_hash is not None and metadata.get("plan_hash") != expected_plan_hash:
        raise ValueError("M39A checkpoint plan hash mismatch")
    actual_semantic_hash = checkpoint_semantic_hash(metadata, state)
    if payload.get("checkpoint_hash") != actual_semantic_hash:
        raise ValueError("M39A checkpoint semantic hash mismatch")
    model = M39APolicyValue()
    model.load_state_dict(state, strict=True)
    model.to(device)
    return model, payload


def encode_decisions(
    observations: Sequence[dict[str, Any]],
    legal_action_sets: Sequence[Sequence[dict[str, Any]]],
    catalog: dict[str, Any],
) -> dict[str, torch.Tensor]:
    if len(observations) != len(legal_action_sets) or not observations:
        raise ValueError("observations/legal_action_sets must be non-empty and aligned")
    entities = []
    masks = []
    globals_ = []
    actions = []
    offsets = [0]
    for observation, legal_actions in zip(observations, legal_action_sets):
        if not legal_actions:
            raise ValueError("every decision requires at least one legal action")
        encoded = encode_observation(observation, catalog)
        entities.append(encoded.entities)
        masks.append(encoded.mask)
        globals_.append(encoded.global_features)
        for action in legal_actions:
            actions.append(
                encode_action(action).tolist()
                + encode_action_delta_v2(observation, action, catalog)
            )
        offsets.append(len(actions))
    return {
        "entities": torch.stack(entities),
        "mask": torch.stack(masks),
        "global_features": torch.stack(globals_),
        "actions": torch.tensor(actions, dtype=torch.float32),
        "action_offsets": torch.tensor(offsets, dtype=torch.long),
    }


def move_encoded(batch: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {key: tensor.to(device) for key, tensor in batch.items()}


@torch.no_grad()
def infer_decision(
    model: M39APolicyValue,
    observation: dict[str, Any],
    legal_actions: Sequence[dict[str, Any]],
    catalog: dict[str, Any],
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    model.eval()
    encoded = move_encoded(encode_decisions([observation], [legal_actions], catalog), device)
    logits, values, auxiliary = model.forward_packed(**encoded)
    if not torch.isfinite(logits).all() or not torch.isfinite(values).all() or not torch.isfinite(auxiliary).all():
        raise ValueError("M39A inference produced non-finite output")
    return logits, values[0], auxiliary[0]
