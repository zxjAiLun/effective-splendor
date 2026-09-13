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
//! Fixed properties of the outlet:
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
//!   `completed_at`), exactly as in Commit C Slice 1.

use crate::error::{Result, StudioLeagueError};
use crate::historical_import::{bind_archived_replay, runtime_match_record, RuntimeOccurrenceV1};
use crate::identity_manifest::IdentityManifestV1;
use crate::ledger::{
    ensure_rating_config, ingest_match, match_receipt, IngestOutcome, MatchReceiptV1,
};
use crate::match_record::StudioMatchRecordV1;
use crate::participant::sync_identity_manifest;
use crate::replay_archive::{archive_replay, ArchivedReplayV1};
use crate::schema::open_league;
use rusqlite::Connection;
use std::path::Path;
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

/// Open the league through the completion authority seams.
///
/// Schema version, protocol rating config, and the durable identity manifest
/// are all enforced here, so every completion runs against a league that passed
/// the same gates — a caller cannot complete an occurrence into a database that
/// skipped one. The manifest must already exist (created by
/// `studio-league-migrate`); a missing manifest is an error, never a fresh
/// identity.
pub fn open_completion_league(
    db_path: &Path,
    identity_manifest_path: &Path,
    now: i64,
) -> Result<Connection> {
    let mut conn = open_league(db_path)?;
    conn.busy_timeout(COMPLETION_BUSY_TIMEOUT)?;
    ensure_rating_config(&conn)?;
    let manifest = match IdentityManifestV1::load_or_recover(identity_manifest_path)? {
        Some(manifest) => manifest,
        None => return Err(StudioLeagueError::Invalid(
            "identity manifest does not exist; initialize it with `studio-league-migrate` first"
                .to_string(),
        )),
    };
    manifest.validate()?;
    // Same reasoning as the ingest transaction: the manifest sync reads and
    // then writes, so it runs IMMEDIATE to serialize with other producers
    // rather than racing on a lock upgrade.
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    sync_identity_manifest(&tx, &manifest, now)?;
    tx.commit()?;
    Ok(conn)
}

/// Complete one runtime occurrence: verify, archive, bind, ingest, receipt.
///
/// This is the single authority for turning a finished occurrence into ledger
/// state. It is safe to call concurrently for the same occurrence: the archive
/// publish is content-addressed and the ledger entry is keyed by
/// `(source_kind, source_identity)`, so at most one match row, one archive
/// object, and one set of rating events result.
pub fn complete_runtime_occurrence(
    conn: &mut Connection,
    archive_root: &Path,
    request: &CompletionRequestV1<'_>,
) -> Result<CompletionOutcomeV1> {
    // 1. Strict parse, full replay verification, report/replay fact agreement,
    //    and exact configuration evidence. A failure here writes nothing.
    let record = runtime_match_record(
        request.occurrence,
        request.report_bytes,
        request.replay_bytes,
        request.config_bytes,
        request.replay_source_path,
    )?;

    // 2. The archive key is exactly the verified replay document hash the
    //    record already carries.
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

    // 3. Publish the immutable object, then bind the record to it. Both happen
    //    before the ledger write, so a failure in either leaves no match row.
    let archived = archive_replay(archive_root, &replay_sha, request.replay_bytes)?;
    let record = bind_archived_replay(record, &archived)?;

    // 4. The single ledger entry point. The canonical-tail guard lives inside
    //    `ingest_match` and is deliberately not bypassed: an occurrence whose
    //    canonical key does not append after the ledger tail fails closed here.
    let ingest = ingest_match(conn, &record)?;

    // 5. Read back what the ledger actually recorded.
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
