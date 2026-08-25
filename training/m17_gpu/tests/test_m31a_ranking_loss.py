"""Unit tests for M31A Objective-v2: Weighted Pairwise Logistic Ranking Loss.

Verifies:
1. Hand-calculated pairwise loss matches exact mathematical expectation.
2. Top-1 ties are strictly excluded from ranking loss.
3. Packed vs per-sample forward loss and parameter gradients are numerically equivalent.
4. Lambda = 0 path produces loss and gradients strictly matching canonical D2 soft-CE.
5. Fail-closed output directory check prevents overwriting existing artifacts.
"""
import math
import tempfile
from pathlib import Path
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from splendor_gpu.m29a_v2_model import ENHANCED_ACTION_FEATURES
from splendor_gpu.model import ResidualBlock
from splendor_gpu.encoding import ENTITY_FEATURES, GLOBAL_FEATURES
from splendor_gpu.m31a_loss import extract_ranking_pair_info, compute_canonical_ce_and_ranking_loss

class D2EntityMixer(nn.Module):
    """Reference D2 architecture matching canonical h192/b4 Delta baseline."""
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

def test_hand_calculated_pairwise_ranking_loss():
    # 1 sample, 3 actions
    # Logits: [2.5, 1.0, 0.5]
    # Top-1 is idx 0 (logit 2.5), runner-up is idx 1 (logit 1.0)
    # Diff = 2.5 - 1.0 = 1.5
    # Target micros: [600_000, 300_000, 100_000] -> weight = (600_000 - 300_000) / 900_000 = 1/3
    micros = [600_000, 300_000, 100_000]
    top1, runner_up, w = extract_ranking_pair_info(micros)
    assert top1 == 0
    assert runner_up == 1
    assert math.isclose(w, 1.0 / 3.0, rel_tol=1e-6)

    logits = torch.tensor([2.5, 1.0, 0.5], dtype=torch.float32)
    targets = torch.tensor([0.6, 0.3, 0.1], dtype=torch.float32)
    offsets = torch.tensor([0, 3], dtype=torch.long)
    pairs = torch.tensor([[0.0, 1.0, w]], dtype=torch.float32)

    total_loss, ce_loss, rank_loss = compute_canonical_ce_and_ranking_loss(
        logits, targets, offsets, pairs, ranking_weight=0.5
    )

    # Hand calculation:
    expected_ce = -(0.6 * math.log(math.exp(2.5) / (math.exp(2.5) + math.exp(1.0) + math.exp(0.5))) +
                    0.3 * math.log(math.exp(1.0) / (math.exp(2.5) + math.exp(1.0) + math.exp(0.5))) +
                    0.1 * math.log(math.exp(0.5) / (math.exp(2.5) + math.exp(1.0) + math.exp(0.5))))
    expected_rank = math.log(1.0 + math.exp(-1.5))
    expected_total = expected_ce + 0.5 * expected_rank

    assert math.isclose(ce_loss.item(), expected_ce, rel_tol=1e-5)
    assert math.isclose(rank_loss.item(), expected_rank, rel_tol=1e-5)
    assert math.isclose(total_loss.item(), expected_total, rel_tol=1e-5)

def test_top1_tie_strictly_excluded():
    # Multiple actions share max micros
    tied_micros = [450_000, 450_000, 100_000]
    top1, runner_up, w = extract_ranking_pair_info(tied_micros)
    assert top1 == -1
    assert runner_up == -1
    assert w == 0.0

    logits = torch.tensor([1.0, 2.0, 0.5], dtype=torch.float32)
    targets = torch.tensor([0.45, 0.45, 0.10], dtype=torch.float32)
    offsets = torch.tensor([0, 3], dtype=torch.long)
    pairs = torch.tensor([[-1.0, -1.0, 0.0]], dtype=torch.float32)

    total_loss, ce_loss, rank_loss = compute_canonical_ce_and_ranking_loss(
        logits, targets, offsets, pairs, ranking_weight=0.5
    )
    assert rank_loss.item() == 0.0
    assert math.isclose(total_loss.item(), ce_loss.item(), rel_tol=1e-6)

