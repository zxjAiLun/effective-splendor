//! `studio-league-complete-match` — the one supported runtime completion path.
//!
//! Commit C's completion outlet turns a finished arena occurrence into ledger
//! state (verify -> archive -> bind -> ingest -> receipt). This module is the
//! **upper orchestration layer** that actually drives it: it runs a real arena
//! match, durably persists the four evidence documents the outlet consumes, and
//! then offers them to the outlet.
//!
//! The layering is deliberate and owner-frozen:
//!
//! ```text
//! Arena / runner
//!     |  persists report + replay + config + RuntimeOccurrenceV1
//!     v
//! this orchestration layer
//!     |  open_completion_league() + complete_runtime_occurrence()
//!     v
//! Studio League ledger + archive
//! ```
//!
//! `splendor-arena` never depends on `splendor-studio-league`; the two halves are
//! joined here, in `splendor-cli`, which already depends on both.
//!
//! `run-match` is intentionally left untouched. Its exit-code, stdout and
//! artifact-refusal contract is frozen and covered by ~15 end-to-end tests, so
//! it gains no Studio League dependency and no new flag. This command is a
//! separate producer instead.
//!
//! # Two facts, reported separately
//!
//! A match completing and a Studio completion succeeding are independent facts.
//! If the match completes and completion fails, the **match is still a real
//! completed match** and its evidence stays on disk, untouched, for retry. This
//! module never lets a completion failure masquerade as a match failure:
//!
//! * match failed -> no evidence, exit `1`, the failure is the match's;
//! * match completed, completion failed -> evidence persisted, exit `3`, and the
//!   message names the completion as the failing half;
//! * both succeeded -> exit `0`.
//!
//! Retry is [`run_studio_league_complete`], which consumes the four persisted
//! documents and never re-runs the match.

use std::fs;
use std::path::{Path, PathBuf};

use splendor_studio_league::{CompletionOutcomeV1, IngestOutcome, StudioLeaguePathsV1};

use crate::arena_command::parent_dir_exists;
use crate::atomic_output;
use crate::runtime_orchestration::{
    complete_persisted_occurrence, completion_receipt_json, produce_and_complete,
    OccurrenceEvidence, RuntimeOrchestrationOutcome,
};
use crate::studio_league_command::render_usage;

/// Exit code for "the match completed and its evidence is durable, but the
/// Studio completion failed". Deliberately distinct from both `0` (all fine) and
/// `1` (the match itself failed) so a caller can retry nothing but completion.
pub const EXIT_COMPLETION_FAILED: i32 = 3;

/// Exit code for "the match itself did not complete" (aborted). Matches
/// `run-match`'s frozen meaning of `2`: the arena ran and deliberately stopped.
const EXIT_MATCH_ABORTED: i32 = 2;

/// Exit code for "the match could not be produced at all": CLI, config, I/O or
/// internal producer error. Matches `run-match`'s frozen meaning of `1`.
const EXIT_MATCH_FAILED: i32 = 1;

/// Exit code for bad usage of *this* command.
///
/// Deliberately NOT `2`: `studio-league-complete-match`'s match half mirrors
/// `run-match`, where `2` already means "arena aborted". Overloading `2` would
/// make "the match aborted" and "you typed a flag wrong" indistinguishable to
/// automation, so usage errors get their own code here.
const EXIT_USAGE: i32 = 64;

const COMPLETE_MATCH_USAGE: &str = "\
Usage: splendor studio-league-complete-match --config <arena-config.json> \
--config-out <match-config.json> --report-out <arena-report.json> \
--replay-out <replay.json> --occurrence-out <occurrence.json> \
--occurrence-id <id> [options]

Run ONE real arena match, durably persist the four evidence documents of the
occurrence (arena report, replay, an immutable snapshot of the config the runner
actually consumed, and the runtime occurrence envelope), then complete that
occurrence into the Studio League through the central completion outlet.

The config is read ONCE. Those same bytes are what the runner parses and what
--config-out persists, so the envelope's config hash cannot disagree with the
configuration that produced the match. After this command returns the original
--config is no longer needed by anything; retries use --config-out.

The match and the Studio completion are reported as two separate facts. If the
match completes but completion fails, the exit code is 3, the evidence stays on
disk unmodified, and `studio-league-complete` can retry completion alone without
re-running the match.

