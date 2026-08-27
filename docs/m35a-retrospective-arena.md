# M35A — Historical Neural Checkpoint Direct Policy Retrospective Arena

```ini
MILESTONE = M35A
STATUS = EXECUTED (15/17 pairings complete; 2 pairings blocked by deterministic engine ply-limit aborts) / PENDING_REVIEW
BASE_COMMIT = f46147c0b82f0fa5653457a419ebf8fbc0df7325
EXECUTION_COMMIT = 709fcca (review repair 1, PASS / FORMAL M35A ARENA AUTHORIZED)
SCOPE = Evaluate the true game-playing strength of 9 historical neural network checkpoints via direct legal-action policy scoring (argmax over server-certified legal actions, without search) in paired-seed Arena matches against M07 Champion and D2-v2 Benchmark.
DATASET / MATCHES = 32 paired seeds (300001..300032) x 2 seat rotations = 64 games per pairing; 9 vs M07 (576 games) + 8 vs D2-v2 (512 games) = 1,088 total matches scheduled.
CHAMPION = M07 (Determinization Search, sample-seed=20260810, sample-count=4, depth=1, max-nodes=2000)
BENCHMARK = M25 D2-v2 (DeltaEntityMixer h192/b4, 59-dim exact action deltas)
CHECKPOINTS = M24-S2, M25-D2-v2, M28A, M28B, M29A-v2, M31A, M32A, M33A, M34A
ARENA_PROTOCOL = NDJSON Protocol v0.5 over stdio (splendor eval / run-match)
EXECUTION_DEVICE = CPU (single/dual-thread bounded, zero CUDA initialization overhead)
PROMOTION = NONE (Exploratory retrospective diagnostic; does not retroactively alter offline gate verdicts or promote checkpoints.)
DECISION = PENDING_REVIEW (formal execution complete with 2 deterministic engine-abort pairings preserved as invalid attempts)
```

## Frozen analysis scope (review repair 1)

The 9 checkpoints do NOT share one offline-metric data contract, so a single
pooled all-model CE/Top-1 correlation ranking is FORBIDDEN. Two cohorts are
frozen for any retrospective correlation analysis:

- **Cohort A (M25 canonical teacher dataset, 16,282 examples, semantic hash
  `1aa7212f...`)**: M25-D2-v2, M29A-v2, M31A, M32A, M33A, M34A. These models'
  offline CE/Top-1 are directly comparable to each other and to Arena results.
- **Cohort B (disparate data contracts)**: M24-S2 (M24 self-play corpus
  `3f8adcd4...`), M28A and M28B (M28 width-scaling corpus `b8a67f5f...`).
  Their offline metrics come from different datasets/eval protocols and must
  not be merged into Cohort A rankings; they may only be reported as separate
  standalone Arena entries.

Cross-cohort comparisons are limited to Arena win rates (same opponents, same
seeds); any offline-metric correlation analysis must be reported per cohort.

## Problem and evidence

Across milestones M24 through M34, offline exploration targeted policy fitting against M07 search demonstrations on canonical M25 dataset (16,282 examples). Evaluation relied on Teacher Cross-Entropy, Excess CE, and Top-1 accuracy.

However, offline imitation accuracy measures *teacher fidelity*, which does not necessarily correlate monotonically with actual game-playing strength:
1. A policy might diverge from the teacher on near-equivalent legal moves without weakening game performance.
2. A policy might closely mimic the teacher's distribution while inheriting its blind spots.
3. Conversely, structural architectural innovations (e.g. attention, width, information parity) might exhibit higher strategic strength in actual play despite hitting imitation CE plateaus.

**Core Scientific Question**:
Does offline imitation fit against the M07 teacher correlate with actual game-playing strength across historical neural checkpoints?

## Initial design and scope

### Direct Policy vs Search-Assisted (Decoupled into M35A / M35B)
- **M35A Scope**: Pure Direct Policy mode. The neural network evaluates server-certified legal actions from public observations and selects the argmax action directly without tree search.
- **Why exclude Neural-ISMCTS in M35A?**: Post-M25 models were trained policy-only or with value heads under disparate objectives/uncalibrated values. Passing uncalibrated value heads into ISMCTS leaf evaluation introduces severe confounding factors. Search-assisted prior-only evaluation is decoupled into **M35B**.

