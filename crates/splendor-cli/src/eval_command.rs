//! The `eval` CLI command.
//!
//! This is the deterministic evaluation *driver*: it reads and validates an
//! [`EvaluationPlanV1`], hashes it, expands the canonical schedule, runs
//! [`ArenaRunner::run`] serially per match, collects one
//! [`EvaluationMatchRecordV1`] per match, aggregates them into an
//! [`EvaluationReportV1`], and atomically publishes the artifacts:
//!
//! - `eval-report.json` — the consolidated roll-up (the **commit marker**);
//! - `plan.json` and `plan-hash.txt` — the inputs the report was built from;
//! - `matches/match-<index>.report.json` — every match's arena report;
//! - `matches/match-<index>.replay.json` — every *completed* match's replay
//!   (an aborted match publishes no replay).
//!
//! Per-match artifact filenames are derived **only** from the canonical
//! `match_index` — never from `game_id`. An evaluation ID may legally contain
//! path separators, `..`, or an absolute-path prefix (the C3 model only
//! rejects empty/overlong/control-character IDs), and the game ID embeds the
//! evaluation ID verbatim; using it in a filename would let plan content
//! escape the output directory. Records map files to matches via
//! `match_index`, which the canonical schedule guarantees to be dense and
//! unique; `game_id` remains inside the JSON artifacts themselves.
//!
//! All publishing is non-clobbering and atomic via [`atomic_output`]: each
//! target is written to a sibling temp and committed with a create-if-absent
//! `hard_link`. The per-match replay is committed before its report (so the
//! report is the per-match marker); the eval-level `plan.json` and
//! `plan-hash.txt` are committed before `eval-report.json`, which is the final
//! marker. If the final `eval-report.json` commit fails, the already-published
//! `plan.json`/`plan-hash.txt` are rolled back so the run is never observed as
//! partially persisted; the per-match artifacts, each independently committed,
//! remain as valid standalone deliverables.
//!
//! On success (including runs where some or all matches aborted) **stdout is
//! empty** — artifacts are the source of truth and diagnostics go to stderr.
//! Exit codes: `0` success, `1` fatal (invalid plan, runner internal error,
//! publish failure, missing output parent, pre-existing target).

use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::Deserialize;
use splendor_arena::{ArenaRun, ArenaRunner};
use splendor_eval::{
    aggregate, evaluation_plan_hash_v1, expand_schedule, EvaluationMatchRecordV1,
    EvaluationPlanHash, EvaluationPlanV1, EvaluationReportV1,
};

use crate::atomic_output;

/// Maximum size of an evaluation plan document, in bytes. A larger file is
/// rejected before any parse to bound accidental/hostile input.
pub const MAX_EVAL_PLAN_BYTES: u64 = 1024 * 1024;

const EVAL_USAGE: &str = "\
Usage: splendor eval --plan <evaluation-plan.json> --out-dir <dir>

Run a deterministic evaluation: read an evaluation plan, expand its canonical
schedule, play every match via the arena runner, aggregate the results, and
atomically publish the eval report plus per-match report/replay artifacts.

Options:
  --plan <path>      Path to the evaluation plan JSON (UTF-8, <= 1 MiB).
  --out-dir <dir>    Directory to write artifacts into. Must not already
                     contain eval-report.json / plan.json / plan-hash.txt, and
                     the directory's parent must exist. Created if absent.
  -h, --help         Print this help and exit 0.

Exit codes: 0 success (artifacts written; stdout empty), 1 fatal error.
Neither --plan nor --out-dir is interpreted as a shell string. Agent commands
embedded in the plan are spawned literally by the arena runner.";

/// A user-facing error while preparing, running, or committing an `eval`.
/// `Display` yields the stable `error:` message body.
#[derive(Debug)]
enum EvalError {
    /// Bad command-line arguments.
    Cli(String),
    /// The plan could not be read (missing, too large, non-UTF-8).
    PlanRead(String),
    /// The plan JSON failed strict deserialization.
    PlanParse(String),
    /// The plan failed validation or hashing.
    PlanInvalid(String),
    /// The arena runner failed internally (not an agent abort).
    Internal(String),
    /// Aggregation or an artifact invariant was violated.
    Artifact(String),
    /// Writing an artifact to disk failed.
    Io(String),
}

