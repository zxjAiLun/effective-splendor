//! End-to-end tests for the `run-match` and `agent-random` CLI commands.
//!
//! The normal-match test uses the `splendor` binary as *both* the outer
//! `run-match` driver and the two inner `agent-random` subprocesses — a real
//! three-process pipeline over stdio NDJSON. The remaining tests pin the
//! error, abort, and no-overwrite contracts at the process boundary.
//!
//! Every test uses a unique temp directory so they are safe to run in parallel,
//! but they can also be pinned with `--test-threads=1`.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::Value;
use splendor_arena::{ArenaOutcomeV1, ArenaReportV1};
use splendor_replay::{verify_replay, ReplayV1};

/// Path to the CLI binary under test.
fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

/// A unique temp directory for one test.
fn tmp_dir() -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("arena-cli-{}-{}", std::process::id(), n));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

/// Write `contents` to `<dir>/<name>` and return its path.
fn write_file(dir: &Path, name: &str, contents: &str) -> PathBuf {
    let path = dir.join(name);
    std::fs::write(&path, contents).expect("write file");
    path
}

/// Serialize a JSON config document to `<dir>/config.json`.
fn write_config(dir: &Path, config: &Value) -> PathBuf {
    let text = serde_json::to_string_pretty(config).expect("serialize config");
    write_file(dir, "config.json", &text)
}

/// A standard two-agent config where both seats are `agent-random`.
fn random_config(game_id: &str, seed: u64, seat_seeds: [u64; 2]) -> Value {
    let program = bin().to_string_lossy().into_owned();
    serde_json::json!({
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 10_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            { "program": program, "args": ["agent-random", "--seed", seat_seeds[0].to_string()] },
            { "program": program, "args": ["agent-random", "--seed", seat_seeds[1].to_string()] },
        ]
    })
}

/// Result of invoking `run-match`.
struct RunOutput {
    code: i32,
    stdout: String,
    stderr: String,
}

fn run_match(config: &Path, report_out: &Path, replay_out: &Path) -> RunOutput {
    let output = Command::new(bin())
        .arg("run-match")
        .arg("--config")
        .arg(config)
        .arg("--report-out")
        .arg(report_out)
        .arg("--replay-out")
        .arg(replay_out)
        .output()
        .expect("spawn run-match");
    RunOutput {
        code: output.status.code().expect("exit code"),
        stdout: String::from_utf8(output.stdout).expect("utf8 stdout"),
        stderr: String::from_utf8(output.stderr).expect("utf8 stderr"),
    }
}

/// The file names present in a directory (sorted).
fn dir_names(dir: &Path) -> Vec<String> {
    let mut names: Vec<String> = std::fs::read_dir(dir)
        .expect("read dir")
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    names
}

/// Assert no temp residue (`*.tmp`) is left in the output directory.
fn assert_no_temp(dir: &Path) {
    for name in dir_names(dir) {
        assert!(
            !name.ends_with(".tmp"),
            "unexpected temp residue: {name} in {}",
            dir.display()
        );
    }
}

// ---------------------------------------------------------------------------
// Normal completed match
// ---------------------------------------------------------------------------

#[test]
fn normal_match_completes_with_verified_artifacts() {
    let dir = tmp_dir();
    let config = write_config(&dir, &random_config("cli-random-2p", 42, [1001, 1002]));
    let report_out = dir.join("report.json");
    let replay_out = dir.join("replay.json");

    let out = run_match(&config, &report_out, &replay_out);

    assert_eq!(
        out.code, 0,
        "expected completed exit 0; stderr={}",
        out.stderr
    );
    assert!(
        out.stderr.is_empty(),
        "stderr must be empty: {}",
        out.stderr
    );

    // stdout is a single compact ArenaOutcomeV1 line ending in one LF.
    assert!(out.stdout.ends_with('\n'), "stdout must end with a newline");
    assert_eq!(out.stdout.lines().count(), 1, "stdout must be one line");
    let outcome: ArenaOutcomeV1 =
        serde_json::from_str(out.stdout.trim_end()).expect("stdout parses as outcome");
    assert!(
        matches!(outcome, ArenaOutcomeV1::Completed { .. }),
        "expected completed outcome"
    );

    // Both artifacts exist and strictly deserialize.
    let report_text = std::fs::read_to_string(&report_out).expect("read report");
    let replay_text = std::fs::read_to_string(&replay_out).expect("read replay");
    assert!(report_text.ends_with('\n'), "report has a trailing LF");
    assert!(replay_text.ends_with('\n'), "replay has a trailing LF");

    let report: ArenaReportV1 = strict_json(&report_text).expect("strict report");
    let replay: ReplayV1 = strict_json(&replay_text).expect("strict replay");

    // Replay re-verifies and the report/replay hashes bind.
    let verified = verify_replay(&replay).expect("replay verifies");
    let report_hash = match &report.outcome {
        ArenaOutcomeV1::Completed {
            replay_final_hash, ..
        } => replay_final_hash.clone(),
        ArenaOutcomeV1::Aborted { .. } => panic!("completed match reported aborted"),
    };
    assert_eq!(report_hash, replay.final_state_hash.as_str());
    assert_eq!(report_hash, verified.final_state_hash);

    // Both seats are the reference agent.
    assert_eq!(report.agents.len(), 2);
    for agent in &report.agents {
        assert_eq!(agent.agent_name.as_deref(), Some("splendor-cli-random"));
        assert_eq!(agent.agent_version.as_deref(), Some("0.4.0"));
    }

    assert_no_temp(&dir);
    assert_eq!(
        dir_names(&dir),
        vec!["config.json", "replay.json", "report.json"]
    );
}

