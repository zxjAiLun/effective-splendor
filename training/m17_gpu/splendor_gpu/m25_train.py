"""M25 M07 Search-Teacher Bootstrap v2 formal trainer and offline gate evaluator."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

from splendor_gpu.data import (
    catalog_semantic_hash,
    collate,
    load_catalog,
)
from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset
from splendor_gpu.encoding import encode_action, encode_observation
from splendor_gpu.model import ModelSpec, build_model
from splendor_gpu.runtime import configure_cpu_runtime
from splendor_gpu.self_play_train import evaluate, self_play_hash
from splendor_gpu.train import (
    checkpoint_semantic_hash,
    file_sha256,
    resolve_device,
    seed_everything,
)
from splendor_gpu.interaction_train import (
    BackgroundThermalGuard,
    require_fail_closed_cooldown,
    wait_for_soft_thermal_envelope,
    iter_physical_microbatches,
    packed_policy_loss,
    policy_loss,
    COOLDOWN_TARGET_C,
    COOLDOWN_TIMEOUT_SECONDS,
    TELEMETRY_INTERVAL_SECONDS,
    PHYSICAL_MICROBATCH_SIZE,
    EXPECTED_CPU_THREADS,
    EXPECTED_CATALOG_HASH,
    _IndexDataset,
    _loader,
    training_config_hash,
)
from splendor_gpu.m25_dataset import (
    M25_DATASET_FORMAT,
    M25_DATASET_VERSION,
    M25_UNIFORM_FLOOR_MICROS,
    M25Dataset,
    build_m25_encoded_cache,
    m25_dataset_hash,
)

EXPECTED_M25_FORMAT = "effective-splendor-m25-m07-search-teacher-bootstrap"
EXPECTED_M25_PARAMETER_COUNT = 949060
EXPECTED_M25_GAMES = 256
EXPECTED_M25_SEEDS = 128
EXPECTED_M25_TRAIN_GAMES = 192
EXPECTED_M25_VAL_GAMES = 64
EXPECTED_UNIFORM_FLOOR_MICROS = 100000
ALLOWED_M07_GENERATOR_IDS = {
    "m07-bootstrap-a",
    "m07-bootstrap-b",
    "m07-determinization-champion",
}

EXPECTED_HOLDOUT_FIXTURE_SHA256 = "331654ba370a489053bcf6cd0452d7aa4883b6c64d5db0be757c4a42860f05f8"
EXPECTED_M24_DATASET_FILE_SHA256 = "ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f"
EXPECTED_M24_DATASET_SEMANTIC_HASH = "b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46"


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def validate_m25_config(config: dict[str, Any], *, allow_cpu: bool = False) -> None:
    """Perform exhaustive machine-freezing assertions on the M25 config."""
    _assert_equal(config.get("format"), EXPECTED_M25_FORMAT, "M25 config format")
    _assert_equal(config.get("version"), 1, "M25 config version")
    _assert_equal(config.get("milestone"), "M25", "M25 config milestone")
    _assert_equal(config.get("revision"), "m07-search-teacher-bootstrap-v2", "M25 config revision")

    # Dataset scope & teacher
    ds = config["dataset"]
    _assert_equal(ds.get("format"), "effective-splendor-search-teacher-dataset-v1", "dataset format")
    _assert_equal(ds.get("version"), 1, "dataset version")
    _assert_equal(ds.get("generator_agent"), "m07-determinization-champion", "dataset generator_agent")
    _assert_equal(ds.get("teacher_builder_format"), "effective-splendor-search-teacher-targets", "teacher builder format")
    _assert_equal(ds.get("teacher_builder_version"), 1, "teacher builder version")
    _assert_equal(int(ds.get("games", 0)), EXPECTED_M25_GAMES, "dataset games count")
    _assert_equal(int(ds.get("player_count", 0)), 2, "dataset player count")
    _assert_equal(ds.get("ruleset"), "base_v1", "dataset ruleset")
    
    seeds = ds.get("game_seeds", [])
    _assert_equal(len(seeds), EXPECTED_M25_SEEDS, "game seeds count")
    expected_seeds = [20260825 + i for i in range(EXPECTED_M25_SEEDS)]
    _assert_equal(seeds, expected_seeds, "game seeds sequence")

    t_cfg = ds["teacher_config"]
    _assert_equal(int(t_cfg["sample_seed"]), 20260810, "teacher sample_seed")
    _assert_equal(int(t_cfg["sample_count"]), 4, "teacher sample_count")
    _assert_equal(int(t_cfg["max_depth_turns"]), 1, "teacher max_depth_turns")
    _assert_equal(int(t_cfg["max_nodes"]), 2000, "teacher max_nodes")
    
    _assert_equal(int(ds["targets"]["uniform_floor_micros"]), EXPECTED_UNIFORM_FLOOR_MICROS, "uniform_floor_micros")
    _assert_equal(ds.get("value_target"), "terminal_outcome_viewer_relative", "value_target")

    split = ds["split"]
    _assert_equal(int(split["total_games"]), EXPECTED_M25_GAMES, "split total_games")
    _assert_equal(int(split["total_seeds"]), EXPECTED_M25_SEEDS, "split total_seeds")
    _assert_equal(int(split["rotations_per_seed"]), 2, "split rotations_per_seed")
    _assert_equal(int(split["validation"]["seed_index_modulus"]), 4, "split val seed modulus")
    _assert_equal(int(split["validation"]["seed_index_remainder"]), 0, "split val seed remainder")
    _assert_equal(int(split["validation"]["seeds"]), 32, "split val seeds")
    _assert_equal(int(split["validation"]["games"]), EXPECTED_M25_VAL_GAMES, "split val games")
    _assert_equal(int(split["train"]["seeds"]), 96, "split train seeds")
    _assert_equal(int(split["train"]["games"]), EXPECTED_M25_TRAIN_GAMES, "split train games")

    # Model architecture
    model = config["model"]
    _assert_equal(model.get("role"), "candidate", "model role")
    _assert_equal(model.get("model_id"), "m25-entity-mixer-h192-b4-m07-bootstrap-v2", "model_id")
    _assert_equal(model.get("architecture"), "entity_mixer", "model architecture")
    _assert_equal(int(model.get("hidden_dim", 0)), 192, "model hidden_dim")
    _assert_equal(int(model.get("blocks", 0)), 4, "model blocks")
    _assert_equal(float(model.get("dropout", -1)), 0.0, "model dropout")
    _assert_equal(int(model.get("interaction_blocks", -1)), 0, "model interaction_blocks")
    _assert_equal(int(model.get("expected_parameter_count", 0)), EXPECTED_M25_PARAMETER_COUNT, "model expected_parameter_count")
    _assert_equal(model.get("initialization"), "fresh_seed", "model initialization")
    _assert_equal(int(model.get("initialization_seed", 0)), 280229, "model initialization_seed")

    # Training recipe
    tr = config["training"]
    if not allow_cpu:
        _assert_equal(tr.get("device"), "cuda", "training device")
        _assert_equal(int(tr.get("epochs", 0)), 32, "training epochs")
    else:
        if tr.get("device") not in ("cuda", "cpu"):
            raise ValueError(f"training device mismatch: {tr.get('device')}")
        if int(tr.get("epochs", 0)) < 1:
            raise ValueError("epochs must be at least 1")
    _assert_equal(int(tr.get("seed", 0)), 280229, "training seed")
    _assert_equal(int(tr.get("shuffle_seed", 0)), 280229, "training shuffle_seed")
    _assert_equal(int(tr.get("batch_size", 0)), 128, "training batch_size")
    _assert_equal(float(tr.get("learning_rate", 0)), 0.0001, "training learning_rate")
    _assert_equal(float(tr.get("weight_decay", 0)), 0.0001, "training weight_decay")
    _assert_equal(float(tr.get("gradient_clip_norm", 0)), 1.0, "training gradient_clip_norm")
    _assert_equal(tr.get("optimizer"), "AdamW", "training optimizer")
    _assert_equal(float(tr.get("value_loss_weight", 0)), 0.5, "training value_loss_weight")
    _assert_equal(tr.get("deterministic_cuda"), True, "training deterministic_cuda")
    _assert_equal(tr.get("cublas_workspace_config"), ":4096:8", "training cublas_workspace_config")
    
    sel = tr["selection"]
    _assert_equal(sel.get("metric"), "policy_cross_entropy + 0.5 * value_mse", "selection metric")
    _assert_equal(sel.get("source"), "m07_validation_games_only", "selection source")
    _assert_equal(sel.get("best_epoch"), True, "selection best_epoch")

    # External holdout
    ho = config["external_holdout"]
    _assert_equal(int(ho.get("positions_count", 0)), 2002, "holdout positions_count")
    _assert_equal(ho.get("fixture_file"), "benchmarks/m24-s2-2002-audit-holdout.json", "holdout fixture_file")
    _assert_equal(ho.get("fixture_sha256"), EXPECTED_HOLDOUT_FIXTURE_SHA256, "holdout fixture_sha256")
    _assert_equal(ho.get("source_dataset_file_sha256"), EXPECTED_M24_DATASET_FILE_SHA256, "holdout source dataset sha")
    _assert_equal(ho.get("source_dataset_semantic_hash"), EXPECTED_M24_DATASET_SEMANTIC_HASH, "holdout source dataset sem hash")

    # Offline gates
    og = config["offline_gates"]
    _assert_equal(float(og["g1_heldout_teacher_fit"]["min_validation_policy_top1"]), 0.4500, "G1 min top1")
    _assert_equal(int(og["g1_heldout_teacher_fit"]["min_policy_ce_improvement_bps_vs_uniform"]), 1000, "G1 min CE bps")
    _assert_equal(float(og["g2_cross_distribution_transfer"]["min_cross_distribution_m07_top1"]), 0.3800, "G2 min top1")
    _assert_equal(float(og["g3_value_non_collapse"]["max_value_mse_multiplier_vs_baseline"]), 1.02, "G3 max multiplier")


def validate_m25_dataset_provenance(payload: dict[str, Any], config: dict[str, Any]) -> str:
    """Perform deep runtime provenance verification on the actual materialized M25 dataset."""
    _assert_equal(payload.get("format"), M25_DATASET_FORMAT, "dataset format")
    _assert_equal(payload.get("version"), M25_DATASET_VERSION, "dataset version")
    _assert_equal(payload.get("generator_agent"), "m07-determinization-champion", "dataset generator_agent")
    _assert_equal(payload.get("ruleset"), "base_v1", "dataset ruleset")
    _assert_equal(int(payload.get("player_count", 0)), 2, "dataset player_count")
    
    games = payload.get("games", [])
    expected_games = int(config["dataset"]["games"])
    _assert_equal(len(games), expected_games, "dataset games count")

    expected_generator = config.get("dataset", {}).get("generator_agent", "m07-determinization-champion")

    # 1. Check seeds schedule & embedded game metadata
    expected_seeds = config["dataset"]["game_seeds"]
    expected_seeds_count = len(expected_seeds)
    allowed_agents = set(config.get("dataset", {}).get("allowed_generator_agents", ALLOWED_M07_GENERATOR_IDS))

    game_by_idx: dict[int, dict[str, Any]] = {}
    game_by_doc_hash: dict[str, dict[str, Any]] = {}
    seed_rotations_seen: dict[int, set[int]] = {}

    for g_i, g in enumerate(games):
        g_idx = int(g.get("game_index", -1))
        _assert_equal(g_idx, g_i, f"game {g_i} game_index")
        
        doc_hash = g.get("replay_document_hash")
        if not doc_hash:
            raise ValueError(f"fail-closed: game {g_i} missing replay_document_hash")
        if doc_hash in game_by_doc_hash:
            raise ValueError(f"fail-closed: duplicate game replay_document_hash: {doc_hash}")

        seed_idx = int(g.get("seed_index", -1))
        if seed_idx < 0 or seed_idx >= expected_seeds_count:
            raise ValueError(f"fail-closed: game {g_i} seed_index {seed_idx} out of range 0..{expected_seeds_count-1}")
        
        rotation = int(g.get("rotation", -1))
        if rotation not in (0, 1):
            raise ValueError(f"fail-closed: game {g_i} rotation {rotation} not in {{0, 1}}")

        if seed_idx not in seed_rotations_seen:
            seed_rotations_seen[seed_idx] = set()
        seed_rotations_seen[seed_idx].add(rotation)

        expected_seed = expected_seeds[seed_idx]
        _assert_equal(int(g["game_seed"]), expected_seed, f"game {g_i} game_seed")
            
        replay = g.get("replay", {})
        agents_by_seat = replay.get("agents_by_seat")
        if agents_by_seat is not None:
            if len(agents_by_seat) != 2:
                raise ValueError(f"fail-closed: game {g_i} replay agents_by_seat length {len(agents_by_seat)} != 2")
            p0 = agents_by_seat[0].get("league_agent_id")
            p1 = agents_by_seat[1].get("league_agent_id")
            if p0 not in allowed_agents or p1 not in allowed_agents:
                raise ValueError(f"fail-closed: game {g_i} replay agents {p0}, {p1} must both be in {allowed_agents}")
        else:
            header = replay.get("header", {})
            players = header.get("players", [])
            if len(players) != 2 or players[0] not in allowed_agents or players[1] not in allowed_agents:
                raise ValueError(f"fail-closed: game {g_i} replay players {players} must both be in {allowed_agents}")

        result = g.get("result", {})
        ranks = result.get("ranks")
        if ranks is None or len(ranks) != 2:
            raise ValueError(f"fail-closed: game {g_i} missing or invalid result.ranks")

        game_by_idx[g_idx] = g
        game_by_doc_hash[doc_hash] = g

    # 2. Check provenance section (mandatory & fail-closed)
    if "provenance" not in payload or not isinstance(payload["provenance"], dict):
        raise ValueError("fail-closed: dataset missing required provenance section")
    provenance = payload["provenance"]
    
    if "teacher_config" not in provenance or not isinstance(provenance["teacher_config"], dict):
        raise ValueError("fail-closed: dataset provenance missing required teacher_config")
    t_cfg = provenance["teacher_config"]
    
    expected_t = config["dataset"]["teacher_config"]
    if "search" in t_cfg:
        search = t_cfg["search"]
        cont = search.get("continuation_search", {})
        actual_seed = int(search.get("sample_seed", -1))
        actual_count = int(search.get("sample_count", -1))
        actual_depth = int(cont.get("max_depth_turns", -1))
        actual_nodes = int(cont.get("max_nodes", -1))
        actual_floor = int(t_cfg.get("uniform_floor_micros", -1))
    else:
        actual_seed = int(t_cfg.get("sample_seed", -1))
        actual_count = int(t_cfg.get("sample_count", -1))
        actual_depth = int(t_cfg.get("max_depth_turns", -1))
        actual_nodes = int(t_cfg.get("max_nodes", -1))
        actual_floor = int(t_cfg.get("uniform_floor_micros", -1))

    _assert_equal(actual_seed, int(expected_t["sample_seed"]), "provenance teacher sample_seed")
    _assert_equal(actual_count, int(expected_t["sample_count"]), "provenance teacher sample_count")
    _assert_equal(actual_depth, int(expected_t["max_depth_turns"]), "provenance teacher max_depth_turns")
    _assert_equal(actual_nodes, int(expected_t["max_nodes"]), "provenance teacher max_nodes")
    _assert_equal(actual_floor, EXPECTED_UNIFORM_FLOOR_MICROS, "provenance teacher uniform_floor_micros")

    examples = payload.get("examples", [])
    if not examples:
        raise ValueError("fail-closed: empty examples in dataset")

    # 3. Verify every example's internal linkage to games and verified ranks
    for idx, ex in enumerate(examples):
        g_idx = int(ex.get("game_index", -1))
        if g_idx not in game_by_idx:
            raise ValueError(f"fail-closed: example {idx} references unknown game_index {g_idx}")
        g = game_by_idx[g_idx]

        if int(ex.get("game_seed", -1)) != int(g["game_seed"]):
            raise ValueError(f"fail-closed: example {idx} game_seed mismatch with game {g_idx}")
        if ex.get("replay_document_hash") != g["replay_document_hash"]:
            raise ValueError(f"fail-closed: example {idx} replay_document_hash mismatch with game {g_idx}")

        actor = int(ex.get("actor", -1))
        if actor not in (0, 1):
            raise ValueError(f"fail-closed: example {idx} invalid actor {actor}")

        micros = ex.get("policy_target_micros", [])
        legal_acts = ex.get("legal_actions", [])
        if len(micros) != len(legal_acts) or len(legal_acts) == 0:
            raise ValueError(f"fail-closed: example {idx} policy_target_micros / legal_actions mismatch")
        if sum(micros) != 1_000_000:
            raise ValueError(f"fail-closed: example {idx} policy_target_micros sum {sum(micros)} != 1000000")
        
        # Verify terminal viewer value target matches authoritative game result.ranks
        ranks = g["result"]["ranks"]
        expected_viewer_val = [1.0 - float(ranks[actor]), 1.0 - float(ranks[1 - actor])]
        actual_val = ex.get("value_target", [])
        if len(actual_val) != 2:
            raise ValueError(f"fail-closed: example {idx} value_target must have length 2")
        if actual_val != expected_viewer_val:
            raise ValueError(f"fail-closed: example {idx} value_target {actual_val} != expected {expected_viewer_val} from ranks {ranks}")

    return m25_dataset_hash(payload)


def build_m25_model(config: dict[str, Any], seed: int) -> nn.Module:
    model_cfg = config["model"]
    spec = ModelSpec(
        architecture=str(model_cfg["architecture"]),
        hidden_dim=int(model_cfg["hidden_dim"]),
        blocks=int(model_cfg["blocks"]),
        dropout=float(model_cfg["dropout"]),
        interaction_blocks=int(model_cfg.get("interaction_blocks", 0)),
    )
    seed_everything(int(seed))
    model = build_model(spec)
    param_count = sum(p.numel() for p in model.parameters())
    _assert_equal(param_count, EXPECTED_M25_PARAMETER_COUNT, "M25 built model parameter count")
    return model


def split_m25_indices(payload: dict[str, Any], config: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Split dataset examples by seed_index (seed-group split) without trajectory leakage."""
    split_cfg = config["dataset"]["split"]
    val_cfg = split_cfg["validation"]
    modulus = int(val_cfg.get("seed_index_modulus", val_cfg.get("game_index_modulus", 4)))
    remainder = int(val_cfg.get("seed_index_remainder", val_cfg.get("game_index_remainder", 0)))
    
    train_indices, validation_indices = [], []
    for idx, ex in enumerate(payload["examples"]):
        seed_idx = int(ex.get("seed_index", ex["game_index"] // 2 if "game_index" in ex else 0))
        if seed_idx % modulus == remainder:
            validation_indices.append(idx)
        else:
            train_indices.append(idx)
            
    if set(train_indices) & set(validation_indices):
        raise ValueError("M25 train and validation partitions overlap")
    return train_indices, validation_indices


def compute_uniform_policy_ce(validation_examples: list[dict[str, Any]]) -> float:
    """Compute exact theoretical cross-entropy of uniform policy on legal actions: mean(ln(|A_i|))."""
    if not validation_examples:
        raise ValueError("fail-closed: empty validation examples for uniform CE calculation")
    total_log_legal = 0.0
    for ex in validation_examples:
        legal_count = len(ex.get("legal_actions", []))
        if legal_count <= 0:
            raise ValueError(f"fail-closed: invalid legal actions count {legal_count}")
        total_log_legal += math.log(legal_count)
    return total_log_legal / len(validation_examples)


def compute_training_value_prior_baseline_mse(train_targets: torch.Tensor, val_targets: torch.Tensor) -> float:
    """Compute baseline MSE by evaluating constant train-mean outcome vector against validation targets."""
    if train_targets.numel() == 0 or val_targets.numel() == 0:
        raise ValueError("fail-closed: empty value targets for prior MSE calculation")
    prior = train_targets.mean(dim=0, keepdim=True)
    mse = F.mse_loss(prior.expand_as(val_targets), val_targets, reduction="sum").item()
    return mse / (val_targets.shape[0] * 2.0)


def evaluate_cross_distribution_holdout(
    model: nn.Module,
    m24_payload: dict[str, Any],
    holdout_fixture: dict[str, Any],
    catalog: dict[str, Any],
    device: torch.device,
    abort_check: Any = None,
) -> dict[str, Any]:
    """Exact-join and raw zero-shot evaluate 2,002 holdout positions against M07 ground truth."""
    model.eval()
    
    # 1. Index M24 examples by (game_index, ply, actor)
    m24_index: dict[tuple[int, int, int], dict[str, Any]] = {}
    for ex in m24_payload["examples"]:
        key = (int(ex["game_index"]), int(ex["ply"]), int(ex["actor"]))
        if key in m24_index:
            raise RuntimeError(f"fail-closed: duplicate key in M24 dataset: {key}")
        m24_index[key] = ex

    positions = holdout_fixture.get("positions", [])
    expected_count = int(holdout_fixture.get("positions_count", 2002))
    if len(positions) != expected_count:
        raise RuntimeError(f"fail-closed: holdout fixture positions {len(positions)} != expected {expected_count}")

    # Check for duplicate keys in fixture upfront
    seen_keys = set()
    for pos in positions:
        key = (int(pos["game_index"]), int(pos["ply"]), int(pos["actor"]))
        if key in seen_keys:
            raise RuntimeError(f"fail-closed: duplicate key in holdout fixture: {key}")
        seen_keys.add(key)

    matched_positions = 0
    missing_positions = 0
    hash_mismatches = 0
    legal_action_mismatches = 0
    agreements = 0

    with torch.no_grad():
        for pos in positions:
            if abort_check is not None:
                abort_check()

            key = (int(pos["game_index"]), int(pos["ply"]), int(pos["actor"]))
            if key not in m24_index:
                missing_positions += 1
                continue

            ex = m24_index[key]
            if ex.get("observation_hash") != pos.get("observation_hash"):
                hash_mismatches += 1
                continue
            if ex.get("information_set_hash") != pos.get("information_set_hash"):
                hash_mismatches += 1
                continue

            legal_acts = ex.get("legal_actions", [])
            if len(legal_acts) == 0:
                legal_action_mismatches += 1
                continue

            matched_positions += 1
            
            # Encode single sample
            obs_enc = encode_observation(ex["observation"], catalog)
            act_encs = [encode_action(a) for a in legal_acts]
            entities = obs_enc.entities.unsqueeze(0).to(device)
            mask = obs_enc.mask.unsqueeze(0).to(device)
            global_f = obs_enc.global_features.unsqueeze(0).to(device)
            actions = torch.stack(act_encs, dim=0).to(device)
            offsets = torch.tensor([0, len(legal_acts)], dtype=torch.long, device=device)

            logits, _ = model.forward_packed(entities, mask, global_f, actions, offsets)
            top1_idx = logits.argmax(dim=-1).item()

            chosen_json = json.dumps(legal_acts[top1_idx], sort_keys=True)
            if chosen_json == pos["m07_top1"]:
                agreements += 1

    if missing_positions > 0 or hash_mismatches > 0 or legal_action_mismatches > 0 or matched_positions != expected_count:
        raise RuntimeError(
            f"fail-closed: holdout join integrity failed! (matched={matched_positions}/{expected_count}, "
            f"missing={missing_positions}, hash_mismatches={hash_mismatches}, legal_action_mismatches={legal_action_mismatches})"
        )

    agreement_rate = agreements / expected_count
    return {
        "expected_positions": expected_count,
        "matched_positions": matched_positions,
        "missing_positions": missing_positions,
        "duplicate_positions": 0,
        "hash_mismatches": hash_mismatches,
        "legal_action_mismatches": legal_action_mismatches,
        "agreements": agreements,
        "m07_top1_agreement": agreement_rate,
    }


def evaluate_m25_gates(
    val_metrics: dict[str, Any],
    holdout_result: dict[str, Any],
    uniform_ce: float,
    baseline_value_mse: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Compute G1, G2, G3 gates and decision tree for M25."""
    gates = config["offline_gates"]
    g1_cfg = gates["g1_heldout_teacher_fit"]
    g2_cfg = gates["g2_cross_distribution_transfer"]
    g3_cfg = gates["g3_value_non_collapse"]

    val_top1 = float(val_metrics.get("visit_top1", 0.0))
    val_ce = float(val_metrics.get("policy_cross_entropy", 0.0))
    
    if uniform_ce <= 0.0:
        raise ValueError("fail-closed: uniform CE must be positive")
        
    ce_improvement_bps = math.floor(10000.0 * (uniform_ce - val_ce) / uniform_ce)

    g1_pass = (val_top1 >= float(g1_cfg["min_validation_policy_top1"])) and (ce_improvement_bps >= int(g1_cfg["min_policy_ce_improvement_bps_vs_uniform"]))
    
    holdout_agreement = float(holdout_result.get("m07_top1_agreement", 0.0))
    g2_pass = holdout_agreement >= float(g2_cfg["min_cross_distribution_m07_top1"])
    
    val_value_mse = float(val_metrics.get("value_mse", 0.0))
    max_allowed_mse = float(baseline_value_mse) * float(g3_cfg["max_value_mse_multiplier_vs_baseline"])
    g3_pass = val_value_mse <= max_allowed_mse

    # Decision tree mapping
    if not g1_pass:
        decision = "M25_POLICY_TEACHER_FIT_FAIL"
        arena_auth = "NOT_AUTHORIZED"
    elif not g2_pass:
        decision = "M25_TEACHER_FIT_NO_TRANSFER"
        arena_auth = "NOT_AUTHORIZED"
    elif not g3_pass:
        decision = "M25_POLICY_SIGNAL_VALUE_BLOCKED"
        arena_auth = "NOT_AUTHORIZED"
    else:
        decision = "M25_ARENA_ELIGIBLE"
        arena_auth = "AUTHORIZED_COMPACT_128_MATCHES"

    return {
        "g1_heldout_teacher_fit": {
            "pass": g1_pass,
            "validation_policy_top1": val_top1,
            "validation_policy_ce": val_ce,
            "uniform_policy_ce": uniform_ce,
            "policy_ce_improvement_bps_vs_uniform": ce_improvement_bps,
            "threshold_top1": float(g1_cfg["min_validation_policy_top1"]),
            "threshold_ce_bps": int(g1_cfg["min_policy_ce_improvement_bps_vs_uniform"]),
        },
        "g2_cross_distribution_transfer": {
            "pass": g2_pass,
            "holdout_m07_agreement": holdout_agreement,
            "threshold_agreement": float(g2_cfg["min_cross_distribution_m07_top1"]),
            "holdout_details": holdout_result,
        },
        "g3_value_non_collapse": {
            "pass": g3_pass,
            "validation_value_mse": val_value_mse,
            "baseline_value_mse": baseline_value_mse,
            "max_allowed_value_mse": max_allowed_mse,
        },
        "decision": decision,
        "arena_authorization": arena_auth,
    }


def train_m25(
    config: dict[str, Any],
    dataset_path: Path,
    catalog_path: Path,
    holdout_dataset_path: Path,
    holdout_fixture_path: Path,
    out_dir: Path,
    *,
    skip_cooldown: bool = False,
    allow_cpu: bool = False,
) -> dict[str, Any]:
    """Execute full M25 training under fail-closed thermal safety guards and microbatching."""
    validate_m25_config(config, allow_cpu=allow_cpu)

    # 1. Output directory safety assertions: Must NOT exist yet
    if out_dir.exists():
        raise RuntimeError(f"fail-closed: output directory already exists: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=False)

    # 2. Validate catalog
    catalog = load_catalog(catalog_path)
    actual_cat_hash = catalog_semantic_hash(catalog)
    _assert_equal(actual_cat_hash, EXPECTED_CATALOG_HASH, "catalog semantic hash")

    # 3. Load dataset and perform deep provenance checks
    ds_raw = dataset_path.read_text(encoding="utf-8")
    ds_file_sha = file_sha256(dataset_path)
    ds_payload = json.loads(ds_raw)
    ds_sem_hash = validate_m25_dataset_provenance(ds_payload, config)

    train_indices, val_indices = split_m25_indices(ds_payload, config)
    _assert_equal(len(train_indices) + len(val_indices), len(ds_payload["examples"]), "split partition sum")

    # 4. Validate G2 external holdout provenance before starting training
    ho_file_sha = file_sha256(holdout_fixture_path)
    _assert_equal(ho_file_sha, EXPECTED_HOLDOUT_FIXTURE_SHA256, "holdout fixture file sha256")
    
    m24_file_sha = file_sha256(holdout_dataset_path)
    _assert_equal(m24_file_sha, EXPECTED_M24_DATASET_FILE_SHA256, "M24 holdout dataset file sha256")
    
    m24_payload = json.loads(holdout_dataset_path.read_text(encoding="utf-8"))
    m24_sem_hash = self_play_hash(m24_payload)
    _assert_equal(m24_sem_hash, EXPECTED_M24_DATASET_SEMANTIC_HASH, "M24 holdout dataset semantic hash")
    
    holdout_fixture = json.loads(holdout_fixture_path.read_text(encoding="utf-8"))

    # 5. Compute theoretical uniform CE & train-value prior baseline MSE
    val_examples = [ds_payload["examples"][i] for i in val_indices]
    uniform_ce = compute_uniform_policy_ce(val_examples)
    
    train_value_targets = torch.tensor([ex["value_target"] for ex in [ds_payload["examples"][i] for i in train_indices]], dtype=torch.float32)
    val_value_targets = torch.tensor([ex["value_target"] for ex in val_examples], dtype=torch.float32)
    baseline_value_mse = compute_training_value_prior_baseline_mse(train_value_targets, val_value_targets)

    # 6. Build EncodedCache via adapter and load
    cache_dir = out_dir / "encoded_cache"
    build_m25_encoded_cache(
        examples=ds_payload["examples"],
        catalog=catalog,
        output_dir=cache_dir,
        dataset_file_sha256=ds_file_sha,
        dataset_semantic_hash=ds_sem_hash,
        catalog_hash=actual_cat_hash,
    )
    cache = EncodedCache.load(cache_dir)
    cache.validate_identity(
        dataset_file_sha256=ds_file_sha,
        self_play_hash=ds_sem_hash,
        catalog_hash=actual_cat_hash,
        examples=len(ds_payload["examples"]),
    )

    training_cfg = config["training"]
    device = resolve_device(str(training_cfg["device"]))
    logical_batch_size = int(training_cfg["batch_size"])
    epochs = int(training_cfg["epochs"])
    lr = float(training_cfg["learning_rate"])
    wd = float(training_cfg["weight_decay"])
    clip_norm = float(training_cfg["gradient_clip_norm"])
    val_weight = float(training_cfg["value_loss_weight"])
    seed = int(training_cfg["seed"])

    train_dataset = PackedEncodedDataset(cache, train_indices)
    val_dataset = PackedEncodedDataset(cache, val_indices)
    
    train_loader = _loader(train_dataset, logical_batch_size, True, seed, device)
    val_loader = _loader(val_dataset, logical_batch_size, False, None, device)

    # 7. Initialize Model & Optimizer
    model = build_m25_model(config, seed=seed).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)

    # 8. Pre-cooldown (unless skip_cooldown in CPU tests)
    if not skip_cooldown:
        require_fail_closed_cooldown(device=device, target_c=COOLDOWN_TARGET_C, timeout_s=COOLDOWN_TIMEOUT_SECONDS)

    # 9. Training loop under BackgroundThermalGuard with microbatching and pacing
    guard = BackgroundThermalGuard(device=device, interval_s=TELEMETRY_INTERVAL_SECONDS)
    guard.start()

    thermal_pacing: dict[str, float | int] = {
        "physical_microbatch_size": PHYSICAL_MICROBATCH_SIZE,
        "logical_batch_size": logical_batch_size,
        "pause_count": 0,
        "total_pause_seconds": 0.0,
        "max_pause_seconds": 0.0,
    }

    def runtime_abort_check() -> None:
        guard.check()
        wait_for_soft_thermal_envelope(guard, thermal_pacing)

    best_score = float("inf")
    best_epoch = 0
    best_state_dict: dict[str, Any] | None = None
    best_val_metrics: dict[str, Any] = {}
    history = []

    try:
        for ep in range(1, epochs + 1):
            t0 = time.time()
            model.train()
            epoch_loss_sum = torch.zeros((), dtype=torch.float64, device=device)
            seen = 0

            for raw in train_loader:
                guard.check()
                optimizer.zero_grad(set_to_none=True)
                logical_count = int(raw["entities"].shape[0])
                logical_loss_sum = torch.zeros((), dtype=torch.float64, device=device)

                for micro_raw in iter_physical_microbatches(raw, PHYSICAL_MICROBATCH_SIZE):
                    guard.check()
                    batch = {
                        key: value.to(device, non_blocking=device.type == "cuda")
                        for key, value in micro_raw.items()
                    }
                    logits, values = model.forward_packed(
                        batch["entities"], batch["entity_mask"], batch["global_features"],
                        batch["actions"], batch["action_offsets"],
                    )
                    p_loss = packed_policy_loss(logits, batch["policy_target"], batch["action_offsets"])
                    v_loss = F.mse_loss(values, batch["value_target"], reduction="mean")
                    count = int(batch["entities"].shape[0])
                    loss = p_loss + val_weight * v_loss
                    (loss * (count / logical_count)).backward()
                    logical_loss_sum += (loss.detach() * count).to(dtype=torch.float64)
                    guard.check()

                if clip_norm > 0:
                    nn.utils.clip_grad_norm_(model.parameters(), clip_norm)
                optimizer.step()
                epoch_loss_sum += logical_loss_sum
                seen += logical_count
                guard.check()
                wait_for_soft_thermal_envelope(guard, thermal_pacing)

            val_metrics = evaluate(model, val_loader, device, abort_check=runtime_abort_check)
            elapsed = time.time() - t0

            # Selection score = CE + 0.5 * MSE
            score = float(val_metrics["policy_cross_entropy"]) + val_weight * float(val_metrics["value_mse"])
            if score < best_score:
                best_score = score
                best_epoch = ep
                best_state_dict = copy.deepcopy(model.state_dict())
                best_val_metrics = dict(val_metrics)

            ep_record = {
                "epoch": ep,
                "train_mean_loss": float((epoch_loss_sum / max(seen, 1)).item()),
                "validation": val_metrics,
                "selection_score": score,
                "elapsed_s": elapsed,
            }
            history.append(ep_record)
            print(f"Epoch {ep:2d}/{epochs}: score={score:.4f} (best={best_score:.4f} @ ep {best_epoch}), val_top1={val_metrics['visit_top1']*100:.2f}%, val_ce={val_metrics['policy_cross_entropy']:.4f}, val_mse={val_metrics['value_mse']:.4f} ({elapsed:.1f}s)")

        # 10. Evaluate external holdout (2,002 positions) under thermal guard
        assert best_state_dict is not None
        model.load_state_dict(best_state_dict)

        holdout_result = evaluate_cross_distribution_holdout(
            model=model,
            m24_payload=m24_payload,
            holdout_fixture=holdout_fixture,
            catalog=catalog,
            device=device,
            abort_check=runtime_abort_check,
        )
        print(f"External Cross-Distribution Holdout (2002 pos): M07 Agreement = {holdout_result['m07_top1_agreement']*100:.2f}%")
    finally:
        guard.stop()

    # 11. Evaluate offline gates & decision tree
    gates_eval = evaluate_m25_gates(
        val_metrics=best_val_metrics,
        holdout_result=holdout_result,
        uniform_ce=uniform_ce,
        baseline_value_mse=baseline_value_mse,
        config=config,
    )
    print(f"M25 Offline Gates Decision: {gates_eval['decision']} (Arena Auth: {gates_eval['arena_authorization']})")

    # 12. Serialize outputs
    manifest_sha = cache.manifest.get("manifest_sha256")
    cfg_hash = training_config_hash(config)
    cfg_rev = config.get("revision", "m07-search-teacher-bootstrap-v2")

    ckpt_meta = {
        "format": "effective-splendor-gpu-checkpoint",
        "version": 1,
        "model_id": config["model"]["model_id"],
        "model_role": "candidate",
        "milestone": "M25",
        "m25_config_revision": cfg_rev,
        "training_config_hash": cfg_hash,
        "source_dataset_file_sha256": ds_file_sha,
        "source_dataset_semantic_hash": ds_sem_hash,
        "encoded_cache_manifest_sha256": manifest_sha,
        "catalog_hash": actual_cat_hash,
        "parameter_count": EXPECTED_M25_PARAMETER_COUNT,
        "best_epoch": best_epoch,
        "best_selection_score": best_score,
        "train_examples": len(train_indices),
        "validation_examples": len(val_indices),
        "uniform_policy_ce": uniform_ce,
        "baseline_value_mse": baseline_value_mse,
    }
    ckpt_file = out_dir / "checkpoint.pt"
    torch.save({"metadata": ckpt_meta, "state_dict": best_state_dict}, ckpt_file)
    ckpt_sha = file_sha256(ckpt_file)
    sem_hash = checkpoint_semantic_hash(ckpt_meta, best_state_dict)

    report = {
        "format": "effective-splendor-m25-training-report",
        "version": 1,
        "milestone": "M25",
        "model_id": config["model"]["model_id"],
        "m25_config_revision": cfg_rev,
        "training_config_hash": cfg_hash,
        "source_dataset_file_sha256": ds_file_sha,
        "source_dataset_semantic_hash": ds_sem_hash,
        "encoded_cache_manifest_sha256": manifest_sha,
        "checkpoint_file_sha256": ckpt_sha,
        "checkpoint_hash": sem_hash,
        "best_epoch": best_epoch,
        "best_selection_score": best_score,
        "validation": best_val_metrics,
        "history": history,
        "holdout": holdout_result,
        "gates": gates_eval,
    }
    (out_dir / "training-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "offline-result.json").write_text(json.dumps(gates_eval, indent=2) + "\n", encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train M25 M07 search-teacher bootstrap candidate.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"))
    parser.add_argument("--holdout-dataset", type=Path, default=Path("local-artifacts/m24-self-play-s2-v1/self-play.json"))
    parser.add_argument("--holdout-fixture", type=Path, default=Path("benchmarks/m24-s2-2002-audit-holdout.json"))
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    configure_cpu_runtime()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    train_m25(
        config=config,
        dataset_path=args.dataset,
        catalog_path=args.catalog,
        holdout_dataset_path=args.holdout_dataset,
        holdout_fixture_path=args.holdout_fixture,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
