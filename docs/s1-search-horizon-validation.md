# S1 — Search-Horizon Validation (depth-2 vs the calibrated field)

STATUS     = APPROVED AS A VALID COMPUTE-FEASIBILITY NEGATIVE /
            COMPLETED_DIAGNOSTIC / CLOSED (final review 2026-09-08 on
            caa85cc: Phase A VALID; verdict COMPUTE_INFEASIBLE; Phase B
            correctly cancelled by frozen contract; P0:0 / P1:0 / P2:4
            non-blocking wording repairs applied docs-only; no repair
            run, no extra probe, no Arena; heuristic-v1 primary reference
            unchanged; M07 historical champion unchanged; promotion NONE)
RESULT     = COMPUTE_INFEASIBLE — a COST-TAIL failure, not an inability
            to reach depth 2 (n2000 completed 82.3%, n10000 98.6% of
            continuations; p95 decision times 2.24 s / 4.16 s vs the
            2.0 s cap; medians ~0.39 s). Depth-2 strength vs heuristic
            remains COMPLETELY UNTESTED (Phase B never ran).
REVISION   = V2 2026-09-08 (frozen, 1f557e0) — review repairs per
            DESIGN_V1 review; executed as frozen; closed at caa85cc.
            V1 = 76d8993.
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
   (StaticEvaluatorV1), same determinization sampling (sample_seed
   20260703, sample_count 4), no action pruning changes, no other
   search modifications. What changes: continuation `max_depth_turns`
   1 -> 2, plus the node budget selected by Phase A.

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

1. **Depth-2 exploratory WALL cost is ~55–85x depth 1; aggregate node
   work is ~34–52x** (6.38M/0.19M = 33.6x, 9.82M/0.19M = 51.7x). Wall
   and node multipliers are different quantities, reported separately.
2. On this one exploratory replay, aggregate node work from n10000 to
   n50000 grows by only ~0.08% — strong evidence that n10000 is near
   THIS replay's depth-2 work saturation, which motivates n10000 as the
   high probe budget. It does NOT establish that most continuations
   complete under 10,000 nodes; the completion fraction remains unknown
   until Phase A measures it.

## Initial design

### Phase A — Feasibility probe (no Arena, no promotion claims)

**Goal**: measure whether depth-2 search actually completes at an
acceptable cost on REAL game positions, before spending any Arena
budget.

- **Corpus (frozen definition)**: 200 decision contexts drawn from ALL
  S0 verified replays (the local, ignored artifacts — fresh real games
  on seeds 5_800_064..127, never used for any strength claim involving
  depth-2):
  - eligible context: `Phase::Main`, `legal_actions >= 2`,
    non-terminal (sub-phase and forced-single-action contexts are
    excluded so the completion rate is not inflated by trivial
    decisions; the Arena still plays every phase);
  - identity: `(observation_hash, visible_history_hash,
    information_set_hash)`;
  - dedupe: exact identity triple;
  - selection: sort by `SHA256("43_000_001" || identity)` ascending,
    take the first 200;
  - the full 200-identity manifest is frozen in the probe result.
- **Probe configs**: `det-s4-d2-n2000` and `det-s4-d2-n10000`
  (sample_seed 20260703, sample_count 4, depth 2).
- **Depth telemetry (approved; frozen boundary)**: a NEW optional
  `depth_diagnostics` object in the per-decision sidecar, emitted only
  when a new `--emit-depth-histogram` flag is present (and only
  together with `--stats-out`):

  ```
  depth_diagnostics:
    continuation_depth_histogram: {0, 1, 2}
    continuation_stop_reasons: {depth_limit_reached, node_budget_reached}
  ```

  Implementation: the determinization aggregation loop already receives
  every `search_maxn_v1` result and currently discards
  `completed_depth_turns`/`stop_reason` after reading utility and
  stats; the diagnostics variant accumulates them into an S1-only
  collector struct. **Nothing frozen is modified**:
  `SearchResultV1`, `RootDeterminizationResultV1` serialization, and
  `RootDeterminizationStatsV1` fields are untouched; the existing
  aggregation function's behavior is unchanged (the diagnostics variant
  is additive).
