# S3 — Heuristic Full-Policy Limited Rollout (rollout policy improvement attempt)

STATUS     = DESIGN_V2 / APPROVED-FOR-PILOT (the aligned review approved
            the direction, the three-policy proposal set, D=4, and
            P=120 for this round, and fixed the complete experimental
            contract below; Stage-A implementation + pilot + minimal
            tests/audits are AUTHORIZED; everything after the pilot —
            including Stage B — requires the Stage-A review. P1:6 /
            P2:3 from the two aligned reviews are all incorporated.)
REVISION   = V2 2026-09-09 (final contract; incorporates the local
            coordinator's four semantic repairs AND the cloud's two
            additions). V1 = c253de7.
BASELINE   = a827207 (S2b record corrections, 2026-09-09)
OWNER-DATE = local implementation + cloud review, 2026-09-09

## Problem and evidence

### The research question

Four closed rounds (S0 calibration, S1 depth-feasibility, S2
attribution, S2b confirmation) establish: heuristic-v1 is the primary
development reference; the search baselines' shallow compute shows no
resolved strength gain; the single highest-frequency preference
difference did not transfer into improvement as an isolated
transplant. The coordinator's standing question:

> **Does added computation actually help the current strongest policy
> make better decisions?**

S3 tests the most direct computation not yet tried: evaluate root
actions by the OUTCOME of letting the FULL heuristic policy play on
from each candidate action — rollout policy improvement, under a
contract with no static-leaf evaluation, no wall-clock action
semantics, and no fabricated value for incomplete simulations. No
automatic improvement guarantee exists (finite sampling, opponent
modeling, imperfect information); S3 measures whether it helps.

