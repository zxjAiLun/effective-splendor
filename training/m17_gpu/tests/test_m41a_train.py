"""M41A trainer contract tests: split access control, initialization
equality, hierarchical (never-flattened) loss, and the shuffle hook."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splendor_gpu import m41a_train as trainer
from splendor_gpu.m41a_helpers import HEAD_INIT_SEED, TRAINER_SEED


# ---------------------------------------------------------------------------
# Split access control (power-cal hard denial)
# ---------------------------------------------------------------------------


def test_power_calibration_is_denied():
    with pytest.raises(PermissionError, match="SEALED"):
        trainer.assert_split_allowed("power-calibration")


def test_formal_is_denied():
    with pytest.raises(PermissionError):
        trainer.assert_split_allowed("formal")


def test_train_validation_allowed():
    trainer.assert_split_allowed("train")
    trainer.assert_split_allowed("validation")


def test_unknown_split_denied():
    with pytest.raises(PermissionError):
        trainer.assert_split_allowed("bogus-split")


def test_load_split_refuses_power_calibration_path():
    """Even a direct load_split('power-calibration') must fail BEFORE any
    file enumeration (the corpus exists on disk — the guard must fire)."""
    with pytest.raises(PermissionError, match="SEALED"):
        trainer.load_split("power-calibration")


# ---------------------------------------------------------------------------
# Model contracts
# ---------------------------------------------------------------------------


def _tiny_d2():
    from splendor_gpu.m31a_train import DeltaEntityMixer

    torch.manual_seed(0)
    return DeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)


def test_q_head_topology_is_frozen_contract():
    head = trainer.M41AQHead()
    layers = list(head.net)
    assert isinstance(layers[0], nn.Linear) and layers[0].in_features == 576
    assert layers[0].out_features == 192
    assert isinstance(layers[1], nn.GELU)
    assert isinstance(layers[2], nn.Linear) and layers[2].in_features == 192
    assert layers[2].out_features == 1


def test_f_arm_freezes_encoders_u_arm_trains_them():
    d2 = _tiny_d2()
    torch.manual_seed(HEAD_INIT_SEED)
    q = trainer.M41AQHead()
    f = trainer.M41AArm(d2, q, freeze_encoders=True)
    trainable_f = {n for n, p in f.named_parameters() if p.requires_grad}
    assert trainable_f and all(n.startswith("q_head.") for n in trainable_f)
    assert all(not p.requires_grad for n, p in f.named_parameters()
               if n.startswith(("policy.", "value.")))

    d2b = _tiny_d2()
    torch.manual_seed(HEAD_INIT_SEED)
    qb = trainer.M41AQHead()
    u = trainer.M41AArm(d2b, qb, freeze_encoders=False)
    trainable_u = {n for n, p in u.named_parameters() if p.requires_grad}
    assert trainable_u and all(not n.startswith(("policy.", "value.")) for n in trainable_u)
    # U trains encoders AND q-head.
    assert any(not n.startswith("q_head.") for n in trainable_u)
    # Policy/value never trainable in either arm.
    assert all(not p.requires_grad for n, p in u.named_parameters()
               if n.startswith(("policy.", "value.")))


def test_q_head_single_draw_bit_copies():
    """ONE draw from HEAD_INIT_SEED, bit-identical across arms."""
    torch.manual_seed(HEAD_INIT_SEED)
    a = trainer.M41AQHead()
    torch.manual_seed(HEAD_INIT_SEED)
    b = trainer.M41AQHead()
    for k in a.state_dict():
        assert torch.equal(a.state_dict()[k], b.state_dict()[k])


def test_arm_construction_restores_requires_grad_regardless_of_order():
    """Regression (the P0 of the first formal run): building F (freeze)
    over shared D2 modules and THEN building U must leave U's encoders
    TRAINABLE — the constructor owns its requires_grad state, so arm
    order can never leak a frozen state into the other arm. (Each arm
    receives its own module copy in production; the shared-module
    variant here pins the constructor's explicit ownership.)"""
    d2 = _tiny_d2()
    torch.manual_seed(HEAD_INIT_SEED)
    q = trainer.M41AQHead()
    f = trainer.M41AArm(d2, q, freeze_encoders=True)
    # Same underlying modules now feed U — requires_grad must be
    # explicitly restored for U's construction to be valid.
    u = trainer.M41AArm(d2, q, freeze_encoders=False)
    encoder_prefixes = ("entity_encoder.", "entity_gate.", "global_encoder.",
                        "mix.", "blocks.", "norm.", "action_encoder.")
    for name, p in u.named_parameters():
        if name.startswith(encoder_prefixes):
            assert p.requires_grad, f"U encoder {name} must be trainable"
    # Production arms never share modules (train_arm deep-copies), so F's
    # frozen state is asserted on F's OWN copy:
    d2_f = _tiny_d2()
    torch.manual_seed(HEAD_INIT_SEED)
    q_f = trainer.M41AQHead()
    f_own = trainer.M41AArm(d2_f, q_f, freeze_encoders=True)
    for name, p in f_own.named_parameters():
        if name.startswith(encoder_prefixes):
            assert not p.requires_grad, f"F encoder {name} must be frozen"


def test_train_arm_deep_copies_do_not_leak_across_arms():
    """train_arm's F run must not mutate the tensors U starts from (the
    second formal-run bug class: shared q_head object)."""
    import copy

    d2 = _tiny_d2()
    torch.manual_seed(HEAD_INIT_SEED)
    q = trainer.M41AQHead()
    q_head_state = {k: v.clone() for k, v in q.state_dict().items()}
    d2_snapshot = {k: v.clone() for k, v in d2.state_dict().items()}

    # A minimal fake game drives one optimizer step.
    fake_game = [{
        "states": [{
            "ply": 0,
            "observation": None,  # unused: encode is monkeypatched
            "actions": [{"type": "pass"}, {"type": "pass"}],
            "returns": [1.0, -1.0],
        }]
    }]

    import splendor_gpu.m41a_train as tr

    class _FakeEncoded:
        def __init__(self, n):
            self.entities = torch.zeros(n, 31, 32)
            self.mask = torch.ones(n, 31, dtype=torch.bool)
            self.globals = torch.zeros(n, 40)
            self.actions = torch.zeros(2 * n, 59)
            self.offsets = torch.arange(0, 2 * n + 1, 2)
            self.game_boundaries = [(0, n)]
            self.targets = torch.randn(2 * n)

        def astuple(self):
            return (self.entities, self.mask, self.globals, self.actions,
                    self.offsets, self.game_boundaries, self.targets)

    original_encode = tr.encode_states
    tr.encode_states = lambda games, catalog, device: _FakeEncoded(
        sum(len(g["states"]) for g in games)
    ).astuple()
    original_epochs = tr.EPOCHS
    original_batch = tr.BATCH_GAMES
    tr.EPOCHS = 1
    tr.BATCH_GAMES = 1
    try:
        result = tr.train_arm("F", fake_game, [], None, torch.device("cpu"), d2, q_head_state)
        # F trained its q-head; U's starting tensors must be untouched.
        assert not torch.equal(
            result["checkpoint"]["q_head_state"]["net.0.weight"],
            q_head_state["net.0.weight"],
        ), "F's q-head must have moved from the initial draw"
        assert all(torch.equal(d2.state_dict()[k], d2_snapshot[k]) for k in d2_snapshot), (
            "F training must not mutate the D2 encoders (frozen)"
        )
    finally:
        tr.encode_states = original_encode
        tr.EPOCHS = original_epochs
        tr.BATCH_GAMES = original_batch


# ---------------------------------------------------------------------------
# Hierarchical loss (never flattened; prediction ALWAYS legal-set centered)
# ---------------------------------------------------------------------------


def test_state_only_annihilation():
    """Test A (P3 Repair 1): a state-only model f(o,a)=c(o) must yield
    A_theta == 0 for EVERY constant — centering annihilates the
    state-only path exactly, regardless of the constant's value."""
    targets = torch.tensor([1.5, -0.5, -0.5, -0.5])
    offsets = torch.tensor([0, 4])
    boundaries = [(0, 1)]
    for c in (-100.0, -1.0, 0.0, 7.0, 100.0):
        raw = torch.full((4,), c)
        loss = trainer.hierarchical_loss(raw, offsets, boundaries, targets)
        expected = nn.functional.huber_loss(
            torch.zeros(4), targets, reduction="mean", delta=1.0
        )
        assert torch.allclose(loss, expected, atol=1e-7), (
            f"constant {c}: centered loss must equal Huber(0, target)"
        )


def test_centering_contract_exact_manual():
    """Test B (P3 Repair 1): raw = [2, 4, 8] must enter the Huber as the
    centered [-8/3, -2/3, 10/3] — NOT the raw scores."""
    raw = torch.tensor([2.0, 4.0, 8.0])
    targets = torch.tensor([1.0, -1.0, 0.0])
    offsets = torch.tensor([0, 3])
    boundaries = [(0, 1)]
    got = trainer.hierarchical_loss(raw, offsets, boundaries, targets)
    centered = torch.tensor([-8.0 / 3.0, -2.0 / 3.0, 10.0 / 3.0])
    want = nn.functional.huber_loss(centered, targets, reduction="mean", delta=1.0)
    assert torch.allclose(got, want, atol=1e-6)
    # And it must NOT equal the raw-score Huber (the VOID-2 objective).
    wrong = nn.functional.huber_loss(raw, targets, reduction="mean", delta=1.0)
    assert not torch.allclose(got, wrong, atol=1e-3), (
        "centered objective must differ from the raw objective on this fixture"
    )


def test_regression_centered_vs_raw_objectives_differ():
    """Test C (P3 Repair 1): the regression that catches VOID-2. With an
    asymmetric centered target, the state-only scalar that minimizes the
    RAW Huber is NOT zero — so Huber(raw, target) != Huber(center(raw),
    target) for the raw-optimal constant, proving this test would have
    failed against the 601dc61 implementation."""
    # Asymmetric centered targets: mean != 0.
    targets = torch.tensor([1.0, -1.0, -1.5, -1.0])
    mean_target = targets.mean().item()
    assert abs(mean_target) > 0.05, "fixture must be genuinely asymmetric"
    offsets = torch.tensor([0, 4])
    boundaries = [(0, 1)]
    # The raw-objective state-only optimum: find the constant c that
    # minimizes Huber(c, targets) (scalar search).
    best_c, best_loss = None, float("inf")
    for c in [x * 0.01 for x in range(-300, 301)]:
        loss = float(nn.functional.huber_loss(
            torch.full((4,), c), targets, reduction="mean", delta=1.0
        ))
        if loss < best_loss:
            best_loss, best_c = loss, c
    # At the raw-optimal constant, the CENTERED objective must be the
    # (higher) zero-prediction loss — the two objectives genuinely
    # disagree, i.e. the centered objective forbids the bias escape.
    raw_opt = torch.full((4,), best_c)
    centered_loss = trainer.hierarchical_loss(raw_opt, offsets, boundaries, targets)
    zero_loss = nn.functional.huber_loss(
        torch.zeros(4), targets, reduction="mean", delta=1.0
    )
    assert torch.allclose(centered_loss, zero_loss, atol=1e-6), (
        "centering must annihilate ANY constant, including the raw-objective optimum"
    )
    assert best_loss < float(zero_loss) - 1e-4, (
        "fixture sanity: the raw objective must reward the bias escape "
        "(this is exactly the VOID-2 escape the design forbids)"
    )


def test_hierarchical_loss_matches_manual_computation():
    """Two games: game 1 has two states (2 and 2 legal actions), game 2
    has one state (1 legal action). The hierarchical mean must equal the
    manual per-state-centered -> per-game -> batch computation, and MUST
    differ from the flattened branch mean."""
    q_raw = torch.tensor([0.1, -0.2, 0.3, 0.4, -0.5], requires_grad=True)
    targets = torch.tensor([1.0, -1.0, 0.5, -0.5, 0.0])
    offsets = torch.tensor([0, 2, 4, 5])
    game_boundaries = [(0, 2), (2, 3)]

    got = trainer.hierarchical_loss(q_raw, offsets, game_boundaries, targets)

    huber = nn.functional.huber_loss
    # game 1 (state-centered predictions)
    s1_raw = q_raw[0:2]
    s2_raw = q_raw[2:4]
    a1 = s1_raw - s1_raw.mean()
    a2 = s2_raw - s2_raw.mean()
    s1 = huber(a1, targets[0:2], reduction="mean", delta=1.0)
    s2 = huber(a2, targets[2:4], reduction="mean", delta=1.0)
    g1 = (s1 + s2) / 2
    # game 2: a single action centers to exactly 0.
    g2 = huber(torch.zeros(1), targets[4:5], reduction="mean", delta=1.0)
    want = (g1 + g2) / 2
    assert torch.allclose(got, want, atol=1e-7)

    # And the flattened mean over the 5 branches would weight the
    # single-action game differently.
    flat = huber(q_raw, targets, reduction="mean", delta=1.0)
    assert not torch.allclose(got, flat), (
        "hierarchical loss must not equal the flattened branch mean"
    )


def test_hierarchical_loss_legal_set_size_weighting():
    """A state with 30 actions must contribute exactly as much as a state
    with 2 actions (per-state mean, then per-game mean)."""
    q_big = torch.randn(30)
    t_big = torch.randn(30)
    q_small = torch.randn(2)
    t_small = torch.randn(2)
    # one game, two states
    q = torch.cat([q_big, q_small])
    t = torch.cat([t_big, t_small])
    offsets = torch.tensor([0, 30, 32])
    boundaries = [(0, 2)]
    got = trainer.hierarchical_loss(q, offsets, boundaries, t)
    a_big = q_big - q_big.mean()
    a_small = q_small - q_small.mean()
    s_big = nn.functional.huber_loss(a_big, t_big, reduction="mean", delta=1.0)
    s_small = nn.functional.huber_loss(a_small, t_small, reduction="mean", delta=1.0)
    want = (s_big + s_small) / 2
    assert torch.allclose(got, want, atol=1e-6)
    # The flattened version would weight the big state 15x.
    flat = nn.functional.huber_loss(q, t, reduction="mean", delta=1.0)
    assert not torch.allclose(got, flat, atol=1e-3)


# ---------------------------------------------------------------------------
# Trainer constants (frozen contract)
# ---------------------------------------------------------------------------


def test_frozen_training_constants():
    assert trainer.EPOCHS == 16
    assert trainer.BATCH_GAMES == 32
    assert trainer.LR == 1e-4
    assert trainer.WEIGHT_DECAY == 1e-4
    assert trainer.BETAS == (0.9, 0.999)
    assert trainer.EPS == 1e-8
    assert trainer.GRAD_CLIP == 1.0
    assert HEAD_INIT_SEED == 40_261_001
    assert TRAINER_SEED == 40_261_002
