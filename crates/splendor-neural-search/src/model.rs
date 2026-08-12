use serde::{Deserialize, Serialize};
use splendor_core::{Action, Observation};
use splendor_learning::{model_checkpoint_hash_v1, PolicyValueModelV1, PolicyValuePredictionV1};

use crate::{NeuralSearchError, NEURAL_ISMCTS_ALGORITHM_ID, NEURAL_ISMCTS_VERSION};

pub const NEURAL_VALUE_SCALE_V1: u32 = 1_000_000;

/// Player-view-only Policy/Value boundary used by neural ISMCTS.
///
/// Implementations may be the accepted in-process M12 model or a persistent
/// GPU inference bridge. Values must be returned in absolute seat order even
/// when the underlying model is viewer-relative.
pub trait PolicyValueEvaluatorV1 {
    fn model_id(&self) -> &str;
    fn checkpoint_hash(&self) -> Result<String, NeuralSearchError>;
    fn predict(
        &self,
        observation: &Observation,
        legal_actions: &[Action],
    ) -> Result<PolicyValuePredictionV1, NeuralSearchError>;
}

impl PolicyValueEvaluatorV1 for PolicyValueModelV1 {
    fn model_id(&self) -> &str {
        &self.checkpoint().model_id
    }

    fn checkpoint_hash(&self) -> Result<String, NeuralSearchError> {
        model_checkpoint_hash_v1(self.checkpoint())
            .map_err(|error| NeuralSearchError::Learning(error.to_string()))
    }

    fn predict(
        &self,
        observation: &Observation,
        legal_actions: &[Action],
    ) -> Result<PolicyValuePredictionV1, NeuralSearchError> {
        PolicyValueModelV1::predict(self, observation, legal_actions)
            .map_err(|error| NeuralSearchError::Learning(error.to_string()))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuralIsmctsActionStatsV1 {
    pub action: Action,
    pub prior_micros: u32,
    pub visits: u32,
    pub value_sum_by_player: Vec<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuralIsmctsStatsV1 {
    pub simulations: u32,
    pub sampled_determinizations: u32,
    pub tree_nodes: u32,
    pub shared_node_hits: u32,
    pub root_visits: u32,
    pub model_evaluations: u32,
    pub terminal_evaluations: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuralIsmctsResultV1 {
    pub algorithm: String,
    pub version: u32,
    pub information_set_hash: String,
    pub model_id: String,
    pub checkpoint_hash: String,
    pub action: Action,
    pub action_stats: Vec<NeuralIsmctsActionStatsV1>,
    pub stats: NeuralIsmctsStatsV1,
}

impl NeuralIsmctsResultV1 {
    pub(crate) fn new(
        information_set_hash: String,
        model_id: String,
        checkpoint_hash: String,
        action: Action,
        action_stats: Vec<NeuralIsmctsActionStatsV1>,
        stats: NeuralIsmctsStatsV1,
    ) -> Self {
        Self {
            algorithm: NEURAL_ISMCTS_ALGORITHM_ID.into(),
            version: NEURAL_ISMCTS_VERSION,
            information_set_hash,
            model_id,
            checkpoint_hash,
            action,
            action_stats,
            stats,
        }
    }
}
