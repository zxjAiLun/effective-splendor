use serde::{Deserialize, Serialize};
use splendor_catalog::{CardId, NobleId, Tier};

use crate::action::Action;
use crate::gems::Gems;
use crate::state::{GameResult, PlayerId};

/// Explicit chance outcome produced by the referee.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ChanceEvent {
    /// A card was drawn from a deck into the market (or reserved blind).
    CardRevealed {
        tier: Tier,
        /// Market slot if revealed to market; `None` for blind reserve draw.
        slot: Option<u8>,
        card: CardId,
        /// Who can see the card identity immediately.
        visible_to: Visibility,
    },
    /// Initial market / noble deal during setup.
    SetupDealt {
        market: [[Option<CardId>; 4]; 3],
        nobles: Vec<NobleId>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Visibility {
    Public,
    Player(PlayerId),
}

/// Append-only game log entry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum GameEvent {
    GameStarted {
        player_count: u8,
        seed: u64,
        ruleset: String,
    },
    ActionApplied {
        player: PlayerId,
        action: Action,
    },
    TokensChanged {
        player: PlayerId,
        delta_player: Gems,
        delta_bank: Gems,
    },
    CardPurchased {
        player: PlayerId,
        card: CardId,
        paid: Gems,
        from: PurchaseSource,
    },
    CardReserved {
        player: PlayerId,
        card: CardId,
        from: ReserveSource,
        received_gold: bool,
        /// True if card identity is public (market reserve); false for deck.
        public_identity: bool,
    },
    NobleTaken {
        player: PlayerId,
        noble: NobleId,
    },
    Chance(ChanceEvent),
    TurnAdvanced {
        next_player: PlayerId,
    },
    EndGameTriggered {
        by: PlayerId,
    },
    GameEnded {
        result: GameResult,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PurchaseSource {
    Market { tier: Tier, slot: u8 },
    Reserved { slot: u8 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReserveSource {
    Market { tier: Tier, slot: u8 },
    Deck { tier: Tier },
}

/// Result of applying one action (or setup).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StepResult {
    pub events: Vec<GameEvent>,
    pub state_hash_before: String,
    pub state_hash_after: String,
}
