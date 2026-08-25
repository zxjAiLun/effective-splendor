# M29A — Action-Conditioned Entity Pooling v1 & v2

```ini
MILESTONE = M29A
STATUS = COMPLETED / STOP_ACTION_ENTITY_REPRESENTATION_ROUTE / NO_ARENA
BASE_COMMIT = 036a402517596a297e20bfd497e682ef9ffbc1eb
SCOPE = Action-to-entity cross-attention pooling on top of h192/b4 + D2 exact action deltas to probe whether dynamic per-action entity querying breaks through the teacher-fit plateau. Evaluated both v1 (replaced policy head) and v2 (nested residual attention with strict D2 zero-initialization).
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
TRAINING = COMPLETED (v1: 128 epochs, best epoch 16; v2: 128 epochs, best epoch 13 selected by validation CE).
OFFLINE_GATES = G1 FAIL (v2 Top-1 38.66% < 45.00%, CE bps 876 < 1000). Representation delta vs D2 FAIL (v2 CE delta -0.0043 nats > -0.03 nats, Top-1 delta +0.25 pp < +3.0 pp).
FIT_ATTRIBUTION = Train top-1 40.37% (CE 2.7677) vs Val top-1 38.66% (CE 2.8134); nested residual attention is strictly mathematically initialized to D2 baseline and verified via 4 targeted unit tests, but training converges to negligible gain (-0.0043 nats / +0.25 pp Top-1), confirming that action-to-entity attention pooling provides no substantive signal above D2 transition deltas.
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

> By augmenting the static gated state pooling with an action-to-entity cross-attention mechanism—where each candidate action dynamically queries the slot-specific entity representations (market cards, player resources, nobles)—can the network resolve fine-grained target preferences and achieve the G1 gate (Top-1 $\ge 45.00\%$, CE $\ge 1000\text{ bps}$)?

## Design: v1 vs v2 Nested Residual Architecture

1. **M29A-v1 (Replaced Policy Path)**:
   - Evaluated a replaced policy head consuming $[S_{\text{global}}, A_{\text{context}}, S_{\text{global}} \odot A_{\text{context}}, A \odot C_{\text{action}}]$.
   - Result: Val CE = 2.8141, Top-1 = 36.55% (regressed Top-1 by -1.87 pp vs D2).
   - Review finding: Replacing the baseline $[S, A, S \odot A]$ direct path confounded the architecture comparison.

2. **M29A-v2 (Nested Residual Attention)**:
   - **Exact D2 Baseline Preservation**: Preserves the exact D2 module initialization order and the baseline logit branch $\text{logit}_{\text{base}} = \text{Policy}([S, A, S \odot A])$.
   - **Zero-Initialized Residual Attention**: Action query $Q = W_Q A$ computes cross-attention over entity sequence $E$ to produce context $C_{\text{action}} = \text{softmax}(Q K^T / \sqrt{h}) V$. A residual head with zero-initialized final projection computes $\text{logit}_{\text{res}} = \text{ResidualHead}([S, A, C_{\text{action}}, A \odot C_{\text{action}}])$.
   - **Mathematical Equivalence at Init**: At initialization, $\text{logit}_{\text{res}} \equiv 0$, guaranteeing strict bitwise and mathematical equality to D2 baseline output.
   - **Parameter Count**: 1,212,484 parameters (+27.2% over D2 baseline).

## Contracts and invariants

- **Exact Initial Equivalence**: Tested via `test_baseline_init_equality` against D2 reference.
- **Batch Packing Invariance**: Tested via `test_packed_per_sample_equality`.
- **Entity Mask Invariance**: Tested via `test_mask_invariance` ensuring masked invalid slots have 0 effect.
- **Gradient Flow Verification**: Tested via `test_residual_gradient_flow` ensuring non-zero gradients across attention projection weights.
- **Fail-Closed Protection**: Asserted `ckpt_dir.exists()` before dataset pre-encoding.

## Scope and non-goals

### In scope
- Nested residual action-to-entity cross-attention (1,212,484 parameters).
- Full 128-epoch training on canonical M25 dataset (init seed `280229`, shuffle seed `20260823`).
- Preregistered representation delta gate: $\Delta\text{CE} \le -0.03\text{ nats}$ or $\Delta\text{Top-1} \ge +3.0\text{ pp}$ relative to Exp D2.
- G1 held-out teacher fit evaluation.

### Non-goals
- No changes to dataset, targets, split, or seeds.
- No Arena matches authorized before offline gate success.
- No further representation expansions if v2 fails representation gate.

## Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Benchmark Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Result Document v1 | `benchmarks/m29a-action-conditioned-entity-pooling-v1.result.json` | M29A-v1 Result Artifact |
| Result Document v2 | `benchmarks/m29a-v2-nested-residual-attention.result.json` | M29A-v2 Result Artifact |
| Checkpoint v2 | `local-artifacts/m29a-v2-nested-residual-attention/checkpoint.pt` | `f3bd8104b1d8177843d9eb919c00aa2923d7fb513f21f6960c662a5e16198873` |
| Architecture Implementation | `training/m17_gpu/splendor_gpu/m29a_v2_model.py` | NestedResidualActionEntityMixer |
| Training Script | `training/m17_gpu/splendor_gpu/m29a_v2_train.py` | M29A-v2 GPU Training Runner |
| Unit Tests | `training/m17_gpu/tests/test_m29a_v2.py` | 4 targeted unit tests (all passed) |

## Validation and evidence

### Comparison against Experiment D2 Baseline

| Metric | Exp D2 (Baseline h192+Delta) | M29A-v1 (Replaced Head) | M29A-v2 (Nested Residual Attention) | Delta (v2 - D2) | Representation Gate Target | Gate Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Parameters** | 953,476 | 1,175,428 | 1,212,484 | +259,008 (+27.2%) | — | — |
| **Best Epoch (CE-selected)** | Epoch 11 | Epoch 16 | **Epoch 13** | +2 epochs | — | — |
| **Validation Policy CE** | 2.8177 | 2.8141 | **2.8134** | **-0.0043 nats** | $\le -0.03\text{ nats}$ | **FAIL** |
| **Validation Excess CE** | +0.3449 nats | +0.3412 nats | **+0.3406 nats** | **-0.0043 nats** | — | — |
| **Validation Policy Top-1** | 38.42% | 36.55% | **38.66%** | **+0.25 pp** | $\ge +3.0\text{ pp}$ | **FAIL** |
| **Validation CE Improvement** | 862 bps | 874 bps | **876 bps** | +14 bps | $\ge 1000\text{ bps}$ | **FAIL** |
| **Train Policy CE (Best Ckpt)** | 2.7839 | 2.7834 | **2.7677** | -0.0162 nats | — | — |
| **Train Policy Top-1 (Best Ckpt)** | 39.52% | 38.15% | **40.37%** | +0.85 pp | — | — |

## Result and decision

1. **Representation Gate Failed**:
   - In M29A-v2 with strict baseline preservation and zero-initialized attention residual logits, the learned attention mechanism only reduces validation CE by **$-0.0043\text{ nats}$** (target $\le -0.03\text{ nats}$) and increases Top-1 by **$+0.25\text{ pp}$** (target $\ge +3.0\text{ pp}$).
2. **G1 Gate Failed**: Validation Top-1 38.66% (< 45.00%) and CE Improvement 876 bps (< 1000 bps).
3. **Scientific Conclusion & Formal Stopping Rule**:
   - Having tested both replaced-head pooling (v1) and strict nested residual attention (v2), the empirical evidence conclusively demonstrates that dynamic action-to-entity cross-attention pooling provides negligible signal over static transition deltas (D2).
   - The **action-entity representation route is formally stopped**.
4. **Arena Execution**: `NOT_AUTHORIZED`.
5. **Promotion**: `NONE`. M07 heuristic determinization champion remains unchanged.
