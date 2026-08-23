"""Contract and provenance tests for M25 dataset materialization and encoded cache adapter."""

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
def dummy_replay():
    return {
        "replay_document_hash": "doc_hash_1",
        "header": {
            "game_seed": 20260825,
            "players": ["m07-determinization-champion", "m07-determinization-champion"],
        },
        "result": {
            "scores": [15, 12],
            "ranks": [0, 1],
            "winners": [0],
            "reason": "points_threshold",
        },
    }


@pytest.fixture
def dummy_training_dataset():
    return {
        "format": "effective-splendor-training-dataset-v1",
        "version": 1,
        "dataset_id": "test-training-ds",
        "examples": [
            {
                "source_id": "match-000000",
                "replay_document_hash": "doc_hash_1",
                "game_index": 0,
                "ply": 0,
                "actor": 0,
                "observation": {"public": {}},
                "observation_hash": "obs_h1",
                "information_set_hash": "info_h1",
                "legal_actions": [
                    {"type": "take_tokens", "gems": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0}},
                    {"type": "pass"},
                ],
                "final_ranks": [0, 1],
            }
        ],
    }


@pytest.fixture
def dummy_search_targets():
    return {
        "format": "effective-splendor-search-teacher-targets",
        "version": 1,
        "dataset_hash": "a" * 64,
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
            }
        ],
    }


@pytest.fixture
def dummy_config():
    return {
        "dataset": {
            "generator_agent": "m07-determinization-champion",
            "ruleset": "base_v1",
            "player_count": 2,
        }
    }


def test_m25_dataset_hash_domain():
    """Assert M25 dataset semantic hash uses effective-splendor-m25-search-teacher-dataset-v1 domain."""
    payload = {"format": M25_DATASET_FORMAT, "version": 1}
    h = m25_dataset_hash(payload)
    assert isinstance(h, str) and len(h) == 64
    assert M25_DATASET_DOMAIN == b"effective-splendor-m25-search-teacher-dataset-v1\0"


