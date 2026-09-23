# M49A Efficiency Q / Distance-to-15 Feasibility & Target Design

- **Status**: M49A-I ACCEPTED / CLOSED @ `e67df05424eee9869342e91b93088d334d423939`; M49A-II Repair 1/1a ACCEPTED @ `06babda`; C1 ACCEPTED / CLOSED @ `efa42987979d13c14fd32555c457a31de7f20ca7`; C1a ACCEPTED / CLOSED @ `fd9dfba465effa3223d0fd8d15375c1342abb11c`; C2 Polyak stability control AUTHORIZED / IN PROGRESS (§17). Canonical 64 seeds remain on HOLD. Earlier sections retain the design/iteration history; §17 is the current scope and next-gate authority.
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
  - Unit test `test_python_rust_action_delta_parity_all_action_types` reading shared fixture `m49a_delta_parity_v1.json`, verifying floating-point parity ($< 10^{-5}$) against Python across all 7 action types plus the leftover-noble semantic boundary case.
- `crates/splendor-learning/tests/fixtures/m49a_delta_parity_v1.json`:
  - Shared cross-language contract covering all 7 action types plus a targeted legal semantic boundary fixture (`leftover_noble_qualifies_post_purchase` testing post-purchase noble acquisition when qualified nobles remained from previous turns, without claiming full engine-reachable replay state history).
- `training/m17_gpu/splendor_gpu/m25_delta_v2.py`:
  - Fixed noble qualification semantics to post-purchase matching engine.
  - Python test `training/m17_gpu/tests/test_m49a_delta_parity.py` reading the exact same shared fixture, verifying cross-language contract consistency.
- `crates/splendor-analysis/src/m49a_collector.rs`:
  - `train_seeds_v1()`, `validation_seeds_v1()`, `canonical_m49s_seeds()`.
  - `assert_seed_partitions_disjoint()` implementing invariant `I-SEED-01`.
  - `TransitionRecord` with `outcome` as single truth and strict `next_legal_actions` contract (non-empty on Running, empty on terminal).
  - `extract_input_features()` guaranteed to exclude `provenance`, `env_seed`, `trajectory_id`, and `next_observation`.
  - `MaterializedTransitionV1` (P1-3 tensor bridge): materializes `input_features` (427-d) and `next_action_features` (Vec of 427-d) directly in Rust, calling `self.validate()?` fail-closed before tensor generation to ensure invalid records (e.g. Running with empty next legal actions, terminal with non-empty next actions, or mismatched step costs) can never enter the PyTorch trainer.
  - `CategoryBiasedPolicy` ($\varepsilon = 0.20$).
  - `collect_solo15_trajectory()`: policy directly chooses action in both `Phase::Main` and `Phase::ChooseNoble` (P1-2), verified by end-to-end integration test `test_collector_obeys_policy_choice_in_choose_noble_phase` on seed 1004049 where multi-noble choice is reached and policy selection of `legal[1]` is recorded into the trajectory.
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

- Owner supplied the terminal review accepting **M49A-I Data Foundation @ e67df05**, P0=0/P1=0/P2=0, and authorizing **M49A-II Efficiency-Q Training**.
- Current request is **design analysis only**. No trainer, weights, aggregation run, or candidate canonical evaluation was started in this review. Resolve the objective/representation choices in §10 before implementing the corresponding training contract; no existing acceptance gate is silently changed.

## 10. Parent Design Review — 2026-09-21

### Scope, baseline, and verdict

- Reviewed local `main` / cached `origin/main` at `e67df05424eee9869342e91b93088d334d423939`, initially clean. The owner-supplied cloud acceptance is recorded as such, not represented as a fresh remote/CI verification by this reviewer.
- Read M49A, M49S, related M25 action-coupling and M47S target limitations, and actual representation/collector/environment code. Direct parent review; no delegated review.
- **REVIEWED**: solo main-turn efficiency is a useful autonomous base-skill objective. Infrastructure acceptance does not establish convergence, exact expected-cost semantics, optimality, or transfer to competitive play.
- No production code changed. Mathematical alternatives below are **PROPOSED**, not approved revisions to the frozen 427-d, loss, or terminal contracts.

### A. Why the objective is useful, and what it does not establish

Minimizing turns to 15 correctly charges token collection, reserving, purchases and delayed investments in a common currency. It is preferable to immediate VP-per-card, VP-per-token, or rewards for buying discounts: those can reward the wrong intermediate behavior. The stochastic optimum is non-clairvoyant expected cost, not the hindsight-best route through the actual deck. Real next observations are legitimate training targets, not permission for inference-time referee peeking.

Solo-15 is still an uncontested resource/market regime. It omits denial, disappearing targets, shared noble races, opponent-generated refills, and the real competitive stopping/tie conditions. Therefore its policy/value is a base skill or initialization, not automatically an additive tactical evaluator for M50. No M50 work is authorized here.

No CE/action imitation is used, but Heuristic and category-priority behavior still bias the data distribution. Use the narrower claim **environment-objective learning without action-imitation loss**, not learning without any human prior. Past teacher experiments do not prove imitation is universally incapable; M25's delta ablation supports useful action coupling, not a unique causal explanation of all past failures.

### B. Verified state aliasing at the time limit

`Solo15Environment` maintains `main_turns` privately and ends at 100, while `Observation` and `encode_observation_v1` omit elapsed/remaining main turns. The actual finite-horizon value is `Q(o, h, a)`, not an exact stationary function `Q(o, a)`.

A legal engine probe on training seed **1001049** reached 10 tokens and repeatedly took/returned identical tokens. At main-turn counts **5 and 99**, the entire Observation, chosen action, and all **427 input floats** were equal. The early transition was Running; the late transition was TurnCap with target 101. This is verified state aliasing, not proof that all training rows or all action values are contradictory; it invalidates the claim that this observation alone is a sufficient Markov state for the capped process.

Proposed choices requiring owner agreement:
1. If the cap is part of the optimization task, expose a dedicated public remaining-main-turn budget and include it in current/next features (a versioned representation extension, not use of provenance/seed/step_index as inputs).
2. If the intended quantity is uncapped distance-to-15, regard the cap as truncation rather than intrinsic terminal value; this requires a separate training target/continuation contract and cannot be done by relabeling existing terminal records informally.
3. Retaining both 427-d and terminal cap=100 is an approximate memoryless-control experiment; document it as such instead of claiming exact SSP Bellman consistency.

