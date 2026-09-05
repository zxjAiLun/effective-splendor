# M42A Visible Action–Entity Relation Residual Probe

```text
Milestone:      M42A
Title:          Visible Action–Entity Relation Residual Probe
Status:         PROPOSED / REVISION_1 / PENDING_FINAL_REVIEW
Baseline:       605bb83 (M41A closure)
Prior rounds:   M41A (COMPLETED_NEGATIVE / CLOSED — M41A_COUNTERFACTUAL_ACTION_VALUE_NOT_VALIDATED)
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE (measurement / representation probe)
Arena:          NOT AUTHORIZED
Power-cal:      SEALED / NOT AUTHORIZED
Formal reserve: SEALED / NOT AUTHORIZED (9_000_304..9_000_815 untouched)
TD / fitted-Q / PPO / search: OUT OF SCOPE
M42S:           NOT YET AUTHORIZED
```

## Problem and evidence

M41A demonstrated that even with exhaustive counterfactual supervision (19,190 branches across 304 games, deterministic D2/D2 teacher), the D2-style joint scorer failed the action-identity integrity gate (`cyclic_shift` ablation failed on both F and U arms: F ranking dropped only ~5.5 pp, U dropped only ~2.4 pp, regret improved or barely moved). While the model passed zero-action ablation, it failed to bind specific action identities to specific state entities.

Historical M29A attempted action-to-entity cross-attention on top of generic card/player embeddings with 59-dim action vectors, and failed (-1.87 pp vs D2). M29A-v2 nested residual attention also failed (+0.25 pp). In both cases, the network was required to derive non-linear token-to-cost deficit arithmetic internally.

M42A tests a strictly targeted hypothesis:
> **If the rule-exact, player-view visible consequences of an action on each entity ($R(o, a, e_i) \in \mathbb{R}^{28}$) are provided explicitly to an action-conditioned entity residual architecture, does the model learn to genuinely bind specific action identities to entity consequences and pass the cyclic-shift ablation gate?**

## Scope and non-goals

### In scope
- Read-only reuse of M41A P2 training and validation corpus (train: 192 games `9_000_000..9_000_191` / 576 states; validation: 48 games `9_000_192..9_000_239` / 144 states).
- Frozen immutable baseline B: M41A-F Run 3 (`6af9d23597ade13663748d96c82d43f0e3159ae60c5e7cd7d8a2066553b7dd9a`, semantic `c475f6f20761e1580f8ec39517f940ab81fa848689ccf6c3473fa676f42cc05c`).
- 28-dim per-entity rule-derived player-view relation tensor $R(o, a, e_i)$.
- Paired experimental arms X (generic residual control: relation tensor = 0) and R (explicit relation residual: relation tensor = $R(o, a, e_i)$), sharing exact parameter count, initialization seed (`42_261_001`), optimizer, and shuffle.
- Zero-initialized residual projection ensuring $B = X = R$ at initialization.
- Offline validation diagnostics: material-pair ranking @ $\tau=1$, mean regret, zero ablation, cyclic shift ablation, relation-only diagnostics.

### Out of scope / strictly forbidden
- Generating any new branch rollouts or modifying M41A corpus.
- Touching power-calibration or formal reserve partitions (`9_000_304..9_000_815`).
- Unfreezing D2 trunk, action encoder, or M41A base head (F arm only).
- Arena games, model promotion, PPO, TD, fitted-Q, heuristic/search teacher rollout.
- FullState leakage (hidden deck identities, replacement cards on refill, opponent blind reserves).

## Contracts and invariants

1. **Information parity & no-leakage contract (P0 hard gate)**:
   $R(o, a, e_i)$ must be computable strictly from `(Observation, Action, Catalog)`. It must never receive `FullState`, unseen deck contents, replacement cards drawn from decks, or opponent private reserves.
2. **Deterministic initialization contract**:
   Residual head projection is initialized to zero (`weight = 0`, `bias = 0`). At epoch 0, `B(o, a) == X(o, a) == R(o, a)` bit-exact.
3. **Paired control contract**:
   Arm X and Arm R have identical architectures and parameter counts. Arm X sets the 28-dim relation tensor to 0. Arm R sets it to $R(o, a, e_i)$.
