"""Contract and provenance tests for M25 training pipeline and offline evaluation gates."""

import copy
import json
import math
from pathlib import Path
import pytest
import torch

from splendor_gpu.data import catalog_semantic_hash, load_catalog
from splendor_gpu.encoded_cache import EncodedCache
from splendor_gpu.encoding import action_key
from splendor_gpu.train import file_sha256
from splendor_gpu.m25_dataset import (
    M25_DATASET_DOMAIN,
    M25_DATASET_FORMAT,
    M25_DATASET_VERSION,
    M25_UNIFORM_FLOOR_MICROS,
    M25Dataset,
    build_m25_encoded_cache,
    m25_dataset_hash,
    materialize_m25_dataset,
    validate_teacher_targets_config,
)
from splendor_gpu.m25_train import (
    EXPECTED_M25_FORMAT,
    EXPECTED_M25_GAMES,
    EXPECTED_M25_SEEDS,
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
    train_m25,
    validate_m25_config,
    validate_m25_dataset_provenance,
)

CONFIG_PATH = Path("benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json")
HOLDOUT_FIXTURE_PATH = Path("benchmarks/m24-s2-2002-audit-holdout.json")
AUDIT_RESULT_PATH = Path("benchmarks/m24-s2-teacher-target-quality-audit-v1.result.json")
M24_DATASET_PATH = Path("local-artifacts/m24-self-play-s2-v1/self-play.json")
CATALOG_PATH = Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")

FROZEN_M25_CONFIG_SHA256 = "bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250"
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


def test_m25_exact_128_seed_schedule(m25_config):
    """Validate explicit 128 game seed schedule 20260825..20260952 (128 seeds x 2 rotations = 256 games)."""
    seeds = m25_config["dataset"]["game_seeds"]
    assert len(seeds) == 128
    expected_seeds = [20260825 + i for i in range(128)]
    assert seeds == expected_seeds


def test_m25_game_split_exact_192_64_and_no_leakage(m25_config):
    """Assert seed-group split creates exactly 192 train games and 64 validation games with zero leakage."""
    fake_examples = []
    for g in range(256):
        seed_idx = g // 2
        rot = g % 2
        for ply in range(2):
            fake_examples.append({
                "game_index": g,
                "seed_index": seed_idx,
                "rotation": rot,
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
    train_seeds = set(fake_examples[i]["seed_index"] for i in train_idx)
    val_seeds = set(fake_examples[i]["seed_index"] for i in val_idx)
    
    assert len(train_games) == 192
    assert len(val_games) == 64
    assert len(train_seeds) == 96
    assert len(val_seeds) == 32
    assert train_games.isdisjoint(val_games)
    assert train_seeds.isdisjoint(val_seeds)
    assert all(s % 4 == 0 for s in val_seeds)
    assert all(s % 4 != 0 for s in train_seeds)


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
    with pytest.raises(ValueError, match="empty validation examples"):
        compute_uniform_policy_ce([])
    with pytest.raises(ValueError, match="invalid legal actions count"):
        compute_uniform_policy_ce([{"legal_actions": []}])


def test_m25_g3_uses_training_prior_only():
    """Validate G3 prior baseline MSE computes mean on training targets expanded to validation shape."""
    train_targets = torch.tensor([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]], dtype=torch.float32)  # mean = [0.5, 0.5]
    val_targets = torch.tensor([[1.0, 0.0], [0.0, 1.0]], dtype=torch.float32)
    # ( (1-0.5)^2 + (0-0.5)^2 + (0-0.5)^2 + (1-0.5)^2 ) / 4 = 1.0 / 4 = 0.25
    base_mse = compute_training_value_prior_baseline_mse(train_targets, val_targets)
    assert math.isclose(base_mse, 0.25, rel_tol=1e-6)


def test_m25_holdout_exact_2002_join():
    """Assert 2,002 holdout positions join exactly with M24-S2 dataset examples."""
    if not HOLDOUT_FIXTURE_PATH.exists() or not M24_DATASET_PATH.exists():
        pytest.skip("Holdout fixture or dataset not found")
    
    holdout = json.loads(HOLDOUT_FIXTURE_PATH.read_text(encoding="utf-8"))
    ds = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))
    
    assert holdout["positions_count"] == 2002
    assert len(holdout["positions"]) == 2002
    
    ex_by_key = {
        (ex["game_index"], ex["ply"], ex["actor"]): ex
        for ex in ds["examples"]
    }
    
    for p in holdout["positions"]:
        key = (p["game_index"], p["ply"], p["actor"])
        assert key in ex_by_key
        ex = ex_by_key[key]
        assert ex["observation_hash"] == p["observation_hash"]
        assert ex["information_set_hash"] == p["information_set_hash"]


