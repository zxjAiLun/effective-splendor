//! M12 supervised player-view policy + multiplayer vector-value baseline.
//!
//! This crate deliberately stops at representation, offline supervised
//! training, checkpointing, inference, and held-out evaluation. It does not
//! connect the learned model to M07/M10 search and never accepts `FullState`.

mod error;
mod formal_result;
mod model;
mod representation;
mod training;

pub use error::LearningError;
pub use formal_result::{
    FormalPolicyValueResultV1, FORMAL_POLICY_VALUE_RESULT_FORMAT,
    FORMAL_POLICY_VALUE_RESULT_VERSION,
};
pub use model::{
    model_checkpoint_hash_v1, ModelParametersV1, PolicyActionProbabilityV1,
    PolicyValueCheckpointV1, PolicyValueModelV1, PolicyValuePredictionV1,
    POLICY_VALUE_CHECKPOINT_FORMAT, POLICY_VALUE_CHECKPOINT_VERSION,
};
pub use representation::{
    encode_action_v1, encode_observation_v1, ACTION_FEATURES_V1, MAX_PLAYERS_V1,
    OBSERVATION_FEATURES_V1, REPRESENTATION_VERSION_V1,
};
pub use training::{
    evaluate_checkpoint_v1, evaluate_checkpoint_with_config_v1, train_policy_value_v1,
    training_config_hash_v1, DatasetIdentityV1, DatasetSplitV1, HeadDatasetSplitV1,
    HeadOfflineMetricsV1, MaterialOfflineGateV1, MetricComparisonV1, OfflineEvaluationReportV1,
    OfflineMetricsV1, PolicyValueTrainingConfigV1, PolicyValueTrainingReportV1, TrainingOutcomeV1,
    OFFLINE_EVALUATION_FORMAT, OFFLINE_EVALUATION_VERSION, POLICY_VALUE_TRAINING_CONFIG_FORMAT,
    POLICY_VALUE_TRAINING_CONFIG_VERSION, POLICY_VALUE_TRAINING_REPORT_FORMAT,
    POLICY_VALUE_TRAINING_REPORT_VERSION,
};
