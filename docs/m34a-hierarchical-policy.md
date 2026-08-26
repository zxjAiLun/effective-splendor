# M34A — Hierarchical Take-Pattern Policy v1

```ini
MILESTONE = M34A
STATUS = PROPOSED / DESIGNED / UNIT_TESTED / PENDING_REVIEW
BASE_COMMIT = 0b632f7154473247bbfafe2fbbf39a39fa852936
SCOPE = Evaluate whether an explicit hierarchical conditional probability decomposition over legal actions (P(family|s) * P(take_pattern|take,s) * P(return|pattern,s)) with D2 condition scorer for non-take actions breaks the token acquisition bottleneck on the canonical M25 dataset.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
ARCHITECTURE = HierarchicalDeltaEntityMixer (192 hidden, 4 blocks, 59-dim exact action deltas, 119,081 hierarchical head parameters, total 1,072,557 parameters).
TRAINING = PLANNED (128 epochs, lr=3e-4 cosine, wd=1e-4, checkpoint selected strictly by validation canonical policy CE).
OFFLINE_GATES = G1 Primary Gate (Val Top-1 >= 45.00%, Val CE improvement >= 1000 bps) -> Authorize G2 only; Hierarchical Signal Gate (Global: Val CE <= 2.7977 nats, Val Top-1 >= 40.42%; Targeted: Take family recall >= 39.1101%, Take exact Top-1 >= 8.3183%, Take pattern exact Top-1 >= 8.3183% [+5.0 pp vs D2 baseline 3.3183%], Reserve exact Top-1 >= 12.22% [stability floor vs 14.22%], Buy exact Top-1 >= 74.15% [max -2 pp drop vs 76.15%]).
FIT_ATTRIBUTION = Tests the Hierarchical Action Decomposition Hypothesis: whether restructuring the action probability space into explicit Family -> Semantic Take Pattern -> Return Gem Choices eliminates the combinatorial credit dilution that prevented flat Softmax and additive factorizations (M33A) from learning token acquisition policies.
DECISION = PENDING_REVIEW
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NOT_STARTED_PENDING_REVIEW
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

M33A experimental results confirmed that additive structured residual logit factorization ($L_{\text{final}} = L_{\text{D2}} + L_{\text{factor}}$) failed to repair the token acquisition bottleneck (Take exact Top-1 remained frozen at 3.17% vs D2 3.32%).

**D2-v2 Baseline Frozen Diagnostics (Validation Set, 4,066 samples, 1,326 Take target samples, Checkpoint SHA `113372fc10...`)**:
- **Overall Top-1**: 38.4161% (1,562 / 4,066)
- **Take Family Recall**: 29.1101% (386 / 1,326)
- **Take Exact Full-Action Top-1**: 3.3183% (44 / 1,326)
- **Take Pattern Exact Top-1 (30-class semantic combination)**: **3.3183%** (44 / 1,326)
- **Take Conditional Return Choice Match (given correct pattern)**: N/A (0 / 0 return cases)
- **Buy Exact Top-1**: 76.15%
- **Reserve Exact Top-1**: 14.22%

**Core Structural Cause**:
In a typical state, there are 10–30 legal Take actions, each sharing overlapping color selections. Under flat single-stage Softmax cross-entropy, credit assignment for a specific target action (e.g., Take W/U/G) across all available permutations is diluted: boosting one combination's logit simultaneously boosts all other legal combinations containing white, blue, or green. When returns are involved, each take combination is further multiplied by possible gem returns, completely diluting credit assignment.

## True Hierarchical Probability Formulation

M34A restructures action probabilities hierarchically:

$$\begin{aligned}
P(a \mid s) &= P(\text{family} \mid s) \cdot P(\text{take\_pattern} \mid \text{take}, s) \cdot P(\text{return} \mid \text{pattern}, s) && \text{for } a \in \text{Take} \\
P(a \mid s) &= P(\text{family} \mid s) \cdot P(a \mid \text{family}, s) && \text{for } a \in \{ \text{Buy, Reserve, Noble, Pass} \}
\end{aligned}$$

Where:
1. **Base Action Potentials**: $z(a) = \text{D2\_Policy}(s, a)$ computed for all server-certified legal actions.
2. **Base Masses**:
   - $B_f = \text{logsumexp}_{a \in f} z(a)$
   - $B_p = \text{logsumexp}_{a \in p} z(a)$ (for $a \in \text{Take}$)
3. **Structured Residuals**:
   - Family logits: $B_f + \text{family\_head}(s)[f]$
   - Take pattern logits: $(B_p - B_{\text{take}}) + \text{take\_pattern\_head}(s)[p]$
   - Return / action logits: $(z(a) - B_p) - \sum_{k=0}^5 \text{return}[k] \cdot \text{return\_penalty\_head}(s)[k]$
   - Non-take action logits within family: $z(a) - B_f$
4. **Normalized Conditional Log-Probabilities**:
   - $\log P(\text{family} \mid s) = \text{log\_softmax}_{f \in \text{active}}(B_f + r_f)$
   - $\log P(\text{pattern} \mid \text{take}, s) = \text{log\_softmax}_{p \in \text{active}}(B_p - B_{\text{take}} + r_p)$
   - $\log P(a \mid \text{pattern}, s) = \text{log\_softmax}_{a \in p}(z(a) - B_p + r_{\text{return}})$
   - Total $\log P(a \mid s)$ is composed via fully vectorized CUDA scatter-reduce operations and guarantees $\sum_a P(a \mid s) \equiv 1.0$ identically for every sample.
5. **Exact Target Conservation & Loss Function**:
   - Canonical soft-CE is computed directly on reconstructed $\log P(a \mid s)$:
     $$\mathcal{L} = -\frac{1}{B} \sum_{b=1}^B \sum_{a \in \mathcal{A}_{\text{legal}}(s_b)} q(a) \log P(a \mid s_b)$$
   - At zero initialization of hierarchical heads, $\log P(a \mid s) \equiv \text{log\_softmax}(z(a))$ bit-for-bit, exactly matching D2 loss and probabilities.

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
   - Initial $\log P(a \mid s)$ matches D2 $\text{log\_softmax}(z(a))$ within floating-point tolerance (`1e-5`).
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
     - Take family recall $\ge 39.1101\%$ (+10.0 pp vs D2 29.1101%)
     - Take exact Top-1 $\ge 8.3183\%$ (+5.0 pp vs D2 3.3183%)
     - **Take pattern exact Top-1 $\ge 8.3183\%$ (+5.0 pp vs D2 baseline 3.3183%)**
     - Reserve exact Top-1 $\ge 12.22\%$ (stability floor vs D2 14.22%)
     - Buy exact Top-1 $\ge 74.15\%$ (maximum 2.0 pp drop vs D2 76.15%)
   - If PASS $\to$ Record confirmed hierarchical policy signal.
3. **Negative Result Rule**:
   - If gates fail $\to$ `STOP_HIERARCHICAL_TAKE_PATTERN_POLICY_ROUTE`.

## Contracts and invariants (Unit Tested)

- **Parameter Count Match**: `test_model_parameter_count` asserts parameter count equals exactly 1,072,557.
- **Probability Sum & D2 Equivalence**: `test_initialization_equivalence_to_d2_and_probability_sum_one` asserts initial $\log P(a \mid s)$ matches D2 within `1e-5` and $\sum_a P(a \mid s) \equiv 1.0$ identically.
- **Two-Stage Gradient Flow**: `test_two_stage_hierarchical_gradient_flow` verifies output projections receive non-zero gradients on step 1, and upstream layers receive non-zero gradients on step 2 under `hierarchical_policy_loss`.
- **Hand-Calculated Ground Truth**: `test_non_zero_residual_hand_calculated_ground_truth` verifies exact step-by-step intermediate and final conditional log-probabilities against manual analytical formulas for non-zero residuals.
- **Diagnostic Evaluator Reference Parity & Fail-Closed**: `test_diagnostic_evaluator_multi_batch_and_first_max_reference` validates exact hand-calculated metric parity between Python diagnostics and GPU vectorized evaluator, and tests fail-closed exception on dataset mismatch.
- **Real Provenance Preflight**: `test_real_provenance_preflight_for_m34a` validates 64-char dataset/catalog semantic hashes, config SHA, D2 baseline SHA, D2-v2 checkpoint SHA (`113372fc10...`), checkpoint internal metadata, and counter-example rejection of old invalid D2 checkpoint.
