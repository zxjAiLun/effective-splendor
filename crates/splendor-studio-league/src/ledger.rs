//! The match ledger and its deterministic Elo events.
//!
//! Invariants this module must enforce, and the reasons they exist:
//!
//! * **`league_seq` fixes the Elo order.** It comes from an explicit canonical
//!   sort ([`canonical_league_order`]), never from filesystem traversal order.
//! * **Ingestion is idempotent on `(source_kind, source_identity)` — and only when
//!   the content matches.** The same key with a different `source_document_hash`
//!   is a conflict, not a no-op.
//! * **The rating config is a fixed protocol constant.** Studio Elo v1 is not a
//!   user setting, so `league_meta` stores it only as version/integrity evidence;
//!   a database written by a different protocol fails closed with zero mutation,
//!   and a rebuild needs nothing out of band (Commit A Repair 2, P1-2).
//! * **`rating_eligible` implies exactly two rating events.** A eligible 1v1 match
//!   that cannot produce a pair event is an error, never a silent skip.
//! * **Batch ingestion is atomic.** `ingest_batch_canonical` shares one
//!   transaction, so a failure at record N leaves nothing committed
//!   (Commit A Repair 2, P1-4).

use crate::eligibility::{evaluate_eligibility, EligibilityInput, RatingEligibility};
use crate::elo::{pair_score_a, plan_pair_update};
use crate::error::{Result, StudioLeagueError};
use crate::match_record::{MatchStatus, ReplayStorage, ReplayVerification, StudioMatchRecordV1};
use crate::participant::{
    derived_participant_id, resolve_engine_participant, resolve_engine_participant_with_key,
    ParticipantKind,
};
use crate::schema::{get_meta, set_meta, RATING_CONFIG_META_KEY};
use rusqlite::{params, params_from_iter, Connection, OptionalExtension, Transaction};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

pub const STUDIO_ELO_ALGORITHM_V1: &str = "studio-elo-v1";
pub const STUDIO_RATING_CONFIG_VERSION: u32 = 1;
pub const DEFAULT_INITIAL_ELO: i32 = 1500;
pub const DEFAULT_K_FACTOR: u32 = 32;
pub const STUDIO_ELIGIBLE_PLAYER_COUNT: u8 = 2;
/// The only ruleset fingerprint present in the 48,273-match historical corpus.
pub const SPLENDOR_BASE_V1_RULESET_FINGERPRINT: &str =
    "1c43f598b23017fab5e9d8b0083942ad1a921d1df804f90d16cd0b4753961afb";

/// The frozen Studio rating identity, persisted in `league_meta` on first use.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StudioRatingConfigV1 {
    pub version: u32,
    pub algorithm: String,
    pub initial_elo: i32,
    pub k_factor: u32,
    pub eligible_player_count: u8,
    pub eligible_ruleset_fingerprint: String,
    pub provisional_threshold: u32,
}

impl Default for StudioRatingConfigV1 {
    fn default() -> Self {
        Self {
            version: STUDIO_RATING_CONFIG_VERSION,
            algorithm: STUDIO_ELO_ALGORITHM_V1.to_string(),
            initial_elo: DEFAULT_INITIAL_ELO,
            k_factor: DEFAULT_K_FACTOR,
            eligible_player_count: STUDIO_ELIGIBLE_PLAYER_COUNT,
            eligible_ruleset_fingerprint: SPLENDOR_BASE_V1_RULESET_FINGERPRINT.to_string(),
            provisional_threshold: crate::participant::PROVISIONAL_MATCH_THRESHOLD,
        }
    }
}

impl StudioRatingConfigV1 {
    pub fn validate(&self) -> Result<()> {
        if self.algorithm != STUDIO_ELO_ALGORITHM_V1 {
            return Err(StudioLeagueError::RatingConfig(format!(
                "algorithm `{}` is not `{STUDIO_ELO_ALGORITHM_V1}`",
                self.algorithm
            )));
        }
        if self.eligible_player_count != STUDIO_ELIGIBLE_PLAYER_COUNT {
            return Err(StudioLeagueError::RatingConfig(
                "Studio Elo is defined for 2-player matches only".to_string(),
            ));
        }
        if self.k_factor == 0 {
            return Err(StudioLeagueError::RatingConfig(
                "k_factor must be non-zero".to_string(),
            ));
        }
        if self.eligible_ruleset_fingerprint.len() != 64 {
            return Err(StudioLeagueError::RatingConfig(
                "eligible_ruleset_fingerprint must be a 64-character fingerprint".to_string(),
            ));
        }
        Ok(())
    }

    pub fn to_json(&self) -> Result<String> {
        Ok(serde_json::to_string(self)?)
    }

    pub fn from_json(text: &str) -> Result<Self> {
        let config: Self = serde_json::from_str(text)?;
        config.validate()?;
        Ok(config)
    }
}

pub fn now_epoch_seconds() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// The rating config this database was built with, if it has one.
pub fn stored_rating_config(conn: &Connection) -> Result<Option<StudioRatingConfigV1>> {
    match get_meta(conn, RATING_CONFIG_META_KEY)? {
        Some(text) => Ok(Some(StudioRatingConfigV1::from_json(&text)?)),
        None => Ok(None),
    }
}

/// The Studio Elo protocol constant.
///
/// Studio Elo v1 is a fixed protocol, not a user setting, so the rating identity
/// travels with the build rather than with the caller. That is what lets a rebuild
/// depend on nothing out of band: the corpus plus the identity manifest are
/// sufficient (Commit A Repair 2, P1-2).
pub fn protocol_rating_config() -> StudioRatingConfigV1 {
    StudioRatingConfigV1::default()
}

