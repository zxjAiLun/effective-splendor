"""Machine-verifiable M39A G2/G3 paired Arena gates."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

from .m39a_contract import LEAGUE_ORDER, file_sha256


LEDGER_FORMAT = "effective-splendor-m39a-evaluation-ledger"
LEDGER_VERSION = 1
REPORT_FORMAT = "effective-splendor-m39a-gate-report"
REPORT_VERSION = 1
G2_CRITICAL = 1.656940343542
G3_CRITICAL = 1.695518782546
SCORES = {"win": 1.0, "draw": 0.5, "loss": 0.0}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _mean_sample_sd(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        raise ValueError("paired Student-t requires at least two blocks")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _validate_envelope(ledger: dict[str, Any], gate: str) -> list[dict[str, Any]]:
    if ledger.get("format") != LEDGER_FORMAT or ledger.get("version") != LEDGER_VERSION:
        raise ValueError("unsupported M39A evaluation ledger format/version")
    if ledger.get("gate") != gate:
        raise ValueError("ledger gate mismatch")
    rows = ledger.get("rows")
    if not isinstance(rows, list):
        raise ValueError("ledger rows must be a list")
    return rows


def _index_rows(
    rows: list[dict[str, Any]], expected: set[tuple[str, str, int, int]]
) -> tuple[dict[tuple[str, str, int, int], dict[str, Any]], dict[str, int]]:
    indexed: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    counts = {"aborted": 0, "candidate_faults": 0, "deterministic_nonterminations": 0}
    for row in rows:
        key = (
            str(row.get("arm")),
            str(row.get("pairing")),
            int(row.get("seed", -1)),
            int(row.get("rotation", -1)),
        )
        if key in indexed:
            raise ValueError(f"duplicate evaluation row {key}")
        if key not in expected:
            raise ValueError(f"unexpected evaluation row {key}")
        completed = bool(row.get("completed"))
        if completed:
            if row.get("outcome") not in SCORES:
                raise ValueError(f"completed row {key} has invalid outcome")
        else:
            counts["aborted"] += 1
        counts["candidate_faults"] += int(bool(row.get("candidate_fault")))
        counts["deterministic_nonterminations"] += int(
            bool(row.get("deterministic_nontermination"))
        )
        indexed[key] = row
    return indexed, counts


def _rotation_score(
    indexed: dict[tuple[str, str, int, int], dict[str, Any]],
    arm: str,
    pairing: str,
    seed: int,
) -> float | None:
    rows = [indexed.get((arm, pairing, seed, rotation)) for rotation in (0, 1)]
    if any(row is None or not bool(row.get("completed")) for row in rows):
        return None
    return 10_000.0 * sum(SCORES[str(row["outcome"])] for row in rows if row) / 2.0


def evaluate_g2(ledger: dict[str, Any]) -> dict[str, Any]:
    rows = _validate_envelope(ledger, "g2")
    seeds = range(5_000_000, 5_000_128)
    expected = {
        (arm, "M07", seed, rotation)
        for arm in ("candidate", "baseline")
        for seed in seeds
        for rotation in (0, 1)
    }
    indexed, counts = _index_rows(rows, expected)
    deltas = []
    complete_blocks = 0
    for seed in seeds:
        candidate = _rotation_score(indexed, "candidate", "M07", seed)
        baseline = _rotation_score(indexed, "baseline", "M07", seed)
        if candidate is not None and baseline is not None:
            complete_blocks += 1
            deltas.append(candidate - baseline)
    mean = sample_sd = lower = None
    if complete_blocks == 128:
        mean, sample_sd = _mean_sample_sd(deltas)
        lower = mean - G2_CRITICAL * sample_sd / math.sqrt(128)
    passed = (
        len(indexed) == 512
        and complete_blocks == 128
        and counts == {"aborted": 0, "candidate_faults": 0, "deterministic_nonterminations": 0}
        and lower is not None
        and lower > 0.0
    )
    return {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "gate": "g2",
        "completed_matches": sum(bool(row.get("completed")) for row in indexed.values()),
        "completed_seed_blocks": complete_blocks,
        **counts,
        "mean_delta_bps": mean,
        "sample_sd_bps": sample_sd,
        "lower_95_bps": lower,
        "critical_value": G2_CRITICAL,
        "pass": passed,
        "verdict": "pass" if passed else "fail",
    }


def evaluate_g3(ledger: dict[str, Any]) -> dict[str, Any]:
    rows = _validate_envelope(ledger, "g3")
    seeds = range(5_100_000, 5_100_032)
    expected = {
        (arm, pairing, seed, rotation)
        for arm in ("candidate", "baseline")
        for pairing in LEAGUE_ORDER
        for seed in seeds
        for rotation in (0, 1)
    }
    indexed, counts = _index_rows(rows, expected)
    pairing_deltas: dict[str, float] = {}
    complete_pairings = {"candidate": 0, "baseline": 0}
    arm_scores: dict[str, list[float]] = {"candidate": [], "baseline": []}
    for pairing in LEAGUE_ORDER:
        complete = True
        scores = {"candidate": [], "baseline": []}
        for arm in scores:
            for seed in seeds:
                score = _rotation_score(indexed, arm, pairing, seed)
                if score is None:
                    complete = False
                else:
                    scores[arm].append(score)
            if len(scores[arm]) == 32:
                complete_pairings[arm] += 1
                arm_scores[arm].extend(scores[arm])
        if complete:
            pairing_deltas[pairing] = sum(scores["candidate"]) / 32 - sum(
                scores["baseline"]
            ) / 32
    seed_deltas = []
    if len(pairing_deltas) == len(LEAGUE_ORDER):
        for seed in seeds:
            seed_deltas.append(
                sum(
                    _rotation_score(indexed, "candidate", pairing, seed)
                    - _rotation_score(indexed, "baseline", pairing, seed)
                    for pairing in LEAGUE_ORDER
                )
                / len(LEAGUE_ORDER)
            )
    candidate_score = (
        sum(arm_scores["candidate"]) / len(arm_scores["candidate"])
        if arm_scores["candidate"]
        else None
    )
    baseline_score = (
        sum(arm_scores["baseline"]) / len(arm_scores["baseline"])
        if arm_scores["baseline"]
        else None
    )
    mean = sample_sd = lower = None
    if len(seed_deltas) == 32:
        mean, sample_sd = _mean_sample_sd(seed_deltas)
        lower = mean - G3_CRITICAL * sample_sd / math.sqrt(32)
    passed = (
        len(indexed) == 1_152
        and complete_pairings == {"candidate": 9, "baseline": 9}
        and counts == {"aborted": 0, "candidate_faults": 0, "deterministic_nonterminations": 0}
        and candidate_score is not None
        and baseline_score is not None
        and candidate_score >= baseline_score
    )
    return {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "gate": "g3",
        "completed_matches": sum(bool(row.get("completed")) for row in indexed.values()),
        "completed_pairings": complete_pairings,
        **counts,
        "candidate_aggregate_score_bps": candidate_score,
        "baseline_aggregate_score_bps": baseline_score,
        "pairing_delta_bps": pairing_deltas,
        "diagnostic_mean_delta_bps": mean,
        "diagnostic_sample_sd_bps": sample_sd,
        "diagnostic_lower_95_bps": lower,
        "diagnostic_critical_value": G3_CRITICAL,
        "pass": passed,
        "verdict": "pass" if passed else "fail",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a frozen M39A gate ledger")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    gate = ledger.get("gate")
    if gate == "g2":
        report = evaluate_g2(ledger)
    elif gate == "g3":
        report = evaluate_g3(ledger)
    else:
        raise ValueError("ledger gate must be g2 or g3")
    report["ledger_file_sha256"] = file_sha256(args.ledger)
    _atomic_json(args.out, report)
    print(json.dumps(report, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