Options:
  --config <path>        Arena config JSON for the match (UTF-8, <= 1 MiB).
                         Read once; only needed for this invocation.
  --config-out <path>    Where to persist the immutable snapshot of those exact
                         config bytes. Must not exist. This is the config
                         evidence a later retry uses.
  --report-out <path>    Where to write the arena report. Must not exist.
  --replay-out <path>    Where to write the replay (completed match only). Must
                         not exist and must differ from --report-out.
  --occurrence-out <path> Where to write the runtime occurrence envelope. Must
                         not exist.
  --occurrence-id <id>   Harness-authored occurrence identity. Minted by the
                         caller with the run, never re-derived from content.
  --project-root <dir>   Root every Studio League path derives from: the league
                         database, the identity manifest and the replay archive
                         all live under <dir>/{league-dir}.
                         Default: the current working directory.
  --json <path>          Write a completion receipt JSON here (only on success).
                         Published without overwriting: an existing file is left
                         untouched and reported, never replaced.
  -h, --help             Print this help and exit 0.

Exit codes: 0 match completed + Studio completion fine,
            3 match completed, Studio completion failed (evidence intact),
            2 arena aborted (matches `splendor run-match`),
            1 config/I/O/internal producer error,
            64 bad usage.
";

const COMPLETE_USAGE: &str = "\
Usage: splendor studio-league-complete --occurrence <occurrence.json> \
--report <arena-report.json> --replay <replay.json> --config <match-config.json> \
[options]

Retry completion for an occurrence whose evidence is already on disk. This never
runs a match and never rewrites the evidence: it re-reads the four documents and
offers them to the completion outlet. Re-offering an occurrence that is already
in the league is idempotent (the ledger answers `already_present`).

Options:
  --occurrence <path>    Runtime occurrence envelope persisted at match completion.
  --report <path>        The arena report the envelope attests to.
  --replay <path>        The replay the envelope attests to.
  --config <path>        The run's own config snapshot the envelope attests to
                         (the file `studio-league-complete-match --config-out`
                         wrote, NOT the original invocation input).
  --project-root <dir>   Root every Studio League path derives from (same meaning
                         as for studio-league-complete-match). Default: the
                         current working directory.
  --json <path>          Write a completion receipt JSON here. Published without
                         overwriting: an existing file is left untouched.
  -h, --help             Print this help and exit 0.

Exit codes: 0 completed (inserted or already present), 1 completion failed,
64 bad usage.
";

/// Parsed arguments shared by both entry points.
struct CompleteArgs {
    config: PathBuf,
    report_out: PathBuf,
    replay_out: PathBuf,
    occurrence_out: PathBuf,
    /// Where the producer persists the immutable snapshot of the exact config
    /// bytes the runner consumed. This is the fourth durable evidence document.
    config_out: PathBuf,
    occurrence_id: String,
    /// Resolved once, here, and threaded through unchanged: the database, the
    /// identity manifest and the replay archive root are never chosen apart.
    paths: StudioLeaguePathsV1,
    json_out: Option<PathBuf>,
}

fn fail_usage(usage: &str, message: &str) -> i32 {
    eprintln!("studio-league-complete-match: {message}");
    eprintln!();
    eprintln!("{}", render_usage(usage));
    EXIT_USAGE
}

/// Same, for the completion-only entry point, which keeps its own smaller code
/// space (it never runs a match, so it has no "aborted" case).
fn fail_usage_complete(usage: &str, message: &str) -> i32 {
    eprintln!("studio-league-complete: {message}");
    eprintln!();
    eprintln!("{}", render_usage(usage));
    EXIT_USAGE
}

