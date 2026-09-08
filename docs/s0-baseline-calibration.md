# S0 — Baseline Calibration (Heuristic / n1 / M07)

STATUS     = EXECUTED (design APPROVED/FROZEN at 825f042; single valid run
            executed 2026-09-08 with final audit ALL CHECKS PASS; result
            tracked; awaiting closure review)
RESULT     = heuristic-v1 is the unique primary reference (double resolved
            win under 98.33% joint-decision CIs); p3 n1-vs-M07 UNRESOLVED
            (unresolved at this budget — NOT equivalence); must-not-regress
            set = all three agents. No promotion claim; M07 champion title
            unchanged.
BASELINE   = 3c50692 (2026-09-08, post M48A closure)
OWNER-DATE = local implementation + cloud review, 2026-09-08

## Problem and evidence

### The research question this round answers

After the M48A terminal closure, the project mainline is re-anchored to
**playing strength at controllable local cost** (user ruling 2026-09-08).
The first unanswered upstream question is: **which of the existing agents
is the credible strength baseline to develop against?** All subsequent
development decisions (S1 search-horizon work, S2 targeted candidates)
need a reference opponent and a "must-not-regress" set. Today that set is
assumed, not measured.

Three agents matter:

| Agent | Definition | Cost per decision (M42S offline) |
|---|---|---|
| `heuristic-v1` | `splendor agent-heuristic --seed 20260812` — pure integer hand-coded scoring, no search, no state cloning | ~0 ms (in-process scoring) |
| `n1` (`det-s4-d1-n1`) | Root determinization, sample_seed 20_260_703, 4 samples, depth 1, max_nodes 1 — forced-root one-step successor evaluator | p50 62 ms (CLI analysis) |
| `M07` (`det-s4-d1-n2000`) | Same pipeline, max_nodes 2000 — frozen search champion | p50 102 ms (CLI analysis) |

### Existing evidence inventory (what we already have)

All three historical sources measured `heuristic-v1` vs the M07 family.
Engine/agent/search core code is **unchanged** between the M07 tag
(`ab573d7`) and current HEAD (verified: only additive test/accessor diffs
in `heuristic.rs`/`evaluation.rs`; `state.rs`, `search.rs`, `catalog` core
untouched), so these results transfer to current HEAD **at the code
level**. However, the participating configurations are NOT identical to
S0's (see "Config comparability" below), so these results are a strong
prior on heuristic beating this family of M07 configurations — not a
settled direction for the exact S0 lineup.

| Source | Matchup | Result | Seeds | Verdict status |
|---|---|---|---|---|
| **M09 formal** (`8ae796e`, 2026-08-11, 64 matches) | M07 (`det-s4-d1-n2000-v1`) vs `heuristic-v1` | **Heuristic 49–15** (2343.8 bps, M07 perspective; gate-reported CI [177, 4509] on the candidate side) | 900000..900031 × 2 rotations | Completed formal run, gate-checked (decision: reject candidate) |
| **M19 championship** (`1841413`, 42 matches) | `heuristic-v1` vs `m07-champion` | Heuristic 2–0 | 190000 × 2 rotations | Provisional (1 seed/pair) |
| **M22 league** (`8ae796e` era, 48 matches) | `heuristic-v1` vs `m07-champion` | Heuristic 6–2 | 220100..220103 × 2 rotations | 4 seeds/pair |
| **M42S** (2026-09-05, 1,152 matches) | n50/n200/n500/n2000 each vs `n1` | n2000 5703.1 bps [4843.8, 6562.5] vs n1 — **UNRESOLVED** (CI crosses 5000) | 5_300_000..5_300_063 × 2 | Formal, paired-block bootstrap |

### Config comparability (review finding 1)

The historical lineups differ from S0's in agent seeds:

| Config | M09 / M22 | M42S / S0 |
|---|---|---|
| determinization sample seed | `20260810` | `20260703` |
| heuristic seed | `101` (M09) / `20260812` (M22) | `20260812` (S0) |

