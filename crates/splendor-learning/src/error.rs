use thiserror::Error;

#[derive(Debug, Error)]
pub enum LearningError {
    #[error("invalid M12 training config: {0}")]
    InvalidConfig(String),
    #[error("invalid M11 training dataset: {0}")]
    InvalidDataset(String),
    #[error("invalid M12 checkpoint: {0}")]
    InvalidCheckpoint(String),
    #[error("invalid M12 formal result: {0}")]
    InvalidFormalResult(String),
    #[error("M12 serialization failed: {0}")]
    Serialization(String),
}

pub(crate) fn invalid_config(message: impl Into<String>) -> LearningError {
    LearningError::InvalidConfig(message.into())
}

pub(crate) fn invalid_dataset(message: impl Into<String>) -> LearningError {
    LearningError::InvalidDataset(message.into())
}

pub(crate) fn invalid_checkpoint(message: impl Into<String>) -> LearningError {
    LearningError::InvalidCheckpoint(message.into())
}

pub(crate) fn invalid_formal_result(message: impl Into<String>) -> LearningError {
    LearningError::InvalidFormalResult(message.into())
}
