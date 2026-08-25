"""Unit tests for M29A-v2 Nested Residual Attention Model.

Verifies:
1. Baseline-init equality: output strictly matches D2 baseline at initialization.
2. Packed vs per-sample equality: batch packing produces numerically identical results to individual forward passes.
3. Mask invariance: invalid entities masked with False do not affect output.
4. Residual-gradient flow: backpropagation through loss computes valid non-zero gradients on attention parameters.
"""
import pytest
import torch
import torch.nn as nn
from splendor_gpu.model import ResidualBlock
from splendor_gpu.encoding import ENTITY_FEATURES, GLOBAL_FEATURES
from splendor_gpu.m29a_v2_model import NestedResidualActionEntityMixer, ENHANCED_ACTION_FEATURES

class ReferenceD2EntityMixer(nn.Module):
    """Reference D2 architecture matching m25_exp_d2.py."""
    def __init__(self, hidden_dim=192, blocks=4, dropout=0.0):
        super().__init__()
        h = hidden_dim
        self.entity_encoder = nn.Sequential(nn.Linear(ENTITY_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.entity_gate = nn.Linear(h, 1)
        self.global_encoder = nn.Sequential(nn.Linear(GLOBAL_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.mix = nn.Linear(h * 2, h)
        self.blocks = nn.Sequential(*(ResidualBlock(h, dropout) for _ in range(blocks)))
        self.norm = nn.LayerNorm(h)

        self.action_encoder = nn.Sequential(nn.Linear(ENHANCED_ACTION_FEATURES, h), nn.GELU(), nn.Linear(h, h))
        self.policy = nn.Sequential(nn.Linear(h * 3, h), nn.GELU(), nn.Linear(h, 1))
        self.value = nn.Sequential(nn.Linear(h, h), nn.GELU(), nn.Linear(h, 2), nn.Sigmoid())

    def state_embedding(self, entities, mask, global_features):
        encoded = self.entity_encoder(entities)
        gate = self.entity_gate(encoded).squeeze(-1).masked_fill(~mask, torch.finfo(encoded.dtype).min)
        weights = torch.softmax(gate, dim=-1).unsqueeze(-1)
        pooled = (encoded * weights).sum(dim=1)
        state = self.mix(torch.cat([pooled, self.global_encoder(global_features)], dim=-1))
        return self.norm(self.blocks(state))

    def forward_packed(self, entities, mask, global_features, actions, action_offsets):
        state = self.state_embedding(entities, mask, global_features)
        action = self.action_encoder(actions)
        counts = action_offsets[1:] - action_offsets[:-1]
        expanded = torch.repeat_interleave(state, counts, dim=0)
        logits = self.policy(torch.cat([expanded, action, expanded * action], dim=-1)).squeeze(-1)
        return logits, self.value(state)

def test_baseline_init_equality():
    seed = 280229
    torch.manual_seed(seed)
    d2_model = ReferenceD2EntityMixer(hidden_dim=192, blocks=4, dropout=0.0)

    torch.manual_seed(seed)
    v2_model = NestedResidualActionEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)

    # Verify D2 shared parameters are bitwise identical
    for name, p_d2 in d2_model.named_parameters():
        p_v2 = dict(v2_model.named_parameters())[name]
        assert torch.equal(p_d2, p_v2), f"Parameter mismatch for {name}"

    B = 3
    N = 25
    torch.manual_seed(42)
    entities = torch.randn(B, N, 32)
    mask = torch.ones(B, N, dtype=torch.bool)
    global_f = torch.randn(B, 40)
    actions = torch.randn(90, 59)
    offsets = torch.tensor([0, 25, 60, 90], dtype=torch.long)

    with torch.no_grad():
        d2_logits, d2_val = d2_model.forward_packed(entities, mask, global_f, actions, offsets)
        v2_logits, v2_val = v2_model.forward_packed(entities, mask, global_f, actions, offsets)

    assert torch.allclose(d2_logits, v2_logits, atol=1e-6)
    assert torch.allclose(d2_val, v2_val, atol=1e-6)

def test_packed_per_sample_equality():
    torch.manual_seed(280229)
    model = NestedResidualActionEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    model.eval()

    B = 2
    N = 25
    torch.manual_seed(100)
    entities = torch.randn(B, N, 32)
    mask = torch.ones(B, N, dtype=torch.bool)
    global_f = torch.randn(B, 40)

    act_0 = torch.randn(20, 59)
    act_1 = torch.randn(30, 59)
    actions = torch.cat([act_0, act_1], dim=0)
    offsets = torch.tensor([0, 20, 50], dtype=torch.long)

    with torch.no_grad():
        packed_logits, packed_val = model.forward_packed(entities, mask, global_f, actions, offsets)

        logits_0, val_0 = model.forward_packed(entities[0:1], mask[0:1], global_f[0:1], act_0, torch.tensor([0, 20], dtype=torch.long))
        logits_1, val_1 = model.forward_packed(entities[1:2], mask[1:2], global_f[1:2], act_1, torch.tensor([0, 30], dtype=torch.long))

    assert torch.allclose(packed_logits[:20], logits_0, atol=1e-5)
    assert torch.allclose(packed_logits[20:], logits_1, atol=1e-5)
    assert torch.allclose(packed_val[0], val_0[0], atol=1e-5)
    assert torch.allclose(packed_val[1], val_1[0], atol=1e-5)

def test_mask_invariance():
    torch.manual_seed(280229)
    model = NestedResidualActionEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    model.eval()

    B = 1
    N = 25
    entities = torch.randn(B, N, 32)
    mask = torch.ones(B, N, dtype=torch.bool)
    mask[0, 20:] = False  # Slots 20..24 are invalid

    global_f = torch.randn(B, 40)
    actions = torch.randn(15, 59)
    offsets = torch.tensor([0, 15], dtype=torch.long)

    with torch.no_grad():
        logits_orig, val_orig = model.forward_packed(entities, mask, global_f, actions, offsets)

        entities_modified = entities.clone()
        entities_modified[0, 20:] = torch.randn(5, 32) * 100.0

        logits_mod, val_mod = model.forward_packed(entities_modified, mask, global_f, actions, offsets)

    assert torch.allclose(logits_orig, logits_mod, atol=1e-5)
    assert torch.allclose(val_orig, val_mod, atol=1e-5)

def test_residual_gradient_flow():
    torch.manual_seed(280229)
    model = NestedResidualActionEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    model.train()

    B = 2
    N = 25
    entities = torch.randn(B, N, 32)
    mask = torch.ones(B, N, dtype=torch.bool)
    global_f = torch.randn(B, 40)
    actions = torch.randn(40, 59)
    offsets = torch.tensor([0, 20, 40], dtype=torch.long)
    targets = torch.softmax(torch.randn(40), dim=0)

    logits, _ = model.forward_packed(entities, mask, global_f, actions, offsets)
    loss = -(targets[:20] * torch.log_softmax(logits[:20], dim=0)).sum() - (targets[20:] * torch.log_softmax(logits[20:], dim=0)).sum()
    loss.backward()

    # Verify gradients flow into residual attention weights
    assert model.action_query_proj.weight.grad is not None
    assert model.entity_key_proj.weight.grad is not None
    assert model.entity_val_proj.weight.grad is not None
    assert model.attn_residual_head[2].weight.grad is not None
    assert model.attn_residual_head[2].weight.grad.abs().sum() > 0
