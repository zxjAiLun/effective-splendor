//! Sequential Elo arithmetic for the Studio League.
//!
//! There is deliberately **one** implementation of the update rule in this
//! workspace: [`splendor_eval::elo_expected_score`] / [`splendor_eval::elo_delta`],
//! which the frozen M16/M19/M22 rating report also uses. This module only shapes
//! that rule into a per-match pair update; it must never grow its own formula.

use crate::error::{Result, StudioLeagueError};

pub use splendor_eval::{elo_delta, elo_expected_score};

/// One paired update, as it is about to be written to `rating_events`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PairEloUpdate {
    pub rating_a_before: f64,
    pub rating_b_before: f64,
    pub expected_a: f64,
    pub score_a: f64,
    pub delta_a: f64,
    pub delta_b: f64,
    pub k_factor: u32,
}

impl PairEloUpdate {
    pub fn rating_a_after(&self) -> f64 {
        self.rating_a_before + self.delta_a
    }
    pub fn rating_b_after(&self) -> f64 {
        self.rating_b_before + self.delta_b
    }
}

/// Map the two seats' win flags to player A's score, mirroring the frozen
/// `build_rating_report_v1` mapping exactly (a shared terminal win is a tie).
pub fn pair_score_a(a_won: bool, b_won: bool) -> Result<f64> {
    match (a_won, b_won) {
        (true, false) => Ok(1.0),
        (false, true) => Ok(0.0),
        (true, true) => Ok(0.5),
        (false, false) => Err(StudioLeagueError::Invalid(
            "a completed match must have at least one winner".to_string(),
        )),
    }
}

/// Apply the canonical rule to one eligible 1v1 match.
pub fn plan_pair_update(
    rating_a: f64,
    rating_b: f64,
    score_a: f64,
    k_factor: u32,
) -> PairEloUpdate {
    let expected_a = elo_expected_score(rating_a, rating_b);
    let delta_a = elo_delta(rating_a, rating_b, score_a, k_factor);
    PairEloUpdate {
        rating_a_before: rating_a,
        rating_b_before: rating_b,
        expected_a,
        score_a,
        delta_a,
        delta_b: -delta_a,
        k_factor,
    }
}
