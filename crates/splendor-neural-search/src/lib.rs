//! M13 neural-guided information-set search.
//!
//! Hidden worlds are sampled with the frozen M07 belief implementation. Tree
//! identity remains acting-player Observation plus visible simulated history,
//! while the accepted M12 model supplies legal-action priors and multiplayer
//! value bootstraps. No referee state is passed into model inference.

mod config;
mod error;
mod model;
mod player_view;
mod search;

pub use config::{
    NeuralAblationModeV1, NeuralIsmctsConfigV1, MAX_NEURAL_ISMCTS_DEPTH_TURNS,
    MAX_NEURAL_ISMCTS_SIMULATIONS, MAX_PUCT_EXPLORATION_MILLI,
};
pub use error::NeuralSearchError;
pub use model::{
    NeuralIsmctsActionStatsV1, NeuralIsmctsResultV1, NeuralIsmctsStatsV1, NEURAL_VALUE_SCALE_V1,
};
pub use player_view::{analyze_player_view_neural_ismcts_v1, PlayerViewNeuralIsmctsAnalysisV1};
pub use search::{search_neural_ismcts_ablation_v1, search_neural_ismcts_v1};

pub const NEURAL_ISMCTS_ALGORITHM_ID: &str = "effective-splendor-neural-ismcts";
pub const NEURAL_ISMCTS_VERSION: u32 = 1;
