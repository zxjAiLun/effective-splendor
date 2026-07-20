use crate::{CardId, GemColor};

/// Development card tier (1–3, zero-based as 0–2 in market arrays).
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, serde::Serialize, serde::Deserialize,
)]
#[repr(u8)]
pub enum Tier {
    One = 0,
    Two = 1,
    Three = 2,
}

impl Tier {
    pub const ALL: [Tier; 3] = [Tier::One, Tier::Two, Tier::Three];

    pub fn index(self) -> usize {
        self as usize
    }

    pub fn from_index(i: usize) -> Option<Self> {
        match i {
            0 => Some(Tier::One),
            1 => Some(Tier::Two),
            2 => Some(Tier::Three),
            _ => None,
        }
    }

    pub fn level(self) -> u8 {
        self as u8 + 1
    }
}

/// Immutable development card definition.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CardDef {
    pub id: CardId,
    pub tier: Tier,
    pub bonus: GemColor,
    pub prestige: u8,
    /// Cost in [W, B, G, R, K] (no gold — gold is a wild payment at runtime).
    pub cost: [u8; 5],
}

impl CardDef {
    pub fn cost_of(&self, color: GemColor) -> u8 {
        self.cost[color.index()]
    }

    pub fn total_cost(&self) -> u8 {
        self.cost.iter().sum()
    }
}

pub const CARD_COUNT: usize = 90;

pub fn all_cards() -> &'static [CardDef] {
    &CARDS
}

pub fn cards_for_tier(tier: Tier) -> Vec<&'static CardDef> {
    all_cards().iter().filter(|c| c.tier == tier).collect()
}

pub fn card(id: CardId) -> &'static CardDef {
    &CARDS[id.index()]
}

#[allow(clippy::too_many_arguments)]
const fn c(
    id: u8,
    tier: Tier,
    bonus: GemColor,
    prestige: u8,
    w: u8,
    b: u8,
    g: u8,
    r: u8,
    k: u8,
) -> CardDef {
    CardDef {
        id: CardId(id),
        tier,
        bonus,
        prestige,
        cost: [w, b, g, r, k],
    }
}

