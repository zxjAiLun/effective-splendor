//! Limited 2-ply continuation simulation agent (Two-Ply Continuation Policy).
//! Performs candidate pruning via v0.3.1 followed by Me -> Opponent -> Me rollout
//! under strict information sets (no oracle peeking at hidden deck cards).

pub mod board;
pub mod candidates;
pub mod evaluator;
pub mod rollout;

#[cfg(test)]
pub mod tests;

use crate::policy::{AgentPolicy, DecisionContext};
use candidates::{select_candidates, CandidatePruningResult};
use rollout::simulate_candidate;
use splendor_core::Action;

pub const TWO_PLY_AGENT_NAME: &str = "splendor-agent-two-ply";
pub const TWO_PLY_AGENT_VERSION: &str = "0.3.2c";

/// Two-ply continuation rollout policy.
#[derive(Default, Clone, Debug)]
pub struct TwoPlyPolicy;

impl TwoPlyPolicy {
    pub fn new() -> Self {
        Self
    }
}

impl AgentPolicy for TwoPlyPolicy {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        match select_candidates(&context.observation, context.legal_actions) {
            CandidatePruningResult::FastPath(action) => Ok(action),
            CandidatePruningResult::EvaluateCandidates(candidates) => {
                let mut best_score = i64::MIN;
                let mut scores = Vec::with_capacity(candidates.len());

                for &cand in &candidates {
                    let score = simulate_candidate(&context.observation, cand);
                    scores.push(score);
                    if score > best_score {
                        best_score = score;
                    }
                }

                let best_indices: Vec<usize> = scores
                    .iter()
                    .enumerate()
                    .filter_map(|(i, &s)| (s == best_score).then_some(i))
                    .collect();

                let chosen_idx = if best_indices.len() == 1 {
                    best_indices[0]
                } else {
                    best_indices[context.rng.index(best_indices.len())]
                };

                Ok(candidates[chosen_idx])
            }
        }
    }
}