Separately, `encode_observation_v1` retains only purchased-card **count** (line 102), not purchased-card identities that raw Observation contains. Those identities help infer remaining deck composition in solo mode. Thus a public-information-safe encoder can still be information-lossy for future refill expectations. Treat this as a representation limitation, not hidden-information leakage or an immediate mandate for a larger model.

### C. Huber and failure penalty are not exact guarantees about expected cost

With stochastic sample targets, squared-error regression fits the conditional mean; fixed-threshold Huber generally fits a different robust location. Analytic toy example (not an experiment result): targets 30 with probability 0.9 and 100 with probability 0.1 have mean 37, but delta=1 Huber is minimized at about **30.1111**. Rare costly outcomes can consequently be strongly underweighted. Huber is a defensible stability heuristic, but it cannot by itself justify the exact expected-main-turn interpretation. Proposals: mean-consistent MSE with optimizer gradient controls, or retain Huber with explicit approximation and tail calibration. Neither proposal was implemented.

Also, current accumulated objective is `E[sum(step_cost) + 100 * I(failure)]`, not lexicographic success-then-speed, nor successful-only mean turns. A trajectory that reaches TurnCap=100 has root return **200**, not 101 (101 is the final Main transition target). Each successful realization costs at most 100, including a win exactly on turn 100; nevertheless a stochastic risky policy can beat a safer one in expectation: 98% finishing at 20 and 2% capping at 100 yields 23.6, below deterministic 30. Keep the 64/64 gate as an additional constraint; do not claim finite penalty mathematically guarantees zero failures. This also corrects the older §4 wording `cost < 100`: successful cost can equal 100.

### D. Legal masks and Softplus do not solve extrapolation

The legal set prevents impossible actions from entering the backup. Softplus prevents negative outputs. Neither establishes that a legal but poorly observed action has a plausible value: predicting 0.1 for a true 40-turn action is non-negative and still destructive under argmin. Taking a minimum over many noisy estimates preferentially selects underestimates (the cost-minimization form of maximization bias).

All seven action kinds appearing globally does not establish local action-comparison coverage. Category-biased behavior still buys whenever possible outside its epsilon branch, so cheap-buy versus useful-save/wait comparisons can remain sparse. Uniform random over serialized take/return actions overweights categories with many variants. Audit state-conditional alternatives, chosen-action Q, action counts, repetitions/no-progress runs, and realized rollout costs; do not infer coverage from kind counts alone.

Data-aggregation rounds are not Bellman propagation iterations. Positive-cost, undiscounted bootstrapping from near-zero initialization may need many target updates to propagate 25–40-step successful tails. A frozen replay containing complete successes helps, but neither three data rounds nor a small MLP guarantees convergence. If Q0 loops, bounded training-seed rollout collection is useful evidence/data; requiring Q0 to be successful before collecting its failures can prevent the proposed correction mechanism from operating. If instability actually appears, Double-Q-style selection/evaluation separation or environment-return initialization are hypotheses, not permission to add teacher CE or claim Monte Carlo behavior returns equal optimal Q.

### E. Verified evaluator seam and interpretation of self-improvement

`collect_solo15_trajectory` calls the policy in Main and ChooseNoble. In contrast, legacy `run_solo15_evaluation` still uses `legal[0]` in ChooseNoble (`solo15.rs:356`). A spy policy on training seed **1004049** got **1** noble callback through the collector (Noble 8 recorded) and **0** through the legacy evaluator. M49A-II must evaluate its complete policy through the collector-equivalent path (or a clearly versioned runner) rather than silently replacing noble decisions. Preserve the existing M49S baseline provenance; do not silently recompute/relabel it under a different runner. Under current solo rules, qualified nobles have equal prestige and bonuses never decrease, so many noble choices can legitimately tie in efficiency; this seam is not evidence of a large turn-performance effect. This is an M49A-II integration constraint, not a request to reopen the accepted Repair 2 seam.

Fixed 256 training seeds control the environment set, not memorization: visible initial boards can fingerprint repeated decks without an explicit seed input. More policy RNG streams diversify trajectories but not deck realizations. Keep current train/validation/canonical partition; do not attribute repeated-training-seed gains to generalization. If a later larger test is desired, preregister a new cohort rather than reuse canonical as a development set.

For validation/checkpoint selection, report success/failure before successful-only turns, plus capped/penalized all-game cost with its definition. Predeclare checkpoint and greedy/tie rules. Bellman residual and best-versus-second-best gaps are diagnostics, not policy quality (genuine ties exist). A 38→32→29.6 curve is encouraging, not proof that aggregation caused it: a compute-matched continuation on frozen D0 is a useful bounded control if making that causal claim. Training randomness and selection across checkpoints also limit claims.

The frozen canonical gate remains unchanged and candidate-only-once. 64/64 is observed cohort success, not proof of population success=1; under an iid binomial model the one-sided 95% lower bound is about **95.43%**. Fixed-seed results support the named cohort first. A small positive mean improvement or significant CI also does not establish broad tactical competence or a large practical gain.

### F. Execution evidence and local artifacts

Only two targeted read-only environment/runner probes were run, using training seeds, with the temporary test source copied from and byte-compared to the retained artifact:

```text
cargo test -p splendor-analysis --test m49a_design_probe -- --nocapture
exit 0; 2 passed; 0 failed; test body 0.03s
```

- Probe source: `local-artifacts/m49a-design-review/probe.rs`
  - SHA256 `eeb101ded11aaad1c78c3626f03a49b8073ff007e1eed6fb5a404868087026e6`
- Execution output: `local-artifacts/m49a-design-review/probe.log`
  - SHA256 `dfa5291019410edddf850f2a6ee4717a333cfdcb624bf493e9615c40b25e08eb`
