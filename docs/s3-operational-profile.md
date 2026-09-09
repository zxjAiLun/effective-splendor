# S3 Operational Profile — live workload, latency distribution, and cost multiple for product decision support

STATUS     = AUTHORIZED / PREREGISTERED CONTRACT (frozen docs-only
            2026-09-09 per user authorization on 84fc895; implementation
            and execution authorized; strictly no production policy code
            modifications; strictly no strength claims/CI computation;
            aimed purely at product decision support for product default
            selection).
RESULT     = PENDING EXECUTION
BASELINE   = 84fc895 (S3 field calibration closure seal, 2026-09-09)
OWNER-DATE = local implementation + cloud review, 2026-09-09

## Question and context

The S3 rollout candidate (`agent-s3-rollout`, zero flags) has been
statistically confirmed as the unique resolved top of the measured field
(S3 Stage B: 80-0-48 vs heuristic-v1; Field Calibration: 104-0-24 vs n1,
100-0-28 vs M07; all direct resolved wins at >= 95% CI). It is now the
official **primary development reference**.

However, strength alone does not determine product default behavior.
Prior latency observations (43 ms ordinary p95, 116 ms wide p95) came
from Stage-A frozen-context feasibility strata, not unconstrained live
play. Before deciding whether `s3-rollout-candidate` should become the
normal product default, remain an opt-in "strong" mode, or become
default with heuristic as an explicit "fast" mode, we must measure its
real operational profile in live matches:

> **How expensive, how slow, and how frequently does S3 invoke rollout
> in genuine live trajectories, and what is its operational cost multiple
> relative to `heuristic-v1`?**

## Investigation boundaries and non-goals

1. **Not a strength experiment**: Game outcomes (W/T/L) are recorded
   solely to verify complete, unexceptional termination. No win rate CIs,
   no hypothesis testing on playing strength, and no re-confirmation of
   `S3 > heuristic` will be computed or claimed.
2. **No production policy changes**: The production `agent-s3-rollout`
   CLI flags, parameters, RNG consumption, proposal set, and rollout
   dynamics remain 100% frozen.
3. **No D/P/proposal tuning**: D=4, P=120, and `C = {a_H, a_n1, a_M07}`
   are strictly untouched.
4. **No search or neural research**: This milestone is an operational
   measurement round, not an algorithmic investigation.
5. **No automatic default change**: The product default remains
   `heuristic-v1` until a formal product decision review explicitly
   selects Choice A, B, or C based on the resulting evidence.

## Protocol and experimental setup

### 1. Seed segment and pairing
- **Segment**: `5_800_384 .. 5_800_447` (64 seeds, registry-verified fresh
  and disjoint from all 3,444 consumed seeds across 25 ranges).
- **Pairing**: `S3` vs `heuristic-v1` across 64 seed blocks x 2 rotations
  = **128 live matches**.
- Both seats are observed under balanced rotations to eliminate seat-specific
  bias while capturing live workloads for both the candidate and the fast
  baseline.

### 2. Telemetry architecture
To avoid polluting or modifying production binaries, telemetry is
collected via dedicated profiling CLI wrappers:
- `agent-s3-rollout-profile --stats-out <path>`
- `agent-heuristic-profile --stats-out <path>`

**Wrapper invariant**:
- Exact same underlying policy code.
- Exact same root seed and deterministic RNG stream.
- Exact same action choices at every decision point.
- Only addition: timing wrapper `Instant::now() -> choose_action() -> elapsed -> emit JSONL line`.
- Telemetry written *after* action selection, ensuring no timing or I/O
  interference with policy logic.

### 3. Action-level telemetry schema (JSONL)
Each line records a single decision event:
```json
{
  "game_id": "s3op-b00-s5800384-r0",
  "request_id": 12,
  "seat": 0,
  "decide_micros": 18420,
  "path": "rollout_comparison",
  "override": true
}
```

S3 decision paths are classified cleanly from policy counters:
- `heuristic_equivalent_fast_path`: non-Main phase, <2 legal moves, or
  proposals strictly identical without needing rollout.
- `rollout_comparison`: multiple distinct proposals evaluated through
  D=4 shared-world heuristic rollouts.
- `ply_cap_fallback`: rollout terminated due to 120-ply cap, falling back
  to `a_H`.

Heuristic decision path is consistently `heuristic_eval`.

### 4. Metrics to report

| Metric | Candidate (`S3`) | Baseline (`heuristic`) |
|---|---|---|
| Decisions count | Total decision steps | Total decision steps |
| Latency mean | Mean decide time (ms) | Mean decide time (ms) |
| Latency p50 | Median decide time (ms) | Median decide time (ms) |
| Latency p90 | 90th percentile (ms) | 90th percentile (ms) |
| Latency p95 | 95th percentile (ms) | 95th percentile (ms) |
| Latency p99 | 99th percentile (ms) | 99th percentile (ms) |
| Latency max | Maximum observed (ms) | Maximum observed (ms) |
| Total decide wall | Sum of all decide durations (s) | Sum of all decide durations (s) |
| Arena wall total | Overall match execution wall (s) | Overall match execution wall (s) |
| Path breakdown | Counts & % of fast-path / rollout / fallback | N/A |
| Override rate | % of decisions where rollout changed `a_H` | N/A |
| Operational cost multiple | S3/H median, S3/H p95, S3/H mean | 1.0x baseline |

*Note on CPU*: Measured via per-decision in-process wall time, sum of
decide times, and total Arena wall clock. If lightweight process CPU time
is accessible without external dependencies, it will be included;
otherwise it is explicitly recorded as not measured (non-blocking).

## Acceptance gates (Correctness-Only)

Unlike strength milestones, there are no artificial latency thresholds
(e.g. "p95 must be < 100ms"). Latency percentiles are empirical inputs
for product design. The round has exactly **three hard correctness gates**:

1. **Gate 1: Profile Wrapper Action Parity = 100%**:
   `agent-s3-rollout-profile` must produce identical action decisions to
   `agent-s3-rollout` on all test cases, and `agent-heuristic-profile`
   must match `agent-heuristic`.
2. **Gate 2: 128/128 Games Completed**:
   All 128 matches must conclude with valid terminal game states and
   verified replays (`splendor verify-replay`).
3. **Gate 3: Zero Timeouts / Zero Process Errors**:
   Zero move timeouts (against the 60s watchdog limit) and zero process
   crashes or abnormal terminations across all 128 matches.

## Product decision options following measurement

Upon passing all three correctness gates, the resulting profile will be
submitted to review to decide between:

- **Choice A: S3 becomes the normal product default**
  (Appropriate if p95/p99 latency is comfortably within interactive
  thresholds and max latency is far from timeout limits).
- **Choice B: Heuristic remains normal default; S3 exposed as "strong" mode**
  (Appropriate if S3 latency tail is considered too heavy for low-power
  or latency-critical default usage).
- **Choice C: S3 becomes default; Heuristic retained as explicit "fast" mode**
  (Appropriate if S3 is generally acceptable but users need an explicit
  near-instant fallback option).
