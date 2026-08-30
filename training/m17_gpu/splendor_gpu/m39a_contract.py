"""Machine-verifiable contracts for M39A arena-driven policy/value RL.

This module intentionally contains no Arena process or torch dependency.  It
owns the deterministic schedule, RNG, trajectory DTO validation, return
mapping, GAE construction, and canonical plan hash used by both collection and
training.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


PLAN_FORMAT = "effective-splendor-m39a-plan"
PLAN_VERSION = 1
SIDECAR_FORMAT = "effective-splendor-m39a-trajectory-sidecar"
SIDECAR_VERSION = 1
BATCH_FORMAT = "effective-splendor-m39a-authoritative-batch"
BATCH_VERSION = 1

MASK64 = (1 << 64) - 1
SPLITMIX64_GAMMA = 0x9E3779B97F4A7C15
SPLITMIX64_MUL1 = 0xBF58476D1CE4E5B9
SPLITMIX64_MUL2 = 0x94D049BB133111EB
SHUFFLE_CYCLE_MIX = 0xD1B54A32D192ED03
SHUFFLE_EPOCH_MIX = 0xABC98388FB8FAC03
SHUFFLE_INDEX_MIX = 0x8CB92BA72F3D8DD7

GAMES_PER_CYCLE = 512
CYCLES = 8
TRAINING_GAME_SEED_BASE = 4_000_000
DECISION_SEED_BASE = 7_000_000
TRAINER_SEED = 40_260_830
HEAD_INIT_SEED = 20_260_829

LEAGUE_ORDER = (
    "M24-S2",
    "M25-D2-v2",
    "M28A",
    "M28B",
    "M29A-v2",
    "M31A",
    "M32A",
    "M33A",
    "M34A",
)

LR_WAYPOINTS = (
    1.000000000000e-4,
    9.554359905560e-5,
    8.305704108364e-5,
    6.501344202804e-5,
    4.498655797196e-5,
    2.694295891636e-5,
    1.445640094440e-5,
    1.000000000000e-5,
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    validate_plan(plan)
    return plan


def plan_hash(plan: dict[str, Any]) -> str:
    validate_plan(plan)
    return sha256_hex(b"effective-splendor-m39a-plan-v1\0" + canonical_json(plan))


def _require_exact(container: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for key, value in expected.items():
        if container.get(key) != value:
            raise ValueError(f"{label}.{key} must equal {value!r}")


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise ValueError("unsupported M39A plan format/version")
    _require_exact(
        plan.get("round", {}),
        {
            "player_count": 2,
            "cycles": CYCLES,
            "games_per_cycle": GAMES_PER_CYCLE,
            "training_game_seed_base": TRAINING_GAME_SEED_BASE,
            "decision_seed_base": DECISION_SEED_BASE,
            "ply_cap": 150,
        },
        "round",
    )
    _require_exact(
        plan.get("trainer", {}),
        {
            "trainer_seed": TRAINER_SEED,
            "head_init_seed": HEAD_INIT_SEED,
            "epochs_per_cycle": 4,
            "minibatch_size": 512,
            "gamma": 1.0,
            "gae_lambda": 0.95,
            "advantage_variance": "population",
            "advantage_epsilon": 1e-8,
            "ppo_clip": 0.2,
            "entropy_coefficient": 0.01,
            "value_coefficient": 0.5,
            "aux_coefficient": 0.25,
            "weight_decay": 1e-4,
            "gradient_clip_norm": 1.0,
            "adamw_betas": [0.9, 0.999],
            "adamw_eps": 1e-8,
            "adamw_amsgrad": False,
            "adamw_maximize": False,
            "adamw_foreach": False,
            "adamw_fused": False,
            "adamw_capturable": False,
            "adamw_differentiable": False,
            "lr_waypoints": list(LR_WAYPOINTS),
        },
        "trainer",
    )
    schedule = plan.get("schedule", {})
    if schedule.get("league_order") != list(LEAGUE_ORDER):
        raise ValueError("schedule.league_order does not match frozen order")
    if schedule.get("cycle_bucket_counts") != {
        "random": 16,
        "heuristic": 48,
        "m07": 128,
        "league": 128,
        "self_play": 192,
    }:
        raise ValueError("schedule.cycle_bucket_counts does not match frozen mix")


def splitmix64(value: int) -> int:
    """One-shot SplitMix64 output with explicit wrapping arithmetic."""

    z = (int(value) + SPLITMIX64_GAMMA) & MASK64
    z = ((z ^ (z >> 30)) * SPLITMIX64_MUL1) & MASK64
    z = ((z ^ (z >> 27)) * SPLITMIX64_MUL2) & MASK64
    return (z ^ (z >> 31)) & MASK64


def game_sampling_seed(game_index: int, seat: int) -> int:
    if game_index < 0 or seat not in (0, 1):
        raise ValueError("game_index must be non-negative and seat must be 0 or 1")
    return splitmix64(DECISION_SEED_BASE + 2 * game_index + seat)


def decision_seed(game_index: int, seat: int, request_id: int) -> int:
    if request_id <= 0:
        raise ValueError("request_id starts at one")
    mixed = game_sampling_seed(game_index, seat) ^ (
        (request_id * SPLITMIX64_GAMMA) & MASK64
    )
    return splitmix64(mixed)


def shuffle_key(cycle: int, epoch: int, logical_index: int, seed: int = TRAINER_SEED) -> int:
    """Stable per-sample key for the M39A total-order permutation.

    Cycle and epoch are one-based.  Sorting by ``(shuffle_key, logical_index)``
    gives a collision-safe total order.
    """

    if not 1 <= cycle <= CYCLES:
        raise ValueError("cycle must be in 1..=8")
    if not 1 <= epoch <= 4:
        raise ValueError("epoch must be in 1..=4")
    if logical_index < 0:
        raise ValueError("logical_index must be non-negative")
    mixed = int(seed) & MASK64
    mixed ^= (cycle * SHUFFLE_CYCLE_MIX) & MASK64
    mixed ^= (epoch * SHUFFLE_EPOCH_MIX) & MASK64
    mixed ^= (logical_index * SHUFFLE_INDEX_MIX) & MASK64
    return splitmix64(mixed)


def shuffled_indices(count: int, cycle: int, epoch: int) -> list[int]:
    if count < 0:
        raise ValueError("count must be non-negative")
    return sorted(range(count), key=lambda index: (shuffle_key(cycle, epoch, index), index))


@dataclass(frozen=True)
class ScheduledGame:
    game_index: int
    cycle: int
    cycle_ordinal: int
    seed: int
    bucket: str
    opponent: str
    learner_seats: tuple[int, ...]


def scheduled_game(game_index: int) -> ScheduledGame:
    if not 0 <= game_index < CYCLES * GAMES_PER_CYCLE:
        raise ValueError("game_index outside frozen M39A round")
    cycle_zero = game_index // GAMES_PER_CYCLE
    ordinal = game_index % GAMES_PER_CYCLE
    if ordinal < 16:
        bucket, opponent = "random", "agent-random"
    elif ordinal < 64:
        bucket, opponent = "heuristic", "agent-heuristic"
    elif ordinal < 192:
        bucket, opponent = "m07", "M07"
    elif ordinal < 320:
        bucket = "league"
        league_ordinal = cycle_zero * 128 + (ordinal - 192)
        opponent = LEAGUE_ORDER[league_ordinal % len(LEAGUE_ORDER)]
    else:
        bucket, opponent = "self_play", "M39A"
    seed = TRAINING_GAME_SEED_BASE + game_index // 2
    learner_seats = (0, 1) if bucket == "self_play" else (game_index % 2,)
    return ScheduledGame(
        game_index=game_index,
        cycle=cycle_zero + 1,
        cycle_ordinal=ordinal,
        seed=seed,
        bucket=bucket,
        opponent=opponent,
        learner_seats=learner_seats,
    )


def cycle_schedule(cycle: int) -> list[ScheduledGame]:
    if not 1 <= cycle <= CYCLES:
        raise ValueError("cycle must be in 1..=8")
    start = (cycle - 1) * GAMES_PER_CYCLE
    return [scheduled_game(index) for index in range(start, start + GAMES_PER_CYCLE)]


def centered_returns(result: dict[str, Any], truncated: bool = False) -> tuple[float, float]:
    scores = result.get("scores")
    if not isinstance(scores, list) or len(scores) != 2:
        raise ValueError("result.scores must contain two values")
    if truncated:
        delta = float(scores[0]) - float(scores[1])
        return (
            -0.5 + 0.5 * math.tanh(delta / 4.0),
            -0.5 + 0.5 * math.tanh(-delta / 4.0),
        )
    ranks = result.get("ranks")
    if not isinstance(ranks, list) or len(ranks) != 2:
        raise ValueError("result.ranks must contain two values")
    if ranks[0] == ranks[1]:
        return (0.0, 0.0)
    return (1.0, -1.0) if ranks[0] < ranks[1] else (-1.0, 1.0)


def auxiliary_target(scores: Sequence[int | float], viewer: int) -> float:
    if len(scores) != 2 or viewer not in (0, 1):
        raise ValueError("auxiliary target requires two scores and viewer 0/1")
    opponent = 1 - viewer
    return max(-1.0, min(1.0, (float(scores[viewer]) - float(scores[opponent])) / 15.0))


def gae_for_trajectory(
    old_values: Sequence[float],
    terminal_return: float,
    gamma: float = 1.0,
    gae_lambda: float = 0.95,
) -> list[float]:
    """GAE over one seat's ordered decisions.

    Intermediate own-decision rewards are zero.  The last decision receives
    the final viewer-relative return and never bootstraps past the game end.
    """

    if not old_values:
        return []
    advantages = [0.0] * len(old_values)
    running = 0.0
    for index in range(len(old_values) - 1, -1, -1):
        current = float(old_values[index])
        if index == len(old_values) - 1:
            delta = float(terminal_return) - current
        else:
            delta = gamma * float(old_values[index + 1]) - current
        running = delta + gamma * gae_lambda * running
        advantages[index] = running
    return advantages


def standardize_advantages(values: Sequence[float], epsilon: float = 1e-8) -> list[float]:
    if not values:
        raise ValueError("cannot standardize an empty advantage set")
    mean = sum(float(value) for value in values) / len(values)
    variance = sum((float(value) - mean) ** 2 for value in values) / len(values)
    denominator = math.sqrt(variance) + epsilon
    return [(float(value) - mean) / denominator for value in values]


def action_index(legal_actions: Sequence[dict[str, Any]], action: dict[str, Any]) -> int:
    matches = [index for index, candidate in enumerate(legal_actions) if candidate == action]
    if len(matches) != 1:
        raise ValueError("chosen action must occur exactly once in ordered legal_actions")
    return matches[0]


def validate_sidecar(sidecar: dict[str, Any]) -> None:
    if sidecar.get("format") != SIDECAR_FORMAT or sidecar.get("version") != SIDECAR_VERSION:
        raise ValueError("unsupported M39A sidecar format/version")
    for key in ("plan_hash", "checkpoint_sha256", "game_id", "game_index", "seat"):
        if key not in sidecar:
            raise ValueError(f"sidecar missing {key}")
    seat = int(sidecar["seat"])
    if seat not in (0, 1):
        raise ValueError("sidecar seat must be 0 or 1")
    records = sidecar.get("records")
    if not isinstance(records, list):
        raise ValueError("sidecar records must be a list")
    last_ply = -1
    for record in records:
        ply = int(record.get("ply_index", -1))
        request_id = int(record.get("request_id", 0))
        if ply <= last_ply:
            raise ValueError("sidecar ply_index must increase")
        if request_id != ply + 1:
            raise ValueError("request_id must equal ply_index + 1")
        if int(record.get("seat", -1)) != seat:
            raise ValueError("record seat does not match sidecar")
        expected_seed = decision_seed(int(sidecar["game_index"]), seat, request_id)
        if int(record.get("decision_seed", -1)) != expected_seed:
            raise ValueError("record decision_seed mismatch")
        legal = record.get("legal_actions")
        action = record.get("action")
        if not isinstance(legal, list) or not legal:
            raise ValueError("record legal_actions must be non-empty")
        action_index(legal, action)
        for numeric in ("old_log_probability", "old_value"):
            if not math.isfinite(float(record.get(numeric, math.nan))):
                raise ValueError(f"record {numeric} must be finite")
        last_ply = ply


def group_records_by_trajectory(records: Iterable[dict[str, Any]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for record in records:
        key = (int(record["game_index"]), int(record["seat"]))
        grouped.setdefault(key, []).append(record)
    for trajectory in grouped.values():
        trajectory.sort(key=lambda record: int(record["ply_index"]))
    return grouped
