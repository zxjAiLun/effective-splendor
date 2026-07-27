//! Errors from building, validating, hashing, scheduling, or aggregating an
//! evaluation plan.
//!
//! Every variant carries enough context to report a precise, user-facing
//! reason. Validation/aggregation never panics on malformed input — it returns
//! one of these so a caller (the future CLI/driver) can decide how to surface
//! it.

use thiserror::Error;

/// Errors from constructing, validating, hashing, scheduling, or aggregating
/// an evaluation plan.
#[derive(Debug, Error)]
pub enum EvaluationError {
    /// The plan failed strict validation (format/version, ids, counts, seeds,
    /// timeouts, or the match ceiling).
    #[error("invalid evaluation plan: {0}")]
    InvalidPlan(String),

    /// The plan would schedule more matches than the frozen ceiling allows.
    #[error("evaluation would schedule {planned} matches, exceeding the ceiling of {limit}")]
    MatchLimitExceeded { limit: u32, planned: u32 },

    /// A schedule slot's derived `ArenaConfig` failed arena validation.
    #[error("arena config error for a scheduled match: {0}")]
    ArenaConfig(String),

    /// A record's `game_id` did not match the scheduled slot it claimed.
    #[error("record for match {match_index} has game_id '{found}', expected '{expected}'")]
    RecordGameIdMismatch {
        match_index: u32,
        expected: String,
        found: String,
    },

    /// A record's seat→agent mapping (or seed/rotation) did not match the
    /// scheduled slot.
    #[error("record for match {match_index} does not match the scheduled seat mapping")]
    RecordSeatMappingMismatch { match_index: u32 },

    /// A completed outcome's score/rank vector length did not match the player
    /// count.
    #[error(
        "outcome length mismatch for match {match_index}: expected {expected} entries, found {found}"
    )]
    OutcomeLengthMismatch {
        match_index: u32,
        expected: usize,
        found: usize,
    },

    /// An aborted outcome's attributed seat was out of bounds for the player
    /// count.
    #[error("aborted seat {seat} out of bounds for {player_count} players (match {match_index})")]
    AbortedSeatOutOfBounds {
        match_index: u32,
        seat: u8,
        player_count: u8,
    },

    /// A completed outcome named a winner seat that was out of bounds for the
    /// player count. Validated before any winner is accumulated so malformed
    /// input can never panic the aggregator.
    #[error("winner seat {seat} out of bounds for {player_count} players (match {match_index})")]
    WinnerSeatOutOfBounds {
        match_index: u32,
        seat: u8,
        player_count: u8,
    },

    /// A completed outcome named the same winner seat more than once. Each
    /// winner must reference a distinct seat.
    #[error("duplicate winner seat {seat} in match {match_index}")]
    DuplicateWinnerSeat { match_index: u32, seat: u8 },

    /// A record's seat→agent mapping referenced an agent id that is not part of
    /// the plan. This is a fail-closed defense: once the canonical-schedule
    /// binding and seat-mapping checks pass this should be unreachable, but the
    /// aggregator never indexes untrusted ids with a panicking `Index`.
    #[error("record for match {match_index} references unknown agent '{agent_id}'")]
    UnknownAgentInRecord { match_index: u32, agent_id: String },

    /// A submitted record referenced a `match_index` absent from the schedule.
    #[error("record references unknown match index {0}")]
    UnknownMatchIndex(u32),

    /// Two records claimed the same `match_index`.
    #[error("duplicate record for match index {0}")]
    DuplicateRecord(u32),

    /// A scheduled match had no submitted record.
    #[error("missing record for match index {0}")]
    MissingRecord(u32),

    /// Serialization (for hashing or round-trip) failed internally.
    #[error("serialization error: {0}")]
    Serialization(String),
}
