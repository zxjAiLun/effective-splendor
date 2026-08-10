//! Deterministic heuristic agent policy (Evaluation v1 baseline).
//!
//! This policy is the first "purposeful" agent for the SDK. It chooses among
//! the server-certified `legal_actions` using ONLY the [`DecisionContext`]:
//! the current player's `Observation`, the public request metadata, and its own
//! `StableRng`. It never imports `FullState`, `FullStateHash`, `ReplayV1`,
//! `ArenaReportV1`, the raw setup seed, an opponent's blind-reserved `CardId`,
//! or the deck order, and it never calls `FullState::legal_actions` / `apply`.
//!
//! Scoring is pure integer, deterministic, and free of floating point, wall
//! clocks, `HashMap` iteration order, and RNG noise. The RNG is used ONLY to
//! break ties among actions that share the maximum score; when a unique
//! maximum exists no RNG is consumed, so the same transcript + seed always
//! yields the same action.

use splendor_catalog::{all_nobles, card, CardDef, GemColor, NobleId, Tier};
use splendor_core::{Action, Gems, Observation};

use crate::policy::{AgentPolicy, DecisionContext};

/// Public name this policy declares in its `Client Hello`.
pub const HEURISTIC_AGENT_NAME: &str = "splendor-cli-heuristic";

/// Public version this policy declares in its `Client Hello`.
pub const HEURISTIC_AGENT_VERSION: &str = "0.1.0";

/// The deterministic heuristic policy.
pub struct HeuristicAgentPolicy;

impl HeuristicAgentPolicy {
    pub fn new() -> Self {
        HeuristicAgentPolicy
    }
}

impl Default for HeuristicAgentPolicy {
    fn default() -> Self {
        Self::new()
    }
}

impl AgentPolicy for HeuristicAgentPolicy {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let scores = score_actions(&context.observation, context.legal_actions);
        let max = *scores.iter().max().unwrap_or(&i64::MIN);
        // The RNG is consumed ONLY among actions that share the top score.
        let best: Vec<usize> = scores
            .iter()
            .enumerate()
            .filter(|(_, &s)| s == max)
            .map(|(i, _)| i)
            .collect();
        let idx = if best.len() == 1 {
            best[0]
        } else {
            best[context.rng.index(best.len())]
        };
        Ok(context.legal_actions[idx])
    }
}

// ---------------------------------------------------------------------------
// Scoring weights (named integer constants, frozen for v1 behavior)
// ---------------------------------------------------------------------------

/// Category base scores; a higher base means the category is preferred.
const SCORE_BUY: i64 = 1_000_000;
const SCORE_TAKE: i64 = 100_000;
const SCORE_RESERVE_VISIBLE: i64 = 10_000;
const SCORE_RESERVE_BLIND: i64 = 1_000;
const SCORE_PASS: i64 = 0;

/// Buy feature weights.
const BUY_PRESTIGE: i64 = 5_000;
const BUY_NOBLE_GAIN: i64 = 60_000;
const BUY_COST_EFFICIENCY: i64 = 50;

/// Take feature weights.
const TAKE_DEFICIT_REDUCTION: i64 = 1_500;
const TAKE_NEW_TARGET: i64 = 8_000;
const TAKE_RETURN_PENALTY: i64 = 1_000;
const TAKE_GOLD_VALUE: i64 = 200;

/// Reserve-visible feature weights.
const RESERVE_PRESTIGE: i64 = 1_500;
const RESERVE_PROXIMITY: i64 = 250;
const RESERVE_GOLD: i64 = 300;

/// Weight applied to a card's bonus-color usefulness in both buy and reserve
/// scoring (see [`bonus_usefulness`]).
const BONUS_USEFULNESS_WEIGHT: i64 = 1_000;

/// Reserve-blind feature weights.
const RESERVE_BLIND_GOLD: i64 = 250;

/// Direct value of claiming a noble (during the `ChooseNoble` phase).
const NOBLE_DIRECT: i64 = 60_000;

// ---------------------------------------------------------------------------
// Scoring
// ---------------------------------------------------------------------------

