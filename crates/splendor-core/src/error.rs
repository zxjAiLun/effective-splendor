use thiserror::Error;

use crate::action::Action;

pub type EngineResult<T> = Result<T, EngineError>;

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum EngineError {
    #[error("invalid player count: {0} (must be 2–4)")]
    InvalidPlayerCount(u8),

    #[error("game is already over")]
    GameOver,

    #[error("not this player's turn")]
    NotYourTurn,

    #[error("action not legal in current phase: {0:?}")]
    WrongPhase(Action),

    #[error("illegal action: {0}")]
    IllegalAction(String),

    #[error("internal invariant broken: {0}")]
    Invariant(String),
}
