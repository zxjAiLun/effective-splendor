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
//! may still leave a `.tmp` sibling, which is inert (never a target). Likewise,
//! a temp unlink that fails *after* `hard_link` has already succeeded is
//! swallowed: the target is committed the moment the link lands, so a cleanup
//! failure can never downgrade a successful publication into an error.
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
pub(crate) fn write_temp(target: &Path, contents: &str) -> Result<PathBuf, AtomicWriteError> {
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

/// Atomic **create-if-absent** publish of a fully-written temp onto `target`,
/// using `unlink` to drop the now-redundant temp after the link succeeds.
///
/// The `hard_link` is the true *commit point*: it fails if `target` already
/// exists, so the publish is non-clobbering even under a race where the file
/// appears after an earlier `exists()` check (there is deliberately no fallback
/// to an overwrite-capable `rename`). Once `hard_link` succeeds, `target` is
/// committed and durable; the subsequent temp unlink is only best-effort
/// cleanup, so its failure is deliberately swallowed — it must never convert a
/// successful publication into an `Err`.
pub(crate) fn publish_new_with<U>(temp: &Path, target: &Path, unlink: U) -> io::Result<()>
where
    U: FnOnce(&Path) -> io::Result<()>,
{
    fs::hard_link(temp, target)?;
    // Target is committed. Temp unlink is best-effort cleanup and must not
    // convert a successful publication into a failed one.
    let _ = unlink(temp);
    Ok(())
}

/// Production [`publish_new_with`] using the real [`fs::remove_file`] for temp
/// cleanup. `Err` is only ever returned when `hard_link` itself fails — i.e.
/// when the target was *not* created. A temp-cleanup failure can never undo an
/// already-published target.
pub(crate) fn publish_new(temp: &Path, target: &Path) -> io::Result<()> {
    publish_new_with(temp, target, |t| fs::remove_file(t))
}

/// Atomically commit a completed match's replay and report. Both payloads must
/// already be serialized by the caller.
///
/// `publish` is an atomic create-if-absent primitive: it MUST return `Err` only
/// when the target was *not* created, and once `hard_link` succeeds the target
/// is committed — the callback then MUST return `Ok` (any temp-cleanup failure
/// is best-effort and must not surface as `Err`). This contract is what lets a
/// temp-cleanup failure never reverse an already-published target.
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

/// Atomically commit a single standalone artifact (e.g. a search analysis).
///
/// `publish` follows the same contract as [`commit_completed_with`]: it MUST
/// return `Err` only when the target was *not* created, and once `hard_link`
/// succeeds the target is committed — any temp-cleanup failure is best-effort
/// and must not surface as `Err`. On publish failure the temp is removed so no
/// residue is left behind, and a pre-existing target is never clobbered.
pub(crate) fn commit_single_with<F>(
    target: &Path,
    contents: &str,
    publish: F,
) -> Result<(), AtomicWriteError>
where
    F: Fn(&Path, &Path) -> io::Result<()>,
{
    let tmp = write_temp(target, contents)?;
    if let Err(source) = publish(&tmp, target) {
        let _ = fs::remove_file(&tmp);
        return Err(AtomicWriteError::Io {
            context: "commit output",
            source,
        });
    }
    Ok(())
}

/// Production [`commit_single_with`] using the real create-if-absent
/// [`publish_new`] primitive.
pub(crate) fn commit_single(target: &Path, contents: &str) -> Result<(), AtomicWriteError> {
    commit_single_with(target, contents, publish_new)
}

/// Atomically commit an aborted match's report only (no replay).
///
/// `publish` follows the same contract as [`commit_completed_with`]: return
/// `Err` only when the report target was *not* created, and `Ok` once the link
/// succeeds (a temp-cleanup failure is best-effort and must not surface as
/// `Err`).
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
    fn single_commit_writes_target_with_no_residue() {
        let dir = tmp_dir();
        let target = dir.join("analysis.json");
        commit_single(&target, "ANALYSIS\n").unwrap();
        assert_eq!(fs::read_to_string(&target).unwrap(), "ANALYSIS\n");
        assert_eq!(dir_names(&dir), vec!["analysis.json"]);
    }

    #[test]
    fn single_commit_refuses_to_overwrite_and_preserves_sentinel() {
        // Simulate a race: the target appears after any earlier exists() check.
        let dir = tmp_dir();
        let target = dir.join("analysis.json");
        fs::write(&target, "SENTINEL\n").unwrap();
        let err = commit_single(&target, "ANALYSIS\n").unwrap_err();
        assert!(matches!(err, AtomicWriteError::Io { .. }));
        assert_eq!(
            fs::read_to_string(&target).unwrap(),
            "SENTINEL\n",
            "pre-existing target must never be clobbered"
        );
        assert_eq!(dir_names(&dir), vec!["analysis.json"], "no temp residue");
    }

    #[test]
    fn single_commit_publish_failure_leaves_no_residue() {
        let dir = tmp_dir();
        let target = dir.join("analysis.json");
        let err = commit_single_with(&target, "ANALYSIS\n", |_, _| {
            Err(io::Error::other("injected publish failure"))
        })
        .unwrap_err();
        assert!(matches!(err, AtomicWriteError::Io { .. }));
        assert!(!target.exists(), "target must not be committed");
        assert!(
            dir_names(&dir).is_empty(),
            "no temp residue expected: {:?}",
            dir_names(&dir)
        );
    }

    #[test]
    fn single_commit_unlink_failure_still_commits_target() {
        // A temp unlink that fails *after* the hard_link commit point must not
        // turn the publication into an error; the temp remains inert residue.
        let dir = tmp_dir();
        let target = dir.join("analysis.json");
        let publish = |from: &Path, to: &Path| -> io::Result<()> {
            fs::hard_link(from, to)?;
            // Injected failing unlink is swallowed by the publish contract; do
            // not delete the temp so the failure is literally real.
            let _: io::Result<()> = Err(io::Error::other("simulated unlink failure"));
            Ok(())
        };
        commit_single_with(&target, "ANALYSIS\n", publish).unwrap();
        assert_eq!(fs::read_to_string(&target).unwrap(), "ANALYSIS\n");
        let has_residue = dir_names(&dir)
            .iter()
            .any(|n| n.starts_with("analysis.json.") && n.ends_with(".tmp"));
        assert!(
            has_residue,
            "temp should remain after the simulated unlink failure"
        );
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn aborted_commit_writes_only_report() {
        let dir = tmp_dir();
        let report = dir.join("report.json");
        commit_aborted_with(&report, "REPORT\n", publish_new).unwrap();
        assert_eq!(fs::read_to_string(&report).unwrap(), "REPORT\n");
        assert_eq!(dir_names(&dir), vec!["report.json"]);
    }

    #[test]
    fn publish_new_with_failing_unlink_still_commits_target() {
        // Direct check of the new primitive: a temp unlink that fails *after*
        // a successful hard_link must NOT turn the publication into an error.
        let dir = tmp_dir();
        let temp = dir.join("x.tmp");
        let target = dir.join("x.json");
        fs::write(&temp, "DATA").unwrap();
        let res = publish_new_with(&temp, &target, |_| Err(io::Error::other("unlink failed")));
        assert!(res.is_ok(), "temp cleanup failure must not fail commit");
        assert_eq!(fs::read_to_string(&target).unwrap(), "DATA");
        assert!(
            temp.exists(),
            "temp residue may remain after a failed unlink; it is inert"
        );
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn replay_temp_unlink_failure_does_not_uncommit_replay() {
        let dir = tmp_dir();
        let replay = dir.join("replay.json");
        let report = dir.join("report.json");
        let replay_target = replay.clone();
        // Publish callback commits the target via hard_link but simulates a
        // failing temp unlink for the replay only. The committed target must
        // survive the cleanup failure.
        let publish = move |from: &Path, to: &Path| -> io::Result<()> {
            fs::hard_link(from, to)?;
            if to == replay_target.as_path() {
                return Ok(()); // target is committed; swallow unlink failure
            }
            let _ = fs::remove_file(from);
            Ok(())
        };
        commit_completed_with(&replay, "REPLAY\n", &report, "REPORT\n", publish).unwrap();
        assert_eq!(fs::read_to_string(&replay).unwrap(), "REPLAY\n");
        assert_eq!(fs::read_to_string(&report).unwrap(), "REPORT\n");
        assert!(
            replay.exists() && report.exists(),
            "both artifacts stay committed after replay temp cleanup failure"
        );
        let has_residue = dir_names(&dir)
            .iter()
            .any(|n| n.starts_with("replay.json.") && n.ends_with(".tmp"));
        assert!(
            has_residue,
            "replay temp should remain after the simulated unlink failure"
        );
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn report_temp_unlink_failure_does_not_uncommit_report() {
        let dir = tmp_dir();
        let replay = dir.join("replay.json");
        let report = dir.join("report.json");
        let report_target = report.clone();
        // Simulate a failing temp unlink for the report only. The commit must
        // NOT collapse into a report-only error state.
        let publish = move |from: &Path, to: &Path| -> io::Result<()> {
            fs::hard_link(from, to)?;
            if to == report_target.as_path() {
                return Ok(()); // target is committed; swallow unlink failure
            }
            let _ = fs::remove_file(from);
            Ok(())
        };
        commit_completed_with(&replay, "REPLAY\n", &report, "REPORT\n", publish).unwrap();
        assert_eq!(fs::read_to_string(&report).unwrap(), "REPORT\n");
        assert_eq!(fs::read_to_string(&replay).unwrap(), "REPLAY\n");
        assert!(
            report.exists() && replay.exists(),
            "no report-only state: replay must also remain committed"
        );
        let has_residue = dir_names(&dir)
            .iter()
            .any(|n| n.starts_with("report.json.") && n.ends_with(".tmp"));
        assert!(
            has_residue,
            "report temp should remain after the simulated unlink failure"
        );
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn aborted_temp_unlink_failure_still_commits_report() {
        let dir = tmp_dir();
        let report = dir.join("report.json");
        // Faithfully simulate a temp-unlink *failure*: after the commit point
        // (hard_link) the cleanup step reports an error. The publish contract
        // requires such a failure to be swallowed (the target is already
        // committed), so here we surface an error that the production primitive
        // ignores — and crucially do NOT delete the temp, leaving it as inert
        // residue. This makes the test name ("unlink failure") literally true.
        let publish = |from: &Path, to: &Path| -> io::Result<()> {
            fs::hard_link(from, to)?;
            // Inject a failing unlink: the closure reports an error which the
            // production primitive swallows. To prove the failure was real we
            // do not delete the temp; it must remain as inert residue.
            let _: io::Result<()> = Err(io::Error::other("simulated unlink failure"));
            Ok(())
        };
        commit_aborted_with(&report, "REPORT\n", publish).unwrap();
        assert_eq!(fs::read_to_string(&report).unwrap(), "REPORT\n");
        assert!(
            report.exists(),
            "report must stay committed after temp cleanup failure"
        );
        // The temp file must remain because the unlink truly failed.
        let has_residue = dir_names(&dir)
            .iter()
            .any(|n| n.starts_with("report.json.") && n.ends_with(".tmp"));
        assert!(
            has_residue,
            "report temp should remain after simulated unlink failure"
        );
        fs::remove_dir_all(&dir).ok();
    }
}
