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

use std::fs::{self, File};
use std::io::{self, BufReader, Read, Write};
use std::path::{Path, PathBuf};

use serde::Deserialize;
use splendor_arena::{ArenaConfig, ArenaRun, ArenaRunner};
use splendor_replay::verify_replay;

use crate::atomic_output;
use splendor_agent::{run_heuristic_agent, run_random_agent};
use splendor_determinization_agent::run_determinization_agent_v1;
use splendor_imperfect_search::RootDeterminizationConfigV1;
use splendor_ismcts::IsmctsConfigV1;
use splendor_ismcts_agent::run_ismcts_agent_v1;
use splendor_learning::PolicyValueCheckpointV1;
use splendor_neural_agent::run_neural_ismcts_agent_v1;
use splendor_neural_search::NeuralIsmctsConfigV1;
use splendor_search::SearchConfigV1;

/// Maximum size of an arena config document, in bytes. A larger file is
/// rejected before any parse to bound accidental/hostile input.
pub const MAX_ARENA_CONFIG_BYTES: u64 = 1024 * 1024;
pub const MAX_POLICY_VALUE_CHECKPOINT_BYTES: u64 = 16 * 1024 * 1024;

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

const AGENT_HEURISTIC_USAGE: &str = "\
Usage: splendor agent-heuristic --seed <u64>

Deterministic heuristic stdio agent: reads server NDJSON on stdin, replies with
the highest-scoring legal action on stdout. Uses the --seed only to break ties
among equally-scored actions; a unique best action is chosen without consuming
the RNG, so the same server transcript always yields the same action.

Options:
  --seed <u64>   Seed for the tie-break RNG (required).
  -h, --help     Print this help and exit 0.";

const AGENT_DETERMINIZATION_USAGE: &str = "\
Usage: splendor agent-determinization --sample-seed <u64> \
--sample-count <u16> --max-depth-turns <u8> --max-nodes <u64>

Player-view-only root-determinization stdio agent. Every decision is built from
the live Observation plus cumulative VisibleEvent history; no replay or raw
game seed crosses the policy boundary.

Options:
  --sample-seed <u64>      Deterministic hidden-state sampler seed (required).
  --sample-count <u16>     Number of determinizations, 1..=64 (required).
  --max-depth-turns <u8>   MaxN continuation depth, 1..=12 (required).
  --max-nodes <u64>        MaxN node budget, 1..=10000000 (required).
  -h, --help               Print this help and exit 0.";

const AGENT_ISMCTS_USAGE: &str = "\
Usage: splendor agent-ismcts --sample-seed <u64> --simulations <u32> \
--max-depth-turns <u8> --exploration-bias <u64>

Player-view-only information-set MCTS agent. Simulations sample hidden worlds,
while future policies are shared by acting-player Observation identity.

Options:
  --sample-seed <u64>       Deterministic hidden-state sampler seed.
  --simulations <u32>       Simulation budget, 1..=10000.
  --max-depth-turns <u8>    Simulation depth in completed turns, 1..=8.
  --exploration-bias <u64>  Integer confidence bonus, 0..=1000000000000.
  -h, --help                Print this help and exit 0.";

const AGENT_NEURAL_ISMCTS_USAGE: &str = "\
Usage: splendor agent-neural-ismcts --checkpoint <checkpoint.json> \
--checkpoint-hash <sha256> --sample-seed <u64> --simulations <u32> \
--max-depth-turns <u8> --puct-exploration-milli <u32>

M13 player-view neural-guided information-set MCTS agent. The M12 checkpoint
is strictly parsed, validated and matched to the required semantic hash before
the protocol handshake. Model inference receives Observation only.

