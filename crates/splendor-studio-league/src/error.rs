//! Errors raised by the Studio League layer.

use thiserror::Error;

/// Every failure mode of the Studio League layer.
#[derive(Debug, Error)]
pub enum StudioLeagueError {
    #[error("studio league database error: {0}")]
    Database(#[from] rusqlite::Error),
    #[error("studio league io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("studio league json error: {0}")]
    Json(#[from] serde_json::Error),
    /// A document claimed a shape the league refuses to interpret. Fail-closed:
    /// the caller must abort rather than import a partially-understood match.
    #[error("invalid studio league document: {0}")]
    Invalid(String),
    #[error("studio league record is missing {0}")]
    Missing(String),
    #[error("studio league rating config is invalid: {0}")]
    RatingConfig(String),
}

pub type Result<T> = std::result::Result<T, StudioLeagueError>;
