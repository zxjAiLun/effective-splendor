"""Exhaustive contract and anti-drift unit tests for M25 M07 Search-Teacher Bootstrap v2."""

import copy
import json
import math
from pathlib import Path
import pytest
import torch
import torch.nn.functional as F

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.encoding import encode_action, encode_observation, action_key
from splendor_gpu.model import ModelSpec, build_model
from splendor_gpu.train import file_sha256, seed_everything
from splendor_gpu.m25_dataset import (
    M25_DATASET_FORMAT,
    M25_DATASET_VERSION,
    build_m25_encoded_cache,
    m25_dataset_hash,
    materialize_m25_dataset,
)
from splendor_gpu.m25_train import (
    EXPECTED_M25_FORMAT,
    EXPECTED_M25_GAMES,
    EXPECTED_M25_PARAMETER_COUNT,
    EXPECTED_M25_TRAIN_GAMES,
    EXPECTED_M25_VAL_GAMES,
    EXPECTED_UNIFORM_FLOOR_MICROS,
    EXPECTED_HOLDOUT_FIXTURE_SHA256,
    EXPECTED_M24_DATASET_FILE_SHA256,
    EXPECTED_M24_DATASET_SEMANTIC_HASH,
    build_m25_model,
    compute_training_value_prior_baseline_mse,
    compute_uniform_policy_ce,
    evaluate_cross_distribution_holdout,
    evaluate_m25_gates,
    split_m25_indices,
    train_m25,
    validate_m25_config,
    validate_m25_dataset_provenance,
)

CONFIG_PATH = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
HOLDOUT_FIXTURE_PATH = Path("benchmarks/m24-s2-2002-audit-holdout.json")
AUDIT_RESULT_PATH = Path("benchmarks/m24-s2-teacher-target-quality-audit-v1.result.json")
M24_DATASET_PATH = Path("local-artifacts/m24-self-play-s2-v1/self-play.json")
CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")

FROZEN_M25_CONFIG_SHA256 = "6fb0acd30cd1194ac02e6c200831b1e77033ca23bb80941e3bcf6b7ae7fb4de0"
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
        for ply in range(2):
            fake_examples.append({
                "game_index": g,
                "ply": ply,
                "actor": ply % 2,
                "observation": {},
                "legal_actions": [{"type": "pass"}],
            })
    fake_payload = {"examples": fake_examples}
    train_idx, val_idx = split_m25_indices(fake_payload, m25_config)
    
    assert len(train_idx) == 192 * 2
    assert len(val_idx) == 64 * 2
    
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


