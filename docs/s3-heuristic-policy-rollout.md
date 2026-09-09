# S3 — Heuristic Full-Policy Limited Rollout (rollout policy improvement attempt)

STATUS     = STAGE-B EXECUTED / CONFIRMED_IMPROVEMENT (single valid run
            2026-09-09: implementation 297891e + 128-match Arena + final
            audit ALL CHECKS PASS; verdict CONFIRMED_IMPROVEMENT —
            candidate 80-0-48 vs heuristic, center 6250.0 bps, 95% decision
            CI [5468.8, 6953.1] entirely above parity. The rollout
            re-ranking of the three frozen policies' proposals IMPROVES
            heuristic's playing strength at D=4/P=120 with p95 decision
            cost ~43-116 ms. REFERENCE_CHALLENGE_SIGNAL = true; the primary
            reference and promotion state are UNCHANGED pending a separate
            field-calibration decision. Awaiting S3 closure review.)
RESULT     = CONFIRMED_IMPROVEMENT (Stage B). Stage A (Run2): PILOT_PASS.
            Stage B: the first CONFIRMED strength improvement of the
            strategy-reset line: added computation (shared-world
            full-heuristic rollouts over the three-policy proposal set)
            measurably helps the strongest policy make better decisions.
REVISION   = V2 2026-09-09 (frozen, 92af7bb) — executed as frozen; Run1
            VOID; Repair 1 + Run2 accepted; Stage B executed and
            CONFIRMED. V1 = c253de7.
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

## Stage-A execution record (Run1 VOID; Repair 1; Run2 PILOT_PASS)

### Run1 (c503bda) — VOID, not used for gate decisions

Five defects found by the Stage-A review of bf5df58:
1. Seat-RNG routing: `rngs[usize::from(actor.index() < 2)]` sent BOTH
   seats to stream 1 — the frozen per-(world, seat) streams were not
   actually in effect.
2. Pilot row join keyed on (basename, ply); every replay's basename is
   `match-replay.json`, so rows collided across games.
3. The eligibility pool came from the S2 census (P1+P2 = 256 games),
   not the frozen all-384 population; no identity-triple dedupe; the
   selector used game_id|py instead of the frozen identity encoding.
4. The rollout tie-stream root identity was the replay FILE PATH — the
   same information set at different paths got different streams.
5. `state.apply` errors were swallowed (`let _ =`), making Gate C
   (zero mismatches) vacuous.

### Repair 1 (authorized scope, all applied)

1. Seat routing fixed: `rngs[actor.index()]` with a 2-player assertion.
2. Root identity = the authoritative `information_set_hash`, derived
   INSIDE `s3_decide` (one shared helper for pilot and future live use;
   file paths can never enter the derivation).
3. All `state.apply` calls are fail-closed `Result` propagation (root
   candidate AND simulated actions); errors abort the decision with a
   non-zero exit — Gate C is now a real gate.
4. Population restored: ALL 384 verified S0 replays (P1+P2+P3), with a
   fresh P3 census pass; identity-triple dedupe (13,483 unique eligible
   contexts); the frozen selector
   `SHA256(utf8("43_300_001|obs|history|info"))` within strata.
5. Unique binding: every decision row carries its `root_identity`
   (information-set hash) and the audit joins contexts by that hash
   (fail-closed on mismatch).
6. Per-world terminal scores added to the decision telemetry; the
   leave-one-world-out diagnostic is computed from them (diagnostic
   only — NO gate).
7. The two frozen isolation regressions added (root public-input
   invariance; simulated-seat observation-purity invariance).
8. The tracked result records the full 200-identity manifest + digest.

### Run2 results (same frozen D=4/P=120/150+50/gates)

| Stratum | p95 full-decision | complete rate | behavioral delta | LOO |
|---|---:|---:|---:|---:|
| ordinary | **43 ms** (gate 2000) | 1.000 (gate 0.70) | 43/150 | 0.870 |
| wide | **116 ms** | 1.000 | 13/50 | 0.805 |

All gates pass in both strata; zero errors (fail-closed engine);
behavioral delta exists (NO_BEHAVIORAL_DELTA did not fire).

Attribution wording (corrected per the re-review — Run1->Run2 changed
seat RNG routing AND corpus AND selector AND identity dedupe AND row
binding, so the delta change admits no single-cause attribution):
Run1's behavioral-delta numbers were invalid under multiple
implementation/protocol defects; after repairing all defects and
restoring the frozen corpus, Run2 produced 43/150 and 13/50. The
magnitude of Run1's inflation cannot be attributed uniquely to the
seat-RNG bug.

