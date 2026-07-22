//! Arena: match model, agent process transport, and lifecycle (v1, part 1).
//!
//! This crate establishes the arena's data model and process plumbing ahead of
//! the seat-bound match runner (a later commit). It does **not** yet contain a
//! full round loop, handshake state machine, action requests, illegal-action
//! policy, replay recording, or a CLI driver.
//!
//! Modules:
//! - [`config`]: `ArenaConfig` / `AgentCommand` and their frozen validation.
//! - [`report`]: the v1 report schema (`ArenaReportV1`, `ArenaOutcomeV1`, the
//!   [`report::AgentFault`] taxonomy, phases).
//! - [`seed_commitment`]: the locked v1 seed-commitment algorithm.
//! - [`process`]: spawning an agent, bounded stdout forwarding, stderr drain,
//!   and best-effort child reaping.
//! - [`error`]: `ArenaConfigError` and `ProcessError`.

pub mod config;
pub mod error;
pub mod process;
pub mod report;
pub mod seed_commitment;

// Re-export the most-used types so consumers need not reach into submodules.
pub use config::{AgentCommand, ArenaConfig};
pub use error::{ArenaConfigError, ProcessError};
pub use process::{
    spawn_agent, AgentProcess, InboundEvent, MAX_AGENT_LINE_BYTES, STDERR_TAIL_BYTES,
};
pub use report::{
    AgentFault, AgentIdentity, ArenaOutcomeV1, ArenaPhase, ArenaReportV1, ARENA_REPORT_FORMAT,
    ARENA_REPORT_VERSION,
};
pub use seed_commitment::{seed_commitment_v1, SeedCommitment};

// Re-export a few core types the schema references, for convenience.
pub use splendor_core::{GameResult, PlayerId, RulesetFingerprint};
