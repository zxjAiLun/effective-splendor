"""Contract and provenance tests for M25 dataset materialization and encoded cache adapter against canonical TrainingDatasetV1 schema."""

import copy
import json
import math
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.encoded_cache import EncodedCache
from splendor_gpu.encoding import action_key
from splendor_gpu.train import file_sha256
from splendor_gpu.m25_dataset import (
    ALLOWED_M07_GENERATOR_IDS,
    CANONICAL_TRAINING_DATASET_FORMAT,
    CANONICAL_TRAINING_DATASET_VERSION,
    M25_DATASET_DOMAIN,
    M25_DATASET_FORMAT,
    M25_DATASET_VERSION,
    M25_UNIFORM_FLOOR_MICROS,
    M25Dataset,
    build_m25_encoded_cache,
    m25_dataset_hash,
    materialize_m25_dataset,
    validate_teacher_targets_config,
)

CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")


@pytest.fixture
def catalog():
    return load_catalog(CATALOG_PATH)


@pytest.fixture
def dummy_config():
    return {
        "dataset": {
            "games": 2,
            "seeds_count": 1,
            "rotations_per_seed": 2,
            "game_seeds": [20260825],
            "generator_agent": "m07-determinization-champion",
            "allowed_generator_agents": ["m07-bootstrap-a", "m07-bootstrap-b", "m07-determinization-champion"],
            "ruleset": "base_v1",
            "player_count": 2,
            "split": {
                "total_games": 2,
                "total_seeds": 1,
                "rotations_per_seed": 2,
                "validation": {
                    "seed_index_modulus": 4,
                    "seed_index_remainder": 0,
                    "seeds": 1,
                    "games": 2,
                },
                "train": {
                    "seeds": 0,
                    "games": 0,
                },
            },
        }
    }


@pytest.fixture
def dummy_training_dataset():
    """Canonical TrainingDatasetV1 fixture conforming strictly to Rust TrainingDatasetV1 schema (1 seed x 2 rotations = 2 games)."""
    return {
        "format": CANONICAL_TRAINING_DATASET_FORMAT,
        "version": CANONICAL_TRAINING_DATASET_VERSION,
        "dataset_id": "test-training-ds",
        "league_manifest_hash": "m" * 64,
        "evaluation_id": "test-eval",
        "evaluation_plan_hash": "p" * 64,
        "evaluation_report_hash": "r" * 64,
        "replays": [
            {
                "source_id": "match-000000",
                "evaluation_match_index": 0,
                "seed_index": 0,
                "rotation": 0,
                "arena_game_id": "game-000",
                "arena_report_hash": "a" * 64,
                "replay_document_hash": "doc_hash_1",
                "engine_version": "0.1.0",
                "ruleset_id": "splendor-base-v1",
                "ruleset_fingerprint": "f" * 64,
                "player_count": 2,
                "steps": 10,
                "final_state_hash": "s1" + "0" * 62,
                "result": {
                    "scores": [15, 12],
                    "ranks": [0, 1],
                    "winners": [0],
                    "reason": "prestige_threshold",
                },
                "agents_by_seat": [
                    {
                        "seat": 0,
                        "league_agent_id": "m07-bootstrap-a",
                        "policy_version": "m07-v1",
                        "model_version": None,
                        "runtime_name": "effective-splendor-determinization-agent-bootstrap-a-v1",
                        "runtime_version": "1",
                    },
                    {
                        "seat": 1,
                        "league_agent_id": "m07-bootstrap-b",
                        "policy_version": "m07-v1",
                        "model_version": None,
                        "runtime_name": "effective-splendor-determinization-agent-bootstrap-b-v1",
                        "runtime_version": "1",
                    },
                ],
            },
            {
                "source_id": "match-000001",
                "evaluation_match_index": 1,
                "seed_index": 0,
                "rotation": 1,
                "arena_game_id": "game-001",
                "arena_report_hash": "a" * 64,
                "replay_document_hash": "doc_hash_2",
                "engine_version": "0.1.0",
                "ruleset_id": "splendor-base-v1",
                "ruleset_fingerprint": "f" * 64,
                "player_count": 2,
                "steps": 12,
                "final_state_hash": "s2" + "0" * 62,
                "result": {
                    "scores": [10, 15],
                    "ranks": [1, 0],
                    "winners": [1],
                    "reason": "prestige_threshold",
                },
                "agents_by_seat": [
                    {
                        "seat": 0,
                        "league_agent_id": "m07-bootstrap-b",
                        "policy_version": "m07-v1",
                        "model_version": None,
                        "runtime_name": "effective-splendor-determinization-agent-bootstrap-b-v1",
                        "runtime_version": "1",
                    },
                    {
                        "seat": 1,
                        "league_agent_id": "m07-bootstrap-a",
                        "policy_version": "m07-v1",
                        "model_version": None,
                        "runtime_name": "effective-splendor-determinization-agent-bootstrap-a-v1",
                        "runtime_version": "1",
                    },
                ],
            },
        ],
        "examples": [
            {
                "source_id": "match-000000",
                "replay_document_hash": "doc_hash_1",
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h1",
                "visible_history_hash": "vis_h1",
                "information_set_hash": "info_h1",
                "observation": {"public": {}},
                "legal_actions": [
                    {"type": "take_tokens", "gems": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0}},
                    {"type": "pass"},
                ],
                "chosen_action": {"type": "pass"},
                "final_scores": [15, 12],
                "final_ranks": [0, 1],
            },
            {
                "source_id": "match-000001",
                "replay_document_hash": "doc_hash_2",
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h2",
                "visible_history_hash": "vis_h2",
                "information_set_hash": "info_h2",
                "observation": {"public": {}},
                "legal_actions": [
                    {"type": "take_tokens", "gems": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0}},
                    {"type": "pass"},
                ],
                "chosen_action": {"type": "pass"},
                "final_scores": [10, 15],
                "final_ranks": [1, 0],
            },
        ],
    }


