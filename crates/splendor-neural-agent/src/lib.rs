//! Live player-view policy for M13 neural-guided ISMCTS v1.

use splendor_agent::{run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{Action, Ruleset};
use splendor_learning::{model_checkpoint_hash_v1, PolicyValueCheckpointV1, PolicyValueModelV1};
use splendor_neural_search::{
    analyze_player_view_neural_ismcts_v1, NeuralIsmctsConfigV1, NeuralSearchError,
};
use splendor_search::canonical_order;
use thiserror::Error;

pub const NEURAL_ISMCTS_AGENT_NAME: &str = "effective-splendor-neural-ismcts-agent-v1";
pub const NEURAL_ISMCTS_AGENT_VERSION: &str = "1";

#[derive(Debug, Clone)]
pub struct NeuralIsmctsAgentPolicyV1 {
    ruleset: Ruleset,
    model: PolicyValueModelV1,
    config: NeuralIsmctsConfigV1,
}

impl NeuralIsmctsAgentPolicyV1 {
    pub fn new(
        checkpoint: PolicyValueCheckpointV1,
        config: NeuralIsmctsConfigV1,
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
        })
    }

    pub fn config(&self) -> &NeuralIsmctsConfigV1 {
        &self.config
    }

    pub fn model(&self) -> &PolicyValueModelV1 {
        &self.model
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
}

impl AgentPolicy for NeuralIsmctsAgentPolicyV1 {
    type Error = NeuralIsmctsAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(NeuralIsmctsAgentError::RecipientViewerMismatch);
        }
        let analysis = analyze_player_view_neural_ismcts_v1(
            self.ruleset,
            &context.observation,
            context.visible_history,
            &self.model,
            &self.config,
        )?;
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
