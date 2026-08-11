//! End-to-end M11 league-plan and executed-evaluation dataset CLI tests.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1};
use splendor_core::{FullState, PlayerId, RulesetFingerprint};
use splendor_eval::{
    aggregate, expand_schedule, promotion_gate_hash_v1, EvaluationMatchRecordV1,
    EvaluationMatchSpecV1, EvaluationPlanV1, PromotionGateV1,
};
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

fn manifest_json(game_seed: u64, simulations: &str, depth: &str) -> serde_json::Value {
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
                    "args": ["agent-ismcts", "--sample-seed", "2", "--simulations", simulations, "--max-depth-turns", depth, "--exploration-bias", "100000000"]
                }
            }
        ],
        "game_seeds": [game_seed],
        "handshake_timeout_ms": 5000,
        "move_timeout_ms": 10000,
        "shutdown_grace_ms": 2000
    })
}

fn arena_report(
    manifest: &LeagueManifestV1,
    spec: &EvaluationMatchSpecV1,
    state: &FullState,
    replay: &ReplayV1,
) -> ArenaReportV1 {
    let fingerprint: RulesetFingerprint = replay.ruleset_fingerprint.as_str().parse().unwrap();
    ArenaReportV1::new(
        spec.arena_config.game_id.clone(),
        replay.engine_version.clone(),
        PROTOCOL_VERSION,
        replay.ruleset.id.clone(),
        replay.ruleset_fingerprint.as_str(),
        replay.player_count,
        seed_commitment_v1(
            &spec.arena_config.game_id,
            replay.player_count,
            replay.seed,
            &fingerprint,
        ),
        spec.agent_ids_by_seat
            .iter()
            .enumerate()
            .map(|(seat, id)| {
                let agent = manifest
                    .agents
                    .iter()
                    .find(|agent| &agent.id == id)
                    .unwrap();
                AgentIdentity {
                    seat: PlayerId(seat as u8),
                    agent_name: Some(agent.runtime_name.clone()),
                    agent_version: Some(agent.runtime_version.clone()),
                }
            })
            .collect(),
        ArenaOutcomeV1::completed(
            state.result.clone().unwrap(),
            replay.steps.len() as u32,
            replay.final_state_hash.as_str().to_string(),
        ),
    )
}

fn write_execution(dir: &Path, manifest: &LeagueManifestV1, state: &FullState, replay: &ReplayV1) {
    let plan = manifest.evaluation_plan_v1().unwrap();
    let specs = expand_schedule(&plan).unwrap();
    let report = arena_report(manifest, &specs[0], state, replay);
    let records = specs
        .iter()
        .map(|spec| EvaluationMatchRecordV1 {
            match_index: spec.match_index,
            game_id: spec.arena_config.game_id.clone(),
            seed_index: spec.seed_index,
            rotation: spec.rotation,
            agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
            outcome: report.outcome.clone(),
        })
        .collect::<Vec<_>>();
    let evaluation_report = aggregate(&plan, &records).unwrap();
    let eval_dir = dir.join("eval");
    let matches_dir = eval_dir.join("matches");
    std::fs::create_dir_all(&matches_dir).unwrap();
    write_json(&eval_dir.join("plan.json"), &plan);
    write_json(&eval_dir.join("eval-report.json"), &evaluation_report);
    write_json(&matches_dir.join("match-000000.report.json"), &report);
    write_json(&matches_dir.join("match-000000.replay.json"), replay);
}

fn write_replay_list(dir: &Path, dataset_id: &str) {
    write_json(
        &dir.join("replays.json"),
        &serde_json::json!({
            "format": "effective-splendor-dataset-replay-list",
            "version": 1,
            "dataset_id": dataset_id,
            "replays": [{ "source_id": "game-000001", "match_index": 0 }]
        }),
    );
}

