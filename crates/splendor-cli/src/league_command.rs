//! M11 league-plan and player-view dataset commands.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use serde::Deserialize;
use splendor_arena::ArenaReportV1;
use splendor_league::{build_training_dataset_v1, DatasetReplaySourceV1, LeagueManifestV1};
use splendor_replay::ReplayV1;

use crate::atomic_output;

const MAX_MANIFEST_BYTES: u64 = 1024 * 1024;
const MAX_REPLAY_BYTES: u64 = 16 * 1024 * 1024;
const MAX_REPORT_BYTES: u64 = 1024 * 1024;
const MAX_DATASET_REPLAYS: usize = 1_000;

const LEAGUE_PLAN_USAGE: &str = "\
Usage: splendor league-plan --manifest <league.json> --out <evaluation-plan.json>

Validate a LeagueManifestV1 and atomically publish its canonical seat-rotated
EvaluationPlanV1. Exit 0 success, 1 fatal; stdout is empty.";

const BUILD_DATASET_USAGE: &str = "\
Usage: splendor build-dataset --manifest <league.json> --replays <replay-list.json> --out <dataset.json>

Strictly bind every Arena report to its replay, verify the replay, and atomically
publish a player-view training dataset. Paths are resolved relative to
replay-list.json. Exit 0 success, 1 fatal; stdout is empty.";

const REPLAY_LIST_FORMAT: &str = "effective-splendor-dataset-replay-list";

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DatasetReplayListV1 {
    format: String,
    version: u32,
    dataset_id: String,
    replays: Vec<DatasetReplayPathV1>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DatasetReplayPathV1 {
    source_id: String,
    path: PathBuf,
    report: PathBuf,
}

#[derive(Debug)]
struct CommandError(String);

impl std::fmt::Display for CommandError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

pub fn run_league_plan(args: &[String]) -> i32 {
    run_command(|| {
        if wants_help(args) {
            print_stdout(LEAGUE_PLAN_USAGE);
            return Ok(());
        }
        let parsed = parse_two_paths(args, "--manifest", "--out")?;
        precheck_output(&parsed.second)?;
        let manifest: LeagueManifestV1 =
            read_json(&parsed.first, MAX_MANIFEST_BYTES, "league manifest")?;
        manifest
            .validate()
            .map_err(|error| CommandError(error.to_string()))?;
        let plan = manifest
            .evaluation_plan_v1()
            .map_err(|error| CommandError(error.to_string()))?;
        commit_json(&parsed.second, &plan)
    })
}

pub fn run_build_dataset(args: &[String]) -> i32 {
    run_command(|| {
        if wants_help(args) {
            print_stdout(BUILD_DATASET_USAGE);
            return Ok(());
        }
        let parsed = parse_dataset_args(args)?;
        precheck_output(&parsed.out)?;
        let manifest: LeagueManifestV1 =
            read_json(&parsed.manifest, MAX_MANIFEST_BYTES, "league manifest")?;
        let list: DatasetReplayListV1 =
            read_json(&parsed.replays, MAX_MANIFEST_BYTES, "replay list")?;
        if list.format != REPLAY_LIST_FORMAT || list.version != 1 {
            return Err(CommandError("invalid replay-list format/version".into()));
        }
        if list.replays.is_empty() || list.replays.len() > MAX_DATASET_REPLAYS {
            return Err(CommandError(format!(
                "replay list must contain 1..={MAX_DATASET_REPLAYS} entries"
            )));
        }
        let base = parsed
            .replays
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        let mut owned = Vec::with_capacity(list.replays.len());
        for entry in &list.replays {
            let replay_path = resolve_input(base, &entry.path);
            let report_path = resolve_input(base, &entry.report);
            let replay: ReplayV1 = read_json(&replay_path, MAX_REPLAY_BYTES, "replay")?;
            let report: ArenaReportV1 = read_json(&report_path, MAX_REPORT_BYTES, "arena report")?;
            owned.push((entry.source_id.clone(), replay, report));
        }
        let sources = owned
            .iter()
            .map(|(source_id, replay, arena_report)| DatasetReplaySourceV1 {
                source_id,
                replay,
                arena_report,
            })
            .collect::<Vec<_>>();
        let dataset = build_training_dataset_v1(&list.dataset_id, &manifest, &sources)
            .map_err(|error| CommandError(error.to_string()))?;
        commit_json(&parsed.out, &dataset)
    })
}

fn resolve_input(base: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        base.join(path)
    }
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
    let mut raw = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut raw)
        .map_err(|error| {
            CommandError(format!("cannot read {label} {}: {error}", path.display()))
        })?;
    if raw.len() as u64 > limit {
        return Err(CommandError(format!("{label} exceeds {limit} bytes")));
    }
    let text =
        String::from_utf8(raw).map_err(|_| CommandError(format!("{label} is not valid UTF-8")))?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let value = T::deserialize(&mut deserializer)
        .map_err(|error| CommandError(format!("invalid {label}: {error}")))?;
    deserializer
        .end()
        .map_err(|_| CommandError(format!("trailing data after {label} JSON")))?;
    Ok(value)
}

