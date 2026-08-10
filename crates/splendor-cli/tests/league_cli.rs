//! End-to-end M11 league-plan and dataset CLI tests.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1};
use splendor_core::{FullState, PlayerId, RulesetFingerprint};
use splendor_eval::EvaluationPlanV1;
use splendor_league::{
    league_manifest_hash_v1, LeagueManifestV1, TrainingDatasetV1, TRAINING_DATASET_FORMAT,
};
use splendor_protocol::PROTOCOL_VERSION;
use splendor_replay::{record_random_game, ReplayV1};

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

fn temp_dir(label: &str) -> PathBuf {
    let sequence = SEQUENCE.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-league-cli-{}-{label}-{sequence}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn write_json(path: &Path, value: &impl serde::Serialize) {
    let mut json = serde_json::to_string_pretty(value).unwrap();
    json.push('\n');
    std::fs::write(path, json).unwrap();
}

fn manifest_json() -> serde_json::Value {
    serde_json::json!({
        "format": "effective-splendor-league-manifest",
        "version": 1,
        "league_id": "m11-cli",
        "lineup_id": "champion-candidate",
        "agents": [
            {
                "id": "champion",
                "role": "champion",
                "policy_version": "heuristic-v1",
                "model_version": null,
                "runtime_name": "splendor-cli-heuristic",
                "runtime_version": "0.1.0",
                "command": { "program": "splendor", "args": ["agent-heuristic", "--seed", "1"] }
            },
            {
                "id": "candidate",
                "role": "candidate",
                "policy_version": "ismcts-v1",
                "model_version": null,
                "runtime_name": "effective-splendor-ismcts-agent-v1",
                "runtime_version": "1",
                "command": {
                    "program": "splendor",
                    "args": ["agent-ismcts", "--sample-seed", "2", "--simulations", "8", "--max-depth-turns", "1", "--exploration-bias", "100000000"]
                }
            }
        ],
        "game_seeds": [101, 102],
        "handshake_timeout_ms": 5000,
        "move_timeout_ms": 10000,
        "shutdown_grace_ms": 2000
    })
}

fn arena_report(state: &FullState, replay: &ReplayV1) -> ArenaReportV1 {
    let fingerprint: RulesetFingerprint = replay.ruleset_fingerprint.as_str().parse().unwrap();
    ArenaReportV1::new(
        "m11-cli-game",
        replay.engine_version.clone(),
        PROTOCOL_VERSION,
        replay.ruleset.id.clone(),
        replay.ruleset_fingerprint.as_str(),
        replay.player_count,
        seed_commitment_v1(
            "m11-cli-game",
            replay.player_count,
            replay.seed,
            &fingerprint,
        ),
        vec![
            AgentIdentity {
                seat: PlayerId(0),
                agent_name: Some("splendor-cli-heuristic".into()),
                agent_version: Some("0.1.0".into()),
            },
            AgentIdentity {
                seat: PlayerId(1),
                agent_name: Some("effective-splendor-ismcts-agent-v1".into()),
                agent_version: Some("1".into()),
            },
        ],
        ArenaOutcomeV1::completed(
            state.result.clone().unwrap(),
            replay.steps.len() as u32,
            replay.final_state_hash.as_str().to_string(),
        ),
    )
}

fn run(args: &[&str], dir: &Path) -> Output {
    Command::new(bin())
        .args(args)
        .current_dir(dir)
        .output()
        .expect("spawn splendor")
}

#[test]
fn checked_in_m10_league_manifest_is_frozen_and_valid() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../benchmarks/m10-ismcts-v1.league.json");
    let manifest: LeagueManifestV1 =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    manifest.validate().unwrap();
    assert_eq!(manifest.game_seeds.len(), 32);
    assert_eq!(
        manifest.agents[0].role,
        splendor_league::LeagueRoleV1::Champion
    );
    assert_eq!(
        manifest.agents[1].role,
        splendor_league::LeagueRoleV1::Candidate
    );
    assert_eq!(
        league_manifest_hash_v1(&manifest).unwrap(),
        "3a8d3d779f0dc56d9284546af5a4552c2b3b15e3cdcd7a2e4908f3d006714ca6"
    );
}

