//! M49S: Solo-15 Research Environment and Efficiency Metrics (`solo15_2p_supply_v1`).
//!
//! # Objective & Conceptual Model
//!
//! Solo-15 is a **stochastic shortest path (SSP) problem** over Splendor:
//!
//! > From an initial deal, what is the minimum/expected number of own main
//! > turns needed to reach prestige >= 15 with zero opponent interference?
//!
//! It is **not** an imitation task and has **no teacher**. It measures pure
//! route efficiency ("card efficiency" / 牌效率) under the official 2-player
//! resource supply (4 colored tokens per color, 5 gold, 3 nobles, standard
//! 3-tier card decks).
//!
//! # Key Invariants & Information Boundaries
//!
//! 1. **Zero Future Deck Leakage**:
//!    `Solo15Environment::observation()` returns an [`Observation`] whose only
//!    deck visibility is `deck_counts: [u8; 3]`. Card identities in the hidden
//!    decks remain private inside the engine.
//!
//! 2. **Zero Successor Peeking**:
//!    No `peek_successor(action)` method exists. Agents cannot clone referee
//!    state to inspect what card turns up on the market or what card is blind-drawn
//!    before choosing their action.
//!
//! 3. **Primary Metric is `main_turns_to_15`**:
//!    - `Phase::Main` action: `step_cost = 1` (`main_turns += 1`, `decision_plies += 1`)
//!    - `Phase::ChooseNoble` action: `step_cost = 0` (`main_turns += 0`, `decision_plies += 1`)
//!    Multi-noble resolution is part of the triggering turn and does not penalize
//!    route efficiency.
//!
//! 4. **Terminal & Stalled Semantics**:
//!    - `Reached15`: Reached prestige >= 15 AND noble resolution is completed.
//!    - `TurnCap`: `main_turns >= max_main_turns` without reaching 15 prestige.
//!    - `Stalled`: If the only legal action in `Phase::Main` is `Action::Pass`,
//!      the state is absorbing (no opponent will ever change the board). The
//!      run terminates immediately as stalled rather than looping forced passes.
//!
//! 5. **Private State**:
//!    The underlying [`FullState`] is strictly private.

use serde::{Deserialize, Serialize};
use splendor_agent::{AgentPolicy, DecisionContext, PublicRequestMeta, StableRng};
use splendor_core::{
    observation_hash, Action, EngineError, EngineResult, FullState, GameConfig, Observation, Phase,
    PlayerId, Ruleset,
};

/// The frozen contract identity for this environment.
pub const SOLO15_CONTRACT_ID_V1: &str = "solo15_2p_supply_v1";

/// Default maximum main turns before censoring a solo run.
pub const DEFAULT_MAX_MAIN_TURNS: u32 = 100;

/// Default policy RNG seed for deterministic evaluation, completely independent
/// of any environment shuffle seed to maintain strict information boundaries.
pub const SOLO15_POLICY_RNG_SEED_V1: u64 = 0x5010_1515;

/// The terminal outcome of a Solo-15 run.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Solo15Outcome {
    /// Game is in progress.
    Running,
    /// Player reached prestige >= 15 (and completed any pending noble selection).
    Reached15,
    /// Player cannot take any action other than Pass; in solo mode, no opponent
    /// exists to alter the board, so the state is an absorbing stall.
    Stalled,
    /// Reached maximum main turns without reaching 15 prestige.
    TurnCap,
}

impl Solo15Outcome {
    pub fn is_terminal(&self) -> bool {
        !matches!(self, Self::Running)
    }
}

/// The result of executing one action in the Solo-15 environment.
#[derive(Debug, Clone)]
pub struct Solo15Step {
    pub action: Action,
    /// 1 for Main actions, 0 for ChooseNoble actions.
    pub step_cost: u32,
    /// Number of Main actions taken so far.
    pub main_turns: u32,
    /// Total decision plies taken so far (Main + ChooseNoble).
    pub decision_plies: u32,
    pub prestige: u8,
    pub phase: Phase,
    pub outcome: Solo15Outcome,
}