Options:
  --checkpoint <path>              M12 checkpoint JSON, <= 16 MiB.
  --checkpoint-hash <sha256>       Required semantic checkpoint hash.
  --sample-seed <u64>              Deterministic hidden-state sampler seed.
  --simulations <u32>              Simulation budget, 1..=10000.
  --max-depth-turns <u8>           Simulation depth in completed turns, 1..=8.
  --puct-exploration-milli <u32>   PUCT constant x1000, 0..=100000.
  -h, --help                       Print this help and exit 0.";

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
///
/// The read is *bounded by the bytes actually read*, not by an up-front
/// `metadata.len()` that a growing file could outrun: we read at most
/// `MAX_ARENA_CONFIG_BYTES + 1` bytes and reject if that overflows the limit.
fn read_config(path: &Path) -> Result<ArenaConfig, RunMatchError> {
    let file = File::open(path).map_err(|e| {
        RunMatchError::ConfigRead(format!("cannot open config {}: {e}", path.display()))
    })?;
    let mut raw = Vec::new();
    file.take(MAX_ARENA_CONFIG_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|e| {
            RunMatchError::ConfigRead(format!("cannot read config {}: {e}", path.display()))
        })?;
    if raw.len() as u64 > MAX_ARENA_CONFIG_BYTES {
        return Err(RunMatchError::ConfigRead(format!(
            "config exceeds {MAX_ARENA_CONFIG_BYTES} bytes"
        )));
    }
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

    let mut stdout = io::stdout().lock();
    publish_completed(
        &parsed.replay_out,
        &replay_json,
        &parsed.report_out,
        &report_json,
        &report.outcome,
        &mut stdout,
        atomic_output::publish_new,
    )
}

/// Serialize and atomically publish an aborted match's report (only).
fn commit_aborted(
    parsed: &RunMatchArgs,
    report: &splendor_arena::ArenaReportV1,
) -> Result<MatchExit, RunMatchError> {
    let report_json = to_pretty_line(report)
        .map_err(|e| RunMatchError::Internal(format!("serialize report failed: {e}")))?;
    let mut stdout = io::stdout().lock();
    publish_aborted(
        &parsed.report_out,
        &report_json,
        &report.outcome,
        &mut stdout,
        atomic_output::publish_new,
    )
}

/// Publish a completed pair, then emit the outcome line — order matters.
///
/// The compact outcome line is serialized *before* any artifact is committed,
/// and if the stdout write or flush fails *after* the artifacts landed, **both**
/// artifacts are removed and an I/O error is returned. This upholds the frozen
/// contract: an error exit (1) must never leave artifacts behind, even when
/// stdout is a closed pipe.
fn publish_completed<W, P>(
    replay_out: &Path,
    replay_json: &str,
    report_out: &Path,
    report_json: &str,
    outcome: &splendor_arena::ArenaOutcomeV1,
    stdout: &mut W,
    publish: P,
) -> Result<MatchExit, RunMatchError>
where
    W: Write,
    P: Fn(&Path, &Path) -> io::Result<()>,
{
    let line = compact_outcome_line(outcome)?;
    atomic_output::commit_completed_with(replay_out, replay_json, report_out, report_json, publish)
        .map_err(|e| RunMatchError::Io(e.to_string()))?;
    if let Err(e) = write_outcome_line(stdout, &line) {
        let _ = fs::remove_file(report_out);
        let _ = fs::remove_file(replay_out);
        return Err(RunMatchError::Io(e));
    }
    Ok(MatchExit::Completed(0))
}

/// Publish an aborted report, then emit the outcome line, with the same
/// serialize-first / roll-back-on-stdout-failure discipline as
/// [`publish_completed`].
fn publish_aborted<W, P>(
    report_out: &Path,
    report_json: &str,
    outcome: &splendor_arena::ArenaOutcomeV1,
    stdout: &mut W,
    publish: P,
) -> Result<MatchExit, RunMatchError>
where
    W: Write,
    P: Fn(&Path, &Path) -> io::Result<()>,
{
    let line = compact_outcome_line(outcome)?;
    atomic_output::commit_aborted_with(report_out, report_json, publish)
        .map_err(|e| RunMatchError::Io(e.to_string()))?;
    if let Err(e) = write_outcome_line(stdout, &line) {
        let _ = fs::remove_file(report_out);
        return Err(RunMatchError::Io(e));
    }
    Ok(MatchExit::Aborted(2))
}

/// Serialize the single compact outcome JSON line (no trailing newline yet).
fn compact_outcome_line(outcome: &splendor_arena::ArenaOutcomeV1) -> Result<String, RunMatchError> {
    serde_json::to_string(outcome)
        .map_err(|e| RunMatchError::Internal(format!("serialize outcome failed: {e}")))
}

