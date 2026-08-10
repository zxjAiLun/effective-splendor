use serde::{Deserialize, Serialize};
use splendor_core::Action;

use crate::{ISMCTS_ALGORITHM_ID, ISMCTS_VERSION};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IsmctsActionStatsV1 {
    pub action: Action,
    pub visits: u32,
    pub utility_sum_by_player: Vec<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IsmctsStatsV1 {
    pub simulations: u32,
    pub sampled_determinizations: u32,
    pub tree_nodes: u32,
    pub shared_node_hits: u32,
    pub root_visits: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IsmctsResultV1 {
    pub algorithm: String,
    pub version: u32,
    pub information_set_hash: String,
    pub action: Action,
    pub action_stats: Vec<IsmctsActionStatsV1>,
    pub stats: IsmctsStatsV1,
}

impl IsmctsResultV1 {
    pub(crate) fn new(
        information_set_hash: String,
        action: Action,
        action_stats: Vec<IsmctsActionStatsV1>,
        stats: IsmctsStatsV1,
    ) -> Self {
        Self {
            algorithm: ISMCTS_ALGORITHM_ID.to_string(),
            version: ISMCTS_VERSION,
            information_set_hash,
            action,
            action_stats,
            stats,
        }
    }
}
