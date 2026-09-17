//! Commit C Slice 3: the central runtime completion outlet.
//!
//! Before this module, the only way an occurrence became ledger state was the
//! `studio-league-ingest` command, and the chain lived inside that command:
//!
//! ```text
//! runtime_match_record -> archive_replay -> bind_archived_replay -> ingest_match
//! ```
//!
//! This module is that chain, in one place, with the ledger session authority
//! (schema, protocol rating config, durable identity manifest) attached, so a
//! second producer — the Arena completion outlet, a worker, a host API — cannot
//! complete an occurrence through a shortcut. `studio-league-ingest` is reduced
//! to an adapter that reads documents, calls [`complete_runtime_occurrence`],
//! and prints the result.
//!
//! ## The authority is the session type, not a convention
//!
//! [`CompletionLeagueV1`] is **opaque**: its only constructor is
//! [`open_completion_league`], it holds its connection privately, and it exposes
//! no method that returns that connection. [`complete_runtime_occurrence`] takes
//! the session, never a bare `rusqlite::Connection`, so a producer cannot open a
//! league itself and skip the session gates — the compiler refuses.
//!
//! The archive root is likewise not a parameter: it is captured from the
//! resolved [`StudioLeaguePathsV1`] when the completion session is opened, and
//! is never a per-call choice. The ledger stores only a content-relative
//! `replay_path`, so a League must have exactly one root for those paths to
//! resolve; letting a caller choose one would reintroduce exactly the
//! un-locatable binding Commit C Slice 2 Repair 1 closed.
//!
//! The chain's primitives — [`runtime_match_record`] and
//! [`bind_archived_replay`] — are crate-private for the same reason (Commit C
//! Slice 3 Repair 2). Re-exporting them publicly would hand an external producer
//! the exact shortcut this module removes: build a legitimate runtime canonical
//! record, bind it to an object on a root of its own choosing, and ingest it
//! directly. The generic ledger and archive tools stay public; the *official
//! runtime completion path* is this outlet.
//!
//! ## Fixed properties
//!
//! * **Verification is never optional.** The replay is strictly parsed, fully
//!   verified, and reconciled against the report before anything is written.
//! * **The archive object precedes the ledger row.** If completion fails after
//!   the object is published, the worst residue is an unreferenced immutable
//!   object; a match row can never point at a replay that was not written.
//! * **The canonical-tail guard is preserved.** Ordering is decided entirely by
//!   [`crate::ledger::ingest_match`]; this module never reorders, retries with a
//!   different position, or otherwise bypasses a fail-closed ordering decision.
//!   An out-of-order occurrence stays an error and requires canonical order, or
//!   a rebuild.
//! * **Occurrence authority is unchanged.** Identity and ordering still come
//!   from the durable occurrence envelope (`runtime:<occurrence_id>`,
//!   `completed_at`).

use crate::error::{Result, StudioLeagueError};
use crate::historical_import::{bind_archived_replay, runtime_match_record, RuntimeOccurrenceV1};
use crate::human_occurrence::{
    human_runtime_match_record, HumanCompletionContextV1, HumanRuntimeOccurrenceV1,
};
use crate::identity_manifest::IdentityManifestV1;
use crate::ledger::{
    ensure_rating_config, ingest_match, match_receipt, IngestOutcome, MatchReceiptV1,
};
use crate::match_record::StudioMatchRecordV1;
use crate::participant::{
    local_human_participant, stored_identity_manifest_hash, sync_identity_manifest,
};
use crate::paths::StudioLeaguePathsV1;
use crate::replay_archive::{archive_replay, ArchivedReplayV1};
use crate::schema::open_league;
use rusqlite::Connection;
use std::path::PathBuf;
use std::time::Duration;

/// How long a completion waits for another writer to release the league
/// database before giving up. Concurrent producers of the same occurrence
/// serialize here instead of failing on the first lock contention.
const COMPLETION_BUSY_TIMEOUT: Duration = Duration::from_secs(30);

/// One finished runtime occurrence offered to the completion outlet.
///
/// The bytes are the documents the harness produced; the occurrence envelope is
/// the identity and ordering authority for them.
pub struct CompletionRequestV1<'a> {
    pub occurrence: &'a RuntimeOccurrenceV1,
    pub report_bytes: &'a [u8],
    pub replay_bytes: &'a [u8],
    pub config_bytes: &'a [u8],
    /// Provenance label of the replay's original location. Recorded only while
    /// the record is built (and in diagnostics); the ledger ends up pointing at
    /// the archive object.
    pub replay_source_path: &'a str,
}

