//! The `run-match` and `agent-random` CLI commands.
//!
//! These two commands are the stable user entry into the arena. They are
//! parsed by a small hand-written strict argument parser (not clap) so the
//! contract is exact: every flag is required, unknown/duplicate flags and any
//! extra positional argument are rejected, and `--help` prints usage and exits
//! `0`.
//!
//! `run-match` never interprets a shell string, expands environment variables,
//! or opens a socket. It reads a JSON [`ArenaConfig`], runs exactly one match
//! via [`ArenaRunner::run`], and publishes artifacts atomically:
//! - **Completed**: a pretty `report-out` *and* a pretty `replay-out`, only
//!   after re-checking `report.replay_final_hash == replay.final_state_hash`
//!   and that `verify_replay` passes. Exit `0`.
//! - **Aborted**: a pretty `report-out` only; `replay-out` is never created.
//!   Exit `2`.
//! - **CLI / config / I/O / internal error**: no artifacts, a single
//!   `error: <message>` line on stderr, empty stdout. Exit `1`.
//!
//! On success the *only* thing written to stdout is a single compact
//! `ArenaOutcomeV1` JSON line.

use std::io::{self, BufReader, Write};
use std::path::{Path, PathBuf};

use serde::Deserialize;
use splendor_arena::{ArenaConfig, ArenaRun, ArenaRunner};
use splendor_replay::verify_replay;

use crate::atomic_output;
use crate::random_agent::run_random_agent;

/// Maximum size of an arena config document, in bytes. A larger file is
/// rejected before any parse to bound accidental/hostile input.
pub const MAX_ARENA_CONFIG_BYTES: u64 = 1024 * 1024;

const RUN_MATCH_USAGE: &str = "\
Usage: splendor run-match --config <arena-config.json> \
--report-out <arena-report.json> --replay-out <replay.json>

Run exactly one arena match between the configured agent subprocesses.

Options:
  --config <path>      Path to the arena config JSON (UTF-8, <= 1 MiB).
  --report-out <path>  Path to write the arena report JSON. Must not exist.
  --replay-out <path>  Path to write the replay JSON (completed match only).
                       Must not exist and must differ from --report-out.
  -h, --help           Print this help and exit 0.

Exit codes: 0 completed, 2 aborted, 1 CLI/config/I/O/internal error.
Relative --config and agent program paths resolve against the current working
directory (and PATH for the program). No shell interpretation is performed.";

const AGENT_RANDOM_USAGE: &str = "\
Usage: splendor agent-random --seed <u64>

Reference stdio agent: reads server NDJSON on stdin, replies with a uniformly
random legal action on stdout. Deterministic for a given --seed.

Options:
  --seed <u64>   Seed for the stable action RNG (required).
  -h, --help     Print this help and exit 0.";

/// A user-facing error while preparing or committing a `run-match`. `Display`
/// yields the stable `error:` message body.
#[derive(Debug)]
enum RunMatchError {
    /// Bad command-line arguments.
    Cli(String),
    /// The config could not be read (missing, too large, non-UTF-8).
    ConfigRead(String),
    /// The config JSON failed strict deserialization.
    ConfigParse(String),
    /// The arena runner failed internally (not an agent abort).
    Internal(String),
    /// A completed match violated an artifact invariant (hash / verify).
    Artifact(String),
    /// Writing an artifact to disk failed.
    Io(String),
}

impl std::fmt::Display for RunMatchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RunMatchError::Cli(m)
            | RunMatchError::ConfigRead(m)
            | RunMatchError::ConfigParse(m)
            | RunMatchError::Internal(m)
            | RunMatchError::Artifact(m)
            | RunMatchError::Io(m) => write!(f, "{m}"),
        }
    }
}

/// Outcome of a successful `run-match`: which exit code and what to print.
enum MatchExit {
    Completed(i32),
    Aborted(i32),
}

