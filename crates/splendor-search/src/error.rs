/// Search-layer error contract.
///
/// The search layer must never panic on a legal core state: engine failures
/// are converted into [`SearchError::Engine`], and every utility vector shape
/// is validated before use.
#[derive(Debug, thiserror::Error)]
pub enum SearchError {
    /// The provided `SearchConfigV1` violates the frozen limits.
    #[error("invalid search config: {0}")]
    InvalidConfig(String),

    /// The root state is terminal; search has no decision to make.
    #[error("root state is terminal")]
    TerminalState,

    /// The root state offered no legal actions outside the terminal phase.
    #[error("root state has no legal actions")]
    NoLegalActions,

    /// A core engine call failed while expanding the search tree.
    #[error("engine failure during search: {0}")]
    Engine(String),

    /// A utility vector did not match the state's player count.
    #[error("utility vector shape mismatch: expected {expected}, found {found}")]
    InvalidUtilityShape { expected: usize, found: usize },
}