/// Entry point for `splendor studio-league-complete-match`. Returns the exit code.
pub fn run_studio_league_complete_match(args: &[String]) -> i32 {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{}", render_usage(COMPLETE_MATCH_USAGE));
        return 0;
    }
    let parsed = match parse_complete_match_args(args) {
        Ok(parsed) => parsed,
        Err(message) => return fail_usage(COMPLETE_MATCH_USAGE, &message),
    };

    // ---- Half one: the match. ------------------------------------------------
    // Everything here mirrors `run-match`'s frozen invariants: refuse to
    // overwrite, require the output parents, and publish report+replay
    // atomically, with the report as the commit marker.
    // The four outputs must be distinct from each other and from the config
    // input: writing the snapshot over the input, or one evidence document over
    // another, would leave a set that cannot be replayed.
    for (left_label, left) in [
        ("--report-out", &parsed.report_out),
        ("--replay-out", &parsed.replay_out),
        ("--occurrence-out", &parsed.occurrence_out),
        ("--config-out", &parsed.config_out),
    ] {
        for (right_label, right) in [
            ("--report-out", &parsed.report_out),
            ("--replay-out", &parsed.replay_out),
            ("--occurrence-out", &parsed.occurrence_out),
            ("--config-out", &parsed.config_out),
            ("--config", &parsed.config),
        ] {
            if left_label < right_label && paths_alias(left, right) {
                return fail_usage(
                    COMPLETE_MATCH_USAGE,
                    &format!("{left_label} and {right_label} must differ"),
                );
            }
        }
    }

    for path in [
        &parsed.report_out,
        &parsed.replay_out,
        &parsed.occurrence_out,
        &parsed.config_out,
    ] {
        if path.exists() {
            return fail_usage(
                COMPLETE_MATCH_USAGE,
                &format!("output already exists: {}", path.display()),
            );
        }
        if !parent_dir_exists(path) {
            return fail_usage(
                COMPLETE_MATCH_USAGE,
                &format!("output parent directory does not exist: {}", path.display()),
            );
        }
    }

    // ---- The config is read exactly ONCE. ------------------------------------
    // The bytes read here are the bytes the runner parses and the bytes the
    // config snapshot persists, so the envelope's `config_sha256` cannot describe
    // a different configuration than the one that produced the match. Reading the
    // file twice (once to parse, once to hash) would leave a window in which the
    // two could disagree.
    let config_bytes = match read_config_bytes(&parsed.config) {
        Ok(bytes) => bytes,
        Err(error) => {
            eprintln!("studio-league-complete-match: error: {error}");
            return EXIT_MATCH_FAILED;
        }
    };

    // Everything below is the shared producer authority; this entry point is only
    // an adapter that turns its typed outcome into the frozen CLI facts.
    let evidence = OccurrenceEvidence {
        config: parsed.config_out.clone(),
        replay: parsed.replay_out.clone(),
        report: parsed.report_out.clone(),
        occurrence: parsed.occurrence_out.clone(),
    };
    let outcome = match produce_and_complete(
        &evidence,
        &config_bytes,
        &parsed.occurrence_id,
        &parsed.paths,
    ) {
        Ok(outcome) => outcome,
        Err(error) => {
            eprintln!("studio-league-complete-match: error: {error}");
            return EXIT_MATCH_FAILED;
        }
    };

    // From here on the match is a settled fact, and the two facts are reported
    // separately: a completion failure must never look like a match failure.
    if let RuntimeOrchestrationOutcome::Aborted { match_status, .. } = &outcome {
        eprintln!(
            "studio-league-complete-match: the match {match_status}; wrote {} and no occurrence evidence",
            outcome.evidence().report.display()
        );
        // A settled, non-completed match is not a Studio completion failure.
        return EXIT_MATCH_ABORTED;
    }

    println!(
        "studio-league-complete-match: match completed; evidence written to {}, {}, {}, {}",
        outcome.evidence().report.display(),
        outcome.evidence().replay.display(),
        outcome.evidence().config.display(),
        outcome.evidence().occurrence.display()
    );

    if let RuntimeOrchestrationOutcome::CompletionFailed { message, .. } = &outcome {
        eprintln!("studio-league-complete-match: {message}");
        // The retry command names the PERSISTED snapshot, never the original
        // `--config` input: after this returns, that input is not part of the
        // evidence set and may legitimately have been moved or deleted.
        eprintln!(
            "studio-league-complete-match: the MATCH completed and its evidence is intact; only the Studio completion failed. \
Repair the condition and retry with `studio-league-complete --occurrence {} --report {} --replay {} --config {}`; the match will not be re-run.",
            parsed.occurrence_out.display(),
            parsed.report_out.display(),
            parsed.replay_out.display(),
            parsed.config_out.display()
        );
        return EXIT_COMPLETION_FAILED;
    }

    if let Some(completion) = outcome.completion() {
        report_completion(
            completion,
            "studio-league-complete-match",
            parsed.json_out.as_ref(),
        );
    }
    0
}