/// Record the protocol config in `league_meta` as integrity evidence, and require
/// any previously stored value to match it exactly.
///
/// The stored row is evidence, not the authority: deleting the database can no
/// longer change the rating identity, and a database written by a different build
/// fails closed with zero mutation.
pub fn ensure_rating_config(conn: &Connection) -> Result<StudioRatingConfigV1> {
    let config = protocol_rating_config();
    config.validate()?;
    match stored_rating_config(conn)? {
        None => {
            set_meta(conn, RATING_CONFIG_META_KEY, &config.to_json()?)?;
            Ok(config)
        }
        Some(stored) => {
            if stored != config {
                return Err(StudioLeagueError::RatingConfig(format!(
                    "this database was built with {} but this build's Studio Elo protocol is {}; the index is derived, so delete and rebuild it",
                    stored.to_json()?,
                    config.to_json()?
                )));
            }
            Ok(stored)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IngestOutcome {
    Inserted {
        match_id: String,
        rating_events: usize,
    },
    AlreadyPresent {
        match_id: String,
    },
}

impl IngestOutcome {
    pub fn match_id(&self) -> &str {
        match self {
            IngestOutcome::Inserted { match_id, .. } => match_id,
            IngestOutcome::AlreadyPresent { match_id } => match_id,
        }
    }
    pub fn was_inserted(&self) -> bool {
        matches!(self, IngestOutcome::Inserted { .. })
    }
    pub fn rating_events(&self) -> usize {
        match self {
            IngestOutcome::Inserted { rating_events, .. } => *rating_events,
            IngestOutcome::AlreadyPresent { .. } => 0,
        }
    }
}

/// How the ledger position of a new match is decided.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IngestOrder {
    /// Next free position — for genuinely new matches arriving now.
    Append,
    /// An explicit position from a canonical sort — for historical migration.
    Assigned(i64),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RatingEventRow {
    pub match_id: String,
    pub league_seq: i64,
    pub participant_id: String,
    pub opponent_id: String,
    pub elo_before: f64,
    pub elo_after: f64,
    pub delta: f64,
    pub score: f64,
    pub expected: f64,
    pub k_factor: u32,
    pub algorithm: String,
}

/// A leaderboard row. W/T/L are **rated** records only: a match that did not move
/// Elo must never appear here as a loss.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LeaderboardRow {
    pub participant_id: String,
    pub kind: ParticipantKind,
    pub display_name: String,
    pub elo: i32,
    /// Matches that moved Elo.
    pub rated_games: u32,
    /// Distinct matches this participant appears in, eligible or not.
    pub recorded_games: u32,
    pub rated_wins: u32,
    pub rated_ties: u32,
    pub rated_losses: u32,
    pub provisional: bool,
}

/// Deterministic league order for a batch of records.
///
/// Returns indices into `records` sorted by `(played_at, source_kind,
/// source_identity)`. Historical migration must assign `league_seq` from this, so
/// the Elo history never depends on how the filesystem was traversed.
pub fn canonical_league_order(records: &[StudioMatchRecordV1]) -> Vec<usize> {
    fn key(record: &StudioMatchRecordV1) -> (i64, String, String) {
        (
            record.played_at.unwrap_or(i64::MIN),
            record.source_kind.clone(),
            record.source_identity.clone(),
        )
    }
    let mut indices: Vec<usize> = (0..records.len()).collect();
    indices.sort_by(|&a, &b| key(&records[a]).cmp(&key(&records[b])));
    indices
}

/// Ingest a whole historical batch in canonical order, assigning positions 1..N.
///
/// Refuses a non-empty ledger, so "the canonical order of this batch" is
/// unambiguous; incremental arrivals use [`IngestOrder::Append`] instead.
pub fn ingest_batch_canonical(
    conn: &mut Connection,
    records: &[StudioMatchRecordV1],
) -> Result<Vec<IngestOutcome>> {
    if match_count(conn)? != 0 {
        return Err(StudioLeagueError::Invalid(
            "ingest_batch_canonical requires an empty ledger; use IngestOrder::Append for new matches"
                .to_string(),
        ));
    }
    let order = canonical_league_order(records);
    // ONE transaction for the whole batch. Per-record transactions would leave
    // the first N-1 records committed when record N fails, which contradicts the
    // documented importer promise that a failure imports nothing
    // (Commit A Repair 2, P1-4).
    let tx = conn.transaction()?;
    let mut outcomes = Vec::with_capacity(records.len());
    for (position, index) in order.into_iter().enumerate() {
        outcomes.push(ingest_match_in_tx(
            &tx,
            &records[index],
            IngestOrder::Assigned(position as i64 + 1),
        )?);
    }
    tx.commit()?;
    Ok(outcomes)
}

/// Insert one finished match, resolving identities and applying Elo if eligible.
pub fn ingest_match(conn: &mut Connection, record: &StudioMatchRecordV1) -> Result<IngestOutcome> {
    ingest_match_ordered(conn, record, IngestOrder::Append)
}

/// One match in its **own** transaction: the unit for live/runtime arrivals.
pub fn ingest_match_ordered(
    conn: &mut Connection,
    record: &StudioMatchRecordV1,
    order: IngestOrder,
) -> Result<IngestOutcome> {
    // IMMEDIATE, not DEFERRED: an incremental arrival is a write, and a
    // deferred transaction that reads before it writes can hit SQLITE_BUSY
    // immediately (no busy handler) when another producer commits in between.
    // Taking the write lock up front lets `busy_timeout` serialize concurrent
    // producers instead of failing one of them (Commit C Slice 3).
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let outcome = ingest_match_in_tx(&tx, record, order)?;
    tx.commit()?;
    Ok(outcome)
}

/// The transaction-scoped primitive shared by single and batch ingestion.
///
/// [`ingest_batch_canonical`] reuses this so one historical batch shares one
/// transaction and any failing record rolls the whole batch back
/// (Commit A Repair 2, P1-4).
fn ingest_match_in_tx(
    tx: &Transaction<'_>,
    record: &StudioMatchRecordV1,
    order: IngestOrder,
) -> Result<IngestOutcome> {
    record.validate_for_ingest()?;

    // Record (or verify) the rating identity before anything else is written.
    let config = ensure_rating_config(tx)?;

    let existing: Option<(String, String)> = tx
        .query_row(
            "SELECT match_id, source_document_hash FROM matches
              WHERE source_kind = ?1 AND source_identity = ?2",
            params![record.source_kind, record.source_identity],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    if let Some((match_id, stored_hash)) = existing {
        if stored_hash == record.source_document_hash {
            return Ok(IngestOutcome::AlreadyPresent { match_id });
        }
        return Err(StudioLeagueError::SourceConflict {
            source_kind: record.source_kind.clone(),
            source_identity: record.source_identity.clone(),
            stored: stored_hash.clone(),
            incoming: record.source_document_hash.clone(),
        });
    }

    // Occurrence authority is exactly `(source_kind, source_identity)` (Commit
    // A): the same identity with the same document is idempotent, the same
    // identity with a changed document is a conflict, and two different
    // authoritative occurrence identities may coexist even when deterministic
    // execution produced byte-identical documents. Document equality is not
    // occurrence equality; the Distinct-Document dedup lives in the historical
    // corpus builder, which lacks occurrence evidence, never here.

    // A runtime occurrence appends only at the ledger's tail (Commit C Slice 1
    // Repair 1, P1-2): `played_at` is the durable Elo-ordering evidence
    // recorded in the occurrence envelope, and an out-of-order arrival would
    // make the live append order diverge from the canonical rebuild order.
    // The guard is scoped to runtime occurrences (Commit A's non-runtime
    // ingest semantics carry no occurrence evidence and are untouched), and
    // compares the **full canonical key** `(played_at, source_kind,
    // source_identity)` so same-second occurrences with a stable identity
    // order still append (Unix-second timestamps are not required to be
    // unique; Repair 2, P2).
    if record.source_identity.starts_with("runtime:") {
        use rusqlite::OptionalExtension;

        let completed_at = record.played_at.ok_or_else(|| {
            StudioLeagueError::Invalid(format!(
                "runtime occurrence `{}` carries no played_at; the occurrence envelope's completed_at is the Elo-ordering evidence",
                record.source_identity
            ))
        })?;
        let tail: Option<(Option<i64>, String, String)> = tx
            .query_row(
                "SELECT played_at, source_kind, source_identity FROM matches
                  ORDER BY league_seq DESC LIMIT 1",
                [],
                |row| {
                    Ok((
                        row.get::<_, Option<i64>>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                },
            )
            .optional()?;
        let incoming = (
            Some(completed_at),
            record.source_kind.clone(),
            record.source_identity.clone(),
        );
        if let Some(tail) = tail {
            if incoming <= tail {
                return Err(StudioLeagueError::Invalid(format!(
                    "runtime occurrence `{}` canonical key {incoming:?} does not append after the ledger's tail {tail:?}; incremental append would diverge from the canonical rebuild order — rebuild the derived database from the occurrence evidence instead",
                    record.source_identity
                )));
            }
        }
    }

    let now = now_epoch_seconds();
    let match_id = record.match_id();

    let league_seq = match order {
        IngestOrder::Append => tx.query_row(
            "SELECT COALESCE(MAX(league_seq), 0) + 1 FROM matches",
            [],
            |row| row.get::<_, i64>(0),
        )?,
        IngestOrder::Assigned(seq) => {
            if seq < 1 {
                return Err(StudioLeagueError::Invalid(format!(
                    "assigned league_seq {seq} must be at least 1"
                )));
            }
            let taken: Option<String> = tx
                .query_row(
                    "SELECT match_id FROM matches WHERE league_seq = ?1",
                    params![seq],
                    |row| row.get(0),
                )
                .optional()?;
            if let Some(other) = taken {
                return Err(StudioLeagueError::Invalid(format!(
                    "league_seq {seq} is already used by match `{other}`"
                )));
            }
            seq
        }
    };

    // Resolve every seat before deciding eligibility: an identity the league
    // cannot determine must block rating rather than be guessed.
    let mut resolved: Vec<Option<String>> = Vec::with_capacity(record.seats.len());
    for seat in &record.seats {
        let id = match (&seat.participant_id, &seat.identity) {
            (Some(explicit), _) => Some(explicit.clone()),
            (None, Some(identity)) => {
                // Always the single canonical path: an alias is followed inside
                // the resolver, so there is no second, divergent resolution
                // order that could disagree with it (Commit A Repair 2, P1-1).
                let name = seat
                    .display_name
                    .clone()
                    .unwrap_or_else(|| identity.agent_name.clone());
                // Three-state policy attribution (Commit B Slice 2 Repair 1,
                // P1-2): a bound configuration resolves the exact policy
                // participant; absent configuration evidence may fall back to
                // the handshake runtime identity; present-but-unattributable
                // evidence (ambiguous candidates, unclassified argv) stays
                // unmapped so the match can never enter Elo through a coarse
                // identity.
                match &seat.policy_identity {
                    crate::match_record::SeatPolicyIdentityV1::Resolved { policy_key } => Some(
                        resolve_engine_participant_with_key(tx, policy_key, &name, now)?,
                    ),
                    crate::match_record::SeatPolicyIdentityV1::NoConfigEvidence => {
                        Some(resolve_engine_participant(tx, identity, &name, now)?)
                    }
                    crate::match_record::SeatPolicyIdentityV1::Unresolved { .. } => None,
                }
            }
            (None, None) => None,
        };
        resolved.push(id);
    }

    let eligibility = evaluate_eligibility(
        &EligibilityInput {
            status: record.status,
            player_count: record.player_count,
            ruleset_fingerprint: record.ruleset_fingerprint.clone(),
            replay_verification: record.replay.verification(),
            participants: resolved.clone(),
            diagnostic: record.diagnostic,
        },
        &config,
    );

    let scores = record.scores();
    let winners = record.winners();
    tx.execute(
        "INSERT INTO matches
            (match_id, source_kind, source_identity, source_path, source_document_hash,
             league_seq, played_at, ruleset_fingerprint, engine_version, player_count, status,
             scores_json, winners_json, completed_plies, main_turn_count, replay_document_hash,
             replay_final_hash, replay_storage, replay_path, replay_verification,
             rating_eligible, rating_ineligible_reason, detail_metrics_available, ingested_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17,
                 ?18, ?19, ?20, ?21, ?22, ?23, ?24)",
        params![
            match_id,
            record.source_kind,
            record.source_identity,
            record.source_path,
            record.source_document_hash,
            league_seq,
            record.played_at,
            record.ruleset_fingerprint,
            record.engine_version,
            record.player_count as i64,
            record.status.as_str(),
            serde_json::to_string(&scores)?,
            serde_json::to_string(&winners)?,
            record.completed_plies.map(|v| v as i64),
            record.main_turn_count.map(|v| v as i64),
            record.replay.document_hash,
            record.replay.final_hash,
            record.replay.storage().as_str(),
            record.replay.path,
            record.replay.verification().as_str(),
            eligibility.is_eligible() as i64,
            eligibility.reason(),
            false as i64,
            now,
        ],
    )?;

    for (index, seat) in record.seats.iter().enumerate() {
        let participant_id = resolved.get(index).cloned().flatten();
        tx.execute(
            "INSERT INTO match_seats
                (match_id, seat, participant_id, agent_name, agent_version, display_name,
                 score, rank, won)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                match_id,
                seat.seat as i64,
                participant_id,
                seat.identity.as_ref().map(|i| i.agent_name.clone()),
                seat.identity.as_ref().map(|i| i.agent_version.clone()),
                seat.display_name,
                seat.score.map(|v| v as i64),
                seat.rank.map(|v| v as i64),
                seat.won as i64,
            ],
        )?;
    }

    let rating_events = if eligibility.is_eligible() {
        apply_rating_for_match(tx, &config, &match_id, league_seq)?
    } else {
        0
    };
    if eligibility.is_eligible() && rating_events != 2 {
        return Err(StudioLeagueError::Invalid(format!(
            "eligible match `{match_id}` produced {rating_events} rating events; a 1v1 Elo update must produce exactly 2"
        )));
    }

    tx.execute(
        "INSERT OR REPLACE INTO ingest_sources
            (source_kind, source_identity, first_seen_at, source_document_hash, document_hash)
         VALUES (?1, ?2, ?3, ?4, ?5)",
        params![
            record.source_kind,
            record.source_identity,
            now,
            record.source_document_hash,
            record.replay.document_hash
        ],
    )?;

    Ok(IngestOutcome::Inserted {
        match_id,
        rating_events,
    })
}

/// Write the two Elo events for an eligible 1v1 match and move current Elo.
///
/// Fails rather than returning `0` when the pair is not a clean 1v1: an eligible
/// match with no rating event would be a silent lie.
fn apply_rating_for_match(
    tx: &Transaction<'_>,
    config: &StudioRatingConfigV1,
    match_id: &str,
    league_seq: i64,
) -> Result<usize> {
    let seats: Vec<(Option<String>, i64)> = {
        let mut stmt = tx.prepare(
            "SELECT participant_id, won FROM match_seats WHERE match_id = ?1 ORDER BY seat ASC",
        )?;
        let rows = stmt
            .query_map(params![match_id], |row| {
                Ok((row.get::<_, Option<String>>(0)?, row.get::<_, i64>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        rows
    };
    if seats.len() != 2 {
        return Err(StudioLeagueError::Invalid(format!(
            "eligible match `{match_id}` has {} seats; a Studio Elo update requires exactly 2",
            seats.len()
        )));
    }
    let (Some(a), Some(b)) = (seats[0].0.clone(), seats[1].0.clone()) else {
        return Err(StudioLeagueError::Invalid(format!(
            "eligible match `{match_id}` has an unresolved participant; it must not have been marked eligible"
        )));
    };

    let rating_a = participant_elo_with(tx, &a, config)?;
    let rating_b = participant_elo_with(tx, &b, config)?;
    let score_a = pair_score_a(seats[0].1 != 0, seats[1].1 != 0)?;
    let update = plan_pair_update(rating_a, rating_b, score_a, config.k_factor);

    for (participant_id, opponent_id, before, after, score, expected, delta) in [
        (
            a.as_str(),
            b.as_str(),
            update.rating_a_before,
            update.rating_a_after(),
            update.score_a,
            update.expected_a,
            update.delta_a,
        ),
        (
            b.as_str(),
            a.as_str(),
            update.rating_b_before,
            update.rating_b_after(),
            1.0 - update.score_a,
            1.0 - update.expected_a,
            update.delta_b,
        ),
    ] {
        tx.execute(
            "INSERT INTO rating_events
                (match_id, league_seq, participant_id, opponent_id, elo_before, elo_after,
                 delta, score, expected, k_factor, algorithm)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
            params![
                match_id,
                league_seq,
                participant_id,
                opponent_id,
                before,
                after,
                delta,
                score,
                expected,
                config.k_factor as i64,
                config.algorithm,
            ],
        )?;
        tx.execute(
            "UPDATE participants SET current_elo = ?1 WHERE participant_id = ?2",
            params![after, participant_id],
        )?;
    }
    Ok(2)
}

/// Current Elo, falling back to the protocol's initial value for a fresh
/// participant.
pub fn participant_elo(conn: &Connection, participant_id: &str) -> Result<f64> {
    participant_elo_with(conn, participant_id, &protocol_rating_config())
}

fn participant_elo_with(
    conn: &Connection,
    participant_id: &str,
    config: &StudioRatingConfigV1,
) -> Result<f64> {
    let stored: Option<f64> = conn
        .query_row(
            "SELECT current_elo FROM participants WHERE participant_id = ?1",
            params![participant_id],
            |row| row.get(0),
        )
        .optional()?
        .flatten();
    Ok(stored.unwrap_or(config.initial_elo as f64))
}

/// Recompute every Elo event from the ledger, in `league_seq` order, under the
/// Studio Elo protocol this build implements.
///
/// The caller supplies nothing: the protocol is a constant, and the database's
/// stored copy is checked for agreement rather than trusted as an input
/// (Commit A Repair 2, P1-2).
pub fn rebuild_ratings(conn: &mut Connection) -> Result<u64> {
    let stored = stored_rating_config(conn)?.ok_or_else(|| {
        StudioLeagueError::RatingConfig(
            "this database has no stored rating config; ingest at least one match before rebuilding"
                .to_string(),
        )
    })?;
    let protocol = protocol_rating_config();
    if stored != protocol {
        return Err(StudioLeagueError::RatingConfig(format!(
            "this database was built with {} but this build's Studio Elo protocol is {}; the index is derived, so delete and rebuild it",
            stored.to_json()?,
            protocol.to_json()?
        )));
    }
    rebuild_with_config(conn, &stored)
}

fn rebuild_with_config(conn: &mut Connection, config: &StudioRatingConfigV1) -> Result<u64> {
    config.validate()?;
    let tx = conn.transaction()?;
    tx.execute("DELETE FROM rating_events", [])?;
    tx.execute("UPDATE participants SET current_elo = NULL", [])?;
    let matches: Vec<(String, i64)> = {
        let mut stmt = tx.prepare(
            "SELECT match_id, league_seq FROM matches WHERE rating_eligible = 1 ORDER BY league_seq ASC",
        )?;
        let rows = stmt
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        rows
    };
    let mut events = 0u64;
    for (match_id, league_seq) in matches {
        events += apply_rating_for_match(&tx, config, &match_id, league_seq)? as u64;
    }
    tx.commit()?;
    Ok(events)
}

pub fn rating_history(conn: &Connection, participant_id: &str) -> Result<Vec<RatingEventRow>> {
    let mut stmt = conn.prepare(
        "SELECT match_id, league_seq, participant_id, opponent_id, elo_before, elo_after,
                delta, score, expected, k_factor, algorithm
           FROM rating_events WHERE participant_id = ?1 ORDER BY league_seq ASC",
    )?;
    let rows = stmt
        .query_map(params![participant_id], |row| {
            Ok(RatingEventRow {
                match_id: row.get(0)?,
                league_seq: row.get(1)?,
                participant_id: row.get(2)?,
                opponent_id: row.get(3)?,
                elo_before: row.get(4)?,
                elo_after: row.get(5)?,
                delta: row.get(6)?,
                score: row.get(7)?,
                expected: row.get(8)?,
                k_factor: row.get::<_, i64>(9)? as u32,
                algorithm: row.get(10)?,
            })
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// The leaderboard, ordered by Studio Elo.
///
/// W/T/L count **rated** matches only, so an aborted, truncated, unmapped or
/// self match can never be presented as a loss; `recorded_games` counts distinct
/// matches separately.
///
/// The set-based shape below is a **real-scale fix, not a stylistic one.** The
/// previous version asked for the same five aggregates with a correlated subquery
/// per participant. That is instant on a fixture league and pathological on the
/// real one: `match_seats` has no index on `participant_id`, so every subquery was
/// a full scan of the whole seat table **per participant** — on the official
/// 42,521-match ledger (85,042 seats, 100 participants) SQLite chose
/// `SCAN s` × 5 × 100, the query took 19.7 s, and because the Host's accept loop is
/// serial that single request made every route (including `/health`) unanswerable
/// for its whole duration.
///
/// The aggregates now run **once** over the join, and are attached to the
/// participants by `participant_id`: the official ledger answers in 1.1 s, and the
/// query plan no longer contains a per-participant scan of `match_seats`. The
/// numbers are unchanged — every participant's Elo, rated/recorded counts and
/// W/T/L were compared field by field against the previous query on the real
/// ledger before this replacement (0 differences across all 100 rows), and the
/// fixture-level semantics stay pinned by `tests/league_core.rs`.
///
/// A `match_seats(participant_id)` index was **not** added: measuring the set-based
/// shape first showed it is not needed, and inventing schema churn for a faster
/// number on one machine is not a reason to migrate a derived database.
/// The production leaderboard query.
///
/// Public so the real-scale gate can `EXPLAIN QUERY PLAN` **this** string rather than
/// a copy of it: a regression back to an aggregate-per-participant scan has to be
/// catchable, and a gate that pins a duplicate would drift away from the query it is
/// supposed to protect.
pub const LEADERBOARD_SQL: &str = "WITH rec AS (
             SELECT participant_id, COUNT(DISTINCT match_id) AS recorded
             FROM match_seats GROUP BY participant_id),
         winners AS (
             SELECT match_id, COUNT(*) AS winners
             FROM match_seats WHERE won = 1 GROUP BY match_id),
         rat AS (
             SELECT s.participant_id,
                    COUNT(*) AS rated,
                    SUM(CASE WHEN s.won = 1 AND w.winners = 1 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN s.won = 1 AND w.winners > 1 THEN 1 ELSE 0 END) AS ties
             FROM match_seats s
             JOIN matches m ON m.match_id = s.match_id AND m.rating_eligible = 1
             LEFT JOIN winners w ON w.match_id = s.match_id
             GROUP BY s.participant_id)
         SELECT p.participant_id, p.kind, p.display_name, p.current_elo,
                COALESCE(rec.recorded, 0), COALESCE(rat.rated, 0),
                COALESCE(rat.wins, 0), COALESCE(rat.ties, 0)
         FROM participants p
         LEFT JOIN rec ON rec.participant_id = p.participant_id
         LEFT JOIN rat ON rat.participant_id = p.participant_id";

pub fn leaderboard(conn: &Connection) -> Result<Vec<LeaderboardRow>> {
    let config = protocol_rating_config();
    let mut stmt = conn.prepare(LEADERBOARD_SQL)?;
    let mut rows: Vec<LeaderboardRow> = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<f64>>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, i64>(6)?,
                row.get::<_, i64>(7)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(|(id, kind, name, elo, recorded, rated, wins, ties)| {
            let rated = rated as u32;
            let wins = wins as u32;
            let ties = ties as u32;
            Ok(LeaderboardRow {
                participant_id: id,
                kind: ParticipantKind::from_db(&kind)?,
                display_name: name,
                elo: elo.unwrap_or(config.initial_elo as f64).round() as i32,
                rated_games: rated,
                recorded_games: recorded as u32,
                rated_wins: wins,
                rated_ties: ties,
                rated_losses: rated.saturating_sub(wins + ties),
                provisional: rated < config.provisional_threshold,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    rows.sort_by(|a, b| {
        b.elo
            .cmp(&a.elo)
            .then_with(|| b.rated_games.cmp(&a.rated_games))
            .then_with(|| a.display_name.cmp(&b.display_name))
    });
    Ok(rows)
}

pub fn match_count(conn: &Connection) -> Result<u64> {
    Ok(conn.query_row("SELECT COUNT(*) FROM matches", [], |row| {
        row.get::<_, i64>(0)
    })? as u64)
}

pub fn eligible_match_count(conn: &Connection) -> Result<u64> {
    Ok(conn.query_row(
        "SELECT COUNT(*) FROM matches WHERE rating_eligible = 1",
        [],
        |row| row.get::<_, i64>(0),
    )? as u64)
}

pub fn rating_event_count(conn: &Connection) -> Result<u64> {
    Ok(
        conn.query_row("SELECT COUNT(*) FROM rating_events", [], |row| {
            row.get::<_, i64>(0)
        })? as u64,
    )
}

pub fn ineligible_reason_counts(conn: &Connection) -> Result<Vec<(String, u64)>> {
    let mut stmt = conn.prepare(
        "SELECT COALESCE(rating_ineligible_reason, '(eligible)'), COUNT(*)
           FROM matches GROUP BY 1 ORDER BY 2 DESC",
    )?;
    let rows = stmt
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)? as u64))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// The `(match_id, league_seq)` assignment, for proving a rebuild is identical.
pub fn league_order(conn: &Connection) -> Result<Vec<(String, i64)>> {
    let mut stmt =
        conn.prepare("SELECT match_id, league_seq FROM matches ORDER BY league_seq ASC")?;
    let rows = stmt
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// Every `(alias_key, canonical_identity_key)` in the index, ordered.
pub fn aliases(conn: &Connection) -> Result<Vec<(String, String)>> {
    let mut stmt = conn.prepare(
        "SELECT alias_key, canonical_identity_key FROM participant_aliases ORDER BY alias_key ASC",
    )?;
    let rows = stmt
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// Every `(identity_key, participant_id)` in the index, ordered.
pub fn identity_index(conn: &Connection) -> Result<Vec<(String, String)>> {
    let mut stmt = conn.prepare(
        "SELECT identity_key, participant_id FROM participants
          WHERE identity_key IS NOT NULL ORDER BY identity_key ASC",
    )?;
    let rows = stmt
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// The id an engine identity will derive, without touching the database.
pub fn participant_id_for_identity(identity_key: &str) -> String {
    derived_participant_id(identity_key)
}

/// Unused-but-reserved id generator, exported so importers never invent one.
pub fn fresh_participant_id() -> String {
    crate::participant::new_participant_id()
}

/// True when `verification` permits Elo. Kept next to the ledger so callers do
/// not hand-roll the comparison.
pub fn is_rating_quality_replay(verification: ReplayVerification) -> bool {
    verification == ReplayVerification::Verified
}

/// The eligibility decision for a record, without touching the database.
pub fn preview_eligibility(
    record: &StudioMatchRecordV1,
    resolved: &[Option<String>],
) -> RatingEligibility {
    evaluate_eligibility(
        &EligibilityInput {
            status: record.status,
            player_count: record.player_count,
            ruleset_fingerprint: record.ruleset_fingerprint.clone(),
            replay_verification: record.replay.verification(),
            participants: resolved.to_vec(),
            diagnostic: record.diagnostic,
        },
        &protocol_rating_config(),
    )
}

/// The post-ingest receipt of one recorded match: its rating eligibility and
/// the Elo events it produced (Commit C Slice 1).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct MatchReceiptV1 {
    pub match_id: String,
    /// `None` when the match is rating-eligible; otherwise the frozen reason.
    pub rating_ineligible_reason: Option<String>,
    pub elo_events: Vec<MatchEloEventV1>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MatchEloEventV1 {
    pub participant_id: String,
    pub elo_before: f64,
    pub elo_after: f64,
}

/// Read the receipt of one match from the ledger. `Ok(None)` when the match is
/// not recorded at all.
pub fn match_receipt(conn: &Connection, match_id: &str) -> Result<Option<MatchReceiptV1>> {
    use rusqlite::OptionalExtension;

    let recorded: Option<String> = conn
        .query_row(
            "SELECT match_id FROM matches WHERE match_id = ?1",
            [match_id],
            |row| row.get(0),
        )
        .optional()?;
    if recorded.is_none() {
        return Ok(None);
    }
    let rating_ineligible_reason: Option<String> = conn
        .query_row(
            "SELECT rating_ineligible_reason FROM matches WHERE match_id = ?1",
            [match_id],
            // An eligible match legitimately stores NULL here.
            |row| row.get::<_, Option<String>>(0),
        )
        .optional()?
        .flatten();
    let mut statement = conn.prepare(
        "SELECT participant_id, elo_before, elo_after FROM rating_events
          WHERE match_id = ?1 ORDER BY participant_id",
    )?;
    let elo_events = statement
        .query_map([match_id], |row| {
            Ok(MatchEloEventV1 {
                participant_id: row.get(0)?,
                elo_before: row.get(1)?,
                elo_after: row.get(2)?,
            })
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(Some(MatchReceiptV1 {
        match_id: match_id.to_string(),
        rating_ineligible_reason,
        elo_events,
    }))
}

/// One recorded match, exactly as the ledger recorded it.
///
/// This is the match-detail read behind the read-only Host API. It reuses the
/// ledger's own view of the row, its seats and its rating events, and adds no
/// interpretation: it never derives a winner from a replay document, never
/// derives an identity from a filename, and never recomputes Elo.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MatchDetailV1 {
    pub match_id: String,
    pub source_kind: String,
    pub source_identity: String,
    pub status: MatchStatus,
    pub played_at: Option<i64>,
    pub league_seq: i64,
    pub player_count: u32,
    pub rating_eligible: bool,
    /// `None` when the match is rating-eligible; otherwise the frozen reason.
    pub rating_ineligible_reason: Option<String>,
    pub replay: ReplayBindingSummaryV1,
    pub seats: Vec<MatchSeatDetailV1>,
    pub rating_events: Vec<MatchEloEventV1>,
}

/// What the ledger records about one match's replay document.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReplayBindingSummaryV1 {
    /// The verified ReplayV1 document SHA-256, when the ledger recorded one.
    ///
    /// This is the content address the replay route accepts. It is an identity,
    /// never a path.
    pub document_sha256: Option<String>,
    pub storage: ReplayStorage,
    pub verification: ReplayVerification,
    /// The recorded provenance path, reported for transparency only.
    ///
    /// The bytes are located by archive root plus content address; this string
    /// never locates anything, and it is never accepted from a client.
    pub path: Option<String>,
    /// Whether the ledger records a usable content-addressed archive object.
    /// This is ledger state, not a filesystem probe: the replay route is the
    /// authority on whether the object can actually be read.
    pub archived: bool,
}

/// One seat of a recorded match.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MatchSeatDetailV1 {
    pub seat: u32,
    pub participant_id: Option<String>,
    pub display_name: Option<String>,
    pub agent_name: Option<String>,
    pub score: Option<i64>,
    pub rank: Option<i64>,
    pub won: bool,
}

/// Read one match in full from the ledger.
///
/// `Ok(None)` when the match is not recorded at all, so a caller answers "not
/// found" rather than inventing a row.
///
/// Crate-internal on purpose: this is the backing primitive behind
/// [`StudioLeagueReaderV1::match_detail`](crate::StudioLeagueReaderV1::match_detail),
/// and the whole point of that read session is that a consumer does not need a
/// raw connection or a query seam. The DTOs stay public because they are the
/// session method's return type.
pub(crate) fn match_detail(conn: &Connection, match_id: &str) -> Result<Option<MatchDetailV1>> {
    use rusqlite::OptionalExtension;

    let header = conn
        .query_row(
            "SELECT match_id, source_kind, source_identity, status, played_at, league_seq,
                    player_count, rating_eligible, rating_ineligible_reason,
                    replay_document_hash, replay_storage, replay_path, replay_verification
               FROM matches WHERE match_id = ?1",
            [match_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, Option<i64>>(4)?,
                    row.get::<_, i64>(5)?,
                    row.get::<_, i64>(6)?,
                    row.get::<_, i64>(7)?,
                    row.get::<_, Option<String>>(8)?,
                    row.get::<_, Option<String>>(9)?,
                    row.get::<_, String>(10)?,
                    row.get::<_, Option<String>>(11)?,
                    row.get::<_, String>(12)?,
                ))
            },
        )
        .optional()?;
    let Some((
        match_id,
        source_kind,
        source_identity,
        status,
        played_at,
        league_seq,
        player_count,
        rating_eligible,
        rating_ineligible_reason,
        replay_document_hash,
        replay_storage,
        replay_path,
        replay_verification,
    )) = header
    else {
        return Ok(None);
    };

    let status = match status.as_str() {
        "completed" => MatchStatus::Completed,
        "aborted" => MatchStatus::Aborted,
        "truncated" => MatchStatus::Truncated,
        other => {
            return Err(StudioLeagueError::Invalid(format!(
                "match `{match_id}` has unknown status `{other}`"
            )))
        }
    };
    let storage = match replay_storage.as_str() {
        "archive" => ReplayStorage::Archive,
        "in_place_reference" => ReplayStorage::InPlaceReference,
        "absent" => ReplayStorage::Absent,
        other => {
            return Err(StudioLeagueError::Invalid(format!(
                "match `{match_id}` has unknown replay storage `{other}`"
            )))
        }
    };
    let verification = match replay_verification.as_str() {
        "verified" => ReplayVerification::Verified,
        "invalid" => ReplayVerification::Invalid,
        "unavailable" => ReplayVerification::Unavailable,
        other => {
            return Err(StudioLeagueError::Invalid(format!(
                "match `{match_id}` has unknown replay verification `{other}`"
            )))
        }
    };

    let mut seats_statement = conn.prepare(
        "SELECT seat, participant_id, display_name, agent_name, score, rank, won
           FROM match_seats WHERE match_id = ?1 ORDER BY seat",
    )?;
    let seats = seats_statement
        .query_map([match_id.as_str()], |row| {
            Ok(MatchSeatDetailV1 {
                seat: row.get::<_, i64>(0)? as u32,
                participant_id: row.get(1)?,
                display_name: row.get(2)?,
                agent_name: row.get(3)?,
                score: row.get(4)?,
                rank: row.get(5)?,
                won: row.get::<_, i64>(6)? != 0,
            })
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;

    let mut events_statement = conn.prepare(
        "SELECT participant_id, elo_before, elo_after FROM rating_events
          WHERE match_id = ?1 ORDER BY participant_id",
    )?;
    let rating_events = events_statement
        .query_map([match_id.as_str()], |row| {
            Ok(MatchEloEventV1 {
                participant_id: row.get(0)?,
                elo_before: row.get(1)?,
                elo_after: row.get(2)?,
            })
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;

    // "Archived" is a statement about what the ledger recorded, not about the
    // filesystem: a recorded, verified, content-addressed object.
    let archived = storage == ReplayStorage::Archive
        && verification == ReplayVerification::Verified
        && replay_document_hash.is_some();

    Ok(Some(MatchDetailV1 {
        match_id,
        source_kind,
        source_identity,
        status,
        played_at,
        league_seq,
        player_count: player_count as u32,
        rating_eligible: rating_eligible != 0,
        rating_ineligible_reason,
        replay: ReplayBindingSummaryV1 {
            document_sha256: replay_document_hash,
            storage,
            verification,
            path: replay_path,
            archived,
        },
        seats,
        rating_events,
    }))
}

pub(crate) const GAMES_PAGE_ALL_SQL: &str =
    "SELECT m.match_id, m.league_seq, m.played_at, m.source_kind, m.status,
                      m.rating_eligible, m.rating_ineligible_reason,
                      m.replay_document_hash, m.replay_storage, m.replay_verification
                 FROM matches m
                WHERE m.league_seq < ?1
                ORDER BY m.league_seq DESC
                LIMIT ?2";

pub(crate) const GAMES_PAGE_FILTERED_SQL: &str =
    "SELECT m.match_id, m.league_seq, m.played_at, m.source_kind, m.status,
                      m.rating_eligible, m.rating_ineligible_reason,
                      m.replay_document_hash, m.replay_storage, m.replay_verification
                 FROM matches m
                WHERE m.league_seq < ?1
                  AND m.match_id IN (
                        SELECT s.match_id FROM match_seats s
                         WHERE s.participant_id = ?2)
                ORDER BY m.league_seq DESC
                LIMIT ?3";

///
/// `league_seq` is the ledger's monotonic position: it is assigned by an explicit
/// canonical sort ([`canonical_league_order`]) and **is not a date**. Historical
/// migration therefore produces a sequence that does not read like a calendar,
/// which is exactly why nothing here orders by `played_at`: a list sorted by a
/// wall clock that was backfilled out of order would interleave two eras, and a
/// list paged by `OFFSET` over a table that is still being written to would drop
/// or repeat rows every time a match arrives mid-scroll. Paging by
/// `league_seq DESC` with `league_seq < before` is stable under concurrent
/// ingestion by construction: new matches are appended *above* the cursor and the
/// page below it can never move.
pub const GAMES_PAGE_DEFAULT_LIMIT: u32 = 50;
/// A hard ceiling, not a preference: the Host answers requests serially, so an
/// unbounded page is how one request starves every other route.
pub const GAMES_PAGE_MAX_LIMIT: u32 = 100;

/// One page request over the recorded matches.
///
/// `before_league_seq` is the cursor: `None` asks for the newest page, and the
/// value returned as [`LeagueMatchPageV1::next_before_league_seq`] asks for the
/// page below it. It is deliberately *exclusive*, so the boundary row is not
/// repeated.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LeagueMatchPageRequestV1 {
    /// Validated as `1..=GAMES_PAGE_MAX_LIMIT`; `None` means the default.
    pub limit: Option<u32>,
    /// Exclusive cursor. `None` means "from the newest match".
    pub before_league_seq: Option<i64>,
    /// Restrict to the matches one participant appears in. `None` means all.
    pub participant_id: Option<String>,
}

/// One page of the games list, ordered by `league_seq` descending.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LeagueMatchPageV1 {
    pub matches: Vec<LeagueMatchListRowV1>,
    /// The cursor for the next page, or `None` when this page reached the end of
    /// the recording.
    ///
    /// It is derived from the **last row returned**, not from the request, so a
    /// page cannot hand back a cursor that pages past live data. `None` is a
    /// statement about the ledger at the moment it was read and is not a promise
    /// about the future: a match recorded later still belongs to a *newer* page,
    /// which is what "one page below" means.
    pub next_before_league_seq: Option<i64>,
}

/// One row of the games list — enough to render a row and reach a detail page.
///
/// This is deliberately **not** [`MatchDetailV1`]: a list page must not carry the
/// full match detail of every row it lists, and the seats here are the recorded
/// facts a row displays (who, on which seat, with what score, whether they won and
/// where they placed). Nothing is recomputed: no Elo, no winner derived from a
/// replay, no identity derived from a filename.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LeagueMatchListRowV1 {
    pub match_id: String,
    pub league_seq: i64,
    pub played_at: Option<i64>,
    pub source_kind: String,
    pub status: MatchStatus,
    pub rating_eligible: bool,
    pub rating_ineligible_reason: Option<String>,
    /// The verified ReplayV1 document SHA-256, when the ledger recorded one. This
    /// is the content address the replay route accepts — an identity, not a path.
    pub replay_document_sha256: Option<String>,
    /// Whether the ledger records a usable content-addressed archive object. Ledger
    /// state, not a filesystem probe; the replay route remains the authority on
    /// whether the bytes can actually be served.
    pub replay_archived: bool,
    pub seats: Vec<LeagueMatchListSeatV1>,
}

/// One seat of a listed match.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LeagueMatchListSeatV1 {
    pub seat: u32,
    pub participant_id: Option<String>,
    pub display_name: Option<String>,
    pub score: Option<i64>,
    pub rank: Option<i64>,
    pub won: bool,
}

/// Read one page of recorded matches, newest `league_seq` first.
///
/// The limit is validated by the read surface rather than clamped: a caller that
/// asks for zero or above the ceiling made a bad request, and should receive 400
/// at the HTTP adapter.
pub(crate) fn league_match_page(
    conn: &Connection,
    request: &LeagueMatchPageRequestV1,
) -> Result<LeagueMatchPageV1> {
    let limit = match request.limit {
        None => GAMES_PAGE_DEFAULT_LIMIT,
        Some(value) if (1..=GAMES_PAGE_MAX_LIMIT).contains(&value) => value,
        Some(value) => {
            return Err(StudioLeagueError::Invalid(format!(
                "the games limit must be between 1 and {GAMES_PAGE_MAX_LIMIT}, got {value}"
            )))
        }
    };
    let before = match request.before_league_seq {
        Some(value) if value > 0 => value,
        // A cursor of `0` can never match a row (`league_seq` starts at 1), which
        // would silently answer `empty` for a well-formed request. A negative
        // cursor is not a position at all. Both are the caller's mistake.
        Some(value) => {
            return Err(StudioLeagueError::Invalid(format!(
                "the games cursor must be a positive league_seq, got {value}"
            )))
        }
        None => i64::MAX,
    };

    // The match header query is set-based. An optional participant filter is a
    // match_seats-driven subquery rather than a correlated probe for every match:
    // rare participants stop at their own seat rows, while the unfiltered path
    // remains driven by matches_league_seq.
    let filtered = request.participant_id.is_some();
    let sql = if filtered {
        GAMES_PAGE_FILTERED_SQL
    } else {
        GAMES_PAGE_ALL_SQL
    };
    let mut bind_values: Vec<Box<dyn rusqlite::types::ToSql>> = vec![Box::new(before)];
    if let Some(participant_id) = &request.participant_id {
        bind_values.push(Box::new(participant_id.clone()));
    }
    bind_values.push(Box::new(limit as i64 + 1));
    let mut statement = conn.prepare(sql)?;
    let headers = statement
        .query_map(
            params_from_iter(bind_values.iter().map(|value| value.as_ref())),
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, Option<i64>>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, i64>(5)?,
                    row.get::<_, Option<String>>(6)?,
                    row.get::<_, Option<String>>(7)?,
                    row.get::<_, String>(8)?,
                    row.get::<_, String>(9)?,
                ))
            },
        )?
        .collect::<std::result::Result<Vec<_>, _>>()?;

    let header_ids: Vec<String> = headers.iter().map(|row| row.0.clone()).collect();
    let mut seats_by_match: HashMap<String, Vec<LeagueMatchListSeatV1>> = HashMap::new();
    if !header_ids.is_empty() {
        let placeholders = std::iter::repeat("?")
            .take(header_ids.len())
            .collect::<Vec<_>>()
            .join(",");
        let seat_sql = format!(
            "SELECT match_id, seat, participant_id, display_name, score, rank, won
               FROM match_seats WHERE match_id IN ({placeholders}) ORDER BY match_id, seat"
        );
        let bind_ids: Vec<Box<dyn rusqlite::types::ToSql>> = header_ids
            .iter()
            .map(|id| Box::new(id.clone()) as Box<dyn rusqlite::types::ToSql>)
            .collect();
        let mut seat_statement = conn.prepare(&seat_sql)?;
        let seat_rows = seat_statement
            .query_map(
                params_from_iter(bind_ids.iter().map(|value| value.as_ref())),
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        LeagueMatchListSeatV1 {
                            seat: row.get::<_, i64>(1)? as u32,
                            participant_id: row.get(2)?,
                            display_name: row.get(3)?,
                            score: row.get(4)?,
                            rank: row.get(5)?,
                            won: row.get::<_, i64>(6)? != 0,
                        },
                    ))
                },
            )?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        for (match_id, seat) in seat_rows {
            seats_by_match.entry(match_id).or_default().push(seat);
        }
    }

    let mut matches = Vec::with_capacity(headers.len());
    for (
        match_id,
        league_seq,
        played_at,
        source_kind,
        status,
        rating_eligible,
        rating_ineligible_reason,
        replay_document_hash,
        replay_storage,
        replay_verification,
    ) in headers
    {
        let status = match status.as_str() {
            "completed" => MatchStatus::Completed,
            "aborted" => MatchStatus::Aborted,
            "truncated" => MatchStatus::Truncated,
            other => {
                return Err(StudioLeagueError::Invalid(format!(
                    "match `{match_id}` has unknown status `{other}`"
                )))
            }
        };
        let storage = match replay_storage.as_str() {
            "archive" => ReplayStorage::Archive,
            "in_place_reference" => ReplayStorage::InPlaceReference,
            "absent" => ReplayStorage::Absent,
            other => {
                return Err(StudioLeagueError::Invalid(format!(
                    "match `{match_id}` has unknown replay storage `{other}`"
                )))
            }
        };
        let verification = match replay_verification.as_str() {
            "verified" => ReplayVerification::Verified,
            "invalid" => ReplayVerification::Invalid,
            "unavailable" => ReplayVerification::Unavailable,
            other => {
                return Err(StudioLeagueError::Invalid(format!(
                    "match `{match_id}` has unknown replay verification `{other}`"
                )))
            }
        };

        let seats = seats_by_match.remove(&match_id).unwrap_or_default();

        // "Archived" is ledger state — a recorded, verified, content-addressed
        // object — and is never a filesystem probe.
        let replay_archived = storage == ReplayStorage::Archive
            && verification == ReplayVerification::Verified
            && replay_document_hash.is_some();

        matches.push(LeagueMatchListRowV1 {
            match_id,
            league_seq,
            played_at,
            source_kind,
            status,
            rating_eligible: rating_eligible != 0,
            rating_ineligible_reason,
            replay_document_sha256: replay_document_hash,
            replay_archived,
            seats,
        });
    }

    let next_before_league_seq = if matches.len() > limit as usize {
        matches.pop();
        matches.last().map(|row| row.league_seq)
    } else {
        None
    };

    Ok(LeagueMatchPageV1 {
        matches,
        next_before_league_seq,
    })
}

pub const PARTICIPANT_PROFILE_SQL: &str = "WITH mine AS MATERIALIZED (
    SELECT match_id, seat FROM match_seats WHERE participant_id = ?1
),
games AS MATERIALIZED (
    SELECT m.match_id, m.status, m.completed_plies
      FROM matches m
     WHERE m.match_id IN (SELECT match_id FROM mine)
),
seat_counts AS (
    SELECT count(*) AS seat_appearances,
           coalesce(sum(CASE WHEN seat = 0 THEN 1 ELSE 0 END), 0) AS seat0,
           coalesce(sum(CASE WHEN seat = 1 THEN 1 ELSE 0 END), 0) AS seat1,
           coalesce(sum(CASE WHEN seat NOT IN (0, 1) THEN 1 ELSE 0 END), 0) AS other_seats
      FROM mine
),
rat AS (
    SELECT count(*) AS rated_games,
           coalesce(sum(CASE WHEN score = 1.0 THEN 1 ELSE 0 END), 0) AS rated_wins,
           coalesce(sum(CASE WHEN score = 0.5 THEN 1 ELSE 0 END), 0) AS rated_ties,
           coalesce(sum(CASE WHEN score = 0.0 THEN 1 ELSE 0 END), 0) AS rated_losses
      FROM rating_events
     WHERE participant_id = ?1
),
game_counts AS (
    SELECT count(*) AS recorded_games,
           coalesce(sum(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_games,
           count(CASE WHEN status = 'completed' AND completed_plies IS NOT NULL THEN 1 END) AS completed_plies_samples,
           avg(CASE WHEN status = 'completed' THEN completed_plies END) AS avg_completed_plies
      FROM games
)
SELECT p.participant_id, p.kind, p.display_name, p.current_elo,
       game_counts.recorded_games, game_counts.completed_games,
       game_counts.completed_plies_samples, game_counts.avg_completed_plies,
       rat.rated_games, rat.rated_wins, rat.rated_ties, rat.rated_losses,
       seat_counts.seat_appearances, seat_counts.seat0, seat_counts.seat1, seat_counts.other_seats
  FROM participants p
 CROSS JOIN game_counts
 CROSS JOIN rat
 CROSS JOIN seat_counts
 WHERE p.participant_id = ?1";

pub const PARTICIPANT_RATING_HISTORY_SQL: &str =
    "SELECT e.participant_id, e.league_seq, e.match_id,
       e.elo_before, e.elo_after, e.delta,
       e.opponent_id, coalesce(p.display_name, e.opponent_id) AS opponent_name,
       m.played_at
  FROM rating_events e
  JOIN matches m ON m.match_id = e.match_id
  LEFT JOIN participants p ON p.participant_id = e.opponent_id
 WHERE e.participant_id = ?1
   AND e.league_seq < ?2
 ORDER BY e.league_seq DESC
 LIMIT ?3";

pub const PARTICIPANT_OPPONENTS_SQL: &str = "WITH mine AS MATERIALIZED (
    SELECT match_id FROM match_seats WHERE participant_id = ?1
),
pairs AS (
    SELECT DISTINCT s.match_id, o.participant_id AS opponent_id
      FROM mine s
     CROSS JOIN match_seats o
     WHERE o.match_id = s.match_id
       AND o.participant_id IS NOT NULL
       AND o.participant_id <> ?1
),
rec AS (
    SELECT opponent_id, count(*) AS recorded_games
      FROM pairs
     GROUP BY opponent_id
),
rat AS (
    SELECT opponent_id,
           count(*) AS rated_games,
           coalesce(sum(CASE WHEN score = 1.0 THEN 1 ELSE 0 END), 0) AS rated_wins,
           coalesce(sum(CASE WHEN score = 0.5 THEN 1 ELSE 0 END), 0) AS rated_ties,
           coalesce(sum(CASE WHEN score = 0.0 THEN 1 ELSE 0 END), 0) AS rated_losses
      FROM rating_events
     WHERE participant_id = ?1
     GROUP BY opponent_id
)
SELECT r.opponent_id,
       p.display_name,
       r.recorded_games,
       coalesce(t.rated_games, 0) AS rated_games,
       coalesce(t.rated_wins, 0) AS rated_wins,
       coalesce(t.rated_ties, 0) AS rated_ties,
       coalesce(t.rated_losses, 0) AS rated_losses
  FROM rec r
  JOIN participants p ON p.participant_id = r.opponent_id
  LEFT JOIN rat t USING(opponent_id)
 WHERE r.opponent_id > ?2
 ORDER BY r.opponent_id ASC
 LIMIT ?3";

pub const RATING_HISTORY_DEFAULT_LIMIT: u32 = 100;
pub const RATING_HISTORY_MAX_LIMIT: u32 = 200;

pub const OPPONENTS_PAGE_DEFAULT_LIMIT: u32 = 20;
pub const OPPONENTS_PAGE_MAX_LIMIT: u32 = 50;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ParticipantEloOriginV1 {
    Rated,
    Initial,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantProfileEloV1 {
    pub value: f64,
    pub display_rounded: i32,
    pub origin: ParticipantEloOriginV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParticipantProfileSeatsV1 {
    pub appearances: u32,
    pub seat0: u32,
    pub seat1: u32,
    pub other: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantProfilePlyAggregateV1 {
    pub availability: String,
    pub value: Option<f64>,
    pub observed_completed_games: u32,
    pub total_completed_games: u32,
    pub unit: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParticipantProfileUnavailableMetricV1 {
    pub availability: String,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantProfileV1 {
    pub participant_id: String,
    pub kind: ParticipantKind,
    pub display_name: String,
    pub elo: ParticipantProfileEloV1,
    pub provisional: bool,
    pub recorded_games: u32,
    pub rated_games: u32,
    pub rated_wins: u32,
    pub rated_ties: u32,
    pub rated_losses: u32,
    pub seats: ParticipantProfileSeatsV1,
    pub completed_plies: ParticipantProfilePlyAggregateV1,
    pub main_turns: ParticipantProfileUnavailableMetricV1,
    pub gameplay: ParticipantProfileUnavailableMetricV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParticipantRatingHistoryRequestV1 {
    pub participant_id: String,
    pub limit: Option<u32>,
    pub before_league_seq: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantRatingHistoryPointV1 {
    pub participant_id: String,
    pub league_seq: i64,
    pub match_id: String,
    pub elo_before: f64,
    pub elo_after: f64,
    pub delta: f64,
    pub opponent_id: String,
    pub opponent_name: String,
    pub played_at: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantRatingHistoryPageV1 {
    pub participant_id: String,
    pub points: Vec<ParticipantRatingHistoryPointV1>,
    pub next_before_league_seq: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParticipantOpponentPageRequestV1 {
    pub participant_id: String,
    pub limit: Option<u32>,
    pub after_opponent_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParticipantOpponentRowV1 {
    pub opponent_id: String,
    pub display_name: String,
    pub recorded_games: u32,
    pub rated_games: u32,
    pub rated_wins: u32,
    pub rated_ties: u32,
    pub rated_losses: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParticipantOpponentPageV1 {
    pub participant_id: String,
    pub opponents: Vec<ParticipantOpponentRowV1>,
    pub next_after_opponent_id: Option<String>,
}

pub(crate) fn participant_profile(
    conn: &Connection,
    participant_id: &str,
) -> Result<Option<ParticipantProfileV1>> {
    let config = protocol_rating_config();
    let mut stmt = conn.prepare(PARTICIPANT_PROFILE_SQL)?;
    let mut rows = stmt.query(params![participant_id])?;
    let row = match rows.next()? {
        Some(row) => row,
        None => return Ok(None),
    };

    let id: String = row.get(0)?;
    let kind_str: String = row.get(1)?;
    let kind = ParticipantKind::from_db(&kind_str)?;
    let display_name: String = row.get(2)?;
    let raw_current_elo: Option<f64> = row.get(3)?;
    let recorded_games: i64 = row.get(4)?;
    let completed_games: i64 = row.get(5)?;
    let completed_plies_samples: i64 = row.get(6)?;
    let avg_completed_plies: Option<f64> = row.get(7)?;
    let rated_games: i64 = row.get(8)?;
    let rated_wins: i64 = row.get(9)?;
    let rated_ties: i64 = row.get(10)?;
    let rated_losses: i64 = row.get(11)?;
    let seat_appearances: i64 = row.get(12)?;
    let seat0: i64 = row.get(13)?;
    let seat1: i64 = row.get(14)?;
    let other_seats: i64 = row.get(15)?;

    let elo = match (rated_games, raw_current_elo) {
        (0, None) => ParticipantProfileEloV1 {
            value: config.initial_elo as f64,
            display_rounded: config.initial_elo as i32,
            origin: ParticipantEloOriginV1::Initial,
        },
        (0, Some(val)) => ParticipantProfileEloV1 {
            value: val,
            display_rounded: val.round() as i32,
            origin: ParticipantEloOriginV1::Initial,
        },
        (n, Some(val)) if n > 0 && val.is_finite() => ParticipantProfileEloV1 {
            value: val,
            display_rounded: val.round() as i32,
            origin: ParticipantEloOriginV1::Rated,
        },
        (n, _) => {
            return Err(StudioLeagueError::Invalid(format!(
                "participant `{id}` has {n} rated games but non-finite or missing current_elo"
            )));
        }
    };

    let (plies_availability, plies_value) = if completed_games == 0 || completed_plies_samples == 0
    {
        ("unavailable", None)
    } else if completed_plies_samples < completed_games {
        ("partial", avg_completed_plies)
    } else {
        ("available", avg_completed_plies)
    };

    Ok(Some(ParticipantProfileV1 {
        participant_id: id,
        kind,
        display_name,
        elo,
        provisional: (rated_games as u32) < config.provisional_threshold,
        recorded_games: recorded_games as u32,
        rated_games: rated_games as u32,
        rated_wins: rated_wins as u32,
        rated_ties: rated_ties as u32,
        rated_losses: rated_losses as u32,
        seats: ParticipantProfileSeatsV1 {
            appearances: seat_appearances as u32,
            seat0: seat0 as u32,
            seat1: seat1 as u32,
            other: other_seats as u32,
        },
        completed_plies: ParticipantProfilePlyAggregateV1 {
            availability: plies_availability.to_string(),
            value: plies_value,
            observed_completed_games: completed_plies_samples as u32,
            total_completed_games: completed_games as u32,
            unit: "decision_plies".to_string(),
        },
        main_turns: ParticipantProfileUnavailableMetricV1 {
            availability: "unavailable".to_string(),
            reason: "not_recorded".to_string(),
        },
        gameplay: ParticipantProfileUnavailableMetricV1 {
            availability: "unavailable".to_string(),
            reason: "no_authoritative_builder".to_string(),
        },
    }))
}

pub(crate) fn participant_rating_history(
    conn: &Connection,
    request: &ParticipantRatingHistoryRequestV1,
) -> Result<Option<ParticipantRatingHistoryPageV1>> {
    let exists: bool = conn
        .query_row(
            "SELECT 1 FROM participants WHERE participant_id = ?1",
            params![request.participant_id],
            |_| Ok(true),
        )
        .optional()?
        .unwrap_or(false);
    if !exists {
        return Ok(None);
    }

    let limit = match request.limit {
        None => RATING_HISTORY_DEFAULT_LIMIT,
        Some(val) if (1..=RATING_HISTORY_MAX_LIMIT).contains(&val) => val,
        Some(val) => {
            return Err(StudioLeagueError::Invalid(format!(
                "rating history limit must be between 1 and {RATING_HISTORY_MAX_LIMIT}, got {val}"
            )))
        }
    };

    let before = match request.before_league_seq {
        None => i64::MAX,
        Some(val) if val > 0 => val,
        Some(val) => {
            return Err(StudioLeagueError::Invalid(format!(
                "rating history cursor must be a positive league_seq, got {val}"
            )))
        }
    };

    let mut stmt = conn.prepare(PARTICIPANT_RATING_HISTORY_SQL)?;
    let mut points: Vec<ParticipantRatingHistoryPointV1> = stmt
        .query_map(
            params![request.participant_id, before, (limit + 1) as i64],
            |row| {
                Ok(ParticipantRatingHistoryPointV1 {
                    participant_id: row.get(0)?,
                    league_seq: row.get(1)?,
                    match_id: row.get(2)?,
                    elo_before: row.get(3)?,
                    elo_after: row.get(4)?,
                    delta: row.get(5)?,
                    opponent_id: row.get(6)?,
                    opponent_name: row.get(7)?,
                    played_at: row.get(8)?,
                })
            },
        )?
        .collect::<std::result::Result<Vec<_>, _>>()?;

    let next_before_league_seq = if points.len() > limit as usize {
        points.pop();
        points.last().map(|p| p.league_seq)
    } else {
        None
    };

    Ok(Some(ParticipantRatingHistoryPageV1 {
        participant_id: request.participant_id.clone(),
        points,
        next_before_league_seq,
    }))
}

pub(crate) fn participant_opponents(
    conn: &Connection,
    request: &ParticipantOpponentPageRequestV1,
) -> Result<Option<ParticipantOpponentPageV1>> {
    let exists: bool = conn
        .query_row(
            "SELECT 1 FROM participants WHERE participant_id = ?1",
            params![request.participant_id],
            |_| Ok(true),
        )
        .optional()?
        .unwrap_or(false);
    if !exists {
        return Ok(None);
    }

    let limit = match request.limit {
        None => OPPONENTS_PAGE_DEFAULT_LIMIT,
        Some(val) if (1..=OPPONENTS_PAGE_MAX_LIMIT).contains(&val) => val,
        Some(val) => {
            return Err(StudioLeagueError::Invalid(format!(
                "opponents limit must be between 1 and {OPPONENTS_PAGE_MAX_LIMIT}, got {val}"
            )))
        }
    };

    let after = request.after_opponent_id.as_deref().unwrap_or("");

    let mut stmt = conn.prepare(PARTICIPANT_OPPONENTS_SQL)?;
    let mut opponents: Vec<ParticipantOpponentRowV1> = stmt
        .query_map(
            params![request.participant_id, after, (limit + 1) as i64],
            |row| {
                let recorded: i64 = row.get(2)?;
                let rated: i64 = row.get(3)?;
                let wins: i64 = row.get(4)?;
                let ties: i64 = row.get(5)?;
                let losses: i64 = row.get(6)?;
                Ok(ParticipantOpponentRowV1 {
                    opponent_id: row.get(0)?,
                    display_name: row.get(1)?,
                    recorded_games: recorded as u32,
                    rated_games: rated as u32,
                    rated_wins: wins as u32,
                    rated_ties: ties as u32,
                    rated_losses: losses as u32,
                })
            },
        )?
        .collect::<std::result::Result<Vec<_>, _>>()?;

    let next_after_opponent_id = if opponents.len() > limit as usize {
        opponents.pop();
        opponents.last().map(|row| row.opponent_id.clone())
    } else {
        None
    };

    Ok(Some(ParticipantOpponentPageV1 {
        participant_id: request.participant_id.clone(),
        opponents,
        next_after_opponent_id,
    }))
}
