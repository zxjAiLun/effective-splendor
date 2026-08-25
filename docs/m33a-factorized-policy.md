# M33A — End-to-End Factorized Legal-Action Policy v1

```ini
MILESTONE = M33A
STATUS = PROPOSED / DESIGNED / UNIT_TESTED / PENDING_REVIEW
BASE_COMMIT = d28006f0e340c498064aee9ec8fa9476aa0a01d6
SCOPE = Evaluate whether decomposing the flat legal-action Softmax logit into an end-to-end factorized sum of semantic components (Action Family Intent + Take Mode + 5-Color Desirability + 6-Color Return Penalty + State-Conditioned Entity Scorer + Deck Tier Scorer + Zero-Initialized D2 Residual Scorer) repairs the severe action-structure bottleneck (Take Top-1 3.32%, Reserve Top-1 14.22%) and achieves offline gates on canonical M25 dataset.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
ARCHITECTURE = FactorizedDeltaEntityMixer (192 hidden, 4 blocks, 59-dim exact action deltas, 301,082 structured factor parameters, total 1,254,558 parameters).
TRAINING = PLANNED (128 epochs, lr=3e-4 cosine, wd=1e-4, checkpoint selected strictly by validation canonical policy CE).
OFFLINE_GATES = G1 Primary Gate (Val Top-1 >= 45.00%, Val CE improvement >= 1000 bps) -> Authorize G2 only; Factorization Signal Gate (Global: Val CE <= 2.7977 nats, Val Top-1 >= 40.42%; Targeted: Take family recall >= 39.11%, Take exact Top-1 >= 8.32%, Reserve exact Top-1 >= 17.22%, Buy exact Top-1 >= 74.15%).
FIT_ATTRIBUTION = Tests the Action Factorization Hypothesis: whether the Student's 38.4% policy ceiling is caused by flat representation of a combinatorial 30-to-500 action space, and whether explicit semantic additive decomposition of color desires, return costs, and target cards enables effective learning of Take and Reserve policies without auxiliary labels.
DECISION = PENDING_REVIEW
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NOT_STARTED_PENDING_REVIEW
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
1. D2's 38.42% accuracy is **not** a uniform 40% capability across all actions.
2. The network excels at identifying and purchasing affordable target cards (**76.15% exact Top-1**).
3. The network catastrophically fails at planning token acquisitions (**3.32% exact Top-1**, Take recall only 29.11%) and selecting strategic reserve targets (**14.22% exact Top-1**).
4. The flat Softmax scorer over combinatorial action vectors (often 30 to 575 legal actions per state) forces the model to memorize full combinations rather than sharing color utilities across actions.

The core question tested in **M33A** is:

> Does additive semantic decomposition of legal-action logits into explicit action family intent, take modes, 5-color desirability, 6-color return keep penalty, state-conditioned entity value, and deck tier value—trained completely end-to-end under canonical soft CE with zero-initialized D2 residual—repair the token acquisition bottleneck and break the 38.4% policy ceiling?

## Frozen experimental design

1. **End-to-End Factorized Action Logit Composition**:
   For any state $s$ and server-certified legal action $a \in \mathcal{A}_{\text{legal}}(s)$:
   $$\text{FinalLogit}(s, a) = \text{D2Logit}(s, a) + \text{Score}_{\text{structured}}(s, a)$$
   where:
   $$\text{Score}_{\text{structured}}(s, a) = L_{\text{family}}(s, \text{family}(a)) + L_{\text{mode}}(s, \text{mode}(a)) + \sum_{c=0}^4 \text{selected}[c] \cdot d_{\text{take}, c}(s) - \sum_{k=0}^5 \text{returned}[k] \cdot d_{\text{keep}, k}(s) + V_{\text{entity}}(s, \text{slot}(a), \text{channel}(a)) + V_{\text{deck\_tier}}(s, \text{tier}(a))$$

2. **Full Legal Action Variety Coverage**:
   - **Take Tokens**:
     - Mode index 0..3 (1-distinct, 2-distinct, 3-distinct, 2-same);
     - 5-color desirability ($d_{\text{take}} \in \mathbb{R}^5$);
     - 6-color return penalty ($d_{\text{keep}} \in \mathbb{R}^6$, explicitly covering Gold tokens).
   - **Buy Card**:
     - Market card: mapped to entity slot $0..11$ ($\text{tier} \times 4 + \text{slot}$);
     - Own reserved card: mapped to entity slot $28..30$ ($28 + \text{slot}$).
   - **Reserve Card**:
     - Market card: mapped to entity slot $0..11$ (channel 1);
     - Deck reserve: mapped to deck tier $0..2$ ($L_{\text{reserve\_deck}} + V_{\text{deck\_tier}}$);
     - 6-color return penalty ($d_{\text{keep}} \in \mathbb{R}^6$).
   - **Choose Noble**:
     - Mapped to public noble entity slot $12..16$.
   - **Pass**:
     - Mapped to family intent index 4 ($L_{\text{pass}}$).

3. **State-Conditioned Target Entity Scoring**:
   - Instead of static card MLPs, card/noble values are computed by an interactive state-conditioned head:
     $$\mathbf{h}_{\text{inter}} = [\mathbf{s}, \mathbf{e}_i, \mathbf{s} \odot \mathbf{e}_i] \in \mathbb{R}^{3h} \to \text{Linear}(3h, h) \to \text{GELU} \to \text{Linear}(h, 3)$$
     producing 3 channels (buy value, reserve value, noble value) across all 31 entity slots simultaneously.

4. **Zero-Initialization Invariant**:
   - D2 backbone and D2 policy heads are constructed first, preserving exact seed RNG alignment.
   - All final output projection layers in the structured branch are strictly initialized to **ZERO**.
   - At step 0, $\text{FinalLogit}(s, a) \equiv \text{D2Logit}(s, a)$ bit-for-bit.

5. **Model Parameter Count**:
   - Total model parameters: **1,254,558** (D2 base 953,476 + structured factor heads 301,082).

6. **Training Configuration**:
   - Dataset: Canonical M25 (12,216 train / 4,066 val, `init_seed = 280229`, `shuffle_seed = 20260823`).
   - Optimizer: AdamW lr=3e-4, wd=1e-4, 128 epochs cosine schedule.
   - Loss: Canonical Soft-Target Cross-Entropy (10% floor, 1,000,000 micros).
   - Checkpoint selection strictly by **validation canonical policy CE** (`val_res["ce"]`).

## Acceptance and decision gates

1. **G1 Primary Gate**:
   - Validation Top-1 $\ge 45.00\%$ AND Validation CE improvement $\ge 1000\text{ bps}$.
   - If PASS $\to$ Authorize G2 transfer only (no direct Arena authorization).
2. **Factorization Signal Gate**:
   - **Global Signal**:
     - $\Delta\text{CE} \le -0.0200\text{ nats}$ vs D2 (Val CE $\le 2.7977$) AND $\Delta\text{Top-1} \ge +2.00\text{ pp}$ vs D2 (Val Top-1 $\ge 40.42\%$)
   - **Targeted Signal**:
     - Take family recall $\ge 39.11\%$ (+10.0 pp vs D2 29.11%)
     - Take exact Top-1 $\ge 8.32\%$ (+5.0 pp vs D2 3.32%)
     - Reserve exact Top-1 $\ge 17.22\%$ (+3.0 pp vs D2 14.22%)
     - Buy exact Top-1 $\ge 74.15\%$ (maximum 2.0 pp regression vs D2 76.15%)
   - If PASS $\to$ Record as confirmed factorization signal for architecture synthesis.
3. **Negative Result Rule**:
   - If gates fail $\to$ `STOP_FACTORIZED_LEGAL_ACTION_POLICY_ROUTE`.

## Contracts and invariants (Unit Tested)

- **Parameter Count Match**: `test_model_parameter_count` asserts parameter count equals exactly 1,254,558.
- **Bit-for-Bit D2 Equivalence**: `test_initialization_equivalence_to_d2` asserts initial logits of M33A match D2 bit-for-bit (max diff == 0.0).
- **Two-Stage Gradient Flow**: `test_two_stage_structured_gradient_flow` verifies output projections receive non-zero gradients on step 1, and upstream layers receive non-zero gradients on step 2.
- **Hand-Calculated Decomposition**: `test_hand_calculated_factor_arithmetic` verifies numerical arithmetic across Take, Buy, Reserve, Noble, Pass, and Gold return combinations.
- **Action Decomposition Rules**: `test_action_decomposition_rules` verifies exact mapping across all 31 entity slots, 4 take modes, and deck tiers.
- **Real Provenance Preflight**: `test_real_provenance_preflight_for_m33a` validates 64-char dataset/catalog semantic hashes, config SHA, D2 baseline SHA, and fail-closed directory protection.

## Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Benchmark Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Dataset Reference | `local-artifacts/m25-generation/m25-materialized-dataset.json` | `2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907` |
| Dataset Semantic Hash | Exact semantic identity across 16,282 examples | `1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419` |
| Catalog Semantic Hash | Exact card & noble entity catalog hash | `4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26` |
| Baseline D2 Result | `benchmarks/m25-recovery-exp-d2.result.json` | `403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38` |
| Factorized Model | `training/m17_gpu/splendor_gpu/m33a_model.py` | Zero-initialized FactorizedDeltaEntityMixer |
| Action Decomposer | `training/m17_gpu/splendor_gpu/m33a_encoding.py` | Strict semantic legal-action decomposition |
| Diagnostic Evaluator | `training/m17_gpu/splendor_gpu/m33a_eval.py` | Granular Take / Buy / Reserve accuracy analyzer |
| Preflight Guard | `training/m17_gpu/splendor_gpu/m33a_preflight.py` | Strict fail-closed input identity assertion |
| Training Script | `training/m17_gpu/splendor_gpu/m33a_train.py` | M33A GPU Training Runner (128 epochs) |
| Unit Tests | `training/m17_gpu/tests/test_m33a_factorized_policy.py` | 6 targeted unit tests (all passed) |
| Milestone Document | `docs/m33a-factorized-policy.md` | M33A Design & Contract Document |
