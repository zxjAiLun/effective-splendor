# M49S Solo-15 Research Environment & Efficiency Metric

- **Status**: IMPLEMENTED / VERIFIED local (owner terminal review pending)
- **Baseline**: `b85943beade59207cc53b3f6afb7f6f2fa421b63` (remote `main == origin/main`)
- **Owner-date**: 2026-09-20; owner formally authorized M49S environment and baseline measurement following recon feedback, freezing 4 contract corrections.
- **Scope**: Research-only Solo-15 environment (`solo15_2p_supply_v1`) in `crates/splendor-analysis/src/solo15.rs`, non-clairvoyant observation boundaries, metric accounting (`main_turns` primary, `decision_plies` diagnostic), noble completion invariants, stalled detection, and canonical 64 fixed-seed paired baseline (Heuristic vs Random).
- **Prohibition**: Zero teacher/action labels, zero cross-entropy loss, zero imitation of S3/M07/champion, zero referee deck peeking, zero arena/ruleset mutations.

## Problem and evidence

Across previous learning milestones (M12 through M48), models consistently struggled with strategic route planning:
- M15 Neural ISMCTS lost 12–52 against reference baselines due to weak value prediction and prior-dominated search.
- M25 Experiment D revealed that providing explicit action-conditioned transition features (VP delta, bonus delta, token deltas, distance-to-15) dramatically improved policy learning, proving that prior architectures lacked an intrinsic model of how actions advance game progress.
- M46A / M48A demonstrated that fitting neural networks to champion continuation targets (e.g. n2000, M07) failed because `n2000 is a continuation target, not ground truth` (M47S finding). Optimizing policy cross-entropy against heuristic or M07 decisions produced models that learned superficial search habits or defense artifacts while failing at basic card-efficiency and resource accumulation.

To establish genuine decision-making competence, the learning objective must be uncoupled from teacher imitation. Splendor's fundamental base capability is **card efficiency** (牌效率):
> Under zero opponent interference, from an initial deal, what is the minimum/expected number of own main decisions required to reach prestige >= 15?

This formulation creates a pure **Stochastic Shortest Path (SSP)** Markov Decision Process where the objective function is derived entirely from environment outcomes (actual turns to threshold), requiring zero teacher labels.

## Initial design

M49S establishes the research environment, metric definitions, and baseline distributions prior to any neural training (which begins in M49A).

1. **Environment Contract (`solo15_2p_supply_v1`)**:
   - Uses the official 2-player resource supply: 4 colored tokens per color, 5 gold tokens, 3 nobles, standard 3-tier card decks.
   - Only Player 0 acts; Player 1 is an untouched dummy that holds no tokens, reserves no cards, and takes no turns.
   - Refills markets from private decks upon card purchase or reservation using official engine mechanics.
2. **Turn & Metric Accounting**:
   - `Phase::Main` action: `step_cost = 1` -> increments `main_turns += 1` and `decision_plies += 1`.
   - `Phase::ChooseNoble` action: `step_cost = 0` -> increments `main_turns += 0` and `decision_plies += 1`.
   - Primary metric: `main_turns_to_15` (the real number of turns used).
   - Diagnostic metric: `decision_plies_to_15` (includes noble resolution choices).
3. **Absorbing Stall Detection**:
   - If the only legal action in `Phase::Main` is `Action::Pass`, the state is an absorbing stall in solo mode (no other player exists to change the board). The environment immediately marks `Solo15Outcome::Stalled` rather than looping forced passes.
4. **Information Boundaries**:
   - `observation()` exposes only `PublicState` (with `deck_counts: [u8; 3]`) and Player 0's `PrivatePlayerView`.
   - The underlying `FullState` is strictly private.
   - Zero successor peeking: no `peek_successor(action)` method is provided, preventing clairvoyant route planning.

## Scope and non-goals