@pytest.fixture
def dummy_search_targets():
    return {
        "format": "effective-splendor-search-teacher-targets",
        "version": 1,
        "dataset_id": "test-training-ds",
        "dataset_hash": "a" * 64,
        "league_manifest_hash": "m" * 64,
        "evaluation_plan_hash": "p" * 64,
        "evaluation_report_hash": "r" * 64,
        "config": {
            "search": {
                "sample_seed": 20260810,
                "sample_count": 4,
                "continuation_search": {
                    "max_depth_turns": 1,
                    "max_nodes": 2000,
                },
            },
            "uniform_floor_micros": 100000,
            "value_utility_scale": 15,
        },
        "targets": [
            {
                "source_id": "match-000000",
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h1",
                "information_set_hash": "info_h1",
                "action_targets": [
                    {"action": {"type": "take_tokens", "gems": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0}}, "policy_target_micros": 800000},
                    {"action": {"type": "pass"}, "policy_target_micros": 200000},
                ],
                "value_target_by_player_micros": [750000, 250000],
            },
            {
                "source_id": "match-000001",
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h2",
                "information_set_hash": "info_h2",
                "action_targets": [
                    {"action": {"type": "take_tokens", "gems": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0}}, "policy_target_micros": 600000},
                    {"action": {"type": "pass"}, "policy_target_micros": 400000},
                ],
                "value_target_by_player_micros": [250000, 750000],
            },
        ],
    }


def test_m25_dataset_hash_domain():
    """Assert M25 dataset semantic hash uses effective-splendor-m25-search-teacher-dataset-v1 domain."""
    payload = {"format": M25_DATASET_FORMAT, "version": 1}
    h = m25_dataset_hash(payload)
    assert isinstance(h, str) and len(h) == 64
    assert M25_DATASET_DOMAIN == b"effective-splendor-m25-search-teacher-dataset-v1\0"


