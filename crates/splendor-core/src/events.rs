use serde::{Deserialize, Serialize};
use splendor_catalog::{CardId, NobleId, Tier};

use crate::action::Action;
use crate::gems::Gems;
use crate::hash::FullStateHash;
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

/// Referee-only game log entry. May carry full hidden information
/// (deck order, blind-reserved `CardId`s). **Never serialize this for agents.**
///
/// Historically named `GameEvent`; kept as an alias for backward compatibility.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RefereeEvent {
    GameStarted {
        player_count: u8,
        seed: u64,
        ruleset: String,
    },
    ActionApplied {
        player: PlayerId,
        action: Action,
    },
    TokensTransferred {
        player: PlayerId,
        taken_from_bank: Gems,
        returned_to_bank: Gems,
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
        /// Who may see the reserved card identity. `Player(p)` for a blind
        /// (deck) reserve so only the owner sees it; `Public` for market.
        visible_to: Visibility,
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

/// Backward-compatible alias.
pub use RefereeEvent as GameEvent;

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

/// Who a `VisibleEvent` transcript is being produced for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Audience {
    /// Full referee log (no redaction).
    Referee,
    /// A specific player — sees their own blind reserves, not opponents'.
    Player(PlayerId),
    /// External observer / spectator — sees only public information.
    Spectator,
    /// After the game, full reveal is permitted.
    PostGame,
}

/// Event after projection to a given audience. Hidden card identities are
/// replaced with `public: false` so the transcript cannot leak them.
///
/// This is the ONLY event type the protocol layer may serialize.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum VisibleEvent {
    GameStarted {
        player_count: u8,
        ruleset: String,
    },
    ActionApplied {
        player: PlayerId,
        action: Action,
    },
    TokensTransferred {
        player: PlayerId,
        taken_from_bank: Gems,
        returned_to_bank: Gems,
    },
    CardPurchased {
        player: PlayerId,
        card: CardId,
        paid: Gems,
        from: PurchaseSource,
    },
    CardReserved {
        player: PlayerId,
        /// `None` means the identity is hidden from this audience.
        card: Option<CardId>,
        from: ReserveSource,
        received_gold: bool,
        public_identity: bool,
        visible_to: Visibility,
    },
    NobleTaken {
        player: PlayerId,
        noble: NobleId,
    },
    ChanceRevealed {
        tier: Tier,
        slot: Option<u8>,
        /// `None` when hidden from this audience.
        card: Option<CardId>,
        visible_to: Visibility,
    },
    SetupDealt {
        market: [[Option<CardId>; 4]; 3],
        nobles: Vec<NobleId>,
    },
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

/// Project a referee log into a visible transcript for `audience`.
///
/// This is the single allowed exit point: protocol/runner code must call this
/// and serialize the result, never `RefereeEvent` directly.
pub fn visible_events(events: &[RefereeEvent], audience: Audience) -> Vec<VisibleEvent> {
    let can_see_hidden = matches!(audience, Audience::Referee | Audience::PostGame);

    events
        .iter()
        .map(|e| project_event(e, audience, can_see_hidden))
        .collect()
}

fn project_event(e: &RefereeEvent, audience: Audience, can_see_hidden: bool) -> VisibleEvent {
    match e {
        RefereeEvent::GameStarted {
            player_count,
            ruleset,
            ..
        } => VisibleEvent::GameStarted {
            player_count: *player_count,
            ruleset: ruleset.clone(),
        },
        RefereeEvent::ActionApplied { player, action } => VisibleEvent::ActionApplied {
            player: *player,
            action: *action,
        },
        RefereeEvent::TokensTransferred {
            player,
            taken_from_bank,
            returned_to_bank,
        } => VisibleEvent::TokensTransferred {
            player: *player,
            taken_from_bank: *taken_from_bank,
            returned_to_bank: *returned_to_bank,
        },
        RefereeEvent::CardPurchased {
            player,
            card,
            paid,
            from,
        } => VisibleEvent::CardPurchased {
            player: *player,
            card: *card,
            paid: *paid,
            from: *from,
        },
        RefereeEvent::CardReserved {
            player,
            card,
            from,
            received_gold,
            public_identity,
            visible_to,
        } => {
            // Visible to the owner (or everyone, if public) and to the referee.
            let visible = match visible_to {
                Visibility::Public => true,
                Visibility::Player(p) => {
                    can_see_hidden || matches!(audience, Audience::Player(q) if q == *p)
                }
            };
            VisibleEvent::CardReserved {
                player: *player,
                card: if visible { Some(*card) } else { None },
                from: *from,
                received_gold: *received_gold,
                public_identity: *public_identity,
                visible_to: *visible_to,
            }
        }
        RefereeEvent::NobleTaken { player, noble } => VisibleEvent::NobleTaken {
            player: *player,
            noble: *noble,
        },
        RefereeEvent::Chance(ChanceEvent::CardRevealed {
            tier,
            slot,
            card,
            visible_to,
        }) => {
            let visible = match visible_to {
                Visibility::Public => true,
                Visibility::Player(p) => {
                    can_see_hidden || matches!(audience, Audience::Player(q) if q == *p)
                }
            };
            VisibleEvent::ChanceRevealed {
                tier: *tier,
                slot: *slot,
                card: if visible { Some(*card) } else { None },
                visible_to: *visible_to,
            }
        }
        RefereeEvent::Chance(ChanceEvent::SetupDealt { market, nobles }) => {
            // Setup deal is fully public.
            VisibleEvent::SetupDealt {
                market: *market,
                nobles: nobles.clone(),
            }
        }
        RefereeEvent::TurnAdvanced { next_player } => VisibleEvent::TurnAdvanced {
            next_player: *next_player,
        },
        RefereeEvent::EndGameTriggered { by } => VisibleEvent::EndGameTriggered { by: *by },
        RefereeEvent::GameEnded { result } => VisibleEvent::GameEnded {
            result: result.clone(),
        },
    }
}

/// Result of applying one action (or setup).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StepResult {
    pub events: Vec<RefereeEvent>,
    pub state_hash_before: FullStateHash,
    pub state_hash_after: FullStateHash,
}
