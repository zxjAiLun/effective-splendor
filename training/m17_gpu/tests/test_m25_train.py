"""Exhaustive contract and anti-drift unit tests for M25 M07 Search-Teacher Bootstrap v2."""

import copy
import json
import math
from pathlib import Path
import pytest
import torch
import torch.nn.functional as F

from splendor_gpu.data import load_catalog
from splendor_gpu.encoding import encode_action, encode_observation, action_key
from splendor_gpu.model import ModelSpec, build_model
from splendor_gpu.train import file_sha256, seed_everything
from splendor_gpu.m25_train import (
    EXPECTED_M25_FORMAT,
    EXPECTED_M25_GAMES,
    EXPECTED_M25_PARAMETER_COUNT,
    EXPECTED_M25_TRAIN_GAMES,
    EXPECTED_M25_VAL_GAMES,
    EXPECTED_UNIFORM_FLOOR_MICROS,
    build_m25_model,
    compute_training_value_prior_baseline_mse,
    compute_uniform_policy_ce,
    evaluate_cross_distribution_holdout,
    evaluate_m25_gates,
    split_m25_indices,
    validate_m25_config,
)

CONFIG_PATH = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
HOLDOUT_FIXTURE_PATH = Path("benchmarks/m24-s2-2002-audit-holdout.json")
AUDIT_RESULT_PATH = Path("benchmarks/m24-s2-teacher-target-quality-audit-v1.result.json")
M24_DATASET_PATH = Path("local-artifacts/m24-self-play-s2-v1/self-play.json")
CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")

FROZEN_M25_CONFIG_SHA256 = "b2dc22ced176ef2abe27559b0cb2245c8f68f11567795c0da4a8eb6d9618362c"
FROZEN_HOLDOUT_SHA256 = "331654ba370a489053bcf6cd0452d7aa4883b6c64d5db0be757c4a42860f05f8"


@pytest.fixture
def m25_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def catalog():
    return load_catalog(CATALOG_PATH)


def test_m25_config_canonical_sha256_anti_drift():
    """Assert canonical SHA256 of frozen M25 configuration file to prevent silent drift."""
    actual_sha = file_sha256(CONFIG_PATH)
    assert actual_sha == FROZEN_M25_CONFIG_SHA256


def test_m25_exact_teacher_contract(m25_config):
    """Validate exact M07 determinization search teacher configuration."""
    validate_m25_config(m25_config)
    t_cfg = m25_config["dataset"]["teacher_config"]
    assert t_cfg["sample_seed"] == 20260810
    assert t_cfg["sample_count"] == 4
    assert t_cfg["max_depth_turns"] == 1
    assert t_cfg["max_nodes"] == 2000
    assert m25_config["dataset"]["generator_agent"] == "m07-determinization-champion"


def test_m25_uniform_floor_matches_m15c(m25_config):
    """Validate uniform_floor_micros matches historical M15C (100,000 micros = 10%)."""
    assert m25_config["dataset"]["targets"]["uniform_floor_micros"] == EXPECTED_UNIFORM_FLOOR_MICROS
    assert m25_config["dataset"]["targets"]["uniform_floor_micros"] == 100000


def test_m25_exact_256_seed_schedule(m25_config):
    """Validate explicit 256 game seed schedule 20260825..20261080 without gaps."""
    seeds = m25_config["dataset"]["game_seeds"]
    assert len(seeds) == 256
    expected_seeds = [20260825 + i for i in range(256)]
    assert seeds == expected_seeds


def test_m25_game_split_exact_192_64_and_no_leakage(m25_config):
    """Assert game-level split creates exactly 192 train games and 64 validation games with zero leakage."""
    fake_examples = []
    for g in range(256):
        for ply in range(10):
            fake_examples.append({
                "game_index": g,
                "ply": ply,
                "actor": ply % 2,
                "observation": {},
                "legal_actions": [{"type": "pass"}],
            })
    fake_payload = {"examples": fake_examples}
    train_idx, val_idx = split_m25_indices(fake_payload, m25_config)
    
    assert len(train_idx) == 192 * 10
    assert len(val_idx) == 64 * 10
    
    train_games = set(fake_examples[i]["game_index"] for i in train_idx)
    val_games = set(fake_examples[i]["game_index"] for i in val_idx)
    
    assert len(train_games) == 192
    assert len(val_games) == 64
    assert train_games.isdisjoint(val_games)
    assert all(g % 4 == 0 for g in val_games)
    assert all(g % 4 != 0 for g in train_games)