def test_m25_exact_tie_produces_ones_for_both_players(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-1 Check 1: Exact tie (ranks=[0, 0]) produces value_target=[1.0, 1.0] for both actors."""
    dummy_replay["result"]["ranks"] = [0, 0]
    dummy_training_dataset["examples"][0]["final_ranks"] = [0, 0]
    
    ds = materialize_m25_dataset(
        replays=[dummy_replay],
        training_dataset=dummy_training_dataset,
        search_targets=dummy_search_targets,
        config=dummy_config,
    )
    assert ds["examples"][0]["value_target"] == [1.0, 1.0]

    # Actor 1 view also produces [1.0, 1.0]
    dummy_training_dataset["examples"][0]["actor"] = 1
    dummy_search_targets["targets"][0]["actor"] = 1
    ds1 = materialize_m25_dataset(
        replays=[dummy_replay],
        training_dataset=dummy_training_dataset,
        search_targets=dummy_search_targets,
        config=dummy_config,
    )
    assert ds1["examples"][0]["value_target"] == [1.0, 1.0]


def test_m25_score_tie_engine_tiebreak_follows_ranks(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-1 Check 2: Scores equal (15 vs 15) but engine ranks=[1, 0] (P1 won tiebreak) -> actor0 value is [0.0, 1.0]."""
    dummy_replay["result"]["scores"] = [15, 15]
    dummy_replay["result"]["ranks"] = [1, 0]
    dummy_training_dataset["examples"][0]["final_ranks"] = [1, 0]
    
    ds = materialize_m25_dataset(
        replays=[dummy_replay],
        training_dataset=dummy_training_dataset,
        search_targets=dummy_search_targets,
        config=dummy_config,
    )
    # Actor 0 lost: [1 - 1, 1 - 0] = [0.0, 1.0]
    assert ds["examples"][0]["value_target"] == [0.0, 1.0]


def test_m25_missing_replay_document_hash_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-2 Check 3: Missing replay_document_hash in example fails closed."""
    dummy_training_dataset["examples"][0].pop("replay_document_hash")
    with pytest.raises(ValueError, match="fail-closed: example 0 missing core provenance fields"):
        materialize_m25_dataset(
            replays=[dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_missing_game_index_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """Repair 3A: Missing game_index in example fails closed."""
    dummy_training_dataset["examples"][0].pop("game_index")
    with pytest.raises(ValueError, match="missing core provenance fields.*game_index"):
        materialize_m25_dataset(
            replays=[dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_non_m07_replay_seat_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """Repair 3A: Replay with non-M07 player seat fails closed."""
    dummy_replay["header"]["players"] = ["m07-determinization-champion", "heuristic-v1"]
    with pytest.raises(ValueError, match="must both be 'm07-determinization-champion'"):
        materialize_m25_dataset(
            replays=[dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_unknown_replay_document_hash_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-2 Check 4: Example references unknown replay_document_hash fails closed."""
    dummy_training_dataset["examples"][0]["replay_document_hash"] = "unknown_doc_hash"
    with pytest.raises(ValueError, match="references unknown replay_document_hash"):
        materialize_m25_dataset(
            replays=[dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_replay_hash_game_index_disagreement_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-2 Check 5: Disagreement between example game_index and replay index fails closed."""
    dummy_training_dataset["examples"][0]["game_index"] = 99
    with pytest.raises(ValueError, match="disagrees with replay game_index"):
        materialize_m25_dataset(
            replays=[dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_duplicate_replay_identity_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-2 Check 6: Duplicate replay_document_hash across replays fails closed."""
    with pytest.raises(ValueError, match="duplicate replay_document_hash"):
        materialize_m25_dataset(
            replays=[dummy_replay, dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_duplicate_teacher_target_key_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-2 Check 7: Duplicate (source_id, ply, actor) in teacher targets fails closed."""
    dummy_search_targets["targets"].append(dummy_search_targets["targets"][0])
    with pytest.raises(ValueError, match="duplicate search target key"):
        materialize_m25_dataset(
            replays=[dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_teacher_config_drift_fails(dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """P1-3 Check 8: Drift in teacher sample_count or max_nodes fails closed."""
    # Drift sample_count
    dummy_search_targets["config"]["search"]["sample_count"] = 8
    with pytest.raises(ValueError, match="teacher sample_count 8 != expected 4"):
        materialize_m25_dataset(
            replays=[dummy_replay],
            training_dataset=dummy_training_dataset,
            search_targets=dummy_search_targets,
            config=dummy_config,
        )


def test_m25_dataset_cache_build_and_load_roundtrip(tmp_path, catalog, dummy_replay, dummy_training_dataset, dummy_search_targets, dummy_config):
    """Assert build_m25_encoded_cache produces valid EncodedCache matching manifest and arrays."""
    real_ex = json.loads(Path("local-artifacts/m24-self-play-s2-v1/self-play.json").read_text(encoding="utf-8"))["examples"][0]
    dummy_training_dataset["examples"][0]["observation"] = real_ex["observation"]
    dummy_training_dataset["examples"][0]["legal_actions"] = real_ex["legal_actions"]
    
    n = len(real_ex["legal_actions"])
    base = 1_000_000 // n
    rem = 1_000_000 % n
    dummy_search_targets["targets"][0]["action_targets"] = [
        {"action": a, "policy_target_micros": base + (1 if i < rem else 0)}
        for i, a in enumerate(real_ex["legal_actions"])
    ]
    
    ds = materialize_m25_dataset(
        replays=[dummy_replay],
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
    assert manifest["examples"] == 1
    
    cache = EncodedCache.load(cache_dir)
    cache.validate_identity(
        dataset_file_sha256=ds_sha,
        self_play_hash=ds_sem_hash,
        catalog_hash=cat_hash,
        examples=len(ds["examples"]),
    )
    assert cache.examples == 1
