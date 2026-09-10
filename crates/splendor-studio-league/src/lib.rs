//! Studio League v1 — persistent participants, a match ledger, and live Studio Elo.
//!
//! This is a **product** layer, deliberately separate from the research rating
//! layer. `RatingReportV1` / `RatedAgentV1` in `splendor-eval` describe one frozen
//! round-robin tournament with executable agents; this crate describes a
//! long-lived league in which a human is a first-class participant. Nothing here
//! rewrites, re-derives or replaces those research artifacts.
//!
//! Boundaries that must hold (see `docs/studio-league-v1.md`):
//! * every completed match enters the ledger; only eligible matches enter Elo;
//! * a human is never pushed into `RatedAgentV1`;
//! * an undetermined identity is never guessed;
//! * Elo has exactly one implementation, in Rust (`splendor_eval::elo_delta`);
//! * the SQLite index is derived state and may always be rebuilt.
//!
//! The crate is named `splendor-studio-league` because `crates/splendor-league` is
//! already the M11 research self-play league (deviation D1).

pub mod eligibility;
pub mod elo;
pub mod error;
pub mod inventory;
pub mod ledger;
pub mod match_record;
pub mod participant;
pub mod schema;

pub use eligibility::{
    evaluate_eligibility, EligibilityInput, RatingEligibility, REASON_ABORTED, REASON_DIAGNOSTIC,
    REASON_INCOMPLETE_SEATS, REASON_PLAYER_COUNT, REASON_REPLAY, REASON_RULESET, REASON_SELF_MATCH,
    REASON_TRUNCATED, REASON_UNMAPPED,
};
pub use elo::{elo_delta, elo_expected_score, pair_score_a, plan_pair_update, PairEloUpdate};
pub use error::{Result, StudioLeagueError};
pub use inventory::{
    scan, write_jsonl, InventoryMatchRowV1, InventoryReportV1, InventoryScanConfig,
    InventorySeatV1, INVENTORY_REPORT_FORMAT, INVENTORY_REPORT_VERSION,
};
pub use ledger::{
    alias_participants, apply_rating_for_match, eligible_match_count, ineligible_reason_counts,
    ingest_match, is_rating_quality_replay, leaderboard, match_count, participant_elo,
    preview_eligibility, rating_history, rebuild_ratings, IngestOutcome, LeaderboardRow,
    RatingEventRow, StudioRatingConfigV1, DEFAULT_INITIAL_ELO, DEFAULT_K_FACTOR,
    SPLENDOR_BASE_V1_RULESET_FINGERPRINT, STUDIO_ELIGIBLE_PLAYER_COUNT, STUDIO_ELO_ALGORITHM_V1,
    STUDIO_RATING_CONFIG_VERSION,
};
pub use match_record::{
    MatchStatus, ReplayBindingV1, ReplayStorage, ReplayVerification, StudioMatchRecordV1,
    StudioMatchSeatV1,
};
pub use participant::{
    ensure_local_human, local_human_participant, new_participant_id, participant,
    rename_participant, resolve_alias, resolve_engine_participant, unassigned_human_participant,
    EngineIdentityV1, ParticipantKind, ParticipantRow, LOCAL_HUMAN_META_KEY,
    PROVISIONAL_MATCH_THRESHOLD, UNASSIGNED_HUMAN_KEY,
};
pub use schema::{
    get_meta, initialise, open_in_memory, open_league, schema_version, set_meta,
    SCHEMA_VERSION_META_KEY, STUDIO_LEAGUE_SCHEMA_VERSION,
};

/// Default location of the derived league index.
pub const STUDIO_LEAGUE_DIR: &str = "local-artifacts/studio-league";
pub const STUDIO_LEAGUE_DB_FILE: &str = "local-artifacts/studio-league/league.sqlite3";
/// Content-addressed replay archive root (`<document sha256>.json`).
pub const STUDIO_LEAGUE_REPLAY_DIR: &str = "local-artifacts/studio-league/replays";
/// Default local human display name, used only when the profile is first created.
pub const DEFAULT_LOCAL_HUMAN_NAME: &str = "You";