/// Entry point for `splendor run-match ...`. Returns the process exit code.
pub fn run_match(args: &[String]) -> i32 {
    match run_match_inner(args) {
        Ok(MatchExit::Completed(code)) | Ok(MatchExit::Aborted(code)) => code,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {err}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run_match_inner(args: &[String]) -> Result<MatchExit, RunMatchError> {
    if wants_help(args) {
        print_stdout(RUN_MATCH_USAGE);
        // Help is a clean exit, modeled as a completed(0) with no output past
        // the usage text already printed.
        return Ok(MatchExit::Completed(0));
    }

    let parsed = parse_run_match_args(args).map_err(RunMatchError::Cli)?;

    // Output-path invariants, before touching the runner.
    if parsed.report_out == parsed.replay_out {
        return Err(RunMatchError::Cli(
            "--report-out and --replay-out must differ".to_string(),
        ));
    }
    if parsed.report_out.exists() {
        return Err(RunMatchError::Cli(format!(
            "report output already exists: {}",
            parsed.report_out.display()
        )));
    }
    if parsed.replay_out.exists() {
        return Err(RunMatchError::Cli(format!(
            "replay output already exists: {}",
            parsed.replay_out.display()
        )));
    }
    if !parent_dir_exists(&parsed.report_out) {
        return Err(RunMatchError::Cli(format!(
            "report output parent directory does not exist: {}",
            parsed.report_out.display()
        )));
    }
    if !parent_dir_exists(&parsed.replay_out) {
        return Err(RunMatchError::Cli(format!(
            "replay output parent directory does not exist: {}",
            parsed.replay_out.display()
        )));
    }

    let config = read_config(&parsed.config)?;

    let run: ArenaRun =
        ArenaRunner::run(config).map_err(|e| RunMatchError::Internal(e.to_string()))?;

    match run.replay {
        Some(replay) => commit_completed(&parsed, &run.report, &replay),
        None => commit_aborted(&parsed, &run.report),
    }
}

/// Read and strictly deserialize the arena config document.
fn read_config(path: &Path) -> Result<ArenaConfig, RunMatchError> {
    let metadata = std::fs::metadata(path).map_err(|e| {
        RunMatchError::ConfigRead(format!("cannot stat config {}: {e}", path.display()))
    })?;
    if metadata.len() > MAX_ARENA_CONFIG_BYTES {
        return Err(RunMatchError::ConfigRead(format!(
            "config exceeds {MAX_ARENA_CONFIG_BYTES} bytes ({} bytes)",
            metadata.len()
        )));
    }
    let raw = std::fs::read(path).map_err(|e| {
        RunMatchError::ConfigRead(format!("cannot read config {}: {e}", path.display()))
    })?;
    let text = String::from_utf8(raw)
        .map_err(|_| RunMatchError::ConfigRead("config is not valid UTF-8".to_string()))?;

    // Strict deserialize: ArenaConfig denies unknown fields; reject trailing
    // bytes after the JSON object as well.
    let mut de = serde_json::Deserializer::from_str(&text);
    let config = ArenaConfig::deserialize(&mut de)
        .map_err(|e| RunMatchError::ConfigParse(format!("invalid arena config: {e}")))?;
    de.end().map_err(|_| {
        RunMatchError::ConfigParse("trailing data after arena config JSON".to_string())
    })?;
    Ok(config)
}

/// Serialize and atomically publish a completed match's report + replay.
fn commit_completed(
    parsed: &RunMatchArgs,
    report: &splendor_arena::ArenaReportV1,
    replay: &splendor_replay::ReplayV1,
) -> Result<MatchExit, RunMatchError> {
    // Cross-check the report/replay binding before publishing anything.
    let replay_final_hash = match &report.outcome {
        splendor_arena::ArenaOutcomeV1::Completed {
            replay_final_hash, ..
        } => replay_final_hash.clone(),
        splendor_arena::ArenaOutcomeV1::Aborted { .. } => {
            return Err(RunMatchError::Internal(
                "runner returned a replay for an aborted outcome".to_string(),
            ));
        }
    };
    if replay_final_hash != replay.final_state_hash.as_str() {
        return Err(RunMatchError::Artifact(
            "report replay_final_hash does not match replay final_state_hash".to_string(),
        ));
    }
    verify_replay(replay)
        .map_err(|e| RunMatchError::Artifact(format!("replay failed verification: {e}")))?;

    let report_json = to_pretty_line(report)
        .map_err(|e| RunMatchError::Internal(format!("serialize report failed: {e}")))?;
    let replay_json = to_pretty_line(replay)
        .map_err(|e| RunMatchError::Internal(format!("serialize replay failed: {e}")))?;

    atomic_output::commit_completed(
        &parsed.replay_out,
        &replay_json,
        &parsed.report_out,
        &report_json,
    )
    .map_err(|e| RunMatchError::Io(e.to_string()))?;

    print_outcome_line(&report.outcome)?;
    Ok(MatchExit::Completed(0))
}

/// Serialize and atomically publish an aborted match's report (only).
fn commit_aborted(
    parsed: &RunMatchArgs,
    report: &splendor_arena::ArenaReportV1,
) -> Result<MatchExit, RunMatchError> {
    let report_json = to_pretty_line(report)
        .map_err(|e| RunMatchError::Internal(format!("serialize report failed: {e}")))?;
    atomic_output::commit_aborted(&parsed.report_out, &report_json)
        .map_err(|e| RunMatchError::Io(e.to_string()))?;
    print_outcome_line(&report.outcome)?;
    Ok(MatchExit::Aborted(2))
}

/// Print the single compact outcome JSON line to stdout.
fn print_outcome_line(outcome: &splendor_arena::ArenaOutcomeV1) -> Result<(), RunMatchError> {
    let line = serde_json::to_string(outcome)
        .map_err(|e| RunMatchError::Internal(format!("serialize outcome failed: {e}")))?;
    let mut stdout = io::stdout().lock();
    writeln!(stdout, "{line}")
        .map_err(|e| RunMatchError::Io(format!("stdout write failed: {e}")))?;
    stdout
        .flush()
        .map_err(|e| RunMatchError::Io(format!("stdout flush failed: {e}")))
}

/// Serialize a value with 2-space pretty formatting and a single trailing LF.
fn to_pretty_line<T: serde::Serialize>(value: &T) -> serde_json::Result<String> {
    let mut s = serde_json::to_string_pretty(value)?;
    s.push('\n');
    Ok(s)
}

// ---------------------------------------------------------------------------
// agent-random
// ---------------------------------------------------------------------------

/// Entry point for `splendor agent-random --seed <u64>`. Returns the exit code.
pub fn agent_random(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(AGENT_RANDOM_USAGE);
        return 0;
    }
    let seed = match parse_agent_random_args(args) {
        Ok(seed) => seed,
        Err(msg) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {msg}");
            let _ = stderr.flush();
            return 1;
        }
    };

    let stdin = io::stdin();
    let input = BufReader::new(stdin.lock());
    let stdout = io::stdout();
    let output = stdout.lock();
    let stderr = io::stderr();
    let diagnostics = stderr.lock();

    match run_random_agent(input, output, diagnostics, seed) {
        Ok(()) => 0,
        Err(_) => 1, // The diagnostic was already written to stderr.
    }
}