- **Hard completion definition**: a non-terminal continuation counts as
  completed depth 2 iff `completed_depth_turns == 2 AND stop_reason ==
  DepthLimitReached`. `stop_reason == NodeBudgetReached` is NOT
  completed, regardless of the completed-depth value. A telemetry
  consistency assertion (`completed_depth_turns == 2` iff
  `stop_reason == DepthLimitReached` under this contract) must hold for
  every continuation; any inconsistency is an audit FAIL.
- **Frozen feasibility thresholds** (decided before seeing results):
  - A depth-2 config is **feasible** iff on the probe corpus:
    (a) **completion gate**: >= 80% of non-terminal continuations
    complete depth 2 per the hard definition. A passing candidate is
    fairly described as "a depth-2-enabled search with at least 80%
    continuation completion" — NOT "every action searched to depth 2";
    (b) **cost gate**: p95 in-process decide time <= **2.0 s** (an
    engineering cap meaning "still worth one confirmation Arena at
    local cost", NOT a strength threshold: it sits far below the 60 s
    move timeout, contains the exploratory ~1 s/decision estimate, and
    blocks configurations drifting into multi-second-to-tens-of-seconds
    tails). Reported alongside: mean, p50, p90, p95, max — only p95 is
    a hard gate.
  - If BOTH n2000 and n10000 are feasible, the CHEAPER one (n2000)
    goes to Arena.
  - If only n10000 is feasible, n10000 goes to Arena.
  - If NEITHER is feasible: **return COMPUTE_INFEASIBLE — S1 stops**.
    This means the current search implementation does not deliver
    depth-2 within the preregistered completion/cost gates; it does NOT
    mean depth-2 is inherently infeasible. Whether to invest in search
    engineering (transposition reuse across continuations, etc.) is a
    separate user decision, NOT an automatic continuation of this
    round.

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
- Candidate decisions: the candidate plays all three pairings, so its
  decision count is ~3 x 128 x ~31 = **~11.9k** (not 7.9k — V1
  arithmetic error), at the Phase-A-measured per-decision cost.
- **Cost observation**: same S0 telemetry (decide_micros + counters +
  depth histogram via the new flag) on the candidate's seats only;
  opponents run without stats (heuristic) or with S0-level stats
  (n1/M07) as in S0.

### Decision table (frozen; 98.33% joint-decision CIs)

The primary reference changes ONLY on a **resolved beats-ALL-THREE**
outcome: the candidate must be RESOLVED stronger than heuristic AND
RESOLVED stronger than n1 AND RESOLVED stronger than M07. UNRESOLVED is
never a tie, and transitivity is never assumed (a 4-agent field can be
non-transitive; D2 > heuristic and heuristic > n1 do NOT imply D2 > n1).

| Outcome pattern | Strategy state | Reference change |
|---|---|---|
| Resolved win vs all three | **NEW_PRIMARY_REFERENCE** | YES — candidate becomes the development reference (promotion/champion title remains a separate formal process) |
| Resolved win vs heuristic, no resolved loss, >= 1 UNRESOLVED vs n1/M07 | **AMBIGUOUS_TOP_FIELD** | NO |
| Resolved win vs heuristic, resolved loss vs n1 or M07 | **NONTRANSITIVE_SPLIT_FIELD** | NO — report the split; S2 investigates the losing matchup |
| UNRESOLVED vs heuristic (regardless of others) | **HORIZON_GAIN_UNRESOLVED** | NO — unresolved at this budget; extra seeds are a user decision, never automatic |
| Resolved loss vs heuristic | **HORIZON_NOT_COMPETITIVE** | NO — valid negative result, sealed; S2 pivots to error attribution on heuristic's losses |

| Phase A outcome | Strategy state |
|---|---|
| Both/one config feasible | Phase B runs with the selected config |
| Neither config feasible | **COMPUTE_INFEASIBLE** — S1 stops |