def test_m25_holdout_missing_position_fails():
    """Assert evaluate_cross_distribution_holdout fails closed if a holdout position is missing from source dataset."""
    holdout_payload = {
        "format": "effective-splendor-audit-holdout-positions",
        "version": 1,
        "positions_count": 1,
        "positions": [
            {
                "game_index": 999,
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h",
                "information_set_hash": "info_h",
                "m07_top1": json.dumps({"type": "pass"}, sort_keys=True),
            }
        ]
    }
    dataset_payload = {
        "format": "effective-splendor-neural-self-play-v2",
        "version": 2,
        "examples": []
    }
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=torch.nn.Module(),
            m24_payload=dataset_payload,
            holdout_fixture=holdout_payload,
            catalog={},
            device=torch.device("cpu"),
        )


def test_m25_holdout_duplicate_position_fails():
    """Assert evaluate_cross_distribution_holdout fails closed if source dataset contains duplicate key."""
    holdout_payload = {
        "format": "effective-splendor-audit-holdout-positions",
        "version": 1,
        "positions_count": 1,
        "positions": [
            {
                "game_index": 0,
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h",
                "information_set_hash": "info_h",
                "m07_top1": json.dumps({"type": "pass"}, sort_keys=True),
            }
        ]
    }
    dataset_payload = {
        "format": "effective-splendor-neural-self-play-v2",
        "version": 2,
        "examples": [
            {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "obs_h", "information_set_hash": "info_h", "legal_actions": [{"type": "pass"}]},
            {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "obs_h", "information_set_hash": "info_h", "legal_actions": [{"type": "pass"}]},
        ]
    }
    
    with pytest.raises(RuntimeError, match="duplicate key in M24 dataset"):
        evaluate_cross_distribution_holdout(
            model=torch.nn.Module(),
            m24_payload=dataset_payload,
            holdout_fixture=holdout_payload,
            catalog={},
            device=torch.device("cpu"),
        )


def test_m25_holdout_observation_hash_mismatch_fails():
    """Assert evaluate_cross_distribution_holdout fails closed on observation_hash mismatch."""
    holdout_payload = {
        "format": "effective-splendor-audit-holdout-positions",
        "version": 1,
        "positions_count": 1,
        "positions": [
            {
                "game_index": 0,
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h_expected",
                "information_set_hash": "info_h",
                "m07_top1": json.dumps({"type": "pass"}, sort_keys=True),
            }
        ]
    }
    dataset_payload = {
        "format": "effective-splendor-neural-self-play-v2",
        "version": 2,
        "examples": [
            {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "obs_h_wrong", "information_set_hash": "info_h", "legal_actions": [{"type": "pass"}]},
        ]
    }
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=torch.nn.Module(),
            m24_payload=dataset_payload,
            holdout_fixture=holdout_payload,
            catalog={},
            device=torch.device("cpu"),
        )


def test_m25_fresh_model_exact_949060(m25_config):
    """Assert fresh initialization creates exact 949,060 parameter Entity Mixer."""
    model = build_m25_model(m25_config, seed=280229)
    assert sum(p.numel() for p in model.parameters()) == 949060


def test_m25_no_checkpoint_inheritance(m25_config):
    """Assert M25 explicitly forbids loading base checkpoints."""
    assert m25_config["model"]["initialization"] == "fresh_seed"
    assert "base_checkpoint" not in m25_config["model"]


