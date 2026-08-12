//! Live player-view policy for M13 neural-guided ISMCTS v1.

use serde::{Deserialize, Serialize};
use splendor_agent::{run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_belief::build_information_set_v1;
use splendor_core::{Action, Observation, Ruleset};
use splendor_learning::{
    model_checkpoint_hash_v1, PolicyValueCheckpointV1, PolicyValueModelV1, PolicyValuePredictionV1,
};
use splendor_neural_search::{
    analyze_player_view_neural_ismcts_ablation_v1, analyze_player_view_neural_ismcts_v1,
    search_neural_ismcts_with_evaluator_v1, NeuralAblationModeV1, NeuralIsmctsConfigV1,
    NeuralSearchError, PolicyValueEvaluatorV1,
};
use splendor_search::canonical_order;
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;
use thiserror::Error;

pub const NEURAL_ISMCTS_AGENT_NAME: &str = "effective-splendor-neural-ismcts-agent-v1";
pub const NEURAL_ISMCTS_AGENT_VERSION: &str = "1";
pub const NEURAL_ISMCTS_ABLATION_AGENT_NAME: &str =
    "effective-splendor-neural-ismcts-ablation-agent-v1";
pub const GPU_NEURAL_ISMCTS_AGENT_NAME: &str = "effective-splendor-gpu-neural-ismcts-agent-v1";

#[derive(Debug, Clone)]
pub struct GpuInferenceConfigV1 {
    pub python: PathBuf,
    pub module_root: PathBuf,
    pub checkpoint: PathBuf,
    pub checkpoint_hash: String,
    pub catalog: PathBuf,
    pub device: String,
}

struct GpuProcess {
    child: Child,
    input: BufWriter<ChildStdin>,
    output: BufReader<ChildStdout>,
    next_request_id: u64,
}

pub struct GpuPolicyValueEvaluatorV1 {
    model_id: String,
    checkpoint_hash: String,
    process: Mutex<GpuProcess>,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum InferenceResponse {
    Ready {
        version: u32,
        model_id: String,
        checkpoint_hash: String,
        value_order: String,
        device: String,
    },
    Prediction {
        version: u32,
        request_id: u64,
        policy: Vec<splendor_learning::PolicyActionProbabilityV1>,
        value_by_player: Vec<f32>,
    },
}

#[derive(Serialize)]
struct InferenceRequest<'a> {
    #[serde(rename = "type")]
    kind: &'static str,
    version: u32,
    request_id: u64,
    observation: &'a Observation,
    legal_actions: &'a [Action],
}

impl GpuPolicyValueEvaluatorV1 {
    pub fn spawn(config: &GpuInferenceConfigV1) -> Result<Self, NeuralIsmctsAgentError> {
        validate_lower_hash(&config.checkpoint_hash)?;
        if config.device != "cpu" && config.device != "cuda" {
            return Err(NeuralIsmctsAgentError::GpuInference(
                "device must be cpu or cuda".into(),
            ));
        }
        let checkpoint = absolute_path(&config.checkpoint)?;
        let catalog = absolute_path(&config.catalog)?;
        let mut child = Command::new(&config.python)
            .current_dir(&config.module_root)
            .arg("-m")
            .arg("splendor_gpu.inference")
            .arg("--checkpoint")
            .arg(checkpoint)
            .arg("--checkpoint-hash")
            .arg(&config.checkpoint_hash)
            .arg("--catalog")
            .arg(catalog)
            .arg("--device")
            .arg(&config.device)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| NeuralIsmctsAgentError::GpuInference(error.to_string()))?;
        let input = child.stdin.take().ok_or_else(|| {
            NeuralIsmctsAgentError::GpuInference("inference stdin unavailable".into())
        })?;
        let output = child.stdout.take().ok_or_else(|| {
            NeuralIsmctsAgentError::GpuInference("inference stdout unavailable".into())
        })?;
        let mut process = GpuProcess {
            child,
            input: BufWriter::new(input),
            output: BufReader::new(output),
            next_request_id: 1,
        };
        let ready = read_inference_response(&mut process.output)?;
        let (model_id, found_hash) = match ready {
            InferenceResponse::Ready {
                version,
                model_id,
                checkpoint_hash,
                value_order,
                device,
            } if version == 1 && value_order == "absolute_seat" && device == config.device => {
                (model_id, checkpoint_hash)
            }
            _ => {
                return Err(NeuralIsmctsAgentError::GpuInference(
                    "invalid inference readiness response".into(),
                ))
            }
        };
        if found_hash != config.checkpoint_hash {
            return Err(NeuralSearchError::CheckpointMismatch {
                expected: config.checkpoint_hash.clone(),
                found: found_hash,
            }
            .into());
        }
        Ok(Self {
            model_id,
            checkpoint_hash: config.checkpoint_hash.clone(),
            process: Mutex::new(process),
        })
    }
}