def test_m25_exact_tie_produces_ones_for_both_players(dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-1 Check 1: Exact tie (ranks=[0, 0]) produces value_target=[1.0, 1.0] for both actors."""
    dummy_training_dataset["replays"][0]["result"]["ranks"] = [0, 0]
    dummy_training_dataset["examples"][0]["final_ranks"] = [0, 0]
    
    ds = materialize_m25_dataset(
        training_dataset=dummy_training_dataset,
        search_targets=dummy_search_targets,
        config=dummy_config,
    )
    assert ds["examples"][0]["value_target"] == [1.0, 1.0]
    assert ds["examples"][0]["game_index"] == 0
    assert ds["examples"][0]["seed_index"] == 0
    assert ds["examples"][0]["rotation"] == 0
    assert ds["examples"][0]["game_seed"] == 20260825


def test_m25_score_tie_engine_tiebreak_follows_ranks(dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-1 Check 2: Scores equal (15 vs 15) but engine ranks=[1, 0] (P1 won tiebreak) -> actor0 value is [0.0, 1.0]."""
    dummy_training_dataset["replays"][0]["result"]["scores"] = [15, 15]
    dummy_training_dataset["replays"][0]["result"]["ranks"] = [1, 0]
    dummy_training_dataset["examples"][0]["final_ranks"] = [1, 0]
    
    ds = materialize_m25_dataset(
        training_dataset=dummy_training_dataset,
        search_targets=dummy_search_targets,
        config=dummy_config,
    )
    assert ds["examples"][0]["value_target"] == [0.0, 1.0]


def test_m25_missing_seed_index_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Missing seed_index in replay fails closed."""
    dummy_training_dataset["replays"][0].pop("seed_index")
    with pytest.raises(ValueError, match="missing seed_index"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_missing_rotation_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Missing rotation in replay fails closed."""
    dummy_training_dataset["replays"][0].pop("rotation")
    with pytest.raises(ValueError, match="missing rotation"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_duplicate_rotation_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Duplicate rotation for the same seed_index fails closed."""
    dummy_training_dataset["replays"][1]["rotation"] = 0
    with pytest.raises(ValueError, match="duplicate rotation"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_non_m07_agents_by_seat_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Non-M07 agents_by_seat in canonical replay fails closed."""
    dummy_training_dataset["replays"][0]["agents_by_seat"][1]["league_agent_id"] = "heuristic-v1"
    with pytest.raises(ValueError, match="not in allowed generators"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_provenance_cross_binding_mismatch_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Cross-binding mismatch between TrainingDatasetV1 and SearchTeacherTargetSetV1 fails closed."""
    dummy_search_targets["evaluation_plan_hash"] = "wrong_plan_hash" * 4
    with pytest.raises(ValueError, match="provenance mismatch on evaluation_plan_hash"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_missing_replay_document_hash_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Missing replay_document_hash in example fails closed."""
    dummy_training_dataset["examples"][0].pop("replay_document_hash")
    with pytest.raises(ValueError, match="fail-closed: example 0 missing core provenance fields"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_unknown_replay_document_hash_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Example references unknown replay_document_hash fails closed."""
    dummy_training_dataset["examples"][0]["replay_document_hash"] = "unknown_doc_hash"
    with pytest.raises(ValueError, match="references unknown replay_document_hash"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_duplicate_teacher_target_key_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Duplicate (source_id, ply, actor) in teacher targets fails closed."""
    dummy_search_targets["targets"].append(dummy_search_targets["targets"][0])
    with pytest.raises(ValueError, match="duplicate search target key"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_teacher_config_drift_fails(dummy_training_dataset, dummy_search_targets, dummy_config):
    """Drift in teacher sample_count or max_nodes fails closed."""
    dummy_search_targets["config"]["search"]["sample_count"] = 8
    with pytest.raises(ValueError, match="teacher sample_count 8 != expected 4"):
        materialize_m25_dataset(
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_dataset_cache_build_and_load_roundtrip(tmp_path, catalog, dummy_training_dataset, dummy_search_targets, dummy_config):
    """Assert build_m25_encoded_cache produces valid EncodedCache matching manifest and arrays."""
    real_examples = json.loads(Path("local-artifacts/m24-self-play-s2-v1/self-play.json").read_text(encoding="utf-8"))["examples"]
    for idx in range(2):
        ex_template = real_examples[idx]
        dummy_training_dataset["examples"][idx]["observation"] = ex_template["observation"]
        dummy_training_dataset["examples"][idx]["legal_actions"] = ex_template["legal_actions"]
        
        n = len(ex_template["legal_actions"])
        base = 1_000_000 // n
        rem = 1_000_000 % n
        dummy_search_targets["targets"][idx]["action_targets"] = [
            {"action": a, "policy_target_micros": base + (1 if i < rem else 0)}
            for i, a in enumerate(ex_template["legal_actions"])
        ]
    
    ds = materialize_m25_dataset(
        training_dataset=dummy_training_dataset,
        search_targets=dummy_search_targets,
        config=dummy_config,
    )
    
    cache_dir = tmp_path / "cache_out"
    ds_file = tmp_path / "m25_ds.json"
    ds_file.write_text(json.dumps(ds), encoding="utf-8")
    
    ds_sha = file_sha256(ds_file)
    ds_sem_hash = m25_dataset_hash(ds)
    cat_hash = catalog_semantic_hash(catalog)
    
    manifest = build_m25_encoded_cache(
        examples=ds["examples"],
        catalog=catalog,
        output_dir=cache_dir,
        dataset_file_sha256=ds_sha,
        dataset_semantic_hash=ds_sem_hash,
        catalog_hash=cat_hash,
    )
    assert manifest["examples"] == 2
    
    cache = EncodedCache.load(cache_dir)
    cache.validate_identity(
        dataset_file_sha256=ds_sha,
        self_play_hash=ds_sem_hash,
        catalog_hash=cat_hash,
        examples=len(ds["examples"]),
    )
    assert cache.examples == 2
