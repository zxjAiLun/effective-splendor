"""Immutable singleton sampling; categorical draw independent of worker order."""
import hashlib
import math

import torch

from ..data import collate_states
from ..io import canonical_hash
from .contract import integer, text, validate_request, validate_response
from .model import behavior_identity, new_model


class Behavior:
    def __init__(self, model, *, catalog_fingerprint, action_seed, runtime):
        self.catalog = text(catalog_fingerprint, "catalog_fingerprint")
        self.action_seed = integer(action_seed, 0, 2**63 - 1, "action_seed")
        self.runtime = dict(runtime)
        self.model = model.frozen_copy()
        self.identity = behavior_identity(self.model, catalog_fingerprint=self.catalog,
                                          action_seed=action_seed, runtime=self.runtime)

    def payload(self):
        return {"format": "prism-ppo-snapshot-v1", "behavior_id": self.identity,
                "catalog_fingerprint": self.catalog, "action_seed": self.action_seed,
                "runtime": self.runtime, "style_enabled": self.model.style_enabled,
                "state_dict": {k: v.detach().cpu().clone() for k, v in self.model.state_dict().items()}}

    @classmethod
    def from_payload(cls, value, *, runtime):
        from .contract import exact
        exact(value, {"format", "behavior_id", "catalog_fingerprint", "action_seed", "runtime", "style_enabled", "state_dict"}, "snapshot")
        if value["format"] != "prism-ppo-snapshot-v1" or value["runtime"] != runtime:
            raise ValueError("snapshot runtime/format mismatch")
        model = new_model(style_enabled=value["style_enabled"], state_dict=value["state_dict"]).to(runtime["device"])
        result = cls(model, catalog_fingerprint=value["catalog_fingerprint"], action_seed=value["action_seed"], runtime=runtime)
        if result.identity != value["behavior_id"]:
            raise ValueError("snapshot behavior identity mismatch")
        return result

    def sample(self, request):
        validate_request(request)
        if request["behavior_id"] != self.identity or request["catalog_fingerprint"] != self.catalog:
            raise ValueError("request snapshot identity mismatch")
        batch = collate_states([request["input"]])
        device = next(self.model.parameters()).device
        batch = {key: v.to(device) for key, v in batch.items()}
        with torch.inference_mode(), torch.autocast(device_type=device.type, enabled=False):
            logits, values, style = self.model.forward_batch(batch)
            # Definition shared with learner: f32 network, f64 softmax, no bias.
            probabilities = torch.softmax(logits[0].double(), -1).cpu().tolist()
        draw_key = ["prism-ppo-draw-v1", self.action_seed, request["job_id"], request["actor"], request["decision_index"]]
        digest = bytes.fromhex(canonical_hash(draw_key))
        uniform = (int.from_bytes(digest[:8], "big") >> 11) / 2**53
        cumulative, index = 0.0, None
        for i, prob in enumerate(probabilities):
            cumulative += prob
            if uniform < cumulative:
                index = i
                break
        if index is None:  # Floating-point summation endpoint only.
            index = max(i for i, p in enumerate(probabilities) if p > 0)
        response = {key: request[key] for key in ("behavior_id", "job_id", "game_id", "actor", "request_id", "decision_index")}
        response.update(format="prism-ppo-response-v1", chosen_index=index,
                        log_prob=math.log(probabilities[index]), value=values.sigmoid()[0].item(),
                        style_value=style[0].item(), probabilities=probabilities)
        return validate_response(response, request)

    def verify(self, row, *, logp_tolerance, value_tolerance):
        actual = self.sample(row["request"])
        old = validate_response(row["response"], row["request"])
        if actual["chosen_index"] != old["chosen_index"]:
            raise ValueError("categorical draw does not reproduce")
        if abs(actual["log_prob"] - old["log_prob"]) > logp_tolerance:
            raise ValueError("behavior logp drift")
        if max(abs(actual[k] - old[k]) for k in ("value", "style_value")) > value_tolerance:
            raise ValueError("behavior value drift")
        # Full distribution binds unchosen actions as well as the selected one.
        if max(abs(a - b) for a, b in zip(actual["probabilities"], old["probabilities"])) > logp_tolerance:
            raise ValueError("behavior distribution drift")
        return actual
