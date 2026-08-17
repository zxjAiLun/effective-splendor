# M27A Fixed-Model Search-Budget Scaling

Status: `AUTHORIZED FOR PREREGISTRATION / DESIGN`; Repair 2 `IMPLEMENTED`, independent review pending
Execution: `NOT AUTHORIZED`
Baseline: `d027a5aa9a80325f3fbfb823a775c303c6d14468`
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
- The statistical unit is one paired seed block: one seed containing both seat
  rotations. Score bounds use the accepted deterministic one-sided Hoeffding
  contract at `confidence_bps = 9500`, with 32 completed paired blocks per
  plan. Anchor uncertainty uses the same blocks after matching S1 and S2 at
  the same budget, seed, and rotation; its block-delta range is `[-10000,
  10000]` bps and its margin numerator is `600000000`.
- The `n=32` power contract makes the Repair 1 anchor margin `4331` bps; its
  former lower-bound gate therefore implied an effective center threshold of
  `4131` bps. Repair 2 keeps the Hoeffding bounds as reported diagnostic
  uncertainty evidence, but removes them from operating-region eligibility,
  transition, and region-span decisions.
- The stable operating-region endpoint remains the matched S2-minus-S1 anchor.
  A budget is eligible only when both pair plans are complete with zero aborts
  and candidate faults and the anchor center is at least `+1000` bps, a
  predeclared practical 10-percentage-point S2-specific gain. Stable
  transitions require strict absolute center movement `< 2000` bps, and a
  region's total center span must also remain `< 2000` bps. A stable region
  requires three consecutive eligible budgets; choose the lowest budget in
  the first such region, otherwise record `M27A_INCONCLUSIVE`.
- The absolute S2-vs-M07 curve remains mandatory to report but is descriptive
  secondary evidence. It never overrides the matched-anchor eligibility or
  stability rule when the two signals disagree.
- No execution occurs before independent review accepts the frozen design and
  realized-plan contract.

## Implementation plan

1. Freeze Repair 2's sample-size/power, uncertainty-role, practical-center,
   plateau, and parent-provenance contracts; strengthen the design test.
2. Independently review Repair 2 and the resulting design/config bindings.
3. Only after that review, generate 14 pairwise plans from the frozen contract.
4. Independently review plan hashes, seeds, identities, timeouts, and matrix
   coverage.
5. Only after both reviews, execute the 896-match screen.
6. Recompute center scores, paired uncertainty, and matched anchor deltas from
   raw reports, then apply the frozen decision function without treating
   higher simulations as inherently better.

## Iteration log

### 2026-08-17 — design authorized

- M24.5 independent review accepted `SEARCH_BOTTLENECK` with P0=0, P1=0, and
  one non-blocking P2 durability follow-up.
- M27A design was authorized; no Arena plan was generated and no evaluation
  was executed.
- The initial design uses a matched S1 control so the curve reports both
  absolute S2-vs-M07 strength and S2-minus-S1 movement.

### 2026-08-17 — Prereg Repair 1 authorized and implemented

- Review findings addressed: P1-1 stable operating region was previously
  underspecified; P1-2 paired uncertainty and its statistical unit were
  incomplete; P2 cross-bind coverage was only a shape test.
- Frozen `effective-splendor-m27a-paired-search-curve-v1` statistics:
  `confidence_bps = 9500`, one paired seed block per seed with two seat
  rotations, score margin numerator `150000000`, and matched-anchor margin
  numerator `600000000` for the `[-10000, 10000]` bps block-delta range.
- Frozen `effective-splendor-m27a-stable-operating-region-v1` decision:
  anchor lower bound `>= -200` bps for eligibility, three consecutive eligible
  budgets, overlapping anchor intervals, at most `200` bps adjacent center
  regression, and lowest budget in the first stable region. If no qualifying
  region exists, the decision is `M27A_INCONCLUSIVE`; the absolute S2 curve is
  descriptive only.
- `crates/splendor-cli/tests/m27a_design.rs` now exact-binds the parent
  manifest/review commits, checkpoint and search identities, full seed list,
  runtime timeouts, statistics contract, and decision contract.
- This is a preregistration repair only. No realized plan, checkpoint, dataset,
  eval report, replay, or Arena result was generated.

### 2026-08-17 — Repair 1 independent review HOLD

- Independent review basis: `16cf9ec193f16175fd6c7e0425ab5212fbb61b51`;
  documentation binding: `d027a5aa9a80325f3fbfb823a775c303c6d14468`.
