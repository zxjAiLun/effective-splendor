//! M49A Transition Collector, Seed Partitions, and Coverage Diagnostics.
//!
//! # Information Boundaries
//!
//! 1. `provenance` (env_seed, behavior_policy, round, step_index) is quarantined metadata;
//!    it NEVER enters feature tensors.
//! 2. `next_observation` is quarantined to the Bellman target computation; it NEVER enters
//!    the input feature vector for $Q(o, a)$.
//! 3. Single source of truth for terminality: `outcome`.
//! 4. Invariant: `outcome == Running` <=> `next_legal_actions.len() > 0`.
//! 5. `I-SEED-01`: Train, Validation, and Canonical seed sets are mathematically disjoint.

use std::collections::{BTreeMap, HashSet};

use serde::{Deserialize, Serialize};
use splendor_agent::{AgentPolicy, DecisionContext, PublicRequestMeta, StableRng};
use splendor_core::{observation_hash, Action, Observation, Phase, PlayerId};
use splendor_learning::{encode_combined_v1, encode_combined_v2, LearningError};

use crate::solo15::{
    MetricDistribution, Solo15Environment, Solo15Outcome, Solo15Summary, SOLO15_CONTRACT_ID_V1,
};

/// 64 frozen Canonical M49S benchmark evaluation seeds.
pub fn canonical_m49s_seeds() -> Vec<u64> {
    (1..=64).map(|i| i * 1000 + 49).collect()
}

/// 256 training seeds for Round 0, 1, 2 iterative data aggregation.
pub fn train_seeds_v1() -> Vec<u64> {
    (1..=256).map(|i| 1_000_000 + i * 1000 + 49).collect()
}

/// 64 validation seeds for hyperparameter tuning, early stopping, and checkpoint selection.
pub fn validation_seeds_v1() -> Vec<u64> {
    (1..=64).map(|i| 2_000_000 + i * 1000 + 49).collect()
}

/// Assert I-SEED-01: Train, Validation, and Canonical seed sets are strictly disjoint.
pub fn assert_seed_partitions_disjoint(train: &[u64], val: &[u64], canonical: &[u64]) {
    let t_set: HashSet<u64> = train.iter().copied().collect();
    let v_set: HashSet<u64> = val.iter().copied().collect();
    let c_set: HashSet<u64> = canonical.iter().copied().collect();

    assert_eq!(t_set.len(), train.len(), "duplicate seeds in training set");
    assert_eq!(v_set.len(), val.len(), "duplicate seeds in validation set");
    assert_eq!(
        c_set.len(),
        canonical.len(),
        "duplicate seeds in canonical set"
    );

    let tv_overlap: Vec<u64> = t_set.intersection(&v_set).copied().collect();
    assert!(
        tv_overlap.is_empty(),
        "I-SEED-01 VIOLATION: Train and Validation sets overlap on {:?}",
        tv_overlap
    );

    let tc_overlap: Vec<u64> = t_set.intersection(&c_set).copied().collect();
    assert!(
        tc_overlap.is_empty(),
        "I-SEED-01 VIOLATION: Train and Canonical sets overlap on {:?}",
        tc_overlap
    );

    let vc_overlap: Vec<u64> = v_set.intersection(&c_set).copied().collect();
    assert!(
        vc_overlap.is_empty(),
        "I-SEED-01 VIOLATION: Validation and Canonical sets overlap on {:?}",
        vc_overlap
    );
}

/// Metadata provenance for auditability; quarantined from model tensors.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransitionProvenance {
    pub env_seed: u64,
    pub behavior_policy: String,
    pub round: u32,
    pub step_index: usize,
}

/// Standardized teacher-free transition record.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TransitionRecord {
    pub contract_id: String,
    pub trajectory_id: String,
    pub provenance: TransitionProvenance,
    pub observation: Observation,
    pub action: Action,
    pub step_cost: f32,
    pub next_observation: Observation,
    pub next_legal_actions: Vec<Action>,
    pub outcome: Solo15Outcome,
    /// Main turns already used when `action` was chosen (public task state).
    pub main_turns: u32,
    /// Turn cap in force for this trajectory (public task state).
    pub max_main_turns: u32,
}

