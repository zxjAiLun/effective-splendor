//! End-to-end M12 training and offline-evaluation CLI contract.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use splendor_core::{CardId, FullState, GameConfig, PlayerId};
use splendor_league::{
    training_dataset_hash_v1, TrainingAgentIdentityV1, TrainingDatasetV1, TrainingExampleV1,
    TrainingReplayV1, TRAINING_DATASET_FORMAT, TRAINING_DATASET_VERSION,
};
use splendor_learning::{
    OfflineEvaluationReportV1, PolicyValueCheckpointV1, PolicyValueTrainingConfigV1,
    PolicyValueTrainingReportV1, POLICY_VALUE_TRAINING_CONFIG_FORMAT,
    POLICY_VALUE_TRAINING_CONFIG_VERSION,
};
use splendor_replay::{ReplayGameResultV1, ReplayTerminalReason};

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

fn temp_dir(label: &str) -> PathBuf {
    let sequence = SEQUENCE.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-learning-cli-{}-{label}-{sequence}",
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

fn run(args: &[&str], dir: &Path) -> Output {
    Command::new(bin())
        .args(args)
        .current_dir(dir)
        .output()
        .expect("spawn splendor")
}

fn fixture() -> (TrainingDatasetV1, PolicyValueTrainingConfigV1) {
    let (state, _) = FullState::new(GameConfig::default()).unwrap();
    let observation = state.observation(PlayerId(0));
    let legal = state.legal_actions();
    let mut dataset = TrainingDatasetV1 {
        format: TRAINING_DATASET_FORMAT.into(),
        version: TRAINING_DATASET_VERSION,
        dataset_id: "m12-cli-dataset".into(),
        league_manifest_hash: "11".repeat(32),
        evaluation_id: "m12-cli-eval".into(),
        evaluation_plan_hash: "22".repeat(32),
        evaluation_report_hash: "33".repeat(32),
        replays: Vec::new(),
        examples: Vec::new(),
    };
    for seed_index in 0..2u32 {
        let source_id = format!("source-{seed_index}");
        let replay_hash = format!("{:064x}", seed_index + 10);
        dataset.replays.push(TrainingReplayV1 {
            source_id: source_id.clone(),
            evaluation_match_index: seed_index,
            seed_index,
            rotation: 0,
            arena_game_id: format!("game-{seed_index}"),
            arena_report_hash: "44".repeat(32),
            replay_document_hash: replay_hash.clone(),
            engine_version: "test".into(),
            ruleset_id: "splendor-base-v1".into(),
            ruleset_fingerprint: "55".repeat(32),
            player_count: 2,
            steps: 2,
            final_state_hash: "66".repeat(32),
            result: ReplayGameResultV1 {
                scores: vec![16, 12],
                ranks: vec![0, 1],
                winners: vec![0],
                reason: ReplayTerminalReason::PrestigeThreshold,
            },
            agents_by_seat: vec![
                TrainingAgentIdentityV1 {
                    seat: PlayerId(0),
                    league_agent_id: "teacher".into(),
                    policy_version: "unit-policy".into(),
                    model_version: None,
                    runtime_name: "unit-runtime".into(),
                    runtime_version: "1".into(),
                },
                TrainingAgentIdentityV1 {
                    seat: PlayerId(1),
                    league_agent_id: "other".into(),
                    policy_version: "unit-policy".into(),
                    model_version: None,
                    runtime_name: "unit-runtime".into(),
                    runtime_version: "1".into(),
                },
            ],
        });
        for ply in 0..2u32 {
            dataset.examples.push(TrainingExampleV1 {
                source_id: source_id.clone(),
                replay_document_hash: replay_hash.clone(),
                ply,
                actor: PlayerId(0),
                observation_hash: "77".repeat(32),
                visible_history_hash: "88".repeat(32),
                information_set_hash: "99".repeat(32),
                observation: observation.clone(),
                legal_actions: legal.clone(),
                chosen_action: legal[(seed_index as usize + ply as usize) % legal.len()],
                final_scores: vec![16, 12],
                final_ranks: vec![0, 1],
            });
        }
    }
    let dataset_hash = training_dataset_hash_v1(&dataset).unwrap();
    let config = PolicyValueTrainingConfigV1 {
        format: POLICY_VALUE_TRAINING_CONFIG_FORMAT.into(),
        version: POLICY_VALUE_TRAINING_CONFIG_VERSION,
        training_id: "m12-cli-training".into(),
        model_id: "m12-cli-model".into(),
        expected_dataset_id: dataset.dataset_id.clone(),
        expected_dataset_hash: dataset_hash,
        expected_league_manifest_hash: dataset.league_manifest_hash.clone(),
        expected_evaluation_plan_hash: dataset.evaluation_plan_hash.clone(),
        expected_evaluation_report_hash: dataset.evaluation_report_hash.clone(),
        hidden_features: 4,
        epochs: 1,
        learning_rate: 0.001,
        value_loss_weight: 1.0,
        l2_weight: 0.0,
        init_seed: 9,
        validation_seed_modulus: 2,
        validation_seed_remainder: 0,
        training_contract_version: None,
        policy_teacher_agent_ids: vec![],
        value_target_agent_ids: vec![],
        min_policy_nll_relative_improvement_bps: None,
        min_value_mse_relative_improvement_bps: None,
        value_updates_shared_encoder: None,
    };
    (dataset, config)
}

#[test]
fn training_and_offline_evaluation_are_atomic_and_bound() {
    let dir = temp_dir("success");
    let (dataset, config) = fixture();
    write_json(&dir.join("dataset.json"), &dataset);
    write_json(&dir.join("config.json"), &config);
    let train_args = [
        "train-policy-value",
        "--dataset",
        "dataset.json",
        "--config",
        "config.json",
        "--checkpoint",
        "checkpoint.json",
        "--report",
        "training-report.json",
    ];
    let output = run(&train_args, &dir);
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stdout.is_empty());
    let checkpoint: PolicyValueCheckpointV1 =
        serde_json::from_str(&std::fs::read_to_string(dir.join("checkpoint.json")).unwrap())
            .unwrap();
    let training: PolicyValueTrainingReportV1 =
        serde_json::from_str(&std::fs::read_to_string(dir.join("training-report.json")).unwrap())
            .unwrap();
    assert_eq!(checkpoint.source_dataset_hash, config.expected_dataset_hash);
    assert_eq!(training.split.train_replays, 1);
    assert_eq!(training.split.validation_replays, 1);

    let evaluate = run(
        &[
            "evaluate-policy-value",
            "--dataset",
            "dataset.json",
            "--checkpoint",
            "checkpoint.json",
            "--out",
            "offline.json",
        ],
        &dir,
    );
    assert_eq!(evaluate.status.code(), Some(0));
    let offline: OfflineEvaluationReportV1 =
        serde_json::from_str(&std::fs::read_to_string(dir.join("offline.json")).unwrap()).unwrap();
    assert_eq!(offline.checkpoint_hash, training.checkpoint_hash);
    assert_eq!(offline.training_config_hash, training.training_config_hash);
    assert_eq!(offline.validation_metrics, training.validation_metrics);

    let second = run(&train_args, &dir);
    assert_eq!(second.status.code(), Some(1));
}