impl PolicyValueEvaluatorV1 for GpuPolicyValueEvaluatorV1 {
    fn model_id(&self) -> &str {
        &self.model_id
    }

    fn checkpoint_hash(&self) -> Result<String, NeuralSearchError> {
        Ok(self.checkpoint_hash.clone())
    }

    fn predict(
        &self,
        observation: &Observation,
        legal_actions: &[Action],
    ) -> Result<PolicyValuePredictionV1, NeuralSearchError> {
        let mut process = self
            .process
            .lock()
            .map_err(|_| NeuralSearchError::Learning("GPU inference lock poisoned".into()))?;
        let request_id = process.next_request_id;
        process.next_request_id = request_id
            .checked_add(1)
            .ok_or(NeuralSearchError::ArithmeticOverflow)?;
        serde_json::to_writer(
            &mut process.input,
            &InferenceRequest {
                kind: "predict",
                version: 1,
                request_id,
                observation,
                legal_actions,
            },
        )
        .map_err(|error| NeuralSearchError::Learning(error.to_string()))?;
        process
            .input
            .write_all(b"\n")
            .and_then(|_| process.input.flush())
            .map_err(|error| NeuralSearchError::Learning(error.to_string()))?;
        match read_inference_response(&mut process.output)
            .map_err(|error| NeuralSearchError::Learning(error.to_string()))?
        {
            InferenceResponse::Prediction {
                version,
                request_id: response_id,
                policy,
                value_by_player,
            } if version == 1 && response_id == request_id => Ok(PolicyValuePredictionV1 {
                policy,
                value_by_player,
            }),
            _ => Err(NeuralSearchError::Learning(
                "invalid GPU inference prediction response".into(),
            )),
        }
    }
}

impl Drop for GpuPolicyValueEvaluatorV1 {
    fn drop(&mut self) {
        if let Ok(process) = self.process.get_mut() {
            let _ = process.child.kill();
            let _ = process.child.wait();
        }
    }
}

pub struct GpuNeuralIsmctsAgentPolicyV1 {
    ruleset: Ruleset,
    evaluator: GpuPolicyValueEvaluatorV1,
    config: NeuralIsmctsConfigV1,
}

impl GpuNeuralIsmctsAgentPolicyV1 {
    pub fn new(
        inference: GpuInferenceConfigV1,
        config: NeuralIsmctsConfigV1,
    ) -> Result<Self, NeuralIsmctsAgentError> {
        config.validate()?;
        let evaluator = GpuPolicyValueEvaluatorV1::spawn(&inference)?;
        if evaluator.checkpoint_hash != config.expected_checkpoint_hash {
            return Err(NeuralSearchError::CheckpointMismatch {
                expected: config.expected_checkpoint_hash,
                found: evaluator.checkpoint_hash.clone(),
            }
            .into());
        }
        Ok(Self {
            ruleset: Ruleset::base_v1(),
            evaluator,
            config,
        })
    }
}

