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
            "players": ["m07-1", "m07-2"],
        },
        "result": {
            "scores": [15, 12],
            "card_counts": [10, 8],
        }
    }


@pytest.fixture
def dummy_training_dataset():
    return {
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
            }
        ]
    }


@pytest.fixture
def dummy_search_targets():
    return {
        "format": "effective-splendor-search-teacher-targets",
        "version": 1,
        "config": {
            "uniform_floor_micros": 100000,
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
                "value_target_by_player_micros": [750000, 250000],  # Search-shaped value target (must be ignored in favor of replay ranks)
            }
        ]
    }


def test_m25_dataset_hash_domain():
    """Assert M25 dataset semantic hash uses effective-splendor-m25-search-teacher-dataset-v1 domain."""
    payload = {"format": M25_DATASET_FORMAT, "version": 1}
    h = m25_dataset_hash(payload)
    assert isinstance(h, str) and len(h) == 64
    assert M25_DATASET_DOMAIN == b"effective-splendor-m25-search-teacher-dataset-v1\0"


def test_m25_dataset_materialize_and_terminal_ranks(dummy_replay, dummy_training_dataset, dummy_search_targets):
    """Verify materialize_m25_dataset binds M07 soft policy target and computes viewer-relative terminal outcome."""
    config = {
        "dataset": {
            "generator_agent": "m07-determinization-champion",
            "ruleset": "base_v1",
            "player_count": 2,
        }
    }
    ds = materialize_m25_dataset(
        replays=[dummy_replay],
        training_dataset=dummy_training_dataset,
        search_targets=dummy_search_targets,
        config=config,
    )
    
    assert ds["format"] == M25_DATASET_FORMAT
    assert ds["version"] == M25_DATASET_VERSION
    assert len(ds["examples"]) == 1
    
    ex = ds["examples"][0]
    assert ex["game_seed"] == 20260825
    assert ex["policy_target_micros"] == [800000, 200000]
    
    # Actor 0 won (15 vs 12) -> value target [1.0, 0.0] (NOT search value [0.75, 0.25])
    assert ex["value_target"] == [1.0, 0.0]


def test_m25_dataset_cache_build_and_load_roundtrip(tmp_path, catalog, dummy_replay, dummy_training_dataset, dummy_search_targets):
    """Assert build_m25_encoded_cache produces valid EncodedCache matching manifest and arrays."""
    config = {
        "dataset": {
            "generator_agent": "m07-determinization-champion",
            "ruleset": "base_v1",
            "player_count": 2,
        }
    }
    # Create sample with full observation for encoding
    real_ex = json.loads(Path("local-artifacts/m24-self-play-s2-v1/self-play.json").read_text(encoding="utf-8"))["examples"][0]
    dummy_training_dataset["examples"][0]["observation"] = real_ex["observation"]
    dummy_training_dataset["examples"][0]["legal_actions"] = real_ex["legal_actions"]
    
    # Update search target action targets to match legal actions
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
        config=config,
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