These are different sampled-determinization streams and different
heuristic tie-break streams. "Core code unchanged" does not make the
participants identical: the historical results establish that heuristic
beat *that* M07 configuration, which is a strong prior — not proof of the
S0 lineup's direction. Additionally, M09's promotion report already
carried confidence bounds (lower 177 / upper 4509 bps at 95%, one-sided
lower-bound gate); it is not a statistically unquantified result, and
this round does not claim otherwise.

Key facts from the inventory:

1. **Heuristic vs the M07 family has a strong, consistent prior.** Three
   independent seed sets and two determinization-sample-seed values
   (20260810 everywhere; heuristic seeds 101/20260812) all show heuristic
   winning: combined 57–17, M09's gate CI excluding parity on the lower
   side. S0 re-measures under the current unified config (20260703)
   rather than assuming the direction.
2. **n1 vs M07 is genuinely UNRESOLVED.** M42S's 128-match pairing
   (5703.1 bps, CI crossing 5000) cannot separate them. This is the one
   matchup where new evidence changes a decision: if the relationship
   stays unresolved, S1 inherits an explicitly unresolved baseline
   question rather than a cheap-by-equivalence claim.
3. **n1 vs heuristic has never been measured.** No historical source
   pairs them.
4. **Historical caveats:** M19 used 1 seed/pair (provisional by design);
   M22 used 4 seeds/pair; M09 is the only 64-match formal gate-checked
   comparison, and its config differs from S0's as above.

### Why a fresh calibration is still warranted

- Unify the lineup under the current frozen M07-family config
  (sample_seed 20260703 — the M42S/M07-champion value) so the result
  describes the exact configuration S1 will inherit.
- Fill the never-measured n1 vs heuristic pairing.
- Measure actual per-decision cost (the historical runs recorded
  configured budgets, not measured cost).
- S1 (deeper horizon) needs a fixed baseline identity and fresh seeds
  disjoint from everything S1 will later use.

## Initial design

### Goal

Produce a frozen, bootstrapped, seat-rotated calibration of the three
pairings among {`heuristic-v1`, `det-s4-d1-n1`, `det-s4-d1-n2000`} on
fresh seeds, with per-decision cost observations, sufficient to name:

- the **development reference** (strongest measured agent),
- the **must-not-regress opponent set** for S1/S2.

Non-goals: no promotion claim, no M07 champion-title change, no new
agents, no evaluator/search changes, no neural anything.

### Matchup schedule

| Pairing | A | B | Prior evidence |
|---|---|---|---|
| P1 | `heuristic-v1` | `det-s4-d1-n1` | none (new) |
| P2 | `heuristic-v1` | `det-s4-d1-n2000` (M07) | M09 49–15 heuristic; M19 2–0; M22 6–2 (direction known, modern protocol never applied) |
| P3 | `det-s4-d1-n1` | `det-s4-d1-n2000` (M07) | M42S 5703.1 [4843.8, 6562.5] UNRESOLVED |

- **Seeds**: fresh segment `5_800_064 .. 5_800_127` (64 seeds; starts
  after M45A's 5_800_000..5_800_063 which is the most recent consumed
  arena segment — disjointness from all prior namespaces asserted by
  script before launch).
- **Rotations**: 2 per seed (A as seat 0 / seat 1) → 128 matches per
  pairing, 384 total.
- Agent configs (frozen, verbatim):
  - `heuristic-v1`: `splendor agent-heuristic --seed 20260812`
  - `det-s4-d1-n1`: `splendor agent-determinization --sample-seed
    20260703 --sample-count 4 --max-depth-turns 1 --max-nodes 1`
    (20260703 ≡ 20_260_703, the frozen M07-family sample seed)
  - `det-s4-d1-n2000`: same with `--max-nodes 2000`.

### Statistical protocol (frozen before any result is seen)

