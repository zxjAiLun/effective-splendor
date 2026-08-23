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
    replays: list[dict[str, Any]],
    training_dataset: dict[str, Any],
    search_targets: dict[str, Any],
    config: dict[str, Any],
    *,
    training_dataset_file_sha256: str | None = None,
    search_targets_file_sha256: str | None = None,
) -> dict[str, Any]:
    """
    Materialize M25 dataset by strictly joining verified M07 replays, TrainingDatasetV1
    player-view observations, and M15C SearchTeacherTargetSetV1 policy targets.
    
    Value targets are computed strictly from verified replay final terminal ranks (result.ranks),
    NOT M15C search values or Python recomputed score tie-breaks.
    """
    expected_generator = config.get("dataset", {}).get("generator_agent", "m07-determinization-champion")

    # 1. Validate search targets format & exact teacher config
    if search_targets.get("format") != M25_TEACHER_TARGETS_FORMAT:
        raise ValueError(f"fail-closed: unexpected search targets format: {search_targets.get('format')}")
    if int(search_targets.get("version", 0)) != M25_TEACHER_TARGETS_VERSION:
        raise ValueError(f"fail-closed: unexpected search targets version: {search_targets.get('version')}")
    
    t_cfg = search_targets.get("config", {})
    validate_teacher_targets_config(t_cfg)

    # 2. Strict index of replays by replay_document_hash
    replay_by_doc_hash: dict[str, dict[str, Any]] = {}
    seen_seeds = set()
    
    for g_idx, r in enumerate(replays):
        doc_hash = r.get("replay_document_hash") or r.get("document_hash")
        if not doc_hash:
            raise ValueError(f"fail-closed: replay index {g_idx} missing replay_document_hash")
        if doc_hash in replay_by_doc_hash:
            raise ValueError(f"fail-closed: duplicate replay_document_hash: {doc_hash}")
        
        header = r.get("header", {})
        seed = header.get("game_seed") if "game_seed" in header else r.get("seed")
        if seed is None:
            raise ValueError(f"fail-closed: replay {doc_hash} missing game_seed")
        if seed in seen_seeds:
            raise ValueError(f"fail-closed: duplicate game_seed across replays: {seed}")
        seen_seeds.add(seed)

        players = header.get("players")
        if players is None and "agents_by_seat" in r:
            players = [a.get("league_agent_id") for a in r["agents_by_seat"]]
        if players is None or len(players) != 2:
            raise ValueError(f"fail-closed: replay {doc_hash} missing or invalid players: {players}")
        if players[0] != expected_generator or players[1] != expected_generator:
            raise ValueError(f"fail-closed: replay {doc_hash} players {players} must both be {expected_generator!r}")

        result = r.get("result", {})
        ranks = result.get("ranks")
        if ranks is None or len(ranks) != 2:
            raise ValueError(f"fail-closed: replay {doc_hash} missing or invalid result.ranks: {ranks}")

        replay_by_doc_hash[doc_hash] = {
            "game_index": g_idx,
            "game_seed": int(seed),
            "replay_document_hash": doc_hash,
            "ranks": [int(ranks[0]), int(ranks[1])],
            "replay": r,
        }

    # 3. Strict index of search targets by (source_id, ply, actor)
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

    # 4. Materialize examples strictly
    examples_out = []
    seen_examples = set()
    matched_target_keys = set()

    for ex_idx, ex in enumerate(training_dataset.get("examples", [])):
        source_id = ex.get("source_id")
        doc_hash = ex.get("replay_document_hash")
        ex_game_idx = ex.get("game_index")
        ply = ex.get("ply")
        actor = ex.get("actor")
        
        if not source_id or not doc_hash or ex_game_idx is None or ply is None or actor is None:
            raise ValueError(f"fail-closed: example {ex_idx} missing core provenance fields (source_id={source_id}, doc_hash={doc_hash}, game_index={ex_game_idx}, ply={ply}, actor={actor})")

        key = (str(source_id), int(ply), int(actor))
        if key in seen_examples:
            raise ValueError(f"fail-closed: duplicate training example key: {key}")
        seen_examples.add(key)

        # Exact replay join
        if doc_hash not in replay_by_doc_hash:
            raise ValueError(f"fail-closed: example {key} references unknown replay_document_hash: {doc_hash}")
        r_info = replay_by_doc_hash[doc_hash]

        if int(ex_game_idx) != r_info["game_index"]:
            raise ValueError(f"fail-closed: example {key} game_index {ex_game_idx} disagrees with replay game_index {r_info['game_index']}")

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

    # Sort games by game_index
    games_out.sort(key=lambda g: g["game_index"])

    provenance_meta = {
        "source_replays_count": len(replays),
        "source_training_dataset_format": training_dataset.get("format"),
        "source_training_dataset_id": training_dataset.get("dataset_id"),
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
    parser.add_argument("--replays-dir", type=Path, help="Directory containing replay JSON files.")
    parser.add_argument("--training-dataset", type=Path, required=True, help="Path to TrainingDatasetV1 JSON.")
    parser.add_argument("--search-targets", type=Path, required=True, help="Path to SearchTeacherTargetSetV1 JSON.")
    parser.add_argument("--config", type=Path, required=True, help="Path to M25 config JSON.")
    parser.add_argument("--out", type=Path, required=True, help="Output path for materialized M25 dataset JSON.")
    args = parser.parse_args()

    if args.out.exists():
        raise FileExistsError(f"fail-closed: output dataset file already exists: {args.out}")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    training_ds_raw = args.training_dataset.read_text(encoding="utf-8")
    search_tgts_raw = args.search_targets.read_text(encoding="utf-8")
    
    training_ds = json.loads(training_ds_raw)
    search_tgts = json.loads(search_tgts_raw)

    td_sha = file_sha256(args.training_dataset)
    st_sha = file_sha256(args.search_targets)

    replays = []
    if args.replays_dir:
        for rf in sorted(args.replays_dir.glob("*.replay.json")):
            replays.append(json.loads(rf.read_text(encoding="utf-8")))
    elif "replays" in training_ds:
        replays = training_ds["replays"]
    else:
        raise ValueError("fail-closed: must provide --replays-dir or training-dataset with embedded replays")

    materialized = materialize_m25_dataset(
        replays=replays,
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