### Evaluated Model Checkpoints
An explicit registry binds all 9 candidate models to their exact checkpoint path, SHA256, architecture, feature pipeline, and output semantics:
1. **M24-S2**: `EntityMixer` (h192/b4, 36-dim base action features)
2. **M25-D2-v2**: `DeltaEntityMixer` (h192/b4, 59-dim exact action deltas)
3. **M28A**: `EntityMixer` (h320/b4, width scaling)
4. **M28B**: `ContextualEntityMixer` (h192/b4, contextual interaction, interaction_blocks=2)
5. **M29A-v2**: `ActionConditionedNestedEntityMixer` (h192/b4, nested residual attention)
6. **M31A**: `DeltaEntityMixer` (h192/b4, pairwise ranking loss)
7. **M32A**: `BeliefDeltaEntityMixer` (h192/b4, 212-dim real-time belief features)
8. **M33A**: `FactorizedDeltaEntityMixer` (h192/b4, structured composite logits)
9. **M34A**: `HierarchicalDeltaEntityMixer` (h192/b4, hierarchical \(\log P(a \mid s)\))

## Contracts and invariants

1. **Arena Rules & Engine**: Strict reuse of frozen M04 Arena, NDJSON Protocol v0.5, replay validation, and seat rotation. Zero modifications to engine rules.
2. **CPU Execution Invariant**: All neural evaluation runs on CPU (`torch.set_num_threads(1)`, `torch.set_num_interop_threads(1)`), eliminating repeated CUDA initialization overhead across 1,088 matches and avoiding thermal throttling.
3. **M32A Live History Reconstruction**: M32A reconstructs player-visible game history and 212-dim belief features dynamically from live NDJSON events (`game_start`, `event`, `action_applied`, `observation`) without access to private referee state or offline sidecars. Real-time belief projection is strictly verified element-wise against the frozen M32A sidecar across both seats on real replay event streams.
4. **M34A Hierarchical Scoring Invariant**: M34A strictly selects actions via normalized hierarchical \(\log P(a \mid s)\) rather than flat base logits.
5. **Production Parity Invariant**: Tests invoke the production `m35a_agent` `score_model_actions` pipeline, verifying legal action order, score vectors (within \(10^{-5}\) atol), and first-max argmax against reference models.
6. **Reproducible Manifest**: All 17 pairing configurations, seeds (`300001..300032`), timeouts, commands, checkpoint SHAs, source SHAs, and realized plan SHAs are tracked in `benchmarks/m35a-retrospective-arena.manifest.json`; neural agent commands must invoke the repository-root entry script `training/m17_gpu/m35a_agent_entry.py` with `--device cpu` (plans cannot carry `PYTHONPATH`).

## Implementation plan

- [x] Implement `training/m17_gpu/splendor_gpu/m35a_registry.py` with fail-closed validation.
- [x] Implement `training/m17_gpu/splendor_gpu/m35a_belief.py` with live NDJSON event tracking.
- [x] Implement `training/m17_gpu/splendor_gpu/m35a_adapters.py` with exact feature pipelines and scoring dispatch.
- [x] Implement `training/m17_gpu/splendor_gpu/m35a_agent.py` NDJSON agent with CPU thread pinning.
- [x] Implement `training/m17_gpu/m35a_agent_entry.py` repository-root entry script (review repair 1).
- [x] Implement `training/m17_gpu/tests/test_m35a_agent_parity.py` and verify production path parity and live replay belief tracking.
- [x] Generate `benchmarks/m35a-retrospective-arena.manifest.json` and 17 realized plans in `local-artifacts/m35a-retrospective-arena/plans/`.
- [x] Implement Rust manifest test in `crates/splendor-cli/tests/m35a_manifest.rs`.
- [x] Review repair 1: fix entry point, M32A color order + real transcript parity, manifest test hardening, cohort freeze, 9-model subprocess smoke.
- [x] Formal execution authorized (`PASS / FORMAL M35A ARENA AUTHORIZED`, basis `709fcca`).
- [x] Execute 17 pairings serially; 15 completed fully, 2 aborted deterministically (see execution result).
- [ ] Review of execution results.

## Formal execution result (2026-08-27)

Execution basis: commit `709fcca`, serial per-pairing
`target/release/splendor eval --plan <plan> --out-dir runs/<name>`,
seeds 300001..300032, 2 rotations each, 64 games per pairing.

### Outcome totals

