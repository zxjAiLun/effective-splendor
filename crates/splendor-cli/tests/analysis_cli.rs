//! Process-level M14A `analyze-replay-neural` contract.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use splendor_analysis::{analysis_trace_hash_v1, AnalysisTraceV1};
use splendor_learning::{
    model_checkpoint_hash_v1, ModelParametersV1, PolicyValueCheckpointV1,
    SearchTeacherBuildConfigV1, ACTION_FEATURES_V1, MAX_PLAYERS_V1, OBSERVATION_FEATURES_V1,
    POLICY_VALUE_CHECKPOINT_FORMAT, POLICY_VALUE_CHECKPOINT_VERSION, REPRESENTATION_VERSION_V1,
};
use splendor_replay::record_random_game;

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

fn temp_dir(label: &str) -> PathBuf {
    let sequence = SEQUENCE.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-analysis-cli-{}-{label}-{sequence}",
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

fn checkpoint() -> PolicyValueCheckpointV1 {
    let hidden = 4usize;
    PolicyValueCheckpointV1 {
        format: POLICY_VALUE_CHECKPOINT_FORMAT.into(),
        version: POLICY_VALUE_CHECKPOINT_VERSION,
        model_id: "m14a-cli-test-model".into(),
        representation_version: REPRESENTATION_VERSION_V1.into(),
        observation_features: OBSERVATION_FEATURES_V1 as u32,
        action_features: ACTION_FEATURES_V1 as u32,
        hidden_features: hidden as u32,
        max_players: MAX_PLAYERS_V1 as u8,
        source_dataset_id: "m14a-cli-test-dataset".into(),
        source_dataset_hash: "11".repeat(32),
        league_manifest_hash: "22".repeat(32),
        evaluation_plan_hash: "33".repeat(32),
        evaluation_report_hash: "44".repeat(32),
        training_config_hash: "55".repeat(32),
        training_contract_version: None,
        search_teacher_targets_hash: None,
        trained_examples: 4,
        validation_examples: 2,
        validation_seed_modulus: 2,
        validation_seed_remainder: 0,
        epochs: 1,
        parameters: ModelParametersV1 {
            encoder_weights: vec![0.0; hidden * OBSERVATION_FEATURES_V1],
            encoder_bias: vec![0.0; hidden],
            policy_bilinear: vec![0.0; hidden * ACTION_FEATURES_V1],
            policy_action_bias: vec![0.0; ACTION_FEATURES_V1],
            value_weights: vec![0.0; MAX_PLAYERS_V1 * hidden],
            value_bias: vec![0.0; MAX_PLAYERS_V1],
        },
    }
}

fn run(dir: &Path, hash: &str, out: &str) -> Output {
    Command::new(bin())
        .args([
            "analyze-replay-neural",
            "--input",
            "replay.json",
            "--checkpoint",
            "checkpoint.json",
            "--checkpoint-hash",
            hash,
            "--sample-seed",
            "20260811",
            "--simulations",
            "2",
            "--max-depth-turns",
            "1",
            "--puct-exploration-milli",
            "1500",
            "--out",
            out,
        ])
        .current_dir(dir)
        .output()
        .expect("spawn analyzer")
}

#[test]
fn complete_replay_publishes_a_valid_no_overwrite_sidecar() {
    let dir = temp_dir("success");
    let checkpoint = checkpoint();
    let checkpoint_hash = model_checkpoint_hash_v1(&checkpoint).unwrap();
    let (_, replay) = record_random_game(2, 42, 7).unwrap();
    write_json(&dir.join("checkpoint.json"), &checkpoint);
    write_json(&dir.join("replay.json"), &replay);

    let output = run(&dir, &checkpoint_hash, "analysis.json");
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
    let raw = std::fs::read_to_string(dir.join("analysis.json")).unwrap();
    let trace: AnalysisTraceV1 = serde_json::from_str(&raw).unwrap();
    trace.validate().unwrap();
    assert_eq!(trace.frames.len(), replay.steps.len());
    assert_eq!(trace.checkpoint_hash, checkpoint_hash);
    assert_eq!(analysis_trace_hash_v1(&trace).unwrap().len(), 64);

    let second = run(&dir, &checkpoint_hash, "analysis.json");
    assert_eq!(second.status.code(), Some(1));
    assert_eq!(
        std::fs::read_to_string(dir.join("analysis.json")).unwrap(),
        raw
    );
}

#[test]
fn checkpoint_mismatch_creates_no_sidecar_or_protocol_output() {
    let dir = temp_dir("mismatch");
    let checkpoint = checkpoint();
    let (_, replay) = record_random_game(2, 7, 11).unwrap();
    write_json(&dir.join("checkpoint.json"), &checkpoint);
    write_json(&dir.join("replay.json"), &replay);

    let output = run(&dir, &"00".repeat(32), "analysis.json");
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert!(!dir.join("analysis.json").exists());
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("checkpoint hash mismatch"));
}

#[test]
fn checked_in_m15c_teacher_build_config_is_frozen_and_valid() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../benchmarks/m15c-search-teacher-targets-v1.config.json");
    let config: SearchTeacherBuildConfigV1 =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    config.validate().unwrap();
    assert_eq!(
        config.expected_dataset_hash,
        "3f8adcd4e8e6ec224a029085a817f87a06fb450d08dbd37cca05d488f1d29c24"
    );
    assert_eq!(config.teacher_agent_ids, ["determinization-s4-d1-n2000-v1"]);
    assert_eq!(config.targets.search.sample_count, 4);
    assert_eq!(config.targets.uniform_floor_micros, 100_000);
    assert_eq!(config.targets.value_utility_scale, 1_000_000_000);
}