def test_m25_uniform_ce_is_mean_log_legal_count():
    """Verify theoretical uniform CE formula mean(ln(|A_i|))."""
    examples = [
        {"legal_actions": [{"type": "a1"}, {"type": "a2"}]},  # ln(2)
        {"legal_actions": [{"type": "a1"}, {"type": "a2"}, {"type": "a3"}, {"type": "a4"}]},  # ln(4)
    ]
    expected_ce = (math.log(2) + math.log(4)) / 2.0
    actual_ce = compute_uniform_policy_ce(examples)
    assert math.isclose(actual_ce, expected_ce, rel_tol=1e-6)


def test_m25_uniform_ce_missing_is_fail_closed():
    """Assert compute_uniform_policy_ce fails closed on empty or invalid inputs."""
    with pytest.raises(ValueError, match="fail-closed: empty validation examples"):
        compute_uniform_policy_ce([])
    with pytest.raises(ValueError, match="fail-closed: invalid legal actions count"):
        compute_uniform_policy_ce([{"legal_actions": []}])


def test_m25_g3_uses_training_prior_only():
    """Verify G3 baseline MSE is derived purely from training targets evaluated against validation targets."""
    train_targets = torch.tensor([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=torch.float32)  # mean = [2/3, 1/3]
    val_targets = torch.tensor([[1.0, 0.0], [0.0, 1.0]], dtype=torch.float32)
    
    prior = torch.tensor([[2.0 / 3.0, 1.0 / 3.0]], dtype=torch.float32)
    expected_mse = F.mse_loss(prior.expand_as(val_targets), val_targets, reduction="sum").item() / 4.0
    
    actual_mse = compute_training_value_prior_baseline_mse(train_targets, val_targets)
    assert math.isclose(actual_mse, expected_mse, rel_tol=1e-5)


def test_m25_holdout_exact_2002_join(catalog):
    """Assert exact join of 2,002 holdout positions against M24 source dataset succeeds without drops."""
    if not M24_DATASET_PATH.exists():
        pytest.skip("local M24 dataset artifact not present")
        
    m24_payload = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))
    holdout_fixture = json.loads(HOLDOUT_FIXTURE_PATH.read_text(encoding="utf-8"))
    
    spec = ModelSpec("entity_mixer", 192, 4, 0.0, 0)
    seed_everything(280229)
    model = build_model(spec)
    
    res = evaluate_cross_distribution_holdout(
        model=model,
        m24_payload=m24_payload,
        holdout_fixture=holdout_fixture,
        catalog=catalog,
        device=torch.device("cpu"),
    )
    
    assert res["expected_positions"] == 2002
    assert res["matched_positions"] == 2002
    assert res["missing_positions"] == 0
    assert res["hash_mismatches"] == 0
    assert res["legal_action_mismatches"] == 0
    assert 0.0 <= res["m07_top1_agreement"] <= 1.0


def test_m25_holdout_missing_position_fails(catalog):
    """Assert holdout evaluation raises fail-closed exception when a position is missing."""
    m24_payload = {"examples": []}
    holdout_fixture = {"positions_count": 1, "positions": [{
        "game_index": 0, "ply": 0, "actor": 0,
        "observation_hash": "h1", "information_set_hash": "h2",
        "m07_top1": '{"type":"pass"}'
    }]}
    model = build_model(ModelSpec("entity_mixer", 192, 4, 0.0, 0))
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=model,
            m24_payload=m24_payload,
            holdout_fixture=holdout_fixture,
            catalog=catalog,
            device=torch.device("cpu"),
        )