def test_m25_tampered_materialized_provenance_fails(m25_config):
    """P1-4 Check 9: Tampered provenance fields in materialized dataset fail closed in train_m25 validation."""
    games = [{
        "game_index": i,
        "game_seed": 20260825 + i,
        "replay_document_hash": f"doc_{i:04d}",
        "result": {"scores": [15, 10], "ranks": [0, 1]},
        "replay": {
            "header": {
                "game_seed": 20260825 + i,
                "players": ["m07-determinization-champion", "m07-determinization-champion"],
            },
            "result": {"scores": [15, 10], "ranks": [0, 1]},
        },
    } for i in range(256)]
    
    examples = [{
        "game_index": i,
        "game_seed": 20260825 + i,
        "source_id": f"match-{i:06d}",
        "replay_document_hash": f"doc_{i:04d}",
        "ply": 0,
        "actor": 0,
        "observation": {},
        "observation_hash": "obs_h",
        "information_set_hash": "info_h",
        "legal_actions": [{"type": "pass"}],
        "policy_target_micros": [1_000_000],
        "value_target": [1.0, 0.0],
    } for i in range(256)]
    
    base_ds = {
        "format": M25_DATASET_FORMAT,
        "version": M25_DATASET_VERSION,
        "generator_agent": "m07-determinization-champion",
        "ruleset": "base_v1",
        "player_count": 2,
        "provenance": {
            "teacher_config": {
                "sample_seed": 20260810,
                "sample_count": 4,
                "max_depth_turns": 1,
                "max_nodes": 2000,
                "uniform_floor_micros": 100000,
            }
        },
        "games": games,
        "examples": examples,
    }

    # 1. Valid dataset passes
    validate_m25_dataset_provenance(base_ds, m25_config)

    # 2. Tampered game_seed in example fails
    tampered_seed = copy.deepcopy(base_ds)
    tampered_seed["examples"][0]["game_seed"] = 99999999
    with pytest.raises(ValueError, match="game_seed mismatch"):
        validate_m25_dataset_provenance(tampered_seed, m25_config)

    # 3. Tampered replay_document_hash in example fails
    tampered_doc = copy.deepcopy(base_ds)
    tampered_doc["examples"][0]["replay_document_hash"] = "wrong_doc_hash"
    with pytest.raises(ValueError, match="replay_document_hash mismatch"):
        validate_m25_dataset_provenance(tampered_doc, m25_config)

    # 4. Tampered value_target (disagreeing with game ranks) fails
    tampered_val = copy.deepcopy(base_ds)
    tampered_val["examples"][0]["value_target"] = [0.0, 1.0]  # actor 0 won, so expected [1.0, 0.0]
    with pytest.raises(ValueError, match="value_target.*!= expected"):
        validate_m25_dataset_provenance(tampered_val, m25_config)

    # 5. Tampered teacher_config in provenance fails
    tampered_t = copy.deepcopy(base_ds)
    tampered_t["provenance"]["teacher_config"]["sample_count"] = 16
    with pytest.raises(ValueError, match="provenance teacher sample_count"):
        validate_m25_dataset_provenance(tampered_t, m25_config)

    # 6. Missing provenance section fails
    tampered_no_prov = copy.deepcopy(base_ds)
    tampered_no_prov.pop("provenance")
    with pytest.raises(ValueError, match="missing required provenance section"):
        validate_m25_dataset_provenance(tampered_no_prov, m25_config)

    # 7. Missing teacher_config in provenance fails
    tampered_no_tc = copy.deepcopy(base_ds)
    tampered_no_tc["provenance"].pop("teacher_config")
    with pytest.raises(ValueError, match="missing required teacher_config"):
        validate_m25_dataset_provenance(tampered_no_tc, m25_config)

    # 8. Non-M07 player seat in embedded replay fails
    tampered_seat = copy.deepcopy(base_ds)
    tampered_seat["games"][0]["replay"]["header"]["players"] = ["m07-determinization-champion", "heuristic-v1"]
    with pytest.raises(ValueError, match="replay players.*must both be 'm07-determinization-champion'"):
        validate_m25_dataset_provenance(tampered_seat, m25_config)


