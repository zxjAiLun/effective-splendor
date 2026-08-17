# M27A Fixed-Model Search-Budget Scaling

Status: `AUTHORIZED FOR PREREGISTRATION / DESIGN`
Execution: `NOT AUTHORIZED`
Baseline: `77be94637b58610eacaaf51a9bb06da3f1e0aff7`
Parent: M24.5 `ACCEPTED` — D24.5 `SEARCH_BOTTLENECK`
Design config: `benchmarks/m27a-search-budget-scaling-v1.json`

## Problem and evidence

M24.5 accepted the search-bottleneck branch. The fixed M24-S2 checkpoint
produced the following M07 anchor deltas under the frozen D2 screen:

```text
sim16 = -625 bps
sim32 = +3125 bps
sim64 = +1250 bps
```

This proves that search budget can rescue the S2 checkpoint on the M07 anchor,
but it does not establish a monotonic curve or a stable operating point.

## Initial design

M27A will measure the fixed-model strength curve with the accepted S1 checkpoint
as a matched control. The proposed budgets are `16, 24, 32, 48, 64, 96, 128`.
The design uses the same S2 and S1 checkpoint identities, the same M07
reviewer, and paired seat rotations at each budget.

The design is authorized for preregistration only. It is not a permission to
run Arena evaluations.

## Scope and non-goals

In scope:

- Fixed S1/S2 checkpoints versus frozen M07.
- Search-budget curve shape and uncertainty.
- Matched S2-minus-S1 anchor deltas at each budget.

Out of scope:

- New training or self-play collection.
- Architecture, dataset, checkpoint, PUCT, depth, or M07 changes.
- Promotion, champion replacement, M25, M26, or M28.

## Contracts and invariants

- S2 checkpoint semantic hash remains
  `c43e3c239124671c77bb7436dcf79e4fe6c71b66c8008186ac68621a8ad7d5a8`.
- S1 checkpoint semantic hash remains
  `1ae31dac9eec37485efdbb906109227dbe77424e78b31a906d158ac1d414f0b8`.
- M07 remains `m07-champion`, sample-count 4, depth 1, max-nodes 2000.
- Proposed matrix: 2 pairs x 7 budgets x 32 seeds x 2 rotations = 896 matches.
- Every plan must validate as `EvaluationPlanV1`; every realized report must
  bind its plan hash, W/T/L, completion counts, and report SHA-256.
- Runtime must use an explicit PATH bootstrap resolving literal `splendor` to
  the reviewed build; `PYTHONPATH` remains unset unless separately reviewed.
- No execution occurs before independent review accepts the frozen design and
  realized-plan contract.

## Implementation plan

1. Review and freeze the JSON design contract.
2. Generate 14 pairwise plans from the frozen contract.
3. Independently review plan hashes, seeds, identities, timeouts, and matrix
   coverage.
4. Only after that review, execute the 896-match screen.
5. Recompute center scores and matched anchor deltas from raw reports.
6. Record the curve decision without treating higher simulations as inherently
   better.

## Iteration log

### 2026-08-17 — design authorized

- M24.5 independent review accepted `SEARCH_BOTTLENECK` with P0=0, P1=0, and
  one non-blocking P2 durability follow-up.
- M27A design was authorized; no Arena plan was generated and no evaluation
  was executed.
- The initial design uses a matched S1 control so the curve reports both
  absolute S2-vs-M07 strength and S2-minus-S1 movement.

## Final implementation

This round contains only the design document and preregistration draft:

- `benchmarks/m27a-search-budget-scaling-v1.json`
- `docs/m27a-search-budget-scaling.md`

No checkpoint, dataset, realized plan, eval report, replay, or Arena result was
created by M27A.

## Validation and evidence

- Parent M24.5 result: `benchmarks/m24-scale-failure-diagnosis-v1.result.json`.
- Parent review basis: `94fc9b8b0acdde71b92a61566a4e6e9aa51c0f7f`.
- Parent documentation binding: `77be94637b58610eacaaf51a9bb06da3f1e0aff7`.
- M27A config status is `DESIGNED`; `execution_authorization` is
  `NOT_AUTHORIZED`.
- Validation must include exact 14-plan / 896-match matrix coverage before any
  execution authorization is considered.

## Result and decision

M27A is `AUTHORIZED FOR PREREGISTRATION / DESIGN`, not authorized for
execution. M24.5 remains `ACCEPTED`; M07 remains champion; no promotion has
occurred.

## Known limitations

- The proposed 32-seed cells are a design choice pending independent review,
  not executed evidence.
- The 128-simulation cell may require the proposed fixed 30-second operational
  timeout; this is an explicit review item, not a runtime exception.
- No optimum or monotonicity claim is made before execution.

## Next authorized gate

Independent review of the M27A design/config and generated-plan contract.
Until that review passes, do not generate formal plans or run search-budget
Arena experiments. M25, M26, and M28 remain unauthorized.