- Statistical unit: paired seed block (2 rotations averaged).
- Bootstrap: deterministic paired-block bootstrap, 10,000 resamples,
  seed `42_280_001` (fresh, disjoint from M42S's 42_270_001).
- Report: center bps + two-sided 95% CI **and** two-sided 98.33% CI per
  pairing (same bootstrap resamples; two percentile cuts).
- Decision rule (per pairing, uses the 98.33% CI — see multiplicity
  note):
  - `STRONGER_A` if the 98.33% CI lies entirely above 5000 bps,
  - `STRONGER_B` if entirely below,
  - `UNRESOLVED` if it crosses 5000.
  The 95% CI is reported for description only and never feeds a joint
  decision.
- No sequential extension: 64 seed blocks is the whole budget; an
  `UNRESOLVED` verdict stays `UNRESOLVED` (no "keep playing until
  significant"). Rationale: the user's instruction that UNRESOLVED is a
  legitimate standing outcome, plus the prior expectation that P3 may
  remain unresolved at this budget (M42S at the same n did).
- Multiplicity note: with three comparisons, Bonferroni gives family-wise
  coverage of at least 85% for three nominal 95% intervals. Therefore
  joint S0 decisions use 98.33% per-pairing intervals, yielding
  family-wise coverage of at least 95%. This adds no matches; it only
  widens the decision CI.

### Cost observation (the new measurement layer)

ArenaReportV1 is frozen (evaluation.md:254 — no per-move telemetry, and
changing it in place is forbidden). Therefore:

- **Sidecar observation file, per match**, written by a small runner-side
  sampler OUTSIDE the frozen report: one JSON per match under
  `local-artifacts/s0-baseline-calibration/observations/`, bound to run
  identity by (game_id, replay_final_hash).
- Measured per decision (both seats):
  - `wall_ms` — end-to-end request→action latency measured by the
    arena-side observer around `wait_for_action` (already has
    `move_deadline` instrumentation points),
  - agent-reported search counters where the agent already computes them:
    `RootDeterminizationStatsV1` (continuation_searches, nodes_visited,
    nodes_expanded, leaf_evaluations, terminal_children, …) — surfaced by
    a new default-off `--stats-out <path>` flag on `agent-determinization`
    that appends one `PerDecisionStatsV1` JSON line per decision
    (game_id, request_id, decide_micros, stats) to an agent-owned NDJSON
    file. NO protocol change and NO arena change: the arena's bounded
    stderr tail stays untouched (implementation note: stderr-forwarding
    was considered first, but the arena drains agent stderr into a
    bounded 64 KiB tail that never reaches the parent, so a dedicated
    stats file is the only sidecar channel that survives long matches).
  - `completed_depth_turns` per continuation is NOT currently aggregated
    into `RootDeterminizationStatsV1`, and **budget-exhaustion fallback
    inside a continuation search is a different event from
    `terminal_children`** (which counts sampled root children that are
    already game-over after the root action — checked against
    `crates/splendor-imperfect-search/src/search.rs`). Therefore this
    round records:
    - `terminal_child_ratio` = terminal_children /
      (continuation_searches + terminal_children), **named and
      interpreted strictly as "fraction of sampled root children already
      terminal"** — NOT as a search-fallback/degradation indicator;
    - `budget_consumption` = nodes_visited /
      (continuation_searches × max_nodes) as a descriptive utilization
      ratio.
    Achieved depth and true budget-fallback rates are **explicitly not
    observed this round** (they would need per-continuation
    stop_reason/completed_depth aggregation — a model-schema extension);
    S1 decides whether to add them.
- Sampling plan: full observation for ALL decisions in all 384 matches
  (heuristic decisions are ~0-cost to observe; determinization stats
  lines are already computed internally).
- Aggregation (report-time, not agent-time): per agent per pairing —
  mean/p50/p90/p95 of `wall_ms`, totals and ratios of search counters,
  and `terminal_child_ratio` (terminal-children share, named as above —
  not a fallback/degradation metric).
- Observation files are local-only artifacts (ignored); a compact cost
  summary (per-agent percentiles) is bound into the tracked result JSON.

### Frozen telemetry boundary (review-ratified)

```text
S0 telemetry allowed:
  wall_ms
  existing RootDeterminizationStatsV1 counters
  terminal_child_ratio (named as terminal-root-children share)
  descriptive node-budget consumption

S0 telemetry NOT allowed:
  new search stats schema
  completed_depth implementation
  stop_reason implementation
  budget-exhaustion instrumentation
  search algorithm changes
```

This boundary exists so S0 does not build half of S1 by inertia.

### P0 semantic gates (must pass before any match counts)

1. Seed-segment disjointness: `5_800_064..5_800_127` ∩ every previously
   consumed arena seed segment = ∅ (script asserts against a registry of
   prior segments listed in the result JSON).
2. M07 identity: `det-s4-d1-n2000` reproduces frozen M07 benchmark
   decisions bit-exact (reuse the M42S H3 fixture).
3. Lineup/rotation verification: every match's `agent_ids_by_seat` and
   rotation match the plan (exhaustive, as M42S).
4. Replay verification: all 384 replays pass `verify_replay`.
5. Observation binding: every observation record's (game_id,
   replay_final_hash) matches its match report; counts of stats lines ==
   decisions made by determinization seats.
6. Stats-flag isolation: the SAME match run with and without
   `--stats-out` produces a bit-identical `replay_final_hash` (verified
   on the smoke match; the flag only appends sidecar lines).

### Estimated cost

- 384 matches × ~62 plies mean ≈ **23.8k total decisions** (both seats
  combined). Per seat ≈ 31 decisions per match, and each of the three
  pairings has 128 matches, so each participating agent identity plays
  ≈ 128 × 31 ≈ **3,968 decisions**:

  | Agent | Pairings | Decisions |
  |---|---|---|
  | heuristic | P1, P2 | ≈ 7.9k |
  | n1 | P1, P3 | ≈ 7.9k |
  | n2000 (M07) | P2, P3 | ≈ 7.9k |

  Total search-agent decisions ≈ **15.9k**; heuristic ≈ 7.9k at ~0
  cost. (Review correction: the earlier draft mislabeled the seat
  composition — P3 is n1 vs n2000 with no heuristic seat — and
  under-counted search decisions.)
- Wall-time estimate: ~7.9k decisions each at CLI-measured ~62 ms (n1)
  and ~102 ms (n2000) upper bounds → ~35 min serial upper bound, likely
  less live (CLI numbers include process startup). **30–60 minutes
  stands as a rough provisional budget, not a measured conclusion.**
- Observation overhead: one stats line per search decision
  (~250 bytes × ~15.9k ≈ 4 MB total) written to agent-owned sidecar
  files; the arena's bounded stderr tail remains for fault diagnosis
  only and is never a telemetry channel.

## Scope and non-goals

- No promotion, no champion change, no evaluator/search modification.
- No new agents beyond the stats-emission flag (which must not alter
  decisions).
- No sequential testing, no early stopping, no post-hoc seed extension.
- No S1 execution in this round (deeper-horizon feasibility is a
  separate authorized work package).
- Neural evaluator research remains STOPPED (M48A terminal ruling).

## Contracts and invariants

- The three agent binaries' decision behavior must be bit-identical to
  their historical selves (P0 gates 2/6).
- Frozen report format: ArenaReportV1 untouched; observations live in
  sidecar files; the tracked result JSON is a new S0 schema.
- Fail-closed: seed registry mismatch, lineup mismatch, replay
  verification failure, observation binding failure, or any abort ⇒ the
  round is VOID (not partial).
- UNRESOLVED is a legitimate standing verdict (no re-rolls).

## Implementation plan

1. `scripts/s0_seed_registry.py` — registry of all prior consumed arena
   seed segments (M09 900000.., M19 190000, M22 220100..103, M13/M10/M11
   segments, M24 series, M35A, M42S 5_300_000.., M44C 5_700_000..,
   M45A 5_800_000..5_800_063); disjointness assert.
2. Rust: add `--stats-out <path>` flag to `agent-determinization`
   (`StatsEmittingPolicy` wrapping `DeterminizationAgentPolicyV1`;
   per-decision PerDecisionStatsV1 = game_id, request_id,
   in-process decide_micros, RootDeterminizationStatsV1); P0 gate 6
   proves decision-identity via replay_final_hash equality.
3. Orchestrator-side observation assembly: per-match sidecar JSON
   combining (a) the agents' `--stats-out` NDJSON lines and (b)
   match-level wall time from the orchestrator's own subprocess timing;
   bound to the match by (game_id, replay_final_hash). Per-request
   arena-side wall_ms timing would need runner changes, so the frozen
   decision-time metric this round is the AGENT-MEASURED decide_micros
   (in-process, excludes transport overhead) plus per-match wall —
   stated as such in the result.
4. `scripts/s0_orchestrator.py` — plan generation, 384-match execution,
   bootstrap, tracked result JSON
   (`benchmarks/s0-baseline-calibration-v1.result.json`).
5. `scripts/s0_final_audit.py` — fail-closed recheck of all P0 gates +
   result recomputation from raw replay/observation files.


## Validation and evidence

### Execution — 2026-09-08 (single valid run)

- P0 pre-run gates:
  1. Seed disjointness PASS (`scripts/s0_seed_registry.py`: 64 S0 seeds
     vs 3,124 consumed seeds across 20 registered ranges).
  2. M07 identity PASS (frozen 12-position benchmark bit-exact,
     `m07_determinization_benchmark_is_reproducible` release run).
  6. Stats-flag decision-identity PASS (same match with/without
     `--stats-out` → identical `replay_final_hash`
     `eb8b9bc4…`; plus a Rust unit test locking parity and the telemetry
     shape).
- 384/384 matches completed, 0 aborts. Total wall 67 s (far under the
  provisional 30–60 min — live in-process search is much cheaper than
  the CLI-analysis numbers suggested).
- Final audit (`scripts/s0_final_audit.py`) ALL CHECKS PASS: exhaustive
  lineup/rotation verification from match configs, 384/384 replays
  verified via `splendor verify-replay --input`, observation binding
  (stats rows == replay-counted decisions per search seat, game_id
  match, monotone request_ids), full recomputation of W/T/L, block
  scores, center bps, both CI levels, verdicts, and the decision block.

### Results (frozen contract)

| Pairing | W-T-L (primary) | Center bps | 95% CI (desc.) | 98.33% CI (decision) | Verdict |
|---|---|---:|---|---|---|
| P1 heuristic vs n1 | 85-0-43 | 6640.6 | [5859.4, 7421.9] | [5625.0, 7656.2] | **STRONGER_A (heuristic)** |
| P2 heuristic vs M07 | 88-0-40 | 6875.0 | [5937.5, 7734.4] | [5781.2, 7890.6] | **STRONGER_A (heuristic)** |
| P3 n1 vs M07 | 68-1-59 | 5351.6 | [4492.2, 6210.9] | [4296.9, 6445.3] | **UNRESOLVED** |

Decision block (98.33% verdicts): heuristic beats both other agents →
**unique primary reference = `heuristic-v1`**. P3 stays UNRESOLVED: at
this budget the 2000-node continuation search is not separable from the
1-node static-successor baseline (consistent with M42S). This is
"unresolved at this budget", NOT equivalence. Must-not-regress set =
{heuristic, n1, M07} (all three; the frozen conservative rule).

Consistency with prior evidence: P2's direction (heuristic over M07)
matches the 20260810-seeded M09/M19/M22 priors (57–17) — the reversal
case did not materialize, and no anomaly handling was needed. P3's
UNRESOLVED matches M42S.

### Measured cost (agent-side, in-process decide_micros; excludes transport)

| Agent | Decisions | p50 | p95 | terminal_child_ratio | budget consumption (desc.) |
|---|---:|---:|---:|---:|---:|
| n1 (P1) | 3,722 | 1.49 ms | 2.66 ms | 0.0113 | 1.000 (budget 1 always exhausted) |
| M07/n2000 (P2) | 3,851 | 14.4 ms | 43.0 ms | 0.0122 | 0.0157 |
| n1 (P3) | 3,963 | 1.66 ms | 5.51 ms | 0.0067 | 1.000 |
| M07/n2000 (P3) | 3,962 | 12.2 ms | 78.1 ms | 0.0092 | 0.0144 |

Heuristic decisions: ~0 by construction (no stats lines; sampler
verified absent). Reading notes: M07's mean decide time is ~8–9× n1's;
its p95 tail reaches 78 ms in P3. n1's budget consumption = 1.0 exactly
(max_nodes=1 exhausted by design — this is the expected degenerate
value, not a finding). terminal_child_ratio is the terminal-root-children
share (naming per the frozen boundary — NOT a fallback indicator).
These are live in-process numbers on the local machine under normal
load; descriptive, not controlled benchmarks.

### Tracked artifacts

- `benchmarks/s0-baseline-calibration-v1.result.json` (git-blob SHA256
  recorded after commit; working-tree hash differs by CRLF).
- Raw per-match artifacts (configs, reports, replays, stats sidecars)
  under ignored `local-artifacts/s0-baseline-calibration/`.

## Result and decision (final)
## Result and decision table (frozen)

### Verdict rule (per pairing, same validity standard for every outcome)

All three pairings pass through the same P0 validity gates regardless of
whether the outcome matches or contradicts historical priors. A
contradiction adds **diagnostic work** (config/lineup/seed/replay
re-verification, which the final audit performs anyway) but does NOT
place the result under a different acceptance standard: if no concrete
error is found, a contradicting result stands as a valid reversal. In
particular, a P2 reversal (M07 over heuristic) would be reported as a
valid finding of this round — noteworthy against the 20260810-seeded
priors, and explicitly hypothesized as possibly config-sensitive
(sample-seed difference) rather than dismissed.

### Verdict vocabulary

- `STRONGER_X` (X = A or B): 98.33% joint-decision CI entirely on one
  side of 5000 bps (see multiplicity note below).
- `UNRESOLVED`: the CI crosses 5000. UNRESOLVED means *evidence
  insufficient to separate* — it does NOT mean "equivalent", and no
  equivalence/equality margin is pre-registered in this round. Choosing a
  cheaper agent over an UNRESOLVED-but-expensive one is a **cost choice
  with an explicitly unresolved strength gap**, and must be recorded as
  such wherever used.

### Multiplicity note

Three per-pairing 95% two-sided CIs do not support a joint "unique
strongest" claim without correction. The frozen rule: **joint decisions
(naming the reference, demotions, "beats both others") use per-pairing
98.33% CIs** (Bonferroni for 3 comparisons; same 384 matches, no extra
games), while the 95% CIs are reported for description only.

### Decision table

The table keys on the 98.33%-CI verdicts:

| Pattern | Decision |
|---|---|
| One agent is `STRONGER` in both of its pairings | That agent is the **primary reference**. The other two remain must-not-regress opponents if their pairings are `STRONGER`-resolved against them or UNRESOLVED (see below). |
| No agent beats both others (e.g. one UNRESOLVED pairing, or a cycle A>B, B>C, C>A) | **No unique reference is named.** Keep the full opponent set {heuristic, n1, M07} as anchors; S1 candidates must face all of them. A cheap agent may be chosen as the *development* baseline for cost reasons, recorded as a cost choice with the strength gap explicitly unresolved. |
| A pairing is `UNRESOLVED` | Both members stay in the must-not-regress set; no demotion of either. "n1 ≈ M07"-style equivalence claims are FORBIDDEN wording — only "unresolved at this budget" is licensed. |

Cost summary (all rows): the per-agent `wall_ms` percentiles and search
counter ratios become the standing cost table for S1's "acceptable cost"
judgment. Cost data never overrides a strength verdict; it selects among
strength-undifferentiated options.

**No outcome in this table changes the M07 champion title** (historical
promotion record) — it changes the *development reference* going forward.

## Known limitations

- 64 seed blocks may leave P3 UNRESOLVED (M42S at same n did); that is
  an accepted outcome, not a failure.
- Live wall_ms depends on machine load; the round records environment
  (CPU, load average at start/end) and the numbers are descriptive, not
  controlled benchmarks. The GPU is not involved (no neural agents).
- Heuristic's cost is ~0 by construction; its observation value is the
  control stream proving the sampler works.
- The M09-era result (49–15 under sample-seed 20260810) is strong prior
  evidence for P2's direction under that config; this round measures the
  unified 20260703 config fresh and reports whatever it shows, including
  a reversal, under the same validity standard.

## Next authorized gate

- Cloud review of this design (matchups, seed segment, budget,
  statistical rule, observation scheme, decision table).
- After APPROVE: implementation per plan (stats flag → P0 gates → 384
  matches → result JSON → final audit), then S0 closure review.
- S1 (search-horizon validation) design is drafted ONLY after S0's
  reference-opponent question is answered.
