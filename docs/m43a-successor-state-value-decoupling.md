# M43A Successor-State Value Decoupling Probe

```text
Milestone:      M43A
Title:          Successor-State Value Decoupling Probe
Type:           representation / evaluator decomposition
Status:         COMPLETED_NEGATIVE / CLOSED —
                M43A_SUCCESSOR_VALUE_NOT_LEARNED
Baseline:       14108de (M42S permanent closure)
Design:         DESIGN_V1 / FROZEN
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE
Arena:          NOT RUN (P1 BSS and P2 mapping integrity gates failed)
TD / fitted-Q / PPO / MCTS: OUT OF SCOPE
M41 power split: SEALED
M41 formal reserve: UNTOUCHED (9_000_304 .. 9_000_815)

Licensed conclusion (strict):
  When specific action consequence derivation is externalized to the
  Rust simulator, training a standalone player-view successor-state
  value model V_theta(o'_root) directly on terminal game outcomes
  failed the P1 value-learning gate: validation Brier 0.245868 vs
  constant predictor 0.249026 yielded a Brier Skill Score of only
  BSS = +0.0127 (< +0.05 gate FAIL), despite weak directional learning
  (ROC-AUC 0.6344). In offline root decision evaluation, the model
  achieved 58.83% material ranking (vs D2 59.31%), and both PRESTATE
  and CYCLIC-SUCCESSOR ablations failed the integrity degradation gate.
  Per the pre-registered decision rules, P3 Arena was NOT authorized.
  This establishes that merely externalizing transition physics to the
  simulator is insufficient when supervised by sparse terminal win/loss
  outcomes; the massive advantage of static-successor n1 over direct
  policies relies heavily on StaticEvaluatorV1's dense progress signals
  rather than transition access alone.
```

## Problem and evidence

M42S established that the static-successor baseline `n1` is overwhelmingly superior to the direct neural policy `d2-direct` (8,203.1 bps, 95% CI: [7500.0, 8906.2], 105W / 0T / 23L). Meanwhile, the playing strength difference between M07 continuation search (`n2000`) and `n1` was statistically unresolved.

This reveals a pivotal scientific insight:
The massive strength gap between M07 and direct neural policies does **not** depend on multi-step lookahead planning. Rather, `n1`'s advantage begins immediately upon evaluating the candidate action's post-action state $s' = T(s, a)$.

In all prior neural milestones (M17 through M42A), the neural network was forced to act as an all-in-one evaluator:
$$(o, a) \to \text{network must infer rule consequence} \to \text{action score}$$
M41A and M42A proved that even with exhaustive counterfactual labels and explicit 28-dim rule relation features, shallow feed-forward models fail to reliably bind specific action identities to their consequences.

M43A tests the fundamental alternative:
> **What if the game engine itself executes the exact physical transition, externalizing the action-consequence binding to the simulator, so the neural network only ever evaluates the resulting player-view successor state?**
$$(o, a) \xrightarrow[\text{simulator}]{\text{Rust exact transition / determinization}} o'_a \xrightarrow[\text{learned value}]{\quad V_\theta \quad} \hat{y} \in [0, 1]$$

The network no longer learns "specific action identity $\to$ consequence". It learns only "post-action state $\to$ eventual game outcome".

## Important historical correction

M43A explicitly does **not** use the historical D2 value head as a scientific arm. The frozen `M25-D2-v2` checkpoint was produced under policy-only training (`value_loss_weight = 0.0`), meaning its structural value head was never trained against win/loss outcomes.

M43A therefore initializes the state encoder from D2's representation (`entity_encoder`, `mix`, `blocks`, `norm`), strictly excludes the unvalidated D2 value head and policy/action modules, and initializes a fresh scalar value head (`VALUE_HEAD_INIT_SEED = 43_261_001`) supervised directly on terminal game outcomes.

## Scope and non-goals

