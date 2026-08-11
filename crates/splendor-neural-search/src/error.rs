use thiserror::Error;

#[derive(Debug, Error)]
pub enum NeuralSearchError {
    #[error("invalid M13 search config: {0}")]
    InvalidConfig(String),
    #[error("M12 checkpoint hash mismatch: expected {expected}, found {found}")]
    CheckpointMismatch { expected: String, found: String },
    #[error("information-set construction/sampling failed: {0}")]
    Belief(String),
    #[error("M12 inference failed: {0}")]
    Learning(String),
    #[error("engine transition failed: {0}")]
    Engine(String),
    #[error("information node exposed different legal actions across determinizations")]
    ActionAvailabilityMismatch,
    #[error("search root observation viewer is not the current player")]
    ViewerMismatch,
    #[error("non-terminal state has no legal actions")]
    NoLegalActions,
    #[error("value vector length {found} does not match player count {expected}")]
    InvalidValueShape { expected: usize, found: usize },
    #[error("model returned a non-finite or out-of-range probability/value")]
    InvalidModelOutput,
    #[error("search arithmetic overflow")]
    ArithmeticOverflow,
    #[error("tree identity serialization failed: {0}")]
    Serialization(String),
}