Framing (frozen): this round tests **re-ranking the actions proposed
by the three frozen policies — via full heuristic continuation
rollouts on four shared hidden-world samples — and whether that
improves heuristic's playing strength.** All proposal-generation cost
(including M07's n2000 decision) is inside the measured full-decision
wall time.

### What this is NOT

- NOT a search-engineering round; NOT a guarantee claim; NOT a
  sequential transplantation of further S2 rules (coordinator's
  prohibition); NOT a hyperparameter search (D=4 and P=120 are frozen
  for this round — no D/P grid).

## The candidate (V2 frozen semantics)

### Step 0 — Root eligibility and the a_H fast paths

At a real decision context (observation + visible history):

```text
H*(context) = argmax-set of frozen heuristic scoring   # no RNG
a_H = canonical-first(H*)

if |H*| > 1:          return a_H      # root tie -> no rollout, keep base
if |C| == 1:          return that action  # proposals agree -> no rollout
```

- Root eligibility for a ROLLOUT COMPARISON therefore requires
  `|H*| == 1 AND |dedup{a_H, a_n1, a_M07}| >= 2`.
- `a_H` is deterministic per context: the canonical-first action of
  the unique-optimum set (the heuristic's runtime tie-break RNG is
  never invoked at the root; see the root RNG spec below).

### Step 1 — Root proposal set (generation cost measured)

```text
C = dedup{ a_H, a_n1, a_M07 }        # canonical order
```

- a_n1 / a_M07: the frozen search policies' actions on this context
  (exact configs 20260703/s4/d1/n{1,2000}).
- |C| <= 3 regardless of branching; the set needs no new
  hyperparameters (no top-K, no score-gap threshold).

### Step 2 — Root heuristic RNG (production candidate)

The live candidate owns ONE persistent root stream:

```text
root_heuristic_rng = StableRng(20260812)
```

- Consumed ONLY by the root heuristic proposal (when a real decision
  somehow requires a tie-break at the root — which the |H*|==1 gate
  already prevents from reaching rollouts).
- Persistent across the candidate's real decisions within a game;
  NEVER consumed by rollout simulation; consumed exactly once per real
  decision that invokes the root heuristic proposal.
- a_H is therefore: heuristic-v1 scoring/tie semantics on the
  candidate's own current trajectory.

(Stage A's isolated fixed contexts have no history RNG state — and
need none: the |H*|==1 eligibility gate makes a_H unique without RNG.)

### Step 3 — Shared evaluation worlds (independent stream)

```text
worlds[0..D) = sample_determinization_v1(root information set,
                                          sample_seed = 43_300_101,
                                          world_index)     # D = 4
```

- **The evaluation stream is independent of the proposal stream**
  (43_300_101 != 20260703): a_n1/a_M07 were selected using the 20260703
  worlds; evaluating them on the SAME worlds would couple proposal and
  evaluation samples unnecessarily. Proposal-generation worlds and
  rollout-evaluation worlds are disjoint by construction.
- The D worlds are sampled ONCE per decision; every candidate is
  evaluated on the SAME worlds (a clone per candidate).

### Step 4 — Full-policy rollouts

For each candidate a in C and each world w: apply a to a clone of w,
then simulate BOTH seats playing the frozen heuristic policy:

- Each simulated seat decides ONLY from its own observation + visible
  history + certified legal actions (ISMCTS isolation pattern; no
  referee-only reads, no true deck order, no opponent blind reserves).
- **Per-(world, seat) persistent tie streams** (candidate-INDEPENDENT
  — common random numbers):

  ```text
  rng_seed(world, seat) = first 64 bits of
      SHA256("s3-rollout-rng-v1|" + root_identity + "|"
             + world_index + "|" + seat)
  ```

  Each simulated seat consumes its own stream along its trajectory.
  After candidate actions fork the trajectories, tie counts differ and
  streams advance differently — that is expected; what matters is
  every candidate starts from the SAME random conditions (same worlds,
  same per-(world,seat) stream heads). NO candidate id enters any
  seed.
- **P = 120** counts simulated action applications AFTER the root
  candidate action is applied (the root action itself does not count).
  A rollout is COMPLETE iff terminal within P; otherwise it is
  ply-capped.

### Step 5 — Completion-gated integer scoring

Terminal score for the ROOT player (integer, no floats):

```text
sole winner = 2 ; co-winner = 1 ; loser = 0
```

Per decision:

```text
if ANY (candidate, world) rollout is ply-capped:
    candidate_action = a_H ; decision marked PLY_CAP_FALLBACK
else:                       # complete comparison only
    score2(a) = sum over w of terminal_score2(a, w)
```

Incomplete comparisons make NO policy improvement (no fabricated
value; the fallback IS the base policy).

### Step 6 — Argmax with the full tie rule

```text
top = { a in C : score2(a) = max }
if a_H in top:  chosen = a_H
else:           chosen = canonical_first(top)
```

### Determinism contract (V2 final)

- The normal path is a pure function of (context, frozen constants,
  frozen seed derivations): unconditionally bitwise deterministic.
  There is NO wall-clock input to action selection — no 2 s fallback,
  no time-based a_H override. (2.0 s exists ONLY as the Stage-A
  acceptance threshold.)
- Operational safety is the Arena's existing `move_timeout_ms` =
  60,000: if it EVER fires, the outcome is an OPERATIONAL_TIMEOUT —
  the match is invalid / the pilot fails feasibility — it NEVER
  produces an a_H action that continues play.
- Full-decision wall time (for Stage A) covers EVERYTHING: a_H
  generation, a_n1 generation, a_M07 generation, information-set
  build, D world samples, all cloning, all rollouts, final selection.

## Stage A — Feasibility pilot (AUTHORIZED; then STOP for review)

### Corpus (frozen)

Source: all verified S0 replays. Root eligibility per the Step-0 gate:

```text
Phase::Main ; non-terminal ; legal_actions >= 2 ;
|H*| == 1 ; dedup identity triple ;
|dedup{a_H, a_n1, a_M07}| >= 2
```

(fast-path contexts — |C|==1 — are counted separately and NEVER enter
the feasibility metrics.)

Stratified selection (exact byte encoding, preregistered):
`SHA256(utf8("43_300_001|" + obs_hash + "|" + history_hash + "|" +
info_hash))` ascending — first **150 within ordinary
(legal_actions < 30)** and first **50 within wide (>= 30)**. If either
stratum cannot fill its quota: `PILOT_CORPUS_INSUFFICIENT` -> stop and
review (no cross-stratum borrowing).

### Reported per stratum (never mixed as "online-natural p95")

- full-decision wall time mean/p50/p90/p95/max (nearest-index
  quantile convention, preregistered);
- `complete_comparison_rate` (decisions where ALL |C| x D rollouts
  terminated — the decision-level usable-signal unit);
- `individual_rollout_terminal_rate` and `ply_cap_fallback_rate`
  (reported; NOT gates);
- |C| distribution; fast-path (|C|==1) counts;
- leave-one-world-out agreement (per complete comparison: does the
  D=3 choice match the D=4 choice?) — a coarse diagnostic, NOT a
  gate, NO bootstrap language;
- rollout-choice != a_H fraction (descriptive scope preview).

### Frozen gates (BOTH strata must pass each)

- Gate A (latency): p95 full-decision wall time <= 2.0 s.
- Gate B (usable comparison): complete_comparison_rate >= 70%.
- Gate C (no operational failure): process errors = 0; watchdog hits =
  0; information/action mismatches = 0. (No wall-time-fallback gate —
  that fallback no longer exists.)

### Soft exit

If rollout_choice != a_H NEVER occurs across all complete comparisons:
`NO_BEHAVIORAL_DELTA` -> S3 stops (a candidate identical to heuristic
in behavior is not worth an Arena). This is a zero-delta sanity exit —
NO scope threshold (no >=5%/10%).

### Information-isolation tests (two layers, fail-closed, architectural)

- ROOT layer: the production candidate's public API accepts ONLY
  (observation, visible_history, legal_actions) and builds its own
  information set — callers can never pass a root FullState.
  Regression: two true hidden worlds projecting to the same root
  information set -> identical candidate decisions.
- SIMULATION layer: a simulated seat's heuristic action depends only
  on its observation/history/legal set. Regression: changing deck
  order / opponent blind reserves / other invisible fields while the
  actor's observation is unchanged -> identical action. Worlds whose
  observations legitimately differ MAY choose different actions.

### Stage-A exit path (frozen)

```text
gates pass AND behavioral delta exists
    -> tracked pilot result -> cloud/coordinator review
    -> ONLY THEN Stage B authorization (no auto-proceed)

any gate fail / PILOT_CORPUS_INSUFFICIENT / NO_BEHAVIORAL_DELTA
    -> S3 stops; constants are NOT tuned in-round
```

## Stage B — Strength confirmation (CONTRACT FROZEN; NOT YET AUTHORIZED)

- Single pairing: `candidate vs heuristic`.
- Seeds: `5_800_256 .. 5_800_319` (64 blocks x 2 rotations = 128
  matches); registry fail-closed before execution.
- Statistics: paired-block bootstrap, 10,000 resamples, seed
  `43_300_201`; **95% two-sided decision CI** (single comparison, no
  Bonferroni).
- Verdicts: CI lower > 5000 -> CONFIRMED_IMPROVEMENT; CI upper < 5000
  -> REFUTED; otherwise UNRESOLVED. No extra seeds; no n1/M07 Arena.
- A confirmed win sets `REFERENCE_CHALLENGE_SIGNAL = true` and a
  separate small field-calibration round would be designed; nothing
  auto-promotes.

## Scope and non-goals

- No StaticEvaluatorV1 changes; no heuristic/n1/M07 behavior changes;
  no truncated-rollout value function; no time-based a_H fallback; no
  StaticEvaluator fallback inside rollouts.
- No D/P changes (no grid); no search engineering; no neural work; no
  promotion/default-agent change.

## Contracts and invariants (all unit-locked)

- Normal-path bitwise determinism (fixed workload; no wall-clock).
- Shared evaluation worlds; candidate-independent per-(world,seat)
  streams; root RNG never advanced by simulation; the root stream is
  production-only (Stage A needs no RNG history thanks to |H*|==1).
- Completion-gated integer scoring; full tie rule (incl. the
  non-a_H-top case); |H*|>1 and |C|==1 fast paths.
- Two-layer isolation (API-enforced at the root).
- Fail-closed audits; per-stage timing telemetry.

## Implementation plan (Stage A only, authorized)

1. Rust rollout engine + candidate policy + `s3-decide` CLI (replay +
   ply -> decision + full telemetry) with the frozen constants; unit
   tests for every invariant above.
2. `scripts/s3_pilot.py`: corpus extraction (Step-0 eligibility),
   stratified selection, pilot execution, per-stratum reporting, gate
   evaluation, tracked result.
3. Tests green (workspace) -> pilot -> tracked result -> STOP ->
   Stage-A review.

## Estimated cost

- Worst-case normal workload per comparison decision: |C| x D x P <=
  3 x 4 x 120 = 1,440 simulated plies + proposal generation (n1 ~1.5
  ms, M07 ~12-14 ms) — all measured, nothing asserted.
- Pilot: 200 contexts; minutes-scale expected.
- Stage B (if later authorized): ~8k candidate decisions at the
  pilot-measured cost; Arena's 60 s move timeout is the only
  operational bound.

## Known limitations

- Both simulated seats play heuristic (opponent model; biased if
  heuristic-vs-heuristic dynamics differ from real play) — stated,
  not corrected.
- D=4 is coarse; the leave-one-out diagnostic quantifies (does not
  certify) stability.
- The proposal set may miss the best action when all three policies
  agree-and-are-wrong — accepted boundary.
- The completion gate trades signal volume for purity; the pilot's
  complete_comparison_rate quantifies the trade before any Arena.

## Next authorized gate

- This document IS the Stage-A authorization. Execution: implement ->
  test -> pilot -> tracked result -> STOP -> Stage-A review (cloud +
  coordinator). Stage B remains unauthorized until that review.
