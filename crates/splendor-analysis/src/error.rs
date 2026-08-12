use thiserror::Error;

#[derive(Debug, Error)]
pub enum AnalysisError {
    #[error("replay verification failed: {0}")]
    Replay(String),
    #[error("M12 checkpoint/model failed: {0}")]
    Learning(String),
    #[error("M13 neural analysis failed at ply {ply}: {message}")]
    Neural { ply: u32, message: String },
    #[error("verified replay binding failed at ply {ply}: {message}")]
    Binding { ply: u32, message: String },
    #[error("analysis arithmetic overflow")]
    ArithmeticOverflow,
    #[error("invalid analysis trace: {0}")]
    InvalidTrace(String),
    #[error("analysis serialization failed: {0}")]
    Serialization(String),
    #[error("evaluation provenance failed: {0}")]
    Evaluation(String),
    #[error("invalid evaluation diagnostic: {0}")]
    InvalidDiagnostic(String),
    #[error("search-teacher target generation failed: {0}")]
    TeacherTarget(String),
}
