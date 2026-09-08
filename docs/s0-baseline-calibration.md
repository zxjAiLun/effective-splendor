# S0 — Baseline Calibration (Heuristic / n1 / M07)

STATUS     = PROPOSED (design frozen for review; execution NOT authorized)
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
untouched), so these results transfer to current HEAD.

| Source | Matchup | Result | Seeds | Verdict status |
|---|---|---|---|---|
| **M09 formal** (`8ae796e`, 2026-08-11, 64 matches) | M07 (`det-s4-d1-n2000-v1`) vs `heuristic-v1` | **Heuristic 49–15** (2343.8 bps, M07 perspective) | 900000..900031 × 2 rotations | Completed formal run, gate-checked |
| **M19 championship** (`1841413`, 42 matches) | `heuristic-v1` vs `m07-champion` | Heuristic 2–0 | 190000 × 2 rotations | Provisional (1 seed/pair) |
| **M22 league** (`8ae796e` era, 48 matches) | `heuristic-v1` vs `m07-champion` | Heuristic 6–2 | 220100..220103 × 2 rotations | 4 seeds/pair |
| **M42S** (2026-09-05, 1,152 matches) | n50/n200/n500/n2000 each vs `n1` | n2000 5703.1 bps [4843.8, 6562.5] vs n1 — **UNRESOLVED** (CI crosses 5000) | 5_300_000..5_300_063 × 2 | Formal, bootstrap CI |

Key facts from the inventory:

1. **Heuristic vs M07 is NOT an open question at the direction level.**
   Three independent seed sets (900000-series, 190000, 220100-series) all
   show heuristic winning. Combined record 57–17 (M07 perspective
   2343.8 bps in the only formal gate-checked run). M07's 15/64 vs
   heuristic's 49/64 in M09 is far outside paired-block noise for that
   sample. The user's recollection that "Heuristic ranked first in M19 and
   M22" is confirmed, and the stronger M09 formal result (which the docs
   under-emphasize) points the same way.
2. **n1 vs M07 is genuinely UNRESOLVED.** M42S's 128-match pairing
   (5703.1 bps, CI crossing 5000) cannot separate them. This is the one
   matchup where new evidence changes a decision: if n1 ≈ M07, the
   champion's 2000-node continuation search adds no measured strength,
   and S1's "deeper horizon" question inherits a cheap baseline.
3. **n1 vs heuristic has never been measured.** No historical source
   pairs them.
4. **Historical caveats:** M19 used 1 seed/pair (provisional by design);
   M22 used 4 seeds/pair; M09 is the only 64-match formal gate-checked
   comparison. None of the three used the modern paired-block bootstrap
   protocol (M42S-era); M09 predates it.

### Why a fresh calibration is still warranted

- M09's heuristic-vs-M07 verdict is old enough (pre-M42S protocol) that
  the project's current standard for "resolved" (paired-block bootstrap
  CI) has never been applied to it.
- n1's status is unresolved, and n1 sits at ~60% of M07's measured cost —
  if n1 ≈ M07 in strength, the cost reference for S1 changes materially.
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
- Report: center bps + two-sided 95% CI per pairing.
- Decision rule (per pairing):
  - `STRONGER_A` if CI entirely above 5000 bps,
  - `STRONGER_B` if entirely below,
  - `UNRESOLVED` if CI crosses 5000.
- No sequential extension: 64 seed blocks is the whole budget; an
  `UNRESOLVED` verdict stays `UNRESOLVED` (no "keep playing until
  significant"). Rationale: the user's instruction that UNRESOLVED is a
  legitimate standing outcome, plus the prior expectation that P3 may
  remain unresolved at this budget (M42S at the same n did).
- Bonferroni note: with 3 pairings, a 95% two-sided CI per pairing gives
  a family-wise coverage ≥ ~85.7%; we report per-pairing CIs and do not
  claim joint confidence. This matches M42S practice (9 pairings, 95%).

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
    into `RootDeterminizationStatsV1`; the fallback-ratio observation
    instead uses `continuation_searches` vs `root_actions × samples`
    plus `nodes_visited / (continuation_searches × max_nodes)` budget
    consumption (both derivable from existing counters). A true
    per-continuation `stop_reason` histogram is deferred (would need
    model-schema extension; S1 can decide if it's needed).
- Sampling plan: full observation for ALL decisions in all 384 matches
  (heuristic decisions are ~0-cost to observe; determinization stats
  lines are already computed internally).
- Aggregation (report-time, not agent-time): per agent per pairing —
  mean/p50/p90/p95 of `wall_ms`, totals and ratios of search counters,
  fallback ratio = terminal_children/(continuation+terminal) meaning
  (fraction of sampled root children that were terminal, i.e. search
  degenerated to static eval).
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

- 384 matches × ~62 plies mean ≈ 23.8k decisions per pairing set.
- Determinization decisions: 2 pairings × 128 × ~60 ≈ 15.4k at n1
  (~62 ms CLI-measured, but that included process startup; live
  per-decision is lower) and P1/P2/P3's n2000 seats ≈ 15.4k at ~100 ms
  → order 30–60 min wall time for the full 384 on the local machine,
  heuristic seats negligible.
- Observation overhead: one stderr line per determinization decision
  (~200 bytes × ~31k ≈ 6 MB total). The existing bounded 64 KiB tail
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

For each pairing, the verdict table maps to development decisions:

| P1 heuristic vs n1 | P2 heuristic vs M07 | P3 n1 vs M07 | Decision |
|---|---|---|---|
| any | STRONGER_A (heuristic) | any | Reference = heuristic-v1; must-not-regress = {heuristic, and best of P3}; S1 runs vs heuristic as primary anchor |
| any | UNRESOLVED | any | Reference stays ambiguous: keep {heuristic, M07} both as anchors; S1 must face both |
| any | STRONGER_B (M07) | any | Contradicts three prior sources ⇒ treat as anomaly: freeze round, review before any use (this outcome would demand explanation, e.g. seed/protocol regression, before being believed) |
| STRONGER_A (heuristic) | any | any | n1 confirmed weaker than heuristic: n1 demoted to diagnostic-only role in S1 |
| any | any | STRONGER_B (M07) | M07's continuation search has measured value: S1's cost-benefit framing keeps n2000 as the cost reference |
| any | any | STRONGER_A (n1) or UNRESOLVED | n1 ≈ M07 at this budget: champion search adds no separable strength; S1's cheap baseline is n1; M07 cost reference demoted |

Cost summary (all rows): the per-agent `wall_ms` percentiles and search
counter ratios become the standing cost table for S1's "acceptable cost"
judgment.

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
- The M09-era result (49–15) is strong prior evidence for P2's
  direction; this round re-measures under the modern protocol rather
  than discovering the answer.

## Next authorized gate

- Cloud review of this design (matchups, seed segment, budget,
  statistical rule, observation scheme, decision table).
- After APPROVE: implementation per plan (stats flag → P0 gates → 384
  matches → result JSON → final audit), then S0 closure review.
- S1 (search-horizon validation) design is drafted ONLY after S0's
  reference-opponent question is answered.