/// Write the outcome line + LF to `stdout` and flush, returning a stable error
/// string on failure (mapped to `RunMatchError::Io` by the caller).
fn write_outcome_line<W: Write>(stdout: &mut W, line: &str) -> Result<(), String> {
    writeln!(stdout, "{line}").map_err(|e| format!("stdout write failed: {e}"))?;
    stdout
        .flush()
        .map_err(|e| format!("stdout flush failed: {e}"))
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
// agent-heuristic
// ---------------------------------------------------------------------------

/// Entry point for `splendor agent-heuristic --seed <u64>`. Returns the exit code.
///
/// The argument contract is identical to `agent_random` (required `--seed`,
/// strict flag parsing, help on `-h`/`--help`). It drives the same generic
/// runtime via [`run_heuristic_agent`], so stdout carries only client NDJSON
/// and diagnostics go to stderr.
pub fn agent_heuristic(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(AGENT_HEURISTIC_USAGE);
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

    match run_heuristic_agent(input, output, diagnostics, seed) {
        Ok(()) => 0,
        Err(_) => 1, // The diagnostic was already written to stderr.
    }
}

// ---------------------------------------------------------------------------
// agent-determinization
// ---------------------------------------------------------------------------

/// Entry point for the live M07-backed player-view search agent.
pub fn agent_determinization(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(AGENT_DETERMINIZATION_USAGE);
        return 0;
    }
    let config = match parse_agent_determinization_args(args) {
        Ok(config) => config,
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

    match run_determinization_agent_v1(input, output, diagnostics, config) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

/// Entry point for the live M10 information-set tree-search agent.
pub fn agent_ismcts(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(AGENT_ISMCTS_USAGE);
        return 0;
    }
    let config = match parse_agent_ismcts_args(args) {
        Ok(config) => config,
        Err(message) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {message}");
            let _ = stderr.flush();
            return 1;
        }
    };
    let stdin = io::stdin();
    let stdout = io::stdout();
    let stderr = io::stderr();
    match run_ismcts_agent_v1(
        BufReader::new(stdin.lock()),
        stdout.lock(),
        stderr.lock(),
        config,
    ) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

/// Entry point for the live M13 checkpoint-bound neural search agent.
pub fn agent_neural_ismcts(args: &[String]) -> i32 {
    if wants_help(args) {
        print_stdout(AGENT_NEURAL_ISMCTS_USAGE);
        return 0;
    }
    let parsed = match parse_agent_neural_ismcts_args(args) {
        Ok(parsed) => parsed,
        Err(message) => return print_agent_error(&message),
    };
    let checkpoint = match read_neural_checkpoint(&parsed.checkpoint) {
        Ok(checkpoint) => checkpoint,
        Err(message) => return print_agent_error(&message),
    };
    let stdin = io::stdin();
    let stdout = io::stdout();
    let stderr = io::stderr();
    match run_neural_ismcts_agent_v1(
        BufReader::new(stdin.lock()),
        stdout.lock(),
        stderr.lock(),
        checkpoint,
        parsed.config,
    ) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

fn print_agent_error(message: &str) -> i32 {
    let mut stderr = io::stderr().lock();
    let _ = writeln!(stderr, "error: {message}");
    let _ = stderr.flush();
    1
}

fn read_neural_checkpoint(path: &Path) -> Result<PolicyValueCheckpointV1, String> {
    let file = File::open(path)
        .map_err(|error| format!("cannot open checkpoint {}: {error}", path.display()))?;
    let mut bytes = Vec::new();
    file.take(MAX_POLICY_VALUE_CHECKPOINT_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("cannot read checkpoint {}: {error}", path.display()))?;
    if bytes.len() as u64 > MAX_POLICY_VALUE_CHECKPOINT_BYTES {
        return Err(format!(
            "checkpoint exceeds {MAX_POLICY_VALUE_CHECKPOINT_BYTES} bytes"
        ));
    }
    let text = String::from_utf8(bytes).map_err(|_| "checkpoint is not valid UTF-8".to_string())?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let checkpoint = PolicyValueCheckpointV1::deserialize(&mut deserializer)
        .map_err(|error| format!("invalid checkpoint: {error}"))?;
    deserializer
        .end()
        .map_err(|_| "trailing data after checkpoint JSON".to_string())?;
    Ok(checkpoint)
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

fn parse_agent_determinization_args(
    args: &[String],
) -> Result<RootDeterminizationConfigV1, String> {
    let mut sample_seed: Option<String> = None;
    let mut sample_count: Option<String> = None;
    let mut max_depth_turns: Option<String> = None;
    let mut max_nodes: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        match arg {
            "--sample-seed" => set_flag(&mut sample_seed, arg, args.get(i + 1))?,
            "--sample-count" => set_flag(&mut sample_count, arg, args.get(i + 1))?,
            "--max-depth-turns" => set_flag(&mut max_depth_turns, arg, args.get(i + 1))?,
            "--max-nodes" => set_flag(&mut max_nodes, arg, args.get(i + 1))?,
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        }
        i += 2;
    }

    let sample_seed = parse_required_number::<u64>(sample_seed, "--sample-seed", "u64")?;
    let sample_count = parse_required_number::<u16>(sample_count, "--sample-count", "u16")?;
    let max_depth_turns = parse_required_number::<u8>(max_depth_turns, "--max-depth-turns", "u8")?;
    let max_nodes = parse_required_number::<u64>(max_nodes, "--max-nodes", "u64")?;

    Ok(RootDeterminizationConfigV1 {
        sample_seed,
        sample_count,
        continuation_search: SearchConfigV1 {
            max_depth_turns,
            max_nodes,
        },
    })
}

fn parse_agent_ismcts_args(args: &[String]) -> Result<IsmctsConfigV1, String> {
    let mut sample_seed = None;
    let mut simulations = None;
    let mut max_depth_turns = None;
    let mut exploration_bias = None;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        match flag {
            "--sample-seed" => set_flag(&mut sample_seed, flag, args.get(index + 1))?,
            "--simulations" => set_flag(&mut simulations, flag, args.get(index + 1))?,
            "--max-depth-turns" => set_flag(&mut max_depth_turns, flag, args.get(index + 1))?,
            "--exploration-bias" => set_flag(&mut exploration_bias, flag, args.get(index + 1))?,
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        }
        index += 2;
    }
    let config = IsmctsConfigV1 {
        sample_seed: parse_required_number(sample_seed, "--sample-seed", "u64")?,
        simulations: parse_required_number(simulations, "--simulations", "u32")?,
        max_depth_turns: parse_required_number(max_depth_turns, "--max-depth-turns", "u8")?,
        exploration_bias: parse_required_number(exploration_bias, "--exploration-bias", "u64")?,
    };
    config.validate().map_err(|error| error.to_string())?;
    Ok(config)
}

struct NeuralAgentArgs {
    checkpoint: PathBuf,
    config: NeuralIsmctsConfigV1,
}

fn parse_agent_neural_ismcts_args(args: &[String]) -> Result<NeuralAgentArgs, String> {
    let mut checkpoint = None;
    let mut checkpoint_hash = None;
    let mut sample_seed = None;
    let mut simulations = None;
    let mut max_depth_turns = None;
    let mut puct_exploration_milli = None;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        match flag {
            "--checkpoint" => set_flag(&mut checkpoint, flag, args.get(index + 1))?,
            "--checkpoint-hash" => set_flag(&mut checkpoint_hash, flag, args.get(index + 1))?,
            "--sample-seed" => set_flag(&mut sample_seed, flag, args.get(index + 1))?,
            "--simulations" => set_flag(&mut simulations, flag, args.get(index + 1))?,
            "--max-depth-turns" => set_flag(&mut max_depth_turns, flag, args.get(index + 1))?,
            "--puct-exploration-milli" => {
                set_flag(&mut puct_exploration_milli, flag, args.get(index + 1))?
            }
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        }
        index += 2;
    }
    let config = NeuralIsmctsConfigV1 {
        sample_seed: parse_required_number(sample_seed, "--sample-seed", "u64")?,
        simulations: parse_required_number(simulations, "--simulations", "u32")?,
        max_depth_turns: parse_required_number(max_depth_turns, "--max-depth-turns", "u8")?,
        puct_exploration_milli: parse_required_number(
            puct_exploration_milli,
            "--puct-exploration-milli",
            "u32",
        )?,
        expected_checkpoint_hash: checkpoint_hash
            .ok_or_else(|| "missing required --checkpoint-hash".to_string())?,
    };
    config.validate().map_err(|error| error.to_string())?;
    Ok(NeuralAgentArgs {
        checkpoint: PathBuf::from(
            checkpoint.ok_or_else(|| "missing required --checkpoint".to_string())?,
        ),
        config,
    })
}

