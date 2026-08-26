# M33A — End-to-End Factorized Legal-Action Policy v1

```ini
MILESTONE = M33A
STATUS = ACCEPTED / CLOSED (NEGATIVE RESULT)
BASE_COMMIT = 0b632f7154473247bbfafe2fbbf39a39fa852936
SCOPE = Evaluate whether decomposing the flat legal-action Softmax logit into an end-to-end factorized sum of semantic components (Action Family Intent + Take Mode + 5-Color Desirability + 6-Color Return Penalty + State-Conditioned Entity Scorer + Deck Tier Scorer + Zero-Initialized D2 Residual Scorer) repairs the severe action-structure bottleneck (Take Top-1 3.32%, Reserve Top-1 14.22%) and achieves offline gates on canonical M25 dataset.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
ARCHITECTURE = FactorizedDeltaEntityMixer (192 hidden, 4 blocks, 59-dim exact action deltas, 301,082 structured factor parameters, total 1,254,558 parameters).
TRAINING = COMPLETED (128 epochs, best epoch 11, lr=3e-4 cosine, wd=1e-4, checkpoint selected strictly by validation canonical policy CE).
OFFLINE_GATES = G1 Primary Gate (Val Top-1 >= 45.00%, Val CE improvement >= 1000 bps) -> FAIL (Val Top-1 = 38.86%, Impr = 890 bps); Factorization Signal Gate -> FAIL (Global: Val CE = 2.8093 vs 2.8177 [-0.0084 nats, target <= -0.0200], Val Top-1 = 38.86% vs 38.42% [+0.44 pp, target >= +2.00 pp]; Targeted: Take family recall = 32.73% [target >= 39.11%], Take exact Top-1 = 3.17% [target >= 8.32%], Reserve exact Top-1 = 17.51% [PASS, target >= 17.22%], Buy exact Top-1 = 75.49% [PASS, target >= 74.15%]).
FIT_ATTRIBUTION = Evaluated whether additive structured residual logit factorization over a single-stage legal-action Softmax could resolve the token acquisition bottleneck. While Reserve exact Top-1 improved (+3.29 pp to 17.51%) and family Top-1 rose (+1.57 pp to 69.60%), Take Tokens exact Top-1 remained unchanged at 3.17% (vs D2 3.32%). This specific additive recipe under canonical soft-CE did not improve Take accuracy, motivating the investigation of explicit hierarchical conditional probability decomposition.
DECISION = STOP_FACTORIZED_LEGAL_ACTION_POLICY_ROUTE
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = COMPLETED
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

Diagnostic decomposition of the D2 validation set performance (4,066 samples, overall Top-1 **38.42%**) revealed a profound structural disparity across action types:

| Teacher Correct Action Family | Validation Samples | D2 Family Recall | D2 Exact Full-Action Top-1 |
| :--- | :---: | :---: | :---: |
| **Buy Card (Market + Reserved)** | 1,820 | **95.93%** | **76.15%** |
| **Reserve Card (Market + Deck)** | 914 | **68.71%** | **14.22%** |
| **Take Tokens (All Modes & Returns)** | 1,326 | **29.11%** | **3.32%** |
| **Choose Noble** | 6 | 100.0% | 33.33% |

**Key Insight**:
1. D2's 38.42% accuracy is dominated by card purchasing (**76.15% exact Top-1**).
2. The network fails at token planning (**3.32% exact Top-1**, Take recall only 29.11%) and selecting strategic reserve targets (**14.22% exact Top-1**).
3. The flat Softmax scorer over combinatorial action vectors (often 30 to 575 legal actions per state) forces the model to memorize full combinations.

**M33A Hypothesis**:
Additive semantic decomposition of legal-action logits into explicit action family intent, take modes, 5-color desirability, 6-color return keep penalty, state-conditioned entity value, and deck tier value—trained completely end-to-end under canonical soft CE with zero-initialized D2 residual—can repair the token acquisition bottleneck and break the 38.4% policy ceiling.

## Final Experimental Results

M33A was trained for 128 epochs under the exact frozen M25 protocol (`init_seed = 280229`, `shuffle_seed = 20260823`). Best validation CE checkpoint was achieved at **Epoch 11** (`val_ce = 2.8093`).

### Comparative Diagnostic Table: D2 Baseline vs M33A Factorized

| Metric / Dimension | Exp D2 Baseline | M33A Factorized Policy | Delta (M33A vs D2) | M33A Signal Target | Gate Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Best Epoch** | 11 | **11** | 0 | - | - |
| **Validation Policy CE** | 2.8177 | **2.8093** | **-0.0084 nats** | $\le -0.0200\text{ nats}$ | FAIL |
| **Validation Excess CE** | +0.3449 | **+0.3365** | **-0.0084 nats** | - | - |
| **Validation CE Impr** | 862 bps | **890 bps** | **+28 bps** | $\ge 1000\text{ bps}$ | FAIL |
| **Full Legal-Action Top-1** | 38.42% | **38.86%** | **+0.44 pp** | $\ge 40.42\%$ (+2.00 pp) | FAIL |
| **Family Top-1 Agreement** | 68.03% | **69.60%** | **+1.57 pp** | - | - |
| **Take Family Recall** | 29.11% | **32.73%** | **+3.62 pp** | $\ge 39.11\%$ (+10.0 pp) | FAIL |
| **Take Exact Top-1** | 3.32% | **3.17%** | **-0.15 pp** | $\ge 8.32\%$ (+5.0 pp) | FAIL |
| **Take Color Exact Match** | - | **3.32%** | - | - | - |
| **Take Color Jaccard** | - | **0.1371** | - | - | - |
| **Buy Family Recall** | 95.93% | **95.49%** | -0.44 pp | - | - |
| **Buy Exact Top-1** | 76.15% | **75.49%** | -0.66 pp | $\ge 74.15\%$ (max -2.0 pp) | **PASS** |
| **Reserve Family Recall** | 68.71% | **71.33%** | **+2.62 pp** | - | - |
| **Reserve Exact Top-1** | 14.22% | **17.51%** | **+3.29 pp** | $\ge 17.22\%$ (+3.0 pp) | **PASS** |
| **Return Choice Accuracy** | - | **8.33%** (4/48) | - | - | - |

## Scientific Analysis & Attribution

1. **What Succeeded**:
   - **Reserve Accuracy Improved**: State-conditioned entity and deck-tier scoring improved Reserve exact Top-1 from **14.22% to 17.51%** (+3.29 pp, passing the targeted reserve gate) and Reserve recall from **68.71% to 71.33%**.
   - **Buy Accuracy Maintained**: Card purchasing remained strong at **75.49%** (well above the 74.15% floor).
   - **Overall Alignment Slightly Better**: Family Top-1 rose to **69.60%** (+1.57 pp), achieving a modest CE improvement of 28 bps (-0.0084 nats).

2. **Why Token Acquisition Failed to Break Through (Root Cause Analysis)**:
   - **Combinatorial Dilution**: In a typical state, there are 10–30 legal Take actions, each sharing overlapping color selections. Under flat Softmax cross-entropy, credit assignment for a specific target action (e.g., Take W/U/G) across all available permutations is diluted: boosting $d_{\text{take}}[\text{white}]$ simultaneously boosts all other legal combinations containing white.
   - **Return Penalty Suppression**: With only 48 return positions in the entire validation set (1.18%), the model cannot learn keep penalties purely from soft CE over the full action list.
   - **Conclusion**: Naive additive logit decomposition alone cannot resolve the combinatorial token search problem under standard single-stage policy Softmax.

## Acceptance and Decision Verdict

- **G1 Primary Gate**: FAIL (Val Top-1 38.86% < 45.00%, Val CE improvement 890 bps < 1000 bps).
- **Factorization Signal Gate**: FAIL (Global CE delta -0.0084 nats > -0.0200 nats, Top-1 delta +0.44 pp < +2.00 pp; Take exact Top-1 3.17% < 8.32%).
- **Decision**: `STOP_FACTORIZED_LEGAL_ACTION_POLICY_ROUTE`.
- **Arena Evaluation**: Strictly NOT AUTHORIZED.

## Artifact Hashes and Provenance

| Artifact | Path | SHA-256 |
| --- | --- | --- |
| Benchmark Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Dataset Semantic Hash | Canonical M25 Dataset (16,282 examples) | `1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419` |
| Catalog Semantic Hash | Entity Catalog | `4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26` |
| Baseline D2 Result | `benchmarks/m25-recovery-exp-d2.result.json` | `403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38` |
| M33A Result Payload | `benchmarks/m33a-factorized-policy.result.json` | Generated |
| M33A Model Checkpoint | `local-artifacts/m33a-factorized-policy/checkpoint.pt` | Generated |
