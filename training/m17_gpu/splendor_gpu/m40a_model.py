"""M40A predictive-head model: architecture, initialization, and the
arm state_dict-copy semantics.

The model extends the M39A D2-v2 actor path with the M40A predictive
heads. The trunk, action encoder, and policy head are byte-identical to
M39A; only the head block differs. The M39A critic (2-way value) and
auxiliary VP head are REPLACED by the M40A head set per the frozen
design: the outcome head is the PPO value source (V = p_win − p_loss).
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any

import torch
from torch import nn

from .m31a_train import DeltaEntityMixer
from .m40a_constants import (
    HEAD_INIT_SEED,
    TIMING_HORIZONS,
    VP_BINS,
    VP_DIFF_NORMALIZER,
)

HIDDEN_DIM = 192
CHECKPOINT_FORMAT = "effective-splendor-m40a-checkpoint"
CHECKPOINT_VERSION = 1
MODEL_ID = "m40a-predictive-critic-warmstart-v1"


class M40APredictiveHeads(nn.Module):
    """The frozen M40A head set, reading the shared state embedding."""

    def __init__(self) -> None:
        super().__init__()
        self.outcome = nn.Linear(HIDDEN_DIM, 3)
        self.final_vp_self = nn.Linear(HIDDEN_DIM, VP_BINS)
        self.final_vp_opp = nn.Linear(HIDDEN_DIM, VP_BINS)
        self.vp_difference = nn.Linear(HIDDEN_DIM, 1)
        # Timing: self/opp × 2/4/8 own decisions (six Bernoulli outputs).
        self.timing = nn.Linear(HIDDEN_DIM, 2 * len(TIMING_HORIZONS))

    def forward(self, state: torch.Tensor) -> dict[str, torch.Tensor]:
        return {
            "outcome": self.outcome(state),
            "final_vp_self": self.final_vp_self(state),
            "final_vp_opp": self.final_vp_opp(state),
            "vp_difference": self.vp_difference(state).squeeze(-1),
            "timing": self.timing(state),
        }


class M40AModel(DeltaEntityMixer):
    """D2-v2 actor/trunk with the M40A predictive heads.

    The inherited D2 sigmoid `.value` head is REMOVED at construction
    (P2-1 of the implementation review): leaving it in place would
    pollute the state_dict, the parameter count, and the checkpoint
    identity with dead parameters that forward never reads. Actor
    weights load from D2-v2 exactly as M39A does — the loader below
    asserts the exact missing/unexpected key sets.
    """

    def __init__(self) -> None:
        super().__init__(hidden_dim=HIDDEN_DIM, blocks=4, dropout=0.0)
        # Remove the inherited legacy sigmoid value head: delete the
        # submodule so it disappears from parameters AND state_dict.
        delattr(self, "value")
        self.heads = M40APredictiveHeads()

    def forward_packed(
        self,
        entities: torch.Tensor,
        mask: torch.Tensor,
        global_features: torch.Tensor,
        actions: torch.Tensor,
        action_offsets: torch.Tensor,
    ) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        counts = action_offsets[1:] - action_offsets[:-1]
        expanded = torch.repeat_interleave(state, counts, dim=0)
        logits = self.policy(
            torch.cat([expanded, action, expanded * action], dim=-1)
        ).squeeze(-1)
        return logits, self.heads(state)


# The frozen expected key sets of the M40A head block (in state_dict
# naming), used by the strict D2 loader below.
_HEAD_KEYS = {
    "heads.outcome.weight",
    "heads.outcome.bias",
    "heads.final_vp_self.weight",
    "heads.final_vp_self.bias",
    "heads.final_vp_opp.weight",
    "heads.final_vp_opp.bias",
    "heads.vp_difference.weight",
    "heads.vp_difference.bias",
    "heads.timing.weight",
    "heads.timing.bias",
}


def load_d2_actor(
    model: M40AModel,
    base_checkpoint: Path,
    expected_file_sha256: str,
) -> None:
    """Load ONLY the D2-v2 actor (trunk/action_encoder/policy) into the
    model, with strict key-set assertions.

    - verifies the D2-v2 checkpoint file SHA first;
    - requires exactly the legacy `value.*` keys to be unexpected (the
      M40A model deliberately has no `.value` head);
    - requires exactly the M40A predictive-head keys to be missing;
    - leaves the heads at whatever state they carry (the caller
      initializes them from the frozen seed separately).
    """
    from .m39a_contract import file_sha256 as _file_sha256

    actual_sha = _file_sha256(base_checkpoint)
    if actual_sha != expected_file_sha256:
        raise ValueError(
            f"D2-v2 checkpoint SHA mismatch: expected {expected_file_sha256}, "
            f"got {actual_sha}"
        )
    payload = torch.load(base_checkpoint, map_location="cpu", weights_only=False)
    state = payload.get("state_dict")
    if not isinstance(state, dict):
        raise ValueError("invalid D2-v2 checkpoint payload")

    # The D2-v2 checkpoint's value head is a Sequential of
    # Linear/GELU/Linear/Sigmoid — the Sigmoid contributes no parameters,
    # so exactly four value.* parameter keys must exist and be dropped.
    value_keys = {
        key for key in state if key.startswith("value.")
    }
    expected_value_keys = {
        "value.0.weight",
        "value.0.bias",
        "value.2.weight",
        "value.2.bias",
    }
    if value_keys != expected_value_keys:
        raise ValueError(
            f"D2-v2 checkpoint value head keys {sorted(value_keys)} != "
            f"expected {sorted(expected_value_keys)}"
        )
    actor_state = {
        key: value for key, value in state.items() if not key.startswith("value.")
    }
    result = model.load_state_dict(actor_state, strict=False)
    if result.unexpected_keys:
        raise ValueError(
            f"D2-v2 actor load produced unexpected keys {sorted(result.unexpected_keys)}"
        )
    if set(result.missing_keys) != _HEAD_KEYS:
        raise ValueError(
            f"D2-v2 actor load missing keys {sorted(result.missing_keys)} "
            f"(expected the M40A predictive heads {sorted(_HEAD_KEYS)})"
        )


def head_state_semantic_hash(model: M40AModel) -> str:
    """A canonical SHA-256 over the ordered head parameter tensors — the
    identity of the head state, used to prove the A/B fork and to bind
    the pretrain input/output states into provenance."""
    hasher = hashlib.sha256()
    for name, tensor in sorted(model.heads.state_dict().items()):
        hasher.update(name.encode("utf-8"))
        hasher.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return hasher.hexdigest()


def _init_linear(linear: nn.Linear, generator: torch.Generator) -> None:
    """The M39A frozen initializer semantics (fresh nn.Linear default)."""
    nn.init.kaiming_uniform_(
        linear.weight,
        a=math.sqrt(5),
        mode="fan_in",
        nonlinearity="leaky_relu",
        generator=generator,
    )
    if linear.bias is not None:
        nn.init.zeros_(linear.bias)


def initialize_predictive_heads(model: M40AModel, seed: int = HEAD_INIT_SEED) -> None:
    """Overwrite all constructor draws in the frozen head order.

    Order (single generator consumption sequence): outcome, final_vp_self,
    final_vp_opp, vp_difference, timing.
    """
    if next(model.parameters()).device.type != "cpu":
        raise ValueError("heads must be initialized on CPU before device transfer")
    generator = torch.Generator(device="cpu").manual_seed(int(seed))
    for linear in (
        model.heads.outcome,
        model.heads.final_vp_self,
        model.heads.final_vp_opp,
        model.heads.vp_difference,
        model.heads.timing,
    ):
        _init_linear(linear, generator)


def copy_head_state(model: M40AModel) -> dict[str, torch.Tensor]:
    """Deep-copy the head state_dict (the A/B arm-fork primitive)."""
    return copy.deepcopy(model.heads.state_dict())


def load_head_state(model: M40AModel, state_dict: dict[str, torch.Tensor]) -> None:
    model.heads.load_state_dict(state_dict)


def outcome_value(outcome_logits: torch.Tensor) -> torch.Tensor:
    """V(s) = p_win − p_loss from the 3-way outcome logits."""
    probabilities = torch.softmax(outcome_logits.to(dtype=torch.float32), dim=-1)
    return probabilities[..., 2] - probabilities[..., 0]


def normalized_vp_difference(vp_self: float, vp_opp: float) -> float:
    """The frozen VP-difference target: clamp((self − opp)/15, −1, +1)."""
    value = (vp_self - vp_opp) / VP_DIFF_NORMALIZER
    return max(-1.0, min(1.0, value))


def checkpoint_metadata(
    *,
    plan_hash: str,
    arm: str,
    cycle: int,
    parent_checkpoint_hash: str | None,
    catalog_hash: str,
    design_sha: str,
) -> dict[str, Any]:
    return {
        "format": CHECKPOINT_FORMAT,
        "version": CHECKPOINT_VERSION,
        "model_id": MODEL_ID,
        "design_sha": design_sha,
        "arm": arm,
        "cycle": cycle,
        "plan_hash": plan_hash,
        "parent_checkpoint_hash": parent_checkpoint_hash,
        "catalog_hash": catalog_hash,
        "head_init_seed": HEAD_INIT_SEED,
        "value_semantics": "V = p_win - p_loss (centered outcome expectation)",
    }
