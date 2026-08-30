from __future__ import annotations

from splendor_gpu.m39a_contract import LEAGUE_ORDER
from splendor_gpu.m39a_gates import (
    LEDGER_FORMAT,
    LEDGER_VERSION,
    evaluate_g2,
    evaluate_g3,
)


def _row(arm: str, pairing: str, seed: int, rotation: int, outcome: str):
    return {
        "arm": arm,
        "pairing": pairing,
        "seed": seed,
        "rotation": rotation,
        "completed": True,
        "outcome": outcome,
        "candidate_fault": False,
        "deterministic_nontermination": False,
    }


def test_g2_uses_128_paired_seed_blocks_and_strict_lower_bound() -> None:
    rows = []
    for seed in range(5_000_000, 5_000_128):
        for rotation in (0, 1):
            rows.append(_row("candidate", "M07", seed, rotation, "win"))
            rows.append(_row("baseline", "M07", seed, rotation, "loss"))
    report = evaluate_g2(
        {"format": LEDGER_FORMAT, "version": LEDGER_VERSION, "gate": "g2", "rows": rows}
    )
    assert report["pass"]
    assert report["completed_seed_blocks"] == 128
    assert report["mean_delta_bps"] == 10_000.0
    assert report["lower_95_bps"] == 10_000.0

    rows.pop()
    failed = evaluate_g2(
        {"format": LEDGER_FORMAT, "version": LEDGER_VERSION, "gate": "g2", "rows": rows}
    )
    assert not failed["pass"]
    assert failed["completed_seed_blocks"] == 127


def test_g3_retains_all_nine_pairings_and_tie_passes_point_gate() -> None:
    rows = []
    for pairing in LEAGUE_ORDER:
        for seed in range(5_100_000, 5_100_032):
            for rotation in (0, 1):
                rows.append(_row("candidate", pairing, seed, rotation, "draw"))
                rows.append(_row("baseline", pairing, seed, rotation, "draw"))
    report = evaluate_g3(
        {"format": LEDGER_FORMAT, "version": LEDGER_VERSION, "gate": "g3", "rows": rows}
    )
    assert report["pass"]
    assert report["completed_pairings"] == {"candidate": 9, "baseline": 9}
    assert report["candidate_aggregate_score_bps"] == 5_000.0
    assert report["baseline_aggregate_score_bps"] == 5_000.0
    assert report["diagnostic_lower_95_bps"] == 0.0
