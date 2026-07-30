//! Search analysis artifact model (v1).
//!
//! Pure data model for the offline `analyze-replay` artifact: a search result
//! bound to the exact verified replay position and configuration it was
//! computed from. This module performs no I/O and no replay verification —
//! `splendor-search` deliberately does not depend on `splendor-replay`; the
//! binding of replay identity hashes into [`ReplaySearchSourceV1`] is done by
//! the CLI after full replay verification.
//!
//! Determinism contract: an analysis artifact contains no timestamp, duration,
//! hostname, filesystem path, thread count or any other non-deterministic
//! metadata. The same replay, ply and config must serialize to byte-identical
//! artifacts.

use serde::{Deserialize, Serialize};
use splendor_core::{Action, PlayerId};

use crate::config::SearchConfigV1;
use crate::model::SearchResultV1;

/// Frozen artifact format identifier.
pub const SEARCH_ANALYSIS_FORMAT: &str = "effective-splendor-search-analysis";

/// Frozen artifact schema version.
pub const SEARCH_ANALYSIS_VERSION: u32 = 1;

/// The verified replay position a search analysis was computed from.
///
/// `replay_document_hash` is the canonical content identity of the whole
/// replay document; `replay_final_state_hash` alone is not an identity because
/// two different action histories could reach the same final state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplaySearchSourceV1 {
    /// Canonical v1 document hash of the verified replay.
    pub replay_document_hash: String,
    /// The replay's recorded final state hash.
    pub replay_final_state_hash: String,
    /// The replay schema version the source document used.
    pub replay_version: u32,
    /// The ruleset fingerprint recorded in the replay.
    pub ruleset_fingerprint: String,
    /// The analyzed ply: the state *before* `steps[analyzed_ply]`.
    pub analyzed_ply: u32,
    /// `full_state_hash` of the analyzed state
    /// (equals `steps[analyzed_ply].state_hash_before`).
    pub analyzed_state_hash: String,
    /// The actor recorded at the analyzed ply.
    pub recorded_actor: PlayerId,
    /// The action recorded at the analyzed ply.
    pub recorded_action: Action,
}

/// A complete search analysis artifact: versions, source binding, exact
/// search configuration and the full deterministic search result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchAnalysisV1 {
    /// Always [`SEARCH_ANALYSIS_FORMAT`].
    pub format: String,
    /// Always [`SEARCH_ANALYSIS_VERSION`].
    pub version: u32,

    /// Engine version the analysis ran against.
    pub engine_version: String,
    /// Card/noble catalog version.
    pub catalog_version: String,
    /// Frozen search algorithm identity (`SEARCH_ALGORITHM_ID`).
    pub search_algorithm_id: String,
    /// Frozen search model version (`SEARCH_VERSION`).
    pub search_version: u32,

    /// The verified replay position this analysis is bound to.
    pub source: ReplaySearchSourceV1,
    /// The exact search configuration used.
    pub config: SearchConfigV1,
    /// The full deterministic search result.
    pub result: SearchResultV1,

    /// Whether the search's recommended root action equals the action the
    /// player actually recorded at the analyzed ply.
    pub recommended_matches_recorded: bool,
}
