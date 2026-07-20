//! Deterministic Splendor rules engine.
//!
//! Design invariants:
//! - `FullState` is referee-only (deck order, blind reserves, RNG).
//! - `Observation` never leaks other players' blind reserved cards.
//! - Chance outcomes are explicit events, not implicit seed side-effects alone.
//! - Semantic `Action` values are protocol-stable; policy indices live elsewhere.

mod action;
mod error;
mod events;
mod gems;
mod hash;
mod observation;
mod state;

pub use action::Action;
pub use error::{EngineError, EngineResult};
pub use events::{
    visible_events, Audience, ChanceEvent, GameEvent, RefereeEvent, StepResult, Visibility,
    VisibleEvent,
};
pub use gems::Gems;
pub use hash::{
    full_state_hash, observation_hash, observer_hash, public_state_hash, ruleset_fingerprint,
    FullStateHash, HashHex, ObservationHash, PublicStateHash, RulesetFingerprint,
};
pub use observation::{
    Observation, PrivatePlayerView, PublicPlayerView, PublicState, ReservedView,
};
pub use state::{
    play_random_game, random_action, FullPlayerState, FullState, GameConfig, GameResult, Phase,
    PlayerId, ReservedCard, SetupInfo, TerminalReason,
};

pub use splendor_catalog::{
    CardDef, CardId, GemColor, NobleDef, NobleId, Ruleset, RulesetId, Tier, CATALOG_VERSION,
    RULESET_BASE_V1,
};

/// Engine semantic version for replays / protocol compatibility.
pub const ENGINE_VERSION: &str = "0.2.0";
