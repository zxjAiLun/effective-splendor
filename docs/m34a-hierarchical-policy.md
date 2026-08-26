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
FIT_ATTRIBUTION = The Hierarchical Action Decomposition Hypothesis is REJECTED offline. Decomposing the action probability space into explicit Family -> Take Pattern -> Return Gem choices did NOT break the token acquisition bottleneck (Take Top-1 remained at 3.92% vs D2 3.32%, Pattern Top-1 4.07% vs D2 3.32%, Global Top-1 regressed to 37.14% vs D2 38.42%).
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

## Experimental Results and Gate Evaluation

M34A completed 128 epochs of training on the canonical M25 dataset. Best checkpoint selected strictly by validation canonical policy CE at Epoch 11:

| Metric | D2-v2 Baseline | M34A Achieved | Target Gate | Verdict |
| :--- | :---: | :---: | :---: | :---: |
| **Validation Policy CE** | 2.8177 nats | **2.8160 nats** | $le 2.7977$ (-0.0200 nats) | **FAIL** (-0.0018 nats) |
| **Validation Excess CE** | +0.3449 nats | **+0.3431 nats** | - | - |
| **Validation Improvement BPS** | 862 bps | **868 bps** | $ge 1000	ext{ bps}$ | **FAIL** (+6 bps) |
| **Validation Global Top-1** | 38.42% | **37.14%** | $ge 45.00%$ (G1) / $ge 40.42%$ (Signal) | **FAIL** (-1.28 pp vs D2) |
| **Family Top-1 Match** | 68.03% | **69.60%** | - | +1.57 pp |
| **Take Family Recall** | 29.11% | **37.71%** | $ge 39.11%$ (+10 pp) | **FAIL** (+8.60 pp) |
| **Take Exact Top-1** | 3.32% | **3.92%** | $ge 8.32%$ (+5 pp) | **FAIL** (+0.60 pp) |
| **Take Pattern Exact Top-1** | 3.32% | **4.07%** | $ge 8.32%$ (+5 pp) | **FAIL** (+0.75 pp) |
| **Take Cond Return Match** | N/A | **0.00% (0/2)** | Tracking | - |
| **Buy Exact Top-1** | 76.15% | **74.40%** | $ge 74.15%$ (max -2 pp) | **PASS** (-1.75 pp) |
| **Reserve Exact Top-1** | 14.22% | **11.16%** | $ge 12.22%$ (stability floor) | **FAIL** (-3.06 pp) |

## Scientific Attribution and Conclusion

1. **Failure of the Hierarchical Action Decomposition Route**:
   Explicitly structuring the action space into $P(	ext{family}) cdot P(	ext{take_pattern}mid	ext{take}) cdot P(	ext{return}mid	ext{pattern})$ yielded only an imperceptible gain in Take pattern accuracy (from 3.32% to 4.07%) and Take exact Top-1 (from 3.32% to 3.92%), while overall validation Top-1 regressed by 1.28 pp (37.14% vs 38.42%).
2. **Structural Bottleneck Diagnostic**:
   The token acquisition bottleneck is not caused by mathematical softmax credit competition or action probability factorization. The representation bottleneck lies upstream in the state-action value / policy representation (e.g. lack of state value guidance or lookahead).
3. **Decision**:
   `STOP_HIERARCHICAL_TAKE_PATTERN_POLICY_ROUTE`. No Arena matches authorized.
