//! M15C provenance-bound search-distribution teacher targets.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use splendor_league::TrainingDatasetV1;
use splendor_learning::{
    build_search_teacher_targets_v1, search_teacher_targets_hash_v1, SearchTeacherBuildConfigV1,
};
use splendor_replay::ReplayV1;

use crate::atomic_output;

const MAX_DATASET_BYTES: u64 = 256 * 1024 * 1024;
const MAX_REPLAY_BYTES: u64 = 16 * 1024 * 1024;
const MAX_CONFIG_BYTES: u64 = 1024 * 1024;

const USAGE: &str = "\
Usage: splendor build-search-teacher-targets --dataset <dataset.json> \
--evaluation-dir <dir> --config <config.json> --out <targets.json>

Strictly join a provenance-bound player-view dataset to its verified replays,
rerun the frozen root-determinization teacher on selected agent decisions, and
publish exact soft Policy plus search-shaped vector-Value targets.

Exit codes: 0 success, 1 fatal; output is atomic and never overwritten.";

#[derive(Debug)]
struct CommandError(String);

impl std::fmt::Display for CommandError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

pub fn run_build_search_teacher_targets(args: &[String]) -> i32 {
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
            let _ = writeln!(stdout, "search_teacher_targets_hash={hash}");
            let _ = stdout.flush();
            0
        }
        Err(error) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {error}");
            let _ = stderr.flush();
            1
        }
    }
}

fn run_inner(args: &[String]) -> Result<String, CommandError> {
    let parsed = parse_args(args)?;
    precheck_output(&parsed.out)?;
    if !parsed.evaluation_dir.is_dir() {
        return Err(CommandError(format!(
            "evaluation directory does not exist: {}",
            parsed.evaluation_dir.display()
        )));
    }
    let dataset: TrainingDatasetV1 =
        read_json(&parsed.dataset, MAX_DATASET_BYTES, "training dataset")?;
    let config: SearchTeacherBuildConfigV1 =
        read_json(&parsed.config, MAX_CONFIG_BYTES, "teacher build config")?;
    let mut replays = Vec::with_capacity(dataset.replays.len());
    for source in &dataset.replays {
        let path = parsed.evaluation_dir.join("matches").join(format!(
            "match-{:06}.replay.json",
            source.evaluation_match_index
        ));
        let replay: ReplayV1 = read_json(&path, MAX_REPLAY_BYTES, "match replay")?;
        replays.push((source.evaluation_match_index, replay));
    }
    let targets = build_search_teacher_targets_v1(&dataset, &replays, &config)
        .map_err(|error| CommandError(error.to_string()))?;
    let hash = search_teacher_targets_hash_v1(&targets)
        .map_err(|error| CommandError(error.to_string()))?;
    let mut json = serde_json::to_string_pretty(&targets)
        .map_err(|error| CommandError(format!("serialize targets failed: {error}")))?;
    json.push('\n');
    atomic_output::commit_single(&parsed.out, &json)
        .map_err(|error| CommandError(error.to_string()))?;
    Ok(hash)
}

struct Args {
    dataset: PathBuf,
    evaluation_dir: PathBuf,
    config: PathBuf,
    out: PathBuf,
}

fn parse_args(args: &[String]) -> Result<Args, CommandError> {
    let mut dataset = None;
    let mut evaluation_dir = None;
    let mut config = None;
    let mut out = None;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        let slot = match flag {
            "--dataset" => &mut dataset,
            "--evaluation-dir" => &mut evaluation_dir,
            "--config" => &mut config,
            "--out" => &mut out,
            other if other.starts_with('-') => {
                return Err(CommandError(format!("unknown flag `{other}`")))
            }
            other => {
                return Err(CommandError(format!(
                    "unexpected positional argument `{other}`"
                )))
            }
        };
        if slot.is_some() {
            return Err(CommandError(format!("duplicate flag `{flag}`")));
        }
        let value = args
            .get(index + 1)
            .filter(|value| !value.starts_with('-'))
            .ok_or_else(|| CommandError(format!("missing value for `{flag}`")))?;
        *slot = Some(value.clone());
        index += 2;
    }
    let required = |value: Option<String>, flag: &str| {
        value.ok_or_else(|| CommandError(format!("missing required {flag}")))
    };
    Ok(Args {
        dataset: PathBuf::from(required(dataset, "--dataset")?),
        evaluation_dir: PathBuf::from(required(evaluation_dir, "--evaluation-dir")?),
        config: PathBuf::from(required(config, "--config")?),
        out: PathBuf::from(required(out, "--out")?),
    })
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

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_args() -> Vec<String> {
        [
            "--dataset",
            "dataset.json",
            "--evaluation-dir",
            "evaluation",
            "--config",
            "teacher-config.json",
            "--out",
            "targets.json",
        ]
        .iter()
        .map(|value| (*value).into())
        .collect()
    }

    #[test]
    fn parser_freezes_every_teacher_projection_input() {
        let parsed = parse_args(&valid_args()).unwrap();
        assert_eq!(parsed.config, PathBuf::from("teacher-config.json"));
        let mut missing = valid_args();
        missing.drain(4..6);
        assert!(parse_args(&missing).is_err());
        let mut duplicate = valid_args();
        duplicate.extend(["--config".into(), "other.json".into()]);
        assert!(parse_args(&duplicate).is_err());
    }
}
