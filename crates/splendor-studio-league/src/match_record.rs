//! The canonical, source-independent match record every ingestion path produces.

use crate::participant::EngineIdentityV1;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchStatus {
    Completed,
    Aborted,
    Truncated,
}

impl MatchStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            MatchStatus::Completed => "completed",
            MatchStatus::Aborted => "aborted",
            MatchStatus::Truncated => "truncated",
        }
    }

    pub fn from_db(value: &str) -> Option<Self> {
        match value {
            "completed" => Some(MatchStatus::Completed),
            "aborted" => Some(MatchStatus::Aborted),
            "truncated" => Some(MatchStatus::Truncated),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplayVerification {
    /// A ReplayV1 was read and passed `verify_replay`.
    Verified,
    /// A ReplayV1 was read and failed verification.
    Invalid,
    /// No replay was available for this match.
    Unavailable,
}

impl ReplayVerification {
    pub fn as_str(self) -> &'static str {
        match self {
            ReplayVerification::Verified => "verified",
            ReplayVerification::Invalid => "invalid",
            ReplayVerification::Unavailable => "unavailable",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplayStorage {
    /// Copied into the content-addressed Studio archive.
    Archive,
    /// Left where the source experiment wrote it; path recorded, never moved.
    InPlaceReference,
    Absent,
}

impl ReplayStorage {
    pub fn as_str(self) -> &'static str {
        match self {
            ReplayStorage::Archive => "archive",
            ReplayStorage::InPlaceReference => "in_place_reference",
            ReplayStorage::Absent => "absent",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ReplayBindingV1 {
    /// SHA-256 of the replay document bytes (the content address).
    pub document_hash: Option<String>,
    /// The referee's `replay_final_hash` as recorded by the arena.
    pub final_hash: Option<String>,
    pub storage: Option<ReplayStorage>,
    pub path: Option<String>,
    pub verification: Option<ReplayVerification>,
}

impl ReplayBindingV1 {
    pub fn verification(&self) -> ReplayVerification {
        self.verification.unwrap_or(ReplayVerification::Unavailable)
    }
    pub fn storage(&self) -> ReplayStorage {
        self.storage.unwrap_or(ReplayStorage::Absent)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StudioMatchSeatV1 {
    pub seat: u8,
    /// Exact engine identity as recorded by the source, when it has one.
    pub identity: Option<EngineIdentityV1>,
    /// Resolved league participant, filled in during ingestion.
    pub participant_id: Option<String>,
    pub display_name: Option<String>,
    pub score: Option<i32>,
    pub rank: Option<i32>,
    pub won: bool,
}

/// One finished match, in the shape the ledger stores.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StudioMatchRecordV1 {
    /// `arena_report` | `human_play` | `evaluation_report` | …
    pub source_kind: String,
    /// Stable within `source_kind`; together they form the ingest key.
    pub source_identity: String,
    pub source_path: Option<String>,
    pub played_at: Option<i64>,
    pub ruleset_fingerprint: String,
    pub engine_version: Option<String>,
    pub player_count: u8,
    pub status: MatchStatus,
    pub seats: Vec<StudioMatchSeatV1>,
    pub completed_plies: Option<u32>,
    /// Real turn count, never `completed_plies` (follow-up decision phases make
    /// one turn several recorded decisions).
    pub main_turn_count: Option<u32>,
    pub replay: ReplayBindingV1,
    /// A diagnostic or deliberately altered temporary configuration.
    pub diagnostic: bool,
}

impl StudioMatchRecordV1 {
    /// Content identity of the match itself. `game_id` is not unique across
    /// historical runs, so it must never be the ledger key.
    pub fn match_id(&self) -> String {
        let mut hasher = <sha2::Sha256 as sha2::Digest>::new();
        sha2::Digest::update(
            &mut hasher,
            format!(
                "studio-league-match-v1\n{}\n{}\n{}\n",
                self.source_kind,
                self.source_identity,
                self.replay.final_hash.as_deref().unwrap_or("-")
            )
            .as_bytes(),
        );
        hex::encode(sha2::Digest::finalize(hasher))
    }

    pub fn winners(&self) -> Vec<u8> {
        self.seats
            .iter()
            .filter(|seat| seat.won)
            .map(|seat| seat.seat)
            .collect()
    }

    pub fn scores(&self) -> Vec<i32> {
        self.seats.iter().filter_map(|seat| seat.score).collect()
    }
}
