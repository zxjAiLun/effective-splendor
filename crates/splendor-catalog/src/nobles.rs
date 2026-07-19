use crate::{GemColor, NobleId};

/// A noble tile: prestige points + bonus requirements.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NobleDef {
    pub id: NobleId,
    pub prestige: u8,
    /// Required permanent bonuses of each color [W,B,G,R,K].
    pub requirements: [u8; 5],
}

pub const NOBLE_COUNT: usize = 10;

/// Official 10 nobles (all worth 3 prestige).
pub fn all_nobles() -> &'static [NobleDef] {
    &NOBLES
}

const fn req(w: u8, b: u8, g: u8, r: u8, k: u8) -> [u8; 5] {
    [w, b, g, r, k]
}

const fn noble(id: u8, requirements: [u8; 5]) -> NobleDef {
    NobleDef {
        id: NobleId(id),
        prestige: 3,
        requirements,
    }
}

/// Requirements use order: White, Blue, Green, Red, Black.
static NOBLES: [NobleDef; NOBLE_COUNT] = [
    noble(0, req(3, 3, 3, 0, 0)), // white/blue/green
    noble(1, req(0, 3, 3, 3, 0)), // blue/green/red
    noble(2, req(0, 0, 3, 3, 3)), // green/red/black
    noble(3, req(3, 0, 0, 3, 3)), // white/red/black
    noble(4, req(3, 3, 0, 0, 3)), // white/blue/black
    noble(5, req(0, 0, 0, 4, 4)), // red/black
    noble(6, req(0, 0, 4, 4, 0)), // green/red
    noble(7, req(0, 4, 4, 0, 0)), // blue/green
    noble(8, req(4, 4, 0, 0, 0)), // white/blue
    noble(9, req(4, 0, 0, 0, 4)), // white/black
];

impl NobleDef {
    pub fn requires(&self, color: GemColor) -> u8 {
        self.requirements[color.index()]
    }
}
