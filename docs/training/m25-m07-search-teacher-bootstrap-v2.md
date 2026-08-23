# M25 — M07 Search-Teacher Bootstrap v2

```ini
MILESTONE = M25
REVISION = m07-search-teacher-bootstrap-v2
STATUS = PREREGISTERED / WAITING_REVIEW
BASELINE_COMMIT = 140ef8248df029a32bcf6d34db436351563fa28c
CONFIG = benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json
CONFIG_SHA256 = bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250
HOLDOUT = benchmarks/m24-s2-2002-audit-holdout.json
HOLDOUT_SHA256 = 331654ba370a489053bcf6cd0452d7aa4883b6c64d5db0be757c4a42860f05f8
SINGLE_VARIABLE = supervision_source_and_trajectory
TRAINING = HOLD pending source review
ARENA = NOT_AUTHORIZED
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

The **M24-S2 Teacher/Target Quality Audit** (`benchmarks/m24-s2-teacher-target-quality-audit-v1.result.json`) demonstrated that the 16-simulation, depth-1 neural search used to generate the M24-S2 training corpus inherits **92.01% [90.72%, 93.27%]** top-1 choices directly from the weak M22 prior (`dc611f3...`), and only improves agreement with the strong M07 reference by **+0.60% [0.05%, 1.15%]** (from 28.07% to 28.67%).

Consequently, student models (M24, M28A, M28B) were accurately fitting a biased teacher distribution.

### Historical context and synthesis

Historical milestones previously evaluated individual elements in isolation:
1. **M15B / M17**: Used M07 one-hot policy labels on a small dataset (3,920 examples) with mixed trajectory distributions -> underfit and failed heuristic screen (1–7).
2. **M15C / M15D**: Used soft M07 search-distribution targets on small models (h32/h64, 16-24 epochs) -> severe underfitting (validation top-1 ~30.98%).
3. **M24 / M28**: Used large datasets (31,505 examples) and modern Entity Mixer (h192/b4, 949k params) with mature GPU training -> corrupted by weak M22 teacher targets.

**M25 synthesizes the valid components together for the first time**:
$$\text{Strong M07 Trajectories} + \text{Soft M07 Search Targets (10% floor)} + \text{Modern Entity Mixer (h192/b4)} + \text{M28 GPU Optimizer Recipe}$$

## Core research question

> Without altering the verified Entity Mixer architecture (h192/b4, 949,060 parameters) or AdamW optimization recipe, does replacing weak M22 supervision with strong M07-vs-M07 self-play trajectories and soft M07 search-distribution targets enable the raw neural policy to achieve high-fidelity alignment with M07 on both held-out and cross-distribution benchmarks?

## Pre-registered experimental design

### 1. Dataset generation
- **Generator**: `m07-determinization-champion` playing self-play matches in 2-player base rules via two canonical identity aliases (`m07-bootstrap-a` vs `m07-bootstrap-b`, sharing the identical `DeterminizationAgentPolicyV1` / search configuration).
- **Volume**: Exactly 256 games (128 distinct seeds `20260825..20260952` $\times$ 2 seat rotations, `~15,000 - 16,000` decision plies).
- **Split**: Disjoint by seed group: `seed_index % 4 == 0` (32 seeds $\times$ 2 rotations = 64 validation games), remaining (96 seeds $\times$ 2 rotations = 192 train games). Both rotations of each seed remain in the same split to eliminate trajectory leakage.
- **Supervision Target**:
  - **Policy**: Soft search distribution computed by frozen M07 determinization search (`sample_seed=20260810, sample_count=4, max_depth_turns=1, max_nodes=2000, uniform_floor_micros=100000`).
  - **Value**: Viewer-relative terminal rank outcome ($[1.0 - \text{rank}_{\text{actor}}, 1.0 - \text{rank}_{1-\text{actor}}]$); 2P matches are typically $[1.0, 0.0]$ / $[0.0, 1.0]$, and an exact tie is legally $[1.0, 1.0]$.

### 2. Model contract
- **Architecture**: `entity_mixer`
- **Hidden Dim**: 192
- **Blocks**: 4 residual blocks
- **Dropout**: 0.0
- **Interaction Blocks**: 0 (no contextual block mutations)
- **Parameters**: Exactly 949,060 parameters
- **Initialization**: Fresh random seed `280229` (no checkpoint inheritance)

### 3. Training contract
- **Optimizer**: AdamW (learning rate `1e-4`, weight decay `1e-4`, gradient clip norm `1.0`)
- **Batch Size**: 128
- **Epochs**: 32
- **Value Loss Weight**: 0.5
- **Best Epoch Selection**: `policy_cross_entropy + 0.5 * value_mse` on M07 validation games only.
- **Deterministic Flags**: `CUBLAS_WORKSPACE_CONFIG=:4096:8`, `torch.use_deterministic_algorithms(True)`
- **Thermal Safety**: Sensor-specific bounds with fail-closed background polling.

## Pre-registered offline acceptance gates

### G1 — Held-out M07 Teacher Fit
- **Requirement**: On the 64 unobserved validation games:
  - Validation Policy Top-1 (\ge 45.00\%) (exceeding historical M17 baseline 36.91%).
  - Policy Cross-Entropy relative improvement vs legal uniform (\ge 1000) bps (10.00%), where (CE_{uniform} = \frac{1}{N}\sum_i \log |A_i|).

### G2 — Cross-Distribution M07 Agreement
- **Requirement**: Evaluated in zero-shot raw forward inference over the frozen 2,002-position audit holdout (`benchmarks/m24-s2-2002-audit-holdout.json`, SHA256 `331654ba370a...`):
  - Top-1 Agreement with M07 (\ge 38.00\%) (an absolute gain of (\ge +10\%) over M22's baseline 28.07%).

### G3 — Value Non-Collapse
- **Requirement**: Held-out validation Value MSE (\le 1.02 \times \text{empirical training outcome prior baseline MSE}), where the baseline MSE is computed by evaluating the constant training-mean outcome vector against validation targets.

### Decision tree

```text
G1 FAIL
    -> M25_POLICY_TEACHER_FIT_FAIL (Stop; investigate optimization / capacity)

