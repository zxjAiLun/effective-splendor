"""M25 M07 Search-Teacher Bootstrap Dataset Materializer, Validator, CLI, and Encoder Adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import torch
from torch.utils.data import Dataset

from splendor_gpu.data import (
    canonical_json,
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
CANONICAL_TRAINING_DATASET_FORMAT = "effective-splendor-training-dataset"
CANONICAL_TRAINING_DATASET_VERSION = 1
M25_TEACHER_TARGETS_FORMAT = "effective-splendor-search-teacher-targets"
M25_TEACHER_TARGETS_VERSION = 1
M25_UNIFORM_FLOOR_MICROS = 100000

EXPECTED_TEACHER_CONFIG = {
    "sample_seed": 20260810,
    "sample_count": 4,
    "max_depth_turns": 1,
    "max_nodes": 2000,
    "uniform_floor_micros": 100000,
}


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


def validate_teacher_targets_config(targets_config: dict[str, Any]) -> None:
    """Validate exact frozen M07 determinization search teacher configuration in target set."""
    search = targets_config.get("search", {})
    cont = search.get("continuation_search", {})
    
    seed = int(search.get("sample_seed", -1))
    count = int(search.get("sample_count", -1))
    depth = int(cont.get("max_depth_turns", -1))
    nodes = int(cont.get("max_nodes", -1))
    floor = int(targets_config.get("uniform_floor_micros", -1))
    
    if seed != EXPECTED_TEACHER_CONFIG["sample_seed"]:
        raise ValueError(f"teacher sample_seed {seed} != expected {EXPECTED_TEACHER_CONFIG['sample_seed']}")
    if count != EXPECTED_TEACHER_CONFIG["sample_count"]:
        raise ValueError(f"teacher sample_count {count} != expected {EXPECTED_TEACHER_CONFIG['sample_count']}")
    if depth != EXPECTED_TEACHER_CONFIG["max_depth_turns"]:
        raise ValueError(f"teacher max_depth_turns {depth} != expected {EXPECTED_TEACHER_CONFIG['max_depth_turns']}")
    if nodes != EXPECTED_TEACHER_CONFIG["max_nodes"]:
        raise ValueError(f"teacher max_nodes {nodes} != expected {EXPECTED_TEACHER_CONFIG['max_nodes']}")
    if floor != EXPECTED_TEACHER_CONFIG["uniform_floor_micros"]:
        raise ValueError(f"teacher uniform_floor_micros {floor} != expected {EXPECTED_TEACHER_CONFIG['uniform_floor_micros']}")


def materialize_m25_dataset(
    training_dataset: dict[str, Any],
    search_targets: dict[str, Any],
    config: dict[str, Any],
    *,
    replays: list[dict[str, Any]] | None = None,
    training_dataset_file_sha256: str | None = None,
    search_targets_file_sha256: str | None = None,
) -> dict[str, Any]:
    """
    Materialize M25 dataset by strictly joining canonical TrainingDatasetV1 (with embedded replays),
    and M15C SearchTeacherTargetSetV1 policy targets.
    
    Replay provenance, seed indices, and authoritative terminal ranks are extracted directly
    from TrainingDatasetV1.replays. Example game_index and game_seed are derived strictly from
    replay_document_hash -> seed_index -> config game_seeds.
    """
    expected_generator = config.get("dataset", {}).get("generator_agent", "m07-determinization-champion")
    expected_games = int(config.get("dataset", {}).get("games", 256))
    expected_seeds = config.get("dataset", {}).get("game_seeds", [])

    # 1. Validate training dataset format & version
    td_fmt = training_dataset.get("format")
    if td_fmt not in (CANONICAL_TRAINING_DATASET_FORMAT, "effective-splendor-training-dataset-v1"):
        raise ValueError(f"fail-closed: unexpected training dataset format: {td_fmt}")
    if int(training_dataset.get("version", 0)) != CANONICAL_TRAINING_DATASET_VERSION:
        raise ValueError(f"fail-closed: unexpected training dataset version: {training_dataset.get('version')}")

    # 2. Validate search targets format & exact teacher config
    if search_targets.get("format") != M25_TEACHER_TARGETS_FORMAT:
        raise ValueError(f"fail-closed: unexpected search targets format: {search_targets.get('format')}")
    if int(search_targets.get("version", 0)) != M25_TEACHER_TARGETS_VERSION:
        raise ValueError(f"fail-closed: unexpected search targets version: {search_targets.get('version')}")
    
    t_cfg = search_targets.get("config", {})
    validate_teacher_targets_config(t_cfg)

    # 3. Extract replays source (from training_dataset.replays or passed replays)
    raw_replays = replays if replays is not None else training_dataset.get("replays", [])
    if len(raw_replays) != expected_games:
        raise ValueError(f"fail-closed: replays count {len(raw_replays)} != expected {expected_games}")

    replay_by_doc_hash: dict[str, dict[str, Any]] = {}
    seen_seed_indices = set()

    for idx, r in enumerate(raw_replays):
        doc_hash = r.get("replay_document_hash") or r.get("document_hash")
        if not doc_hash:
            raise ValueError(f"fail-closed: replay index {idx} missing replay_document_hash")
        if doc_hash in replay_by_doc_hash:
            raise ValueError(f"fail-closed: duplicate replay_document_hash: {doc_hash}")

        # Extract seed_index
        seed_idx = r.get("seed_index")
        if seed_idx is None:
            # Fallback if raw replay header has game_seed matching config sequence
            header_seed = r.get("header", {}).get("game_seed") or r.get("seed")
            if header_seed is not None and header_seed in expected_seeds:
                seed_idx = expected_seeds.index(header_seed)
            else:
                raise ValueError(f"fail-closed: replay {doc_hash} missing seed_index")
        
        seed_idx = int(seed_idx)
        if seed_idx < 0 or seed_idx >= expected_games:
            raise ValueError(f"fail-closed: replay {doc_hash} seed_index {seed_idx} out of range 0..{expected_games-1}")
        if seed_idx in seen_seed_indices:
            raise ValueError(f"fail-closed: duplicate seed_index across replays: {seed_idx}")
        seen_seed_indices.add(seed_idx)

        game_seed = expected_seeds[seed_idx] if seed_idx < len(expected_seeds) else None
        if game_seed is None:
            raise ValueError(f"fail-closed: seed_index {seed_idx} not found in config game_seeds schedule")

        # Check players / agents_by_seat
        agents_by_seat = r.get("agents_by_seat")
        if agents_by_seat is not None:
            if len(agents_by_seat) != 2:
                raise ValueError(f"fail-closed: replay {doc_hash} agents_by_seat length {len(agents_by_seat)} != 2")
            p0 = agents_by_seat[0].get("league_agent_id")
            p1 = agents_by_seat[1].get("league_agent_id")
            if p0 != expected_generator or p1 != expected_generator:
                raise ValueError(f"fail-closed: replay {doc_hash} agents {p0}, {p1} must both be {expected_generator!r}")
        else:
            header_players = r.get("header", {}).get("players", [])
            if len(header_players) != 2 or header_players[0] != expected_generator or header_players[1] != expected_generator:
                raise ValueError(f"fail-closed: replay {doc_hash} header players {header_players} must both be {expected_generator!r}")

        # Check result ranks
        result = r.get("result", {})
        ranks = result.get("ranks")
        if ranks is None or len(ranks) != 2:
            raise ValueError(f"fail-closed: replay {doc_hash} missing or invalid result.ranks: {ranks}")

        replay_by_doc_hash[doc_hash] = {
            "game_index": seed_idx,
            "game_seed": game_seed,
            "replay_document_hash": doc_hash,
            "ranks": [int(ranks[0]), int(ranks[1])],
            "replay": r,
        }

    if len(seen_seed_indices) != expected_games:
        missing = set(range(expected_games)) - seen_seed_indices
        raise ValueError(f"fail-closed: missing {len(missing)} seed_indices (e.g. {sorted(list(missing))[:5]})")

    # 4. Strict index of search targets by (source_id, ply, actor)
    target_index: dict[tuple[str, int, int], dict[str, Any]] = {}
    for tgt in search_targets.get("targets", []):
        source_id = tgt.get("source_id")
        if not source_id:
            raise ValueError("fail-closed: search target missing source_id")
        ply = tgt.get("ply")
        actor = tgt.get("actor")
        if ply is None or actor is None:
            raise ValueError(f"fail-closed: search target {source_id} missing ply or actor")
            
        key = (str(source_id), int(ply), int(actor))
        if key in target_index:
            raise ValueError(f"fail-closed: duplicate search target key: {key}")
        target_index[key] = tgt

    # 5. Materialize examples strictly
    examples_out = []
    seen_examples = set()
    matched_target_keys = set()

    for ex_idx, ex in enumerate(training_dataset.get("examples", [])):
        source_id = ex.get("source_id")
        doc_hash = ex.get("replay_document_hash")
        ply = ex.get("ply")
        actor = ex.get("actor")
        
        if not source_id or not doc_hash or ply is None or actor is None:
            raise ValueError(f"fail-closed: example {ex_idx} missing core provenance fields (source_id={source_id}, doc_hash={doc_hash}, ply={ply}, actor={actor})")

        key = (str(source_id), int(ply), int(actor))
        if key in seen_examples:
            raise ValueError(f"fail-closed: duplicate training example key: {key}")
        seen_examples.add(key)

        # Exact replay join
        if doc_hash not in replay_by_doc_hash:
            raise ValueError(f"fail-closed: example {key} references unknown replay_document_hash: {doc_hash}")
        r_info = replay_by_doc_hash[doc_hash]

        # Exact search target join
        if key not in target_index:
            raise ValueError(f"fail-closed: missing search target for example: {key}")
        tgt = target_index[key]
        matched_target_keys.add(key)

        # Verify observation / info hashes match
        if ex.get("observation_hash") != tgt.get("observation_hash"):
            raise ValueError(f"fail-closed: observation_hash mismatch for example {key}: {ex.get('observation_hash')} != {tgt.get('observation_hash')}")
        if ex.get("information_set_hash") != tgt.get("information_set_hash"):
            raise ValueError(f"fail-closed: information_set_hash mismatch for example {key}: {ex.get('information_set_hash')} != {tgt.get('information_set_hash')}")

        # Verify legal actions match action_targets
        legal_acts = ex.get("legal_actions", [])
        act_targets = tgt.get("action_targets", [])
        if len(legal_acts) != len(act_targets) or len(legal_acts) == 0:
            raise ValueError(f"fail-closed: legal_actions count {len(legal_acts)} != action_targets count {len(act_targets)} for {key}")

        legal_keys = [action_key(a) for a in legal_acts]
        target_keys = [action_key(at["action"]) for at in act_targets]
        if legal_keys != target_keys:
            raise ValueError(f"fail-closed: legal_actions exact order/content mismatch for {key}")

        policy_micros = [int(at["policy_target_micros"]) for at in act_targets]
        if sum(policy_micros) != 1_000_000:
            raise ValueError(f"fail-closed: policy_target_micros sum {sum(policy_micros)} != 1000000 for {key}")

        # Compute viewer-relative terminal outcome value directly from authoritative replay result.ranks
        ranks = r_info["ranks"]
        if ex.get("final_ranks") is not None and list(ex["final_ranks"]) != ranks:
            raise ValueError(f"fail-closed: example {key} final_ranks {ex['final_ranks']} != replay ranks {ranks}")
            
        viewer_value = [1.0 - float(ranks[actor]), 1.0 - float(ranks[1 - actor])]

        examples_out.append({
            "game_index": r_info["game_index"],
            "game_seed": r_info["game_seed"],
            "source_id": str(source_id),
            "replay_document_hash": doc_hash,
            "ply": int(ply),
            "actor": int(actor),
            "observation": ex["observation"],
            "observation_hash": ex["observation_hash"],
            "information_set_hash": ex["information_set_hash"],
            "legal_actions": legal_acts,
            "policy_target_micros": policy_micros,
            "value_target": viewer_value,
        })

    # Ensure no unmatched search targets exist
    if len(matched_target_keys) != len(target_index):
        unmatched = set(target_index.keys()) - matched_target_keys
        raise ValueError(f"fail-closed: {len(unmatched)} unmatched search targets in input artifact (e.g. {next(iter(unmatched))})")

    games_out = [{
        "game_index": info["game_index"],
        "game_seed": info["game_seed"],
        "replay_document_hash": info["replay_document_hash"],
        "result": info["replay"]["result"],
        "replay": info["replay"],
    } for info in replay_by_doc_hash.values()]

    # Sort games strictly by game_index (0..255)
    games_out.sort(key=lambda g: g["game_index"])

    provenance_meta = {
        "source_replays_count": len(raw_replays),
        "source_training_dataset_format": training_dataset.get("format"),
        "source_training_dataset_id": training_dataset.get("dataset_id"),
        "source_training_dataset_league_manifest_hash": training_dataset.get("league_manifest_hash"),
        "source_training_dataset_evaluation_id": training_dataset.get("evaluation_id"),
        "source_training_dataset_evaluation_plan_hash": training_dataset.get("evaluation_plan_hash"),
        "source_training_dataset_evaluation_report_hash": training_dataset.get("evaluation_report_hash"),
        "source_search_targets_format": search_targets.get("format"),
        "source_search_targets_dataset_hash": search_targets.get("dataset_hash"),
        "teacher_config": t_cfg,
    }
    if training_dataset_file_sha256:
        provenance_meta["source_training_dataset_file_sha256"] = training_dataset_file_sha256
    if search_targets_file_sha256:
        provenance_meta["source_search_targets_file_sha256"] = search_targets_file_sha256

    return {
        "format": M25_DATASET_FORMAT,
        "version": M25_DATASET_VERSION,
        "milestone": "M25",
        "generator_agent": config["dataset"]["generator_agent"],
        "ruleset": config["dataset"]["ruleset"],
        "player_count": int(config["dataset"]["player_count"]),
        "provenance": provenance_meta,
        "games": games_out,
        "examples": examples_out,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize M25 Search-Teacher Dataset.")
    parser.add_argument("--training-dataset", type=Path, required=True, help="Path to canonical TrainingDatasetV1 JSON.")
    parser.add_argument("--search-targets", type=Path, required=True, help="Path to SearchTeacherTargetSetV1 JSON.")
    parser.add_argument("--config", type=Path, required=True, help="Path to M25 config JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Output path for materialized M25 dataset JSON.")
    args = parser.parse_args()

    if args.out.exists():
        raise FileExistsError(f"fail-closed: output dataset file already exists: {args.out}")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    training_ds = json.loads(args.training_dataset.read_text(encoding="utf-8"))
    search_tgts = json.loads(args.search_targets.read_text(encoding="utf-8"))

    td_sha = file_sha256(args.training_dataset)
    st_sha = file_sha256(args.search_targets)

    materialized = materialize_m25_dataset(
        training_dataset=training_ds,
        search_targets=search_tgts,
        config=config,
        training_dataset_file_sha256=td_sha,
        search_targets_file_sha256=st_sha,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(materialized, indent=2) + "\n", encoding="utf-8")
    
    out_sha = file_sha256(args.out)
    out_sem_hash = m25_dataset_hash(materialized)
    print(f"Materialized M25 dataset to {args.out}")
    print(f"  Examples: {len(materialized['examples'])}")
    print(f"  Games:    {len(materialized['games'])}")
    print(f"  File SHA256:     {out_sha}")
    print(f"  Semantic Hash:   {out_sem_hash}")


if __name__ == "__main__":
    main()