/// A two-agent config mixing the heuristic and random programs.
fn mixed_config(game_id: &str, seed: u64, args0: &[&str], args1: &[&str]) -> Value {
    let program = bin().to_string_lossy().into_owned();
    serde_json::json!({
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 10_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            { "program": program, "args": args0 },
            { "program": program, "args": args1 },
        ]
    })
}

/// Run a completed match and assert the artifacts verify and the agent
/// identities are reported correctly. Returns the report for further checks.
fn assert_completed_match(config: &Path, dir: &Path) -> ArenaReportV1 {
    let report_out = dir.join("report.json");
    let replay_out = dir.join("replay.json");
    let out = run_match(config, &report_out, &replay_out);
    assert_eq!(
        out.code, 0,
        "expected completed exit 0; stderr={}",
        out.stderr
    );
    assert!(
        out.stderr.is_empty(),
        "stderr must be empty: {}",
        out.stderr
    );

    let report_text = std::fs::read_to_string(&report_out).expect("read report");
    let replay_text = std::fs::read_to_string(&replay_out).expect("read replay");
    let report: ArenaReportV1 = strict_json(&report_text).expect("strict report");
    let replay: ReplayV1 = strict_json(&replay_text).expect("strict replay");

    let verified = verify_replay(&replay).expect("replay verifies");
    let report_hash = match &report.outcome {
        ArenaOutcomeV1::Completed {
            replay_final_hash, ..
        } => replay_final_hash.clone(),
        ArenaOutcomeV1::Aborted { .. } => panic!("completed match reported aborted"),
    };
    assert_eq!(report_hash, replay.final_state_hash.as_str());
    assert_eq!(report_hash, verified.final_state_hash);
    assert_no_temp(dir);
    report
}

#[test]
fn heuristic_vs_random_match_completes() {
    let dir = tmp_dir();
    let config = write_config(
        &dir,
        &mixed_config(
            "cli-heur-vs-rand",
            42,
            &["agent-heuristic", "--seed", "1001"],
            &["agent-random", "--seed", "1002"],
        ),
    );
    let report = assert_completed_match(&config, &dir);
    assert_eq!(report.agents.len(), 2);
    assert_eq!(
        report.agents[0].agent_name.as_deref(),
        Some("splendor-cli-heuristic")
    );
    assert_eq!(report.agents[0].agent_version.as_deref(), Some("0.1.0"));
    assert_eq!(
        report.agents[1].agent_name.as_deref(),
        Some("splendor-cli-random")
    );
}

#[test]
fn random_vs_heuristic_match_completes() {
    // Seat swap: random in seat 0, heuristic in seat 1.
    let dir = tmp_dir();
    let config = write_config(
        &dir,
        &mixed_config(
            "cli-rand-vs-heur",
            43,
            &["agent-random", "--seed", "2001"],
            &["agent-heuristic", "--seed", "2002"],
        ),
    );
    let report = assert_completed_match(&config, &dir);
    assert_eq!(report.agents.len(), 2);
    assert_eq!(
        report.agents[0].agent_name.as_deref(),
        Some("splendor-cli-random")
    );
    assert_eq!(
        report.agents[1].agent_name.as_deref(),
        Some("splendor-cli-heuristic")
    );
    assert_eq!(report.agents[1].agent_version.as_deref(), Some("0.1.0"));
}

