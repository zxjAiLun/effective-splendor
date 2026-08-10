//! M11 self-play league and traceable player-view dataset contracts.

mod dataset;
mod error;
mod manifest;

pub use dataset::{
    build_training_dataset_v1, training_dataset_hash_v1, DatasetReplaySourceV1,
    TrainingAgentIdentityV1, TrainingDatasetV1, TrainingExampleV1, TrainingReplayV1,
    TRAINING_DATASET_FORMAT, TRAINING_DATASET_VERSION,
};
pub use error::LeagueError;
pub use manifest::{
    league_manifest_hash_v1, LeagueAgentV1, LeagueManifestV1, LeagueRoleV1, LEAGUE_MANIFEST_FORMAT,
    LEAGUE_VERSION,
};
