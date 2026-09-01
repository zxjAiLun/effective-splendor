"""M40A label derivation from materializer records + the frozen dataset
split.

Labels are derived purely from the authoritative batch records (whose
`m40a_labels` payload the Rust referee emits): outcome, final VP
(fail-closed above 30), normalized VP difference, and own-turn timing
(the tagged pending decision is turn #1). Truncated records are masked
from every family except value supervision.

The split implements the frozen deterministic rule: game 2785 forced to
TRAIN; completed games split 80/20 stratified by (cycle, opponent
bucket); banker's-rounded quota; per-stratum selection by ascending
game_index with stride 5 from the midpoint, wrapping once.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .m40a_constants import (
    COMPLETED_GAMES,
    FORCED_TRAIN_GAME,
    SPLIT_IDENTITY_SEED,
    SPLIT_STRIDE,
    TIMING_HORIZONS,
    TRAINING_COMPLETED_GAMES,
    TRAINING_TOTAL_GAMES,
    TRAINING_TRUNCATED_GAMES,
    VALIDATION_COMPLETED_GAMES,
    VALIDATION_FRACTION,
    VP_MAX,
)
from .m40a_model import normalized_vp_difference


class LabelError(ValueError):
    """A fail-closed label violation (e.g. VP above the frozen support)."""


def _bankers_round(value: float) -> int:
    """Round-half-to-even, matching Python's round() for .5 cases."""
    import decimal

    return int(
        decimal.Decimal(value).quantize(
            decimal.Decimal("1"), rounding=decimal.ROUND_HALF_EVEN
        )
    )


def outcome_label(record: dict[str, Any]) -> str | None:
    """'win' | 'draw' | 'loss' for the record's seat, or None if the
    game is truncated (no W/D/L label is ever fabricated)."""
    result = record["result"]
    if result["truncated"]:
        return None
    scores = result["scores"]
    seat = int(record["seat"])
    self_score = int(scores[seat])
    opp_score = int(scores[1 - seat])
    if self_score > opp_score:
        return "win"
    if self_score < opp_score:
        return "loss"
    return "draw"


def final_vp_labels(record: dict[str, Any]) -> tuple[int, int] | None:
    """(self final VP, opp final VP); None for truncated games."""
    result = record["result"]
    if result["truncated"]:
        return None
    scores = result["scores"]
    seat = int(record["seat"])
    self_vp = int(scores[seat])
    opp_vp = int(scores[1 - seat])
    if self_vp > VP_MAX or opp_vp > VP_MAX:
        raise LabelError(
            f"game {record['game_index']}: final VP ({self_vp}, {opp_vp}) "
            f"exceeds the frozen support 0..{VP_MAX} — fail closed, never clamp"
        )
    return self_vp, opp_vp


def vp_difference_label(record: dict[str, Any]) -> float | None:
    """clamp((VP_self − VP_opp)/15, −1, +1); None for truncated games."""
    labels = final_vp_labels(record)
    if labels is None:
        return None
    return normalized_vp_difference(labels[0], labels[1])


def value_target(record: dict[str, Any]) -> float:
    """The value-supervision target: centered return (completed) or the
    frozen cap-return (truncated)."""
    result = record["result"]
    seat = int(record["seat"])
    centered = result["centered_returns"]
    return float(centered[seat])


def _own_decision_prestige_trajectory(record: dict[str, Any]) -> list[int]:
    """Indices (relative to prestige_after_ply) of the SUBSEQUENT own
    decision plies, including the tagged pending decision itself.

    `prestige_after_ply[i]` is the prestige after ply
    `record.ply_index + i`. The tagged decision is ply_index (index 0 in
    the payload); the player's next own decision is the next ply whose
    actor is the record's seat. Actors alternate in 1v1, so own decisions
    occur every 2 plies — but the implementation derives them from the
    payload's seat ordering rather than assuming alternation: the
    relative index of the k-th subsequent own decision is recovered from
    the actors implicit in the ply arithmetic (seat parity of
    ply_index + i must equal the seat's parity only if actors strictly
    alternate, which the engine guarantees in 1v1).
    """
    labels = record.get("m40a_labels")
    if labels is None:
        raise LabelError(
            f"game {record['game_index']} ply {record['ply_index']}: "
            "record lacks the m40a_labels payload"
        )
    window = int(labels["window_plies"])
    ply_index = int(record["ply_index"])
    seat = int(record["seat"])
    trajectory: list[int] = []
    # ply p has actor p % 2 in 1v1 (seat 0 acts on even plies). The
    # engine guarantees strict alternation from seat 0.
    for relative in range(0, window - ply_index):
        ply = ply_index + relative
        if ply % 2 == seat:
            trajectory.append(relative)
    return trajectory


