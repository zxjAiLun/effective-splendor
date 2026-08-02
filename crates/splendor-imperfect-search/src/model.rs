use serde::{Deserialize, Serialize};
use splendor_core::{Action, PlayerId};

/// Utility totals for one root action over all sampled determinizations.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootActionAggregateV1 {
    /// Root action in the frozen canonical order.
    pub action: Action,
    /// Checked sum of continuation utilities in player-ID order.
    pub utility_sum_by_player: Vec<i64>,
}

/// Aggregate execution counters for one root-determinization call.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootDeterminizationStatsV1 {
    /// Number of sampled determinizations evaluated.
    pub samples: u16,
    /// Number of distinct legal root actions.
    pub root_actions: u32,
    /// Number of non-terminal sampled root children sent to MaxN.
    pub continuation_searches: u64,
    /// Number of terminal sampled root children evaluated statically.
    pub terminal_children: u64,
    /// Sum of continuation `nodes_visited` counters.
    pub nodes_visited: u64,
    /// Sum of continuation `nodes_expanded` counters.
    pub nodes_expanded: u64,
    /// Sum of continuation `leaf_evaluations` counters.
    pub leaf_evaluations: u64,
    /// Sum of continuation `transposition_hits` counters.
    pub transposition_hits: u64,
}

/// Public result of root-determinization aggregation.
///
/// This result intentionally contains no sampled `FullState`, deck order,
/// blind-reserved `CardId`, per-sample hash, or principal variation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootDeterminizationResultV1 {
    /// Selected root action, legal in every sampled root state.
    pub action: Action,
    /// Player whose utility component selects the root action.
    pub root_player: PlayerId,
    /// Seed used for the deterministic sample stream.
    pub sample_seed: u64,
    /// Number of samples used for every action aggregate.
    pub sample_count: u16,
    /// Canonically ordered action aggregates.
    pub action_aggregates: Vec<RootActionAggregateV1>,
    /// Checked aggregate counters.
    pub stats: RootDeterminizationStatsV1,
}
