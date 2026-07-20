use serde::de::{self, Deserializer};
use serde::{Deserialize, Serialize};
use splendor_core::{Action, GameResult, PlayerId, Ruleset, TerminalReason};

/// Fixed replay document format identifier.
pub const REPLAY_FORMAT: &str = "effective-splendor-replay";
/// Replay schema version implemented by this crate.
pub const REPLAY_VERSION: u32 = 1;
/// The only ruleset the v1 verifier understands.
pub const SUPPORTED_RULESET_ID: &str = "splendor-base-v1";

/// A 64-character lowercase hex hash copied out of a `FullStateHash`.
///
/// It intentionally does not implement `From<FullStateHash>` via `serde`;
/// callers build it from `FullStateHash::as_str()`. Deserialization is strict:
/// exactly 64 lowercase hex characters.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct ReplayHash(String);

impl ReplayHash {
    /// Build from an engine hash string, validating shape.
    pub fn from_hash_str(value: &str) -> Result<Self, String> {
        validate_hash(value)?;
        Ok(Self(value.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for ReplayHash {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn validate_hash(value: &str) -> Result<(), String> {
    if value.len() != 64 {
        return Err(format!("expected 64 hex chars, got {}", value.len()));
    }
    if !value
        .bytes()
        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("expected only lowercase hex digits".to_string());
    }
    Ok(())
}

impl<'de> Deserialize<'de> for ReplayHash {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = String::deserialize(deserializer)?;
        validate_hash(&raw).map_err(de::Error::custom)?;
        Ok(Self(raw))
    }
}

/// Owned ruleset DTO for replay files. Distinct from the runtime `Ruleset`,
/// which carries `&'static str` fields unsuitable for owned deserialization.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayRulesetV1 {
    pub id: String,
    pub catalog_version: String,
    pub min_players: u8,
    pub max_players: u8,
    pub prestige_to_end: u8,
    pub max_tokens: u8,
    pub max_reserved: u8,
    pub market_slots_per_tier: u8,
    pub gold_tokens: u8,
    pub color_tokens_by_players: [u8; 3],
    pub noble_extra: u8,
}

impl ReplayRulesetV1 {
    pub fn from_ruleset(ruleset: &Ruleset) -> Self {
        Self {
            id: ruleset.id.0.to_string(),
            catalog_version: ruleset.catalog_version.to_string(),
            min_players: ruleset.min_players,
            max_players: ruleset.max_players,
            prestige_to_end: ruleset.prestige_to_end,
            max_tokens: ruleset.max_tokens,
            max_reserved: ruleset.max_reserved,
            market_slots_per_tier: ruleset.market_slots_per_tier,
            gold_tokens: ruleset.gold_tokens,
            color_tokens_by_players: ruleset.color_tokens_by_players,
            noble_extra: ruleset.noble_extra,
        }
    }
}

/// Terminal reason DTO mirroring `splendor_core::TerminalReason`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplayTerminalReason {
    PrestigeThreshold,
    Stalemate,
}

impl From<TerminalReason> for ReplayTerminalReason {
    fn from(reason: TerminalReason) -> Self {
        match reason {
            TerminalReason::PrestigeThreshold => Self::PrestigeThreshold,
            TerminalReason::Stalemate => Self::Stalemate,
        }
    }
}

impl From<ReplayTerminalReason> for TerminalReason {
    fn from(reason: ReplayTerminalReason) -> Self {
        match reason {
            ReplayTerminalReason::PrestigeThreshold => Self::PrestigeThreshold,
            ReplayTerminalReason::Stalemate => Self::Stalemate,
        }
    }
}

/// Owned game-result DTO mirroring `splendor_core::GameResult`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayGameResultV1 {
    pub scores: Vec<u8>,
    pub ranks: Vec<u8>,
    pub winners: Vec<u8>,
    pub reason: ReplayTerminalReason,
}

impl ReplayGameResultV1 {
    pub fn from_result(result: &GameResult) -> Self {
        Self {
            scores: result.scores.clone(),
            ranks: result.ranks.clone(),
            winners: result.winners.iter().map(|p| p.0).collect(),
            reason: result.reason.into(),
        }
    }

    /// Whether this DTO describes the same outcome as a runtime `GameResult`.
    pub fn matches(&self, result: &GameResult) -> bool {
        self.scores == result.scores
            && self.ranks == result.ranks
            && self.winners == result.winners.iter().map(|p| p.0).collect::<Vec<_>>()
            && TerminalReason::from(self.reason) == result.reason
    }
}

/// One recorded ply.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayStepV1 {
    pub ply: u32,
    pub actor: PlayerId,
    pub action: Action,
    pub state_hash_before: ReplayHash,
    pub state_hash_after: ReplayHash,
}

/// A complete, self-describing replay document.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayV1 {
    pub format: String,
    pub version: u32,
    pub engine_version: String,

    pub ruleset: ReplayRulesetV1,
    pub ruleset_fingerprint: ReplayHash,

    pub player_count: u8,
    pub seed: u64,

    pub initial_state_hash: ReplayHash,
    pub steps: Vec<ReplayStepV1>,

    pub final_state_hash: ReplayHash,
    pub result: ReplayGameResultV1,
}
