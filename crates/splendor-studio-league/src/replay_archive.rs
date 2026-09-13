//! Commit C Slice 2: the content-addressed replay archive.
//!
//! A verified runtime `ReplayV1` is copied into an immutable, content-addressed
//! store so that the league's `verified` binding survives deletion of the run
//! directory that produced it (invariant 2: every future eligible match keeps
//! its ReplayV1).
//!
//! The key is the **verified replay document SHA-256** — the same value the
//! ledger already records as `ReplayBindingV1.document_hash`. The object is
//! therefore identified by content alone: no original filename, no run
//! directory, and no path participates in its identity.
//!
//! Contract:
//! 1. archive key = verified replay document SHA-256;
//! 2. the same hash already present with **identical** bytes is an idempotent
//!    no-op;
//! 3. the same target hash path holding **different** bytes fails closed, with
//!    zero mutation and the existing object left byte-identical;
//! 4. the archived replay stays readable and re-verifiable after the original
//!    run directory is deleted.
//!
//! The archive is append-only. Nothing here deletes, moves, or rewrites an
//! object, and nothing here trusts a pre-existing file on the strength of its
//! name: on a collision the existing bytes are re-hashed.

use crate::error::{Result, StudioLeagueError};
use sha2::{Digest, Sha256};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

/// Per-process counter that keeps concurrent temporary file names distinct, so
/// two threads of one process publishing the same content address never fight
/// over the same temp path.
static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

/// Outcome of archiving one replay document.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ArchiveOutcome {
    /// The object did not exist and was written.
    Stored,
    /// The object already existed with byte-identical content; nothing changed.
    AlreadyPresent,
}

impl ArchiveOutcome {
    pub fn as_str(&self) -> &'static str {
        match self {
            ArchiveOutcome::Stored => "stored",
            ArchiveOutcome::AlreadyPresent => "already_present",
        }
    }
}

/// A verified replay document placed in the content-addressed archive.
///
/// This is an **opaque handle**: its fields are private and the only way to
/// obtain one is [`archive_replay`], which has already published the object (or
/// confirmed a byte-identical one is present) under the content address. No
/// caller can fabricate a handle and make the ledger claim an archive object
/// that was never written.
///
/// A handle proves the object existed **when it was created**. Because the
/// filesystem can change afterwards, a caller that is about to record
/// `ReplayStorage::Archive` must first call [`ArchivedReplayV1::verify_present`],
/// which re-reads the object and re-checks it against the content address.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArchivedReplayV1 {
    document_sha256: String,
    logical_path: String,
    filesystem_path: PathBuf,
    outcome: ArchiveOutcome,
}

impl ArchivedReplayV1 {
    /// The only constructor; reached solely from [`archive_replay`] once the
    /// object is known to be published.
    fn published(
        document_sha256: &str,
        logical_path: String,
        filesystem_path: PathBuf,
        outcome: ArchiveOutcome,
    ) -> Self {
        Self {
            document_sha256: document_sha256.to_string(),
            logical_path,
            filesystem_path,
            outcome,
        }
    }

    /// SHA-256 of the archived bytes (the content address, 64 lowercase hex).
    pub fn document_sha256(&self) -> &str {
        &self.document_sha256
    }

    /// Portable, `/`-separated logical path of the object inside the archive.
    /// This is exactly what the ledger records as `replay_path`.
    pub fn logical_path(&self) -> &str {
        &self.logical_path
    }

    /// Filesystem path of the object, for the caller that actually reads it.
    pub fn filesystem_path(&self) -> &Path {
        &self.filesystem_path
    }

    /// Whether the object was newly written or already present.
    pub fn outcome(&self) -> ArchiveOutcome {
        self.outcome.clone()
    }

    /// Re-validate that the object this handle names is present **right now**
    /// and still hashes to the handle's content address.
    ///
    /// Creating a handle only proves the object existed when [`archive_replay`]
    /// returned; the filesystem can change afterwards. Any caller about to
    /// record `ReplayStorage::Archive` on the strength of this handle must call
    /// this first, so a ledger row can never claim an archive object that has
    /// since been deleted or overwritten with different bytes.
    pub fn verify_present(&self) -> Result<()> {
        let bytes = std::fs::read(&self.filesystem_path).map_err(|error| {
            StudioLeagueError::Invalid(format!(
                "archived replay `{}` is no longer readable at `{}`: {error}",
                self.document_sha256,
                self.filesystem_path.display()
            ))
        })?;
        let actual = replay_document_sha256(&bytes);
        if actual != self.document_sha256 {
            return Err(StudioLeagueError::Invalid(format!(
                "archived replay at `{}` hashes to {actual}, not its content address {}; the archive object changed after it was written",
                self.filesystem_path.display(),
                self.document_sha256
            )));
        }
        Ok(())
    }
}

/// The two-character fan-out directory for a content address.
fn fanout(sha256: &str) -> &str {
    // `archive_replay` validates the hash before it is ever used as a path
    // component, so this split cannot panic on malformed input.
    &sha256[..2]
}