def test_m25_best_epoch_selection_is_frozen(m25_config):
    """Assert best epoch selection uses policy_cross_entropy + 0.5 * value_mse on validation only."""
    sel = m25_config["training"]["selection"]
    assert sel["metric"] == "policy_cross_entropy + 0.5 * value_mse"
    assert sel["source"] == "m07_validation_games_only"
    assert sel["best_epoch"] is True
    assert sel["arena_reselection"] is False


def test_m25_gates_boundary_values(m25_config):
    """Verify exact boundary conditions on M25 offline acceptance gates."""
    # 1. G1 Fail
    d1 = evaluate_m25_gates(
        val_metrics={"visit_top1": 0.4499, "policy_cross_entropy": 2.0},
        holdout_result={"m07_top1_agreement": 0.40},
        uniform_ce=2.5,
        baseline_value_mse=0.50,
        config=m25_config,
    )
    assert d1["decision"] == "M25_POLICY_TEACHER_FIT_FAIL"
    assert d1["arena_authorization"] == "NOT_AUTHORIZED"
    
    # 2. G1 Pass, G2 Fail
    d2 = evaluate_m25_gates(
        val_metrics={"visit_top1": 0.4500, "policy_cross_entropy": 2.0},
        holdout_result={"m07_top1_agreement": 0.3799},
        uniform_ce=2.5,
        baseline_value_mse=0.50,
        config=m25_config,
    )
    assert d2["decision"] == "M25_TEACHER_FIT_NO_TRANSFER"
    assert d2["arena_authorization"] == "NOT_AUTHORIZED"
    
    # 3. G1 Pass, G2 Pass, G3 Fail
    d3 = evaluate_m25_gates(
        val_metrics={"visit_top1": 0.4500, "policy_cross_entropy": 2.0, "value_mse": 0.5101},
        holdout_result={"m07_top1_agreement": 0.3800},
        uniform_ce=2.5,
        baseline_value_mse=0.50,
        config=m25_config,
    )
    assert d3["decision"] == "M25_POLICY_SIGNAL_VALUE_BLOCKED"
    assert d3["arena_authorization"] == "NOT_AUTHORIZED"
    
    # 4. G1 Pass, G2 Pass, G3 Pass -> Arena Eligible
    d4 = evaluate_m25_gates(
        val_metrics={"visit_top1": 0.4500, "policy_cross_entropy": 2.0, "value_mse": 0.5100},
        holdout_result={"m07_top1_agreement": 0.3800},
        uniform_ce=2.5,
        baseline_value_mse=0.50,
        config=m25_config,
    )
    assert d4["decision"] == "M25_ARENA_ELIGIBLE"
    assert d4["arena_authorization"] == "AUTHORIZED_COMPACT_128_MATCHES"


def test_m25_holdout_information_set_hash_mismatch_fails():
    """Assert evaluate_cross_distribution_holdout fails closed on information_set_hash mismatch."""
    holdout_payload = {
        "format": "effective-splendor-audit-holdout-positions",
        "version": 1,
        "positions_count": 1,
        "positions": [
            {
                "game_index": 0,
                "ply": 0,
                "actor": 0,
                "observation_hash": "obs_h",
                "information_set_hash": "info_h_expected",
                "m07_top1": json.dumps({"type": "pass"}, sort_keys=True),
            }
        ]
    }
    dataset_payload = {
        "format": "effective-splendor-neural-self-play-v2",
        "version": 2,
        "examples": [
            {"game_index": 0, "ply": 0, "actor": 0, "observation_hash": "obs_h", "information_set_hash": "info_h_wrong", "legal_actions": [{"type": "pass"}]},
        ]
    }
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=torch.nn.Module(),
            m24_payload=dataset_payload,
            holdout_fixture=holdout_payload,
            catalog={},
            device=torch.device("cpu"),
        )


