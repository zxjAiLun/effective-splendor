use splendor_core::{Action, EngineError, PlayerId};
use thiserror::Error;

pub type ReplayResult<T> = Result<T, ReplayError>;

/// Every replay failure carries enough context (usually the exact `ply`) to
/// locate the divergence. `verify_replay` never returns a bare "mismatch".
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum ReplayError {
    #[error("unexpected replay format {found:?}, expected {expected:?}")]
    WrongFormat { expected: String, found: String },

    #[error("unsupported replay version {found}, this verifier supports {supported}")]
    UnsupportedVersion { supported: u32, found: u32 },

    #[error("engine version mismatch: replay {recorded:?}, verifier {current:?}")]
    EngineVersionMismatch { current: String, recorded: String },

    #[error("catalog version mismatch: replay {recorded:?}, engine {current:?}")]
    CatalogVersionMismatch { current: String, recorded: String },

    #[error("unsupported ruleset {0:?}")]
    UnsupportedRuleset(String),

    #[error("ruleset parameter mismatch: {field} replay={recorded} engine={current}")]
    RulesetParameterMismatch {
        field: &'static str,
        current: String,
        recorded: String,
    },

    #[error("ruleset fingerprint mismatch: replay {recorded:?}, engine {current:?}")]
    RulesetFingerprintMismatch { current: String, recorded: String },

    #[error("player count {recorded} is out of range [{min}, {max}]")]
    InvalidPlayerCount { recorded: u8, min: u8, max: u8 },

    #[error("player count mismatch: replay {recorded}, rebuilt {rebuilt}")]
    PlayerCountMismatch { recorded: u8, rebuilt: u8 },

    #[error("initial state hash mismatch: replay {expected:?}, rebuilt {actual:?}")]
    InitialHashMismatch { expected: String, actual: String },

    #[error("ply {ply} is out of order (expected {expected})")]
    NonContiguousPly { ply: u32, expected: u32 },

    #[error("step {ply} runs after the game already ended")]
    StepAfterTerminal { ply: u32 },

    #[error("step {ply} actor mismatch: expected {expected:?}, recorded {recorded:?}")]
    ActorMismatch {
        ply: u32,
        expected: PlayerId,
        recorded: PlayerId,
    },

    #[error("step {ply} before-hash mismatch: expected {expected:?}, actual {actual:?}")]
    BeforeHashMismatch {
        ply: u32,
        expected: String,
        actual: String,
    },

    #[error("step {ply} action {action:?} is not legal: {source}")]
    IllegalAction {
        ply: u32,
        action: Action,
        source: EngineError,
    },

    #[error("step {ply} broke an invariant after apply: {source}")]
    InvariantBroken { ply: u32, source: EngineError },

    #[error("step {ply} after-hash mismatch: expected {expected:?}, actual {actual:?}")]
    AfterHashMismatch {
        ply: u32,
        expected: String,
        actual: String,
    },

    #[error("replay ended before the game reached a terminal state (after {plies} plies)")]
    NotTerminal { plies: u32 },

    #[error("final state hash mismatch: replay {expected:?}, actual {actual:?}")]
    FinalHashMismatch { expected: String, actual: String },

    #[error("final result mismatch between replay and re-run engine")]
    ResultMismatch,

    #[error("recorder cannot finish: game is not terminal")]
    ReplayNotTerminal,

    #[error("random recording exceeded the {limit}-ply safety limit")]
    PlyLimitExceeded { limit: u32 },

    #[error("engine error: {0}")]
    Engine(#[from] EngineError),

    #[error("invalid replay hash encoding: {0:?}")]
    InvalidHashEncoding(String),

    #[error("json error: {0}")]
    Json(String),
}
