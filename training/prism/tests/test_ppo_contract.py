import copy
import json
import math
import socket
import threading

import pytest
import torch

from training.prism.data import collate_states
from training.prism.export import load_weights
from training.prism.io import parse_json, tensor_identity
from training.prism.ppo.contract import PPOConfig, validate_audit, validate_input, validate_request, validate_response
from training.prism.ppo.learner import Learner, clipped_surrogate, prepare_batch, terminal_gae
from training.prism.ppo.model import new_model
from training.prism.ppo.runtime import configure
from training.prism.ppo.sampling import Behavior
from training.prism.ppo.service import BehaviorServer
from training.prism.tests.ppo_support import CATALOG, config, encoded, game, request


@pytest.fixture
def behavior():
    runtime = configure("cpu", 2)
    return Behavior(new_model(style_enabled=False), catalog_fingerprint=CATALOG, action_seed=7, runtime=runtime)


@pytest.mark.parametrize("change", [dict(lr=0), dict(lr=float("nan")), dict(passes=True),
                                    dict(clip_epsilon=1), dict(gae_lambda=-1), dict(style_beta=1),
                                    dict(style_value_weight=0.5), dict(normalize_advantage=1)])
def test_explicit_config_rejects_bad_parameters(change):
    with pytest.raises(ValueError):
        config(**change)


def test_config_no_defaults_or_unknown_fields():
    value = config().to_dict()
    assert PPOConfig.from_dict(value) == config()
    del value["lr"]
    with pytest.raises(ValueError):
        PPOConfig.from_dict(value)
    value = config().to_dict() | {"teacher_ce": 1.0}
    with pytest.raises(ValueError):
        PPOConfig.from_dict(value)


@pytest.mark.parametrize("mutation", ["unknown", "nonfinite", "target", "width", "bool", "empty"])
def test_features_strict(mutation):
    value = encoded()
    if mutation == "unknown": value["seed"] = 9
    if mutation == "nonfinite": value["entities"][0][0] = float("nan")
    if mutation == "target": value["targets"][0] = 2
    if mutation == "width": value["actions"][0].pop()
    if mutation == "bool": value["targets"][0] = True
    if mutation == "empty": value["entities"] = []
    with pytest.raises(ValueError):
        validate_input(value)


def test_metadata_does_not_enter_model_and_draw_is_reproducible(behavior):
    req = request(behavior)
    before = torch.get_rng_state().clone()
    a = behavior.sample(req)
    b = behavior.sample(req | {"game_id": "other-public-id", "request_id": 999})
    assert a["probabilities"] == b["probabilities"]
    assert a["chosen_index"] == b["chosen_index"]
    assert torch.equal(before, torch.get_rng_state())
    assert a["log_prob"] == math.log(a["probabilities"][a["chosen_index"]])
    with pytest.raises(ValueError):
        behavior.sample(req | {"future_winner": 1})
    with pytest.raises(ValueError):
        behavior.sample(req | {"behavior_id": "0" * 64})


def test_snapshot_is_immutable_and_checked(behavior):
    payload = behavior.payload()
    other = Behavior.from_payload(payload, runtime=behavior.runtime)
    assert other.sample(request(other)) == behavior.sample(request(behavior))
    payload["state_dict"]["policy.policy_out.bias"].add_(1)
    with pytest.raises(ValueError, match="identity"):
        Behavior.from_payload(payload, runtime=behavior.runtime)
    with pytest.raises(ValueError, match="runtime"):
        Behavior.from_payload(behavior.payload(), runtime=behavior.runtime | {"cpu_threads": 1})


def test_sampler_is_not_greedy_even_with_equal_logits(behavior):
    with torch.no_grad():
        behavior.model.policy.policy_out.weight.zero_()
        behavior.model.policy.policy_out.bias.zero_()
    # Re-freeze identity after the deliberate TEST-ONLY model alteration.
    uniform = Behavior(behavior.model, catalog_fingerprint=CATALOG, action_seed=7, runtime=behavior.runtime)
    counts = [0, 0, 0]
    for i in range(180):
        response = uniform.sample(request(uniform, job=f"draw-{i}"))
        counts[response["chosen_index"]] += 1
    assert all(35 < c < 85 for c in counts), counts


@pytest.mark.parametrize("field,value", [("chosen_index", 99), ("log_prob", 0.0), ("value", float("nan")),
                                          ("style_value", float("inf")), ("actor", True), ("job_id", "wrong")])
def test_bad_response_rejected(behavior, field, value):
    req = request(behavior)
    response = behavior.sample(req) | {field: value}
    with pytest.raises(ValueError):
        validate_response(response, req)


def test_player_time_axis_and_terminal_return():
    assert terminal_gae([0.2, 0.3, 0.4], 1, 1) == pytest.approx([0.8, 0.7, 0.6])
    assert terminal_gae([0.2, 0.3, 0.4], 0, 1) == pytest.approx([-0.2, -0.3, -0.4])
    assert terminal_gae([0.2, 0.3], 0.5, 0) == pytest.approx([0.1, 0.2])