- **Scheduled**: 1,088 matches across 17 pairings.
- **Completed & scored**: 960 matches across 15 pairings
  (960/960 in those pairings, **0 aborts, 0 agent faults**, every replay
  verified by the arena runner).
- **Invalid attempts (engine safety abort, not agent faults)**: 2 pairings.
  - `M29A-v2 vs M07`: abort at match 61 (seed 300031, rotation 0) —
    `engine internal error: match exceeded ply safety limit`
    (`MAX_MATCH_PLIES = 10,000`). 60 matches completed before abort,
    preserved under `runs/invalid-attempt-1-m35a-m29a-v2-vs-m07-v1/`.
  - `M31A vs M07`: abort at match 16 (seed 300008, rotation 1) — same
    engine ply-limit error. 15 matches completed before abort, preserved
    under `runs/invalid-attempt-1-m35a-m31a-vs-m07-v1/`.
  - Both aborts were reproduced deterministically in isolated single-seed
    reruns (fresh subprocesses, identical commands): seed 300031
    (M29A-v2-vs-M07) and seed 300008 (M31A-vs-M07) each hit the 10,000-ply
    limit again. The games are genuine endless take/pass loops (neither
    player reaches 15 prestige and the stalemate rule never triggers
    because the bank retains tokens). Per the no-post-hoc-seed-change rule
    these pairings are NOT re-seeded; their completed prefixes are retained
    as evidence but not scored.
- Result payload (local): `local-artifacts/m35a-retrospective-arena/m35a-retrospective-arena.result.json`
  SHA256 `1072e855627e42b966d14ad3cdeff54b2fc4203214080f814a66b89d27371e9d`.

### Per-pairing results (candidate perspective, 64 games each)

| Candidate | Opponent | W–D–L | Win rate | Seat split (cand s0 W/G, s1 W/G) | Avg score (c–o) | eval-report SHA256 (16) |
| --- | --- | --- | --- | --- | --- | --- |
| M24-S2 | M07 | 17–0–47 | 26.6% | 8/32, 9/32 | 10.8–15.0 | `76163270560484e3` |
| M25-D2-v2 | M07 | 11–0–53 | 17.2% | 6/32, 5/32 | 10.0–15.6 | `bd6aa756685491f1` |
| M28A | M07 | 21–0–43 | 32.8% | 13/32, 8/32 | 11.8–14.6 | `d666e963b8b12fd5` |
| M28B | M07 | 16–0–48 | 25.0% | 8/32, 8/32 | 10.9–15.4 | `abe66fd7a76cd297` |
| M29A-v2 | M07 | INVALID | — | — | — | aborted (ply limit) |
| M31A | M07 | INVALID | — | — | — | aborted (ply limit) |
| M32A | M07 | 18–0–46 | 28.1% | 8/32, 10/32 | 10.7–14.8 | `9d1566f1d4623228` |
| M33A | M07 | 16–0–48 | 25.0% | 10/32, 6/32 | 11.6–14.8 | `cda9bd0bdca9b1d8` |
| M34A | M07 | 13–0–51 | 20.3% | 8/32, 5/32 | 10.4–15.5 | `e105093bcf5d7fc2` |
| M24-S2 | M25-D2-v2 | 25–0–39 | 39.1% | 18/32, 7/32 | 12.8–13.9 | `833254590e1e35d3` |
| M28A | M25-D2-v2 | 27–0–37 | 42.2% | 16/32, 11/32 | 13.2–13.9 | `146dbef46d4be8af` |
| M28B | M25-D2-v2 | 30–0–34 | 46.9% | 15/32, 15/32 | 13.1–13.7 | `2a78a577cecafed0` |
| M29A-v2 | M25-D2-v2 | 42–0–22 | 65.6% | 21/32, 21/32 | 14.1–12.7 | `e2468a140f7d0278` |
| M31A | M25-D2-v2 | 37–0–27 | 57.8% | 20/32, 17/32 | 14.0–13.0 | `0225ba61633d807a` |
| M32A | M25-D2-v2 | 32–0–32 | 50.0% | 17/32, 15/32 | 13.4–12.7 | `04c95b815ae243a9` |
| M33A | M25-D2-v2 | 37–0–27 | 57.8% | 23/32, 14/32 | 14.1–13.0 | `a1974931b9e43dfd` |
| M34A | M25-D2-v2 | 31–0–33 | 48.4% | 16/32, 15/32 | 13.3–13.6 | `c7403576a0ba64ab` |

