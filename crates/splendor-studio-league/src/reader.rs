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
//!
//! # ... and they are re-checked on every read
//!
//! Checking once, when the session opens, would be enough for a one-shot
//! completion session but not for a server: `StudioHost` runs indefinitely, and
//! the owner may legally edit the manifest at any moment without rebuilding. A
//! league that was trustworthy at startup can be stale by the next request, so
//! every read revalidates both evidences before it answers. The session's
//! contract is not "this league was valid when it was opened" but "this answer is
//! still backed by authority evidence".

use rusqlite::{Connection, OpenFlags};
use std::path::PathBuf;

use crate::error::{Result, StudioLeagueError};
use crate::identity_manifest::IdentityManifestV1;
use crate::ledger::{
    leaderboard, league_match_page, match_detail, participant_opponents, participant_profile,
    participant_rating_history, protocol_rating_config, stored_rating_config, LeaderboardRow,
    LeagueMatchPageRequestV1, LeagueMatchPageV1, MatchDetailV1, ParticipantOpponentPageRequestV1,
    ParticipantOpponentPageV1, ParticipantProfileV1, ParticipantRatingHistoryPageV1,
    ParticipantRatingHistoryRequestV1,
};
use crate::participant::stored_identity_manifest_hash;
use crate::paths::StudioLeaguePathsV1;
use crate::replay_archive::{archived_replay_present, read_archived_replay};
use crate::schema::{schema_version, STUDIO_LEAGUE_SCHEMA_VERSION};

/// An opened, read-only view of one Studio League installation.
#[derive(Debug)]
pub struct StudioLeagueReaderV1 {
    conn: Connection,
    identity_path: PathBuf,
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
    let reader = StudioLeagueReaderV1 {
        conn,
        identity_path: paths.identity().to_path_buf(),
        replay_root: paths.replay_root().to_path_buf(),
    };
    // The very same check every read runs, so opening can never be laxer than
    // reading: a league is refused here for the same reason it would be refused
    // on the ten-thousandth request.
    reader.validate_authority_evidence()?;
    Ok(reader)
}

impl StudioLeagueReaderV1 {
    /// Re-check the authority evidences this session may only answer while they
    /// hold, and refuse the read otherwise.
    ///
    /// Every read runs this first, because the evidences can move while the
    /// process is up. All of it is pure reading: two `league_meta` lookups and
    /// one strict manifest load, with no mutation, and deliberately not
    /// [`IdentityManifestV1::load_or_recover`], which can heal the primary and
    /// therefore writes.
    fn validate_authority_evidence(&self) -> Result<()> {
        // The rating protocol identity is integrity evidence, not a setting: a
        // database written by another protocol must be rebuilt, not served.
        let stored = stored_rating_config(&self.conn)?.ok_or_else(|| {
            StudioLeagueError::Invalid(
                "no Studio rating config integrity evidence is recorded; rebuild the derived database"
                    .to_string(),
            )
        })?;
        let protocol = protocol_rating_config();
        if stored != protocol {
            return Err(StudioLeagueError::RatingConfig(format!(
                "the derived database was built with {} but this build's Studio Elo protocol is {}; the index is derived, so rebuild it",
                stored.to_json()?,
                protocol.to_json()?
            )));
        }

        // The durable manifest is the authored identity authority and this
        // database is derived from it, so the recorded hash must still match the
        // manifest on disk.
        let manifest = IdentityManifestV1::load(&self.identity_path)?.ok_or_else(|| {
            StudioLeagueError::Invalid(format!(
                "identity manifest `{}` does not exist; rebuild the derived database",
                self.identity_path.display()
            ))
        })?;
        let expected_hash = manifest.hash()?;
        match stored_identity_manifest_hash(&self.conn)? {
            Some(stored) if stored == expected_hash => Ok(()),
            Some(stored) => Err(StudioLeagueError::Invalid(format!(
                "identity manifest hash `{expected_hash}` disagrees with stored database evidence `{stored}`; rebuild the derived database to apply identity or alias changes"
            ))),
            None => Err(StudioLeagueError::Invalid(
                "no identity manifest hash integrity evidence is recorded; rebuild the derived database"
                    .to_string(),
            )),
        }
    }
    /// The league table, exactly as the ledger derives it. Nothing is
    /// recomputed here: no Elo, no wins, no provisional flag.
    pub fn leaderboard(&self) -> Result<Vec<LeaderboardRow>> {
        self.validate_authority_evidence()?;
        leaderboard(&self.conn)
    }

