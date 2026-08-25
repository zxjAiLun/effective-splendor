# M29A — Action-Conditioned Entity Pooling v1

```ini
MILESTONE = M29A
STATUS = COMPLETED / STOP_ACTION_ENTITY_REPRESENTATION_ROUTE / NO_ARENA
BASE_COMMIT = 036a402517596a297e20bfd497e682ef9ffbc1eb
SCOPE = Single-layer action-to-entity cross-attention pooling on top of h192/b4 + D2 exact action deltas (1,175,428 parameters) to probe whether dynamic per-action entity querying breaks through the teacher-fit plateau.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
TRAINING = COMPLETED (128/128 epochs on CUDA; best epoch 16 selected by validation CE).
OFFLINE_GATES = G1 FAIL (Top-1 36.55% < 45.00%, CE bps 874 < 1000). Representation delta vs D2 FAIL (CE delta -0.0037 nats > -0.03 nats, Top-1 delta -1.87 pp < +3.0 pp).
FIT_ATTRIBUTION = Train top-1 38.15% (CE 2.7834) vs Val top-1 36.55% (CE 2.8141); action cross-attention yields negligible CE gain (-0.0037 nats) and regresses Top-1 accuracy (-1.87 pp) compared to standard D2 pooling.
DECISION = STOP_ACTION_ENTITY_REPRESENTATION_ROUTE
ARENA = NOT_AUTHORIZED
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

Following the M25 Lean Recovery explorations:
1. **Experiment D2** confirmed that injecting explicit 23-dim exact post-action state transition deltas into action embeddings yielded a major breakthrough (Validation CE 2.8879 $\to$ 2.8177, Top-1 31.87% $\to$ 38.42%, +227 bps CE improvement over baseline action encoding).
2. **Experiment B & E** confirmed that scaling model width by 2.75x (h192 $\to$ h320, 0.95M $\to$ 2.61M parameters) yielded virtually zero validation gain ($\le 0.0020\text{ nats}$ CE reduction).
3. **Experiment F** confirmed that de-floored advantage loss training slightly sharpened Top-1 (+0.25 pp) but did not solve the fitting bottleneck (CE improvement 845 bps < 1000 bps).

The M29A question was:

> By replacing static uniform/gated state pooling with a single-layer action-to-entity cross-attention mechanism—where each candidate action dynamically queries the slot-specific entity representations (market cards, player resources, nobles)—can the network resolve fine-grained target preferences and achieve the G1 gate (Top-1 $\ge 45.00\%$, CE $\ge 1000\text{ bps}$)?

## Initial design

M29A added an action-conditioned cross-attention layer to the h192/b4 + D2 architecture:
1. **Entity Sequence**: State entities are encoded into hidden representations $E \in \mathbb{R}^{B \times N \times h}$ ($N=25, h=192$).
2. **Action Queries**: Action embeddings $A \in \mathbb{R}^{\text{actions} \times h}$ project to queries $Q = W_Q A$.
3. **Cross-Attention Pooling**: Keys $K = W_K E$ and values $V = W_V E$ produce per-action attention weights over entities:
   $$\alpha = \text{softmax}\left(\frac{Q K^T}{\sqrt{h}}\right)$$
   $$C_{\text{action}} = \alpha V$$
4. **Policy Scoring**: Policy head consumes $[S_{\text{global}}, A_{\text{context}}, S_{\text{global}} \odot A_{\text{context}}, A \odot C_{\text{action}}]$.
5. **Frozen Configuration**: Evaluated on identical data split (12,216 train / 4,066 val), identical initialization seed (`280229`), identical shuffle seed (`20260823`), 128 epochs with Cosine Annealing learning rate schedule (3e-4 $\to$ 1e-5), and weight decay `1e-4`.

## Scope and non-goals

### In scope
- Single-layer action-to-entity cross-attention (1,175,428 parameters, +23% over baseline h192).
- Full 128-epoch training on canonical M25 dataset.
- Preregistered representation delta gate: $\Delta\text{CE} \le -0.03\text{ nats}$ or $\Delta\text{Top-1} \ge +3.0\text{ pp}$ relative to Exp D2.
- G1 held-out teacher fit evaluation.

### Non-goals
- No changes to dataset, targets, split, or seeds.
- No Arena matches authorized before offline gate success.
- No multi-layer cross-attention expansion if single layer fails representation gate.

## Iteration log

- **2026-08-23 M29A Architecture & Smoke Test**: Designed `ActionConditionedEntityMixer` (1,175,428 parameters) with action-conditioned cross-attention pooling. Verified packed batch forward pass on CUDA.
- **2026-08-23 M29A 128-Epoch GPU Training**: Executed full 128-epoch training on CUDA. Best epoch 16 achieved Validation CE = 2.8141 (Excess CE = +0.3412 nats), Validation Top-1 = 36.55%, CE Improvement = 874 bps.
- **2026-08-23 Gate Evaluation & Decision**:
  - G1 Gate: FAIL (Top-1 36.55% < 45.00%, CE Improvement 874 bps < 1000 bps).
  - Representation Gate: FAIL (CE delta vs D2 = -0.0037 nats > -0.03 nats; Top-1 delta vs D2 = -1.87 pp < +3.0 pp).
  - Formal Decision: `STOP_ACTION_ENTITY_REPRESENTATION_ROUTE`. Arena `NOT_AUTHORIZED`.

## Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Benchmark Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Result Document | `benchmarks/m29a-action-conditioned-entity-pooling-v1.result.json` | Formal M29A Result Artifact |
| Checkpoint | `local-artifacts/m29a-action-conditioned-entity-pooling-v1/checkpoint.pt` | `658d3d2c19a400ce0835a1e186a9a56f20225f04d27ff599d7381736c336eb41` |
| Architecture Implementation | `training/m17_gpu/splendor_gpu/m29a_model.py` | ActionConditionedEntityMixer v1 |
| Training Script | `training/m17_gpu/splendor_gpu/m29a_train.py` | M29A GPU Training Runner |

## Validation and evidence

### Comparison against Experiment D2 Baseline

| Metric | Exp D2 (Standard Gated Pooling) | M29A (Action Cross-Attention Pooling) | Delta (M29A - D2) | Representation Gate Target | Gate Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Parameters** | 953,476 | 1,175,428 | +221,952 (+23.3%) | — | — |
| **Best Epoch (CE-selected)** | Epoch 11 | **Epoch 16** | +5 epochs | — | — |
| **Validation Policy CE** | 2.8177 | **2.8141** | **-0.0037 nats** | $\le -0.03\text{ nats}$ | **FAIL** |
| **Validation Excess CE** | +0.3449 nats | **+0.3412 nats** | **-0.0037 nats** | — | — |
| **Validation Policy Top-1** | **38.42%** | 36.55% | **-1.87 pp** | $\ge +3.0\text{ pp}$ | **FAIL** |
| **Validation CE Improvement** | 862 bps | **874 bps** | +12 bps | $\ge 1000\text{ bps}$ | **FAIL** |
| **Train Policy CE (Best Ckpt)** | 2.7839 | **2.7834** | -0.0005 nats | — | — |
| **Train Policy Top-1 (Best Ckpt)** | 39.52% | 38.15% | -1.37 pp | — | — |

## Result and decision

1. **Representation Gate Failed**: Dynamically querying entity representations per action via cross-attention provides negligible validation cross-entropy gain ($-0.0037\text{ nats}$, far from the required $-0.03\text{ nats}$ threshold) and regresses Top-1 accuracy by $-1.87\text{ pp}$ (from 38.42% down to 36.55%).
2. **G1 Gate Failed**: Validation Top-1 36.55% (< 45.00%) and CE Improvement 874 bps (< 1000 bps).
3. **Scientific Conclusion & Stopping Rule**:
   - Explicit post-action transition state deltas (D2) already provide the critical observation-action coupling information; adding parameter-heavy attention over entity tokens offers no additional structural advantage and increases optimization variance.
   - Per preregistered instruction, the **action-entity representation route is formally stopped**.
4. **Arena Execution**: `NOT_AUTHORIZED`.
5. **Promotion**: `NONE`. M07 heuristic determinization champion remains unchanged.