Full 64-char eval-report SHA256 values are recorded in the result payload.
All completed matches ended `prestige_threshold` except two stalemates
(M33A-vs-M07 one, M24-S2-vs-D2-v2 one).

### vs M07 series summary (completed pairings only)

All 7 scored candidates lose to the M07 champion (win rates 17.2%–32.8%,
each below 50% with 64 games): M07 champion remains strictly stronger than
every direct-policy neural checkpoint under test. Ordering by win rate:
M28A (32.8%) > M32A (28.1%) > M24-S2 (26.6%) = M28B (25.0%) = M33A (25.0%)
> M34A (20.3%) > M25-D2-v2 (17.2%). M29A-v2 and M31A are unscored against
M07 (invalid attempts).

### vs D2-v2 series summary

Net results relative to the D2-v2 benchmark (candidate wins minus losses):
M29A-v2 +20 (65.6%), M31A +10 (57.8%), M33A +10 (57.8%), M32A 0 (50.0%),
M34A −2 (48.4%), M28B −4 (46.9%), M28A −10 (42.2%), M24-S2 −14 (39.1%).
Four of the M25-canonical models (M29A-v2, M31A, M33A, M32A to a draw)
beat or tie their own teacher-fitting baseline D2-v2 in direct play, while
the non-canonical-cohort models (M24-S2, M28A, M28B) all lose to it.

### Cohort A descriptive relationship (frozen scope)

Within Cohort A only (M25-canonical data contract), offline validation
Top-1 vs Arena outcome:

| Model | Offline Val Top-1 | Arena vs M07 | Arena vs D2-v2 |
| --- | --- | --- | --- |
| M25-D2-v2 | 38.42% | 17.2% | (benchmark) |
| M29A-v2 | 38.66% | invalid attempt | 65.6% |
| M31A | ≈38.7% | invalid attempt | 57.8% |
| M32A | 36.40% | 28.1% | 50.0% |
| M33A | 38.86% | 25.0% | 57.8% |
| M34A | 37.14% | 20.3% | 48.4% |

Descriptive finding: offline imitation Top-1 does **not** monotonically
track direct-play strength. M32A has the *lowest* offline Top-1 (36.40%)
yet the *best* scored vs-M07 win rate (28.1%), while M25-D2-v2 (38.42%)
is the weakest vs M07 (17.2%). The vs-D2-v2 ordering
(M29A-v2 > M31A = M33A > M32A > M34A) also does not follow the offline
Top-1 ordering. Small offline-CE/Top-1 differences are not reliable
predictors of game-playing strength — consistent with the milestone's
original motivation. No pooled cross-cohort ranking is reported (frozen
cohort scope; M24-S2/M28A/M28B offline metrics come from different data
contracts).

Seat effects are modest overall; the largest seat splits are M24-S2 and
M33A vs D2-v2 (18–7 and 23–14 in candidate-seat wins), worth noting as a
possible first-move/interaction effect but with no action taken.

## Iteration log