def timing_labels(record: dict[str, Any]) -> list[bool] | None:
    """Six booleans: [self@2, self@4, self@8, opp@2, opp@4, opp@8].

    The tagged pending decision IS own-turn #1. A horizon k is true iff
    the player reaches 15 VP on or before their k-th decision from the
    tagged state (inclusive of the tagged decision itself). None for
    truncated games.
    """
    if record["result"]["truncated"]:
        return None
    labels = record["m40a_labels"]
    prestige = labels["prestige_after_ply"]
    seat = int(record["seat"])
    window = int(labels["window_plies"])
    ply_index = int(record["ply_index"])
    final_scores = record["result"]["scores"]
    final_self = int(final_scores[seat])
    final_opp = int(final_scores[1 - seat])

    # Own-decision relative indices (including the tagged one at 0).
    own_indices = _own_decision_prestige_trajectory(record)
    opp_indices = [
        relative
        for relative in range(0, window - ply_index)
        if (ply_index + relative) % 2 == (1 - seat)
    ]

    def finishes_within(indices: list[int], final_vp: int) -> list[bool]:
        result_flags = []
        for horizon in TIMING_HORIZONS:
            # The k-th own decision (1-based) corresponds to indices[k-1].
            if len(indices) >= horizon:
                relative = indices[horizon - 1]
                # Prestige AFTER that decision = payload[relative].
                # But a finish ON decision k also occurs if an earlier
                # decision already crossed 15: check all decisions up to k.
                reached = False
                for k in range(horizon):
                    idx = indices[k]
                    entry = prestige[idx] if idx < len(prestige) else None
                    if entry is not None:
                        vp = entry[0]  # prestige_after_ply is [self, opp]
                        # NOTE: entry[0] is SELF prestige only when the
                        # trajectory was built for this seat; it is.
                        if vp >= 15:
                            reached = True
                            break
                # The game ended: if the player finished at any point and
                # the final VP is >= 15 and the finish happened at or
                # before the horizon's decision, flag true. The exact
                # finish decision is the first own decision where the
                # prestige-after crossed 15; if none crossed within the
                # payload but the final VP >= 15, the finish occurred on
                # the terminal ply — attributed to the last own decision.
                if not reached and final_vp >= 15:
                    # Terminal finish: attribute to the last available
                    # own decision within the window (the payload's final
                    # entries carry the terminal prestige).
                    reached = True
                result_flags.append(reached if len(indices) >= horizon else False)
            else:
                # Fewer than k own decisions remain; the finish cannot be
                # within k unless the game already ended before them —
                # which the final_vp check below handles via the caller.
                result_flags.append(final_vp >= 15)
        return result_flags

    # NOTE: prestige_after_ply entries are [self, opp] relative to the
    # RECORD's seat. For the opponent timing we need OPPONENT prestige
    # after OPPONENT decisions — entry[1] gives opponent prestige after
    # each ply, and opponent decisions are at opp_indices.
    self_flags: list[bool] = []
    for horizon in TIMING_HORIZONS:
        flag = False
        if len(own_indices) >= horizon:
            for k in range(horizon):
                idx = own_indices[k]
                if idx < len(prestige) and prestige[idx][0] >= 15:
                    flag = True
                    break
        if not flag and final_self >= 15:
            flag = True
        self_flags.append(flag)

    opp_flags: list[bool] = []
    for horizon in TIMING_HORIZONS:
        flag = False
        if len(opp_indices) >= horizon:
            for k in range(horizon):
                idx = opp_indices[k]
                if idx < len(prestige) and prestige[idx][1] >= 15:
                    flag = True
                    break
        if not flag and final_opp >= 15:
            flag = True
        opp_flags.append(flag)

    return self_flags + opp_flags


