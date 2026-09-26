//! Independent observation-only heuristic v0.2 candidate.
//!
//! All action families share one score scale. This module never accesses a
//! referee state, a deck order, or a hidden opponent reserve. A market refill
//! is deliberately NOT predicted after a buy/reservation.

use splendor_catalog::{all_nobles, card, CardDef, CardId, GemColor, NobleId, Tier};
use splendor_core::{Action, Gems, Observation};

use crate::policy::{AgentPolicy, DecisionContext};

pub const HEURISTIC_V02_AGENT_NAME: &str = "splendor-cli-heuristic-v02";
pub const HEURISTIC_V02_AGENT_VERSION: &str = "0.2.7";

const TERMINAL_PRIORITY: i64 = 1_000_000;
const VP_WEIGHT: i64 = 1_000;
const SHORTFALL_WEIGHT: i64 = 300;
const BONUS_WEIGHT: i64 = 250;
const READY_WEIGHT: i64 = 500;
const GOLD_WEIGHT: i64 = 150;
const SECURED_WEIGHT: i64 = 500;
const VISIBLE_RESERVE_TEMPO: i64 = 350;
const BLIND_RESERVE_TEMPO: i64 = 500;

// --- v0.2.1 phase awareness ---------------------------------------------
//
// Splendor has two regimes: an early/mid *construction* phase where a
// permanent bonus has high option value even at zero VP, and a late *scoring*
// phase where reaching 15 fast is what matters. v0.2.0 used one static scale
// and therefore refused cheap engine cards it should have grabbed early (see
// the seed 9_250_000 ply 4 case). v0.2.1 blends the two regimes with a single
// observation-only phase scalar in per-mille [0, 1000]: 0 = pure construction,
// 1000 = pure scoring. The scalar is derived only from public prestige and the
// public end-game flag — never from hidden state.

/// Extra weight added to each realized VP as the game approaches scoring phase
/// (per full-scoring; scaled by the phase scalar).
const VP_LATE_BONUS: i64 = 2_000;
/// Value of the permanent bonus gained by a purchase, per unit of remaining
/// board demand for that color, in pure construction phase (tapers to 0).
const ENGINE_WEIGHT: i64 = 120;
/// Board demand for the gained color is capped here so one purchase cannot be
/// scored as if it unlocked the entire board.
const ENGINE_DEMAND_CAP: i64 = 12;
/// Per-card contribution cap when summing board color demand.
const ENGINE_PER_CARD_CAP: u8 = 3;
/// Lead prestige at/below which the game is treated as pure construction.
const PHASE_LOW: i64 = 4;
/// Lead-prestige span from construction to full scoring.
const PHASE_SPAN: i64 = 8;

// v0.2.2: phase is determined by *own* permanent discounts, with an
// observation-only emergency scoring override near the public finish.
const CHEAP_BUY_ULTRA: i64 = 500; // multiplied by 7 - printed T1 cost (3/4)
const CHEAP_BUY_BUILD: i64 = 350;
const CHEAP_READY_ULTRA: i64 = 1_100;
const CHEAP_READY_BUILD: i64 = 700;
const CONVERSION_ULTRA: i64 = 180;
const CONVERSION_BUILD: i64 = 120;
const CONVERSION_CAP: i64 = 8;
const BOMB_7_FOR_4: i64 = 2_400;
const BOMB_6_FOR_3: i64 = 1_700; // tier TWO in this catalog
const BOMB_7_PLUS_3_FOR_5: i64 = 900;
const STRANDED_TOKEN_PENALTY: i64 = 850;
const ZERO_NET_TAKE_PENALTY: i64 = 2_000;
const VP_EFFICIENCY_WEIGHT: i64 = 1_200;
// v0.2.5: value improved readiness for ONE currently known scoring card,
// not the sum of mutually exclusive purchases supported by the same tokens.
const SCORING_READINESS_PER_VP: i64 = 500;

// v0.2.3: explicitly pursue simultaneous near-noble races and reduce
// additional early reservations once two cards are already held.
const NOBLE_RACE_DISTANCE_MAX: i64 = 4;
const NOBLE_RACE_MIN_COUNT: usize = 2;
const NOBLE_RACE_PROGRESS_WEIGHT: i64 = 800;
const NOBLE_RACE_THREE_VP_WEIGHT: i64 = 1_200;
const NOBLE_RACE_RESERVED_WEIGHT: i64 = 1_200;
const NOBLE_RACE_RESERVED_EFFICIENCY_MIN: i64 = 600;
const RESERVE_COUNT_THRESHOLD: usize = 2;
const RESERVE_COUNT_GUARD: i64 = 500;

// v0.2.4 (single factor vs v0.2.3): a near noble only counts as a race target
// when it is still WINNABLE — the opponent's own missing-bonus distance must
// not be strictly smaller. Both sides' bonuses are public observation data;
// the trigger (>=2 near nobles) and all constants are unchanged.

// v0.2.7: Reachable Target Route Locking with Dynamic Tempo Balance.
// Softens low-VP suppression from -2000 to -600, exempts 1-VP cards that contribute
// to high-cost target colors, enforces strict infrastructure requirements for single-color
// high-cost cards (>=2 discount), and provides reserve tempo bonuses for promising 3+ VP cards.
const LOW_VP_RUSH_SUPPRESSION: i64 = -600;
const HIGH_VP_RUSH_EXECUTION_BONUS: i64 = 1_000;
const HIGH_VP_RUSH_PROTECT_BONUS: i64 = 800;
const TYCOON_SCORING_CARD_BONUS: i64 = 1_500;
const TYCOON_IMMEDIATE_CLAIM_BONUS: i64 = 2_500;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum DevelopmentPhase {
    Ultra, // own permanent discounts 0..=4
    Build, // own permanent discounts 5..=8
    Score, // >8, public 12+ VP race, or publicly triggered endgame
}

fn development_phase(obs: &Observation, own: &OwnProjection) -> DevelopmentPhase {
    let lead_prestige = obs
        .public
        .players
        .iter()
        .map(|p| p.prestige)
        .max()
        .unwrap_or(0);
    if obs.public.end_game_triggered || lead_prestige >= 12 {
        return DevelopmentPhase::Score;
    }
    match own.bonuses.iter().map(|&b| u16::from(b)).sum::<u16>() {
        0..=4 => DevelopmentPhase::Ultra,
        5..=8 => DevelopmentPhase::Build,
        _ => DevelopmentPhase::Score,
    }
}

fn high_value_t2(def: &CardDef) -> bool {
    def.tier == Tier::Two
        && ((def.prestige == 2 && def.total_cost() == 5)
            || (def.prestige == 3 && def.total_cost() == 6))
}

/// Actual catalog shapes, not a fictitious tier-three 6-mono/3VP card.
fn bomb_reserve_value(def: &CardDef) -> i64 {
    let mut positive: Vec<u8> = def.cost.into_iter().filter(|&v| v > 0).collect();
    positive.sort_unstable();
    match (def.tier, def.prestige, positive.as_slice()) {
        (Tier::Three, 4, [7]) => BOMB_7_FOR_4,
        (Tier::Two, 3, [6]) => BOMB_6_FOR_3,
        (Tier::Three, 5, [3, 7]) => BOMB_7_PLUS_3_FOR_5,
        _ => 0,
    }
}

fn effective_cost(def: &CardDef, bonuses: [u8; 5]) -> i64 {
    GemColor::ALL
        .iter()
        .map(|&c| i64::from(def.cost[c.index()].saturating_sub(bonuses[c.index()])))
        .sum()
}

fn reserve_efficiency(def: &CardDef, bonuses: [u8; 5]) -> i64 {
    i64::from(def.prestige) * 1_000 / (1 + effective_cost(def, bonuses))
}

fn noble_distance(noble_id: NobleId, bonuses: &[u8; 5]) -> i64 {
    let noble = &all_nobles()[noble_id.index()];
    GemColor::ALL
        .iter()
        .map(|&color| i64::from(noble.requires(color).saturating_sub(bonuses[color.index()])))
        .sum()
}

fn near_noble_ids(obs: &Observation, bonuses: &[u8; 5]) -> Vec<NobleId> {
    obs.public
        .nobles
        .iter()
        .copied()
        .filter(|&id| noble_distance(id, bonuses) <= NOBLE_RACE_DISTANCE_MAX)
        .collect()
}

fn opponent_min_distance(obs: &Observation, noble_id: NobleId) -> i64 {
    obs.public
        .players
        .iter()
        .filter(|p| p.id != obs.viewer)
        .map(|p| noble_distance(noble_id, &p.bonuses))
        .min()
        .unwrap_or(i64::MAX)
}

fn winnable_near_nobles(obs: &Observation, own_bonuses: &[u8; 5]) -> Vec<NobleId> {
    near_noble_ids(obs, own_bonuses)
        .into_iter()
        .filter(|&id| noble_distance(id, own_bonuses) <= opponent_min_distance(obs, id))
        .collect()
}

#[derive(Clone, Copy)]
struct OwnProjection {
    tokens: Gems,
    bonuses: [u8; 5],
    prestige: u8,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum MidLateRoute {
    HighCostRush,
    Tycoon { target: NobleId },
    Balanced,
}

fn is_reachable_rush_target(c: &CardDef, own: &OwnProjection, is_reserved: bool) -> bool {
    if c.prestige < 3 {
        return false;
    }
    let max_deficit = if is_reserved { 5 } else { 4 };
    if deficit(c, own) > max_deficit {
        return false;
    }
    // High single-color demand check: if a card demands 6+ in any single color,
    // we must already possess at least 2 permanent discounts in that color.
    // This prevents locking impossible cards like 7-black with 0 black discount.
    for color in GemColor::ALL {
        if c.cost[color.index()] >= 6 && own.bonuses[color.index()] < 2 {
            return false;
        }
    }
    true
}

fn has_viable_rush_target(obs: &Observation, own: &OwnProjection) -> bool {
    for tier in [Tier::Two, Tier::Three] {
        for slot in 0..4 {
            if let Some(cid) = obs.public.market[tier.index()][slot] {
                let c = card(cid);
                if is_reachable_rush_target(c, own, false) {
                    return true;
                }
            }
        }
    }
    for r in &obs.private.reserved {
        let c = card(r.card);
        if is_reachable_rush_target(c, own, true) {
            return true;
        }
    }
    false
}

fn rush_needed_colors(obs: &Observation, own: &OwnProjection) -> [bool; 5] {
    let mut needed = [false; 5];
    for tier in [Tier::Two, Tier::Three] {
        for slot in 0..4 {
            if let Some(cid) = obs.public.market[tier.index()][slot] {
                let c = card(cid);
                if is_reachable_rush_target(c, own, false) {
                    for color in GemColor::ALL {
                        if c.cost[color.index()] > own.bonuses[color.index()] {
                            needed[color.index()] = true;
                        }
                    }
                }
            }
        }
    }
    for r in &obs.private.reserved {
        let c = card(r.card);
        if is_reachable_rush_target(c, own, true) {
            for color in GemColor::ALL {
                if c.cost[color.index()] > own.bonuses[color.index()] {
                    needed[color.index()] = true;
                }
            }
        }
    }
    needed
}

fn find_tycoon_target(obs: &Observation, bonuses: &[u8; 5]) -> Option<NobleId> {
    let winnable = winnable_near_nobles(obs, bonuses);
    let mut best: Option<(NobleId, i64)> = None;
    for nid in winnable {
        let dist = noble_distance(nid, bonuses);
        if dist <= 2 {
            if best.map_or(true, |(_, d)| dist < d) {
                best = Some((nid, dist));
            }
        } else if dist <= 3 {
            let noble = &all_nobles()[nid.index()];
            let mut has_scoring_card = false;
            for tier in Tier::ALL {
                for slot in 0..4 {
                    if let Some(cid) = obs.public.market[tier.index()][slot] {
                        let c = card(cid);
                        if c.prestige >= 1 && noble.requires(c.bonus) > bonuses[c.bonus.index()] {
                            has_scoring_card = true;
                            break;
                        }
                    }
                }
                if has_scoring_card {
                    break;
                }
            }
            if !has_scoring_card {
                for r in &obs.private.reserved {
                    let c = card(r.card);
                    if c.prestige >= 1 && noble.requires(c.bonus) > bonuses[c.bonus.index()] {
                        has_scoring_card = true;
                        break;
                    }
                }
            }
            if has_scoring_card && best.map_or(true, |(_, d)| dist < d) {
                best = Some((nid, dist));
            }
        }
    }
    best.map(|(nid, _)| nid)
}

#[derive(Default, Clone, Debug)]
pub struct HeuristicAgentPolicyV02 {
    route: Option<MidLateRoute>,
}

impl HeuristicAgentPolicyV02 {
    pub fn new() -> Self {
        Self { route: None }
    }

