//! The `analyze-replay` CLI command (M06 C4).
//!
//! Offline replay-bound search analysis: read a replay document, fully verify
//! it (prefix, target position and the entire suffix through the terminal
//! result), rebuild the referee `FullState` before `steps[ply]`, run the
//! frozen deterministic MaxN search on that state, and atomically publish a
//! non-overwritable [`SearchAnalysisV1`] JSON artifact binding the replay
//! identity, the analyzed position, the exact configuration and the full
//! search result.
//!
//! Dependency discipline: `splendor-search` never sees a replay and
//! `splendor-replay` never sees the search; this command is the *only* place
//! the two are bound together. The rebuilt `FullState` is referee-only data
//! and is never emitted anywhere — only its hash enters the artifact.
//!
//! Contract:
//! - all five flags are required, each exactly once, no unknown or positional
//!   tokens: `--input --ply --max-depth-turns --max-nodes --out`;
//! - on success **stdout and stderr are both empty**; the artifact is the
//!   single output;
//! - exit codes: `0` success; `2` usage error (bad argv grammar, non-numeric
//!   values, or a config value outside the frozen search limits); `1` fatal
//!   runtime error (I/O, oversized/invalid replay, verification failure
//!   including an out-of-range ply, internal binding violation, search
//!   failure, or publish failure — a pre-existing `--out` target included).
//! - the publish is atomic create-if-absent: a half-written artifact is never
//!   observable and an existing file at `--out` is never clobbered.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::Deserialize;
use splendor_core::{full_state_hash, ENGINE_VERSION};
use splendor_replay::{replay_document_hash_v1, verify_replay_position, ReplayV1};
use splendor_search::{
    search_maxn_v1, ReplaySearchSourceV1, SearchAnalysisV1, SearchConfigV1, SEARCH_ALGORITHM_ID,
    SEARCH_ANALYSIS_FORMAT, SEARCH_ANALYSIS_VERSION, SEARCH_VERSION,
};

use crate::atomic_output;

/// Maximum size of a replay document, in bytes. A larger file is rejected
/// before any parse to bound accidental/hostile input.
pub const MAX_REPLAY_BYTES: u64 = 16 * 1024 * 1024;

const ANALYZE_USAGE: &str = "\
Usage: splendor analyze-replay --input <replay.json> --ply <n> \\
           --max-depth-turns <n> --max-nodes <n> --out <analysis.json>

Fully verify a replay, rebuild the referee state before steps[<ply>], run the
deterministic MaxN search on it, and atomically publish a search-analysis JSON
artifact. The artifact binds the replay document hash, the analyzed position,
the exact search configuration and the full search result.

Options:
  --input <path>           Path to the replay v1 JSON (UTF-8, <= 16 MiB).
  --ply <n>                Position to analyze: the state before steps[n].
                           Valid range is 0 <= n < steps.len().
  --max-depth-turns <n>    Search depth limit in completed player turns.
  --max-nodes <n>          Hard node budget for the whole search.
  --out <path>             Artifact target. Must not already exist; its parent
                           directory must exist. Never overwritten.
  -h, --help               Print this help and exit 0.

Exit codes: 0 success (artifact written; stdout and stderr empty),
2 usage error, 1 fatal error (I/O, verification, search, publish).";

/// A user-facing error for `analyze-replay`. `Display` yields the stable
/// `error:` message body; the variant selects the exit code.
#[derive(Debug)]
enum AnalyzeError {
    /// Bad command-line arguments or config outside frozen limits (exit 2).
    Usage(String),
    /// Any fatal runtime failure (exit 1).
    Fatal(String),
}

impl std::fmt::Display for AnalyzeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AnalyzeError::Usage(m) | AnalyzeError::Fatal(m) => write!(f, "{m}"),
        }
    }
}

/// Entry point for `splendor analyze-replay ...`. Returns the process exit
/// code. On success nothing is printed anywhere.
pub fn run_analyze_replay(args: &[String]) -> i32 {
    match run_analyze_inner(args) {
        Ok(()) => 0,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {err}");
            let _ = stderr.flush();
            match err {
                AnalyzeError::Usage(_) => 2,
                AnalyzeError::Fatal(_) => 1,
            }
        }
    }
}