Cost data never overrides strength verdicts (S0 rule).

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
- Phase B (if run): the candidate plays all three pairings, so its
  decision count is ~11.9k (3 × 128 × ~31), at the Phase-A-measured
  cost. At the exploratory ~0.7–1.2 s/decision, candidate compute
  alone is ~2.3–4.0 h serial; opponent seats add their S0-measured
  costs (~4k decisions each for heuristic/n1/M07 across the pairings
  they appear in). With 4 workers the whole 384-match Arena remains
  roughly an hour-scale local job. (V1 understated the candidate
  decision count as 7.9k — corrected.)

## Validation and evidence

### Phase A execution — 2026-09-08 (single valid run)

- Depth-diagnostics implementation (4bf3e42): `ContinuationDepthDiagnosticsV1`
  (additive; frozen schemas untouched); parity + consistency locked by a
  Rust regression test and a live flag-on/off match smoke (identical
  `replay_final_hash`); workspace 772 tests 0 fail.
- Corpus: 22,026 unique eligible contexts extracted from all 384 S0
  verified replays (Phase::Main, >=2 legal actions, non-terminal,
  identity-triple dedupe); 200 selected by SHA256(43_000_001 || identity)
  ascending; full manifest in the tracked result.
- Probe: `splendor s1-probe` (live fixed-seed policy on rebuilt verified
  contexts — identical decision path to the arena agent, in-process
  timing). 200 decisions x 2 configs; every telemetry row carries
  depth_diagnostics; all consistency assertions passed (histogram totals
  == stop totals == continuation counts; top-depth bin ==
  DepthLimitReached count).

### Results (frozen gates: completion >= 80%, p95 <= 2.0 s)

| Config | Completion | p50 | p95 | Max | Verdict |
|---|---:|---:|---:|---:|---|
| d2-n2000 | 17,291/21,000 = **0.8234** | 0.39 s | **2.24 s** | 28.2 s | completion PASS, cost **FAIL** |
| d2-n10000 | 20,704/21,000 = **0.9859** | 0.39 s | **4.16 s** | 132.0 s | completion PASS, cost **FAIL** |

Neither config is feasible => per the frozen selection rule:
**COMPUTE_INFEASIBLE — Phase B did not run — S1 stops.**

Tail anatomy (post-hoc descriptive association, no gate, no causal
claim): n2000 has 13/200 and n10000 has 19/200 decisions above 2.0 s,
with maxima 28 s and 132 s. The slow-tail observations are concentrated
among wide-action Main-phase contexts (legal_actions up to 187 in the
manifest) — an observed association, not a proven sole cause (child
branching, subtree shape, TT hit rate, and determinization complexity
also vary across contexts). Medians are ~0.39 s for both configs: the
failure is a heterogeneous heavy tail, not uniformly slow decisions.
Increasing the per-continuation node budget from 2k to 10k substantially
increased completion on this corpus (82.3% -> 98.6%) but also worsened
the observed decision-time tail (p95 2.24 -> 4.16 s) — an observation
about this budget comparison, not a proven structural law. Future
search-engineering direction (NOT authorized by this round; a user
decision): the median/tail split suggests tail-control (worst-case
work) matters more than uniform speedup.

### Tracked artifacts

- `benchmarks/s1-feasibility-probe-v1.result.json` (git-blob SHA256,
  LF form, execution commit `771a4c5`:
  `8ab9b53e61f043a606b5adb84b22093700d609b4598dfe1a36f3eb1792055964`).
- Raw probe telemetry under ignored
  `local-artifacts/s1-feasibility/` (per-context analysis traces +
  probe NDJSON sidecars).

## Interpretation boundaries (frozen wording)

What a Phase B loss to heuristic licenses:

> The tested depth-2-enabled continuation search (StaticEvaluatorV1,
> s4 determinization, depth 2, Phase-A-selected budget, current MaxN)
> did not beat the calibrated heuristic reference.

It does NOT license "deeper search has no value" — only this contract
was tested.

What COMPUTE_INFEASIBLE licenses:

> Under the current search implementation, depth-2 did not meet the
> preregistered completion/cost gates.