/// The objective terminal summary of a completed Solo-15 run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Solo15Summary {
    pub seed: u64,
    pub contract_id: String,
    pub outcome: Solo15Outcome,
    pub reached_15: bool,
    /// Primary metric: number of main turns used to reach prestige >= 15.
    /// `None` if the run stalled or was censored by the turn cap.
    pub main_turns_to_15: Option<u32>,
    /// Diagnostic metric: total decision plies including noble selections.
    pub decision_plies_to_15: u32,
    pub final_prestige: u8,
    pub purchased_count: usize,
    pub reserved_count: usize,
    pub nobles_count: usize,
    pub max_main_turns: u32,
}

/// Research-only Solo-15 environment.
pub struct Solo15Environment {
    seed: u64,
    state: FullState,
    main_turns: u32,
    decision_plies: u32,
    max_main_turns: u32,
    outcome: Solo15Outcome,
}

impl Solo15Environment {
    /// Create a new Solo-15 environment with default turn cap (100).
    pub fn new(seed: u64) -> EngineResult<Self> {
        Self::with_max_main_turns(seed, DEFAULT_MAX_MAIN_TURNS)
    }

    /// Create a new Solo-15 environment with an explicit main-turn cap.
    pub fn with_max_main_turns(seed: u64, max_main_turns: u32) -> EngineResult<Self> {
        let config = GameConfig {
            player_count: 2,
            seed,
            ruleset: Ruleset::base_v1(),
        };
        let (state, _) = FullState::new(config)?;

        let mut env = Self {
            seed,
            state,
            main_turns: 0,
            decision_plies: 0,
            max_main_turns,
            outcome: Solo15Outcome::Running,
        };

        // Check if initial state is somehow stalled (e.g. empty deck edge case)
        env.refresh_outcome();
        Ok(env)
    }

    #[inline]
    pub fn seed(&self) -> u64 {
        self.seed
    }