#[test]
fn determinization_agent_runs_complete_live_matches_for_two_three_four_players() {
    for player_count in 2usize..=4 {
        let dir = tmp_dir();
        let program = bin().to_string_lossy().into_owned();
        let determinization_seat = if player_count == 2 {
            0
        } else {
            player_count - 1
        };
        let agents = (0..player_count)
            .map(|seat| {
                if seat == determinization_seat {
                    serde_json::json!({
                        "program": program,
                        "args": [
                            "agent-determinization",
                            "--sample-seed", "17",
                            "--sample-count", "1",
                            "--max-depth-turns", "1",
                            "--max-nodes", "100"
                        ]
                    })
                } else {
                    serde_json::json!({
                        "program": program,
                        "args": ["agent-heuristic", "--seed", (1000 + seat).to_string()]
                    })
                }
            })
            .collect::<Vec<_>>();
        let config = write_config(
            &dir,
            &serde_json::json!({
                "game_id": format!("cli-determinization-{player_count}p"),
                "seed": 40 + player_count,
                "handshake_timeout_ms": 10_000,
                "move_timeout_ms": 10_000,
                "shutdown_grace_ms": 2_000,
                "agents": agents
            }),
        );
        let report = assert_completed_match(&config, &dir);
        assert_eq!(
            report.agents[determinization_seat].agent_name.as_deref(),
            Some("effective-splendor-determinization-agent-v1")
        );
        assert_eq!(
            report.agents[determinization_seat].agent_version.as_deref(),
            Some("1")
        );
    }
}

#[test]
fn ismcts_agent_completes_a_live_player_view_match() {
    let dir = tmp_dir();
    let config = write_config(
        &dir,
        &mixed_config(
            "cli-ismcts-vs-heuristic",
            55,
            &[
                "agent-ismcts",
                "--sample-seed",
                "23",
                "--simulations",
                "8",
                "--max-depth-turns",
                "1",
                "--exploration-bias",
                "100000000",
            ],
            &["agent-heuristic", "--seed", "1002"],
        ),
    );
    let report = assert_completed_match(&config, &dir);
    assert_eq!(
        report.agents[0].agent_name.as_deref(),
        Some("effective-splendor-ismcts-agent-v1")
    );
    assert_eq!(report.agents[0].agent_version.as_deref(), Some("1"));
}

#[test]
fn heuristic_vs_random_replay_verifies() {
    let dir = tmp_dir();
    let config = write_config(
        &dir,
        &mixed_config(
            "cli-heur-replay",
            44,
            &["agent-heuristic", "--seed", "3001"],
            &["agent-random", "--seed", "3002"],
        ),
    );
    let report = assert_completed_match(&config, &dir);
    // The replay must verify and bind to the report's final hash; both agents
    // must appear with their distinct identities.
    let names: Vec<&str> = report
        .agents
        .iter()
        .map(|a| a.agent_name.as_deref().unwrap_or(""))
        .collect();
    assert!(names.contains(&"splendor-cli-heuristic"));
    assert!(names.contains(&"splendor-cli-random"));
}

/// Strict deserialize: reject unknown fields (via the DTO's own
/// `deny_unknown_fields`) and any trailing data after the JSON object.
fn strict_json<T: serde::de::DeserializeOwned>(text: &str) -> serde_json::Result<T> {
    let mut de = serde_json::Deserializer::from_str(text);
    let value = T::deserialize(&mut de)?;
    de.end()?;
    Ok(value)
}

// ---------------------------------------------------------------------------
// Aborted match
// ---------------------------------------------------------------------------

