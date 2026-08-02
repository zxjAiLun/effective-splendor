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
//!   blind-reserved `CardId`. `FullState` may appear only in tests as an oracle
//!   that *produces* observations and visible transcripts.
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
mod error;
mod hash;
mod model;

pub use build::build_information_set_v1;
pub use error::BeliefError;
pub use hash::{InformationSetHashV1, VisibleHistoryHashV1};
pub use model::{
    InformationSetV1, PlayerReservedKnowledgeV1, ReservedKnowledgeV1, INFORMATION_SET_VERSION,
};
