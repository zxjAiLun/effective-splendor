# S3 Field Calibration — candidate positioning in the current measured field

STATUS     = FROZEN / EXECUTING (contract frozen docs-only per the S3
            closure review of 7f911fb, which authorized the entire chain:
            run -> audit -> tracked result -> closure review. No policy
            code changes permitted: the candidate identity is the zero-flag
            agent-s3-rollout, frozen.)
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

## Execution plan

1. `scripts/s3_field_calibration.py`: registry check (320..383), 256
   matches, bootstrap, decision table, tracked result
   `benchmarks/s3-field-calibration-v1.result.json`.
2. Final audit (lineup / replay verification / recomputation / decision
   table / registry).
3. Docs closure + handoff; closure review.
