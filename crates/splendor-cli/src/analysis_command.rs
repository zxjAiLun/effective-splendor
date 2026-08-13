//! M14A replay-wide neural analysis sidecar command.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use splendor_analysis::{
    analysis_trace_hash_v1, analysis_trace_hash_v2, analyze_replay_neural_v1,
    analyze_replay_neural_v2, ReviewerConfigV2, ReviewerIdentityV2, ReviewerResultKindV2,
    ReviewerStatusV2, M13_REVIEWER_DISPLAY_NAME, M13_REVIEWER_ID,
};
use splendor_learning::PolicyValueCheckpointV1;
use splendor_neural_search::NeuralIsmctsConfigV1;
use splendor_replay::ReplayV1;

use crate::atomic_output;

const MAX_REPLAY_BYTES: u64 = 16 * 1024 * 1024;
const MAX_CHECKPOINT_BYTES: u64 = 16 * 1024 * 1024;

const USAGE: &str = "\
Usage: splendor analyze-replay-neural --input <replay.json> \
--checkpoint <checkpoint.json> --checkpoint-hash <sha256> \
--sample-seed <u64> --simulations <u32> --max-depth-turns <u8> \
--puct-exploration-milli <u32> --out <analysis.json> [--trace-version 1|2]

Verify the complete ReplayV1 once, rerun the exact checkpoint-bound M13 search
at every decision ply, and atomically publish a replay-bound sidecar.
The trace defaults to actor Observation and segregates referee reveal data.
--trace-version 2 emits an AnalysisTraceV2 with the M13 reviewer identity.

All eight flags are required exactly once. Existing outputs are never replaced.";

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

pub fn run_analyze_replay_neural(args: &[String]) -> i32 {
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
    parsed
        .config
        .validate()
        .map_err(|error| CommandError::Fatal(error.to_string()))?;
    if parsed.input == parsed.out || parsed.checkpoint == parsed.out {
        return Err(CommandError::Fatal(
            "--out must differ from both input files".into(),
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
    let checkpoint: PolicyValueCheckpointV1 =
        read_json(&parsed.checkpoint, MAX_CHECKPOINT_BYTES, "checkpoint")?;

    match parsed.trace_version {
        1 => {
            let trace = analyze_replay_neural_v1(&replay, &checkpoint, &parsed.config)
                .map_err(|error| CommandError::Fatal(error.to_string()))?;
            trace
                .validate()
                .map_err(|error| CommandError::Fatal(error.to_string()))?;
            analysis_trace_hash_v1(&trace)
                .map_err(|error| CommandError::Fatal(error.to_string()))?;
            let mut json = serde_json::to_string_pretty(&trace)
                .map_err(|error| CommandError::Fatal(format!("serialize trace failed: {error}")))?;
            json.push('\n');
            atomic_output::commit_single(&parsed.out, &json)
                .map_err(|error| CommandError::Fatal(error.to_string()))
        }
        2 => {
            let reviewer = ReviewerIdentityV2::new(
                M13_REVIEWER_ID,
                M13_REVIEWER_DISPLAY_NAME,
                ReviewerStatusV2::Rejected,
                ReviewerResultKindV2::NeuralIsmcts,
                ReviewerConfigV2::NeuralIsmcts(parsed.config.clone()),
                Some(parsed.config.expected_checkpoint_hash.clone()),
            );
            let trace = analyze_replay_neural_v2(&replay, &checkpoint, &reviewer)
                .map_err(|error| CommandError::Fatal(error.to_string()))?;
            trace
                .validate()
                .map_err(|error| CommandError::Fatal(error.to_string()))?;
            analysis_trace_hash_v2(&trace)
                .map_err(|error| CommandError::Fatal(error.to_string()))?;
            let mut json = serde_json::to_string_pretty(&trace)
                .map_err(|error| CommandError::Fatal(format!("serialize trace failed: {error}")))?;
            json.push('\n');
            atomic_output::commit_single(&parsed.out, &json)
                .map_err(|error| CommandError::Fatal(error.to_string()))
        }
        other => Err(CommandError::Fatal(format!(
            "unsupported --trace-version {other}; expected 1 or 2"
        ))),
    }
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
    checkpoint: PathBuf,
    out: PathBuf,
    config: NeuralIsmctsConfigV1,
    trace_version: u32,
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut input = None;
    let mut checkpoint = None;
    let mut checkpoint_hash = None;
    let mut sample_seed = None;
    let mut simulations = None;
    let mut max_depth_turns = None;
    let mut puct_exploration_milli = None;
    let mut out = None;
    let mut trace_version = None;
    let mut index = 0usize;
    while index < args.len() {
        let flag = args[index].as_str();
        let slot = match flag {
            "--input" => &mut input,
            "--checkpoint" => &mut checkpoint,
            "--checkpoint-hash" => &mut checkpoint_hash,
            "--sample-seed" => &mut sample_seed,
            "--simulations" => &mut simulations,
            "--max-depth-turns" => &mut max_depth_turns,
            "--puct-exploration-milli" => &mut puct_exploration_milli,
            "--trace-version" => &mut trace_version,
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

    let sample_seed = parse_number(sample_seed, "--sample-seed", "u64")?;
    let simulations = parse_number(simulations, "--simulations", "u32")?;
    let max_depth_turns = parse_number(max_depth_turns, "--max-depth-turns", "u8")?;
    let puct_exploration_milli =
        parse_number(puct_exploration_milli, "--puct-exploration-milli", "u32")?;
    let trace_version = match trace_version {
        Some(value) => parse_number(Some(value), "--trace-version", "u32")?,
        None => 1,
    };
    Ok(Args {
        input: PathBuf::from(required(input, "--input")?),
        checkpoint: PathBuf::from(required(checkpoint, "--checkpoint")?),
        out: PathBuf::from(required(out, "--out")?),
        config: NeuralIsmctsConfigV1 {
            sample_seed,
            simulations,
            max_depth_turns,
            puct_exploration_milli,
            expected_checkpoint_hash: required(checkpoint_hash, "--checkpoint-hash")?,
        },
        trace_version,
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
            "--checkpoint",
            "checkpoint.json",
            "--checkpoint-hash",
            &"11".repeat(32),
            "--sample-seed",
            "20260811",
            "--simulations",
            "64",
            "--max-depth-turns",
            "2",
            "--puct-exploration-milli",
            "1500",
            "--out",
            "analysis.json",
        ]
        .iter()
        .map(|value| (*value).to_string())
        .collect()
    }

    #[test]
    fn parser_requires_the_complete_frozen_contract() {
        let parsed = parse_args(&valid_args()).unwrap();
        assert_eq!(parsed.config.simulations, 64);
        assert_eq!(parsed.config.max_depth_turns, 2);
        assert_eq!(parsed.config.puct_exploration_milli, 1_500);

        let mut missing = valid_args();
        missing.drain(4..6);
        assert!(parse_args(&missing).is_err());

        let mut duplicate = valid_args();
        duplicate.extend(["--out".into(), "again.json".into()]);
        assert!(parse_args(&duplicate).is_err());
    }
}
