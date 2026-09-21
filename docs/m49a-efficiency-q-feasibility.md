# M49A Efficiency Q / Distance-to-15 Feasibility & Target Design

- **Status**: PROPOSED / DESIGN REPAIR 1 COMPLETED (owner terminal review pending)
- **Baseline**: `116525c3ee874ee6fc64e40f96640d0bd90b2327` (M49S accepted/closed)
- **Owner-date**: 2026-09-20; owner delivered M49A Design Review (P0=0/P1=3/P2=2), establishing strict mathematical consistency for Bellman targets, non-negative cost bounds, transition schema expansion, eval-split separation, and iterative data aggregation.
- **Scope**:
  1. Reusable representation infrastructure from M25 / M43 / M46 (state encoding 368-d, action encoding 36-d, action-conditioned delta features 23-d -> 427-d total).
  2. Parity requirement: Port M25 23-d delta encoder to canonical Rust implementation in `crates/splendor-learning`.
  3. Teacher-free transition record schema `(o, a, c, o', next_legal_actions, outcome, provenance)` with zero seed / referee leakage.
  4. Unified Bellman target: $y = c(a) + V(o')$, with $V(o') = 0$ for Reached15, $V(o') = 100$ for failure (Main failure $Q = 101$), and $V(o') = \min_{a' \in \mathcal{A}(o')} Q_{\text{target}}(o', a')$ for Running.
  5. Non-negative Q output via Softplus activation to prevent negative cost extrapolation.
  6. Iterative $Q$-policy $\varepsilon$-data aggregation (2–3 rounds) instead of static single-pass offline FQI.
  7. Rigorous 3-way seed split: 256 Train seeds, 64 separate Validation seeds, 64 Canonical M49S benchmark seeds (strictly disjoint).
  8. Two-tier evaluation gate: $<29.20$ feasibility floor vs meaningful paired improvement threshold.
- **Prohibitions**: Zero teacher labels (S3/M07/champion/heuristic), zero CE loss, zero referee successor peeking, zero arena/Elo/3P/4P scope expansion.

## 1. Problem and Root-Cause Analysis

Previous learning milestones failed to produce autonomous route planning:
- **M15**: Neural ISMCTS scored 12–52 against reference baselines; search was prior-dominated with a weak value head.
- **M46A / M48A**: Relational successor representation was fitted to M07 / n2000 teacher continuation targets. Even with high diagnostic accuracy on natural states, models failed on counterfactuals and failed holdout evaluation because "n2000 is a continuation target, not ground truth" (M47S finding).
- **M25 (Experiment D2)**: The key breakthrough was that explicitly providing post-action transition features (VP delta, bonus delta, token deltas, distance to 15) made policy learning substantially easier, proving that past models lacked an intrinsic internal model of how actions advance game progress.

**M49A Core Shift**: Replace "Who to imitate" with "What objective to optimize".
In Solo-15 (`solo15_2p_supply_v1`), the objective is the expected remaining main-turn cost to reach 15 prestige:
$$Q^*(o, a) = c(a) + \mathbb{E}_{o' \sim P(\cdot \mid o, a)} \left[ V^*(o') \right]$$
$$V^*(o') = \begin{cases}
0.0 & \text{if } o' \text{ reached 15 prestige} \\
100.0 & \text{if } o' \in \{\text{Stalled}, \text{TurnCap}\} \\
\min_{a' \in \mathcal{A}(o')} Q^*(o', a') & \text{if } o' \text{ is Running}
\end{cases}$$

## 2. Reusable Representation Infrastructure

We audited the codebase and identified three primary assets that are directly reusable without teacher dependencies:

### A. State Observation Representation (`crates/splendor-learning/src/representation.rs`)
- `encode_observation_v1(observation: &Observation) -> Result<Vec<f32>, LearningError>` (368 features).
- Fully compliant with `I-SOLO-01`: encodes public bank, market card properties (cost, prestige, bonus), deck counts, nobles, and player 0's private reserved cards.
- Contains **zero** future deck information and **zero** referee state.

### B. Action Representation (`crates/splendor-learning/src/representation.rs`)
- `encode_action_v1(action: &Action) -> Result<Vec<f32>, LearningError>` (36 features).
- One-hot action category (Take, BuyMarket, BuyReserved, ReserveMarket, ReserveDeck, ChooseNoble, Pass), token deltas, tier, market slot, noble index.

### C. Action-Conditioned State Transition Delta (`training/m17_gpu/splendor_gpu/m25_delta_v2.py`)
- Python prototype: `encode_action_delta_v2(observation, action, catalog) -> list[float]` (23 features).
- Computes exact mathematical delta from visible board state:
  `delta_vp, post_vp, dist_15, delta_bonuses (5), delta_tokens (6), post_tokens, card_cost (5), card_prestige, gold_spent, noble_delta`.