def test_m25_holdout_legal_action_mismatch_fails():
    """Assert evaluate_cross_distribution_holdout fails closed if legal_actions are empty."""
    real_ex = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))["examples"][0]
    holdout_payload = {
        "format": "effective-splendor-audit-holdout-positions",
        "version": 1,
        "positions_count": 1,
        "positions": [
            {
                "game_index": 0,
                "ply": 0,
                "actor": 0,
                "observation_hash": real_ex["observation_hash"],
                "information_set_hash": real_ex["information_set_hash"],
                "m07_top1": json.dumps({"type": "take_tokens", "gems": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0}}, sort_keys=True),
            }
        ]
    }
    dataset_payload = {
        "format": "effective-splendor-neural-self-play-v2",
        "version": 2,
        "examples": [
            {"game_index": 0, "ply": 0, "actor": 0, "observation": real_ex["observation"], "observation_hash": real_ex["observation_hash"], "information_set_hash": real_ex["information_set_hash"], "legal_actions": []},
        ]
    }
    
    with pytest.raises(RuntimeError, match="holdout join integrity failed"):
        evaluate_cross_distribution_holdout(
            model=torch.nn.Module(),
            m24_payload=dataset_payload,
            holdout_fixture=holdout_payload,
            catalog=load_catalog(CATALOG_PATH),
            device=torch.device("cpu"),
        )


def test_m25_holdout_raw_top1_mapping():
    """Assert holdout evaluation correctly computes exact top-1 match without MCTS."""
    real_ex = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))["examples"][0]
    legal_acts = real_ex["legal_actions"]
    
    class DummyModel(torch.nn.Module):
        def eval(self):
            pass
        def forward_packed(self, entities, mask, global_f, actions, offsets):
            # Give index 1 highest logit
            logits = torch.tensor([0.0] * len(legal_acts), dtype=torch.float32)
            logits[1] = 10.0
            values = torch.zeros((1, 2), dtype=torch.float32)
            return logits, values

    holdout_payload = {
        "format": "effective-splendor-audit-holdout-positions",
        "version": 1,
        "positions_count": 1,
        "positions": [
            {
                "game_index": 0,
                "ply": 0,
                "actor": 0,
                "observation_hash": real_ex["observation_hash"],
                "information_set_hash": real_ex["information_set_hash"],
                "m07_top1": json.dumps(legal_acts[1], sort_keys=True),
            }
        ]
    }
    dataset_payload = {
        "format": "effective-splendor-neural-self-play-v2",
        "version": 2,
        "examples": [
            {
                "game_index": 0,
                "ply": 0,
                "actor": 0,
                "observation": real_ex["observation"],
                "observation_hash": real_ex["observation_hash"],
                "information_set_hash": real_ex["information_set_hash"],
                "legal_actions": legal_acts,
            }
        ]
    }
    
    res = evaluate_cross_distribution_holdout(
        model=DummyModel(),
        m24_payload=dataset_payload,
        holdout_fixture=holdout_payload,
        catalog=load_catalog(CATALOG_PATH),
        device=torch.device("cpu"),
    )
    assert res["matched_positions"] == 1
    assert math.isclose(res["m07_top1_agreement"], 1.0, rel_tol=1e-6)


def test_m25_soft_policy_sum_exact(m25_config):
    """Validate M25 Dataset normalization when given policy_target_micros."""
    real_ex = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))["examples"][0]
    ex = {
        "observation": real_ex["observation"],
        "legal_actions": real_ex["legal_actions"][:2],
        "policy_target_micros": [750000, 250000],
        "value_target": [1.0, 0.0],
    }
    ds = M25Dataset([ex], catalog=load_catalog(CATALOG_PATH))
    item = ds[0]
    p_target = item["policy_target"]
    assert torch.allclose(p_target, torch.tensor([0.75, 0.25], dtype=torch.float32))
    assert math.isclose(p_target.sum().item(), 1.0, rel_tol=1e-6)


