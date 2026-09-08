# S3 — Heuristic Full-Policy Limited Rollout (rollout policy improvement attempt)

STATUS     = PROPOSED (design-only, authorized by the S2b closure /
            coordinator's 2026-09-09 direction; execution NOT authorized
            until this design passes review)
BASELINE   = 18f798d (S2b closure, 2026-09-09)
OWNER-DATE = local implementation + cloud review, 2026-09-09

## Problem and evidence

### The research question

Four closed rounds (S0 calibration, S1 depth-feasibility, S2
attribution, S2b confirmation) establish: heuristic-v1 is the primary
development reference; the search baselines' shallow compute shows no
resolved strength gain; the single highest-frequency preference
difference (take-vs-buy, 11.27%) did NOT transfer into improvement when
transplanted as an isolated rule (S2b: UNRESOLVED vs n1, resolved
weaker than heuristic). One full calibration-to-confirmation cycle is
complete, and the coordinator's standing question is:

> **Does added computation actually help the current strongest policy
> make better decisions?**

S3 tests the most direct computation the project has NOT yet tried:
evaluate root actions by the OUTCOME of letting the FULL heuristic
policy play on from each candidate action — rollout policy
improvement. This is the classic rollout idea (Bertsekas): approximate
the value of action a by simulating the base policy forward from a and
scoring the terminal outcome, then pick the action with the best
simulated outcome.