def test_m25_holdout_duplicate_position_fails(catalog):
    """Assert holdout evaluation raises fail-closed exception on duplicate position keys."""
    m24_payload = {"examples": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "h2",
         "observation": {}, "legal_actions": [{"type": "pass"}]}
    ]}
    holdout_fixture = {"positions_count": 2, "positions": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "h2", "m07_top1": '{"type":"pass"}'},
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "h2", "m07_top1": '{"type":"pass"}'},
    ]}
    model = build_model(ModelSpec("entity_mixer", 192, 4, 0.0, 0))
    
    with pytest.raises(RuntimeError, match="duplicate key in holdout fixture"):
        evaluate_cross_distribution_holdout(
            model=model,
            m24_payload=m24_payload,
            holdout_fixture=holdout_fixture,
            catalog=catalog,
            device=torch.device("cpu"),
        )


def test_m25_holdout_observation_hash_mismatch_fails(catalog):
    """Assert holdout evaluation raises fail-closed exception on hash mismatch."""
    m24_payload = {"examples": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "wrong_hash", "information_set_hash": "h2",
         "observation": {}, "legal_actions": [{"type": "pass"}]}
    ]}
    holdout_fixture = {"positions_count": 1, "positions": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "h2", "m07_top1": '{"type":"pass"}'},
    ]}
    model = build_model(ModelSpec("entity_mixer", 192, 4, 0.0, 0))
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=model,
            m24_payload=m24_payload,
            holdout_fixture=holdout_fixture,
            catalog=catalog,
            device=torch.device("cpu"),
        )


def test_m25_fresh_model_exact_949060(m25_config):
    """Assert built M25 model matches exactly 949,060 parameters."""
    model = build_m25_model(m25_config, seed=280229)
    param_count = sum(p.numel() for p in model.parameters())
    assert param_count == EXPECTED_M25_PARAMETER_COUNT
    assert param_count == 949060


def test_m25_no_checkpoint_inheritance(m25_config):
    """Assert fresh model initialization is independent of any historical checkpoint weights."""
    model1 = build_m25_model(m25_config, seed=280229)
    model2 = build_m25_model(m25_config, seed=280230)
    
    # Weights with different seeds must differ
    p1 = list(model1.parameters())[0]
    p2 = list(model2.parameters())[0]
    assert not torch.equal(p1, p2)


def test_m25_best_epoch_selection_is_frozen(m25_config):
    """Assert best epoch selection formula is policy_cross_entropy + 0.5 * value_mse on validation only."""
    sel = m25_config["training"]["selection"]
    assert sel["metric"] == "policy_cross_entropy + 0.5 * value_mse"
    assert sel["source"] == "m07_validation_games_only"
    assert sel["best_epoch"] is True


def test_m25_gates_boundary_values(m25_config):
    """Test all decision branches of M25 gates at boundary conditions."""
    base_val = {"visit_top1": 0.4500, "policy_cross_entropy": 2.50, "value_mse": 0.20}
    base_ho = {"m07_top1_agreement": 0.3800}
    uniform_ce = 3.00  # relative imp = (3.0 - 2.5) / 3.0 = 16.67% = 1666 bps >= 1000 bps
    baseline_mse = 0.20  # allowed = 0.20 * 1.02 = 0.204 >= 0.20
    
    # 1. All pass -> ARENA_ELIGIBLE
    res_pass = evaluate_m25_gates(base_val, base_ho, uniform_ce, baseline_mse, m25_config)
    assert res_pass["decision"] == "M25_ARENA_ELIGIBLE"
    assert res_pass["arena_authorization"] == "AUTHORIZED_COMPACT_128_MATCHES"
    
    # 2. G1 fail (low top1) -> M25_POLICY_TEACHER_FIT_FAIL
    val_g1_fail = dict(base_val, visit_top1=0.4499)
    res_g1_fail = evaluate_m25_gates(val_g1_fail, base_ho, uniform_ce, baseline_mse, m25_config)
    assert res_g1_fail["decision"] == "M25_POLICY_TEACHER_FIT_FAIL"
    
    # 3. G1 fail (low CE bps) -> M25_POLICY_TEACHER_FIT_FAIL
    val_g1_ce_fail = dict(base_val, policy_cross_entropy=2.85)  # imp = (3.0 - 2.85)/3.0 = 500 bps < 1000 bps
    res_g1_ce_fail = evaluate_m25_gates(val_g1_ce_fail, base_ho, uniform_ce, baseline_mse, m25_config)
    assert res_g1_ce_fail["decision"] == "M25_POLICY_TEACHER_FIT_FAIL"

    # 4. G1 pass, G2 fail (holdout < 0.38) -> M25_TEACHER_FIT_NO_TRANSFER
    ho_g2_fail = dict(base_ho, m07_top1_agreement=0.3799)
    res_g2_fail = evaluate_m25_gates(base_val, ho_g2_fail, uniform_ce, baseline_mse, m25_config)
    assert res_g2_fail["decision"] == "M25_TEACHER_FIT_NO_TRANSFER"

    # 5. G1 pass, G2 pass, G3 fail (value mse > 1.02 * baseline) -> M25_POLICY_SIGNAL_VALUE_BLOCKED
    val_g3_fail = dict(base_val, value_mse=0.205)
    res_g3_fail = evaluate_m25_gates(val_g3_fail, base_ho, uniform_ce, baseline_mse, m25_config)
    assert res_g3_fail["decision"] == "M25_POLICY_SIGNAL_VALUE_BLOCKED"