- **In Scope**:
  - `crates/splendor-analysis/src/solo15.rs`: `Solo15Environment`, `Solo15Outcome`, `Solo15Step`, `Solo15Summary`, `Solo15CohortReport`.
  - Comprehensive unit tests verifying contract identity, step costs, turn cap censoring, and stalled handling.
  - Canonical paired baseline evaluation over 64 fixed deterministic seeds (`seed = i * 1000 + 49` for `i` in `1..=64`, cap = 100 main turns) for `HeuristicAgentPolicy` and `RandomAgentPolicy`.
- **Non-Goals**:
  - No neural network training (reserved for M49A).
  - No teacher labels, action supervision, or imitation targets.
  - No 3P or 4P supply configurations in this milestone (explicitly 2P supply).
  - No multi-player arena, protocol, or engine rule modifications.
  - No evaluation of S3 or M07 in the canonical baseline (S3 depends on multi-player alternating history and is out-of-distribution in solo mode).

## Contracts and invariants

- **Contract ID**: `solo15_2p_supply_v1`
- **Default Cap**: `DEFAULT_MAX_MAIN_TURNS = 100`
- **Invariants**:
  - `I-SOLO-01 (Deck Order Privacy)`: `Observation` never leaks card IDs in hidden decks.
  - `I-SOLO-02 (No Successor Peeking)`: Environment provides no public method to evaluate post-action chance outcomes before an action is chosen.
  - `I-SOLO-03 (Noble Resolution Non-Truncation)`: If buying a card reaches prestige >= 15 while entering `Phase::ChooseNoble`, the environment remains `Running` until the noble choice is executed, terminating only when the turn is fully resolved.
  - `I-SOLO-04 (Zero Fake History)`: Evaluation runners provide `visible_history = &[]` to agents, never synthesizing fraudulent multi-player transcripts.

## Implementation plan

1. Implement `crates/splendor-analysis/src/solo15.rs` implementing `Solo15Environment` and cohort evaluation tools.
2. Re-export module and key types in `crates/splendor-analysis/src/lib.rs`.
3. Add comprehensive tests in `crates/splendor-analysis/tests/solo15_tests.rs`.
4. Run the canonical 64 fixed-seed paired baseline.
5. Record results in tracked milestone documentation and handoff snapshot.

## Iteration log

- **2026-09-20 (Recon Phase)**: Initial feasibility test on 20 seeds verified that `FullState` mechanics (bank conservation, market refills, noble grants, hand limits) work under solo P0 loops. Heuristic reached 15 prestige on 20/20 seeds with mean 29.2 decisions, but bought ~20.5 cards per game. S3 rollout agent exhibited out-of-distribution failure due to expectation of `GameStarted` and alternating player history.
- **2026-09-20 (Owner Guidance & 4 Contract Corrections)**:
  1. *Private state & no synthetic history*: Wrapped `FullState` as strictly private; disallowed faking alternating history for competitive agents.
  2. *Metric correction*: Changed primary metric from `decision plies` to `main turns` (`step_cost = 1` for Main, `0` for ChooseNoble).
  3. *No successor peeking*: Excluded any `peek_successor` method to prevent clairvoyance during search.
  4. *Baseline discipline*: Dropped S3 from canonical baseline; restricted baseline to `Heuristic` and `Random` on identical 64 seeds.
- **2026-09-20 (Canonical Implementation)**: Implemented `crates/splendor-analysis/src/solo15.rs` and `crates/splendor-analysis/tests/solo15_tests.rs`.

## Final implementation

### Tracked Artifacts

- `crates/splendor-analysis/src/solo15.rs`:
  - `Solo15Environment`: encapsulated solo simulation wrapper.
  - `Solo15Outcome`: `Running`, `Reached15`, `Stalled`, `TurnCap`.
  - `Solo15Step`: per-step record with `step_cost`, `main_turns`, `decision_plies`.
  - `Solo15Summary`: objective terminal summary.
  - `MetricDistribution`: percentile-aware distribution (`mean, median, p75, p90, min, max`).
  - `Solo15CohortReport`: batch evaluator across deterministic seed cohorts.