- Temporary `crates/splendor-analysis/tests/m49a_design_probe.rs` removed after execution. No product code modified; no full-suite rerun or CI claim in this review.
- Analytic toy examples above were calculated separately and are not network measurements.
- Historical coverage remains in §8. Correction to stale §8 prose: post-Repair-1 category counts are 1160 / mean 35.97 / ReserveMarket 111 / ReserveDeck 39, as shown in its report. An illustrative 60/35/5 **trajectory** mix at these observed lengths would be approximately **58.30/28.29/13.40 percent transitions**, not 60/35/5 samples. No mixture ratio is newly frozen.

### Next decision

Support the efficiency-first research direction. Before M49A-II implementation, settle finite-horizon representation versus truncation semantics, state whether the learner estimates expected cost or a Huber approximation, and ensure the evaluation runner executes the entire Q policy. Keep the small single-Q baseline, environment-only supervision, and existing held-out gate; observe extrapolation/coverage with bounded iteration rather than promising success or expanding the scope.

## 11. Historical Provisional M49A-II Q0→Q2 Results (2026-09-21)

- **Status**: HISTORICAL PROVISIONAL EXPERIMENT. Evaluated on Validation dev partition prior to Repair 1 / 1a. **Canonical 64 seeds remain UNTOUCHED**.
- **Context**: This initial experiment demonstrated the directional feasibility of iterative Q-aggregation for solo-15 efficiency, but operated under provisional data collection/aggregation scripts (repaired in §12) and a legacy flat-next Python caching pipeline (retired in §13).
- **Horizon-aware Bridge**: Implemented versioned 428-d representation (`encode_combined_v2`), augmenting the frozen 427-d features with the normalized remaining main-turn budget (`remaining_main_turns / max_main_turns`).
- **Trainer Implementation**:
  - Small Efficiency-Q MLP: `Linear(428, 256) -> LayerNorm -> ReLU -> Linear(256, 128) -> ReLU -> Linear(128, 1) -> Softplus` (~143k parameters).
  - Unified Bellman targets: `y = step_cost + V(o')` with $V(o') = 0.0$ (Reached15), $100.0$ (TurnCap/Stalled), $\min_{a'} Q_{\text{target}}(o', a')$ (Running).
  - Provisional Python flat-next tensor caching (historical; replaced by Streaming Rust Target Builder in §13).
- **Evaluation Runner**:
  - `m49a-eval-validation`: Evaluates strictly on the 64 validation seeds (`2_001_049 .. 2_064_049`).
  - Executes the complete Q-policy across both `Phase::Main` and `Phase::ChooseNoble`.

### Progression Across Iterative Self-Improvement Rounds (64 Validation Seeds, Cap=100) (Provisional Run)

| Candidate | Dataset Size | Validation Success Rate | Validation Failures | Median Turns | Min Turns | Mean Turns (Succ) | P90 Turns |
|---|---|---:|---:|---:|---:|---:|---:|
| **Heuristic Baseline** | N/A | **64 / 64 (100.0%)** | 0 | 29.0 | 24 | 29.05 | 31.0 |
| **M49A-II Q0 (Round 0)** | 9,393 transitions | **24 / 64 (37.5%)** | 40 | 31.0 | 28 | 36.46 | 62.0 |
| **M49A-II Q1 (Round 1)** | 23,187 transitions | **43 / 64 (67.2%)** | 21 | 31.0 | 25 | 32.05 | 34.0 |
| **M49A-II Q2 (Round 2)** | 34,364 transitions | **55 / 64 (85.9%)** | **9** | **31.0** | **24** | **34.35** | **39.0** |

### Key Empirical Findings:
1. **Monotonic Success Rate Growth**: Success rate monotonically surged from **37.5% (24/64)** $\to$ **67.2% (43/64)** $\to$ **85.9% (55/64)**. Failures collapsed from 40 $\to$ 21 $\to$ **9**.
2. **Best Route Efficiency Reached Heuristic Limit**: Minimum turns to 15 decreased from **28** $\to$ **25** $\to$ **24**, tying the Heuristic baseline's record best run on the validation cohort.
3. **Robust Median**: Across all three rounds, the median successful trajectory held steadily at **31.0 turns**.
4. **Failure Analysis**: Failures are overwhelmingly driven by token-swapping looping behavior when unvisited actions are optimistically underestimated. Appending self-rollout failure trajectories during Round 1 and Round 2 successfully penalized these looping modes, directly cutting failures by >75%.
5. **Evaluation Discipline Maintained**: The 64 Canonical M49S Benchmark seeds were **never loaded or evaluated** during training, model selection, or round iterations.

## 12. M49A-II Repair 1 / 1a — Pipeline Disjointness, Live Horizon, Fail-Closed Hardening, and Legacy Cache Retirement (2026-09-21)

- **Status**: M49A-II REPAIR 1a IMPLEMENTED / PUSHED FOR OWNER REVIEW. **Canonical 64 remains on HOLD**.
- **Owner Review Context**: Following initial training review of commit `a67d687` and subsequent Repair 1 review, critical collection, weighting, and data pipeline invariants were hardened. The existing provisional Q0 $\to$ Q2 trajectory is retained as **provisional positive evidence**, while the underlying contracts are strictly repaired before running the clean experimental chain.

### Repaired Invariants & Hardening Details:
1. **P1-1: Seed Partition Disjointness & Full Unique Coverage**:
   - `m49a_export_command.rs`: Replaced overlapping `take(count)` iteration with strict non-overlapping slices:
     - `category_biased`: `seeds[0 .. n_cat]` (154 train seeds)
     - `heuristic`: `seeds[n_cat .. n_cat + n_heu]` (90 train seeds)
     - `random`: `seeds[n_cat + n_heu .. n]` (12 train seeds)
   - Added runtime assertions: `seen_seeds.len() == n` (guaranteeing exact 256 unique train seeds and 64 unique validation seeds) and `total_trajectories == n`.
2. **P1-2: Live Remaining Horizon in Iterative Q Data Aggregation**:
   - Implemented `collect_solo15_q_trajectory()` in `m49a_collector.rs`.
   - At each decision step, the network queries `encode_combined_v2(obs, act, remaining, max_turns)` using live `remaining = max_turns.saturating_sub(env.main_turns())`.
   - `Phase::Main` advances `main_turns` by 1; `Phase::ChooseNoble` leaves `main_turns` unchanged (step_cost = 0).
   - Targeted unit test `test_collect_solo15_q_trajectory_updates_live_horizon` asserts that every transition's normalized budget feature (`input_features[427]`) exactly tracks live remaining turns throughout the trajectory.
