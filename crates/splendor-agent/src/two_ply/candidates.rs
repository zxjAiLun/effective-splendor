//! Candidate action selection and pruning for 2-ply continuation rollout.
//! Uses v0.3.1 heuristic scoring to filter: Top-3 Buys, Top-2 Takes, and at most Top-1 Reserve
//! with strict gating against reserve-bloat.

use crate::heuristic_v02::heuristic_v02_term_scores;
use splendor_core::{Action, Observation, Phase};

pub const MAX_BUY_CANDIDATES: usize = 3;
pub const MAX_TAKE_CANDIDATES: usize = 2;
pub const MAX_RESERVE_CANDIDATES: usize = 1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CandidatePruningResult {
    /// Fast path: take this action directly without running rollouts.
    FastPath(Action),
    /// Non-trivial candidate set requiring 2-ply rollout evaluation.
    EvaluateCandidates(Vec<Action>),
}

/// Select a pruned subset of promising actions across categories.
pub fn select_candidates(obs: &Observation, legal_actions: &[Action]) -> CandidatePruningResult {
    // 1. Fast paths
    if obs.public.phase != Phase::Main || legal_actions.len() <= 1 {
        let best_action = legal_actions.first().copied().unwrap_or(Action::Pass);
        return CandidatePruningResult::FastPath(best_action);
    }

    let scores = heuristic_v02_term_scores(obs, legal_actions);

    // Check if in final triggered round or immediate terminal win exists
    if obs.public.end_game_triggered {
        let best_idx = scores
            .iter()
            .enumerate()
            .max_by_key(|(_, t)| t.total())
            .map(|(i, _)| i)
            .unwrap_or(0);
        return CandidatePruningResult::FastPath(legal_actions[best_idx]);
    }

    for (i, terms) in scores.iter().enumerate() {
        if terms.terminal_lead >= 100_000 {
            return CandidatePruningResult::FastPath(legal_actions[i]);
        }
    }

    // Categorize
    let mut buys: Vec<(Action, i64)> = Vec::new();
    let mut takes: Vec<(Action, i64)> = Vec::new();
    let mut reserves: Vec<(Action, i64)> = Vec::new();

    for (action, terms) in legal_actions.iter().zip(scores.iter()) {
        let score = terms.total();
        match action {
            Action::BuyMarket { .. } | Action::BuyReserved { .. } => {
                buys.push((*action, score));
            }
            Action::TakeTokens { .. } => {
                takes.push((*action, score));
            }
            Action::ReserveMarket { .. } | Action::ReserveDeck { .. } => {
                reserves.push((*action, score));
            }
            _ => {}
        }
    }

    // Sort within each category descending
    buys.sort_by_key(|&(_, score)| std::cmp::Reverse(score));
    takes.sort_by_key(|&(_, score)| std::cmp::Reverse(score));
    reserves.sort_by_key(|&(_, score)| std::cmp::Reverse(score));

    let mut candidates =
        Vec::with_capacity(MAX_BUY_CANDIDATES + MAX_TAKE_CANDIDATES + MAX_RESERVE_CANDIDATES);

    for (a, _) in buys.into_iter().take(MAX_BUY_CANDIDATES) {
        candidates.push(a);
    }
    for (a, _) in takes.into_iter().take(MAX_TAKE_CANDIDATES) {
        candidates.push(a);
    }

    // Reserve gating: only consider reserving if held < 2 cards AND
    // the reserve action is genuinely competitive (ranked in overall Top 3 of all legal actions)
    let my_reserved_count = obs.private.reserved.len();
    if my_reserved_count < 2 {
        let mut all_sorted_scores: Vec<i64> = scores.iter().map(|t| t.total()).collect();
        all_sorted_scores.sort_by_key(|&s| std::cmp::Reverse(s));
        let top3_cutoff = if all_sorted_scores.len() >= 3 {
            all_sorted_scores[2]
        } else {
            i64::MIN
        };

        for (a, score) in reserves.into_iter().take(MAX_RESERVE_CANDIDATES) {
            if score >= top3_cutoff {
                candidates.push(a);
            }
        }
    }

    if candidates.len() <= 1 {
        let best_action = candidates
            .first()
            .copied()
            .or_else(|| legal_actions.first().copied())
            .unwrap_or(Action::Pass);
        CandidatePruningResult::FastPath(best_action)
    } else {
        CandidatePruningResult::EvaluateCandidates(candidates)
    }
}
