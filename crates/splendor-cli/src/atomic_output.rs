//! Atomic, no-overwrite artifact commit for the arena CLI.
//!
//! The `run-match` command must publish each artifact (report and, for a
//! completed match, replay) *atomically and without ever overwriting an
//! existing target*: a reader must never observe a half-written file, and a
//! pre-existing file at a target path must never be clobbered.
//!
//! The strategy is write-temp-then-publish:
//! 1. write each payload to a sibling temp file in the *same directory* as the
//!    final target (so publishing is a same-filesystem operation), named with
//!    the process id and a per-process atomic counter so concurrent invocations
//!    never collide;
//! 2. `write_all` → `flush` → `sync_all` → close each temp before any publish;
//! 3. publish the temp with [`publish_new`], an atomic **create-if-absent**
//!    operation (`hard_link` then unlink the temp). Unlike `rename`, this fails
//!    if the target already exists, so it closes the TOCTOU window between the
//!    command layer's early `exists()` check and this final publish: if the
//!    target appears in between, the publish fails rather than overwriting it.
//!    There is deliberately **no** fallback to an overwrite-capable `rename`.
//!
//! ## What is and is not guaranteed
//!
//! Each individual publish is atomic and non-clobbering. For a completed match
//! the replay is published first and the **report last**: the report is the
//! single *commit marker*. A consumer must treat the replay as committed only
//! once the report exists. The two publishes are separate operations, so a
//! consumer racing the writer could briefly observe the replay without the
//! report — that intermediate state is expected, which is exactly why the
//! report is the marker. The pair is *not* claimed to appear atomically.
//!
//! If the report publish fails after the replay has landed, the committed
//! replay is rolled back so no "replay-only" success is left behind, and every
//! temp this code touched is removed. This cleanup is best-effort on the
//! failure paths the code actually reaches; a hard process crash mid-publish
//! may still leave a `.tmp` sibling, which is inert (never a target).
//!
//! The command layer keeps an early `exists()` check on both targets purely for
//! a role-specific, fast error message; [`publish_new`] is what actually
//! *enforces* no-overwrite. Temp files additionally use `create_new(true)` so a
//! stray sibling temp is never clobbered either.

use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

/// Per-process monotonic counter making temp file names unique.
static TEMP_SEQ: AtomicU64 = AtomicU64::new(0);

/// A failure while committing artifacts to disk. `Display` yields a stable,
/// concise message suitable for the CLI's `error: <message>` stderr line.
#[derive(Debug)]
pub enum AtomicWriteError {
    /// An I/O failure at a named step (create / write / flush / sync / rename).
    Io {
        /// Stable, human-readable step name.
        context: &'static str,
        /// The underlying I/O error.
        source: io::Error,
    },
}

impl std::fmt::Display for AtomicWriteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AtomicWriteError::Io { context, source } => write!(f, "{context}: {source}"),
        }
    }
}

impl std::error::Error for AtomicWriteError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            AtomicWriteError::Io { source, .. } => Some(source),
        }
    }
}

/// Build a sibling temp path in the same directory as `target`, tagged with the
/// process id and a per-process counter.
fn temp_path(target: &Path) -> PathBuf {
    let seq = TEMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let pid = std::process::id();
    let mut name = target.file_name().map(|s| s.to_owned()).unwrap_or_default();
    name.push(format!(".{pid}.{seq}.tmp"));
    match target.parent() {
        Some(dir) if !dir.as_os_str().is_empty() => dir.join(name),
        _ => PathBuf::from(name),
    }
}

/// Write `contents` to a fresh sibling temp of `target`, fully durable on
/// return (`flush` + `sync_all`). Returns the temp path on success.
fn write_temp(target: &Path, contents: &str) -> Result<PathBuf, AtomicWriteError> {
    let tmp = temp_path(target);
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&tmp)
        .map_err(|source| AtomicWriteError::Io {
            context: "create temp file",
            source,
        })?;
    file.write_all(contents.as_bytes())
        .map_err(|source| AtomicWriteError::Io {
            context: "write temp file",
            source,
        })?;
    file.flush().map_err(|source| AtomicWriteError::Io {
        context: "flush temp file",
        source,
    })?;
    file.sync_all().map_err(|source| AtomicWriteError::Io {
        context: "sync temp file",
        source,
    })?;
    Ok(tmp)
}

/// Atomic **create-if-absent** publish of a fully-written temp onto `target`.
///
/// Uses `hard_link` (which fails if `target` already exists) then unlinks the
/// temp, so `target` is *never* overwritten — even under a race where the file
/// appears after an earlier `exists()` check. There is deliberately no fallback
/// to an overwrite-capable `rename`: if `hard_link` is unsupported the error is
/// propagated and the caller turns it into an artifact error.
pub(crate) fn publish_new(temp: &Path, target: &Path) -> io::Result<()> {
    fs::hard_link(temp, target)?;
    fs::remove_file(temp)?;
    Ok(())
}

