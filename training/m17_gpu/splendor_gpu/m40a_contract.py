"""M40A machine-verifiable execution contract: the single source for the
canonical plan, seed schedules, checkpoint identity, and validation.

Everything here mirrors the frozen design (docs/
m40a-predictive-critic-warmstart-ab.md, design SHA 09fd8ec, approval
dacb527). Changing any value is an amendment, not an implementation
detail.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .m39a_contract import (
    GAMES_PER_CYCLE as M39A_GAMES_PER_CYCLE,
    LEAGUE_ORDER,
    action_index,
    decision_seed,
)
from .m40a_constants import (
    ANCHOR_CRITICAL_DF63,
    AUX_FAMILY_COEFFICIENT,
    AUX_COEFFICIENT_BUDGET,
    DESIGN_SHA,
    D2_SEED_BASE,
    D2_SEED_BLOCKS,
    ENTROPY_COEFFICIENT,
    GAE_LAMBDA,
    GRAD_CLIP_NORM,
    H1_CRITICAL_DF127,
    H1_SEED_BASE,
    H1_SEED_BLOCKS,
    LEAGUE_CRITICAL_DF31,
    LEAGUE_SEED_BASE,
    LEAGUE_SEED_BLOCKS,
    LR_WAYPOINTS,
    M07_SEED_BASE,
    M07_SEED_BLOCKS,
    PPO_CLIP_EPSILON,
    PPO_CYCLES,
    PPO_EPOCHS_PER_CYCLE,
    PPO_MINIBATCH,
    PPO_TRAINER_SEED,
    TIMING_HORIZONS,
    TRAINING_SEED_BASE,
    TRAINING_SEED_BLOCKS,
    VALUE_COEFFICIENT,
    VP_BINS,
    WEIGHT_DECAY,
)

APPROVAL_SHA = "dacb527"
PLAN_FORMAT = "effective-splendor-m40a-plan"
PLAN_VERSION = 1

M40A_AGENT_NAME = "effective-splendor-m40a-predictive-agent-v1"
M40A_SERVER_FORMAT = "effective-splendor-m40a-inference-server"
M40A_SERVER_VERSION = 1
M40A_SIDECAR_FORMAT = "effective-splendor-m40a-sidecar"
M40A_SIDECAR_VERSION = 1

M40A_BATCH_FORMAT = "effective-splendor-m40a-authoritative-batch"
M40A_BATCH_VERSION = 1
M40A_ONLINE_MANIFEST_FORMAT = "effective-splendor-m40a-online-materialization-manifest"
M40A_OFFLINE_MANIFEST_FORMAT = "effective-splendor-m40a-materialization-manifest"
M40A_MANIFEST_VERSION = 1

CHECKPOINT_FORMAT = "effective-splendor-m40a-checkpoint"
CHECKPOINT_VERSION = 1
MODEL_ID = "m40a-predictive-critic-warmstart-v1"

# The frozen D2-v2 source (inherited identity, same file as M39A's base).
D2_CHECKPOINT_REL = "local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt"
D2_CHECKPOINT_SHA256 = (
    "113372fc1092e611804cb7261844ac2a104608772f68ab74a854a038370c7e17"
)
CATALOG_REL = "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
FROZEN_CATALOG_SHA256 = (
    "4e6e5bc7f6134500fc501674e1be97dd34dd5306188dd2fb9220e6d8c58612d4"
)
M39A_PLAN_REL = "benchmarks/m39a-arena-driven-policy-value-rl.plan.json"
M39A_PLAN_HASH = "06cbd7b2413b7e640402799ff25c25ae57985ab3ea25b113b3eddf053f2841d6"

# The frozen split over the historical M39A offline dataset.
FROZEN_SPLIT_MANIFEST_HASH = (
    "265edc3923d28a15238e89a52926634e20ce157bd65c674336224bcde3ae3946"
)


def canonical_json(value: Any) -> bytes:
    """The canonical serialization for M40A hashing (sorted keys, compact)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(plan)).hexdigest()