G1 PASS and G2 FAIL
    -> M25_TEACHER_FIT_NO_TRANSFER (Stop; investigate state representation / distribution shift)

G1 PASS and G2 PASS and G3 FAIL
    -> M25_POLICY_SIGNAL_VALUE_BLOCKED (Hold; open isolated M25B value target repair)

G1 PASS and G2 PASS and G3 PASS
    -> M25_ARENA_ELIGIBLE (Authorize compact 128-game Arena evaluation vs M07 and Heuristic)
```

## Arena evaluation scope (conditional on G1+G2+G3 PASS)

- **Matchup 1**: M25 vs M07 Champion (32 seeds x 2 seat rotations = 64 games).
- **Matchup 2**: M25 vs Heuristic Baseline (32 seeds x 2 seat rotations = 64 games).
- **Total**: 128 games.
- **Practical Signal Threshold**: Score (\ge 40\%) vs M07 to consider neural self-play continuation in M26.
- **Promotion**: `NONE` (M07 remains champion until formal promotion gate).

## Implementation and Review Iterations

### Repair 1 (2026-08-22)
- Fixed G1 theoretical uniform cross-entropy baseline formula ($\frac{1}{N}\sum \ln |A_i|$).
- Fixed G2 cross-distribution holdout evaluation to join on exact (game_index, ply, actor, observation_hash, information_set_hash) and execute fail-closed.
- Fixed G3 baseline MSE to compute training-mean outcome vector against validation targets.
- Created frozen M25 configuration and production trainer.

### Repair 2 (2026-08-22)
- Replaced non-existent cache build method with `build_m25_encoded_cache` adapter writing to mapped tensors.
- Implemented M25 dataset materializer and semantic hash domain `effective-splendor-m25-search-teacher-dataset-v1\0`.
- Restored microbatched execution (batch 128 / microbatch 32), gradient accumulation, and soft thermal pacing.
- Corrected M24-S2 dataset hash to authoritative `self_play_hash` domain.

### Repair 3 (2026-08-22)
- **P1-1 (Authoritative Splendor Dense Rank Values)**: Fixed terminal value target computation to directly read authoritative `replay.result.ranks` instead of recomputing scores/card counts in Python, properly handling exact ties ($[0,0] \to [1.0, 1.0]$) and engine tiebreak dense ranks.
- **P1-2 (Fail-Closed Provenance Join)**: Removed all fallback defaults in `materialize_m25_dataset`; strictly enforced `replay_document_hash`, `game_index`, `source_id`, `ply`, `actor`, rejecting unmatched or duplicate records.
- **P1-3 (Teacher Artifact Strict Config Binding)**: Bound input SearchTeacherTargetSet config (`sample_seed`, `sample_count`, `max_depth_turns`, `max_nodes`, `uniform_floor_micros`) against frozen preregistration.
- **P1-4 (Trainer Provenance Validator)**: Bound `train_m25` to verify full internal game/example linkage, replay ranks, and teacher configuration.
- **P2-1 (True Bridge E2E Smoke Test)**: Updated smoke test to exercise raw replays + TrainingDatasetV1 + SearchTeacherTargetSetV1 $\to$ `materialize_m25_dataset` $\to$ cache $\to$ training $\to$ holdout $\to$ gate decision.
- **P2-2 (Materialization CLI)**: Added CLI entry point to `training/m17_gpu/splendor_gpu/m25_dataset.py`.

### Repair 3A (2026-08-22)
- **P1-1 (Mandatory game_index & Consistency)**: Enforced required `game_index` in materializer with fail-closed rejection on missing or inconsistent values.
- **P1-2 (Mandatory Provenance & M07 Seat Assertion)**: Made `provenance` and `provenance.teacher_config` unconditionally required in `validate_m25_dataset_provenance`, asserting both player seats are `m07-determinization-champion`.
- **P1-3 (Checkpoint & Report Metadata Binding)**: Bound `source_dataset_file_sha256`, `source_dataset_semantic_hash`, `encoded_cache_manifest_sha256`, and `training_config_hash` into `checkpoint.pt` and `training-report.json`.
- **P2-1 (Raw File SHA256 Recording)**: Recorded `source_training_dataset_file_sha256` and `source_search_targets_file_sha256` in dataset metadata.
- **P2-2 (Value Target Documentation)**: Documented exact tie value target $[1.0, 1.0]$.

### Repair 3B (2026-08-22)
- **P1 (Canonical TrainingDatasetV1 Schema Alignment)**: Aligned M25 Materializer to take Rust `TrainingDatasetV1` (`replays[]` + `examples[]`) directly as the replay provenance authority, eliminating synthetic hybrid schemas; derived `game_index` from `replay_document_hash -> replay.evaluation_match_index`.

### Canonical Generation Binding (2026-08-22)
- **1. Determinization Agent Runtime Identity Aliasing**: Added `--runtime-name` and `--runtime-version` CLI flags and `run_determinization_agent_with_identity_v1` to allow executing M07 self-play matches between `m07-bootstrap-a` and `m07-bootstrap-b` under a valid `LeagueManifestV1` without violating agent ID / runtime identity uniqueness invariants. Both aliases share the exact immutable `DeterminizationAgentPolicyV1` / M07 search mathematics.
- **2. 128 Seeds $\times$ 2 Rotations Schedule**: Pre-registered 128 distinct seeds (`20260825..20260952`) with 2 seat rotations per seed, producing exactly 256 games.
- **3. Seed-Group Split (96/32 Seeds = 192/64 Games)**: Split assigned by `seed_index % 4 == 0` (32 validation seeds $\times$ 2 rotations = 64 validation games; 96 train seeds $\times$ 2 rotations = 192 train games). Both seat rotations of every seed remain together in the same split to strictly eliminate trajectory leakage.
- **4. Strict Cross-Binding & Provenance**: Materializer strictly validates cross-binding of `dataset_id`, `league_manifest_hash`, `evaluation_plan_hash`, and `evaluation_report_hash` between `TrainingDatasetV1` and `SearchTeacherTargetSetV1`, and deleted all legacy raw-replays fallback entries.
- **5. Canonical E2E Smoke & Integration**: Full integration test exercises canonical 128 seeds $\times$ 2 rotations `TrainingDatasetV1` $\to$ `materialize_m25_dataset` $\to$ cache $\to$ trainer $\to$ holdout.

