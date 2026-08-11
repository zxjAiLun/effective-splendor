use serde::{Deserialize, Serialize};
use splendor_core::Action;

use crate::{NEURAL_ISMCTS_ALGORITHM_ID, NEURAL_ISMCTS_VERSION};

pub const NEURAL_VALUE_SCALE_V1: u32 = 1_000_000;

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
