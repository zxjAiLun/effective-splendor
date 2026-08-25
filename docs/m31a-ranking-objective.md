# M31A — Objective-v2: Weighted Pairwise Logistic Ranking Auxiliary Loss

```ini
MILESTONE = M31A
STATUS = PROPOSED / DESIGNED / UNIT_TESTED / PENDING_REVIEW
BASE_COMMIT = ba2c7acc831a29f5ddbeee0bcbb36440f13511eb
SCOPE = Evaluate composite policy loss objective L = L_canonical_CE + 0.5 * L_weighted_pairwise_logistic on top of canonical D2 architecture (h192/b4, 59-dim exact action deltas, 953,476 parameters, 128 epochs) to test whether explicit pairwise teacher ranking margin breaks the student fit ceiling without sacrificing soft-target cross-entropy calibration.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
TRAINING = PLANNED (128 epochs, lr=3e-4 cosine, wd=1e-4, checkpoint selected strictly by validation canonical policy CE).
OFFLINE_GATES = G1 Primary Gate (Val Top-1 >= 45.00%, Val CE improvement >= 1000 bps) -> Authorize G2 only; Objective Signal Gate (Relative to D2 baseline: Top-1 delta >= +3.0 pp and CE degradation <= +0.005 nats).
FIT_ATTRIBUTION = Tested as a remaining high-value hypothesis following the exclusion of width scaling (Exp B/E), dynamic action-entity attention (M29A-v1/v2), and 4-to-16 teacher sample scaling (M30A).
DECISION = PENDING_REVIEW
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NOT_STARTED_PENDING_REVIEW
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

Across the M25 recovery and downstream probes:
1. **Experiment D2** proved that injecting 23-dim exact post-action state transition deltas into action embeddings yielded a major fit improvement (Val CE 2.8879 $\to$ 2.8177, Top-1 31.87% $\to$ 38.42%).
2. **Experiment B & E** ruled out model width scaling (0.95M $\to$ 2.61M parameters yielded $\le 0.0020\text{ nats}$ CE reduction).
3. **M29A-v1/v2** ruled out dynamic action-to-entity cross-attention pooling (gain $\le 0.0043\text{ nats}$).
4. **M30A** proved that 4-sample teacher search targets already have 76.56% repeat agreement (median JSD 0.0019 nats), and 4-to-16 sample scaling increased agreement by only +3.12 pp, ruling out teacher sampling variance as the dominant ceiling cause.

The remaining high-value hypothesis in **M31A** is:

> Standard cross-entropy over soft-floored probabilities penalizes probability discrepancies diffusely across all legal actions. By adding an auxiliary pairwise ranking loss $\mathcal{L}_{\text{rank}} = w \cdot \text{softplus}(-(\text{logit}_{\text{top1}} - \text{logit}_{\text{runner\_up}}))$ weighted by the teacher's normalized advantage margin $w = (M_{\text{top1}} - M_{\text{runner\_up}}) / 900000$, can the network sharpen its separation of the primary decision boundary and achieve the G1 gate (Top-1 $\ge 45.00\%$, CE $\ge 1000\text{ bps}$) without degrading probability calibration?

## Frozen experimental design

1. **Model Architecture**:
   - Fixed to exact D2 baseline: `DeltaEntityMixer(hidden_dim=192, blocks=4, dropout=0.0)`.
   - Input action dimension: 59 (36 baseline + 23 exact transition delta).
   - Parameters: 953,476.
2. **Dataset & Partition**:
   - Canonical M25 materialized dataset (`12,216` train / `4,066` val, `init_seed = 280229`, `shuffle_seed = 20260823`).
   - No sweep over $\lambda$; single candidate with frozen $\lambda = 0.5$.
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
- **Packed vs Per-Sample Equivalence**: `test_packed_vs_per_sample_equivalence` verifies bit-accurate loss and parameter gradient equivalence.
- **$\lambda = 0$ Equivalence**: `test_lambda_zero_matches_canonical_d2` verifies $\lambda=0$ matches pure D2 soft-CE path.
- **Fail-Closed Output Directory**: `test_fail_closed_output_directory` and runtime checks assert `local-artifacts/m31a-ranking-objective/` does not exist prior to training.
- **No Model Training Before Review**: Training script implemented and tested, but training execution paused pending review.

## Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Benchmark Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Dataset Reference | `local-artifacts/m25-generation/m25-materialized-dataset.json` | `2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907` |
| Ranking Loss Implementation | `training/m17_gpu/splendor_gpu/m31a_loss.py` | Canonical CE + Weighted Logistic Ranking |
| Training Script | `training/m17_gpu/splendor_gpu/m31a_train.py` | M31A GPU Training Runner |
| Unit Tests | `training/m17_gpu/tests/test_m31a_ranking_loss.py` | 5 targeted unit tests (all passed) |
| Milestone Document | `docs/m31a-ranking-objective.md` | M31A Design & Review Contract |
