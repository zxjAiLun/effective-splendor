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
    game is truncated (no W/D/L label is ever fabricated).

    The label is the AUTHORITATIVE realized outcome, read from the
    referee-computed `centered_returns[seat]` — NOT derived from final VP
    comparison. Splendor can split equal-VP games by tiebreak rank, so
    VP comparison would mislabel tiebreak wins as draws and disagree
    with the value target (which is the same centered return).
    """
    result = record["result"]
    if result["truncated"]:
        return None
    seat = int(record["seat"])
    centered = result["centered_returns"][seat]
    if centered == 1.0:
        label = "win"
    elif centered == 0.0:
        label = "draw"
    elif centered == -1.0:
        label = "loss"
    else:
        raise LabelError(
            f"game {record['game_index']} seat {seat}: completed "
            f"centered_returns entry {centered!r} is not one of "
            "{-1.0, 0.0, +1.0} — fail closed"
        )
    # Consistency check against the authoritative terminal ranks when
    # present: the rank-derived outcome must agree with the centered
    # return (both come from the referee, so disagreement means a
    # corrupted record).
    terminal = result.get("source_terminal_result")
    if terminal is not None:
        ranks = terminal.get("ranks")
        if isinstance(ranks, list) and len(ranks) == 2:
            own_rank = int(ranks[seat])
            opp_rank = int(ranks[1 - seat])
            if own_rank < opp_rank:
                expected = "win"
            elif own_rank > opp_rank:
                expected = "loss"
            else:
                expected = "draw"
            if expected != label:
                raise LabelError(
                    f"game {record['game_index']} seat {seat}: centered "
                    f"return says {label!r} but terminal ranks say "
                    f"{expected!r} — corrupted record, fail closed"
                )
    return label


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


def _decision_indices(record: dict[str, Any], seat: int) -> list[int]:
    """Payload-relative indices of `seat`'s subsequent decision plies,
    including the tagged pending decision itself at relative index 0.

    `prestige_after_ply[i]` is the prestige after ply
    `record.ply_index + i`; ply p has actor p % 2 in 1v1 (the engine
    guarantees strict alternation from seat 0), so a ply belongs to
    `seat` iff `(ply_index + relative) % 2 == seat`.
    """
    labels = record["m40a_labels"]
    window = int(labels["window_plies"])
    ply_index = int(record["ply_index"])
    return [
        relative
        for relative in range(0, window - ply_index)
        if (ply_index + relative) % 2 == seat
    ]


def _first_finish_ordinal(
    decision_indices: list[int],
    prestige_after_ply: list[list[int]],
    prestige_slot: int,
) -> int | None:
    """The 1-based ordinal of the first decision whose POST-action
    prestige reaches 15, or None if no such decision exists in the
    window.

    Horizon membership is judged STRICTLY from this ordinal — never from
    the final score. An eventual winner whose finish falls beyond the
    horizon must NOT be labelled positive.
    """
    for ordinal, relative in enumerate(decision_indices, start=1):
        if relative < len(prestige_after_ply):
            if prestige_after_ply[relative][prestige_slot] >= 15:
                return ordinal
    return None


def timing_labels(record: dict[str, Any]) -> list[bool] | None:
    """Six booleans: [self@2, self@4, self@8, opp@2, opp@4, opp@8].

    The tagged pending decision IS own-turn #1 (the opponent's pending
    decision, one ply later, is their turn #1). A horizon h is true iff
    the player's first finish decision ordinal satisfies
    `first_finish_ordinal <= h`. There is NO final-score fallback: an
    eventual winner that finishes on decision #9 is self@2=false,
    self@4=false, self@8=false. None for truncated games.
    """
    if record["result"]["truncated"]:
        return None
    labels = record["m40a_labels"]
    prestige = labels["prestige_after_ply"]
    seat = int(record["seat"])

    own_indices = _decision_indices(record, seat)
    opp_indices = _decision_indices(record, 1 - seat)

    self_finish = _first_finish_ordinal(own_indices, prestige, 0)
    opp_finish = _first_finish_ordinal(opp_indices, prestige, 1)

    self_flags = [
        self_finish is not None and self_finish <= horizon
        for horizon in TIMING_HORIZONS
    ]
    opp_flags = [
        opp_finish is not None and opp_finish <= horizon
        for horizon in TIMING_HORIZONS
    ]
    return self_flags + opp_flags


def _labels_for_batch(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive the per-family label tensors for a batch of records."""
    outcomes: list[int | None] = []
    vp_self: list[int | None] = []
    vp_opp: list[int | None] = []
    vp_diff: list[float | None] = []
    timings: list[list[bool] | None] = []
    values: list[float] = []
    for record in records:
        outcome = outcome_label(record)
        outcomes.append({"win": 2, "draw": 1, "loss": 0}.get(outcome) if outcome else None)
        labels = final_vp_labels(record)
        if labels is None:
            vp_self.append(None)
            vp_opp.append(None)
        else:
            vp_self.append(labels[0])
            vp_opp.append(labels[1])
        vp_diff.append(vp_difference_label(record))
        timings.append(timing_labels(record))
        values.append(value_target(record))
    return {
        "outcome": outcomes,
        "vp_self": vp_self,
        "vp_opp": vp_opp,
        "vp_diff": vp_diff,
        "timing": timings,
        "value": values,
    }


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