3. **P1-3: Strict Decoupling of Policy RNG from Environment Seed**:
   - Round 0 export, Round 1 aggregation, Round 2 aggregation, and Validation evaluation now construct `StableRng` exclusively from behavior tags, round ordinals, and trajectory ordinals (e.g. `tag.wrapping_add(ordinal)`), completely eliminating any functional dependency on `env_seed`.
4. **P1 (Repair 1a Block): Fail-Closed Round 1 / Round 2 Trajectory Collection**:
   - `m49a_round1_command.rs` and `m49a_round2_command.rs`: Replaced silent `if let Ok(...)` skipping with fail-closed error handling. Any failure in trajectory collection, transition materialization, JSON serialization, or file write/flush immediately halts execution with a non-zero exit code. Added post-collection assertion: `completed_trajectories == 256` and `seen_seeds.len() == 256`.
5. **P2-1: Production Weight Validator Integration**:
   - `crates/splendor-cli/src/m49a_eval_command.rs`: `load_weights_from_json()` now unconditionally invokes `weights.validate().map_err(...)` immediately upon deserialization, guaranteeing that malformed or non-finite weights fail closed in evaluation and aggregation before inference.
6. **P2-2: Legacy Flat-Next Python Cache Pipeline Retired**:
   - Retired legacy `m49a_prepare_round1_cache.py`, `m49a_merge_binary.py`, `m49a_merge_round2.py`, and multi-round Python flat-next scripts to prevent high-memory object expansion and duplicate data paths.
   - Authorized successor path: Streaming Rust on-demand Bellman target builder.
7. **P2-3: TransitionRecord Horizon Invariant Validation**:
   - `TransitionRecord::validate()` now asserts `max_main_turns > 0` and `main_turns <= max_main_turns`, backed by negative controls.
8. **P2-4: Dynamic Epsilon Provenance**:
   - Behavior policy provenance in `m49a_round1_command.rs` and `m49a_round2_command.rs` dynamically formats the true epsilon (e.g. `q0_eps_0.15`).

### Next Step:
- M49A-II Repair 1 / 1a ACCEPTED / CLOSED @ 06babda.
- Implement streaming on-demand Rust Bellman target builder (§13).
- Execute clean Q0 $\to$ Q1 $\to$ Q2 chain on verified partitions. Canonical 64 seeds remain strictly on HOLD.

## 13. Streaming Rust Bellman Target Builder & Compact Transport Architecture (2026-09-22)

