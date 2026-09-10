//! The match ledger and its deterministic Elo events.
//!
//! Two invariants drive this module:
//! * `league_seq` — not arrival or thread order — fixes the Elo order, so a
//!   rebuild from the same sources reproduces the same Elo history.
//! * ingestion is idempotent on `(source_kind, source_identity)`, so a repeated
//!   scan of the same artifacts can never double-rate a match.

use crate::eligibility::{evaluate_eligibility, EligibilityInput, RatingEligibility};
use crate::elo::{pair_score_a, plan_pair_update};
use crate::error::{Result, StudioLeagueError};
use crate::match_record::{ReplayVerification, StudioMatchRecordV1};
use crate::participant::{
    declare_alias, new_participant_id, resolve_alias, resolve_engine_participant, ParticipantKind,
};
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

/// The frozen Studio rating identity. Recorded in `league_meta` so a rebuild can
/// prove it used the same rule.
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

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LeaderboardRow {
    pub participant_id: String,
    pub kind: ParticipantKind,
    pub display_name: String,
    pub elo: i32,
    /// Matches that actually moved Elo.
    pub rated_games: u32,
    /// Every match this participant appears in, eligible or not.
    pub recorded_games: u32,
    pub wins: u32,
    pub ties: u32,
    pub losses: u32,
    pub provisional: bool,
}