impl TransitionRecord {
    /// Remaining main-turn budget derived from public task state.
    pub fn remaining_main_turns(&self) -> u32 {
        self.max_main_turns.saturating_sub(self.main_turns)
    }
    /// Validates all contract invariants for a recorded transition.
    pub fn validate(&self) -> Result<(), String> {
        if self.contract_id != SOLO15_CONTRACT_ID_V1 {
            return Err(format!(
                "contract_id mismatch: expected {}, got {}",
                SOLO15_CONTRACT_ID_V1, self.contract_id
            ));
        }

        // Cost check: Main actions cost 1.0, ChooseNoble costs 0.0
        if matches!(self.action, Action::ChooseNoble { .. }) {
            if (self.step_cost - 0.0).abs() > 1e-5 {
                return Err(format!(
                    "ChooseNoble must have step_cost 0.0, got {}",
                    self.step_cost
                ));
            }
        } else if (self.step_cost - 1.0).abs() > 1e-5 {
            return Err(format!(
                "Main action must have step_cost 1.0, got {}",
                self.step_cost
            ));
        }

        // Legal actions contract at next state:
        // Running <=> next_legal_actions is non-empty.
        // Terminal <=> next_legal_actions is strictly empty.
        match self.outcome {
            Solo15Outcome::Running => {
                if self.next_legal_actions.is_empty() {
                    return Err(
                        "P2-1 contract violation: Running transition MUST have non-empty next_legal_actions"
                            .to_string(),
                    );
                }
            }
            Solo15Outcome::Reached15 | Solo15Outcome::Stalled | Solo15Outcome::TurnCap => {
                if !self.next_legal_actions.is_empty() {
                    return Err(format!(
                        "P2-1 contract violation: Terminal outcome {:?} MUST have empty next_legal_actions, got {} actions",
                        self.outcome,
                        self.next_legal_actions.len()
                    ));
                }
            }
        }

        Ok(())
    }

    /// Extract the combined 427-dimensional feature vector $\mathbf{x}(o, a)$.
    ///
    /// GUARANTEE: `provenance`, `env_seed`, `trajectory_id`, and `next_observation`
    /// NEVER enter this tensor.
    pub fn extract_input_features(&self) -> Result<Vec<f32>, LearningError> {
        encode_combined_v1(&self.observation, &self.action)
    }

    /// Materialize the transition into complete, canonical 427-dimensional tensors
    /// for direct consumption by the PyTorch trainer.
    ///
    /// Contract:
    /// - `input_features`: 427-d vector for $(o, a)$;
    /// - `next_action_features`: vector of 427-d vectors for each $a' \in \text{next\_legal\_actions}$
    ///   at $o'$; strictly empty if terminal;
    /// - `step_cost`: 1.0 (Main) or 0.0 (ChooseNoble);
    /// - `outcome`: single terminal truth.
    ///
    /// GUARANTEE: raw provenance, environment seed, and trajectory identifiers NEVER
    /// enter this tensor payload.
    pub fn materialize(&self) -> Result<MaterializedTransitionV1, LearningError> {
        self.materialize_v2()
    }

    /// Horizon-aware materialization used by the M49A-II trainer.
    ///
    /// Extends the frozen 427-d contract with one normalized public
    /// remaining-main-turn budget feature (428-d total) so that the finite
    /// cap is visible to the network without leaking any provenance.
    pub fn materialize_v2(&self) -> Result<MaterializedTransitionV1, LearningError> {
        self.validate().map_err(LearningError::InvalidDataset)?;

        let remaining = self.remaining_main_turns();
        let input_features = encode_combined_v2(
            &self.observation,
            &self.action,
            remaining,
            self.max_main_turns,
        )?;
        let next_remaining = remaining.saturating_sub(self.step_cost as u32);
        let mut next_action_features = Vec::with_capacity(self.next_legal_actions.len());
        if self.outcome == Solo15Outcome::Running {
            for next_action in &self.next_legal_actions {
                let next_feat = encode_combined_v2(
                    &self.next_observation,
                    next_action,
                    next_remaining,
                    self.max_main_turns,
                )?;
                next_action_features.push(next_feat);
            }
        }
        Ok(MaterializedTransitionV1 {
            input_features,
            next_action_features,
            step_cost: self.step_cost,
            outcome: self.outcome,
        })
    }
}

