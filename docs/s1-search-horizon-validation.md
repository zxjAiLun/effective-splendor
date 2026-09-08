# S1 — Search-Horizon Validation (depth-2 vs the calibrated field)

STATUS     = PROPOSED (design-only, per S0 closure authorization; execution
            NOT authorized until this design passes review)
BASELINE   = 093e5fa (S0 closure, 2026-09-08)
OWNER-DATE = local implementation + cloud review, 2026-09-08

## Problem and evidence

### Research question

S0 established the calibrated field: `heuristic-v1` is the primary
development reference (resolved stronger than both `n1` and `M07` under
98.33% joint-decision CIs); `n1` vs `M07` is UNRESOLVED at this budget —
there is no competitive evidence that M07's additional shallow compute
buys a separable gain, but that is NOT evidence that deeper search has
no value (M42S varied node budget at FIXED depth 1; it never tested a
longer horizon).

S1's question, refined by S0's closure:

> **Can increasing the true search horizon (depth 1 → depth 2, same
> evaluator, same determinization sampling) produce a competitive gain
> sufficient to beat the calibrated field — starting with heuristic?**

Design principles frozen by the S0 closure:

1. Primary strength anchor = `heuristic-v1`.
2. Final candidates must face the FULL {heuristic, n1, M07} pool.
3. A small compute-feasibility probe MUST precede any Arena (prove that
   "depth=2" actually completes a meaningful fraction of deeper
   continuations within local budget, rather than being a configured
   label that degenerates to budget-exhaustion fallback).
4. Only the horizon and its enabling budget change — same evaluator
   (StaticEvaluatorV1), same sampling (s4/d1 root determinization with
   sample_seed 20260703), no action pruning changes, no other search
   modifications.

### Why depth 2 (and not 3+)

- `--max-depth-turns` accepts 1..=12; depth 2 is the smallest step
  that changes the horizon at all. If depth 2 cannot beat the field,
  deeper depths are strictly more expensive follow-ups requiring their
  own evidence, not automatic continuations.
- The determinization information-set limitation (ISMCTS literature)
  applies at any depth; Arena is the only accepted strength test.

### Grounding measurements (pre-design, one S0 replay, 62 frames)

Whole-replay offline analysis wall (includes process startup and
per-frame artifact writing; live in-process cost is lower):

| Config | Wall | Nodes | ms/frame (offline) |
|---|---:|---:|---:|
| depth 1, n2000 (= M07) | 1.1 s | 189,798 | ~17 |
| depth 2, n2000 | 57.4 s | 6,384,445 | ~926 |
| depth 2, n10000 | 89.1 s | 9,821,103 | ~1,437 |
| depth 2, n50000 | 152.3 s | 9,829,240 | ~2,457 |

Two structural facts:

1. **Depth 2 costs ~55–85× depth 1** at the node level. n10000→n50000
   adds ~68% wall for +0.08% nodes — the marginal budget above n10000
   is nearly pure waste on this sample.
2. The nodes/continuation SATURATES around ~1,430 nodes (n10000 vs
   n50000 identical), meaning most continuations complete depth 2 well
   under 10,000 nodes — but this sample cannot tell us the completion
   FRACTION or the tail. That is exactly what the feasibility probe
   must measure with the new telemetry.

## Initial design

### Phase A — Feasibility probe (no Arena, no promotion claims)

**Goal**: measure whether depth-2 search actually completes at an
acceptable cost on REAL game positions, before spending any Arena
budget.

- **Corpus**: 200 real decision contexts sampled deterministically
  (seed 43_000_001, SHA-256 derivation as in prior milestones) from the
  S0 replays (the local, ignored artifacts — they are fresh real games
  on seeds 5_800_064..127, never used for any strength claim involving
  depth-2).
- **Probe configs**: `det-s4-d2-n2000` and `det-s4-d2-n10000`
  (sample_seed 20260703, 4 samples, depth 2).
- **New minimal telemetry (authorized by S0 closure, frozen schema
  here)**: extend the S0 `PerDecisionStatsV1` sidecar with two OPTIONAL
  fields, emitted only when a new `--emit-depth-histogram` flag is
  present:
  - `continuation_depth_histogram`: counts of each continuation's
    `completed_depth_turns` (0/1/2) for this decision;
  - `continuation_stop_reasons`: {depth_limit, node_budget} counts.
  Implementation note: this requires the determinization aggregator to
  accumulate per-continuation `completed_depth_turns`/`stop_reason`
  (already returned by every `search_maxn_v1` call and currently
  discarded by the aggregation loop). It is an additive counter in
  `RootDeterminizationStatsV1`'s aggregation site — NO frozen schema is
  modified (new optional fields in the sidecar struct only; the search
  itself is untouched).
- **Frozen feasibility thresholds** (decide before seeing results):
  - A depth-2 config is **feasible** iff on the probe corpus:
    (a) ≥ 80% of non-terminal continuations complete depth 2
    (histogram bin 2 / all non-terminal continuations);
    (b) p95 in-process decide time ≤ 150 ms (the S0-measured M07 p95
    was 43–78 ms; 150 ms is ~2× the worst observed tail, bounding the
    live agent within the existing 60 s move timeout with enormous
    margin).
  - If BOTH n2000 and n10000 are feasible, the CHEAPER one (n2000)
    goes to Arena.
  - If only n10000 is feasible, n10000 goes to Arena.
  - If NEITHER is feasible: **return COMPUTE_INFEASIBLE — S1 stops**.
    Whether to invest in search engineering (transposition reuse
    across continuations, etc.) is a separate user decision, NOT an
    automatic continuation of this round.

