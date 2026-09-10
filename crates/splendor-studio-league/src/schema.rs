//! SQLite schema for the Studio League long-term index.
//!
//! The database is **derived state**: every row is reconstructible from the
//! original arena/evaluation/human-play artifacts, so it is safe to delete and
//! rebuild. Nothing in this module may become the only copy of a fact.

use crate::error::{Result, StudioLeagueError};
use rusqlite::Connection;
use std::path::Path;

/// Bumped whenever the DDL below changes shape.
pub const STUDIO_LEAGUE_SCHEMA_VERSION: u32 = 1;

pub const SCHEMA_VERSION_META_KEY: &str = "schema_version";
pub const RATING_CONFIG_META_KEY: &str = "studio_rating_config";

const DDL: &str = r#"
CREATE TABLE IF NOT EXISTS league_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS participants (
    participant_id TEXT PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('human','engine')),
    display_name   TEXT NOT NULL,
    -- Exact policy identity for engines (`agent_name@agent_version`); NULL for
    -- humans and for the reserved unassigned-human pseudo participant.
    identity_key   TEXT UNIQUE,
    current_elo    REAL,
    created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS participant_aliases (
    alias_key      TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL REFERENCES participants(participant_id),
    note           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS matches (
    match_id                 TEXT PRIMARY KEY,
    source_kind              TEXT NOT NULL,
    source_identity          TEXT NOT NULL,
    source_path              TEXT,
    -- Monotonic position that fixes the Elo order; never derived from arrival time.
    league_seq               INTEGER NOT NULL UNIQUE,
    played_at                INTEGER,
    ruleset_fingerprint      TEXT NOT NULL,
    engine_version           TEXT,
    player_count             INTEGER NOT NULL,
    status                   TEXT NOT NULL CHECK (status IN ('completed','aborted','truncated')),
    scores_json              TEXT,
    winners_json             TEXT,
    completed_plies          INTEGER,
    main_turn_count          INTEGER,
    replay_document_hash     TEXT,
    replay_final_hash        TEXT,
    replay_storage           TEXT NOT NULL CHECK (replay_storage IN ('archive','in_place_reference','absent')),
    replay_path              TEXT,
    replay_verification      TEXT NOT NULL CHECK (replay_verification IN ('verified','invalid','unavailable')),
    rating_eligible          INTEGER NOT NULL,
    rating_ineligible_reason TEXT,
    detail_metrics_available INTEGER NOT NULL,
    ingested_at              INTEGER NOT NULL,
    UNIQUE (source_kind, source_identity)
);

CREATE TABLE IF NOT EXISTS match_seats (
    match_id       TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    seat           INTEGER NOT NULL,
    participant_id TEXT REFERENCES participants(participant_id),
    agent_name     TEXT,
    agent_version  TEXT,
    display_name   TEXT,
    score          INTEGER,
    rank           INTEGER,
    won            INTEGER NOT NULL,
    PRIMARY KEY (match_id, seat)
);

-- Only ever populated for replay-backed matches (invariant 7/12).
CREATE TABLE IF NOT EXISTS match_gameplay_stats (
    match_id         TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    seat             INTEGER NOT NULL,
    tier1_vp         INTEGER NOT NULL,
    tier2_vp         INTEGER NOT NULL,
    tier3_vp         INTEGER NOT NULL,
    noble_vp         INTEGER NOT NULL,
    final_prestige   INTEGER NOT NULL,
    tier1_purchases  INTEGER NOT NULL,
    tier2_purchases  INTEGER NOT NULL,
    tier3_purchases  INTEGER NOT NULL,
    nobles           INTEGER NOT NULL,
    take_tokens      INTEGER NOT NULL,
    buy_cards        INTEGER NOT NULL,
    reserve_cards    INTEGER NOT NULL,
    metric_integrity TEXT NOT NULL CHECK (metric_integrity IN ('ok','failed')),
    PRIMARY KEY (match_id, seat)
);

CREATE TABLE IF NOT EXISTS rating_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id       TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    league_seq     INTEGER NOT NULL,
    participant_id TEXT NOT NULL REFERENCES participants(participant_id),
    opponent_id    TEXT NOT NULL,
    elo_before     REAL NOT NULL,
    elo_after      REAL NOT NULL,
    delta          REAL NOT NULL,
    score          REAL NOT NULL,
    expected       REAL NOT NULL,
    k_factor       INTEGER NOT NULL,
    algorithm      TEXT NOT NULL,
    UNIQUE (match_id, participant_id)
);

CREATE TABLE IF NOT EXISTS ingest_sources (
    source_kind     TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    first_seen_at   INTEGER NOT NULL,
    document_hash   TEXT,
    PRIMARY KEY (source_kind, source_identity)
);

CREATE INDEX IF NOT EXISTS matches_league_seq ON matches (league_seq);
CREATE INDEX IF NOT EXISTS rating_events_participant ON rating_events (participant_id, league_seq);
"#;

/// Open (creating if needed) the league database at `path`.
pub fn open_league(path: &Path) -> Result<Connection> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let conn = Connection::open(path)?;
    initialise(&conn)?;
    Ok(conn)
}

/// An in-memory league, for tests and for read-only exploration.
pub fn open_in_memory() -> Result<Connection> {
    let conn = Connection::open_in_memory()?;
    initialise(&conn)?;
    Ok(conn)
}

/// Create the schema and record its version. Idempotent.
pub fn initialise(conn: &Connection) -> Result<()> {
    conn.execute_batch("PRAGMA foreign_keys = ON;")?;
    conn.execute_batch(DDL)?;
    let existing: Option<String> = conn
        .query_row(
            "SELECT value FROM league_meta WHERE key = ?1",
            rusqlite::params![SCHEMA_VERSION_META_KEY],
            |row| row.get(0),
        )
        .ok();
    match existing {
        None => {
            conn.execute(
                "INSERT INTO league_meta (key, value) VALUES (?1, ?2)",
                rusqlite::params![
                    SCHEMA_VERSION_META_KEY,
                    STUDIO_LEAGUE_SCHEMA_VERSION.to_string()
                ],
            )?;
            Ok(())
        }
        Some(value) => {
            let found: u32 = value
                .parse()
                .map_err(|_| StudioLeagueError::Invalid(format!("schema_version `{value}`")))?;
            if found != STUDIO_LEAGUE_SCHEMA_VERSION {
                return Err(StudioLeagueError::Invalid(format!(
                    "studio league schema version {found} does not match this build's version {STUDIO_LEAGUE_SCHEMA_VERSION}; the index is derived, so delete and rebuild it"
                )));
            }
            Ok(())
        }
    }
}

pub fn schema_version(conn: &Connection) -> Result<u32> {
    let value: String = conn.query_row(
        "SELECT value FROM league_meta WHERE key = ?1",
        rusqlite::params![SCHEMA_VERSION_META_KEY],
        |row| row.get(0),
    )?;
    value
        .parse()
        .map_err(|_| StudioLeagueError::Invalid(format!("schema_version `{value}`")))
}

/// Set a `league_meta` value.
pub fn set_meta(conn: &Connection, key: &str, value: &str) -> Result<()> {
    conn.execute(
        "INSERT OR REPLACE INTO league_meta (key, value) VALUES (?1, ?2)",
        rusqlite::params![key, value],
    )?;
    Ok(())
}

pub fn get_meta(conn: &Connection, key: &str) -> Result<Option<String>> {
    use rusqlite::OptionalExtension;
    Ok(conn
        .query_row(
            "SELECT value FROM league_meta WHERE key = ?1",
            rusqlite::params![key],
            |row| row.get::<_, String>(0),
        )
        .optional()?)
}
