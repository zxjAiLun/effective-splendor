"""Targeted unit tests for M25 M07 Search-Teacher Bootstrap v2 pipeline."""

import json
from pathlib import Path
import pytest
import torch
import torch.nn as nn

from splendor_gpu.m25_train import (
    validate_m25_config,
    build_m25_model,
    split_m25_indices,
    evaluate_m25_gates,
    EXPECTED_M25_PARAMETER_COUNT,
)


def test_m25_config_validation():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    assert config_path.exists(), "M25 config must exist in benchmarks/"
    
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_m25_config(config)

    # Test invalid parameter count rejection
    bad_config = dict(config)
    bad_config["model"] = dict(config["model"])
    bad_config["model"]["expected_parameter_count"] = 1000000
    with pytest.raises(ValueError, match="M25 parameter count mismatch"):
        validate_m25_config(bad_config)


def test_m25_model_architecture_and_parameter_count():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    
    model = build_m25_model(config, seed=280229)
    param_count = sum(p.numel() for p in model.parameters())
    assert param_count == EXPECTED_M25_PARAMETER_COUNT == 949060


def test_m25_game_level_split_disjointness():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    # Synthetic payload with 256 games
    examples = []
    for g_idx in range(256):
        # 10 examples per game
        for e in range(10):
            examples.append({"game_index": g_idx})

    payload = {"examples": examples}
    train_idx, val_idx = split_m25_indices(payload, config)

    assert len(train_idx) == 1920 # 192 games * 10
    assert len(val_idx) == 640   # 64 games * 10
    assert len(set(train_idx) & set(val_idx)) == 0, "Train and val must be strictly disjoint"


def test_m25_gate_decision_tree_logic():
    config_path = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    
    baseline_value_mse = 0.25

    # Case 1: G1 FAIL (Top-1 too low)
    val_fail_g1 = {
        "visit_top1": 0.40, # < 0.45
        "policy_cross_entropy": 2.0,
        "uniform_policy_cross_entropy": 3.0,
        "value_mse": 0.24,
    }
    decision_g1_fail = evaluate_m25_gates(val_fail_g1, holdout_m07_agreement=0.40, baseline_value_mse=baseline_value_mse, config=config)
    assert decision_g1_fail["decision"] == "M25_POLICY_TEACHER_FIT_FAIL"
    assert decision_g1_fail["arena_authorization"] == "NOT_AUTHORIZED"

    # Case 2: G1 PASS, G2 FAIL (Cross-distribution holdout too low)
    val_pass_g1 = {
        "visit_top1": 0.48, # >= 0.45
        "policy_cross_entropy": 2.0,
        "uniform_policy_cross_entropy": 3.0, # 3333 bps > 1000 bps
        "value_mse": 0.24,
    }
    decision_g2_fail = evaluate_m25_gates(val_pass_g1, holdout_m07_agreement=0.35, baseline_value_mse=baseline_value_mse, config=config) # 0.35 < 0.38
    assert decision_g2_fail["decision"] == "M25_TEACHER_FIT_NO_TRANSFER"
    assert decision_g2_fail["arena_authorization"] == "NOT_AUTHORIZED"

    # Case 3: G1 PASS, G2 PASS, G3 FAIL (Value MSE exploded)
    decision_g3_fail = evaluate_m25_gates(val_pass_g1, holdout_m07_agreement=0.42, baseline_value_mse=baseline_value_mse, config=config)
    val_fail_g3 = dict(val_pass_g1, value_mse=0.30) # > 0.25 * 1.02 = 0.255
    decision_g3_fail = evaluate_m25_gates(val_fail_g3, holdout_m07_agreement=0.42, baseline_value_mse=baseline_value_mse, config=config)
    assert decision_g3_fail["decision"] == "M25_POLICY_SIGNAL_VALUE_BLOCKED"
    assert decision_g3_fail["arena_authorization"] == "NOT_AUTHORIZED"

    # Case 4: G1 PASS, G2 PASS, G3 PASS (Full Pass)
    decision_all_pass = evaluate_m25_gates(val_pass_g1, holdout_m07_agreement=0.42, baseline_value_mse=baseline_value_mse, config=config)
    assert decision_all_pass["decision"] == "M25_ARENA_ELIGIBLE"
    assert decision_all_pass["arena_authorization"] == "AUTHORIZED_COMPACT_128_MATCHES"


def test_m24_audit_holdout_fixture_integrity():
    holdout_path = Path("benchmarks/m24-s2-2002-audit-holdout.json")
    assert holdout_path.exists(), "Holdout fixture must exist"
    
    data = json.loads(holdout_path.read_text(encoding="utf-8"))
    assert data["format"] == "effective-splendor-audit-holdout-positions"
    assert data["positions_count"] == 2002
    assert len(data["positions"]) == 2002
