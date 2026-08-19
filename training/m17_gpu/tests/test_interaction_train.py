import inspect
import json
from pathlib import Path

import pytest
import torch

from splendor_gpu import interaction_train
from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.model import ModelSpec
from splendor_gpu.train import checkpoint_semantic_hash


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "benchmarks/m28b-contextual-entity-interaction-v1.config.json"
DATASET_PATH = ROOT / "local-artifacts/m24-self-play-s2-v1/self-play.json"
CATALOG_PATH = ROOT / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def test_m28b_config_and_models_match_the_frozen_contract():
    frozen = config()
    interaction_train.validate_config(frozen)
    assert frozen["models"] == list(interaction_train.EXPECTED_MODELS)
    assert frozen["training_authorization"] == "NOT_AUTHORIZED"
    assert frozen["arena_authorization"] == "NOT_AUTHORIZED"
    assert frozen["interaction"]["standard_multi_head_attention"] is False
    assert frozen["interaction"]["transformer_encoder"] is False


def test_m28b_parameter_counts_are_exact():
    for model_contract in interaction_train.EXPECTED_MODELS:
        model = interaction_train.build_fresh_model(model_contract, 280229)
        assert interaction_train.parameter_count(model) == model_contract["expected_parameter_count"]


def test_wrong_dataset_identity_is_rejected():
    frozen = config()
    frozen["dataset"]["self_play_hash"] = "0" * 64
    with pytest.raises(ValueError, match="self-play semantic hash mismatch"):
        interaction_train.validate_dataset(DATASET_PATH, frozen)


def test_validation_split_is_game_level_and_s1_reference_stays_out_of_train():
    frozen = config()
    interaction_train.validate_config(frozen)
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    train, validation, reference = interaction_train.split_m28b_examples(payload, frozen)
    train_games = {int(example["game_index"]) for example in train}
    validation_games = {int(example["game_index"]) for example in validation}
    reference_games = {int(example["game_index"]) for example in reference}
    assert train_games.isdisjoint(validation_games)
    assert all(game % 4 != 0 for game in train_games)
    assert all(game % 4 == 0 for game in validation_games)
    assert reference_games <= set(range(0, 128, 4))


def test_fresh_trainer_never_loads_inherited_weights(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("M28B fresh trainer attempted to load a checkpoint")

    monkeypatch.setattr("splendor_gpu.agent.load_model", fail_if_called)
    monkeypatch.setattr("splendor_gpu.self_play_train.load_model", fail_if_called)
    assert "load_model" not in inspect.getsource(interaction_train.train_one)
    model = interaction_train.build_fresh_model(interaction_train.EXPECTED_MODELS[1], 280229)
    assert interaction_train.parameter_count(model) == 1689798


def test_checkpoint_metadata_binds_interaction_and_dataset_provenance():
    frozen = config()
    catalog = load_catalog(CATALOG_PATH)
    model = interaction_train.build_fresh_model(interaction_train.EXPECTED_MODELS[1], 280229)
    metadata = interaction_train.build_checkpoint_metadata(
        model,
        interaction_train.EXPECTED_MODELS[1],
        frozen,
        catalog,
        frozen["dataset"]["self_play_hash"],
        frozen["dataset"]["file_sha256"],
        23654,
        7851,
        1953,
    )
    assert metadata["training_stage"] == "m28b_contextual_entity_interaction_v1"
    assert metadata["initialization"] == "fresh"
    assert metadata["initialization_seed"] == 280229
    assert metadata["model_role"] == "candidate"
    assert metadata["parameter_count"] == 1689798
    assert metadata["source_self_play_hash"] == frozen["dataset"]["self_play_hash"]
    assert metadata["source_self_play_file_sha256"] == frozen["dataset"]["file_sha256"]
    assert metadata["catalog_hash"] == catalog_semantic_hash(catalog)
    assert metadata["interaction_contract"] == frozen["interaction"]


def test_offline_comparison_applies_frozen_gates_without_authorizing_arena():
    frozen = config()
    control = {
        "validation": {"policy_cross_entropy": 1.0, "value_mse": 1.0, "visit_top1": 0.50},
        "s1_reference": {"policy_cross_entropy": 1.0, "value_mse": 1.0, "visit_top1": 0.50},
    }
    candidate = {
        "validation": {"policy_cross_entropy": 0.99, "value_mse": 0.98, "visit_top1": 0.50},
        "s1_reference": {"policy_cross_entropy": 1.009, "value_mse": 1.0, "visit_top1": 0.495},
    }
    comparison = interaction_train.offline_comparison(control, candidate, frozen)
    assert comparison["G1_full_s2_validation"]["pass"] is True
    assert comparison["G2_s1_reference_non_regression"]["pass"] is True
    assert comparison["decision"] == "M28B_ARENA_ELIGIBLE"
    assert comparison["arena_authorization"] == "NOT_AUTHORIZED"

    candidate["validation"]["policy_cross_entropy"] = 1.02
    assert interaction_train.offline_comparison(control, candidate, frozen)["decision"] == "M28B_OFFLINE_NO_INTERACTION_SIGNAL"
