"""Independent training-only style head; unchanged v0.1 deployment model."""
import copy

import torch
from torch import nn

from ..export import export_weights, load_weights, validate_state_dict
from ..io import canonical_hash, tensor_identity
from ..model import HIDDEN_DIM, INPUT_KEYS, PrismModel, masked_mean


class PPOModel(nn.Module):
    def __init__(self, policy=None, *, style_enabled):
        super().__init__()
        if type(style_enabled) is not bool:
            raise ValueError("style_enabled must be bool")
        self.policy = policy if policy is not None else PrismModel()
        validate_state_dict(self.policy.state_dict())
        self.style_enabled = style_enabled
        self.style_head = nn.Sequential(nn.Linear(HIDDEN_DIM, HIDDEN_DIM), nn.ReLU(), nn.Linear(HIDDEN_DIM, 1))
        nn.init.zeros_(self.style_head[-1].weight)
        nn.init.zeros_(self.style_head[-1].bias)
        self.style_head.requires_grad_(style_enabled)

    def forward_batch(self, batch):
        features = {key: batch[key] for key in INPUT_KEYS}
        logits, value_logits = self.policy.forward_batch(features)
        if not self.style_enabled:
            return logits, value_logits, torch.zeros_like(value_logits)
        # Reuse weights but not source changes/hooks in frozen v0.1. A second
        # encoder pass is deliberate for the initial, correctness-first adapter.
        mask = features["entity_mask"]
        entities = features["entities"].masked_fill(~mask.unsqueeze(-1), 0)
        h = torch.relu(self.policy.encoder(entities))
        for block in self.policy.blocks:
            h = block(h, mask)
        style = self.style_head(masked_mean(h, mask)).squeeze(-1)
        if not torch.isfinite(style).all():
            raise ValueError("nonfinite style value")
        return logits, value_logits, style

    def frozen_copy(self):
        result = copy.deepcopy(self).eval()
        result.requires_grad_(False)
        return result

    def export(self, path, catalog_fingerprint, *, provenance):
        return export_weights(self.policy, path, catalog_fingerprint, provenance=provenance)


def new_model(*, style_enabled, state_dict=None):
    # Loading/validating a snapshot does not perturb any training RNG.
    with torch.random.fork_rng(devices=[]):
        model = PPOModel(style_enabled=style_enabled)
    if state_dict is not None:
        expected = model.state_dict()
        if not isinstance(state_dict, dict) or set(state_dict) != set(expected):
            raise ValueError("wrong PPO tensor keys")
        for key, tensor in state_dict.items():
            if not isinstance(tensor, torch.Tensor) or tensor.shape != expected[key].shape or tensor.dtype != torch.float32 or not torch.isfinite(tensor).all():
                raise ValueError(f"invalid PPO tensor: {key}")
        model.load_state_dict(state_dict, strict=True)
    return model


def warm_start(weights, catalog_fingerprint, *, style_enabled, initialization_seed):
    policy = load_weights(weights, expected_catalog_fingerprint=catalog_fingerprint)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(initialization_seed)
        model = PPOModel(policy, style_enabled=style_enabled)
    return model


def behavior_identity(model, *, catalog_fingerprint, action_seed, runtime):
    return canonical_hash({"format": "prism-ppo-behavior-v1", "tensors": tensor_identity(model.state_dict()),
                           "style_enabled": model.style_enabled, "catalog_fingerprint": catalog_fingerprint,
                           "action_seed": action_seed, "runtime": runtime, "sampling": "softmax-f64-t1-sha256-cdf-v1"})
