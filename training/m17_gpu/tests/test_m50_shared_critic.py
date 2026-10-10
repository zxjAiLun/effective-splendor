"""Lean checks for M50 outcome-gradient routing; no arena or GPU required."""

import torch
import torch.nn.functional as F

from m50_train_mortal_actor_critic import (
    ACT_DIM,
    OBS_DIM,
    STEPS_NORM,
    MortalActorCriticNet,
    segmented_logsumexp,
)


def batch():
    torch.manual_seed(23)
    return (
        torch.rand(3, OBS_DIM),
        torch.rand(6, ACT_DIM),
        torch.tensor([0, 0, 1, 1, 2, 2]),
        torch.tensor([1.0, 0.0, 0.5]),
    )


def test_critic_gradient_switch_preserves_forward_and_checkpoint_schema():
    obs, actions, parents, outcomes = batch()
    detached = MortalActorCriticNet(hidden_dim=32, num_blocks=1)
    shared = MortalActorCriticNet(hidden_dim=32, num_blocks=1, critic_backbone_grad=True)
    shared.load_state_dict(detached.state_dict(), strict=True)
    assert detached.critic_backbone_grad is False
    assert shared.state_dict().keys() == detached.state_dict().keys()

    old_outputs = detached(obs, actions, parents)
    new_outputs = shared(obs, actions, parents)
    for old, new in zip(old_outputs, new_outputs):
        torch.testing.assert_close(new, old, rtol=0, atol=0)

    F.binary_cross_entropy_with_logits(old_outputs[1], outcomes).backward()
    F.binary_cross_entropy_with_logits(new_outputs[1], outcomes).backward()
    for name in ["entity_backbone.card_encoder.0.weight", "state_res_blocks.0.fc1.weight"]:
        assert dict(detached.named_parameters())[name].grad is None
        grad = dict(shared.named_parameters())[name].grad
        assert grad is not None and torch.isfinite(grad).all() and grad.abs().sum() > 0
    assert shared.val_head[0].weight.grad.abs().sum() > 0
    assert shared.action_net[0].weight.grad is None
    assert shared.adv_head[0].weight.grad is None


def test_shared_critic_mixed_outcome_loss_has_finite_update():
    obs, actions, parents, outcomes = batch()
    model = MortalActorCriticNet(hidden_dim=32, num_blocks=1, critic_backbone_grad=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    logits, values, steps = model(obs, actions, parents)
    lse, _ = segmented_logsumexp(logits, [2, 2, 2])
    chosen = logits[torch.tensor([0, 2, 4])]
    winners = outcomes > 0.5
    policy_loss = (lse[winners] - chosen[winners]).mean()
    critic_loss = F.binary_cross_entropy_with_logits(values, outcomes)
    steps_loss = F.smooth_l1_loss(steps[winners] / STEPS_NORM, torch.tensor([10.0]) / STEPS_NORM)
    loss = policy_loss + 0.5 * critic_loss + 0.25 * steps_loss
    assert torch.isfinite(loss)
    loss.backward()
    assert all(p.grad is None or torch.isfinite(p.grad).all() for p in model.parameters())
    before = model.entity_backbone.card_encoder[0].weight.detach().clone()
    torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
    optimizer.step()
    assert not torch.equal(before, model.entity_backbone.card_encoder[0].weight)
    assert all(torch.isfinite(p).all() for p in model.parameters())
