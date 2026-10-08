import math

import numpy as np
import pytest
import torch
from torch.nn import functional as F

from training.prism import PrismModel, collate, predict
from training.prism.train import loss_terms
from conftest import make_state


def test_exact_names_and_numpy_numerical_contract():
    torch.manual_seed(19)
    model = PrismModel()
    prefixes = {"encoder", "action", "target", "global_action", "key", "entity_value",
                "policy_hidden", "policy_out", "value_hidden", "value_out"}
    prefixes |= {f"blocks.{i}.{name}" for i in range(2) for name in ("local", "context", "norm")}
    assert set(model.state_dict()) == {f"{name}.{suffix}" for name in prefixes for suffix in ("weight", "bias")}
    state = make_state(71, 5, 7)
    weights = {key: val.detach().numpy() for key, val in model.state_dict().items()}

    def linear(name, x):
        return x @ weights[name + ".weight"].T + weights[name + ".bias"]

    h = np.maximum(linear("encoder", state["entities"]), 0)
    for i in range(2):
        g = h.mean(0)
        u = np.maximum(linear(f"blocks.{i}.local", h) + linear(f"blocks.{i}.context", g), 0)
        x = h + u
        h = (x - x.mean(-1, keepdims=True)) / np.sqrt(x.var(-1, keepdims=True) + np.float32(1e-5))
        h = h * weights[f"blocks.{i}.norm.weight"] + weights[f"blocks.{i}.norm.bias"]
    g = h.mean(0)
    targets = np.zeros((7, 128), dtype=np.float32)
    for i, target in enumerate(state["targets"]):
        if target >= 0:
            targets[i] = h[target]
    q = np.maximum(linear("action", state["actions"]) + linear("target", targets) + linear("global_action", g), 0)
    attention = q @ linear("key", h).T / np.float32(math.sqrt(128))
    attention = np.exp(attention - attention.max(-1, keepdims=True))
    attention /= attention.sum(-1, keepdims=True)
    r = attention @ linear("entity_value", h)
    x = np.concatenate((q, r, np.broadcast_to(g, q.shape)), -1)
    expected_logits = linear("policy_out", np.maximum(linear("policy_hidden", x), 0)).ravel()
    expected_value = 1 / (1 + np.exp(-linear("value_out", np.maximum(linear("value_hidden", g), 0))))
    prediction = predict(model, state)
    np.testing.assert_allclose(prediction["logits"], expected_logits, atol=1e-5, rtol=1e-5)
    np.testing.assert_allclose(prediction["value"], expected_value.item(), atol=1e-5, rtol=1e-5)


def test_padding_excluded_from_pool_attention_logits_and_gradients():
    torch.manual_seed(11)
    model = PrismModel()
    first, second = make_state(1, 2, 3), make_state(2, 6, 7)
    single = predict(model, first)
    batch = collate([first, second])
    batch["entities"][0, 2:] = torch.nan
    batch["actions"][0, 3:] = torch.inf
    batch["targets"][0, 3:] = 123456
    batch["entities"].requires_grad_()
    batch["actions"].requires_grad_()
    logits, values = model.forward_batch(batch)
    torch.testing.assert_close(logits[0, :3], torch.tensor(single["logits"]), atol=1e-5, rtol=1e-5)
    assert values.sigmoid()[0].item() == pytest.approx(single["value"], abs=1e-6)
    assert torch.isneginf(logits[0, 3:]).all()
    assert torch.softmax(logits, -1)[0, 3:].eq(0).all()
    ce, bce = loss_terms(logits, values, torch.tensor([1, 2]), torch.tensor([0.0, 0.5]))
    loss = (ce + 0.5 * bce).mean()
    assert torch.isfinite(loss)
    loss.backward()
    assert batch["entities"].grad[0, 2:].eq(0).all()
    assert batch["actions"].grad[0, 3:].eq(0).all()
    assert all(p.grad is None or torch.isfinite(p.grad).all() for p in model.parameters())


def test_entity_and_action_permutation_equivariance():
    torch.manual_seed(3)
    model = PrismModel()
    state = make_state(13, 7, 13)
    ep = np.array([5, 2, 0, 6, 1, 4, 3])
    ap = np.array([3, 7, 0, 12, 2, 10, 1, 5, 4, 11, 8, 6, 9])
    inverse = np.argsort(ep)
    targets = state["targets"][ap].copy()
    targets[targets >= 0] = inverse[targets[targets >= 0]]
    reordered = {"entities": state["entities"][ep], "actions": state["actions"][ap], "targets": targets}
    before, after = predict(model, state), predict(model, reordered)
    np.testing.assert_allclose(after["logits"], np.array(before["logits"])[ap], atol=1e-5, rtol=1e-5)
    assert before["value"] == pytest.approx(after["value"], abs=1e-6)


def test_value_gradients_enter_shared_encoder_and_both_blocks():
    torch.manual_seed(7)
    model = PrismModel()
    batch = collate([make_state(1), make_state(2)])
    _, values = model.forward_batch(batch)
    F.binary_cross_entropy_with_logits(values, torch.tensor([0.0, 0.5])).backward()
    for name in ("encoder.weight", "blocks.0.local.weight", "blocks.0.context.weight",
                 "blocks.1.local.weight", "blocks.1.context.weight", "value_hidden.weight", "value_out.weight"):
        gradient = model.get_parameter(name).grad
        assert gradient is not None and torch.isfinite(gradient).all() and gradient.abs().sum() > 0
    assert model.policy_out.weight.grad is None


@pytest.mark.parametrize("change", ["empty_entities", "empty_actions", "target_padding", "bad_target", "nan", "dtype"])
def test_malformed_batched_inputs_fail(change):
    batch = collate([make_state(1, 2, 3), make_state(2, 4, 5)])
    if change == "empty_entities":
        batch["entity_mask"][0] = False
    elif change == "empty_actions":
        batch["action_mask"][0] = False
    elif change == "target_padding":
        batch["targets"][0, 0] = 2
    elif change == "bad_target":
        batch["targets"][0, 0] = -2
    elif change == "nan":
        batch["entities"][0, 0, 0] = torch.nan
    else:
        batch["actions"] = batch["actions"].double()
    with pytest.raises(ValueError):
        PrismModel().forward_batch(batch)


def test_single_entity_single_action_and_maximum_dimensions():
    model = PrismModel()
    single = predict(model, make_state(1, 1, 1))
    assert len(single["logits"]) == 1 and 0 <= single["value"] <= 1
    result = predict(model, make_state(1, 128, 4096))
    assert len(result["logits"]) == 4096 and np.isfinite(result["logits"]).all()
