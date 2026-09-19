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

pub mod agent_configuration;
pub mod completion;
pub mod eligibility;
pub mod elo;
pub mod error;
pub mod historical_import;
pub mod human_occurrence;
pub mod identity_manifest;
pub mod inventory;
pub mod ledger;
pub mod match_record;
pub mod participant;
pub mod paths;
pub mod reader;
pub mod replay_archive;
pub mod replay_index;
pub mod schema;

#[cfg(test)]
#[path = "games_page_tests.rs"]
mod games_page;

/// Crate-internal gates over the runtime completion chain.
#[cfg(test)]
mod chain_tests;

pub use agent_configuration::{
    classify_switch, is_diagnostic_configuration, parse_match_configuration,
    resolve_policy_identity, AgentPolicyIdentityV1, MatchConfigurationV1,
    SeatConfigurationIdentityV1, SwitchClass,
};
pub use completion::{
    complete_human_runtime_occurrence, complete_runtime_occurrence, open_completion_league,
    CompletionLeagueV1, CompletionOutcomeV1, CompletionRequestV1, HumanCompletionRequestV1,
};
pub use eligibility::{
    evaluate_eligibility, EligibilityInput, RatingEligibility, REASON_ABORTED, REASON_DIAGNOSTIC,
    REASON_INCOMPLETE_SEATS, REASON_PLAYER_COUNT, REASON_REPLAY, REASON_RULESET, REASON_SELF_MATCH,
    REASON_TRUNCATED, REASON_UNMAPPED,
};
pub use elo::{elo_delta, elo_expected_score, pair_score_a, plan_pair_update, PairEloUpdate};
pub use error::{Result, StudioLeagueError};
pub use historical_import::{
    arena_report_to_match_record, associate_configuration, build_historical_corpus,
    compute_canonical_set_digest, compute_policy_attribution_digest, parse_arena_report,
    parse_runtime_occurrence, resolve_arena_report_replay, run_historical_dry_run,
    runtime_occurrence_evidence_hash, ConfigAssociationV1, ConfigurationCandidateV1,
    HistoricalDryRunConfig, HistoricalDryRunReportV1, HistoricalReplayResolutionV1,
    OccurrenceIdentityV1, RuntimeOccurrenceV1, RUNTIME_OCCURRENCE_FORMAT,
    RUNTIME_OCCURRENCE_VERSION,
};
pub use human_occurrence::{
    human_runtime_occurrence_evidence_hash, parse_human_runtime_occurrence, HumanOccurrenceHumanV1,
    HumanOccurrenceOpponentV1, HumanRuntimeOccurrenceV1, HUMAN_PLAY_SOURCE_KIND,
    HUMAN_RUNTIME_OCCURRENCE_FORMAT, HUMAN_RUNTIME_OCCURRENCE_VERSION,
};
pub use identity_manifest::{
    backup_path, temp_path, AliasEntryV1, IdentityManifestV1, LocalHumanIdentityV1,
    IDENTITY_MANIFEST_FORMAT, IDENTITY_MANIFEST_VERSION,
};
pub use inventory::{
    scan, write_jsonl, InventoryMatchRowV1, InventoryReportV1, InventoryScanConfig,
    InventorySeatV1, INVENTORY_REPORT_FORMAT, INVENTORY_REPORT_VERSION,
};
pub use ledger::{
    aliases, canonical_league_order, eligible_match_count, ensure_rating_config, identity_index,
    ineligible_reason_counts, ingest_batch_canonical, ingest_match, ingest_match_ordered,
    is_rating_quality_replay, leaderboard, league_order, match_count, match_receipt,
    now_epoch_seconds, participant_elo, participant_id_for_identity, preview_eligibility,
    protocol_rating_config, rating_event_count, rating_history, rebuild_ratings,
    stored_rating_config, IngestOrder, IngestOutcome, LeaderboardRow, LeagueMatchListRowV1,
    LeagueMatchListSeatV1, LeagueMatchPageRequestV1, LeagueMatchPageV1, MatchDetailV1,
    MatchEloEventV1, MatchReceiptV1, MatchSeatDetailV1, RatingEventRow, ReplayBindingSummaryV1,
    StudioRatingConfigV1, DEFAULT_INITIAL_ELO, DEFAULT_K_FACTOR, GAMES_PAGE_DEFAULT_LIMIT,
    GAMES_PAGE_MAX_LIMIT, LEADERBOARD_SQL, SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
    STUDIO_ELIGIBLE_PLAYER_COUNT, STUDIO_ELO_ALGORITHM_V1, STUDIO_RATING_CONFIG_VERSION,
};
pub use match_record::{
    is_lowercase_hex64, MatchStatus, ReplayBindingV1, ReplayStorage, ReplayVerification,
    SeatPolicyIdentityV1, StudioMatchRecordV1, StudioMatchSeatV1,
};
pub use participant::{
    canonical_identity_key, derived_participant_id, local_human_participant, new_participant_id,
    participant, resolve_engine_participant, resolve_engine_participant_with_key,
    stored_identity_manifest_hash, sync_identity_manifest, unassigned_human_participant,
    EngineIdentityV1, ParticipantKind, ParticipantRow, IDENTITY_MANIFEST_HASH_META_KEY,
    LOCAL_HUMAN_META_KEY, PROVISIONAL_MATCH_THRESHOLD, UNASSIGNED_HUMAN_KEY,
};
pub use paths::StudioLeaguePathsV1;
pub use reader::{open_studio_league_reader, StudioLeagueReaderV1};
pub use replay_archive::{
    archive_replay, read_archived_replay, replay_document_sha256, ArchiveOutcome, ArchivedReplayV1,
};
pub use replay_index::{
    build_replay_content_index, build_replay_content_index_roots, collect_corpus_files, CorpusFile,
    CorpusRoot, ReplayContentCandidateV1, ReplayContentIndexV1,
};
pub use schema::{
    get_meta, initialise, open_in_memory, open_league, schema_version, set_meta,
    SCHEMA_VERSION_META_KEY, STUDIO_LEAGUE_SCHEMA_VERSION,
};

// The league layout (the root-relative directory and the three leaf names) is
// private to `paths`, because [`StudioLeaguePathsV1`] is the only supported way
// to locate a league: exposing the names would let an external crate compose a
// league path without ever mentioning the type that keeps the three locations
// together.
/// Default local human display name, used only when the profile is first created.
pub const DEFAULT_LOCAL_HUMAN_NAME: &str = "You";