    pub fn current_route(&self) -> Option<MidLateRoute> {
        self.route
    }

    pub fn set_route(&mut self, route: Option<MidLateRoute>) {
        self.route = route;
    }

    pub fn update_route(&mut self, obs: &Observation) {
        let me_player = obs
            .public
            .players
            .iter()
            .find(|p| p.id == obs.viewer)
            .expect("viewer is a valid player");
        let me = OwnProjection {
            tokens: me_player.tokens,
            bonuses: me_player.bonuses,
            prestige: me_player.prestige,
        };
        let discounts: u16 = me.bonuses.iter().map(|&x| u16::from(x)).sum();
        let lead_prestige = obs
            .public
            .players
            .iter()
            .map(|p| p.prestige)
            .max()
            .unwrap_or(0);
        let in_score = obs.public.end_game_triggered || lead_prestige >= 12 || discounts >= 9;

        if !in_score {
            self.route = None;
            return;
        }

        match self.route {
            None => {
                if has_viable_rush_target(obs, &me) {
                    self.route = Some(MidLateRoute::HighCostRush);
                } else if let Some(target) = find_tycoon_target(obs, &me.bonuses) {
                    self.route = Some(MidLateRoute::Tycoon { target });
                } else {
                    self.route = Some(MidLateRoute::Balanced);
                }
            }
            Some(MidLateRoute::HighCostRush) => {
                if !has_viable_rush_target(obs, &me) {
                    self.route = Some(MidLateRoute::Balanced);
                }
            }
            Some(MidLateRoute::Tycoon { target }) => {
                if !obs.public.nobles.contains(&target) || noble_distance(target, &me.bonuses) > 3 {
                    if let Some(new_target) = find_tycoon_target(obs, &me.bonuses) {
                        self.route = Some(MidLateRoute::Tycoon { target: new_target });
                    } else {
                        self.route = Some(MidLateRoute::Balanced);
                    }
                }
            }
            Some(MidLateRoute::Balanced) => {}
        }
    }
}

impl AgentPolicy for HeuristicAgentPolicyV02 {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        self.update_route(&context.observation);
        let scores = heuristic_v02_term_scores_with_route(
            &context.observation,
            context.legal_actions,
            self.route,
        );
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

/// Signed, additive terms. The terminal term represents a *safe lead on
/// reaching 15*, not a claim that the match has already ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub struct HeuristicV02Terms {
    pub terminal_lead: i64,
    pub immediate_prestige: i64,
    pub engine_value: i64,
    pub cheap_engine_buy: i64,
    pub cheap_ready: i64,
    pub conversion_value: i64,
    pub bomb_reserve: i64,
    pub rotation_guard: i64,
    pub vp_efficiency: i64,
    pub target_shortfall: i64,
    pub useful_discount: i64,
    pub new_affordable_target: i64,
    pub gold_liquidity: i64,
    pub secured_target: i64,
    pub reserve_tempo: i64,
    pub noble_race_progress: i64,
    pub noble_race_three_vp: i64,
    pub noble_race_reserved: i64,
    pub reserve_count_guard: i64,
    pub scoring_readiness: i64,
    pub route_guidance: i64,
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
            + self.route_guidance
    }
}

/// Exact for the visible own token/bonus/VP changes, except that a purchased
/// market slot is intentionally left empty rather than peeking at the refill.
/// Only the already certified legal actions may be scored.
pub fn heuristic_v02_term_scores(obs: &Observation, actions: &[Action]) -> Vec<HeuristicV02Terms> {
    heuristic_v02_term_scores_with_route(obs, actions, None)
}

