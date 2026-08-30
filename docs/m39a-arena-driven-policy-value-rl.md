# M39A Arena-Driven Policy-Value RL

```text
Milestone:      M39A
Title:          Arena-Driven Policy-Value RL (Environment-Reward Self-Play)
Status:         IMPLEMENTED / IMPLEMENTATION_SMOKE_PASS / PHASE_0_PENDING
Review R1:      NEEDS_REVISION — P0 = 0, P1 = 5, P2 = 0 (2026-08-29)
Review R2:      NEEDS_REVISION — P0 = 0, P1 = 4, P2 = 2 (2026-08-29)
Rev 2 re-review: NEEDS_REVISION — P0 = 0, P1 = 3, P2 = 2 (2026-08-29)
Rev 3 re-review: NEEDS_REVISION — P0 = 0, P1 = 2, P2 = 2 (2026-08-30)
Rev 4 revision:  2026-08-30, document-only; baseline unchanged 573434f
Rev 4 re-review: NEEDS_REVISION — P0 = 0, P1 = 2, P2 = 2 (2026-08-30)
Training:       ONE-GAME CPU+CUDA IMPLEMENTATION SMOKE ONLY; no formal cycle
Arena:          CPU+CUDA implementation smoke only; Phase 0 not started
Baseline:       573434f (pushed HEAD; local main == origin/main)
Baseline moved: 733401c -> 573434f on 2026-08-29, five engineering-only
                 commits (see "Not addressed by this revision"). No frozen
                 constant, seed, or gate in this document changed.
Revision date:  2026-08-30 (Asia/Shanghai)
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE (this round does not seek promotion)
```

> **Review R1 verdict: `NEEDS_REVISION`.** Independent review found `P0 = 0`
> and `P1 = 5`. Training and data collection are **not** authorized. All five
> P1 findings are addressed in Revision 1; each change is marked `[R1-P1-n]`
> at its site. §Review R1 — findings and disposition records the full
> mapping. Re-review is required before any collection begins.

> **Review R2 verdict: `NEEDS_REVISION`.** P0 = 0, P1 = 4, P2 = 2. Training
> and data collection remain **not** authorized. Revision 2 addresses all
> four P1 and both P2 findings; each change is marked `[R2-P1-n]` /
> `[R2-P2-n]` at its site. §Review R2 — findings and disposition records the
> full mapping. Re-review is again required before any collection begins.

> **Revision 2 independent re-review verdict: `NEEDS_REVISION`.** The
> arithmetic corrections are sound, but the trajectory join still does not
> bind every value consumed by PPO, G0's four-bucket probe cannot produce the
> five timing means in its projection, G0b's exact family probabilities assume
> independence contradicted by reusing the same seeds across buckets, and G3's
> diagnostic interval treats repeated measurements under 32 shared seeds as
> 288 independent units. P0 = 0, P1 = 3, P2 = 2. The execution fence remains
> unchanged.

> **Revision 3 (2026-08-29, document-only).** All five re-review findings are
> closed: `[RR3-P1-1]` the join now binds the stored observation payload,
> sampling seed, behaviour log-probability, and old value to the replay and
> the bound checkpoint, and reproduces the sampled action by the frozen draw
> (Phase 2); `[RR3-P1-2]` G0 collapses to four timing strata matching the
> probe's four buckets, with units frozen in seconds and the hours conversion
> in the formula (§5.4 G0); `[RR3-P1-3]` G0b's four buckets receive disjoint
> 96-seed ranges (384 unique probe games), restoring the independent-binomial
> model its count rules were computed under (§5.4 G0b);
> `[RR3-P2-1]` G3's diagnostic interval is re-frozen to 32 cross-opponent
> seed aggregates, `df = 31`, critical value `1.695518782546` (§5.4 G3);
> `[RR3-P2-2]` the three prose drifts are repaired in place (§3.5, I4, Phase 2).
> No other frozen value changed; the baseline is unchanged at `573434f`.

> **Revision 3 independent re-review verdict: `NEEDS_REVISION`.** The five
> targeted repairs are directionally correct, and the G3/statistical constants
> recompute exactly, but Phase 0 still leaves the diversified and league
> opponent assignment plus warm-up weighting to the executor, and the PPO
> trainer still has no frozen minibatch/optimizer-step contract. Two additional
> P2 clarifications are required for the bit-exact checkpoint replay and the
> homogeneous-binomial interpretation of the mixed-opponent probe. P0 = 0,
> P1 = 2, P2 = 2. The execution fence remains unchanged.

> **Revision 4 (2026-08-30, document-only).** All four Rev 3 re-review
> findings are closed: `[RR4-P1-1]` the Phase 0 probe now freezes a
> bucket-local ordinal with exact opponent assignment — DIVERSIFIED's 72/24
> interleave and LEAGUE's 96-to-9 round-robin — and replaces the "first 2
> games" warm-up with predeclared proportional warm-up subsets (64/16 and
> 8 per bucket timed), so Phase 0 has no remaining design choice (§5.4
> G0/G0b); `[RR4-P1-2]` the full PPO trainer execution contract is frozen —
> minibatch size and deterministic shuffle, optimizer steps, AdamW
> parameters, per-cycle LR waypoints, loss reductions, and explicit head
> initializers — and bound into the training plan hash (§5.3);
> `[RR4-P2-1]` behaviour-value recomputation gets a frozen runtime
> environment plus finite-value checks, with an explicit pre-registered
> contingency: recorded-value equality becomes a frozen diagnostic while
> recomputed values stay authoritative for PPO (Phase 2);
> `[RR4-P2-2]` G0b's quoted probabilities are re-labelled homogeneous-p
> reference operating characteristics, with per-sub-stratum reporting added
> (§5.4 G0b). The count rules, thresholds, and all previously frozen
> constants are numerically unchanged; the baseline is unchanged at
> `573434f`.

> **Revision 4 independent re-review verdict: `NEEDS_REVISION`.** Phase 0's
> named 384-game schedule and the heterogeneous-probe reporting contract are
> now executable, and all independently checked numerical constants agree.
> The PPO trainer is not yet a single reproducible algorithm: its shuffle has
> no per-index key formula, its GAE recursion/normalization remains ambiguous,
> and the stated `nn.Linear` bias/default-generator semantics are false under
> the frozen PyTorch 2.6 runtime. Two additional P2 contract/prose repairs are
> also required. P0 = 0, P1 = 2, P2 = 2. The execution fence remains
> unchanged.

This document is a **pre-registration**. Every number in the *Frozen constants*
and *Gates* sections is declared before any data is collected and may only be
amended during the review window — never after a result is observed.

> **Implementation authorization (2026-08-30).** The user explicitly ended
> the document-only review loop and authorized implementation. This overrides
> the earlier execution fence for code and bounded implementation smoke only;
> it does not silently authorize the 384-game Phase 0 probe or 4,096-game
> formal collection. The Revision 5 closures are implemented as executable
> contracts and tests rather than another prose-only revision.

---

## Problem and evidence

### Why the previous direction was terminated

The Teacher-fitting route is closed. Evidence:

- **M25 / M29A / M30A / M31A / M32A / M33A / M34A**: eight consecutive rounds
  of fitting M07 search output. All stopped at offline gates; validation
  Top-1 never left the 36–39% band regardless of representation change.
- **M35A** (`PARTIAL_VALID / ACCEPTED / CLOSED`): M07 beats every scored
  direct-policy checkpoint with win rates in **17.2%–32.8%** (i.e. M07 wins
  67–83%). Offline Top-1 and Arena strength are **non-monotonic** across
  Cohort A — M31A has the *lowest* offline Top-1 (35.91%) yet is the *second
  strongest* (57.8%) against D2-v2.
- **M38A** (`Utility-Regret Reassessment`) was designed and then
  **cancelled before implementation**. Its own finding is the reason: CE,
  Top-1, and teacher utility/regret all measure *similarity to M07*, and M07
  has a demonstrable strategic ceiling. Fitting it harder cannot answer the
  only question that matters — actual playing strength.

### Why this direction is not simply "self-play again"

This direction has already failed three times. The new round must not be a
rerun, so the failures are recorded here as design constraints:

| Round | Scale | Result |
|---|---|---|
| M18A (Neural ISMCTS RL) | 2 games / 122 examples | `REJECT` |
| M22 (Scaled Self-Play) | 32 games / 1,992 examples | `NOT_PROMOTED`; vs heuristic 1–7, vs M07 1–7 |
| M24-S2 | 384 fresh games | offline fit improved, vs-S1 improved, **M07 anchor −313 bps** vs frozen −200 threshold → G4 `FAIL` / G5 `STOP` |

- **M24.5** attributed the M24-S2 failure to `SEARCH_BOTTLENECK`.
- **M27A** (the follow-up search-budget scan) returned `M27A_INCONCLUSIVE`:
  14 cells / 896 matches, all 7 anchor centres below +1000 bps, no budget
  selected.

The recurring failure mode is specific and is the primary thing M39A is
designed against:

> More self-play data improves performance against the self-play distribution
> and against weak opponents, while *degrading* relative performance against
> M07.

Three structural differences from all three prior rounds:

1. **Objective.** M18A/M22/M24-S2 trained the policy target on
   `normalized_visits` — i.e. still imitation of a search (in M22's case,
   imitation of the model's own weak search). M39A trains the policy only
   from realised environment return.
2. **Opponent distribution.** M24-S2 collected almost entirely from the
   self-play distribution while gating on M07. M39A puts M07 *inside* the
   training opponent pool.
3. **Scale.** 4,096 games versus 2 / 32 / 384.

---

## Initial design

### 3.1 Initialization

- Architecture: the **M25-D2-v2** `DeltaEntityMixer` unchanged
  (`h192 / b4`, 59-dim action encoding = 36 base + 23 exact-transition delta).
  Class defined at `training/m17_gpu/splendor_gpu/m25_exp_d2.py:126`.
- Checkpoint: the official D2-v2 weights, bound by SHA via the existing
  `m35a_registry.py` loader.
- Heads:
  - **actor**: reuses the existing 59-dim `action_encoder` + `policy` MLP
    producing one logit per legal action; interpreted as a masked categorical
    distribution.
  - **critic** `[R1-P1-1]`: a **new** two-unit viewer-relative head with a
    **linear** (no-activation) output, replacing the D2-v2 `value` MLP:

    ```python
    self.value = nn.Sequential(
        nn.Linear(h, h), nn.GELU(), nn.Linear(h, 2),
    )   # final activation = none
    ```

    Output semantics are frozen: `output[0]` is the **current viewer's**
    expected centered outcome, `output[1]` the opponent's. The D2-v2 head is
    **not** reused: it terminates in `nn.Sigmoid()` (`m25_exp_d2.py:139`),
    so its range is `[0, 1]²` and it cannot represent the negative returns
    defined in §5.2. This is not a warm-start loss — D2 was trained with
    `value_loss_weight = 0.0` (`m25_exp_d2.py:318`), so its value head never
    received gradient and carries no trained information.
  - **auxiliary score-difference head** `[R2-P1-4]`: a new **scalar linear**
    head off the state embedding — same input as the critic head, no shared
    parameters, no output activation — predicting the signed, normalized VP
    differential whose full contract (target normalization, truncation
    timing, loss, initialization seed) is frozen in §5.3.
- The architecture is deliberately **not** changed this round, with the single
  exception above. The single experimental variable is the learning signal.

`[R1-P1-1]` Initialization is therefore **asymmetric** and must be recorded in
checkpoint metadata:

```text
load from D2-v2 : trunk.*, action_encoder.*, policy.*
do not load     : value.*, auxiliary_score_head.*
new heads       : re-initialized from a frozen seed

value_semantics        = centered_outcome_viewer_relative
value_output_shape     = 2
value_activation       = linear
base_value_head_loaded = false
new_head_init_seed     = 20_260_829
```

`[R2-P1-4]` The two new heads are re-initialized from one dedicated
`torch.Generator` seeded with `new_head_init_seed`, consumed in a frozen
order — **critic head first, then auxiliary head** — so re-initialization is
reproducible and the trunk weights are untouched by it.

### 3.2 Action selection (on-policy)

For each decision, the actor produces logits over the current legal-action
set; the sampled action is drawn from

```text
p(a) = softmax(logits) restricted to the legal-action mask
```

Requirement: **sampling, not argmax.** `m35a_agent.py:118` uses
`scores.argmax()`; the M39A rollout agent must sample and must record
`log p(a)` for the PPO ratio. The legal-action mask is taken directly from
the `request_action` message's `legal_actions`, so variable-length action
sets are handled exactly as in the existing path.

### 3.3 Opponent pool (frozen at 4,096 games)

```text
1536  latest vs latest          (both seats = current policy snapshot)
1024  latest vs M07             (determinization-s4-d1-n2000-v1, frozen args)
1024  latest vs historical neural league
 512  latest vs heuristic / diversified baseline
     (of which 384 vs splendor agent-heuristic, 128 vs splendor agent-random)
```

- The historical neural league pool is the 9 registered checkpoints
  (`training/m17_gpu/splendor_gpu/m35a_registry.py:53-166`). The set is bound
  to the M35A manifest key set, not restated from memory:

  ```text
  M24-S2, M25-D2-v2, M28A, M28B, M29A-v2, M31A, M32A, M33A, M34A

  manifest : benchmarks/m35a-retrospective-arena.manifest.json
  SHA-256  : 2f29a06cd2385c6a39ddec0e543d5c7ff982caa3d2568181a6d11f2a71a4a1cd
  ```

- `[R1-P1-3]` `[R2-P1-1]` **Bucket assignment is a closed-form, cycle-local
  function of `game_index` with no RNG.** "Sampled uniformly" is not a
  specification, and Revision 1's global partition made every cycle a
  single-opponent block — cycle 1 = 128 random + 384 heuristic, cycles 2–3 =
  M07 only, cycles 4–5 = league only, cycles 6–8 = self-play only — which
  contradicted §3.5 and turned the schedule into a strong curriculum.
  `game_index` is therefore split into a cycle coordinate and an in-cycle
  coordinate, and the buckets are assigned **within** the cycle:

  ```text
  cycle = game_index // 512            (cycle 0 .. 7)
  j     = game_index mod 512

  j [  0,  16)  -> RANDOM       16 games/cycle   ( 128 total)
  j [ 16,  64)  -> HEURISTIC    48 games/cycle   ( 384 total)
  j [ 64, 192)  -> M07         128 games/cycle   (1024 total)
  j [192, 320)  -> LEAGUE      128 games/cycle   (1024 total)
  j [320, 512)  -> SELF_PLAY   192 games/cycle   (1536 total)

  league_ordinal  = cycle * 128 + (j - 192)        (0 .. 1023, consecutive)
  league_opponent = LEAGUE_ORDER[league_ordinal mod 9]
  ```

  Bucket **totals are unchanged** from Revision 1 (16+48+128+128+192 = 512
  per cycle); only their arrangement along the index axis changed, so all
  eight cycles now see the same opponent distribution. `LEAGUE_ORDER` is the
  registry insertion order of `m35a_registry.py` — it is defined here, not
  imported from code:

  ```text
  LEAGUE_ORDER = [M24-S2, M25-D2-v2, M28A, M28B, M29A-v2, M31A, M32A, M33A, M34A]
  ```

  Since `1024 = 9 × 113 + 7`, the per-opponent counts are frozen exactly:
  `M24-S2 / M25-D2-v2 / M28A / M28B / M29A-v2 / M31A / M32A` receive **114**
  games each; `M33A / M34A` receive **113** each. **D2-v2 appears in 114 of
  the 1,024 league games**, which is the exposure the Q3 discussion
  anticipated.

- `[R1-P1-3]` D2-v2 is deliberately **kept** in the training pool (see Q3 in §Open questions). It
  is simultaneously the initialization, a league opponent, and the G2
  baseline. That triple role is intentional, and §5.4 G3 gives the resulting
  `D2-v2 vs D2-v2` self-play pairing an explicit interpretation rather than
  silently dropping it.
- Only the **learner's seat** produces training transitions. Opponent
  decisions are discarded entirely.
- `[R2-P2-1]` Expected decision volume (not a gate). Revision 1 multiplied the
  number of learner trajectories by the **whole-game** ply count, double
  counting: ~63 is the mean number of actor plies in a *game*, and one seat
  makes about half of them. Corrected:

  ```text
  self-play    1536 games × 2 learner seats × ~31.5 decisions ≈  96,800
  vs-opponent  2560 games × 1 learner seat  × ~31.5 decisions ≈  80,600
  total                                                      ≈ 177,000
  ```

  (~63 total actor-plies per game, from the §5.1 ply distribution with mean
  max ply 62.6.)

### 3.4 Game indexing and seeds

```text
game_index ∈ [0, 4096)
seed        = 4_000_000 + (game_index // 2)
learner_seat = game_index % 2
```

The learner occupies both seats in self-play; in the other three buckets the
`learner_seat` field fixes which side is the learner, so seat assignment is
balanced by construction rather than by rotation.

### 3.5 Collection schedule

Eight collection/update cycles of 512 games each — cycles 1 through 8
inclusive, eight iterations total `[RR3-P2-2]` (the earlier `for cycle in
1..8` prose read as seven iterations):

```text
for cycle in 1, 2, 3, 4, 5, 6, 7, 8:     # eight iterations, inclusive
    snapshot current policy
    collect 512 games — bucket assignment is the cycle-local function of
      §3.3 evaluated on this cycle's 512 game_index values, so every cycle
      sees the identical opponent mix (16/48/128/128/192)
    join trajectories with match reports → returns
    4 PPO epochs over that batch
    discard the batch
    checkpoint as cycle-N
```

`[R2-P1-1]` The mix is proportional **within** every cycle by construction of
the cycle-local formula, so the learner sees M07 and the league from cycle 1
onward rather than only in dedicated cycles.

---

## Scope and non-goals

**In scope**

- An additive Rust rollout entry point with a configurable ply cap.
- A Python rollout agent that samples, records `(observation, legal_actions,
  action, log p(a), critic value)`, and writes a per-`(game, seat)` JSONL
  side file `[R2-P1-2]`.
- A PPO/actor-critic trainer over the collected batches.
- Frozen Arena evaluation and behaviour diagnostics.

**Explicit non-goals**

- No promotion. Beating M07 for the championship requires the existing
  `min_pairwise_score_lower_bound_bps: 5000` promotion gate
  (`benchmarks/m13-neural-ismcts-v1.gate.json`); M39A does not attempt it and
  does not change it.
- **No M07-derived labels.** M07's actions, search visit counts,
  `utility_sum_by_player`, and any CE / Top-1 against M07 are *never* used as
  training targets. M07 appears only as a game environment.
- No `normalized_visits` target in any form.
- No architecture change, no width change, no new representation.
- No change to the frozen engine, the frozen `StaticEvaluatorV1` weights, or
  `MAX_MATCH_PLIES`.
- No teacher-side metric as a gate. CE / Top-1 / teacher-agreement may be
  reported for compatibility with historical rounds but carries **no gate
  weight and no selection weight**.

---

## Contracts and invariants

### I1 — M07 is an environment, not a target

M07 participates only as a spawned opponent subprocess with frozen arguments:

```text
target/release/splendor agent-determinization \
  --sample-seed 20260810 --sample-count 4 \
  --max-depth-turns 1 --max-nodes 2000
```

Nothing M07 emits is written into the training batch.

### I2 — Frozen artifacts stay frozen

- `crates/splendor-arena/src/runner.rs:39` `MAX_MATCH_PLIES = 10_000` is
  **not** modified. It remains the formal-Arena ceiling.
- `crates/splendor-search/src/evaluation.rs:16-24` evaluator weights are not
  touched.
- `crates/splendor-arena/src/config.rs:25` `ArenaConfig` is not modified.
- Existing `splendor run-match` behaviour is byte-identical; M39A adds a
  **separate, additive** rollout entry.

### I3 — Truncation never fabricates a win

A game that reaches the training ply cap is recorded with
`status = truncated`. It contributes **no** win/loss label. Its return is the
truncation return defined in §5.2. Truncated games are counted and reported
separately and are never folded into the completed-game statistics.

### I4 — Determinism

- Every game is seeded from the frozen schedule; no wall-clock reads, no RNG
  other than the seeded match RNG and the frozen SPLITMIX64 categorical
  sampler of Phase 2 `[RR3-P2-2]` (no `torch` RNG is used for action
  sampling).
- Sampling uses a per-decision seed derived deterministically from
  `(game_index, seat, request_id)` by the frozen Phase 2 formulas.
- The critic/actor update order is fixed by the batch file order.

### I5 — Arena contract

Timeouts and fault tolerances are the established ones. The **block count is
no longer the legacy 32** `[R1-P1-2]`:

```text
                                  G2        G3
min_completed_seed_blocks         128        32
seat_rotations_per_seed             2         2
matches per pairing               256        64
pairings                            2         9
total matches                     512      1152
confidence_bps                   9500      9500
max_aborted_matches                 0         0
max_candidate_faults                0         0
handshake_timeout_ms             5000      5000
move_timeout_ms                 10000     10000
shutdown_grace_ms                2000      2000
```

The legacy `min_completed_seed_blocks = 32` descends from M27A/M35A, where the
`n = 32` Hoeffding bound was accepted as **reported diagnostic uncertainty**
rather than as a decision threshold. G2 puts a lower bound **on the decision**
itself, which is a materially stronger use: at `n = 32` it would demand a
~43 pp Hoeffding margin, or under Student-t would miss a true 10 pp gain about
60% of the time. G2 therefore uses 128 blocks. G3 keeps 32 blocks per pairing
because it carries no lower-bound requirement.

Everything else is unchanged: no change to `ArenaConfig`, to report
validation, or to `MAX_MATCH_PLIES`.

### I6 — Publication boundary

Games, trajectories, checkpoints, and reports live under ignored
`local-artifacts/`. Only this document, frozen config/plan/gate JSON, and
compact result manifests are tracked.

---

## Implementation plan

### Phase 0 — Pre-flight smoke (`G0` and `G0b`, both blocking)

Before any training game is collected, measure on the actual hardware **for
each of the four opponent buckets** (diversified / M07 / league / self-play
— the same four strata G0's timing projection now uses `[RR3-P1-2]`):

1. wall-clock per match (`G0`, `[R2-P1-3]` `[RR3-P1-2]` `[RR4-P1-1]` —
   warm-up, opponent assignment, parallelism, units, and projection formula
   are frozen in §5.4 G0);
2. the truncation rate at `TRAINING_PLY_CAP = 150` (`G0b`, `[R1-P1-4]`
   `[R2-P1-3]` `[RR3-P1-3]` `[RR4-P1-1]` — probe sizes, opponent
   assignment, disjoint per-bucket seed ranges, and pass rules are frozen
   in §5.4 G0b).

Phase 0 is their **executor, not their designer**: every number, every
opponent assignment, and the intra-bucket game order are in §5.4, and it
must not substitute its own `[RR4-P1-1]`.

*Throughput reason:* the only available historical datapoint for whole-Arena
throughput is M35A, whose artifacts span roughly 15:02→21:24 on 2026-08-27 for
1,088 scheduled matches (≈6.4 h, parallelism unrecorded). A 4,096-game
commitment must not be made on that basis alone.

*Truncation reason* `[R1-P1-4]`: the cap's justification in §5.1 rests on
M07-vs-M07 games only, while M35A shows a neural policy facing M07 can reach
the 10,000-ply ceiling. The probe must therefore sample **all four** buckets,
with the learner actually playing the M07 bucket and the league bucket — those
are where non-termination was observed — and must **not** be satisfied by a
self-play-only sample, which is exactly the distribution the original
justification came from.

Freeze `MAX_COLLECTION_WALL_CLOCK_HOURS = 72`. If the projection exceeds it,
the round must add parallelism, accept the reduced N permitted in §5.5, or be
re-designed — **it must not silently run over and then re-scope**.

Phase 0 emits a tracked result binding both measurements, the probe seed
list actually used, per-bucket wall-clock means and truncation counts **plus
the sub-stratum splits of `[RR4-P2-2]`** (diversified 72/24; nine league
opponents), the worker count `J`, the resulting projection, and the
checkpoint SHA it ran against.

### Phase 1 — Additive rollout entry (Rust)

New subcommand alongside `run-match`, reusing `splendor-arena` internals:

```text
splendor run-rollout --config <arena-config.json> --max-plies <n> \
  --report-out <report.json> [--replay-out <replay.json>]
```

- Identical `ArenaConfig` input shape.
- Report gains a `truncated` status alongside the existing `completed` /
  `aborted` statuses; `aborted` semantics unchanged.
- `--replay-out` is written for completed **and** truncated matches.
- Unit tests: cap reached → `truncated`; cap never reached → identical output
  to `run-match` for the same seed.

### Phase 2 — Rollout agent (Python)

Derived from `training/m17_gpu/splendor_gpu/m35a_agent.py`, which already
implements the NDJSON agent protocol (`PROTOCOL_VERSION = "0.5"`).

Changes:
- `argmax` → masked categorical sampling; emit `log p(a)`.
- Emit the critic value for the current state. Per §3.1 this head emits the
  viewer-relative pair; the value written to the rollout is **`value[0]`**.
- Append one JSONL record per decision to a side file keyed by
  `(game_index, seat)` `[R2-P1-2]` — one file per seat, never shared.
- Do not depend on the `game_end` payload for outcome data; the driver reads
  outcome and final VP from the report/replay.

`[R1-P1-5]` `[R2-P1-2]` **Trajectory record schema — frozen field set.** A
side file "keyed by `game_index`" is a filename convention, not a provenance
contract. Revision 1's schema also assumed `request_id` is contiguous from 0
**within the learner seat**, which contradicts the Arena's actual contract:
`request_id` starts at **1** and is a **global** counter incremented once per
ply across both seats (`crates/splendor-arena/src/controller.rs:195`,
`runner.rs:461`), so a learner seat observes only odd or only even values.
The schema is re-frozen around the engine's semantics — `ply_index` is the
join key, `request_id` is recorded verbatim for cross-checking:

```text
plan/config hash      canonical hash of the rollout plan + ArenaConfig that
                      produced this game (hash spec frozen below), so a stale
                      config cannot be joined in
checkpoint SHA        the policy checkpoint that made this decision
game_id / game_index  game identity. game_index ∈ [0, 4096) is unique across
                      the whole round in this schedule (one pass, no reuse
                      `[RR3-P2-2]`); game_id is still recorded because the
                      Arena report is keyed by it and the pair — not the bare
                      index — is what the report hash binds
seat                  the learner seat that produced this record (0 or 1)
ply_index             the ply this decision belongs to, counted by the
                      authoritative replay (0-based)
request_id            the Arena's global request ordinal, recorded verbatim;
                      equals ply_index + 1
observation_hash      SHA-256 (lowercase hex) of the observation as received:
                      this is the engine's own splendor-core
                      `observation_hash` of the player view (the same value
                      the `RequestAction` message carries, `hash.rs:331`),
                      not an ad-hoc digest
observation           the exact observation the policy saw, stored as the
                      typed player-view observation (audit payload; the join
                      compares the stored payload itself, not just its
                      self-reported hash `[RR3-P1-1]`)
legal_actions         the legal-action set the mask was built from, **in the
                      order the engine sent it**
action                the action taken, as a stable semantic id
old_log_probability   log p(a) under the behaviour policy, as recorded at
                      decision time (audit/diagnostic record; the join
                      recomputes this value from the bound checkpoint and
                      the recomputed value is what PPO consumes
                      `[RR3-P1-1]` `[RR4-P2-1]`)
old_value             value[0] at decision time, as recorded (audit/
                      diagnostic record, same rule as above
                      `[RR3-P1-1]` `[RR4-P2-1]`)
sampling seed         the per-decision decision_seed, derived by the frozen
                      formula below (I4); validated by the join
                      `[RR3-P1-1]`
```

and every **game** record must additionally bind:

```text
Arena report hash
replay hash
```

`[R2-P1-2]` **One sidecar per `(game_index, seat)`.** In self-play both
agents run concurrently and must not append to one file. Each seat writes
`<sidecar-dir>/<game_index>.seat<seat>.jsonl`; the driver merges the pair
only after the match has ended and the report is bound. Non-self-play
buckets produce a single seat file by construction.

`[R2-P1-2]` **Canonical hash and sampling-seed formulas — frozen.**

```text
canonical bytes       = serde_json::to_vec of the value (Rust); serde emits
                        struct fields in declaration order, so the byte
                        sequence is canonical for a given build
hash                  = SHA-256, encoded lowercase hex

plan/config hash      = SHA-256 over
                        b"m39a-rollout-plan-v1\0"
                        || canonical(ArenaConfig JSON)
                        || canonical(plan JSON)

SPLITMIX64(z):        state += 0x9E3779B97F4A7C15
                      z = state
                      z ^= z >> 30;  z *= 0xBF58476D1CE4E5B9
                      z ^= z >> 27;  z *= 0x94D049BB133111EB
                      z ^= z >> 31
                      return z

game_sampling_seed    = SPLITMIX64(7_000_000 + 2*game_index + seat)
decision_seed         = SPLITMIX64(game_sampling_seed
                                   ^ (request_id * 0x9E3779B97F4A7C15))
                       # a pure function of (game_index, seat, request_id);
                       # the join recomputes it and validates the record's
                       # stored seed field against it [RR3-P1-1]

categorical draw      u = (decision_seed >> 11) * 2^-53  ∈ [0, 1)
                      walk legal_actions in recorded order; take the first
                      index whose cumulative softmax probability exceeds u
                      # the join re-executes this draw over the bound
                      # checkpoint's masked softmax and requires the
                      # selected action to equal the recorded action
                      # [RR3-P1-1]
```

No `torch` RNG is used for sampling. `7_000_000` is a new seed base, disjoint
from the training (`4_000_000 + game_index // 2`), G2 (`5_000_000..`),
G3 (`5_100_000..`), and probe (`5_200_000..`) ranges.

`[R1-P1-5]` `[R2-P1-2]` `[RR3-P1-1]` **Join validation — fail-closed,
replay-authoritative, and checkpoint-bound.** Revision 1 validated a sidecar
against itself, which a self-consistent stale sidecar would pass. Revision 2
added replay-authoritative observation and legal-action checks but left the
stored observation payload, `old_log_probability`, `old_value`, and the
sampling seed self-reported, so a stale or tampered sidecar could still feed
PPO numbers the bound checkpoint never produced. Revision 3 closes that: every
value PPO consumes is either rebuilt from the authoritative replay or
recomputed from the bound checkpoint, and the sampled action is reproduced by
the frozen draw. Before a batch enters PPO the driver must rebuild, **from the
authoritative replay prefix** (engine state reconstruction up to each ply),
the player-view observation and the ordered legal-action list, then:

1. **ply coverage**: every learner-seat ply present in the replay has exactly
   one record for that `(game_index, seat)`; `ply_index` values are strictly
   increasing; there are no extra records.
2. **request identity**: the record's `request_id` equals `ply_index + 1`,
   and `seat` equals the replay's actor at that ply.
3. **observation binding** `[RR3-P1-1]`: the **stored observation payload**,
   typed and canonicalized, equals the rebuilt player-view observation
   field-for-field, and `splendor_core::observation_hash(stored observation)`
   equals both the record's `observation_hash` and the rebuilt observation's
   hash. A payload that differs from the rebuilt observation in any field
   fails the join even if its self-reported hash is self-consistent.
4. **legal-action equality**: the ordered legal-action list rebuilt from the
   replay prefix equals the record's `legal_actions` **element-for-element**,
   not merely as a set.
5. **action equality and draw reproduction** `[RR3-P1-1]`: the recorded
   `action` equals the action the replay records at that ply, **and** the
   frozen categorical draw — `decision_seed` derived from
   `(game_index, seat, request_id)` by the frozen formula, `u = (decision_seed
   >> 11) * 2^-53`, walking `legal_actions` in recorded order over the
   checkpoint's masked softmax — selects exactly the recorded `action`. The
   record's `sampling seed` field must equal that derived `decision_seed`.
6. **behaviour-value recomputation** `[RR3-P1-1]` `[RR4-P2-1]`: running the
   **bound checkpoint** (the record's `checkpoint SHA`, loaded and verified
   by SHA) over the rebuilt observation and the ordered legal actions must
   reproduce `old_log_probability` and `old_value` exactly — equality on the
   frozen `f64` bit pattern (no tolerance) — **under the frozen inference
   runtime contract below**. The recomputed values — not the sidecar's
   self-reported ones — are what enters PPO under all outcomes of this
   check; see the pre-registered contingency for the one non-fail-closed
   case.
7. **provenance and outcome**: `plan/config hash` and `checkpoint SHA` match
   the cycle being built; the game record's report/replay hashes match the
   artifacts on disk; the final result (outcome, final VP, truncated flag)
   agrees with the report.

`[RR4-P2-1]` **Inference runtime contract — frozen.** "Same deterministic
function" is only portable if the runtime is part of the contract. All
checkpoint forward passes in this round — rollout sampling, join checks 5–6,
and the G0b/G2/G3 evaluation agents alike — run under:

```text
mode            model.eval(); no autograd; no dropout (the D2 path uses
                dropout 0 already); no torch.compile; no cudnn/cublas
                autotuning — torch.backends.cudnn.deterministic = true,
                torch.backends.cudnn.benchmark = false,
                torch.use_deterministic_algorithms(True)
dtype           f32 parameters, f32 activations (the checkpoint's stored
                dtype); logits and log-softmax computed in f32, then cast
                to f64 only for hashing/comparison arithmetic
device          one named GPU recorded in the result artifact (rollout and
                recompute must use the SAME device class; a CPU recompute
                against a GPU rollout is not bit-comparable and is not
                attempted)
batch shape     batch dimension 1 (one decision per forward pass) for the
                join recompute — matching how the rollout itself ran, so
                kernel selection is identical on both sides
softmax helper  one shared implementation for rollout and recompute:
                log_softmax over the legal-action logits (mask = −inf on
                illegal entries), computed by the same code path in both
                the agent and the join driver, so the two sides cannot
                disagree by construction
finite values   all recomputed logits, log-probabilities, and values must
                be finite (torch.isfinite); any NaN/Inf is a batch-level
                abort regardless of any other check
```

`[RR4-P2-1]` **Pre-registered contingency for check 6.** The fail-closed
boundary of the join is unchanged: observation binding (3), legal-action
equality (4), action reproduction (5), and provenance (7) always abort the
batch on failure. For check 6 specifically, a **bitwise** mismatch between
recomputed and recorded `old_log_probability`/`old_value` may, despite the
runtime contract above, arise from a harmless kernel/runtime difference
(e.g. a driver or library update between collection and join). The
pre-registered resolution is:

- The **recomputed values always enter PPO** — this was already true in
  Revision 3 and does not change; there is no configuration in which the
  sidecar's self-reported numbers are trained on.
- The recorded values therefore serve as a **diagnostic**: the result
  artifact reports the count and max absolute deviation of
  `|recomputed − recorded|` per cycle, compared against a frozen diagnostic
  threshold of `1e-6` (log-probability) and `1e-5` (value).
- If ALL deviations are within threshold, the mismatch is recorded as
  `benign_runtime_drift` and the batch proceeds on recomputed values.
- If ANY deviation exceeds threshold, or any value is non-finite, the batch
  aborts — at that magnitude the sidecar was not produced by the claimed
  checkpoint/runtime, which is exactly the stale-sidecar failure mode.

This is a relaxation of Revision 3's unconditional bitwise abort for check 6
only, registered **before** any data exists; checks 3, 4, 5, and 7 remain
unconditionally fail-closed, and the PPO inputs remain recomputed values in
every case.

The failure mode this defends against is unchanged — a **stale sidecar from
an earlier cycle**, or a trajectory from a different game, silently entering
the batch and being trained on as if it were on-policy — now including the
subtler variant where such a sidecar is internally self-consistent but was
produced by a different checkpoint or observation than the ones it claims.
Every check compares the sidecar to what the **engine replay** and the
**bound checkpoint** say, not to what the sidecar claims about itself. A
failed join is a **batch-level abort**, not a warning.

Recomputation cost is bounded and accepted: checks 5–6 run one forward pass
per learner decision (~177k per the whole round), which is negligible against
the 4,096-game collection itself; the same forward pass serves both checks.

### Phase 3 — Trainer (Python)

PPO with clipped surrogate, GAE, masked categorical distributions, entropy
bonus, and the auxiliary score-difference head. Environment:
`local-artifacts/m24-torch-cu124`. `[RR4-P1-2]` The trainer is an **executor
of §5.3's frozen execution contract**, not its designer: minibatch size,
shuffle key, optimizer steps, AdamW parameters, LR waypoints, loss
reductions, and head initializers are all frozen there and bound into the
training plan hash.

### Phase 4 — Frozen Arena evaluation

See §5.4.

---

## Frozen constants

### 5.1 Training ply cap

```text
TRAINING_PLY_CAP = 150
```

Justification, measured on the 256 M07-vs-M07 games in the M25 corpus
(`local-artifacts/m25-generation/search-teacher-targets.json`):

```text
mean max ply 62.6   min 53   p50 63   p90 69   p99 71   max 72
```

`[R1-P1-4]` **This justification is insufficient on its own and is no longer
offered as sufficient.** The distribution above is M07 **self-play only**. It
says nothing about the learner, and the counter-evidence is direct: M35A
recorded two **deterministic non-terminations against M07**, both reaching the
engine's `MAX_MATCH_PLIES = 10_000` ceiling (M29A-v2, seed 300031 r0; M31A,
seed 300008 r1 — bound under `deterministic_nontermination_evidence` in
`benchmarks/m35a-retrospective-arena.result.json`). A neural policy facing M07
can therefore run **two orders of magnitude** past the M07-vs-M07 maximum of
72 plies.

`TRAINING_PLY_CAP = 150` is retained, but its defence is now empirical rather
than inherited:

- A cap is only sound if the truncation rate it induces is small. `G0b` (§5.4)
  promotes that rate from a report-only statistic to a **blocking gate**,
  measured in Phase 0 across **all four** opponent buckets.
- A learner that routinely stalls into the cap is not producing usable
  on-policy data; training on it would optimize the truncation return rather
  than the game.
- If `G0b` fails, the required response is to amend this section's cap and/or
  §5.2's truncation return **before** collection starts — never to collect
  first and rationalize afterwards.

The cap still bounds a runaway game at 1.5% of the formal ceiling, which
contains the cost even if the rate is higher than hoped.

### 5.2 Returns

`[R1-P1-1]` The return is a **centered outcome**. Revision 0 used a unipolar
outcome while placing truncation in `[-1, 0]`; that combination is
self-contradictory and is replaced here.

Completed game, viewer-relative (both seats receive the symmetric pair):

```text
win   : R = [+1, -1]
draw  : R = [ 0,  0]
loss  : R = [-1, +1]
```

Truncated game, for **both** seats, with `d = VP_viewer − VP_opponent`:

```text
R[0] = -0.5 + 0.5 * tanh( d / 4 )    ∈ [-1.0, 0.0]
R[1] = -0.5 + 0.5 * tanh(-d / 4 )    ∈ [-1.0, 0.0]
```

**Why Revision 0 was wrong.** It defined `outcome ∈ {1.0, 0.5, 0.0}` with
`loss = 0.0`, then asserted that truncation is "never worse than an outright
loss". The assertion is inverted: a truncation at `d = −8` scores `≈ −0.96`,
which is **strictly worse than losing at `0.0`**. The contract therefore
rewarded a player for abandoning a winnable game and taking a clean loss —
precisely the perverse incentive it claimed to prevent. Centering the outcome
at `0` removes the contradiction: **loss becomes the floor**, and truncation
sits between loss and draw where it belongs.

Properties of the corrected contract:

- `loss = −1 ≤ R_trunc ≤ 0 = draw < win = +1`. Truncation is never better
  than a draw, so there is no incentive to stall; and it is never worse than
  a loss, so there is no incentive to prefer an outright loss over a stall.
- Completed games are strictly zero-sum: `R[0] + R[1] = 0`.
- Truncated games satisfy `R[0] + R[1] = −1` **for every `d`**: both seats
  share a fixed `−1` penalty for wasting the game, then split it according to
  the VP margin. At `d = 0` each receives `−0.5`.
- A player far ahead who fails to convert receives `≈ 0` — far worse than the
  `+1` they should have taken. This is the penalty for not closing out.
- The pair is the correct zero-sum mirror: `R[1](d) = R[0](−d)`.

**Critic targets are the identical quantity**, so actor and critic optimize
against one and the same target:

| game outcome | value target |
|---|---|
| win  | `[+1, −1]` |
| draw | `[ 0,  0]` |
| loss | `[−1, +1]` |
| truncated, margin `d` | `[-0.5 + 0.5·tanh(d/4), −0.5 + 0.5·tanh(−d/4)]` |

`[R1-P1-1]` PPO usage rules, frozen:

- GAE and the advantage use **`value[:, 0]` only** — the viewer's own estimate.
- The value loss supervises **both** outputs; `value[:, 1]` is an auxiliary
  opponent-modelling signal, never a second advantage source.
- The rollout records `log p(a)` and **`value[0]`** as `old_log_prob` /
  `old_value`.
- The critic output is **not** clamped anywhere in the training path; the
  linear head must be free to exceed `[-1, 1]` while learning.
- Advantages are standardized within the batch.

### 5.3 PPO hyperparameters and trainer execution contract

```text
discount gamma                 1.0     (episodic; return is ground truth)
GAE lambda                     0.95
clip epsilon                   0.2
epochs per cycle                  4
learning rate             1e-4, cosine decay to 1e-5 over 8 cycles
optimizer                   AdamW
weight decay                  1e-4
gradient clip norm            1.0
entropy coefficient         0.010
value loss coefficient       0.500
aux score-diff coefficient   0.250
```

`[RR4-P1-2]` **Trainer execution contract.** The headline table above does
not by itself determine the update; two compliant implementations could
produce different policies from identical data. Revision 4 therefore freezes
the complete execution semantics — every remaining degree of freedom the
trainer had is now specified:

```text
epoch definition         one epoch = one full pass over the cycle's joined
                         decision set (~22k decisions/cycle average,
                         177k/8), visited in minibatches
minibatch size           512 decisions, logical batch dimension (padding
                         to the model's tensor layout is an implementation
                         detail and does not change the logical grouping)
minibatch partition      contiguous chunks of the shuffled order; the final
                         chunk may be smaller (incomplete minibatch is
                         kept, never dropped)
shuffle                  per epoch: indices sorted by SPLITMIX64 keyed on
                         (trainer_seed, cycle, epoch), a total order, so
                         the permutation is deterministic and reproducible
trainer_seed             40_260_830 (new, disjoint from every other seed
                         base in this document)
optimizer steps          one AdamW step per minibatch per epoch
                         (≈ ⌈22k / 512⌉ × 4 ≈ 176 steps per cycle)
AdamW parameters         betas = (0.9, 0.999), eps = 1e-8, amsgrad = off,
                         maximized = off; weight_decay = 1e-4 as above,
                         applied to all parameters (no param-group
                         exemptions, including the new heads)
gradient clipping        clip_grad_norm_ over ALL trainable parameters
                         jointly, max_norm = 1.0, after loss.backward(),
                         before optimizer.step()
scheduler                per-cycle waypoints, stepped ONCE at the START of
                         each cycle (before the first minibatch of that
                         cycle); lr(c) = 1e-5 + 4.5e-5 × (1 + cos(π (c−1)/7)):
                           c=1: 1.000000e-4   c=2: 9.554360e-5
                           c=3: 8.305704e-5   c=4: 6.501344e-5
                           c=5: 4.498656e-5   c=6: 2.694296e-5
                           c=7: 1.445640e-5   c=8: 1.000000e-5
                         implemented as an explicit table lookup, not a
                         torch scheduler object
loss reduction           total = policy + 0.010 × entropy_term_negated +
                         0.500 × value_loss + 0.250 × aux_loss, where each
                         term is the MEAN over the minibatch's decisions:
                           policy   = mean( −min(r_t·A_t, clip(r_t,1±ε)·A_t) )
                                      with r_t = exp(logp_t − old_logp_t),
                                      A_t the standardized advantage
                           entropy  = mean( −H(π(·|s_t)) )  (natural units,
                                      nats; subtracted via the + sign above)
                           value    = mean( 0.5 × (v_t[:,0]−R_t)²
                                            + 0.5 × (v_t[:,1]−R_t_opponent)² )
                           aux      = mean( (aux_t − target_t)² )
                         no sample weighting, no per-game weighting, no
                         masking of any term; f32 accumulate inside the
                         kernel graph, f64 only for the reported scalars
advantage                GAE(γ=1.0, λ=0.95) per trajectory with the
                         terminal return of §5.2 as bootstrap-free ground
                         truth, then standardized (subtract batch mean,
                         divide batch sd, computed over the CYCLE's full
                         decision set, frozen before the epochs begin and
                         not recomputed per minibatch)
dtype / device           parameters and optimizer state in f32 on the
                         training GPU; the environment is
                         local-artifacts/m24-torch-cu124
```

`[RR4-P1-2]` **Head initializers.** A seed and a draw order do not determine
weights; the initializer functions are frozen explicitly. Both new heads are
initialized from one `torch.Generator` seeded `20_260_829`, consumed in the
order critic-then-auxiliary (§3.1), with:

```text
critic head              nn.Linear(h=192, 192):  Kaiming-uniform with
                         a=sqrt(5)  (PyTorch default for nn.Linear) on the
                         weight, zeros on the bias; then the second
                         nn.Linear(192, 2) the same way
auxiliary head           nn.Linear(h=192, 1):  Kaiming-uniform with a=sqrt(5)
                         on the weight, zeros on the bias
```

The intent is "PyTorch default re-initialization, made explicit": the
initializer is `nn.init.kaiming_uniform_(w, a=math.sqrt(5))` and
`nn.init.zeros_(b)`, exactly what `nn.Linear.reset_parameters()` performs,
so an implementation that constructs fresh `nn.Linear` modules under the
seeded generator is compliant by construction.

`[RR4-P1-2]` **Plan-hash binding.** Every field in this execution contract
(minibatch size, shuffle key and trainer seed, step rule, AdamW parameters,
LR waypoints, loss formulas and coefficients, initializers) is part of the
training plan JSON whose canonical hash enters the rollout/training plan
hash of Phase 2 and is recorded in every cycle checkpoint's metadata and in
the result manifest. Changing any of them after review is an amendment
under §5.5, not an implementation detail.

`[R2-P1-4]` **Auxiliary score-difference head — full contract.** Revision 1
named only the coefficient `0.250` and left the target shape, loss, and
initialization to the implementer; those choices swing the auxiliary
gradient scale by orders of magnitude, so Q1's "margin enters only the
auxiliary head" was not yet an experiment contract. Frozen here:

```text
target            clamp((VP_viewer − VP_opponent) / 15, −1, +1)
head              scalar linear off the state embedding, no activation
loss              MSE, averaged over the batch
coefficient       0.250 (the row above)
VP readout        completed games: final VP from the report
                  truncated games: VP at the ply cap — the same snapshot
                  that defines d in §5.2, so completed and truncated games
                  differ only in the return, never in aux-target timing
normalizer        15 = the VP needed to win a two-player game, so a full
                  margin saturates the target; the clamp bounds it beyond
                  that, whatever the engine's maximum VP turns out to be
init seed         20_260_829 (shared with the critic head, per §3.1)
```

Rationale for two of these:
- `gamma = 1.0` because the return is a real terminal outcome, not a
  bootstrapped estimate; discounting would bias against long winning lines.
- `entropy coefficient > 0` is mandatory, not optional: the average position
  has ~30 legal actions of which ~19 are token-takes, and a policy that
  collapses onto a single take pattern early will not recover.

### 5.4 Gates

**G0 — Pre-flight throughput** (blocking, before collection) `[R2-P1-3]`
`[RR3-P1-2]` `[RR4-P1-1]`

Revision 1 said "measured per-match wall-clock for all four buckets, projected
total ≤ 72 h" without freezing the projection formula, warm-up, or
parallelism. Revision 2 froze a formula that nevertheless required **five**
timing means (RANDOM, HEURISTIC, M07, LEAGUE, SELF_PLAY) from a probe whose
four buckets merge heuristic and random — an inexecutable contract whose
RANDOM and HEURISTIC means had no defined denominators. Revision 3 made the
timing strata identical to the probe buckets but still left two design
choices to the executor: the "first 2 games" warm-up did not define the
intra-bucket order (so the diversified timed sample need not retain the 72/24
composition), and no opponent assignment existed at all. Revision 4 freezes
the complete game list — assignment, order, and warm-up — in G0b's probe
schedule; G0 consumes its timing fields. Frozen:

```text
instrumentation           the G0b probe schedule below (384 games) carries
                          per-match wall-clock
warm-up [RR4-P1-1]        per bucket, the predeclared warm-up subset is the
                          FIRST 32 games of that bucket's probe sequence
                          (ordinals 0..31); they are excluded from timing
                          but not from G0b counting. The subset is
                          composition-preserving by construction: DIVERSIFIED
                          ordinals 0..31 contain exactly 24 heuristic + 8
                          random (3:1), and LEAGUE ordinals 0..31 contain
                          each of the 9 opponents at least 3 times; every
                          bucket's timed remainder keeps the production
                          mixture
mean_t(bucket)            arithmetic mean wall-clock, in SECONDS [RR3-P1-2],
                          over the remaining 64 timed games of each bucket —
                          four means, one per probe bucket: DIVERSIFIED (48
                          heuristic + 16 random timed together; no separate
                          RANDOM/HEURISTIC means exist or are needed), M07,
                          LEAGUE (all 9 opponents), SELF_PLAY
parallelism J             the probe's actual worker count, recorded in the
                          Phase 0 result artifact
projected_parallel_hours  = ( Σ_bucket N_bucket × mean_t(bucket) ) / 3600 / J
                          [RR3-P1-2: seconds-to-hours conversion is part of
                          the formula; mean_t is recorded in seconds]
  N_bucket: DIVERSIFIED 512 (384 heuristic + 128 random), M07 1024,
            LEAGUE 1024, SELF_PLAY 1536 — the §3.3 totals, after [R2-P1-1]
G0_PASS = projected_parallel_hours <= 72
```

If the projection exceeds 72 h, the round must add parallelism, accept the
reduced N permitted in §5.5, or be re-designed — **it must not silently run
over and then re-scope**. The warm-up set was enlarged from Rev 3's "first 2"
to 32 per bucket precisely so that removing it cannot distort the mixture;
32 warm-up + 64 timed per bucket also keeps the probe a single 384-game
schedule shared by G0 and G0b unchanged in size.

**G0b — Pre-flight truncation rate** `[R1-P1-4]` `[R2-P1-3]` `[RR3-P1-3]`
`[RR4-P1-1]` `[RR4-P2-2]` (**blocking**, before collection)

Revision 1 fixed the threshold but left the probe design — sample sizes,
bucket split, seeds, and the pass rule's exact form — to the Phase 0
executor, so "measured truncation rate ≤ 1%" had no determinate meaning.
Revision 2 froze all of it but assigned **the same 96 seeds to all four
buckets**, which makes the four per-seed outcomes repeated measurements on
one randomization unit; the aggregate is then not `Bin(384, p)` in general,
and the exact four-bucket convolution does not describe the schedule.
Revision 3 kept the count rules and all operating characteristics unchanged
and restored the model they were computed under by giving the buckets
**disjoint seed ranges** — 384 distinct probe games. Revision 4 closes the
last executor choices: the exact opponent assignment and intra-bucket order
are frozen below, so two compliant executors run the **same 384 named
games** in the same order.

```text
probe size per bucket   = 96 games (4 × 96 = 384 total, all distinct games)
probe seeds [RR3-P1-3]  = disjoint 96-seed ranges per bucket, in bucket
                          order DIVERSIFIED, M07, LEAGUE, SELF_PLAY:
                            DIVERSIFIED  5_200_000 .. 5_200_095
                            M07          5_200_096 .. 5_200_191
                            LEAGUE       5_200_192 .. 5_200_287
                            SELF_PLAY    5_200_288 .. 5_200_383
                          Every probe game is an independent randomization
                          unit; the ranges are disjoint from the training
                          range (4_000_000 + game_index // 2), G2
                          (5_000_000..), and G3 (5_100_000..) ranges

bucket-local ordinal    = o = seed − bucket_seed_base  (o ∈ [0, 96))
learner seat            = seat (seed mod 2)  — equivalently (o mod 2) since
                          each bucket's base is even; recorded per game

opponent assignment [RR4-P1-1]
  DIVERSIFIED           o mod 4 ∈ {0, 1, 2}  -> agent-heuristic
                          o mod 4 = 3         -> agent-random
                        (72 heuristic + 24 random; the production 3:1 ratio,
                        interleaved so every contiguous prefix — including
                        the 32-game warm-up subset — is composition-
                        preserving)
  M07                   all 96 games vs M07 (frozen args, §I1)
  LEAGUE                opponent = LEAGUE_ORDER[o mod 9]
                        (96 = 9 × 10 + 6: M24-S2, M25-D2-v2, M28A, M28B,
                        M29A-v2, M31A receive 11 games; M32A, M33A, M34A
                        receive 10)
  SELF_PLAY             all 96 games learner vs learner (both seats = the
                        current snapshot)

intra-bucket order      = ascending seed within each bucket; buckets
                          themselves may be interleaved across workers, but
                          the (seed -> opponent, seat) mapping above is
                          order-independent and total
bucket rule (FAIL)      = a bucket observes >= 4 truncated games
aggregate rule (FAIL)   = the four buckets together observe >= 9 truncated
                          games
reporting               = per-bucket counts plus the exact Clopper–Pearson
                          95% upper bound per bucket; the decision is the
                          two count rules above, not the intervals

G0b_PASS = no bucket rule and no aggregate rule fires
```

`[RR4-P2-2]` **What the quoted probabilities are.** DIVERSIFIED and LEAGUE
deliberately mix opponents whose truncation probabilities need not be equal,
so their fixed-stratum counts are in general **Poisson-binomial**, not
`Bin(96, p)`, and the 384-game aggregate is `Bin(384, p)` only under a
homogeneous common-p model. The numbers below are therefore **homogeneous-p
reference operating characteristics** — a calibration for reading the gate,
not exact pass probabilities of the heterogeneous schedule. They remain
exactly as computed in Rev 2/3 (exact binomial arithmetic, unchanged):

```text
homogeneous-p reference (all 384 games share the stated p):
true p = 1.0%   P(bucket >= 4) = 1.61%   P(agg >= 9) = 1.64%
                family pass probability (all four buckets <= 3 and
                total <= 8, by exact convolution) = 93.2%
true p = 2.0%   family pass probability = 51.0%
true p = 5.0%   P(bucket >= 4) = 71.3%   P(agg >= 9) = 99.7%
```

At these small thresholds and a mean-preserving spread, heterogeneity moves
the reference values only modestly in either direction (numerical spot
checks at mean 0.96 expected truncations: splitting the diversified bucket
into p = 0.5% / 2.5% gives `P(bucket ≥ 4) = 1.56%`; 1.2% / 0.4% gives
1.60%; homogeneous gives 1.61%), so the table remains a usable calibration —
but it is a **reference model**, not a claim about the actual schedule. The
**decision procedure is the count rules above and is unaffected by this
relabelling** — the thresholds stay frozen unless a future pre-collection
amendment deliberately changes them.

`[RR4-P2-2]` **Sub-stratum reporting.** The Phase 0 result must report, in
addition to the four bucket counts: DIVERSIFIED split into heuristic (72)
and random (24); LEAGUE split into the nine per-opponent counts (11 or 10
games each, in `LEAGUE_ORDER`); SELF_PLAY and M07 reported as-is. These
splits are diagnostic — they do not add gate rules — and exist so that a
bucket failure can be attributed to a specific opponent stratum rather than
guessed at.

So a cap that truly holds the 1% line passes with ≈93% probability under the
homogeneous reference, a true 2% rate is a coin flip, and a true 5% rate —
the regime where §5.1's justification collapses — is caught essentially
always. The asymmetry is intentional: a false FAIL costs one redesign round,
a false PASS costs the whole 4,096-game commitment.

Rationale (unchanged from Revision 1): §5.1's original justification rested
only on M07-vs-M07 games (max 72 plies), while M35A shows a neural policy
facing M07 can reach the 10,000-ply engine ceiling. A high truncation rate
would mean the round is optimizing the truncation return instead of the
game, so this cannot remain a report-only statistic. **On `G0b` FAIL, amend
§5.1 (cap) and/or §5.2 (truncation return) and re-run Phase 0. Do not begin
collection.**

**G1 — Behaviour gate** (diagnostic-to-blocking on one clause)

| metric | requirement |
|---|---|
| non-termination rate in formal Arena | **0** (blocking) |
| truncation rate in training games | reported here; **gated at `G0b`**, not here |
| mean completed-game length | reported; expected 50–80 plies |
| mean VP differential vs M07 | reported |
| tokens + gold paid per VP gained | reported |
| fraction of games the learner reaches 15 VP | reported |

The behaviour block is deliberately narrow: only the non-termination clause
can fail the round. The rest are explanatory and **must not** be allowed to
override Arena results.

**G2 — Primary Arena gate** `[R1-P1-2]`

Revision 0 specified "a one-sided 95% lower bound" without naming the
statistic, the variance source, or the seed list. Under the contract this
project has actually used before — M27A's deterministic one-sided Hoeffding
bound over a block-delta range of `[-10000, 10000]` bps — that phrasing is
not merely underspecified, it is **unsatisfiable in practice**:

```text
Hoeffding margin = 20000 × sqrt(ln(20) / (2n)) bps

  n = 32  ->  4327 bps   (M27A's own frozen constant: 4331 bps)
  n = 96  ->  2498 bps
  n = 128 ->  2164 bps
```

With `n = 32`, requiring `lower > 0` would demand a **true improvement larger
than ~43 percentage points**. Hoeffding is therefore abandoned for this gate:
it is distribution-free, and the price of that guarantee is a bound too loose
for the effect sizes a policy-gradient round can produce.

Frozen contract:

```text
statistical unit   = paired seed block
seed blocks        = 128
rotations per seed = 2
plans              = cycle-8 checkpoint  vs M07
                     M25-D2-v2 baseline  vs M07
total matches      = 128 × 2 × 2 = 512
test               = one-sided paired Student-t
alpha              = 0.05
```

```text
C = cycle-8 checkpoint,  B = M25-D2-v2 baseline
match score:  win = 1.0   draw = 0.5   loss = 0.0

score(C_i) = 10000 × mean(two rotation match scores)
score(B_i) = 10000 × mean(two rotation match scores)
delta_i    = score(C_i) - score(B_i)

mean_delta = mean(delta_i)
sample_sd  = sqrt( sum( (delta_i - mean_delta)^2 ) / (n - 1) )
lower_95   = mean_delta - 1.656940343542 × sample_sd / sqrt(128)
```

`1.656940343542` is the one-sided 95% Student-t critical value at `df = 127`;
it is frozen here so the gate cannot be recomputed with a different constant
after the fact.

```text
G2_PASS = lower_95 > 0 bps
          AND completed_seed_blocks        = 128
          AND completed_matches            = 512
          AND aborted                      = 0
          AND candidate_faults             = 0
          AND deterministic_nonterminations = 0
```

Additional terms, all frozen:

- **Evaluation seeds are new and fully isolated from training**:
  `5_000_000 .. 5_000_127`. Training uses `4_000_000 + game_index // 2`
  (§3.4); the two ranges are disjoint by construction.
- Cycle-8 and baseline run on **identical seeds, identical rotations, and
  identical M07 runtime arguments**.
- Both models under test use **deterministic `argmax`** in the formal Arena —
  never the categorical sampling used during training.
- If **any rotation is missing, the whole seed block is incomplete**, and an
  incomplete block makes `G2_FAIL` directly. No partial-block accounting.
- **No early stopping**, and **no re-selecting a checkpoint after seeing
  cycles 1–7** (see Q2 in §Open questions).
- `σ = 4000 bps` is recorded **only** as sample-size design evidence. It must
  **not** be substituted for this round's `sample_sd` and must not be used as
  a known-variance Normal test.
- Bootstrap intervals, medians, and counts of positive `delta_i` may be
  reported as diagnostics but carry **no** decision weight.
- No flooring, clamping, or integer conversion before the decision: compute in
  `f64`, and only round for presentation (two decimals, and integer bps).

Design evidence for `n = 128` (σ = 4000 bps, the value implied by M35A's
observed 64-match spread of ≈ 555 bps; indicative only, per the clause above):

| seed blocks | typical one-sided 95% margin | power at a true +10 pp improvement |
|---|---|---|
| 32 | 11.99 pp | 39.7% |
| 96 | 6.78 pp | 78.4% |
| 100 | 6.64 pp | 79.9% |
| **128** | **5.86 pp** | **87.9%** |

The operative defect in Revision 0 was not only its ~12 pp margin at `n = 32`,
but that a genuine 10 pp gain would have been **missed about 60% of the time**.
`n = 128` is the smallest scale at which the gate measures what it claims to.

The gate remains a **paired improvement over the initialization**, not an
absolute requirement to beat M07. Beating M07 outright is the separate
promotion question and is out of scope (§ Scope and non-goals).

**G3 — Secondary Arena gate** `[R1-P1-3]`

Revision 0 named neither the seed list, nor whether the baseline also runs
the full league, nor how pairings aggregate. Frozen contract:

```text
league opponents    = the 9 M35A checkpoints (SHA-bound in §3.3)
seed blocks         = 32 per pairing
rotations per seed  = 2
matches per pairing = 64
pairings            = 9
arms                = cycle-8 AND D2-v2 baseline, each running all 9
total matches       = 9 × 64 × 2 = 1152
evaluation seeds    = 5_100_000 .. 5_100_031
```

Answers to the specific questions raised in review:

- **Seed isolation.** `5_100_000 .. 5_100_031` is disjoint from both the
  training range (`4_000_000 + game_index // 2`) and the G2 range
  (`5_000_000 .. 5_000_127`).
- **Does the baseline run the full nine?** **Yes.** Without both arms over the
  same nine pairings there is no paired comparison, and G3 would reduce to an
  unpaired aggregate against a historical number.
- **Aggregation.** Every pairing contributes 64 matches, so pairings are
  **equally weighted**; no re-weighting by games played.
- **Identical conditions.** Cycle-8 and baseline use the **same seeds,
  rotations, and opponent checkpoints** for every pairing.
- **The `D2-v2 vs D2-v2` self-play pairing.** In the baseline arm this pairing
  is a self-play match with expected score `0.5`. It is **retained, not
  dropped**: in the cycle-8 arm the same slot becomes `cycle-8 vs D2-v2`, so
  the paired delta there measures improvement over the initialization at its
  own starting point — which is exactly the quantity G2 tests. It is flagged
  as a self-play pairing in the report so it is not read as a league result.
- **Non-termination.** Any deterministic non-termination, in either arm,
  makes **G3_FAIL**. It is never absorbed into an excluded-prefix bucket to
  rescue a result; this follows how M35A recorded its two non-terminations as
  `NO 64-GAME RESULT` rather than as scored games.

```text
G3_PASS = aggregate_score(cycle-8) >= aggregate_score(baseline)
          AND completed_pairings = 9 in both arms
          AND aborted            = 0
          AND candidate_faults   = 0
```

Per §5.4 of Revision 0, G3 carries **no lower-bound requirement**; the
aggregate comparison is a point-estimate condition. `[R2-P2-2]` `[RR3-P2-1]`
When an interval is reported alongside it, the statistical unit is frozen
here — not chosen per report:

```text
interval unit   = the 32 cross-opponent seed aggregates. For each seed
                  block i ∈ [0, 32): delta_i = mean over the 9 pairings of
                  ( score(cycle-8 arm, pairing, i) − score(baseline arm,
                  pairing, i) ), each score being that block's two-rotation
                  mean in bps
interval        = one-sided 95% Student-t lower bound over the 32 deltas,
                  df = 31, critical value 1.695518782546 (frozen; computed
                  by the same independent incomplete-beta implementation
                  that reproduced the G2 constant 1.656940343542 to 12
                  decimals)
```

Revision 2 froze the unit as the 288 `(pairing, seed-block)` deltas with
`df = 287`. That schedule reuses the same 32 seeds across all nine opponent
strata, so the 288 deltas are repeated measurements on 32 randomization
units, and the df-287 interval understates uncertainty (pseudoreplication).
The 32 aggregates — one per seed, each averaging the nine within-seed
pairing deltas — are the independent units the schedule actually
randomizes; `df = 31` follows. The within-seed average is unweighted across
pairings because every pairing contributes exactly 64 matches. As in G2,
the interval carries **no** decision weight; `G3_PASS` is the point-estimate
condition above.

### 5.5 Amendment rules

- Any change to the §Frozen constants after review but before collection: permitted,
  must be recorded as an amendment in this document with the reason. Revisions 2,
  3, and 4 are all such amendment records: every `[R2-*]` / `[RR3-*]` /
  `[RR4-*]` site names the review finding that motivated it, and no change
  was made after observing any collected result (none exists).
- Any change after collection has begun: forbidden.
- Reducing N below **2,048** games is not permitted; below that the round is
  not worth running and must be re-designed instead.

---

## Implementation checkpoint (2026-08-30)

The first executable M39A checkpoint now exists in the worktree. It includes:

- a plan-hash-bound D2-v2 actor load with a fresh two-output linear critic and
  auxiliary VP-margin head;
- exact SplitMix64 categorical sampling, cycle-local opponent schedule,
  per-seat GAE, population advantage normalization, deterministic total-order
  shuffle, and fully explicit AdamW/PPO execution;
- an Arena v0.5 M39A policy process with categorical training mode and argmax
  evaluation mode;
- a resumable cycle collector and the exact 384-game Phase 0 executor;
- a Rust referee-side materializer which fully verifies replay/report/seed and
  scheduled runtime identities, rebuilds every player-view observation and
  ordered legal-action list, checks action and sampling seed, and emits the
  only batch schema accepted by the trainer;
- machine evaluators for the frozen G2 and G3 paired contracts.

The training ply cap does not create an invalid partial replay. Arena always
runs to a legal terminal state and archives the full replay. If the full game
exceeds 150 plies, the authoritative batch takes only the first 150 and derives
the truncation score from the referee state before ply 150.

## Validation and evidence

Implementation smoke evidence (local-only artifacts, not formal evidence):

- Python contract/model/trainer/probe/gate tests: 13 passed;
- full historical GPU test directory: 147 passed / 6 failed. All six failures
  are in unchanged M28B compute-repair tests: four require NVML telemetry when
  CUDA is visible, one old BMM gradient tolerance observed `6.10e-5 > 5e-5`,
  and one Windows text round-trip changes a frozen control-report byte hash;
  none touches an M39A file or contract;
- Rust M39A tests: cross-language plan/seed vectors, frozen learner seats, and
  a real random-game authoritative join plus observation-tamper rejection;
- CPU collection -> Rust materialization -> PPO update passed;
- CUDA collection on RTX 4060 Laptop GPU -> Rust materialization -> CUDA PPO
  update passed (36 decisions, 4 epochs); behaviour recomputation was 27
  bit-exact plus 9 benign drifts, max log-probability deviation
  `4.44e-16`, max value deviation `2.78e-17`;
- local smoke roots: `local-artifacts/m39a-collector-smoke/` and
  `local-artifacts/m39a-cuda-smoke-r2/`.

Formal execution evidence still to be recorded:

- exact commands and exit codes for every phase;
- tracked config / gate / result JSON with file SHA-256 and semantic hashes;
- checkpoint SHAs for all 8 cycle checkpoints and the D2-v2 baseline;
- the G0 throughput table;
- the full G1 behaviour table;
- G2 and G3 arena reports with per-seed-block W/T/L;
- local artifact paths under `local-artifacts/`;
- explicit separation of implementation smoke, offline diagnostics, and
  competitive measurement.

---

## Result and decision

*Empty until execution. The decision vocabulary is fixed by `AGENTS.md`:*

| G2 | G3 | decision |
|---|---|---|
| PASS | PASS | `M39A_RL_IMPROVEMENT_CONFIRMED` — Arena authorized for the next round |
| PASS | FAIL | `M39A_IMPROVES_VS_M07_ONLY` — M07 gain real, league transfer weak |
| FAIL | PASS | `M39A_LEAGUE_ONLY` — improvement not detectable against M07 |
| FAIL | FAIL | `M39A_NO_IMPROVEMENT` — negative result, route reconsideration |

A `FAIL` on G2 is a valid result and must not trigger a seed, gate,
threshold, or opponent-mix change followed by a result-oriented rerun.

---

## Known limitations

1. **Outcome-only returns are label-sparse.** 4,096 games yield 4,096 outcome
   labels for ~177k learner decisions `[R2-P2-1]`. The value head is the
   credit-assignment mechanism; if it fails to generalize, the advantage
   estimates will be weak regardless of PPO tuning. Mitigation: the
   auxiliary score-difference head and the `gamma = 1.0` episodic return.
   This is the round's main technical risk.
2. **M07 moves are expensive.** M07 runs 4 determinizations × a 2000-node
   continuation search per root action. 1,024 M07 games are the dominant cost
   of the round. G0 exists to bound this.
3. **Self-play in a two-player zero-sum game can oscillate.** Eight cycles is
   short. A learning curve that peaks mid-training is a finding, not a
   failure to be patched.
4. **No search at inference.** M24.5 diagnosed `SEARCH_BOTTLENECK`; M39A does
   not add search. It tests whether environment reward alone closes part of
   the gap. Adding search back on top of a trained value head is a separate
   round.
5. **Deterministic non-termination is an unresolved engine property.** M35A
   recorded two games reaching `MAX_MATCH_PLIES = 10_000`. M39A detects,
   penalizes, and reports it; it does not fix the engine.
6. **Cycle-8-only gating forfeits a potentially better intermediate
   checkpoint.** This is deliberate — see Q2 in §Open questions.
7. **Throughput datapoint is weak.** The only historical whole-Arena timing
   evidence is M35A's ~6.4 h for 1,088 matches with unrecorded parallelism.
   G0 exists because this is not a sound basis for a 4,096-game commitment.
8. **`[R1-P1-1]` The critic starts from zero, not from a warm start.** D2-v2
   was trained with `value_loss_weight = 0.0`, so its value head never
   received gradient and is discarded outright; the replacement head is
   randomly initialized. This makes P1-1 cheap to fix, but it means credit
   assignment — already the round's main technical risk per item 1 — begins
   with no prior value estimate whatsoever. If the critic fails to learn
   within eight cycles, advantage estimates will be near noise and the round
   will read as `M39A_NO_IMPROVEMENT` for reasons unrelated to the learning
   signal under test.
9. **`[R1-P1-2]` Evaluation cost rises from 64 matches to 1,664.** G2 now
   costs 512 matches and G3 1,152. At M35A's observed ~6.4 h per 1,088 matches
   with unrecorded parallelism, the evaluation phase alone is roughly 10 h,
   **in addition to** the 4,096 collection games bounded by G0. This is the
   direct price of replacing an unsatisfiable gate with a measurable one, and
   it is recorded here rather than absorbed silently.

---

## Review R1 — findings and disposition

Independent review of Revision 0, 2026-08-29. Verdict **`NEEDS_REVISION`**;
`P0 = 0`, `P1 = 5`, `P2 = 0`. Training, Arena, data collection, and promotion
remained unauthorized throughout, and none were performed.

| # | finding | disposition |
|---|---|---|
| P1-1 | Returns and critic are incompatible. `loss = 0.0` against truncation `∈ [-1, 0]` inverts the document's own "never worse than an outright loss" claim; and the D2-v2 critic terminates in `nn.Sigmoid()`, bounding it to `[0, 1]²` where negative returns are unreachable. | **Accepted.** Returns recentred to `{−1, 0, +1}` (§5.2). Critic replaced with a 2-unit viewer-relative **linear** head (§3.1). |
| P1-2 | G2 named no statistic, no variance source, and no seed list. Under the contract this project has actually used — M27A's `n = 32` Hoeffding bound over `[-10000, 10000]` bps — `lower > 0` implies a ~43 pp center requirement. | **Accepted.** Hoeffding abandoned for G2. Frozen 128-block one-sided paired Student-t contract with isolated seeds and fail-closed completeness rules (§5.4). |
| P1-3 | No frozen evaluation schedule: no seed list, no training/eval seed isolation, G3's baseline arm undefined, aggregation unspecified, non-termination handling unspecified. | **Accepted.** G2 and G3 frozen with disjoint seed ranges; baseline runs all nine pairings; pairings equally weighted; the `D2-v2 vs D2-v2` self-play pairing retained with a stated interpretation; non-termination fails the gate (§5.4). |
| P1-4 | The 150-ply cap is justified only by M07-vs-M07 games, while M35A shows neural policies reaching the 10,000-ply ceiling **against M07**; the truncation rate was report-only, so mass truncation could not stop the round. | **Accepted.** The original justification is explicitly withdrawn as sufficient. New blocking `G0b` gates the truncation rate at ≤ 1% across all four buckets; Phase 0 extended (§5.1, §5.4, Phase 0). |
| P1-5 | Trajectory provenance specified only as "JSONL keyed by `game_index`" — no config binding, no checkpoint SHA, no sampling seed, no report hash, no join validation. A stale sidecar could enter PPO unnoticed. | **Accepted.** Frozen decision- and game-level record schema plus fail-closed join validation (Phase 2). |

### Additional finding raised during revision

Not flagged in review, recorded here because it changes the cost of P1-1: the
D2-v2 critic was trained with `value_loss_weight = 0.0`
(`training/m17_gpu/splendor_gpu/m25_exp_d2.py:318`), so it never received
gradient. Replacing it therefore costs **no warm-start capability** — there
was no trained value estimate to inherit. The P1-1 fix is cheap rather than
disruptive, and the fact is recorded in checkpoint metadata as
`base_value_head_loaded = false`.

Relatedly, the viewer-relative output semantics this round freezes are already
the project's existing convention rather than a new invention:
`m25_dataset.py:443` defines `viewer_value = [1 - ranks[actor], 1 -
ranks[1 - actor]]`, i.e. index 0 is the current viewer. M39A keeps that
ordering and changes only the quantity being predicted (win probability →
centered outcome) and the activation (`Sigmoid` → linear).

### Verification performed during revision

- `t_ppf(0.95, df = 127) = 1.656940343542` — recomputed independently from an
  incomplete-beta implementation; agrees with the frozen constant to 12
  decimal places.
- Hoeffding margins and the `n = 32 / 96 / 100 / 128` power table recomputed
  independently; agree with the values tabulated in §5.4.
- `benchmarks/m35a-retrospective-arena.manifest.json` SHA-256 recomputed and
  confirmed as `2f29a06cd2385c6a39ddec0e543d5c7ff982caa3d2568181a6d11f2a71a4a1cd`.
  The nine-checkpoint set is read from that manifest, not restated.
- M35A non-termination evidence re-read and confirmed: 2 entries, seeds
  300031 r0 (M29A-v2) and 300008 r1 (M31A).

### Not addressed by this revision

No Arena was run, no data collected, no model trained, and **this revision
changed no product code**.

**Amendment 2026-08-29 (after review R2, before re-review).** The baseline
advanced `733401c` -> `573434f` while this document was pending re-review.
Five engineering-only commits landed; one group of them *is* product code, so
it is declared here rather than left implicit:

- `419f290` — the integration test accompanying `733401c`
  (`crates/splendor-arena/tests/process_program_resolution.rs`), which was
  untracked and unexecuted when this section was first written. It is now
  tracked, and it passes.
- `31ec366`, `a4fa657` — **product code**: `resolve_program` now prefers this
  host's native spelling over a stale foreign binary, and on Windows bridges
  only *extensionless* names (`.cmd`/`.bat`/`.EXE` are left alone). This
  changes how a registry `program` path becomes a spawned binary, which
  Phase 4 depends on. It does not change game rules, seeds, replays, or any
  frozen constant in this document.
- `69b07a1` — Rust 1.94 clippy debt in `splendor-cli` (no behavior change).
- `573434f` — four symlink tests in `splendor-cli` gated `#[cfg(unix)]`
  (test-only; they previously failed on Windows because only the link-creation
  line was gated).

Re-review should read `573434f` as the baseline. Evidence: `handoff.md`
(changelog 2026-08-29, final three entries) and
`local-artifacts/m39a-review-r1/`.

---

## Review R2 — findings and disposition

Verdict `NEEDS_REVISION`, `P0 = 0 / P1 = 4 / P2 = 2` (2026-08-29). Every
factual claim below was verified against the current tree before this
revision was written; the verification is recorded per finding.

| # | Finding | Disposition | Where |
|---|---|---|---|
| P1-1 | Global bucket formula + 512-game contiguous cycles produced a strong curriculum (cycle 1 = random+heuristic only, cycles 2–3 = M07 only, …), contradicting "mix proportional within every cycle" | Bucket assignment re-frozen as a **cycle-local** function; totals unchanged; every cycle now carries the full mix | §3.3, §3.5 |
| P1-2 | Trajectory contract assumed `request_id` contiguous from 0 within the learner seat, but the Arena starts at 1 and increments **globally** per ply; schema lacked `seat`/`ply_index`/`observation_hash`; self-play could not share one sidecar; join validated the sidecar against itself, not against the engine; plan-hash and sampling-seed derivations unspecified | Schema re-frozen around engine semantics (`ply_index` is the join key, `request_id = ply_index + 1` recorded verbatim); per-seat sidecars; join rebuilt **from the replay prefix** with observation-hash, ordered legal-action, and per-ply action equality; canonical hash and SPLITMIX64 sampling-seed formulas frozen | §Phase 2 |
| P1-3 | G0/G0b left probe sample sizes, heuristic/random split, per-bucket vs aggregate rule, probe seeds, estimate form, and the projection formula to the Phase 0 executor | All frozen: 96/bucket (384 total), 72/24 split, seeds `5_200_000..5_200_095`, two count rules with exact binomial operating characteristics, Clopper–Pearson reporting, warm-up/parallelism/projection formula for G0 | §5.4 G0, G0b |
| P1-4 | Auxiliary head defined only by a coefficient; target normalization, truncation timing, loss, activation, and init seed unspecified | Full contract frozen: `clamp(ΔVP/15, −1, +1)`, scalar linear head, MSE, VP at cap for truncated games, init seed `20_260_829` shared with the critic head in a fixed draw order | §3.1, §5.3 |
| P2-1 | 355k decisions double-counted: 63 is whole-game actor-plies, not per-seat | Corrected to ≈177k with the per-seat arithmetic shown | §3.3 |
| P2-2 | G3's "same interval machinery as G2" did not define the interval's statistical unit | Unit frozen as the 288 paired (pairing, seed-block) deltas; df = 287 critical value `1.650180210723` frozen | §5.4 G3 |

### Verification performed during this revision

- **P1-1 arithmetic.** The Revision 1 formula was re-derived: with
  `g = game_index mod 4096` and 512-game contiguous cycles, cycles land
  exactly on bucket boundaries (0–511 → random+heuristic, 512–1535 → M07,
  …), confirming the reviewer's cycle table. Under the cycle-local formula
  `league_ordinal` also runs over a consecutive `0..1023` range, so the
  114/113 per-opponent split is unchanged; `1024 = 9 × 113 + 7` re-checked.
- **LEAGUE_ORDER.** The name does not exist in code; it is now defined in
  §3.3 as the registry insertion order, verified against
  `m35a_registry.py:53-166` (`M24-S2 … M34A` in that order).
- **P1-2 engine contract.** `request_id` semantics read from source:
  `controller.rs:195` (`request_id_starts_at_one` — first value 1, then 2)
  and `runner.rs:461` (one `next_request_id()` per ply, seat-independent).
- **G0b operating characteristics.** All probabilities computed exactly by
  binomial convolution, not Poisson approximation: at p = 1%,
  `P(bucket ≥ 4) = 1.61%`, `P(agg ≥ 9) = 1.64%`, family pass 93.2%; at
  p = 2%, family pass 51.0%; at p = 5%, `P(bucket ≥ 4) = 71.3%`,
  `P(agg ≥ 9) = 99.7%`. The aggregate threshold was raised from 8 to 9
  because it cut the false-FAIL rate at p = 1% from 8.2% to 6.8% while
  losing ≈0.2 pp of detection power at p = 5%.
- **df = 287 critical value.** Computed with an independent
  incomplete-beta (Lentz continued-fraction) implementation; the same
  implementation reproduces the frozen df = 127 constant `1.656940343542`
  to 12 decimal places, then yields `1.650180210723` for df = 287.

### Passed unchanged in this review

The reviewer explicitly confirmed, and Revision 2 does not touch: the
centered `{−1, 0, +1}` return; the two-output viewer-relative linear critic;
D2 `value.*` non-loading; the G2 128-block paired Student-t contract with
its seed, rotation, argmax, and fail-closed completeness terms; G3's
two-arms-over-nine-opponents 1,152-match schedule; the Q1/Q2/Q3 direction
decisions; and the M35A manifest SHA binding.

---

## Revision 2 independent re-review — findings

Independent re-review on 2026-08-29. Verdict **`NEEDS_REVISION`**;
`P0 = 0`, `P1 = 3`, `P2 = 2`. This was a document/source/statistical-contract
review only: no training, Arena run, data collection, or promotion occurred.

### Verified closures and independent calculations

- `[R2-P1-1]` is closed. The cycle-local allocation is exactly
  `16 / 48 / 128 / 128 / 192` in every 512-game cycle. Across eight cycles,
  league counts are `114` for the first seven registry entries and `113` for
  the final two; seat counts are `57/57` for the first seven and differ by one
  for the final two.
- `[R2-P1-4]` is closed. The auxiliary target, head shape, loss, VP readout,
  normalization, coefficient, and initialization order are all frozen.
- `[R2-P2-1]` is closed. The corrected learner-decision estimate is
  approximately `177k`; the former `355k` figure double-counted actor plies.
- The `request_id` fact is correct: the Arena starts it at 1 and increments it
  once per global ply (`controller.rs:195`, `runner.rs:461`). The M35A manifest
  hash and `LEAGUE_ORDER` insertion order were also rechecked against the
  current tree.
- Independent SciPy recomputation reproduced the stated G0b numbers
  (`93.2319%`, `50.9462%`, `71.2769%`, `99.7133%`) **conditional on the
  independent-binomial model**, and reproduced the df-287 one-sided critical
  value `1.650180210723`. The findings below concern whether the frozen
  schedules satisfy those models, not arithmetic mistakes in the constants.

### Findings requiring Revision 3

| # | Severity | Finding | Required closure |
|---|---|---|---|
| RR2-P1-1 | P1 | **The trajectory join does not bind every value consumed by PPO.** Step 3 checks only `hash(rebuilt observation) == record.observation_hash`; it never checks the stored `record.observation` against the rebuilt observation or recomputes the hash from the stored payload. A changed observation payload can therefore pass while PPO trains on it. `old_log_probability` and `old_value` are self-reported and never recomputed from the bound checkpoint, even though the PPO ratio and GAE consume them; the same replay action can occur under different logits/values. The recorded sampling seed is also absent from the six join checks. | Compare the stored observation to the rebuilt typed `Observation` and require its existing `splendor_core::observation_hash` to equal the `RequestMeta.observation_hash`. Recompute and validate the frozen sampling seed. Run the bound checkpoint over the authoritative observation and ordered legal actions, then either use recomputed `old_log_probability` / `old_value` for PPO or fail closed on a frozen numeric comparison; also verify that the deterministic categorical draw reproduces the replay action. |
| RR2-P1-2 | P1 | **G0 is not an executable dimensional contract.** The probe has four truncation buckets because heuristic/random are combined, but the projection requires five separate `N_bucket × mean_t(bucket)` terms. `mean_t` is defined as the remaining 94 games of each four-way bucket, so no independent RANDOM and HEURISTIC means exist. The unit of `mean_t` is also absent while the result is named hours. | Freeze either five timing strata or one combined diversified timing term. If retaining separate RANDOM/HEURISTIC terms, define their warm-up removal and denominators separately. Freeze wall-clock units and include the seconds-to-hours conversion (or explicitly record means in hours). |
| RR2-P1-3 | P1 | **G0b's exact family operating characteristics do not apply to its frozen schedule.** All four buckets reuse the same 96 seeds. The four outcomes at one seed are repeated/common-random-number measurements and need not be independent, so the aggregate count is not generally `Bin(384,p)` and the four-bucket convolution is not exact. Per-bucket binomial/Clopper-Pearson calculations remain interpretable, but the aggregate and family claims that justify the blocking gate do not. | Give the four buckets disjoint 96-seed ranges (384 unique probe seeds) if the independent-binomial calculation is to remain the contract, or retain shared seeds and replace the aggregate/family model with a pre-registered clustered/paired analysis whose operating characteristics match that schedule. |
| RR2-P2-1 | P2 | **G3's interval uses pseudoreplicated units.** The df-287 constant is numerically correct for 288 independent observations, but the schedule reuses 32 seeds across all nine opponent strata. The 288 `(pairing, seed)` deltas are not 288 independent randomization units. This does not alter `G3_PASS`, because the interval is diagnostic only, but it makes the reported uncertainty too optimistic. | With the current shared-seed schedule, average the nine opponent deltas within each seed and use 32 cross-opponent seed aggregates (`df = 31`, one-sided critical value `1.695518782546`), or pre-register a cluster-aware alternative. |
| RR2-P2-2 | P2 | **Three prose contracts drift from the frozen design.** `for cycle in 1..8` conventionally denotes seven iterations; I4 still names a seeded torch sampler although §Phase 2 says no torch RNG is used for sampling; and the schema says `game_index` repeats across cycles although the frozen global range is `0..4095`. | Write the loop as an explicitly inclusive eight-cycle range, make I4 name the SPLITMIX64 categorical sampler, and correct the game identity rationale without weakening the `game_id + game_index` binding. |

### Re-review verdict

Revision 2 closes the cycle schedule, auxiliary-head contract, and decision
count. It only partially closes the trajectory and G0/G0b findings, and the
chosen G3 interval unit is not valid for the shared-seed schedule. Therefore:

```text
M39A_REVISION_2_RE_REVIEW = NEEDS_REVISION
P0 = 0
P1 = 3
P2 = 2
TRAINING_AUTHORIZED = NO
ARENA_AUTHORIZED = NO
DATA_COLLECTION_AUTHORIZED = NO
PROMOTION_AUTHORIZED = NO
```

The next permissible action is a **Revision 3 document-only amendment** that
closes the five findings above, followed by another independent re-review.

---

## Revision 3 — findings and disposition

Document-only amendment on 2026-08-29, closing all five Rev 2 re-review
findings. No training, Arena run, data collection, or promotion occurred; no
code changed; the baseline is unchanged at `573434f`.

| # | Finding | Disposition | Where |
|---|---|---|---|
| RR2-P1-1 | The join did not bind the stored observation, `old_log_probability`, `old_value`, or sampling seed; stale/self-consistent sidecars could feed PPO | The stored **observation payload** is now compared to the rebuilt player view, its engine `observation_hash` validated on both sides (check 3); the derived `decision_seed` is recomputed and matched to the stored field, and the frozen categorical draw over the bound checkpoint's masked softmax must reproduce the recorded action (check 5); the bound checkpoint's forward pass must reproduce `old_log_probability` and `old_value` bit-exactly, and the **recomputed** values — not the sidecar's — enter PPO (check 6) | Phase 2, join checks 3/5/6 |
| RR2-P1-2 | G0 needed five timing means from four probe buckets; units absent | Timing strata collapsed to **four**, identical to the probe buckets (the diversified bucket's combined mean covers heuristic+random; no separate RANDOM/HEURISTIC means exist); `mean_t` frozen in **seconds** with the `/3600` conversion inside the projection formula | §5.4 G0 |
| RR2-P1-3 | G0b reused one 96-seed set across four buckets; the `Bin(384,p)` / convolution model does not describe that schedule | Buckets given **disjoint** 96-seed ranges (`5_200_000..5_200_383`, 384 distinct probe games); count rules, thresholds, and operating characteristics unchanged — they now describe the schedule exactly | §5.4 G0b |
| RR2-P2-1 | G3's df-287 interval pseudoreplicates 288 deltas over 32 shared seeds | Interval unit re-frozen as the **32 cross-opponent seed aggregates** (within-seed mean over the nine pairing deltas, unweighted); `df = 31`, critical value `1.695518782546` frozen | §5.4 G3 |
| RR2-P2-2 | Three prose drifts: `1..8`, torch sampler in I4, `game_index` "repeats across cycles" | §3.5 now writes the loop as an explicit inclusive eight-iteration list; I4 names the SPLITMIX64 categorical sampler (no torch RNG); the schema's game-identity rationale corrected — `game_index` is unique round-wide; `game_id` is still recorded because the report binding is keyed by it | §3.5, I4, Phase 2 |

### Verification performed during this revision

- **df = 31 critical value.** `1.695518782546` recomputed independently with
  an mpmath (30-digit) incomplete-beta implementation; the same code path
  reproduces the frozen df = 127 constant `1.656940343542` and the df = 287
  constant `1.650180210723` to 12 decimal places. SciPy `t.ppf(0.95, 31)`
  agrees.
- **G0b operating characteristics under disjoint seeds.** The Rev 2 numbers
  were recomputed exactly (binomial pmf, four-bucket capped convolution):
  at p = 1%, `P(bucket ≥ 4) = 1.61%`, `P(agg ≥ 9) = 1.64%`, family pass
  93.23%; at p = 2%, 50.95%; at p = 5%, `P(bucket ≥ 4) = 71.28%`,
  `P(agg ≥ 9) = 99.71%`. Unchanged from Rev 2 — the seeds change restored
  the model's applicability, not its arithmetic.
- **Engine facts re-verified.** `request_id` starts at 1 and increments once
  per global ply (`controller.rs:195`, `runner.rs:461`); the
  `RequestAction` message carries the engine's `observation_hash`
  (`runner.rs:436`, `hash.rs:331`); the Arena report exposes the seed
  commitment binding `(game_id, player_count, seed, ruleset_fingerprint)`
  (`report.rs:150`, `seed_commitment.rs:81`) — supporting the join's
  game-identity binding.
- **Cost of the new join checks.** Checks 5–6 add one checkpoint forward
  pass per learner decision (~177k round-wide), accepted in Phase 2's text.

### Passed unchanged in this revision

The re-review's verified-closure list is untouched: cycle-local allocation
`16/48/128/128/192`; the 114/113 league split; ≈177k learner decisions; the
`request_id` contract; the auxiliary-head contract; the G2 128-block paired
Student-t contract; the centered return and linear critic; and the M35A
manifest SHA binding.

---

## Revision 3 independent re-review — findings

Independent re-review completed on 2026-08-30. Verdict
**`NEEDS_REVISION`**; `P0 = 0`, `P1 = 2`, `P2 = 2`. This was a read-only
source/document/statistical-contract review before the review record itself was
appended. No training, Arena run, data collection, or promotion occurred.

### Verified closures and calculations

- `[RR3-P1-1]` closes the original provenance hole at the contract level:
  stored and rebuilt typed observations are compared; the engine observation
  hash is recomputed; legal-action order, action, derived sampling seed, bound
  checkpoint, report, replay, and outcome are fail-closed; and recomputed
  behaviour values, rather than self-reported sidecar values, enter PPO.
- `[RR3-P2-1]` is closed. With the frozen shared-seed G3 schedule, the 32
  cross-opponent seed aggregates are the correct independent units. Independent
  SciPy recomputation gives the one-sided df-31 critical value
  `1.695518782545865`, agreeing with the frozen `1.695518782546`.
- `[RR3-P2-2]` is closed. The schedule now names all eight cycles explicitly,
  I4 names the SPLITMIX64 categorical sampler, and `game_index` is correctly
  described as round-wide unique.
- The four G0b seed ranges are pairwise disjoint, contain exactly 384 unique
  seeds, and do not overlap the training, G2, or G3 ranges. The independently
  recomputed homogeneous-binomial reference values remain `93.2319%`,
  `50.9462%`, `71.2769%`, and `99.7133%`.

### Findings requiring Revision 4

| # | Severity | Finding | Required closure |
|---|---|---|---|
| R3R-P1-1 | P1 | **Phase 0 is still partly a designer rather than an executor.** The probe freezes four seed ranges and says the diversified bucket contains 72 heuristic plus 24 random games, but it never maps bucket-local ordinals to those two opponents. More importantly, it never maps the 96 LEAGUE games to the nine `LEAGUE_ORDER` checkpoints. Different compliant executors can therefore measure materially different truncation rates and wall times. G0 also excludes the "first 2" games but does not define the intra-bucket order; after removing two games, the diversified timed sample cannot retain the stated 72/24 composition (`70/24`, `71/23`, or `72/22` are all possible), while the text still calls the remaining 94 a 72+24 combined mean. | Freeze a bucket-local ordinal and exact opponent assignment for DIVERSIFIED and LEAGUE, including the 96-to-9 league distribution and learner-seat semantics. Freeze warm-ups so the timing estimator matches the production mixture: use separate out-of-sample warm-ups, or exclude a predeclared proportional set and update the denominator/weights. Phase 0 must have no remaining assignment or ordering choice. |
| R3R-P1-2 | P1 | **The core PPO experiment is not yet a reproducible training contract.** §5.3 freezes headline hyperparameters but not minibatch size/partition, epoch shuffle and seed, optimizer-step count, AdamW `betas`/`eps`, cosine-scheduler stepping granularity, or the exact aggregation/reduction of policy, entropy, value, and auxiliary losses. I4 says update order follows batch-file order, but does not say whether an epoch is one full-batch step or many minibatch steps. These choices materially change the policy update and cannot be delegated after data are observed. The new-head seed also lacks the actual initializer algorithm/distribution; a seed and "critic then auxiliary" order alone do not determine weights. | Freeze the complete trainer execution contract before implementation/collection: logical minibatch size, deterministic partition/shuffle and seed, incomplete-minibatch handling, optimizer steps per epoch/cycle, AdamW parameters, scheduler step points, loss formulas/reductions, and explicit head initializer functions with generator draw order. Bind these fields into the rollout/training plan hash and result metadata. |
| R3R-P2-1 | P2 | **Bit-exact behaviour-value replay assumes a runtime determinism contract that is not written.** The D2 path uses dropout 0 and existing loaders call `model.eval()`, which lowers risk, but the document does not freeze inference mode, dtype, device, per-decision batch shape, deterministic-algorithm/CUDA settings, shared encoder/softmax implementation, or non-finite rejection. Consequently "same deterministic function" and f64 bit equality are assertions, not yet a portable operational contract; an otherwise valid batch can false-abort after a harmless kernel/runtime difference. | Either freeze the complete behaviour/recompute inference environment and require all recomputed logits/probabilities/values to be finite, or make recomputed values authoritative for PPO and treat recorded-value equality as a diagnostic with a frozen comparison rule. Action reproduction and checkpoint/observation binding must remain fail-closed. |
| R3R-P2-2 | P2 | **Disjoint seeds remove cross-bucket clustering, but do not make mixed-opponent counts exactly binomial.** DIVERSIFIED deliberately mixes heuristic/random and LEAGUE mixes nine checkpoints, whose truncation probabilities need not be equal. Their fixed-stratum count is generally Poisson-binomial, not `Bin(96,p)`; likewise the 384-game aggregate is only `Bin(384,p)` under a homogeneous common-p reference model. The deterministic count gate remains executable and unchanged, so this is a calibration/reporting issue rather than a gate blocker. | Describe the quoted probabilities explicitly as homogeneous-p reference operating characteristics, not exact properties of the heterogeneous schedule. Report per-opponent/sub-stratum counts alongside the four gate buckets; retain the frozen gate thresholds unless a future pre-collection amendment deliberately changes them. |

### Re-review verdict

Revision 3 closes the 32-seed G3 interval and all three prose drifts, restores
cross-bucket seed separation, and materially strengthens trajectory
provenance. It does not yet freeze the actual Phase 0 opponent schedule or the
PPO update algorithm. Therefore:

```text
M39A_REVISION_3_RE_REVIEW = NEEDS_REVISION
P0 = 0
P1 = 2
P2 = 2
TRAINING_AUTHORIZED = NO
ARENA_AUTHORIZED = NO
DATA_COLLECTION_AUTHORIZED = NO
PROMOTION_AUTHORIZED = NO
```

The next permissible action is a **Revision 4 document-only amendment** that
closes `R3R-P1-1..2` and `R3R-P2-1..2`, followed by another independent
re-review.

---

## Revision 4 — findings and disposition

Document-only amendment on 2026-08-30, closing all four Rev 3 re-review
findings. No training, Arena run, data collection, or promotion occurred; no
code changed; the baseline is unchanged at `573434f`.

| # | Finding | Disposition | Where |
|---|---|---|---|
| R3R-P1-1 | Phase 0 still a partial designer: no DIVERSIFIED 72/24 ordinal mapping, no LEAGUE 96-to-9 assignment, warm-up "first 2" undefined in order and broke the 72/24 composition of the timed sample | Bucket-local ordinal `o = seed − base` frozen with exact opponent assignment: DIVERSIFIED `o mod 4 ∈ {0,1,2} → heuristic, o mod 4 = 3 → random` (72/24, interleave makes every prefix composition-preserving); LEAGUE `LEAGUE_ORDER[o mod 9]` (11×6 + 10×3); M07/SELF_PLAY whole-bucket. Warm-up replaced by the predeclared **first 32 ordinals** per bucket (24 heuristic + 8 random; every league opponent ≥ 3), timed sample = remaining **64 per bucket** (48/16 diversified, all-nine league). Phase 0 now executes a fully named 384-game schedule with zero design freedom | §5.4 G0, G0b |
| R3R-P1-2 | PPO not a reproducible training contract: no minibatch size/partition, shuffle rule, optimizer-step count, AdamW betas/eps, scheduler granularity, loss reductions, or head initializer algorithm | Full trainer execution contract frozen: 512-decision minibatches, contiguous chunks of a SPLITMIX64-keyed per-epoch permutation (`trainer_seed = 40_260_830`), one AdamW step per minibatch (incomplete final chunk kept), `betas=(0.9, 0.999), eps=1e-8, amsgrad=off`, joint grad-norm clip 1.0 before step, per-cycle LR **waypoint table** stepped once at cycle start, exact per-term loss formulas with mean reduction and frozen coefficients, GAE standardized once per cycle, f32/GPU dtype, and explicit head initializers (Kaiming-uniform `a=√5` + zero bias, PyTorch `nn.Linear` default, made explicit). All fields bound into the training plan hash and checkpoint metadata | §5.3 |
| R3R-P2-1 | Bit-exact behaviour-value replay had no runtime contract; could false-abort on harmless kernel/runtime differences | Frozen inference runtime contract (eval mode, deterministic algorithms, cudnn deterministic/no-benchmark, no compile, f32, one named GPU for both rollout and recompute, batch dimension 1 matching rollout, shared log-softmax helper, `torch.isfinite` on all recomputed outputs). Check 6 relaxed to a **pre-registered contingency**: recomputed values always enter PPO; recorded values become a diagnostic with frozen thresholds (`1e-6` log-prob, `1e-5` value) — within = `benign_runtime_drift`, beyond or non-finite = batch abort. Checks 3/4/5/7 remain unconditionally fail-closed | Phase 2 |
| R3R-P2-2 | Mixed-opponent buckets are Poisson-binomial, not binomial; quoted probabilities over-claim | Probabilities re-labelled **homogeneous-p reference operating characteristics** with an explicit Poisson-binomial caveat and mean-preserving numerical spot checks (1.56%–1.61% at the 1% line); decision procedure explicitly unchanged. Sub-stratum reporting added: DIVERSIFIED split 72/24, LEAGUE split into nine per-opponent counts (diagnostic, no new gate rules) | §5.4 G0b |

### Verification performed during this revision

- **Warm-up composition.** DIVERSIFIED ordinals 0..31 under `o mod 4`:
  24 heuristic / 8 random — exactly 3:1; timed ordinals 32..95 contain
  48/16, also 3:1. LEAGUE ordinals 0..31 cover `LEAGUE_ORDER[0..8]` at
  least ⌊32/9⌋ = 3 times each; the 96-game bucket assigns 11 games to each
  of the first six opponents and 10 to the last three (96 = 9×10 + 6),
  verified by direct enumeration.
- **LR waypoints.** All eight values in the §5.3 table computed from
  `lr(c) = 1e-5 + 4.5e-5 × (1 + cos(π(c−1)/7))`; endpoints are exactly
  1.000000e-4 (c=1) and 1.000000e-5 (c=8).
- **Poisson-binomial spot checks.** Mean-preserving splits of the
  diversified bucket at mean 0.96 recomputed exactly by convolution:
  p = 0.5%/2.5% → `P(≥4) = 1.56%`; p = 1.2%/0.4% → 1.60%; homogeneous
  1% → 1.61% — supporting the "usable calibration, not exact claim"
  wording in §5.4.
- **Optimizer-step arithmetic.** ~22k decisions/cycle ÷ 512 ≈ 44 minibatches
  × 4 epochs ≈ 176 steps/cycle, ~1,408 steps round-wide; consistent with
  the frozen per-minibatch stepping rule.
- **Seed-base disjointness.** `trainer_seed = 40_260_830` is distinct from
  training (4M-base), rollout (7M-base), new-head init (20_260_829), G2/G3
  (5.0M/5.1M), and probe (5.2M) ranges.

### Passed unchanged in this revision

The Rev 3 re-review's verified-closure list is untouched: trajectory
provenance binding (with check 6's PPO inputs still recomputed values);
G3's 32 cross-opponent seed aggregates with `df = 31`; the 384 disjoint
probe seeds and their isolation from all other ranges; the eight-cycle
loop, SPLITMIX64 sampler naming, and round-wide `game_index`; the G0
four-strata/seconds-unit projection; and all earlier accepted sets (return
contract, G2 Student-t contract, cycle-local schedule, auxiliary head,
114/113 split, ≈177k decisions).

---

## Revision 4 independent re-review — findings

Independent re-review completed on 2026-08-30. Verdict
**`NEEDS_REVISION`**; `P0 = 0`, `P1 = 2`, `P2 = 2`. This was a document,
source, runtime-contract, and statistical-contract review. No training, Arena
run, data collection, or promotion occurred.

### Verified closures and calculations

- `[RR4-P1-1]` closes the Phase 0 scheduling defect at the executable-contract
  level. Direct enumeration gives DIVERSIFIED warm-up `24/8`, timed `48/16`,
  and full `72/24`; the 96 LEAGUE games allocate
  `[11,11,11,11,11,11,10,10,10]`, while its first 32 ordinals allocate
  `[4,4,4,4,4,3,3,3,3]`. The named schedule, learner seat, and ordinal order
  no longer require the Phase 0 executor to choose opponents.
- `[RR4-P2-2]` is closed at the decision-contract level. Independent exact
  convolution reproduces the homogeneous-p reference values: at `p = 1%`,
  `P(bucket >= 4) = 1.6057%`, `P(aggregate >= 9) = 1.6448%`, and family pass
  `= 93.2319%`; at `p = 2%`, family pass `= 50.9462%`; at `p = 5%`, the two
  trigger probabilities are `71.2769%` and `99.7133%`. The heterogeneous
  spot checks also reproduce `1.5626%`, `1.5988%`, and `1.6057%`.
- All eight LR calculations agree with the stated cosine formula; the exact
  values begin `1e-4, 9.55435990556e-5, 8.30570410836e-5` and end at `1e-5`.
  The G2/G3 schedules, Student-t constants, cycle-local allocation, disjoint
  seed ranges, and round-wide `game_index` did not drift in Revision 4.
- The named `local-artifacts/m24-torch-cu124` environment reports PyTorch
  `2.6.0+cu124` (`torch/version.py:4`). Inspecting its
  `torch/nn/modules/linear.py:114-122` confirms the weight call is
  `kaiming_uniform_(a=sqrt(5))`, but the bias call is
  `uniform_(-1/sqrt(fan_in), +1/sqrt(fan_in))`, not zero initialization.

### Findings requiring Revision 5

| # | Severity | Finding | Required closure |
|---|---|---|---|
| R4R-P1-1 | P1 | **The trainer's sample order and advantage tensor are still not uniquely defined.** “Indices sorted by SPLITMIX64 keyed on `(trainer_seed, cycle, epoch)`” supplies one epoch-level tuple, not a key for each logical sample index; it does not define tuple-to-u64 mixing, per-index input, collision tie-break, or an equivalent Fisher–Yates draw sequence. The GAE clause also does not define the per-seat transition sequence, `delta_t` recursion, last-step handling, whether cycle SD is population or sample SD, or the zero-denominator epsilon. Two implementations can therefore produce different minibatches and different `A_t` while both claim compliance. AdamW also leaves `foreach`/`fused` dispatch at runtime defaults despite calling the update contract complete. | Freeze an executable permutation formula, including 64-bit wrapping, cycle/epoch indexing, the logical sample index, and a deterministic tie-break (or freeze exact Fisher–Yates draws). Freeze the per-seat GAE equations and transition order, terminal/truncation handling, normalization variance convention and epsilon. Freeze the AdamW execution variant (`foreach`, `fused`, `capturable`, `differentiable`) and bind all fields into the plan hash. |
| R4R-P1-2 | P1 | **The new-head initializer contract contradicts the actual frozen runtime.** PyTorch 2.6 `nn.Linear.reset_parameters()` initializes bias uniformly in `[-1/sqrt(fan_in), +1/sqrt(fan_in)]`; it does not call `zeros_`. Moreover, constructing a fresh `nn.Linear` does not accept the dedicated `torch.Generator`, so it is not “compliant by construction” with the promised private-generator draw order. The document currently permits both zero and random bias implementations and does not actually bind constructor draws to `20_260_829`. | Choose one initializer contract. If zero bias is intended, explicitly call `kaiming_uniform_(weight, a=sqrt(5), mode='fan_in', nonlinearity='leaky_relu', generator=g)` followed by `zeros_(bias)` for each layer in the frozen critic-then-aux order, and state that constructor-created parameters are overwritten and their global-RNG draws carry no contract meaning. Otherwise freeze PyTorch's real uniform-bias draws and their generator order. Remove the false default-initializer claim. |
| R4R-P2-1 | P2 | **Join check 6 states two different admission rules.** The numbered check says the bound checkpoint “must reproduce” both values exactly with “no tolerance”, but its contingency later allows a bitwise mismatch within `1e-6` / `1e-5` to proceed. The later paragraph makes the intended policy inferable, but the formal checklist itself remains contradictory. The runtime block also says “no cuBLAS autotuning” without freezing the CUDA environment variable used by this repository's existing deterministic GPU recipes (`CUBLAS_WORKSPACE_CONFIG=:4096:8`). | Rewrite check 6 as one three-outcome rule: bit-exact match; finite within-threshold `benign_runtime_drift`; otherwise abort, with recomputed values authoritative in the first two cases. Freeze the cuBLAS workspace setting before importing torch, or explicitly explain why the selected inference kernels do not require it; record the setting in the result. |
| R4R-P2-2 | P2 | **The Rev 4 summary layer contains several factual drifts.** The top banner says “64/16 and 8 per bucket timed” although the binding schedule is `48/16` and `64` total timed per bucket; and “every contiguous prefix” preserves 3:1 is false except at four-game boundaries. The binding 32/64 subsets are correct, so these are navigation/prose defects rather than a schedule defect. The LR formula and rounded table also need an authority rule because an explicit lookup of the printed values is not bit-identical to evaluating the formula. (The duplicate Rev 3 status line was corrected while recording this review verdict.) | Correct the banner to `48/16` and 64 timed games; limit the prefix claim to complete four-game blocks or just the frozen 32/64 subsets. Declare either the full-precision constants or the displayed table as the authoritative LR values. |

### Re-review verdict

Revision 4 closes the Phase 0 opponent assignment/warm-up defect and correctly
reframes the mixed-opponent operating characteristics. It also adds most of
the missing PPO and inference structure. However, the two P1 items above mean
the core policy update is still not one reproducible algorithm. Therefore:

```text
M39A_REVISION_4_RE_REVIEW = NEEDS_REVISION
P0 = 0
P1 = 2
P2 = 2
TRAINING_AUTHORIZED = NO
ARENA_AUTHORIZED = NO
DATA_COLLECTION_AUTHORIZED = NO
PROMOTION_AUTHORIZED = NO
```

The next permissible action is a **Revision 5 document-only amendment** that
closes `R4R-P1-1..2` and `R4R-P2-1..2`, followed by another independent
re-review.

---

## Open questions for review

**Q1 — Should the VP margin enter the return, or only the auxiliary head?**
`[RESOLVED R1 — margin stays out of the return]`

As frozen (§5.2) the return is pure outcome and the margin is a separate
predictive head. This follows the stated design. The concern: with 4,096
outcome labels, the return carries 1 bit per game while the margin carries
roughly 4 bits and directly encodes the "push for points" behaviour the round
is meant to produce.

Alternative: `R = outcome + 0.25 * clamp((VP_me − VP_opp)/15, −1, 1)`, with
the outcome term still dominant. **Recommendation: keep the frozen
outcome-only return for this round.** Mixing shaping into the return makes it
impossible to attribute a G2 result to "genuine strength" versus "the shaping
term was well chosen", and the auxiliary head already supplies the dense
gradient without contaminating the objective. Resolve before collection.

**Q2 — Gate on cycle-8 only, or select the best of 8 on Arena?**
`[RESOLVED R1 — cycle-8 only]`

As frozen (§5.4 G2) the gate is on the cycle-8 checkpoint, and cycles 1–7 are
reported as a diagnostic learning curve with **no selection weight**.

Rationale: selecting the maximum of 8 checkpoints on a 64-match Arena incurs a
winner's-curse bias of roughly +5–10 pp, which is larger than the effect the
round is trying to detect. A paired bound on a pre-declared checkpoint is
unbiased.

The cost is real: if the curve peaks at cycle 5 and cycle 8 regresses, G2
fails even though a better policy existed. **Recommendation: keep cycle-8-only
gating, and treat a mid-training peak as the headline finding for the next
round** (it would indicate the LR schedule or cycle count is wrong, which is
a cheap fix). Resolve before collection.

**Q3 — Should M25-D2-v2 be in the training opponent pool?**
`[RESOLVED R1 — keep it, with a frozen assignment]`

It is both the initialization and a league opponent. Arguments for inclusion:
it is the opponent whose strength most closely matches the learner's starting
point, so games against it carry the most information early. Arguments
against: self-play against your own initialization is close to pure self-play,
which is the M24-S2 failure mode. **Recommendation: keep it in the pool** —
it is 1 of 9 league opponents, so at most ~114 of the 1,024 league games, and
the pool's diversity is the point. Resolve before collection.

### R1 resolution of Q1–Q3

All three are resolved as recommended, and each resolution is now enforced by a
frozen constant rather than left as prose:

| Q | resolution | where it is now binding |
|---|---|---|
| Q1 | VP margin enters the **auxiliary head only**, never the return | §5.2 defines the return as the centered outcome alone; `aux_score_diff_coefficient` in §5.3 is the only path by which margin information reaches the objective |
| Q2 | **cycle-8 only** for the formal gate; cycles 1–7 are diagnostics | §5.4 G2 names `cycle-8` explicitly and adds "no re-selecting a checkpoint after seeing cycles 1–7" |
| Q3 | D2-v2 **stays** in the training pool | §3.3 replaces "sampled uniformly" with a closed-form `game_index` assignment that fixes D2-v2 at exactly **114** of the 1,024 league games |

Q1's bit-count argument is unaffected by the P1-1 re-centering: the return is
still one coarse terminal label per game whether its alphabet is
`{1, 0.5, 0}` or `{−1, 0, +1}`, and the auxiliary head remains the dense
gradient source.

---

## Next authorized gate

M39A is `IMPLEMENTED / IMPLEMENTATION_SMOKE_PASS / PHASE_0_PENDING`.

The next operational gate is the frozen **384-game Phase 0** probe. Formal
cycle collection remains blocked until both G0 and G0b pass:

```text
PHASE_0_AUTHORIZATION_REQUIRED
NO FORMAL 4096-GAME COLLECTION BEFORE G0/G0b PASS
NO PROMOTION
```

The former Revision 5 requirements are now executable implementation
contracts and remain regression obligations:

- **`[R4R-P1-1]`** an executable per-index shuffle formula and tie-break;
  complete per-seat GAE recursion, terminal handling, and cycle-normalization
  formula; and explicit AdamW backend flags, all plan-hash bound;
- **`[R4R-P1-2]`** one factually correct, dedicated-generator initializer
  contract for every new-head weight and bias, with constructor draws either
  overwritten or explicitly included;
- **`[R4R-P2-1]`** one non-contradictory three-outcome rule for join check 6
  plus a frozen/recorded cuBLAS workspace setting;
- **`[R4R-P2-2]`** the banner/prefix/LR-authority prose repairs listed
  in the Revision 4 re-review.

Revision 4's verified closures remain binding: Phase 0's named 384-game
schedule, the 32/64 warm-up/timed split, the four timing strata and seconds
conversion, homogeneous-p reference labelling, and sub-stratum reporting must
not drift during Revision 5.

The successfully closed Revision 3 items remain in scope for drift checking:

- **`[RR3-P1-1]`** the join binds every PPO input: stored observation
  payload vs. rebuilt player view (engine `observation_hash` validated on
  both sides), derived `decision_seed` vs. the stored field, frozen
  categorical draw reproducing the recorded action, and checkpoint
  recomputation of behaviour values — recomputed values enter PPO;
- **`[RR3-P1-2]`** G0's four timing strata match the probe buckets,
  `mean_t` is in seconds, the hours conversion is inside the formula;
- **`[RR3-P1-3]`** G0b's four buckets use disjoint 96-seed ranges
  (`5_200_000..5_200_383`);
- **`[RR3-P2-1]`** G3's diagnostic interval uses the 32 cross-opponent
  seed aggregates, `df = 31`, critical value `1.695518782546`;
- **`[RR3-P2-2]`** the three prose drifts remain repaired (§3.5 inclusive
  eight-cycle loop; I4 names the SPLITMIX64 sampler; `game_index` unique
  round-wide).

The successfully closed Revision 2 items remain in scope for drift checking:

- **§3.3 / §3.5** — the cycle-local bucket formula `[R2-P1-1]`: totals
  unchanged, identical mix across all eight cycles, `LEAGUE_ORDER` defined
  in the document, 114/113 split preserved;
- **Phase 2** — the re-frozen trajectory schema and join `[R2-P1-2]`:
  `ply_index` / `seat` / `request_id = ply_index + 1` semantics against the
  engine's global counter, per-seat sidecars, the replay-authoritative join,
  and the canonical hash + SPLITMIX64 sampling formulas;
- **§5.4 G0 / G0b** — the frozen probe structure `[R2-P1-3]`: 96 games per
  bucket with the two count rules, and the G0 warm-up / parallelism /
  projection machinery (now with Rev 4's exact assignment);
- **§3.1 / §5.3** — the auxiliary-head contract `[R2-P1-4]`: target
  normalization `clamp(ΔVP/15, −1, +1)`, VP-at-cap timing for truncated
  games, MSE, and init seed `20_260_829`;
- **§3.3 / §5.4 G3** — the corrected decision volume `[R2-P2-1]`.

Reviewers should additionally confirm that the Revision 4 dispositions
resolve the Rev 3 findings they cite, that nothing in the Rev 3 re-review's
verified-closure list drifted, and that no gate changed its decision rule
between Revision 3 and Revision 4: the Phase 0 changes name a schedule the
previous text left open and replace an ill-defined warm-up with a
composition-preserving one (G0b's 96-per-bucket counting and both count
rules are untouched), and the check-6 contingency changes only the response
to a mismatch, never the values PPO trains on. The Revision 1–3 re-review
scopes (return/critic contract, G2 Student-t contract, G3 schedule,
cycle-local formula, trajectory schema, G0/G0b freeze, auxiliary head,
Rev 3 repairs) remain in scope by inheritance.