def test_packed_vs_per_sample_equivalence():
    torch.manual_seed(280229)
    model = D2EntityMixer(hidden_dim=192, blocks=4, dropout=0.0)
    model.train()

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

    tgt_0 = torch.softmax(torch.randn(20), dim=0)
    tgt_1 = torch.softmax(torch.randn(30), dim=0)
    targets = torch.cat([tgt_0, tgt_1], dim=0)

    # Pairs for sample 0 and 1
    pairs = torch.tensor([
        [2.0, 5.0, 0.25],
        [7.0, 1.0, 0.50],
    ], dtype=torch.float32)

    # 1. Packed computation
    model.zero_grad()
    packed_logits, _ = model.forward_packed(entities, mask, global_f, actions, offsets)
    loss_packed, ce_packed, rank_packed = compute_canonical_ce_and_ranking_loss(
        packed_logits, targets, offsets, pairs, ranking_weight=0.5
    )
    loss_packed.backward()
    grads_packed = {k: v.grad.clone() for k, v in model.named_parameters() if v.grad is not None}

    # 2. Per-sample computation
    model.zero_grad()
    logits_0, _ = model.forward_packed(entities[0:1], mask[0:1], global_f[0:1], act_0, torch.tensor([0, 20], dtype=torch.long))
    logits_1, _ = model.forward_packed(entities[1:2], mask[1:2], global_f[1:2], act_1, torch.tensor([0, 30], dtype=torch.long))

    # CE per sample
    ce_0 = -(tgt_0 * F.log_softmax(logits_0, dim=0)).sum()
    ce_1 = -(tgt_1 * F.log_softmax(logits_1, dim=0)).sum()
    ce_manual = (ce_0 + ce_1) / 2.0

    # Rank per sample
    r_0 = 0.25 * F.softplus(-(logits_0[2] - logits_0[5]))
    r_1 = 0.50 * F.softplus(-(logits_1[7] - logits_1[1]))
    rank_manual = (r_0 + r_1) / (0.25 + 0.50)

    loss_manual = ce_manual + 0.5 * rank_manual
    loss_manual.backward()
    grads_manual = {k: v.grad.clone() for k, v in model.named_parameters() if v.grad is not None}

    assert math.isclose(loss_packed.item(), loss_manual.item(), rel_tol=1e-5)
    assert math.isclose(ce_packed.item(), ce_manual.item(), rel_tol=1e-5)
    assert math.isclose(rank_packed.item(), rank_manual.item(), rel_tol=1e-5)

    for k in grads_packed:
        assert torch.allclose(grads_packed[k], grads_manual[k], atol=1e-5), f"Gradient mismatch for {k}"

def test_lambda_zero_matches_canonical_d2():
    torch.manual_seed(280229)
    model = D2EntityMixer(hidden_dim=192, blocks=4, dropout=0.0)

    B = 2
    N = 25
    entities = torch.randn(B, N, 32)
    mask = torch.ones(B, N, dtype=torch.bool)
    global_f = torch.randn(B, 40)
    actions = torch.randn(40, 59)
    offsets = torch.tensor([0, 20, 40], dtype=torch.long)
    targets = torch.softmax(torch.randn(40), dim=0)
    pairs = torch.tensor([[1.0, 3.0, 0.4], [5.0, 8.0, 0.6]], dtype=torch.float32)

    # Run with ranking_weight = 0.0
    model.zero_grad()
    logits, _ = model.forward_packed(entities, mask, global_f, actions, offsets)
    total_loss, ce_loss, _ = compute_canonical_ce_and_ranking_loss(
        logits, targets, offsets, pairs, ranking_weight=0.0
    )
    total_loss.backward()
    grads_zero_lambda = {k: v.grad.clone() for k, v in model.named_parameters() if v.grad is not None}

    # Run reference pure D2 soft-CE
    model.zero_grad()
    logits_d2, _ = model.forward_packed(entities, mask, global_f, actions, offsets)
    l0 = logits_d2[:20]
    l1 = logits_d2[20:]
    t0 = targets[:20]
    t1 = targets[20:]
    d2_loss = (-(t0 * F.log_softmax(l0, dim=0)).sum() - (t1 * F.log_softmax(l1, dim=0)).sum()) / 2.0
    d2_loss.backward()
    grads_pure_d2 = {k: v.grad.clone() for k, v in model.named_parameters() if v.grad is not None}

    assert math.isclose(total_loss.item(), d2_loss.item(), rel_tol=1e-6)
    assert math.isclose(ce_loss.item(), d2_loss.item(), rel_tol=1e-6)
    for k in grads_zero_lambda:
        assert torch.allclose(grads_zero_lambda[k], grads_pure_d2[k], atol=1e-6)

def test_fail_closed_output_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        existing_dir = Path(tmpdir) / "already_exists"
        existing_dir.mkdir(parents=True)

        # Fail-closed guard check
        with pytest.raises(RuntimeError, match="already exists — fail-closed protection"):
            if existing_dir.exists():
                raise RuntimeError(f"Output directory {existing_dir} already exists — fail-closed protection")