/// A fully materialized tensor transition sample ready for offline Bellman Q-training.
///
/// Python trainer directly consumes these tensors without re-implementing 368-d observation,
/// 36-d action, 23-d delta encoding, or game legality engines.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MaterializedTransitionV1 {
    /// Horizon-aware 428-d input feature vector $\mathbf{x}(o, a)$
    /// (427 frozen features + normalized remaining-main-turn budget).
    pub input_features: Vec<f32>,
    /// List of 428-d feature vectors $\mathbf{x}(o', a')$ for each $a' \in \mathcal{A}(o')$.
    /// Strictly empty if `outcome != Solo15Outcome::Running`.
    pub next_action_features: Vec<Vec<f32>>,
    /// Step cost: 1.0 (Main) or 0.0 (ChooseNoble).
    pub step_cost: f32,
    /// Terminal outcome (Running, Reached15, Stalled, TurnCap).
    pub outcome: Solo15Outcome,
}

/// Category-biased exploratory behavior policy.
///
/// Action priority:
/// 1. Buy (BuyMarket, BuyReserved)
/// 2. Reserve (ReserveMarket, ReserveDeck)
/// 3. Take (TakeTokens)
/// 4. ChooseNoble / Pass
///
/// With probability $\varepsilon$, selects uniformly at random from all legal actions.
/// Uses an independent policy RNG stream completely decoupled from the environment.
pub struct CategoryBiasedPolicy {
    pub epsilon: f64,
}

impl CategoryBiasedPolicy {
    pub fn new(epsilon: f64) -> Self {
        Self { epsilon }
    }
}

impl AgentPolicy for CategoryBiasedPolicy {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let legal = context.legal_actions;
        if legal.len() <= 1 {
            return Ok(legal[0]);
        }

        // Epsilon random choice
        let roll_percent = (context.rng.index(10000) as f64) / 10000.0;
        if roll_percent < self.epsilon {
            let idx = context.rng.index(legal.len());
            return Ok(legal[idx]);
        }

        // Priority partitioning
        let buys: Vec<usize> = legal
            .iter()
            .enumerate()
            .filter(|(_, a)| matches!(a, Action::BuyMarket { .. } | Action::BuyReserved { .. }))
            .map(|(i, _)| i)
            .collect();
        if !buys.is_empty() {
            let idx = buys[context.rng.index(buys.len())];
            return Ok(legal[idx]);
        }

        let reserves: Vec<usize> = legal
            .iter()
            .enumerate()
            .filter(|(_, a)| matches!(a, Action::ReserveMarket { .. } | Action::ReserveDeck { .. }))
            .map(|(i, _)| i)
            .collect();
        if !reserves.is_empty() {
            let idx = reserves[context.rng.index(reserves.len())];
            return Ok(legal[idx]);
        }

        let takes: Vec<usize> = legal
            .iter()
            .enumerate()
            .filter(|(_, a)| matches!(a, Action::TakeTokens { .. }))
            .map(|(i, _)| i)
            .collect();
        if !takes.is_empty() {
            let idx = takes[context.rng.index(takes.len())];
            return Ok(legal[idx]);
        }

        let idx = context.rng.index(legal.len());
        Ok(legal[idx])
    }
}

/// Collects an entire trajectory into transition records.
pub fn collect_solo15_trajectory<P: AgentPolicy>(
    env_seed: u64,
    policy: &mut P,
    behavior_name: &str,
    round: u32,
    max_turns: u32,
    policy_rng: &mut StableRng,
) -> Result<(Vec<TransitionRecord>, Solo15Summary), String> {
    let max_main_turns = max_turns;
    let mut env =
        Solo15Environment::with_max_main_turns(env_seed, max_turns).map_err(|e| e.to_string())?;
    let empty_history = Vec::new();
    let trajectory_id = format!("traj_s{env_seed}_r{round}_{behavior_name}");

    let mut transitions = Vec::new();
    let mut step_index = 0;

    while !env.is_terminal() {
        let obs = env.observation();
        let legal = env.legal_actions();
        if legal.is_empty() {
            break;
        }

        let action = match env.phase() {
            Phase::Main | Phase::ChooseNoble => {
                let obs_hash = observation_hash(&obs);
                let ctx = DecisionContext {
                    observation: obs.clone(),
                    visible_history: &empty_history,
                    legal_actions: &legal,
                    meta: PublicRequestMeta {
                        game_id: SOLO15_CONTRACT_ID_V1.to_string(),
                        recipient_seat: PlayerId(0),
                        request_id: step_index as u64,
                        observation_hash: obs_hash,
                    },
                    rng: policy_rng,
                };
                policy
                    .choose_action(ctx)
                    .map_err(|e| format!("policy error: {e}"))?
            }
            Phase::GameOver => break,
        };

        let step = env.step(action).map_err(|e| e.to_string())?;
        let next_obs = env.observation();
        let next_legal = env.legal_actions();

        let record = TransitionRecord {
            contract_id: SOLO15_CONTRACT_ID_V1.to_string(),
            trajectory_id: trajectory_id.clone(),
            provenance: TransitionProvenance {
                env_seed,
                behavior_policy: behavior_name.to_string(),
                round,
                step_index,
            },
            observation: obs,
            action,
            step_cost: step.step_cost as f32,
            next_observation: next_obs,
            next_legal_actions: next_legal,
            outcome: step.outcome,
            main_turns: step.main_turns - step.step_cost,
            max_main_turns,
        };

        record.validate()?;
        transitions.push(record);
        step_index += 1;
    }

    Ok((transitions, env.summary()))
}