    #[inline]
    pub fn contract_id(&self) -> &'static str {
        SOLO15_CONTRACT_ID_V1
    }

    #[inline]
    pub fn main_turns(&self) -> u32 {
        self.main_turns
    }

    #[inline]
    pub fn decision_plies(&self) -> u32 {
        self.decision_plies
    }

    #[inline]
    pub fn max_main_turns(&self) -> u32 {
        self.max_main_turns
    }

    #[inline]
    pub fn outcome(&self) -> Solo15Outcome {
        self.outcome
    }

    #[inline]
    pub fn is_terminal(&self) -> bool {
        self.outcome.is_terminal()
    }

    #[inline]
    pub fn phase(&self) -> Phase {
        self.state.phase
    }

    /// Public player observation for Player 0.
    ///
    /// Exposes only the public board and Player 0's private view.
    /// Does not expose hidden deck card order.
    pub fn observation(&self) -> Observation {
        self.state.observation(PlayerId(0))
    }

    /// Legal actions for Player 0 in the current phase.
    pub fn legal_actions(&self) -> Vec<Action> {
        if self.is_terminal() {
            return Vec::new();
        }
        self.state.legal_actions()
    }

    /// Execute one action.
    ///
    /// - If `Phase::Main`: `step_cost = 1`, increments `main_turns` and `decision_plies`.
    /// - If `Phase::ChooseNoble`: `step_cost = 0`, increments only `decision_plies`.
    pub fn step(&mut self, action: Action) -> EngineResult<Solo15Step> {
        if self.is_terminal() {
            return Err(EngineError::GameOver);
        }

        let step_cost = match self.state.phase {
            Phase::Main => {
                if matches!(action, Action::ChooseNoble { .. }) {
                    return Err(EngineError::WrongPhase(action));
                }
                1
            }
            Phase::ChooseNoble => {
                if !matches!(action, Action::ChooseNoble { .. }) {
                    return Err(EngineError::WrongPhase(action));
                }
                0
            }
            Phase::GameOver => return Err(EngineError::GameOver),
        };

        // Apply action to underlying engine
        self.state.apply(action)?;

        // Update counters
        self.main_turns += step_cost;
        self.decision_plies += 1;

        // Reset current_player to PlayerId(0) if not in game over
        if self.state.phase != Phase::GameOver {
            self.state.current_player = PlayerId(0);
        }

        // Evaluate terminal conditions
        self.refresh_outcome();

        Ok(Solo15Step {
            action,
            step_cost,
            main_turns: self.main_turns,
            decision_plies: self.decision_plies,
            prestige: self.state.players[0].prestige,
            phase: self.state.phase,
            outcome: self.outcome,
        })
    }

    fn refresh_outcome(&mut self) {
        let p0_prestige = self.state.players[0].prestige;

        // Pending forced turn-resolution (multi-noble choice) must ALWAYS complete first!
        // ChooseNoble has step_cost = 0 and is atomic with the triggering Main turn.
        // Cap evaluation must occur at complete Main Turn boundaries, never mid-turn.
        if self.state.phase == Phase::ChooseNoble {
            self.outcome = Solo15Outcome::Running;
        } else if p0_prestige >= 15 {
            self.outcome = Solo15Outcome::Reached15;
        } else if self.main_turns >= self.max_main_turns {
            self.outcome = Solo15Outcome::TurnCap;
        } else if self.state.phase == Phase::Main {
            let legal = self.state.legal_actions();
            if legal.len() == 1 && legal[0] == Action::Pass {
                self.outcome = Solo15Outcome::Stalled;
            } else {
                self.outcome = Solo15Outcome::Running;
            }
        } else {
            self.outcome = Solo15Outcome::Running;
        }
    }

    /// Generate an objective summary of the run.
    pub fn summary(&self) -> Solo15Summary {
        let reached_15 = self.outcome == Solo15Outcome::Reached15;
        Solo15Summary {
            seed: self.seed,
            contract_id: SOLO15_CONTRACT_ID_V1.to_string(),
            outcome: self.outcome,
            reached_15,
            main_turns_to_15: if reached_15 {
                Some(self.main_turns)
            } else {
                None
            },
            decision_plies_to_15: self.decision_plies,
            final_prestige: self.state.players[0].prestige,
            purchased_count: self.state.players[0].purchased.len(),
            reserved_count: self.state.players[0].reserved.len(),
            nobles_count: self.state.players[0].nobles.len(),
            max_main_turns: self.max_main_turns,
        }
    }
}

/// Evaluate an [`AgentPolicy`] in the Solo-15 environment until completion.
///
/// This runner:
/// - strictly passes `visible_history = &[]` (zero synthetic multi-player history);
/// - automatically handles multi-noble choice by taking the first pending noble
///   if the policy only handles Main actions;
/// - returns a clean [`Solo15Summary`].
pub fn run_solo15_evaluation<P: AgentPolicy>(
    policy: &mut P,
    seed: u64,
    max_main_turns: u32,
    policy_rng: &mut StableRng,
) -> Result<Solo15Summary, String> {
    let mut env =
        Solo15Environment::with_max_main_turns(seed, max_main_turns).map_err(|e| e.to_string())?;
    let empty_history = Vec::new();

    while !env.is_terminal() {
        let action = match env.phase() {
            Phase::Main => {
                let legal = env.legal_actions();
                if legal.is_empty() {
                    break;
                }
                let obs = env.observation();
                let obs_hash = observation_hash(&obs);
                let ctx = DecisionContext {
                    observation: obs,
                    visible_history: &empty_history,
                    legal_actions: &legal,
                    meta: PublicRequestMeta {
                        game_id: SOLO15_CONTRACT_ID_V1.to_string(),
                        recipient_seat: PlayerId(0),
                        request_id: env.decision_plies() as u64,
                        observation_hash: obs_hash,
                    },
                    rng: policy_rng,
                };
                policy
                    .choose_action(ctx)
                    .map_err(|e| format!("policy error: {e}"))?
            }
            Phase::ChooseNoble => {
                let legal = env.legal_actions();
                if legal.is_empty() {
                    break;
                }
                // First legal noble selection
                legal[0]
            }
            Phase::GameOver => break,
        };

        env.step(action).map_err(|e| e.to_string())?;
    }

    Ok(env.summary())
}