4. **Hierarchical training contract**:
   Identical to M41A: 16 epochs, AdamW (lr=1e-4, wd=1e-4), 32 games/batch, FP32, gradient clip 1.0, legal-set centered Huber loss ($\delta=1.0$), state-to-game-to-batch hierarchical mean, final epoch checkpoint only.
5. **Ablation gates (M41A inherited)**:
   Both zero and cyclic-shift corruptions must cause:
   $\Delta\text{ranking} \le -10\text{ pp}$ OR $\Delta\text{regret} \ge +0.05$.

## Relation Tensor Specification (28 dims per entity)

Defined for each entity $e_i \in \{0..30\}$:
- Dims 0..6: entity type & action interaction booleans (`is_card`, `is_noble`, `action_targets_entity`, `action_buys_entity`, `action_reserves_entity`, `action_claims_entity`, `entity_consumed_or_relocated`).
- Dims 7..11: per-color deficit before action $[cost_c - bonus_c - token_c]_+ / 7.0$.
- Dims 12..16: per-color deficit after action $[cost_c - bonus_c' - token_c']_+ / 7.0$.
- Dims 17..21: per-color deficit reduction `(before - after)`.
- Dim 22: total deficit before $\sum d_c / 35.0$.
- Dim 23: total deficit after $\sum d_c' / 35.0$.
- Dim 24: total deficit reduction `(total_before - total_after)`.
- Dim 25: `feasible_before` ($1.0$ if $\sum d_c \le gold$, else $0.0$).
- Dim 26: `feasible_after` ($1.0$ if $\sum d_c' \le gold'$, else $0.0$).
- Dim 27: `newly_feasible` ($1.0$ if !feasible_before and feasible_after, else $0.0$).
For player entities and empty padding slots: all 28 dimensions are $0.0$.

## Implementation plan

1. **P0 Relation Encoder & Tests**:
   - Create `training/m17_gpu/splendor_gpu/m42a_relation_v1.py`.
   - Create `training/m17_gpu/tests/test_m42a_relation_v1.py` covering no-leak invariants, microfixtures (take, buy, reserve_market, reserve_deck, noble, pass), and normalization.
2. **P0 Model Architecture & Tests**:
   - Create `training/m17_gpu/splendor_gpu/m42a_model.py`.
   - Create `training/m17_gpu/tests/test_m42a_model.py` testing $B = X = R$ initialization equality, freeze invariants, and forward shapes.
3. **Baseline B Reproduction**:
   - Load M41A-F Run 3 checkpoint and verify exact reproduction of validation metrics (ranking 59.31%, regret 0.8750).
4. **P1 Training Pipeline**:
   - Create `training/m17_gpu/splendor_gpu/m42a_train.py` training paired arms X and R.
5. **P2 Validation Diagnostics & Evaluation**:
   - Create `training/m17_gpu/splendor_gpu/m42a_diagnostics.py`.
   - Evaluate B, X, R against Zero, Cyclic Shift, and Relation-only ablations.
   - Apply frozen decision table.

## Iteration log

- 2026-09-05: M42A Design v1 frozen and authorized by user. P0 implementation, P1 training, and P2 validation diagnostics authorized.
- 2026-09-05: P0 implementation complete: `m42a_relation_v1.py` and `m42a_model.py`.
- 2026-09-05: Run 1 executed: Arm X (loss 0.272681) and Arm R (loss 0.272681). Review verdict: **Run 1 VOID** due to optimizer contract drift (missing `foreach=False`), unasserted base contracts, and unvalidated cache. P0=1, P1=3, P2=2. Milestone reopened for Repair 1 + exact rerun.
- 2026-09-05 (Repair 1):
  - **P0-1**: AdamW updated with explicit `foreach=False`.
  - **P1-3**: Hard fail-closed assertions added for B file SHA (`6af9d235…`), B semantic SHA (`c475f6f2…`), and M41 run-contract SHA (`2a449550…`).
  - **P1-2**: Derived cache deleted and completely rebuilt from scratch with per-state authoritative hashes (`authoritative_observation_hash`, `authoritative_state_hash`, `authoritative_legal_hash`, `ordered_actions_hash`, `relation_tensor_sha256`) and split canonical manifest SHA (`898445e5…` train, `7b551272…` val). Loading validates every state fail-closed.
  - **P2-1**: Comprehensive tests added in `test_m42a_relation_v1.py` including hand-calculated numeric deficit/feasibility oracle, reserve_deck, pass, and strict player-view boundary checks.
  - **P1-1**: Activation instrumentation implemented (parameter L2 deltas from init, X vs R tensor comparison, gradient norms, $q_{res}$ within-state standard deviations, and R vs relzero score deltas).
  - Run 1 artifacts preserved as `*-VOID1-*`.
  - Fresh Run 2 executed (Arm X and Arm R, 16 epochs each).
  - Diagnostics re-executed and full activation audit table generated.

