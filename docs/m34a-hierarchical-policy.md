# M34A — Hierarchical Take-Pattern Policy v1

```ini
MILESTONE = M34A
STATUS = COMPLETED_NEGATIVE / GATES_FAILED / REJECTED_OFFLINE
BASE_COMMIT = 0b632f7154473247bbfafe2fbbf39a39fa852936
SCOPE = Evaluate whether an explicit hierarchical conditional probability decomposition over legal actions (P(family|s) * P(take_pattern|take,s) * P(return|pattern,s)) with D2 condition scorer for non-take actions breaks the token acquisition bottleneck on the canonical M25 dataset.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
ARCHITECTURE = HierarchicalDeltaEntityMixer (192 hidden, 4 blocks, 59-dim exact action deltas, 119,081 hierarchical head parameters, total 1,072,557 parameters).
TRAINING = COMPLETED (128 epochs, lr=3e-4 cosine, wd=1e-4, best epoch 11, val CE 2.8160 nats, val Top-1 37.14%).
OFFLINE_GATES = G1 Primary Gate (Val Top-1 >= 45.00%, Val CE improvement >= 1000 bps) -> FAIL (Top-1 37.14%, Impr 868 bps); Hierarchical Signal Gate (Global: Val CE <= 2.7977 nats, Val Top-1 >= 40.42% -> FAIL; Targeted: Take family recall >= 39.1101% -> FAIL [37.71%], Take exact Top-1 >= 8.3183% -> FAIL [3.92%], Take pattern exact Top-1 >= 8.3183% -> FAIL [4.07%], Reserve exact Top-1 >= 12.22% -> FAIL [11.16%], Buy exact Top-1 >= 74.15% -> PASS [74.40%]).
FIT_ATTRIBUTION = M34A-v1 increased Take family recall (+8.60 pp vs D2), but did not improve exact Take pattern or full-action selection (Take Top-1 3.92% vs D2 3.32%, Pattern Top-1 4.07% vs D2 3.32%) and regressed overall validation Top-1 (37.14% vs D2 38.42%), failing all primary and signal gates. This outcome terminates the current hierarchical take-pattern recipe without excluding alternative hierarchical targets, conditioned action decoders, value guidance, or search-based policies.
DECISION = STOP_HIERARCHICAL_TAKE_PATTERN_POLICY_ROUTE
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = COMPLETED_STOP_ROUTE
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

## Iteration log and validation results

- **P0 Remediation**:
  1. Replaced additive residual logit flattening with true explicit hierarchical conditional probability decomposition ($P(\text{family}) \cdot P(\text{pattern}\mid\text{take}) \cdot P(\text{return}\mid\text{pattern})$).
  2. Implemented fully vectorized grouped logsumexp via CUDA scatter-reduce, eliminating host-device synchronization during training.
  3. Bound preflight to official D2-v2 checkpoint SHA `113372fc1092e611804cb7261844ac2a104608772f68ab74a854a038370c7e17` and verified internal checkpoint metadata.
  4. Corrected family action identifier to `choose_noble` and verified all 6 unit tests in `test_m34a_hierarchical_policy.py`.

### 128-Epoch Training and Gate Evaluation Results

M34A completed 128 epochs of training on the canonical M25 dataset. Best checkpoint selected strictly by validation canonical policy CE at Epoch 11:

| Metric | D2-v2 Baseline | M34A Achieved | Target Gate | Verdict |
| :--- | :---: | :---: | :---: | :---: |
| **Validation Policy CE** | 2.8177 nats | **2.8160 nats** | $\le 2.7977$ (-0.0200 nats) | **FAIL** (-0.0018 nats) |
| **Validation Excess CE** | +0.3449 nats | **+0.3431 nats** | - | - |
| **Validation Improvement BPS** | 862 bps | **868 bps** | $\ge 1000\text{ bps}$ | **FAIL** (+6 bps) |
| **Validation Global Top-1** | 38.42% | **37.14%** (1,510/4,066) | $\ge 45.00\%$ (G1) / $\ge 40.42\%$ (Signal) | **FAIL** (-1.28 pp vs D2) |
| **Family Top-1 Match** | 68.03% | **69.60%** | - | +1.57 pp |
| **Take Family Recall** | 29.11% | **37.71%** (500/1,326) | $\ge 39.1101\%$ (+10 pp) | **FAIL** (+8.60 pp) |
| **Take Exact Top-1** | 3.32% | **3.92%** (52/1,326) | $\ge 8.3183\%$ (+5 pp) | **FAIL** (+0.60 pp) |
| **Take Pattern Exact Top-1** | 3.32% | **4.07%** (54/1,326) | $\ge 8.3183\%$ (+5 pp) | **FAIL** (+0.75 pp) |
| **Take Cond Return Match** | N/A | **0.00% (0/2)** | Tracking | - |
| **Buy Exact Top-1** | 76.15% | **74.40%** (1,354/1,820) | $\ge 74.15\%$ (max -2 pp) | **PASS** (-1.75 pp) |
| **Reserve Exact Top-1** | 14.22% | **11.16%** (102/914) | $\ge 12.22\%$ (stability floor) | **FAIL** (-3.06 pp) |

## Scientific Attribution and Conclusion

M34A-v1 提升了 Take family recall（从 29.11% 提升至 37.71%），但未改善精确 Take pattern/action 选择（Take Top-1 3.92% vs D2 3.32%，Pattern Top-1 4.07% vs D2 3.32%），也未通过全局门禁（全局 Top-1 降至 37.14% vs D2 38.42%）；因此停止当前 hierarchical take-pattern recipe。

该结果不排除其他层次目标、条件式组合解码、价值辅助或搜索方法。

**最终决策**：`STOP_HIERARCHICAL_TAKE_PATTERN_POLICY_ROUTE`。无 Arena 授权。