/// Comprehensive coverage diagnostic report over a dataset of collected transitions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CoverageDiagnosticReport {
    pub total_trajectories: usize,
    pub total_transitions: usize,
    pub reached_15_count: usize,
    pub stalled_count: usize,
    pub turn_cap_count: usize,
    pub success_rate: f64,
    pub action_kinds: BTreeMap<String, usize>,
    pub vp_buckets: BTreeMap<String, usize>,
    pub main_turns_distribution: Option<MetricDistribution>,
    pub purchased_cards_distribution: MetricDistribution,
    pub legal_actions_distribution: MetricDistribution,
}

impl CoverageDiagnosticReport {
    pub fn build(transitions: &[TransitionRecord], summaries: &[Solo15Summary]) -> Self {
        let total_trajectories = summaries.len();
        let total_transitions = transitions.len();

        let mut reached_15_count = 0;
        let mut stalled_count = 0;
        let mut turn_cap_count = 0;
        let mut successful_main_turns = Vec::new();
        let mut all_purchased = Vec::new();

        for s in summaries {
            match s.outcome {
                Solo15Outcome::Reached15 => {
                    reached_15_count += 1;
                    if let Some(t) = s.main_turns_to_15 {
                        successful_main_turns.push(t as f64);
                    }
                }
                Solo15Outcome::Stalled => stalled_count += 1,
                Solo15Outcome::TurnCap => turn_cap_count += 1,
                Solo15Outcome::Running => {}
            }
            all_purchased.push(s.purchased_count as f64);
        }

        let success_rate = if total_trajectories > 0 {
            reached_15_count as f64 / total_trajectories as f64
        } else {
            0.0
        };

        let mut action_kinds = BTreeMap::new();
        let mut vp_buckets = BTreeMap::new();
        let mut legal_counts = Vec::with_capacity(transitions.len());

        for t in transitions {
            let kind = match t.action {
                Action::TakeTokens { .. } => "TakeTokens",
                Action::BuyMarket { .. } => "BuyMarket",
                Action::BuyReserved { .. } => "BuyReserved",
                Action::ReserveMarket { .. } => "ReserveMarket",
                Action::ReserveDeck { .. } => "ReserveDeck",
                Action::ChooseNoble { .. } => "ChooseNoble",
                Action::Pass => "Pass",
            };
            *action_kinds.entry(kind.to_string()).or_insert(0) += 1;

            let vp = t.observation.public.players[t.observation.viewer.index()].prestige;
            let bucket = match vp {
                0..=2 => "0-2",
                3..=5 => "3-5",
                6..=8 => "6-8",
                9..=11 => "9-11",
                12..=14 => "12-14",
                _ => "15+",
            };
            *vp_buckets.entry(bucket.to_string()).or_insert(0) += 1;

            if !t.next_legal_actions.is_empty() {
                legal_counts.push(t.next_legal_actions.len() as f64);
            }
        }

        Self {
            total_trajectories,
            total_transitions,
            reached_15_count,
            stalled_count,
            turn_cap_count,
            success_rate,
            action_kinds,
            vp_buckets,
            main_turns_distribution: MetricDistribution::from_values(&successful_main_turns),
            purchased_cards_distribution: MetricDistribution::from_values(&all_purchased).unwrap(),
            legal_actions_distribution: MetricDistribution::from_values(&legal_counts)
                .unwrap_or(MetricDistribution {
                    count: 0,
                    mean: 0.0,
                    median: 0.0,
                    p75: 0.0,
                    p90: 0.0,
                    min: 0.0,
                    max: 0.0,
                }),
        }
    }
}
