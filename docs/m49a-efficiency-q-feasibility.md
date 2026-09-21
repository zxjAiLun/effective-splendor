# M49A Efficiency Q / Distance-to-15 Feasibility & Target Design

- **Status**: M49A-I DATA FOUNDATION IMPLEMENTED / VERIFIED local (owner terminal review pending)
- **Baseline**: `01b98df15cf467167ca6ee5e4d31a9d74ac091b9` (M49A design accepted/closed)
- **Owner-date**: 2026-09-20; owner accepted M49A Design Repair 2 (`01b98df`), authorized M49A implementation in two slices: M49A-I Data Foundation (Rust parity delta encoder, transition schema, seed partition assertions, coverage report) followed by M49A-II Efficiency-Q Training.
- **Scope**:
  1. Reusable representation infrastructure from M25 / M43 / M46 (state encoding 368-d, action encoding 36-d, action-conditioned delta features 23-d -> 427-d total).
  2. Parity requirement: Port M25 23-d delta encoder to canonical Rust implementation in `crates/splendor-learning`.
  3. Teacher-free transition record schema `(o, a, c, o', next_legal_actions, outcome, provenance)` with zero seed / referee leakage and single-truth `outcome`.
  4. Contract for `next_legal_actions`: non-empty on `Running`, strictly empty `[]` on terminal outcomes.
  5. Unified Bellman target: $y = c(a) + V(o')$, with $V(o') = 0$ for Reached15, $V(o') = 100$ for failure (Main failure $Q = 101$), and $V(o') = \min_{a' \in \text{next\_legal\_actions}} Q_{\text{target}}(o', a')$ for Running.
  6. Non-negative Q output via Softplus activation to prevent negative cost extrapolation.
  7. Iterative $Q$-policy $\varepsilon$-data aggregation (2–3 rounds) on the **same fixed 256 training seeds** (isolating policy improvement from environment shifts).
  8. Rigorous 3-way disjoint seed partition: 256 Train seeds (`1_000_000 + i * 1000 + 49`), 64 separate Validation seeds (`2_000_000 + i * 1000 + 49`), 64 Canonical M49S benchmark seeds (`i * 1000 + 49`), with implementation assertions enforcing disjointness.
  9. Two-tier evaluation gate with exact paired difference sign $\Delta_i = T_{\text{M49A}, i} - T_{\text{Heuristic}, i}$: $<29.20$ feasibility floor vs $\bar{\Delta} \le -0.50$ (or $\text{CI}_{95\%, \text{upper}}(\bar{\Delta}) < 0$) substantive improvement.
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
    "env_seed": 1001049,
    "behavior_policy": "category_biased_eps_0.20",
    "step_index": 15
  },
  "observation": { ... },
  "action": { ... },
  "step_cost": 1,
  "next_observation": { ... },
  "next_legal_actions": [ ... ],
  "outcome": "running"
}
```

### Strict Information Boundaries & Anti-Extrapolation Schema
1. **Single Truth Source for Termination (P2-1 Repair)**:
   The `outcome` field is the sole authoritative indicator of terminal state:
   - `"running"`: game in progress (non-terminal);
   - `"reached_15"`: player achieved prestige >= 15 with noble resolution completed (terminal);
   - `"stalled"`: main phase only permitted Pass (absorbing failure terminal);
   - `"turn_cap"`: main turn limit reached without 15 prestige (terminal).
   The redundant `terminal: bool` field is removed to prevent conflicting dual-truth states.
2. **Contract for `next_legal_actions` (P2-1 Repair)**:
   - If `outcome == "running"`, `next_legal_actions` **MUST be non-empty** (`len() > 0`).
   - If `outcome != "running"` (terminal), `next_legal_actions` **MUST be empty** (`[]`).
   The offline trainer computes $\min_{a' \in \text{next\_legal\_actions}} Q_{\text{target}}(o', a')$ only for running states, without having to re-implement a fragile, drift-prone legality engine in Python.
3. **Metadata Quarantine**: `provenance` (including `env_seed` and `behavior_policy`) is strictly metadata for dataset tracking and train/val splits; it is **forbidden from entering model tensors**.
4. **No Teacher Fields**: No `chosen_by_teacher`, `teacher_prob`, `heuristic_score`, or `m07_score` fields exist.
5. **Post-Action Chance Quarantine**: `next_observation` represents the state $o'$ **after** environment transition (incorporating the true market refill). It is used **only** as a sample for target computation in offline training, never as an input to $Q(o, a)$.

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

### B. Iterative Self-Improvement Pipeline (P1-3 & P1 Repair)
To prevent the model from getting trapped in static offline coverage, M49A adopts iterative data aggregation over the **same fixed 256 training seeds**:
1. **Round 0**: Collect exploratory transitions $\mathcal{D}_0$ on the 256 training seeds using multi-source behavior policies -> Train initial $Q_0$.
2. **Round 1**: Roll out trajectories on the **same 256 training seeds** using $Q_0$-greedy policy with $\varepsilon = 0.15$ exploration -> Append new transitions $\mathcal{D}_1$ -> Train $Q_1$.
3. **Round 2**: Roll out on the **same 256 training seeds** with $Q_1$-greedy ($\varepsilon = 0.10$) -> Append $\mathcal{D}_2$ -> Train $Q_2$.

*Rationale*: Keeping the environment seed universe fixed across rounds ensures that performance differences across $Q_0 \to Q_1 \to Q_2$ isolate true policy self-improvement from stochastic environment distribution shifts.

## 7. Seed Partitioning & Evaluation Gates

### A. Three-Way Disjoint Seed Partitioning (P1 Repair)
To guarantee that the canonical evaluation baseline remains a true blind test and is not corrupted as a development set, seeds are partitioned into three strictly separated non-overlapping ranges:

1. **Canonical M49S Benchmark Set** (Frozen evaluation cohort):
   $$\text{seed} = i \times 1000 + 49 \quad (i \in 1..=64) \implies [1\,049, \; 64\,049]$$
   Evaluated **only once** on the frozen candidate model.
2. **Training Set** (256 seeds):
   $$\text{seed} = 1\,000\,000 + i \times 1000 + 49 \quad (i \in 1..=256) \implies [1\,001\,049, \; 1\,256\,049]$$
   Used for Round 0/1/2 trajectory generation and fitted Q updates.
3. **Validation Set** (64 seeds):
   $$\text{seed} = 2\,000\,000 + i \times 1000 + 49 \quad (i \in 1..=64) \implies [2\,001\,049, \; 2\,064\,049]$$
   Used during training for hyperparameter tuning, learning rate scheduling, target update tuning, and checkpoint selection.

**Formal Verification Invariant (`I-SEED-01`)**:
The data loader and evaluation harness must explicitly assert that all three sets are disjoint:
```rust
assert!(train_seeds.is_disjoint(&val_seeds));
assert!(train_seeds.is_disjoint(&canonical_seeds));
assert!(val_seeds.is_disjoint(&canonical_seeds));
```

### B. Two-Tier Evaluation Gate & Paired Delta Sign Convention (P2-2 Repair)
Evaluated on the 64 canonical M49S seeds (`solo15_2p_supply_v1`, cap = 100).
Define the paired per-seed turn difference as:
$$\Delta_i = T_{\text{M49A}, i} - T_{\text{Heuristic}, i}$$
where $\Delta_i < 0$ signifies that M49A required fewer turns than Heuristic on seed $i$.

| Tier | Gate | Criteria |
|---|---|---|
| **Tier 1: Feasibility Floor** | Pass / Fail | - Success Rate: **64 / 64 (100.0%)**<br>- Mean Main Turns: **$< 29.20$** (Heuristic baseline: 29.20)<br>- P90 Main Turns: **$\le 32.0$** (Heuristic baseline: 32.0)<br>- Zero seed leakage and zero referee peeking. |
| **Tier 2: Substantive Improvement** | Promoted / Baseline | - Paired Mean Turn Reduction: **$\bar{\Delta} \le -0.50$ turns** compared to Heuristic on the identical 64 seeds, OR paired bootstrap 95% upper confidence interval bound $\text{CI}_{95\%, \text{upper}}(\bar{\Delta}) < 0.0$. |

A marginal drop of 0.02 turns (e.g. 29.18 vs 29.20, $\bar{\Delta} = -0.02$) satisfies the feasibility floor to prove Q-learning convergence, but is transparently labeled as a feasibility pass rather than a substantive breakthrough.

## 8. M49A-I Data Foundation Implementation & Evidence

### A. Tracked Rust & Python Code
- `crates/splendor-learning/src/representation.rs`:
  - `encode_action_delta_v2(obs, action)`: exact 23-d deterministic feature vector matching engine post-purchase noble qualification semantics (checks all post-purchase qualified nobles, including leftover nobles from multi-noble choices).
  - `encode_combined_v1(obs, action)`: 427-d combined vector ($368 + 36 + 23$).
  - `ACTION_DELTA_FEATURES_V2 = 23`, `COMBINED_FEATURES_V1 = 427`.
  - Unit test `test_python_rust_action_delta_parity_all_action_types` reading shared fixture `m49a_delta_parity_v1.json`, verifying floating-point parity ($< 10^{-5}$) against Python across all 7 action types plus the leftover-noble qualification case.
- `training/m17_gpu/splendor_gpu/m25_delta_v2.py`:
  - Fixed noble qualification semantics to post-purchase matching engine.
  - Python test `training/m17_gpu/tests/test_m49a_delta_parity.py` reading the exact same shared fixture, verifying cross-language contract consistency.
- `crates/splendor-analysis/src/m49a_collector.rs`:
  - `train_seeds_v1()`, `validation_seeds_v1()`, `canonical_m49s_seeds()`.
  - `assert_seed_partitions_disjoint()` implementing invariant `I-SEED-01`.
  - `TransitionRecord` with `outcome` as single truth and strict `next_legal_actions` contract (non-empty on Running, empty on terminal).
  - `extract_input_features()` guaranteed to exclude `provenance`, `env_seed`, `trajectory_id`, and `next_observation`.
  - `MaterializedTransitionV1` (P1-3 tensor bridge): materializes `input_features` (427-d) and `next_action_features` (Vec of 427-d) directly in Rust, allowing the Python trainer to consume canonical tensors without re-implementing encoders or game legality rules.
  - `CategoryBiasedPolicy` ($\varepsilon = 0.20$).
  - `collect_solo15_trajectory()`: policy directly chooses action in both `Phase::Main` and `Phase::ChooseNoble` (P1-2), verified by test `test_collector_obeys_policy_choice_in_choose_noble_phase`.
  - `CoverageDiagnosticReport`.

### B. Empirical Coverage Diagnostic Report (32 Training Seeds per Source)

```text
==========================================================================
M49A BEHAVIOR COVERAGE DIAGNOSTIC REPORT (32 TRAINING SEEDS PER SOURCE)
==========================================================================