// Card data aligned with the standard base-game set (same tables used by
// common open-source engines such as cestpasphoto/alpha-zero-general).
// Order: tier1 (40) → tier2 (30) → tier3 (20), grouped by bonus color.
static CARDS: [CardDef; CARD_COUNT] = {
    use GemColor::*;
    use Tier::*;
    [
        // ===== Tier 1 — Blue bonus (8) =====
        c(0, One, Blue, 0, 0, 0, 0, 0, 3),
        c(1, One, Blue, 0, 1, 0, 0, 0, 2),
        c(2, One, Blue, 0, 0, 0, 2, 0, 2),
        c(3, One, Blue, 0, 1, 0, 2, 2, 0),
        c(4, One, Blue, 0, 0, 1, 3, 1, 0),
        c(5, One, Blue, 0, 1, 0, 1, 1, 1),
        c(6, One, Blue, 0, 1, 0, 1, 2, 1),
        c(7, One, Blue, 1, 0, 0, 0, 4, 0),
        // ===== Tier 1 — Red bonus (8) =====
        c(8, One, Red, 0, 3, 0, 0, 0, 0),
        c(9, One, Red, 0, 0, 2, 1, 0, 0),
        c(10, One, Red, 0, 2, 0, 0, 2, 0),
        c(11, One, Red, 0, 2, 0, 1, 0, 2),
        c(12, One, Red, 0, 1, 0, 0, 1, 3),
        c(13, One, Red, 0, 1, 1, 1, 0, 1),
        c(14, One, Red, 0, 2, 1, 1, 0, 1),
        c(15, One, Red, 1, 4, 0, 0, 0, 0),
        // ===== Tier 1 — Black bonus (8) =====
        c(16, One, Black, 0, 0, 0, 3, 0, 0),
        c(17, One, Black, 0, 0, 0, 2, 1, 0),
        c(18, One, Black, 0, 2, 0, 2, 0, 0),
        c(19, One, Black, 0, 2, 2, 0, 1, 0),
        c(20, One, Black, 0, 0, 0, 1, 3, 1),
        c(21, One, Black, 0, 1, 1, 1, 1, 0),
        c(22, One, Black, 0, 1, 2, 1, 1, 0),
        c(23, One, Black, 1, 0, 4, 0, 0, 0),
        // ===== Tier 1 — White bonus (8) =====
        c(24, One, White, 0, 0, 3, 0, 0, 0),
        c(25, One, White, 0, 0, 0, 0, 2, 1),
        c(26, One, White, 0, 0, 2, 0, 0, 2),
        c(27, One, White, 0, 0, 2, 2, 0, 1),
        c(28, One, White, 0, 3, 1, 0, 0, 1),
        c(29, One, White, 0, 0, 1, 1, 1, 1),
        c(30, One, White, 0, 0, 1, 2, 1, 1),
        c(31, One, White, 1, 0, 0, 4, 0, 0),
        // ===== Tier 1 — Green bonus (8) =====
        c(32, One, Green, 0, 0, 0, 0, 3, 0),
        c(33, One, Green, 0, 2, 1, 0, 0, 0),
        c(34, One, Green, 0, 0, 2, 0, 2, 0),
        c(35, One, Green, 0, 0, 1, 0, 2, 2),
        c(36, One, Green, 0, 1, 3, 1, 0, 0),
        c(37, One, Green, 0, 1, 1, 0, 1, 1),
        c(38, One, Green, 0, 1, 1, 0, 1, 2),
        c(39, One, Green, 1, 0, 0, 0, 0, 4),
        // ===== Tier 2 — Blue bonus (6) =====
        c(40, Two, Blue, 1, 0, 2, 2, 3, 0),
        c(41, Two, Blue, 1, 0, 2, 3, 0, 3),
        c(42, Two, Blue, 2, 0, 5, 0, 0, 0),
        c(43, Two, Blue, 2, 5, 3, 0, 0, 0),
        c(44, Two, Blue, 2, 2, 0, 0, 1, 4),
        c(45, Two, Blue, 3, 0, 6, 0, 0, 0),
        // ===== Tier 2 — Red bonus (6) =====
        c(46, Two, Red, 1, 2, 0, 0, 2, 3),
        c(47, Two, Red, 1, 0, 3, 0, 2, 3),
        c(48, Two, Red, 2, 0, 0, 0, 0, 5),
        c(49, Two, Red, 2, 3, 0, 0, 0, 5),
        c(50, Two, Red, 2, 1, 4, 2, 0, 0),
        c(51, Two, Red, 3, 0, 0, 0, 6, 0),
        // ===== Tier 2 — Black bonus (6) =====
        c(52, Two, Black, 1, 3, 2, 2, 0, 0),
        c(53, Two, Black, 1, 3, 0, 3, 0, 2),
        c(54, Two, Black, 2, 5, 0, 0, 0, 0),
        c(55, Two, Black, 2, 0, 0, 5, 3, 0),
        c(56, Two, Black, 2, 0, 1, 4, 2, 0),
        c(57, Two, Black, 3, 0, 0, 0, 0, 6),
        // ===== Tier 2 — White bonus (6) =====
        c(58, Two, White, 1, 0, 0, 3, 2, 2),
        c(59, Two, White, 1, 2, 3, 0, 3, 0),
        c(60, Two, White, 2, 0, 0, 0, 5, 0),
        c(61, Two, White, 2, 0, 0, 0, 5, 3),
        c(62, Two, White, 2, 0, 0, 1, 4, 2),
        c(63, Two, White, 3, 6, 0, 0, 0, 0),
        // ===== Tier 2 — Green bonus (6) =====
        c(64, Two, Green, 1, 2, 3, 0, 0, 2),
        c(65, Two, Green, 1, 3, 0, 2, 3, 0),
        c(66, Two, Green, 2, 0, 0, 5, 0, 0),
        c(67, Two, Green, 2, 0, 5, 3, 0, 0),
        c(68, Two, Green, 2, 4, 2, 0, 0, 1),
        c(69, Two, Green, 3, 0, 0, 6, 0, 0),
        // ===== Tier 3 — Blue bonus (4) =====
        c(70, Three, Blue, 3, 3, 0, 3, 3, 5),
        c(71, Three, Blue, 4, 7, 0, 0, 0, 0),
        c(72, Three, Blue, 4, 6, 3, 0, 0, 3),
        c(73, Three, Blue, 5, 7, 3, 0, 0, 0),
        // ===== Tier 3 — Red bonus (4) =====
        c(74, Three, Red, 3, 3, 5, 3, 0, 3),
        c(75, Three, Red, 4, 0, 0, 7, 0, 0),
        c(76, Three, Red, 4, 0, 3, 6, 3, 0),
        c(77, Three, Red, 5, 0, 0, 7, 3, 0),
        // ===== Tier 3 — Black bonus (4) =====
        c(78, Three, Black, 3, 3, 3, 5, 3, 0),
        c(79, Three, Black, 4, 0, 0, 0, 7, 0),
        c(80, Three, Black, 4, 0, 0, 3, 6, 3),
        c(81, Three, Black, 5, 0, 0, 0, 7, 3),
        // ===== Tier 3 — White bonus (4) =====
        c(82, Three, White, 3, 0, 3, 3, 5, 3),
        c(83, Three, White, 4, 0, 0, 0, 0, 7),
        c(84, Three, White, 4, 3, 0, 0, 3, 6),
        c(85, Three, White, 5, 3, 0, 0, 0, 7),
        // ===== Tier 3 — Green bonus (4) =====
        c(86, Three, Green, 3, 5, 3, 0, 3, 3),
        c(87, Three, Green, 4, 0, 7, 0, 0, 0),
        c(88, Three, Green, 4, 3, 6, 3, 0, 0),
        c(89, Three, Green, 5, 0, 7, 3, 0, 0),
    ]
};
