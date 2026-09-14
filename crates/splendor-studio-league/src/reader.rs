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
//!
//! # Reading still respects the authority evidence
//!
//! A schema version is the weakest of the three integrity contracts this
//! database carries, so opening a reader checks the other two as well, with pure
//! reads and zero mutation:
//!
//! * **the rating protocol identity** — the persisted `studio_rating_config`
//!   evidence must equal this build's [`protocol_rating_config`]. A derived
//!   database written by a different Studio Elo protocol must be rebuilt, not
//!   served: [`ensure_rating_config`](crate::ensure_rating_config) already fails
//!   closed on that mismatch for every write path, and a read path that skipped
//!   it would present another protocol's Elo as if this build stood behind it.
//! * **the durable identity authority** — the identity manifest on disk is
//!   *authored* state and the SQLite index is *derived* from it, so the manifest
//!   is loaded strictly (never [`IdentityManifestV1::load_or_recover`], which can
//!   heal the primary and therefore writes) and its canonical hash must equal the
//!   hash recorded in the database. A rename or an alias added but not yet
//!   rebuilt then fails closed instead of being served as a stale leaderboard.
//!
//! Both are the same comparisons [`sync_identity_manifest`] already enforces on
//! the write side, so the read and write paths agree on what this database is.

use rusqlite::{Connection, OpenFlags};
use std::path::PathBuf;

use crate::error::{Result, StudioLeagueError};
use crate::identity_manifest::IdentityManifestV1;
use crate::ledger::{
    leaderboard, match_detail, protocol_rating_config, stored_rating_config, LeaderboardRow,
    MatchDetailV1,
};
use crate::participant::stored_identity_manifest_hash;
use crate::paths::StudioLeaguePathsV1;
use crate::replay_archive::{archived_replay_present, read_archived_replay};
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
    // The rating protocol identity is integrity evidence, not a setting: a
    // database written by another protocol must be rebuilt rather than served.
    let stored = stored_rating_config(&conn)?.ok_or_else(|| {
        StudioLeagueError::Invalid(format!(
            "`{}` has no Studio rating config integrity evidence; rebuild the derived database",
            db.display()
        ))
    })?;
    let protocol = protocol_rating_config();
    if stored != protocol {
        return Err(StudioLeagueError::RatingConfig(format!(
            "`{}` was built with {} but this build's Studio Elo protocol is {}; the index is derived, so rebuild it",
            db.display(),
            stored.to_json()?,
            protocol.to_json()?
        )));
    }

    // The durable manifest is the authored identity authority and this database
    // is derived from it, so the recorded hash must still match the manifest on
    // disk. `load` is the strict pure read; `load_or_recover` could heal the
    // primary, which a read-only session must not do.
    let identity_path = paths.identity();
    let manifest = IdentityManifestV1::load(identity_path)?.ok_or_else(|| {
        StudioLeagueError::Invalid(format!(
            "identity manifest `{}` does not exist; rebuild the derived database",
            identity_path.display()
        ))
    })?;
    let expected_hash = manifest.hash()?;
    match stored_identity_manifest_hash(&conn)? {
        Some(stored) if stored == expected_hash => {}
        Some(stored) => {
            return Err(StudioLeagueError::Invalid(format!(
                "identity manifest hash `{expected_hash}` disagrees with stored database evidence `{stored}`; rebuild the derived database to apply identity or alias changes"
            )));
        }
        None => {
            return Err(StudioLeagueError::Invalid(format!(
                "`{}` has no identity manifest hash integrity evidence; rebuild the derived database",
                db.display()
            )));
        }
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

    /// Whether the archive holds an object at this content address.
    ///
    /// [`read_replay`](Self::read_replay) fails both when there is no such object
    /// and when the archive holds one it cannot serve. Only the first is an
    /// absence from the client's point of view, so a caller that wants to report
    /// server-side corruption honestly needs to tell them apart, and this is that
    /// distinction without widening the error taxonomy. A malformed address is
    /// not present.
    pub fn replay_present(&self, document_sha256: &str) -> bool {
        archived_replay_present(&self.replay_root, document_sha256)
    }
}
