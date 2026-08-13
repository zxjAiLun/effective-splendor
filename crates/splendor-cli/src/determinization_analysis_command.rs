//! The `analyze-replay-determinization` command (M23 P0.2).
//!
//! One process reads and verifies a complete ReplayV1 once, then analyzes
//! every decision ply with the frozen M07 root-determinization reviewer in a
//! single pass, publishing exactly one AnalysisTraceV2 sidecar. No per-ply
//! subprocess is spawned and no per-ply JSON is produced.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use splendor_analysis::{
    analysis_trace_hash_v2, analyze_replay_determinization_v2, ReviewerConfigV2,
    ReviewerIdentityV2, ReviewerResultKindV2, ReviewerStatusV2, M07_REVIEWER_DISPLAY_NAME,
    M07_REVIEWER_ID,
};
use splendor_imperfect_search::RootDeterminizationConfigV1;
use splendor_replay::ReplayV1;
use splendor_search::SearchConfigV1;

use crate::atomic_output;

const MAX_REPLAY_BYTES: u64 = 16 * 1024 * 1024;
const FROZEN_SAMPLE_SEED: u64 = 20260810;

const USAGE: &str = "\
Usage: splendor analyze-replay-determinization --input <replay.json> \
--sample-count <u16> --max-depth-turns <u8> --max-nodes <u64> \
[--sample-seed <u64>] --out <analysis-v2.json>

Verify the complete ReplayV1 once, then analyze every decision ply with the
frozen M07 root-determinization reviewer in one pass and atomically publish a
single AnalysisTraceV2 sidecar. Per-ply sampling seeds are derived from the
frozen --sample-seed (default 20260810), the ply, and the replay document hash.

Existing outputs are never replaced.";

#[derive(Debug)]
enum CommandError {
    Usage(String),
    Fatal(String),
}

impl std::fmt::Display for CommandError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Usage(message) | Self::Fatal(message) => formatter.write_str(message),
        }
    }
}

pub fn run_analyze_replay_determinization(args: &[String]) -> i32 {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        let mut stdout = io::stdout().lock();
        let _ = writeln!(stdout, "{USAGE}");
        let _ = stdout.flush();
        return 0;
    }
    match run_inner(args) {
        Ok(()) => 0,
        Err(error) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {error}");
            let _ = stderr.flush();
            match error {
                CommandError::Usage(_) => 2,
                CommandError::Fatal(_) => 1,
            }
        }
    }
}

fn run_inner(args: &[String]) -> Result<(), CommandError> {
    let parsed = parse_args(args).map_err(CommandError::Usage)?;
    let config = RootDeterminizationConfigV1 {
        sample_seed: parsed.sample_seed,
        sample_count: parsed.sample_count,
        continuation_search: SearchConfigV1 {
            max_depth_turns: parsed.max_depth_turns,
            max_nodes: parsed.max_nodes,
        },
    };
    config
        .validate()
        .map_err(|error| CommandError::Fatal(format!("invalid search config: {error}")))?;
    if parsed.input == parsed.out {
        return Err(CommandError::Fatal(
            "--out must differ from the input file".into(),
        ));
    }
    if !parent_dir_exists(&parsed.out) {
        return Err(CommandError::Fatal(format!(
            "output parent directory does not exist: {}",
            parsed.out.display()
        )));
    }
    if parsed.out.exists() {
        return Err(CommandError::Fatal(format!(
            "artifact already exists: {}",
            parsed.out.display()
        )));
    }

    let replay: ReplayV1 = read_json(&parsed.input, MAX_REPLAY_BYTES, "replay")?;
    let reviewer = ReviewerIdentityV2::new(
        M07_REVIEWER_ID,
        M07_REVIEWER_DISPLAY_NAME,
        ReviewerStatusV2::Champion,
        ReviewerResultKindV2::RootDeterminization,
        ReviewerConfigV2::RootDeterminization(config),
        None,
    );
    let trace = analyze_replay_determinization_v2(&replay, &reviewer)
        .map_err(|error| CommandError::Fatal(error.to_string()))?;
    trace
        .validate()
        .map_err(|error| CommandError::Fatal(error.to_string()))?;
    analysis_trace_hash_v2(&trace).map_err(|error| CommandError::Fatal(error.to_string()))?;
    let mut json = serde_json::to_string_pretty(&trace)
        .map_err(|error| CommandError::Fatal(format!("serialize trace failed: {error}")))?;
    json.push('\n');
    atomic_output::commit_single(&parsed.out, &json)
        .map_err(|error| CommandError::Fatal(error.to_string()))
}

