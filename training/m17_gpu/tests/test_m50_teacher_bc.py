"""Small CPU-only contracts for teacher BC; no production training or artifacts."""
import json
from pathlib import Path

import numpy as np
import pytest
import torch
import torch.nn.functional as F

import m50_train_mortal_actor_critic as t


@pytest.fixture(autouse=True)
def cpu_only(monkeypatch):
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    yield
    torch.set_num_threads(previous)


def dataset(root, *, targets=None, mask=None, groups=None, count=4, metadata=None):
    manifest = dict(observation_width=368, action_width=72,
                    action_representation="semantic-reserve-target-v1",
                    policy_supervision="teacher-only", policy_label_source="chosen_action.u32",
                    policy_mask="all", policy_row_alignment="dataset-row")
    if targets is not None:
        manifest.update(policy_supervision="teacher-query", policy_label_source="policy_target.u32")
    if mask is not None:
        manifest["policy_mask"] = "policy_mask.u8"
    if groups is not None:
        manifest.update(policy_group="policy_group.u8", policy_group_labels={"0": "teacher", "1": "query"})
    if metadata is not None:
        manifest.update(metadata)
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest))
    rng = np.random.default_rng(34)
    for split in ("train", "val"):
        d = root / split
        d.mkdir()
        rng.normal(size=(count, 368)).astype("<f4").tofile(d / "obs.f32")
        rng.normal(size=(count * 2, 72)).astype("<f4").tofile(d / "actions.f32")
        np.arange(0, count * 2 + 1, 2, dtype="<u8").tofile(d / "action_offsets.u64")
        np.zeros(count, dtype="<u4").tofile(d / "chosen_action.u32")
        np.array([[i % 2, 0, 5] for i in range(count)], dtype="<f4").tofile(d / "values.f32")
        for name, values, dtype in (("policy_target.u32", targets, "<u4"),
                                    ("policy_mask.u8", mask, "u1"),
                                    ("policy_group.u8", groups, "u1")):
            if values is not None:
                np.asarray(values, dtype=dtype).tofile(d / name)
    return root


def test_losing_teacher_has_ce_gradient_but_aux_heads_do_not():
    model = t.MortalActorCriticNet(hidden_dim=16, num_blocks=0, critic_backbone_grad=True)
    adv, val, steps = model(torch.randn(2, 368), torch.randn(4, 56), torch.tensor([0, 0, 1, 1]))
    adv.retain_grad()
    loss = t.compute_training_loss(adv, val, steps, [2, 2], torch.tensor([0, 3]),
                                   torch.tensor([1., 0.]), torch.tensor([5., float("nan")]), "teacher-bc")
    loss.backward()
    assert adv.grad[2:].abs().sum() > 0
    assert model.action_net[0].weight.grad.abs().sum() > 0
    assert model.entity_backbone.fusion[0].weight.grad.abs().sum() > 0
    assert all(p.grad is None for p in model.val_head.parameters())
    assert all(p.grad is None for p in model.v_steps_head.parameters())


def test_objectives_differ_and_legacy_formula_preserved():
    adv = torch.tensor([2., 0., 3., -1.], requires_grad=True)
    val = torch.tensor([.2, -.3], requires_grad=True)
    steps = torch.tensor([2., 6.], requires_grad=True)
    won, target_steps, chosen = torch.tensor([1., 0.]), torch.tensor([4., 7.]), torch.tensor([0, 3])
    legacy = t.compute_training_loss(adv, val, steps, [2, 2], chosen, won, target_steps)
    expected = adv[:2].logsumexp(0) - adv[0] + .5 * F.binary_cross_entropy_with_logits(val, won)
    expected += .25 * F.smooth_l1_loss(steps[:1] / 20, target_steps[:1] / 20)
    torch.testing.assert_close(legacy, expected)
    bc = t.compute_training_loss(adv, val, steps, [2, 2], chosen, won, target_steps, "teacher-bc")
    assert not torch.isclose(bc, legacy)
    assert torch.isfinite(t.compute_training_loss(adv, val, steps, [2, 2], chosen, won * 0, target_steps))


