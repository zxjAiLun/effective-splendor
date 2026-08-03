//! Validated player information sets built from purely visible inputs.
//!
//! This crate is the information-set / determinization foundation of M07. It
//! reconstructs each player's reserved-card knowledge — including the *slot
//! layout* of blind (deck) reserves that `Observation` intentionally hides —
//! from the cumulative player-visible event history, then validates that the
//! reconstruction is exactly consistent with the current `Observation`.
//!
//! Information boundary (frozen, M07 C1):
//! - Production inputs are `Ruleset` + `Observation` + `&[VisibleEvent]` only.
//! - No production entry point accepts `FullState`, `RefereeEvent`, `ReplayV1`,
//!   a raw setup seed, deck order, `FullStateHash`, or another player's
//!   blind-reserved `CardId`. C2 may produce a referee-only sampled `FullState`
//!   internally from a validated information set; that sampled state is never
//!   accepted as a production input and is not exposed by C2's public result
//!   identity.
//! - Any hidden-information leak in the input history (an opponent's blind
//!   reserved `CardId`) is rejected with `BeliefError::HiddenInformationLeak`,
//!   never silently ignored.
//! - `Observation` and `VisibleEvent` inputs are never mutated.
//!
//! Dependency discipline: `splendor-belief -> splendor-core + splendor-catalog`
//! among workspace crates (plus the external `serde_json`, `sha2`, `hex`,
//! `thiserror`). No dependency on search, replay, protocol, agent, arena, eval
//! or cli.

mod build;
mod deterministic_rng;
mod error;
mod hash;
mod model;
mod sampler;

pub use build::build_information_set_v1;
pub use error::BeliefError;
pub use hash::{InformationSetHashV1, VisibleHistoryHashV1};
pub use model::{
    DeterminizationV1, InformationSetV1, PlayerReservedKnowledgeV1, ReservedKnowledgeV1,
    DETERMINIZATION_VERSION, INFORMATION_SET_VERSION,
};
pub use sampler::sample_determinization_v1;