#[test]
fn provenance_mismatch_creates_no_outputs() {
    let dir = temp_dir("mismatch");
    let (dataset, mut config) = fixture();
    config.expected_dataset_hash = "aa".repeat(32);
    write_json(&dir.join("dataset.json"), &dataset);
    write_json(&dir.join("config.json"), &config);
    let output = run(
        &[
            "train-policy-value",
            "--dataset",
            "dataset.json",
            "--config",
            "config.json",
            "--checkpoint",
            "checkpoint.json",
            "--report",
            "training-report.json",
        ],
        &dir,
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(!dir.join("checkpoint.json").exists());
    assert!(!dir.join("training-report.json").exists());
}

#[test]
fn source_aware_training_requires_config_bound_offline_evaluation() {
    let dir = temp_dir("source-aware");
    let (dataset, mut config) = fixture();
    config.training_contract_version = Some(2);
    config.policy_teacher_agent_ids = vec!["teacher".into()];
    config.value_target_agent_ids = vec!["teacher".into()];
    config.min_policy_nll_relative_improvement_bps = Some(1);
    config.min_value_mse_relative_improvement_bps = Some(1);
    write_json(&dir.join("dataset.json"), &dataset);
    write_json(&dir.join("config.json"), &config);
    let train = run(
        &[
            "train-policy-value",
            "--dataset",
            "dataset.json",
            "--config",
            "config.json",
            "--checkpoint",
            "checkpoint.json",
            "--report",
            "training-report.json",
        ],
        &dir,
    );
    assert_eq!(train.status.code(), Some(0));

    let legacy = run(
        &[
            "evaluate-policy-value",
            "--dataset",
            "dataset.json",
            "--checkpoint",
            "checkpoint.json",
            "--out",
            "legacy.json",
        ],
        &dir,
    );
    assert_eq!(legacy.status.code(), Some(1));
    assert!(!dir.join("legacy.json").exists());

    let source_aware = run(
        &[
            "evaluate-policy-value-source-aware",
            "--dataset",
            "dataset.json",
            "--checkpoint",
            "checkpoint.json",
            "--config",
            "config.json",
            "--out",
            "offline.json",
        ],
        &dir,
    );
    assert_eq!(
        source_aware.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&source_aware.stderr)
    );
    let training: PolicyValueTrainingReportV1 =
        serde_json::from_str(&std::fs::read_to_string(dir.join("training-report.json")).unwrap())
            .unwrap();
    let offline: OfflineEvaluationReportV1 =
        serde_json::from_str(&std::fs::read_to_string(dir.join("offline.json")).unwrap()).unwrap();
    assert_eq!(offline.head_split, training.head_split);
    assert_eq!(offline.material_gate, training.material_gate);
}