/// Validate a claimed content address: exactly 64 lowercase hex characters.
fn validated_sha256(document_sha256: &str) -> Result<()> {
    if !crate::match_record::is_lowercase_hex64(document_sha256) {
        return Err(StudioLeagueError::Invalid(format!(
            "archive key must be a 64-character lowercase replay document SHA-256, got `{document_sha256}`"
        )));
    }
    Ok(())
}

/// Recompute the SHA-256 of a byte slice (the archive's own hash, used to
/// re-check pre-existing objects rather than trusting their name).
pub fn replay_document_sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// Inspect whatever currently occupies a content address.
///
/// `Ok(true)` when a byte-identical object is already published, `Ok(false)`
/// when the address is empty, and `Err` when it holds different bytes (corrupt
/// evidence that must never be overwritten) or cannot be read.
fn object_present(target: &Path, expected_sha256: &str) -> Result<bool> {
    match std::fs::read(target) {
        Ok(existing) => {
            let existing_hash = replay_document_sha256(&existing);
            if existing_hash == expected_sha256 {
                Ok(true)
            } else {
                Err(StudioLeagueError::Invalid(format!(
                    "archive target `{}` already holds different bytes (found {existing_hash}, expected {expected_sha256}); refusing to overwrite an immutable object",
                    target.display()
                )))
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(StudioLeagueError::Invalid(format!(
            "cannot read archive target `{}`: {error}",
            target.display()
        ))),
    }
}

/// Create a fresh temporary file next to the content address. The name embeds
/// the process id and a per-process atomic counter, and `create_new` refuses to
/// reuse an existing path, so concurrent writers never share a temp file (the
/// previous `.{sha}.{pid}.tmp` name collided across threads of one process).
fn create_unique_temp(directory: &Path, sha256: &str) -> Result<(PathBuf, std::fs::File)> {
    loop {
        let nonce = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
        let candidate = directory.join(format!(".{sha256}.{}.{nonce}.tmp", std::process::id()));
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(file) => return Ok((candidate, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(StudioLeagueError::Invalid(format!(
                    "cannot create archive temp file `{}`: {error}",
                    candidate.display()
                )))
            }
        }
    }
}

/// Archive one verified replay document.
///
/// `archive_root` is the archive directory (created if absent). `bytes` must be
/// the verified replay document; `expected_sha256` is its content address. The
/// function is idempotent for identical bytes and fail-closed on a collision.
pub fn archive_replay(
    archive_root: &Path,
    expected_sha256: &str,
    bytes: &[u8],
) -> Result<ArchivedReplayV1> {
    validated_sha256(expected_sha256)?;

    // The bytes really are the document the caller says they are. This is the
    // archive's own guard: it never indexes content under a name it did not
    // verify.
    let actual = replay_document_sha256(bytes);
    if actual != expected_sha256 {
        return Err(StudioLeagueError::Invalid(format!(
            "replay document hashes to {actual} but was offered as archive key {expected_sha256}"
        )));
    }

    let directory = archive_root.join(fanout(expected_sha256));
    std::fs::create_dir_all(&directory)?;
    let target = directory.join(format!("{expected_sha256}.json"));
    let logical_path = format!(
        "{}/{}",
        fanout(expected_sha256),
        format_args!("{expected_sha256}.json")
    );

    // Idempotency / conflict: re-hash whatever already occupies the content
    // address. Identical bytes are a no-op; different bytes are corrupt
    // evidence and must never be overwritten.
    if object_present(&target, expected_sha256)? {
        return Ok(ArchivedReplayV1::published(
            expected_sha256,
            logical_path,
            target,
            ArchiveOutcome::AlreadyPresent,
        ));
    }

    // Write to a unique temporary file in the same directory, flush it, then
    // publish atomically. A crash leaves at most an orphan `.tmp`, never a
    // half-written object under a content address.
    let (temp, mut file) = create_unique_temp(&directory, expected_sha256)?;
    let write_result = (|| -> std::io::Result<()> {
        file.write_all(bytes)?;
        file.sync_all()
    })();
    drop(file);
    if let Err(error) = write_result {
        // Do not leave a partial temp file behind on a write failure.
        let _ = std::fs::remove_file(&temp);
        return Err(error.into());
    }

    match std::fs::rename(&temp, &target) {
        Ok(()) => Ok(ArchivedReplayV1::published(
            expected_sha256,
            logical_path,
            target,
            ArchiveOutcome::Stored,
        )),
        Err(rename_error) => {
            let _ = std::fs::remove_file(&temp);
            // Concurrency: another producer may have published the identical
            // object between the check above and this rename (on Windows the
            // loser's rename fails with an existing target). Accept the object
            // only when its bytes still hash to the expected address; anything
            // else must fail closed.
            match object_present(&target, expected_sha256) {
                Ok(true) => Ok(ArchivedReplayV1::published(
                    expected_sha256,
                    logical_path,
                    target,
                    ArchiveOutcome::AlreadyPresent,
                )),
                Ok(false) => Err(StudioLeagueError::Invalid(format!(
                    "failed to publish archived replay to `{}`: {rename_error}",
                    target.display()
                ))),
                Err(mismatch) => Err(mismatch),
            }
        }
    }
}

/// Read an archived replay back by its content address.
///
/// The bytes are re-hashed and refused unless they still hash to the requested
/// address, so on-disk corruption fails closed instead of handing back bytes
/// that do not match the record's `document_hash`. Used to prove the archive
/// survives deletion of the original run directory.
pub fn read_archived_replay(archive_root: &Path, document_sha256: &str) -> Result<Vec<u8>> {
    validated_sha256(document_sha256)?;
    let target = archive_root
        .join(fanout(document_sha256))
        .join(format!("{document_sha256}.json"));
    let bytes = std::fs::read(&target).map_err(|error| {
        StudioLeagueError::Invalid(format!(
            "archived replay `{document_sha256}` is not readable at `{}`: {error}",
            target.display()
        ))
    })?;
    let actual = replay_document_sha256(&bytes);
    if actual != document_sha256 {
        return Err(StudioLeagueError::Invalid(format!(
            "archived replay at `{}` hashes to {actual}, not its content address {document_sha256}; the archive object is corrupt",
            target.display()
        )));
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tempdir(label: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("splendor-archive-{}-{}", std::process::id(), label));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn archiving_the_same_bytes_twice_is_an_idempotent_no_op() {
        let root = tempdir("idempotent");
        let bytes = b"{\"format\":\"replay-v1\"}".to_vec();
        let sha = replay_document_sha256(&bytes);

        let first = archive_replay(&root, &sha, &bytes).unwrap();
        assert_eq!(first.outcome(), ArchiveOutcome::Stored);
        assert_eq!(
            first.logical_path(),
            format!("{}/{}", &sha[..2], format_args!("{sha}.json"))
        );

        let second = archive_replay(&root, &sha, &bytes).unwrap();
        assert_eq!(second.outcome(), ArchiveOutcome::AlreadyPresent);
        assert_eq!(second.filesystem_path(), first.filesystem_path());

        // Exactly one object exists.
        let objects: Vec<_> = std::fs::read_dir(root.join(&sha[..2]))
            .unwrap()
            .filter_map(|entry| entry.ok())
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .ends_with(&format!("{sha}.json"))
            })
            .collect();
        assert_eq!(objects.len(), 1);
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn a_collision_with_different_bytes_fails_closed_without_overwriting() {
        let root = tempdir("collision");
        let original = b"original-bytes".to_vec();
        let sha = replay_document_sha256(&original);
        archive_replay(&root, &sha, &original).unwrap();

        // Simulate a corrupt object occupying the content address: bytes that
        // do not hash to their own name. Re-archiving the real document must
        // refuse and leave the occupant byte-identical.
        let target = root.join(&sha[..2]).join(format!("{sha}.json"));
        let intruder = b"different-bytes".to_vec();
        std::fs::write(&target, &intruder).unwrap();

        let error = archive_replay(&root, &sha, &original).unwrap_err();
        assert!(error.to_string().contains("different bytes"), "{error}");

        let stored = std::fs::read(&target).unwrap();
        assert_eq!(stored, intruder, "the occupant must not be overwritten");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn bytes_that_do_not_match_their_claimed_address_are_rejected() {
        let root = tempdir("mismatch");
        let bytes = b"some-bytes".to_vec();
        let wrong = replay_document_sha256(b"other-bytes");
        let error = archive_replay(&root, &wrong, &bytes).unwrap_err();
        assert!(error.to_string().contains("hashes to"), "{error}");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn a_wrong_content_address_is_rejected_before_any_write() {
        let root = tempdir("wrong-address");
        let bytes = b"some-replay".to_vec();
        let wrong = "0".repeat(64);
        let error = archive_replay(&root, &wrong, &bytes).unwrap_err();
        assert!(error.to_string().contains("hashes to"), "{error}");
        // Nothing was created for the wrong address.
        assert!(std::fs::read_dir(&root).unwrap().next().is_none());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn an_archived_replay_survives_deletion_of_the_source_directory() {
        let root = tempdir("survives");
        let source_directory = root.join("run-a");
        std::fs::create_dir_all(&source_directory).unwrap();
        let bytes = b"{\"format\":\"replay-v1\",\"steps\":[]}".to_vec();
        std::fs::write(source_directory.join("match-replay.json"), &bytes).unwrap();
        let sha = replay_document_sha256(&bytes);

        let archived = archive_replay(&root, &sha, &bytes).unwrap();
        std::fs::remove_dir_all(&source_directory).unwrap();
        assert!(!source_directory.exists());

        let from_archive = read_archived_replay(&root, &sha).unwrap();
        assert_eq!(from_archive, bytes);
        assert!(archived.filesystem_path().exists());
        let _ = std::fs::remove_dir_all(&root);
    }
}