### Phase B — Arena validation (only if Phase A passes)

- **Candidates**: the single feasible depth-2 config chosen by Phase A.
- **Opponent pool** (S0 closure principle 2): all three of
  {heuristic-v1, n1, M07} — three pairings × 64 fresh seeds × 2
  rotations = 384 matches.
- **Fresh seed segment**: `5_800_128 .. 5_800_191` (64 seeds,
  immediately after the S0 segment; registry script extended and
  disjointness re-asserted).
- **Statistical protocol**: identical to S0 (paired-block bootstrap,
  10,000 resamples, seed 43_100_001; 95% descriptive CI; 98.33%
  joint-decision CI for the 3 pairings; Bonferroni wording:
  "approximately 95% family-wise").
- **Primary read-out**: the depth-2 candidate vs heuristic pairing
  (the anchor). The other two pairings are required context (does the
  candidate also beat the search baselines it modifies?).
- **Cost observation**: same S0 telemetry (decide_micros + counters +
  depth histogram via the new flag) on the candidate's seats only;
  opponents run without stats (heuristic) or with S0-level stats
  (n1/M07) as in S0.

### Decision table (frozen)

| Outcome (98.33% CIs) | Decision |
|---|---|
| Depth-2 beats heuristic AND beats or ties both n1 and M07 resolutions | Depth-2 is the new primary development reference; S2 targets making it cheaper or stronger; M07 historical champion still unchanged (promotion is a separate formal process). |
| Depth-2 beats heuristic but loses to n1 or M07 | Report the split field; no reference change; investigate the specific losing matchup in S2 scoping. |
| Depth-2 UNRESOLVED vs heuristic (regardless of others) | No reference change. Horizon gain unproven at this budget; S2 chooses between more seeds for this pairing (user decision) or error-attribution direction. UNRESOLVED ≠ equivalence. |
| Depth-2 LOSES to heuristic (resolved) | Negative result, sealed: single-step horizon extension does not beat the calibrated field under this contract. S2 pivots to error attribution on heuristic's losses (what beats heuristic at all?). |
| Phase A returns COMPUTE_INFEASIBLE | S1 stops; search-engineering investment is a separate user decision. |

Cost data never overrides strength verdicts (S0 rule).

## Scope and non-goals

- No evaluator changes, no sampling changes, no action pruning, no
  transposition-table changes, no search algorithm work beyond reading
  already-computed per-continuation depth/stop fields into the sidecar.
- No depth 3+ in this round.
- No neural anything (research line STOPPED).
- No promotion / champion-title change in any outcome (promotion
  remains a separate formal process; S1 only moves the development
  reference).
- No modification of the executed S0 result or artifacts.

## Contracts and invariants

- The depth-2 agent's decision behavior with telemetry flags OFF must
  be bit-identical to a flag-off build without the telemetry code (the
  counters are read-only observations of already-computed values; the
  S0 parity-test pattern is extended).
- `analyze-replay-determinization` per-ply sampling derivation means
  probe contexts are exactly reproducible; the probe corpus manifest
  (context identity hashes) is frozen in the probe result.
- Feasibility thresholds, seed segments, and the decision table are
  frozen BEFORE any probe or match runs.
- UNRESOLVED remains a standing verdict; no sequential extension.

## Implementation plan

1. Rust: add `--emit-depth-histogram` flag + the two optional sidecar
   fields (aggregation-site counters; additive; parity-locked).
2. `scripts/s1_feasibility_probe.py`: sample 200 contexts from S0
   replays, run both probe configs, emit probe result JSON (frozen
   manifest + histograms + timing percentiles + threshold verdict).
3. If feasible: `scripts/s0_seed_registry.py` extended with S1 segment;
   `scripts/s0_orchestrator.py` parameterized for the S1 lineup
   (candidate vs three opponents); `scripts/s1_final_audit.py`
   (S0-audit pattern + histogram consistency checks).
4. Tracked results: `benchmarks/s1-feasibility-probe-v1.result.json`
   (always) and `benchmarks/s1-search-horizon-validation-v1.result.json`
   (only if Phase B runs).

## Estimated cost

- Phase A: 200 contexts × 2 configs × ~1–2.5 s/decision (offline
  upper bound) ≈ 10–17 min serial; likely less live.
- Phase B (if run): 384 matches; the candidate's decisions at depth 2
  cost ~55–85× M07's S0-measured in-process p50 (12–14 ms) →
  ~0.7–1.2 s/decision ceiling; ~7.9k candidate decisions → ~2–3 h
  serial worst case, parallelizable ~4× → under 1 h expected.
  (S0's 67 s full run sets the efficiency precedent; the depth-2
  multiplier dominates.)

## Known limitations

- The probe corpus comes from S0 replays (heuristic/n1/M07 games);
  depth-2's own games may reach different state distributions — the
  80%/150 ms thresholds are feasibility screens, not guarantees.
- Offline ms/frame numbers include process startup and artifact
  writing; the 150 ms threshold is specified against in-process
  decide time (S0-style), measured live in the probe.
- Depth 2 keeps the same StaticEvaluatorV1; deeper horizon may AMPLIFY
  static-evaluation bias (a known risk, not a defect — the Arena is
  the accepted arbiter).
- The determinization information-set limitation persists at any depth.

## Next authorized gate

- Cloud review of this design (question, phases, thresholds, seed
  segment, telemetry schema addition, decision table).
- After APPROVE: Phase A probe → (if feasible) Phase B Arena →
  closure review. COMPUTE_INFEASIBLE stops the round by design.
