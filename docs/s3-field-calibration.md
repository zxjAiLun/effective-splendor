# S3 Field Calibration — candidate positioning in the current measured field

STATUS     = APPROVED / COMPLETED_CALIBRATION / CLOSED (final review
            2026-09-09 on 2f54b0f: FIELD_TOP_CONFIRMED accepted — the
            candidate has DIRECT resolved wins over heuristic (S3 Stage
            B), n1, and M07 (this round, both at the preregistered 97.5%
            joint-decision CI); no transitivity used. The reference
            switch is OFFICIAL: new primary development reference =
            s3-rollout-candidate; historical primary reference =
            heuristic-v1; historical champion = M07 (narrative label
            only — no longer the current strongest reference). Product
            default UNCHANGED; promotion NONE. P0:0 / P1:0 / P2:4
            non-blocking closure items applied docs-only + audit
            hardening, audit re-run PASS.)
RESULT     = FIELD_TOP_CONFIRMED: candidate > n1 104-0-24 (8125.0,
            97.5% [7343.75, 8828.125]); candidate > M07 100-0-28
            (7812.5, 97.5% [6953.125, 8593.75]); with candidate >
            heuristic 80-0-48 (95% [5468.75, 6953.125], S3 Stage B) —
            the candidate is the unique resolved top of the measured
            field.
BASELINE   = 3ffdcd8 (S3 closure, 2026-09-09)
OWNER-DATE = local implementation + cloud review, 2026-09-09

## Question

S3 Stage B resolved candidate > heuristic. The current field knowledge:

    candidate > heuristic   (resolved, S3 Stage B)
    heuristic > n1          (resolved, S0)
    heuristic > M07         (resolved, S0)
    n1 ? M07                (unresolved, S0/M42S)

Transitivity is NOT assumed (the candidate's rollout opponent model IS
heuristic — opponent-specific non-transitivity is a live possibility).
The field calibration asks:

> **Is the S3 candidate the unique top of the entire current measured
> field?**

## Contract (frozen)

- Pairings (exactly two, both NEW — the heuristic rematch is NOT rerun;
  S3 Stage B is an independent preregistered valid confirmation):
  - P1: `candidate vs n1`
  - P2: `candidate vs M07`
- Candidate identity: `agent-s3-rollout`, zero flags. NO S3 policy code
  changes before or during this round (D/P, sampling, proposal set,
  rollout scoring, tie semantics, fast paths all frozen; only docs /
  orchestrator / audit / registry tooling may change).
- Seeds: `5_800_320 .. 5_800_383` (64 blocks x 2 rotations x 2 pairings =
  256 matches; registry-asserted disjoint — recorded).
- Statistics: paired-block bootstrap, 10,000 resamples, seed
  `43_300_301`; 95% descriptive CI + **97.5% two-sided decision CI**
  (Bonferroni for the two-comparison family, alpha 0.05/2). Per pairing:
  lower > 5000 -> STRONGER_A; upper < 5000 -> STRONGER_B; else
  UNRESOLVED. No extra seeds.

## Reference decision table (frozen BEFORE results)

| Outcome | State | Reference decision |
|---|---|---|
| Both resolved wins (vs n1 AND vs M07) | **FIELD_TOP_CONFIRMED** | The S3 candidate becomes the new PRIMARY DEVELOPMENT REFERENCE (development reference only — NOT the product default, NOT an automatic promotion) |
| Any UNRESOLVED, no resolved loss | **TOP_FIELD_UNRESOLVED** | heuristic remains the incumbent primary reference; the candidate is recorded as a CONFIRMED HEURISTIC CHALLENGER. No transitivity derivations. |
| Any resolved loss (vs n1 or M07) | **NONTRANSITIVE_SPLIT_FIELD** | No reference change. A genuine cycle (e.g. candidate > heuristic > n1 > candidate) is an important scientific result — the rollout gain may be opponent/model-specific. No seed additions to "grind away" a cycle. |

## Product default (explicitly out of scope)

Even on FIELD_TOP_CONFIRMED, the product default is a SEPARATE small
product decision (live latency profile, CPU, packaging, the n1+n2000
proposal cost, user preference for strong-vs-fast). Nothing changes
automatically.

## Execution record (2026-09-09, single valid run)

Arena (seeds 5_800_320..383 — registry-asserted disjoint via the REAL
updated registry, no monkeypatching; 2 pairings x 64 blocks x 2 rotations
= 256 matches; ~140 s wall):

| Pairing | W-T-L | Center | 97.5% decision CI | Verdict |
|---|---|---:|---|---|
| candidate vs n1 | **104-0-24** | 8125.0 | [7343.8, 8828.1] | **STRONGER_A** |
| candidate vs M07 | **100-0-28** | 7812.5 | [6953.1, 8593.8] | **STRONGER_A** |

(95% descriptive CIs, corrected to the tracked result values — the
earlier doc numbers were a transcription error: [7421.875, 8750.0] and
[7109.375, 8515.625].)

Decision table application: both resolved wins -> **FIELD_TOP_CONFIRMED**
-> per the frozen table, the S3 candidate becomes the new PRIMARY
DEVELOPMENT REFERENCE.

The complete measured field after this round:

    candidate > heuristic   (S3 Stage B: 80-0-48, 95% [5468.75, 6953.125])
    candidate > n1          (this round: 104-0-24, 97.5% [7343.8, 8828.1])
    candidate > M07         (this round: 100-0-28, 97.5% [6953.1, 8593.8])
    heuristic > n1          (S0)
    heuristic > M07         (S0)
    n1 ? M07                (unresolved, S0/M42S)

Final audit (fail-closed): real-registry disjointness; exhaustive
lineup (zero-flag candidate; exact frozen n1/M07 configs); 256/256
replays verified; full recomputation of W/T/L, block scores, centers,
both CI levels, verdicts, and the decision table; binary identity. ALL
CHECKS PASS.

Canonical result sentence (permanent):

> In fresh paired-seed Arenas, the S3 rollout candidate is resolved
> stronger than every other agent in the current measured field —
> heuristic-v1 (80-0-48), n1 (104-0-24), and M07 (100-0-28) — making it
> the new primary development reference. This is a development-reference
> change only: the product default and all promotion state are unchanged
> pending a separate product decision.

## Execution plan

1. `scripts/s3_field_calibration.py`: registry check (320..383), 256
   matches, bootstrap, decision table, tracked result
   `benchmarks/s3-field-calibration-v1.result.json`.
2. Final audit (lineup / replay verification / recomputation / decision
   table / registry).
3. Docs closure + handoff; closure review.
