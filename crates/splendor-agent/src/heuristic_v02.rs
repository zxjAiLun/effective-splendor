//! Observation-only heuristic candidate. No referee state, hidden reserve or
//! deck order is available here; unknown market refills are not manufactured.
//! See docs/s4-heuristic-v02-design.md, S4.11, for scope and evidence.

use crate::policy::{AgentPolicy, DecisionContext};
use splendor_catalog::{all_nobles, card, CardDef, CardId, GemColor, NobleId, Tier};
use splendor_core::{Action, Gems, Observation};

mod competition;
mod economy;
mod position;
mod projection;
mod targets;
#[cfg(test)]
mod tests;

use competition::*;
use economy::*;
use position::*;
use projection::*;
use targets::*;

pub const HEURISTIC_V02_AGENT_NAME: &str = "splendor-cli-heuristic-v02";
// Development-command compatibility only, NOT a frozen binary identity.
// Release/default/registry changes require a separate evaluation and authority.
pub const HEURISTIC_V02_AGENT_VERSION: &str = "0.2.9";

const TERMINAL_PRIORITY: i64 = 1_000_000;
const VP_WEIGHT: i64 = 1_000;
const SHORTFALL_WEIGHT: i64 = 300;
const BONUS_WEIGHT: i64 = 250;
const READY_WEIGHT: i64 = 500;
const GOLD_WEIGHT: i64 = 150;
const SECURED_WEIGHT: i64 = 500;
const VISIBLE_RESERVE_TEMPO: i64 = 350;
const BLIND_RESERVE_TEMPO: i64 = 500;
const VP_LATE_BONUS: i64 = 2_000;
const ENGINE_WEIGHT: i64 = 120;
const ENGINE_DEMAND_CAP: i64 = 12;
const ENGINE_PER_CARD_CAP: u8 = 3;
const PHASE_LOW: i64 = 4;
const PHASE_SPAN: i64 = 8;
const CHEAP_BUY_ULTRA: i64 = 500;
const CHEAP_BUY_BUILD: i64 = 350;
const CHEAP_READY_ULTRA: i64 = 1_100;
const CHEAP_READY_BUILD: i64 = 700;
const CONVERSION_ULTRA: i64 = 180;
const CONVERSION_BUILD: i64 = 120;
const CONVERSION_CAP: i64 = 8;
const STRANDED_TOKEN_PENALTY: i64 = 850;
const ZERO_NET_TAKE_PENALTY: i64 = 2_000;
const VP_QUADRATIC_WEIGHT: i64 = 500;
const SCORING_READINESS_PER_VP: i64 = 500;
const NOBLE_RACE_DISTANCE_MAX: i64 = 4;
const NOBLE_RACE_PROGRESS_WEIGHT: i64 = 800;
const NOBLE_RACE_THREE_VP_WEIGHT: i64 = 1_200;
const NOBLE_RACE_RESERVED_WEIGHT: i64 = 1_200;
const NOBLE_RACE_RESERVED_EFFICIENCY_MIN: i64 = 600;
const RESERVE_COUNT_THRESHOLD: usize = 2;
const RESERVE_COUNT_GUARD: i64 = 500;
const NOBLE_BUILD_DISTANCE_MAX: i64 = 6;
const NOBLE_BUILD_PROGRESS_WEIGHT: i64 = 200;
const FINISH_PRESSURE_RESERVE_PENALTY: i64 = 600;

#[derive(Default)]
pub struct HeuristicAgentPolicyV02;

impl HeuristicAgentPolicyV02 {
    pub fn new() -> Self {
        Self
    }
}

impl AgentPolicy for HeuristicAgentPolicyV02 {
    type Error = std::convert::Infallible;
    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let scores = heuristic_v02_term_scores(&context.observation, context.legal_actions);
        let best_score = scores
            .iter()
            .map(HeuristicV02Terms::total)
            .max()
            .unwrap_or(i64::MIN);
        let best: Vec<_> = scores
            .iter()
            .enumerate()
            .filter_map(|(i, terms)| (terms.total() == best_score).then_some(i))
            .collect();
        let idx = if best.len() == 1 {
            best[0]
        } else {
            best[context.rng.index(best.len())]
        };
        Ok(context.legal_actions[idx])
    }
}

/// Signed, additive trace terms; field names remain compatible with consumers.
/// `terminal_lead` distinguishes a last-seat strict win (1,000,000) from a
/// trigger not refuted by public responses (100,000). The latter is NOT safe
/// against unknown refills or blind reserves. In an already-triggered round,
/// 1 is only a public-reply tie-break for positive-VP buys with later seats.
/// Zero does not forbid a finish.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub struct HeuristicV02Terms {
    pub terminal_lead: i64,
    pub immediate_prestige: i64,
    pub engine_value: i64,
    pub cheap_engine_buy: i64,
    pub cheap_ready: i64,
    pub conversion_value: i64,
    /// Compatibility-only zero field. There is no bomb recognition/scoring.
    pub bomb_reserve: i64,
    pub rotation_guard: i64,
    pub vp_efficiency: i64,
    pub target_shortfall: i64,
    pub useful_discount: i64,
    /// Includes half the change in the best known value/preparation-time plan.
    pub new_affordable_target: i64,
    pub gold_liquidity: i64,
    /// Target protection plus genuine reduction of an opponent's public finish.
    pub secured_target: i64,
    pub reserve_tempo: i64,
    /// Contestable near-noble progress; also the small ChooseNoble tie-break.
    pub noble_race_progress: i64,
    pub noble_race_three_vp: i64,
    pub noble_race_reserved: i64,
    pub reserve_count_guard: i64,
    pub scoring_readiness: i64,
    pub noble_build: i64,
    /// Foregone-buy opportunity cost and public finish pressure, not raw deficit.
    pub race_reserve_penalty: i64,
    pub final_round_card_cost: i64,
}

impl HeuristicV02Terms {
    pub fn total(&self) -> i64 {
        self.terminal_lead
            + self.immediate_prestige
            + self.engine_value
            + self.cheap_engine_buy
            + self.cheap_ready
            + self.conversion_value
            + self.bomb_reserve
            + self.rotation_guard
            + self.vp_efficiency
            + self.target_shortfall
            + self.useful_discount
            + self.new_affordable_target
            + self.gold_liquidity
            + self.secured_target
            + self.reserve_tempo
            + self.noble_race_progress
            + self.noble_race_three_vp
            + self.noble_race_reserved
            + self.reserve_count_guard
            + self.scoring_readiness
            + self.noble_build
            + self.race_reserve_penalty
            + self.final_round_card_cost
    }
}

/// Score server-certified legal actions without restricting their set. Shared
/// alternatives come from the observation, never from the supplied action slice.
pub fn heuristic_v02_term_scores(obs: &Observation, actions: &[Action]) -> Vec<HeuristicV02Terms> {
    let position = PositionContext::new(obs);
    actions
        .iter()
        .map(|&action| {
            let projected = ActionProjection::new(&position, action);
            if let Some(terminal) = terminal_terms(&position, &projected) {
                return terminal;
            }
            let plan = compare_targets(&position, &projected);
            let mut terms = economic_terms(&position, &projected, &plan);
            score_competition(&position, &projected, &plan, &mut terms);
            terms
        })
        .collect()
}
