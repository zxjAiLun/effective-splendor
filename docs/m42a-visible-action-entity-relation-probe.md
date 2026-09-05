# M42A Visible Action–Entity Relation Residual Probe

```text
Milestone:      M42A
Title:          Visible Action–Entity Relation Residual Probe
Status:         COMPLETED_NEGATIVE / CLOSED —
                M42A_RELATION_REPRESENTATION_NOT_VALIDATED
Baseline:       605bb83 (M41A closure)
Prior rounds:   M41A (COMPLETED_NEGATIVE / CLOSED — M41A_COUNTERFACTUAL_ACTION_VALUE_NOT_VALIDATED)
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE (measurement / representation probe)
Arena:          NOT AUTHORIZED
Power-cal:      SEALED / NOT AUTHORIZED
Formal reserve: SEALED / NOT AUTHORIZED (9_000_304..9_000_815 untouched)
TD / fitted-Q / PPO / search: OUT OF SCOPE
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
- 2026-09-05: P0 implementation complete: `m42a_relation_v1.py` and `m42a_model.py`. 11 unit tests passed (`test_m42a_relation_v1.py` 8/8, `test_m42a_model.py` 3/3).
- 2026-09-05: Immutable Baseline B reproduction verified on validation split: material ranking 59.3056% (59.31%), mean regret 0.8750, bit-exact match (`test_m42a_baseline_b_reproduction.py` 1/1).
- 2026-09-05: P1 paired training executed: Arm X (16 epochs, 7.5s, loss 0.272681) and Arm R (16 epochs, 16.8s, loss 0.272681).
- 2026-09-05: P2 validation diagnostics completed: both Arm X and Arm R fail the cyclic-shift identity integrity gate. Case A ruling applied: `M42A_RELATION_REPRESENTATION_NOT_VALIDATED / CLOSED_NEGATIVE`.

## Final implementation

- Relation encoder: `training/m17_gpu/splendor_gpu/m42a_relation_v1.py` (28-dim player-view relation tensor $R(o, a, e_i)$ across 31 entity slots, zero access to FullState or hidden cards).
- Model architecture: `training/m17_gpu/splendor_gpu/m42a_model.py` (`M42AModel`, `M42ARelationResidual`, zero-init final linear layer, 277,314 trainable parameters).
- Trainer: `training/m17_gpu/splendor_gpu/m42a_train.py` (hierarchical legal-set centered Huber loss, 16 epochs, 32 games/batch, FP32 deterministic CUDA).
- Diagnostics: `training/m17_gpu/splendor_gpu/m42a_diagnostics.py` (normal, zero, cyclic-shift, relation-zero, relation-shift ablations).
- Artifacts:
  - Cache: `local-artifacts/m42a-derived/`
  - Checkpoints: `local-artifacts/m42a-run/m42a-X-final.pt` (SHA: `3608681354cc6d7a19673fe66b3b88e315105db1b96e743d6b52785cb829eb0a`), `local-artifacts/m42a-run/m42a-R-final.pt` (SHA: `d44420c39c7584971cb7e0184c0f3fd47184d212518407cb9894d436f4b4ae79`).
  - Report: `local-artifacts/m42a-run/m42a-diagnostics-report.json`.

## Validation and evidence

144 validation states, 27,677 material pairs, $\tau = 1.0$:

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

### Relation-only Diagnostics (Arm R)
- `relation-zero`: ranking 59.25% ($\Delta = 0.00\text{ pp}$), regret 0.8750 ($\Delta = 0.00$).
- `relation-shift`: ranking 59.26% ($\Delta = +0.01\text{ pp}$), regret 0.8750 ($\Delta = 0.00$).

## Result and decision

Both Arm X and Arm R fail the cyclic-shift action-identity integrity gate (ranking drops only ~5.52 pp < 10 pp, regret degrades by only +0.0139 < 0.05).
Per the pre-registered decision table (Section 20):
**Case A applies**:
- `X FAIL identity`
- `R FAIL identity`
- Ruling: **`M42A_RELATION_REPRESENTATION_NOT_VALIDATED / CLOSED_NEGATIVE`**.

Strict scientific verdict:
Adding an explicit 28-dimensional player-view visible action-entity relation residual (even with zero-init Bit-exact start, exact deficit calculations, and 277k parameters) was insufficient to force the action-conditioned model to genuinely bind specific action identities to entity outcomes. The residual network remained essentially dormant/flat relative to the frozen base Q-head, and the cyclic shift corruption continued to produce only marginal degradation.

As stipulated in the design contract:
> **不再继续堆 architecture (Stop piling on representation architecture).**

## Known limitations

1. Residual head zero-initialization on top of an already converged base Q-head ($f_B$) created an optimization landscape where gradient steps on the centered Huber loss were insufficient to overcome the dominance of $f_B$.
2. Linear pooling of pair representations still relies on soft entity attention weights without relational graph message-passing or hard candidate filtering.
3. The offline target remains bounded by D2/D2 continuation values.

## Next authorized gate

M42A is permanently closed. No further training or ablations authorized under M42A.
Next authorized steps:
1. Parallel diagnostic **M42S (Search Gap Diagnostic)** to measure the empirical strength-compute frontier of shallow search on top of fixed evaluators.
2. Any future representation or value-learning work requires an entirely independent hypothesis and milestone design.