#[test]
fn league_manifest_publishes_canonical_evaluation_plan() {
    let dir = temp_dir("plan");
    write_json(&dir.join("league.json"), &manifest_json());
    let output = run(
        &[
            "league-plan",
            "--manifest",
            "league.json",
            "--out",
            "plan.json",
        ],
        &dir,
    );
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
    let plan: EvaluationPlanV1 =
        serde_json::from_str(&std::fs::read_to_string(dir.join("plan.json")).unwrap()).unwrap();
    assert_eq!(plan.evaluation_id, "m11-cli-champion-candidate");
    assert_eq!(plan.agents.len(), 2);
    assert_eq!(plan.game_seeds, vec![101, 102]);
}

#[test]
fn verified_replay_list_publishes_player_view_dataset_without_overwrite() {
    let dir = temp_dir("dataset");
    write_json(&dir.join("league.json"), &manifest_json());
    let (state, replay) = record_random_game(2, 42, 9).unwrap();
    write_json(&dir.join("game.replay.json"), &replay);
    write_json(
        &dir.join("game.report.json"),
        &arena_report(&state, &replay),
    );
    write_json(
        &dir.join("replays.json"),
        &serde_json::json!({
            "format": "effective-splendor-dataset-replay-list",
            "version": 1,
            "dataset_id": "m11-cli-dataset",
            "replays": [{
                "source_id": "game-000001",
                "path": "game.replay.json",
                "report": "game.report.json"
            }]
        }),
    );
    let args = [
        "build-dataset",
        "--manifest",
        "league.json",
        "--replays",
        "replays.json",
        "--out",
        "dataset.json",
    ];
    let output = run(&args, &dir);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    let raw = std::fs::read_to_string(dir.join("dataset.json")).unwrap();
    let dataset: TrainingDatasetV1 = serde_json::from_str(&raw).unwrap();
    assert_eq!(dataset.format, TRAINING_DATASET_FORMAT);
    assert_eq!(dataset.examples.len(), replay.steps.len());
    assert!(!raw.contains("state_hash_before"));
    assert!(!raw.contains("\"seed\""));

    let second = run(&args, &dir);
    assert_eq!(second.status.code(), Some(1));
    assert_eq!(
        std::fs::read_to_string(dir.join("dataset.json")).unwrap(),
        raw
    );
}

#[test]
fn tampered_replay_is_fatal_and_creates_no_dataset() {
    let dir = temp_dir("tampered");
    write_json(&dir.join("league.json"), &manifest_json());
    let (state, mut replay) = record_random_game(2, 7, 8).unwrap();
    let report = arena_report(&state, &replay);
    replay.steps[0].actor.0 = 1;
    write_json(&dir.join("bad.replay.json"), &replay);
    write_json(&dir.join("game.report.json"), &report);
    write_json(
        &dir.join("replays.json"),
        &serde_json::json!({
            "format": "effective-splendor-dataset-replay-list",
            "version": 1,
            "dataset_id": "tampered",
            "replays": [{
                "source_id": "bad",
                "path": "bad.replay.json",
                "report": "game.report.json"
            }]
        }),
    );
    let output = run(
        &[
            "build-dataset",
            "--manifest",
            "league.json",
            "--replays",
            "replays.json",
            "--out",
            "dataset.json",
        ],
        &dir,
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(!dir.join("dataset.json").exists());
}

#[test]
fn mismatched_arena_identity_is_fatal_and_creates_no_dataset() {
    let dir = temp_dir("bad-report");
    write_json(&dir.join("league.json"), &manifest_json());
    let (state, replay) = record_random_game(2, 70, 8).unwrap();
    let mut report = arena_report(&state, &replay);
    report.agents[1].agent_version = Some("unregistered".into());
    write_json(&dir.join("game.replay.json"), &replay);
    write_json(&dir.join("game.report.json"), &report);
    write_json(
        &dir.join("replays.json"),
        &serde_json::json!({
            "format": "effective-splendor-dataset-replay-list",
            "version": 1,
            "dataset_id": "bad-report",
            "replays": [{
                "source_id": "bad-report",
                "path": "game.replay.json",
                "report": "game.report.json"
            }]
        }),
    );
    let output = run(
        &[
            "build-dataset",
            "--manifest",
            "league.json",
            "--replays",
            "replays.json",
            "--out",
            "dataset.json",
        ],
        &dir,
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(!dir.join("dataset.json").exists());
}