/// Distribution statistics for a set of numeric observations.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MetricDistribution {
    pub count: usize,
    pub mean: f64,
    pub median: f64,
    pub p75: f64,
    pub p90: f64,
    pub min: f64,
    pub max: f64,
}

impl MetricDistribution {
    pub fn from_values(values: &[f64]) -> Option<Self> {
        if values.is_empty() {
            return None;
        }
        let count = values.len();
        let sum: f64 = values.iter().sum();
        let mean = sum / count as f64;

        let mut sorted = values.to_vec();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

        let min = sorted[0];
        let max = sorted[count - 1];

        let percentile = |p: f64| -> f64 {
            if count == 1 {
                return sorted[0];
            }
            let idx = (p * (count - 1) as f64).round() as usize;
            sorted[idx.min(count - 1)]
        };

        Some(Self {
            count,
            mean,
            median: percentile(0.50),
            p75: percentile(0.75),
            p90: percentile(0.90),
            min,
            max,
        })
    }
}

/// Aggregate evaluation report over a cohort of seeds.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Solo15CohortReport {
    pub contract_id: String,
    pub agent_id: String,
    pub total_seeds: usize,
    pub success_count: usize,
    pub success_rate: f64,
    pub stalled_count: usize,
    pub turn_cap_count: usize,
    pub max_main_turns: u32,
    /// Distribution over successful runs only.
    pub main_turns: Option<MetricDistribution>,
    /// Distribution over successful runs only.
    pub decision_plies: Option<MetricDistribution>,
    /// Distribution over all runs.
    pub purchased_cards: MetricDistribution,
    /// Distribution over all runs.
    pub final_prestige: MetricDistribution,
    /// Distribution over all runs.
    pub nobles_taken: MetricDistribution,
    pub summaries: Vec<Solo15Summary>,
}