#[test]
fn malformed_catalog_id_is_fatal_without_panic_or_outputs() {
    let dir = temp_dir("bad-card-id");
    let (mut dataset, mut config) = fixture();
    dataset.examples[0].observation.public.market[0][0] = Some(CardId(255));
    config.expected_dataset_hash = training_dataset_hash_v1(&dataset).unwrap();
    write_json(&dir.join("dataset.json"), &dataset);
    write_json(&dir.join("config.json"), &config);

    let output = run(
        &[
            "train-policy-value",
            "--dataset",
            "dataset.json",
            "--config",
            "config.json",
            "--checkpoint",
            "checkpoint.json",
            "--report",
            "training-report.json",
        ],
        &dir,
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("outside the catalog"), "{stderr}");
    assert!(!stderr.contains("panicked"), "{stderr}");
    assert!(!dir.join("checkpoint.json").exists());
    assert!(!dir.join("training-report.json").exists());
}

#[test]
fn checked_in_m15b_isolated_config_is_source_bound_and_frozen() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../benchmarks/m15b-isolated-policy-value-v2.config.json");
    let config: PolicyValueTrainingConfigV1 =
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    config.validate().unwrap();
    assert_eq!(config.training_contract_version, Some(2));
    assert_eq!(config.value_updates_shared_encoder, Some(false));
    assert_eq!(
        config.expected_dataset_hash,
        "3f8adcd4e8e6ec224a029085a817f87a06fb450d08dbd37cca05d488f1d29c24"
    );
    assert_eq!(config.min_policy_nll_relative_improvement_bps, Some(1500));
    assert_eq!(config.min_value_mse_relative_improvement_bps, Some(500));
}
