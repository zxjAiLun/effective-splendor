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
use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde::{Deserialize, Serialize};
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
pub fn leaderboard(conn: &Connection) -> Result<Vec<LeaderboardRow>> {
    let config = protocol_rating_config();
    let mut stmt = conn.prepare(
        "SELECT p.participant_id, p.kind, p.display_name, p.current_elo,
                (SELECT COUNT(DISTINCT s.match_id) FROM match_seats s
                  WHERE s.participant_id = p.participant_id),
                (SELECT COUNT(*) FROM match_seats s
                   JOIN matches m ON m.match_id = s.match_id
                  WHERE s.participant_id = p.participant_id AND m.rating_eligible = 1),
                (SELECT COUNT(*) FROM match_seats s
                   JOIN matches m ON m.match_id = s.match_id
                  WHERE s.participant_id = p.participant_id AND m.rating_eligible = 1
                    AND s.won = 1
                    AND (SELECT COUNT(*) FROM match_seats s2
                          WHERE s2.match_id = s.match_id AND s2.won = 1) = 1),
                (SELECT COUNT(*) FROM match_seats s
                   JOIN matches m ON m.match_id = s.match_id
                  WHERE s.participant_id = p.participant_id AND m.rating_eligible = 1
                    AND s.won = 1
                    AND (SELECT COUNT(*) FROM match_seats s2
                          WHERE s2.match_id = s.match_id AND s2.won = 1) > 1)
           FROM participants p",
    )?;
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