/// An opened League that has passed the completion authority seams.
///
/// Deliberately opaque: private connection, one constructor, no accessors. The
/// only thing a caller can do with one is offer it an occurrence.
///
/// The replay archive root is captured here, at session open, from the resolved
/// [`StudioLeaguePathsV1`] — so a completion can never be pointed at a different
/// root than the session that accepted it, and [`complete_runtime_occurrence`]
/// needs no path parameter at all.
#[derive(Debug)]
pub struct CompletionLeagueV1 {
    conn: Connection,
    replay_root: PathBuf,
}

/// Open the league through the completion authority seams.
///
/// Schema version, protocol rating config, and the durable identity manifest
/// are all enforced here, so every completion runs against a league that passed
/// the same gates. The manifest must already exist (created by
/// `studio-league-migrate`); a missing manifest is an error, never a fresh
/// identity.
///
/// `paths` is resolved once by the caller (launcher, CLI, harness) and carries
/// the database, the identity manifest and the replay archive root together, so
/// the three cannot be chosen independently.
pub fn open_completion_league(paths: &StudioLeaguePathsV1, now: i64) -> Result<CompletionLeagueV1> {
    let mut conn = open_league(paths.db())?;
    conn.busy_timeout(COMPLETION_BUSY_TIMEOUT)?;
    ensure_rating_config(&conn)?;
    let manifest = match IdentityManifestV1::load_or_recover(paths.identity())? {
        Some(manifest) => manifest,
        None => return Err(StudioLeagueError::Invalid(
            "identity manifest does not exist; initialize it with `studio-league-migrate` first"
                .to_string(),
        )),
    };
    manifest.validate()?;
    // The manifest sync reads and then writes, so it runs IMMEDIATE to serialize
    // with other producers rather than racing on a lock upgrade.
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    sync_identity_manifest(&tx, &manifest, now)?;
    tx.commit()?;
    Ok(CompletionLeagueV1 {
        conn,
        replay_root: paths.replay_root().to_path_buf(),
    })
}

/// What the league did with one occurrence.
#[derive(Debug, Clone, PartialEq)]
pub struct CompletionOutcomeV1 {
    pub ingest: IngestOutcome,
    /// The canonical record that was ingested, bound to the archive object.
    pub record: StudioMatchRecordV1,
    /// The immutable archive object the record was bound to.
    pub archived: ArchivedReplayV1,
    /// The receipt read back from the ledger: eligibility and Elo events.
    pub receipt: MatchReceiptV1,
}

impl CompletionOutcomeV1 {
    pub fn match_id(&self) -> &str {
        self.ingest.match_id()
    }

    /// `true` when this call actually inserted the match; `false` when an
    /// identical occurrence was already recorded.
    pub fn was_inserted(&self) -> bool {
        self.ingest.was_inserted()
    }

    /// Rating events produced by this call (0 on an idempotent re-offer).
    pub fn rating_events(&self) -> usize {
        self.ingest.rating_events()
    }
}

/// Complete one runtime occurrence: verify, archive, bind, ingest, receipt.
///
/// This is the single authority for turning a finished occurrence into ledger
/// state. It is safe to call concurrently for the same occurrence: the archive
/// publish is content-addressed and the ledger entry is keyed by
/// `(source_kind, source_identity)` with the occurrence's full evidence hash as
/// its collision evidence, so at most one match row, one archive object, and one
/// set of rating events result — and the same occurrence id carrying *different*
/// evidence is a conflict, not a silent no-op.
pub fn complete_runtime_occurrence(
    league: &mut CompletionLeagueV1,
    request: &CompletionRequestV1<'_>,
) -> Result<CompletionOutcomeV1> {
    // Strict parse, full replay verification, report/replay fact agreement, and
    // exact configuration evidence. A failure here writes nothing.
    let record = runtime_match_record(
        request.occurrence,
        request.report_bytes,
        request.replay_bytes,
        request.config_bytes,
        request.replay_source_path,
    )?;
    complete_verified_record(league, record, request.replay_bytes)
}

