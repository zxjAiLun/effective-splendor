//! Rating eligibility: which recorded matches may move Studio Elo.
//!
//! Invariant 1 of `docs/studio-league-v1.md`: every completed match enters the
//! ledger, but only eligible matches enter Elo. The excluded families are the
//! owner's list plus deviation D3 (self-matches).

use crate::ledger::StudioRatingConfigV1;
use crate::match_record::{MatchStatus, ReplayVerification};

pub const REASON_ABORTED: &str = "aborted";
pub const REASON_TRUNCATED: &str = "truncated";
pub const REASON_INCOMPLETE_SEATS: &str = "incomplete_seats";
pub const REASON_PLAYER_COUNT: &str = "player_count_not_eligible";
pub const REASON_RULESET: &str = "ruleset_mismatch";
pub const REASON_REPLAY: &str = "replay_not_verified";
pub const REASON_DIAGNOSTIC: &str = "diagnostic_agent";
pub const REASON_UNMAPPED: &str = "unmapped_participant";
pub const REASON_SELF_MATCH: &str = "self_match";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RatingEligibility {
    Eligible,
    Ineligible(&'static str),
}

impl RatingEligibility {
    pub fn is_eligible(&self) -> bool {
        matches!(self, RatingEligibility::Eligible)
    }

    pub fn reason(&self) -> Option<&'static str> {
        match self {
            RatingEligibility::Eligible => None,
            RatingEligibility::Ineligible(reason) => Some(reason),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EligibilityInput {
    pub status: MatchStatus,
    pub player_count: u8,
    pub ruleset_fingerprint: String,
    pub replay_verification: ReplayVerification,
    /// Resolved participant per seat; `None` means the identity could not be
    /// determined and is never guessed.
    pub participants: Vec<Option<String>>,
    pub diagnostic: bool,
}

/// Decide, in a fixed precedence so the recorded reason is stable.
///
/// Precedence: status → seat count → player count → ruleset → replay →
/// diagnostic → unmapped identity → self-match.
pub fn evaluate_eligibility(
    input: &EligibilityInput,
    config: &StudioRatingConfigV1,
) -> RatingEligibility {
    match input.status {
        MatchStatus::Aborted => return RatingEligibility::Ineligible(REASON_ABORTED),
        MatchStatus::Truncated => return RatingEligibility::Ineligible(REASON_TRUNCATED),
        MatchStatus::Completed => {}
    }
    if input.participants.len() < 2 {
        return RatingEligibility::Ineligible(REASON_INCOMPLETE_SEATS);
    }
    if input.player_count != config.eligible_player_count {
        return RatingEligibility::Ineligible(REASON_PLAYER_COUNT);
    }
    if input.ruleset_fingerprint != config.eligible_ruleset_fingerprint {
        return RatingEligibility::Ineligible(REASON_RULESET);
    }
    if input.replay_verification != ReplayVerification::Verified {
        return RatingEligibility::Ineligible(REASON_REPLAY);
    }
    if input.diagnostic {
        return RatingEligibility::Ineligible(REASON_DIAGNOSTIC);
    }
    if input.participants.iter().any(|seat| seat.is_none()) {
        return RatingEligibility::Ineligible(REASON_UNMAPPED);
    }
    let first = input.participants[0].as_deref();
    if input.participants[1..]
        .iter()
        .any(|seat| seat.as_deref() == first)
    {
        // Deviation D3: a participant cannot rate itself.
        return RatingEligibility::Ineligible(REASON_SELF_MATCH);
    }
    RatingEligibility::Eligible
}