impl AgentPolicy for GpuNeuralIsmctsAgentPolicyV1 {
    type Error = NeuralIsmctsAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(NeuralIsmctsAgentError::RecipientViewerMismatch);
        }
        let information_set =
            build_information_set_v1(self.ruleset, &context.observation, context.visible_history)
                .map_err(|error| NeuralSearchError::Belief(error.to_string()))?;
        let result = search_neural_ismcts_with_evaluator_v1(
            &information_set,
            &self.evaluator,
            &self.config,
        )?;
        let search_actions = result
            .action_stats
            .iter()
            .map(|stats| stats.action)
            .collect::<Vec<_>>();
        if canonical_order(context.legal_actions) != search_actions {
            return Err(NeuralIsmctsAgentError::LegalActionSetMismatch);
        }
        Ok(result.action)
    }
}

fn validate_lower_hash(value: &str) -> Result<(), NeuralIsmctsAgentError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(NeuralIsmctsAgentError::GpuInference(
            "checkpoint hash is not lowercase SHA-256".into(),
        ));
    }
    Ok(())
}

fn absolute_path(path: &Path) -> Result<PathBuf, NeuralIsmctsAgentError> {
    std::fs::canonicalize(path)
        .map_err(|error| NeuralIsmctsAgentError::GpuInference(error.to_string()))
}

fn read_inference_response(
    output: &mut BufReader<ChildStdout>,
) -> Result<InferenceResponse, NeuralIsmctsAgentError> {
    let mut line = String::new();
    if output
        .read_line(&mut line)
        .map_err(|error| NeuralIsmctsAgentError::GpuInference(error.to_string()))?
        == 0
    {
        return Err(NeuralIsmctsAgentError::GpuInference(
            "GPU inference process closed stdout".into(),
        ));
    }
    serde_json::from_str(&line)
        .map_err(|error| NeuralIsmctsAgentError::GpuInference(error.to_string()))
}

#[derive(Debug, Clone)]
pub struct NeuralIsmctsAgentPolicyV1 {
    ruleset: Ruleset,
    model: PolicyValueModelV1,
    config: NeuralIsmctsConfigV1,
    mode: NeuralAblationModeV1,
}

impl NeuralIsmctsAgentPolicyV1 {
    pub fn new(
        checkpoint: PolicyValueCheckpointV1,
        config: NeuralIsmctsConfigV1,
    ) -> Result<Self, NeuralIsmctsAgentError> {
        Self::new_with_mode(checkpoint, config, NeuralAblationModeV1::Full)
    }

    pub fn new_ablation(
        checkpoint: PolicyValueCheckpointV1,
        config: NeuralIsmctsConfigV1,
        mode: NeuralAblationModeV1,
    ) -> Result<Self, NeuralIsmctsAgentError> {
        if mode == NeuralAblationModeV1::Full {
            return Err(NeuralIsmctsAgentError::InvalidAblationMode);
        }
        Self::new_with_mode(checkpoint, config, mode)
    }

    fn new_with_mode(
        checkpoint: PolicyValueCheckpointV1,
        config: NeuralIsmctsConfigV1,
        mode: NeuralAblationModeV1,
    ) -> Result<Self, NeuralIsmctsAgentError> {
        config.validate()?;
        let checkpoint_hash = model_checkpoint_hash_v1(&checkpoint)
            .map_err(|error| NeuralIsmctsAgentError::Checkpoint(error.to_string()))?;
        if checkpoint_hash != config.expected_checkpoint_hash {
            return Err(NeuralSearchError::CheckpointMismatch {
                expected: config.expected_checkpoint_hash,
                found: checkpoint_hash,
            }
            .into());
        }
        let model = PolicyValueModelV1::from_checkpoint(checkpoint)
            .map_err(|error| NeuralIsmctsAgentError::Checkpoint(error.to_string()))?;
        Ok(Self {
            ruleset: Ruleset::base_v1(),
            model,
            config,
            mode,
        })
    }

    pub fn config(&self) -> &NeuralIsmctsConfigV1 {
        &self.config
    }

    pub fn model(&self) -> &PolicyValueModelV1 {
        &self.model
    }