pub fn heuristic_v02_term_scores_with_route(
    obs: &Observation,
    actions: &[Action],
    route: Option<MidLateRoute>,
) -> Vec<HeuristicV02Terms> {
    let me = obs
        .public
        .players
        .iter()
        .find(|p| p.id == obs.viewer)
        .expect("an observation must include its viewer");
    let before = OwnProjection {
        tokens: me.tokens,
        bonuses: me.bonuses,
        prestige: me.prestige,
    };
    let targets = visible_targets(obs);
    let phase = development_phase(obs, &before);
    let scoring_readiness_enabled =
        phase == DevelopmentPhase::Score && !obs.public.end_game_triggered;
    let ready_vp_before = if scoring_readiness_enabled {
        best_affordable_card_vp(&targets, &before)
    } else {
        0
    };
    let near_nobles = near_noble_ids(obs, &before.bonuses);
    let multi_noble_race =
        phase == DevelopmentPhase::Score && near_nobles.len() >= NOBLE_RACE_MIN_COUNT;
    // v0.2.4: races you cannot win (opponent strictly closer) earn nothing.
    let winnable_nobles = if multi_noble_race {
        winnable_near_nobles(obs, &before.bonuses)
    } else {
        Vec::new()
    };
    // Observation affordability, not a scan of the supplied action slice:
    // scoring one certified action or all certified siblings must agree.
    let has_cheap_buy = targets
        .iter()
        .any(|def| def.tier == Tier::One && def.total_cost() <= 4 && deficit(def, &before) == 0);
    let has_reserved_bomb = obs
        .private
        .reserved
        .iter()
        .any(|r| bomb_reserve_value(card(r.card)) > 0);

    // Phase scalar in per-mille: 0 = pure construction, 1000 = pure scoring.
    // Derived only from public prestige and the public end-game flag.
    let lead_prestige = obs
        .public
        .players
        .iter()
        .map(|p| i64::from(p.prestige))
        .max()
        .unwrap_or(0);
    let scoring_milli = if phase == DevelopmentPhase::Score {
        1000
    } else {
        (((lead_prestige - PHASE_LOW) * 1000) / PHASE_SPAN).clamp(0, 1000)
    };
    // Remaining board demand per color (how much each color is still needed
    // across all visible cards), capped per card so no single card dominates.
    let mut board_demand = [0i64; 5];
    for def in &targets {
        for color in GemColor::ALL {
            let c = color.index();
            let need = def.cost[c].saturating_sub(before.bonuses[c]);
            board_demand[c] += i64::from(need.min(ENGINE_PER_CARD_CAP));
        }
    }

    actions
        .iter()
        .map(|action| {
            let (after, bought, secured, reserve_tempo) = project_action(obs, *action, before);
            // Only known cards and exact own resource effects count. A reserve
            // can receive gold but cannot invent points or a blind card target.
            // Disable in the final round: no subsequent own buy is available.
            let scoring_readiness = if scoring_readiness_enabled
                && matches!(
                    action,
                    Action::TakeTokens { .. }
                        | Action::ReserveMarket { .. }
                        | Action::ReserveDeck { .. }
                ) {
                (best_affordable_card_vp(&targets, &after) - ready_vp_before).max(0)
                    * SCORING_READINESS_PER_VP
            } else {
                0
            };

            // A bought card is present on neither side of the *comparison*; its
            // realized VP/bonus is scored separately, rather than falsely treating
            // its absence as deterioration in the remaining goal set.
            let remaining: Vec<_> = targets
                .iter()
                .copied()
                .filter(|def| Some(def.id) != bought)
                .collect();
            let selected = select_targets(&remaining, &before, obs, phase);
            let before_def: Vec<i64> = selected.iter().map(|def| deficit(def, &before)).collect();
            let after_def: Vec<i64> = selected.iter().map(|def| deficit(def, &after)).collect();
            let shortfall = before_def
                .iter()
                .zip(&after_def)
                .map(|(&b, &a)| b.min(6) - a.min(6))
                .sum::<i64>();
            let discount = selected
                .iter()
                .map(|def| {
                    GemColor::ALL
                        .iter()
                        .map(|&color| {
                            let c = color.index();
                            i64::from(def.cost[c].saturating_sub(before.bonuses[c]))
                                - i64::from(def.cost[c].saturating_sub(after.bonuses[c]))
                        })
                        .sum::<i64>()
                })
                .sum::<i64>();
            let newly_ready = before_def
                .iter()
                .zip(&after_def)
                .any(|(&b, &a)| b > 0 && a == 0);
            let max_other = obs
                .public
                .players
                .iter()
                .filter(|p| p.id != obs.viewer)
                .map(|p| p.prestige)
                .max()
                .unwrap_or(0);
            let safe_lead =
                before.prestige < 15 && after.prestige >= 15 && after.prestige > max_other;
            // Engine value: acquiring a permanent bonus color has standalone
            // option value in construction phase, independent of the current
            // top-2 targets. Only a realized purchase gains a bonus; the value
            // tapers to zero as the game enters scoring phase.
            let engine_value = match bought {
                Some(id) => {
                    let color = card(id).bonus.index();
                    let demand = board_demand[color].min(ENGINE_DEMAND_CAP);
                    ((1000 - scoring_milli) * ENGINE_WEIGHT * demand) / 1000
                }
                None => 0,
            };
            let cheap_engine_buy = bought.map_or(0, |id| {
                let def = card(id);
                if def.tier != Tier::One || def.total_cost() > 4 {
                    return 0;
                }
                let weight = match phase {
                    DevelopmentPhase::Ultra => CHEAP_BUY_ULTRA,
                    DevelopmentPhase::Build => CHEAP_BUY_BUILD,
                    DevelopmentPhase::Score => 0,
                };
                (7 - i64::from(def.total_cost())) * weight
            });
            let cheap_ready = if matches!(action, Action::TakeTokens { .. })
                && targets.iter().any(|def| {
                    def.tier == Tier::One
                        && def.total_cost() <= 4
                        && deficit(def, &before) > 0
                        && deficit(def, &after) == 0
                }) {
                match phase {
                    DevelopmentPhase::Ultra => CHEAP_READY_ULTRA,
                    DevelopmentPhase::Build => CHEAP_READY_BUILD,
                    DevelopmentPhase::Score => 0,
                }
            } else {
                0
            };
            // Direct enabling value: a purchased discount must help OTHER
            // currently visible cheap T1 or efficient T2 cards. v0.2.1's
            // broader engine_value remains as a separate (correlated) term.
            let conversion_value = bought.map_or(0, |id| {
                let color = card(id).bonus.index();
                let demand: i64 = targets
                    .iter()
                    .filter(|def| def.id != id && def.cost[color] > before.bonuses[color])
                    .map(|def| {
                        if def.tier == Tier::One && def.total_cost() <= 4 {
                            2
                        } else if def.tier == Tier::One {
                            1
                        } else if high_value_t2(def) {
                            2
                        } else {
                            0
                        }
                    })
                    .sum();
                let weight = match phase {
                    DevelopmentPhase::Ultra => CONVERSION_ULTRA,
                    DevelopmentPhase::Build => CONVERSION_BUILD,
                    DevelopmentPhase::Score => 0,
                };
                demand.min(CONVERSION_CAP) * weight
            });
            let bomb_reserve = if phase == DevelopmentPhase::Ultra
                && !has_cheap_buy
                && !has_reserved_bomb
                && matches!(action, Action::ReserveMarket { .. })
            {
                secured.map_or(0, |id| bomb_reserve_value(card(id)))
            } else {
                0
            };
            let rotation_guard = match *action {
                Action::TakeTokens { take, give_back } if take == give_back => {
                    -ZERO_NET_TAKE_PENALTY
                }
                Action::TakeTokens { .. }
                    if phase != DevelopmentPhase::Score
                        && after.tokens.total() > 7
                        && !targets.iter().any(|def| deficit(def, &after) == 0) =>
                {
                    -STRANDED_TOKEN_PENALTY * i64::from(after.tokens.total() - 7)
                }
                _ => 0,
            };
            let vp_efficiency = if phase == DevelopmentPhase::Score {
                bought.map_or(0, |id| {
                    i64::from(after.prestige - before.prestige) * VP_EFFICIENCY_WEIGHT
                        / (1 + effective_cost(card(id), before.bonuses))
                })
            } else {
                0
            };
            let noble_race_progress = if multi_noble_race {
                winnable_nobles
                    .iter()
                    .map(|&id| {
                        (noble_distance(id, &before.bonuses) - noble_distance(id, &after.bonuses))
                            .max(0)
                    })
                    .sum::<i64>()
                    * NOBLE_RACE_PROGRESS_WEIGHT
            } else {
                0
            };
            let noble_race_three_vp = if multi_noble_race {
                bought.map_or(0, |id| {
                    let def = card(id);
                    if def.prestige == 3 && def.total_cost() > 6 {
                        NOBLE_RACE_THREE_VP_WEIGHT
                    } else {
                        0
                    }
                })
            } else {
                0
            };
            let noble_race_reserved = if multi_noble_race
                && matches!(action, Action::BuyReserved { .. })
            {
                bought.map_or(0, |id| {
                    let def = card(id);
                    if reserve_efficiency(def, before.bonuses) >= NOBLE_RACE_RESERVED_EFFICIENCY_MIN
                    {
                        NOBLE_RACE_RESERVED_WEIGHT
                    } else {
                        0
                    }
                })
            } else {
                0
            };
            let reserve_count_guard = if phase != DevelopmentPhase::Score
                && obs.private.reserved.len() >= RESERVE_COUNT_THRESHOLD
                && matches!(
                    action,
                    Action::ReserveMarket { .. } | Action::ReserveDeck { .. }
                ) {
                -RESERVE_COUNT_GUARD
            } else {
                0
            };
            let secured = secured.is_some_and(|id| {
                let def = card(id);
                selected.iter().any(|target| target.id == id)
                    && deficit(def, &after) <= 5
                    && obs
                        .public
                        .players
                        .iter()
                        .filter(|p| p.id != obs.viewer)
                        .any(|p| {
                            let opponent = OwnProjection {
                                tokens: p.tokens,
                                bonuses: p.bonuses,
                                prestige: p.prestige,
                            };
                            deficit(def, &opponent) <= 1
                        })
            });
            let route_guidance = match route {
                Some(MidLateRoute::HighCostRush) => {
                    let needed_colors = rush_needed_colors(obs, &before);
                    match action {
                        Action::BuyMarket { tier, slot } => {
                            let cid: Option<CardId> =
                                obs.public.market[tier.index()][*slot as usize];
                            cid.map_or(0, |id| {
                                let c = card(id);
                                if c.prestige <= 1 {
                                    if needed_colors[c.bonus.index()] {
                                        0
                                    } else {
                                        LOW_VP_RUSH_SUPPRESSION
                                    }
                                } else if c.prestige >= 3 {
                                    HIGH_VP_RUSH_EXECUTION_BONUS
                                } else {
                                    0
                                }
                            })
                        }
                        Action::BuyReserved { slot } => {
                            let idx = *slot as usize;
                            if idx < obs.private.reserved.len() {
                                let id = obs.private.reserved[idx].card;
                                let c = card(id);
                                if c.prestige <= 1 {
                                    if needed_colors[c.bonus.index()] {
                                        0
                                    } else {
                                        LOW_VP_RUSH_SUPPRESSION
                                    }
                                } else if c.prestige >= 3 {
                                    HIGH_VP_RUSH_EXECUTION_BONUS
                                } else {
                                    0
                                }
                            } else {
                                0
                            }
                        }
                        Action::ReserveMarket { tier, slot, .. } => {
                            let cid: Option<CardId> =
                                obs.public.market[tier.index()][*slot as usize];
                            cid.map_or(0, |id| {
                                let c = card(id);
                                if c.prestige >= 3 && deficit(c, &before) <= 6 {
                                    HIGH_VP_RUSH_PROTECT_BONUS
                                } else {
                                    0
                                }
                            })
                        }
                        _ => 0,
                    }
                }
                Some(MidLateRoute::Tycoon { target }) => match action {
                    Action::BuyMarket { tier, slot } => {
                        let cid: Option<CardId> = obs.public.market[tier.index()][*slot as usize];
                        cid.map_or(0, |id| {
                            let c = card(id);
                            let noble = &all_nobles()[target.index()];
                            if noble.requires(c.bonus) > before.bonuses[c.bonus.index()] {
                                if c.prestige >= 1 {
                                    TYCOON_SCORING_CARD_BONUS
                                } else if noble_distance(target, &before.bonuses) <= 1 {
                                    TYCOON_IMMEDIATE_CLAIM_BONUS
                                } else {
                                    LOW_VP_RUSH_SUPPRESSION
                                }
                            } else if c.prestige <= 1 {
                                LOW_VP_RUSH_SUPPRESSION
                            } else {
                                0
                            }
                        })
                    }
                    Action::BuyReserved { slot } => {
                        let idx = *slot as usize;
                        if idx < obs.private.reserved.len() {
                            let id = obs.private.reserved[idx].card;
                            let c = card(id);
                            let noble = &all_nobles()[target.index()];
                            if noble.requires(c.bonus) > before.bonuses[c.bonus.index()] {
                                if c.prestige >= 1 {
                                    TYCOON_SCORING_CARD_BONUS
                                } else if noble_distance(target, &before.bonuses) <= 1 {
                                    TYCOON_IMMEDIATE_CLAIM_BONUS
                                } else {
                                    LOW_VP_RUSH_SUPPRESSION
                                }
                            } else if c.prestige <= 1 {
                                LOW_VP_RUSH_SUPPRESSION
                            } else {
                                0
                            }
                        } else {
                            0
                        }
                    }
                    _ => 0,
                },
                Some(MidLateRoute::Balanced) | None => 0,
            };

            HeuristicV02Terms {
                terminal_lead: if safe_lead { TERMINAL_PRIORITY } else { 0 },
                // Points beyond 15 still determine the winner in the final round.
                // Each realized VP is worth more as the game enters scoring phase.
                immediate_prestige: i64::from(after.prestige - before.prestige)
                    * (VP_WEIGHT + (scoring_milli * VP_LATE_BONUS) / 1000),
                engine_value,
                cheap_engine_buy,
                cheap_ready,
                conversion_value,
                bomb_reserve,
                rotation_guard,
                vp_efficiency,
                target_shortfall: shortfall * SHORTFALL_WEIGHT,
                useful_discount: discount * BONUS_WEIGHT,
                new_affordable_target: if newly_ready { READY_WEIGHT } else { 0 },
                gold_liquidity: (i64::from(after.tokens.gold.min(3))
                    - i64::from(before.tokens.gold.min(3)))
                    * GOLD_WEIGHT,
                secured_target: if secured { SECURED_WEIGHT } else { 0 },
                reserve_tempo,
                noble_race_progress,
                noble_race_three_vp,
                noble_race_reserved,
                reserve_count_guard,
                scoring_readiness,
                route_guidance,
            }
        })
        .collect()
}

/// Project only the player's visible resource effects; no market refill is
/// manufactured or read from the private deck. Server legality is the input.
fn project_action(
    obs: &Observation,
    action: Action,
    before: OwnProjection,
) -> (OwnProjection, Option<CardId>, Option<CardId>, i64) {
    let mut after = before;
    let mut bought = None;
    let mut secured = None;
    let mut reserve_tempo = 0;
    match action {
        Action::TakeTokens { take, give_back } => {
            after.tokens = after
                .tokens
                .saturating_add(take)
                .checked_sub(give_back)
                .expect("legal take has a legal return");
        }
        Action::BuyMarket { tier, slot } => {
            let id = obs.public.market[tier.index()][slot as usize]
                .expect("legal market purchase has a card");
            bought = Some(id);
            apply_buy(&mut after, card(id), obs);
        }
        Action::BuyReserved { slot } => {
            let id = obs.private.reserved[slot as usize].card;
            bought = Some(id);
            apply_buy(&mut after, card(id), obs);
        }
        Action::ReserveMarket {
            tier,
            slot,
            give_back,
        } => {
            secured = obs.public.market[tier.index()][slot as usize];
            after.tokens = reserve_tokens(before.tokens, give_back, obs.public.bank.gold > 0);
            reserve_tempo = -VISIBLE_RESERVE_TEMPO;
        }
        Action::ReserveDeck { give_back, .. } => {
            // No fictitious average card, no access to the sampled deck top.
            after.tokens = reserve_tokens(before.tokens, give_back, obs.public.bank.gold > 0);
            reserve_tempo = -BLIND_RESERVE_TEMPO;
        }
        Action::ChooseNoble { noble } => {
            after.prestige = after
                .prestige
                .saturating_add(all_nobles()[noble.index()].prestige);
        }
        Action::Pass => {}
    }
    (after, bought, secured, reserve_tempo)
}

