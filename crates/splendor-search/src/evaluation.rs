//! Frozen static evaluator (`StaticEvaluatorV1`).
//!
//! Pure integer arithmetic only. The weights below are frozen at C1
//! acceptance: later strength-benchmark failures must not be fixed by tuning
//! these coefficients or lowering gates.

use splendor_catalog::{all_nobles, card};
use splendor_core::{FullPlayerState, FullState, GemColor};

use crate::error::SearchError;

/// Frozen terminal rank unit: terminal ranking must dominate any
/// non-terminal material difference.
pub const TERMINAL_RANK_UNIT: i64 = 1_000_000_000_000;

const PRESTIGE_WEIGHT: i64 = 100_000_000;
const BONUS_WEIGHT: i64 = 2_000_000;
const PURCHASED_CARD_WEIGHT: i64 = 250_000;
const COLORED_TOKEN_WEIGHT: i64 = 20_000;
const GOLD_TOKEN_WEIGHT: i64 = 40_000;
const RESERVED_CARD_WEIGHT: i64 = 10_000;
const AFFORDABLE_CARD_WEIGHT: i64 = 100_000;
const MAX_AFFORDABLE_PRESTIGE_WEIGHT: i64 = 5_000_000;
const NOBLE_PROGRESS_WEIGHT: i64 = 10_000;

/// Per-noble contribution ceiling: `max(25 - deficit, 0)`.
const NOBLE_CONTRIBUTION_CEILING: i64 = 25;

/// Frozen terminal base for a dense rank produced by the core engine.
///
/// Rank 0 (winner, shared winners included) maps to `+TERMINAL_RANK_UNIT`;
/// rank `r > 0` maps to `-(r) * TERMINAL_RANK_UNIT`.
pub fn terminal_rank_base(rank: u8) -> i64 {
    if rank == 0 {
        TERMINAL_RANK_UNIT
    } else {
        -i64::from(rank) * TERMINAL_RANK_UNIT
    }
}

/// Frozen static evaluator for search v1.
pub struct StaticEvaluatorV1;

impl StaticEvaluatorV1 {
    /// Utility vector in seat/player-ID order; length equals player count.
    ///
    /// Non-terminal states use relative progress:
    /// `utility_i = progress_i * player_count - sum(progress)`, which is
    /// zero-sum for every player count. Terminal states add the frozen
    /// terminal rank base on top of the same relative progress, reusing the
    /// ranks already computed by the core engine (including stalemate and
    /// shared winners) without inventing new rules.
    pub fn utilities(state: &FullState) -> Result<Vec<i64>, SearchError> {
        let player_count = state.players.len();
        let progress: Vec<i64> = state
            .players
            .iter()
            .map(|player| progress_for(state, player))
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
}

/// Frozen integer progress score for one player.
fn progress_for(state: &FullState, player: &FullPlayerState) -> i64 {
    let prestige = i64::from(player.prestige);
    let total_permanent_bonuses: i64 = player.bonuses.iter().map(|&b| i64::from(b)).sum();
    let purchased_card_count = player.purchased.len() as i64;
    let colored_token_count = i64::from(player.tokens.total_colors());
    let gold_token_count = i64::from(player.tokens.gold);
    let reserved_card_count = player.reserved.len() as i64;

    // Affordable cards: current market cards plus this player's own reserved
    // cards (never other players' reserves).
    let mut affordable_card_count = 0i64;
    let mut max_affordable_prestige = 0i64;
    let mut consider = |cost: [u8; 5], prestige: u8| {
        if player.can_afford(cost) {
            affordable_card_count += 1;
            max_affordable_prestige = max_affordable_prestige.max(i64::from(prestige));
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

    // Noble progress over nobles still on the board.
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

    prestige * PRESTIGE_WEIGHT
        + total_permanent_bonuses * BONUS_WEIGHT
        + purchased_card_count * PURCHASED_CARD_WEIGHT
        + colored_token_count * COLORED_TOKEN_WEIGHT
        + gold_token_count * GOLD_TOKEN_WEIGHT
        + reserved_card_count * RESERVED_CARD_WEIGHT
        + affordable_card_count * AFFORDABLE_CARD_WEIGHT
        + max_affordable_prestige * MAX_AFFORDABLE_PRESTIGE_WEIGHT
        + noble_progress * NOBLE_PROGRESS_WEIGHT
}
