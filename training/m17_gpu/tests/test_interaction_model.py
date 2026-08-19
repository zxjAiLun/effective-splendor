import json

import torch

from splendor_gpu.agent import load_model
from splendor_gpu.encoding import ACTION_FEATURES, ENTITY_FEATURES, ENTITY_SLOTS, GLOBAL_FEATURES
from splendor_gpu.model import ContextualEntityMixerPolicyValue, ModelSpec, build_model
from splendor_gpu.train import checkpoint_semantic_hash, seed_everything


def contextual_spec(hidden_dim: int = 64, blocks: int = 2, interaction_blocks: int = 2) -> ModelSpec:
    return ModelSpec(
        "contextual_entity_mixer",
        hidden_dim,
        blocks,
        dropout=0.0,
        interaction_blocks=interaction_blocks,
    )


def batch_inputs(batch_size: int = 2, visible_entities: int = 6):
    entities = torch.randn(batch_size, ENTITY_SLOTS, ENTITY_FEATURES)
    mask = torch.zeros(batch_size, ENTITY_SLOTS, dtype=torch.bool)
    mask[:, :visible_entities] = True
    globals_ = torch.randn(batch_size, GLOBAL_FEATURES)
    actions = torch.randn(batch_size, 5, ACTION_FEATURES)
    action_mask = torch.ones(batch_size, 5, dtype=torch.bool)
    return entities, mask, globals_, actions, action_mask


def test_historical_entity_mixer_parameter_count_and_strict_checkpoint_load(tmp_path):
    model = build_model(ModelSpec("entity_mixer", 192, 4))
    assert sum(parameter.numel() for parameter in model.parameters()) == 949060
    metadata = {
        "format": "effective-splendor-gpu-checkpoint",
        "version": 1,
        "model_id": "historical-entity-mixer-unit",
        **model.checkpoint_metadata(),
    }
    assert "interaction_blocks" not in metadata["architecture"]
    state = model.state_dict()
    checkpoint_hash = checkpoint_semantic_hash(metadata, state)
    path = tmp_path / "historical-entity-mixer.pt"
    torch.save({"metadata": metadata, "state_dict": state}, path)

    loaded, loaded_metadata = load_model(path, checkpoint_hash, torch.device("cpu"))

    assert type(loaded).__name__ == "EntityMixerPolicyValue"
    assert loaded_metadata["architecture"] == metadata["architecture"]
    assert all(torch.equal(state[key], loaded.state_dict()[key]) for key in state)


def test_contextual_candidate_has_frozen_parameter_count_and_metadata():
    model = build_model(ModelSpec("contextual_entity_mixer", 192, 4, interaction_blocks=2))
    assert isinstance(model, ContextualEntityMixerPolicyValue)
    assert sum(parameter.numel() for parameter in model.parameters()) == 1689798
    metadata = model.checkpoint_metadata()
    assert metadata["architecture"] == {
        "architecture": "contextual_entity_mixer",
        "hidden_dim": 192,
        "blocks": 4,
        "dropout": 0.0,
        "interaction_blocks": 2,
    }


def test_contextual_forward_shapes_and_values_are_viewer_relative():
    model = build_model(contextual_spec())
    entities, mask, globals_, actions, action_mask = batch_inputs()

    logits, values = model(entities, mask, globals_, actions, action_mask)

    assert logits.shape == (2, 5)
    assert values.shape == (2, 2)
    assert torch.isfinite(logits).all()
    assert values.min() >= 0.0 and values.max() <= 1.0
    assert model.checkpoint_metadata()["value_order"] == "viewer_relative"


def test_masked_entities_do_not_affect_context_or_output():
    model = build_model(contextual_spec()).eval()
    entities, mask, globals_, actions, action_mask = batch_inputs()
    altered = entities.clone()
    altered[:, ~mask[0]] = torch.randn_like(altered[:, ~mask[0]]) * 1000.0

    original_logits, original_values = model(entities, mask, globals_, actions, action_mask)
    altered_logits, altered_values = model(altered, mask, globals_, actions, action_mask)
    original_contexts = model.contextual_interaction_contexts(entities, mask, globals_)
    altered_contexts = model.contextual_interaction_contexts(altered, mask, globals_)

    torch.testing.assert_close(original_logits, altered_logits)
    torch.testing.assert_close(original_values, altered_values)
    for original, changed in zip(original_contexts, altered_contexts):
        torch.testing.assert_close(original, changed)
        assert torch.equal(changed[:, ~mask[0]], torch.zeros_like(changed[:, ~mask[0]]))


def test_pairwise_context_respects_visible_entity_mask():
    model = build_model(contextual_spec()).eval()
    entities, mask, globals_, _, _ = batch_inputs(batch_size=1, visible_entities=3)
    contexts = model.contextual_interaction_contexts(entities, mask, globals_)
    assert len(contexts) == 2
    for context in contexts:
        assert context.shape == (1, ENTITY_SLOTS, 64)
        assert torch.equal(context[:, 3:], torch.zeros_like(context[:, 3:]))


def test_legal_action_padding_does_not_change_valid_logits_or_value():
    model = build_model(contextual_spec()).eval()
    entities, mask, globals_, actions, _ = batch_inputs(batch_size=1)
    valid_actions = actions[:, :3]
    padded_actions = torch.cat((valid_actions, torch.randn(1, 4, ACTION_FEATURES)), dim=1)
    valid_mask = torch.ones(1, 3, dtype=torch.bool)
    padded_mask = torch.tensor([[True, True, True, False, False, False, False]])

    valid_logits, valid_values = model(entities, mask, globals_, valid_actions, valid_mask)
    padded_logits, padded_values = model(entities, mask, globals_, padded_actions, padded_mask)

    torch.testing.assert_close(valid_logits, padded_logits[:, :3])
    torch.testing.assert_close(valid_values, padded_values)


def test_fresh_initialization_is_deterministic():
    seed_everything(280229)
    first = build_model(contextual_spec())
    seed_everything(280229)
    second = build_model(contextual_spec())
    assert all(torch.equal(first.state_dict()[key], second.state_dict()[key]) for key in first.state_dict())


def test_pairwise_representation_distinguishes_entity_combinations_with_same_mean():
    model = build_model(contextual_spec()).eval()
    entities, mask, globals_, _, _ = batch_inputs(batch_size=1, visible_entities=3)
    alternate = entities.clone()
    delta = torch.zeros_like(alternate)
    delta[:, 0, 0] = 0.75
    delta[:, 1, 0] = -0.75
    alternate = alternate + delta
    assert torch.allclose(entities[:, :3].mean(dim=1), alternate[:, :3].mean(dim=1))

    first = model.contextual_entity_embeddings(entities, mask, globals_)
    second = model.contextual_entity_embeddings(alternate, mask, globals_)

    assert not torch.allclose(first[:, :3], second[:, :3])