/// Score every legal action for `obs`. The returned vector is aligned with
/// `actions` by index.
fn score_actions(obs: &Observation, actions: &[Action]) -> Vec<i64> {
    let me = obs
        .public
        .players
        .iter()
        .find(|p| p.id == obs.viewer)
        .expect("an observation must include the viewer's public view");
    let tokens = me.tokens;
    let bonuses = me.bonuses;

    // Target cards: visible market cards plus the viewer's own reserved cards
    // (both are fully known to the viewer — a blind reserve still reveals its
    // card to the owner, so it is NOT referee-only information).
    let mut targets: Vec<CardDef> = Vec::new();
    for tier in Tier::ALL {
        for slot in 0..4usize {
            if let Some(id) = obs.public.market[tier.index()][slot] {
                targets.push(*card(id));
            }
        }
    }
    for rv in &obs.private.reserved {
        targets.push(*card(rv.card));
    }

    let nobles_in_play: Vec<NobleId> = obs.public.nobles.clone();
    let bonus_useful = bonus_usefulness(&targets, bonuses);
    let nobles_now = nobles_completable(&nobles_in_play, bonuses);
    let gold_available = obs.public.bank.gold > 0;

    actions
        .iter()
        .map(|action| match *action {
            Action::BuyMarket { tier, slot } => {
                let id = obs.public.market[tier.index()][slot as usize]
                    .expect("a legal buy references a present market card");
                score_buy(
                    *card(id),
                    &nobles_in_play,
                    bonuses,
                    nobles_now,
                    &bonus_useful,
                )
            }
            Action::BuyReserved { slot } => {
                let id = obs.private.reserved[slot as usize].card;
                score_buy(
                    *card(id),
                    &nobles_in_play,
                    bonuses,
                    nobles_now,
                    &bonus_useful,
                )
            }
            Action::TakeTokens { take, give_back } => {
                score_take(take, give_back, &targets, tokens, bonuses)
            }
            Action::ReserveMarket {
                tier,
                slot,
                give_back,
            } => {
                let id = obs.public.market[tier.index()][slot as usize]
                    .expect("a legal reserve references a present market card");
                score_reserve_visible(
                    *card(id),
                    give_back,
                    tokens,
                    bonuses,
                    gold_available,
                    &bonus_useful,
                )
            }
            Action::ReserveDeck { give_back, .. } => score_reserve_blind(give_back, gold_available),
            Action::ChooseNoble { .. } => SCORE_BUY + 3 * BUY_PRESTIGE + NOBLE_DIRECT,
            Action::Pass => SCORE_PASS,
        })
        .collect()
}

/// Score a buy (market or reserved) of `card`.
fn score_buy(
    card: CardDef,
    nobles_in_play: &[NobleId],
    bonuses: [u8; 5],
    nobles_now: usize,
    bonus_useful: &[i64; 5],
) -> i64 {
    let mut s = SCORE_BUY;
    s += card.prestige as i64 * BUY_PRESTIGE;

    // A buy that completes a noble is worth a large premium.
    let mut bonuses_after = bonuses;
    bonuses_after[card.bonus.index()] += 1;
    let nobles_after = nobles_completable(nobles_in_play, bonuses_after);
    let gain = nobles_after.saturating_sub(nobles_now);
    s += gain as i64 * BUY_NOBLE_GAIN;

    // Reward the bonus color this card grants if it is still useful.
    s += bonus_useful[card.bonus.index()] * BONUS_USEFULNESS_WEIGHT;

    // Cheaper cards are marginally preferred among equal prestige/noble gains.
    s -= card.total_cost() as i64 * BUY_COST_EFFICIENCY;
    s
}

/// Score a `TakeTokens` action by how much it shrinks the token deficit toward
/// the target cards, whether it makes a target affordable, and the tokens it is
/// forced to return.
fn score_take(
    take: Gems,
    give_back: Gems,
    targets: &[CardDef],
    tokens: Gems,
    bonuses: [u8; 5],
) -> i64 {
    let mut s = SCORE_TAKE;

    let before: i64 = targets
        .iter()
        .map(|c| card_deficit(c, tokens, bonuses))
        .sum();
    let after = apply_take(tokens, take, give_back);
    let after_total: i64 = targets
        .iter()
        .map(|c| card_deficit(c, after, bonuses))
        .sum();
    let reduction = before - after_total;
    s += reduction * TAKE_DEFICIT_REDUCTION;

    let newly = targets
        .iter()
        .filter(|c| card_deficit(c, tokens, bonuses) > 0 && card_deficit(c, after, bonuses) == 0)
        .count() as i64;
    s += newly * TAKE_NEW_TARGET;

    // Tokens forced back to the bank are wasted acquisition.
    s -= give_back.total() as i64 * TAKE_RETURN_PENALTY;

    // Gold is a wild resource usable against any color deficit.
    s += take.gold as i64 * TAKE_GOLD_VALUE;
    s
}