fn visible_targets(obs: &Observation) -> Vec<CardDef> {
    let mut out = Vec::with_capacity(15);
    for tier in Tier::ALL {
        for id in obs.public.market[tier.index()].iter().flatten() {
            out.push(*card(*id));
        }
    }
    out.extend(obs.private.reserved.iter().map(|r| *card(r.card)));
    out
}

fn select_targets(
    targets: &[CardDef],
    own: &OwnProjection,
    obs: &Observation,
    phase: DevelopmentPhase,
) -> Vec<CardDef> {
    let mut demand = [0i64; 5];
    for def in targets {
        for color in GemColor::ALL {
            let c = color.index();
            demand[c] += i64::from(def.cost[c].saturating_sub(own.bonuses[c])).min(2);
        }
    }
    let near = if phase == DevelopmentPhase::Score {
        near_noble_ids(obs, &own.bonuses)
    } else {
        Vec::new()
    };
    let multi_noble_race = near.len() >= NOBLE_RACE_MIN_COUNT;
    let winnable = if multi_noble_race {
        winnable_near_nobles(obs, &own.bonuses)
    } else {
        Vec::new()
    };
    let mut ordered = targets.to_vec();
    ordered.sort_by_key(|def| {
        let color = def.bonus.index();
        let noble_help = if multi_noble_race {
            winnable
                .iter()
                .filter(|&&id| own.bonuses[color] < all_nobles()[id.index()].requires(def.bonus))
                .count() as i64
        } else {
            0
        };
        let value = 1 + 2 * i64::from(def.prestige) + 2 * demand[color].min(3) + noble_help;
        let gap = deficit(def, own);
        match phase {
            DevelopmentPhase::Ultra | DevelopmentPhase::Build => {
                let group = if def.tier == Tier::One && def.total_cost() <= 4 {
                    0
                } else if def.tier == Tier::One {
                    1
                } else if high_value_t2(def) {
                    2
                } else {
                    3
                };
                (group, 0, -(100 * value / (1 + gap)), gap, def.id.index())
            }
            DevelopmentPhase::Score => {
                let race_group = if !multi_noble_race {
                    0
                } else if noble_help > 0 {
                    0
                } else if (def.prestige == 3 && def.total_cost() > 6)
                    || (obs.private.reserved.iter().any(|r| r.card == def.id)
                        && reserve_efficiency(def, own.bonuses)
                            >= NOBLE_RACE_RESERVED_EFFICIENCY_MIN)
                {
                    1
                } else {
                    2
                };
                let efficiency = reserve_efficiency(def, own.bonuses);
                // In a multi-noble race, permanent-discount progress comes
                // first, then the frozen high-value-card/reserve group. Within
                // each group keep VP efficiency and reachability ordering.
                (
                    race_group,
                    -noble_help,
                    -(efficiency * 10 / (1 + gap)),
                    gap,
                    def.id.index(),
                )
            }
        }
    });
    ordered.truncate(2);
    ordered
}

fn best_affordable_card_vp(targets: &[CardDef], own: &OwnProjection) -> i64 {
    targets
        .iter()
        .filter(|def| deficit(def, own) == 0)
        .map(|def| i64::from(def.prestige))
        .max()
        .unwrap_or(0)
}

fn deficit(def: &CardDef, own: &OwnProjection) -> i64 {
    let raw: i64 = GemColor::ALL
        .iter()
        .map(|&c| {
            (i64::from(def.cost[c.index()].saturating_sub(own.bonuses[c.index()]))
                - i64::from(own.tokens.color(c)))
            .max(0)
        })
        .sum();
    (raw - i64::from(own.tokens.gold)).max(0)
}

fn apply_buy(own: &mut OwnProjection, def: &CardDef, obs: &Observation) {
    let mut gold_needed = 0u8;
    for color in GemColor::ALL {
        let need = def.cost[color.index()].saturating_sub(own.bonuses[color.index()]);
        let paid = own.tokens.color(color).min(need);
        own.tokens.set_color(color, own.tokens.color(color) - paid);
        gold_needed += need - paid;
    }
    own.tokens.gold -= gold_needed; // every passed action is server-certified legal
    own.bonuses[def.bonus.index()] = own.bonuses[def.bonus.index()].saturating_add(1);
    own.prestige = own.prestige.saturating_add(def.prestige);
    // The engine grants only ONE qualifying noble per purchase, including
    // the ChooseNoble path when several are simultaneously eligible.
    if let Some(noble) = obs
        .public
        .nobles
        .iter()
        .filter_map(|&id| {
            let def = &all_nobles()[id.index()];
            let now_qualified = GemColor::ALL
                .iter()
                .all(|&c| own.bonuses[c.index()] >= def.requires(c));
            now_qualified.then_some(def.prestige)
        })
        .max()
    {
        own.prestige = own.prestige.saturating_add(noble);
    }
}

