use splendor_catalog::{CardId, Tier};
use splendor_core::PlayerId;

/// Structured error type for information-set construction.
///
/// Every failure is a structured variant; the builder never panics on
/// malformed history, out-of-range slots, out-of-range players, or card
/// mismatches.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum BeliefError {
    /// `ruleset_fingerprint(ruleset)` does not match `observation.ruleset_fingerprint`.
    #[error("ruleset fingerprint mismatch")]
    RulesetFingerprintMismatch,

    /// The observation's `viewer` is not a valid player for its player count.
    #[error("viewer {viewer:?} is out of range for {player_count} players")]
    ViewerOutOfRange { viewer: PlayerId, player_count: u8 },

    /// A visible-history event violates the input contract (bad structure,
    /// out-of-range slot/player, inconsistent card identity, ...).
    #[error("malformed visible history at event {index}: {reason}")]
    MalformedHistory { index: usize, reason: String },

    /// The visible history exposed a hidden `CardId` (an opponent's blind
    /// reserved card) that the viewer must never see.
    #[error("visible history leaked hidden information at event {index}")]
    HiddenInformationLeak { index: usize },

    /// The reconstructed reserved slots for a player disagree with the
    /// observation (count, ordering, card identity, tier, or from_deck flag).
    #[error("reserved knowledge does not match the observation for player {player:?}")]
    ReservedKnowledgeMismatch { player: PlayerId },

    /// The same known `CardId` appears twice across market / purchased /
    /// reserved regions.
    #[error("duplicate known card {card:?}")]
    DuplicateKnownCard { card: CardId },

    /// Per-tier unseen-card accounting does not satisfy
    /// `total - known == deck_count + hidden_opponent_reserves`.
    #[error("card accounting mismatch for tier {tier:?}: expected {expected}, found {found}")]
    CardAccountingMismatch {
        tier: Tier,
        expected: usize,
        found: usize,
    },

    /// The observation itself is structurally inconsistent (player-count vs
    /// players length, non-contiguous player ids, out-of-catalog card, card
    /// tier not matching its region, ...).
    #[error("malformed observation: {0}")]
    MalformedObservation(String),

    /// Serialization of the visible history failed.
    #[error("serialization failed: {0}")]
    Serialization(String),
}
