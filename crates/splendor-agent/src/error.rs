//! Agent error taxonomy.

use std::fmt;

/// Why an agent stopped before a clean `game_end`.
#[derive(Debug)]
pub enum AgentError {
    /// The server sent something that violated the protocol state machine
    /// (unexpected type, wrong game id / recipient / request id, stale
    /// observation hash, empty legal-action set, a server `error`, or EOF
    /// before `game_end`). Carries a stable, concise reason.
    Protocol(String),
    /// A stdin/stdout I/O failure or a malformed (unparseable) server line.
    Io(String),
    /// The policy could not choose an action (for example an internal or
    /// learning error). The runtime emits the `Display` form as a stable
    /// diagnostic.
    Policy(String),
}

impl fmt::Display for AgentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AgentError::Protocol(m) => write!(f, "{m}"),
            AgentError::Io(m) => write!(f, "{m}"),
            AgentError::Policy(m) => write!(f, "{m}"),
        }
    }
}

impl std::error::Error for AgentError {}
