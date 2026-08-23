"""M25 M07 Search-Teacher Bootstrap v2 formal trainer and offline gate evaluator."""

from __future__ import annotations

import argparse
import copy
import json
import math
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
    dataset_hash,
    load_catalog,
)
from splendor_gpu.encoded_cache import EncodedCache, PackedEncodedDataset, collate_packed
from splendor_gpu.encoding import encode_action, encode_observation
from splendor_gpu.model import ModelSpec, build_model
from splendor_gpu.runtime import configure_cpu_runtime
from splendor_gpu.self_play_train import evaluate
from splendor_gpu.train import (
    checkpoint_semantic_hash,
    file_sha256,
    resolve_device,
    seed_everything,
)
from splendor_gpu.interaction_train import (
    training_config_hash,
    BackgroundThermalGuard,
    require_fail_closed_cooldown,
    COOLDOWN_TARGET_C,
    COOLDOWN_TIMEOUT_SECONDS,
    TELEMETRY_INTERVAL_SECONDS,
    EXPECTED_CPU_THREADS,
    EXPECTED_CATALOG_HASH,
    _IndexDataset,
    _loader,
)

EXPECTED_M25_FORMAT = "effective-splendor-m25-m07-search-teacher-bootstrap"
EXPECTED_M25_PARAMETER_COUNT = 949060
EXPECTED_M25_GAMES = 256
EXPECTED_M25_TRAIN_GAMES = 192
EXPECTED_M25_VAL_GAMES = 64
EXPECTED_UNIFORM_FLOOR_MICROS = 100000


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def validate_m25_config(config: dict[str, Any]) -> None:
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
    _assert_equal(len(seeds), EXPECTED_M25_GAMES, "game seeds count")
    expected_seeds = [20260825 + i for i in range(EXPECTED_M25_GAMES)]
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
    _assert_equal(int(split["validation"]["game_index_modulus"]), 4, "split val modulus")
    _assert_equal(int(split["validation"]["game_index_remainder"]), 0, "split val remainder")
    _assert_equal(int(split["validation"]["games"]), EXPECTED_M25_VAL_GAMES, "split val games")
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
    _assert_equal(tr.get("device"), "cuda", "training device")
    _assert_equal(int(tr.get("seed", 0)), 280229, "training seed")
    _assert_equal(int(tr.get("shuffle_seed", 0)), 280229, "training shuffle_seed")
    _assert_equal(int(tr.get("epochs", 0)), 32, "training epochs")
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
    _assert_equal(ho.get("fixture_sha256"), "331654ba370a489053bcf6cd0452d7aa4883b6c64d5db0be757c4a42860f05f8", "holdout fixture_sha256")
    _assert_equal(ho.get("source_dataset_file_sha256"), "ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f", "holdout source dataset sha")
    _assert_equal(ho.get("source_dataset_semantic_hash"), "b035d4959e78b8e661d0f13ed4384d67a1fdefa8b5d6ed24eb5d67622594b90b", "holdout source dataset sem hash")

    # Offline gates
    og = config["offline_gates"]
    _assert_equal(float(og["g1_heldout_teacher_fit"]["min_validation_policy_top1"]), 0.4500, "G1 min top1")
    _assert_equal(int(og["g1_heldout_teacher_fit"]["min_policy_ce_improvement_bps_vs_uniform"]), 1000, "G1 min CE bps")
    _assert_equal(float(og["g2_cross_distribution_transfer"]["min_cross_distribution_m07_top1"]), 0.3800, "G2 min top1")
    _assert_equal(float(og["g3_value_non_collapse"]["max_value_mse_multiplier_vs_baseline"]), 1.02, "G3 max multiplier")


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


