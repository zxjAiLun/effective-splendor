//! M10 deterministic information-set Monte Carlo tree search.
//!
//! Each simulation samples one referee world from the root information set,
//! but tree identity is derived only from the acting player's `Observation`
//! plus that player's visible simulated history from the root. Consequently
//! indistinguishable future states share one action policy across
//! determinizations instead of receiving separate perfect-information plans.

mod config;
mod error;
mod model;
mod player_view;
mod search;

pub use config::{
    IsmctsConfigV1, MAX_EXPLORATION_BIAS, MAX_ISMCTS_DEPTH_TURNS, MAX_ISMCTS_SIMULATIONS,
};
pub use error::IsmctsError;
pub use model::{IsmctsActionStatsV1, IsmctsResultV1, IsmctsStatsV1};
pub use player_view::{analyze_player_view_ismcts_v1, PlayerViewIsmctsAnalysisV1};
pub use search::search_ismcts_v1;

pub const ISMCTS_ALGORITHM_ID: &str = "effective-splendor-ismcts";
pub const ISMCTS_VERSION: u32 = 1;