fn dataset_args() -> [&'static str; 9] {
    [
        "build-dataset",
        "--manifest",
        "league.json",
        "--evaluation-dir",
        "eval",
        "--replays",
        "replays.json",
        "--out",
        "dataset.json",
    ]
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
fn checked_in_m13_neural_candidate_inputs_are_frozen_and_valid() {
    let benchmark_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../benchmarks");
    let manifest: LeagueManifestV1 = serde_json::from_str(
        &std::fs::read_to_string(benchmark_dir.join("m13-neural-ismcts-v1.league.json")).unwrap(),
    )
    .unwrap();
    let gate: PromotionGateV1 = serde_json::from_str(
        &std::fs::read_to_string(benchmark_dir.join("m13-neural-ismcts-v1.gate.json")).unwrap(),
    )
    .unwrap();

    manifest.validate().unwrap();
    gate.validate().unwrap();
    let plan = manifest.evaluation_plan_v1().unwrap();
    assert_eq!(manifest.game_seeds.len(), 32);
    assert_eq!(expand_schedule(&plan).unwrap().len(), 64);
    assert_eq!(gate.min_completed_seed_blocks, 32);
    assert_eq!(gate.candidate_agent_id, manifest.agents[1].id);
    assert_eq!(gate.champion_agent_id, manifest.agents[0].id);
    assert_eq!(
        manifest.agents[1].model_version.as_deref(),
        Some(
            "m12-policy-value-h32-v1@108d32fa2d0d2499ead38e99b23e42cd905644358a76d5adb7392ad43401b462"
        )
    );
    assert_eq!(
        league_manifest_hash_v1(&manifest).unwrap(),
        "d43a15ce20bde451b8bb41b389a71eb136d1b4c07e7908e543c52bcf90841190"
    );
    assert_eq!(
        promotion_gate_hash_v1(&gate).unwrap().as_str(),
        "039d3ce342d6f1bdcc462b3e6c3cfde98f289391372a48be76b31edda6f97f2c"
    );
}

#[test]
fn league_manifest_publishes_canonical_evaluation_plan() {
    let dir = temp_dir("plan");
    write_json(&dir.join("league.json"), &manifest_json(101, "8", "1"));
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
    assert_eq!(plan.game_seeds, vec![101]);
}

#[test]
fn executed_evaluation_publishes_player_view_dataset_without_overwrite() {
    let dir = temp_dir("dataset");
    let manifest_value = manifest_json(42, "8", "1");
    let manifest: LeagueManifestV1 = serde_json::from_value(manifest_value.clone()).unwrap();
    write_json(&dir.join("league.json"), &manifest_value);
    let (state, replay) = record_random_game(2, 42, 9).unwrap();
    write_execution(&dir, &manifest, &state, &replay);
    write_replay_list(&dir, "m11-cli-dataset");

    let args = dataset_args();
    let output = run(&args, &dir);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    let raw = std::fs::read_to_string(dir.join("dataset.json")).unwrap();
    let dataset: TrainingDatasetV1 = serde_json::from_str(&raw).unwrap();
    assert_eq!(dataset.format, TRAINING_DATASET_FORMAT);
    assert_eq!(dataset.examples.len(), replay.steps.len());
    assert_eq!(dataset.replays[0].evaluation_match_index, 0);
    assert_eq!(dataset.evaluation_plan_hash.len(), 64);
    assert_eq!(dataset.evaluation_report_hash.len(), 64);
    assert_eq!(dataset.replays[0].arena_report_hash.len(), 64);
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
    let manifest_value = manifest_json(7, "8", "1");
    let manifest: LeagueManifestV1 = serde_json::from_value(manifest_value.clone()).unwrap();
    write_json(&dir.join("league.json"), &manifest_value);
    let (state, mut replay) = record_random_game(2, 7, 8).unwrap();
    write_execution(&dir, &manifest, &state, &replay);
    replay.steps[0].actor.0 = 1;
    write_json(&dir.join("eval/matches/match-000000.replay.json"), &replay);
    write_replay_list(&dir, "tampered");
    let output = run(&dataset_args(), &dir);
    assert_eq!(output.status.code(), Some(1));
    assert!(!dir.join("dataset.json").exists());
}

#[test]
fn mismatched_arena_identity_is_fatal_and_creates_no_dataset() {
    let dir = temp_dir("bad-report");
    let manifest_value = manifest_json(70, "8", "1");
    let manifest: LeagueManifestV1 = serde_json::from_value(manifest_value.clone()).unwrap();
    write_json(&dir.join("league.json"), &manifest_value);
    let (state, replay) = record_random_game(2, 70, 8).unwrap();
    write_execution(&dir, &manifest, &state, &replay);
    let report_path = dir.join("eval/matches/match-000000.report.json");
    let mut report: ArenaReportV1 =
        serde_json::from_str(&std::fs::read_to_string(&report_path).unwrap()).unwrap();
    report.agents[1].agent_version = Some("unregistered".into());
    write_json(&report_path, &report);
    write_replay_list(&dir, "bad-report");
    let output = run(&dataset_args(), &dir);
    assert_eq!(output.status.code(), Some(1));
    assert!(!dir.join("dataset.json").exists());
}

#[test]
fn same_runtime_but_different_executed_command_is_rejected() {
    let dir = temp_dir("wrong-command");
    let declared_value = manifest_json(81, "64", "2");
    let actual_value = manifest_json(81, "16", "1");
    let actual: LeagueManifestV1 = serde_json::from_value(actual_value).unwrap();
    write_json(&dir.join("league.json"), &declared_value);
    let (state, replay) = record_random_game(2, 81, 8).unwrap();
    write_execution(&dir, &actual, &state, &replay);
    write_replay_list(&dir, "wrong-command");

    let output = run(&dataset_args(), &dir);
    assert_eq!(output.status.code(), Some(1));
    assert!(!dir.join("dataset.json").exists());
    assert!(String::from_utf8_lossy(&output.stderr).contains("evaluation plan hash"));
}
