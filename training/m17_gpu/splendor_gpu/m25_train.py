"""M25 M07 Search-Teacher Bootstrap v2 trainer and offline gate evaluator."""

import argparse
import json
import math
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
from splendor_gpu.train import seed_everything
from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset
from splendor_gpu.model import ModelSpec, build_model
from splendor_gpu.runtime import configure_cpu_runtime
from splendor_gpu.self_play_train import evaluate
from splendor_gpu.train import file_sha256, resolve_device
from splendor_gpu.interaction_train import (
    training_config_hash,
    BackgroundThermalGuard,
    require_fail_closed_cooldown,
    COOLDOWN_TARGET_C,
    COOLDOWN_TIMEOUT_SECONDS,
    TELEMETRY_INTERVAL_SECONDS,
    EXPECTED_CPU_THREADS,
    EXPECTED_CATALOG_HASH,
    _loader,
    _IndexDataset,
)

EXPECTED_M25_FORMAT = "effective-splendor-m25-m07-search-teacher-bootstrap"
EXPECTED_M25_PARAMETER_COUNT = 949060


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def validate_m25_config(config: dict[str, Any]) -> None:
    _assert_equal(config.get("format"), EXPECTED_M25_FORMAT, "M25 config format")
    _assert_equal(config.get("version"), 1, "M25 config version")
    _assert_equal(config.get("milestone"), "M25", "M25 config milestone")
    
    model = config["model"]
    _assert_equal(model["architecture"], "entity_mixer", "M25 model architecture")
    _assert_equal(int(model["hidden_dim"]), 192, "M25 model hidden_dim")
    _assert_equal(int(model["blocks"]), 4, "M25 model blocks")
    _assert_equal(float(model["dropout"]), 0.0, "M25 model dropout")
    _assert_equal(int(model.get("interaction_blocks", 0)), 0, "M25 interaction_blocks")
    _assert_equal(int(model["expected_parameter_count"]), EXPECTED_M25_PARAMETER_COUNT, "M25 parameter count")

    training = config["training"]
    _assert_equal(int(training["batch_size"]), 128, "M25 batch_size")
    _assert_equal(int(training["epochs"]), 32, "M25 epochs")
    _assert_equal(float(training["learning_rate"]), 0.0001, "M25 learning_rate")
    _assert_equal(float(training["weight_decay"]), 0.0001, "M25 weight_decay")
    _assert_equal(float(training["value_loss_weight"]), 0.5, "M25 value_loss_weight")
    _assert_equal(float(training["gradient_clip_norm"]), 1.0, "M25 gradient_clip_norm")


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
    """Split dataset examples by game_index without trajectory leakage."""
    split_cfg = config["dataset"]["split"]
    modulus = int(split_cfg["validation"]["game_index_modulus"])
    remainder = int(split_cfg["validation"]["game_index_remainder"])
    
    train_indices, validation_indices = [], []
    for idx, ex in enumerate(payload["examples"]):
        game_idx = int(ex["game_index"])
        if game_idx % modulus == remainder:
            validation_indices.append(idx)
        else:
            train_indices.append(idx)
            
    if set(train_indices) & set(validation_indices):
        raise ValueError("M25 train and validation partitions overlap")
    return train_indices, validation_indices


def evaluate_cross_distribution_holdout(
    model: nn.Module,
    holdout_positions: list[dict[str, Any]],
    cache: EncodedCache,
    device: torch.device,
) -> float:
    """Evaluate raw model top-1 agreement against M07 on the 2,002 audited holdout positions."""
    model.eval()
    if not holdout_positions:
        return 0.0

    agreements = 0
    with torch.no_grad():
        # Match each holdout position by observation hash or index in cache
        for pos in holdout_positions:
            obs_hash = pos["observation_hash"]
            m07_top1 = pos["m07_top1"]
            
            # Find sample in cache
            sample_idx = cache.find_by_observation_hash(obs_hash) if hasattr(cache, "find_by_observation_hash") else None
            if sample_idx is None:
                continue
                
            sample = cache.sample(sample_idx)
            batch = collate([sample])
            
            logits, _ = model.forward_packed(
                batch["entities"].to(device),
                batch["entity_mask"].to(device),
                batch["global_features"].to(device),
                batch["actions"].to(device),
                batch["action_offsets"].to(device),
            )
            top1_idx = logits.argmax(dim=-1).item()
            # Action at top1_idx
            act_json = json.dumps(sample["legal_actions"][top1_idx], sort_keys=True)
            if act_json == m07_top1:
                agreements += 1

    return agreements / len(holdout_positions)


def evaluate_m25_gates(
    val_metrics: dict[str, Any],
    holdout_m07_agreement: float,
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
    val_uniform_ce = float(val_metrics.get("uniform_policy_cross_entropy", 3.2))
    
    # CE relative improvement vs legal uniform
    ce_improvement_bps = math.floor(10000.0 * (val_uniform_ce - val_ce) / val_uniform_ce) if val_uniform_ce > 0 else 0

    g1_pass = (val_top1 >= float(g1_cfg["min_validation_policy_top1"])) and (ce_improvement_bps >= int(g1_cfg["min_policy_ce_improvement_bps_vs_uniform"]))
    g2_pass = holdout_m07_agreement >= float(g2_cfg["min_cross_distribution_m07_top1"])
    
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
            "policy_ce_improvement_bps_vs_uniform": ce_improvement_bps,
        },
        "g2_cross_distribution_transfer": {
            "pass": g2_pass,
            "holdout_m07_agreement": holdout_m07_agreement,
            "baseline_m22_agreement": float(config["external_holdout"]["baseline_m22_agreement"]),
        },
        "g3_value_non_collapse": {
            "pass": g3_pass,
            "validation_value_mse": val_value_mse,
            "max_allowed_value_mse": max_allowed_mse,
        },
        "decision": decision,
        "arena_authorization": arena_auth,
    }