/// Print the completion facts for one booked occurrence.
///
/// Shared by both CLI entry points so the two commands cannot describe the same
/// booking differently. It prints; the shared producer authority does not.
fn report_completion(completion: &CompletionOutcomeV1, command: &str, json_out: Option<&PathBuf>) {
    let archived = &completion.archived;
    let receipt = &completion.receipt;
    println!(
        "{command}: archived replay {} ({})",
        archived.document_sha256(),
        archived.outcome().as_str()
    );
    let eligibility_text = match &receipt.rating_ineligible_reason {
        Some(reason) => format!("ineligible ({reason})"),
        None => "eligible".to_string(),
    };
    println!(
        "{command}: recorded occurrence `{}`",
        completion.record.source_identity
    );
    println!("  match_id:    {}", receipt.match_id);
    match &completion.ingest {
        IngestOutcome::Inserted { rating_events, .. } => {
            println!("  outcome:     inserted ({rating_events} rating events)");
        }
        IngestOutcome::AlreadyPresent { .. } => {
            println!("  outcome:     already_present (no new Elo)");
        }
    }
    println!("  eligibility: {eligibility_text}");
    for event in &receipt.elo_events {
        println!(
            "  elo:         {}: {:.1} -> {:.1}",
            event.participant_id, event.elo_before, event.elo_after
        );
    }

    if let Some(out_json_path) = json_out {
        let receipt_json = completion_receipt_json(completion);
        if let Err(error) = write_json_report(out_json_path, &receipt_json) {
            // The occurrence IS booked; only the export failed. Re-offering is
            // idempotent, so this is reported as a success with a warning.
            eprintln!(
                "{command}: the occurrence WAS committed; only the receipt export failed ({}: {error}). \
Re-offering the same occurrence is a no-op, so the receipt can be re-derived safely",
                out_json_path.display()
            );
        } else {
            println!(
                "Wrote completion receipt JSON to {}",
                out_json_path.display()
            );
        }
    }
}
/// Entry point for `splendor studio-league-complete`: completion-only retry.
pub fn run_studio_league_complete(args: &[String]) -> i32 {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{}", render_usage(COMPLETE_USAGE));
        return 0;
    }
    let mut occurrence_path: Option<PathBuf> = None;
    let mut report_path: Option<PathBuf> = None;
    let mut replay_path: Option<PathBuf> = None;
    let mut config_path: Option<PathBuf> = None;
    let mut project_root: Option<PathBuf> = None;
    let mut json_out: Option<PathBuf> = None;

    let mut index = 0;
    while index < args.len() {
        let value = || args.get(index + 1);
        match args[index].as_str() {
            "--occurrence" => match value() {
                Some(path) => occurrence_path = Some(PathBuf::from(path)),
                None => return fail_usage_complete(COMPLETE_USAGE, "--occurrence needs a path"),
            },
            "--report" => match value() {
                Some(path) => report_path = Some(PathBuf::from(path)),
                None => return fail_usage_complete(COMPLETE_USAGE, "--report needs a path"),
            },
            "--replay" => match value() {
                Some(path) => replay_path = Some(PathBuf::from(path)),
                None => return fail_usage_complete(COMPLETE_USAGE, "--replay needs a path"),
            },
            "--config" => match value() {
                Some(path) => config_path = Some(PathBuf::from(path)),
                None => return fail_usage_complete(COMPLETE_USAGE, "--config needs a path"),
            },
            "--project-root" => match value() {
                Some(path) => project_root = Some(PathBuf::from(path)),
                None => {
                    return fail_usage_complete(COMPLETE_USAGE, "--project-root needs a directory")
                }
            },
            "--json" => match value() {
                Some(path) => json_out = Some(PathBuf::from(path)),
                None => return fail_usage_complete(COMPLETE_USAGE, "--json needs a path"),
            },
            other => {
                return fail_usage_complete(
                    COMPLETE_USAGE,
                    &format!("unexpected argument `{other}`"),
                )
            }
        }
        index += 2;
    }
    let (occurrence_path, report_path, replay_path, config_path) =
        match (occurrence_path, report_path, replay_path, config_path) {
            (Some(a), Some(b), Some(c), Some(d)) => (a, b, c, d),
            _ => {
                return fail_usage_complete(
                    COMPLETE_USAGE,
                    "--occurrence, --report, --replay and --config are all required",
                )
            }
        };

    // Resolve the league locations once; everything below uses these.
    let paths = StudioLeaguePathsV1::resolve(project_root.as_deref());

    // The receipt export must never be able to overwrite the evidence it
    // describes, nor the league authority state.
    if let Some(json_out) = &json_out {
        if let Err(message) = reject_receipt_alias(
            json_out,
            &[
                ("--occurrence", &occurrence_path),
                ("--report", &report_path),
                ("--replay", &replay_path),
                ("--config", &config_path),
                ("--project-root database", paths.db()),
                ("--project-root identity", paths.identity()),
                ("--project-root archive", paths.replay_root()),
            ],
        ) {
            return fail_usage_complete(COMPLETE_USAGE, &message);
        }
    }

    // The four persisted documents ARE the occurrence's authority: this reads
    // them, verifies them against the envelope's own hashes, and never runs a
    // match or consults a configuration of its own.
    let evidence = OccurrenceEvidence {
        config: config_path.clone(),
        replay: replay_path.clone(),
        report: report_path.clone(),
        occurrence: occurrence_path.clone(),
    };
    // `None`: this command's authority is the four documents the operator named, not
    // an occurrence slot, so it completes whatever envelope they point at. The Host
    // route, which addresses a slot by id, binds that id instead.
    match complete_persisted_occurrence(&evidence, &paths, None) {
        Ok(completion) => {
            report_completion(&completion, "studio-league-complete", json_out.as_ref());
            0
        }
        Err(error) => {
            eprintln!("studio-league-complete: {error}");
            EXIT_MATCH_FAILED
        }
    }
}