/// Score a visible-card reserve.
fn score_reserve_visible(
    card: CardDef,
    give_back: Gems,
    tokens: Gems,
    bonuses: [u8; 5],
    gold_available: bool,
    bonus_useful: &[i64; 5],
) -> i64 {
    let mut s = SCORE_RESERVE_VISIBLE;
    s += card.prestige as i64 * RESERVE_PRESTIGE;
    s += bonus_useful[card.bonus.index()] * BONUS_USEFULNESS_WEIGHT;
    // Prefer reserving cards we are closer to affording.
    s -= card_deficit(&card, tokens, bonuses) * RESERVE_PROXIMITY;
    if gold_available {
        s += RESERVE_GOLD;
    }
    s -= give_back.total() as i64 * TAKE_RETURN_PENALTY;
    s
}

/// Score a blind deck reserve (no public card information is available).
fn score_reserve_blind(give_back: Gems, gold_available: bool) -> i64 {
    let mut s = SCORE_RESERVE_BLIND;
    if gold_available {
        s += RESERVE_BLIND_GOLD;
    }
    s -= give_back.total() as i64 * TAKE_RETURN_PENALTY;
    s
}

/// Tokens a player would hold after the take/give-back exchange, capped at the
/// per-player maximum so deficit math stays realistic.
fn apply_take(tokens: Gems, take: Gems, give_back: Gems) -> Gems {
    let mut after = Gems::ZERO;
    for c in GemColor::ALL {
        let v = (tokens.color(c) as i64 + take.color(c) as i64 - give_back.color(c) as i64)
            .clamp(0, 10) as u8;
        after.set_color(c, v);
    }
    let g = (tokens.gold as i64 + take.gold as i64 - give_back.gold as i64).clamp(0, 10) as u8;
    after.gold = g;
    after
}

/// Minimum colored+gold tokens still needed to afford `card`, given current
/// `tokens` and permanent `bonuses`. Gold can pay any color shortfall.
fn card_deficit(card: &CardDef, tokens: Gems, bonuses: [u8; 5]) -> i64 {
    let mut raw: i64 = 0;
    for c in GemColor::ALL {
        let need = card.cost[c.index()] as i64 - bonuses[c.index()] as i64;
        if need > 0 {
            let short = need - tokens.color(c) as i64;
            if short > 0 {
                raw += short;
            }
        }
    }
    let gold = tokens.gold as i64;
    if raw > gold {
        raw - gold
    } else {
        0
    }
}

/// How many in-play nobles are already completable with `bonuses`.
fn nobles_completable(nobles: &[NobleId], bonuses: [u8; 5]) -> usize {
    let all = all_nobles();
    nobles
        .iter()
        .filter(|&&id| {
            let def = &all[id.index()];
            GemColor::ALL
                .iter()
                .all(|&c| bonuses[c.index()] >= def.requires(c))
        })
        .count()
}