fn read_json<T: DeserializeOwned>(
    path: &Path,
    max_bytes: u64,
    label: &str,
) -> Result<T, CommandError> {
    let file = File::open(path).map_err(|error| {
        CommandError::Fatal(format!("cannot open {label} {}: {error}", path.display()))
    })?;
    let mut bytes = Vec::new();
    file.take(max_bytes + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| {
            CommandError::Fatal(format!("cannot read {label} {}: {error}", path.display()))
        })?;
    if bytes.len() as u64 > max_bytes {
        return Err(CommandError::Fatal(format!(
            "{label} exceeds {max_bytes} bytes"
        )));
    }
    let text = String::from_utf8(bytes)
        .map_err(|_| CommandError::Fatal(format!("{label} is not valid UTF-8")))?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let value = T::deserialize(&mut deserializer)
        .map_err(|error| CommandError::Fatal(format!("invalid {label}: {error}")))?;
    deserializer
        .end()
        .map_err(|_| CommandError::Fatal(format!("trailing data after {label} JSON")))?;
    Ok(value)
}

struct Args {
    input: PathBuf,
    sample_seed: u64,
    sample_count: u16,
    max_depth_turns: u8,
    max_nodes: u64,
    out: PathBuf,
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut input = None;
    let mut sample_seed = None;
    let mut sample_count = None;
    let mut max_depth_turns = None;
    let mut max_nodes = None;
    let mut out = None;
    let mut index = 0usize;
    while index < args.len() {
        let flag = args[index].as_str();
        let slot = match flag {
            "--input" => &mut input,
            "--sample-seed" => &mut sample_seed,
            "--sample-count" => &mut sample_count,
            "--max-depth-turns" => &mut max_depth_turns,
            "--max-nodes" => &mut max_nodes,
            "--out" => &mut out,
            other if other.starts_with('-') => return Err(format!("unknown flag `{other}`")),
            other => return Err(format!("unexpected positional argument `{other}`")),
        };
        if slot.is_some() {
            return Err(format!("duplicate flag `{flag}`"));
        }
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("missing value for `{flag}`"))?;
        if value.starts_with('-') {
            return Err(format!("missing value for `{flag}`"));
        }
        *slot = Some(value.clone());
        index += 2;
    }

    let sample_seed = match sample_seed {
        Some(value) => parse_number(Some(value), "--sample-seed", "u64")?,
        None => FROZEN_SAMPLE_SEED,
    };
    let sample_count = parse_number(sample_count, "--sample-count", "u16")?;
    let max_depth_turns = parse_number(max_depth_turns, "--max-depth-turns", "u8")?;
    let max_nodes = parse_number(max_nodes, "--max-nodes", "u64")?;
    Ok(Args {
        input: PathBuf::from(required(input, "--input")?),
        sample_seed,
        sample_count,
        max_depth_turns,
        max_nodes,
        out: PathBuf::from(required(out, "--out")?),
    })
}

fn required(value: Option<String>, flag: &str) -> Result<String, String> {
    value.ok_or_else(|| format!("missing required {flag}"))
}

fn parse_number<T: std::str::FromStr>(
    value: Option<String>,
    flag: &str,
    kind: &str,
) -> Result<T, String> {
    required(value, flag)?
        .parse::<T>()
        .map_err(|_| format!("invalid {kind} for {flag}"))
}

fn parent_dir_exists(path: &Path) -> bool {
    path.parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
        .is_dir()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_args() -> Vec<String> {
        [
            "--input",
            "replay.json",
            "--sample-count",
            "4",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "2000",
            "--out",
            "analysis.json",
        ]
        .iter()
        .map(|value| (*value).to_string())
        .collect()
    }

    #[test]
    fn parser_defaults_the_frozen_sample_seed() {
        let parsed = parse_args(&valid_args()).unwrap();
        assert_eq!(parsed.sample_seed, FROZEN_SAMPLE_SEED);
        assert_eq!(parsed.sample_count, 4);
        assert_eq!(parsed.max_depth_turns, 1);
        assert_eq!(parsed.max_nodes, 2000);
    }

    #[test]
    fn parser_rejects_duplicate_and_unknown_flags() {
        let mut duplicate = valid_args();
        duplicate.extend(["--out".into(), "again.json".into()]);
        assert!(parse_args(&duplicate).is_err());

        let mut unknown = valid_args();
        unknown.extend(["--bogus".into(), "x".into()]);
        assert!(parse_args(&unknown).is_err());
    }
}