/// Atomically commit a completed match's replay and report using the real
/// [`publish_new`] no-clobber primitive. Both payloads must already be
/// serialized by the caller.
pub(crate) fn commit_completed_with<F>(
    replay_out: &Path,
    replay_json: &str,
    report_out: &Path,
    report_json: &str,
    publish: F,
) -> Result<(), AtomicWriteError>
where
    F: Fn(&Path, &Path) -> io::Result<()>,
{
    // 1+2. Write both temps up front. If the second write fails, drop the first
    //      temp so no residue is left behind.
    let replay_tmp = write_temp(replay_out, replay_json)?;
    let report_tmp = match write_temp(report_out, report_json) {
        Ok(tmp) => tmp,
        Err(e) => {
            let _ = fs::remove_file(&replay_tmp);
            return Err(e);
        }
    };

    // 3. Publish the replay first (create-if-absent).
    if let Err(source) = publish(&replay_tmp, replay_out) {
        let _ = fs::remove_file(&replay_tmp);
        let _ = fs::remove_file(&report_tmp);
        return Err(AtomicWriteError::Io {
            context: "commit replay output",
            source,
        });
    }

    // 4. Publish the report last (the commit marker). On failure, roll back the
    //    already-published replay so a "replay-only" success can never appear,
    //    and drop the remaining temp.
    if let Err(source) = publish(&report_tmp, report_out) {
        let _ = fs::remove_file(replay_out);
        let _ = fs::remove_file(&report_tmp);
        return Err(AtomicWriteError::Io {
            context: "commit report output",
            source,
        });
    }

    Ok(())
}

/// Atomically commit an aborted match's report only (no replay), using the real
/// [`publish_new`] no-clobber primitive.
pub(crate) fn commit_aborted_with<F>(
    report_out: &Path,
    report_json: &str,
    publish: F,
) -> Result<(), AtomicWriteError>
where
    F: Fn(&Path, &Path) -> io::Result<()>,
{
    let report_tmp = write_temp(report_out, report_json)?;
    if let Err(source) = publish(&report_tmp, report_out) {
        let _ = fs::remove_file(&report_tmp);
        return Err(AtomicWriteError::Io {
            context: "commit report output",
            source,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp_dir() -> PathBuf {
        let seq = TEMP_SEQ.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("atomic-out-{}-{}", std::process::id(), seq));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn dir_names(dir: &Path) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(dir)
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    #[test]
    fn completed_commit_writes_both_files_with_no_residue() {
        let dir = tmp_dir();
        let replay = dir.join("replay.json");
        let report = dir.join("report.json");
        commit_completed_with(&replay, "REPLAY\n", &report, "REPORT\n", publish_new).unwrap();
        assert_eq!(fs::read_to_string(&replay).unwrap(), "REPLAY\n");
        assert_eq!(fs::read_to_string(&report).unwrap(), "REPORT\n");
        assert_eq!(dir_names(&dir), vec!["replay.json", "report.json"]);
    }

    #[test]
    fn publish_new_refuses_to_overwrite_existing_report() {
        // The real create-if-absent primitive must not clobber a report that
        // appears after the command's early exists() check. The already
        // -published replay is rolled back and no temp is left behind.
        let dir = tmp_dir();
        let replay = dir.join("replay.json");
        let report = dir.join("report.json");
        fs::write(&report, "PRE-EXISTING REPORT").unwrap();
        let err = commit_completed_with(&replay, "REPLAY\n", &report, "REPORT\n", publish_new)
            .unwrap_err();
        assert!(matches!(err, AtomicWriteError::Io { .. }));
        assert_eq!(fs::read_to_string(&report).unwrap(), "PRE-EXISTING REPORT");
        assert!(!replay.exists(), "our replay must be rolled back");
        assert_eq!(dir_names(&dir), vec!["report.json"]);
    }

    #[test]
    fn publish_new_refuses_to_overwrite_existing_replay() {
        let dir = tmp_dir();
        let replay = dir.join("replay.json");
        let report = dir.join("report.json");
        fs::write(&replay, "PRE-EXISTING REPLAY").unwrap();
        let err = commit_completed_with(&replay, "REPLAY\n", &report, "REPORT\n", publish_new)
            .unwrap_err();
        assert!(matches!(err, AtomicWriteError::Io { .. }));
        assert_eq!(fs::read_to_string(&replay).unwrap(), "PRE-EXISTING REPLAY");
        assert!(!report.exists(), "our report must not be published");
        assert_eq!(dir_names(&dir), vec!["replay.json"]);
    }

    #[test]
    fn completed_pair_is_not_partially_published() {
        let dir = tmp_dir();
        let replay = dir.join("replay.json");
        let report = dir.join("report.json");
        let report_target = report.clone();
        let err =
            commit_completed_with(&replay, "REPLAY\n", &report, "REPORT\n", move |from, to| {
                if to == report_target {
                    Err(io::Error::other("injected report failure"))
                } else {
                    fs::rename(from, to)
                }
            })
            .unwrap_err();
        assert!(matches!(err, AtomicWriteError::Io { .. }));
        assert!(
            !replay.exists(),
            "replay must be rolled back on report failure"
        );
        assert!(!report.exists(), "report must not exist");
        assert!(
            dir_names(&dir).is_empty(),
            "no temp residue expected: {:?}",
            dir_names(&dir)
        );
    }

    #[test]
    fn failed_commit_leaves_no_temp_files() {
        let dir = tmp_dir();
        let replay = dir.join("replay.json");
        let report = dir.join("report.json");
        let replay_target = replay.clone();
        let err =
            commit_completed_with(&replay, "REPLAY\n", &report, "REPORT\n", move |from, to| {
                if to == replay_target {
                    Err(io::Error::other("injected replay failure"))
                } else {
                    fs::rename(from, to)
                }
            })
            .unwrap_err();
        assert!(matches!(err, AtomicWriteError::Io { .. }));
        assert!(!replay.exists());
        assert!(!report.exists());
        assert!(
            dir_names(&dir).is_empty(),
            "no temp residue expected: {:?}",
            dir_names(&dir)
        );
    }

    #[test]
    fn aborted_commit_writes_only_report() {
        let dir = tmp_dir();
        let report = dir.join("report.json");
        commit_aborted_with(&report, "REPORT\n", publish_new).unwrap();
        assert_eq!(fs::read_to_string(&report).unwrap(), "REPORT\n");
        assert_eq!(dir_names(&dir), vec!["report.json"]);
    }
}