fn run_analyze_inner(args: &[String]) -> Result<(), AnalyzeError> {
    if wants_help(args) {
        let mut stdout = io::stdout().lock();
        let _ = writeln!(stdout, "{ANALYZE_USAGE}");
        let _ = stdout.flush();
        return Ok(());
    }

    let parsed = parse_analyze_args(args).map_err(AnalyzeError::Usage)?;

    // Config validation against the frozen limits is an argument-level error:
    // the values came straight from the command line.
    let config = SearchConfigV1 {
        max_depth_turns: parsed.max_depth_turns,
        max_nodes: parsed.max_nodes,
    };
    config
        .validate()
        .map_err(|e| AnalyzeError::Usage(e.to_string()))?;

    // Output invariants before any heavy work.
    if !parent_dir_exists(&parsed.out) {
        return Err(AnalyzeError::Fatal(format!(
            "output parent directory does not exist: {}",
            parsed.out.display()
        )));
    }
    if parsed.out.exists() {
        return Err(AnalyzeError::Fatal(format!(
            "artifact already exists: {}",
            parsed.out.display()
        )));
    }

    // Read + strictly parse the replay document.
    let replay = read_replay(&parsed.input)?;

    // Canonical document identity of the input as parsed.
    let replay_document_hash = replay_document_hash_v1(&replay)
        .map_err(|e| AnalyzeError::Fatal(format!("replay document hash failed: {e}")))?;

    // Full verification (prefix + position + entire suffix) and position
    // capture. An out-of-range ply or any tampering fails here.
    let position = verify_replay_position(&replay, parsed.ply)
        .map_err(|e| AnalyzeError::Fatal(format!("replay verification failed: {e}")))?;

    // Binding assertions: fail closed on any internal inconsistency between
    // the captured position and the replay document it claims to come from.
    let step = replay
        .steps
        .get(parsed.ply as usize)
        .ok_or_else(|| AnalyzeError::Fatal("verified ply not present in replay".to_string()))?;
    if position.ply != parsed.ply {
        return Err(AnalyzeError::Fatal(format!(
            "position ply {} does not match requested ply {}",
            position.ply, parsed.ply
        )));
    }
    let recomputed = full_state_hash(&position.state);
    if position.state_hash != recomputed.as_str()
        || position.state_hash != step.state_hash_before.as_str()
    {
        return Err(AnalyzeError::Fatal(
            "analyzed state hash does not match the replay's recorded before-hash".to_string(),
        ));
    }
    if position.state.current_player != position.recorded_actor
        || position.recorded_actor != step.actor
    {
        return Err(AnalyzeError::Fatal(
            "analyzed state's current player does not match the recorded actor".to_string(),
        ));
    }
    if position.recorded_action != step.action {
        return Err(AnalyzeError::Fatal(
            "captured recorded action does not match the replay step".to_string(),
        ));
    }

    // Run the frozen deterministic search on the rebuilt referee state.
    let result = search_maxn_v1(&position.state, config)
        .map_err(|e| AnalyzeError::Fatal(format!("search failed: {e}")))?;

    // Result-side binding assertions.
    if result.root_player != position.state.current_player {
        return Err(AnalyzeError::Fatal(
            "search root player does not match the analyzed state's current player".to_string(),
        ));
    }
    if !position.state.legal_actions().contains(&result.action) {
        return Err(AnalyzeError::Fatal(
            "search recommended an action that is not legal in the analyzed state".to_string(),
        ));
    }

    let recommended_matches_recorded = result.action == position.recorded_action;

    let analysis = SearchAnalysisV1 {
        format: SEARCH_ANALYSIS_FORMAT.to_string(),
        version: SEARCH_ANALYSIS_VERSION,
        engine_version: ENGINE_VERSION.to_string(),
        catalog_version: splendor_core::CATALOG_VERSION.to_string(),
        search_algorithm_id: SEARCH_ALGORITHM_ID.to_string(),
        search_version: SEARCH_VERSION,
        source: ReplaySearchSourceV1 {
            replay_document_hash,
            replay_final_state_hash: replay.final_state_hash.as_str().to_string(),
            replay_version: replay.version,
            ruleset_fingerprint: replay.ruleset_fingerprint.as_str().to_string(),
            analyzed_ply: position.ply,
            analyzed_state_hash: position.state_hash.clone(),
            recorded_actor: position.recorded_actor,
            recorded_action: position.recorded_action,
        },
        config,
        result,
        recommended_matches_recorded,
    };

    let json = to_pretty_line(&analysis)
        .map_err(|e| AnalyzeError::Fatal(format!("serialize analysis failed: {e}")))?;

    atomic_output::commit_single(&parsed.out, &json)
        .map_err(|e| AnalyzeError::Fatal(e.to_string()))?;

    Ok(())
}

