use splendor_catalog::{CardId, Tier};
use splendor_core::{FullState, FullStateHash, Observation, PlayerId, Ruleset};

use crate::hash::{InformationSetHashV1, VisibleHistoryHashV1};

/// Frozen model version of the information-set layer (M07 C1).
pub const INFORMATION_SET_VERSION: u32 = 1;

/// Frozen model version of the deterministic hidden-state sampler (M07 C2).
pub const DETERMINIZATION_VERSION: u32 = 1;

/// What a viewer knows about one reserved slot of a player.
///
/// The slot layout of the real reserved vector is preserved: buying a reserved
/// card removes that exact slot and shifts later slots left.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReservedKnowledgeV1 {
    /// The viewer knows the exact reserved card.
    Known {
        card: CardId,
        /// `true` for a blind (deck) reserve owned by the viewer; `false` for a
        /// face-up market reserve (public for everyone).
        from_deck: bool,
    },
    /// The viewer only knows that an opponent blind-reserved the top card of a
    /// tier deck.
    HiddenDeck { tier: Tier },
}

/// One player's reserved-knowledge vector, in real slot order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlayerReservedKnowledgeV1 {
    pub player: PlayerId,
    pub slots: Vec<ReservedKnowledgeV1>,
}

/// Validated information set: what the viewer could know from the visible
/// transcript plus the current observation.
///
/// Construction happens exclusively through
/// [`crate::build_information_set_v1`]; there is no public struct-literal
/// constructor that could bypass the invariants.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InformationSetV1 {
    ruleset: Ruleset,
    observation: Observation,
    visible_history_hash: VisibleHistoryHashV1,
    information_set_hash: InformationSetHashV1,
    reserved_knowledge: Vec<PlayerReservedKnowledgeV1>,
    unseen_cards_by_tier: [Vec<CardId>; 3],
}

impl InformationSetV1 {
    /// Construct from already-validated parts. Crate-private: the only public
    /// entry point is [`crate::build_information_set_v1`].
    pub(crate) fn new(
        ruleset: Ruleset,
        observation: Observation,
        visible_history_hash: VisibleHistoryHashV1,
        information_set_hash: InformationSetHashV1,
        reserved_knowledge: Vec<PlayerReservedKnowledgeV1>,
        unseen_cards_by_tier: [Vec<CardId>; 3],
    ) -> Self {
        Self {
            ruleset,
            observation,
            visible_history_hash,
            information_set_hash,
            reserved_knowledge,
            unseen_cards_by_tier,
        }
    }

    /// The ruleset used to build this information set.
    pub fn ruleset(&self) -> Ruleset {
        self.ruleset
    }

    /// The observation this information set is consistent with.
    pub fn observation(&self) -> &Observation {
        &self.observation
    }

    /// SHA-256 identity of the visible-history transcript.
    pub fn visible_history_hash(&self) -> &VisibleHistoryHashV1 {
        &self.visible_history_hash
    }

    /// SHA-256 identity of the whole information set.
    pub fn information_set_hash(&self) -> &InformationSetHashV1 {
        &self.information_set_hash
    }

    /// Per-player reserved knowledge in player-index order.
    pub fn reserved_knowledge(&self) -> &[PlayerReservedKnowledgeV1] {
        &self.reserved_knowledge
    }

    /// Canonical pool of cards the viewer has not seen in `tier`, ascending by
    /// `CardId`. Includes both remaining deck positions and opponent
    /// `HiddenDeck` slots. C2's sampler starts from this canonical pool.
    pub fn unseen_cards(&self, tier: Tier) -> &[CardId] {
        &self.unseen_cards_by_tier[tier.index()]
    }
}

/// One deterministic hidden-state completion of an [`InformationSetV1`]
/// (M07 C2).
///
/// Construction happens exclusively through
/// [`crate::sample_determinization_v1`]; there is no public struct-literal
/// constructor that could bypass the sampling invariants.
///
/// (`FullState` does not implement `PartialEq`; identity comparisons use
/// `state_hash`.)
#[derive(Debug, Clone)]
pub struct DeterminizationV1 {
    state: FullState,
    state_hash: FullStateHash,
    sample_seed: u64,
    sample_index: u64,
}

impl DeterminizationV1 {
    /// Crate-private constructor: only the sampler may create instances.
    pub(crate) fn new(
        state: FullState,
        state_hash: FullStateHash,
        sample_seed: u64,
        sample_index: u64,
    ) -> Self {
        Self {
            state,
            state_hash,
            sample_seed,
            sample_index,
        }
    }

    /// The reconstructed referee state. Its `seed` is a synthetic internal
    /// identity derived from the sample key; it is never the original setup
    /// seed (which C2 does not receive).
    pub fn state(&self) -> &FullState {
        &self.state
    }

    /// SHA-256 identity of the sampled state.
    pub fn state_hash(&self) -> &FullStateHash {
        &self.state_hash
    }

    /// The sample key used for this determinization.
    pub fn sample_seed(&self) -> u64 {
        self.sample_seed
    }

    /// The sample index used for this determinization.
    pub fn sample_index(&self) -> u64 {
        self.sample_index
    }
}