// ---------------------------------------------------------------------------
// Strict argument parsing
// ---------------------------------------------------------------------------

/// Parsed `run-match` arguments.
struct RunMatchArgs {
    config: PathBuf,
    report_out: PathBuf,
    replay_out: PathBuf,
}

fn parse_run_match_args(args: &[String]) -> Result<RunMatchArgs, String> {
    let mut config: Option<String> = None;
    let mut report_out: Option<String> = None;
    let mut replay_out: Option<String> = None;

    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        match arg {
            "--config" => set_flag(&mut config, "--config", args.get(i + 1))?,
            "--report-out" => set_flag(&mut report_out, "--report-out", args.get(i + 1))?,
            "--replay-out" => set_flag(&mut replay_out, "--replay-out", args.get(i + 1))?,
            other if other.starts_with('-') => {
                return Err(format!("unknown flag `{other}`"));
            }
            other => {
                return Err(format!("unexpected positional argument `{other}`"));
            }
        }
        i += 2;
    }

    let config = config.ok_or_else(|| "missing required --config".to_string())?;
    let report_out = report_out.ok_or_else(|| "missing required --report-out".to_string())?;
    let replay_out = replay_out.ok_or_else(|| "missing required --replay-out".to_string())?;

    Ok(RunMatchArgs {
        config: PathBuf::from(config),
        report_out: PathBuf::from(report_out),
        replay_out: PathBuf::from(replay_out),
    })
}

fn parse_agent_random_args(args: &[String]) -> Result<u64, String> {
    let mut seed: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        match arg {
            "--seed" => set_flag(&mut seed, "--seed", args.get(i + 1))?,
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        }
        i += 2;
    }
    let seed = seed.ok_or_else(|| "missing required --seed".to_string())?;
    seed.parse::<u64>()
        .map_err(|_| format!("--seed must be a u64 (got `{seed}`)"))
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
/// recognizable flag form (so `--config -5` is a value, `--config --report-out`
/// is a missing value). We treat a leading `--word` as a flag; other leading
/// dashes (negative numbers, stdin `-`) are values.
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
