//! Error types for the arena crate.
//!
//! `ArenaConfigError` classifies configuration validation failures so the
//! arena CLI can report a precise, user-facing reason. `ProcessError`
//! classifies failures of the agent process transport: spawn, I/O, and
//! reaping.

use std::io;

/// A configuration value violated a frozen arena invariant.
#[derive(Debug, thiserror::Error)]
pub enum ArenaConfigError {
    /// `game_id` was empty or only whitespace.
    #[error("game_id must not be empty")]
    EmptyGameId,

    /// `game_id` exceeded the 128-byte UTF-8 limit.
    #[error("game_id exceeds the 128-byte limit (got {0} bytes)")]
    GameIdTooLong(usize),

    /// `game_id` contained a forbidden control character (`\r`, `\n`, or NUL).
    #[error("game_id contains a forbidden control character")]
    GameIdControlCharacter,

    /// The agent list did not have between 2 and 4 entries.
    #[error("agent count must be 2..=4 (got {0})")]
    AgentCount(u8),

    /// An agent `program` path was empty.
    #[error("agent program path must not be empty")]
    EmptyProgram,

    /// A timeout was zero.
    #[error("{field} must be greater than zero")]
    ZeroTimeout {
        /// The offending field name.
        field: &'static str,
    },

    /// A timeout exceeded the 24-hour safety ceiling.
    #[error("{field} exceeds the 24h ceiling ({value_ms} ms)")]
    TimeoutTooLarge {
        /// The offending field name.
        field: &'static str,
        /// The rejected value, in milliseconds.
        value_ms: u64,
    },
}

/// A failure of the agent process transport.
#[derive(Debug, thiserror::Error)]
pub enum ProcessError {
    /// The agent program could not be spawned (not found, permission, etc.).
    #[error("failed to spawn agent: {0}")]
    Spawn(#[source] io::Error),

    /// A stdin/stdout/stderr I/O operation failed after spawn.
    #[error("agent I/O error: {0}")]
    Io(#[source] io::Error),

    /// The child pipe was closed before/while writing (`write` returned
    /// `BrokenPipe`). Reported rather than panicked.
    #[error("agent pipe closed unexpectedly")]
    BrokenPipe,

    /// `child.wait()` or `try_wait()` failed.
    #[error("failed to reap agent: {0}")]
    Wait(#[source] io::Error),
}

impl ProcessError {
    pub(crate) fn from_write(err: io::Error) -> Self {
        if err.kind() == io::ErrorKind::BrokenPipe {
            ProcessError::BrokenPipe
        } else {
            ProcessError::Io(err)
        }
    }
}

/// An arena-internal failure that is *not* an agent fault.
///
/// These surface as `Err` from [`crate::runner::ArenaRunner::run`], distinct
/// from an `Aborted` match outcome (which is a normal `Ok` result with no
/// replay). Internal errors mean the arena itself could not honor its own
/// invariants: bad configuration, engine/replay divergence, or a broken
/// internal channel.
#[derive(Debug, thiserror::Error)]
pub enum ArenaInternalError {
    /// The arena configuration violated a frozen invariant.
    #[error("arena configuration error: {0}")]
    Config(#[from] ArenaConfigError),

    /// An agent process could not be spawned or its pipe broke unexpectedly.
    #[error("agent transport error: {0}")]
    Transport(String),

    /// The rules engine reported an internal error the arena could not absorb.
    #[error("engine internal error: {0}")]
    Engine(String),

    /// Replay recording or verification failed internally.
    #[error("replay internal error: {0}")]
    Replay(String),

    /// An internal channel (inbound event fan-in) disconnected unexpectedly.
    #[error("internal channel error: {0}")]
    Channel(String),
}