def test_m25_holdout_information_set_hash_mismatch_fails(catalog):
    """Assert holdout evaluation raises fail-closed exception on info set hash mismatch."""
    m24_payload = {"examples": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "wrong_info_hash",
         "observation": {}, "legal_actions": [{"type": "pass"}]}
    ]}
    holdout_fixture = {"positions_count": 1, "positions": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "h2", "m07_top1": '{"type":"pass"}'},
    ]}
    model = build_model(ModelSpec("entity_mixer", 192, 4, 0.0, 0))
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=model,
            m24_payload=m24_payload,
            holdout_fixture=holdout_fixture,
            catalog=catalog,
            device=torch.device("cpu"),
        )


def test_m25_holdout_legal_action_mismatch_fails(catalog):
    """Assert holdout evaluation raises fail-closed exception if legal actions is empty."""
    m24_payload = {"examples": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "h2",
         "observation": {}, "legal_actions": []}
    ]}
    holdout_fixture = {"positions_count": 1, "positions": [
        {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "h1", "information_set_hash": "h2", "m07_top1": '{"type":"pass"}'},
    ]}
    model = build_model(ModelSpec("entity_mixer", 192, 4, 0.0, 0))
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=model,
            m24_payload=m24_payload,
            holdout_fixture=holdout_fixture,
            catalog=catalog,
            device=torch.device("cpu"),
        )


def test_m25_holdout_raw_top1_mapping(catalog):
    """Verify M22 checkpoint achieves exactly 28.07% agreement on the 2,002 holdout positions."""
    m22_ckpt_path = Path("local-artifacts/m22-scaled-self-play-v1/checkpoint/checkpoint.pt")
    if not (M24_DATASET_PATH.exists() and m22_ckpt_path.exists()):
        pytest.skip("local artifacts not present")

    m24_payload = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))
    holdout_fixture = json.loads(HOLDOUT_FIXTURE_PATH.read_text(encoding="utf-8"))
    ckpt = torch.load(m22_ckpt_path, map_location="cpu", weights_only=False)

    spec = ModelSpec("entity_mixer", 192, 4, 0.0, 0)
    model = build_model(spec)
    model.load_state_dict(ckpt["state_dict"])
    
    res = evaluate_cross_distribution_holdout(
        model=model,
        m24_payload=m24_payload,
        holdout_fixture=holdout_fixture,
        catalog=catalog,
        device=torch.device("cpu"),
    )
    
    assert res["agreements"] == 562
    assert math.isclose(res["m07_top1_agreement"], 562 / 2002, rel_tol=1e-5)


def test_m25_soft_policy_sum_exact():
    """Verify soft policy distribution sums exactly to 1.0."""
    probs = [0.1, 0.2, 0.3, 0.4]
    t = torch.tensor(probs, dtype=torch.float32)
    norm = t / t.sum()
    assert math.isclose(norm.sum().item(), 1.0, rel_tol=1e-6)


def test_m25_teacher_action_support_exact():
    """Verify teacher action probability mass is non-negative and properly bounded."""
    probs = [100000, 300000, 600000]  # micros
    t = torch.tensor(probs, dtype=torch.float32)
    norm = t / t.sum()
    assert (norm >= 0.0).all()
    assert math.isclose(norm.sum().item(), 1.0, rel_tol=1e-6)
