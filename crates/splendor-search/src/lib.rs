//! Deterministic perfect-information search over the referee-only `FullState`.
//!
//! This crate is a referee/offline library, not an agent projection. It sits
//! outside the Agent SDK information boundary on purpose: it consumes the
//! full `FullState` (deck order, blind reserves, phase, current player and
//! terminal result) that agents must never see.
//!
//! Design invariants (M06, frozen):
//! - Pure integers only: no floating point, no RNG, no wall clock, no threads,
//!   and no behavior that depends on hash-map iteration order.
//! - The input `FullState` is never mutated by any public entry point.
//! - Legal actions are always considered in the frozen canonical order defined
//!   by [`order`]; ties select the earlier canonical action.
//! - `StaticEvaluatorV1` weights and the terminal rank encoding are frozen at
//!   C1 acceptance and must not be tuned afterwards to pass benchmarks.
//!
//! Dependency discipline: `splendor-search -> splendor-core + splendor-catalog`
//! only. No dependency on protocol, replay, arena, agent, eval or cli.

mod config;
mod error;
mod evaluation;
mod model;
mod order;
mod search;

pub use config::{
    SearchConfigV1, MAX_SEARCH_DEPTH_TURNS, MAX_SEARCH_NODES, MIN_SEARCH_DEPTH_TURNS,
    MIN_SEARCH_NODES,
};
pub use error::SearchError;
pub use evaluation::{terminal_rank_base, StaticEvaluatorV1, TERMINAL_RANK_UNIT};
pub use model::{SearchResultV1, SearchStatsV1, SearchStopReasonV1};
pub use order::{canonical_order, canonical_sort, first_canonical_action, gems_tuple};
pub use search::search_maxn_v1;

/// Frozen public identity of the search algorithm family.
pub const SEARCH_ALGORITHM_ID: &str = "effective-splendor-maxn";

/// Frozen search model version.
pub const SEARCH_VERSION: u32 = 1;