def _train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    value_loss_weight: float,
    clip_norm: float,
    abort_check: Any = None,
) -> dict[str, float]:
    model.train()
    total_loss = 0.0
    total_policy_loss = 0.0
    total_value_loss = 0.0
    examples = 0

    for batch in loader:
        if abort_check is not None:
            abort_check()

        optimizer.zero_grad(set_to_none=True)
        entities = batch["entities"].to(device)
        mask = batch["entity_mask"].to(device)
        global_f = batch["global_features"].to(device)
        actions = batch["actions"].to(device)
        offsets = batch["action_offsets"].to(device)
        p_target = batch["policy_target"].to(device)
        v_target = batch["value_target"].to(device)

        logits, values = model.forward_packed(entities, mask, global_f, actions, offsets)
        
        # Segmented policy loss
        counts = offsets[1:] - offsets[:-1]
        batch_size = counts.shape[0]
        segment_ids = torch.repeat_interleave(torch.arange(batch_size, device=device), counts)
        max_per_seg = torch.full((batch_size,), -torch.inf, dtype=logits.dtype, device=device)
        max_per_seg.scatter_reduce_(0, segment_ids, logits, reduce="amax")
        shifted_exp = torch.exp(logits - max_per_seg[segment_ids])
        sum_exp_per_seg = torch.zeros(batch_size, dtype=logits.dtype, device=device)
        sum_exp_per_seg.scatter_add_(0, segment_ids, shifted_exp)
        lse_per_seg = max_per_seg + torch.log(sum_exp_per_seg)
        log_probs = logits - lse_per_seg[segment_ids]
        
        prod = p_target * log_probs
        loss_per_seg = torch.zeros(batch_size, dtype=logits.dtype, device=device)
        loss_per_seg.scatter_add_(0, segment_ids, -prod)
        policy_loss = loss_per_seg.sum() / batch_size

        value_loss = F.mse_loss(values, v_target, reduction="mean")
        loss = policy_loss + value_loss_weight * value_loss

        loss.backward()
        if clip_norm > 0:
            nn.utils.clip_grad_norm_(model.parameters(), clip_norm)
        optimizer.step()

        total_loss += loss.item() * batch_size
        total_policy_loss += policy_loss.item() * batch_size
        total_value_loss += value_loss.item() * batch_size
        examples += batch_size

    return {
        "loss": total_loss / examples,
        "policy_loss": total_policy_loss / examples,
        "value_loss": total_value_loss / examples,
    }


