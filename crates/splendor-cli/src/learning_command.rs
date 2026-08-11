//! M12 deterministic supervised policy/value training and offline evaluation.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use splendor_league::TrainingDatasetV1;
use splendor_learning::{
    evaluate_checkpoint_v1, train_policy_value_v1, PolicyValueCheckpointV1,
    PolicyValueTrainingConfigV1,
};

use crate::atomic_output;

const MAX_DATASET_BYTES: u64 = 256 * 1024 * 1024;
const MAX_CONFIG_BYTES: u64 = 1024 * 1024;
const MAX_CHECKPOINT_BYTES: u64 = 16 * 1024 * 1024;

const TRAIN_USAGE: &str = "\
Usage: splendor train-policy-value --dataset <dataset.json> --config <config.json> --checkpoint <checkpoint.json> --report <training-report.json>

Train the deterministic M12 player-view policy + multiplayer vector-value
baseline. The checkpoint is published first and the report last as the commit
marker. Both outputs are atomic and never overwrite existing files.

Exit codes: 0 success, 1 fatal; stdout is empty.";

const EVALUATE_USAGE: &str = "\
Usage: splendor evaluate-policy-value --dataset <dataset.json> --checkpoint <checkpoint.json> --out <offline-eval.json>

Recompute source-level train/validation metrics from a bound M12 checkpoint.
The output is atomic and never overwrites an existing file.

Exit codes: 0 success, 1 fatal; stdout is empty.";

#[derive(Debug)]
struct CommandError(String);

impl std::fmt::Display for CommandError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

pub fn run_train_policy_value(args: &[String]) -> i32 {
    run_command(|| {
        if wants_help(args) {
            print_stdout(TRAIN_USAGE);
            return Ok(());
        }
        let paths = parse_train_args(args)?;
        precheck_output(&paths.checkpoint)?;
        precheck_output(&paths.report)?;
        let dataset: TrainingDatasetV1 =
            read_json(&paths.dataset, MAX_DATASET_BYTES, "training dataset")?;
        let config: PolicyValueTrainingConfigV1 =
            read_json(&paths.config, MAX_CONFIG_BYTES, "training config")?;
        let (checkpoint, report) = train_policy_value_v1(&dataset, &config)
            .map_err(|error| CommandError(error.to_string()))?;
        let checkpoint_json = pretty_json(&checkpoint)?;
        let report_json = pretty_json(&report)?;
        atomic_output::commit_completed_with(
            &paths.checkpoint,
            &checkpoint_json,
            &paths.report,
            &report_json,
            atomic_output::publish_new,
        )
        .map_err(|error| CommandError(error.to_string()))
    })
}

pub fn run_evaluate_policy_value(args: &[String]) -> i32 {
    run_command(|| {
        if wants_help(args) {
            print_stdout(EVALUATE_USAGE);
            return Ok(());
        }
        let paths = parse_evaluate_args(args)?;
        precheck_output(&paths.out)?;
        let dataset: TrainingDatasetV1 =
            read_json(&paths.dataset, MAX_DATASET_BYTES, "training dataset")?;
        let checkpoint: PolicyValueCheckpointV1 = read_json(
            &paths.checkpoint,
            MAX_CHECKPOINT_BYTES,
            "policy/value checkpoint",
        )?;
        let report = evaluate_checkpoint_v1(&dataset, &checkpoint)
            .map_err(|error| CommandError(error.to_string()))?;
        let report_json = pretty_json(&report)?;
        atomic_output::commit_single(&paths.out, &report_json)
            .map_err(|error| CommandError(error.to_string()))
    })
}

fn run_command<F>(command: F) -> i32
where
    F: FnOnce() -> Result<(), CommandError>,
{
    match command() {
        Ok(()) => 0,
        Err(error) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {error}");
            let _ = stderr.flush();
            1
        }
    }
}

fn read_json<T: DeserializeOwned>(path: &Path, limit: u64, label: &str) -> Result<T, CommandError> {
    let file = File::open(path).map_err(|error| {
        CommandError(format!("cannot open {label} {}: {error}", path.display()))
    })?;
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| {
            CommandError(format!("cannot read {label} {}: {error}", path.display()))
        })?;
    if bytes.len() as u64 > limit {
        return Err(CommandError(format!("{label} exceeds {limit} bytes")));
    }
    let text = String::from_utf8(bytes)
        .map_err(|_| CommandError(format!("{label} is not valid UTF-8")))?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let value = T::deserialize(&mut deserializer)
        .map_err(|error| CommandError(format!("invalid {label}: {error}")))?;
    deserializer
        .end()
        .map_err(|_| CommandError(format!("trailing data after {label} JSON")))?;
    Ok(value)
}