- `crates/splendor-analysis/src/lib.rs`: exposed `pub mod solo15` and re-exported core types.
- `crates/splendor-analysis/tests/solo15_tests.rs`: contract, censoring, and canonical 64-seed paired baseline tests.

## Validation and evidence

### Automated Test Suite

Executed command:
```bash
cargo test -p splendor-analysis
```
Result: **30 passed; 0 failed** (26 unit tests + 1 frontend fixture test + 3 solo15 tests).

### Canonical 64-Seed Paired Baseline (`solo15_2p_supply_v1`)

Executed command:
```bash
cargo test -p splendor-analysis --test solo15_tests test_solo15_canonical_64_seed_paired_baseline -- --nocapture
```

Cohort: 64 fixed deterministic seeds (`seed = i * 1000 + 49` for `i` in `1..=64`), `max_main_turns = 100`.

#### 1. Heuristic Agent (`heuristic_v1`)

| Metric | Value |
|---|---|
| Total Seeds | 64 |
| Success Count | 64 |
| **Success Rate** | **100.0%** |
| Terminal Distribution | Reached15 = 64, Stalled = 0, TurnCap = 0 |
| **Main Turns (Primary)** | **Mean: 29.20, Median: 29.0, P75: 31.0, P90: 32.0, Min: 25, Max: 35** |
| Decision Plies (Diagnostic) | Mean: 29.48, Median: 29.0, P75: 31.0, P90: 33.0, Min: 25, Max: 36 |
| Purchased Cards | Mean: 20.78, Median: 21.0 |
| Final Prestige | Mean: 16.12, Median: 16.0 |
| Nobles Taken | Mean: 2.25, Median: 2.0 |

#### 2. Random Agent (`random_v1`)

| Metric | Value |
|---|---|
| Total Seeds | 64 |
| Success Count | 0 |
| **Success Rate** | **0.0%** |
| Terminal Distribution | Reached15 = 0, Stalled = 0, TurnCap = 64 |
| **Main Turns (Primary)** | **N/A** (0/64 completed; 100% censored at 100 main turns) |
| Decision Plies (Diagnostic) | N/A (censored at 100 plies) |
| Purchased Cards | Mean: 1.25, Median: 1.0 |
| Final Prestige | Mean: 0.31, Median: 0.0 |
| Nobles Taken | Mean: 0.00, Median: 0.0 |

## Result and decision

- **M49S Verdict**: **IMPLEMENTED / VERIFIED local (owner terminal review pending)**.
- **Key Empirical Takeaways**:
  1. The Heuristic baseline exhibits a remarkably tight distribution on 64 seeds (mean 29.20, min 25, max 35).
  2. However, Heuristic achieves this almost exclusively through low-tier volume: purchasing an average of **20.78 cards** and capturing **2.25 nobles**. It builds discounts rather than executing focused high-tier card rush routes.
  3. Random completely fails to achieve 15 prestige within 100 turns (mean prestige 0.31), demonstrating that random exploration cannot stumble upon threshold victory by chance in 2P Splendor.
  4. The gap between 29 turns (Heuristic card-volume route) and theoretical optimal card rush routes represents the target optimization surface for future neural learners (M49A).

## Known limitations

- Environment currently supports only the 2-player resource supply (`solo15_2p_supply_v1`). 3-player (5 tokens per color, 4 nobles) and 4-player supplies are deferred.
- Single-agent only: opponent dynamics, token starvation, defensive reservation, and competitive race tactics are deliberately omitted and deferred to M50.

## Next authorized gate

- Await owner terminal review of M49S.
- Proposed next milestone: **M49A Efficiency Q / Distance-to-15 Learner** (formulating the teacher-free transition dataset and neural architecture to predict remaining main turns).