def test_selection_strict_ce_vs_top1():
    metrics = {"pi_loss": .9, "top1_match": .5}
    assert t.selection_improved("teacher-bc", metrics, 1.)
    assert not t.selection_improved("teacher-bc", metrics, .9)
    assert not t.selection_improved("legacy", metrics, .6)
    assert not t.selection_improved("legacy", metrics, .5)
    assert t.selection_improved("legacy", metrics, .4)
    with pytest.raises(ValueError):
        t.selection_improved("unknown", metrics, 0.)


@pytest.mark.parametrize("source,target,extra", [(56, 72, 16), (72, 97, 25), (97, 97, 0), (72, 72, 0)])
def test_migration_exact_and_forward_equivalent(source, target, extra):
    torch.manual_seed(12)
    parent = t.MortalActorCriticNet(act_dim=source, hidden_dim=16, num_blocks=0)
    child = t.MortalActorCriticNet(act_dim=target, hidden_dim=16, num_blocks=0)
    state, migrations = t.migrate_state_dict(child, parent.state_dict())
    assert len(migrations) == (2 if extra else 0)
    for key, original in parent.state_dict().items():
        if extra and key in t.RESERVE_TARGET_INPUT_WEIGHTS:
            assert torch.equal(state[key][:, :-extra], original)
            assert torch.count_nonzero(state[key][:, -extra:]) == 0
        else:
            assert torch.equal(state[key], original)
    child.load_state_dict(state, strict=True)
    obs, act, idx = torch.randn(2, 368), torch.randn(6, source), torch.tensor([0, 0, 0, 1, 1, 1])
    expanded = torch.cat([act, torch.randn(6, extra)], 1)
    for a, b in zip(parent(obs, act, idx), child(obs, expanded, idx)):
        torch.testing.assert_close(a, b, atol=1e-6, rtol=1e-5)


def test_migration_rejects_other_tensor_changes_and_schema():
    parent = t.MortalActorCriticNet(act_dim=72, hidden_dim=16, num_blocks=0)
    child = t.MortalActorCriticNet(act_dim=97, hidden_dim=16, num_blocks=0)
    state = parent.state_dict()
    state["val_head.0.weight"] = state["val_head.0.weight"][:, :-1]
    with pytest.raises(ValueError, match="shape"):
        t.migrate_state_dict(child, state)
    with pytest.raises(ValueError):
        t.validate_action_schema(97, "invented")
    with pytest.raises(ValueError):
        t.validate_action_schema(97)
    with pytest.raises(ValueError):
        t.MortalActorCriticNet(act_dim=98)


def test_policy_target_separate_from_chosen_and_mask(tmp_path):
    root = dataset(tmp_path, targets=[1, 0, 1, 4294967295], mask=[1, 1, 1, 0])
    original = (root / "train/chosen_action.u32").read_bytes()
    d = t.SemanticDataset(root / "train", "teacher-bc")
    batch = d.get_batch(np.array([2, 0, 3]), torch.device("cpu"))
    assert batch[4].tolist() == [1, 3, 4]
    assert d.batch_policy_mask(np.array([2, 0, 3]), torch.device("cpu")).tolist() == [True, True, False]
    assert d.chosen_actions.tolist() == [0] * 4
    assert (root / "train/chosen_action.u32").read_bytes() == original
    with pytest.raises(ValueError, match="legacy"):
        t.SemanticDataset(root / "train")


def test_empty_mask_loss_skips_without_nan_or_aux_grad():
    adv, val, steps = (torch.randn(n, requires_grad=True) for n in (4, 2, 2))
    result = t.compute_training_loss(adv, val, steps, [2, 2], torch.tensor([999, 999]),
                                     torch.full((2,), float("nan")), torch.full((2,), float("nan")),
                                     "teacher-bc", torch.zeros(2, dtype=torch.bool))
    assert result is None
    assert all(x.grad is None for x in (adv, val, steps))


@pytest.mark.parametrize("override", [
    {"policy_supervision": "mixed-coev"}, {"policy_supervision": None},
    {"policy_row_alignment": "game-row"}, {"policy_mask": "guess"},
    {"policy_supervision": "teacher-query"}, {"policy_label_source": "guess"},
])
def test_reject_bad_metadata(tmp_path, override):
    dataset(tmp_path, metadata=override)
    with pytest.raises(ValueError):
        t.SemanticDataset(tmp_path / "train", "teacher-bc")


