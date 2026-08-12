"""M18A AlphaZero-like fine-tuning from neural-ISMCTS self-play targets."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from .agent import load_model
from .data import canonical_json, catalog_semantic_hash, load_catalog
from .encoding import EncodedObservation, action_key, encode_action, encode_observation
from .train import checkpoint_semantic_hash, file_sha256, resolve_device, seed_everything

SELF_PLAY_DOMAIN = b"effective-splendor-neural-self-play-v1\0"


def self_play_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        SELF_PLAY_DOMAIN
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def normalized_visits(example: dict[str, Any]) -> torch.Tensor:
    legal_keys = [action_key(action) for action in example["legal_actions"]]
    stats = {action_key(entry["action"]): int(entry["visits"]) for entry in example["action_stats"]}
    if set(stats) != set(legal_keys) or len(stats) != len(legal_keys):
        raise ValueError("action_stats must exactly bind legal_actions")
    visits = torch.tensor([stats[key] for key in legal_keys], dtype=torch.float32)
    if visits.sum() <= 0:
        return torch.full_like(visits, 1.0 / len(visits))
    return visits / visits.sum()


class SelfPlayDataset(Dataset):
    def __init__(self, examples: list[dict[str, Any]], catalog: dict[str, Any]):
        self.examples = examples
        self.catalog = catalog

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int):
        example = self.examples[index]
        observation: EncodedObservation = encode_observation(example["observation"], self.catalog)
        actor = int(example["actor"])
        ranks = example["final_ranks"]
        if len(ranks) != 2 or actor not in (0, 1):
            raise ValueError("M18A requires valid 1v1 terminal ranks")
        return {
            "entities": observation.entities,
            "entity_mask": observation.mask,
            "global_features": observation.global_features,
            "actions": torch.stack([encode_action(action) for action in example["legal_actions"]]),
            "policy_target": normalized_visits(example),
            "value_target": torch.tensor(
                [1.0 - float(ranks[actor]), 1.0 - float(ranks[1 - actor])],
                dtype=torch.float32,
            ),
        }


def collate(samples: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    max_actions = max(sample["actions"].shape[0] for sample in samples)
    width = samples[0]["actions"].shape[1]
    actions = torch.zeros((len(samples), max_actions, width), dtype=torch.float32)
    policy = torch.zeros((len(samples), max_actions), dtype=torch.float32)
    mask = torch.zeros((len(samples), max_actions), dtype=torch.bool)
    for row, sample in enumerate(samples):
        count = sample["actions"].shape[0]
        actions[row, :count] = sample["actions"]
        policy[row, :count] = sample["policy_target"]
        mask[row, :count] = True
    return {
        "entities": torch.stack([sample["entities"] for sample in samples]),
        "entity_mask": torch.stack([sample["entity_mask"] for sample in samples]),
        "global_features": torch.stack([sample["global_features"] for sample in samples]),
        "actions": actions,
        "action_mask": mask,
        "policy_target": policy,
        "value_target": torch.stack([sample["value_target"] for sample in samples]),
    }


def split_examples(payload: dict[str, Any], modulus: int, remainder: int):
    train, validation = [], []
    for example in payload["examples"]:
        target = validation if int(example["game_index"]) % modulus == remainder else train
        target.append(example)
    if not train or not validation:
        raise ValueError("game-level split produced an empty partition")
    return train, validation


def move(batch: dict[str, torch.Tensor], device: torch.device):
    return {key: value.to(device, non_blocking=device.type == "cuda") for key, value in batch.items()}


def policy_loss(logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    return -(targets * torch.log_softmax(logits, dim=-1)).sum(dim=-1).mean()


@torch.no_grad()
def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> dict[str, float | int]:
    model.eval()
    cross_entropy = value_mse = visit_top1 = model_top1 = examples = 0.0
    for raw in loader:
        batch = move(raw, device)
        logits, values = model(
            batch["entities"], batch["entity_mask"], batch["global_features"],
            batch["actions"], batch["action_mask"],
        )
        count = logits.shape[0]
        cross_entropy += (-(batch["policy_target"] * torch.log_softmax(logits, dim=-1)).sum(dim=-1)).sum().item()
        value_mse += nn.functional.mse_loss(values, batch["value_target"], reduction="sum").item()
        visit_top1 += batch["policy_target"].argmax(dim=-1).eq(logits.argmax(dim=-1)).sum().item()
        model_top1 += count
        examples += count
    return {
        "examples": int(examples),
        "policy_cross_entropy": cross_entropy / examples,
        "visit_top1": visit_top1 / model_top1,
        "value_mse": value_mse / (examples * 2.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-play", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.self_play.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if payload.get("format") != "effective-splendor-neural-self-play" or payload.get("version") != 1:
        raise ValueError("unsupported self-play dataset")
    if config.get("format") != "effective-splendor-self-play-training-config" or config.get("version") != 1:
        raise ValueError("unsupported M18A training config")
    actual_self_play_hash = self_play_hash(payload)
    if actual_self_play_hash != config["expected_self_play_hash"]:
        raise ValueError("self-play hash mismatch")
    if payload["checkpoint_hash"] != config["base_checkpoint_hash"]:
        raise ValueError("self-play was not generated by the frozen base checkpoint")
    device = resolve_device(config["device"])
    seed_everything(int(config["seed"]))
    catalog = load_catalog(args.catalog)
    model, base_metadata = load_model(Path(config["base_checkpoint"]), config["base_checkpoint_hash"], device)
    if catalog_semantic_hash(catalog) != base_metadata["catalog_hash"]:
        raise ValueError("catalog differs from base checkpoint")
    train_examples, validation_examples = split_examples(
        payload, int(config["validation_game_modulus"]), int(config["validation_game_remainder"])
    )
    train_set = SelfPlayDataset(train_examples, catalog)
    validation_set = SelfPlayDataset(validation_examples, catalog)
    generator = torch.Generator().manual_seed(int(config["seed"]))
    train_loader = DataLoader(train_set, batch_size=int(config["batch_size"]), shuffle=True, generator=generator, num_workers=0, collate_fn=collate, pin_memory=device.type == "cuda")
    validation_loader = DataLoader(validation_set, batch_size=int(config["batch_size"]), shuffle=False, num_workers=0, collate_fn=collate, pin_memory=device.type == "cuda")
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(config["learning_rate"]), weight_decay=float(config["weight_decay"]))
    start = time.perf_counter()
    best_score = math.inf
    best_epoch = 0
    best_state = None
    history = []
    for epoch in range(int(config["epochs"])):
        model.train()
        total = seen = 0.0
        for raw in train_loader:
            batch = move(raw, device)
            optimizer.zero_grad(set_to_none=True)
            logits, values = model(batch["entities"], batch["entity_mask"], batch["global_features"], batch["actions"], batch["action_mask"])
            p_loss = policy_loss(logits, batch["policy_target"])
            v_loss = nn.functional.mse_loss(values, batch["value_target"])
            loss = p_loss + float(config["value_loss_weight"]) * v_loss
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(config["gradient_clip_norm"]))
            optimizer.step()
            total += loss.item() * logits.shape[0]
            seen += logits.shape[0]
        validation = evaluate(model, validation_loader, device)
        score = float(validation["policy_cross_entropy"]) + float(config["value_loss_weight"]) * float(validation["value_mse"])
        history.append({"epoch": epoch + 1, "mean_loss": total / seen, "validation": validation, "selection_score": score})
        if score < best_score:
            best_score, best_epoch = score, epoch + 1
            best_state = copy.deepcopy({key: value.detach().cpu() for key, value in model.state_dict().items()})
    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    model.load_state_dict(best_state, strict=True)
    validation = evaluate(model, validation_loader, device)
    args.out_dir.mkdir(parents=True, exist_ok=False)
    metadata = {
        **base_metadata,
        "model_id": config["model_id"],
        "training_stage": "m18a_neural_ismcts_self_play_v1",
        "base_checkpoint_hash": config["base_checkpoint_hash"],
        "self_play_id": payload["self_play_id"],
        "self_play_hash": actual_self_play_hash,
        "self_play_config_hash": payload["config_hash"],
        "training_config_hash": hashlib.sha256(b"effective-splendor-self-play-training-config-v1\0" + canonical_json(config)).hexdigest(),
        "train_examples": len(train_set),
        "validation_examples": len(validation_set),
    }
    checkpoint_hash = checkpoint_semantic_hash(metadata, best_state)
    checkpoint_path = args.out_dir / "checkpoint.pt"
    torch.save({"metadata": metadata, "state_dict": best_state}, checkpoint_path)
    report = {
        "format": "effective-splendor-self-play-training-report",
        "version": 1,
        "training_id": config["training_id"],
        "model_id": config["model_id"],
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "elapsed_seconds": time.perf_counter() - start,
        "base_checkpoint_hash": config["base_checkpoint_hash"],
        "self_play_hash": actual_self_play_hash,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_file_sha256": file_sha256(checkpoint_path),
        "selection": {"best_epoch": best_epoch, "best_score": best_score},
        "validation": validation,
        "history": history,
    }
    (args.out_dir / "training-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checkpoint": str(checkpoint_path), "checkpoint_hash": checkpoint_hash, "validation": validation}))


if __name__ == "__main__":
    main()
