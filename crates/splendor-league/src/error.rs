use thiserror::Error;

#[derive(Debug, Error)]
pub enum LeagueError {
    #[error("invalid league manifest: {0}")]
    InvalidManifest(String),
    #[error("invalid training dataset request: {0}")]
    InvalidDataset(String),
    #[error("evaluation plan is invalid: {0}")]
    InvalidEvaluationPlan(String),
    #[error("replay `{source_id}` failed verification: {message}")]
    ReplayVerification { source_id: String, message: String },
    #[error("duplicate replay source id `{0}`")]
    DuplicateReplaySource(String),
    #[error("arena/replay binding failed for `{source_id}`: {message}")]
    ArenaBinding { source_id: String, message: String },
    #[error("replay `{source_id}` cannot produce information set at ply {ply}: {message}")]
    InformationSet {
        source_id: String,
        ply: u32,
        message: String,
    },
    #[error("recorded action is not legal in replay `{source_id}` at ply {ply}")]
    RecordedActionNotLegal { source_id: String, ply: u32 },
    #[error("serialization failed: {0}")]
    Serialization(String),
}
