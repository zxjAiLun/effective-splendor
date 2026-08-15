import json
from pathlib import Path

import pytest
import torch

from splendor_gpu.data import collate, dataset_hash, load_catalog
from splendor_gpu.encoding import ACTION_FEATURES, ENTITY_FEATURES, ENTITY_SLOTS, GLOBAL_FEATURES, EncodedObservation, encode_action, encode_observation
from splendor_gpu.model import ModelSpec, build_model
from splendor_gpu.agent import load_model
from splendor_gpu.train import checkpoint_semantic_hash
from splendor_gpu.self_play_train import normalized_visits, self_play_hash
from splendor_gpu.rainbow import DistributionalQNetwork, RainbowSpec, project_distribution

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"


def fixture(): return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_encodes_rust_trace_player_view_and_legal_actions():
    trace = fixture(); frame = trace["frames"][0]; catalog = load_catalog(FIXTURE)
    observation = encode_observation(frame["player_view"], catalog)
    assert observation.entities.shape == (ENTITY_SLOTS, ENTITY_FEATURES)
    assert observation.mask.dtype == torch.bool
    assert observation.global_features.shape == (GLOBAL_FEATURES,)
    assert all(encode_action(action).shape == (ACTION_FEATURES,) for action in frame["legal_actions"])


@pytest.mark.parametrize("architecture", ["flat_resmlp", "entity_mixer"])
def test_models_mask_padded_actions_and_return_two_player_values(architecture):
    model = build_model(ModelSpec(architecture, 64, 2))
    entities = torch.randn(2, ENTITY_SLOTS, ENTITY_FEATURES)
    entity_mask = torch.ones(2, ENTITY_SLOTS, dtype=torch.bool)
    globals_ = torch.randn(2, GLOBAL_FEATURES)
    actions = torch.randn(2, 7, ACTION_FEATURES)
    action_mask = torch.tensor([[1,1,1,0,0,0,0],[1,1,1,1,1,1,1]], dtype=torch.bool)
    logits, values = model(entities, entity_mask, globals_, actions, action_mask)
    assert logits.shape == (2, 7) and values.shape == (2, 2)
    assert torch.isneginf(logits[0, 3:]).all() or (logits[0, 3:] < -1e20).all()
    assert values.min() >= 0 and values.max() <= 1


def test_dataset_domain_hash_matches_rust_contract():
    dataset = json.loads((ROOT / "local-artifacts/m15b-teacher-data-v2/dataset.json").read_text(encoding="utf-8"))
    assert dataset_hash(dataset) == "3f8adcd4e8e6ec224a029085a817f87a06fb450d08dbd37cca05d488f1d29c24"


def test_player_view_encoder_rejects_non_1v1():
    trace = fixture(); observation = trace["frames"][0]["player_view"]; observation["public"]["player_count"] = 3
    with pytest.raises(ValueError, match="1v1"): encode_observation(observation, load_catalog(FIXTURE))


def test_checkpoint_contract_is_viewer_relative():
    model = build_model(ModelSpec("entity_mixer", 64, 1))
    assert model.checkpoint_metadata()["value_order"] == "viewer_relative"


def test_checkpoint_file_hash_is_enforced_before_load(tmp_path):
    model = build_model(ModelSpec("entity_mixer", 32, 1))
    path = tmp_path / "checkpoint.pt"
    torch.save({"metadata": {"format": "effective-splendor-gpu-checkpoint", "version": 1, "model_id": "unit", **model.checkpoint_metadata()}, "state_dict": model.state_dict()}, path)
    with pytest.raises(ValueError, match="hash mismatch"):
        load_model(path, "0" * 64, torch.device("cpu"))


def test_semantic_checkpoint_hash_ignores_state_dict_insertion_order():
    model = build_model(ModelSpec("entity_mixer", 32, 1))
    metadata = {"format": "effective-splendor-gpu-checkpoint", "version": 1, "model_id": "unit", **model.checkpoint_metadata()}
    state = model.state_dict()
    assert checkpoint_semantic_hash(metadata, state) == checkpoint_semantic_hash(metadata, dict(reversed(list(state.items()))))
    changed = {key: value.clone() for key, value in state.items()}
    first = next(iter(changed)); changed[first].view(-1)[0] += 1
    assert checkpoint_semantic_hash(metadata, state) != checkpoint_semantic_hash(metadata, changed)


def test_self_play_visit_targets_follow_legal_action_order():
    take = {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0}, "return": None}
    passed = {"type": "pass"}
    target = normalized_visits({
        "legal_actions": [passed, take],
        "action_stats": [{"action": take, "visits": 3}, {"action": passed, "visits": 1}],
    })
    assert torch.allclose(target, torch.tensor([0.25, 0.75]))


def test_self_play_hash_domain_follows_dataset_version():
    payload = {"format": "effective-splendor-neural-self-play-v2", "version": 2, "self_play_id": "unit"}
    assert self_play_hash(payload) == self_play_hash(payload)
    legacy = {"format": "effective-splendor-neural-self-play", "version": 1, "self_play_id": "unit"}
    assert self_play_hash(payload) != self_play_hash(legacy)


def test_v2_policy_target_visits_are_explicit_and_must_match_action_stats():
    take = {"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0}, "return": None}
    passed = {"type": "pass"}
    target = normalized_visits({
        "legal_actions": [passed, take],
        "action_stats": [
            {"action": passed, "visits": 3},
            {"action": take, "visits": 1},
        ],
        "policy_target_visits": [3, 1],
    })
    assert torch.allclose(target, torch.tensor([0.75, 0.25]))
    with pytest.raises(ValueError, match="policy_target_visits"):
        normalized_visits({
            "legal_actions": [passed, take],
            "action_stats": [{"action": passed, "visits": 3}, {"action": take, "visits": 1}],
            "policy_target_visits": [0, 1],
        })


def test_c51_projection_is_normalized_and_terminal_reward_is_exact():
    support = torch.linspace(-1.0, 1.0, 51)
    distribution = torch.softmax(torch.randn(51), dim=0)
    projected = project_distribution(distribution, 1.0, True, 0.99, support)
    assert torch.isclose(projected.sum(), torch.tensor(1.0))
    assert projected.argmax() == 50


def test_distributional_q_returns_action_atom_logits():
    model = DistributionalQNetwork(RainbowSpec(64, 2, 51, -1.0, 1.0))
    logits = model(
        torch.randn(2, ENTITY_SLOTS, ENTITY_FEATURES),
        torch.ones(2, ENTITY_SLOTS, dtype=torch.bool),
        torch.randn(2, GLOBAL_FEATURES),
        torch.randn(2, 5, ACTION_FEATURES),
        torch.ones(2, 5, dtype=torch.bool),
    )
    assert logits.shape == (2, 5, 51)
    assert model.expected_q(logits).shape == (2, 5)