It does NOT license "depth-2 is inherently infeasible to implement
efficiently".

## Known limitations

- The probe corpus comes from S0 replays (heuristic/n1/M07 games);
  depth-2's own games may reach different state distributions — the
  80% completion and 2.0 s p95 thresholds are feasibility screens, not
  guarantees.
- Offline ms/frame numbers include process startup and artifact
  writing; the 2.0 s p95 gate is specified against in-process decide
  time (S0-style), measured live in the probe.
- Depth 2 keeps the same StaticEvaluatorV1; deeper horizon may AMPLIFY
  static-evaluation bias (a known risk, not a defect — the Arena is
  the accepted arbiter).
- The determinization information-set limitation persists at any depth.

## Preregistration precision lessons (recorded for future gates)

1. **Selector byte encoding**: DESIGN_V2 froze `SHA256(seed || identity)`
   abstractly; the executed script used
   `SHA256(utf8("43_000_001|<obs_hash>|<history_hash>|<info_hash>"))`.
   The executed encoding was deterministic, fixed in the committed
   script before the run, and the full 200-identity manifest is in the
   tracked result — so this is NOT a protocol violation — but future
   designs must freeze the exact byte serialization whenever a selector
   feeds a hard gate.
2. **Quantile convention**: the p95 gate did not preregister a quantile
   interpolation method; the script used nearest-index
   (`round(q*(n-1))`). Immaterial to this verdict (13 and 19 of 200
   decisions exceed 2.0 s; no common convention moves either p95 under
   the cap), but future cost gates should preregister the convention.

## Cloud evidence boundary

As in S0: the frozen design, implementation, probe selector and
runner, 200-context manifest, aggregated histograms, summary timing,
and result hash are tracked and independently checkable from the cloud;
the 400 raw per-context telemetry rows and the S0 source replays are
local-only (ignored `local-artifacts/`), so the cloud cannot recompute
the percentiles from raw rows. The cloud review verified the script
logic, tracked aggregates, manifest, contract, and commit provenance
are mutually consistent.

## Canonical result sentences (closure wording)

Core result (permanent):

> On the frozen 200-context S1 feasibility corpus, both tested depth-2
> configurations met the >= 80% continuation-completion requirement, but
> neither met the preregistered <= 2.0 s p95 in-process decision-time
> cap. S1 therefore terminated as COMPUTE_INFEASIBLE before Arena, as
> required by the frozen contract.

More important detail (permanent):

> The failure was a cost-tail failure rather than an inability to reach
> depth 2: d2-n2000 completed 82.3% of continuations and d2-n10000
> 98.6%, while their p95 decision times were 2.24 s and 4.16 s
> respectively.

Forbidden wording: "deeper search is infeasible"; "deeper search has no
strength value" (Phase B never ran; depth-2 strength vs heuristic is
completely untested).

## Closure and next authorized gate

Executed path: (1) depth diagnostics + parity tests; (2) Phase A probe
(200 contexts, both configs) -> tracked feasibility result; (3) Phase A
FAILED the cost gate -> Phase B correctly NOT RUN per the frozen
contract; (4) closure review completed (basis caa85cc): APPROVED AS A
VALID COMPUTE-FEASIBILITY NEGATIVE / COMPLETED_DIAGNOSTIC / CLOSED.

Standing authorizations after closure (per the S1 final review):
- Search engineering: NOT AUTHORIZED (the candidate's strength value is
  unknown — optimizing it before any strength evidence repeats the old
  build-first-ask-later pattern).
- S2 implementation: NOT AUTHORIZED.
- **S2 error-attribution design (design-only): AUTHORIZED** — the next
  round studies why heuristic stably beats n1/M07: where they disagree,
  which disagreement classes predict heuristic's wins, and which
  heuristic terms drive those decisions, culminating in at most one
  S2-candidate hypothesis for review — no implementation.
- Still NOT authorized: depth 3+, search optimization, TT redesign,
  evaluator changes, sampling changes, pruning, extra seeds after
  UNRESOLVED, promotion/default-agent change, neural work.
