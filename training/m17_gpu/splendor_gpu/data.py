"""Provenance checks, source split, and padded legal-action batches."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset

from .encoding import ACTION_FEATURES, EncodedObservation, action_key, encode_action, encode_observation

DATASET_DOMAIN = b"effective-splendor-training-dataset-v1\0"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def dataset_hash(dataset: dict[str, Any]) -> str:
    return hashlib.sha256(DATASET_DOMAIN + canonical_json(dataset)).hexdigest()


def load_catalog(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    source = raw.get("catalog", raw)
    cards, nobles = source.get("cards"), source.get("nobles")
    if not isinstance(cards, list) or len(cards) != 90 or not isinstance(nobles, list) or len(nobles) != 10:
        raise ValueError("catalog must contain exactly 90 cards and 10 nobles")
    return {"cards": {int(item["id"]): item for item in cards}, "nobles": {int(item["id"]): item for item in nobles}}


def catalog_semantic_hash(catalog: dict[str, Any]) -> str:
    normalized = {
        "cards": [catalog["cards"][key] for key in sorted(catalog["cards"])],
        "nobles": [catalog["nobles"][key] for key in sorted(catalog["nobles"])],
    }
    return hashlib.sha256(b"effective-splendor-gpu-catalog-v1\0" + canonical_json(normalized)).hexdigest()


@dataclass(frozen=True)
class Sample:
    observation: EncodedObservation
    actions: torch.Tensor
    chosen_index: int
    value_target: torch.Tensor
    source_id: str


class SplendorDataset(Dataset[Sample]):
    def __init__(self, examples: list[dict[str, Any]], catalog: dict[str, Any]):
        self.examples = examples
        self.catalog = catalog

    def __len__(self) -> int: return len(self.examples)

    def __getitem__(self, index: int) -> Sample:
        example = self.examples[index]
        observation = encode_observation(example["observation"], self.catalog)
        actions = torch.stack([encode_action(action) for action in example["legal_actions"]])
        chosen = action_key(example["chosen_action"])
        keys = [action_key(action) for action in example["legal_actions"]]
        if keys.count(chosen) != 1:
            raise ValueError("chosen_action must occur exactly once in legal_actions")
        ranks = example["final_ranks"]
        if len(ranks) != 2:
            raise ValueError("M17 v1 requires 1v1 rank targets")
        actor = int(example["actor"])
        target = torch.tensor(
            [1.0 - float(ranks[actor]), 1.0 - float(ranks[1 - actor])],
            dtype=torch.float32,
        )
        return Sample(observation, actions, keys.index(chosen), target, example["source_id"])


def collate(samples: list[Sample]) -> dict[str, torch.Tensor]:
    max_actions = max(sample.actions.shape[0] for sample in samples)
    action_batch = torch.zeros((len(samples), max_actions, ACTION_FEATURES), dtype=torch.float32)
    action_mask = torch.zeros((len(samples), max_actions), dtype=torch.bool)
    for row, sample in enumerate(samples):
        count = sample.actions.shape[0]
        action_batch[row, :count] = sample.actions
        action_mask[row, :count] = True
    return {
        "entities": torch.stack([s.observation.entities for s in samples]),
        "entity_mask": torch.stack([s.observation.mask for s in samples]),
        "global_features": torch.stack([s.observation.global_features for s in samples]),
        "actions": action_batch,
        "action_mask": action_mask,
        "chosen": torch.tensor([s.chosen_index for s in samples], dtype=torch.long),
        "value_target": torch.stack([s.value_target for s in samples]),
    }


def split_examples(dataset: dict[str, Any], teacher_ids: set[str], modulus: int, remainder: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    replay_agents = {replay["source_id"]: {int(a["seat"]): a["league_agent_id"] for a in replay["agents_by_seat"]} for replay in dataset["replays"]}
    replay_seeds = {replay["source_id"]: int(replay["seed_index"]) for replay in dataset["replays"]}
    selected = [example for example in dataset["examples"] if replay_agents[example["source_id"]][int(example["actor"])] in teacher_ids]
    train, validation = [], []
    for example in selected:
        bucket = replay_seeds[example["source_id"]] % modulus
        (validation if bucket == remainder else train).append(example)
    if not train or not validation:
        raise ValueError("source-level split produced an empty partition")
    return train, validation
