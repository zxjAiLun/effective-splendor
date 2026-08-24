# M25 — M07 Search-Teacher Bootstrap v2

```ini
MILESTONE = M25
STATUS = COMPLETED / M25_POLICY_TEACHER_FIT_FAIL / STOP_NO_ARENA
BASE_COMMIT = d75e10ca45fdf29d38101a04918e79435645512d
SCOPE = Canonical 256-game M07 self-play trajectory generation, soft search-target extraction, 32-epoch Entity Mixer (h192/b4) GPU training, frozen offline G1/G2/G3 acceptance gates, fit attribution, and lean recovery experiments (A–E).
DATASET = 256 games (128 seeds x 2 seat rotations), 16,282 decision plies, 100,000 micros uniform floor.
TRAINING = COMPLETED (32/32 epochs on CUDA; best epoch 5 selected by val CE + 0.5 * val MSE).
OFFLINE_GATES = G1 FAIL (Top-1 32.81% < 45.00%, CE bps 592 < 1000), G2 FAIL (26.02% < 38.00%), G3 FAIL (MSE 0.2717 > 0.2550).
FIT_ATTRIBUTION = Train top-1 32.06% (630 bps) vs Val top-1 32.81% (593 bps); underfitting on policy head (optimization / representation / model expressivity bottleneck).
LEAN_RECOVERY = 2x2 Action-Coupling x Width Matrix complete. Action delta features confirmed as primary bottleneck (Val CE 2.8177, Top-1 38.42%, +227 bps over baseline); width scaling confirmed ineffective (h320 vs h192 diff <0.002 nats).
DECISION = M25_POLICY_TEACHER_FIT_FAIL / STOP_WIDTH_SCALING_TRANSITION_TO_OBJECTIVE_V2
ARENA = NOT_AUTHORIZED
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

The M24-S2 teacher audit (`benchmarks/m24-s2-teacher-target-quality-audit-v1.result.json`) confirmed that historical neural self-play datasets inherited weak search-distribution supervision from low-budget (16-sim) neural rollouts. Subsequent scale and capacity explorations (M24-S2, M27A, M28A, M28B) failed to produce competitive policy improvements against the frozen M07 heuristic search champion.

The M25 question was:

> With strong M07-vs-M07 self-play trajectories and soft M07 search-distribution supervision replacing weak M22 self-play targets, does the frozen Entity Mixer (h192/b4, 949,060 parameters) learn a strong policy function that transfers across state distributions and unlocks competitive strength?

## Initial design

M25 established a 6-phase end-to-end pipeline:
1. **Phase 1 (Canonical Corpus)**: Run 256 matches across 128 seeds (`20260825..20260952`) with 2 seat rotations under the canonical `LeagueManifestV1` using registered aliases `m07-bootstrap-a` and `m07-bootstrap-b` (each sharing the exact frozen `DeterminizationAgentPolicyV1` implementation: sample seed 20260810, 4 samples, 1 depth turn, 2000 max nodes).
2. **Phase 2 (TrainingDatasetV1)**: Aggregate matches and verified replays via `splendor build-dataset`.
3. **Phase 3 (SearchTeacherTargetSetV1)**: Compute soft search-distribution policy targets with 100,000 micros uniform floor and terminal outcome value targets via `splendor build-search-teacher-targets`.
4. **Phase 4 (Materialization)**: Combine `TrainingDatasetV1` and `SearchTeacherTargetSetV1` via `splendor_gpu.m25_dataset` with strict 4-way provenance verification, seed-group split (32 validation seeds / 64 games vs 96 training seeds / 192 games), and binary cache packing.
5. **Phase 5 (Formal GPU Training)**: Train fresh Entity Mixer (h192/b4, 949,060 parameters) for 32 epochs on CUDA using AdamW (lr 1e-4, wd 1e-4, grad clip 1.0, value weight 0.5, seed 280229) with best epoch selection on validation `CE + 0.5 * MSE`.
6. **Phase 6 (Offline Acceptance Gates & Lean Recovery)**: Evaluate frozen gates G1 (Held-out teacher fit), G2 (Cross-distribution transfer on M24-S2 2,002 holdout positions), and G3 (Value non-collapse). Perform read-only Fit Attribution comparing training vs validation fit. Execute lean recovery experiments (A–E) to isolate optimization, multi-task, capacity, and action representation bottlenecks.

## Scope and non-goals

### In scope
- 128 canonical seeds x 2 seat rotations = 256 games between M07 self-play aliases.
- Soft search-distribution targets with exact 100,000 micros uniform floor.
- Seed-group partition: `seed_index % 4 == 0` assigning both rotations of a seed to either train or validation, preventing intra-seed leakage.
- Fresh-init Entity Mixer (h192/b4, 949,060 parameters) with no checkpoint inheritance.
- Frozen offline gates G1, G2, G3.
- Full fit attribution and controlled 2x2 recovery experiments (Experiments A, B, C, D2, E).

### Non-goals
- No architectural mutations during formal training.
- No Arena matches before offline gate evaluation.
- No auto-promotion to champion.

## Contracts and invariants

- **Deterministic Self-Play Provenance**: In deterministic M07 self-play, identical seed and identical policy produce identical move sequences across rotation 0 and rotation 1. Replays are keyed and linked by unique `source_id` (`match-000000`..`match-000255`) while asserting valid `replay_document_hash` matching.
- **Strict Provenance Binding**: Materialization validates `league_manifest_hash`, `evaluation_plan_hash`, `evaluation_report_hash`, and `training_dataset_hash_v1` before joining.
- **Fail-Closed Gate Decision**: Any gate failure automatically sets `arena_authorization = "NOT_AUTHORIZED"`.

## Implementation plan

- [x] Phase 1: Canonical M07 trajectory corpus generation (256 games).
- [x] Phase 2: Canonical TrainingDatasetV1 extraction.
- [x] Phase 3: M07 SearchTeacherTargetSetV1 target generation.
- [x] Phase 4: M25 dataset materialization and cache encoding.
- [x] Phase 5: 32-epoch GPU training on CUDA.
- [x] Phase 6: Frozen offline gate evaluation, fit attribution, recovery experiments (A–E), documentation update, and STOP.

## Iteration log

- **2026-08-23 Phase 1 Generation**: Executed 256 matches across 128 seeds. All 256 matches completed with 0 aborted and 0 faults.
- **2026-08-23 Phase 2 & 3 Target Extraction**: Extracted 16,282 decision plies into `TrainingDatasetV1` and generated exact soft policy/value targets via `SearchTeacherTargetSetV1`.
- **2026-08-23 Phase 4 Materializer Adjustment**: In deterministic self-play, rotation 0 and 1 on identical seeds produce matching replay content hashes. Updated `m25_dataset.py` and `m25_train.py` to key games by canonical `source_id` and `game_index` while preserving strict content hash validation.
- **2026-08-23 Phase 5 GPU Training**: Executed formal 32-epoch training on NVIDIA GeForce RTX 4060 Laptop GPU. Best epoch 5 achieved validation score 3.0368.
- **2026-08-23 Phase 6 Gate Evaluation & STOP**: Evaluated G1, G2, and G3. All three gates failed against the frozen thresholds. Emitted decision `M25_POLICY_TEACHER_FIT_FAIL`. Arena authorization remained `NOT_AUTHORIZED`.
- **2026-08-23 Fit Attribution**: Evaluated the best epoch 5 checkpoint on both train (12,216 examples) and validation (4,066 examples). Found train top-1 at 32.06% (630 bps) vs validation top-1 at 32.81% (593 bps), confirming a severe underfitting bottleneck rather than a generalization/overfitting gap on the policy head.
- **2026-08-23 Sanity Test (1024 Subset)**: Saturated 1024-subset training to Excess CE = 0.0145 nats (73.83% Top-1), proving the h192/b4 Entity Mixer has sufficient parameter memory to fit teacher distributions.
- **2026-08-23 Recovery Exp A (Policy-Only 128ep)**: Val CE = 2.8879, Top-1 = 31.87% (+0.4150 nats excess CE), ruling out value multi-task interference and simple epoch scarcity as primary bottlenecks.
- **2026-08-23 Recovery Exp B (h320 Width Probe)**: Val CE = 2.8878, Top-1 = 32.76% (+0.4149 nats excess CE), ruling out global model width/capacity as primary bottleneck.
- **2026-08-23 Recovery Exp C (Contextual Interaction Probe)**: Val CE = 2.8866, Top-1 = 32.22% (+0.4137 nats excess CE), ruling out generic pairwise observation interaction.
- **2026-08-23 Recovery Exp D2 (Exact Transition Delta Probe)**: Fixed reserve gold/token return rules and noble VP triggers. Achieved Val CE = 2.8177 (-0.0702 nats vs Exp A), Top-1 = 38.42% (+6.54 pp vs Exp A), confirming action-conditioned transition coupling as a strong signal.
- **2026-08-23 Recovery Exp E (h320 + Exact Transition Delta)**: Completed the 2x2 matrix. Achieved Val CE = 2.8157, Top-1 = 38.47% (869 bps CE impr). Since G1 (45.0% / 1000 bps) was not reached and width scaling delivered no meaningful gain over h192 (+0.0020 nats / +0.05 pp), formal decision concluded: `STOP_WIDTH_SCALING_TRANSITION_TO_OBJECTIVE_V2`.

## Final implementation

### Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Preregistered Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Result Document | `benchmarks/m25-m07-search-teacher-bootstrap-v2.result.json` | Formal M25 Result Artifact |
| Fit Attribution Sanity | `benchmarks/m25-policy-fit-sanity.result.json` | 1024-subset policy fit result |
| Recovery Exp A Result | `benchmarks/m25-recovery-exp-a.result.json` | Full data policy-only control |
| Recovery Exp B Result | `benchmarks/m25-recovery-exp-b.result.json` | Full data h320 width probe |
| Recovery Exp C Result | `benchmarks/m25-recovery-exp-c.result.json` | Full data contextual interaction probe |
| Recovery Exp D2 Result | `benchmarks/m25-recovery-exp-d2.result.json` | Exact action-delta probe (h192) |
| Recovery Exp E Result | `benchmarks/m25-recovery-exp-e.result.json` | Exact action-delta probe (h320) |
| Checkpoint Exp D2 | `local-artifacts/m25-recovery-exp-d2-v2/checkpoint.pt` | `113372fc1092e611804cb7261844ac2a104608772f68ab74a854a038370c7e17` |
| Checkpoint Exp E | `local-artifacts/m25-recovery-exp-e/checkpoint.pt` | `b81c95f6260137d4686f2ec0c9d7ca505c8dd452052dcf1cbb867332128b9f53` |
| Materialized Dataset | `local-artifacts/m25-generation/m25-materialized-dataset.json` | File SHA: `2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907`<br>Semantic Hash: `1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419` |
| Formal Checkpoint | `local-artifacts/m25-training-run-v1/checkpoint.pt` | File SHA: `aaaab9c00e526f9cd0d976371d753417f55245e15caa14336407c3b1ae153a02`<br>Checkpoint Hash: `23e1f0dd666eeadc0dc7cd32f68816f3bad284ae09ef2744bb59e545b4408249` |
| Offline Result | `local-artifacts/m25-training-run-v1/offline-result.json` | Decision: `M25_POLICY_TEACHER_FIT_FAIL` |

## Validation and evidence

### Formal 32-epoch Training Metrics Progression
- Epoch 1: val score 3.0719 (val top-1 29.61%, val CE 2.9511, val MSE 0.2417)
- Epoch 2: val score 3.0440 (val top-1 30.55%, val CE 2.9201, val MSE 0.2478)
- Epoch 5 (Best): val score **3.0368** (val top-1 **32.81%**, val CE **2.9009**, val MSE **0.2717**)
- Epoch 32: val score 3.2749 (val top-1 26.36%, val CE 3.0606, val MSE 0.4286)

### Frozen Offline Acceptance Gates (Best Checkpoint @ Epoch 5)

```json
{
  "g1_heldout_teacher_fit": {
    "pass": false,
    "validation_policy_top1": 0.3280865715691097,
    "validation_policy_ce": 2.9008806746579485,
    "uniform_policy_ce": 3.0836541094107153,
    "policy_ce_improvement_bps_vs_uniform": 592,
    "threshold_top1": 0.45,
    "threshold_ce_bps": 1000
  },
  "g2_cross_distribution_transfer": {
    "pass": false,
    "holdout_m07_agreement": 0.26023976023976025,
    "threshold_agreement": 0.38,
    "holdout_details": {
      "expected_positions": 2002,
      "matched_positions": 2002,
      "missing_positions": 0,
      "duplicate_positions": 0,
      "hash_mismatches": 0,
      "legal_action_mismatches": 0,
      "agreements": 521,
      "m07_top1_agreement": 0.26023976023976025
    }
  },
  "g3_value_non_collapse": {
    "pass": false,
    "validation_value_mse": 0.2717495309385946,
    "baseline_value_mse": 0.24999977483341276,
    "max_allowed_value_mse": 0.25499977033008103
  },
  "decision": "M25_POLICY_TEACHER_FIT_FAIL",
  "arena_authorization": "NOT_AUTHORIZED"
}
```

### Controlled 2x2 Recovery Matrix (128 Epochs, Policy-Only)

| Action Representation \ Architecture | h192/b4 (~0.95M parameters) | h320/b4 (~2.61M parameters) | Width Effect ($Delta$ h320 - h192) |
| :--- | :--- | :--- | :--- |
| **Baseline Action (36-dim)** | **Exp A**: Val CE 2.8879<br>Excess CE: +0.4150 nats<br>Top-1: 31.87% (635 bps) | **Exp B**: Val CE 2.8878<br>Excess CE: +0.4149 nats<br>Top-1: 32.76% (635 bps) | $Delta	ext{CE} = -0.0001	ext{ nats}$<br>$Delta	ext{Top-1} = +0.89	ext{ pp}$ |
| **Exact Action Delta (59-dim)** | **Exp D2**: Val CE 2.8177<br>Excess CE: +0.3449 nats<br>Top-1: 38.42% (862 bps) | **Exp E**: Val CE 2.8157<br>Excess CE: +0.3428 nats<br>Top-1: 38.47% (869 bps) | $Delta	ext{CE} = -0.0020	ext{ nats}$<br>$Delta	ext{Top-1} = +0.05	ext{ pp}$ |
| **Action Feature Effect** | $Delta	ext{CE} = mathbf{-0.0702	ext{ nats}}$<br>$Delta	ext{Top-1} = mathbf{+6.55	ext{ pp}}$ | $Delta	ext{CE} = mathbf{-0.0721	ext{ nats}}$<br>$Delta	ext{Top-1} = mathbf{+5.71	ext{ pp}}$ | **Dominant Factor: Action Coupling** |

## Result and decision

1. **Gate G1/G2/G3 Failed**: Formal 32-epoch Entity Mixer failed all three offline acceptance gates (`M25_POLICY_TEACHER_FIT_FAIL`).
2. **2x2 Controlled Recovery Matrix Conclusion**:
   - **Width Scaling Ineffective**: In both baseline action encoding (Exp B vs Exp A) and delta action encoding (Exp E vs Exp D2), increasing model width by 2.75x (0.95M $	o$ 2.61M params) produces negligible validation gains ($le 0.0020	ext{ nats}$ CE reduction).
   - **Action Coupling Confirmed**: Injecting explicit post-action state delta features (Exp D2/E) yields a substantial and consistent validation breakthrough ($sim 0.07	ext{ nats}$ CE improvement, $+6.5	ext{ pp}$ Top-1 increase).
   - **G1 Gap Remains**: Even with exact action delta features, h320 reaches 38.47% Top-1 and 869 bps CE improvement, falling short of G1's 45.00% Top-1 / 1000 bps threshold.
3. **Formal Direction Decision**:
   - **STOP width scaling** (no further h320/h512 exploration on current setup).
   - **Transition to Action Representation & Loss Objective v2** (e.g. deeper relational state-action coupling, target distillation/temperature calibration, or contrastive action ranking).
4. **Arena Execution**: `NOT_AUTHORIZED` (no Arena matches were started).
5. **Promotion**: `NONE`. M07 heuristic determinization champion remains unchanged.

## Known limitations

- Direct behavioral cloning of soft M07 search distributions without action-conditioned delta features suffers an information bottleneck at ~32% Top-1.
- Exact post-action delta features alleviate the bottleneck (+6.5 pp), but imitation learning alone on 256 games still encounters target ambiguity from high-entropy search teacher distributions (mean entropy 2.456 nats).

## Next authorized gate

- M25 execution and lean recovery explorations are fully completed and stopped.
- Downstream milestone exploration (Action Representation / Objective v2) requires formal preregistration and review.