impl std::fmt::Display for EvalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EvalError::Cli(m)
            | EvalError::PlanRead(m)
            | EvalError::PlanParse(m)
            | EvalError::PlanInvalid(m)
            | EvalError::Internal(m)
            | EvalError::Artifact(m)
            | EvalError::Io(m) => write!(f, "{m}"),
        }
    }
}

/// Entry point for `splendor eval ...`. Returns the process exit code.
pub fn run_eval(args: &[String]) -> i32 {
    match run_eval_inner(args) {
        Ok(()) => 0,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {err}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run_eval_inner(args: &[String]) -> Result<(), EvalError> {
    if wants_help(args) {
        print_stdout(EVAL_USAGE);
        return Ok(());
    }

    let parsed = parse_eval_args(args).map_err(EvalError::Cli)?;

    let plan = read_plan(&parsed.plan)?;
    execute_plan_inner(plan, &parsed.out_dir)
}

/// Execute an already-deserialized plan into a fresh output directory.
///
/// The M16 round-robin driver uses this entry point so every pair receives the
/// exact same canonical execution and atomic artifact guarantees as the
/// standalone `eval` command.
pub(crate) fn execute_plan(plan: EvaluationPlanV1, out_dir: &Path) -> Result<(), String> {
    execute_plan_inner(plan, out_dir).map_err(|error| error.to_string())
}

fn execute_plan_inner(plan: EvaluationPlanV1, out_dir: &Path) -> Result<(), EvalError> {
    // Output invariants, before touching the runner or any target.
    if !parent_dir_exists(out_dir) {
        return Err(EvalError::Cli(format!(
            "output directory parent does not exist: {}",
            out_dir.display()
        )));
    }
    let eval_report_path = out_dir.join("eval-report.json");
    let plan_path = out_dir.join("plan.json");
    let hash_path = out_dir.join("plan-hash.txt");
    pre_check_target(&eval_report_path)?;
    pre_check_target(&plan_path)?;
    pre_check_target(&hash_path)?;

    // Validate + hash the plan.
    let plan_hash: EvaluationPlanHash =
        evaluation_plan_hash_v1(&plan).map_err(|e| EvalError::PlanInvalid(e.to_string()))?;

    // Expand the canonical schedule (cheap; already validated for hashing).
    let specs = expand_schedule(&plan).map_err(|e| EvalError::PlanInvalid(e.to_string()))?;

    // Pre-check every per-match target path so a pre-existing artifact fails
    // fast (exit 1) with no partial commits, rather than mid-run. The same
    // path helpers are used here and at publish time so the rules cannot
    // drift apart.
    let matches_dir = out_dir.join("matches");
    for spec in &specs {
        pre_check_target(&match_report_path(&matches_dir, spec.match_index))?;
        pre_check_target(&match_replay_path(&matches_dir, spec.match_index))?;
    }

    // Create the output tree now that all targets are confirmed clear.
    fs::create_dir_all(out_dir).map_err(|e| EvalError::Io(e.to_string()))?;
    fs::create_dir_all(&matches_dir).map_err(|e| EvalError::Io(e.to_string()))?;

    // Serial execution: run each match, collect a record, and publish its
    // artifacts atomically before moving to the next match.
    let mut records: Vec<EvaluationMatchRecordV1> = Vec::with_capacity(specs.len());
    for spec in &specs {
        let run: ArenaRun = ArenaRunner::run(spec.arena_config.clone())
            .map_err(|e| EvalError::Internal(e.to_string()))?;

        records.push(EvaluationMatchRecordV1 {
            match_index: spec.match_index,
            game_id: spec.arena_config.game_id.clone(),
            seed_index: spec.seed_index,
            rotation: spec.rotation,
            agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
            outcome: run.report.outcome.clone(),
        });

        let report_json = to_pretty_line(&run.report)
            .map_err(|e| EvalError::Internal(format!("serialize match report failed: {e}")))?;
        let report_path = match_report_path(&matches_dir, spec.match_index);

        match &run.replay {
            Some(replay) => {
                let replay_json = to_pretty_line(replay)
                    .map_err(|e| EvalError::Internal(format!("serialize replay failed: {e}")))?;
                let replay_path = match_replay_path(&matches_dir, spec.match_index);
                atomic_output::commit_completed_with(
                    &replay_path,
                    &replay_json,
                    &report_path,
                    &report_json,
                    atomic_output::publish_new,
                )
                .map_err(|e| EvalError::Io(e.to_string()))?;
            }
            None => {
                atomic_output::commit_aborted_with(
                    &report_path,
                    &report_json,
                    atomic_output::publish_new,
                )
                .map_err(|e| EvalError::Io(e.to_string()))?;
            }
        }
    }

    // Aggregate the records into the consolidated report.
    let report: EvaluationReportV1 =
        aggregate(&plan, &records).map_err(|e| EvalError::Artifact(e.to_string()))?;

    // Publish the eval-level artifacts: plan.json + plan-hash.txt first, then
    // eval-report.json LAST as the commit marker. Roll back the earlier two if
    // the marker fails so the run is never observed as partially persisted.
    let plan_json = to_pretty_line(&plan)
        .map_err(|e| EvalError::Internal(format!("serialize plan failed: {e}")))?;
    let hash_text = format!("{}\n", plan_hash);
    let eval_report_json = to_pretty_line(&report)
        .map_err(|e| EvalError::Internal(format!("serialize eval report failed: {e}")))?;

    commit_eval_report_with(
        &plan_path,
        &plan_json,
        &hash_path,
        &hash_text,
        &eval_report_path,
        &eval_report_json,
        atomic_output::publish_new,
    )?;

    Ok(())
}

/// Build the per-match report path from the canonical `match_index`.
///
/// This is the **only** source of per-match report filenames — both the
/// up-front pre-check and the publish path call it, so the naming rule cannot
/// drift. `game_id` (which embeds the caller-controlled evaluation ID and may
/// contain path separators or `..`) never enters a filesystem path.
fn match_report_path(matches_dir: &Path, match_index: u32) -> PathBuf {
    matches_dir.join(format!("match-{match_index:06}.report.json"))
}

/// Build the per-match replay path from the canonical `match_index`.
/// Same containment rule as [`match_report_path`].
fn match_replay_path(matches_dir: &Path, match_index: u32) -> PathBuf {
    matches_dir.join(format!("match-{match_index:06}.replay.json"))
}

/// Atomically publish `plan.json` then `plan-hash.txt`, then `eval-report.json`
/// (the commit marker) last. On any failure, roll back every artifact published
/// so far. Each commit is a create-if-absent `hard_link`, so a pre-existing
/// target (guarded by [`pre_check_target`] up front) would fail here too.
///
/// `publish` is injectable for fault tests (mirroring the M04
/// `commit_completed_with` pattern); production passes
/// [`atomic_output::publish_new`], whose commit-point semantics are unchanged.
#[allow(clippy::too_many_arguments)]
fn commit_eval_report_with<F>(
    plan_path: &Path,
    plan_json: &str,
    hash_path: &Path,
    hash_text: &str,
    report_path: &Path,
    report_json: &str,
    publish: F,
) -> Result<(), EvalError>
where
    F: Fn(&Path, &Path) -> io::Result<()>,
{
    // Write every temp up front so a mid-publish failure leaves at most temps
    // (which are inert) and never a half-written target.
    let plan_tmp = write_temp_checked(plan_path, plan_json)?;
    let hash_tmp = match write_temp_checked(hash_path, hash_text) {
        Ok(tmp) => tmp,
        Err(e) => {
            let _ = fs::remove_file(&plan_tmp);
            return Err(e);
        }
    };
    let report_tmp = match write_temp_checked(report_path, report_json) {
        Ok(tmp) => tmp,
        Err(e) => {
            let _ = fs::remove_file(&plan_tmp);
            let _ = fs::remove_file(&hash_tmp);
            return Err(e);
        }
    };

    // Publish plan.json (auxiliary), then hash.txt (auxiliary), then
    // eval-report.json (marker). Roll back on first failure.
    if let Err(source) = publish(&plan_tmp, plan_path) {
        let _ = fs::remove_file(&plan_tmp);
        let _ = fs::remove_file(&hash_tmp);
        let _ = fs::remove_file(&report_tmp);
        return Err(EvalError::Io(format!("commit plan.json failed: {source}")));
    }
    if let Err(source) = publish(&hash_tmp, hash_path) {
        let _ = fs::remove_file(plan_path);
        let _ = fs::remove_file(&hash_tmp);
        let _ = fs::remove_file(&report_tmp);
        return Err(EvalError::Io(format!(
            "commit plan-hash.txt failed: {source}"
        )));
    }
    if let Err(source) = publish(&report_tmp, report_path) {
        let _ = fs::remove_file(plan_path);
        let _ = fs::remove_file(hash_path);
        let _ = fs::remove_file(&report_tmp);
        return Err(EvalError::Io(format!(
            "commit eval-report.json failed: {source}"
        )));
    }

    Ok(())
}

/// Write a payload to a fresh sibling temp. Thin wrapper that maps the
/// `atomic_output` error into [`EvalError::Io`].
fn write_temp_checked(target: &Path, contents: &str) -> Result<PathBuf, EvalError> {
    atomic_output::write_temp(target, contents).map_err(|e| EvalError::Io(e.to_string()))
}

/// Fail if `target` already exists, so the create-if-absent publish never
/// clobbers a prior artifact. A missing target (including a not-yet-created
/// output directory) is fine.
fn pre_check_target(target: &Path) -> Result<(), EvalError> {
    if target.exists() {
        return Err(EvalError::Cli(format!(
            "artifact already exists: {}",
            target.display()
        )));
    }
    Ok(())
}

/// Read and strictly deserialize the evaluation plan document.
///
/// The read is *bounded by the bytes actually read*, not by an up-front
/// `metadata.len()` that a growing file could outrun: we read at most
/// `MAX_EVAL_PLAN_BYTES + 1` bytes and reject if that overflows the limit.
fn read_plan(path: &Path) -> Result<EvaluationPlanV1, EvalError> {
    let file = File::open(path)
        .map_err(|e| EvalError::PlanRead(format!("cannot open plan {}: {e}", path.display())))?;
    let mut raw = Vec::new();
    file.take(MAX_EVAL_PLAN_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|e| EvalError::PlanRead(format!("cannot read plan {}: {e}", path.display())))?;
    if raw.len() as u64 > MAX_EVAL_PLAN_BYTES {
        return Err(EvalError::PlanRead(format!(
            "plan exceeds {MAX_EVAL_PLAN_BYTES} bytes"
        )));
    }
    let text = String::from_utf8(raw)
        .map_err(|_| EvalError::PlanRead("plan is not valid UTF-8".to_string()))?;

    // Strict deserialize: EvaluationPlanV1 denies unknown fields; reject
    // trailing bytes after the JSON object as well.
    let mut de = serde_json::Deserializer::from_str(&text);
    let plan = EvaluationPlanV1::deserialize(&mut de)
        .map_err(|e| EvalError::PlanParse(format!("invalid evaluation plan: {e}")))?;
    de.end().map_err(|_| {
        EvalError::PlanParse("trailing data after evaluation plan JSON".to_string())
    })?;
    Ok(plan)
}

/// Serialize a value with 2-space pretty formatting and a single trailing LF.
fn to_pretty_line<T: serde::Serialize>(value: &T) -> serde_json::Result<String> {
    let mut s = serde_json::to_string_pretty(value)?;
    s.push('\n');
    Ok(s)
}

// ---------------------------------------------------------------------------
// Strict argument parsing
// ---------------------------------------------------------------------------

/// Parsed `eval` arguments.
struct EvalArgs {
    plan: PathBuf,
    out_dir: PathBuf,
}

fn parse_eval_args(args: &[String]) -> Result<EvalArgs, String> {
    let mut plan: Option<String> = None;
    let mut out_dir: Option<String> = None;

    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        match arg {
            "--plan" => set_flag(&mut plan, "--plan", args.get(i + 1))?,
            "--out-dir" => set_flag(&mut out_dir, "--out-dir", args.get(i + 1))?,
            other if other.starts_with('-') => {
                return Err(format!("unknown flag `{other}`"));
            }
            other => {
                return Err(format!("unexpected positional argument `{other}`"));
            }
        }
        i += 2;
    }

    let plan = plan.ok_or_else(|| "missing required --plan".to_string())?;
    let out_dir = out_dir.ok_or_else(|| "missing required --out-dir".to_string())?;

    Ok(EvalArgs {
        plan: PathBuf::from(plan),
        out_dir: PathBuf::from(out_dir),
    })
}

/// Assign a flag value exactly once, rejecting duplicates and missing values.
fn set_flag(slot: &mut Option<String>, name: &str, value: Option<&String>) -> Result<(), String> {
    if slot.is_some() {
        return Err(format!("duplicate flag `{name}`"));
    }
    match value {
        Some(v) if looks_like_value(v) => {
            *slot = Some(v.clone());
            Ok(())
        }
        _ => Err(format!("flag `{name}` is missing a value")),
    }
}

/// A value token that begins with `-` is accepted only if it is not itself a
/// recognizable flag form (so `--plan -5` is a value, `--plan --out-dir` is a
/// missing value). We treat a leading `--word` as a flag; other leading dashes
/// (negative numbers, stdin `-`) are values.
fn looks_like_value(token: &str) -> bool {
    !token.starts_with("--")
}

fn wants_help(args: &[String]) -> bool {
    args.iter().any(|a| a == "--help" || a == "-h")
}

fn parent_dir_exists(path: &Path) -> bool {
    match path.parent() {
        Some(dir) if dir.as_os_str().is_empty() => true, // implicit current dir
        Some(dir) => dir.is_dir(),
        None => true,
    }
}

fn print_stdout(text: &str) {
    let mut stdout = io::stdout().lock();
    let _ = writeln!(stdout, "{text}");
    let _ = stdout.flush();
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    /// Per-match artifact names are derived only from `match_index` with a
    /// fixed, zero-padded shape; the (caller-controlled) game ID never
    /// appears in a filesystem path.
    #[test]
    fn match_artifact_paths_use_only_match_index() {
        let dir = PathBuf::from("out/matches");
        assert_eq!(
            match_report_path(&dir, 0),
            dir.join("match-000000.report.json")
        );
        assert_eq!(
            match_replay_path(&dir, 0),
            dir.join("match-000000.replay.json")
        );
        assert_eq!(
            match_report_path(&dir, 123_456),
            dir.join("match-123456.report.json")
        );
    }

    // -----------------------------------------------------------------
    // commit_eval_report_with fault injection (M04-style callback form)
    // -----------------------------------------------------------------

    struct EvalCommitFixture {
        dir: PathBuf,
        plan_path: PathBuf,
        hash_path: PathBuf,
        report_path: PathBuf,
    }

    fn eval_commit_fixture(label: &str) -> EvalCommitFixture {
        static SEQ: AtomicU32 = AtomicU32::new(0);
        let n = SEQ.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "splendor-eval-commit-{}-{label}-{n}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).unwrap();
        EvalCommitFixture {
            plan_path: dir.join("plan.json"),
            hash_path: dir.join("plan-hash.txt"),
            report_path: dir.join("eval-report.json"),
            dir,
        }
    }

    fn commit_with<F>(fx: &EvalCommitFixture, publish: F) -> Result<(), EvalError>
    where
        F: Fn(&Path, &Path) -> io::Result<()>,
    {
        commit_eval_report_with(
            &fx.plan_path,
            "{\"plan\":true}\n",
            &fx.hash_path,
            "hash\n",
            &fx.report_path,
            "{\"report\":true}\n",
            publish,
        )
    }

    /// No leftover temp siblings in the fixture directory. Real temp names
    /// have the shape `<target>.<pid>.<seq>.tmp`, so match the `.tmp` suffix.
    fn assert_no_temp_residue(dir: &Path) {
        let leftovers: Vec<String> = fs::read_dir(dir)
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .filter(|n| n.ends_with(".tmp"))
            .collect();
        assert!(leftovers.is_empty(), "temp residue found: {leftovers:?}");
    }

    /// A publish callback that fails when the target file name matches
    /// `fail_on`, and otherwise delegates to the real `publish_new`.
    fn failing_on(fail_on: &'static str) -> impl Fn(&Path, &Path) -> io::Result<()> {
        move |temp: &Path, target: &Path| {
            if target.file_name().and_then(|n| n.to_str()) == Some(fail_on) {
                return Err(io::Error::other(format!("injected failure on {fail_on}")));
            }
            atomic_output::publish_new(temp, target)
        }
    }

    #[test]
    fn eval_commit_plan_publish_failure_leaves_nothing() {
        let fx = eval_commit_fixture("plan-fail");
        let err = commit_with(&fx, failing_on("plan.json")).unwrap_err();
        assert!(err.to_string().contains("commit plan.json failed"));
        assert!(!fx.plan_path.exists(), "plan.json must not be committed");
        assert!(
            !fx.hash_path.exists(),
            "plan-hash.txt must not be committed"
        );
        assert!(!fx.report_path.exists(), "marker must not be committed");
        assert_no_temp_residue(&fx.dir);
    }

    #[test]
    fn eval_commit_hash_publish_failure_rolls_back_plan() {
        let fx = eval_commit_fixture("hash-fail");
        let err = commit_with(&fx, failing_on("plan-hash.txt")).unwrap_err();
        assert!(err.to_string().contains("commit plan-hash.txt failed"));
        assert!(
            !fx.plan_path.exists(),
            "already-committed plan.json must be rolled back"
        );
        assert!(!fx.hash_path.exists());
        assert!(!fx.report_path.exists(), "marker must not be committed");
        assert_no_temp_residue(&fx.dir);
    }

    #[test]
    fn eval_commit_marker_publish_failure_rolls_back_plan_and_hash() {
        let fx = eval_commit_fixture("marker-fail");
        let err = commit_with(&fx, failing_on("eval-report.json")).unwrap_err();
        assert!(err.to_string().contains("commit eval-report.json failed"));
        assert!(
            !fx.plan_path.exists() && !fx.hash_path.exists(),
            "no committed auxiliary targets may remain after marker failure"
        );
        assert!(!fx.report_path.exists());
        assert_no_temp_residue(&fx.dir);
    }

    #[test]
    fn eval_commit_pre_existing_marker_race_fails_and_preserves_it() {
        let fx = eval_commit_fixture("race");
        // Simulate a race: the marker target appears after the pre-check.
        let sentinel = "SENTINEL\n";
        fs::write(&fx.report_path, sentinel).unwrap();
        let err = commit_with(&fx, atomic_output::publish_new).unwrap_err();
        assert!(err.to_string().contains("commit eval-report.json failed"));
        assert_eq!(
            fs::read_to_string(&fx.report_path).unwrap(),
            sentinel,
            "pre-existing marker must never be clobbered"
        );
        assert!(
            !fx.plan_path.exists() && !fx.hash_path.exists(),
            "auxiliary targets must be rolled back after the race failure"
        );
        assert_no_temp_residue(&fx.dir);
    }

    #[test]
    fn eval_commit_success_commits_all_three() {
        let fx = eval_commit_fixture("ok");
        commit_with(&fx, atomic_output::publish_new).unwrap();
        assert!(fx.plan_path.exists() && fx.hash_path.exists() && fx.report_path.exists());
        assert_no_temp_residue(&fx.dir);
    }

    #[test]
    fn parse_eval_args_requires_both_flags() {
        assert!(parse_eval_args(&[]).is_err());
        assert!(parse_eval_args(&["--plan".into(), "p.json".into()]).is_err());
        assert!(parse_eval_args(&["--out-dir".into(), "out".into()]).is_err());
        let ok = parse_eval_args(&[
            "--plan".into(),
            "p.json".into(),
            "--out-dir".into(),
            "out".into(),
        ])
        .unwrap();
        assert_eq!(ok.plan, PathBuf::from("p.json"));
        assert_eq!(ok.out_dir, PathBuf::from("out"));
    }

    #[test]
    fn parse_eval_args_rejects_unknown_and_duplicate() {
        assert!(parse_eval_args(&[
            "--plan".into(),
            "p.json".into(),
            "--out-dir".into(),
            "out".into(),
            "--bogus".into(),
        ])
        .is_err());
        assert!(parse_eval_args(&[
            "--plan".into(),
            "p.json".into(),
            "--plan".into(),
            "q.json".into(),
            "--out-dir".into(),
            "out".into(),
        ])
        .is_err());
    }

    #[test]
    fn help_flag_is_detected() {
        assert!(wants_help(&["--help".into()]));
        assert!(wants_help(&["-h".into()]));
        assert!(!wants_help(&["--plan".into(), "p.json".into()]));
    }
}