def test_sidecars_require_declaration_and_row_alignment(tmp_path):
    dataset(tmp_path)
    np.array([1, 1, 1, 1], dtype="<u4").tofile(tmp_path / "train/policy_target.u32")
    with pytest.raises(ValueError, match="Undeclared"):
        t.SemanticDataset(tmp_path / "train", "teacher-bc")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["policy_label_source"] = "policy_target.u32"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    np.array([1], dtype="<u4").tofile(tmp_path / "train/policy_target.u32")
    with pytest.raises(ValueError, match="align"):
        t.SemanticDataset(tmp_path / "train", "teacher-bc")


def test_group_sampling_equal_bounded_and_masks(tmp_path):
    dataset(tmp_path, count=10, groups=[0] * 9 + [1], mask=[1] * 8 + [0, 1])
    d = t.SemanticDataset(tmp_path / "train", "teacher-bc")
    rows = d.epoch_indices("balanced-groups", np.random.default_rng(2))
    assert len(rows) == d.count
    assert sum(d.policy_groups[rows] == 0) == 5
    assert sum(d.policy_groups[rows] == 1) == 5
    assert 8 not in rows
    assert len(d.epoch_indices()) == d.count
    assert np.array_equal(rows, d.epoch_indices("balanced-groups", np.random.default_rng(2)))
    d.policy_groups = None
    rows = d.epoch_indices("balanced-groups", np.random.default_rng(3))
    assert len(rows) == d.count and 8 not in rows
    d.policy_mask[:] = 0
    with pytest.raises(ValueError, match="No valid"):
        d.epoch_indices()


@pytest.mark.parametrize("objective", ["legacy", "teacher-bc"])
def test_tiny_cpu_training_selection_summary_and_export(tmp_path, monkeypatch, objective):
    data = dataset(tmp_path / "data")
    # Baseline is better than all trained epochs, but must never be selected.
    diagnostics = iter([(.1, .99), (.7, .6), (.6, .5), (.6, .5)])
    def fake_eval(*args, **kwargs):
        ce, top1 = next(diagnostics)
        result = {"pi_loss": ce, "top1_match": top1}
        if objective == "legacy":
            result.update(val_acc=.5, steps_mae=2.)
        return result
    monkeypatch.setattr(t, "evaluate", fake_eval)
    out = tmp_path / "out"
    history = t.train_mortal_actor_critic(data, out, hidden_dim=8, num_blocks=0, epochs=3,
                                         batch_size=2, accumulation_steps=1, policy_objective=objective)
    summary = json.loads((out / "training-summary.json").read_text())
    exported = json.loads((out / "mortal_actor_critic_weights.json").read_text())
    assert summary["best_epoch"] == (2 if objective == "teacher-bc" else 1)
    assert summary["val_ce_history"] == [.7, .6, .6]
    assert summary["policy_objective"] == objective
    assert summary["selection_epochs"] == [1, 3]
    assert exported["action_dim"] == 72 and exported["is_argmax"] is True
    if objective == "teacher-bc":
        assert exported["training_objective"] == objective
        assert not summary["auxiliary_heads_trained"]
        assert "val_critic_acc" not in history[0]
        assert "val_acc" not in summary["baseline"]
    else:
        assert "training_objective" not in exported


def test_teacher_evaluation_ignores_invalid_rows_and_aux(tmp_path):
    dataset(tmp_path, targets=[1, 4294967295, 0, 4294967295], mask=[1, 0, 1, 0])
    d = t.SemanticDataset(tmp_path / "val", "teacher-bc")
    model = t.MortalActorCriticNet(act_dim=72, hidden_dim=8, num_blocks=0)
    metrics = t.evaluate(model, d, torch.device("cpu"), batch_size=1, policy_objective="teacher-bc")
    assert set(metrics) == {"pi_loss", "top1_match"}
    assert all(np.isfinite(v) for v in metrics.values())
