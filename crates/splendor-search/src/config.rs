use crate::error::SearchError;

/// Frozen lower bound for `max_depth_turns`.
pub const MIN_SEARCH_DEPTH_TURNS: u8 = 1;
/// Frozen upper bound for `max_depth_turns`.
pub const MAX_SEARCH_DEPTH_TURNS: u8 = 12;

/// Frozen lower bound for `max_nodes`.
pub const MIN_SEARCH_NODES: u64 = 1;
/// Frozen upper bound for `max_nodes`.
pub const MAX_SEARCH_NODES: u64 = 10_000_000;

/// Deterministic search configuration.
///
/// Depth is measured in completed player *turns*, not action plies. There is
/// deliberately no timeout, temperature, seed, thread count or floating-point
/// parameter: the same `(state, config)` pair must always produce the same
/// result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SearchConfigV1 {
    /// Maximum search depth in completed player turns.
    pub max_depth_turns: u8,
    /// Hard node budget across all iterative-deepening iterations.
    pub max_nodes: u64,
}

impl Default for SearchConfigV1 {
    fn default() -> Self {
        Self {
            max_depth_turns: 2,
            max_nodes: 50_000,
        }
    }
}

impl SearchConfigV1 {
    /// Validate this configuration against the frozen limits.
    pub fn validate(&self) -> Result<(), SearchError> {
        if self.max_depth_turns < MIN_SEARCH_DEPTH_TURNS {
            return Err(SearchError::InvalidConfig(format!(
                "max_depth_turns {} is below the minimum {}",
                self.max_depth_turns, MIN_SEARCH_DEPTH_TURNS
            )));
        }
        if self.max_depth_turns > MAX_SEARCH_DEPTH_TURNS {
            return Err(SearchError::InvalidConfig(format!(
                "max_depth_turns {} exceeds the maximum {}",
                self.max_depth_turns, MAX_SEARCH_DEPTH_TURNS
            )));
        }
        if self.max_nodes < MIN_SEARCH_NODES {
            return Err(SearchError::InvalidConfig(format!(
                "max_nodes {} is below the minimum {}",
                self.max_nodes, MIN_SEARCH_NODES
            )));
        }
        if self.max_nodes > MAX_SEARCH_NODES {
            return Err(SearchError::InvalidConfig(format!(
                "max_nodes {} exceeds the maximum {}",
                self.max_nodes, MAX_SEARCH_NODES
            )));
        }
        Ok(())
    }
}