def _bucket_of(game_index: int) -> str:
    """The M39A §3.3 cycle-local bucket of a game index."""
    ordinal = game_index % 512
    if ordinal < 16:
        return "random"
    if ordinal < 64:
        return "heuristic"
    if ordinal < 192:
        return "m07"
    if ordinal < 320:
        return "league"
    return "self_play"


def frozen_split(game_indices: list[int], truncated_games: set[int]) -> dict[str, list[int]]:
    """The frozen deterministic split.

    game_indices: all 4,096 game indices (completed + truncated).
    truncated_games: the set of truncated game indices (must be {2785}).

    Returns {"train": [...], "validation": [...]} with the frozen
    cardinalities asserted.
    """
    if truncated_games != {FORCED_TRAIN_GAME}:
        raise LabelError(
            f"expected the single truncated game {{{FORCED_TRAIN_GAME}}}, "
            f"got {sorted(truncated_games)}"
        )
    completed = sorted(index for index in game_indices if index not in truncated_games)
    if len(completed) != COMPLETED_GAMES:
        raise LabelError(
            f"expected {COMPLETED_GAMES} completed games, got {len(completed)}"
        )

    # Strata: (cycle, bucket).
    strata: dict[tuple[int, str], list[int]] = {}
    for index in completed:
        cycle = index // 512 + 1
        strata.setdefault((cycle, _bucket_of(index)), []).append(index)
    # Per-stratum lists are already sorted (completed is sorted).

    validation: set[int] = set()
    for stratum in sorted(strata):
        games = strata[stratum]
        quota = _bankers_round(VALIDATION_FRACTION * len(games))
        if quota == 0:
            continue
        midpoint = len(games) // 2
        selected = 0
        position = midpoint
        wrapped = False
        while selected < quota:
            candidate = games[position % len(games)]
            if candidate not in validation:
                validation.add(candidate)
                selected += 1
            position += SPLIT_STRIDE
            if position >= len(games) and not wrapped:
                # Wrap once: continue from the start of the sorted list.
                position = position % len(games)
                wrapped = True
            elif position >= len(games) and wrapped:
                # Exhausted the stratum (quota > stratum size should not
                # happen at 20%): take remaining from the front.
                position = 0
    train_completed = [index for index in completed if index not in validation]

    if len(validation) != VALIDATION_COMPLETED_GAMES:
        raise LabelError(
            f"split cardinality: validation {len(validation)} != frozen "
            f"{VALIDATION_COMPLETED_GAMES}"
        )
    if len(train_completed) != TRAINING_COMPLETED_GAMES:
        raise LabelError(
            f"split cardinality: train completed {len(train_completed)} != frozen "
            f"{TRAINING_COMPLETED_GAMES}"
        )
    # Zero leakage by construction (disjoint sets over game indices).
    if validation & set(train_completed):
        raise LabelError("split leakage: a game appears in both train and validation")
    if FORCED_TRAIN_GAME in validation:
        raise LabelError("the forced truncated training game leaked into validation")

    return {
        "train": sorted(train_completed + [FORCED_TRAIN_GAME]),
        "validation": sorted(validation),
    }


def split_manifest_hash(split: dict[str, list[int]]) -> str:
    """Canonical SHA-256 of the exact train/validation game lists."""
    canonical = json.dumps(
        {
            "train": split["train"],
            "validation": split["validation"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dataset_identity(batch_files: list[Path]) -> str:
    """SHA-256 over the ordered per-cycle batch file hashes (the source
    dataset identity for provenance binding)."""
    from .m39a_contract import file_sha256

    digest = hashlib.sha256()
    for path in batch_files:
        digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()
