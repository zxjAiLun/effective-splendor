//! Independent observation-only heuristic v0.2 candidate.
//!
//! All action families share one score scale. This module never accesses a
//! referee state, a deck order, or a hidden opponent reserve. A market refill
//! is deliberately NOT predicted after a buy/reservation.

use splendor_catalog::{all_nobles, card, CardDef, CardId, GemColor, Tier};
use splendor_core::{Action, Gems, Observation};

use crate::policy::{AgentPolicy, DecisionContext};

pub const HEURISTIC_V02_AGENT_NAME: &str = "splendor-cli-heuristic-v02";
pub const HEURISTIC_V02_AGENT_VERSION: &str = "0.2.0";

const TERMINAL_PRIORITY: i64 = 1_000_000;
const VP_WEIGHT: i64 = 1_000;
const SHORTFALL_WEIGHT: i64 = 300;
const BONUS_WEIGHT: i64 = 250;
const READY_WEIGHT: i64 = 500;
const GOLD_WEIGHT: i64 = 150;
const SECURED_WEIGHT: i64 = 500;
const VISIBLE_RESERVE_TEMPO: i64 = 350;
const BLIND_RESERVE_TEMPO: i64 = 500;

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

/// Signed, additive terms. The terminal term represents a *safe lead on
/// reaching 15*, not a claim that the match has already ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub struct HeuristicV02Terms {
    pub terminal_lead: i64,
    pub immediate_prestige: i64,
    pub target_shortfall: i64,
    pub useful_discount: i64,
    pub new_affordable_target: i64,
    pub gold_liquidity: i64,
    pub secured_target: i64,
    pub reserve_tempo: i64,
}

impl HeuristicV02Terms {
    pub fn total(&self) -> i64 {
        self.terminal_lead
            + self.immediate_prestige
            + self.target_shortfall
            + self.useful_discount
            + self.new_affordable_target
            + self.gold_liquidity
            + self.secured_target
            + self.reserve_tempo
    }
}

#[derive(Clone, Copy)]
struct OwnProjection {
    tokens: Gems,
    bonuses: [u8; 5],
    prestige: u8,
}

/// Exact for the visible own token/bonus/VP changes, except that a purchased
/// market slot is intentionally left empty rather than peeking at the refill.
/// Only the already certified legal actions may be scored.
pub fn heuristic_v02_term_scores(obs: &Observation, actions: &[Action]) -> Vec<HeuristicV02Terms> {
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

    actions
        .iter()
        .map(|action| {
            let (after, bought, secured, reserve_tempo) = project_action(obs, *action, before);

            // A bought card is present on neither side of the *comparison*; its
            // realized VP/bonus is scored separately, rather than falsely treating
            // its absence as deterioration in the remaining goal set.
            let remaining: Vec<_> = targets
                .iter()
                .copied()
                .filter(|def| Some(def.id) != bought)
                .collect();
            let selected = select_targets(&remaining, &before, obs);
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
            HeuristicV02Terms {
                terminal_lead: if safe_lead { TERMINAL_PRIORITY } else { 0 },
                // Points beyond 15 still determine the winner in the final round.
                immediate_prestige: i64::from(after.prestige - before.prestige) * VP_WEIGHT,
                target_shortfall: shortfall * SHORTFALL_WEIGHT,
                useful_discount: discount * BONUS_WEIGHT,
                new_affordable_target: if newly_ready { READY_WEIGHT } else { 0 },
                gold_liquidity: (i64::from(after.tokens.gold.min(3))
                    - i64::from(before.tokens.gold.min(3)))
                    * GOLD_WEIGHT,
                secured_target: if secured { SECURED_WEIGHT } else { 0 },
                reserve_tempo,
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

fn select_targets(targets: &[CardDef], own: &OwnProjection, obs: &Observation) -> Vec<CardDef> {
    let mut demand = [0i64; 5];
    for def in targets {
        for color in GemColor::ALL {
            let c = color.index();
            demand[c] += i64::from(def.cost[c].saturating_sub(own.bonuses[c])).min(2);
        }
    }
    let mut ordered = targets.to_vec();
    ordered.sort_by_key(|def| {
        let color = def.bonus.index();
        let noble_help = obs
            .public
            .nobles
            .iter()
            .filter(|&&id| {
                let noble = &all_nobles()[id.index()];
                own.bonuses[color] < noble.requires(def.bonus)
            })
            .count() as i64;
        let value = 1 + 2 * i64::from(def.prestige) + 2 * demand[color].min(3) + noble_help;
        (
            -(100 * value / (1 + deficit(def, own))),
            deficit(def, own),
            def.id.index(),
        )
    });
    ordered.truncate(2);
    ordered
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
    use splendor_core::{FullState, GameConfig, Phase, PlayerId, Ruleset};

    fn game(seed: u64) -> FullState {
        FullState::new(GameConfig {
            seed,
            player_count: 2,
            ruleset: Ruleset::base_v1(),
        })
        .expect("valid game")
        .0
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
}