--- [HEURISTIC (Warm-Start)] ---
Trajectories: 32, Transitions: 965, Success Rate: 100.0% (Reached15: 32, Stalled: 0, TurnCap: 0)
Main Turns (successful): Mean: 29.97, Median: 30.0, P75: 32.0, P90: 32.0, Min: 26, Max: 34
Purchased Cards:         Mean: 21.25, Median: 21.0
Action Kinds:            {"BuyMarket": 680, "ChooseNoble": 6, "TakeTokens": 279}
VP Buckets:              {"0-2": 639, "3-5": 133, "6-8": 62, "9-11": 66, "12-14": 64, "15+": 1}
Legal Actions Count:     Mean: 31.0, Median: 29.0, Min: 2, Max: 145

--- [CATEGORY-BIASED EXPLORATION (eps = 0.20)] ---
Trajectories: 32, Transitions: 1160, Success Rate: 100.0% (Reached15: 32, Stalled: 0, TurnCap: 0)
Main Turns (successful): Mean: 35.97, Median: 36.0, P75: 37.0, P90: 41.0, Min: 31, Max: 43
Purchased Cards:         Mean: 20.62, Median: 21.0
Action Kinds:            {"BuyMarket": 582, "BuyReserved": 78, "ChooseNoble": 9, "ReserveDeck": 39, "ReserveMarket": 111, "TakeTokens": 341}
VP Buckets:              {"0-2": 738, "3-5": 173, "6-8": 107, "9-11": 75, "12-14": 66, "15+": 1}
Legal Actions Count:     Mean: 35.2, Median: 16.0, Min: 2, Max: 437

