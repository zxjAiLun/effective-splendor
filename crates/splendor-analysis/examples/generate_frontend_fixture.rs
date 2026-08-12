use std::fs;
use std::path::PathBuf;

use splendor_analysis::analyze_replay_neural_v1;
use splendor_learning::{
    model_checkpoint_hash_v1, ModelParametersV1, PolicyValueCheckpointV1, ACTION_FEATURES_V1,
    MAX_PLAYERS_V1, OBSERVATION_FEATURES_V1, POLICY_VALUE_CHECKPOINT_FORMAT,
    POLICY_VALUE_CHECKPOINT_VERSION, REPRESENTATION_VERSION_V1,
};
use splendor_neural_search::NeuralIsmctsConfigV1;
use splendor_replay::record_random_game;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let checkpoint = fixture_checkpoint();
    let config = NeuralIsmctsConfigV1 {
        sample_seed: 20_260_811,
        simulations: 2,
        max_depth_turns: 1,
        puct_exploration_milli: 1_500,
        expected_checkpoint_hash: model_checkpoint_hash_v1(&checkpoint)?,
    };
    let (_, replay) = record_random_game(2, 42, 9)?;
    let mut trace = analyze_replay_neural_v1(&replay, &checkpoint, &config)?;
    trace.frames.truncate(1);
    trace.validate()?;

    let mut bytes = serde_json::to_vec_pretty(&trace)?;
    bytes.push(b'\n');
    let output =
        workspace_root().join("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json");
    fs::create_dir_all(output.parent().expect("fixture path has parent"))?;
    fs::write(&output, bytes)?;
    println!("wrote {}", output.display());
    Ok(())
}

fn workspace_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .expect("analysis crate is under workspace/crates")
        .to_path_buf()
}

fn fixture_checkpoint() -> PolicyValueCheckpointV1 {
    let hidden = 4usize;
    PolicyValueCheckpointV1 {
        format: POLICY_VALUE_CHECKPOINT_FORMAT.into(),
        version: POLICY_VALUE_CHECKPOINT_VERSION,
        model_id: "m14a-frontend-fixture-model".into(),
        representation_version: REPRESENTATION_VERSION_V1.into(),
        observation_features: OBSERVATION_FEATURES_V1 as u32,
        action_features: ACTION_FEATURES_V1 as u32,
        hidden_features: hidden as u32,
        max_players: MAX_PLAYERS_V1 as u8,
        source_dataset_id: "m14a-frontend-fixture-dataset".into(),
        source_dataset_hash: "11".repeat(32),
        league_manifest_hash: "22".repeat(32),
        evaluation_plan_hash: "33".repeat(32),
        evaluation_report_hash: "44".repeat(32),
        training_config_hash: "55".repeat(32),
        training_contract_version: None,
        search_teacher_targets_hash: None,
        model_architecture_version: None,
        optimizer_version: None,
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
            policy_hidden_bias: vec![],
            policy_output_weights: vec![],
            value_encoder_weights: vec![],
            value_encoder_bias: vec![],
        },
    }
}
