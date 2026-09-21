# M49A Efficiency Q / Distance-to-15 Feasibility & Target Design

- **Status**: PROPOSED / RECON COMPLETED (owner terminal authorization for design pending)
- **Baseline**: `116525c3ee874ee6fc64e40f96640d0bd90b2327` (M49S accepted/closed)
- **Owner-date**: 2026-09-20; owner authorized M49A Recon + Target/Data Feasibility, directing transition away from imitation/CE to fitted Q / stochastic shortest-path optimization.
- **Scope**:
  1. Reusable representation infrastructure from M25 / M43 / M46 (state encoding, action encoding, action-conditioned delta features).
  2. Teacher-free transition record schema `(o, a, c, o', terminal, outcome)` with zero seed / referee leakage.
  3. Fitted Q / TD Bellman target formulation: $Q(o,a) \approx c(a) + \min_{a'} Q_{\text{target}}(o', a')$.
  4. Multi-source exploration data supply (Random, Progress-biased $\varepsilon$-exploration, and warm-start Heuristic) without cross-entropy or action supervision.
  5. Canonical gate definition: evaluating $a^* = \arg\min_a Q(o, a)$ against M49S 64-seed canonical baseline (29.20 mean turns).
- **Prohibitions**: Zero teacher labels (S3/M07/champion/heuristic), zero CE loss, zero referee successor peeking, zero arena/Elo/3P/4P scope expansion.

## 1. Problem and Root-Cause Analysis

Previous learning milestones failed to produce autonomous planning:
- **M15**: Neural ISMCTS scored 12–52 against reference baselines; search was prior-dominated with a weak value head.
- **M46A / M48A**: Relational successor representation was fitted to M07 / n2000 teacher continuation targets. Even with high diagnostic accuracy on natural states, models failed on counterfactuals and failed holdout evaluation because "n2000 is a continuation target, not ground truth" (M47S finding).
- **M25 (Experiment D2)**: The key breakthrough was that explicitly providing post-action transition features (VP delta, bonus delta, token deltas, distance to 15) made policy learning substantially easier, proving that past models lacked an intrinsic internal model of how actions advance game progress.

**M49A Core Shift**: Replace "Who to imitate" with "What objective to optimize".
In Solo-15 (`solo15_2p_supply_v1`), the objective is the expected number of remaining main turns to reach 15 prestige:
$$Q^*(o, a) = c(a) + \mathbb{E}_{o' \sim P(\cdot \mid o, a)} \left[ V^*(o') \right]$$
$$V^*(o') = \begin{cases} 0 & \text{if } o' \text{ reached 15 prestige} \\ \text{failure penalty} & \text{if } o' \text{ stalled} \\ \min_{a' \in \mathcal{A}(o')} Q^*(o', a') & \text{otherwise} \end{cases}$$

## 2. Reusable Representation Infrastructure

We audited the codebase and identified three primary assets that are directly reusable without teacher dependencies:

### A. State Observation Representation (`crates/splendor-learning/src/representation.rs`)
- `encode_observation_v1(observation: &Observation) -> Vec<f32>` (368 features).
- Fully compliant with `I-SOLO-01`: encodes public bank, market card properties (cost, prestige, bonus), deck counts, nobles, and player 0's private reserved cards.
- Contains **zero** future deck information and **zero** referee state.

### B. Action Representation (`crates/splendor-learning/src/representation.rs`)
- `encode_action_v1(action: &Action) -> Vec<f32>` (36 features).
- One-hot action category (Take, BuyMarket, BuyReserved, ReserveMarket, ReserveDeck, ChooseNoble, Pass), token deltas, tier, market slot, noble index.

### C. Action-Conditioned State Transition Delta (`training/m17_gpu/splendor_gpu/m25_delta_v2.py`)
- `encode_action_delta_v2(observation, action, catalog) -> Vec<f32>` (23 features).
- Computes exact mathematical delta from visible board state:
  `delta_vp, post_vp, dist_15, delta_bonuses (5), delta_tokens (6), post_tokens, card_cost (5), card_prestige, gold_spent, noble_delta`.
- **Zero clairvoyance**: strictly computes player-side deterministic effects (costs paid, bonuses gained, visible noble visits triggered). Does **not** inspect what random card refills the market.

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
    "behavior_policy": "progress_biased_eps_0.15",
    "step_index": 15
  },
  "observation": { ... },
  "action": { ... },
  "step_cost": 1,
  "next_observation": { ... },
  "terminal": false,
  "outcome": "running"
}
```

### Strict Information & Feature Sanitization Rules
1. `provenance` (including `env_seed` and `behavior_policy`) is strictly metadata for dataset tracking and train/val splits; it is **forbidden from entering model tensors**.
2. No `chosen_by_teacher`, `teacher_prob`, `heuristic_score`, or `m07_score` fields exist.
3. `next_observation` represents the state $o'$ **after** environment transition (incorporating the true market refill). It is used **only** as a target computation sample in offline training, never as an input to $Q(o, a)$.

## 4. Bellman Target & Loss Formulation

### A. Step Cost Definition
- `Phase::Main` action: $c(a) = 1.0$
- `Phase::ChooseNoble` action: $c(a) = 0.0$

### B. Target Computation
Given a transition $(o, a, c, o', \text{terminal}, \text{outcome})$:
$$y = \begin{cases}
0.0 & \text{if outcome} == \text{Reached15} \\
c(a) + \min_{a' \in \mathcal{A}(o')} Q_{\text{target}}(o', a') & \text{if outcome} == \text{Running} \\
\text{CAP\_PENALTY} \quad (= 40.0) & \text{if outcome} \in \{\text{Stalled}, \text{TurnCap}\}
\end{cases}$$

### C. Target Network Stability
- Target network $Q_{\text{target}}$ weights updated periodically (or via Polyak averaging $\tau = 0.005$).
- Loss: Smooth L1 / Huber loss:
  $$\mathcal{L}(\theta) = \mathbb{E} \left[ \text{Huber}(Q_\theta(o, a) - y) \right]$$
- No cross-entropy loss, no policy head, no teacher imitation.

## 5. Non-Teacher Exploration & Data Supply

To avoid the "latent teacher trap" (where training only on Heuristic rollouts trains the model to predict Heuristic's remaining turns rather than optimal efficiency), M49A constructs an exploratory data mix:

1. **Heuristic Coverage (Warm-Start)**: ~30% of transitions. Provides states along reachable paths to 15 prestige, but only environmental returns $(o, a, c, o')$ are recorded—never action targets.
2. **Progress-Biased $\varepsilon$-Greedy Exploration**: ~50% of transitions.
   - Evaluates legal actions with a simple heuristic priority (Buy > Reserve > Take), but selects randomly with probability $\varepsilon = 0.20$.
   - Introduces diverse and unconventional card combinations that Heuristic never explores.
3. **Uniform Random Exploration**: ~20% of transitions.
   - High-entropy transitions ensuring coverage of awkward bank states, hand limits, and token returns.
4. **Curriculum Seed / State Diversity**:
   - Initial pool: 256 distinct training seeds (completely disjoint from the 64 canonical evaluation seeds).

## 6. Model Architecture: Small Relational / MLP Q-Network

Consistent with the "narrow feasibility first" principle, M49A avoids massive search trees or unmanageable architectures.

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
                       Scalar Predicted Turns Q(o, a)
```