@pytest.mark.parametrize("ranks,actor,outcome", [([0, 1], 0, 1), ([0, 1], 1, 0), ([1, 0], 1, 1), ([0, 0], 0, 0.5)])
def test_terminal_uses_actor_ranks_not_last_mover_or_scores(behavior, ranks, actor, outcome):
    shard = game(behavior, ranks=ranks, actor=actor)
    shard["result"]["scores"] = [15, 15]  # equal scores need not mean draw
    batch = prepare_batch([shard], behavior, config(gae_lambda=1, normalize_advantage=False), max_decisions=10)
    assert all(row["outcome"] == outcome for row in batch["rows"])
    for row, original in zip(batch["rows"], shard["decisions"]):
        assert row["advantage"] == pytest.approx(outcome - original["response"]["value"])


def test_adjacent_noble_decision_no_sign_flip(behavior):
    shard = game(behavior, count=2)
    row = shard["decisions"][1]
    row["request"]["request_id"] = 2  # same actor immediately after first decision
    row["response"]["request_id"] = 2
    batch = prepare_batch([shard], behavior, config(gae_lambda=1, normalize_advantage=False), max_decisions=10)
    assert all(row["advantage"] > 0 for row in batch["rows"])


@pytest.mark.parametrize("mutation", ["truncate", "duplicate", "gap", "actor", "probability", "opponent", "three_players"])
def test_bad_trajectories_fail_closed(behavior, mutation):
    shard = game(behavior)
    if mutation == "truncate": shard["terminal"] = False
    if mutation == "duplicate": shard["decisions"].append(copy.deepcopy(shard["decisions"][-1]))
    if mutation == "gap": shard["decisions"].pop(1)
    if mutation == "actor": shard["actor"] = 1
    if mutation == "probability": shard["decisions"][0]["response"]["probabilities"][0] = 0.9
    if mutation == "opponent": shard["decisions"][0]["request"]["behavior_id"] = "0" * 64
    if mutation == "three_players": shard["result"]["ranks"].append(2)
    with pytest.raises(ValueError):
        prepare_batch([shard], behavior, config(), max_decisions=10)


def test_critic_drift_rejected(behavior):
    shard = game(behavior)
    shard["decisions"][0]["response"]["value"] += 0.01
    with pytest.raises(ValueError, match="value drift"):
        prepare_batch([shard], behavior, config(), max_decisions=10)


@pytest.mark.parametrize("advantage,sign", [(1.0, -1), (-1.0, 1)])
def test_clipped_policy_gradient_sign(advantage, sign):
    lp = torch.tensor(-0.5, requires_grad=True)
    loss, ratio = clipped_surrogate(lp, lp.detach(), lp.new_tensor(advantage), 0.2)
    loss.backward()
    assert lp.grad.item() * sign > 0
    assert ratio.item() == 1


def test_clipping_saturates_favorable_direction():
    lp = torch.tensor(math.log(1.5), requires_grad=True)
    loss, _ = clipped_surrogate(lp, lp.new_tensor(0), lp.new_tensor(1), 0.2)
    loss.backward()
    assert lp.grad.item() == 0


def test_learner_updates_and_balanced_style_is_frozen(behavior):
    cfg = config()
    model = new_model(style_enabled=False, state_dict=behavior.payload()["state_dict"])
    learner = Learner(model, cfg)
    batch = prepare_batch([game(behavior)], behavior, cfg, max_decisions=10)
    initial = tensor_identity(model.policy.state_dict())
    style = {k: v.clone() for k, v in model.style_head.state_dict().items()}
    assert learner.diagnostics(batch)["max_ratio_error"] < 1e-10
    metrics = learner.step(batch, [0, 1])
    assert all(math.isfinite(v) for v in metrics.values())
    assert tensor_identity(model.policy.state_dict()) != initial
    assert all(torch.equal(style[k], v) for k, v in model.style_head.state_dict().items())
    assert all(p.grad is None for p in model.style_head.parameters())


def test_single_action_and_zero_variance_are_finite(behavior):
    cfg = config()
    batch = prepare_batch([game(behavior, count=1, actions=1)], behavior, cfg, max_decisions=10)
    learner = Learner(new_model(style_enabled=False, state_dict=behavior.payload()["state_dict"]), cfg)
    assert batch["rows"][0]["advantage"] == 0
    assert learner.diagnostics(batch)["entropy"] == 0
    assert learner.step(batch, [0])["policy_loss"] == 0


