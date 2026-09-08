# S0 — Baseline Calibration (Heuristic / n1 / M07)

STATUS     = PROPOSED (design revision 2 for review; execution NOT authorized)
REVISION   = v2 2026-09-08 — review repairs: (1) config-comparability section
            (M09/M22 used sample-seed 20260810 + heuristic seed 101/20260812;
            historical results are a strong prior, not the S0 lineup's settled
            direction; M09 already carried gate CI bounds); (2) decision table
            rewritten — complete rule set, UNRESOLVED ≠ equivalence, cheap-baseline
            choice is a cost choice with unresolved gap; (3) contradiction
            handling unified (same validity gates, reversal stands if no error
            found); (4) terminal_child_ratio renamed and scoped (NOT a
            budget-fallback metric; achieved depth/fallback rate explicitly
            unobserved this round); (5) joint decisions use per-pairing 98.33%
            CIs (Bonferroni, same matches); (6) cost estimate de-double-counted
            (~8k search decisions, provisional).
BASELINE   = 3c50692 (2026-09-08, post M48A closure); design v1 commit bb881ca
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
- Multiplicity note: three pairwise comparisons without independence
  assumptions have family-wise error ≥ 1 − (0.95)^... — the Bonferroni
  bound for 3 comparisons at per-pairing 95% is ≥ 85% family-wise
  coverage (1 − 3×0.05 = 0.85 in the worst case), which is why joint
  decisions use per-pairing 98.33% CIs (1 − 3×0.0167 ≈ 0.95 family-wise
  in the union-bound sense). This adds no matches; it only widens the
  decision CI.

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
    nodes_expanded, leaf_evaluations) — surfaced via the agent's
    **stderr diagnostics channel** (bounded 64 KiB tail already captured
    by `splendor-arena/src/process.rs`), one NDJSON line per decision.
    This requires NO protocol change: stderr is already drained and
    retained; we extend the determinization agent to emit a per-decision
    stats line (additive, off by default, enabled by a new
    `--emit-per-decision-stats` flag so existing agents' behavior and
    identity are untouched).
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
6. Stats-flag isolation: agents launched WITHOUT the stats flag produce
   zero stderr stats lines and identical actions to the flagless
   baseline on a fixed 12-position smoke (actions must be bit-identical
   with flag on — the flag only adds stderr output).

### Estimated cost

- 384 matches × ~62 plies mean ≈ **23.8k total decisions** (both seats
  combined; a "decision" is one player action — counting each match's
  plies once, not per pairing set).
- Determinization decisions: each pairing has one determinization seat
  and one heuristic seat per match, so n1 seats ≈ 128 × ~31 ≈ 4.0k
  decisions (P1's n1 + P3's n1) and n2000 seats ≈ 128 × ~31 ≈ 4.0k (P2's
  M07 + P3's M07) — total ≈ **8k search-agent decisions**, plus ~15.8k
  heuristic decisions at ~0 cost. (Review correction: the earlier draft
  double-counted both seats per match.)
- Wall-time estimate: ~8k decisions at CLI-measured ~62 ms (n1) and
  ~102 ms (n2000) upper bounds → ~30–35 min serial upper bound, likely
  less live (CLI numbers include process startup); heuristic seats and
  observation I/O add little. **30–60 minutes stands as a provisional
  budget, not a measured conclusion.**
- Observation overhead: one stderr line per determinization decision
  (~200 bytes × ~8k ≈ 1.6 MB total). The existing bounded 64 KiB tail
  remains for fault diagnosis only; the observation sampler drains the
  full stderr stream incrementally into the per-match sidecar file, so
  the bound never truncates observations.

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
2. Rust: add `--emit-per-decision-stats` flag to
   `agent-determinization` (stderr NDJSON: per-decision
   RootDeterminizationStatsV1 + wall ms measured in-process); P0 gate 6
   proves decision-identity.
3. Arena-side observation sampler: wrap `wait_for_action` timing
   (runner-external driver script preferred; if runner changes are
   needed, they must be additive and behind a config default-off) and
   drain stderr to per-match sidecar JSON.
4. `scripts/s0_orchestrator.py` — plan generation, 384-match execution,
   bootstrap, tracked result JSON
   (`benchmarks/s0-baseline-calibration-v1.result.json`).
5. `scripts/s0_final_audit.py` — fail-closed recheck of all P0 gates +
   result recomputation from raw replay/observation files.

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