- **Status**: IMPLEMENTED / VERIFIED.
- **Contract & Architecture**:
  - Current-side feature matrix: Emits `current_x.f32` ([N, 428] float32 binary), `step_costs.f32` ([N] float32), and `outcomes.u8` ([N] u8). Consumed directly via `np.fromfile` / memory mapping in Python without large Python object overhead.
  - Compact target-side transitions: `M49ACompactTransitionV1` serializes only terminal outcomes or $(o', \mathcal{A}(o'), r', r_{\text{max}})$ for Running transitions. Quarantined metadata (env_seed, provenance, trajectory_id, referee state, future decks) never enter this representation.
  - On-Demand Target Evaluator: Rust CLI `splendor m49a-build-targets` computes $y = c + V(o')$ per FQI iteration using the latest exported `target_net` weights. Emits `targets.f32` (N * 4 bytes).
  - Validation Gates:
    1. Terminal targets: Main $\to$ Reached15: $1.0$, ChooseNoble $\to$ Reached15: $0.0$, Main $\to$ Stalled/TurnCap: $101.0$.
    2. Running min: Hand-constructed actions match $1.0 + \min_{a'} Q_{\text{target}}(o', a')$.
    3. Horizon awareness: Different remaining budgets on the same state yield different targets.
    4. Fail-closed: Non-finite weights, empty actions on Running, or invalid records fail closed.
    5. Parity: Rust target builder exactly matches PyTorch / formulaic targets ($< 10^{-5}$).
  - Legacy `m49a_prepare_cache.py` removed from repository.
  - **Parallel target computation**: `m49a-build-targets` parses all compact transitions into memory (compact = one next_obs + legal-action list, NOT expanded 428-d features), then computes the independent per-transition min-Q targets across all CPU worker threads via `std::thread::scope`. This is a **compact in-memory + parallel on-demand target builder** (not strict line-by-line streaming), but the memory problem is already solved because compact transitions are orders of magnitude smaller than the expanded per-successor 428-d tensors. Worker-thread panics are fail-closed (join errors set the error flag; no zero-initialized target is silently written). Release build + 20 threads reduced Round-1 target computation (~26k transitions) from single-threaded debug ~700s/iter to ~45s/iter.

## 14. CLEAN Q0 → Q1 → Q2 Chain — Reproduced Self-Improvement on Verified Pipeline (2026-09-22)

- **Status**: IMPLEMENTED / VERIFIED on Validation dev partition (64 seeds `2_001_049 .. 2_064_049`). **Canonical 64 seeds remain UNTOUCHED / HOLD**.
- **Pipeline correctness**: Disjoint verified seed partitions (P1-1), live remaining horizon in aggregation (P1-2), RNG decoupled from env_seed (P1-3), fail-closed collection/validation (P2), streaming Rust on-demand Bellman targets (§13). No teacher/CE/imitation.

### Historical diagnostic: 40×8 versus 4×15 (not single-variable isolation)

The first clean run used the historical default configuration `fqi_iterations = 4, epochs_per_fqi = 15`. Result: clean Q0 only **9.4%** success, Q1 **12.5%** — below the provisional 37.5% → 67.2%. Limited Bellman propagation is a plausible explanation with undiscounted positive step costs and near-zero Softplus initialization, not an isolated root cause. The whole-dataset `Q_med ≈ 4.5` is a diagnostic over heterogeneous states; it cannot be calibrated directly against root rollout length.

The follow-up probe changed the configuration to `fqi_iterations = 40, epochs_per_fqi = 8`. **This is NOT a strict single-variable change** (both the FQI update count and the per-iteration epoch count differed from the historical 4×15 run); it establishes only that the 40×8 configuration substantially outperforms the historical shallow 4×15 configuration:

| Config | Q_med | Q_max | Validation Success | $J_{\text{val}}$ |
|---|---:|---:|---:|---:|
| historical 4×15 | 4.5 | 5.7 | 9.4% (6/64) | 95.66 |
| 40×8 | 13.5 | 24.0 | **32.8% (21/64)** | **78.64** |

With function approximation and shared representation, a single FQI update can influence more than one graph-distance step via generalization, so the “~1 step per update” framing is an intuition, not a theorem. The empirical takeaway is that the 4×15 configuration performed poorly and 40×8 improved it; neither the effect of update count alone nor convergence is established. C1 (§15) subsequently examined fixed D2 and fixed 8 epochs/FQI through 80 updates.

Conclusion: these runs do not isolate optimization effects from data aggregation. A compute-matched frozen-D0 control was not run; gains associated with aggregation are not a causal estimate of aggregation alone.

### Clean Chain Results (all rounds `fqi_iterations = 40`, `epochs_per_fqi = 8`, everything else fixed)

| Candidate | Train Transitions | Round Collection Success | Validation Success | Failures | $J_{\text{val}}$ | Mean (Succ) | Median | Min | P90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Heuristic Baseline** | N/A | N/A | 64/64 (100.0%) | 0 | — | 29.05 | 29.0 | 25 | 31.0 |
| **Clean Q0** (Round 0 only) | 9,491 | 60/35/5 mix | **21/64 (32.8%)** | 43 | **78.64** | 32.86 | 32.0 | 27 | 38.0 |
| **Clean Q1** (+Round 1 @ ε=0.15) | 26,059 | 174/256 reached 15 | **51/64 (79.7%)** | 13 | **49.06** | 35.82 | 32.0 | 25 | 41.0 |
| **Clean Q2** (+Round 2 @ ε=0.10) | 36,674 | 241/256 reached 15 | **55/64 (85.9%)** | **9** | **42.84** | 33.33 | 31.0 | **24** | 35.0 |

### Key Findings:
1. **Self-improvement reproduces on the corrected pipeline**: At the fixed 40×8 configuration, Validation success **32.8% → 79.7% → 85.9%**; failures **43 → 13 → 9**; $J_{\text{val}}$ **78.64 → 49.06 → 42.84**. This does not establish convergence of any round.
2. **Aggregated self-generated data is associated with additional improvement beyond clean Q0**: The largest jump (32.8% → 79.7%) coincides with adding Round 1 data collected by the 40×8 Q0 policy (174/256 successes during collection). Its causal contribution remains unisolated from dataset-size and optimization effects without a compute-matched frozen-D0 control. C1's fixed-D2 curve does not substitute for that control.
3. **Observed minimum turns**: The clean-chain minima improved **27 → 25 → 24**. These unpaired minima are diagnostic, not evidence of superiority over Heuristic.
4. **Endpoint matches provisional**: Clean Q2 (85.9%) reproduces the provisional Q2 endpoint (85.9%), but now on verified-disjoint seeds, live horizon, decoupled RNG, and memory-safe streaming targets — establishing the result is a genuine teacher-free self-improvement signal, not a pipeline artifact.
5. **Evaluation discipline maintained**: The 64 Canonical M49S seeds were never loaded during any training, aggregation, model selection, or diagnostic.

### Residual observations (interpretation corrected in C1a):
- Whole-dataset `Q_med ≈ 14` and `Q_max ≈ 27` mix early, late, near-terminal, and zero-cost ChooseNoble rows. They cannot be directly compared with successful root rollout length (~31) to establish absolute underestimation. Root chosen-action Q versus realized cost, or remaining-turn buckets, would be more appropriate calibration diagnostics; not implemented here.
- There is **no evidence that iter40 is near a Bellman fixed point**. It still has 9 failures. C1 (§15) exposes non-monotonic rollout performance; it does not establish sufficient data coverage or the cause of the remaining failures. Round3 remains unauthorized.

## 15. C1 Fixed-D2 FQI Convergence Probe (2026-09-22)

- **Status**: ACCEPTED / CLOSED by owner @ `efa42987979d13c14fd32555c457a31de7f20ca7`. **Canonical 64 seeds remain UNTOUCHED / HOLD**.
- **Design**: Owner-authorized narrow convergence control. Fixed dataset D2 = 36,674 transitions (NO new trajectories generated). All hyperparameters fixed (network, Huber, lr, batch size, `epochs_per_fqi = 8`, training seed, failure penalty 100). FQI training ran to 80 updates; weights were exported every 10 updates. Exports did not change the training trajectory. Rollout measurements were performed post-training on those eight checkpoints, not used for live early stopping.

| FQI updates | Q_med | Q_max | Val success | Failures | $J_{\text{val}}$ |
|---:|---:|---:|---:|---:|---:|
| 10 | 10.2 | 22.6 | 29.7% (19/64) | 45 | 86.06 |
| 20 | 13.1 | 19.8 | 81.2% (52/64) | 12 | 46.39 |
| 30 | 14.4 | 24.9 | 90.6% (58/64) | 6 | 37.86 |
| 40 | 14.0 | 26.9 | 85.9% (55/64) | 9 | 42.84 |
| 50 | 13.9 | 27.7 | **92.2% (59/64)** | **5** | 40.27 |
| 60 | 13.4 | 27.1 | 87.5% (56/64) | 8 | 44.81 |
| 70 | 12.8 | 25.2 | 82.8% (53/64) | 11 | 52.59 |
| 80 | 12.4 | 24.1 | 67.2% (43/64) | 21 | 60.95 |

### Findings (C1a owner correction; original numeric evidence retained):
1. **Rapid rise → high-band oscillation → late degradation.** More FQI updates do not monotonically resolve the remaining failures on this fixed D2: success falls from 59/64 at iter50 to 43/64 at iter80, while `val_huber` rises in the tail. Rollout success/J_val, not whole-dataset Q-to-root-turn comparisons, support this observation.
2. **Iter50 maximizes success; iter30 minimizes J_val.** Iter50 is the **C1 selected checkpoint under `m49a_validation_select_v1`** (§16), not a metric-independent “best.” Iter30 retains **58/64, J_val=37.859375**, versus iter50 **59/64, J_val=40.265625**. A finite failure penalty and the success-first reliability objective need not rank policies identically.
3. **Current visible concern: optimization / fitted-Q stability.** C1 does not prove that data is sufficient, exclude coverage holes, or isolate hard target replacement, min-selection bias, or any other cause. There is no basis to prioritize Round3 merely from this curve. Periodic checkpoint export only saved weights; C1a supplies a model-selection rule, **not** a stability treatment or online early stopping.
4. **Scope of the result**: 59/64 (92.1875%) is selected on the development validation cohort, **not a generalization estimate or an acceptance-gate pass**. Canonical 64 remains on HOLD. Future authorized stability comparisons must use the same schedule and selection contract on both arms; comparing a hard-target final iterate with a Polyak-selected checkpoint would be confounded.

## 16. C1a Validation Checkpoint Selection Contract

### Authorization, scope, and frozen gates

- **Status**: ACCEPTED / CLOSED by owner @ `fd9dfba465effa3223d0fd8d15375c1342abb11c` (P0=0/P1=0/P2=1 nonblocking training-identity follow-up, addressed in C2 scope). Implementation baseline `efa42987979d13c14fd32555c457a31de7f20ca7`.
- Contract: `m49a_validation_select_v1`. Fixed schedule **[10,20,30,40,50,60,70,80]**; no denser sweep, no online rollout early stopping, no retraining. Selection happens after the fixed training trajectory ends.
- Frozen lexicographic order: **max success_count → min J_val → min successful mean turns → earliest iteration**. This is a model-selection rule, not a convergence-stability fix. The rule is frozen by this owner decision after seeing C1; it is not retroactively described as preregistered before C1 training.
- Expected application to retained C1 measurements: iter50 (59/64) selected over iter30 (58/64), despite iter30's lower J_val. Both points remain in evidence.
- Implementation plan: pure selector over complete validation reports; fixed-schedule CLI; validated metrics and weight hashes; immutable selection report; four-level tie-break and negative-input tests; compare the existing C1 eight checkpoints without changing training or policy semantics.
- Acceptance checks: deterministic choice/order independence; reject missing, duplicate, out-of-schedule or non-finite entries; no successful output on an evaluation/input failure; full report including selected iteration/path/key and the complete evaluated schedule.
- **Not authorized in C1a**: C2/Polyak, Double-Q, Round3, new training data, Canonical evaluation. C2 is next in the owner's roadmap, not executed by this slice.

### Implementation contract and information boundaries

- `crates/splendor-cli/src/m49a_select_command.rs`: pure `select_checkpoint_v1()` validates a complete eight-row schedule and ranks it lexicographically. Empty, partial, duplicate, extra, or unscheduled sets are errors, not partial selections. Rows can arrive in any order; output rows are sorted by iteration.
- CLI input is **exactly one** of:
  - `--reports-json FILE`: consume saved evaluation reports; no rollout, inference, or training. Required envelope: `evaluation_contract`, `checkpoint_schedule`, `validation_seeds`, `max_main_turns`, `evaluated`. Each row contains iteration, weight path/SHA256, success/failure counts, unrounded J_val, and successful mean. Weight files must still be present and match their reported hashes. Relative paths resolve from the invocation cwd. Prior selection fields, if present, are ignored and recomputed.
  - `--checkpoint-dir DIR`: convenience measurement adapter; preflight **all eight** `weights_iterNNN.json` files before any rollout, evaluate them with the shared validation evaluator, then pass their rows to the same selector. It does not enumerate arbitrary directory contents.
- `--schedule`, if provided, must equal `10,20,30,40,50,60,70,80`; omitted means exactly the same schedule. No interval/range/sweep option. Unknown, duplicate, malformed, or missing CLI flags/values fail with usage exit 2. `--out-json` is required; existing reports are never overwritten. Publication uses the existing atomic create-only output helper; input/evaluation/write failures return nonzero without publishing a selection.
- Evaluation identity: `m49a_validation_64_cap100_rng_ordinal_v1`, validation seeds `(1..=64)*1000 + 2_000_049`, cap 100, policy RNG `0x5010_1515_0000_0000 + cohort_ordinal` (not env_seed). `QPolicy` still uses live horizon-aware 428-d features, both Main/ChooseNoble callbacks, and the existing argmin/tie policy. No seed, provenance, future deck, or teacher labels enter network inputs.
- `m49a_eval_command.rs` now supplies a shared `evaluate_weights_on_validation()` measurement function. Invalid weights, non-finite action Q, a nonterminal empty legal set/GameOver phase, or `env.step()` errors fail closed rather than falling back to a nominal failure/first action. SHA256 binds the exact bytes parsed for evaluation, not a later read of the path.
- J_val is frozen as `(sum_successful_main_turns + 101 * failures) / 64`. It is a **reporting score with failure imputed as 101**, not the Bellman accumulated root return (which includes elapsed costs plus failure continuation 100). Successful mean is JSON `null` for zero successes; an all-failure cohort has J_val=101 and selects iter10 on the final tie-break. Counts must total 64, metrics must be finite/in-range and consistent to `1e-10`; rounded table metrics are not valid report inputs. With exact values and equal success/J_val, successful mean is algebraically tied; the tertiary rule is nevertheless implemented explicitly and frozen for comparisons.
- Output includes `selection_contract`, `criterion`, the full evaluation envelope/rows, `selected_iteration`, `selected_weights_path`, `selected_weights_sha256`, and `selection_key`. Report replay checks identities and metric consistency; it is **not** cryptographic proof that the stated rollouts occurred. The fresh measurement below anchors this C1 result.
- P2 cleanup: provided malformed/non-finite/negative `--failure-penalty` is a usage error; omission still defaults to 100. This changes no Bellman objective or C1 training run. The teacher-free `step_cost + V(next)` contract remains unchanged.

### Iteration log and corrections (2026-09-22)

1. Owner froze success-first selection **after observing C1**, resolving the iter30/iter50 metric conflict. This is the reusable rule for future runs, not a retroactive pre-C1 preregistration claim.
2. Initial local selector only measured weights, allowed arbitrary schedules, and treated incomparable floats as ties. Before release it was narrowed to the frozen schedule, gained report replay and fail-closed metric/identity validation, and separated measurement from pure selection. No extra checkpoint was evaluated.
3. Initial P2 negative tests lacked other required CLI inputs, so a generic usage error could mask bad parsing. They were strengthened to use valid weights/transitions/all required flags, assert the exact failure-penalty diagnostic and no output, and verify omitted/explicit/custom finite values produce 101/101/8 targets respectively.
4. The first Python regression launch used a nonexistent Windows executable inside a Linux-shaped `.venv` and failed with ENOENT before any test ran. Re-executed with `C:/Python312/python.exe` (torch 2.6.0+cu124, pytest 9.0.2): all three tests passed.
5. §14/§15 interpretation supersedes the older `efa4298` wording “bottleneck is NOT insufficient data,” “proper/converged FQI,” and “periodic export fixed selection.” Numeric results are unchanged. The historical 40×8 versus 4×15 comparison changed **both** update count and epochs/update; aggregation's causal contribution is unisolated. Whole-dataset Q median is not directly calibrated to root turns. Historical provisional §11 remains provisional, not causal evidence about failures.
6. Kept generated reports under ignored `local-artifacts/`, including the pre-existing untracked result draft moved from `benchmarks/` to `local-artifacts/m49a-c1a/selection_draft_v1.json`. No weights/datasets/reports or local `handoff.md` are published; the tracked contract lives in code/tests and this document.

### Validation and exact evidence

All commands below ran from repository root; **exit 0** unless the explicitly described expected-negative CLI tests. Local logs are under `local-artifacts/m49a-c1a/`.

```bash
cargo test -p splendor-cli --bin splendor m49a_select_command
# 8 passed (selector-unit.log)
cargo test -p splendor-cli --test m49a_selection_cli
# 6 passed (selector-cli.log)
cargo test -p splendor-analysis --test m49a_target_builder_tests
# 5 passed (builder.log)
cargo test -p splendor-analysis --test m49a_collector_tests
# 6 passed (collector.log)
cargo build --release -p splendor-cli --bin splendor
# PASS (release.log)
PYTHONPATH=training/m17_gpu C:/Python312/python.exe -m pytest -q \
  training/m17_gpu/tests/test_m49a_streaming_builder.py \
  training/m17_gpu/tests/test_m49a_forward_parity.py \
  training/m17_gpu/tests/test_m49a_delta_parity.py
# 3 passed (python.log)

target/release/splendor.exe m49a-select-checkpoint \
  --checkpoint-dir local-artifacts/m49a-c1-curve/checkpoints \
  --schedule 10,20,30,40,50,60,70,80 \
  --out-json local-artifacts/m49a-c1a/selection_v1.json
# All eight measurements match the retained historical C1 selection_v1.json.
target/release/splendor.exe m49a-select-checkpoint \
  --reports-json local-artifacts/m49a-c1a/selection_v1.json \
  --out-json local-artifacts/m49a-c1a/selection_replayed.json
# Report-only selection, byte-identical to the fresh measurement output.
```

- **Selector tests**: all four comparator levels, success-versus-J conflict, order-independent choice and serialized output, null mean/all-failure case, missing/duplicate/out-of-schedule records, corrupt/non-finite metrics, cohort/cap/contract/hash errors, missing weights, no partial-schedule rollout, no output overwrite, CLI malformed inputs. Synthetic report tests prove contract behavior, not policy strength.
- **Fresh C1 measurement and replay**: `measure.log` / `replay.log`, both exit 0; exact selected key `success_count=59`, `j_val=40.265625`, `successful_mean_turns=35.11864406779661`, selected iteration **50**.
- **Selected weights**: `local-artifacts/m49a-c1-curve/checkpoints/weights_iter050.json`; SHA256 `cfae5398860a0f02d2c8bccd4e4e638a126b64d83d22ff7ee38635ea3291be0a`.
- **Full eight-row report**: `local-artifacts/m49a-c1a/selection_v1.json`; SHA256 `02851b031f4664882d772e46822e9c2545c82902427e812776a1fdacedafacff`. Replay and retained draft have the same bytes/hash. The historical pre-contract report at `local-artifacts/m49a-c1-curve/selection_v1.json` is preserved, not overwritten.
- **Training-history provenance**: C1 `local-artifacts/m49a-c1-curve/q0_report.json`, 80 history rows; SHA256 `de3dcaa22e1e63f93c33620e4be5a385c0dad3381f8e163a2a6fe0b6865d69d0`. The wrapper's `q0_*` names do not mean this is D0; C1 trained on fixed D2.
- **Input preservation**: before/after SHA256 comparison passed for 18 files: eight D2 train/val transport files, eight C1 checkpoints, C1 model and history. Manifest `local-artifacts/m49a-c1a/inputs-before.json`, SHA256 `8d93bacbf0aedd43788ddaa0b37da0581a18eb3fb7eb46d6808ae7f71b012671`.
- **Repository hygiene**: `git diff --check` exit 0; 11 current contract/artifact references exist; ignore rules verified (`handoff.md`: `.gitignore:12`, `local-artifacts/`: `.gitignore:20`). Scoped `rustfmt --check --edition 2021 --config skip_children=true` passes for the shared evaluator, selector, selector unit tests, and CLI tests. A formatting pass initially produced churn/non-idempotent formatting in the untouched legacy exporter; that churn was removed and the builder diff is only the P2 parser. Final selector/CLI tests and release build were rerun successfully. Local summaries: `hygiene.log`, `verification.json`.
- These are local implementation/regression and validation-selection checks, **not independent review, a new training experiment, or canonical acceptance**. No canonical benchmark test or candidate canonical rollout was run.

### Result, hard-target baseline, limitations, and next gate

**C1a ACCEPTED / CLOSED @ `fd9dfba` by owner; local checks are not independent CI.** The selection contract is frozen by the owner's decision, and its application selects iter50. The model remains imperfect (5 validation failures); no convergence/stability/generalization claim is licensed by selecting it.

Reusable hard-target baseline:

```text
D2 = 36,674 transitions; 428→256→LayerNorm/ReLU→128→ReLU→1→Softplus
Huber; AdamW lr=1e-3, weight_decay=1e-4; batch=256; grad_clip=1.0
training seed=49000001; 8 epochs/FQI; 80 FQI updates
hard target replacement once per FQI iteration
checkpoint schedule=[10,20,30,40,50,60,70,80]
m49a_validation_select_v1 → iter50 → 59/64, J_val=40.265625
```

Future stability controls must retain that schedule/selector on **both** arms. C2 was not executed in C1a; subsequent owner authorization is recorded in §17. Double-Q and Round3 stay deferred/unapproved; no M50. No live validation early stopping, every-iteration rollout, or iter41–59 sweep. **Canonical 64: HOLD / UNTOUCHED.**

## 17. C2 Polyak Target Stability Control

### Problem, authorization, and frozen design

- **Status**: AUTHORIZED / IN PROGRESS. Baseline `fd9dfba465effa3223d0fd8d15375c1342abb11c`; owner closed C1a with P0=0/P1=0/P2=1 and authorized exactly this control.
- **Question**: Does smoothing the Bellman target network reduce the late instability observed in C1? Not merely whether another selected checkpoint exceeds 59/64.
- **Only experimental change**: after each complete FQI iteration (after all 8 epochs), update all target parameters as `target = 0.95 * target + 0.05 * online`. Tau is **0.05**, not a CLI sweep parameter. Initialization still copies online to target exactly, as in C1.
- **Everything else fixed**: D2 (36,674 train transitions; 2,402 offline validation rows), 428→256→LayerNorm/ReLU→128→ReLU→1→Softplus, Huber, AdamW lr=1e-3 / weight_decay=1e-4, batch256, clip1.0, seed49000001, 8 epochs/FQI, exactly 80 FQI updates. No trajectories generated or validation-failure seeds inserted into training.
- **Device control**: retained C1 `q0_model.pt` contains CPU tensors; the baseline wrapper saves the network without moving devices. Use **CPU**, preserving the C1 device/RNG path rather than opportunistically switching to the available GPU.
- **Target versus policy**: target_net generates Bellman labels only. All saved/checkpoint/evaluated candidates are the **online network**, as in C1. Preserve model initialization and training RNG consumption.
- **Evaluation**: training ends before any validation rollout. Evaluate exactly `[10,20,30,40,50,60,70,80]` using the accepted shared evaluator and `m49a_validation_select_v1`. Never run canonical, densify checkpoints, stop from rollout metrics, sweep tau, or extend to 100/120 even if learning is slow. A longer run would require a separately authorized C2b.

### Implementation plan and gates

1. Add a small explicit target-update helper: unchanged hard-copy default plus fixed Polyak-0.05 mode. Test initialization/update arithmetic, no online mutation, once-per-FQI timing, and online (not target) checkpoint serialization through the real training loop using synthetic targets.
2. **Implemented, tests pass**: C1a P2 uses `training_manifest.json` with effective C2 config, exact eight-file D2 SHA256 identity, run ID and all eight online-checkpoint SHA256s. The selector checks the complete checkpoint-name/hash map before rollout and carries optional `training_run_id` into the report. Legacy unbound C1 reports remain readable/replay byte-identically; no historical run is relabeled.
3. Run local Rust/Python regression gates, then **one** fresh C2 run in ignored `local-artifacts/m49a-c2-polyak005/`. Keep existing C1/D2 inputs untouched. Store complete logs, online weights, offline diagnostics, and post-training selection locally.
4. Present both eight-point curves and selected checkpoints. Freeze descriptive comparisons before C2 results: `success80 - success50`, `J80 - J50`; on updates 30–80, success/J range (max−min) and mean absolute adjacent change (five adjacent differences). These describe tail drift/variation, not a post-hoc numeric acceptance threshold. A flat low-performing or slowly rising curve is not by itself proof of successful stabilization.
5. Reconcile this record and local handoff, commit/push the authorized implementation and findings, then return to owner review. No Double-Q, Round3, or M50.

### Iteration log

- Start: verified clean `main` at `fd9dfba`; all 18 retained C1/D2 hashes match C1a's manifest. CPU checkpoint device and D2 row counts verified directly. No C2 training or rollout has run yet.
- Implementation: added explicit `polyak_update_target_net()` and preserved hard replacement as default; once-per-FQI call occurs after the full epoch block. The periodic checkpoint path still serializes the online `net`; tests run the real trainer loop with synthetic targets and assert target recursion, call count, and checkpoint-vs-target identity.
- C1a P2 closure: selection report gained backward-compatible optional `training_run_id`; C2 checkpoint-dir selection parses the training manifest and requires exact equality of all eight checkpoint filename/hash pairs, nonempty training config, and complete, valid SHA256s for the eight D2 data files. Unit/process tests reject mismatch before validation rollout. Legacy C1 selection report replay is byte-identical.
- C2 entrypoint is a dedicated fixed-contract script with tau 0.05 hardcoded (no tau CLI), exact hashes for all eight train/validation D2 transport files, CPU, fixed 80×8 and checkpoint cadence 10; it refuses non-empty output dirs and verifies input hashes did not drift during training. C2 train/evaluation is not yet started.
- Pre-run regressions after source freeze: `cargo test -p splendor-cli --bin splendor m49a_select_command` **10 passed**; `cargo test -p splendor-cli --test m49a_selection_cli` **7 passed**; `cargo test -p splendor-analysis --test m49a_target_builder_tests` **5 passed**; `cargo test -p splendor-analysis --test m49a_collector_tests` **6 passed**; Python Polyak/target-builder/forward/delta regressions **8 passed**. Release build, scoped `rustfmt --check`, and `git diff --check` PASS. Frozen C2 preflight verified all eight exact C1 D2 SHA256s and expected row counts; C1 report-only replay with the updated selector remains byte-identical.
- Ruff was not available in `C:/Python312` (`No module named ruff`); no Ruff pass is claimed.

### Final implementation / validation / result

Implementation is pending final release build + exact D2 hash preflight and the one authorized C2 80-update run. No C2 performance result or acceptance claim yet.
