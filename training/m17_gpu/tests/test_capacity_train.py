import inspect
import json
from pathlib import Path

import pytest
import torch

from splendor_gpu import capacity_train
from splendor_gpu.capacity_train import (
    EXPECTED_MODELS,
    build_checkpoint_metadata,
    build_fresh_model,
    parameter_count,
    split_m28a_examples,
    validate_config,
    validate_dataset,
)
from splendor_gpu.data import catalog_semantic_hash, load_catalog


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "benchmarks/m28a-entity-mixer-width-v1.config.json"
DATASET_PATH = ROOT / "local-artifacts/m24-self-play-s2-v1/self-play.json"
CATALOG_PATH = ROOT / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def test_m28a_config_accepts_exact_two_model_specs():
    frozen = config()
    validate_config(frozen)
    assert frozen["models"] == list(EXPECTED_MODELS)


@pytest.mark.parametrize("model_contract, expected", [(EXPECTED_MODELS[0], 949060), (EXPECTED_MODELS[1], 2605764)])
def test_m28a_entity_mixer_parameter_counts_are_exact(model_contract, expected):
    model = build_fresh_model(model_contract, 280129)
    assert parameter_count(model) == expected


def test_wrong_dataset_semantic_hash_is_rejected():
    frozen = config()
    frozen["dataset"]["self_play_hash"] = "0" * 64
    with pytest.raises(ValueError, match="self-play semantic hash mismatch"):
        validate_dataset(DATASET_PATH, frozen)


def test_wrong_dataset_file_sha_is_rejected():
    frozen = config()
    frozen["dataset"]["file_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="dataset file SHA-256 mismatch"):
        validate_dataset(DATASET_PATH, frozen)


def test_fresh_trainer_does_not_load_a_base_checkpoint(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("M28A fresh trainer attempted to load a checkpoint")

    monkeypatch.setattr("splendor_gpu.agent.load_model", fail_if_called)
    monkeypatch.setattr("splendor_gpu.self_play_train.load_model", fail_if_called)
    model = build_fresh_model(EXPECTED_MODELS[0], 280129)
    assert parameter_count(model) == 949060
    assert "load_model" not in inspect.getsource(capacity_train.train_one)


def test_same_seed_reproduces_fresh_initialization():
    first = build_fresh_model(EXPECTED_MODELS[0], 280129)
    second = build_fresh_model(EXPECTED_MODELS[0], 280129)
    assert all(torch.equal(first.state_dict()[key], second.state_dict()[key]) for key in first.state_dict())


def test_validation_split_is_game_level_and_s1_reference_stays_out_of_train():
    frozen = config()
    validate_config(frozen)
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    train, validation, reference = split_m28a_examples(payload, frozen)
    train_games = {int(example["game_index"]) for example in train}
    validation_games = {int(example["game_index"]) for example in validation}
    reference_games = {int(example["game_index"]) for example in reference}
    assert train_games.isdisjoint(validation_games)
    assert all(game % 4 != 0 for game in train_games)
    assert all(game % 4 == 0 for game in validation_games)
    assert reference_games
    assert reference_games <= set(range(0, 128, 4))
    assert not any(int(example["game_index"]) < 128 and int(example["game_index"]) % 4 == 0 for example in train)


def test_checkpoint_metadata_contains_m28a_provenance():
    frozen = config()
    catalog = load_catalog(CATALOG_PATH)
    model = build_fresh_model(EXPECTED_MODELS[1], 280129)
    metadata = build_checkpoint_metadata(
        model,
        EXPECTED_MODELS[1],
        frozen,
        catalog,
        frozen["dataset"]["self_play_hash"],
        frozen["dataset"]["file_sha256"],
        23654,
        7851,
        1953,
    )
    assert metadata["format"] == "effective-splendor-gpu-checkpoint"
    assert metadata["version"] == 1
    assert metadata["training_stage"] == "m28a_entity_mixer_width_scaling_v1"
    assert metadata["initialization"] == "fresh"
    assert metadata["model_role"] == "candidate"
    assert metadata["source_self_play_hash"] == frozen["dataset"]["self_play_hash"]
    assert metadata["source_self_play_file_sha256"] == frozen["dataset"]["file_sha256"]
    assert metadata["dataset_generator_checkpoint_hash"] == frozen["dataset"]["generator_checkpoint_hash"]
    assert metadata["train_examples"] == 23654
    assert metadata["validation_examples"] == 7851
    assert metadata["s1_reference_examples"] == 1953
    assert metadata["catalog_hash"] == catalog_semantic_hash(catalog)
