#!/usr/bin/env python3
"""S0 P0 gate 1: seed-segment registry and disjointness assert.

Fails closed (exit 1) if the frozen S0 segment 5_800_064..5_800_127
overlaps any previously consumed arena/game-seed namespace.

The registry below is the union of:
  - a scan of every local-artifacts plan/config/registry/manifest/
    provenance/summary/result JSON (game_seeds / frozen_seeds arrays),
  - the tracked artifacts/formal-2026-08-11 plans (M09/M10/M13),
  - the M46A corpus seed ranges (training/eval data namespaces),
  - the segments documented in milestone docs (M42S 5_300_000..63,
    M44C 5_700_000..63, M45A 5_800_000..63).

Scan date: 2026-09-08. The registry is committed so the audit can
reproduce the disjointness check without re-scanning.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The segment to check is assigned by the caller (each round's
# orchestrator sets its own frozen segment before calling check()).
# Registry updated 2026-09-09 to the real current state: the early static
# scan ended at the M45A/M46A era and did not list the S-era segments,
# forcing callers to monkeypatch — that gap is closed here.
CHECK_SEGMENT = range(5_800_064, 5_800_128)  # default: the S0 segment

# S-era arena segments (2026-09-08/09):
#   5_800_064..127  S0 baseline calibration — CONSUMED
#   5_800_128..191  S1 — RESERVED then RETIRED (Phase B never ran; retired
#                    namespace, must NOT be reused)
#   5_800_192..255  S2b confirmation — CONSUMED
#   5_800_256..319  S3 Stage-B — CONSUMED
#   5_800_320..383  S3 field calibration — CANDIDATE segment (asserted
#                    disjoint here; that round's result records consumption)

# Frozen scanned ranges (start, end_inclusive, label).
# Single-seed ranges are (s, s).
REGISTRY: list[tuple[int, int, str]] = [
    (181_000, 181_003, "m15-era-a"),
    (182_000, 182_003, "m15-era-b"),
    (190_000, 190_000, "m19-championship"),
    (220_100, 220_103, "m22-league"),
    (269_001, 269_003, "m16-era"),
    (300_001, 300_032, "m10-era"),
    (301_001, 301_032, "m11-era"),
    (900_000, 900_031, "m09-formal"),
    (930_000, 930_031, "m13-formal-a"),
    (940_000, 940_015, "m15-era-c"),
    (950_000, 950_063, "m24-era"),
    (960_000, 960_015, "m15-era-d"),
    (971_000, 971_003, "m17-era"),
    (5_300_000, 5_300_063, "m42s-arena"),
    (5_700_000, 5_700_063, "m44c-arena"),
    (5_800_000, 5_800_063, "m45a-arena"),
    (5_800_064, 5_800_127, "s0-baseline-calibration"),
    (5_800_128, 5_800_191, "s1-reserved-retired-never-reuse"),
    (5_800_192, 5_800_255, "s2b-confirmation"),
    (5_800_256, 5_800_319, "s3-stage-b"),
    (20_260_825, 20_260_952, "m25-bootstrap"),
    (6_600_000, 6_602_047, "m46a-corpus-train"),
    (6_602_048, 6_602_303, "m46a-corpus-val"),
    (6_602_304, 6_602_559, "m46a-corpus-test"),
]


def check() -> int:
    consumed: set[int] = set()
    duplicates: list[str] = []
    for lo, hi, label in REGISTRY:
        rng = range(lo, hi + 1)
        clash = consumed.intersection(rng)
        if clash:
            duplicates.append(f"{label} overlaps prior ranges at {sorted(clash)[:3]}")
        consumed.update(rng)

    s0 = set(CHECK_SEGMENT)
    overlap = sorted(s0.intersection(consumed))
    if overlap:
        print(f"FAIL: segment {CHECK_SEGMENT.start}..{CHECK_SEGMENT.stop - 1} overlaps consumed seeds: {overlap}")
        return 1
    if duplicates:
        print(f"FAIL: registry self-overlaps: {duplicates}")
        return 1
    print(
        f"PASS: segment {CHECK_SEGMENT.start}..{CHECK_SEGMENT.stop - 1} "
        f"({len(s0)} seeds) disjoint from "
        f"{len(consumed)} consumed seeds across {len(REGISTRY)} ranges."
    )
    return 0


if __name__ == "__main__":
    sys.exit(check())