- **2026-08-25**: Authorized M35A Retrospective Arena milestone in direct-policy mode. Scoped to 9 historical neural checkpoints vs M07 Champion (576 matches) and D2-v2 Benchmark (512 matches). Decoupled search-assisted PUCT evaluation into M35B. Switched execution device to CPU to avoid CUDA initialization overhead in M04 subprocess architecture.
- **2026-08-25**: Implemented strict registry (`m35a_registry.py`) with pre-load SHA256 checksums, exact parameter count validation, and frozen catalog hash assertion.
- **2026-08-25**: Implemented live NDJSON event belief tracker (`m35a_belief.py`) reconstructing 212-dim features on the fly without referee state access.
- **2026-08-25**: Implemented model adapters (`m35a_adapters.py`) and unified NDJSON agent CLI (`m35a_agent.py`).
- **2026-08-25**: Verified all 9 model architectures with full score parity and argmax equivalence on CPU. Benchmark single-action latency: ~2.54 ms.
- **2026-08-25**: Generated 17 realized evaluation plans and tracked manifest at `benchmarks/m35a-retrospective-arena.manifest.json`. Validated with Rust evaluation plan parser and schema checker.
- **2026-08-27 Review repair 1 (blocking findings fixed in one round)**:
  - **P0-1 Entry point**: Realized plans invoked `-m splendor_gpu.m35a_agent`, which fails with `ModuleNotFoundError` without `PYTHONPATH=training/m17_gpu` (arena plans cannot carry env vars). Added `training/m17_gpu/m35a_agent_entry.py` (mirroring `agent_entry.py`), regenerated all 17 plans to invoke the script path directly, and recomputed all plan SHA256 bindings in the manifest.
  - **P0-2 Empty parity test**: `test_m32a_live_replay_belief_features_parity` never converted replays to live events, never called `handle_event`/`project_features`, and never compared outputs to the sidecar. Rewritten to reconstruct the real player-projected v0.5 visible event stream (game_started + per-step card_reserved/card_purchased events with viewer-correct visibility) from 6 M25 replays, feed every event through `LiveBeliefTracker`, project at every acting ply for both seats, and compare all 212 dims element-wise against the frozen sidecar (364 comparisons, tolerance 1e-6, minimum 300 enforced). Verified fail-closed: reverting the color fix makes the test fail.
  - **P0-3 M32A color order bug**: `m35a_belief.py` used `["white","blue","black","red","green"]` for bonus/cost channels; the frozen M32A/Rust contract (`splendor_gpu.encoding.COLORS`, `GemColor::ALL`, JSON catalog cost order) is `["white","blue","green","red","black"]`. Green/Black bonus channels were swapped, corrupting M32A Arena inputs. Fixed; the real parity test now passes bit-consistent with the sidecar across reserve/purchase plies and both seats.
  - **P0-4 Weak manifest test**: `m35a_manifest.rs` only checked plan SHAs, schema, seed count and timeouts. Strengthened to also verify: `source_shas` bind current source bytes (incl. new entry script), checkpoint field structure (SHA format, param count, output semantics) plus on-disk SHA when files exist, plan `--model-id` matches the manifest pairing, neural commands use the entry script + `--device cpu` + pinned python, M07 commands match `champion_command` exactly, pairing-matrix coverage (9 vs M07 / 8 vs D2-v2, 1,088 total), and a real checkpoint-SHA tamper probe through the Python registry (must raise). Added an entry-script launch test without `PYTHONPATH`.
  - **Cohort freeze**: Offline metrics of M24-S2/M28A/M28B come from different data contracts than the M25-canonical cohort; frozen two-cohort analysis scope (see above) forbids pooled all-model CE/Top-1 correlation rankings.
  - **Subprocess smoke**: 9 models x 1 seed x 2 rotations = 18 real `splendor eval` matches vs M07 plus 2 neural-pair matches (M33A vs D2-v2) run through the actual subprocess arena: all completed, 0 aborts, verified replays, both seats exercised.
- **2026-08-27 Formal execution (authorized by review `PASS / FORMAL M35A ARENA AUTHORIZED`)**:
  - Executed all 17 pairings serially against commit `709fcca`.
  - 15/17 pairings completed fully: 960/960 scheduled matches, 0 aborts, 0 agent faults, all replays verified.
  - 2 pairings aborted on the engine's frozen `MAX_MATCH_PLIES = 10,000` safety limit: M29A-v2-vs-M07 at seed 300031 r0 (60 matches completed first) and M31A-vs-M07 at seed 300008 r1 (15 matches completed first). Both aborts reproduced deterministically in isolated single-seed reruns; the games are endless take/pass loops in which neither player reaches 15 prestige and the stalemate rule (both forced to pass) never triggers because the bank still holds tokens. No seeds were changed post hoc; both directories preserved as `invalid-attempt-1-*` and their completed prefixes are not scored.
  - Recorded full per-pairing results, seat splits, scores, eval-report SHA256s, series summaries, and the Cohort A descriptive relationship (see Formal execution result above).
  - Result payload written to `local-artifacts/m35a-retrospective-arena/m35a-retrospective-arena.result.json` (SHA256 `1072e855...71e9d`).

## Validation and evidence

### 1. Parity and Production Tests (Python)
Command:
```bash
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests/test_m35a_agent_parity.py -v
```
Output (2026-08-27, after review repair 1):
```
test_registry_fail_closed_tamper_rejection PASSED
test_all_9_models_production_path_parity PASSED
test_m34a_hierarchical_log_prob_invariant PASSED
test_m32a_live_replay_belief_features_parity PASSED  (6 matches / 364 ply-seat comparisons, full 212-dim element-wise sidecar parity, both seats)
test_cpu_single_action_latency_smoke PASSED
5 passed in 5.81s
```