def test_style_mc_is_separate_and_export_has_only_v01_keys(tmp_path):
    runtime = configure("cpu", 2)
    model = new_model(style_enabled=True)
    behavior = Behavior(model, catalog_fingerprint=CATALOG, action_seed=7, runtime=runtime)
    cfg = config(style_beta=0.2, style_value_weight=0.5, normalize_advantage=False, gae_lambda=1)
    shard = game(behavior, ranks=[1, 0])
    batch = prepare_batch([shard], behavior, cfg, max_decisions=10, style_returns={("synthetic-job", 0): 0.8})
    for row, original in zip(batch["rows"], shard["decisions"]):
        assert row["outcome"] == 0 and row["style_return"] == 0.8
        assert row["advantage"] == pytest.approx(-original["response"]["value"] + 0.2 * 0.8)
    Learner(model, cfg).step(batch, [0, 1])
    assert model.style_head[-1].bias.item() != 0
    path = tmp_path / "weights.json"
    model.export(path, CATALOG, provenance={"test": True})
    restored = load_weights(path, expected_catalog_fingerprint=CATALOG)
    assert len(restored.state_dict()) == 32
    assert tensor_identity(restored.state_dict()) == tensor_identity(model.policy.state_dict())


def test_local_service_real_socket_and_rejection(behavior):
    server = BehaviorServer(("127.0.0.1", 0), behavior, "test-secret")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def send(value):
        with socket.create_connection(server.server_address, timeout=5) as connection:
            connection.sendall(json.dumps(value).encode() + b"\n")
            return parse_json(connection.makefile("rb").readline().decode())
    try:
        req = request(behavior)
        assert send(req | {"token": "test-secret"}) == behavior.sample(req)
        assert send(req | {"token": "wrong"}) == {"error": "request rejected"}
        assert send(req | {"token": "test-secret", "hidden": 1}) == {"error": "request rejected"}
    finally:
        server.shutdown(); thread.join(5); server.server_close()
    assert not thread.is_alive()
    with pytest.raises(ValueError):
        BehaviorServer(("0.0.0.0", 0), behavior, "test-secret")

def test_huge_json_integer_is_rejected_as_value_error():
    from training.prism.ppo.contract import number
    with pytest.raises(ValueError):
        number(10**1000, 0, float("inf"), "untrusted number")


def test_bounded_audit_json_and_timeout(tmp_path, monkeypatch):
    import subprocess
    from training.prism.ppo.audit import audit_game, bounded_json
    from training.prism.io import sha256_file
    source = tmp_path / "source.json"
    source.write_text('{"x":1}', encoding="utf-8")
    assert bounded_json(source, 20) == {"x": 1}
    with pytest.raises(ValueError, match="size"):
        bounded_json(source, 2)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("test-only", 120)
    monkeypatch.setattr("training.prism.ppo.audit.subprocess.run", timeout)
    with pytest.raises(ValueError, match="timed out"):
        audit_game(source, sha256_file(source), source, source, tmp_path / "output.json",
                   behavior_id="a" * 64, job_id="fixture", actor=0)


def test_forged_old_probabilities_rejected_before_optimizer(behavior):
    from training.prism.io import canonical_hash
    cfg = config()
    batch = prepare_batch([game(behavior)], behavior, cfg, max_decisions=10)
    batch["rows"][0]["old_probabilities"] = [1.0, 1.0, 1.0]
    batch["batch_id"] = canonical_hash({k: v for k, v in batch.items() if k != "batch_id"})
    learner = Learner(new_model(style_enabled=False, state_dict=behavior.payload()["state_dict"]), cfg)
    initial = tensor_identity(learner.model.state_dict())
    with pytest.raises(ValueError, match="normalized"):
        learner.step(batch, [0])
    assert tensor_identity(learner.model.state_dict()) == initial


def test_minibatch_metrics_match_same_preupdate_forward(behavior):
    cfg = config(minibatch_size=3)
    learner = Learner(new_model(style_enabled=False, state_dict=behavior.payload()['state_dict']), cfg)
    batch = prepare_batch([game(behavior)], behavior, cfg, max_decisions=10)
    # Move weights without an optimizer step to create measurable KL/clip.
    with torch.no_grad(): learner.model.policy.policy_out.weight.mul_(20)
    expected = learner.diagnostics(batch)
    metrics = learner.step(batch, [0, 1, 2])
    for key in ('kl', 'clip_fraction', 'entropy', 'normalized_entropy', 'max_ratio_error'):
        assert metrics[key] == pytest.approx(expected[key], abs=1e-12)


def test_kl_stop_does_not_apply_optimizer_or_change_weights(behavior):
    cfg = config(minibatch_size=3, target_kl=1e-8)
    learner = Learner(new_model(style_enabled=False, state_dict=behavior.payload()['state_dict']), cfg)
    batch = prepare_batch([game(behavior)], behavior, cfg, max_decisions=10)
    with torch.no_grad(): learner.model.policy.policy_out.weight.mul_(100)
    before = tensor_identity(learner.model.state_dict())
    metrics = learner.step(batch, [0, 1, 2])
    assert metrics['kl'] > cfg.target_kl and not metrics['optimizer_applied']
    assert tensor_identity(learner.model.state_dict()) == before
    assert learner.optimizer.state_dict()['state'] == {}
    assert all(p.grad is None for p in learner.model.parameters())