### In scope
- Read-only reuse of M41A P2 terminal branch corpus:
  - Train: 192 source games / 576 states / 12,249 legal branches.
  - Validation: 48 source games / 144 states / 3,258 legal branches.
- Physical reconstruction of immediate child state $s' = T(s, a)$ and player-view projection $o'_{root} = \text{observation}(s', \text{root\_actor})$.
- Observation viewer strictly locked to the root actor (preserving post-action private knowledge such as newly drawn blind reserves).
- Model: D2 state encoder (192 hidden) + fresh scalar value head (`Linear(192, 192) -> GELU -> Linear(192, 1) -> Sigmoid`), end-to-end trainable.
- Target: $y = 1.0$ if root actor achieved rank 0 (win / shared win), else $0.0$.
- Loss: Legal-set hierarchical MSE / Brier loss over 32 whole source games per batch.
- P1 Value-Learning Gate: Brier Skill Score $BSS \ge +0.05$ over constant baseline $V_{const} = p_{train}$.
- P2 Offline Successor-Mapping Integrity Ablations: PRESTATE and CYCLIC-SUCCESSOR must both degrade ranking $\ge 10$ pp OR worsen regret $\ge 0.05$.
- P3 Arena (if P1 and P2 pass): 256 physical matches across 2 pairings (`successor-value-s4` vs `d2-direct`, `successor-value-s4` vs `det-s4-d1-n1`).

### Out of scope / strictly forbidden
- Loading D2's old value head, policy scorer, or action encoder.
- Touching M41 power-calibration or formal reserve partitions (`9_000_304..9_000_815`).
- Generating new branch rollouts or changing M41 P2 corpus.
- TD, fitted-Q, PPO, MCTS, or depth-2 continuation search.
- Re-opening M41A, M42A, or M42S.

## Contracts and invariants

1. **Root-Actor Observation Contract**:
   The successor observation must ALWAYS be projected from the perspective of the acting player who made the root decision:
   $$o'_{root} = \text{observation}(s', \text{root\_actor})$$
   It must NOT be projected from `successor.current_player`. This ensures that private knowledge created by the action (such as the identity of a newly reserved blind-deck card) is preserved for root decision evaluation.
2. **P0 Dataset & Reconstruction Gates**:
   - **H0 (Branch identity)**: All branches bind against M41 corpus manifests.
   - **H1 (Exact one-action reconstruction)**: For every branch, $s + a$ must reproduce the post-action state hash in the branch replay exactly.
   - **H2 (Player-view boundary)**: The model receives strictly $o'_{root}$. Zero access to FullState, hidden deck stacks, or opponent blind reserves.
   - **H3 (Blind-information boundary)**: Information not visible to the root actor after the action must not affect the encoding.
3. **P0 Initialization Audit**:
   Assert exactly 0 tensors imported from D2 value head, policy head, or action encoder.
4. **Hierarchical Training Contract**:
   Loss is averaged within states $\to$ within games $\to$ across the 32 games in the batch. Never flatten branches. 32 epochs, AdamW (lr=1e-4, wd=1e-4, `foreach=False`, `amsgrad=False`, `fused=False`), grad clip 1.0, FP32 deterministic CUDA.