- **Zero clairvoyance**: strictly computes player-side deterministic effects (costs paid, bonuses gained, visible noble visits triggered). Does **not** inspect what random card refills the market.
- **Canonical Rust Implementation Requirement (P2 Repair)**: To eliminate dual-language contract drift, `encode_action_delta_v2` will be ported to `crates/splendor-learning/src/representation.rs` in Rust, verified against frozen fixtures for all action types (`TakeTokens`, `BuyMarket`, `BuyReserved`, `ReserveMarket`, `ReserveDeck`, `ChooseNoble`), ensuring Python training and Rust inference use identical features.

**Combined Input Vector for $Q(o, a)$**:
$$\mathbf{x}(o, a) = [\text{encode\_obs}(o) \; (368), \; \text{encode\_act}(a) \; (36), \; \text{encode\_delta}(o, a) \; (23)] = 427 \text{ features}$$

## 3. Teacher-Free Transition Record Schema

Every step taken by the research environment generates a standardized transition tuple:

```json
{
  "contract_id": "solo15_2p_supply_v1",
  "trajectory_id": "traj_00042_step_015",
  "provenance": {
    "env_seed": 1049,
    "behavior_policy": "progress_biased_eps_0.20",
    "step_index": 15
  },
  "observation": { ... },
  "action": { ... },
  "step_cost": 1,
  "next_observation": { ... },
  "next_legal_actions": [ ... ],
  "terminal": false,
  "outcome": "running"
}
```

### Strict Information Boundaries & Anti-Extrapolation Schema
1. **`next_legal_actions` Explicitly Recorded (P1-3 Repair)**: The environment records the exact list of legal actions available at $o'$. The offline trainer computes $\min_{a' \in \text{next\_legal\_actions}} Q_{\text{target}}(o', a')$, without having to re-implement a fragile, drift-prone legality engine in Python.
2. **Metadata Quarantine**: `provenance` (including `env_seed` and `behavior_policy`) is strictly metadata for dataset tracking and train/val splits; it is **forbidden from entering model tensors**.
3. **No Teacher Fields**: No `chosen_by_teacher`, `teacher_prob`, `heuristic_score`, or `m07_score` fields exist.
4. **Post-Action Chance Quarantine**: `next_observation` represents the state $o'$ **after** environment transition (incorporating the true market refill). It is used **only** as a sample for target computation in offline training, never as an input to $Q(o, a)$.

## 4. Unified Bellman Target & Mathematical Consistency

### A. Step Cost Definition
- `Phase::Main` action: $c(a) = 1.0$
- `Phase::ChooseNoble` action: $c(a) = 0.0$

