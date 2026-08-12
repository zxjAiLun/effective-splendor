"""M18B distributional Double-DQN with deterministic prioritized replay."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn

from .agent import load_model
from .data import canonical_json, catalog_semantic_hash, load_catalog
from .encoding import ACTION_FEATURES, EncodedObservation, encode_action, encode_observation
from .model import EntityMixerPolicyValue, ModelSpec
from .self_play_train import self_play_hash
from .train import file_sha256, resolve_device, seed_everything

RAINBOW_CHECKPOINT_FORMAT = "effective-splendor-distributional-q-checkpoint"
RAINBOW_CHECKPOINT_DOMAIN = b"effective-splendor-distributional-q-checkpoint-v1\0"


@dataclass(frozen=True)
class RainbowSpec:
    hidden_dim: int
    blocks: int
    atoms: int
    v_min: float
    v_max: float

    def validate(self) -> None:
        if self.atoms < 3 or self.atoms > 201:
            raise ValueError("atoms must be within 3..=201")
        if not self.v_min < self.v_max:
            raise ValueError("v_min must be smaller than v_max")
        ModelSpec("entity_mixer", self.hidden_dim, self.blocks).validate()


class DistributionalQNetwork(nn.Module):
    def __init__(self, spec: RainbowSpec):
        super().__init__()
        spec.validate()
        self.spec = spec
        base = EntityMixerPolicyValue(ModelSpec("entity_mixer", spec.hidden_dim, spec.blocks))
        self.entity_encoder = base.entity_encoder
        self.entity_gate = base.entity_gate
        self.global_encoder = base.global_encoder
        self.mix = base.mix
        self.blocks = base.blocks
        self.norm = base.norm
        self.action_encoder = base.action_encoder
        h = spec.hidden_dim
        self.q_head = nn.Sequential(nn.Linear(h * 3, h), nn.GELU(), nn.Linear(h, spec.atoms))
        self.register_buffer("support", torch.linspace(spec.v_min, spec.v_max, spec.atoms))

    def state_embedding(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor) -> torch.Tensor:
        encoded = self.entity_encoder(entities)
        gate = self.entity_gate(encoded).squeeze(-1).masked_fill(~mask, torch.finfo(encoded.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        return self.norm(self.blocks(self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))))

    def forward(self, entities: torch.Tensor, mask: torch.Tensor, global_features: torch.Tensor, actions: torch.Tensor, action_mask: torch.Tensor) -> torch.Tensor:
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        expanded = state.unsqueeze(1).expand(-1, actions.shape[1], -1)
        logits = self.q_head(torch.cat([expanded, action, expanded * action], dim=-1))
        return logits.masked_fill(~action_mask.unsqueeze(-1), torch.finfo(logits.dtype).min)

    def expected_q(self, logits: torch.Tensor) -> torch.Tensor:
        return (torch.softmax(logits, dim=-1) * self.support).sum(dim=-1)


def initialize_from_policy_value(model: DistributionalQNetwork, checkpoint: Path, checkpoint_hash: str, device: torch.device) -> dict[str, Any]:
    base, metadata = load_model(checkpoint, checkpoint_hash, device)
    source = base.state_dict()
    target = model.state_dict()
    copied = []
    for name in target:
        if name in source and target[name].shape == source[name].shape:
            target[name] = source[name].detach().to(target[name].device)
            copied.append(name)
    model.load_state_dict(target, strict=True)
    return {"base_metadata": metadata, "copied_tensors": copied}


def rainbow_checkpoint_hash(metadata: dict[str, Any], state_dict: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256(RAINBOW_CHECKPOINT_DOMAIN)
    digest.update(canonical_json(metadata))
    for name in sorted(state_dict):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(str(tensor.dtype).encode("ascii") + b"\0")
        digest.update(canonical_json(list(tensor.shape)))
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def load_rainbow_model(path: Path, required_hash: str, device: torch.device):
    payload = torch.load(path, map_location="cpu", weights_only=True)
    metadata = payload["metadata"]
    if metadata.get("format") != RAINBOW_CHECKPOINT_FORMAT or metadata.get("version") != 1:
        raise ValueError("unsupported Rainbow checkpoint")
    actual = rainbow_checkpoint_hash(metadata, payload["state_dict"])
    if actual != required_hash:
        raise ValueError(f"checkpoint hash mismatch: expected {required_hash}, got {actual}")
    model = DistributionalQNetwork(RainbowSpec(**metadata["architecture"]))
    model.load_state_dict(payload["state_dict"], strict=True)
    model.to(device).eval()
    return model, metadata


@dataclass
class Transition:
    observation: dict[str, Any]
    legal_actions: list[dict[str, Any]]
    action_index: int
    reward: float
    next_observation: dict[str, Any] | None
    next_legal_actions: list[dict[str, Any]]
    terminal: bool
    game_index: int


def build_transitions(payload: dict[str, Any]) -> list[Transition]:
    by_game: dict[int, list[dict[str, Any]]] = {}
    for example in payload["examples"]:
        by_game.setdefault(int(example["game_index"]), []).append(example)
    transitions = []
    for game_index in sorted(by_game):
        examples = sorted(by_game[game_index], key=lambda item: int(item["ply"]))
        for index, example in enumerate(examples):
            actor = int(example["actor"])
            next_example = next((item for item in examples[index + 1:] if int(item["actor"]) == actor), None)
            legal = example["legal_actions"]
            chosen_key = json.dumps(example["chosen_action"], sort_keys=True, separators=(",", ":"))
            keys = [json.dumps(action, sort_keys=True, separators=(",", ":")) for action in legal]
            if keys.count(chosen_key) != 1:
                raise ValueError("chosen action must occur exactly once")
            terminal = next_example is None
            reward = (1.0 if int(example["final_ranks"][actor]) == 0 else -1.0) if terminal else 0.0
            transitions.append(Transition(
                observation=example["observation"], legal_actions=legal,
                action_index=keys.index(chosen_key), reward=reward,
                next_observation=None if terminal else next_example["observation"],
                next_legal_actions=[] if terminal else next_example["legal_actions"],
                terminal=terminal, game_index=game_index,
            ))
    if not transitions or not any(item.terminal for item in transitions):
        raise ValueError("self-play contains no terminal transitions")
    return transitions


def encode_transition(transition: Transition, catalog: dict[str, Any], device: torch.device):
    current: EncodedObservation = encode_observation(transition.observation, catalog)
    actions = torch.stack([encode_action(action) for action in transition.legal_actions])
    result = {
        "entities": current.entities.unsqueeze(0).to(device),
        "mask": current.mask.unsqueeze(0).to(device),
        "global": current.global_features.unsqueeze(0).to(device),
        "actions": actions.unsqueeze(0).to(device),
        "action_mask": torch.ones((1, len(actions)), dtype=torch.bool, device=device),
    }
    if not transition.terminal:
        nxt = encode_observation(transition.next_observation, catalog)
        next_actions = torch.stack([encode_action(action) for action in transition.next_legal_actions])
        result.update({
            "next_entities": nxt.entities.unsqueeze(0).to(device),
            "next_mask": nxt.mask.unsqueeze(0).to(device),
            "next_global": nxt.global_features.unsqueeze(0).to(device),
            "next_actions": next_actions.unsqueeze(0).to(device),
            "next_action_mask": torch.ones((1, len(next_actions)), dtype=torch.bool, device=device),
        })
    return result


def project_distribution(next_distribution: torch.Tensor, reward: float, terminal: bool, gamma: float, support: torch.Tensor) -> torch.Tensor:
    atoms = support.numel()
    delta = (support[-1] - support[0]) / (atoms - 1)
    target_support = torch.full_like(support, reward) if terminal else reward + gamma * support
    target_support = target_support.clamp(float(support[0]), float(support[-1]))
    location = (target_support - support[0]) / delta
    lower, upper = location.floor().long(), location.ceil().long()
    projected = torch.zeros_like(support)
    for index in range(atoms):
        if lower[index] == upper[index]:
            projected[lower[index]] += next_distribution[index]
        else:
            projected[lower[index]] += next_distribution[index] * (upper[index] - location[index])
            projected[upper[index]] += next_distribution[index] * (location[index] - lower[index])
    return projected


@torch.no_grad()
def transition_loss(model: DistributionalQNetwork, target: DistributionalQNetwork, transition: Transition, catalog: dict[str, Any], gamma: float, device: torch.device) -> tuple[torch.Tensor, float]:
    batch = encode_transition(transition, catalog, device)
    logits = model(batch["entities"], batch["mask"], batch["global"], batch["actions"], batch["action_mask"])[0, transition.action_index]
    if transition.terminal:
        next_distribution = torch.zeros_like(model.support)
        next_distribution[(model.support - transition.reward).abs().argmin()] = 1.0
    else:
        online_next = model(batch["next_entities"], batch["next_mask"], batch["next_global"], batch["next_actions"], batch["next_action_mask"])
        best = model.expected_q(online_next)[0].argmax()
        target_next = target(batch["next_entities"], batch["next_mask"], batch["next_global"], batch["next_actions"], batch["next_action_mask"])
        next_distribution = torch.softmax(target_next[0, best], dim=-1)
    projected = project_distribution(next_distribution, transition.reward, transition.terminal, gamma, model.support)
    loss = -(projected * torch.log_softmax(logits, dim=-1)).sum()
    predicted_q = float((torch.softmax(logits, dim=-1) * model.support).sum().item())
    target_q = float((projected * model.support).sum().item())
    return loss, abs(predicted_q - target_q)


@torch.no_grad()
def evaluate(model: DistributionalQNetwork, target: DistributionalQNetwork, transitions: list[Transition], catalog: dict[str, Any], gamma: float, device: torch.device) -> dict[str, float | int]:
    model.eval(); target.eval()
    losses, errors = [], []
    for transition in transitions:
        loss, error = transition_loss(model, target, transition, catalog, gamma, device)
        losses.append(float(loss.item())); errors.append(error)
    return {"transitions": len(transitions), "mean_cross_entropy": sum(losses) / len(losses), "mean_abs_td_error": sum(errors) / len(errors)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-play", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.self_play.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("format") != "effective-splendor-rainbow-training-config" or config.get("version") != 1:
        raise ValueError("unsupported M18B config")
    actual_hash = self_play_hash(payload)
    if actual_hash != config["expected_self_play_hash"]:
        raise ValueError("self-play hash mismatch")
    device = resolve_device(config["device"])
    seed_everything(int(config["seed"]))
    catalog = load_catalog(args.catalog)
    transitions = build_transitions(payload)
    train = [item for item in transitions if item.game_index % int(config["validation_game_modulus"]) != int(config["validation_game_remainder"])]
    validation = [item for item in transitions if item.game_index % int(config["validation_game_modulus"]) == int(config["validation_game_remainder"])]
    if not train or not validation:
        raise ValueError("game-level split produced empty partition")
    spec = RainbowSpec(**config["architecture"])
    online = DistributionalQNetwork(spec).to(device)
    initialization = initialize_from_policy_value(online, Path(config["base_checkpoint"]), config["base_checkpoint_hash"], device)
    if catalog_semantic_hash(catalog) != initialization["base_metadata"]["catalog_hash"]:
        raise ValueError("catalog differs from base checkpoint")
    target = copy.deepcopy(online).to(device).eval()
    optimizer = torch.optim.AdamW(online.parameters(), lr=float(config["learning_rate"]), weight_decay=float(config["weight_decay"]))
    priorities = torch.ones(len(train), dtype=torch.float64)
    rng = random.Random(int(config["seed"]))
    start = time.perf_counter(); history = []; best_score = math.inf; best_state = None; best_step = 0
    for step in range(1, int(config["gradient_steps"]) + 1):
        alpha = float(config["priority_alpha"])
        weights = priorities.pow(alpha); weights /= weights.sum()
        index = rng.choices(range(len(train)), weights=weights.tolist(), k=1)[0]
        online.train(); optimizer.zero_grad(set_to_none=True)
        transition = train[index]
        batch = encode_transition(transition, catalog, device)
        logits = online(batch["entities"], batch["mask"], batch["global"], batch["actions"], batch["action_mask"])[0, transition.action_index]
        with torch.no_grad():
            if transition.terminal:
                next_distribution = torch.zeros_like(online.support)
                next_distribution[(online.support - transition.reward).abs().argmin()] = 1.0
            else:
                online_next = online(batch["next_entities"], batch["next_mask"], batch["next_global"], batch["next_actions"], batch["next_action_mask"])
                best = online.expected_q(online_next)[0].argmax()
                target_next = target(batch["next_entities"], batch["next_mask"], batch["next_global"], batch["next_actions"], batch["next_action_mask"])
                next_distribution = torch.softmax(target_next[0, best], dim=-1)
            projected = project_distribution(next_distribution, transition.reward, transition.terminal, float(config["gamma"]), online.support)
        loss = -(projected * torch.log_softmax(logits, dim=-1)).sum()
        loss.backward(); nn.utils.clip_grad_norm_(online.parameters(), float(config["gradient_clip_norm"])); optimizer.step()
        with torch.no_grad():
            predicted_q = (torch.softmax(logits, dim=-1) * online.support).sum()
            target_q = (projected * online.support).sum()
            priorities[index] = max(float((predicted_q - target_q).abs().item()), float(config["priority_epsilon"]))
        if step % int(config["target_update_steps"]) == 0:
            target.load_state_dict(online.state_dict(), strict=True)
        if step % int(config["evaluation_interval_steps"]) == 0 or step == int(config["gradient_steps"]):
            metrics = evaluate(online, target, validation, catalog, float(config["gamma"]), device)
            history.append({"step": step, "validation": metrics})
            score = float(metrics["mean_cross_entropy"])
            if score < best_score:
                best_score, best_step = score, step
                best_state = copy.deepcopy({key: value.detach().cpu() for key, value in online.state_dict().items()})
    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    online.load_state_dict(best_state, strict=True); target.load_state_dict(best_state, strict=True)
    validation_metrics = evaluate(online, target, validation, catalog, float(config["gamma"]), device)
    args.out_dir.mkdir(parents=True, exist_ok=False)
    metadata = {
        "format": RAINBOW_CHECKPOINT_FORMAT, "version": 1, "model_id": config["model_id"],
        "architecture": asdict(spec), "value_order": "viewer_relative", "max_players": 2,
        "catalog_hash": catalog_semantic_hash(catalog), "base_checkpoint_hash": config["base_checkpoint_hash"],
        "self_play_hash": actual_hash,
        "training_config_hash": hashlib.sha256(b"effective-splendor-rainbow-training-config-v1\0" + canonical_json(config)).hexdigest(),
        "algorithm": "c51_double_dqn_prioritized_replay", "train_transitions": len(train), "validation_transitions": len(validation),
    }
    checkpoint_hash = rainbow_checkpoint_hash(metadata, best_state)
    checkpoint_path = args.out_dir / "checkpoint.pt"
    torch.save({"metadata": metadata, "state_dict": best_state}, checkpoint_path)
    report = {
        "format": "effective-splendor-rainbow-training-report", "version": 1,
        "training_id": config["training_id"], "model_id": config["model_id"],
        "algorithm": metadata["algorithm"], "device": str(device), "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda, "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "elapsed_seconds": time.perf_counter() - start, "checkpoint_hash": checkpoint_hash,
        "checkpoint_file_sha256": file_sha256(checkpoint_path), "best_step": best_step,
        "validation": validation_metrics, "priority_range": [float(priorities.min()), float(priorities.max())],
        "initialization": {"base_checkpoint_hash": config["base_checkpoint_hash"], "copied_tensor_count": len(initialization["copied_tensors"])},
        "history": history,
    }
    (args.out_dir / "training-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checkpoint": str(checkpoint_path), "checkpoint_hash": checkpoint_hash, "validation": validation_metrics}))


if __name__ == "__main__":
    main()