- Parameter count: ~145k parameters (extremely lightweight, fast CPU/GPU inference, low risk of overfitting).
- Evaluation inference: For a given observation $o$ with legal actions $\{a_1, \dots, a_k\}$, batch-forward $[(o, a_1), \dots, (o, a_k)]$ and select:
  $$a^* = \arg\min_{a \in \mathcal{A}(o)} Q(o, a)$$

## 7. Canonical Acceptance Gate for M49A

The model is evaluated using the frozen M49S evaluator:
- **Environment**: `Solo15Environment::with_max_main_turns(seed, 100)` on the 64 canonical evaluation seeds (`seed = i * 1000 + 49`, $i \in 1..=64$).
- **Success Criteria**:
  1. **Success Rate**: 64 / 64 (100.0%) reached prestige >= 15 without stalling.
  2. **Route Efficiency Improvement Gate**:
     $$\text{Mean Main Turns} < 29.20 \quad (\text{Heuristic baseline: } 29.20)$$
     $$\text{P90 Main Turns} \le 32.0 \quad (\text{Heuristic baseline: } 32.0)$$
  3. **Zero Seed/Future Leakage**: Model strictly receives `Observation + legal_actions` (zero seed metadata, zero referee peeking).

## 8. Next Authorized Step

- Review and approve M49A Target/Data Feasibility specification.
- Proceed to implementation of the teacher-free transition collector and PyTorch/Rust fitted Q training pipeline.
