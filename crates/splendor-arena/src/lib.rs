//! Arena: seat-bound match runner, agent process transport, and lifecycle.
//!
//! The arena drives one complete match between agent subprocesses over the
//! NDJSON protocol: strict handshake, per-turn observation/request/action
//! state machine with deadlines, per-seat event projection, and a verified
//! replay on a clean terminal.
//!
//! Modules:
//! - [`config`]: `ArenaConfig` / `AgentCommand` and their frozen validation.
//! - [`report`]: the v1 report schema (`ArenaReportV1`, `ArenaOutcomeV1`, the
//!   [`report::AgentFault`] taxonomy, phases).
//! - [`seed_commitment`]: the locked v1 seed-commitment algorithm.
//! - [`process`]: spawning an agent, bounded stdout forwarding, stderr drain,
//!   and best-effort child reaping.
//! - [`controller`]: global counters, per-seat state, and pure validation.
//! - [`runner`]: [`ArenaRunner`] — the seat-bound match state machine.
//! - [`error`]: `ArenaConfigError`, `ProcessError`, and `ArenaInternalError`.

pub mod config;
pub mod controller;
pub mod error;
pub mod process;
pub mod report;
pub mod runner;
pub mod seed_commitment;

// Re-export the most-used types so consumers need not reach into submodules.
pub use config::{AgentCommand, ArenaConfig};
pub use error::{ArenaConfigError, ArenaInternalError, ProcessError};
pub use process::{
    spawn_agent, AgentProcess, InboundEvent, MAX_AGENT_LINE_BYTES, STDERR_TAIL_BYTES,
};
pub use report::{
    AgentFault, AgentIdentity, ArenaOutcomeV1, ArenaPhase, ArenaReportV1, ARENA_REPORT_FORMAT,
    ARENA_REPORT_VERSION,
};
pub use runner::{ArenaRun, ArenaRunner};
pub use seed_commitment::{seed_commitment_v1, SeedCommitment};

// Re-export a few core types the schema references, for convenience.
pub use splendor_core::{GameResult, PlayerId, RulesetFingerprint};