/// One finished human-play game offered to the completion outlet.
///
/// The request carries identity claims in its occurrence (participant id and
/// manifest hash), but no authoritative league context or caller-built record.
/// The outlet reads the authority from its own league and requires those claims
/// to match it; a producer cannot choose the league's human identity.
pub struct HumanCompletionRequestV1<'a> {
    pub occurrence: &'a HumanRuntimeOccurrenceV1,
    pub replay_bytes: &'a [u8],
    /// Provenance label of the replay's original location, recorded only while
    /// the record is built. The ledger ends up pointing at the archive object.
    pub replay_source_path: &'a str,
}

/// Complete one human-play occurrence: verify, archive, bind, ingest, receipt.
///
/// The human counterpart of [`complete_runtime_occurrence`], and the second
/// legitimate producer of the same completion authority. It differs only in how
/// the verified record is built: the human occurrence envelope supplies the seat
/// attribution (which seat is the local human, which policy the opponent ran),
/// while the archive / ledger / receipt tail is shared verbatim.
///
/// The local human identity and the stored manifest hash are read from the
/// league the session holds, never from the request, so a producer cannot
/// attribute a match to an identity the league does not recognize.
pub fn complete_human_runtime_occurrence(
    league: &mut CompletionLeagueV1,
    request: &HumanCompletionRequestV1<'_>,
) -> Result<CompletionOutcomeV1> {
    let (local_human, stored_manifest_hash): (Option<String>, Option<String>) = {
        let conn = &league.conn;
        (
            local_human_participant(conn)?,
            stored_identity_manifest_hash(conn)?,
        )
    };
    let context = HumanCompletionContextV1 {
        local_human_participant_id: local_human.as_deref(),
        stored_identity_manifest_hash: stored_manifest_hash.as_deref(),
    };
    let record = human_runtime_match_record(
        request.occurrence,
        request.replay_bytes,
        &context,
        request.replay_source_path,
    )?;
    complete_verified_record(league, record, request.replay_bytes)
}

/// The shared completion tail: archive, bind, ingest, receipt.
///
/// `record` must already be a fully verified canonical record — built by the
/// arena path or the human path, each of which owns its own verification. This
/// function is deliberately **private**: it is the one place a record becomes
/// ledger state, and it must never be reachable with a caller-constructed
/// record. The archive root comes from the session, not from a parameter, and
/// the ledger write goes through the single entry point [`ingest_match`], whose
/// canonical-tail guard is never bypassed.
pub(crate) fn complete_verified_record(
    league: &mut CompletionLeagueV1,
    record: StudioMatchRecordV1,
    replay_bytes: &[u8],
) -> Result<CompletionOutcomeV1> {
    // Capture the session's archive root before borrowing the connection, so the
    // publish below uses the same root the session was opened with.
    let replay_root = league.replay_root.clone();
    let conn = &mut league.conn;

    // 1. The archive key is exactly the verified replay document hash the record
    //    already carries, under the protocol root. No caller chooses it.
    let replay_sha = record
        .replay
        .document_hash
        .as_deref()
        .filter(|sha| crate::match_record::is_lowercase_hex64(sha))
        .ok_or_else(|| {
            StudioLeagueError::Invalid(
                "the verified occurrence carries no replay document hash; nothing to archive"
                    .to_string(),
            )
        })?
        .to_string();

    // 2. Publish the immutable object, then bind the record to it. Both happen
    //    before the ledger write, so a failure in either leaves no match row.
    let archived = archive_replay(&replay_root, &replay_sha, replay_bytes)?;
    let record = bind_archived_replay(record, &archived)?;

    // 3. The single ledger entry point. The canonical-tail guard lives inside
    //    `ingest_match` and is deliberately not bypassed: an occurrence whose
    //    canonical key does not append after the ledger tail fails closed here.
    let ingest = ingest_match(conn, &record)?;

    // 4. Read back what the ledger actually recorded.
    let match_id = record.match_id();
    let receipt = match_receipt(conn, &match_id)?.ok_or_else(|| {
        StudioLeagueError::Invalid(format!(
            "completion reported `{ingest:?}` but match `{match_id}` is not in the ledger"
        ))
    })?;

    Ok(CompletionOutcomeV1 {
        ingest,
        record,
        archived,
        receipt,
    })
}