def build_plan() -> dict[str, Any]:
    """The canonical M40A plan (frozen values only)."""
    return {
        "format": PLAN_FORMAT,
        "version": PLAN_VERSION,
        "milestone": "M40A",
        "design_sha": DESIGN_SHA,
        "approval_sha": APPROVAL_SHA,
        "round": {
            "cycles": PPO_CYCLES,
            "games_per_cycle": 512,
            "training_seed_base": TRAINING_SEED_BASE,
            "training_seed_blocks": TRAINING_SEED_BLOCKS,
            "ply_cap": 150,
        },
        "initialization": {
            "d2_checkpoint": D2_CHECKPOINT_REL,
            "d2_checkpoint_sha256": D2_CHECKPOINT_SHA256,
            "head_init_seed": 20_260_829,
            "load_prefixes": [
                "entity_encoder.",
                "entity_gate.",
                "global_encoder.",
                "mix.",
                "blocks.",
                "norm.",
                "action_encoder.",
                "policy.",
            ],
            "discard_prefixes": ["value."],
        },
        "catalog": {"path": CATALOG_REL, "sha256": FROZEN_CATALOG_SHA256},
        "trainer": {
            "trainer_seed": PPO_TRAINER_SEED,
            "epochs_per_cycle": PPO_EPOCHS_PER_CYCLE,
            "minibatch_size": PPO_MINIBATCH,
            "gamma": 1.0,
            "gae_lambda": GAE_LAMBDA,
            "ppo_clip": PPO_CLIP_EPSILON,
            "entropy_coefficient": ENTROPY_COEFFICIENT,
            "value_coefficient": VALUE_COEFFICIENT,
            "weight_decay": WEIGHT_DECAY,
            "gradient_clip_norm": GRAD_CLIP_NORM,
            "lr_waypoints": LR_WAYPOINTS,
            "aux_family_coefficient": AUX_FAMILY_COEFFICIENT,
            "aux_coefficient_budget": AUX_COEFFICIENT_BUDGET,
        },
        "pretrain": {
            "source_plan": M39A_PLAN_REL,
            "source_plan_hash": M39A_PLAN_HASH,
            "epochs": 16,
            "batch": 512,
            "lr": 3e-4,
            "weight_decay": 1e-4,
            "shuffle_seed": 40_260_902,
            "split_identity_seed": 40_260_901,
            "expected_split_manifest_hash": FROZEN_SPLIT_MANIFEST_HASH,
            "forced_train_game": 2785,
        },
        "heads": {
            "outcome": 3,
            "vp_bins": VP_BINS,
            "vp_difference_normalizer": 15.0,
            "timing_horizons": list(TIMING_HORIZONS),
        },
        "evaluation": {
            "h1": {
                "seed_base": H1_SEED_BASE,
                "seed_blocks": H1_SEED_BLOCKS,
                "critical_value": H1_CRITICAL_DF127,
            },
            "league": {
                "seed_base": LEAGUE_SEED_BASE,
                "seed_blocks": LEAGUE_SEED_BLOCKS,
                "critical_value": LEAGUE_CRITICAL_DF31,
                "league_order": list(LEAGUE_ORDER),
            },
            "m07_anchor": {
                "seed_base": M07_SEED_BASE,
                "seed_blocks": M07_SEED_BLOCKS,
                "critical_value": ANCHOR_CRITICAL_DF63,
            },
            "d2_anchor": {
                "seed_base": D2_SEED_BASE,
                "seed_blocks": D2_SEED_BLOCKS,
                "critical_value": ANCHOR_CRITICAL_DF63,
            },
            "formal_checkpoint": "cycle-4-final-only",
        },
    }


def validate_plan(plan: dict[str, Any]) -> str:
    """Fail-closed validation; returns the plan hash."""
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise ValueError("unsupported M40A plan format/version")
    if plan.get("design_sha") != DESIGN_SHA:
        raise ValueError("plan design_sha mismatch")
    if plan.get("approval_sha") != APPROVAL_SHA:
        raise ValueError("plan approval_sha mismatch")
    canonical = build_plan()
    if plan != canonical:
        differing = sorted(
            key
            for key in set(plan) | set(canonical)
            if plan.get(key) != canonical.get(key)
        )
        raise ValueError(f"plan deviates from the canonical frozen plan: {differing}")
    return plan_hash(plan)


def checkpoint_semantic_hash(metadata: dict[str, Any], state: dict[str, Any]) -> str:
    """The canonical M40A checkpoint semantic hash (top-level
    `checkpoint_hash`): SHA-256 over the canonical metadata followed by
    the ordered canonical tensors."""
    hasher = hashlib.sha256()
    hasher.update(canonical_json(metadata))
    for name in sorted(state):
        tensor = state[name].detach().cpu().contiguous()
        hasher.update(name.encode("utf-8"))
        hasher.update(str(tuple(tensor.shape)).encode("utf-8"))
        hasher.update(str(tensor.dtype).encode("utf-8"))
        hasher.update(tensor.numpy().tobytes())
    return hasher.hexdigest()


def online_seed(game_index: int) -> int:
    """The frozen M40A online collection seed: 8_000_000 + g // 2."""
    if not 0 <= game_index < TRAINING_SEED_BLOCKS * 2:
        raise ValueError("game_index outside frozen M40A online round")
    return TRAINING_SEED_BASE + game_index // 2


def online_scheduled_game(game_index: int) -> dict[str, Any]:
    """The M40A online schedule entry: the M39A cycle-local bucket mix,
    re-based on the 8M seed range, with the M40A learner identity."""
    from .m39a_contract import scheduled_game as m39a_scheduled

    base = m39a_scheduled(game_index)
    return {
        "game_index": game_index,
        "cycle": (game_index // 512) + 1,
        "cycle_ordinal": game_index % 512,
        "seed": online_seed(game_index),
        "bucket": base.bucket,
        "opponent": base.opponent,
        "learner_seats": list(base.learner_seats),
        "learner_runtime": M40A_AGENT_NAME,
    }


def online_cycle_schedule(cycle: int) -> list[dict[str, Any]]:
    if not 1 <= cycle <= PPO_CYCLES:
        raise ValueError("cycle must be in 1..=4")
    start = (cycle - 1) * 512
    return [online_scheduled_game(i) for i in range(start, start + 512)]


def crn_schedule_hash(arm_stripped: bool = True) -> str:
    """Canonical hash of the full 2,048-entry shared A/B schedule.

    The schedule is arm-independent by construction; `arm_stripped` is
    accepted for symmetry with collection-manifest comparisons.
    """
    schedule = [online_scheduled_game(i) for i in range(TRAINING_SEED_BLOCKS * 2)]
    return hashlib.sha256(canonical_json(schedule)).hexdigest()
