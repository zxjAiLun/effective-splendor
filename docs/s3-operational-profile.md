# S3 Operational Profile — live workload, latency distribution, and cost multiple for product decision support

STATUS     = APPROVED / COMPLETED_PROFILE / CLOSED (final review 2026-09-09
            on ba8f2b1: operational profile accepted; all 3 correctness
            gates PASS; PRODUCT DECISION: CHOICE C adopted — S3 rollout
            becomes the product default AI, heuristic-v1 retained and
            exposed as explicit Fast mode; primary development reference =
            s3-rollout-candidate; promotion = NONE. P0:0 / P1:0 / P2:4
            non-blocking closure wording items applied docs-only).
RESULT     = S3 LIVE WORKLOAD PROFILED:
            - S3 latency: p50 = 55.94 ms, p95 = 152.73 ms, p99 = 507.40 ms,
              max = 3,020.86 ms (watchdog headroom: 19.9x vs 60s limit).
            - Heuristic latency: p50 = 0.013 ms, p95 = 0.026 ms, max = 0.252 ms.
            - Latency multiple vs Heuristic: 4,303x median, 5,874x p95, 4,727.8x mean.
            - S3 rollout invocation rate: 61.08% (2,287/3,744 decisions).
            - S3 fast-path rate: 38.92% (1,457/3,744 decisions).
            - S3 override rate: 18.35% overall (687/3,744 decisions;
              30.04% of comparisons).
            - Ply-cap fallbacks: 0 (0.00% — 100% completed simulation).
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

## Acceptance gates (Correctness-Only)

Unlike strength milestones, there are no artificial latency thresholds
(e.g. "p95 must be < 100ms"). Latency percentiles are empirical inputs
for product design. The round has exactly **three hard correctness gates**:

1. **Gate 1: Profile Wrapper Action Parity = 100%**:
   `agent-s3-rollout-profile` must produce identical action decisions to
   `agent-s3-rollout` on all test cases, and `agent-heuristic-profile`
   must match `agent-heuristic`.
   -> **PASS**: 100% byte-identical replay hashes and action sequences on smoke
      matches and automated integration tests.
2. **Gate 2: 128/128 Games Completed**:
   All 128 matches must conclude with valid terminal game states and
   verified replays (`splendor verify-replay`).
   -> **PASS**: 128/128 matches completed; 7,487 plies verified.
3. **Gate 3: Zero Timeouts / Zero Process Errors**:
   Zero move timeouts (against the 60s watchdog limit) and zero process
   crashes or abnormal terminations across all 128 matches.
   -> **PASS**: 0 timeouts, 0 process errors. Maximum observed S3 latency
      was 3.02s (19.9x watchdog headroom).

## Empirical execution results (2026-09-09)

### 1. Decision latency distributions

| Metric | Candidate (`S3`) | Baseline (`heuristic`) | Operational multiple |
|---|---:|---:|---:|
| **Decisions count** | 3,744 | 3,743 | — |
| **Mean** | **72.81 ms** | **0.0154 ms** (15.4 µs) | **4,727.8x** |
| **p50 (Median)** | **55.94 ms** | **0.0130 ms** (13.0 µs) | **4,303.0x** |
| **p90** | **115.97 ms** | **0.0190 ms** (19.0 µs) | **6,103.7x** |
| **p95** | **152.73 ms** | **0.0260 ms** (26.0 µs) | **5,874.3x** |
| **p99** | **507.40 ms** | **0.0790 ms** (79.0 µs) | **6,422.8x** |
| **Max** | **3,020.86 ms** | **0.2520 ms** (252 µs) | **11,987.5x** |
| **Total decide wall** | 272.60 s | 0.0577 s | — |
| **Arena match wall (4 workers)** | 95.9 s (~0.75 s / match) | 95.9 s | — |

*CPU observation*: per-decision in-process wall duration, sum of decide
times (272.60 s for S3 across 3,744 decisions), and overall Arena wall
clock (95.9 s) recorded. Process-specific CPU time not measured
(non-blocking).

