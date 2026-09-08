# S3 — Heuristic Full-Policy Limited Rollout (rollout policy improvement attempt)

STATUS     = PROPOSED (design revision 2; execution NOT authorized until
            this design passes review. The V1 review approved the
            mainline and the three-policy proposal set but required
            four experimental-semantics revisions — determinism
            contract, incomplete-rollout scoring, shared randomness,
            pilot gating — plus the Stage-B contraction to a
            heuristic-only primary comparison. All applied in this
            revision.)
REVISION   = V2 2026-09-09 — review repairs: (1) the normal decision
            path is a FIXED-WORKLOAD computation (frozen C-candidate /
            D-sample / P-ply contract) with unconditional bitwise
            determinism; the 2.0 s figure is the PILOT ACCEPTANCE LINE
            ONLY; a separate, much larger emergency guard (30 s,
            cooperative checks between rollouts) exists for live-Arena
            safety — if it EVER fires, that decision is recorded as an
            over-budget event and the run is flagged LOAD_TAINTED (the
            policy then explicitly depends on machine load; bitwise
            determinism is disclaimed for that decision); timing
            covers the entire pipeline (candidate generation,
            information-set construction, sampling, simulation,
            selection). (2) Incomplete rollouts no longer score 0.5:
            if ANY rollout participating in a decision's comparison
            fails to complete, the decision KEEPS a_H (no truncation
            fill-in; the comparison signal must come from completed
            worlds only). (3) Shared randomness: all candidates are
            evaluated on the SAME D sampled worlds; the simulated
            heuristic tie-break RNG is candidate-INDEPENDENT (derived
            from root identity, world index, ply, seat — fixed byte
            encoding); the root a_H is the canonical-first action of
            H* (no runtime RNG); the argmax tie rule is fully
            specified (prefer a_H only if it is IN the top-scoring
            set; otherwise canonical-first among the top set).
            (4) Pilot gating distinguishes "runs" from "performs
            meaningful comparisons": per-stratum reporting, exact
            selection (150 ordinary + 50 wide), |C|==1 decisions
            excluded from feasibility metrics and separately counted,
            D=4 stability reported as coarse only, and two-layer
            information-isolation tests. Stage B contracted to
            heuristic-only: 64 fresh blocks x 2 rotations = 128
            matches, single primary comparison, 95% decision CI (no
            multiplicity correction needed for one comparison).
            V1 = c253de7.
BASELINE   = a827207 (S2b record corrections, 2026-09-09)
OWNER-DATE = local implementation + cloud review, 2026-09-09

## Problem and evidence

### The research question

Four closed rounds (S0 calibration, S1 depth-feasibility, S2
attribution, S2b confirmation) establish: heuristic-v1 is the primary
development reference; the search baselines' shallow compute shows no
resolved strength gain; the single highest-frequency preference
difference did NOT transfer into improvement when transplanted as an
isolated rule. The coordinator's standing question:

> **Does added computation actually help the current strongest policy
> make better decisions?**

S3 tests the most direct computation the project has NOT yet tried:
evaluate root actions by the OUTCOME of letting the FULL heuristic
policy play on from each candidate action — rollout policy
improvement. No automatic improvement guarantee exists under finite
sampling, opponent modeling (both simulated seats play heuristic), and
imperfect information; S3 measures whether it helps in practice.

What this round specifically tests (framed exactly): **whether
re-ranking the actions proposed by the three frozen policies — using
full heuristic continuation rollouts on shared sampled worlds —
improves heuristic's playing strength.** The proposal-generation cost
(computing a_n1 and a_M07 on each context) is part of the measured
pipeline.

### What this is NOT

- NOT a search-engineering round (no TT redesign, no depth-2, no
  StaticEvaluator changes).