### 2. Manifest and Realized Plan Schema Invariant Tests (Rust)
Command:
```bash
cargo test --test m35a_manifest
```
Output (2026-08-27, after review repair 1):
```
test test_m35a_agent_entry_script_launches_without_pythonpath ... ok
test test_m35a_checkpoint_tamper_rejected_by_registry ... ok
test test_m35a_manifest_and_all_17_realized_plans ... ok
test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured
```

### 3. Real Subprocess Arena Smoke (all 9 models)
Command (per model):
```bash
target/release/splendor eval --plan /tmp/opencode/m35a-smoke/smoke-<model>.plan.json --out-dir /tmp/opencode/m35a-smoke/run-<model>
```
Each plan pairs the model's entry-script agent against the M07 champion on
seed 400001 (2 seat rotations). Result: 9/9 runs exit 0; all 18 matches
`status=completed`, 0 aborts, replay ply counts equal `completed_plies`,
agent handshakes confirmed (`agent_name=effective-splendor-m35a-direct-agent-v1`,
`agent_version=<model>`). An additional neural-vs-neural smoke
(M33A vs M25-D2-v2, seed 400002) completed 2/2 matches. Smoke artifacts are
local-only under `/tmp/opencode/m35a-smoke/`.

### 4. Formatting
Commands:
```bash
cargo fmt --all -- --check
git diff --check
```
Both pass on 2026-08-27.

## Result and decision

- Review round 1 verdict was `FAIL / FORMAL ARENA HOLD` with 4 blocking
  findings. Review repair 1 addressed all of them in a single round and the
  follow-up review returned `PASS / FORMAL M35A ARENA AUTHORIZED` (basis
  `709fcca`).
- Formal execution then ran serially: 15/17 pairings complete (960/960
  matches, 0 aborts, 0 faults); 2 pairings (M29A-v2-vs-M07, M31A-vs-M07)
  each contain one deterministic 10,000-ply engine safety-limit abort,
  preserved as invalid attempts with completed prefixes retained but not
  scored. No re-seeding was performed (frozen-seed rule).
- Core findings: M07 champion is strictly stronger than every scored
  direct-policy checkpoint (all win rates 17.2%–32.8%); within Cohort A,
  offline Top-1 does not monotonically predict Arena strength; four
  M25-canonical models beat or tie D2-v2 in direct play while all
  non-canonical-cohort models lose to it.
- PROMOTION: NONE, as pre-declared. The 2 aborted pairings are reported as
  a genuine engine/engine-policy interaction failure (endless take/pass
  loop), not hidden.
- Current status: `EXECUTED / PENDING_REVIEW` of execution results.

## Known limitations

- 2 of 17 pairings (M29A-v2 vs M07, M31A vs M07) could not complete: each
  contains a deterministic match that reaches the engine's frozen
  10,000-ply safety limit (an endless take/pass loop). Their completed
  prefixes (60 and 15 matches) are preserved but unscored; conclusions
  about those two models vs M07 are NOT available from this evaluation.
- The 9 checkpoints span three different offline data contracts; per the
  frozen cohort scope, offline-metric correlation analysis is restricted to
  the M25-canonical cohort (M25-D2-v2, M29A-v2, M31A, M32A, M33A, M34A) and
  must not be pooled across cohorts.
- M32A live belief features are reconstructed from the v0.5 event stream the
  arena actually delivers; parity is proven against the frozen sidecar on 6
  M25 replays (364 ply-seat comparisons), not on all 256 matches.
- Smoke matches (18 vs M07 + 2 neural-pair) validate launch, handshake,
  completion, and replay integrity only; they carry no competitive meaning
  and must not be reported as Arena results.
- Checkpoint files live under `local-artifacts/` (git-ignored); the Rust
  manifest test validates on-disk SHAs only when the files are present.
- Arena runs and the result payload are local-only artifacts; only the
  manifest, tests, docs, and result summaries are tracked in Git.

## Next authorized gate

- Independent review of the formal execution results (15 complete pairings
  + 2 deterministic engine-abort invalid attempts). No promotion is
  authorized from this milestone; M07 remains champion. Follow-up options
  for the reviewer to consider: (a) accept the 960-match result as final
  for M35A and close the milestone; (b) authorize a separately-scoped
  amendment (e.g. an engine-side iteration/termination rule change under a
  new milestone) before retrying the two aborted pairings — explicitly NOT
  a seed change.