- Findings were P0=0, P1=2, P2=1. The Hoeffding formulas, paired blocks, and
  exact cross-bind coverage were accepted as mathematically correct, but plan
  materialization remained unauthorized because the 32-block sample size did
  not support the former lower-bound gate and the one-sided non-regression rule
  did not define a true plateau.

### 2026-08-17 — Prereg Repair 2 implemented

- `revision` is now `design-1-repair-2`, with explicit prior-review HOLD
  provenance and no authorization for plan materialization or Arena execution.
- Added an explicit power contract: `n=32`, anchor margin `4331` bps, prior
  lower-bound gate `-200` bps, and prior effective center threshold `4131` bps.
- Chosen diagnostic route: Hoeffding lower/upper bounds remain mandatory
  uncertainty evidence but do not control eligibility, adjacent transitions,
  region span, or promotion.
- Frozen practical selection predicates: anchor center `>= +1000` bps;
  strict adjacent absolute center movement `< 2000` bps; total anchor-center
  span `< 2000` bps; at least three consecutive budgets; first stable region's
  lowest budget; otherwise `M27A_INCONCLUSIVE`.
- Parent M24.5 manifest provenance is now cross-recomputed by the regression
  test from `benchmarks/m24-scale-failure-diagnosis-v1.result.json`, rather
  than checked only against a hard-coded digest.
- No realized plan, checkpoint, dataset, eval report, replay, or Arena result
  was generated by this repair.

## Final implementation

This round contains only the design document, preregistration draft, and its
machine-checking regression test:

- `benchmarks/m27a-search-budget-scaling-v1.json`
- `docs/m27a-search-budget-scaling.md`
- `crates/splendor-cli/tests/m27a_design.rs`

No checkpoint, dataset, realized plan, eval report, replay, or Arena result was
created by M27A.

## Validation and evidence

- Parent M24.5 result: `benchmarks/m24-scale-failure-diagnosis-v1.result.json`.
- Parent review basis: `94fc9b8b0acdde71b92a61566a4e6e9aa51c0f7f`.
- Parent documentation binding: `77be94637b58610eacaaf51a9bb06da3f1e0aff7`.
- Repair 1 implementation commit: `16cf9ec193f16175fd6c7e0425ab5212fbb61b51`;
  Repair 1 documentation binding: `d027a5aa9a80325f3fbfb823a775c303c6d14468`.
- M27A config revision is `design-1-repair-2`; status remains `DESIGNED`,
  `review.repair_status` is `IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`, and
  `execution_authorization` remains `NOT_AUTHORIZED`.
- Local validation commands and results:

  ```text
  python3 -m json.tool benchmarks/m27a-search-budget-scaling-v1.json >/dev/null — exit 0
  cargo fmt --all -- --check — exit 0
  cargo test --locked -p splendor-cli --test m27a_design -- --test-threads=1 — PASS, exit 0 (1 test)
  cargo test --locked --workspace --all-targets -- --test-threads=1 — exit 101; only the known Linux process test `shutdown_reaps_child` failed
  cargo test --locked --workspace --all-targets -- --test-threads=1 --skip shutdown_reaps_child — exit 0; all non-skipped workspace tests passed
  git diff --check — exit 0
  ```

- Validation must include exact 14-plan / 896-match matrix coverage before any
  execution authorization is considered.
- The unskipped workspace failure is an existing Linux child-process status
  issue outside this design-only change and is recorded rather than relabeled
  as a clean full-workspace pass.

## Result and decision

M27A Repair 2 is `IMPLEMENTED` and locally verified, but the design remains
pending independent review and is not authorized for plan materialization or
execution. M24.5 remains `ACCEPTED`; M07 remains champion; no promotion has
occurred.

## Known limitations

- The 32-seed cells and all Repair 2 operating-region thresholds are
  preregistered choices pending independent review, not executed evidence.
- The 128-simulation cell uses the same fixed 30-second operational timeout as
  every other budget; there is no budget-specific timeout exception.
- The anchor Hoeffding interval is a per-budget diagnostic bound and is not a
  promotion or family-wise claim across the seven budgets; Repair 2 explicitly
  keeps it out of the practical operating-region decision function.
- No optimum or monotonicity claim is made; the selected value, if any, is the
  first low-cost stable operating point under the frozen rule.

## Next authorized gate

Independent review of the M27A Repair 2 design/config contract. Until that
review passes, do not generate formal plans or run search-budget Arena
experiments. After it passes, plan materialization requires a separate review;
M25, M26, and M28 remain unauthorized.
