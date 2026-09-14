//! A read-only Studio League session.
//!
//! The ledger owns this connection. A caller gets typed reads, and no way to
//! write, to name the connection, or to reach SQL.
//!
//! # Why this exists
//!
//! The read-only Host API serves ledger reads, but `rusqlite` is deliberately a
//! *test-only* dependency of the CLI that hosts it. Without a type like this the
//! Host would have to be given either a raw connection or SQL, and hand-written
//! SQL over the ledger is how a consumer becomes a **second ledger authority** —
//! the shortcut class closed in Slice 3 Repair 2. This type is deliberately
//! symmetric with [`CompletionLeagueV1`](crate::CompletionLeagueV1): one
//! constructor, private state, no accessor. The difference is that it is
//! read-only *by construction*.
//!
//! # It cannot write, and it cannot invent a league
//!
//! The database is opened with `SQLITE_OPEN_READ_ONLY`, so it cannot create a
//! database, create a table, or write a row, and the schema version is checked
//! on open — a missing file or a foreign SQLite database fails closed instead of
//! being served as an empty league.

use rusqlite::{Connection, OpenFlags};
use std::path::PathBuf;

use crate::error::{Result, StudioLeagueError};
use crate::ledger::{leaderboard, match_detail, LeaderboardRow, MatchDetailV1};
use crate::paths::StudioLeaguePathsV1;
use crate::replay_archive::read_archived_replay;
use crate::schema::{schema_version, STUDIO_LEAGUE_SCHEMA_VERSION};

/// An opened, read-only view of one Studio League installation.
#[derive(Debug)]
pub struct StudioLeagueReaderV1 {
    conn: Connection,
    replay_root: PathBuf,
}

/// Open a read-only session over an existing league.
///
/// Fails closed when the database is missing, unreadable, or not a Studio League
/// database of the current schema. It never creates anything.
pub fn open_studio_league_reader(paths: &StudioLeaguePathsV1) -> Result<StudioLeagueReaderV1> {
    let db = paths.db();
    let conn =
        Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|error| {
            StudioLeagueError::Invalid(format!(
                "no readable Studio League database at `{}`: {error}",
                db.display()
            ))
        })?;
    let version = schema_version(&conn).map_err(|error| {
        StudioLeagueError::Invalid(format!(
            "`{}` is not a Studio League database: {error}",
            db.display()
        ))
    })?;
    if version != STUDIO_LEAGUE_SCHEMA_VERSION {
        return Err(StudioLeagueError::Invalid(format!(
            "`{}` has Studio League schema version {version}, expected {STUDIO_LEAGUE_SCHEMA_VERSION}",
            db.display()
        )));
    }
    Ok(StudioLeagueReaderV1 {
        conn,
        replay_root: paths.replay_root().to_path_buf(),
    })
}

impl StudioLeagueReaderV1 {
    /// The league table, exactly as the ledger derives it. Nothing is
    /// recomputed here: no Elo, no wins, no provisional flag.
    pub fn leaderboard(&self) -> Result<Vec<LeaderboardRow>> {
        leaderboard(&self.conn)
    }

    /// One match in full. `Ok(None)` when it is not recorded at all.
    pub fn match_detail(&self, match_id: &str) -> Result<Option<MatchDetailV1>> {
        match_detail(&self.conn, match_id)
    }

    /// The archived ReplayV1 document for a verified content address.
    ///
    /// The argument is a document SHA-256 and nothing else: the bytes are located
    /// by replay root plus content address, so a caller cannot ask for an
    /// arbitrary path.
    pub fn read_replay(&self, document_sha256: &str) -> Result<Vec<u8>> {
        read_archived_replay(&self.replay_root, document_sha256)
    }
}