fn commit_json<T: serde::Serialize>(path: &Path, value: &T) -> Result<(), CommandError> {
    let mut json = serde_json::to_string_pretty(value)
        .map_err(|error| CommandError(format!("serialize output: {error}")))?;
    json.push('\n');
    atomic_output::commit_single(path, &json).map_err(|error| CommandError(error.to_string()))
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

struct TwoPaths {
    first: PathBuf,
    second: PathBuf,
}

fn parse_two_paths(
    args: &[String],
    first_flag: &str,
    second_flag: &str,
) -> Result<TwoPaths, CommandError> {
    let mut first = None;
    let mut second = None;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        let slot = if flag == first_flag {
            &mut first
        } else if flag == second_flag {
            &mut second
        } else {
            return Err(CommandError(format!("unknown flag `{flag}`")));
        };
        set_path(slot, flag, args.get(index + 1))?;
        index += 2;
    }
    Ok(TwoPaths {
        first: first.ok_or_else(|| CommandError(format!("missing required {first_flag}")))?,
        second: second.ok_or_else(|| CommandError(format!("missing required {second_flag}")))?,
    })
}

struct DatasetArgs {
    manifest: PathBuf,
    replays: PathBuf,
    out: PathBuf,
}

fn parse_dataset_args(args: &[String]) -> Result<DatasetArgs, CommandError> {
    let mut manifest = None;
    let mut replays = None;
    let mut out = None;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        let slot = match flag {
            "--manifest" => &mut manifest,
            "--replays" => &mut replays,
            "--out" => &mut out,
            _ => return Err(CommandError(format!("unknown flag `{flag}`"))),
        };
        set_path(slot, flag, args.get(index + 1))?;
        index += 2;
    }
    Ok(DatasetArgs {
        manifest: manifest.ok_or_else(|| CommandError("missing required --manifest".into()))?,
        replays: replays.ok_or_else(|| CommandError("missing required --replays".into()))?,
        out: out.ok_or_else(|| CommandError("missing required --out".into()))?,
    })
}

fn set_path(
    slot: &mut Option<PathBuf>,
    flag: &str,
    value: Option<&String>,
) -> Result<(), CommandError> {
    if slot.is_some() {
        return Err(CommandError(format!("duplicate flag `{flag}`")));
    }
    let value = value
        .filter(|value| !value.starts_with("--"))
        .ok_or_else(|| CommandError(format!("flag `{flag}` is missing a value")))?;
    *slot = Some(PathBuf::from(value));
    Ok(())
}

fn wants_help(args: &[String]) -> bool {
    args.iter().any(|arg| arg == "-h" || arg == "--help")
}

fn print_stdout(text: &str) {
    let mut stdout = io::stdout().lock();
    let _ = writeln!(stdout, "{text}");
    let _ = stdout.flush();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strict_path_parser_rejects_missing_duplicate_and_unknown_flags() {
        assert!(parse_two_paths(&[], "--manifest", "--out").is_err());
        assert!(parse_two_paths(
            &[
                "--manifest".into(),
                "a".into(),
                "--manifest".into(),
                "b".into()
            ],
            "--manifest",
            "--out"
        )
        .is_err());
        assert!(parse_dataset_args(&["--wat".into(), "x".into()]).is_err());
    }
}