fn reserve_tokens(before: Gems, give_back: Gems, gold_available: bool) -> Gems {
    let received = if gold_available {
        Gems {
            gold: 1,
            ..Gems::ZERO
        }
    } else {
        Gems::ZERO
    };
    before
        .saturating_add(received)
        .checked_sub(give_back)
        .expect("legal reserve return")
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{FullState, GameConfig, Phase, PlayerId, ReservedCard, Ruleset};

    fn game(seed: u64) -> FullState {
        FullState::new(GameConfig {
            seed,
            player_count: 2,
            ruleset: Ruleset::base_v1(),
        })
        .expect("valid game")
        .0
    }

    /// Expose an actual catalog card without duplicating it in the deck.
    fn expose(state: &mut FullState, id: CardId, slot: usize) {
        let t = card(id).tier.index();
        let old = state.market[t][slot].expect("full market fixture");
        if old == id {
            return;
        }
        if let Some(other_slot) = state.market[t].iter().position(|&x| x == Some(id)) {
            state.market[t][other_slot] = Some(old);
        } else {
            let pos = state.decks[t]
                .iter()
                .position(|&x| x == id)
                .expect("card in deck");
            state.decks[t][pos] = old;
        }
        state.market[t][slot] = Some(id);
    }

    #[test]
    fn visible_projection_matches_engine_for_all_legal_siblings() {
        let mut examined = 0usize;
        for seed in 1..=5 {
            let mut state = game(seed);
            for step in 0..55usize {
                if state.is_terminal() {
                    break;
                }
                let obs = state.observation(state.current_player);
                let legal = state.legal_actions();
                let me = &obs.public.players[obs.viewer.index()];
                let before = OwnProjection {
                    tokens: me.tokens,
                    bonuses: me.bonuses,
                    prestige: me.prestige,
                };
                assert_eq!(heuristic_v02_term_scores(&obs, &legal).len(), legal.len());
                for &action in &legal {
                    let (projected, _, _, _) = project_action(&obs, action, before);
                    let mut child = state.clone();
                    child.apply(action).expect("certified action applies");
                    if child.phase == Phase::ChooseNoble {
                        let noble = child.pending_nobles[0];
                        child
                            .apply(Action::ChooseNoble { noble })
                            .expect("complete turn");
                    }
                    let actual = &child.players[obs.viewer.index()];
                    assert_eq!(projected.tokens, actual.tokens, "{seed} {step} {action:?}");
                    assert_eq!(
                        projected.bonuses, actual.bonuses,
                        "{seed} {step} {action:?}"
                    );
                    assert_eq!(
                        projected.prestige, actual.prestige,
                        "{seed} {step} {action:?}"
                    );
                    examined += 1;
                }
                let action = legal[(step * 13 + seed as usize) % legal.len()];
                state.apply(action).expect("deterministic walk legal");
            }
        }
        assert!(
            examined > 1_000,
            "must actually cover many legal return siblings"
        );
    }

    #[test]
    fn blind_reserve_has_no_fabricated_card_vp_and_no_deck_order_dependence() {
        let mut state = game(42);
        let obs = state.observation(PlayerId(0));
        let legal = state.legal_actions();
        let scores = heuristic_v02_term_scores(&obs, &legal);
        let blind = legal
            .iter()
            .position(|a| {
                matches!(
                    a,
                    Action::ReserveDeck {
                        tier: Tier::Three,
                        ..
                    }
                )
            })
            .expect("base game can reserve tier three");
        assert_eq!(scores[blind].immediate_prestige, 0);
        assert_eq!(scores[blind].reserve_tempo, -BLIND_RESERVE_TEMPO);
        state.decks[2].reverse();
        assert_eq!(obs, state.observation(PlayerId(0)));
        assert_eq!(
            scores,
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &legal)
        );
    }

    #[test]
    fn purchase_gold_payment_and_visible_reserve_do_not_invent_vp() {
        let mut state = game(10);
        // Tier-1 card zero costs three black. The referee's deterministic
        // payment spends the one colored token before two gold tokens.
        let old = state.market[0][0].unwrap();
        if old != CardId(0) {
            if let Some(slot) = state.market[0].iter().position(|&id| id == Some(CardId(0))) {
                state.market[0][slot] = Some(old);
            } else {
                let pos = state.decks[0]
                    .iter()
                    .position(|&id| id == CardId(0))
                    .unwrap();
                state.decks[0][pos] = old;
            }
            state.market[0][0] = Some(CardId(0));
        }
        state.players[0].tokens = Gems {
            black: 1,
            gold: 2,
            ..Gems::ZERO
        };
        state.bank.black -= 1;
        state.bank.gold -= 2;
        let obs = state.observation(PlayerId(0));
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        let visible_reserve = state
            .legal_actions()
            .into_iter()
            .find(|a| {
                matches!(
                    a,
                    Action::ReserveMarket {
                        tier: Tier::One,
                        slot: 0,
                        ..
                    }
                )
            })
            .unwrap();
        let before = OwnProjection {
            tokens: state.players[0].tokens,
            bonuses: state.players[0].bonuses,
            prestige: state.players[0].prestige,
        };
        let projected = project_action(&obs, buy, before).0;
        let mut actual = state.clone();
        actual.apply(buy).unwrap();
        assert_eq!(projected.tokens, actual.players[0].tokens);
        assert_eq!(projected.tokens.black, 0);
        assert_eq!(projected.tokens.gold, 0);
        assert_eq!(
            heuristic_v02_term_scores(&obs, &[visible_reserve])[0].immediate_prestige,
            0
        );
    }

    #[test]
    fn multiple_eligible_nobles_grant_only_one_and_settle_before_trigger() {
        let mut state = game(42);
        // The same mechanically valid edge fixture used by the core rules
        // tests: buying card zero with enough bonuses qualifies two nobles.
        let replacement = state.market[0][0].unwrap();
        if let Some(slot) = state.market[0].iter().position(|&x| x == Some(CardId(0))) {
            state.market[0][slot] = Some(replacement);
        } else if let Some(pos) = state.decks[0].iter().position(|&x| x == CardId(0)) {
            state.decks[0][pos] = replacement;
        }
        state.market[0][0] = Some(CardId(0));
        state.nobles = vec![splendor_catalog::NobleId(0), splendor_catalog::NobleId(1)];
        state.players[0].bonuses = [4; 5];
        state.players[0].prestige = 14;
        state.players[0].tokens.black = 3;
        state.bank.black -= 3;
        let obs = state.observation(PlayerId(0));
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        assert!(state.legal_actions().contains(&buy));
        let projected = project_action(
            &obs,
            buy,
            OwnProjection {
                tokens: state.players[0].tokens,
                bonuses: state.players[0].bonuses,
                prestige: state.players[0].prestige,
            },
        )
        .0;
        let mut child = state.clone();
        child.apply(buy).unwrap();
        assert_eq!(child.phase, Phase::ChooseNoble);
        assert_eq!(child.players[0].prestige, 14);
        let choice = Action::ChooseNoble {
            noble: child.pending_nobles[0],
        };
        child.apply(choice).unwrap();
        assert_eq!(projected.prestige, child.players[0].prestige);
        assert_eq!(projected.prestige, 17); // one noble, not two
        assert!(heuristic_v02_term_scores(&obs, &[buy])[0].terminal_lead > 0);
    }

    #[test]
    fn opponent_blind_identity_cannot_change_our_scores() {
        let mut state = game(93);
        let blind = state
            .legal_actions()
            .into_iter()
            .find(|a| {
                matches!(
                    a,
                    Action::ReserveDeck {
                        tier: Tier::One,
                        ..
                    }
                )
            })
            .unwrap();
        state.apply(blind).unwrap(); // player zero's blind reserve; now player one acts
        let obs = state.observation(PlayerId(1));
        let legal = state.legal_actions();
        let baseline = heuristic_v02_term_scores(&obs, &legal);
        let original = state.players[0].reserved[0].card;
        let other = state.decks[0][0];
        state.players[0].reserved[0].card = other;
        state.decks[0][0] = original;
        assert_eq!(state.observation(PlayerId(1)), obs);
        assert_eq!(state.legal_actions(), legal);
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(1)), &legal),
            baseline
        );
    }

    #[test]
    fn a_legal_purchase_does_not_automatically_beat_all_token_takes() {
        // Every position has a legal zero-point buy; changing the visible
        // target selection can still make a valuable take the better move.
        let mut found = false;
        for seed in 1..=30 {
            let mut state = game(seed);
            let old = state.market[0][0].unwrap();
            if old != CardId(0) {
                if let Some(slot) = state.market[0].iter().position(|&id| id == Some(CardId(0))) {
                    state.market[0][slot] = Some(old);
                } else {
                    let pos = state.decks[0]
                        .iter()
                        .position(|&id| id == CardId(0))
                        .unwrap();
                    state.decks[0][pos] = old;
                }
                state.market[0][0] = Some(CardId(0));
            }
            state.players[0].tokens.black = 3;
            state.bank.black -= 3;
            let obs = state.observation(PlayerId(0));
            let legal = state.legal_actions();
            let scores = heuristic_v02_term_scores(&obs, &legal);
            let buy = legal
                .iter()
                .position(|a| {
                    *a == Action::BuyMarket {
                        tier: Tier::One,
                        slot: 0,
                    }
                })
                .unwrap();
            if legal.iter().zip(&scores).any(|(a, s)| {
                matches!(a, Action::TakeTokens { .. }) && s.total() > scores[buy].total()
            }) {
                found = true;
                break;
            }
        }
        assert!(found, "a family base must not silently reappear");
    }

    #[test]
    fn different_legal_return_colors_can_have_different_values() {
        let mut state = game(41);
        let me = &mut state.players[0];
        me.tokens = Gems {
            white: 3,
            blue: 2,
            green: 2,
            red: 1,
            black: 1,
            gold: 1,
        };
        state.bank.white -= 3;
        state.bank.blue -= 2;
        state.bank.green -= 2;
        state.bank.red -= 1;
        state.bank.black -= 1;
        state.bank.gold -= 1;
        let obs = state.observation(PlayerId(0));
        let legal = state.legal_actions();
        let scores = heuristic_v02_term_scores(&obs, &legal);
        let mut distinct_scores = std::collections::BTreeSet::new();
        for (a, s) in legal.iter().zip(scores) {
            if matches!(a, Action::TakeTokens { .. }) {
                distinct_scores.insert(s.total());
            }
        }
        assert!(
            distinct_scores.len() > 1,
            "return composition must affect score"
        );
    }

    #[test]
    fn construction_phase_rewards_a_cheap_zero_vp_engine_card() {
        // v0.2.0 regression fixture: early game, a cheap 0-VP bonus card whose
        // color the board still demands must score positively (v0.2.0 gave it
        // a negative total and reserved instead). Uses card 0 (blue bonus,
        // 0 VP, costs three black).
        let mut state = game(10);
        let old = state.market[0][0].unwrap();
        if old != CardId(0) {
            if let Some(slot) = state.market[0].iter().position(|&id| id == Some(CardId(0))) {
                state.market[0][slot] = Some(old);
            } else {
                let pos = state.decks[0]
                    .iter()
                    .position(|&id| id == CardId(0))
                    .unwrap();
                state.decks[0][pos] = old;
            }
            state.market[0][0] = Some(CardId(0));
        }
        state.players[0].tokens.black = 3;
        state.bank.black -= 3;
        let obs = state.observation(PlayerId(0));
        // Everyone at 0 prestige => pure construction phase.
        assert_eq!(obs.public.players.iter().map(|p| p.prestige).max(), Some(0));
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        let terms = heuristic_v02_term_scores(&obs, &[buy])[0];
        assert_eq!(terms.immediate_prestige, 0, "card 0 is 0 VP");
        assert!(
            terms.engine_value > 0,
            "a demanded bonus color must have construction-phase engine value: {terms:?}"
        );
        assert!(
            terms.total() > 0,
            "a cheap engine card must not score negative early: {terms:?}"
        );
    }

    #[test]
    fn scoring_phase_lifts_vp_weight_and_removes_engine_value() {
        // A late-game state (someone already near 15) must weight realized VP
        // at the full late rate and drop construction-phase engine value.
        let mut state = game(10);
        let old = state.market[0][0].unwrap();
        // A tier-2 card worth VP that the player can afford outright.
        let scoring_card = CardId(53); // T2 black bonus, 1 VP
        if old != scoring_card {
            if let Some(slot) = state.market[0]
                .iter()
                .position(|&id| id == Some(scoring_card))
            {
                state.market[0][slot] = Some(old);
            } else if let Some(pos) = state.decks[1].iter().position(|&id| id == scoring_card) {
                let repl = state.market[0][0].unwrap();
                state.decks[1][pos] = repl;
            }
            state.market[0][0] = Some(scoring_card);
        }
        let def = *card(scoring_card);
        // Give exactly the colored tokens for its cost so the buy is legal.
        let mut tokens = Gems::ZERO;
        for c in GemColor::ALL {
            tokens.set_color(c, def.cost[c.index()]);
        }
        state.players[0].tokens = tokens;
        // Opponent already near the finish => full scoring phase.
        state.players[1].prestige = 13;
        let obs = state.observation(PlayerId(0));
        assert!(
            obs.public.players.iter().map(|p| p.prestige).max() >= Some(12),
            "fixture must be in scoring phase"
        );
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        assert!(
            state.legal_actions().contains(&buy),
            "scoring buy must be legal"
        );
        let terms = heuristic_v02_term_scores(&obs, &[buy])[0];
        assert_eq!(
            terms.immediate_prestige,
            i64::from(def.prestige) * (VP_WEIGHT + VP_LATE_BONUS),
            "scoring phase must pay the full late VP rate: {terms:?}"
        );
        assert_eq!(
            terms.engine_value, 0,
            "engine value must vanish in scoring phase: {terms:?}"
        );
    }

    #[test]
    fn end_game_flag_forces_scoring_phase_regardless_of_prestige() {
        // Even at low prestige, a triggered end game is treated as full
        // scoring phase (no residual construction discount).
        let mut state = game(7);
        state.players[0].tokens = Gems {
            black: 3,
            ..Gems::ZERO
        };
        let old = state.market[0][0].unwrap();
        if old != CardId(0) {
            if let Some(slot) = state.market[0].iter().position(|&id| id == Some(CardId(0))) {
                state.market[0][slot] = Some(old);
            } else {
                let pos = state.decks[0]
                    .iter()
                    .position(|&id| id == CardId(0))
                    .unwrap();
                state.decks[0][pos] = old;
            }
            state.market[0][0] = Some(CardId(0));
        }
        let obs_before = state.observation(PlayerId(0));
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        let engine_before = heuristic_v02_term_scores(&obs_before, &[buy])[0].engine_value;
        assert!(engine_before > 0, "pre-endgame construction value expected");
        state.end_game_triggered = true;
        let obs_after = state.observation(PlayerId(0));
        let engine_after = heuristic_v02_term_scores(&obs_after, &[buy])[0].engine_value;
        assert_eq!(
            engine_after, 0,
            "end-game flag must zero construction engine value"
        );
    }

    #[test]
    fn discount_phase_boundaries_and_public_scoring_override() {
        let mut state = game(53);
        for (count, expected) in [
            (4, DevelopmentPhase::Ultra),
            (5, DevelopmentPhase::Build),
            (8, DevelopmentPhase::Build),
            (9, DevelopmentPhase::Score),
        ] {
            state.players[0].bonuses = [count, 0, 0, 0, 0];
            let obs = state.observation(PlayerId(0));
            let own = OwnProjection {
                tokens: Gems::ZERO,
                bonuses: [count, 0, 0, 0, 0],
                prestige: 0,
            };
            assert_eq!(development_phase(&obs, &own), expected, "discounts={count}");
        }
        let own = OwnProjection {
            tokens: Gems::ZERO,
            bonuses: [0; 5],
            prestige: 0,
        };
        state.players[0].bonuses = [0; 5];
        state.players[1].prestige = 12;
        assert_eq!(
            development_phase(&state.observation(PlayerId(0)), &own),
            DevelopmentPhase::Score
        );
        state.players[1].prestige = 0;
        state.end_game_triggered = true;
        assert_eq!(
            development_phase(&state.observation(PlayerId(0)), &own),
            DevelopmentPhase::Score
        );
    }

    #[test]
    fn real_catalog_bomb_order_and_tier_correction() {
        assert_eq!(bomb_reserve_value(card(CardId(71))), BOMB_7_FOR_4); // T3 7 white -> 4VP
        assert_eq!(bomb_reserve_value(card(CardId(45))), BOMB_6_FOR_3); // T2 6 blue -> 3VP
        assert_eq!(bomb_reserve_value(card(CardId(73))), BOMB_7_PLUS_3_FOR_5); // T3 7+3 -> 5VP
        assert!(BOMB_7_FOR_4 > BOMB_6_FOR_3 && BOMB_6_FOR_3 > BOMB_7_PLUS_3_FOR_5);
        assert!(
            splendor_catalog::all_cards()
                .iter()
                .filter(|def| def.tier == Tier::Three
                    && def.prestige == 3
                    && def.cost.iter().filter(|&&x| x > 0).count() == 1
                    && def.cost.contains(&6))
                .next()
                .is_none(),
            "no fictitious T3 6-mono/3VP"
        );
        for (id, expected) in [
            (71, BOMB_7_FOR_4),
            (45, BOMB_6_FOR_3),
            (73, BOMB_7_PLUS_3_FOR_5),
        ] {
            assert_eq!(bomb_reserve_value(card(CardId(id))), expected);
        }
    }

    #[test]
    fn cheap_buy_and_conversion_use_real_sibling_actions() {
        let mut state = game(54);
        expose(&mut state, CardId(0), 0); // T1 zero-VP blue engine, 3 black
        expose(&mut state, CardId(9), 1); // T1 red bonus needs blue
        expose(&mut state, CardId(42), 0); // T2 2VP/5 needs blue
        state.players[0].tokens.black = 3;
        state.bank.black -= 3;
        let obs = state.observation(PlayerId(0));
        let legal = state.legal_actions();
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        let idx = legal.iter().position(|&a| a == buy).unwrap();
        let score = heuristic_v02_term_scores(&obs, &legal)[idx];
        assert_eq!(score.cheap_engine_buy, 4 * CHEAP_BUY_ULTRA); // printed cost=3
        assert!(
            score.conversion_value > 0,
            "blue bonus enables T1/T2 board: {score:?}"
        );
        // Taking tokens can prepare a cheap card: not every buy is hard-coded
        // ahead of every take (old no-family-base regression remains in force).
        assert!(legal.iter().any(|a| matches!(a, Action::TakeTokens { .. })));
        let mut without_followups = obs.clone();
        for tier in Tier::ALL {
            for id in &mut without_followups.public.market[tier.index()] {
                if *id != Some(CardId(0)) {
                    *id = None;
                }
            }
        }
        let alone = heuristic_v02_term_scores(&without_followups, &[buy])[0];
        assert_eq!(
            alone.conversion_value, 0,
            "card cannot count itself as its own followup"
        );
    }

    #[test]
    fn cheap_take_readiness_and_stranded_rotation_penalty() {
        let mut state = game(55);
        expose(&mut state, CardId(0), 0);
        state.players[0].tokens.black = 2;
        state.bank.black -= 2;
        let obs = state.observation(PlayerId(0));
        let legal = state.legal_actions();
        let ready = legal
            .iter()
            .position(|a| {
                matches!(a,
            Action::TakeTokens { take, .. } if take.black >= 1)
            })
            .expect("can take black");
        let scores = heuristic_v02_term_scores(&obs, &legal);
        assert_eq!(scores[ready].cheap_ready, CHEAP_READY_ULTRA);

        // Construct a real legal take above 7 tokens with no visible target;
        // player-view scoring may not infer market refills or hidden cards.
        let mut crowded = game(56);
        crowded.players[0].tokens = Gems {
            white: 3,
            blue: 3,
            green: 1,
            ..Gems::ZERO
        };
        crowded.bank.white -= 3;
        crowded.bank.blue -= 3;
        crowded.bank.green -= 1;
        crowded.market = [[None; 4]; 3];
        let obs = crowded.observation(PlayerId(0));
        let legal = crowded.legal_actions();
        let idx = legal
            .iter()
            .position(|a| {
                matches!(a,
            Action::TakeTokens { take, give_back } if take.total() == 3 && give_back.total() == 0)
            })
            .expect("legal take to exactly ten");
        let s = heuristic_v02_term_scores(&obs, &legal)[idx];
        assert_eq!(s.rotation_guard, -3 * STRANDED_TOKEN_PENALTY);
        let mut full = game(57);
        full.players[0].tokens = Gems {
            white: 3,
            blue: 3,
            green: 3,
            red: 1,
            ..Gems::ZERO
        };
        full.bank.white -= 3;
        full.bank.blue -= 3;
        full.bank.green -= 3;
        full.bank.red -= 1;
        let obs = full.observation(PlayerId(0));
        let legal = full.legal_actions();
        if let Some(idx) = legal.iter().position(|a| {
            matches!(a,
            Action::TakeTokens { take, give_back } if take == give_back)
        }) {
            assert_eq!(
                heuristic_v02_term_scores(&obs, &legal)[idx].rotation_guard,
                -ZERO_NET_TAKE_PENALTY
            );
        } else {
            panic!("10-token fixture must expose a net-zero legal take");
        }
    }

    #[test]
    fn scoring_targets_and_bonus_match_vp_per_effective_cost() {
        let state = game(58);
        let obs = state.observation(PlayerId(0));
        let own = OwnProjection {
            tokens: Gems::ZERO,
            bonuses: [0; 5],
            prestige: 0,
        };
        let ranked = select_targets(
            &[*card(CardId(42)), *card(CardId(43))],
            &own,
            &obs,
            DevelopmentPhase::Score,
        );
        assert_eq!(
            ranked[0].id,
            CardId(42),
            "2VP/5 outranks 2VP/8, same budget"
        );
        assert_eq!(effective_cost(card(CardId(42)), own.bonuses), 5);
        assert_eq!(effective_cost(card(CardId(43)), own.bonuses), 8);
        // Evaluate a genuinely legal 2VP/5 purchase in emergency scoring.
        let mut scoring = game(59);
        expose(&mut scoring, CardId(42), 0);
        scoring.players[1].prestige = 12;
        scoring.players[0].tokens = Gems {
            blue: 4,
            gold: 1,
            ..Gems::ZERO
        };
        scoring.bank.blue -= 4;
        scoring.bank.gold -= 1;
        let buy = Action::BuyMarket {
            tier: Tier::Two,
            slot: 0,
        };
        assert!(scoring.legal_actions().contains(&buy));
        let score = heuristic_v02_term_scores(&scoring.observation(PlayerId(0)), &[buy])[0];
        assert_eq!(score.immediate_prestige, 2 * (VP_WEIGHT + VP_LATE_BONUS));
        assert_eq!(score.vp_efficiency, 2 * VP_EFFICIENCY_WEIGHT / 6);
        assert_eq!(score.cheap_engine_buy, 0);
        assert_eq!(score.conversion_value, 0);
    }

    #[test]
    fn actual_legal_reserve_ranking_is_gated_by_stage_and_cheap_buy() {
        let mut state = game(60);
        expose(&mut state, CardId(71), 0); // T3 7 white -> 4VP
        expose(&mut state, CardId(73), 1); // T3 7+3 -> 5VP
        expose(&mut state, CardId(45), 0); // T2 6 blue -> 3VP
        let a4 = Action::ReserveMarket {
            tier: Tier::Three,
            slot: 0,
            give_back: Gems::ZERO,
        };
        let a3 = Action::ReserveMarket {
            tier: Tier::Two,
            slot: 0,
            give_back: Gems::ZERO,
        };
        let a5 = Action::ReserveMarket {
            tier: Tier::Three,
            slot: 1,
            give_back: Gems::ZERO,
        };
        let legal = state.legal_actions();
        assert!([a4, a3, a5].iter().all(|a| legal.contains(a)));
        let scores = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[a4, a3, a5]);
        assert_eq!(
            scores.iter().map(|s| s.bomb_reserve).collect::<Vec<_>>(),
            vec![BOMB_7_FOR_4, BOMB_6_FOR_3, BOMB_7_PLUS_3_FOR_5]
        );
        assert!(
            scores[0].total() > scores[1].total() && scores[1].total() > scores[2].total(),
            "true legal action order: {scores:?}"
        );
        state.players[0].bonuses = [5, 0, 0, 0, 0];
        assert!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[a4, a3, a5])
                .iter()
                .all(|s| s.bomb_reserve == 0),
            "no ultra bonus beyond four discounts"
        );

        // If an immediate cheap T1 buy exists, secondary reserve bonuses do
        // not compete with the owner's primary construction goal.
        state.players[0].bonuses = [0; 5];
        expose(&mut state, CardId(0), 0);
        state.players[0].tokens.black = 3;
        state.bank.black -= 3;
        let legal = state.legal_actions();
        assert!(legal.contains(&Action::BuyMarket {
            tier: Tier::One,
            slot: 0
        }));
        assert!(legal.contains(&a4));
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[a4])[0].bomb_reserve,
            0,
            "primary-buy gate must not depend on sibling action slice"
        );
        let s = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &legal);
        assert_eq!(
            s[legal.iter().position(|&a| a == a4).unwrap()].bomb_reserve,
            0
        );
    }

    fn multi_noble_scoring_state(seed: u64) -> FullState {
        let mut state = game(seed);
        state.nobles = vec![NobleId(0), NobleId(8)];
        state.players[0].bonuses = [2, 4, 2, 0, 3];
        state.players[1].prestige = 12;
        state
    }

    fn give_race_buy_tokens(state: &mut FullState) {
        state.players[0].tokens = Gems {
            white: 1,
            blue: 1,
            green: 1,
            ..Gems::ZERO
        };
        state.bank.white -= 1;
        state.bank.blue -= 1;
        state.bank.green -= 1;
    }

    #[test]
    fn multi_noble_race_progress_and_target_order_use_frozen_distance() {
        let mut state = game(61);
        state.nobles = vec![NobleId(0), NobleId(8)];
        state.players[0].bonuses = [2, 2, 1, 0, 0];
        state.players[1].prestige = 12;
        assert_eq!(noble_distance(NobleId(0), &[2, 2, 1, 0, 0]), 4);
        assert_eq!(noble_distance(NobleId(8), &[2, 2, 1, 0, 0]), 4);
        assert_eq!(
            near_noble_ids(&state.observation(PlayerId(0)), &[2, 2, 1, 0, 0]).len(),
            2
        );

        expose(&mut state, CardId(0), 0); // blue bonus advances both nobles
        state.players[0].tokens.black = 3;
        state.bank.black -= 3;
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        assert!(state.legal_actions().contains(&buy));
        let score = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0];
        assert_eq!(score.noble_race_progress, 2 * NOBLE_RACE_PROGRESS_WEIGHT);

        // One near noble is not enough; neither is a multi-noble state outside
        // the scoring phase. Both retain the pre-v0.2.3 behavior.
        state.nobles = vec![NobleId(0)];
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0]
                .noble_race_progress,
            0
        );
        state.nobles = vec![NobleId(0), NobleId(8)];
        state.players[1].prestige = 0;
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0]
                .noble_race_progress,
            0
        );

        let mut ranked_state = multi_noble_scoring_state(62);
        ranked_state.players[0].reserved = vec![ReservedCard {
            card: CardId(74),
            from_deck: false,
        }];
        let own = OwnProjection {
            tokens: ranked_state.players[0].tokens,
            bonuses: ranked_state.players[0].bonuses,
            prestige: ranked_state.players[0].prestige,
        };
        let ranked = select_targets(
            &[*card(CardId(8)), *card(CardId(74)), *card(CardId(24))],
            &own,
            &ranked_state.observation(PlayerId(0)),
            DevelopmentPhase::Score,
        );
        assert_eq!(ranked[0].id, CardId(24), "white helps both near nobles");
        assert_eq!(ranked[1].id, CardId(74), "valuable own reserve is next");
    }

    #[test]
    fn high_cost_three_vp_and_legal_high_efficiency_reserve_get_race_bonus() {
        let mut market_state = multi_noble_scoring_state(63);
        expose(&mut market_state, CardId(74), 0); // T3, 3VP, printed cost 14
        give_race_buy_tokens(&mut market_state);
        let market_buy = Action::BuyMarket {
            tier: Tier::Three,
            slot: 0,
        };
        assert!(market_state.legal_actions().contains(&market_buy));
        let market_score =
            heuristic_v02_term_scores(&market_state.observation(PlayerId(0)), &[market_buy])[0];
        assert_eq!(market_score.noble_race_three_vp, NOBLE_RACE_THREE_VP_WEIGHT);
        assert_eq!(market_score.noble_race_reserved, 0);

        let mut reserved_state = multi_noble_scoring_state(64);
        expose(&mut reserved_state, CardId(74), 0);
        reserved_state.market[Tier::Three.index()][0] = None;
        reserved_state.players[0].reserved.push(ReservedCard {
            card: CardId(74),
            from_deck: false,
        });
        give_race_buy_tokens(&mut reserved_state);
        let reserved_buy = Action::BuyReserved { slot: 0 };
        assert!(reserved_state.legal_actions().contains(&reserved_buy));
        assert_eq!(reserve_efficiency(card(CardId(74)), [2, 4, 2, 0, 3]), 750);
        let reserved_score =
            heuristic_v02_term_scores(&reserved_state.observation(PlayerId(0)), &[reserved_buy])[0];
        assert_eq!(
            reserved_score.noble_race_three_vp,
            NOBLE_RACE_THREE_VP_WEIGHT
        );
        assert_eq!(
            reserved_score.noble_race_reserved,
            NOBLE_RACE_RESERVED_WEIGHT
        );
        assert_eq!(reserved_score.vp_efficiency, 900);
    }

    #[test]
    fn winnable_only_race_progress_and_priority() {
        // v0.2.4: races the opponent is strictly closer on earn nothing.
        let mut lost = game(66);
        lost.nobles = vec![NobleId(0), NobleId(8)];
        lost.players[0].bonuses = [2, 2, 1, 0, 0]; // near both: missing 4 and 4
        lost.players[1].bonuses = [3, 3, 3, 0, 0]; // strictly closer: 0 and 2
        lost.players[1].prestige = 12;
        expose(&mut lost, CardId(0), 0);
        lost.players[0].tokens.black = 3;
        lost.bank.black -= 3;
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        assert!(lost.legal_actions().contains(&buy));
        let s = heuristic_v02_term_scores(&lost.observation(PlayerId(0)), &[buy])[0];
        assert_eq!(s.noble_race_progress, 0, "both near nobles are lost races");

        // One winnable, one lost: only the winnable one's progress counts.
        let mut mixed = lost.clone();
        mixed.players[1].bonuses = [3, 0, 3, 0, 0]; // noble0 lost (3<4), noble8 winnable (5>4)
        let s = heuristic_v02_term_scores(&mixed.observation(PlayerId(0)), &[buy])[0];
        assert_eq!(
            s.noble_race_progress, NOBLE_RACE_PROGRESS_WEIGHT,
            "blue advances noble0(lost)+noble8(winnable); only winnable counts"
        );

        // Target priority: with both nobles lost, white-bonus cards get no
        // race-first group; with an idle opponent they do.
        let mut ranked_state = game(67);
        ranked_state.nobles = vec![NobleId(0), NobleId(8)];
        ranked_state.players[0].bonuses = [2, 4, 2, 0, 3]; // near both: 4 and 3
        ranked_state.players[1].bonuses = [4, 3, 3, 0, 0]; // strictly closer: 0 and 1
        ranked_state.players[1].prestige = 12;
        ranked_state.players[0].reserved = vec![ReservedCard {
            card: CardId(74),
            from_deck: false,
        }];
        let own = OwnProjection {
            tokens: ranked_state.players[0].tokens,
            bonuses: ranked_state.players[0].bonuses,
            prestige: ranked_state.players[0].prestige,
        };
        let ranked = select_targets(
            &[*card(CardId(24)), *card(CardId(74))],
            &own,
            &ranked_state.observation(PlayerId(0)),
            DevelopmentPhase::Score,
        );
        assert_eq!(ranked[0].id, CardId(74), "lost races get no priority");
        let mut win_state = ranked_state.clone();
        win_state.players[1].bonuses = [0; 5];
        let own2 = OwnProjection {
            tokens: win_state.players[0].tokens,
            ..own
        };
        let ranked2 = select_targets(
            &[*card(CardId(24)), *card(CardId(74))],
            &own2,
            &win_state.observation(PlayerId(0)),
            DevelopmentPhase::Score,
        );
        assert_eq!(
            ranked2[0].id,
            CardId(24),
            "winnable races keep group-0 priority"
        );
    }

    fn readiness_fixture() -> FullState {
        let mut state = game(68);
        expose(&mut state, CardId(45), 0); // 3VP, six blue; exact colored cost below.
                                           // Keep one known market card, returning the other identities to their
                                           // own decks so these fixtures do not duplicate/discard hidden cards.
        for tier in Tier::ALL {
            for slot in 0..4 {
                if state.market[tier.index()][slot] != Some(CardId(45)) {
                    if let Some(id) = state.market[tier.index()][slot].take() {
                        state.decks[tier.index()].push(id);
                    }
                }
            }
        }
        state.players[0].bonuses = [0, 3, 0, 0, 0];
        state.players[0].tokens.blue = 2;
        state.bank.blue -= 2;
        state.players[1].prestige = 12; // public emergency Score phase
        state
    }

    fn ready_take() -> Action {
        Action::TakeTokens {
            take: Gems {
                white: 1,
                blue: 1,
                green: 1,
                ..Gems::ZERO
            },
            give_back: Gems::ZERO,
        }
    }

    #[test]
    fn scoring_readiness_counts_known_market_and_own_reserve_equally() {
        let market = readiness_fixture();
        let action = ready_take();
        assert!(market.legal_actions().contains(&action));
        let market_terms =
            heuristic_v02_term_scores(&market.observation(PlayerId(0)), &[action])[0];
        assert_eq!(market_terms.scoring_readiness, 3 * SCORING_READINESS_PER_VP);
        assert_eq!(
            market_terms.immediate_prestige, 0,
            "readiness is not earned VP"
        );
        let mut held = market.clone();
        held.market[Tier::Two.index()][0] = None;
        held.players[0].reserved.push(ReservedCard {
            card: CardId(45),
            from_deck: true,
        });
        assert!(held.legal_actions().contains(&action));
        assert_eq!(
            heuristic_v02_term_scores(&held.observation(PlayerId(0)), &[action])[0]
                .scoring_readiness,
            market_terms.scoring_readiness,
            "own blind reserve is known to its owner, not worth extra by sunk cost"
        );
        let all = market.legal_actions();
        let i = all.iter().position(|a| *a == action).unwrap();
        assert_eq!(
            heuristic_v02_term_scores(&market.observation(PlayerId(0)), &all)[i],
            market_terms
        );
    }

    #[test]
    fn scoring_readiness_is_incremental_max_not_sum_or_repeated_reward() {
        let three = *card(CardId(45));
        let two = *card(CardId(42));
        let before = OwnProjection {
            tokens: Gems {
                blue: 2,
                ..Gems::ZERO
            },
            bonuses: [0, 3, 0, 0, 0],
            prestige: 0,
        };
        let after = OwnProjection {
            tokens: Gems {
                blue: 3,
                ..Gems::ZERO
            },
            ..before
        };
        assert_eq!(best_affordable_card_vp(&[two, three], &before), 2);
        assert_eq!(best_affordable_card_vp(&[two, three], &after), 3);
        assert_eq!(
            best_affordable_card_vp(&[three, three], &after),
            3,
            "same tokens buy only one card"
        );
        assert_eq!(best_affordable_card_vp(&[], &after), 0);
        let mut state = readiness_fixture();
        let index = state.decks[Tier::Two.index()]
            .iter()
            .position(|id| *id == CardId(42))
            .unwrap();
        state.decks[Tier::Two.index()].remove(index);
        state.market[Tier::Two.index()][1] = Some(CardId(42));
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[ready_take()])[0]
                .scoring_readiness,
            SCORING_READINESS_PER_VP,
            "one already-affordable 2VP card leaves only a 1VP readiness increment"
        );
        state.players[0].tokens.blue += 1;
        state.bank.blue -= 1;
        assert!(state.legal_actions().contains(&ready_take()));
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[ready_take()])[0]
                .scoring_readiness,
            0
        );
    }

    #[test]
    fn scoring_readiness_uses_gold_and_exact_legal_returns_without_blind_card_value() {
        let mut state = readiness_fixture();
        let mut obs = state.observation(PlayerId(0));
        let visible = Action::ReserveMarket {
            tier: Tier::Two,
            slot: 0,
            give_back: Gems::ZERO,
        };
        let blind = Action::ReserveDeck {
            tier: Tier::Three,
            give_back: Gems::ZERO,
        };
        assert!([visible, blind]
            .iter()
            .all(|a| state.legal_actions().contains(a)));
        let terms = heuristic_v02_term_scores(&obs, &[visible, blind]);
        assert_eq!(terms[0].scoring_readiness, 3 * SCORING_READINESS_PER_VP);
        assert_eq!(terms[1].scoring_readiness, terms[0].scoring_readiness);
        assert_eq!(terms[1].immediate_prestige, 0);
        state.decks[Tier::Three.index()].reverse();
        assert_eq!(obs, state.observation(PlayerId(0)));
        assert_eq!(
            terms,
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[visible, blind])
        );
        obs.public.bank.gold = 0;
        assert_eq!(
            heuristic_v02_term_scores(&obs, &[blind])[0].scoring_readiness,
            0,
            "no gold means no invented improvement"
        );

        let mut full = readiness_fixture();
        for (c, n) in [
            (GemColor::White, 3),
            (GemColor::Green, 3),
            (GemColor::Red, 2),
        ] {
            full.players[0].tokens.set_color(c, n);
            full.bank.set_color(c, full.bank.color(c) - n);
        }
        assert_eq!(full.players[0].tokens.total(), 10);
        let keep_gold = Action::ReserveDeck {
            tier: Tier::Three,
            give_back: Gems {
                white: 1,
                ..Gems::ZERO
            },
        };
        let return_gold = Action::ReserveDeck {
            tier: Tier::Three,
            give_back: Gems {
                gold: 1,
                ..Gems::ZERO
            },
        };
        assert!([keep_gold, return_gold]
            .iter()
            .all(|a| full.legal_actions().contains(a)));
        let terms =
            heuristic_v02_term_scores(&full.observation(PlayerId(0)), &[keep_gold, return_gold]);
        assert_eq!(terms[0].scoring_readiness, 3 * SCORING_READINESS_PER_VP);
        assert_eq!(terms[1].scoring_readiness, 0);
        let no_net = full
            .legal_actions()
            .into_iter()
            .find(|a| matches!(a, Action::TakeTokens { take, give_back } if take == give_back))
            .unwrap();
        assert_eq!(
            heuristic_v02_term_scores(&full.observation(PlayerId(0)), &[no_net])[0]
                .scoring_readiness,
            0
        );
    }

    #[test]
    fn scoring_readiness_is_off_during_build_final_round_and_real_purchases() {
        let mut state = readiness_fixture();
        state.players[1].prestige = 0;
        for bonuses in [[0, 3, 0, 0, 0], [2, 3, 0, 0, 0]] {
            state.players[0].bonuses = bonuses;
            assert_eq!(
                heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[ready_take()])[0]
                    .scoring_readiness,
                0
            );
        }
        state.players[1].prestige = 12;
        state.end_game_triggered = true;
        state.turns_remaining_in_final_round = Some(1);
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[ready_take()])[0]
                .scoring_readiness,
            0
        );
        let mut buy_state = readiness_fixture();
        buy_state.players[0].tokens.blue += 1;
        buy_state.bank.blue -= 1;
        let buy = Action::BuyMarket {
            tier: Tier::Two,
            slot: 0,
        };
        assert!(buy_state.legal_actions().contains(&buy));
        let terms = heuristic_v02_term_scores(&buy_state.observation(PlayerId(0)), &[buy])[0];
        assert_eq!(terms.scoring_readiness, 0);
        assert_eq!(terms.immediate_prestige, 3 * (VP_WEIGHT + VP_LATE_BONUS));
    }

    #[test]
    fn scoring_readiness_cannot_see_opponent_blind_card_identities() {
        let mut state = readiness_fixture();
        let id = state.decks[Tier::Three.index()].pop().unwrap();
        state.players[1].reserved.push(ReservedCard {
            card: id,
            from_deck: true,
        });
        let obs = state.observation(PlayerId(0));
        let legal = state.legal_actions();
        let scores = heuristic_v02_term_scores(&obs, &legal);
        assert!(
            scores.iter().any(|t| t.scoring_readiness > 0),
            "test must exercise enabled term"
        );
        let other = state.decks[Tier::Three.index()][0];
        state.decks[Tier::Three.index()][0] = id;
        state.players[1].reserved[0].card = other;
        assert_eq!(obs, state.observation(PlayerId(0)));
        assert_eq!(legal, state.legal_actions());
        assert_eq!(
            scores,
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &legal)
        );
    }

    #[test]
    fn early_reservation_count_guard_starts_at_two_and_is_off_in_scoring() {
        let mut state = game(65);
        let first = state.market[Tier::Three.index()][0].take().unwrap();
        let second = state.market[Tier::Three.index()][1].take().unwrap();
        state.players[0].reserved = vec![
            ReservedCard {
                card: first,
                from_deck: false,
            },
            ReservedCard {
                card: second,
                from_deck: false,
            },
        ];
        let legal = state.legal_actions();
        let visible = legal
            .iter()
            .copied()
            .find(|a| matches!(a, Action::ReserveMarket { .. }))
            .expect("visible reserve remains legal with two held cards");
        let blind = legal
            .iter()
            .copied()
            .find(|a| matches!(a, Action::ReserveDeck { .. }))
            .expect("blind reserve remains legal with two held cards");
        let obs = state.observation(PlayerId(0));
        let scores = heuristic_v02_term_scores(&obs, &[visible, blind]);
        assert_eq!(scores[0].reserve_count_guard, -RESERVE_COUNT_GUARD);
        assert_eq!(scores[1].reserve_count_guard, -RESERVE_COUNT_GUARD);

        state.players[0].reserved.pop();
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[visible])[0]
                .reserve_count_guard,
            0,
            "one reserve is not penalized"
        );
        state.players[0].reserved.push(ReservedCard {
            card: second,
            from_deck: false,
        });
        state.players[1].prestige = 12;
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[visible])[0]
                .reserve_count_guard,
            0,
            "scoring phase keeps the legacy reserve policy"
        );
    }

    #[test]
    fn test_mid_late_route_transitions_and_locking() {
        let mut policy = HeuristicAgentPolicyV02::new();
        let mut state = game(68);
        // Early construction phase
        let obs = state.observation(PlayerId(0));
        policy.update_route(&obs);
        assert_eq!(policy.current_route(), None, "early game has no route lock");

        // Transition to Score phase with CardId(71) (4VP, 7 white) in market
        expose(&mut state, CardId(71), 0);
        state.players[0].bonuses = [4, 0, 0, 0, 0]; // 4 white discount -> deficit is 3 (<= 5)
        state.players[1].prestige = 12; // triggers Score phase
        let score_obs = state.observation(PlayerId(0));
        policy.update_route(&score_obs);
        assert_eq!(
            policy.current_route(),
            Some(MidLateRoute::HighCostRush),
            "locks HighCostRush when 4VP card is reachable"
        );

        // Verify route persistence across subsequent calls (memory check)
        policy.update_route(&score_obs);
        assert_eq!(
            policy.current_route(),
            Some(MidLateRoute::HighCostRush),
            "route remains locked"
        );

        // When bonuses drop so no 3+ VP card is reachable within 5 deficit, exit to Balanced
        state.players[0].bonuses = [0, 0, 0, 0, 0];
        let empty_obs = state.observation(PlayerId(0));
        policy.update_route(&empty_obs);
        assert_eq!(
            policy.current_route(),
            Some(MidLateRoute::Balanced),
            "transitions to Balanced when high cost route exhausted"
        );
    }

    #[test]
    fn test_high_cost_rush_suppresses_low_vp_buy_favoring_token_take() {
        let mut state = game(68);
        // Expose CardId(71) (Tier 3, 4VP, 7 white) at slot 0
        expose(&mut state, CardId(71), 0);
        // Expose CardId(7) (Tier 1, 1VP, 4 red) at Tier 1 slot 0
        expose(&mut state, CardId(7), 0);
        state.players[0].bonuses = [4, 0, 0, 4, 0]; // 4 white (needs 3 white for 71), 4 red (can buy 7 right now!)

        let buy_1vp = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        let buy_4vp = Action::BuyMarket {
            tier: Tier::Three,
            slot: 0,
        };
        let reserve_4vp = Action::ReserveMarket {
            tier: Tier::Three,
            slot: 0,
            give_back: Gems::ZERO,
        };

        let obs = state.observation(PlayerId(0));

        // Under HighCostRush:
        // CardId(7) bonus is Blue, while CardId(71) demands White.
        // So CardId(7) does NOT contribute to White, and gets suppressed!
        let rush_scores = heuristic_v02_term_scores_with_route(
            &obs,
            &[buy_1vp, reserve_4vp],
            Some(MidLateRoute::HighCostRush),
        );
        assert_eq!(
            rush_scores[0].route_guidance, LOW_VP_RUSH_SUPPRESSION,
            "1VP buy unrelated to target color is suppressed"
        );
        assert_eq!(
            rush_scores[1].route_guidance, HIGH_VP_RUSH_PROTECT_BONUS,
            "reserving 4VP card is protected"
        );

        // Now test color exemption: if an affordable 1VP card provides White (which 71 demands),
        // it must be completely EXEMPT from suppression (route_guidance == 0)
        let white_1vp_card = splendor_catalog::all_cards()
            .iter()
            .find(|c| c.bonus == GemColor::White && c.prestige == 1)
            .unwrap();
        expose(&mut state, white_1vp_card.id, 1);
        // Ensure player has enough tokens to legally afford white_1vp_card
        state.players[0].tokens.gold = 5;
        let buy_white_1vp = Action::BuyMarket {
            tier: white_1vp_card.tier,
            slot: 1,
        };
        let obs_with_white = state.observation(PlayerId(0));
        let white_scores = heuristic_v02_term_scores_with_route(
            &obs_with_white,
            &[buy_white_1vp],
            Some(MidLateRoute::HighCostRush),
        );
        assert_eq!(
            white_scores[0].route_guidance, 0,
            "1VP card contributing to target color is exempt from suppression"
        );

        // When buy_4vp is affordable:
        state.players[0].tokens.white = 3;
        let obs_ready = state.observation(PlayerId(0));
        let ready_scores = heuristic_v02_term_scores_with_route(
            &obs_ready,
            &[buy_4vp],
            Some(MidLateRoute::HighCostRush),
        );
        assert_eq!(
            ready_scores[0].route_guidance, HIGH_VP_RUSH_EXECUTION_BONUS,
            "executing 4VP buy is strongly boosted"
        );
    }

    #[test]
    fn test_tycoon_route_rewards_scoring_cards_and_immediate_claim() {
        let mut state = game(68);
        let target_noble = state.nobles[0];
        let noble_req = all_nobles()[target_noble.index()].requirements;

        // Find a color required by the noble
        let req_color = GemColor::ALL
            .into_iter()
            .find(|&c| noble_req[c.index()] > 0)
            .unwrap();

        // Expose a card with prestige >= 1 that has that color
        let scoring_card = splendor_catalog::all_cards()
            .iter()
            .find(|c| c.bonus == req_color && c.prestige >= 1)
            .unwrap();
        expose(&mut state, scoring_card.id, 0);

        // Give player enough tokens to legally afford the card
        state.players[0].tokens.gold = 5;

        let buy_action = Action::BuyMarket {
            tier: scoring_card.tier,
            slot: 0,
        };
        let obs = state.observation(PlayerId(0));
        let scores = heuristic_v02_term_scores_with_route(
            &obs,
            &[buy_action],
            Some(MidLateRoute::Tycoon {
                target: target_noble,
            }),
        );
        assert_eq!(
            scores[0].route_guidance, TYCOON_SCORING_CARD_BONUS,
            "scoring card contributing to target noble gets tycoon bonus"
        );
    }

    #[test]
    fn test_route_cannot_see_hidden_information() {
        let mut state = readiness_fixture();
        let mut policy = HeuristicAgentPolicyV02::new();
        let obs = state.observation(PlayerId(0));
        policy.update_route(&obs);
        let route_before = policy.current_route();
        let scores_before =
            heuristic_v02_term_scores_with_route(&obs, &state.legal_actions(), route_before);

        // Permute opponent's hidden deck
        state.decks[Tier::Three.index()].reverse();
        let obs_after = state.observation(PlayerId(0));
        let mut policy_after = HeuristicAgentPolicyV02::new();
        policy_after.update_route(&obs_after);
        let route_after = policy_after.current_route();
        let scores_after =
            heuristic_v02_term_scores_with_route(&obs_after, &state.legal_actions(), route_after);

        assert_eq!(obs, obs_after, "observation must be identical");
        assert_eq!(
            route_before, route_after,
            "route determination must be identical"
        );
        assert_eq!(scores_before, scores_after, "scores must be identical");
    }
}