/// Read the config document once, bounded by the bytes actually read.
///
/// Mirrors [`crate::arena_command::read_config`]'s bounds exactly, but returns
/// the raw bytes so the caller can both parse them and hash them without a second
/// read.
fn read_config_bytes(path: &Path) -> Result<Vec<u8>, String> {
    use std::io::Read as _;
    let file = fs::File::open(path)
        .map_err(|error| format!("cannot open config {}: {error}", path.display()))?;
    let mut raw = Vec::new();
    file.take(crate::arena_command::MAX_ARENA_CONFIG_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|error| format!("cannot read config {}: {error}", path.display()))?;
    if raw.len() as u64 > crate::arena_command::MAX_ARENA_CONFIG_BYTES {
        return Err(format!(
            "config exceeds {} bytes",
            crate::arena_command::MAX_ARENA_CONFIG_BYTES
        ));
    }
    Ok(raw)
}

/// Refuse a receipt path that aliases a piece of durable state.
///
/// This is the friendly first line of defence. It is deliberately not the only
/// one: [`write_json_report`] publishes without overwriting, so even an alias
/// this check does not catch (a symlink, a differently-spelled path, a
/// hardlink) cannot destroy evidence. The check exists so that an obvious
/// mistake is an immediate usage error instead of a silent degradation.
fn reject_receipt_alias(json_out: &Path, protected: &[(&str, &Path)]) -> Result<(), String> {
    for (label, path) in protected {
        if paths_alias(json_out, path) {
            return Err(format!(
                "--json must not name {label} (`{}`); the receipt is a derived export and must never share a path with durable state",
                path.display()
            ));
        }
    }
    Ok(())
}

/// Whether two paths refer to the same target.
///
/// Compares raw components first, then falls back to canonicalising the parent
/// directories so `./a/x` and `a/x` are recognised as the same file even when
/// the target does not exist yet.
fn paths_alias(left: &Path, right: &Path) -> bool {
    if left == right {
        return true;
    }
    let canon = |path: &Path| -> Option<PathBuf> {
        let parent = path.parent()?;
        let parent = if parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            parent
        };
        let parent = parent.canonicalize().ok()?;
        let name = path.file_name()?;
        Some(parent.join(name))
    };
    match (canon(left), canon(right)) {
        (Some(a), Some(b)) => a == b,
        _ => false,
    }
}