### B. Unified Bellman Target Formulation (P1-1 & P1-2 Repair)
To eliminate off-by-one errors and suicide-route preference, we define a single unified formula:
$$y = c(a) + V(o')$$

Where the next-state value $V(o')$ is:
$$V(o') = \begin{cases}
0.0 & \text{if outcome} == \text{Reached15} \\
100.0 & \text{if outcome} \in \{\text{Stalled}, \text{TurnCap}\} \\
\min_{a' \in \text{next\_legal\_actions}} Q_{\text{target}}(o', a') & \text{if outcome} == \text{Running}
\end{cases}$$

#### Mathematical Verification of Targets:
1. **Winning Main Action** (e.g. at 14 VP, `BuyMarket` reaches 15 VP):
   $y = 1.0 + 0.0 = 1.0$ turn. Correct: taking 1 main action to win costs 1 remaining turn.
2. **Winning Noble Action** (e.g. `ChooseNoble` reaches 15 VP):
   $y = 0.0 + 0.0 = 0.0$ turns. Correct: noble choice is zero-cost completion of the current turn.
3. **Multi-Noble Transition** (e.g. at 12 VP, `BuyMarket` triggers multi-noble phase):
   $y = 1.0 + \min_{a' \in \text{nobles}} Q_{\text{target}}(o', a')$. Correct: pays 1 main turn plus subsequent noble resolution cost.
4. **Main Action Causing Terminal Failure** (stalling or reaching turn cap):
   $y = 1.0 + 100.0 = 101.0$ turns. Correct: strictly penalizes failure, guaranteeing that any route reaching 15 VP within the 100-turn cap (cost $< 100$) is strictly preferred over a stalled or capped trajectory.

### C. Loss Formulation
- Target network $Q_{\text{target}}$ weights updated periodically (every $K$ steps or Polyak averaging $\tau = 0.005$).
- Loss: Huber loss (Smooth L1):
  $$\mathcal{L}(\theta) = \mathbb{E} \left[ \text{Huber}(Q_\theta(o, a) - y) \right]$$

## 5. Network Architecture: M49A Small Efficiency-Q MLP

To prevent negative cost extrapolation where unobserved actions collapse into arbitrarily negative predictions (P1-3 Repair), the network terminates in a **Softplus** activation:

```text
               Input [o (368), a (36), delta (23)] (427-d)
                                 │
                            Linear(427, 256)
                                 │
                             LayerNorm
                                 │
                               ReLU
                                 │
                            Linear(256, 128)
                                 │
                               ReLU
                                 │
                             Linear(128, 1)
                                 │
                             Softplus
                                 │
                    Scalar Remaining Turns Q(o, a) >= 0
```

- **Output Guarantee**: $Q(o, a) \ge 0.0$, matching the physical nature of remaining-turn counts.
- **Parameter count**: ~143k parameters (lightweight, fast batch inference, robust against overfitting).
- **Decision Selection**: For observation $o$ with legal actions $\{a_1, \dots, a_k\}$, batch-forward $[(o, a_1), \dots, (o, a_k)]$ and select:
  $$a^* = \arg\min_{a \in \mathcal{A}(o)} Q(o, a)$$

## 6. Data Generation & Iterative Aggregation

### A. Behavior Data Sources (Initial Proposal, Not Frozen)
Data coverage will be audited across diverse behavior sources:
- **Heuristic Coverage (Warm-Start)**: Provides successful trajectories reaching 15 prestige, contributing valid terminal-value samples. (Recorded strictly as environment return, zero action labels).
- **Category-Biased Exploration**: Explores legal actions with heuristic priority (Buy > Reserve > Take) mixed with $\varepsilon = 0.20$ uniform random choice.
- **Uniform Random Exploration**: High-entropy rollouts ensuring coverage of boundary states (token hand limits, empty banks, pass boundaries).
- *Discipline*: Initial mix ratio (e.g. 30/50/20) is an empirical proposal; data collector will generate and inspect a coverage diagnostic report (action distributions, outcomes, VP buckets, turn distributions) before locking the dataset.

### B. Iterative Self-Improvement Pipeline (P1-3 Repair)
To prevent the model from getting trapped in static offline coverage, M49A adopts iterative data aggregation:
1. **Round 0**: Collect multi-source exploratory transitions $\mathcal{D}_0$ on 256 training seeds -> Train initial $Q_0$.
2. **Round 1**: Roll out trajectories using $Q_0$-greedy policy with $\varepsilon = 0.15$ exploration on new training seeds -> Append new transitions $\mathcal{D}_1$ -> Train $Q_1$.
3. **Round 2**: Roll out with $Q_1$-greedy ($\varepsilon = 0.10$) -> Append $\mathcal{D}_2$ -> Train $Q_2$.
This ensures the model encounters and learns true environmental outcomes for the actions it actually prefers, directly resolving offline extrapolation.

## 7. Seed Partitioning & Evaluation Gates

### A. Three-Way Disjoint Seed Partitioning (P2-1 Repair)
To guarantee that the canonical evaluation baseline remains a true blind test and is not corrupted as a development set:
1. **Training Set**: 256 deterministic seeds (`seed = 100000 + i * 1000 + 49`, $i \in 1..=256$).
2. **Validation Set**: 64 separate deterministic seeds (`seed = 200000 + i * 1000 + 49`, $i \in 1..=64$). Used for hyperparameter tuning, learning rate scheduling, target update tuning, and checkpoint selection.
3. **Canonical M49S Benchmark Set**: 64 frozen seeds (`seed = i * 1000 + 49`, $i \in 1..=64$). Evaluated **only once** on the frozen candidate model.

### B. Two-Tier Evaluation Gate (P2-2 Repair)
Evaluated on the 64 canonical M49S seeds (`solo15_2p_supply_v1`, cap = 100):

| Tier | Gate | Criteria |
|---|---|---|
| **Tier 1: Feasibility Floor** | Pass / Fail | - Success Rate: **64 / 64 (100.0%)**<br>- Mean Main Turns: **$< 29.20$** (Heuristic baseline: 29.20)<br>- P90 Main Turns: **$\le 32.0$** (Heuristic baseline: 32.0)<br>- Zero seed leakage and zero referee peeking. |
| **Tier 2: Substantive Improvement** | Promoted / Baseline | - Paired Mean Turn Reduction: **$\ge 0.50$ turns** compared to Heuristic on the identical 64 seeds, OR paired bootstrap 95% upper CI $< 0$. |

A marginal drop of 0.02 turns (e.g. 29.18 vs 29.20) satisfies the feasibility floor to prove Q-learning convergence, but is transparently labeled as a feasibility pass rather than a substantive breakthrough.

## 8. Next Authorized Step

- Await owner review and approval of M49A Design Repair 1.
- Upon authorization:
  1. Implement Rust parity encoder `encode_action_delta_v2` in `crates/splendor-learning`.
  2. Implement teacher-free transition collector in `crates/splendor-analysis`.
  3. Implement PyTorch training pipeline with Softplus Q-network, unified Bellman loss, and iterative aggregation.
