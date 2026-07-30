use serde::{Deserialize, Serialize};
use splendor_core::{Action, PlayerId};

/// Why the search stopped.
///
/// Serialized with stable snake_case tags (`depth_limit_reached`,
/// `node_budget_reached`) for artifact use.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchStopReasonV1 {
    /// Every iteration up to `max_depth_turns` completed within budget.
    DepthLimitReached,
    /// The hard node budget was exhausted before the final depth completed.
    NodeBudgetReached,
}

/// Deterministic search statistics.
///
/// Frozen counting semantics:
/// - Every entry into a recursion node consumes one `nodes_visited` first;
///   a transposition hit still counts as a visit.
/// - `nodes_visited` never exceeds the configured `max_nodes`.
/// - `nodes_expanded` increments only when a node actually enumerates its
///   children (not terminal, not a depth cutoff, not a transposition hit).
/// - `leaf_evaluations` increments for every static/terminal evaluation at a
///   terminal node or depth cutoff.
/// - The transposition table stores only fully solved exact entries; partial
///   subtrees interrupted by the budget are never cached.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchStatsV1 {
    pub nodes_visited: u64,
    pub nodes_expanded: u64,
    pub leaf_evaluations: u64,
    pub transposition_hits: u64,
    /// Number of *unique* exact-TT entries in the current search context.
    ///
    /// Equals the live transposition-table length (`tt.len()`): the value is
    /// re-synced from the table after every store, so it counts distinct cached
    /// nodes rather than cumulative insert calls. A re-insert of an existing key
    /// (replacement) must not inflate this counter.
    pub transposition_entries: u64,
}

/// Result of a deterministic MaxN search from a non-terminal root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchResultV1 {
    /// Chosen root action; always a member of the root's `legal_actions()`.
    pub action: Action,
    /// The player to move at the root.
    pub root_player: PlayerId,
    /// Depth (in completed player turns) of the last fully completed
    /// iterative-deepening iteration; 0 if not even depth 1 completed.
    pub completed_depth_turns: u8,
    /// MaxN utility vector in seat/player-ID order;
    /// length equals `state.player_count()`.
    pub utility_by_player: Vec<i64>,
    /// Principal variation from the root; may contain more actions than
    /// `completed_depth_turns` because a turn can span multiple actions.
    pub principal_variation: Vec<Action>,
    pub stop_reason: SearchStopReasonV1,
    pub stats: SearchStatsV1,
}