fn pretty_json(value: &impl serde::Serialize) -> Result<String, CommandError> {
    let mut json = serde_json::to_string_pretty(value)
        .map_err(|error| CommandError(format!("serialize output: {error}")))?;
    json.push('\n');
    Ok(json)
}

fn precheck_output(path: &Path) -> Result<(), CommandError> {
    if path.exists() {
        return Err(CommandError(format!(
            "artifact already exists: {}",
            path.display()
        )));
    }
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        if !parent.is_dir() {
            return Err(CommandError(format!(
                "output parent does not exist: {}",
                parent.display()
            )));
        }
    }
    Ok(())
}

struct TrainPaths {
    dataset: PathBuf,
    config: PathBuf,
    checkpoint: PathBuf,
    report: PathBuf,
}

fn parse_train_args(args: &[String]) -> Result<TrainPaths, CommandError> {
    let mut dataset = None;
    let mut config = None;
    let mut checkpoint = None;
    let mut report = None;
    parse_flags(
        args,
        &mut [
            ("--dataset", &mut dataset),
            ("--config", &mut config),
            ("--checkpoint", &mut checkpoint),
            ("--report", &mut report),
        ],
    )?;
    Ok(TrainPaths {
        dataset: required(dataset, "--dataset")?,
        config: required(config, "--config")?,
        checkpoint: required(checkpoint, "--checkpoint")?,
        report: required(report, "--report")?,
    })
}

struct EvaluatePaths {
    dataset: PathBuf,
    checkpoint: PathBuf,
    out: PathBuf,
}

fn parse_evaluate_args(args: &[String]) -> Result<EvaluatePaths, CommandError> {
    let mut dataset = None;
    let mut checkpoint = None;
    let mut out = None;
    parse_flags(
        args,
        &mut [
            ("--dataset", &mut dataset),
            ("--checkpoint", &mut checkpoint),
            ("--out", &mut out),
        ],
    )?;
    Ok(EvaluatePaths {
        dataset: required(dataset, "--dataset")?,
        checkpoint: required(checkpoint, "--checkpoint")?,
        out: required(out, "--out")?,
    })
}

fn parse_flags(
    args: &[String],
    slots: &mut [(&str, &mut Option<PathBuf>)],
) -> Result<(), CommandError> {
    if args.len() % 2 != 0 {
        return Err(CommandError("every flag requires one path value".into()));
    }
    for pair in args.chunks_exact(2) {
        let flag = pair[0].as_str();
        let value = pair[1].as_str();
        if value.is_empty() || value.starts_with('-') {
            return Err(CommandError(format!("invalid value for {flag}")));
        }
        let slot = slots
            .iter_mut()
            .find(|(name, _)| *name == flag)
            .ok_or_else(|| CommandError(format!("unknown flag `{flag}`")))?;
        if slot.1.replace(PathBuf::from(value)).is_some() {
            return Err(CommandError(format!("duplicate flag `{flag}`")));
        }
    }
    Ok(())
}

fn required(value: Option<PathBuf>, flag: &str) -> Result<PathBuf, CommandError> {
    value.ok_or_else(|| CommandError(format!("missing required {flag}")))
}

fn wants_help(args: &[String]) -> bool {
    args.len() == 1 && matches!(args[0].as_str(), "-h" | "--help")
}

fn print_stdout(text: &str) {
    let mut stdout = io::stdout().lock();
    let _ = writeln!(stdout, "{text}");
    let _ = stdout.flush();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strings(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_string()).collect()
    }

    #[test]
    fn strict_training_parser_accepts_exact_contract() {
        let parsed = parse_train_args(&strings(&[
            "--dataset",
            "data.json",
            "--config",
            "config.json",
            "--checkpoint",
            "model.json",
            "--report",
            "report.json",
        ]))
        .unwrap();
        assert_eq!(parsed.dataset, PathBuf::from("data.json"));
    }

    #[test]
    fn strict_parser_rejects_duplicate_unknown_and_missing_flags() {
        assert!(parse_train_args(&strings(&["--dataset", "a"])).is_err());
        assert!(parse_evaluate_args(&strings(&[
            "--dataset",
            "a",
            "--checkpoint",
            "b",
            "--wat",
            "c",
        ]))
        .is_err());
        assert!(parse_evaluate_args(&strings(&[
            "--dataset",
            "a",
            "--dataset",
            "b",
            "--checkpoint",
            "c",
            "--out",
            "d",
        ]))
        .is_err());
    }
}