## Final implementation (Repair 1)

- Relation encoder: `training/m17_gpu/splendor_gpu/m42a_relation_v1.py` (28-dim player-view relation tensor $R(o, a, e_i)$ across 31 entity slots, zero access to FullState or hidden cards).
- Model architecture: `training/m17_gpu/splendor_gpu/m42a_model.py` (`M42AModel`, `M42ARelationResidual`, zero-init final linear layer, 277,314 trainable parameters).
- Trainer: `training/m17_gpu/splendor_gpu/m42a_train.py` (hierarchical legal-set centered Huber loss, 16 epochs, 32 games/batch, FP32 deterministic CUDA, explicit `foreach=False`).
- Diagnostics: `training/m17_gpu/splendor_gpu/m42a_diagnostics.py` (normal, zero, cyclic-shift, relation-zero, relation-shift ablations, activation audit, relation dataset audit).
- Artifacts:
  - Cache: `local-artifacts/m42a-derived/` (train manifest: `898445e5ff371089…`, val manifest: `7b5512726899b55a…`)
  - Run 1 (VOID): `local-artifacts/m42a-run/m42a-*-VOID1-*.pt`
  - Run 2 Checkpoints:
    - Arm X: `local-artifacts/m42a-run/m42a-X-final.pt` (File SHA: `20e43618ace1edb8a99932a766b58437b78ed3e47c2271932c309fe1d08c62b3`, Residual Semantic SHA: `666f24ae5afd4426e72fb17acfa50f1ea9b5d467e8a17edbc6981ae8830f5df6`)
    - Arm R: `local-artifacts/m42a-run/m42a-R-final.pt` (File SHA: `d6268786d827af7eeb52dd11e73e1de2651444b04a0170ce87b24a693d522ba3`, Residual Semantic SHA: `3f32c7c637303c71584fdcde606530a36f205ca1ec73ee718d214c2d654d3928`)
  - Report: `local-artifacts/m42a-run/m42a-diagnostics-report.json`.

## Validation and evidence (Run 2 Valid)

144 validation states, 27,677 material pairs, $\tau = 1.0$:

### 1. Main Metrics & Ablation Table

| Metric / Arm | Baseline B (M41A-F) | Arm X (Generic Residual) | Arm R (Relation Residual) |
|---|---|---|---|
| **Validation Huber Mean** | 0.250080 | 0.250053 | 0.250053 |
| **Material Ranking Accuracy** | 59.31% | 59.25% | 59.25% |
| **Mean Regret** | 0.8750 | 0.8750 | 0.8750 |
| **D2 Baseline Regret** | 0.8750 | 0.8750 | 0.8750 |
| **Zero-Ablation Ranking** | 50.00% (-9.31 pp) | 50.00% (-9.25 pp) | 50.00% (-9.25 pp) |
| **Zero-Ablation Regret** | 0.9514 (+0.0764) | 0.9514 (+0.0764) | 0.9514 (+0.0764) |
| **Zero-Ablation Gate** | **PASS** | **PASS** | **PASS** |
| **Cyclic Shift Ranking** | 53.85% (-5.46 pp) | 53.73% (-5.52 pp) | 53.73% (-5.52 pp) |
| **Cyclic Shift Regret** | 0.8889 (+0.0139) | 0.8889 (+0.0139) | 0.8889 (+0.0139) |
| **Shift Integrity Gate** | **FAIL** | **FAIL** | **FAIL** |