def train_m25(
    config: dict[str, Any],
    dataset_path: Path,
    catalog_path: Path,
    holdout_dataset_path: Path,
    holdout_fixture_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    """Execute full M25 training under fail-closed thermal safety guards."""
    validate_m25_config(config)

    # 1. Output directory safety assertions: Must NOT exist yet
    if out_dir.exists():
        raise RuntimeError(f"fail-closed: output directory already exists: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=False)

    # 2. Validate catalog
    catalog = load_catalog(catalog_path)
    actual_cat_hash = catalog_semantic_hash(catalog)
    _assert_equal(actual_cat_hash, EXPECTED_CATALOG_HASH, "catalog semantic hash")

    # 3. Load dataset and perform provenance checks
    ds_raw = dataset_path.read_text(encoding="utf-8")
    ds_payload = json.loads(ds_raw)
    _assert_equal(ds_payload.get("format"), "effective-splendor-search-teacher-dataset-v1", "dataset format")
    _assert_equal(ds_payload.get("generator_agent"), "m07-determinization-champion", "dataset generator_agent")
    _assert_equal(len(ds_payload.get("games", [])), EXPECTED_M25_GAMES, "dataset games count")

    train_indices, val_indices = split_m25_indices(ds_payload, config)
    _assert_equal(len(train_indices) + len(val_indices), len(ds_payload["examples"]), "split partition sum")

    # 4. Compute theoretical uniform CE & train-value prior baseline MSE
    val_examples = [ds_payload["examples"][i] for i in val_indices]
    uniform_ce = compute_uniform_policy_ce(val_examples)
    
    train_value_targets = torch.tensor([ex["value_target"] for ex in [ds_payload["examples"][i] for i in train_indices]], dtype=torch.float32)
    val_value_targets = torch.tensor([ex["value_target"] for ex in val_examples], dtype=torch.float32)
    baseline_value_mse = compute_training_value_prior_baseline_mse(train_value_targets, val_value_targets)

    # 5. Build EncodedCache
    cache_dir = out_dir / "encoded_cache"
    cache = EncodedCache.build(
        dataset_path=dataset_path,
        catalog_path=catalog_path,
        cache_dir=cache_dir,
    )

    training_cfg = config["training"]
    device = resolve_device(str(training_cfg["device"]))
    batch_size = int(training_cfg["batch_size"])
    epochs = int(training_cfg["epochs"])
    lr = float(training_cfg["learning_rate"])
    wd = float(training_cfg["weight_decay"])
    clip_norm = float(training_cfg["gradient_clip_norm"])
    val_weight = float(training_cfg["value_loss_weight"])
    seed = int(training_cfg["seed"])

    train_dataset = PackedEncodedDataset(cache, train_indices)
    val_dataset = PackedEncodedDataset(cache, val_indices)
    
    train_loader = _loader(train_dataset, batch_size, True, seed, device)
    val_loader = _loader(val_dataset, batch_size, False, None, device)

    # 6. Initialize Model & Optimizer
    model = build_m25_model(config, seed=seed).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)

    # 7. Pre-cooldown
    require_fail_closed_cooldown(device=device, target_c=COOLDOWN_TARGET_C, timeout_s=COOLDOWN_TIMEOUT_SECONDS)

    # 8. Training loop under BackgroundThermalGuard
    guard = BackgroundThermalGuard(device=device, interval_s=TELEMETRY_INTERVAL_SECONDS)
    guard.start()

    best_score = float("inf")
    best_epoch = 0
    best_state_dict: dict[str, Any] | None = None
    best_val_metrics: dict[str, Any] = {}
    history = []

    try:
        for ep in range(1, epochs + 1):
            t0 = time.time()
            train_metrics = _train_one_epoch(
                model=model,
                loader=train_loader,
                optimizer=optimizer,
                device=device,
                value_loss_weight=val_weight,
                clip_norm=clip_norm,
                abort_check=guard.check,
            )
            val_metrics = evaluate(model, val_loader, device, abort_check=guard.check)
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
                "train": train_metrics,
                "validation": val_metrics,
                "selection_score": score,
                "elapsed_s": elapsed,
            }
            history.append(ep_record)
            print(f"Epoch {ep:2d}/{epochs}: score={score:.4f} (best={best_score:.4f} @ ep {best_epoch}), val_top1={val_metrics['visit_top1']*100:.2f}%, val_ce={val_metrics['policy_cross_entropy']:.4f}, val_mse={val_metrics['value_mse']:.4f} ({elapsed:.1f}s)")
    finally:
        guard.stop()

    assert best_state_dict is not None
    model.load_state_dict(best_state_dict)

    # 9. Evaluate external holdout (2,002 positions)
    m24_payload = json.loads(holdout_dataset_path.read_text(encoding="utf-8"))
    holdout_fixture = json.loads(holdout_fixture_path.read_text(encoding="utf-8"))
    holdout_result = evaluate_cross_distribution_holdout(
        model=model,
        m24_payload=m24_payload,
        holdout_fixture=holdout_fixture,
        catalog=catalog,
        device=device,
    )
    print(f"External Cross-Distribution Holdout (2002 pos): M07 Agreement = {holdout_result['m07_top1_agreement']*100:.2f}%")

    # 10. Evaluate offline gates & decision tree
    gates_eval = evaluate_m25_gates(
        val_metrics=best_val_metrics,
        holdout_result=holdout_result,
        uniform_ce=uniform_ce,
        baseline_value_mse=baseline_value_mse,
        config=config,
    )
    print(f"M25 Offline Gates Decision: {gates_eval['decision']} (Arena Auth: {gates_eval['arena_authorization']})")

    # 11. Serialize outputs
    ckpt_meta = {
        "format": "effective-splendor-gpu-checkpoint",
        "version": 1,
        "model_id": config["model"]["model_id"],
        "model_role": "candidate",
        "milestone": "M25",
        "training_config_hash": training_config_hash(config),
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