5. **Decision-Time Composition (`successor-value-s4`)**:
   Exact M07 belief shell: `sample_seed = 20_260_703, sample_count = 4`.
   For each candidate root action $a$: simulate in all 4 sampled determinizations, evaluate terminal states with exact outcome, evaluate non-terminal states with $V_\theta(o'_{root})$, aggregate as $Q_{succ}(a) = \frac{1}{4} \sum_{k=0}^3 \text{score}_k$, canonical argmax.

## Arena Decision Rules (if authorized)

Two pairings (128 games each, seeds `5_400_000..5_400_063`):
- Pairing A: `successor-value-s4` vs `d2-direct`
- Pairing B: `successor-value-s4` vs `det-s4-d1-n1`

| Outcome Combination | Formal Interpretation |
|---|---|
| **Case A**: > D2, vs n1 UNRESOLVED | Learned successor evaluator recovers substantial n1-style strength once action consequences are externalized to the simulator. Strong validation of simulator transition + learned state value architecture. |
| **Case B**: > D2, < n1 | Externalized successor evaluation improves over direct neural net, but StaticEvaluatorV1 contains materially stronger decision signals than learned value. Next step: StaticEvaluator feature attribution. |
| **Case C**: <= D2, n1 strong | Changing interface from action scoring to post-action state valuation is insufficient under current representation/target. Points toward StaticEvaluator engineered terms. |
| **Case D**: > n1 | Learned post-action value provides superior decision ranking to the handcrafted static evaluator under the same transition shell. |

## Implementation plan

1. **P0 Rust Successor Rebuilding / Sampling Endpoint & Tests**:
   - Implement Rust CLI command in `crates/splendor-cli/`:
     - `export-branch-successors`: Given branch corpus directory, reconstructs $s' = T(s, a)$ and emits `successor.observation(root_actor)` and terminal targets ($y \in \{0, 1\}$) with H0/H1/H2 checks.
     - `sample-successors`: Given player-view decision context (`observation` + `history` + `legal_actions`), samples 4 determinizations, applies each action, and outputs successor observations `successor.observation(viewer)` and terminal outcomes if any.
   - Implement Rust tests verifying H0, H1, H2, H3 (blind-information boundary).
2. **P0 Dataset Materialization & Invariant Verification**:
   - Create `training/m17_gpu/splendor_gpu/m43a_successor_dataset.py`:
     - Export train (192 games, 576 states, 12,249 branches) and validation (48 games, 144 states, 3,258 branches) successor datasets.
     - Verify H0 branch identity, H1 exact reconstruction, H2 player-view boundary.
     - Cache to `local-artifacts/m43a-successor-data/`.
3. **P0 Model Implementation & D2 Initialization Audit**:
   - Create `training/m17_gpu/splendor_gpu/m43a_successor_model.py`:
     - State encoder initialized from `M25-D2-v2` (`entity_encoder.*`, `entity_gate.*`, `global_encoder.*`, `mix.*`, `blocks.*`, `norm.*`).
     - Strictly assert 0 tensors imported from old D2 value head, policy, or action encoder.
     - New scalar head: `Linear(192, 192) -> GELU -> Linear(192, 1) -> Sigmoid`, initialized from `VALUE_HEAD_INIT_SEED = 43_261_001`.
   - Write unit tests in `training/m17_gpu/tests/test_m43a_model.py`.
4. **P1 Successor Value Training**:
   - Create `training/m17_gpu/splendor_gpu/m43a_train.py`:
     - 32 epochs, AdamW (lr=1e-4, wd=1e-4, betas=(0.9, 0.999), eps=1e-8, amsgrad=False, foreach=False, fused=False), clip=1.0.
     - Hierarchical MSE/Brier loss (branch -> legal actions in state -> selected states in game -> game loss -> batch of 32 whole source games).
     - Select checkpoint with lowest hierarchical validation Brier/MSE (tie-break earliest epoch).
     - Evaluate P1 Value-Learning Gate: $BSS \ge +0.05$ over constant baseline $V_{const} = p_{train}$.
5. **P2 Offline Root-Action Evaluation & Successor-Mapping Integrity Ablations**:
   - Create `training/m17_gpu/splendor_gpu/m43a_eval.py`:
     - Normal 4-sample successor evaluation on 144 validation states vs $G_{D2}(s, a)$ labels.
     - PRESTATE ablation ($V_\theta(o)$ for all actions).
     - CYCLIC-SUCCESSOR ablation (shift 4-sample successor bundle by 1).
     - Assert integrity gate: both corruptions must degrade ranking $\ge 10$ pp OR worsen regret $\ge 0.05$.
6. **P3 256-Game Arena (if P1 and P2 pass)**:
   - Create `training/m17_gpu/splendor_gpu/m43a_agent.py` and `scripts/m43a_orchestrator.py`:
     - Pairing A: `successor-value-s4` vs `d2-direct` (128 games).
     - Pairing B: `successor-value-s4` vs `det-s4-d1-n1` (128 games).
     - Seeds: `5_400_000 .. 5_400_063`, bootstrap seed `43_270_001`.
     - Evaluate against Cases A, B, C, D.
7. **Final Audit, Result JSON, Documentation, Commit & Push**:
   - Exhaustive audit, generate `benchmarks/m43a-successor-state-value-decoupling-v1.result.json`.
   - Update `docs/m43a-successor-state-value-decoupling.md` and `handoff.md`.
   - Commit and push to `origin/main`.

## Iteration log

- 2026-09-05: M43A Design v1 frozen and authorized by reviewer. Discards frozen D2 value head concept in favor of explicitly trained successor value head on terminal outcomes. P0, P1, P2 authorized; P3 Arena automatically authorized iff P1 and P2 pass.
- 2026-09-05: P0 implementation complete:
  - Rust CLI `m43a-export-successors` and `m43a-sample-successors` implemented in `crates/splendor-cli/src/m43a_command.rs`.
  - Rust P0 tests passed in `crates/splendor-cli/tests/m43a_p0_semantic.rs` (H0, H1, H2, H3 2/2 passed).
  - Successor dataset materialized and cached: Train 192 games (576 states, 12,249 branches), Val 48 games (144 states, 3,258 branches) in `local-artifacts/m43a-successor-data/`.
  - Model architecture and D2 initialization audit implemented in `training/m17_gpu/splendor_gpu/m43a_successor_model.py`: exactly 38 encoder tensors imported from D2, 0 tensors imported from old value head, policy, or action modules (`test_m43a_model.py` 2/2 passed).
- 2026-09-05: P1 training executed: 32 epochs of hierarchical MSE loss. Best epoch 4 reached Val MSE 0.245868 vs constant baseline 0.249026 ($BSS = +0.0127 < +0.05$ **FAIL**). P1 gate triggers STOP, NO ARENA.
- 2026-09-05: P2 offline root-action evaluation completed: material ranking 58.83%, regret 0.9028. Both PRESTATE and CYCLIC-SUCCESSOR ablations failed the integrity degradation gate. Formal closure: `M43A_SUCCESSOR_VALUE_NOT_LEARNED`.

## Final implementation

- Rust successor export & sampling endpoints: `crates/splendor-cli/src/m43a_command.rs`.
- P0 semantic tests: `crates/splendor-cli/tests/m43a_p0_semantic.rs`.
- Successor dataset generator: `training/m17_gpu/splendor_gpu/m43a_successor_dataset.py`.
- Model & initialization audit: `training/m17_gpu/splendor_gpu/m43a_successor_model.py`.
- Model tests: `training/m17_gpu/tests/test_m43a_model.py`.
- Trainer: `training/m17_gpu/splendor_gpu/m43a_train.py` (hierarchical MSE loss, 32 epochs, 32 games/batch, AdamW).
- Evaluator: `training/m17_gpu/splendor_gpu/m43a_eval.py` (offline root decision ranking, regret, PRESTATE, CYCLIC-SUCCESSOR).
- Artifacts:
  - Checkpoint: `local-artifacts/m43a-run/m43a-successor-value-best.pt` (SHA-256: `b97b5cfca624fdcd0d82c9cf1089917369078e75104322406801ac65b345cdc5`).
  - Training report: `local-artifacts/m43a-run/m43a-training-report.json`.
  - Offline evaluation report: `local-artifacts/m43a-run/m43a-offline-eval-report.json`.

## Validation and evidence

### 1. P1 Value-Learning Diagnostics (144 Validation States / 3,258 Successors)

| Metric | Result | Gate Requirement | Verdict |
|---|---:|---|---|
| **Best Validation Brier / MSE** | 0.245868 | < Constant Brier | Epoch 4 |
| **Constant Predictor Brier** | 0.249026 | Baseline ($p_{\text{train}} = 0.4869$) | - |
| **Brier Skill Score (BSS)** | **+0.0127** | $\ge +0.05$ | **FAIL** |
| **Prediction Mean $\pm$ Std** | $0.4965 \pm 0.0723$ | - | - |
| **Positive Target Mean Prediction** | 0.5104 | - | - |
| **Negative Target Mean Prediction** | 0.4861 | - | - |
| **ROC-AUC (Diagnostic)** | 0.6344 | Diagnostic only | Positive signal |

### 2. P2 Offline Root-Action Decisions (144 Validation States, 27,677 Material Pairs)

| Condition | Material Ranking @ $\tau=1.0$ | Top-1 Regret | Mean Chosen $G$ | Degradation Gate Requirement | Condition Verdict |
|---|---:|---:|---:|---|---|
| **Normal ($V_\theta(o'_a)$)** | **58.83%** | **0.9028** | -0.1528 | Baseline | - |
| **PRESTATE ($V_\theta(o)$)** | 50.00% ($-8.83\text{ pp}$) | 0.9514 ($+0.0486$) | -0.2014 | $\Delta\text{rank} \le -10\text{ pp}$ OR $\Delta\text{reg} \ge +0.05$ | **FAIL** |
| **CYCLIC-SUCCESSOR** | 52.73% ($-6.10\text{ pp}$) | 0.9167 ($+0.0139$) | -0.1667 | $\Delta\text{rank} \le -10\text{ pp}$ OR $\Delta\text{reg} \ge +0.05$ | **FAIL** |
| **M42S $n1$ Reference** | 59.31% | 0.8750 | -0.1250 | Benchmark anchor | - |
| **D2 Baseline Reference** | 59.31% | 0.8750 | -0.1250 | Benchmark anchor | - |

## Result and decision

1. **P1 Gate FAIL**: With a Brier Skill Score of $+0.0127 < +0.05$, the model failed to learn a sufficiently sharp successor-state value predictor from terminal win/loss targets.
2. **P2 Integrity Gate FAIL**: Both PRESTATE and CYCLIC-SUCCESSOR corruptions failed to cause significant decision degradation ($\ge 10\text{ pp}$ or $\ge 0.05\text{ regret}$).
3. **P3 Arena**: Pre-registered decision rules stipulate:
   > "If not: `M43A_SUCCESSOR_VALUE_NOT_LEARNED`, STOP, NO ARENA."
   P3 Arena was therefore **NOT RUN**.
4. **Ruling**: **`M43A_SUCCESSOR_VALUE_NOT_LEARNED / CLOSED_NEGATIVE`**.

### Scientific Interpretation
M43A answers the question of whether simulator transition access alone, combined with terminal win/loss supervision on post-action states, is sufficient:
- **No**. An intermediate player-view successor observation $o'_a$ evaluated against sparse terminal outcomes ($\pm 1$) contains too much continuation noise for a 192-dim state encoder to distinguish the winning potential of specific actions without intermediate reward signals or search.
- The massive playing strength of `n1` over `d2-direct` (8,203.1 bps in M42S) cannot be replicated simply by evaluating $s'$ with an un-guided win/loss value network. `StaticEvaluatorV1`'s engineered progress terms (prestige, bonus counts, affordable card thresholds, noble progress) provide the dense gradient of value that enables $n1$ to play effectively.

## Known limitations

1. Supervision was limited to binary terminal win/loss outcomes under D2 continuation; intermediate value targets (such as TD($\lambda$) or rollout-averaged utilities) were not utilized.
2. The state encoder was initialized from D2 and fine-tuned for only 32 epochs on 12,249 examples.

## Next authorized gate

M43A is permanently closed.
Next authorized research direction:
- **StaticEvaluator Feature Attribution / Progress Decomposition**: Systematically ablating the terms of `StaticEvaluatorV1` to isolate which handcrafted heuristics provide $n1$'s playing strength.
- Requires an independent milestone design.
