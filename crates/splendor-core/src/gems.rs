use serde::{Deserialize, Serialize};
use splendor_catalog::GemColor;

/// Token counts: five colors + gold.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Gems {
    pub white: u8,
    pub blue: u8,
    pub green: u8,
    pub red: u8,
    pub black: u8,
    pub gold: u8,
}

impl Gems {
    pub const ZERO: Self = Self {
        white: 0,
        blue: 0,
        green: 0,
        red: 0,
        black: 0,
        gold: 0,
    };

    pub fn color(self, c: GemColor) -> u8 {
        match c {
            GemColor::White => self.white,
            GemColor::Blue => self.blue,
            GemColor::Green => self.green,
            GemColor::Red => self.red,
            GemColor::Black => self.black,
        }
    }

    pub fn set_color(&mut self, c: GemColor, v: u8) {
        match c {
            GemColor::White => self.white = v,
            GemColor::Blue => self.blue = v,
            GemColor::Green => self.green = v,
            GemColor::Red => self.red = v,
            GemColor::Black => self.black = v,
        }
    }

    pub fn add_color(&mut self, c: GemColor, n: u8) {
        let cur = self.color(c);
        self.set_color(c, cur.saturating_add(n));
    }

    pub fn sub_color(&mut self, c: GemColor, n: u8) -> bool {
        let cur = self.color(c);
        if cur < n {
            return false;
        }
        self.set_color(c, cur - n);
        true
    }

    pub fn total_colors(self) -> u8 {
        self.white + self.blue + self.green + self.red + self.black
    }

    pub fn total(self) -> u8 {
        self.total_colors() + self.gold
    }

    pub fn saturating_add(self, other: Self) -> Self {
        Self {
            white: self.white.saturating_add(other.white),
            blue: self.blue.saturating_add(other.blue),
            green: self.green.saturating_add(other.green),
            red: self.red.saturating_add(other.red),
            black: self.black.saturating_add(other.black),
            gold: self.gold.saturating_add(other.gold),
        }
    }

    pub fn checked_sub(self, other: Self) -> Option<Self> {
        Some(Self {
            white: self.white.checked_sub(other.white)?,
            blue: self.blue.checked_sub(other.blue)?,
            green: self.green.checked_sub(other.green)?,
            red: self.red.checked_sub(other.red)?,
            black: self.black.checked_sub(other.black)?,
            gold: self.gold.checked_sub(other.gold)?,
        })
    }

    /// Whether `self` dominates `need` on every color component (gold ignored).
    pub fn covers_colors(self, need: [u8; 5]) -> bool {
        GemColor::ALL
            .iter()
            .all(|&c| self.color(c) >= need[c.index()])
    }

    pub fn from_colors(counts: [u8; 5]) -> Self {
        Self {
            white: counts[0],
            blue: counts[1],
            green: counts[2],
            red: counts[3],
            black: counts[4],
            gold: 0,
        }
    }

    pub fn colors_array(self) -> [u8; 5] {
        [self.white, self.blue, self.green, self.red, self.black]
    }

    /// Number of distinct non-zero color piles (ignores gold).
    pub fn distinct_colors(self) -> u8 {
        GemColor::ALL.iter().filter(|&&c| self.color(c) > 0).count() as u8
    }

    pub fn is_zero(self) -> bool {
        self == Self::ZERO
    }
}

impl std::ops::Add for Gems {
    type Output = Self;
    fn add(self, rhs: Self) -> Self {
        self.saturating_add(rhs)
    }
}

impl std::ops::AddAssign for Gems {
    fn add_assign(&mut self, rhs: Self) {
        *self = self.saturating_add(rhs);
    }
}