    pub fn mode(&self) -> NeuralAblationModeV1 {
        self.mode
    }
}

#[derive(Debug, Error)]
pub enum NeuralIsmctsAgentError {
    #[error(transparent)]
    Search(#[from] NeuralSearchError),
    #[error("invalid M12 checkpoint: {0}")]
    Checkpoint(String),
    #[error("request recipient does not match observation viewer")]
    RecipientViewerMismatch,
    #[error("server-certified legal actions do not match the neural search root")]
    LegalActionSetMismatch,
    #[error("live ablation agent requires a non-full diagnostic mode")]
    InvalidAblationMode,
    #[error("GPU inference bridge failed: {0}")]
    GpuInference(String),
}

impl AgentPolicy for NeuralIsmctsAgentPolicyV1 {
    type Error = NeuralIsmctsAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(NeuralIsmctsAgentError::RecipientViewerMismatch);
        }
        let analysis = if self.mode == NeuralAblationModeV1::Full {
            analyze_player_view_neural_ismcts_v1(
                self.ruleset,
                &context.observation,
                context.visible_history,
                &self.model,
                &self.config,
            )?
        } else {
            analyze_player_view_neural_ismcts_ablation_v1(
                self.ruleset,
                &context.observation,
                context.visible_history,
                &self.model,
                &self.config,
                self.mode,
            )?
        };
        let search_actions = analysis
            .result()
            .action_stats
            .iter()
            .map(|stats| stats.action)
            .collect::<Vec<_>>();
        if canonical_order(context.legal_actions) != search_actions {
            return Err(NeuralIsmctsAgentError::LegalActionSetMismatch);
        }
        Ok(analysis.result().action)
    }
}

pub fn run_neural_ismcts_ablation_agent_v1<R, W, E>(
    input: R,
    output: W,
    diagnostics: E,
    checkpoint: PolicyValueCheckpointV1,
    config: NeuralIsmctsConfigV1,
    mode: NeuralAblationModeV1,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = NeuralIsmctsAgentPolicyV1::new_ablation(checkpoint, config, mode)
        .map_err(|error| AgentError::Policy(error.to_string()))?;
    run_agent(
        input,
        output,
        diagnostics,
        AgentIdentity {
            name: NEURAL_ISMCTS_ABLATION_AGENT_NAME,
            version: NEURAL_ISMCTS_AGENT_VERSION,
        },
        0,
        policy,
    )
}

pub fn run_neural_ismcts_agent_v1<R, W, E>(
    input: R,
    output: W,
    diagnostics: E,
    checkpoint: PolicyValueCheckpointV1,
    config: NeuralIsmctsConfigV1,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = NeuralIsmctsAgentPolicyV1::new(checkpoint, config)
        .map_err(|error| AgentError::Policy(error.to_string()))?;
    run_agent(
        input,
        output,
        diagnostics,
        AgentIdentity {
            name: NEURAL_ISMCTS_AGENT_NAME,
            version: NEURAL_ISMCTS_AGENT_VERSION,
        },
        0,
        policy,
    )
}

pub fn run_gpu_neural_ismcts_agent_v1<R, W, E>(
    input: R,
    output: W,
    diagnostics: E,
    inference: GpuInferenceConfigV1,
    config: NeuralIsmctsConfigV1,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = GpuNeuralIsmctsAgentPolicyV1::new(inference, config)
        .map_err(|error| AgentError::Policy(error.to_string()))?;
    run_agent(
        input,
        output,
        diagnostics,
        AgentIdentity {
            name: GPU_NEURAL_ISMCTS_AGENT_NAME,
            version: NEURAL_ISMCTS_AGENT_VERSION,
        },
        0,
        policy,
    )
}

#[cfg(test)]
mod tests {
    use splendor_agent::{PublicRequestMeta, StableRng};
    use splendor_core::{
        observation_hash, visible_events, Audience, FullState, GameConfig, PlayerId,
    };
    use splendor_learning::{
        model_checkpoint_hash_v1, ModelParametersV1, ACTION_FEATURES_V1, MAX_PLAYERS_V1,
        OBSERVATION_FEATURES_V1, POLICY_VALUE_CHECKPOINT_FORMAT, POLICY_VALUE_CHECKPOINT_VERSION,
        REPRESENTATION_VERSION_V1,
    };

