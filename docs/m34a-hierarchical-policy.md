# M34A — Hierarchical Take-Pattern Policy v1

```ini
MILESTONE = M34A
STATUS = PROPOSED / DESIGNED / UNIT_TESTED / PENDING_REVIEW
BASE_COMMIT = 0b632f7154473247bbfafe2fbbf39a39fa852936
SCOPE = Evaluate whether an explicit hierarchical conditional probability decomposition over legal actions (P(family|s) * P(take_pattern|take,s) * P(return|pattern,s)) with D2 condition scorer for non-take actions breaks the token acquisition bottleneck (D2 Take Exact Top-1 3.32%, Pattern Exact Top-1 3.92%) on the canonical M25 dataset.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
ARCHITECTURE = HierarchicalDeltaEntityMixer (192 hidden, 4 blocks, 59-dim exact action deltas, 119,081 hierarchical head parameters, total 1,072,557 parameters).
TRAINING = PLANNED (128 epochs, lr=3e-4 cosine, wd=1e-4, checkpoint selected strictly by validation canonical policy CE).
OFFLINE_GATES = G1 Primary Gate (Val Top-1 >= 45.00%, Val CE improvement >= 1000 bps) -> Authorize G2 only; Hierarchical Signal Gate (Global: Val CE <= 2.7977 nats, Val Top-1 >= 40.42%; Targeted: Take family recall >= 39.11%, Take exact Top-1 >= 8.32%, Take pattern exact Top-1 >= 8.92% [+5 pp vs D2 3.92%], Reserve exact Top-1 >= 17.22%, Buy exact Top-1 >= 74.15%).
FIT_ATTRIBUTION = Tests the Hierarchical Action Decomposition Hypothesis: whether restructuring the action probability space into explicit Family -> Semantic Take Pattern -> Return Gem Choices eliminates the combinatorial credit dilution that prevented flat Softmax and additive factorizations (M33A) from learning token acquisition policies.
DECISION = PENDING_REVIEW
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NOT_STARTED_PENDING_REVIEW
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

M33A experimental results confirmed that additive structured residual logit factorization ($L_{\text{final}} = L_{\text{D2}} + L_{\text{factor}}$) failed to repair the token acquisition bottleneck (Take exact Top-1 remained frozen at 3.17% vs D2 3.32%).

**D2 Baseline Diagnostic Breakdown (Validation Set, 4,066 samples, 1,326 Take target samples)**:
- **Take Family Recall**: 29.11% (or 39.06% on argmax tie variations)
- **Take Exact Full-Action Top-1**: 3.32% (50/1326 = 3.77%)
- **Take Pattern Exact Top-1 (30-class semantic combination)**: **3.92%** (52/1326)
- **Take Conditional Return Choice Match (given correct pattern)**: 50.00% (2/4 return cases)
- **Buy Exact Top-1**: 76.15%
- **Reserve Exact Top-1**: 14.22%

**Core Structural Cause**:
In a typical state, there are 10–30 legal Take actions, each sharing overlapping color selections. Under flat single-stage Softmax cross-entropy, a gradient update for a specific target action (e.g., Take W/U/G) across all available permutations simultaneously raises the logits of all other legal combinations containing white, blue, or green. When returns are involved, each take combination is further multiplied by possible gem returns, completely diluting credit assignment.

## Hierarchical Probability Formulation

M34A restructures action probabilities hierarchically:

$$\begin{aligned}
P(a \mid s) &= P(\text{family} \mid s) \cdot P(\text{take\_pattern} \mid \text{take}, s) \cdot P(\text{return} \mid \text{pattern}, s) && \text{for } a \in \text{Take} \\
P(a \mid s) &= P(\text{family} \mid s) \cdot P(a \mid \text{family}, s) && \text{for } a \in \{ \text{Buy, Reserve, Noble, Pass} \}
\end{aligned}$$

Where:
1. **Action Family**: 5 classes (Take, Buy, Reserve, Noble, Pass) scored via $L_{\text{family}}(s) \in \mathbb{R}^5$.
2. **Take Pattern**: 30 canonical semantic combinations (10 3-distinct, 5 2-same, 10 2-distinct, 5 1-distinct) scored via $L_{\text{pattern}}(s) \in \mathbb{R}^{30}$.
3. **Return Penalties**: 6 gem weights (W, U, G, R, K, Gold) scored via $w_{\text{return}}(s) \in \mathbb{R}^6$, yielding logit penalty $-\sum_{k=0}^5 \text{return}[k] \cdot w_{\text{return}, k}(s)$.
4. **Non-Take Conditional Scorers**: Buy, Reserve, Noble, and Pass actions are scored by the established D2 backbone policy scorer conditioned on action embeddings, avoiding confounding shifts across other action families.
5. **Exact Target Conservation & Canonical Soft-CE**:
   - The teacher's soft targets $q(a)$ are marginalized without synthetic labels:
     $$q(\text{family}) = \sum_{a \in \text{family}} q(a)$$
     $$q(\text{pattern} \mid \text{take}) = \frac{\sum_{a \in \text{pattern}} q(a)}{q(\text{take})}$$
     $$q(\text{return} \mid \text{pattern}) = \frac{q(a)}{\sum_{a' \in \text{pattern}} q(a')}$$
   - The training loss is the canonical soft cross-entropy over reconstructed legal-action probabilities.

## Frozen experimental design

1. **Architecture & Parameter Count**:
   - `HierarchicalDeltaEntityMixer` (192 hidden, 4 blocks, 59-dim action deltas).
   - D2 Backbone: 953,476 parameters.
   - Hierarchical Heads:
     - `family_head`: 38,021 parameters.
     - `take_pattern_head`: 42,846 parameters.
     - `return_penalty_head`: 38,214 parameters.
   - Total parameters: **1,072,557** (asserted by unit tests and preflight).
2. **Zero-Initialization Invariant**:
   - D2 backbone and D2 policy heads constructed first under seed `280229`.
   - All final output projection layers in the hierarchical heads are strictly initialized to **ZERO**.
   - Initial logits match D2 bit-for-bit (`atol=0, rtol=0`).
3. **Training Hyperparameters**:
   - Dataset: Canonical M25 (12,216 train / 4,066 val, `init_seed = 280229`, `shuffle_seed = 20260823`).
   - Optimizer: AdamW lr=3e-4, wd=1e-4, 128 epochs cosine schedule.
   - Checkpoint selection strictly by **validation canonical policy CE** (`val_res["ce"]`).

## Acceptance and decision gates

1. **G1 Primary Gate**:
   - Validation Top-1 $\ge 45.00\%$ AND Validation CE improvement $\ge 1000\text{ bps}$.
   - If PASS $\to$ Authorize G2 transfer only (no Arena).
2. **Hierarchical Signal Gate**:
   - **Global Signal**: $\Delta\text{CE} \le -0.0200\text{ nats}$ vs D2 (Val CE $\le 2.7977$) AND $\Delta\text{Top-1} \ge +2.00\text{ pp}$ vs D2 (Val Top-1 $\ge 40.42\%$).
   - **Targeted Signal**:
     - Take family recall $\ge 39.11\%$ (+10.0 pp vs D2 29.11%)
     - Take exact Top-1 $\ge 8.32\%$ (+5.0 pp vs D2 3.32%)
     - **Take pattern exact Top-1 $\ge 8.92\%$ (+5.0 pp vs D2 baseline 3.92%)**
     - Reserve exact Top-1 $\ge 17.22\%$ (+3.0 pp vs D2 14.22%)
     - Buy exact Top-1 $\ge 74.15\%$ (maximum 2.0 pp drop vs D2 76.15%)
   - If PASS $\to$ Record confirmed hierarchical policy signal.
3. **Negative Result Rule**:
   - If gates fail $\to$ `STOP_HIERARCHICAL_TAKE_PATTERN_POLICY_ROUTE`.

## Contracts and invariants (Unit Tested)

- **Parameter Count Match**: `test_model_parameter_count` asserts parameter count equals exactly 1,072,557.
- **Bit-for-Bit D2 Equivalence**: `test_initialization_equivalence_to_d2` asserts initial logits match D2 bit-for-bit (`atol=0, rtol=0`).
- **Two-Stage Gradient Flow**: `test_two_stage_hierarchical_gradient_flow` verifies output projections receive non-zero gradients on step 1, and upstream layers receive non-zero gradients on step 2.
- **Marginal Target Conservation**: `test_marginal_target_conservation_and_pattern_decomposition` verifies probability sum conservation, family marginalization, and conditional return probability arithmetic.
- **Diagnostic Evaluator Reference Parity & Fail-Closed**: `test_diagnostic_evaluator_multi_batch_and_first_max_reference` validates exact hand-calculated metric parity between Python diagnostics and GPU vectorized evaluator, and tests fail-closed exception on dataset mismatch.
- **Real Provenance Preflight**: `test_real_provenance_preflight_for_m34a` validates 64-char dataset/catalog semantic hashes, config SHA, D2 baseline SHA, and fail-closed output directory protection.