fn write_json_report(path: &Path, value: &serde_json::Value) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
    }
    let text = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    // NEVER `fs::write`: this path is user-supplied and has already been used to
    // book an occurrence, so an overwrite here could destroy the very evidence
    // the booking depends on (or, if `--json` aliases `--db`, the league itself).
    // `commit_single` publishes create-if-absent and refuses an existing target.
    atomic_output::commit_single(path, &text).map_err(|error| error.to_string())
}

fn parse_complete_match_args(args: &[String]) -> Result<CompleteArgs, String> {
    let mut config: Option<String> = None;
    let mut config_out: Option<String> = None;
    let mut report_out: Option<String> = None;
    let mut replay_out: Option<String> = None;
    let mut occurrence_out: Option<String> = None;
    let mut occurrence_id: Option<String> = None;
    let mut project_root: Option<PathBuf> = None;
    let mut json_out: Option<PathBuf> = None;

    let mut index = 0;
    while index < args.len() {
        let value = || args.get(index + 1);
        match args[index].as_str() {
            "--config" => set_once(&mut config, "--config", value())?,
            "--config-out" => set_once(&mut config_out, "--config-out", value())?,
            "--report-out" => set_once(&mut report_out, "--report-out", value())?,
            "--replay-out" => set_once(&mut replay_out, "--replay-out", value())?,
            "--occurrence-out" => set_once(&mut occurrence_out, "--occurrence-out", value())?,
            "--occurrence-id" => set_once(&mut occurrence_id, "--occurrence-id", value())?,
            "--project-root" => match value() {
                Some(path) => project_root = Some(PathBuf::from(path)),
                None => return Err("--project-root needs a directory".to_string()),
            },
            "--json" => match value() {
                Some(path) => json_out = Some(PathBuf::from(path)),
                None => return Err("--json needs a path".to_string()),
            },
            other => return Err(format!("unexpected argument `{other}`")),
        }
        index += 2;
    }

    let config = config.ok_or("--config is required")?;
    let config_out = config_out.ok_or("--config-out is required")?;
    let report_out = report_out.ok_or("--report-out is required")?;
    let replay_out = replay_out.ok_or("--replay-out is required")?;
    let occurrence_out = occurrence_out.ok_or("--occurrence-out is required")?;
    let occurrence_id = occurrence_id.ok_or("--occurrence-id is required")?;
    if occurrence_id.trim().is_empty() || occurrence_id.chars().any(|c| c.is_control()) {
        return Err("--occurrence-id must be non-empty and free of control characters".to_string());
    }

    let parsed = CompleteArgs {
        config: PathBuf::from(config),
        report_out: PathBuf::from(report_out),
        replay_out: PathBuf::from(replay_out),
        occurrence_out: PathBuf::from(occurrence_out),
        config_out: PathBuf::from(config_out),
        occurrence_id,
        paths: StudioLeaguePathsV1::resolve(project_root.as_deref()),
        json_out,
    };

    // A receipt export must never be able to name durable evidence or the league
    // authority itself.
    if let Some(json_out) = &parsed.json_out {
        reject_receipt_alias(
            json_out,
            &[
                ("--report-out", &parsed.report_out),
                ("--replay-out", &parsed.replay_out),
                ("--occurrence-out", &parsed.occurrence_out),
                ("--config-out", &parsed.config_out),
                ("--config (input)", &parsed.config),
                ("--project-root database", parsed.paths.db()),
                ("--project-root identity", parsed.paths.identity()),
                ("--project-root archive", parsed.paths.replay_root()),
            ],
        )?;
    }

    Ok(parsed)
}

/// Set a flag once, rejecting a duplicate and a missing value.
///
/// `run-match`'s parser is strict about duplicates and the arena CLI contract is
/// frozen; this producer matches that strictness rather than quietly taking the
/// last occurrence.
fn set_once(slot: &mut Option<String>, name: &str, value: Option<&String>) -> Result<(), String> {
    let value = value.ok_or_else(|| format!("{name} needs a value"))?;
    if slot.is_some() {
        return Err(format!("duplicate flag `{name}`"));
    }
    *slot = Some(value.clone());
    Ok(())
}
