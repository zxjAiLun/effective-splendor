# M27A Fixed-Model Search-Budget Scaling

Status: `ACCEPTED / FROZEN`; 14-plan materialization `ACCEPTED`; Execution-Gate Repair 1 `HOLD`
Execution: `NOT AUTHORIZED`
Baseline: `d027a5aa9a80325f3fbfb823a775c303c6d14468`
Implementation: `a13bcdd` (`fix(training): repair M27A diagnostic operating gate`)
Materialization: `1db2241229a4d3bfe89cdf00f011789cdbbaee11` (`feat(training): materialize M27A search-budget plans`)
Review: `a13bcdde67cbb9390cd7cb905ae7f3a9fce469bd` → `ACCEPTED`; documentation binding `4d8ef5b82a11ec0a6a9df3aae42c7330f8e0cbb1`
Materialization review: `1db2241229a4d3bfe89cdf00f011789cdbbaee11` → `ACCEPTED`; P0/P1/P2 = `0/0/0`
Execution-gate review: P1 = `1` (`HOLD`); no Arena authorization
Execution-Gate Repair 1: `6d79e8adfd6fd3143d62e26d5634bdb82dbd4731` (`fix(training): repair M27A execution decision gate`)
Parent: M24.5 `ACCEPTED` — D24.5 `SEARCH_BOTTLENECK`
Design config: `benchmarks/m27a-search-budget-scaling-v1.json`
Materialization bundle: `benchmarks/m27a-search-budget-scaling-v1.bundle.json`

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
- The preregistration and 14-plan materialization are accepted/frozen. The
  executable operating-region gate is on `HOLD` until overlapping stable
  windows are handled by the start-window enumeration semantics and reviewed;
  execution remains unauthorized.

## Implementation plan

1. Freeze Repair 2's sample-size/power, uncertainty-role, practical-center,
   plateau, and parent-provenance contracts; strengthen the design test.
2. Independently review Repair 2 and the resulting design/config bindings.
3. Generate 14 pairwise realized plans and a compact hash-bound bundle.
4. Independently review plan hashes, seeds, identities, timeouts, and matrix
   coverage; execute no Arena matches during this stage.
5. Repair and independently review executable stable-region decision semantics;
   then freeze runtime/build identity and perform the reviewed execution smoke.
6. Only after those gates and a separate execution authorization, execute the
   896-match screen.
7. Recompute center scores, paired uncertainty, and matched anchor deltas from
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

### 2026-08-17 — Repair 2 accepted and plans materialized

- Independent review accepted basis `a13bcdde67cbb9390cd7cb905ae7f3a9fce469bd`
  with documentation binding `4d8ef5b82a11ec0a6a9df3aae42c7330f8e0cbb1`;
  findings are P0=0, P1=0, P2=1 non-blocking.
- The preregistration is `ACCEPTED / FROZEN`; plan materialization is
  `AUTHORIZED`, while plan execution and 896-match Arena execution remain
  `NOT AUTHORIZED`.
- Materialized exactly 14 plans: `s2_vs_m07` and `s1_vs_m07` across
  simulations `16,24,32,48,64,96,128`; each has 32 seeds, two seat rotations,
  and 64 scheduled matches. The bundle binds the preregistration SHA, review
  commits, raw plan-file SHA-256 values, canonical plan hashes, seed digest,
  and the 14-cell matrix.
- Added executable synthetic decision tests for strict adjacent movement,
  strict region span, first-region selection, minimum run length, and the
  continuing-rise rejection case.
- Tracked materialization commit:
  `1db2241229a4d3bfe89cdf00f011789cdbbaee11`.
- No eval-report, replay, result manifest, or Arena execution artifact was
  generated.

### 2026-08-18 — Execution-Gate Repair 1 required

- Materialization review accepted the 14 plans and bundle with basis
  `1db2241229a4d3bfe89cdf00f011789cdbbaee11`, documentation binding
  `8a703c9b3793757582b491afb125c0462bf85466`, and P0/P1/P2 = `0/0/0`.
- The review found P1=1 in the synthetic executable decision helper: greedy
  maximal-run partitioning skipped a valid stable window beginning at a later
  budget when the earliest prefix failed the region-span predicate.
- Repaired semantics now enumerate every candidate start from low to high and
  every contiguous end point; the first start with any valid window of at least
  three eligible budgets is selected. Added regressions for
  `[1000,2900,4000,4100] => Some(24)`, the two-point negative case, and the
  five-point extension case.
- The frozen thresholds, seeds, checkpoint identities, 14 plans, and plan
  hashes remain unchanged. The bundle's preregistration SHA metadata was
  updated only to bind the revised config wording; no plan hash changed.
- Implementation commit:
  `6d79e8adfd6fd3143d62e26d5634bdb82dbd4731`.
- Arena execution remains `NOT AUTHORIZED` pending this repair's review and
  the separate runtime/build freeze.

## Final implementation

This round contains the accepted preregistration, its 14 realized plans, the
hash-bound materialization bundle, the machine-checking regression test, and
the living milestone record:

- `benchmarks/m27a-search-budget-scaling-v1.json`
- `benchmarks/m27a-{s1_vs_m07,s2_vs_m07}-v1-sim{16,24,32,48,64,96,128}.plan.json`
- `benchmarks/m27a-search-budget-scaling-v1.bundle.json`
- `docs/m27a-search-budget-scaling.md`
- `crates/splendor-cli/tests/m27a_design.rs`

No checkpoint, dataset, eval report, replay, result manifest, or Arena result
was created by M27A.

## Validation and evidence

- Parent M24.5 result: `benchmarks/m24-scale-failure-diagnosis-v1.result.json`.
- Parent review basis: `94fc9b8b0acdde71b92a61566a4e6e9aa51c0f7f`.
- Parent documentation binding: `77be94637b58610eacaaf51a9bb06da3f1e0aff7`.
- Repair 1 implementation commit: `16cf9ec193f16175fd6c7e0425ab5212fbb61b51`;
  Repair 1 documentation binding: `d027a5aa9a80325f3fbfb823a775c303c6d14468`.
- Repair 2 implementation commit: `a13bcdd`; documentation binding:
  `4d8ef5b82a11ec0a6a9df3aae42c7330f8e0cbb1`.
- Independent Repair 2 review: basis
  `a13bcdde67cbb9390cd7cb905ae7f3a9fce469bd`, documentation binding
  `4d8ef5b82a11ec0a6a9df3aae42c7330f8e0cbb1`, P0=0/P1=0/P2=1;
  preregistration `ACCEPTED / FROZEN`.
- M27A config revision is `design-1-repair-2`; `review.acceptance` is
  `ACCEPTED`, plan materialization is authorized, and
  `execution_authorization` remains `NOT_AUTHORIZED`.
- Materialization bundle SHA-256:
  `19edd68cb089234e9571a3adae9d5fddc3fa88a40c35fb7b53d39d90bf2680e7`.
- Current prereg config SHA-256:
  `a50a62aed489cdc1c0022d924ba26463ba79fa29b7e66000d8fa9d51b1c2671e`.
- Materialization commit:
  `1db2241229a4d3bfe89cdf00f011789cdbbaee11`.
- Materialization plan invariance check against `8a703c9`: no tracked plan
  file changed and no plan hash changed.
- Execution-Gate Repair 1 validation: `cargo fmt --all -- --check`, JSON parse,
  `cargo test --locked -p splendor-cli --test m27a_design -- --test-threads=1`
  (`3 passed`, exit 0), and `git diff --check` passed.
- Execution-Gate Repair 1 commit:
  `6d79e8adfd6fd3143d62e26d5634bdb82dbd4731`.
- Materialization validation: JSON parse, `cargo fmt --all -- --check`,
  `cargo test --locked -p splendor-cli --test m27a_design -- --test-threads=1`
  (`3 passed`, exit 0), and `git diff --check` passed. All 14 plans
  deserialized, validated, expanded to 64 matches, and matched their bundle
  raw/canonical hashes.
- Local validation commands and results:

  ```text
  python3 -m json.tool benchmarks/m27a-search-budget-scaling-v1.json >/dev/null — exit 0
  cargo fmt --all -- --check — exit 0
  cargo test --locked -p splendor-cli --test m27a_design -- --test-threads=1 — PASS, exit 0 (1 test)
  cargo test --locked --workspace --all-targets -- --test-threads=1 — exit 101; only the known Linux process test `shutdown_reaps_child` failed
  cargo test --locked --workspace --all-targets -- --test-threads=1 --skip shutdown_reaps_child — exit 0; all non-skipped workspace tests passed
  git diff --check — exit 0
  ```

- Validation includes exact 14-plan / 896-match matrix coverage before any
  execution authorization is considered.
- The unskipped workspace failure is an existing Linux child-process status
  issue outside this design-only change and is recorded rather than relabeled
  as a clean full-workspace pass.

## Result and decision

M27A Repair 2 and the 14-plan materialization are `ACCEPTED / FROZEN`. The
materialization review is closed, but Execution-Gate Repair 1 is `HOLD` because
the prior helper could miss an overlapping valid stable window. The repair is
implemented and locally verified; plan execution and Arena execution remain
unauthorized pending independent repair review and runtime/build freeze.
M24.5 remains `ACCEPTED`; M07 remains champion; no promotion has occurred.

## Known limitations

- The 32-seed cells and all Repair 2 operating-region thresholds are frozen
  diagnostic choices, not executed evidence.
- Plan materialization proves only the exact schedule/provenance contract; it
  does not prove runtime availability, competitive strength, or the operating
  region decision.
- The executable decision helper now uses start-window enumeration; its repair
  still requires independent review before any execution authorization.
- The 128-simulation cell uses the same fixed 30-second operational timeout as
  every other budget; there is no budget-specific timeout exception.
- The anchor Hoeffding interval is a per-budget diagnostic bound and is not a
  promotion or family-wise claim across the seven budgets; Repair 2 explicitly
  keeps it out of the practical operating-region decision function.
- No optimum or monotonicity claim is made; the selected value, if any, is the
  first low-cost stable operating point under the frozen rule.

## Next authorized gate

Independent review of Execution-Gate Repair 1, followed by the runtime/build
freeze and reviewed execution smoke. Until both gates pass, do not execute any
plan or generate eval-report/replay/result artifacts. M25, M26, and M28 remain
unauthorized.