#[test]
fn aborted_match_writes_report_but_no_replay() {
    let dir = tmp_dir();
    let program = bin().to_string_lossy().into_owned();
    // Seat 0 points at a program that cannot be spawned: the match aborts in
    // the handshake phase before any move, blaming seat 0 with `agent_io`.
    let config = write_config(
        &dir,
        &serde_json::json!({
            "game_id": "cli-abort-2p",
            "seed": 7,
            "handshake_timeout_ms": 10_000,
            "move_timeout_ms": 10_000,
            "shutdown_grace_ms": 2_000,
            "agents": [
                { "program": "splendor-nonexistent-agent-xyz", "args": [] },
                { "program": program, "args": ["agent-random", "--seed", "1"] },
            ]
        }),
    );
    let report_out = dir.join("report.json");
    let replay_out = dir.join("replay.json");

    let out = run_match(&config, &report_out, &replay_out);

    assert_eq!(
        out.code, 2,
        "expected aborted exit 2; stderr={}",
        out.stderr
    );
    assert!(
        out.stderr.is_empty(),
        "stderr must be empty: {}",
        out.stderr
    );
    assert_eq!(out.stdout.lines().count(), 1);
    let outcome: ArenaOutcomeV1 =
        serde_json::from_str(out.stdout.trim_end()).expect("stdout parses as outcome");
    match outcome {
        ArenaOutcomeV1::Aborted {
            seat,
            phase,
            reason,
            request_id,
            completed_plies,
        } => {
            assert_eq!(seat, 0);
            assert_eq!(phase, splendor_arena::ArenaPhase::Handshake);
            assert_eq!(reason, splendor_arena::AgentFault::AgentIo);
            assert_eq!(request_id, None);
            assert_eq!(completed_plies, 0);
        }
        ArenaOutcomeV1::Completed { .. } => panic!("expected aborted outcome"),
    }

    // Report exists; replay must NOT.
    assert!(report_out.exists(), "aborted match must write a report");
    assert!(
        !replay_out.exists(),
        "aborted match must not write a replay"
    );
    let report: ArenaReportV1 =
        strict_json(&std::fs::read_to_string(&report_out).unwrap()).expect("strict report");
    assert!(matches!(report.outcome, ArenaOutcomeV1::Aborted { .. }));

    assert_no_temp(&dir);
    assert_eq!(dir_names(&dir), vec!["config.json", "report.json"]);
}

// ---------------------------------------------------------------------------
// Error scenarios
// ---------------------------------------------------------------------------

#[test]
fn invalid_config_creates_no_artifacts() {
    let dir = tmp_dir();
    let config = write_file(&dir, "config.json", "{ this is not valid json ");
    let report_out = dir.join("report.json");
    let replay_out = dir.join("replay.json");

    let out = run_match(&config, &report_out, &replay_out);

    assert_eq!(out.code, 1);
    assert!(out.stdout.is_empty(), "no stdout on error");
    assert!(out.stderr.starts_with("error: "), "stderr: {}", out.stderr);
    assert!(!report_out.exists());
    assert!(!replay_out.exists());
    assert_no_temp(&dir);
}

#[test]
fn unknown_config_field_is_rejected() {
    let dir = tmp_dir();
    let mut config = random_config("cli-random-2p", 42, [1, 2]);
    config
        .as_object_mut()
        .unwrap()
        .insert("surprise".to_string(), Value::Bool(true));
    let config_path = write_config(&dir, &config);
    let report_out = dir.join("report.json");
    let replay_out = dir.join("replay.json");

    let out = run_match(&config_path, &report_out, &replay_out);

    assert_eq!(out.code, 1);
    assert!(out.stdout.is_empty());
    assert!(
        out.stderr.contains("surprise") || out.stderr.contains("unknown"),
        "stderr: {}",
        out.stderr
    );
    assert!(!report_out.exists());
    assert!(!replay_out.exists());
}

#[test]
fn existing_report_is_not_overwritten() {
    let dir = tmp_dir();
    let config = write_config(&dir, &random_config("cli-random-2p", 42, [1, 2]));
    let report_out = write_file(&dir, "report.json", "PRE-EXISTING");
    let replay_out = dir.join("replay.json");

    let out = run_match(&config, &report_out, &replay_out);

    assert_eq!(out.code, 1);
    assert!(out.stdout.is_empty());
    assert!(
        out.stderr.contains("report output already exists"),
        "stderr: {}",
        out.stderr
    );
    // The pre-existing file is untouched.
    assert_eq!(
        std::fs::read_to_string(&report_out).unwrap(),
        "PRE-EXISTING"
    );
    assert!(!replay_out.exists());
}

#[test]
fn existing_replay_is_not_overwritten() {
    let dir = tmp_dir();
    let config = write_config(&dir, &random_config("cli-random-2p", 42, [1, 2]));
    let report_out = dir.join("report.json");
    let replay_out = write_file(&dir, "replay.json", "PRE-EXISTING");

    let out = run_match(&config, &report_out, &replay_out);

    assert_eq!(out.code, 1);
    assert!(out.stdout.is_empty());
    assert!(
        out.stderr.contains("replay output already exists"),
        "stderr: {}",
        out.stderr
    );
    assert_eq!(
        std::fs::read_to_string(&replay_out).unwrap(),
        "PRE-EXISTING"
    );
    assert!(!report_out.exists());
}

#[test]
fn same_output_path_is_rejected() {
    let dir = tmp_dir();
    let config = write_config(&dir, &random_config("cli-random-2p", 42, [1, 2]));
    let same = dir.join("same.json");

    let out = run_match(&config, &same, &same);

    assert_eq!(out.code, 1);
    assert!(out.stdout.is_empty());
    assert!(out.stderr.contains("must differ"), "stderr: {}", out.stderr);
    assert!(!same.exists());
}

