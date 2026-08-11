//! M14B/M15 batch analysis of one frozen evaluation directory.

use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use splendor_analysis::{analyze_evaluation_neural_v1, evaluation_diagnostic_hash_v1};
use splendor_eval::{expand_schedule, EvaluationPlanV1, EvaluationReportV1};
use splendor_learning::PolicyValueCheckpointV1;
use splendor_neural_search::NeuralIsmctsConfigV1;

use crate::atomic_output;

const MAX_JSON_BYTES: u64 = 16 * 1024 * 1024;

const USAGE: &str = "\
Usage: splendor diagnose-neural-evaluation --evaluation-dir <dir> \
--checkpoint <checkpoint.json> --checkpoint-hash <sha256> \
--sample-seed <u64> --simulations <u32> --max-depth-turns <u8> \
--puct-exploration-milli <u32> --candidate-agent-id <id> \
--champion-agent-id <id> --out-dir <new-dir>

Strictly bind plan.json, eval-report.json and every canonical match replay,
generate one M14A sidecar per match, and publish the M15 controlled-ablation
diagnostic last as diagnostic.json. The output directory must not exist.";

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

pub fn run_diagnose_neural_evaluation(args: &[String]) -> i32 {
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        let mut stdout = io::stdout().lock();
        let _ = writeln!(stdout, "{USAGE}");
        let _ = stdout.flush();
        return 0;
    }
    match run_inner(args) {
        Ok(hash) => {
            let mut stdout = io::stdout().lock();
            let _ = writeln!(stdout, "ok");
            let _ = writeln!(stdout, "diagnostic_hash={hash}");
            let _ = stdout.flush();
            0
        }
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

fn run_inner(args: &[String]) -> Result<String, CommandError> {
    let parsed = parse_args(args).map_err(CommandError::Usage)?;
    parsed
        .config
        .validate()
        .map_err(|error| CommandError::Fatal(error.to_string()))?;
    if !parsed.evaluation_dir.is_dir() {
        return Err(CommandError::Fatal(format!(
            "evaluation directory does not exist: {}",
            parsed.evaluation_dir.display()
        )));
    }
    if parsed.out_dir.exists() {
        return Err(CommandError::Fatal(format!(
            "output directory already exists: {}",
            parsed.out_dir.display()
        )));
    }
    if !parent_dir_exists(&parsed.out_dir) {
        return Err(CommandError::Fatal(format!(
            "output parent directory does not exist: {}",
            parsed.out_dir.display()
        )));
    }

    let plan: EvaluationPlanV1 = read_json(
        &parsed.evaluation_dir.join("plan.json"),
        MAX_JSON_BYTES,
        "evaluation plan",
    )?;
    let report: EvaluationReportV1 = read_json(
        &parsed.evaluation_dir.join("eval-report.json"),
        MAX_JSON_BYTES,
        "evaluation report",
    )?;
    let checkpoint: PolicyValueCheckpointV1 =
        read_json(&parsed.checkpoint, MAX_JSON_BYTES, "checkpoint")?;
    let specs = expand_schedule(&plan)
        .map_err(|error| CommandError::Fatal(format!("invalid evaluation plan: {error}")))?;
    let mut replays = Vec::with_capacity(specs.len());
    for spec in &specs {
        let path = parsed
            .evaluation_dir
            .join("matches")
            .join(format!("match-{:06}.replay.json", spec.match_index));
        let replay = read_json(&path, MAX_JSON_BYTES, "match replay")?;
        replays.push((spec.match_index, replay));
    }

    let output = analyze_evaluation_neural_v1(
        &plan,
        &report,
        &replays,
        &checkpoint,
        &parsed.config,
        &parsed.candidate_agent_id,
        &parsed.champion_agent_id,
    )
    .map_err(|error| CommandError::Fatal(error.to_string()))?;
    let diagnostic_hash = evaluation_diagnostic_hash_v1(&output.diagnostic)
        .map_err(|error| CommandError::Fatal(error.to_string()))?;
    let mut trace_json = Vec::with_capacity(output.traces.len());
    for trace in &output.traces {
        let mut json = serde_json::to_string_pretty(trace)
            .map_err(|error| CommandError::Fatal(format!("serialize trace failed: {error}")))?;
        json.push('\n');
        trace_json.push(json);
    }
    let mut diagnostic_json = serde_json::to_string_pretty(&output.diagnostic)
        .map_err(|error| CommandError::Fatal(format!("serialize diagnostic failed: {error}")))?;
    diagnostic_json.push('\n');

    fs::create_dir(&parsed.out_dir).map_err(|error| {
        CommandError::Fatal(format!(
            "cannot create output directory {}: {error}",
            parsed.out_dir.display()
        ))
    })?;
    let matches_dir = parsed.out_dir.join("matches");
    fs::create_dir(&matches_dir).map_err(|error| {
        CommandError::Fatal(format!(
            "cannot create matches directory {}: {error}",
            matches_dir.display()
        ))
    })?;
    for (entry, json) in output.diagnostic.matches.iter().zip(&trace_json) {
        atomic_output::commit_single(&parsed.out_dir.join(&entry.analysis_relative_path), json)
            .map_err(|error| CommandError::Fatal(error.to_string()))?;
    }
    atomic_output::commit_single(&parsed.out_dir.join("diagnostic.json"), &diagnostic_json)
        .map_err(|error| CommandError::Fatal(error.to_string()))?;
    Ok(diagnostic_hash)
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
    evaluation_dir: PathBuf,
    checkpoint: PathBuf,
    out_dir: PathBuf,
    candidate_agent_id: String,
    champion_agent_id: String,
    config: NeuralIsmctsConfigV1,
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut values: HashSlots = Default::default();
    let mut index = 0usize;
    while index < args.len() {
        let flag = args[index].as_str();
        let slot = values.slot(flag)?;
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
    Ok(Args {
        evaluation_dir: PathBuf::from(required(values.evaluation_dir, "--evaluation-dir")?),
        checkpoint: PathBuf::from(required(values.checkpoint, "--checkpoint")?),
        out_dir: PathBuf::from(required(values.out_dir, "--out-dir")?),
        candidate_agent_id: required(values.candidate_agent_id, "--candidate-agent-id")?,
        champion_agent_id: required(values.champion_agent_id, "--champion-agent-id")?,
        config: NeuralIsmctsConfigV1 {
            sample_seed: parse_number(values.sample_seed, "--sample-seed", "u64")?,
            simulations: parse_number(values.simulations, "--simulations", "u32")?,
            max_depth_turns: parse_number(values.max_depth_turns, "--max-depth-turns", "u8")?,
            puct_exploration_milli: parse_number(
                values.puct_exploration_milli,
                "--puct-exploration-milli",
                "u32",
            )?,
            expected_checkpoint_hash: required(values.checkpoint_hash, "--checkpoint-hash")?,
        },
    })
}

#[derive(Default)]
struct HashSlots {
    evaluation_dir: Option<String>,
    checkpoint: Option<String>,
    checkpoint_hash: Option<String>,
    sample_seed: Option<String>,
    simulations: Option<String>,
    max_depth_turns: Option<String>,
    puct_exploration_milli: Option<String>,
    candidate_agent_id: Option<String>,
    champion_agent_id: Option<String>,
    out_dir: Option<String>,
}

impl HashSlots {
    fn slot(&mut self, flag: &str) -> Result<&mut Option<String>, String> {
        match flag {
            "--evaluation-dir" => Ok(&mut self.evaluation_dir),
            "--checkpoint" => Ok(&mut self.checkpoint),
            "--checkpoint-hash" => Ok(&mut self.checkpoint_hash),
            "--sample-seed" => Ok(&mut self.sample_seed),
            "--simulations" => Ok(&mut self.simulations),
            "--max-depth-turns" => Ok(&mut self.max_depth_turns),
            "--puct-exploration-milli" => Ok(&mut self.puct_exploration_milli),
            "--candidate-agent-id" => Ok(&mut self.candidate_agent_id),
            "--champion-agent-id" => Ok(&mut self.champion_agent_id),
            "--out-dir" => Ok(&mut self.out_dir),
            other if other.starts_with('-') => Err(format!("unknown flag `{other}`")),
            other => Err(format!("unexpected positional argument `{other}`")),
        }
    }
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
            "--evaluation-dir",
            "evaluation",
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
            "--candidate-agent-id",
            "candidate",
            "--champion-agent-id",
            "champion",
            "--out-dir",
            "diagnostic",
        ]
        .iter()
        .map(|value| (*value).to_string())
        .collect()
    }

    #[test]
    fn parser_requires_exact_batch_contract() {
        let parsed = parse_args(&valid_args()).unwrap();
        assert_eq!(parsed.config.simulations, 64);
        assert_eq!(parsed.candidate_agent_id, "candidate");

        let mut duplicate = valid_args();
        duplicate.extend(["--out-dir".into(), "again".into()]);
        assert!(parse_args(&duplicate).is_err());

        let mut unknown = valid_args();
        unknown.extend(["--extra".into(), "value".into()]);
        assert!(parse_args(&unknown).is_err());
    }
}
