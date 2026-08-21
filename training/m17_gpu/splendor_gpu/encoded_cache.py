"""Packed, memory-mapped M28B input cache.

The cache is a runtime artifact, not a second scientific dataset.  It stores
the exact tensors emitted by :class:`SelfPlayDataset` so the trainer can avoid
re-encoding JSON observations and legal actions on every epoch.  A manifest
binds the source file, semantic self-play identity, catalog identity, encoder
contract, tensor dimensions, and every binary array hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import torch
from torch.utils.data import Dataset

from .encoding import ACTION_FEATURES, ENTITY_FEATURES, ENTITY_SLOTS, GLOBAL_FEATURES
from .self_play_train import SelfPlayDataset


CACHE_FORMAT = "effective-splendor-m28b-encoded-cache"
CACHE_VERSION = 1
ENCODER_CONTRACT = "effective-splendor-m17-player-view-encoding-v1"
MANIFEST_NAME = "manifest.json"

EXPECTED_ARRAYS: dict[str, tuple[str, torch.dtype]] = {
    "entities": ("entities.bin", torch.float32),
    "entity_masks": ("entity_masks.bin", torch.bool),
    "global_features": ("global_features.bin", torch.float32),
    "value_targets": ("value_targets.bin", torch.float32),
    "actions": ("actions.bin", torch.float32),
    "policy_targets": ("policy_targets.bin", torch.float32),
    "action_offsets": ("action_offsets.bin", torch.int64),
}

EXPECTED_SHAPES = {
    "entities": ("examples", ENTITY_SLOTS, ENTITY_FEATURES),
    "entity_masks": ("examples", ENTITY_SLOTS),
    "global_features": ("examples", GLOBAL_FEATURES),
    "value_targets": ("examples", 2),
    "actions": ("total_actions", ACTION_FEATURES),
    "policy_targets": ("total_actions",),
    "action_offsets": ("examples_plus_one",),
}


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dtype_name(dtype: torch.dtype) -> str:
    names = {
        torch.float32: "float32",
        torch.bool: "bool",
        torch.int64: "int64",
    }
    try:
        return names[dtype]
    except KeyError as exc:
        raise ValueError(f"unsupported cache dtype: {dtype}") from exc


def _dtype_from_name(name: str) -> torch.dtype:
    names = {"float32": torch.float32, "bool": torch.bool, "int64": torch.int64}
    try:
        return names[name]
    except KeyError as exc:
        raise ValueError(f"unsupported cache manifest dtype: {name}") from exc


def _numel(shape: Sequence[int]) -> int:
    result = 1
    for value in shape:
        result *= int(value)
    return result


def _manifest_digest(manifest: dict[str, Any]) -> str:
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def _resolve_shape(symbolic_shape: Sequence[str | int], examples: int, total_actions: int) -> tuple[int, ...]:
    symbols = {
        "examples": examples,
        "examples_plus_one": examples + 1,
        "total_actions": total_actions,
    }
    result: list[int] = []
    for value in symbolic_shape:
        if isinstance(value, str):
            if value not in symbols:
                raise ValueError(f"unknown cache shape symbol: {value}")
            result.append(symbols[value])
        else:
            result.append(int(value))
    return tuple(result)


class EncodedCache:
    """Read-only view of a validated memory-mapped tensor cache."""

    def __init__(self, root: Path, manifest: dict[str, Any], arrays: dict[str, torch.Tensor]):
        self.root = root
        self.manifest = manifest
        self.manifest_sha256 = str(manifest["manifest_sha256"])
        self.examples = int(manifest["examples"])
        self.total_actions = int(manifest["total_actions"])
        self.arrays = arrays

    @classmethod
    def load(cls, root: Path) -> "EncodedCache":
        root = root.resolve()
        manifest_path = root / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != CACHE_FORMAT or manifest.get("version") != CACHE_VERSION:
            raise ValueError("unsupported encoded cache format")
        claimed_digest = manifest.get("manifest_sha256")
        if not isinstance(claimed_digest, str) or _manifest_digest(manifest) != claimed_digest:
            raise ValueError("encoded cache manifest digest mismatch")
        examples = int(manifest["examples"])
        total_actions = int(manifest["total_actions"])
        arrays: dict[str, torch.Tensor] = {}
        array_manifest = manifest.get("arrays")
        if not isinstance(array_manifest, dict) or set(array_manifest) != set(EXPECTED_ARRAYS):
            raise ValueError("encoded cache array manifest is incomplete")
        for name, (expected_filename, expected_dtype) in EXPECTED_ARRAYS.items():
            entry = array_manifest[name]
            if not isinstance(entry, dict):
                raise ValueError(f"invalid encoded cache array entry: {name}")
            filename = entry.get("filename")
            if filename != expected_filename:
                raise ValueError(f"encoded cache filename mismatch for {name}")
            dtype = _dtype_from_name(str(entry.get("dtype")))
            if dtype != expected_dtype:
                raise ValueError(f"encoded cache dtype mismatch for {name}")
            shape = tuple(int(value) for value in entry.get("shape", []))
            expected_shape = _resolve_shape(EXPECTED_SHAPES[name], examples, total_actions)
            if shape != expected_shape:
                raise ValueError(f"encoded cache shape mismatch for {name}: {shape} != {expected_shape}")
            path = root / filename
            expected_bytes = _numel(shape) * torch.tensor([], dtype=dtype).element_size()
            if not path.is_file() or path.stat().st_size != expected_bytes:
                raise ValueError(f"encoded cache byte-size mismatch for {name}")
            if entry.get("sha256") != _sha256_file(path):
                raise ValueError(f"encoded cache content digest mismatch for {name}")
            arrays[name] = torch.from_file(
                str(path),
                shared=False,
                size=_numel(shape),
                dtype=dtype,
            ).reshape(shape)
        offsets = arrays["action_offsets"]
        if offsets[0].item() != 0 or offsets[-1].item() != total_actions:
            raise ValueError("encoded cache action offsets do not cover the packed action array")
        if bool(torch.any(offsets[1:] < offsets[:-1])):
            raise ValueError("encoded cache action offsets are not monotonic")
        return cls(root, manifest, arrays)

    def sample(self, index: int) -> dict[str, torch.Tensor]:
        if index < 0 or index >= self.examples:
            raise IndexError(index)
        start = int(self.arrays["action_offsets"][index].item())
        end = int(self.arrays["action_offsets"][index + 1].item())
        return {
            "entities": self.arrays["entities"][index],
            "entity_mask": self.arrays["entity_masks"][index],
            "global_features": self.arrays["global_features"][index],
            "actions": self.arrays["actions"][start:end],
            "policy_target": self.arrays["policy_targets"][start:end],
            "value_target": self.arrays["value_targets"][index],
        }

    def validate_identity(
        self,
        *,
        dataset_file_sha256: str,
        self_play_hash: str,
        catalog_hash: str,
        examples: int,
    ) -> None:
        source = self.manifest.get("source")
        expected_source = {
            "dataset_file_sha256": dataset_file_sha256,
            "self_play_hash": self_play_hash,
            "catalog_semantic_hash": catalog_hash,
        }
        if source != expected_source:
            raise ValueError(f"encoded cache source identity mismatch: expected {expected_source!r}, got {source!r}")
        if self.examples != examples:
            raise ValueError(f"encoded cache example count mismatch: {self.examples} != {examples}")
        if self.manifest.get("encoder_contract") != ENCODER_CONTRACT:
            raise ValueError("encoded cache encoder contract mismatch")
        if self.manifest.get("dimensions") != {
            "entity_slots": ENTITY_SLOTS,
            "entity_features": ENTITY_FEATURES,
            "global_features": GLOBAL_FEATURES,
            "action_features": ACTION_FEATURES,
        }:
            raise ValueError("encoded cache feature dimensions mismatch")


class PackedEncodedDataset(Dataset):
    """Dataset view selecting examples from a shared :class:`EncodedCache`."""

    def __init__(self, cache: EncodedCache, indices: Sequence[int]):
        self.cache = cache
        self.indices = tuple(int(index) for index in indices)
        if any(index < 0 or index >= cache.examples for index in self.indices):
            raise ValueError("encoded dataset index is outside cache")

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        return self.cache.sample(self.indices[index])


def collate_packed(samples: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    """Collate packed samples into a continuous 1D action batch without max-action padding."""
    entities = torch.stack([s["entities"] for s in samples])
    entity_mask = torch.stack([s["entity_mask"] for s in samples])
    global_features = torch.stack([s["global_features"] for s in samples])
    value_target = torch.stack([s["value_target"] for s in samples])

    actions_list = [s["actions"] for s in samples]
    policy_list = [s["policy_target"] for s in samples]
    actions = torch.cat(actions_list, dim=0)
    policy_target = torch.cat(policy_list, dim=0)

    counts = [a.shape[0] for a in actions_list]
    offsets = torch.zeros(len(samples) + 1, dtype=torch.int64)
    offsets[1:] = torch.tensor(counts, dtype=torch.int64).cumsum(dim=0)

    return {
        "entities": entities,
        "entity_mask": entity_mask,
        "global_features": global_features,
        "actions": actions,
        "action_offsets": offsets,
        "policy_target": policy_target,
        "value_target": value_target,
    }


def _create_mapped_tensor(root: Path, name: str, shape: Sequence[int]) -> torch.Tensor:
    filename, dtype = EXPECTED_ARRAYS[name]
    return torch.from_file(
        str(root / filename),
        shared=True,
        size=_numel(shape),
        dtype=dtype,
    ).reshape(tuple(int(value) for value in shape))


def build_encoded_cache(
    examples: Sequence[dict[str, Any]],
    catalog: dict[str, Any],
    output_dir: Path,
    *,
    dataset_file_sha256: str,
    self_play_hash: str,
    catalog_hash: str,
) -> dict[str, Any]:
    """Encode each example once and write a new packed cache directory."""

    if output_dir.exists():
        raise FileExistsError(f"encoded cache output already exists: {output_dir}")
    if not examples:
        raise ValueError("cannot build an empty encoded cache")
    output_dir.mkdir(parents=True)
    action_counts = [len(example.get("legal_actions", [])) for example in examples]
    if any(count <= 0 for count in action_counts):
        raise ValueError("every example must contain at least one legal action")
    total_actions = sum(action_counts)
    examples_count = len(examples)
    shapes = {
        name: _resolve_shape(symbolic_shape, examples_count, total_actions)
        for name, symbolic_shape in EXPECTED_SHAPES.items()
    }
    mapped = {name: _create_mapped_tensor(output_dir, name, shape) for name, shape in shapes.items()}
    offsets = mapped["action_offsets"]
    offsets[0] = 0
    cursor = 0
    online = SelfPlayDataset(list(examples), catalog)
    for index, action_count in enumerate(action_counts):
        sample = online[index]
        mapped["entities"][index].copy_(sample["entities"])
        mapped["entity_masks"][index].copy_(sample["entity_mask"])
        mapped["global_features"][index].copy_(sample["global_features"])
        mapped["value_targets"][index].copy_(sample["value_target"])
        mapped["actions"][cursor : cursor + action_count].copy_(sample["actions"])
        mapped["policy_targets"][cursor : cursor + action_count].copy_(sample["policy_target"])
        cursor += action_count
        offsets[index + 1] = cursor
    if cursor != total_actions:
        raise RuntimeError("encoded cache action cursor mismatch")
    del mapped, offsets, online

    manifest: dict[str, Any] = {
        "format": CACHE_FORMAT,
        "version": CACHE_VERSION,
        "encoder_contract": ENCODER_CONTRACT,
        "examples": examples_count,
        "total_actions": total_actions,
        "source": {
            "dataset_file_sha256": dataset_file_sha256,
            "self_play_hash": self_play_hash,
            "catalog_semantic_hash": catalog_hash,
        },
        "dimensions": {
            "entity_slots": ENTITY_SLOTS,
            "entity_features": ENTITY_FEATURES,
            "global_features": GLOBAL_FEATURES,
            "action_features": ACTION_FEATURES,
        },
        "arrays": {},
    }
    for name, (filename, dtype) in EXPECTED_ARRAYS.items():
        shape = shapes[name]
        path = output_dir / filename
        manifest["arrays"][name] = {
            "filename": filename,
            "dtype": _dtype_name(dtype),
            "shape": list(shape),
            "sha256": _sha256_file(path),
        }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_cache_exact(
    cache: EncodedCache,
    examples: Sequence[dict[str, Any]],
    catalog: dict[str, Any],
    *,
    progress_every: int = 0,
) -> int:
    """Compare every packed sample with a fresh online encoding, bit-for-bit."""

    if len(examples) != cache.examples:
        raise ValueError("online/cache example count mismatch")
    online = SelfPlayDataset(list(examples), catalog)
    fields = ("entities", "entity_mask", "global_features", "actions", "policy_target", "value_target")
    for index in range(len(examples)):
        expected = online[index]
        actual = cache.sample(index)
        for field in fields:
            if not torch.equal(expected[field], actual[field]):
                raise ValueError(f"online/cache exact equality failed at example {index}, field {field}")
        if progress_every and (index + 1) % progress_every == 0:
            print(f"exact cache equality: {index + 1}/{len(examples)}")
    return len(examples)


def cache_manifest_sha256(cache_dir: Path) -> str:
    manifest = json.loads((cache_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    claimed = manifest.get("manifest_sha256")
    if not isinstance(claimed, str) or _manifest_digest(manifest) != claimed:
        raise ValueError("encoded cache manifest digest mismatch")
    return claimed