/// Read and strictly deserialize the replay document. The read is bounded by
/// the bytes actually read (not a racy up-front `metadata.len()`), rejects
/// non-UTF-8 input, denies unknown fields, and rejects trailing bytes.
fn read_replay(path: &Path) -> Result<ReplayV1, AnalyzeError> {
    let file = File::open(path)
        .map_err(|e| AnalyzeError::Fatal(format!("cannot open replay {}: {e}", path.display())))?;
    let mut raw = Vec::new();
    file.take(MAX_REPLAY_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|e| AnalyzeError::Fatal(format!("cannot read replay {}: {e}", path.display())))?;
    if raw.len() as u64 > MAX_REPLAY_BYTES {
        return Err(AnalyzeError::Fatal(format!(
            "replay exceeds {MAX_REPLAY_BYTES} bytes"
        )));
    }
    let text = String::from_utf8(raw)
        .map_err(|_| AnalyzeError::Fatal("replay is not valid UTF-8".to_string()))?;

    let mut de = serde_json::Deserializer::from_str(&text);
    let replay = ReplayV1::deserialize(&mut de)
        .map_err(|e| AnalyzeError::Fatal(format!("invalid replay: {e}")))?;
    de.end()
        .map_err(|_| AnalyzeError::Fatal("trailing data after replay JSON".to_string()))?;
    Ok(replay)
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

/// Parsed `analyze-replay` arguments.
#[derive(Debug)]
struct AnalyzeArgs {
    input: PathBuf,
    ply: u32,
    max_depth_turns: u8,
    max_nodes: u64,
    out: PathBuf,
}

fn parse_analyze_args(args: &[String]) -> Result<AnalyzeArgs, String> {
    let mut input: Option<String> = None;
    let mut ply: Option<String> = None;
    let mut max_depth_turns: Option<String> = None;
    let mut max_nodes: Option<String> = None;
    let mut out: Option<String> = None;

    let mut i = 0;
    while i < args.len() {
        let arg = args[i].as_str();
        match arg {
            "--input" => set_flag(&mut input, "--input", args.get(i + 1))?,
            "--ply" => set_flag(&mut ply, "--ply", args.get(i + 1))?,
            "--max-depth-turns" => {
                set_flag(&mut max_depth_turns, "--max-depth-turns", args.get(i + 1))?
            }
            "--max-nodes" => set_flag(&mut max_nodes, "--max-nodes", args.get(i + 1))?,
            "--out" => set_flag(&mut out, "--out", args.get(i + 1))?,
            other if other.starts_with('-') => {
                return Err(format!("unknown flag `{other}`"));
            }
            other => {
                return Err(format!("unexpected positional argument `{other}`"));
            }
        }
        i += 2;
    }

    let input = input.ok_or_else(|| "missing required --input".to_string())?;
    let ply = ply.ok_or_else(|| "missing required --ply".to_string())?;
    let max_depth_turns =
        max_depth_turns.ok_or_else(|| "missing required --max-depth-turns".to_string())?;
    let max_nodes = max_nodes.ok_or_else(|| "missing required --max-nodes".to_string())?;
    let out = out.ok_or_else(|| "missing required --out".to_string())?;

    Ok(AnalyzeArgs {
        input: PathBuf::from(input),
        ply: parse_number::<u32>("--ply", &ply)?,
        max_depth_turns: parse_number::<u8>("--max-depth-turns", &max_depth_turns)?,
        max_nodes: parse_number::<u64>("--max-nodes", &max_nodes)?,
        out: PathBuf::from(out),
    })
}

/// Parse a strictly-decimal unsigned number; anything else is a usage error.
fn parse_number<T: std::str::FromStr>(name: &str, raw: &str) -> Result<T, String> {
    raw.parse::<T>()
        .map_err(|_| format!("flag `{name}` expects an unsigned integer, got `{raw}`"))
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

/// A token beginning with `--` is a flag form, not a value; other leading
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

#[cfg(test)]
mod tests {
    use super::*;

    fn s(items: &[&str]) -> Vec<String> {
        items.iter().map(|x| x.to_string()).collect()
    }

    fn full_ok() -> Vec<String> {
        s(&[
            "--input",
            "r.json",
            "--ply",
            "3",
            "--max-depth-turns",
            "2",
            "--max-nodes",
            "1000",
            "--out",
            "a.json",
        ])
    }

    #[test]
    fn parse_accepts_all_five_flags() {
        let parsed = parse_analyze_args(&full_ok()).unwrap();
        assert_eq!(parsed.input, PathBuf::from("r.json"));
        assert_eq!(parsed.ply, 3);
        assert_eq!(parsed.max_depth_turns, 2);
        assert_eq!(parsed.max_nodes, 1000);
        assert_eq!(parsed.out, PathBuf::from("a.json"));
    }

    #[test]
    fn parse_rejects_each_missing_flag() {
        for skip in [
            "--input",
            "--ply",
            "--max-depth-turns",
            "--max-nodes",
            "--out",
        ] {
            let mut args = Vec::new();
            let full = full_ok();
            let mut i = 0;
            while i < full.len() {
                if full[i] == skip {
                    i += 2;
                    continue;
                }
                args.push(full[i].clone());
                args.push(full[i + 1].clone());
                i += 2;
            }
            let err = parse_analyze_args(&args).unwrap_err();
            assert!(
                err.contains(&format!("missing required {skip}")),
                "expected missing-{skip} error, got: {err}"
            );
        }
    }

    #[test]
    fn parse_rejects_duplicate_unknown_and_positional() {
        let mut dup = full_ok();
        dup.extend(s(&["--ply", "4"]));
        assert!(parse_analyze_args(&dup).unwrap_err().contains("duplicate"));

        let mut unknown = full_ok();
        unknown.extend(s(&["--bogus", "x"]));
        assert!(parse_analyze_args(&unknown)
            .unwrap_err()
            .contains("unknown flag"));

        let mut positional = full_ok();
        positional.push("stray".to_string());
        assert!(parse_analyze_args(&positional)
            .unwrap_err()
            .contains("unexpected positional"));
    }

    #[test]
    fn parse_rejects_non_numeric_values() {
        for (flag, bad) in [
            ("--ply", "abc"),
            ("--ply", "-1"),
            ("--max-depth-turns", "1.5"),
            ("--max-nodes", ""),
        ] {
            let mut args = Vec::new();
            let full = full_ok();
            let mut i = 0;
            while i < full.len() {
                args.push(full[i].clone());
                if full[i] == flag {
                    args.push(bad.to_string());
                } else {
                    args.push(full[i + 1].clone());
                }
                i += 2;
            }
            let err = parse_analyze_args(&args).unwrap_err();
            assert!(
                err.contains("unsigned integer") || err.contains("missing a value"),
                "flag {flag} value `{bad}` should be rejected, got: {err}"
            );
        }
    }

    #[test]
    fn flag_value_may_not_be_another_flag() {
        let args = s(&["--input", "--ply"]);
        assert!(parse_analyze_args(&args)
            .unwrap_err()
            .contains("missing a value"));
    }
}
