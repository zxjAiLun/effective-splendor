use thiserror::Error;

#[derive(Debug, Error)]
pub enum IsmctsError {
    #[error("invalid ISMCTS config: {0}")]
    InvalidConfig(String),
    #[error("belief error: {0}")]
    Belief(String),
    #[error("search evaluation error: {0}")]
    Evaluation(String),
    #[error("engine error: {0}")]
    Engine(String),
    #[error("information-node serialization failed: {0}")]
    Serialization(String),
    #[error("information-set viewer is not the current player")]
    ViewerMismatch,
    #[error("non-terminal search node has no legal actions")]
    NoLegalActions,
    #[error("the same information-set node produced a different legal-action set")]
    ActionAvailabilityMismatch,
    #[error("utility vector length {found} does not match player count {expected}")]
    InvalidUtilityShape { expected: usize, found: usize },
    #[error("integer overflow while accumulating ISMCTS statistics")]
    ArithmeticOverflow,
}
