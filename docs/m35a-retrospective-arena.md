# M35A — Historical Neural Checkpoint Direct Policy Retrospective Arena

```ini
MILESTONE = M35A
STATUS = IMPLEMENTED / VERIFIED / REVIEW_REPAIR_1_APPLIED / PENDING_EVALUATION_EXECUTION
BASE_COMMIT = f46147c0b82f0fa5653457a419ebf8fbc0df7325
SCOPE = Evaluate the true game-playing strength of 9 historical neural network checkpoints via direct legal-action policy scoring (argmax over server-certified legal actions, without search) in paired-seed Arena matches against M07 Champion and D2-v2 Benchmark.
DATASET / MATCHES = 32 paired seeds (300001..300032) x 2 seat rotations = 64 games per pairing; 9 vs M07 (576 games) + 8 vs D2-v2 (512 games) = 1,088 total matches.
CHAMPION = M07 (Determinization Search, sample-seed=20260810, sample-count=4, depth=1, max-nodes=2000)
BENCHMARK = M25 D2-v2 (DeltaEntityMixer h192/b4, 59-dim exact action deltas)
CHECKPOINTS = M24-S2, M25-D2-v2, M28A, M28B, M29A-v2, M31A, M32A, M33A, M34A
ARENA_PROTOCOL = NDJSON Protocol v0.5 over stdio (splendor eval / run-match)
EXECUTION_DEVICE = CPU (single/dual-thread bounded, zero CUDA initialization overhead)
PROMOTION = NONE (Exploratory retrospective diagnostic; does not retroactively alter offline gate verdicts or promote checkpoints).
DECISION = PENDING_EVALUATION_EXECUTION
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
- [ ] Staged review: present complete plan and test verification before executing 1,088 Arena matches.

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
  findings. Review repair 1 addressed all of them in a single round:
  entry-point launchability, real transcript parity, M32A color-order fix,
  and manifest binding surface.
- Current status: `IMPLEMENTED / VERIFIED / REVIEW_REPAIR_1_APPLIED /
  PENDING_EVALUATION_EXECUTION`. The 1,088-match formal Arena remains on
  HOLD until the next review round approves execution.

## Known limitations

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

## Next authorized gate

- Independent review of review repair 1 (entry point, parity test realism,
  color order, manifest hardening, cohort freeze). On approval, execute the
  17 realized plans for the 1,088 formal Arena matches under the frozen
  seeds, timeouts, and commands.
