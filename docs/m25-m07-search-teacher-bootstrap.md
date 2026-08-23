# M25 — M07 Search-Teacher Bootstrap v2

```ini
MILESTONE = M25
STATUS = COMPLETED / M25_POLICY_TEACHER_FIT_FAIL / STOP_NO_ARENA
BASE_COMMIT = d75e10ca45fdf29d38101a04918e79435645512d
SCOPE = Canonical 256-game M07 self-play trajectory generation, soft search-target extraction, 32-epoch Entity Mixer (h192/b4) GPU training, frozen offline G1/G2/G3 acceptance gates, and fit attribution analysis.
DATASET = 256 games (128 seeds x 2 seat rotations), 16,282 decision plies, 100,000 micros uniform floor.
TRAINING = COMPLETED (32/32 epochs on CUDA; best epoch 5 selected by val CE + 0.5 * val MSE).
OFFLINE_GATES = G1 FAIL (Top-1 32.81% < 45.00%, CE bps 592 < 1000), G2 FAIL (26.02% < 38.00%), G3 FAIL (MSE 0.2717 > 0.2550).
FIT_ATTRIBUTION = Train top-1 32.06% (630 bps) vs Val top-1 32.81% (593 bps); underfitting on policy head (optimization / representation / model expressivity bottleneck).
DECISION = M25_POLICY_TEACHER_FIT_FAIL
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
6. **Phase 6 (Offline Acceptance Gates & Fit Attribution)**: Evaluate frozen gates G1 (Held-out teacher fit), G2 (Cross-distribution transfer on M24-S2 2,002 holdout positions), and G3 (Value non-collapse). Perform read-only Fit Attribution comparing training vs validation fit and analyzing teacher target entropy.

## Scope and non-goals

### In scope
- 128 canonical seeds x 2 seat rotations = 256 games between M07 self-play aliases.
- Soft search-distribution targets with exact 100,000 micros uniform floor.
- Seed-group partition: `seed_index % 4 == 0` assigning both rotations of a seed to either train or validation, preventing intra-seed leakage.
- Fresh-init Entity Mixer (h192/b4, 949,060 parameters) with no checkpoint inheritance.
- Frozen offline gates G1, G2, G3.
- Full fit attribution on train vs validation splits.

### Non-goals
- No architectural mutations during training.
- No learning rate sweeps or hyperparameter tuning.
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
- [x] Phase 6: Frozen offline gate evaluation, fit attribution, documentation update, and STOP.

## Iteration log

- **2026-08-23 Phase 1 Generation**: Executed 256 matches across 128 seeds. All 256 matches completed with 0 aborted and 0 faults.
- **2026-08-23 Phase 2 & 3 Target Extraction**: Extracted 16,282 decision plies into `TrainingDatasetV1` and generated exact soft policy/value targets via `SearchTeacherTargetSetV1`.
- **2026-08-23 Phase 4 Materializer Adjustment**: In deterministic self-play, rotation 0 and 1 on identical seeds produce matching replay content hashes. Updated `m25_dataset.py` and `m25_train.py` to key games by canonical `source_id` and `game_index` while preserving strict content hash validation.
- **2026-08-23 Phase 5 GPU Training**: Executed formal 32-epoch training on NVIDIA GeForce RTX 4060 Laptop GPU. Best epoch 5 achieved validation score 3.0368.
- **2026-08-23 Phase 6 Gate Evaluation & STOP**: Evaluated G1, G2, and G3. All three gates failed against the frozen thresholds. Emitted decision `M25_POLICY_TEACHER_FIT_FAIL`. Arena authorization remained `NOT_AUTHORIZED`.
- **2026-08-23 Fit Attribution**: Evaluated the best epoch 5 checkpoint on both train (12,216 examples) and validation (4,066 examples). Found train top-1 at 32.06% (630 bps) vs validation top-1 at 32.81% (593 bps), confirming a severe underfitting bottleneck rather than a generalization/overfitting gap on the policy head.

## Final implementation

### Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Preregistered Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Result Document | `benchmarks/m25-m07-search-teacher-bootstrap-v2.result.json` | Bound result artifact with fit attribution |
| League Manifest | `local-artifacts/m25-generation/league-manifest.json` | `42be03260c8cb0a908a8d16d13d71ba826fcfe0a89fc0cba002efc2a9ec67735` |
| Evaluation Plan | `local-artifacts/m25-generation/evaluation-plan.json` | Plan hash: `6f82ccef1e9f229ec47ce4561369d4d97b51119ffab41e7eb4d8f1e7b7fe8e73` |
| Evaluation Report | `local-artifacts/m25-generation/eval-run/evaluation-report.json` | Report hash: `123e25c95b9523e399e4c46b5a9d7b3dfe3d48ed01e1c151595198f80adc4696` |
| Training Dataset | `local-artifacts/m25-generation/training-dataset.json` | Dataset hash: `b0adbea50da9ae75a5566a4512679bb4a587adcc6725e4cf1a631bad59353fb7` |
| Search Targets | `local-artifacts/m25-generation/search-teacher-targets.json` | Targets hash: `c52912e6f8c730b8e7d2721fdbd5854ae95ab4125974c661604d468ab793e9fc` |
| Materialized Dataset | `local-artifacts/m25-generation/m25-materialized-dataset.json` | File SHA: `2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907`<br>Semantic Hash: `1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419` |
| Trained Checkpoint | `local-artifacts/m25-training-run-v1/checkpoint.pt` | File SHA: `aaaab9c00e526f9cd0d976371d753417f55245e15caa14336407c3b1ae153a02`<br>Checkpoint Hash: `23e1f0dd666eeadc0dc7cd32f68816f3bad284ae09ef2744bb59e545b4408249` |
| Training Report | `local-artifacts/m25-training-run-v1/training-report.json` | Best Epoch: 5, Score: 3.0368 |
| Offline Result | `local-artifacts/m25-training-run-v1/offline-result.json` | Decision: `M25_POLICY_TEACHER_FIT_FAIL` |

## Validation and evidence

### Training metrics progression
- Epoch 1: val score 3.0719 (val top-1 29.61%, val CE 2.9511, val MSE 0.2417)
- Epoch 2: val score 3.0440 (val top-1 30.55%, val CE 2.9201, val MSE 0.2478)
- Epoch 5 (Best): val score **3.0368** (val top-1 **32.81%**, val CE **2.9009**, val MSE **0.2717**)
- Epoch 32: val score 3.2749 (val top-1 26.36%, val CE 3.0606, val MSE 0.4286)

### Frozen offline acceptance gates

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

### Fit Attribution Analysis (Best Checkpoint @ Epoch 5)

| Metric | Train Split (12,216 ex) | Validation Split (4,066 ex) | Gap (Val - Train) |
| --- | --- | --- | --- |
| **Policy Top-1 Agreement** | **32.06%** | **32.81%** | +0.75% |
| **Policy Cross-Entropy** | **2.8729** | **2.9009** | +0.0280 |
| **Legal-Uniform CE** | **3.0660** | **3.0837** | +0.0177 |
| **CE Improvement vs Uniform** | **630 bps** | **593 bps** | -37 bps |
| **Value MSE** | **0.2067** | **0.2717** | +0.0650 |

#### Teacher Target Distribution Statistics

| Metric | Train Split | Validation Split | Combined (16,282 plies) |
| --- | --- | --- | --- |
| **Mean Target Entropy (nats)** | 2.4501 | 2.4729 | 2.4558 |
| **Mean Top-1 Probability Mass** | 28.00% | 27.69% | 27.92% |
| **Legal Action Count (Mean)** | 30.00 | 29.76 | 29.94 |
| **Legal Action Count (Median)** | 25 | 25 | 25 |
| **Legal Action Count (P25 / P75 / P95)** | 14 / 28 / 66 | 15 / 28 / 67 | 14 / 28 / 66 |
| **Legal Action Count (Min / Max)** | 1 / 575 | 1 / 575 | 1 / 575 |

## Result and decision

1. **Gate G1 Failed**: Validation policy top-1 reached 32.81% (threshold $ge 45.00%$), and CE improvement over legal uniform was 592 bps (threshold $ge 1000	ext{ bps}$).
2. **Gate G2 Failed**: Zero-shot cross-distribution transfer agreement on the 2,002 M24 holdout positions reached 26.02% (threshold $ge 38.00%$).
3. **Gate G3 Failed**: Validation value MSE (0.2717) exceeded the maximum allowed threshold (0.2550).
4. **Attribution Finding**:
   - The policy head fit is virtually identical between train (32.06%, 630 bps) and validation (32.81%, 593 bps).
   - This proves that the policy failure is **not** driven by generalization error or lack of trajectory diversity between seed groups.
   - Instead, the bottleneck lies in **optimization / representation / model expressivity**: the 0.95M-parameter Entity Mixer architecture struggles to absorb the high-entropy M07 search distribution (mean target entropy 2.456 nats across ~30 legal actions) even on its own training set.
5. **Final Decision**: `M25_POLICY_TEACHER_FIT_FAIL`.
6. **Arena Execution**: `NOT_AUTHORIZED` (no Arena matches were started).
7. **Promotion**: `NONE`. M07 heuristic determinization champion remains unchanged.

## Known limitations

- Direct behavioral cloning of soft M07 search distributions using a small Entity Mixer (h192/b4) from 256 games underfits the training policy target (only 32.06% top-1 fit).
- The value head experiences non-negligible error on terminal outcomes when trained jointly with cross-entropy loss under fixed equal weighting.

## Next authorized gate

- M25 execution is fully completed and stopped.
- Any downstream exploration requires formal preregistration and review.
