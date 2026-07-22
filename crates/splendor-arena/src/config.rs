//! Arena configuration model and validation.
//!
//! `ArenaConfig` and `AgentCommand` are deserialized from the arena's input
//! document. They are deliberately free of any executable interpretation: an
//! `AgentCommand` names a program and (optionally) literal argv tokens, and
//! the arena spawns it directly. Agent args are **never** joined into a shell
//! command.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::error::ArenaConfigError;

/// Hard ceiling on any configured timeout, to bound config/integer accidents.
/// 24 hours, expressed in milliseconds.
pub const MAX_TIMEOUT_MS: u64 = 24 * 60 * 60 * 1_000;

/// Maximum UTF-8 byte length of `game_id`.
pub const MAX_GAME_ID_BYTES: usize = 128;

/// The arena configuration document.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArenaConfig {
    /// Stable, human-readable game identifier. Must be non-empty, fit within
    /// [`MAX_GAME_ID_BYTES`], and contain no `\r`, `\n`, or NUL.
    pub game_id: String,
    /// Seed for the deterministic match RNG.
    pub seed: u64,
    /// Max time allowed for an agent to complete the handshake.
    pub handshake_timeout_ms: u64,
    /// Max time allowed for an agent to return an action per request.
    pub move_timeout_ms: u64,
    /// Grace period before a SIGKILL-equivalent `kill` on shutdown.
    pub shutdown_grace_ms: u64,
    /// Agents, in seat order. Must contain 2–4 entries.
    pub agents: Vec<AgentCommand>,
}

/// A single agent's spawn command.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentCommand {
    /// Program to execute. Relative paths are resolved against the arena's
    /// working directory at spawn time; the arena does not verify existence
    /// here (a missing program surfaces as a spawn error).
    pub program: PathBuf,
    /// Literal argv tokens passed after `program`. Never shell-interpreted.
    #[serde(default)]
    pub args: Vec<String>,
}

impl ArenaConfig {
    /// Validate the frozen invariants. Returns [`ArenaConfigError`] on the
    /// first violation.
    pub fn validate(&self) -> Result<(), ArenaConfigError> {
        if self.game_id.trim().is_empty() {
            return Err(ArenaConfigError::EmptyGameId);
        }
        let bytes = self.game_id.as_bytes();
        if bytes.len() > MAX_GAME_ID_BYTES {
            return Err(ArenaConfigError::GameIdTooLong(bytes.len()));
        }
        // Reject C0 control characters (NUL and the classic whitespace-ish
        // controls) so a crafted `game_id` can never corrupt framing or
        // shell-adjacent handling.
        if bytes.iter().any(|b| *b < 0x20) {
            return Err(ArenaConfigError::GameIdControlCharacter);
        }

        let count = self.agents.len();
        let count_u8 = u8::try_from(count).unwrap_or(u8::MAX);
        if !(2..=4).contains(&count) {
            return Err(ArenaConfigError::AgentCount(count_u8));
        }

        for agent in &self.agents {
            if agent.program.as_os_str().is_empty() {
                return Err(ArenaConfigError::EmptyProgram);
            }
        }

        self.check_timeout("handshake_timeout_ms", self.handshake_timeout_ms)?;
        self.check_timeout("move_timeout_ms", self.move_timeout_ms)?;
        self.check_timeout("shutdown_grace_ms", self.shutdown_grace_ms)?;

        Ok(())
    }

    fn check_timeout(&self, field: &'static str, value: u64) -> Result<(), ArenaConfigError> {
        if value == 0 {
            return Err(ArenaConfigError::ZeroTimeout { field });
        }
        if value > MAX_TIMEOUT_MS {
            return Err(ArenaConfigError::TimeoutTooLarge {
                field,
                value_ms: value,
            });
        }
        Ok(())
    }

    /// Number of seats, derived from the agent list length.
    pub fn player_count(&self) -> u8 {
        // Safe: validated count is 2..=4, so this never overflows.
        self.agents.len() as u8
    }
}