### 2. Post-Training Activation Audit Table

| Evidence Metric | Arm X | Arm R |
|---|---:|---:|
| **Residual Semantic SHA** | `666f24ae5afd4426…` | `3f32c7c637303c71…` |
| **Total Parameter L2 Delta $\|\theta_{\text{final}} - \theta_{\text{init}}\|_2$** | 0.295970 | 0.301228 |
| **relation_encoder Delta** | 0.005062 | **0.016167** (3.2x vs X) |
| **pair_encoder Delta** | 0.149322 | **0.155542** |
| **gate Delta** | 0.000104 | **0.000395** (3.8x vs X) |
| **residual_head[0] Delta** | 0.254698 | 0.256666 |
| **residual_head[final] Delta** | 0.020123 | 0.020150 |
| **Mean $\|q_{\text{res}}\|$** | 0.000727 | 0.000768 |
| **Within-State $\text{std}(q_{\text{res}})$** | 0.000642 | 0.000642 |
| **Mean $\|R(\text{normal}) - R(\text{relation-zero})\|$** | N/A | **0.000009** (max: 0.000022) |
| **Mean $\|R - X\|$ Score Delta** | 0.000059 | 0.000059 (max: 0.000068) |

**Comparison X vs R**:
- Tensors different: 13 / 14 (only 1 tensor identical, 13 changed differently).
- Max absolute tensor delta: 0.001455.
- $L_2$ parameter distance between X and R: 0.046826.

### 3. Relation Dataset Audit

| Dataset Feature | Validation Split (144 states) |
|---|---:|
| **States with $\ge 2$ distinct relation tensors** | 143 / 144 (**99.31%**) |
| **Action pairs with distinct relation tensors** | 88,475 / 89,363 (**99.01%**) |
| **Relation tensor nonzero rate** | **17.75%** |
| **Mean pairwise L1 distance between distinct relations** | **10.3601** |
| **Mean pairwise L2 distance between distinct relations** | **2.2757** |

## Result and decision

### Scientific Diagnosis
1. **The dataset genuinely varies**: 99.31% of states and 99.01% of legal action pairs exhibit distinctly different relation tensors, with substantial mean L1 distance (10.36). There is no dataset redundancy or lack of input signal.
2. **Gradients flowed and weights updated**: In both arms, the residual parameters moved significantly from initialization ($\|\theta_{\text{final}} - \theta_{\text{init}}\|_2 \approx 0.30$). Arm R's relation encoder and gate moved 3.2x and 3.8x further than Arm X, and 13 of 14 tensors diverged between X and R.
3. **The residual signal was suppressed**: Despite weight updates, the residual score magnitude remained minuscule (mean $\|q_{\text{res}}\| \approx 0.00077$), and the sensitivity of Arm R's output to zeroing the relation tensor was on the order of $10^{-5}$ ($0.000009$). The converged base Q-head $f_B$ completely dominated predictions.
4. **Integrity gate result**: Cyclic shift of actions degrades ranking by only 5.52 pp (< 10 pp) and regret by only +0.0139 (< 0.05). Both Arm X and Arm R FAIL the action-identity integrity gate.

### Ruling
Per the pre-registered decision table:
- Case A applies (`X FAIL identity`, `R FAIL identity`).
- Proposed verdict: `M42A_RELATION_REPRESENTATION_NOT_VALIDATED / CLOSED_NEGATIVE`.
- Status: **`PENDING_FINAL_REVIEW`** (awaiting reviewer confirmation).

## Known limitations

1. Adding a zero-initialized residual head on top of a converged base Q-head under a legal-set centered Huber loss allowed the network to satisfy gradients with minimal output perturbations, effectively suppressing the newly added relation pathway.
2. The probe evaluated a residual addition; it did not re-train an end-to-end model from scratch where relation features could participate in primary state-action representation learning.

## Next authorized gate

Awaiting final review on M42A Repair 1 evidence.
`M42S` remains NOT YET AUTHORIZED until M42A formal review approval.
