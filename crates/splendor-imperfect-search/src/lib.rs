//! Deterministic root-determinization aggregation for imperfect information.
//!
//! This crate samples the hidden state behind one validated [`InformationSetV1`]
//! and evaluates every legal root action on every sampled `FullState`. The
//! sampled child is then handed to the frozen perfect-information MaxN search
//! from `splendor-search`, and the resulting utility vectors are summed in
//! integer arithmetic before one root action is selected.
//!
//! This is root determinization, not ISMCTS, POMCP, or a belief-tree search. It
//! is deliberately a small, reproducible baseline: the root action is shared
//! across samples, while the perfect-information continuation may see each
//! sample's hidden state. That makes the result a strategy-fusion-prone
//! baseline, not an optimal imperfect-information policy.
//!
//! Dependency discipline: `splendor-imperfect-search` depends only on the
//! belief, perfect-information search, and core layers. It does not depend on
//! replay, protocol, agent, arena, evaluation, or CLI crates.

mod config;
mod error;
mod model;
mod player_view;
mod search;

pub use config::{
    RootDeterminizationConfigV1, DEFAULT_SAMPLE_COUNT, MAX_SAMPLE_COUNT, MIN_SAMPLE_COUNT,
};
pub use error::{ImperfectSearchError, RootDeterminizationError};
pub use model::{RootActionAggregateV1, RootDeterminizationResultV1, RootDeterminizationStatsV1};
pub use player_view::{analyze_player_view_v1, PlayerViewRootAnalysisV1};
pub use search::{aggregate_root_determinizations_v1, search_root_determinizations_v1};
pub use splendor_belief::{DETERMINIZATION_VERSION, INFORMATION_SET_VERSION};

/// Frozen public identity of the root-determinization algorithm family.
pub const IMPERFECT_SEARCH_ALGORITHM_ID: &str = "effective-splendor-root-determinization-maxn";

/// Frozen public version of the root-determinization model.
pub const IMPERFECT_SEARCH_VERSION: u32 = 1;
