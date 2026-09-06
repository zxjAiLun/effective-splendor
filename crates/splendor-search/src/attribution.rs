//! Research-only StaticEvaluator information attribution module (M44A).
//!
//! Partitions the 9 frozen non-terminal terms into 4 semantic information families:
//! - F1 (REALIZED_SCORE): prestige
//! - F2 (PERMANENT_ENGINE): total permanent bonuses, purchased card count, noble progress
//! - F3 (LIQUIDITY_OPTIONALITY): colored tokens, gold tokens, reserved card count
//! - F4 (IMMEDIATE_CONVERTIBILITY): affordable card count, maximum affordable prestige
//!
//! Preserves exact integer coefficients and terminal rank base (+/- 1,000,000,000,000).
//! Guaranteed exact integer equality: FULL progress == F1 + F2 + F3 + F4.

use serde::{Deserialize, Serialize};
use splendor_catalog::{all_nobles, card};
use splendor_core::{FullPlayerState, FullState, GemColor};

use crate::error::SearchError;
use crate::evaluation::terminal_rank_base;

const PRESTIGE_WEIGHT: i64 = 100_000_000;
const BONUS_WEIGHT: i64 = 2_000_000;
const PURCHASED_CARD_WEIGHT: i64 = 250_000;
const COLORED_TOKEN_WEIGHT: i64 = 20_000;
const GOLD_TOKEN_WEIGHT: i64 = 40_000;
const RESERVED_CARD_WEIGHT: i64 = 10_000;
const AFFORDABLE_CARD_WEIGHT: i64 = 100_000;
const MAX_AFFORDABLE_PRESTIGE_WEIGHT: i64 = 5_000_000;
const NOBLE_PROGRESS_WEIGHT: i64 = 10_000;

const NOBLE_CONTRIBUTION_CEILING: i64 = 25;

/// Information attribution profile for M44A.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AttributionProfile {
    Full,
    DropScore,
    DropEngine,
    DropLiquidity,
    DropConvertibility,
    ZeroProgress,
    OnlyScore,
    OnlyEngine,
    OnlyLiquidity,
    OnlyConvertibility,
    // M44B Subfamily Profiles
    DropCoreEngine,
    DropNobleProgress,
    OnlyCoreEngine,
    OnlyNobleProgress,
}

impl std::str::FromStr for AttributionProfile {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_lowercase().replace('-', "_").as_str() {
            "full" => Ok(Self::Full),
            "drop_score" => Ok(Self::DropScore),
            "drop_engine" => Ok(Self::DropEngine),
            "drop_liquidity" => Ok(Self::DropLiquidity),
            "drop_convertibility" => Ok(Self::DropConvertibility),
            "zero_progress" => Ok(Self::ZeroProgress),
            "only_score" => Ok(Self::OnlyScore),
            "only_engine" => Ok(Self::OnlyEngine),
            "only_liquidity" => Ok(Self::OnlyLiquidity),
            "only_convertibility" => Ok(Self::OnlyConvertibility),
            "drop_core_engine" => Ok(Self::DropCoreEngine),
            "drop_noble_progress" => Ok(Self::DropNobleProgress),
            "only_core_engine" => Ok(Self::OnlyCoreEngine),
            "only_noble_progress" => Ok(Self::OnlyNobleProgress),
            other => Err(format!("unknown attribution profile `{other}`")),
        }
    }
}

/// Exact integer contributions from the 4 information families and F2 subfamilies for one player.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct FamilyProgress {
    pub f1_score: i64,
    pub f2_engine: i64,
    pub f3_liquidity: i64,
    pub f4_convertibility: i64,
    pub e1_core_engine: i64,
    pub e2_noble_progress: i64,
}

impl FamilyProgress {
    /// Exact integer sum of all four families.
    #[inline]
    pub fn total(&self) -> i64 {
        self.f1_score + self.f2_engine + self.f3_liquidity + self.f4_convertibility
    }

    /// Evaluated progress under a specific attribution profile.
    #[inline]
    pub fn for_profile(&self, profile: AttributionProfile) -> i64 {
        match profile {
            AttributionProfile::Full => self.total(),
            AttributionProfile::DropScore => self.f2_engine + self.f3_liquidity + self.f4_convertibility,
            AttributionProfile::DropEngine => self.f1_score + self.f3_liquidity + self.f4_convertibility,
            AttributionProfile::DropLiquidity => self.f1_score + self.f2_engine + self.f4_convertibility,
            AttributionProfile::DropConvertibility => self.f1_score + self.f2_engine + self.f3_liquidity,
            AttributionProfile::ZeroProgress => 0,
            AttributionProfile::OnlyScore => self.f1_score,
            AttributionProfile::OnlyEngine => self.f2_engine,
            AttributionProfile::OnlyLiquidity => self.f3_liquidity,
            AttributionProfile::OnlyConvertibility => self.f4_convertibility,
            AttributionProfile::DropCoreEngine => self.f1_score + self.e2_noble_progress + self.f3_liquidity + self.f4_convertibility,
            AttributionProfile::DropNobleProgress => self.f1_score + self.e1_core_engine + self.f3_liquidity + self.f4_convertibility,
            AttributionProfile::OnlyCoreEngine => self.e1_core_engine,
            AttributionProfile::OnlyNobleProgress => self.e2_noble_progress,
        }
    }
}