fn parse_required_number<T>(value: Option<String>, flag: &str, kind: &str) -> Result<T, String>
where
    T: std::str::FromStr,
{
    let value = value.ok_or_else(|| format!("missing required {flag}"))?;
    value
        .parse::<T>()
        .map_err(|_| format!("{flag} must be a {kind} (got `{value}`)"))
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    use splendor_arena::{AgentFault, ArenaOutcomeV1, ArenaPhase};

    static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

    fn tmp_dir() -> PathBuf {
        let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("arena-cmd-{}-{}", std::process::id(), n));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn assert_no_tmp(dir: &Path) {
        for entry in fs::read_dir(dir).unwrap() {
            let name = entry.unwrap().file_name().to_string_lossy().into_owned();
            assert!(!name.ends_with(".tmp"), "temp residue: {name}");
        }
    }

    /// A stand-in outcome; only its serialized bytes matter to these tests.
    fn sample_outcome() -> ArenaOutcomeV1 {
        ArenaOutcomeV1::aborted(0, ArenaPhase::Handshake, AgentFault::AgentIo, None, 0)
    }

    #[test]
    fn neural_agent_parser_binds_checkpoint_and_all_search_budgets() {
        let args = [
            "--checkpoint",
            "model.json",
            "--checkpoint-hash",
            &"11".repeat(32),
            "--sample-seed",
            "17",
            "--simulations",
            "64",
            "--max-depth-turns",
            "2",
            "--puct-exploration-milli",
            "1500",
        ]
        .iter()
        .map(|value| (*value).to_string())
        .collect::<Vec<_>>();
        let parsed = parse_agent_neural_ismcts_args(&args).unwrap();
        assert_eq!(parsed.checkpoint, PathBuf::from("model.json"));
        assert_eq!(parsed.config.simulations, 64);
        assert_eq!(parsed.config.puct_exploration_milli, 1_500);

        let mut missing = args.clone();
        missing.drain(2..4);
        assert!(parse_agent_neural_ismcts_args(&missing).is_err());
    }

    /// A `Write` that fails on `write` (fail_flush=false) or on `flush`
    /// (fail_flush=true), used to simulate a closed stdout pipe.
    struct FailWriter {
        fail_flush: bool,
    }

    impl Write for FailWriter {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            if self.fail_flush {
                Ok(buf.len())
            } else {
                Err(io::Error::other("stdout write failed"))
            }
        }
        fn flush(&mut self) -> io::Result<()> {
            if self.fail_flush {
                Err(io::Error::other("stdout flush failed"))
            } else {
                Ok(())
            }
        }
    }

    // -- Blocker 1: a target that appears during the match is never clobbered --

    #[test]
    fn report_target_appears_during_match_is_not_overwritten() {
        // Model the race: the early exists() check passed, the match ran, and
        // the report target appeared before final publish. publish_new must
        // refuse to clobber it; our replay is rolled back; nothing on stdout.
        let dir = tmp_dir();
        let replay_out = dir.join("replay.json");
        let report_out = dir.join("report.json");
        fs::write(&report_out, "PRE-EXISTING REPORT").unwrap();

        let mut stdout: Vec<u8> = Vec::new();
        let res = publish_completed(
            &replay_out,
            "REPLAY\n",
            &report_out,
            "REPORT\n",
            &sample_outcome(),
            &mut stdout,
            atomic_output::publish_new,
        );

        assert!(matches!(res, Err(RunMatchError::Io(_))));
        assert_eq!(
            fs::read_to_string(&report_out).unwrap(),
            "PRE-EXISTING REPORT",
            "pre-existing report must be preserved"
        );
        assert!(!replay_out.exists(), "our replay must be rolled back");
        assert!(stdout.is_empty(), "no stdout on error");
        assert_no_tmp(&dir);
    }

    #[test]
    fn replay_target_appears_during_match_is_not_overwritten() {
        let dir = tmp_dir();
        let replay_out = dir.join("replay.json");
        let report_out = dir.join("report.json");
        fs::write(&replay_out, "PRE-EXISTING REPLAY").unwrap();

        let mut stdout: Vec<u8> = Vec::new();
        let res = publish_completed(
            &replay_out,
            "REPLAY\n",
            &report_out,
            "REPORT\n",
            &sample_outcome(),
            &mut stdout,
            atomic_output::publish_new,
        );

        assert!(matches!(res, Err(RunMatchError::Io(_))));
        assert_eq!(
            fs::read_to_string(&replay_out).unwrap(),
            "PRE-EXISTING REPLAY",
            "pre-existing replay must be preserved"
        );
        assert!(!report_out.exists(), "our report must not be published");
        assert!(stdout.is_empty(), "no stdout on error");
        assert_no_tmp(&dir);
    }

    // -- Blocker 2: a stdout failure must roll the artifacts back to none --

    #[test]
    fn completed_stdout_failure_rolls_back_artifacts() {
        let dir = tmp_dir();
        let replay_out = dir.join("replay.json");
        let report_out = dir.join("report.json");

        let mut stdout = FailWriter { fail_flush: false };
        let res = publish_completed(
            &replay_out,
            "REPLAY\n",
            &report_out,
            "REPORT\n",
            &sample_outcome(),
            &mut stdout,
            atomic_output::publish_new,
        );

        assert!(matches!(res, Err(RunMatchError::Io(_))));
        assert!(!report_out.exists(), "report must be rolled back");
        assert!(!replay_out.exists(), "replay must be rolled back");
        assert_no_tmp(&dir);
    }

    #[test]
    fn aborted_stdout_failure_rolls_back_report() {
        let dir = tmp_dir();
        let report_out = dir.join("report.json");

        let mut stdout = FailWriter { fail_flush: false };
        let res = publish_aborted(
            &report_out,
            "REPORT\n",
            &sample_outcome(),
            &mut stdout,
            atomic_output::publish_new,
        );

        assert!(matches!(res, Err(RunMatchError::Io(_))));
        assert!(!report_out.exists(), "report must be rolled back");
        assert_no_tmp(&dir);
    }

    #[test]
    fn stdout_flush_failure_rolls_back_artifacts() {
        let dir = tmp_dir();
        let replay_out = dir.join("replay.json");
        let report_out = dir.join("report.json");

        let mut stdout = FailWriter { fail_flush: true };
        let res = publish_completed(
            &replay_out,
            "REPLAY\n",
            &report_out,
            "REPORT\n",
            &sample_outcome(),
            &mut stdout,
            atomic_output::publish_new,
        );

        assert!(matches!(res, Err(RunMatchError::Io(_))));
        assert!(
            !report_out.exists(),
            "report must be rolled back on flush failure"
        );
        assert!(
            !replay_out.exists(),
            "replay must be rolled back on flush failure"
        );
        assert_no_tmp(&dir);
    }

    #[test]
    fn completed_success_writes_one_outcome_line_and_both_artifacts() {
        let dir = tmp_dir();
        let replay_out = dir.join("replay.json");
        let report_out = dir.join("report.json");

        let mut stdout: Vec<u8> = Vec::new();
        let res = publish_completed(
            &replay_out,
            "REPLAY\n",
            &report_out,
            "REPORT\n",
            &sample_outcome(),
            &mut stdout,
            atomic_output::publish_new,
        )
        .unwrap();

        assert!(matches!(res, MatchExit::Completed(0)));
        assert_eq!(fs::read_to_string(&report_out).unwrap(), "REPORT\n");
        assert_eq!(fs::read_to_string(&replay_out).unwrap(), "REPLAY\n");
        let printed = String::from_utf8(stdout).unwrap();
        assert!(printed.ends_with('\n'));
        assert_eq!(printed.lines().count(), 1);
        assert_no_tmp(&dir);
    }

    // -- Sibling fix: config read is bounded by bytes actually read --

    #[test]
    fn config_actual_bytes_over_limit_is_rejected() {
        let dir = tmp_dir();
        let path = dir.join("big.json");
        let oversized = vec![b' '; MAX_ARENA_CONFIG_BYTES as usize + 16];
        fs::write(&path, &oversized).unwrap();
        let err = read_config(&path).unwrap_err();
        assert!(
            matches!(err, RunMatchError::ConfigRead(_)),
            "oversized config must be a ConfigRead error, got {err:?}"
        );
    }
}
