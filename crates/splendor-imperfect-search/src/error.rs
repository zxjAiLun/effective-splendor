use splendor_belief::BeliefError;
use splendor_core::PlayerId;
use splendor_search::SearchError;

/// Errors produced while validating or executing root-determinization
/// aggregation.
#[derive(Debug, thiserror::Error)]
pub enum ImperfectSearchError {
    /// The root or continuation configuration is outside its frozen limits.
    #[error("invalid root determinization config: {0}")]
    InvalidConfig(String),

    /// The supplied information set is not viewed from the player to move.
    #[error("viewer {viewer:?} is not the root player {current_player:?}")]
    ViewerIsNotRootPlayer {
        viewer: PlayerId,
        current_player: PlayerId,
    },

    /// A terminal information set has no root decision to aggregate.
    #[error("cannot aggregate a terminal information set")]
    TerminalInformationSet,

    /// The validated information set could not be determinized.
    #[error(transparent)]
    Belief(#[from] BeliefError),

    /// A sampled continuation search failed.
    #[error(transparent)]
    Search(#[from] SearchError),

    /// A core state transition failed while applying a root action.
    #[error("engine failure during root aggregation: {0}")]
    Engine(String),

    /// Different samples exposed different canonical root action sets.
    #[error("root action set mismatch at sample {sample_index}")]
    RootActionSetMismatch { sample_index: u64 },

    /// A utility vector did not match the information set's player count.
    #[error("utility vector shape mismatch: expected {expected}, found {found}")]
    UtilityShapeMismatch { expected: usize, found: usize },

    /// A checked integer accumulation would overflow.
    #[error("checked arithmetic overflow: {0}")]
    Overflow(String),

    /// A non-terminal sampled root unexpectedly offered no legal actions.
    #[error("root state has no legal actions")]
    NoLegalActions,
}

/// Descriptive alias for callers that prefer the operation-specific name.
pub type RootDeterminizationError = ImperfectSearchError;
