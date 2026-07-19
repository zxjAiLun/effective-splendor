//! Static game catalog: gem colors, development cards, nobles, and rulesets.
//!
//! This crate is pure data + accessors. Game logic lives in `splendor-core`.

mod cards;
mod nobles;
mod ruleset;

pub use cards::{all_cards, card, cards_for_tier, CardDef, Tier, CARD_COUNT};
pub use nobles::{all_nobles, NobleDef, NOBLE_COUNT};
pub use ruleset::{Ruleset, RulesetId, RULESET_BASE_V1};

/// Gem color used for bonuses and token costs (excludes gold).
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, serde::Serialize, serde::Deserialize,
)]
#[repr(u8)]
pub enum GemColor {
    White = 0,
    Blue = 1,
    Green = 2,
    Red = 3,
    Black = 4,
}

impl GemColor {
    pub const ALL: [GemColor; 5] = [
        GemColor::White,
        GemColor::Blue,
        GemColor::Green,
        GemColor::Red,
        GemColor::Black,
    ];

    pub const COUNT: usize = 5;

    pub fn index(self) -> usize {
        self as usize
    }

    pub fn from_index(i: usize) -> Option<Self> {
        match i {
            0 => Some(GemColor::White),
            1 => Some(GemColor::Blue),
            2 => Some(GemColor::Green),
            3 => Some(GemColor::Red),
            4 => Some(GemColor::Black),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            GemColor::White => "white",
            GemColor::Blue => "blue",
            GemColor::Green => "green",
            GemColor::Red => "red",
            GemColor::Black => "black",
        }
    }
}

/// Dense card identifier into the catalog table.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, serde::Serialize, serde::Deserialize,
)]
pub struct CardId(pub u8);

impl CardId {
    pub fn index(self) -> usize {
        self.0 as usize
    }
}

/// Dense noble identifier into the catalog table.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, serde::Serialize, serde::Deserialize,
)]
pub struct NobleId(pub u8);

impl NobleId {
    pub fn index(self) -> usize {
        self.0 as usize
    }
}

/// Catalog version string embedded in replays / protocol.
pub const CATALOG_VERSION: &str = "0.1.0";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn card_counts_match_standard() {
        assert_eq!(cards_for_tier(Tier::One).len(), 40);
        assert_eq!(cards_for_tier(Tier::Two).len(), 30);
        assert_eq!(cards_for_tier(Tier::Three).len(), 20);
        assert_eq!(all_cards().len(), 90);
        assert_eq!(all_nobles().len(), 10);
    }

    #[test]
    fn card_ids_are_dense() {
        for (i, card) in all_cards().iter().enumerate() {
            assert_eq!(card.id.index(), i);
        }
    }

    #[test]
    fn every_card_has_valid_bonus() {
        for card in all_cards() {
            assert!(GemColor::ALL.contains(&card.bonus));
            assert!(card.prestige <= 5);
        }
    }
}