Three project-specific reasons (coordinator's ruling):

1. The base policy has real win-rate support (heuristic is the
   measured strongest reference) — a rollout candidate directly
   challenges the strongest agent instead of patching a weaker one.
2. It preserves heuristic's ENTIRE downstream decision machinery —
   no need to guess which isolated rule is transplantable (S2b showed
   the isolated-rule path failed once).
3. It tests a different evaluation source: M10 ISMCTS still evaluates
   leaves with StaticEvaluatorV1; full-policy rollouts are not a rerun
   of the existing ISMCTS.

### What this is NOT

- NOT an improvement guarantee: finite sampling, opponent modeling
  (both seats play heuristic), and imperfect information mean rollout
  policy improvement has NO automatic improvement property here. The
  coordinator's ruling states this explicitly; S3 measures whether it
  helps in practice.
- NOT a search-engineering round: no TT redesign, no depth-2, no
  StaticEvaluator changes.

## Initial design

### The candidate (parameter-free except the frozen rollout budget)

At a decision context (the acting player's observation + visible
history):

```text
1. Root candidate set C = dedup{ a_H, a_n1, a_M07 }  (the frozen
   heuristic action, the frozen n1 action, the frozen M07 action —
   each computed on this context; deduplicated). Rationale: the three
   frozen policies define the project's known decision diversity; the
   set stays small (<= 3) independent of branching factor.

2. Sample D determinizations of the player's information set
   (sample_seed 20260703 stream, sample_count D — frozen below) —
   the same hidden-state sampler the determinization family uses.

3. For each candidate action a in C and each sampled determinization
   d: apply a to d, then SIMULATE forward with BOTH seats playing the
   frozen heuristic policy (each seat decides from ITS OWN observation
   + visible history — information-isolated, no referee-only reads),
   until terminal or the ply cap P (frozen below).

4. Score each (a, d) rollout by terminal outcome from the root
   player's perspective: win = 1, tie = 0.5, loss = 0; an
   incomplete rollout (ply cap) scores 0.5 (conservative neutral —
   frozen before any result; alternatives rejected: static-eval
   fallback would reintroduce the evaluator we are trying to get away
   from; 0 would punish viable long games).

5. Choose argmax_a of the mean score over D rollouts; tie between
   candidates -> keep a_H (the base policy's action — conservative
   rollout convention; frozen before any result).
```

Frozen budget constants (design-review decision points, defaults
proposed):

- D (determinizations per candidate): 4 (matches the family's
  sample_count).
- P (ply cap per rollout): 120 plies (S0 games ran ~52-66 plies mean;
  120 covers natural termination with margin; the pilot measures the
  actual completion rate).
- TOTAL per-decision budget: the work is |C| x D rollouts x <= P
  heuristic decisions = at most 3 x 4 x 120 = 1,440 heuristic
  decisions, each ~0-cost (integer scoring on an observation) — but
  the REAL cost is state cloning + event log growth per applied
  action, which the pilot measures. A hard wall-clock guard W
  (default 2.0 s per decision, the S1 cost-gate precedent) bounds the
  worst case: if exceeded, the candidate falls back to a_H for that
  decision (conservative; the trigger count is recorded).

### Information-isolation invariants (frozen)

- Every simulated seat — including the root player after the candidate
  action — decides ONLY from its own observation + visible history
  reconstructed from the simulated state (the ISMCTS pattern:
  `state.observation(current_player)` + `visible_events(...,
  Audience::Player(...))`); never from the true hidden state, deck
  order, or opponent blind reserves.
- The determinizations are sampled from the ROOT player's information
  set only (the same `sample_determinization_v1` machinery as the
  frozen family); within a rollout, the sampled state is the ground
  truth of that simulated world (both seats stay observation-bound
  inside it).
- The heuristic's tie-break RNG: rollouts use a FIXED per-rollout seed
  derived from (root identity, candidate, determinization index) —
  deterministic, reproducible, and never carrying state across
  rollouts. (The heuristic consumes RNG only on exact-score ties.)

### What must be frozen before the confirmation Arena

- D, P, W and the fallback rule (pilot may only MEASURE, not tune:
  the pilot runs with the defaults above; if the pilot fails its
  gates, S3 stops — the constants are NOT adjusted and re-run within
  this round; any change reopens the design).
- Incomplete-rollout scoring (0.5) and the candidate tie-break
  (prefer a_H).
- The root candidate set definition (dedup of the three frozen
  policies' actions).

## Two-stage work package (per the coordinator's ruling)

### Stage A — Feasibility pilot (no Arena, no strength claims)

Question: can full-heuristic rollouts distinguish the candidate
actions within acceptable latency, on both ordinary and
wide-branching positions?

- Corpus: 200 contexts sampled deterministically (SHA256 selection,
  exact byte encoding preregistered — S1 lesson) from the S0 replays,
  stratified 150 ordinary (legal_actions < 30) + 50 wide-branching
  (legal_actions >= 30) — the S1 tail lesson demands wide-branching
  coverage.
- Measurements per context: wall time per decision (mean/p50/p95/max),
  rollout completion rate (terminated vs ply-capped), candidate-set
  size distribution, sampling disagreement (how often the argmax over
  D samples is unstable — a bootstrap-over-determinizations proxy),
  and the fallback-trigger rate under W.
- Frozen pilot gates (defaults; review may adjust BEFORE execution):
  - p95 decision time <= 2.0 s (the S1 cost-gate precedent — the
    candidate must fit the same local-cost envelope);
  - rollout completion >= 70% (most rollouts reach terminal within P;
    if most hit the cap, the terminal-outcome signal is diluted);
  - fallback rate under W <= 5% (the guard must be rare, not the norm).
- If ANY gate fails: **S3 STOPS (COMPUTE_INFEASIBLE-style)**. The
  constants are not tuned within this round; whether to invest further
  is the coordinator's separate decision. If ALL gates pass, Stage A
  also reports (descriptively) how often the rollout choice differs
  from a_H on the pilot corpus — a scope preview, NOT a success
  signal.

### Stage B — Independent strength confirmation (only if Stage A passes)

- The single frozen candidate (the rule above with the Stage-A-measured
  constants — which are the defaults, since no tuning is allowed)
  enters a fresh-seed Arena.
- Pairings: `candidate vs heuristic` (PRIMARY — the coordinator's
  anchor question) + `candidate vs n1` + `candidate vs M07`
  (adaptability checks). 64 fresh blocks x 2 rotations x 3 pairings =
  384 matches. Seed segment: fresh (next after S2b's 5_800_192..255;
  registry-asserted).
- Statistics: the S0 frozen protocol (paired-block bootstrap, 10,000
  resamples; 95% descriptive + 98.33% joint-decision CI for the
  3-comparison family; UNRESOLVED stands).
- Success (frozen): RESOLVED improvement over heuristic in the primary
  pairing. Any lesser outcome is recorded as-is:
  - resolved loss vs heuristic: REFUTED (valid negative, sealed);
  - UNRESOLVED vs heuristic: UNRESOLVED (extra seeds = coordinator
    decision);
  - win vs n1/M07 but not heuristic: recorded as adaptability signal
    only — the candidate's purpose is improving ON heuristic.
- No outcome changes the M07 historical champion or promotion state.

## Scope and non-goals

- No StaticEvaluatorV1 changes; no heuristic behavior changes (the
  heuristic policy is only INVOKED inside rollouts); no n1/M07
  behavior changes (their actions only join the root candidate set).
- No neural work; no depth-2/3+; no TT/search engineering.
- No offline tuning between implementation and Arena (S2b contract).
- No sequential transplantation of further S2 rules (coordinator's
  explicit prohibition).

## Contracts and invariants

- Determinism: identical inputs produce identical decisions (fixed
  seeds, sorted candidate order by canonical action order with a_H
  tie-preference).
- Information isolation per the frozen invariants above; a regression
  test constructs a context where referee-only information would
  change the rollout choice and asserts it does not.
- Stage A gate arithmetic preregistered (S1 lesson: quantile
  convention = nearest-index `round(q*(n-1))`, stated here).
- Selector byte encoding for the pilot corpus preregistered:
  `SHA256(utf8("43_300_001|" + obs_hash + "|" + history_hash + "|" +
  info_hash))` ascending, first 200 within each stratum (150 + 50).
- Fail-closed audits: lineup/rotation, replay verification, exhaustive
  recomputation, per-decision budget-guard telemetry binding.

## Implementation plan

1. Rust: rollout engine (sample determinizations; step states; both
  seats = frozen heuristic policy from their own observations; ply
  cap; terminal scoring) + the candidate composition policy; CLI
   `agent-rollout` with the frozen constants; unit tests (information
   isolation, determinism, ply-cap scoring, tie preference, candidate
   dedup).
2. `scripts/s3_pilot.py`: corpus selection (stratified), pilot
   execution, gate evaluation, tracked pilot result.
3. If Stage A passes: `scripts/s3_orchestrator.py` (384-match Arena)
   + `scripts/s3_final_audit.py`; tracked result.
4. Docs closure + handoff; S3 closure review (the coordinator's two
   intervention points: pilot end and Arena end).

## Estimated cost

- Heuristic decisions are ~0-cost; the real cost is state cloning and
  event-log growth per simulated ply. Worst case per decision:
  |C| x D x P = 1,440 simulated plies (each a clone + apply +
  observation rebuild). The pilot measures actual cost; the 2.0 s
  guard bounds the tail.
- Pilot: 200 contexts x ~1,440 plies worst case ~ minutes.
- Arena (if run): candidate decisions at pilot-measured cost; n1/M07
  opponent seats at their S0-measured costs; total expected
  minutes-to-low-hours depending on the measured per-decision cost;
  the 2.0 s guard caps the candidate at ~8k decisions x <= 2 s ~<=
  4.4 h serial worst case (4 workers ~<= 1.1 h). The pilot's p95
  measurement will refine this before Stage B is scheduled.

## Known limitations

- Both simulated seats play heuristic — an opponent model; if
  heuristic-vs-heuristic dynamics differ from real opponents, rollout
  values are biased. Stated, not corrected (correcting it = opponent
  modeling, out of scope).
- The terminal-outcome signal with D=4 samples is coarse; sampling
  disagreement is reported in the pilot.
- The candidate set (3 frozen policies' actions) may miss the true
  best action when all three agree-and-are-wrong; that is an accepted
  boundary of this design.
- A REFUTED or UNRESOLVED outcome closes S3 without prejudging
  alternative rollout variants (any variant = new design).

## Next authorized gate

- Cloud review of this design: (a) the candidate rule and frozen
  constants (D=4, P=120, W=2.0 s, 0.5 cap-score, a_H tie-preference);
  (b) the root candidate set definition; (c) the pilot gates and
  stratified corpus; (d) the Stage-B pairing set and success rule;
  (e) the no-tuning boundary.
- After APPROVE: Stage A pilot -> (if gates pass) Stage B Arena ->
  closure review at the coordinator's two intervention points.