--- [UNIFORM RANDOM EXPLORATION] ---
Trajectories: 32, Transitions: 3200, Success Rate: 0.0% (Reached15: 0, Stalled: 0, TurnCap: 32)
Main Turns (successful): N/A (0 trajectories reached 15)
Purchased Cards:         Mean: 1.38, Median: 1.0
Action Kinds:            {"BuyMarket": 38, "BuyReserved": 6, "ReserveDeck": 15, "ReserveMarket": 87, "TakeTokens": 3054}
VP Buckets:              {"0-2": 3019, "3-5": 181}
Legal Actions Count:     Mean: 181.6, Median: 124.0, Min: 6, Max: 573
==========================================================================
```

#### Key Diagnostic Insights:
1. **Heuristic has zero reserve coverage**: In 965 transitions, Heuristic executed **0** `BuyReserved`, **0** `ReserveMarket`, and **0** `ReserveDeck`. Training on Heuristic alone would blind the Q-network to reserve mechanics.
2. **Category-Biased policy provides complete action coverage**: Reserving cards (`ReserveMarket`: 112, `ReserveDeck`: 38) and buying reserved cards (`BuyReserved`: 78) are richly sampled while still achieving 100% threshold success (mean 35.84 turns).
3. **Random exploration is 95.4% token noise**: In 3,200 transitions, 3,054 are `TakeTokens` in 0-2 VP states, with 0% success. A 20% trajectory budget for Random would produce ~3.3x more transitions than Heuristic while contributing almost zero high-VP or purchase data. The data mix for Round 0 should weight category-biased and heuristic transitions much higher, capping uniform random to a modest noise budget.

## 9. Next Authorized Step

- Await owner review of **M49A-I Data Foundation**.
- Upon acceptance: proceed to **M49A-II Efficiency-Q Training** (PyTorch Q-network, unified Bellman loss, validation early stopping, and Round 0 -> Round 1 -> Round 2 iterative aggregation on the fixed 256 training seeds).