/// Per-color usefulness: total unmet need (relative to current bonuses) across
/// target cards that are not yet affordable. A higher value means gaining a
/// bonus of that color would help buy more cards.
fn bonus_usefulness(targets: &[CardDef], bonuses: [u8; 5]) -> [i64; 5] {
    let mut useful = [0i64; 5];
    for card in targets {
        let need_total = card_deficit(card, Gems::ZERO, bonuses);
        if need_total > 0 {
            for c in GemColor::ALL {
                let need = card.cost[c.index()] as i64 - bonuses[c.index()] as i64;
                if need > 0 {
                    useful[c.index()] += need;
                }
            }
        }
    }
    useful
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{DecisionContext, PublicRequestMeta, StableRng};
    use splendor_catalog::CardId;
    use splendor_core::{observation_hash, FullState, GameConfig, PlayerId};

    fn obs_for_state(state: FullState) -> (Observation, Vec<Action>) {
        let obs = state.observation(PlayerId(0));
        let actions = state.legal_actions();
        (obs, actions)
    }

    fn decide(obs: &Observation, actions: &[Action], seed: u64) -> Action {
        let mut rng = StableRng::new(seed);
        let ctx = DecisionContext {
            observation: obs.clone(),
            visible_history: &[],
            legal_actions: actions,
            meta: PublicRequestMeta {
                game_id: "t".into(),
                recipient_seat: PlayerId(0),
                request_id: 1,
                observation_hash: observation_hash(obs),
            },
            rng: &mut rng,
        };
        HeuristicAgentPolicy::new().choose_action(ctx).unwrap()
    }

    // Return accounting: two take actions that reduce the same deficit must be
    // ranked by how many tokens they are forced to give back.
    #[test]
    fn returned_tokens_are_accounted_for() {
        // One target card needs exactly 1 white; the viewer already holds 10
        // white tokens, so neither take changes the deficit — only the return
        // penalty differs.
        let (mut state, _) = FullState::new(GameConfig {
            seed: 3,
            ..Default::default()
        })
        .expect("setup");
        for tier in Tier::ALL {
            for slot in 0..4usize {
                state.market[tier.index()][slot] = None;
            }
        }
        state.market[0][0] = Some(CardId(1)); // white-costing card
        state.bank = Gems {
            white: 4,
            blue: 1,
            green: 1,
            ..Gems::ZERO
        };
        state.players[0].tokens = Gems {
            white: 10,
            ..Gems::ZERO
        };
        state.players[0].bonuses = [0, 5, 5, 5, 5];

        let obs = state.observation(PlayerId(0));
        let low_return = Action::TakeTokens {
            take: Gems {
                white: 2,
                ..Gems::ZERO
            },
            give_back: Gems {
                white: 2,
                ..Gems::ZERO
            },
        };
        let high_return = Action::TakeTokens {
            take: Gems {
                white: 1,
                blue: 1,
                green: 1,
                ..Gems::ZERO
            },
            give_back: Gems {
                white: 1,
                blue: 1,
                green: 1,
                ..Gems::ZERO
            },
        };
        let scores = score_actions(&obs, &[high_return, low_return]);
        // high_return gives back 3 tokens, low_return gives back 2; the smaller
        // return must score higher when deficit reduction is identical.
        assert!(
            scores[1] > scores[0],
            "smaller return should outrank larger return: {scores:?}"
        );
    }

    // Tie-break discipline: a unique maximum is chosen deterministically
    // (independent of seed), while a tie is broken by the RNG within the tied
    // set only.
    #[test]
    fn tie_break_is_confined_to_max_score_actions() {
        // Unique maximum: one affordable buy dominates every take/reserve.
        let (mut state, _) = FullState::new(GameConfig {
            seed: 7,
            ..Default::default()
        })
        .expect("setup");
        for tier in Tier::ALL {
            for slot in 0..4usize {
                state.market[tier.index()][slot] = None;
            }
        }
        state.market[0][0] = Some(CardId(7)); // affordable tier-1 card
        state.bank = Gems {
            white: 4,
            ..Gems::ZERO
        };
        state.players[0].tokens = Gems {
            blue: 4,
            ..Gems::ZERO
        };
        state.players[0].bonuses = [5, 0, 5, 5, 5];
        let (obs, actions) = obs_for_state(state);
        let a1 = decide(&obs, &actions, 1);
        let a2 = decide(&obs, &actions, 2);
        assert_eq!(a1, a2, "unique maximum must be seed-independent");
        assert!(
            matches!(a1, Action::BuyMarket { .. }),
            "expected a buy to win"
        );

        // Tie among symmetric take actions with no buys/reserves to break it:
        // the only distinction is the tie-break.
        let (mut state, _) = FullState::new(GameConfig {
            seed: 11,
            ..Default::default()
        })
        .expect("setup");
        state.bank = Gems {
            white: 4,
            black: 4,
            ..Gems::ZERO
        };
        state.players[0].tokens = Gems::ZERO;
        state.players[0].bonuses = [5, 5, 5, 5, 5];
        for tier in Tier::ALL {
            for slot in 0..4usize {
                state.market[tier.index()][slot] = None;
            }
        }
        let (obs, actions) = obs_for_state(state);
        let scores = score_actions(&obs, &actions);
        let max = *scores.iter().max().unwrap();
        let tie_count = scores.iter().filter(|&&s| s == max).count();
        assert!(tie_count >= 2, "expected a genuine tie among takes");

        // Across many seeds the tie-break must only ever pick tied actions.
        let mut seen = std::collections::HashSet::new();
        for seed in 0..16u64 {
            let a = decide(&obs, &actions, seed);
            let idx = actions.iter().position(|x| *x == a).unwrap();
            assert_eq!(scores[idx], max, "tie-break must stay within the top score");
            seen.insert(a);
        }
        assert!(seen.len() >= 2, "tie-break should diversify across seeds");
    }
}
