# M31A — Objective-v2: Weighted Pairwise Logistic Ranking Auxiliary Loss

```ini
MILESTONE = M31A
STATUS = ACCEPTED / CLOSED / STOP_WEIGHTED_PAIRWISE_LOGISTIC_RANKING_ROUTE / NO_ARENA / NO_FURTHER_MODEL_TRAINING
BASE_COMMIT = 489592ef65306ea64e320f86915222955feebda7
SCOPE = Evaluate composite policy loss objective L = L_canonical_CE + 0.5 * L_weighted_pairwise_logistic on top of canonical D2 architecture (h192/b4, 59-dim exact action deltas, 953,476 parameters, 128 epochs) to test whether explicit pairwise teacher ranking margin breaks the student fit ceiling without sacrificing soft-target cross-entropy calibration.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
TRAINING = COMPLETED (128 epochs in 110.3s, lr=3e-4 cosine, wd=1e-4, best epoch 13 selected strictly by validation canonical policy CE = 2.8375, excess CE = +0.3646, val Top-1 = 35.91%, impr = 798 bps).
OFFLINE_GATES = G1 Primary Gate FAIL (Val Top-1 35.91% < 45.00%, Val CE impr 798 bps < 1000 bps); Objective Signal Gate FAIL (Relative to Exp D2 baseline: Top-1 delta -2.51 pp < +3.0 pp, CE delta +0.0197 nats > +0.005 nats degradation ceiling).
FIT_ATTRIBUTION = Adding the weighted pairwise logistic ranking objective on top of canonical soft CE yielded strictly inferior results compared to the pure soft-CE D2 baseline: Val CE degraded by +0.0197 nats (2.8177 -> 2.8375) and Val Top-1 dropped by -2.51 pp (38.42% -> 35.91%). The model peaked early (best epoch 13) and showed continuous validation CE degradation in later epochs under this formulation.
DECISION = STOP_WEIGHTED_PAIRWISE_LOGISTIC_RANKING_ROUTE
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NO_FURTHER_MODEL_TRAINING
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

Across the M25 recovery and downstream probes:
1. **Experiment D2** proved that injecting 23-dim exact post-action state transition deltas into action embeddings yielded a major fit improvement (Val CE 2.8879 $\to$ 2.8177, Top-1 31.87% $\to$ 38.42%).
2. **Experiment B & E** ruled out model width scaling (0.95M $\to$ 2.61M parameters yielded $\le 0.0020\text{ nats}$ CE reduction).
3. **M29A-v1/v2** ruled out dynamic action-to-entity cross-attention pooling (gain $\le 0.0043\text{ nats}$).
4. **M30A** proved that 4-sample teacher search targets already have 76.56% repeat agreement (median JSD 0.0019 nats), and 4-to-16 sample scaling increased agreement by only +3.12 pp, ruling out teacher sampling variance as the dominant ceiling cause.

The remaining high-value hypothesis in **M31A** was:

> Standard cross-entropy over soft-floored probabilities penalizes probability discrepancies diffusely across all legal actions. By adding an auxiliary pairwise ranking loss $\mathcal{L}_{\text{rank}} = w \cdot \text{softplus}(-(\text{logit}_{\text{top1}} - \text{logit}_{\text{runner\_up}}))$ weighted by the teacher's normalized advantage margin $w = (M_{\text{top1}} - M_{\text{runner\_up}}) / 900000$, can the network sharpen its separation of the primary decision boundary and achieve the G1 gate (Top-1 $\ge 45.00\%$, CE $\ge 1000\text{ bps}$) without degrading probability calibration?

## Frozen experimental design

1. **Model Architecture**:
   - Fixed to exact D2 baseline: `DeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)`.
   - Input action dimension: 59 (36 baseline + 23 exact transition delta).
   - Parameters: 953,476.
2. **Dataset & Partition**:
   - Canonical M25 materialized dataset (`12,216` train / `4,066` val, `init_seed = 280229`, `shuffle_seed = 20260823`).
   - Single candidate with frozen $\lambda = 0.5$.
3. **Loss Formulation**:
   $$\mathcal{L}_{\text{total}} = \mathcal{L}_{\text{canonical\_CE}} + 0.5 \cdot \mathcal{L}_{\text{weighted\_pairwise\_logistic}}$$
   - **Pair construction rules per sample**:
     1. Only create a pair if teacher top-1 is unique. If top-1 is tied, $w = 0$ (excluded from ranking).
     2. Positive action is unique teacher top-1.
     3. Negative action is runner-up (highest non-top1 target micros, first-max tie breaking).
     4. Weight: $w = (M_{\text{top1}} - M_{\text{runner\_up}}) / 900000.0$.
     5. Pair loss: $w \cdot \text{softplus}(-(\text{logit}_{\text{top1}} - \text{logit}_{\text{runner\_up}}))$.
   - **Batch Normalization**:
     $$\mathcal{L}_{\text{rank}} = \frac{\sum_{i \in \text{valid}} w_i \cdot \text{softplus}(-(\text{logit}_{i, \text{top1}} - \text{logit}_{i, \text{runner\_up}}))}{\sum_{i \in \text{valid}} w_i}$$
     If all weights in batch are 0, $\mathcal{L}_{\text{rank}} = 0.0$.
4. **Validation & Checkpoint Selection**:
   - Checkpoints are strictly selected by **validation canonical policy CE** (`val_res["ce"]`), ensuring direct comparability against Exp D2.

## Acceptance and decision gates

1. **G1 Primary Gate**:
   - Validation Top-1 $\ge 45.00\%$ AND Validation CE improvement $\ge 1000\text{ bps}$.
   - If PASS $\to$ Authorize G2 transfer only (no direct Arena authorization).
2. **Objective Signal Gate**:
   - Relative to Exp D2 baseline (Val CE 2.8177, Top-1 38.42%):
     - $\Delta\text{Top-1} \ge +3.0\text{ pp}$ (Top-1 $\ge 41.42\%$) AND $\Delta\text{CE} \le +0.005\text{ nats}$ (Val CE $\le 2.8227$).
   - If PASS $\to$ Record as confirmed ranking signal for further objective refinement.
3. **Negative Result Rule**:
   - If both gates fail $\to$ `STOP_WEIGHTED_PAIRWISE_LOGISTIC_RANKING_ROUTE`. Strictly bounded to this ranking formulation without overgeneralizing to all objective-v2 approaches.

## Contracts and invariants (Unit Tested)

- **Hand-Calculated Match**: `test_hand_calculated_pairwise_ranking_loss` verifies exact numerical output against manual formula.
- **Top-1 Tie Exclusion**: `test_top1_tie_strictly_excluded` verifies tied positions contribute 0 to ranking loss.
- **Packed vs Per-Sample Equivalence**: `test_packed_vectorized_vs_per_sample_equivalence` verifies bit-accurate loss and parameter gradient equivalence.
- **$\lambda = 0$ Equivalence**: `test_lambda_zero_matches_canonical_d2` verifies $\lambda=0$ matches pure D2 soft-CE path.
- **Real Provenance Preflight**: `test_real_provenance_preflight_enforcement` validates full 64-char semantic hashes and fail-closed directory protection.
- **Vectorized Evaluation**: `test_vectorized_evaluation_first_max_matches_reference` verifies segmented GPU Top-1 matches reference Python loop.

## Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Benchmark Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Dataset Reference | `local-artifacts/m25-generation/m25-materialized-dataset.json` | `2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907` |
| Dataset Semantic Hash | Exact semantic identity across 16,282 examples | `1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419` |
| Catalog Semantic Hash | Exact card & noble entity catalog hash | `4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26` |
| Baseline D2 Result | `benchmarks/m25-recovery-exp-d2.result.json` | `403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38` |
| Probe Result Document | `benchmarks/m31a-ranking-objective.result.json` | Fully verified experiment results and metrics |
| Checkpoint Artifact | `local-artifacts/m31a-ranking-objective/checkpoint.pt` | `1225ec99c0a09b875a3ef8f9724ebbc271d7f224ceadcd79a9af49aca6ea13f5` |
| Runner Script | `training/m17_gpu/splendor_gpu/m31a_train.py` | `08fe05851d9d48160a1dd27d8cd0cc239d3882a0a0de5790df5c72cee3d1d342` |
| Ranking Loss Implementation | `training/m17_gpu/splendor_gpu/m31a_loss.py` | `085e06e994e33fbae347286ad0f4c10337e0a960b0297e1157224ab5f5893134` |
| Vectorized Evaluation | `training/m17_gpu/splendor_gpu/m31a_eval.py` | `f9fea09dc171c4ecb7d15ae9764b019e7ec16bf4ec427d3a2b704147f670906a` |
| Preflight Guard | `training/m17_gpu/splendor_gpu/m31a_preflight.py` | Strict fail-closed input identity assertion |
| Unit Tests | `training/m17_gpu/tests/test_m31a_ranking_loss.py` | 6 targeted unit tests (all passed) |

## Validation and evidence

### M31A vs D2 Baseline Performance Comparison

| Metric | Exp D2 Baseline (Pure Soft-CE) | M31A (Soft-CE + 0.5 * Ranking) | Delta (M31A vs D2) | Gate Target | Gate Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Best Epoch** | 11 | 13 | +2 | — | — |
| **Validation Policy CE (nats)** | **2.8177** | 2.8375 | **+0.0197 nats** | $\le +0.0050\text{ nats}$ | **FAIL** (Degraded) |
| **Validation Excess CE (nats)** | **+0.3449** | +0.3646 | +0.0197 nats | — | (Degraded) |
| **Validation Top-1 Agreement** | **38.42%** | 35.91% | **-2.51 pp** | $\ge +3.00\text{ pp}$ | **FAIL** (Degraded) |
| **Uniform CE Improvement (bps)** | 862 bps | 798 bps | -64 bps | $\ge 1000\text{ bps}$ | **FAIL** |
| **Training Policy CE (nats)** | 2.7839 | 2.7962 | +0.0123 nats | — | — |
| **Training Top-1 Agreement** | 39.52% | 38.52% | -1.00 pp | — | — |

## Result and decision

1. **Gate Evaluation**:
   - **G1 Primary Gate**: Validation Top-1 was **35.91%** (threshold $\ge 45.00\%$) and CE improvement was **798 bps** (threshold $\ge 1000\text{ bps}$), **FAIL**.
   - **Objective Signal Gate**: Validation Top-1 dropped by **-2.51 pp** vs D2 (threshold $\ge +3.0\text{ pp}$) and Validation CE degraded by **+0.0197 nats** (ceiling $\le +0.005\text{ nats}$), **FAIL**.
2. **Scientific Conclusion & Bounded Finding**:
   - In this controlled experiment, adding the weighted pairwise logistic ranking objective proved significantly inferior to the pure soft-CE D2 baseline across all validation and training fit metrics (Val CE +0.0197 nats, Val Top-1 -2.51 pp).
   - Training peaked early (epoch 13) and exhibited continuous validation CE degradation throughout later epochs (drifting to 3.0258 at epoch 128).
   - This negative finding is strictly bounded: it specifically rules out the **weighted pairwise logistic ranking** formulation on top of soft-CE, without disproving other potential multi-objective or policy restructuring approaches.
3. **Formal Decision**:
   - **`STOP_WEIGHTED_PAIRWISE_LOGISTIC_RANKING_ROUTE`**: Do not proceed with further pairwise logistic ranking training.
   - **Model Training**: `NO_FURTHER_MODEL_TRAINING` (M31A closed).
   - **Arena Execution**: `NOT_AUTHORIZED`.
   - **Promotion**: `NONE`. M07 champion remains unchanged.
