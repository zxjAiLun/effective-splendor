//! The canonical, source-independent match record every ingestion path produces.

use crate::error::{Result, StudioLeagueError};
use crate::participant::EngineIdentityV1;
use serde::{Deserialize, Serialize};

/// A 64-character lowercase hex SHA-256.
///
/// Every content hash the league stores must satisfy this: otherwise a missing
/// hash (`None`) or an arbitrary string could masquerade as a content identity,
/// which is exactly how a hashless duplicate slipped through as idempotent
/// (Commit A Repair 2, P1-3).
pub fn is_lowercase_hex64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}

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

    /// A replay this league is willing to *claim* it verified must be fully
    /// traceable; a claim with no binding is a structural contradiction.
    fn require_complete(&self, label: &str) -> Result<()> {
        let hash_ok = self
            .document_hash
            .as_deref()
            .map(is_lowercase_hex64)
            .unwrap_or(false);
        if !hash_ok {
            return Err(StudioLeagueError::Invalid(format!(
                "{label} replay must carry a 64-character lowercase replay document hash"
            )));
        }
        if self.final_hash.as_deref().unwrap_or("").trim().is_empty() {
            return Err(StudioLeagueError::Invalid(format!(
                "{label} replay must carry the referee's replay_final_hash"
            )));
        }
        if matches!(self.storage(), ReplayStorage::Absent) {
            return Err(StudioLeagueError::Invalid(format!(
                "{label} replay must record where it is stored"
            )));
        }
        if self.path.as_deref().unwrap_or("").trim().is_empty() {
            return Err(StudioLeagueError::Invalid(format!(
                "{label} replay must record its path"
            )));
        }
        Ok(())
    }
}

/// How a seat's league participant may be attributed (Commit B Slice 2
/// Repair 1, P1-2). Three states, never a silent fallback:
///
/// * configuration evidence exists and resolves the seat exactly;
/// * configuration evidence is **absent**, so the handshake runtime identity in
///   `identity` is the only evidence and may be used (coarse fallback);
/// * configuration evidence exists but **cannot attribute** this seat
///   (unclassified argv switch, no entry point, conflicting candidate
///   configurations). The seat is left unmapped rather than guessed, so the
///   match can never enter Elo through a coarse identity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SeatPolicyIdentityV1 {
    NoConfigEvidence,
    Resolved { policy_key: String },
    Unresolved { reason: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StudioMatchSeatV1 {
    pub seat: u8,
    /// Exact engine identity as recorded by the source, when it has one.
    pub identity: Option<EngineIdentityV1>,
    /// The seat's policy-level attribution state, recovered from the arena's
    /// `match-config.json` when one was available.
    ///
    /// The handshake runtime name/version in `identity` collapses distinct
    /// search configurations (for example `--max-nodes 2000` versus
    /// `--max-nodes 1`) into one string, which fabricated self-matches and hid
    /// real head-to-head results from Elo. Only
    /// [`SeatPolicyIdentityV1::Resolved`] proves an exact policy participant;
    /// [`SeatPolicyIdentityV1::Unresolved`] must stay unmapped, never fall
    /// back to `identity`.
    pub policy_identity: SeatPolicyIdentityV1,
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
    /// SHA-256 of the source document itself. Idempotency compares this, so a
    /// changed document under an unchanged key is a conflict, never a silent
    /// no-op (P1 of the Commit A review).
    ///
    /// **Required**: `None == None` would let two different hashless documents
    /// share one key and be swallowed as `AlreadyPresent`, so every ingestable
    /// source must carry a stable content hash (Commit A Repair 2, P1-3).
    pub source_document_hash: String,
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

    /// Structural gate applied before anything is written.
    ///
    /// These are hard contradictions, not eligibility opinions: a record that
    /// fails here must be reported, never stored as "eligible" and then quietly
    /// produce no rating event.
    pub fn validate_for_ingest(&self) -> Result<()> {
        if self.source_kind.trim().is_empty() {
            return Err(StudioLeagueError::Invalid(
                "source_kind must not be empty".to_string(),
            ));
        }
        if self.source_identity.trim().is_empty() {
            return Err(StudioLeagueError::Invalid(
                "source_identity must not be empty".to_string(),
            ));
        }
        if !is_lowercase_hex64(&self.source_document_hash) {
            return Err(StudioLeagueError::Invalid(
                "source_document_hash must be a 64-character lowercase hex sha256; a source without a stable content hash cannot be ingested"
                    .to_string(),
            ));
        }
        if self.player_count == 0 {
            return Err(StudioLeagueError::Invalid(
                "player_count must be at least 1".to_string(),
            ));
        }
        if self.seats.is_empty() {
            return Err(StudioLeagueError::Invalid(
                "a match record must carry at least one seat".to_string(),
            ));
        }
        // Exactly one seat per player: seat count and player_count must agree, so a
        // "2-player" record with three seats cannot sneak through as eligible.
        if self.seats.len() != self.player_count as usize {
            return Err(StudioLeagueError::Invalid(format!(
                "player_count {} does not match {} recorded seats",
                self.player_count,
                self.seats.len()
            )));
        }
        let mut seen = std::collections::BTreeSet::new();
        for seat in &self.seats {
            if !seen.insert(seat.seat) {
                return Err(StudioLeagueError::Invalid(format!(
                    "seat {} is recorded twice",
                    seat.seat
                )));
            }
        }
        if let Some(highest) = seen.iter().next_back() {
            if *highest as usize >= self.seats.len() {
                return Err(StudioLeagueError::Invalid(format!(
                    "seat {highest} is outside 0..{}",
                    self.seats.len()
                )));
            }
        }
        match self.status {
            MatchStatus::Completed => {
                if !self.seats.iter().any(|seat| seat.won) {
                    return Err(StudioLeagueError::Invalid(
                        "a completed match must record at least one winner".to_string(),
                    ));
                }
            }
            MatchStatus::Aborted | MatchStatus::Truncated => {
                if self.seats.iter().any(|seat| seat.won) {
                    return Err(StudioLeagueError::Invalid(format!(
                        "a {} match must not record a winner",
                        self.status.as_str()
                    )));
                }
            }
        }
        match self.replay.verification() {
            ReplayVerification::Verified => self.replay.require_complete("a verified")?,
            ReplayVerification::Invalid => {
                // Something was read and rejected; the hash of what was read is
                // the evidence, so it must be present and no binding may be implied.
                if self.replay.document_hash.is_none() {
                    return Err(StudioLeagueError::Invalid(
                        "an invalid replay must record the hash of the document that failed"
                            .to_string(),
                    ));
                }
            }
            ReplayVerification::Unavailable => {
                if self.replay.document_hash.is_some()
                    || self.replay.final_hash.is_some()
                    || self.replay.path.is_some()
                    || !matches!(self.replay.storage(), ReplayStorage::Absent)
                {
                    return Err(StudioLeagueError::Invalid(
                        "a match without a replay must not carry a replay binding".to_string(),
                    ));
                }
            }
        }
        Ok(())
    }
}