#[test]
fn missing_output_parent_is_error() {
    let dir = tmp_dir();
    let config = write_config(&dir, &random_config("cli-random-2p", 42, [1, 2]));
    let report_out = dir.join("no_such_subdir").join("report.json");
    let replay_out = dir.join("replay.json");

    let out = run_match(&config, &report_out, &replay_out);

    assert_eq!(out.code, 1);
    assert!(out.stdout.is_empty());
    assert!(
        out.stderr.contains("parent directory does not exist"),
        "stderr: {}",
        out.stderr
    );
    assert!(!report_out.exists());
    assert!(!replay_out.exists());
}

#[test]
fn internal_error_has_no_stdout() {
    // A config that strictly deserializes but fails `ArenaConfig::validate`
    // (only one agent) surfaces as an internal error from the runner: exit 1,
    // empty stdout, no artifacts.
    let dir = tmp_dir();
    let program = bin().to_string_lossy().into_owned();
    let config = write_config(
        &dir,
        &serde_json::json!({
            "game_id": "cli-one-agent",
            "seed": 1,
            "handshake_timeout_ms": 1_000,
            "move_timeout_ms": 1_000,
            "shutdown_grace_ms": 1_000,
            "agents": [
                { "program": program, "args": ["agent-random", "--seed", "1"] },
            ]
        }),
    );
    let report_out = dir.join("report.json");
    let replay_out = dir.join("replay.json");

    let out = run_match(&config, &report_out, &replay_out);

    assert_eq!(out.code, 1);
    assert!(
        out.stdout.is_empty(),
        "internal error must not print to stdout"
    );
    assert!(out.stderr.starts_with("error: "), "stderr: {}", out.stderr);
    assert!(!report_out.exists());
    assert!(!replay_out.exists());
    assert_no_temp(&dir);
}

// ---------------------------------------------------------------------------
// agent-random argument contract
// ---------------------------------------------------------------------------

#[test]
fn agent_random_requires_seed() {
    let output = Command::new(bin())
        .arg("agent-random")
        .output()
        .expect("spawn agent-random");
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(stderr.contains("--seed"), "stderr: {stderr}");
}

#[test]
fn agent_determinization_requires_all_budgets() {
    let output = Command::new(bin())
        .arg("agent-determinization")
        .arg("--sample-seed")
        .arg("17")
        .output()
        .expect("spawn agent-determinization");
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(stderr.contains("--sample-count"), "stderr: {stderr}");
}

#[test]
fn agent_determinization_help_exits_zero() {
    let output = Command::new(bin())
        .arg("agent-determinization")
        .arg("--help")
        .output()
        .expect("spawn agent-determinization --help");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(
        stdout.contains("Usage: splendor agent-determinization"),
        "stdout: {stdout}"
    );
}

#[test]
fn agent_ismcts_help_and_required_budgets_are_strict() {
    let help = Command::new(bin())
        .arg("agent-ismcts")
        .arg("--help")
        .output()
        .expect("spawn agent-ismcts --help");
    assert_eq!(help.status.code(), Some(0));
    assert!(String::from_utf8(help.stdout)
        .unwrap()
        .contains("Usage: splendor agent-ismcts"));

    let missing = Command::new(bin())
        .arg("agent-ismcts")
        .arg("--sample-seed")
        .arg("1")
        .output()
        .expect("spawn agent-ismcts");
    assert_eq!(missing.status.code(), Some(1));
    assert!(String::from_utf8(missing.stderr)
        .unwrap()
        .contains("--simulations"));
}

#[test]
fn run_match_help_exits_zero() {
    let output = Command::new(bin())
        .arg("run-match")
        .arg("--help")
        .output()
        .expect("spawn run-match --help");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(
        stdout.contains("Usage: splendor run-match"),
        "stdout: {stdout}"
    );
}

#[test]
fn run_match_rejects_unknown_flag() {
    let dir = tmp_dir();
    let config = write_config(&dir, &random_config("cli-random-2p", 42, [1, 2]));
    let output = Command::new(bin())
        .arg("run-match")
        .arg("--config")
        .arg(&config)
        .arg("--report-out")
        .arg(dir.join("report.json"))
        .arg("--replay-out")
        .arg(dir.join("replay.json"))
        .arg("--bogus")
        .output()
        .expect("spawn run-match");
    assert_eq!(output.status.code(), Some(1));
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(stderr.contains("unknown flag"), "stderr: {stderr}");
}
