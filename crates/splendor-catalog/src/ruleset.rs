use serde::{Deserialize, Serialize};

/// Identifies a rules + catalog combination for replay compatibility.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct RulesetId(pub &'static str);

/// Base 2–4 player Splendor, no expansions.
pub const RULESET_BASE_V1: RulesetId = RulesetId("splendor-base-v1");

/// Runtime rules parameters (player-count dependent values computed by core).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Ruleset {
    pub id: RulesetId,
    pub catalog_version: &'static str,
    pub min_players: u8,
    pub max_players: u8,
    pub prestige_to_end: u8,
    pub max_tokens: u8,
    pub max_reserved: u8,
    pub market_slots_per_tier: u8,
    pub gold_tokens: u8,
    /// Tokens of each non-gold color for 2 / 3 / 4 players.
    pub color_tokens_by_players: [u8; 3],
    /// Nobles dealt = player_count + noble_extra.
    pub noble_extra: u8,
}

impl Ruleset {
    pub fn base_v1() -> Self {
        Self {
            id: RULESET_BASE_V1,
            catalog_version: crate::CATALOG_VERSION,
            min_players: 2,
            max_players: 4,
            prestige_to_end: 15,
            max_tokens: 10,
            max_reserved: 3,
            market_slots_per_tier: 4,
            gold_tokens: 5,
            // Official: 4 / 5 / 7 for 2 / 3 / 4 players.
            color_tokens_by_players: [4, 5, 7],
            noble_extra: 1,
        }
    }

    pub fn color_token_count(self, player_count: u8) -> u8 {
        match player_count {
            2 => self.color_tokens_by_players[0],
            3 => self.color_tokens_by_players[1],
            4 => self.color_tokens_by_players[2],
            _ => panic!("unsupported player count: {player_count}"),
        }
    }

    pub fn noble_count(self, player_count: u8) -> u8 {
        player_count + self.noble_extra
    }
}
