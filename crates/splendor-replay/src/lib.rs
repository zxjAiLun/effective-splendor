//! Referee-only Splendor replay v1.
//!
//! A replay is a persisted, self-verifying audit record of one game. It stores
//! the seed, the exact ruleset parameters, and the full ordered action stream,
//! together with a `FullStateHash` before and after every ply. Reloading a
//! replay lets a verifier re-run the engine and confirm, ply by ply, that the
//! recorded hashes match — and pinpoint the exact ply and reason on any
//! divergence or tampering.
//!
//! Information boundary: a replay contains the raw `seed` and full-state hashes,
//! from which hidden decks and blind reserves can be reconstructed. It is a
//! referee / post-game artifact and MUST NOT be sent to an agent or spectator
//! during a live match. This crate deliberately does not depend on
//! `splendor-protocol`: replay is not an agent projection.
//!
//! v1 compatibility: a replay is reproducible from `seed + exact ruleset +
//! action sequence + a compatible engine`. It does not record a full resolved
//! chance stream, so v1 makes no promise of reconstruction across incompatible
//! engine versions. A future v2 would add an explicit chance stream.

mod compat;
mod error;
mod format;
mod recorder;
mod verify;

pub use error::{ReplayError, ReplayResult};
pub use format::{
    ReplayGameResultV1, ReplayHash, ReplayRulesetV1, ReplayStepV1, ReplayTerminalReason, ReplayV1,
    REPLAY_FORMAT, REPLAY_VERSION, SUPPORTED_RULESET_ID,
};
pub use recorder::{record_random_game, ReplayRecorder, MAX_RANDOM_REPLAY_PLIES};
pub use verify::{verify_replay, VerifiedReplay};