### 2. S3 decision path breakdown and rollout frequency

| Path | Decisions | % of S3 decisions | Notes |
|---|---:|---:|---|
| **`heuristic_equivalent_fast_path`** | 1,457 | **38.92%** | Non-Main, <2 legal, or identical proposals |
| **`rollout_comparison`** | 2,287 | **61.08%** | D=4 shared-world rollouts evaluated |
| **`ply_cap_fallback`** | 0 | **0.00%** | Zero ply-cap truncations (P=120 completed 100%) |
| **Total S3 decisions** | 3,744 | 100.00% | — |

### 3. Action override frequency

| Metric | Count | Rate |
|---|---:|---:|
| **Overrides (changed from `a_H`)** | 687 | **18.35% of all decisions** |
| **Overrides of comparisons** | 687 | **30.04% of rollout comparisons** |

In roughly 1 in every 5 decisions (and 30.04% of rollout comparisons),
the S3 rollout policy changed the heuristic proposal `a_H`. The aggregate
policy containing these changes is empirically resolved stronger (S3
Stage B: 80-0-48 vs H; Field Calibration: 104-0-24 vs n1, 100-0-28 vs M07),
though individual overrides are not claimed to be point-by-point proven
corrections.

### 4. Operational latency observations

- **Typical interactive latency**: Median decision latency is **~56 ms**,
  and 90% of decisions finish under **~116 ms**. This is completely
  comfortable for interactive play and CLI usage.
- **Latency tail**: p95 is **~153 ms**, p99 is **~507 ms**, and the
  single worst-case decision across 3,744 decisions took **3.02 s**.
- **Watchdog headroom**: No timeout was observed in this 128-match profile;
  the worst observed decision was 3.02s versus the 60.0s watchdog limit
  (19.9x observed headroom on this test host). Note: operational latency
  is environment- and platform-specific.
- **Cost multiple**: Compared to the microsecond-level heuristic baseline
  (13 µs median), S3 is ~4,300x heavier in compute time, reflecting the
  full evaluation of search proposals (n1 and M07 2000-node searches) plus
  heuristic rollout simulations.

## Product decision support: Choice A, Choice B, or Choice C

With all correctness gates passed and empirical operational data in hand,
the project faces three clear product choices:

### Choice A: S3 becomes the normal product default
- **Arguments for**:
  - Confirmed strongest agent across the entire measured field (beats H, n1, M07).
  - Median latency (56 ms) and p95 (153 ms) are well within sub-second
    interactive thresholds for human play.
  - Zero watchdog risk (3s max vs 60s limit).
- **Arguments against**:
  - S3 is orders of magnitude more computationally expensive per decision
    than the microsecond heuristic (4,303x median per-decision latency
    ratio); heuristic remains the preferred option for high-throughput batch
    simulation.

### Choice B: Heuristic remains normal default; S3 exposed as "strong" mode
- **Arguments for**:
  - Retains maximum throughput and zero CPU footprint for batch simulations
    and lightweight default usage.
  - S3 is explicitly reserved for when users or benchmarks demand top strength.
- **Arguments against**:
  - The default CLI experience gives users a provably inferior player
    (80-48 win rate disadvantage vs S3).

### Choice C: S3 becomes default; Heuristic retained as explicit "fast" mode
- **Arguments for**:
  - "Batteries included" best experience out of the box: user plays against
    the strongest known AI by default.
  - Batch scripts and large-scale simulation tools can pass `--fast` or
    `agent-heuristic` when microsecond throughput is desired.
- **Arguments against**:
  - Requires documentation clarity so high-volume simulation users know
    to select the fast mode.

## Formal product decision: Choice C adopted

Following formal closure review (2026-09-09), **Choice C** was adopted:
- **Product default**: `s3-rollout-candidate` (strongest confirmed agent).
- **Explicit Fast mode**: `heuristic-v1` (retained for high-throughput batch runs).
- **Primary development reference**: `s3-rollout-candidate`.
- **Historical champion**: `M07` (narrative label only).
- **Promotion**: NONE (product default selection is not a research promotion).