    use super::*;

    fn checkpoint() -> PolicyValueCheckpointV1 {
        let hidden = 4usize;
        PolicyValueCheckpointV1 {
            format: POLICY_VALUE_CHECKPOINT_FORMAT.into(),
            version: POLICY_VALUE_CHECKPOINT_VERSION,
            model_id: "m13-agent-test-model".into(),
            representation_version: REPRESENTATION_VERSION_V1.into(),
            observation_features: OBSERVATION_FEATURES_V1 as u32,
            action_features: ACTION_FEATURES_V1 as u32,
            hidden_features: hidden as u32,
            max_players: MAX_PLAYERS_V1 as u8,
            source_dataset_id: "m13-agent-test-dataset".into(),
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

    fn config(checkpoint: &PolicyValueCheckpointV1) -> NeuralIsmctsConfigV1 {
        NeuralIsmctsConfigV1 {
            sample_seed: 23,
            simulations: 8,
            max_depth_turns: 1,
            puct_exploration_milli: 1_500,
            expected_checkpoint_hash: model_checkpoint_hash_v1(checkpoint).unwrap(),
        }
    }

    #[test]
    fn policy_returns_a_server_certified_legal_action() {
        let (state, setup) = FullState::new(GameConfig::default()).unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = state.legal_actions();
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: "m13-agent-test".into(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };
        let checkpoint = checkpoint();
        let action = NeuralIsmctsAgentPolicyV1::new(checkpoint.clone(), config(&checkpoint))
            .unwrap()
            .choose_action(context)
            .unwrap();
        assert!(legal.contains(&action));
    }

    #[test]
    fn policy_only_control_returns_a_server_certified_legal_action() {
        let (state, setup) = FullState::new(GameConfig::default()).unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = state.legal_actions();
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: "m15-policy-only-agent-test".into(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };
        let checkpoint = checkpoint();
        let mut policy = NeuralIsmctsAgentPolicyV1::new_ablation(
            checkpoint.clone(),
            config(&checkpoint),
            NeuralAblationModeV1::PolicyOnly,
        )
        .unwrap();
        assert_eq!(policy.mode(), NeuralAblationModeV1::PolicyOnly);
        let action = policy.choose_action(context).unwrap();
        assert!(legal.contains(&action));
    }

    #[test]
    fn ablation_agent_rejects_full_mode() {
        let checkpoint = checkpoint();
        assert!(matches!(
            NeuralIsmctsAgentPolicyV1::new_ablation(
                checkpoint.clone(),
                config(&checkpoint),
                NeuralAblationModeV1::Full,
            ),
            Err(NeuralIsmctsAgentError::InvalidAblationMode)
        ));
    }

    #[test]
    fn policy_fails_closed_on_legal_set_mismatch() {
        let (state, setup) = FullState::new(GameConfig::default()).unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &[Action::Pass],
            meta: PublicRequestMeta {
                game_id: "m13-agent-mismatch".into(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };
        let checkpoint = checkpoint();
        assert!(matches!(
            NeuralIsmctsAgentPolicyV1::new(checkpoint.clone(), config(&checkpoint))
                .unwrap()
                .choose_action(context),
            Err(NeuralIsmctsAgentError::LegalActionSetMismatch)
        ));
    }

    #[test]
    fn policy_rejects_checkpoint_mismatch_before_runtime_start() {
        let checkpoint = checkpoint();
        let mut config = config(&checkpoint);
        config.expected_checkpoint_hash = "00".repeat(32);
        assert!(matches!(
            NeuralIsmctsAgentPolicyV1::new(checkpoint, config),
            Err(NeuralIsmctsAgentError::Search(
                NeuralSearchError::CheckpointMismatch { .. }
            ))
        ));
    }
}