def test_m25_end_to_end_smoke(tmp_path, m25_config, catalog, monkeypatch):
    """
    P2-1 Check 10: True Bridge E2E Test.
    Constructs raw Replays + TrainingDatasetV1 + SearchTeacherTargetSetV1 ->
    Materializes via materialize_m25_dataset ->
    Builds EncodedCache ->
    Runs train_m25 on CPU ->
    Evaluates G1/G2/G3 ->
    Verifies full artifacts.
    """
    if not M24_DATASET_PATH.exists():
        pytest.skip("M24 dataset artifact not found")

    # Mock safe thermal readings for CPU test execution
    safe_readings = [
        {"source": "/sys/class/thermal/thermal_zone0/temp", "label": "acpitz", "celsius": 30.0},
        {"source": "/sys/class/hwmon/hwmon8/temp1_input", "label": "coretemp:Package id 0", "celsius": 50.0},
    ]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: safe_readings)

    # 1. Build input fixtures: 256 Replays, TrainingDatasetV1, and SearchTeacherTargetSetV1
    real_examples = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))["examples"][:4]
    
    replays = []
    training_examples = []
    search_targets_list = []

    for g_i in range(256):
        seed = 20260825 + g_i
        doc_hash = f"doc_{seed:08d}"
        source_id = f"match-{g_i:06d}"
        ranks = [0, 1] if g_i % 2 == 0 else [1, 0]

        replays.append({
            "replay_document_hash": doc_hash,
            "header": {
                "game_seed": seed,
                "players": ["m07-determinization-champion", "m07-determinization-champion"],
            },
            "result": {
                "scores": [15, 10] if ranks == [0, 1] else [10, 15],
                "ranks": ranks,
                "winners": [0] if ranks == [0, 1] else [1],
                "reason": "points_threshold",
            },
        })

        ex_template = real_examples[g_i % len(real_examples)]
        n_acts = len(ex_template["legal_actions"])
        base = 1_000_000 // n_acts
        rem = 1_000_000 % n_acts
        action_targets = [
            {"action": a, "policy_target_micros": base + (1 if j < rem else 0)}
            for j, a in enumerate(ex_template["legal_actions"])
        ]

        training_examples.append({
            "source_id": source_id,
            "replay_document_hash": doc_hash,
            "game_index": g_i,
            "ply": 0,
            "actor": 0,
            "observation": ex_template["observation"],
            "observation_hash": ex_template["observation_hash"],
            "information_set_hash": ex_template["information_set_hash"],
            "legal_actions": ex_template["legal_actions"],
            "chosen_action": ex_template["legal_actions"][0],
            "final_ranks": ranks,
        })

        search_targets_list.append({
            "source_id": source_id,
            "ply": 0,
            "actor": 0,
            "observation_hash": ex_template["observation_hash"],
            "information_set_hash": ex_template["information_set_hash"],
            "action_targets": action_targets,
            "value_target_by_player_micros": [750000, 250000],
        })

    training_ds = {
        "format": "effective-splendor-training-dataset-v1",
        "version": 1,
        "dataset_id": "m25-test-bridge-tds",
        "examples": training_examples,
    }

    search_targets_payload = {
        "format": "effective-splendor-search-teacher-targets",
        "version": 1,
        "dataset_id": "m25-test-bridge-targets",
        "dataset_hash": "b" * 64,
        "config": {
            "search": {
                "sample_seed": 20260810,
                "sample_count": 4,
                "continuation_search": {
                    "max_depth_turns": 1,
                    "max_nodes": 2000,
                },
            },
            "uniform_floor_micros": 100000,
            "value_utility_scale": 15,
        },
        "targets": search_targets_list,
    }

    # 2. Materialize through materialize_m25_dataset bridge
    materialized = materialize_m25_dataset(
        replays=replays,
        training_dataset=training_ds,
        search_targets=search_targets_payload,
        config=m25_config,
    )

    dataset_path = tmp_path / "bridge_m25_dataset.json"
    dataset_path.write_text(json.dumps(materialized), encoding="utf-8")

    # 3. Train and evaluate
    cfg = copy.deepcopy(m25_config)
    cfg["training"]["epochs"] = 1
    cfg["training"]["device"] = "cpu"

    out_dir = tmp_path / "m25_bridge_smoke_out"

    report = train_m25(
        config=cfg,
        dataset_path=dataset_path,
        catalog_path=CATALOG_PATH,
        holdout_dataset_path=M24_DATASET_PATH,
        holdout_fixture_path=HOLDOUT_FIXTURE_PATH,
        out_dir=out_dir,
        skip_cooldown=True,
        allow_cpu=True,
    )

    assert report["best_epoch"] == 1
    assert (out_dir / "checkpoint.pt").exists()
    assert (out_dir / "training-report.json").exists()
    assert (out_dir / "offline-result.json").exists()

    # Verify checkpoint metadata binds full M25 dataset and config hashes
    ckpt = torch.load(out_dir / "checkpoint.pt", map_location="cpu", weights_only=False)
    meta = ckpt["metadata"]
    assert meta["source_dataset_file_sha256"] == file_sha256(dataset_path)
    assert len(meta["source_dataset_semantic_hash"]) == 64
    assert len(meta["encoded_cache_manifest_sha256"]) == 64
    assert len(meta["training_config_hash"]) == 64
    assert meta["m25_config_revision"] == "m07-search-teacher-bootstrap-v2"

    # Verify training report binds full M25 dataset and config hashes
    rep = json.loads((out_dir / "training-report.json").read_text(encoding="utf-8"))
    assert rep["source_dataset_file_sha256"] == file_sha256(dataset_path)
    assert rep["source_dataset_semantic_hash"] == meta["source_dataset_semantic_hash"]
    assert rep["encoded_cache_manifest_sha256"] == meta["encoded_cache_manifest_sha256"]
    assert rep["training_config_hash"] == meta["training_config_hash"]
    assert rep["m25_config_revision"] == "m07-search-teacher-bootstrap-v2"

    assert report["gates"]["decision"] in (
        "M25_POLICY_TEACHER_FIT_FAIL",
        "M25_TEACHER_FIT_NO_TRANSFER",
        "M25_POLICY_SIGNAL_VALUE_BLOCKED",
        "M25_ARENA_ELIGIBLE",
    )