LOO diagnostic correction (post-hoc, from the raw per-world scores —
the Run2 result's recorded values used a canonical-only D=3 tie rule;
the corrected rule is the frozen a_H-preference rule): ordinary
544/600 = 0.9067, wide 182/200 = 0.9100, overall 726/800 = 0.9075
(diagnostic only; no gate). The tracked Run2 result is left unchanged;
this paragraph is the correction record. The Rust `loo_agreement` now
implements the a_H tie rule for future runs.

|C| distribution (from the raw rows): 146 contexts with |C|=2, 54 with
|C|=3. The pilot contexts are pre-filtered to |C|>=2 and are all
RolloutComparison, so 100% complete comparison implies every
participating individual rollout terminated. The 56/200 behavioral
delta is on the SELECTED rollout-eligible comparison contexts — NOT a
fresh-game override rate (Stage B measures the live rate).

### Live-candidate semantics for Stage B (P1-6, frozen here BEFORE any Arena)

The Stage-B candidate's base behavior at every real decision:

```text
compute the frozen heuristic proposal exactly once, using the
persistent root_heuristic_rng = StableRng(20260812):
    unique maximum -> no RNG consumed; tie -> the stream advances

if phase != Main:               return the actual heuristic action
if legal_actions < 2:           return the actual heuristic action
if |H*| > 1:                    return the RNG-tiebroken heuristic action
otherwise (Main, >=2 legal, unique H optimum):
    proposal set dedup{a_H, a_n1, a_M07}; |C|==1 -> return it
    else full rollout comparison per the V2 contract
```

The root stream matches the standalone heuristic agent's semantics
(same seed, same tie-only consumption, never advanced by simulation),
so on fast paths and root ties the candidate is EXACTLY heuristic — no
hidden tie-behavior change. Non-Main phases fast-path to the heuristic
(decided now, not at Stage-B implementation time).

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

## Stage-B execution record (2026-09-09, single valid run)

Implementation (297891e): `agent-s3-rollout` live agent (zero flags;
identity fully frozen). Live semantics per the Repair-1 frozen contract:
the persistent root RNG is the run_agent seed 20_260_812 (the standalone
heuristic stream; unique maxima consume no RNG, ties advance it exactly
as the standalone agent); non-Main / <2 legal / |H*|>1 fast paths return
the ACTUAL standalone heuristic action including RNG-tiebreaks (an
initial closure-based tie helper had a tie-index bug caught by the
3-match smoke — fixed before any Arena match). Regressions added:
step-by-step lockstep parity vs the standalone heuristic policy
(including ties; any divergence must be an actual rollout override),
and counter consistency. Workspace 790/0; smoke 3/3 live matches
complete (~0.9 s each).

Arena (seeds 5_800_256..319 — registry-asserted fresh; 64 blocks x 2
rotations = 128 matches; candidate vs heuristic only; ~47 s wall):

| Metric | Value |
|---|---|
| Record (candidate perspective) | **80-0-48** |
| Center | **6250.0 bps** |
| 95% decision CI | **[5468.8, 6953.1]** — entirely above 5000 |
| Verdict | **CONFIRMED_IMPROVEMENT** |

Final audit (fail-closed): seed disjointness; exhaustive lineup
(candidate = exact zero-flag args; heuristic = exact frozen args);
128/128 replays verified; full recomputation of W/T/L, block scores,
center, CI, verdict; decision-block consistency; binary identity. ALL
CHECKS PASS.

Decision (frozen table): CONFIRMED_IMPROVEMENT sets
REFERENCE_CHALLENGE_SIGNAL = true. The primary reference and promotion
state are UNCHANGED — a separate small field calibration (the candidate
vs n1 and vs M07, plus the reference question) is the follow-up design
decision for the closure review. No transitivity claims (n1/M07
unmeasured this round). Extra seeds not authorized (none needed).

Canonical result sentence (permanent):

> In a fresh 128-match paired-seed Arena against heuristic-v1, the
> rollout-enhanced candidate (D=4 shared-world full-heuristic rollouts
> re-ranking the {a_H, a_n1, a_M07} proposal set, P=120,
> completion-gated integer scoring) won 80-0-48 (center 6250.0 bps;
> 95% CI [5468.8, 6953.1]) — a resolved improvement over the calibrated
> primary reference at a measured p95 decision cost of ~43-116 ms.

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