/// Insert one finished match, resolving identities and applying Elo if eligible.
pub fn ingest_match(
    conn: &mut Connection,
    config: &StudioRatingConfigV1,
    record: &StudioMatchRecordV1,
) -> Result<IngestOutcome> {
    config.validate()?;
    let tx = conn.transaction()?;
    let existing: Option<String> = tx
        .query_row(
            "SELECT match_id FROM matches WHERE source_kind = ?1 AND source_identity = ?2",
            params![record.source_kind, record.source_identity],
            |row| row.get(0),
        )
        .optional()?;
    if let Some(match_id) = existing {
        return Ok(IngestOutcome::AlreadyPresent { match_id });
    }

    let now = now_epoch_seconds();
    let match_id = record.match_id();

    // Resolve every seat before deciding eligibility: an identity the league
    // cannot determine must block rating rather than be guessed.
    let mut resolved: Vec<Option<String>> = Vec::with_capacity(record.seats.len());
    for seat in &record.seats {
        let id = match (&seat.participant_id, &seat.identity) {
            (Some(explicit), _) => Some(explicit.clone()),
            (None, Some(identity)) => {
                let key = identity.key();
                match resolve_alias(&tx, &key)? {
                    Some(existing) => Some(existing),
                    None => {
                        let name = seat
                            .display_name
                            .clone()
                            .unwrap_or_else(|| identity.agent_name.clone());
                        Some(resolve_engine_participant(&tx, identity, &name, now)?)
                    }
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
        config,
    );

    let next_seq: i64 = tx.query_row(
        "SELECT COALESCE(MAX(league_seq), 0) + 1 FROM matches",
        [],
        |row| row.get(0),
    )?;

    let scores = record.scores();
    let winners = record.winners();
    tx.execute(
        "INSERT INTO matches
            (match_id, source_kind, source_identity, source_path, league_seq, played_at,
             ruleset_fingerprint, engine_version, player_count, status, scores_json,
             winners_json, completed_plies, main_turn_count, replay_document_hash,
             replay_final_hash, replay_storage, replay_path, replay_verification,
             rating_eligible, rating_ineligible_reason, detail_metrics_available, ingested_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17,
                 ?18, ?19, ?20, ?21, ?22, ?23)",
        params![
            match_id,
            record.source_kind,
            record.source_identity,
            record.source_path,
            next_seq,
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
        apply_rating_for_match(&tx, config, &match_id, next_seq)?
    } else {
        0
    };

    tx.execute(
        "INSERT OR REPLACE INTO ingest_sources
            (source_kind, source_identity, first_seen_at, document_hash)
         VALUES (?1, ?2, ?3, ?4)",
        params![
            record.source_kind,
            record.source_identity,
            now,
            record.replay.document_hash
        ],
    )?;

    tx.commit()?;
    Ok(IngestOutcome::Inserted {
        match_id,
        rating_events,
    })
}

/// Write the two Elo events for an eligible 1v1 match and move current Elo.
pub fn apply_rating_for_match(
    tx: &Transaction<'_>,
    config: &StudioRatingConfigV1,
    match_id: &str,
    league_seq: i64,
) -> Result<usize> {
    let seats: Vec<(i64, Option<String>, i64)> = {
        let mut stmt = tx.prepare(
            "SELECT seat, participant_id, won FROM match_seats WHERE match_id = ?1 ORDER BY seat ASC",
        )?;
        let rows = stmt
            .query_map(params![match_id], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, Option<String>>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        rows
    };
    if seats.len() != 2 {
        return Ok(0);
    }
    let (Some(a), Some(b)) = (seats[0].1.clone(), seats[1].1.clone()) else {
        return Ok(0);
    };

    let rating_a = participant_elo(tx, &a, config)?;
    let rating_b = participant_elo(tx, &b, config)?;
    let score_a = pair_score_a(seats[0].2 != 0, seats[1].2 != 0)?;
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

/// Current Elo, falling back to the config's initial value for a fresh participant.
pub fn participant_elo(
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

/// Recompute every Elo event from the ledger, in `league_seq` order.
///
/// This is the determinism proof: if it reproduces the same events, the stored
/// history contains nothing that depends on write order.
pub fn rebuild_ratings(conn: &mut Connection, config: &StudioRatingConfigV1) -> Result<u64> {
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

/// The leaderboard, ordered by Studio Elo. Numbers come from the database only;
/// no caller may recompute them.
pub fn leaderboard(
    conn: &Connection,
    config: &StudioRatingConfigV1,
) -> Result<Vec<LeaderboardRow>> {
    let mut stmt = conn.prepare(
        "SELECT p.participant_id, p.kind, p.display_name,
                (SELECT COUNT(*) FROM match_seats s WHERE s.participant_id = p.participant_id),
                (SELECT COUNT(*) FROM match_seats s
                   JOIN matches m ON m.match_id = s.match_id
                  WHERE s.participant_id = p.participant_id AND m.rating_eligible = 1),
                (SELECT COUNT(*) FROM match_seats s
                  WHERE s.participant_id = p.participant_id AND s.won = 1
                    AND (SELECT COUNT(*) FROM match_seats s2
                          WHERE s2.match_id = s.match_id AND s2.won = 1) = 1),
                (SELECT COUNT(*) FROM match_seats s
                  WHERE s.participant_id = p.participant_id AND s.won = 1
                    AND (SELECT COUNT(*) FROM match_seats s2
                          WHERE s2.match_id = s.match_id AND s2.won = 1) > 1),
                p.current_elo
           FROM participants p",
    )?;
    let mut rows: Vec<LeaderboardRow> = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, i64>(6)?,
                row.get::<_, Option<f64>>(7)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(|(id, kind, name, recorded, rated, wins, ties, elo)| {
            let rated = rated as u32;
            Ok(LeaderboardRow {
                participant_id: id,
                kind: ParticipantKind::from_db(&kind)?,
                display_name: name,
                elo: elo.unwrap_or(config.initial_elo as f64).round() as i32,
                rated_games: rated,
                recorded_games: recorded as u32,
                wins: wins as u32,
                ties: ties as u32,
                losses: recorded as u32 - wins as u32 - ties as u32,
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

/// Convenience for tests and the importer: declare an explicit merge.
pub fn alias_participants(
    conn: &Connection,
    alias_key: &str,
    participant_id: &str,
    note: &str,
) -> Result<()> {
    declare_alias(conn, alias_key, participant_id, note)
}

/// Unused-but-reserved id generator, exported so importers never invent one.
pub fn fresh_participant_id() -> String {
    new_participant_id()
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
    config: &StudioRatingConfigV1,
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
        config,
    )
}