/// Compute exact four-family progress breakdown for one player.
pub fn family_progress_for(state: &FullState, player: &FullPlayerState) -> FamilyProgress {
    // F1: Realized score
    let prestige = i64::from(player.prestige);
    let f1_score = prestige * PRESTIGE_WEIGHT;

    // F2: Permanent engine
    let total_permanent_bonuses: i64 = player.bonuses.iter().map(|&b| i64::from(b)).sum();
    let purchased_card_count = player.purchased.len() as i64;

    let mut noble_progress = 0i64;
    for &noble_id in &state.nobles {
        let def = &all_nobles()[noble_id.index()];
        let mut deficit = 0i64;
        for color in GemColor::ALL {
            deficit += i64::from(
                def.requirements[color.index()].saturating_sub(player.bonuses[color.index()]),
            );
        }
        noble_progress += (NOBLE_CONTRIBUTION_CEILING - deficit).max(0);
    }

    let e1_core_engine = total_permanent_bonuses * BONUS_WEIGHT
        + purchased_card_count * PURCHASED_CARD_WEIGHT;
    let e2_noble_progress = noble_progress * NOBLE_PROGRESS_WEIGHT;
    let f2_engine = e1_core_engine + e2_noble_progress;

    // F3: Liquidity and optionality
    let colored_token_count = i64::from(player.tokens.total_colors());
    let gold_token_count = i64::from(player.tokens.gold);
    let reserved_card_count = player.reserved.len() as i64;

    let f3_liquidity = colored_token_count * COLORED_TOKEN_WEIGHT
        + gold_token_count * GOLD_TOKEN_WEIGHT
        + reserved_card_count * RESERVED_CARD_WEIGHT;

    // F4: Immediate convertibility
    let mut affordable_card_count = 0i64;
    let mut max_affordable_prestige = 0i64;
    let mut consider = |cost: [u8; 5], pres: u8| {
        if player.can_afford(cost) {
            affordable_card_count += 1;
            max_affordable_prestige = max_affordable_prestige.max(i64::from(pres));
        }
    };
    for card_id in state.market.iter().flat_map(|row| row.iter().flatten()) {
        let def = card(*card_id);
        consider(def.cost, def.prestige);
    }
    for reserved in &player.reserved {
        let def = card(reserved.card);
        consider(def.cost, def.prestige);
    }

    let f4_convertibility = affordable_card_count * AFFORDABLE_CARD_WEIGHT
        + max_affordable_prestige * MAX_AFFORDABLE_PRESTIGE_WEIGHT;

    FamilyProgress {
        f1_score,
        f2_engine,
        f3_liquidity,
        f4_convertibility,
        e1_core_engine,
        e2_noble_progress,
    }
}

/// Isolated research evaluator with 4-family attribution mask.
pub struct StaticEvaluatorAttributionV1;

impl StaticEvaluatorAttributionV1 {
    /// Zero-sum relative utilities under the selected attribution profile.
    pub fn utilities(
        state: &FullState,
        profile: AttributionProfile,
    ) -> Result<Vec<i64>, SearchError> {
        let player_count = state.players.len();
        let family_progress: Vec<FamilyProgress> = state
            .players
            .iter()
            .map(|player| family_progress_for(state, player))
            .collect();
        let progress: Vec<i64> = family_progress
            .iter()
            .map(|fp| fp.for_profile(profile))
            .collect();
        let total: i64 = progress.iter().sum();
        let relative: Vec<i64> = progress
            .iter()
            .map(|&p| p * player_count as i64 - total)
            .collect();

        if !state.is_terminal() {
            return Ok(relative);
        }

        let result = state
            .result
            .as_ref()
            .ok_or_else(|| SearchError::Engine("terminal state has no game result".into()))?;
        if result.ranks.len() != player_count {
            return Err(SearchError::Engine(format!(
                "terminal ranks length {} does not match player count {}",
                result.ranks.len(),
                player_count
            )));
        }

        Ok(result
            .ranks
            .iter()
            .zip(relative)
            .map(|(&rank, relative_progress)| terminal_rank_base(rank) + relative_progress)
            .collect())
    }

    /// Extract family progress breakdown for all players.
    pub fn family_progress_for_all(state: &FullState) -> Vec<FamilyProgress> {
        state.players.iter().map(|p| family_progress_for(state, p)).collect()
    }
}