- NOT a guarantee claim; NOT a sequential transplantation of further
  S2 rules (coordinator's explicit prohibition).

## The candidate (V2 frozen semantics)

At a decision context (the acting player's observation + visible
history):

### Step 1 — Root candidate set (proposal generation)

```text
C = dedup{ a_H, a_n1, a_M07 }
```

- a_H = the canonical-FIRST action of H*(context) (the heuristic
  score-optimal set; deterministic, NO runtime RNG — the heuristic
  agent's tie-break RNG is never invoked at the root).
- a_n1 / a_M07 = the frozen search policies' actions on this context
  (exact configs 20260703/s4/d1/n{1,2000}).
- Dedup by canonical action equality; C is ordered canonically.
- If |C| == 1: the decision returns that action immediately (no
  rollouts; recorded as a no-comparison decision and counted
  separately — these decisions must not inflate feasibility metrics).

### Step 2 — Shared sampled worlds

```text
worlds[0..D) = sample_determinization_v1(root information set,
                                          sample_seed 20260703 stream,
                                          world_index)
```

- D = 4 (frozen; design-review parameter).
- ALL candidates are evaluated on the SAME worlds (shared random
  conditions — a candidate never gets an easier world draw).

### Step 3 — Full-policy rollouts

For each candidate a in C and each world w: apply a to a clone of w,
then simulate BOTH seats playing the frozen heuristic policy until
terminal or the ply cap:

- Each simulated seat decides ONLY from its own observation + visible
  history (the ISMCTS information-isolation pattern; no referee-only
  reads, no true deck order, no opponent blind reserves).
- Simulated tie-break RNG: candidate-INDEPENDENT, derived per
  (root identity, world index, ply, seat) with a fixed byte encoding
  `SHA256("s3-rollout|" + root_info_hash + "|" + world + "|" + ply +
  "|" + seat)` -> StableRng. Forked trajectories after different root
  actions therefore see DIFFERENT tie-break streams at the same
  (world, ply, seat) only when their root identity differs — which it
  does not — so the streams are identical across candidates at equal
  (world, ply, seat): the comparison is randomized-common-random-
  numbers. (Divergent trajectories legitimately choose different
  actions later; only the tie-break STREAMS are shared.)
- P = 120 plies per rollout (frozen; design-review parameter).

### Step 4 — Completion-gated scoring (V2 semantics)

A rollout is COMPLETE iff it reaches a terminal state within P plies
(incomplete = ply-capped; there is no time-based truncation in the
normal path).

```text
if ANY (candidate, world) rollout in this decision is incomplete:
    decision action = a_H                      (keep the base policy)
    decision marked fallback_ply_cap
else:
    score(a) = mean over w of terminal_score(a, w)     # win=1, tie=0.5, loss=0
```

- NO truncation fill-in value: an incomplete world contributes no
  signal, and a decision with any incomplete rollout keeps a_H. The
  comparison signal must come from completed worlds only.
- Recorded per decision: all-complete flag, per-rollout completion,
  and (in the emergency-guard case below) fallback_time.

### Step 5 — Argmax with the full tie rule (V2)

```text
T = { a in C : score(a) == max_score }        # top-scoring set
if a_H in T:  chosen = a_H
else:         chosen = canonical_first(T)
```

This fully specifies ties among non-a_H candidates (canonical-first)
and the a_H preference (only when a_H is itself in the top set).

### Determinism contract (V2, replaces the wall-clock guard)

- **Normal path**: the decision is a pure function of (context,
  frozen constants, frozen seed derivations) — unconditionally
  bitwise deterministic. There is NO wall-clock input to the action
  choice.
- **2.0 s is the PILOT ACCEPTANCE LINE ONLY** (Stage A measures the
  distribution; it is not enforced at runtime).
- **Emergency guard (live-Arena safety only)**: a cooperative check
  BETWEEN rollouts (never mid-rollout) against a 30 s per-decision
  budget. If it fires: the decision keeps a_H, the event is recorded
  (over-budget), and the Arena run is flagged `LOAD_TAINTED` — from
  that point the policy explicitly depends on machine load for the
  affected decisions, and bitwise determinism is disclaimed for them.
  The guard is expected to NEVER fire given the pilot's measured
  costs; its existence does not weaken the normal-path determinism.
- **Timing scope**: all pipeline stages are timed (candidate
  generation, information-set construction, sampling, simulation,
  selection) — reported per stage in the pilot.

## Two-stage work package

### Stage A — Feasibility pilot (no Arena, no strength claims)

Question: does the fixed-workload computation complete meaningful
comparisons within acceptable latency, on ordinary AND wide-branching
positions?

**Corpus**: eligible contexts from the S0 replays — `Phase::Main`,
`>= 2` legal actions, non-terminal, identity-triple dedupe; stratified:

- ordinary stratum: legal_actions < 30;
- wide stratum: legal_actions >= 30.

Selection (exact byte encoding, preregistered):
`SHA256(utf8("43_300_001|" + obs_hash + "|" + history_hash + "|" +
info_hash))` ascending — first **150 within the ordinary stratum** and
first **50 within the wide stratum** (per-stratum selection; V1's
"first 200" phrasing is corrected). If a stratum has fewer eligible
contexts than its quota, take all of them and record the shortfall.

**Reported per stratum separately** (never mixed into one "natural
distribution p95"):

- decision wall time (mean/p50/p90/p95/max; nearest-index quantile
  convention `round(q*(n-1))`, preregistered);
- per-rollout completion rate; all-complete decision fraction;
- |C| distribution and the no-comparison (|C|==1) decision count —
  these are EXCLUDED from the latency/completion feasibility metrics
  and reported separately;
- ply-cap fallback rate (decisions keeping a_H due to incompleteness);
- sampling stability: the fraction of decisions whose argmax changes
  under leave-one-world-out (a coarse descriptive diagnostic for
  D=4 — explicitly NOT a high-precision confidence statement).

**Frozen pilot gates** (evaluated on the ORDINARY stratum; the wide
stratum is reported but gated only on the emergency-guard expectation):

- G1: p95 decision wall time <= 2.0 s (ordinary stratum).
- G2: all-complete decision fraction >= 70% (ordinary stratum).
- G3: ply-cap fallback rate <= 30% (ordinary stratum; the complement
  of G2 stated separately so both are auditable).

If any gate fails: **S3 STOPS** (constants are not tuned within this
round; any change reopens the design). If all gates pass, the pilot
also reports (descriptively, NOT a success signal) the fraction of
comparable decisions where the rollout choice differs from a_H.

**Information-isolation tests (two layers, both fail-closed)**:

1. ROOT layer: with the root information set fixed, changing the TRUE
   hidden world (a different determinization consistent with the same
   information set) must not change the root decision inputs
   (candidate set, a_H) — the decision procedure reads only the
   information set.
2. SIMULATION layer: within a rollout, with a simulated player's
   observation fixed, changing fields invisible to that player must
   not change that player's chosen action. Simulated worlds whose
   observations legitimately differ MAY choose different actions.

### Stage B — Independent strength confirmation (only if Stage A passes)

Contracted per the V1 review (first round tests ONLY the primary
question — can rollout improve heuristic?):

- **Single pairing**: `candidate vs heuristic`.
- 64 fresh seed blocks x 2 rotations = **128 matches**; seed segment
  fresh after S2b's (registry-asserted disjoint).
- **Statistics**: paired-block bootstrap, 10,000 resamples, seed
  43_300_001; **95% descriptive CI and 95% decision CI** (a single
  primary comparison needs no multiplicity correction). UNRESOLVED
  stands; extra seeds are the coordinator's decision, never automatic.
- **Success (frozen)**: RESOLVED improvement over heuristic (95%
  decision CI entirely above 5000 bps). Resolved loss = REFUTED
  (sealed negative). UNRESOLVED = UNRESOLVED.
- Opponent-pool calibration vs n1/M07 happens only AFTER a confirmed
  win, as a separate round.
- Emergency-guard telemetry: any firing is recorded per decision; a
  LOAD_TAINTED flag on the run is reported in the result and to the
  closure review (it does not void the run by itself, but the review
  sees it).
- No outcome changes the M07 historical champion, the promotion
  state, or the primary reference without a separate field
  calibration.

## Scope and non-goals

- No StaticEvaluatorV1 changes; no heuristic/n1/M07 behavior changes
  (the policies are only INVOKED; the root a_H is computed from the
  frozen scoring, never from the heuristic agent's RNG).
- No offline tuning between implementation and Arena (S2b contract);
  the frozen constants (D=4, P=120, the tie rule, the completion
  gate) change only through a design review.
- No sequential transplantation of further S2 rules.
- No neural work; no depth-2/3+; no TT/search engineering.

## Contracts and invariants

- Normal-path bitwise determinism (fixed workload, fixed seed
  derivations, no wall-clock inputs) — regression-tested.
- Shared-randomness invariants: same worlds across candidates;
  candidate-independent simulated tie-break streams; root RNG never
  advanced by simulation — all locked by unit tests.
- Completion-gated scoring and the full tie rule — locked by unit
  tests (including the "two non-a_H candidates tie above a_H" case).
- Two-layer information isolation — locked by the tests above.
- Fail-closed audits: lineup/rotation, replay verification, exhaustive
  recomputation, per-stage timing telemetry, guard-event binding.

## Implementation plan

1. Rust: rollout engine (shared worlds; step states; both seats =
   frozen heuristic scoring from their own observations with the
   shared tie-break stream; ply cap; terminal scoring; completion
   gating; the full tie rule) + the candidate composition policy +
   CLI `agent-rollout` with the frozen constants + per-stage timing +
   guard telemetry. Unit tests: determinism (same input -> same
   action, twice), shared-world equality, candidate-independent
   streams, |C|==1 short-circuit, ply-cap fallback, tie rule,
   isolation layers.
2. `scripts/s3_pilot.py`: stratified corpus selection, pilot
   execution, per-stratum reporting, gate evaluation, tracked pilot
   result.
3. If Stage A passes: `scripts/s3_orchestrator.py` (128-match Arena,
   heuristic-only) + `scripts/s3_final_audit.py`; tracked result.
4. Docs closure + handoff; S3 closure review at the coordinator's two
   intervention points (pilot end; Arena end).

## Estimated cost

- Worst-case normal-path workload per decision: |C| x D x P = at most
  3 x 4 x 120 = 1,440 simulated plies (each: clone + apply +
  observation rebuild + integer scoring) PLUS candidate generation
  (one n1 and one M07 decision ~1.5 ms / ~12-14 ms). The pilot
  measures the actual distribution; nothing is asserted in advance
  beyond the gates.
- Pilot: 200 contexts; minutes-scale expected.
- Arena (if run): ~8k candidate decisions at the pilot-measured cost;
  the emergency guard (30 s) bounds the pathological tail.

## Known limitations

- Both simulated seats play heuristic — an opponent model; rollout
  values are biased if heuristic-vs-heuristic dynamics differ from
  real play. Stated, not corrected.
- D=4 gives a coarse signal; leave-one-out stability is a descriptive
  diagnostic, not a confidence measure.
- The proposal set (three frozen policies) may miss the true best
  action when all three agree-and-are-wrong — an accepted boundary.
- The completion gate means long games reduce the comparison signal;
  the pilot's all-complete fraction quantifies this before any Arena.
- A REFUTED/UNRESOLVED outcome closes S3 without prejudging rollout
  variants (any variant = new design).

## Next authorized gate

- Cloud review of this V2: (a) the fixed-workload determinism contract
  and the emergency-guard semantics; (b) the completion-gated scoring
  and the full tie rule; (c) shared-randomness derivations; (d) the
  pilot gates/strata and the |C|==1 exclusion; (e) Stage-B contraction
  (heuristic-only, 128 matches, 95% decision CI); (f) the frozen
  constants (D=4, P=120).
- After APPROVE: Stage A pilot -> coordinator checkpoint -> (if gates
  pass) Stage B Arena -> closure review.
