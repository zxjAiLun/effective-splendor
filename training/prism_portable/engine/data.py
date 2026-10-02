"""Read-only ragged memmaps; provenance is never a network input."""

from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from .io import canonical_hash, read_json, sha256_file
from .model import ACTION_DIM, ACTION_SCHEMA, ENTITY_DIM, MAX_ACTIONS, MAX_ENTITIES, OBS_SCHEMA

ARRAYS = {
    "entities.f32": ("<f4", "entities", ENTITY_DIM),
    "entity_offsets.u64": ("<u8", "offsets", 1),
    "actions.f32": ("<f4", "actions", ACTION_DIM),
    "action_offsets.u64": ("<u8", "offsets", 1),
    "targets.i32": ("<i4", "actions", 1),
    "chosen.u32": ("<u4", "states", 1),
    "outcomes.f32": ("<f4", "states", 1),
}
FILES = set(ARRAYS) | {"rows.jsonl"}


def _positive_int(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("expected lowercase SHA-256")


def validate_manifest(manifest, expected_catalog_fingerprint=None):
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    for key, value in (("format", "prism-dataset-v1"), ("observation_schema", OBS_SCHEMA),
                       ("action_schema", ACTION_SCHEMA), ("entity_dim", ENTITY_DIM), ("action_dim", ACTION_DIM)):
        if manifest.get(key) != value:
            raise ValueError(f"dataset {key} mismatch")
    catalog = manifest.get("catalog_fingerprint")
    if not isinstance(catalog, str) or not catalog:
        raise ValueError("missing catalog fingerprint")
    if expected_catalog_fingerprint is not None and catalog != expected_catalog_fingerprint:
        raise ValueError("dataset catalog fingerprint mismatch")
    splits = manifest.get("splits")
    if not isinstance(splits, dict) or set(splits) != {"train", "val"}:
        raise ValueError("dataset requires train and val splits")
    for name, split in splits.items():
        if not isinstance(split, dict):
            raise ValueError("invalid split metadata")
        for key in ("games", "states", "entities", "actions"):
            _positive_int(split.get(key), f"{name}.{key}")
        if split["games"] > split["states"]:
            raise ValueError("games exceed states")
        hashes = split.get("hashes")
        if not isinstance(hashes, dict) or set(hashes) != FILES:
            raise ValueError("split hashes must cover all eight dataset files")
        for digest in hashes.values():
            _digest(digest)
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("missing dataset sources")
    counts = {name: [0, 0] for name in splits}
    seeds = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("invalid source")
        seed, split = source.get("seed"), source.get("split")
        if type(seed) is not int or seed < 0 or seed in seeds or split not in splits:
            raise ValueError("duplicate/invalid source seed or split")
        seeds.add(seed)
        if not isinstance(source.get("path"), str) or not source["path"]:
            raise ValueError("source path missing")
        _digest(source.get("sha256"))
        steps = _positive_int(source.get("steps"), "source.steps")
        counts[split][0] += 1
        counts[split][1] += steps
    for name, (games, states) in counts.items():
        if games != splits[name]["games"] or states != splits[name]["states"]:
            raise ValueError("source counts do not match splits")


class PrismDataset(Dataset):
    """Validates every numeric row in bounded chunks, then streams state slices.

    SHA verification is on by default. Disabling it does NOT disable structural,
    offset, label or finite-value checks (useful for targeted corruption tests).
    """

    def __init__(self, data_dir, split="train", *, expected_catalog_fingerprint=None, verify_hashes=True):
        self.root = Path(data_dir)
        self.manifest = read_json(self.root / "manifest.json")
        validate_manifest(self.manifest, expected_catalog_fingerprint)
        if split not in ("train", "val"):
            raise ValueError("unknown split")
        self.split = split
        self.meta = self.manifest["splits"][split]
        self.manifest_sha256 = sha256_file(self.root / "manifest.json")
        self.dataset_sha256 = canonical_hash({
            "manifest_sha256": self.manifest_sha256,
            "splits": {key: val["hashes"] for key, val in self.manifest["splits"].items()},
        })
        self.arrays = {}
        try:
            for name, (dtype, count, width) in ARRAYS.items():
                n = self.meta["states"] + 1 if count == "offsets" else self.meta[count]
                path = self.root / split / name
                expected_bytes = n * width * np.dtype(dtype).itemsize
                if not path.is_file() or path.stat().st_size != expected_bytes:
                    raise ValueError(f"{split}/{name}: wrong file size (expected {expected_bytes})")
                if verify_hashes and sha256_file(path) != self.meta["hashes"][name]:
                    raise ValueError(f"{split}/{name}: SHA-256 mismatch")
                shape = (n, width) if width != 1 else (n,)
                array = np.memmap(path, mode="r", dtype=dtype, shape=shape)
                self.arrays[name] = array
                setattr(self, name.split(".")[0], array)
            rows = self.root / split / "rows.jsonl"
            if verify_hashes and sha256_file(rows) != self.meta["hashes"]["rows.jsonl"]:
                raise ValueError(f"{split}/rows.jsonl: SHA-256 mismatch")
            with rows.open("rb") as stream:
                # Count only: JSON provenance is deliberately never deserialized.
                count = sum(1 for line in stream if line.strip())
            if count != len(self):
                raise ValueError("rows.jsonl count mismatch")
            self._validate_arrays()
        except BaseException:
            self.close()
            raise

    def _validate_arrays(self):
        for offsets, total, bound in ((self.entity_offsets, self.meta["entities"], MAX_ENTITIES),
                                      (self.action_offsets, self.meta["actions"], MAX_ACTIONS)):
            if int(offsets[0]) != 0 or int(offsets[-1]) != total:
                raise ValueError("offset endpoints mismatch")
            for start in range(0, len(self), 8192):
                part = offsets[start:min(start + 8192, len(self)) + 1]
                if (part[1:] <= part[:-1]).any():
                    raise ValueError("offsets must be strictly increasing")
                if ((part[1:] - part[:-1]) > bound).any():
                    raise ValueError("state exceeds entity/action bound")
        for array in (self.entities, self.actions):
            for start in range(0, len(array), 8192):
                if not np.isfinite(array[start:start + 8192]).all():
                    raise ValueError("nonfinite dataset feature")
        for start in range(0, len(self), 8192):
            outcomes = self.outcomes[start:start + 8192]
            if not np.isin(outcomes, (0.0, 0.5, 1.0)).all():
                raise ValueError("outcomes must be 0, 0.5 or 1")
            end = min(start + 8192, len(self))
            counts = self.action_offsets[start + 1:end + 1] - self.action_offsets[start:end]
            if (self.chosen[start:end] >= counts).any():
                raise ValueError("chosen action out of range")
        for index in range(len(self)):
            lo, hi = int(self.action_offsets[index]), int(self.action_offsets[index + 1])
            entity_count = int(self.entity_offsets[index + 1]) - int(self.entity_offsets[index])
            targets = self.targets[lo:hi]
            if targets.min() < -1 or targets.max() >= entity_count:
                raise ValueError(f"invalid target in state {index}")

    def __len__(self):
        return self.meta["states"]

    def __getitem__(self, index):
        index = int(index)
        if not 0 <= index < len(self):
            raise IndexError(index)
        elo, ehi = int(self.entity_offsets[index]), int(self.entity_offsets[index + 1])
        alo, ahi = int(self.action_offsets[index]), int(self.action_offsets[index + 1])
        return {"entities": self.entities[elo:ehi], "actions": self.actions[alo:ahi],
                "targets": self.targets[alo:ahi], "chosen": int(self.chosen[index]),
                "outcome": float(self.outcomes[index])}

    def close(self):
        for array in self.arrays.values():
            array._mmap.close()
        self.arrays.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _state_arrays(state):
    required = {"entities", "actions", "targets"}
    if not isinstance(state, dict) or not required.issubset(state) or set(state) - required - {"chosen", "outcome"}:
        raise ValueError("state has missing or unknown fields")
    try:
        entities = np.asarray(state["entities"])
        actions = np.asarray(state["actions"])
        targets = np.asarray(state["targets"])
        if entities.dtype.kind not in "iuf" or actions.dtype.kind not in "iuf":
            raise ValueError("features must be real numbers, not strings/bools/objects")
        with np.errstate(over="ignore", invalid="ignore"):
            entities = entities.astype(np.float32, copy=False)
            actions = actions.astype(np.float32, copy=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid state array") from exc
    if entities.ndim != 2 or entities.shape[1] != ENTITY_DIM or not 1 <= len(entities) <= MAX_ENTITIES:
        raise ValueError("invalid entities shape")
    if actions.ndim != 2 or actions.shape[1] != ACTION_DIM or not 1 <= len(actions) <= MAX_ACTIONS:
        raise ValueError("invalid actions shape")
    if targets.shape != (len(actions),) or targets.dtype.kind not in "iu":
        raise ValueError("invalid targets shape/dtype")
    if not np.isfinite(entities).all() or not np.isfinite(actions).all():
        raise ValueError("nonfinite state features")
    if (targets < -1).any() or (targets >= len(entities)).any():
        raise ValueError("invalid target index")
    return entities, actions, targets


def collate_states(states):
    """Pad one batch only; masks True=valid. Optional chosen/outcomes are labels."""
    if not states:
        raise ValueError("empty batch")
    rows = [_state_arrays(state) for state in states]
    labeled = "chosen" in states[0] and "outcome" in states[0]
    for state in states:
        if ("chosen" in state) != labeled or ("outcome" in state) != labeled:
            raise ValueError("mixed/missing labels")
    b, e, a = len(rows), max(len(row[0]) for row in rows), max(len(row[1]) for row in rows)
    batch = {"entities": torch.zeros((b, e, ENTITY_DIM), dtype=torch.float32),
             "actions": torch.zeros((b, a, ACTION_DIM), dtype=torch.float32),
             "targets": torch.full((b, a), -1, dtype=torch.int64),
             "entity_mask": torch.zeros((b, e), dtype=torch.bool),
             "action_mask": torch.zeros((b, a), dtype=torch.bool)}
    for i, (entities, actions, targets) in enumerate(rows):
        ne, na = len(entities), len(actions)
        # Explicit bounded copy avoids exposing read-only memmaps to writable torch tensors.
        batch["entities"][i, :ne] = torch.from_numpy(np.array(entities, copy=True))
        batch["actions"][i, :na] = torch.from_numpy(np.array(actions, copy=True))
        batch["targets"][i, :na] = torch.from_numpy(np.array(targets, dtype=np.int64, copy=True))
        batch["entity_mask"][i, :ne] = True
        batch["action_mask"][i, :na] = True
    if labeled:
        for state, (_, actions, _) in zip(states, rows):
            chosen, outcome = state["chosen"], state["outcome"]
            if not isinstance(chosen, (int, np.integer)) or isinstance(chosen, bool) or not 0 <= chosen < len(actions):
                raise ValueError("chosen action out of range")
            if not isinstance(outcome, (int, float, np.number)) or isinstance(outcome, bool) or outcome not in (0, 0.5, 1):
                raise ValueError("invalid outcome")
        batch["chosen"] = torch.tensor([state["chosen"] for state in states], dtype=torch.int64)
        batch["outcomes"] = torch.tensor([state["outcome"] for state in states], dtype=torch.float32)
    return batch


collate = collate_states
