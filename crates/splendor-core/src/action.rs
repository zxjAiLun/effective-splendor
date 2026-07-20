use serde::{Deserialize, Serialize};
use splendor_catalog::{NobleId, Tier};

use crate::gems::Gems;

/// Semantic game action. Protocol and replay use this shape, not policy indices.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Action {
    /// Take gems and optionally return excess in one atomic step.
    TakeTokens {
        take: Gems,
        #[serde(default, rename = "return")]
        give_back: Gems,
    },
    /// Buy a face-up market card.
    BuyMarket { tier: Tier, slot: u8 },
    /// Buy one of the current player's reserved cards.
    BuyReserved { slot: u8 },
    /// Reserve a face-up market card (may grant gold).
    ReserveMarket {
        tier: Tier,
        slot: u8,
        #[serde(default, rename = "return")]
        give_back: Gems,
    },
    /// Blind-reserve the top card of a tier deck (may grant gold).
    ReserveDeck {
        tier: Tier,
        #[serde(default, rename = "return")]
        give_back: Gems,
    },
    /// Choose a noble after a purchase that qualifies for multiple nobles.
    ChooseNoble { noble: NobleId },
    /// Only legal when no other main action exists (depleted bank / full reserves).
    Pass,
}

impl Action {
    pub fn is_main_action(self) -> bool {
        !matches!(self, Action::ChooseNoble { .. })
    }
}
