"""CPU-only reserve-target schema/migration checks and a small Rust parity fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import torch
import torch.nn.functional as F

import m50_train_mortal_actor_critic as trainer
from m50_train_mortal_actor_critic import (
    ACT_DIM,
    ACTION_REPRESENTATIONS,
    OBS_DIM,
    RESERVE_TARGET_INPUT_WEIGHTS,
    MortalActorCriticNet,
    SemanticDataset,
    export_weights,
    load_action_schema,
    load_pretrained_weights,
    migrate_state_dict,
)


@pytest.fixture(autouse=True)
def single_cpu_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def fixed_inputs() -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Three states, two candidates each; first pair shares its legacy prefix."""
    obs = torch.linspace(0.0, 1.0, 3 * OBS_DIM).reshape(3, OBS_DIM)
    actions56 = (torch.arange(6 * 56, dtype=torch.float32) % 17).reshape(6, 56) / 17
    actions56[1] = actions56[0]
    suffix = torch.linspace(0.0, 1.0, 6 * 16).reshape(6, 16)
    actions72 = torch.cat([actions56, suffix], dim=1)
    parents = torch.tensor([0, 0, 1, 1, 2, 2])
    return obs, actions56, actions72, parents


def generate_reserve_target_fixture(
    out_dir: str | Path, hidden_dim: int = 256, num_blocks: int = 2,
) -> dict[str, Path]:
    """Write deterministic 56/72 JSON weights and forward expectations, no training.

    Returns paths for fixture.json and legacy56/migrated72/bound72 weights.
    fixture.json contains obs, actions56, actions72, parent_idx and cases with
    weights filename, state_h, adv_logits, val_logits, and v_steps. bound72 has
    deterministic nonzero suffix weights, so it also exercises new-column use.
    All scores are raw argmax logits, not probabilities or negated costs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(23005672)
        legacy = MortalActorCriticNet(hidden_dim=hidden_dim, num_blocks=num_blocks)
        migrated = MortalActorCriticNet(act_dim=72, hidden_dim=hidden_dim, num_blocks=num_blocks)
        state_dict, _ = migrate_state_dict(migrated, legacy.state_dict())
        migrated.load_state_dict(state_dict, strict=True)
        bound = MortalActorCriticNet(act_dim=72, hidden_dim=hidden_dim, num_blocks=num_blocks)
        bound.load_state_dict(migrated.state_dict(), strict=True)
        with torch.no_grad():
            bound.action_net[0].weight[:, -16:] = torch.linspace(-0.02, 0.02, 128 * 16).reshape(128, 16)
            bound.adv_head[0].weight[:, -16:] = torch.linspace(0.03, -0.03, 128 * 16).reshape(128, 16)
        obs, actions56, actions72, parents = fixed_inputs()
        payload = {
            "hidden_dim": hidden_dim,
            "num_blocks": num_blocks,
            "obs": obs.tolist(),
            "actions56": actions56.tolist(),
            "actions72": actions72.tolist(),
            "parent_idx": parents.tolist(),
            "cases": {},
        }
        paths = {}
        for name, model, actions in (
            ("legacy56", legacy, actions56),
            ("migrated72", migrated, actions72),
            ("bound72", bound, actions72),
        ):
            model.eval()
            paths[name] = out_dir / f"{name}_weights.json"
            export_weights(model, paths[name])
            with torch.no_grad():
                state_h = model.entity_backbone(obs)
                for block in model.state_res_blocks:
                    state_h = block(state_h)
                logits, values, steps = model(obs, actions, parents)
            payload["cases"][name] = {
                "weights": paths[name].name,
                "action_dim": model.act_dim,
                "action_representation": model.action_representation,
                "state_h": state_h.tolist(),
                "adv_logits": logits.tolist(),
                "val_logits": values.tolist(),
                "v_steps": steps.tolist(),
            }
        paths["fixture"] = out_dir / "fixture.json"
        paths["fixture"].write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        return paths


def write_tiny_dataset(root: Path, act_dim: int, schema: str | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"observation_width": OBS_DIM, "action_width": act_dim}
    if schema is not None:
        manifest["action_representation"] = schema
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    obs, actions56, actions72, _ = fixed_inputs()
    actions = actions56 if act_dim == 56 else actions72
    for split_name in ("train", "val"):
        split = root / split_name
        split.mkdir()
        obs.numpy().astype("<f4").tofile(split / "obs.f32")
        actions.numpy().astype("<f4").tofile(split / "actions.f32")
        np.array([0, 2, 4, 6], dtype="<u8").tofile(split / "action_offsets.u64")
        np.array([0, 1, 0], dtype="<u4").tofile(split / "chosen_action.u32")
        np.array([[1, 2, 8], [0, -2, 12], [0.5, 0, 10]], dtype="<f4").tofile(split / "values.f32")


@pytest.mark.parametrize("hidden_dim", [32, 256])
def test_migration_pads_only_two_input_weights_and_preserves_every_tensor(hidden_dim):
    old = MortalActorCriticNet(hidden_dim=hidden_dim, num_blocks=1)
    new = MortalActorCriticNet(act_dim=72, hidden_dim=hidden_dim, num_blocks=1)
    source = old.state_dict()
    migrated, changes = migrate_state_dict(new, source)
    assert set(migrated) == set(source) == set(new.state_dict())
    assert [change["parameter"] for change in changes] == list(RESERVE_TARGET_INPUT_WEIGHTS)
    assert migrated["action_net.0.weight"].shape == (128, 72)
    assert migrated["adv_head.0.weight"].shape == (128, hidden_dim * 2 + 72)
    for name, value in source.items():
        if name in RESERVE_TARGET_INPUT_WEIGHTS:
            assert torch.equal(migrated[name][:, :-16], value)
            assert torch.count_nonzero(migrated[name][:, -16:]) == 0
            assert migrated[name].shape[1] == value.shape[1] + 16
        else:
            assert torch.equal(migrated[name], value)
    for change in changes:
        assert change["from_shape"] == list(source[change["parameter"]].shape)
        assert change["to_shape"] == list(migrated[change["parameter"]].shape)
        assert change["zero_suffix_columns"] == 16
    new.load_state_dict(migrated, strict=True)
    for name, value in new.state_dict().items():
        assert torch.equal(value, migrated[name])


@pytest.mark.parametrize("hidden_dim", [32, 256])
@pytest.mark.parametrize("critic_backbone_grad", [False, True])
def test_migrated_three_heads_match_legacy_even_with_nonzero_target_features(hidden_dim, critic_backbone_grad):
    old = MortalActorCriticNet(hidden_dim=hidden_dim, num_blocks=1, critic_backbone_grad=critic_backbone_grad)
    new = MortalActorCriticNet(act_dim=72, hidden_dim=hidden_dim, num_blocks=1, critic_backbone_grad=critic_backbone_grad)
    migrated, _ = migrate_state_dict(new, old.state_dict())
    new.load_state_dict(migrated, strict=True)
    obs, actions56, actions72, parents = fixed_inputs()
    with torch.no_grad():
        for previous, current in zip(old(obs, actions56, parents), new(obs, actions72, parents)):
            torch.testing.assert_close(previous, current, atol=1e-6, rtol=1e-5)


@pytest.mark.parametrize("act_dim", [56, 72])
def test_same_schema_checkpoint_is_loaded_exactly(tmp_path, act_dim):
    old = MortalActorCriticNet(act_dim=act_dim, hidden_dim=32, num_blocks=1)
    new = MortalActorCriticNet(act_dim=act_dim, hidden_dim=32, num_blocks=1)
    path = tmp_path / "parent.pt"
    torch.save(old.state_dict(), path)
    identity = load_pretrained_weights(new, path)
    assert identity["migration"] == []
    assert identity["parent_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert identity["parent_action_representation"] == ACTION_REPRESENTATIONS[act_dim]
    for name, value in old.state_dict().items():
        assert torch.equal(value, new.state_dict()[name])


@pytest.mark.parametrize("act_dim", [56, 72])
@pytest.mark.parametrize("corruption", ["missing", "unexpected", "shape", "input_shape", "dtype", "wrapped"])
def test_checkpoint_rejects_partial_or_malformed_loads(act_dim, corruption):
    old = MortalActorCriticNet(hidden_dim=32, num_blocks=1)
    new = MortalActorCriticNet(act_dim=act_dim, hidden_dim=32, num_blocks=1)
    state = old.state_dict()
    if corruption == "missing":
        del state["val_head.0.bias"]
    elif corruption == "unexpected":
        state["bogus"] = torch.zeros(1)
    elif corruption == "shape":
        state["val_head.0.weight"] = state["val_head.0.weight"][:, :-1]
    elif corruption == "input_shape":
        state["adv_head.0.weight"] = state["adv_head.0.weight"][:, :-1]
    elif corruption == "dtype":
        state["val_head.0.weight"] = state["val_head.0.weight"].double()
    else:
        state = {"state_dict": state}
    with pytest.raises((ValueError, TypeError)):
        migrate_state_dict(new, state)


def test_checkpoint_rejects_wrong_schema_reverse_migration_and_missing_path(tmp_path):
    old = MortalActorCriticNet(hidden_dim=32, num_blocks=1)
    new = MortalActorCriticNet(act_dim=72, hidden_dim=32, num_blocks=1)
    with pytest.raises(ValueError, match="action_representation"):
        migrate_state_dict(new, old.state_dict(), source_action_representation="semantic-reserve-target-v1")
    with pytest.raises(ValueError, match="Unsupported checkpoint action migration"):
        migrate_state_dict(old, new.state_dict())
    with pytest.raises(FileNotFoundError):
        load_pretrained_weights(new, tmp_path / "missing.pt")


@pytest.mark.parametrize("act_dim,schema", [(56, None), (56, "semantic-v1"), (72, "semantic-reserve-target-v1")])
def test_existing_manifest_fields_control_dataset_width(tmp_path, act_dim, schema):
    write_tiny_dataset(tmp_path, act_dim, schema)
    assert load_action_schema(tmp_path) == (act_dim, ACTION_REPRESENTATIONS[act_dim])
    dataset = SemanticDataset(tmp_path / "train")
    batch = dataset.get_batch(np.arange(3), torch.device("cpu"))
    assert dataset.act_dim == act_dim
    assert batch[1].shape == (6, act_dim)
    assert batch[3] == [2, 2, 2]


@pytest.mark.parametrize("width,schema", [(72, None), (72, "semantic-v1"), (56, "semantic-reserve-target-v1"), (56, "unknown"), (48, "semantic-v1"), (56.0, "semantic-v1")])
def test_manifest_rejects_unknown_or_conflicting_schema(tmp_path, width, schema):
    manifest = {"observation_width": OBS_DIM, "action_width": width, "action_representation": schema}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        load_action_schema(tmp_path)


def test_manifest_rejects_wrong_field_names_and_observation_width(tmp_path):
    for manifest in (
        {"observation_width": OBS_DIM, "action_dim": 56},
        {"observation_width": 367, "action_width": 56},
    ):
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            load_action_schema(tmp_path)


@pytest.mark.parametrize("input_weight", RESERVE_TARGET_INPUT_WEIGHTS)
def test_target_suffix_receives_finite_gradient_and_can_change_raw_score(input_weight):
    torch.manual_seed(23)
    old = MortalActorCriticNet(hidden_dim=32, num_blocks=1)
    new = MortalActorCriticNet(act_dim=72, hidden_dim=32, num_blocks=1)
    migrated, _ = migrate_state_dict(new, old.state_dict())
    new.load_state_dict(migrated, strict=True)
    obs, _, actions, parents = fixed_inputs()
    logits = new(obs, actions, parents)[0]
    torch.testing.assert_close(logits[0], logits[1], atol=1e-7, rtol=1e-6)
    (logits[1] - logits[0]).backward()
    for name in RESERVE_TARGET_INPUT_WEIGHTS:
        suffix_grad = dict(new.named_parameters())[name].grad[:, -16:]
        assert torch.isfinite(suffix_grad).all()
        assert torch.count_nonzero(suffix_grad) > 0
    # Perturb only one of the two previously zero weight suffixes at a time.
    weight = dict(new.named_parameters())[input_weight]
    with torch.no_grad():
        weight[:, -16:] += 0.5 * weight.grad[:, -16:].sign()
        changed = new(obs, actions, parents)[0]
    assert abs((changed[1] - changed[0]).item()) > 1e-5


def test_default_critic_stays_detached_with_new_action_schema():
    assert ACT_DIM == 56
    model = MortalActorCriticNet(act_dim=72, hidden_dim=32, num_blocks=1)
    assert model.critic_backbone_grad is False
    obs, _, actions, parents = fixed_inputs()
    _, values, _ = model(obs, actions, parents)
    F.binary_cross_entropy_with_logits(values, torch.tensor([1.0, 0.0, 0.5])).backward()
    for name, parameter in model.named_parameters():
        if not name.startswith("val_head."):
            assert parameter.grad is None
    assert torch.isfinite(model.val_head[0].weight.grad).all()
    assert torch.count_nonzero(model.val_head[0].weight.grad) > 0


def test_fixture_exports_schema_weights_and_forward_expectations(tmp_path):
    paths = generate_reserve_target_fixture(tmp_path, hidden_dim=32, num_blocks=1)
    fixture = json.loads(paths["fixture"].read_text(encoding="utf-8"))
    obs, actions56, actions72, parents = fixed_inputs()
    for name, case in fixture["cases"].items():
        weights = json.loads(paths[name].read_text(encoding="utf-8"))
        assert weights.pop("is_argmax") is True
        assert weights.pop("action_dim") == case["action_dim"]
        assert weights.pop("action_representation") == case["action_representation"]
        model = MortalActorCriticNet(act_dim=case["action_dim"], hidden_dim=32, num_blocks=1)
        model.load_state_dict({key: torch.tensor(value) for key, value in weights.items()}, strict=True)
        with torch.no_grad():
            state_h = model.entity_backbone(obs)
            for block in model.state_res_blocks:
                state_h = block(state_h)
            outputs = model(obs, actions56 if case["action_dim"] == 56 else actions72, parents)
        torch.testing.assert_close(state_h, torch.tensor(case["state_h"]), rtol=0, atol=0)
        for key, output in zip(("adv_logits", "val_logits", "v_steps"), outputs):
            torch.testing.assert_close(output, torch.tensor(case[key]), rtol=0, atol=0)
    legacy = fixture["cases"]["legacy56"]["adv_logits"]
    migrated = fixture["cases"]["migrated72"]["adv_logits"]
    torch.testing.assert_close(torch.tensor(legacy), torch.tensor(migrated), atol=1e-6, rtol=1e-5)
    bound = fixture["cases"]["bound72"]["adv_logits"]
    assert abs(bound[1] - bound[0]) > 1e-5
    with pytest.raises(ValueError, match="action_representation"):
        export_weights(model, tmp_path / "bad.json", "semantic-v1")
    assert not (tmp_path / "bad.json").exists()


@pytest.mark.parametrize("epochs", [0, -1])
def test_epoch_zero_cannot_be_selected_or_export_stale_weights(tmp_path, epochs):
    with pytest.raises(ValueError, match="epoch 0 is diagnostic only"):
        trainer.train_mortal_actor_critic(data_dir=tmp_path, out_dir=tmp_path, epochs=epochs)


@pytest.mark.parametrize("filename", ["best_model.pt", "latest_model.pt", "mortal_actor_critic_weights.json", "training-summary.json"])
def test_training_refuses_previous_run_artifacts(tmp_path, filename):
    artifact = tmp_path / filename
    artifact.write_bytes(b"previous run")
    with pytest.raises(FileExistsError, match="choose a fresh out_dir"):
        trainer.train_mortal_actor_critic(data_dir=tmp_path, out_dir=tmp_path)
    assert artifact.read_bytes() == b"previous run"


def test_first_trained_epoch_is_saved_even_below_baseline_with_zero_top1(tmp_path, monkeypatch):
    # Two one-batch CPU updates only; this tests selection, not model quality.
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    data_dir, out_dir = tmp_path / "data", tmp_path / "run"
    write_tiny_dataset(data_dir, 72, "semantic-reserve-target-v1")
    parent = MortalActorCriticNet(hidden_dim=32, num_blocks=1)
    parent_path = tmp_path / "parent.pt"
    torch.save(parent.state_dict(), parent_path)
    top1_values = iter([0.9, 0.0, 0.0])
    monkeypatch.setattr(trainer, "evaluate", lambda *args: {
        "pi_loss": 1.0, "val_acc": 0.5, "steps_mae": 1.0,
        "top1_match": next(top1_values),
    })
    trainer.train_mortal_actor_critic(
        data_dir=data_dir, out_dir=out_dir, hidden_dim=32, num_blocks=1,
        epochs=2, batch_size=3, accumulation_steps=1, pretrained=str(parent_path),
    )
    summary = json.loads((out_dir / "training-summary.json").read_text(encoding="utf-8"))
    assert summary["baseline"]["top1_match"] == 0.9
    assert summary["best_epoch"] == 1
    assert summary["best_val_top1"] == 0.0
    assert summary["action_dim"] == 72
    assert summary["action_representation"] == "semantic-reserve-target-v1"
    assert summary["parent_sha256"] == hashlib.sha256(parent_path.read_bytes()).hexdigest()
    assert [entry["parameter"] for entry in summary["migration"]] == list(RESERVE_TARGET_INPUT_WEIGHTS)
    assert summary["critic_backbone_grad"] is False
    best = torch.load(out_dir / "best_model.pt", weights_only=True)
    assert all(isinstance(value, torch.Tensor) for value in best.values())
    weights = json.loads((out_dir / "mortal_actor_critic_weights.json").read_text(encoding="utf-8"))
    for key, value in best.items():
        assert torch.equal(value, torch.tensor(weights[key]))
    assert not torch.equal(best["action_net.0.weight"][:, :56], parent.action_net[0].weight)


@pytest.mark.parametrize("metric", ["pi_loss", "val_acc", "steps_mae", "top1_match"])
@pytest.mark.parametrize("stage", ["baseline", "trained"])
def test_nonfinite_metrics_stop_without_exporting_a_checkpoint(tmp_path, monkeypatch, metric, stage):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    data_dir, out_dir = tmp_path / "data", tmp_path / "run"
    write_tiny_dataset(data_dir, 72, "semantic-reserve-target-v1")
    calls = 0

    def evaluate(*args):
        nonlocal calls
        calls += 1
        metrics = {"pi_loss": 1.0, "val_acc": 0.5, "steps_mae": 1.0, "top1_match": 0.5}
        if calls == (1 if stage == "baseline" else 2):
            metrics[metric] = float("nan")
        return metrics

    monkeypatch.setattr(trainer, "evaluate", evaluate)
    with pytest.raises(FloatingPointError, match="Non-finite"):
        trainer.train_mortal_actor_critic(
            data_dir=data_dir, out_dir=out_dir, hidden_dim=32, num_blocks=1,
            epochs=1, batch_size=3, accumulation_steps=1,
        )
    for name in ("best_model.pt", "latest_model.pt", "mortal_actor_critic_weights.json", "training-summary.json"):
        assert not (out_dir / name).exists()


def test_validation_top1_remains_tie_aware_and_includes_non_winners(tmp_path):
    write_tiny_dataset(tmp_path, 56, None)
    dataset = SemanticDataset(tmp_path / "val")

    class FixedScores(torch.nn.Module):
        def forward(self, obs, actions, parents):
            return (
                torch.tensor([2.0, 2.00005, 0.0, 1.0, 1.0, 2.0]),
                torch.tensor([1.0, -1.0, -1.0]),
                torch.tensor([8.0, 12.0, 10.0]),
            )

    metrics = trainer.evaluate(FixedScores(), dataset, torch.device("cpu"))
    assert metrics["top1_match"] == pytest.approx(2 / 3)
    assert metrics["val_acc"] == 1.0
    assert metrics["steps_mae"] == 0.0
