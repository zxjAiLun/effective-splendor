"""M25 M07 Search-Teacher Bootstrap Dataset Materializer, Validator, and Encoder Adapter."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import torch
from torch.utils.data import Dataset

from splendor_gpu.data import (
    catalog_semantic_hash,
    load_catalog,
)
from splendor_gpu.encoded_cache import (
    CACHE_FORMAT,
    CACHE_VERSION,
    ENCODER_CONTRACT,
    ENTITY_FEATURES,
    ENTITY_SLOTS,
    GLOBAL_FEATURES,
    ACTION_FEATURES,
    EXPECTED_ARRAYS,
    EXPECTED_SHAPES,
    MANIFEST_NAME,
    EncodedCache,
    _create_mapped_tensor,
    _dtype_name,
    _manifest_digest,
    _resolve_shape,
    _sha256_file,
)
from splendor_gpu.encoding import EncodedObservation, action_key, encode_action, encode_observation
from splendor_gpu.train import file_sha256

M25_DATASET_FORMAT = "effective-splendor-search-teacher-dataset-v1"
M25_DATASET_VERSION = 1
M25_DATASET_DOMAIN = b"effective-splendor-m25-search-teacher-dataset-v1\0"
M25_TEACHER_TARGETS_FORMAT = "effective-splendor-search-teacher-targets"
M25_TEACHER_TARGETS_VERSION = 1
M25_UNIFORM_FLOOR_MICROS = 100000


def m25_dataset_hash(payload: dict[str, Any]) -> str:
    """Authoritative semantic hash for M25 search-teacher dataset."""
    return hashlib.sha256(
        M25_DATASET_DOMAIN + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


class M25Dataset(Dataset):
    """PyTorch Dataset wrapping materialized M25 search-teacher examples."""

    def __init__(self, examples: list[dict[str, Any]], catalog: dict[str, Any]):
        self.examples = examples
        self.catalog = catalog

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        example = self.examples[index]
        obs_enc: EncodedObservation = encode_observation(example["observation"], self.catalog)
        
        # Policy target from soft search target micros
        micros = example.get("policy_target_micros")
        if micros is None:
            if "policy_target" in example:
                policy_target = torch.tensor(example["policy_target"], dtype=torch.float32)
            else:
                raise ValueError(f"example {index} missing policy_target_micros")
        else:
            micros_tensor = torch.tensor(micros, dtype=torch.float32)
            s = micros_tensor.sum()
            if s <= 0:
                raise ValueError(f"example {index} policy_target_micros sum is non-positive: {s}")
            policy_target = micros_tensor / s

        # Value target: viewer-relative terminal outcome
        v_target = example.get("value_target")
        if v_target is None:
            raise ValueError(f"example {index} missing value_target")
        value_tensor = torch.tensor(v_target, dtype=torch.float32)
        if value_tensor.shape != (2,):
            raise ValueError(f"example {index} value_target must have shape (2,), got {value_tensor.shape}")

        legal_acts = example["legal_actions"]
        if len(legal_acts) == 0:
            raise ValueError(f"example {index} has zero legal actions")
        if len(policy_target) != len(legal_acts):
            raise ValueError(f"example {index} policy_target length {len(policy_target)} != legal_actions count {len(legal_acts)}")

        return {
            "entities": obs_enc.entities,
            "entity_mask": obs_enc.mask,
            "global_features": obs_enc.global_features,
            "actions": torch.stack([encode_action(a) for a in legal_acts]),
            "policy_target": policy_target,
            "value_target": value_tensor,
        }


def build_m25_encoded_cache(
    examples: Sequence[dict[str, Any]],
    catalog: dict[str, Any],
    output_dir: Path,
    *,
    dataset_file_sha256: str,
    dataset_semantic_hash: str,
    catalog_hash: str,
) -> dict[str, Any]:
    """Encode each M25 search-teacher example and write a new packed cache directory."""
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
    online = M25Dataset(list(examples), catalog)
    
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
            "self_play_hash": dataset_semantic_hash,
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


def materialize_m25_dataset(
    replays: list[dict[str, Any]],
    training_dataset: dict[str, Any],
    search_targets: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Materialize M25 dataset by joining verified M07 replays, TrainingDatasetV1 player-view
    observations, and M15C SearchTeacherTargetSetV1 policy targets.
    
    Value targets are computed strictly from verified replay final terminal ranks, NOT M15C search values.
    """
    # 1. Validate search targets header
    if search_targets.get("format") != M25_TEACHER_TARGETS_FORMAT:
        raise ValueError(f"unexpected search targets format: {search_targets.get('format')}")
    if int(search_targets.get("version", 0)) != M25_TEACHER_TARGETS_VERSION:
        raise ValueError(f"unexpected search targets version: {search_targets.get('version')}")
    
    t_cfg = search_targets.get("config", {})
    floor = int(t_cfg.get("uniform_floor_micros", -1))
    if floor != M25_UNIFORM_FLOOR_MICROS:
        raise ValueError(f"search targets uniform_floor_micros {floor} != expected {M25_UNIFORM_FLOOR_MICROS}")

    # 2. Index replays and final ranks
    replay_by_doc_hash = {}
    replay_by_game_idx = {}
    for g_idx, r in enumerate(replays):
        doc_hash = r.get("replay_document_hash") or r.get("document_hash")
        # Calculate terminal ranks from final state/events
        players = r["header"]["players"]
        if len(players) != 2:
            raise ValueError("M25 requires 2-player games")
        final_scores = r["result"]["scores"]
        # Winner is rank 0, loser rank 1
        p0_score, p1_score = final_scores[0], final_scores[1]
        if p0_score > p1_score:
            ranks = [0, 1]
        elif p1_score > p0_score:
            ranks = [1, 0]
        else:
            # tie break on card count
            p0_cards = r["result"].get("card_counts", [0, 0])[0]
            p1_cards = r["result"].get("card_counts", [0, 0])[1]
            ranks = [0, 1] if p0_cards <= p1_cards else [1, 0]
        
        info = {"replay": r, "ranks": ranks, "game_index": g_idx, "seed": r["header"].get("game_seed")}
        if doc_hash:
            replay_by_doc_hash[doc_hash] = info
        replay_by_game_idx[g_idx] = info

    # 3. Index search targets by (source_id, ply, actor)
    target_index = {}
    for tgt in search_targets.get("targets", []):
        key = (str(tgt["source_id"]), int(tgt["ply"]), int(tgt["actor"]))
        if key in target_index:
            raise ValueError(f"duplicate target key: {key}")
        target_index[key] = tgt

    # 4. Materialize examples
    examples_out = []
    seen_examples = set()
    
    for ex in training_dataset.get("examples", []):
        source_id = str(ex["source_id"])
        ply = int(ex["ply"])
        actor = int(ex["actor"])
        key = (source_id, ply, actor)
        if key in seen_examples:
            raise ValueError(f"duplicate training example key: {key}")
        seen_examples.add(key)

        if key not in target_index:
            raise ValueError(f"missing search target for example: {key}")
        tgt = target_index[key]

        # Verify observation / info hashes match
        if ex.get("observation_hash") != tgt.get("observation_hash"):
            raise ValueError(f"observation_hash mismatch for example {key}")
        if ex.get("information_set_hash") != tgt.get("information_set_hash"):
            raise ValueError(f"information_set_hash mismatch for example {key}")

        # Verify legal actions match action_targets
        legal_acts = ex["legal_actions"]
        act_targets = tgt["action_targets"]
        if len(legal_acts) != len(act_targets):
            raise ValueError(f"legal_actions count {len(legal_acts)} != action_targets count {len(act_targets)} for {key}")

        legal_keys = [action_key(a) for a in legal_acts]
        target_keys = [action_key(at["action"]) for at in act_targets]
        if legal_keys != target_keys:
            raise ValueError(f"legal_actions order mismatch for {key}")

        policy_micros = [int(at["policy_target_micros"]) for at in act_targets]
        if sum(policy_micros) != 1_000_000:
            raise ValueError(f"policy_target_micros sum {sum(policy_micros)} != 1000000 for {key}")

        # Find terminal outcome from replay
        doc_hash = ex.get("replay_document_hash")
        if doc_hash and doc_hash in replay_by_doc_hash:
            r_info = replay_by_doc_hash[doc_hash]
        else:
            game_idx = int(ex.get("game_index", 0))
            r_info = replay_by_game_idx[game_idx]
            
        ranks = r_info["ranks"]
        # Viewer-relative terminal value target: [1.0, 0.0] if actor won, [0.0, 1.0] if actor lost
        viewer_value = [1.0 - float(ranks[actor]), 1.0 - float(ranks[1 - actor])]

        examples_out.append({
            "game_index": r_info["game_index"],
            "game_seed": r_info["seed"],
            "source_id": source_id,
            "ply": ply,
            "actor": actor,
            "observation": ex["observation"],
            "observation_hash": ex["observation_hash"],
            "information_set_hash": ex["information_set_hash"],
            "legal_actions": legal_acts,
            "policy_target_micros": policy_micros,
            "value_target": viewer_value,
        })

    games_out = [{
        "game_index": info["game_index"],
        "game_seed": info["seed"],
        "replay": info["replay"],
    } for info in replay_by_game_idx.values()]

    return {
        "format": M25_DATASET_FORMAT,
        "version": M25_DATASET_VERSION,
        "milestone": "M25",
        "generator_agent": config["dataset"]["generator_agent"],
        "ruleset": config["dataset"]["ruleset"],
        "player_count": int(config["dataset"]["player_count"]),
        "games": games_out,
        "examples": examples_out,
    }