impl Solo15CohortReport {
    pub fn evaluate<P: AgentPolicy>(
        agent_id: &str,
        mut policy_factory: impl FnMut() -> P,
        seeds: &[u64],
        max_main_turns: u32,
    ) -> Result<Self, String> {
        let mut summaries = Vec::with_capacity(seeds.len());
        let mut success_count = 0;
        let mut stalled_count = 0;
        let mut turn_cap_count = 0;

        let mut successful_main_turns = Vec::new();
        let mut successful_plies = Vec::new();
        let mut all_purchased = Vec::new();
        let mut all_prestige = Vec::new();
        let mut all_nobles = Vec::new();

        for &seed in seeds {
            let mut policy = policy_factory();
            let mut rng = StableRng::new(SOLO15_POLICY_RNG_SEED_V1);
            let summary = run_solo15_evaluation(&mut policy, seed, max_main_turns, &mut rng)?;

            match summary.outcome {
                Solo15Outcome::Reached15 => {
                    success_count += 1;
                    if let Some(t) = summary.main_turns_to_15 {
                        successful_main_turns.push(t as f64);
                    }
                    successful_plies.push(summary.decision_plies_to_15 as f64);
                }
                Solo15Outcome::Stalled => stalled_count += 1,
                Solo15Outcome::TurnCap => turn_cap_count += 1,
                Solo15Outcome::Running => {}
            }

            all_purchased.push(summary.purchased_count as f64);
            all_prestige.push(summary.final_prestige as f64);
            all_nobles.push(summary.nobles_count as f64);
            summaries.push(summary);
        }

        let total_seeds = seeds.len();
        let success_rate = if total_seeds > 0 {
            success_count as f64 / total_seeds as f64
        } else {
            0.0
        };

        Ok(Self {
            contract_id: SOLO15_CONTRACT_ID_V1.to_string(),
            agent_id: agent_id.to_string(),
            total_seeds,
            success_count,
            success_rate,
            stalled_count,
            turn_cap_count,
            max_main_turns,
            main_turns: MetricDistribution::from_values(&successful_main_turns),
            decision_plies: MetricDistribution::from_values(&successful_plies),
            purchased_cards: MetricDistribution::from_values(&all_purchased).unwrap(),
            final_prestige: MetricDistribution::from_values(&all_prestige).unwrap(),
            nobles_taken: MetricDistribution::from_values(&all_nobles).unwrap(),
            summaries,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_catalog::{NobleId, Tier};
    use splendor_core::Gems;

    #[test]
    fn test_turn_cap_atomicity_at_noble_resolution_boundary() {
        // Setup cap = 5
        let mut env = Solo15Environment::with_max_main_turns(1049, 5).expect("valid env");

        // Fast-forward to 4 main turns (1 turn remaining before cap)
        env.main_turns = 4;
        env.decision_plies = 4;

        // Stage Player 0: prestige = 12 (pre-noble prestige < 15)
        // Bonuses: 3 White, 3 Blue, 2 Green, 3 Red, 0 Black
        // Tokens: 1 Green
        env.state.players[0].prestige = 12;
        env.state.players[0].bonuses = [3, 3, 2, 3, 0];
        env.state.players[0].tokens = Gems {
            white: 0,
            blue: 0,
            green: 1,
            red: 0,
            black: 0,
            gold: 0,
        };

        // Ensure board has Noble 0 (req 3,3,3,0,0) and Noble 1 (req 0,3,3,3,0)
        env.state.nobles = vec![NobleId(0), NobleId(1)];

        // Card 33 has Green bonus, 0 prestige, cost 2 White + 1 Blue.
        // With Player 0 having 3 White and 3 Blue bonuses, it is completely free to purchase.
        let green_card_id = splendor_catalog::CardId(33);

        // Place this card at Market Tier 1 Slot 0
        env.state.market[Tier::One.index()][0] = Some(green_card_id);

        // Step 1: Execute BuyMarket on the 5th (and final allowed) main turn
        let step = env
            .step(Action::BuyMarket {
                tier: Tier::One,
                slot: 0,
            })
            .expect("buy step");

        // Main action increments main_turns to 5 (= cap)
        assert_eq!(step.step_cost, 1);
        assert_eq!(step.main_turns, 5);
        assert_eq!(step.decision_plies, 5);
        assert_eq!(step.prestige, 12); // pre-noble prestige < 15
        assert_eq!(step.phase, Phase::ChooseNoble);

        // Crucial contract invariant: must remain Running despite main_turns == cap!
        assert_eq!(step.outcome, Solo15Outcome::Running);
        assert_eq!(env.is_terminal(), false);

        // Step 2: Choose noble (step_cost must be 0)
        let choose_step = env
            .step(Action::ChooseNoble { noble: NobleId(0) })
            .expect("choose noble step");
        assert_eq!(choose_step.step_cost, 0);
        assert_eq!(choose_step.main_turns, 5);
        assert_eq!(choose_step.decision_plies, 6);
        assert_eq!(choose_step.prestige, 15); // reached >= 15!
        assert_eq!(choose_step.outcome, Solo15Outcome::Reached15);
        assert_eq!(env.is_terminal(), true);

        let summary = env.summary();
        assert_eq!(summary.outcome, Solo15Outcome::Reached15);
        assert_eq!(summary.reached_15, true);
        assert_eq!(summary.main_turns_to_15, Some(5)); // Exactly equal to cap!
        assert_eq!(summary.decision_plies_to_15, 6);
        assert_eq!(summary.final_prestige, 15);
    }
}