    /// One match in full. `Ok(None)` when it is not recorded at all.
    pub fn match_detail(&self, match_id: &str) -> Result<Option<MatchDetailV1>> {
        self.validate_authority_evidence()?;
        match_detail(&self.conn, match_id)
    }

    /// One bounded page of recorded matches, newest first.
    ///
    /// Why a page and not the whole list: the official league holds tens of
    /// thousands of matches, and this Host answers requests serially, so an
    /// unbounded read is how one request starves every other route. The limit is
    /// validated to `1..=`[`GAMES_PAGE_MAX_LIMIT`](crate::GAMES_PAGE_MAX_LIMIT), and
    /// the cursor is a `league_seq`, never an offset — see
    /// [`league_match_page`](crate::league_match_page) for why that distinction is
    /// load-bearing under concurrent ingestion.
    ///
    /// The authority evidence is re-checked first, like every other read, so a
    /// page is never served from a league that has gone stale.
    pub fn league_match_page(
        &self,
        request: &LeagueMatchPageRequestV1,
    ) -> Result<LeagueMatchPageV1> {
        self.validate_authority_evidence()?;
        league_match_page(&self.conn, request)
    }

    /// The archived ReplayV1 document for a verified content address.
    ///
    /// The argument is a document SHA-256 and nothing else: the bytes are located
    /// by replay root plus content address, so a caller cannot ask for an
    /// arbitrary path.
    ///
    /// `Ok(None)` means the archive holds no object at this address (which
    /// includes a malformed address); `Err` means the session refused to answer,
    /// or the archive holds something it cannot serve. The order matters: the
    /// authority check runs first and owns the result, so a league that has gone
    /// stale can never be reported as "this replay does not exist" — the
    /// distinction between absence and refusal is decided here, once, rather than
    /// left to the caller to re-derive with a second call.
    pub fn read_replay(&self, document_sha256: &str) -> Result<Option<Vec<u8>>> {
        self.validate_authority_evidence()?;
        if !archived_replay_present(&self.replay_root, document_sha256) {
            return Ok(None);
        }
        read_archived_replay(&self.replay_root, document_sha256).map(Some)
    }

    /// One participant profile in full. `Ok(None)` when the participant is not
    /// recorded in the league.
    pub fn participant_profile(
        &self,
        participant_id: &str,
    ) -> Result<Option<ParticipantProfileV1>> {
        self.validate_authority_evidence()?;
        participant_profile(&self.conn, participant_id)
    }

    /// One bounded page of a participant's Elo history, newest event first.
    ///
    /// `Ok(None)` when the participant is not recorded in the league.
    pub fn participant_rating_history(
        &self,
        request: &ParticipantRatingHistoryRequestV1,
    ) -> Result<Option<ParticipantRatingHistoryPageV1>> {
        self.validate_authority_evidence()?;
        participant_rating_history(&self.conn, request)
    }

    /// One bounded page of a participant's opponents and head-to-head record.
    ///
    /// `Ok(None)` when the participant is not recorded in the league.
    pub fn participant_opponents(
        &self,
        request: &ParticipantOpponentPageRequestV1,
    ) -> Result<Option<ParticipantOpponentPageV1>> {
        self.validate_authority_evidence()?;
        participant_opponents(&self.conn, request)
    }
}