def test_m25_teacher_action_support_exact(m25_config):
    """Assert soft policy target length must strictly match legal actions count."""
    real_ex = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))["examples"][0]
    ex = {
        "observation": real_ex["observation"],
        "legal_actions": real_ex["legal_actions"][:1],
        "policy_target_micros": [500000, 500000],
        "value_target": [1.0, 0.0],
    }
    ds = M25Dataset([ex], catalog=load_catalog(CATALOG_PATH))
    with pytest.raises(ValueError, match="policy_target length 2 != legal_actions count 1"):
        _ = ds[0]


def test_m25_tampered_materialized_provenance_fails(m25_config):
    """Assert validate_m25_dataset_provenance detects any tampering in dataset provenance or linkage."""
    # Build synthetic valid dataset for 256 games (128 seeds x 2 rotations)
    games = [{
        "game_index": i,
        "evaluation_match_index": i,
        "seed_index": i // 2,
        "rotation": i % 2,
        "game_seed": 20260825 + (i // 2),
        "replay_document_hash": f"doc_{i:04d}",
        "result": {"scores": [15, 10], "ranks": [0, 1]},
        "replay": {
            "source_id": f"match-{i:06d}",
            "evaluation_match_index": i,
            "seed_index": i // 2,
            "rotation": i % 2,
            "replay_document_hash": f"doc_{i:04d}",
            "result": {"scores": [15, 10], "ranks": [0, 1]},
            "agents_by_seat": [
                {"seat": 0, "league_agent_id": "m07-bootstrap-a", "policy_version": "m07-v1", "model_version": None, "runtime_name": "effective-splendor-determinization-agent-bootstrap-a-v1", "runtime_version": "1"},
                {"seat": 1, "league_agent_id": "m07-bootstrap-b", "policy_version": "m07-v1", "model_version": None, "runtime_name": "effective-splendor-determinization-agent-bootstrap-b-v1", "runtime_version": "1"},
            ],
        },
    } for i in range(256)]
    
    examples = [{
        "game_index": i,
        "evaluation_match_index": i,
        "seed_index": i // 2,
        "rotation": i % 2,
        "game_seed": 20260825 + (i // 2),
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
    tampered_seat["games"][0]["replay"]["agents_by_seat"][1]["league_agent_id"] = "heuristic-v1"
    with pytest.raises(ValueError, match="replay agents.*must both be in"):
        validate_m25_dataset_provenance(tampered_seat, m25_config)


def test_m25_end_to_end_smoke(tmp_path, m25_config, catalog, monkeypatch):
    """
    P2-1 Check 10: True Bridge E2E Test against canonical TrainingDatasetV1 schema (128 seeds x 2 rotations = 256 games).
    Constructs canonical TrainingDatasetV1 (with embedded TrainingReplayV1 replays and TrainingExampleV1 examples with NO game_index)
    + SearchTeacherTargetSetV1 ->
    Materializes via materialize_m25_dataset ->
    Asserts derived game_index equals evaluation_match_index ->
    Asserts seed-group split (192 train / 64 val) ->
    Builds EncodedCache ->
    Runs train_m25 on CPU ->
    Evaluates G1/G2/G3 ->
    Verifies full artifacts and checkpoint/report hash bindings.
    """
    if not M24_DATASET_PATH.exists():
        pytest.skip("M24 dataset artifact not found")

    # Mock safe thermal readings for CPU test execution
    safe_readings = [
        {"source": "/sys/class/thermal/thermal_zone0/temp", "label": "acpitz", "celsius": 30.0},
        {"source": "/sys/class/hwmon/hwmon8/temp1_input", "label": "coretemp:Package id 0", "celsius": 50.0},
    ]
    monkeypatch.setattr("splendor_gpu.interaction_train.cpu_temperatures_c", lambda: safe_readings)

    # 1. Build canonical TrainingDatasetV1 and SearchTeacherTargetSetV1 fixtures (128 seeds x 2 rotations = 256 matches)
    real_examples = json.loads(M24_DATASET_PATH.read_text(encoding="utf-8"))["examples"][:4]
    
    replays = []
    training_examples = []
    search_targets_list = []

    for g_i in range(256):
        seed_idx = g_i // 2
        rot = g_i % 2
        seed = 20260825 + seed_idx
        doc_hash = f"doc_{seed:08d}_r{rot}"
        source_id = f"match-{g_i:06d}"
        ranks = [0, 1] if g_i % 2 == 0 else [1, 0]

        agent0 = "m07-bootstrap-a" if rot == 0 else "m07-bootstrap-b"
        agent1 = "m07-bootstrap-b" if rot == 0 else "m07-bootstrap-a"

        replays.append({
            "source_id": source_id,
            "evaluation_match_index": g_i,
            "seed_index": seed_idx,
            "rotation": rot,
            "arena_game_id": f"game-{g_i:06d}",
            "arena_report_hash": "a" * 64,
            "replay_document_hash": doc_hash,
            "engine_version": "0.1.0",
            "ruleset_id": "splendor-base-v1",
            "ruleset_fingerprint": "f" * 64,
            "player_count": 2,
            "steps": 10,
            "final_state_hash": "s" * 64,
            "result": {
                "scores": [15, 10] if ranks == [0, 1] else [10, 15],
                "ranks": ranks,
                "winners": [0] if ranks == [0, 1] else [1],
                "reason": "prestige_threshold",
            },
            "agents_by_seat": [
                {
                    "seat": 0,
                    "league_agent_id": agent0,
                    "policy_version": "m07-v1",
                    "model_version": None,
                    "runtime_name": f"effective-splendor-determinization-agent-{agent0}-v1",
                    "runtime_version": "1",
                },
                {
                    "seat": 1,
                    "league_agent_id": agent1,
                    "policy_version": "m07-v1",
                    "model_version": None,
                    "runtime_name": f"effective-splendor-determinization-agent-{agent1}-v1",
                    "runtime_version": "1",
                },
            ],
        })

        ex_template = real_examples[g_i % len(real_examples)]
        n_acts = len(ex_template["legal_actions"])
        base = 1_000_000 // n_acts
        rem = 1_000_000 % n_acts
        action_targets = [
            {"action": a, "policy_target_micros": base + (1 if j < rem else 0)}
            for j, a in enumerate(ex_template["legal_actions"])
        ]

        # Canonical TrainingExampleV1: has NO game_index
        training_examples.append({
            "source_id": source_id,
            "replay_document_hash": doc_hash,
            "ply": 0,
            "actor": 0,
            "observation": ex_template["observation"],
            "observation_hash": ex_template["observation_hash"],
            "visible_history_hash": "vis_h",
            "information_set_hash": ex_template["information_set_hash"],
            "legal_actions": ex_template["legal_actions"],
            "chosen_action": ex_template["legal_actions"][0],
            "final_scores": [15, 10] if ranks == [0, 1] else [10, 15],
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
        "format": "effective-splendor-training-dataset",
        "version": 1,
        "dataset_id": "m25-test-bridge-tds",
        "league_manifest_hash": "m" * 64,
        "evaluation_id": "m25-test-eval",
        "evaluation_plan_hash": "p" * 64,
        "evaluation_report_hash": "r" * 64,
        "replays": replays,
        "examples": training_examples,
    }

    search_targets_payload = {
        "format": "effective-splendor-search-teacher-targets",
        "version": 1,
        "dataset_id": "m25-test-bridge-tds",
        "dataset_hash": "b" * 64,
        "league_manifest_hash": "m" * 64,
        "evaluation_plan_hash": "p" * 64,
        "evaluation_report_hash": "r" * 64,
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
        training_dataset=training_ds,
        search_targets=search_targets_payload,
        config=m25_config,
    )

    # Verify derived game_index strictly equals evaluation_match_index, seed_index, and rotation
    for g_i, ex in enumerate(materialized["examples"]):
        assert ex["game_index"] == g_i
        assert ex["evaluation_match_index"] == g_i
        assert ex["seed_index"] == g_i // 2
        assert ex["rotation"] == g_i % 2
        assert ex["game_seed"] == 20260825 + (g_i // 2)

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
