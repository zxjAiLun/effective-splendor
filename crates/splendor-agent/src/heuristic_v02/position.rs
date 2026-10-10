//! Per-observation facts and memoization. Never derive alternatives from the
//! caller's legal-action slice; equal projections may reuse arithmetic only.
use super::*;
use std::cell::RefCell;
use std::collections::HashMap;

pub(super) type Rank = (u8, std::cmp::Reverse<usize>);
type ValueKey = (CardId, [u8; 5], Option<NobleId>);
type TimeKey = (CardId, Gems, [u8; 5], Gems, usize, usize);

pub(super) struct NobleContext {
    pub id: NobleId,
    pub distance: i64,
    pub contestable: bool,
    pub choice_value: i64,
}

pub(super) struct OpponentContext {
    pub seat: usize,
    pub own: OwnProjection,
    pub held: usize,
    pub current_rank: Rank,
    pub affordable: Vec<CardId>,
    pub best_rank: Rank,
}

pub(super) struct PositionContext<'a> {
    pub obs: &'a Observation,
    pub before: OwnProjection,
    pub purchased: usize,
    pub targets: Vec<CardDef>,
    pub ranked: Vec<RankedTarget>,
    pub scoring: i64,
    pub board_demand: [i64; 5],
    pub conversion_demand: [i64; 5],
    pub cheap_buy_weight: i64,
    pub cheap_ready_weight: i64,
    pub conversion_weight: i64,
    pub nobles: Vec<NobleContext>,
    pub has_contestable_noble: bool,
    pub noble_progress: [i64; 5],
    pub noble_build_progress: [i64; 5],
    pub opponents: Vec<OpponentContext>,
    pub finish_pressure: bool,
    pub ready_vp: i64,
    pub immediate_alternative: i64,
    pub reservable: usize,
    values: RefCell<HashMap<ValueKey, i64>>,
    times: RefCell<HashMap<TimeKey, i64>>,
    denial: RefCell<HashMap<CardId, bool>>,
}

impl<'a> PositionContext<'a> {
    pub fn new(obs: &'a Observation) -> Self {
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
        let opponents: Vec<_> = obs
            .public
            .players
            .iter()
            .filter(|p| p.id != obs.viewer)
            .map(|p| {
                let own = OwnProjection {
                    tokens: p.tokens,
                    bonuses: p.bonuses,
                    prestige: p.prestige,
                };
                let affordable: Vec<_> = public_cards(obs, p)
                    .filter(|&id| deficit(card(id), &own) == 0)
                    .collect();
                let current_rank = player_rank(p.prestige, p.purchased.len());
                let best_rank = affordable
                    .iter()
                    .map(|&id| {
                        player_rank(
                            p.prestige + purchase_vp(card(id), p.bonuses, obs),
                            p.purchased.len() + 1,
                        )
                    })
                    .chain(std::iter::once(current_rank))
                    .max()
                    .unwrap();
                OpponentContext {
                    seat: p.id.index(),
                    own,
                    held: usize::from(p.reserved_count),
                    current_rank,
                    affordable,
                    best_rank,
                }
            })
            .collect();
        let finish_pressure = opponents.iter().any(|p| p.best_rank.0 >= 15);
        let scoring = phase_weight_with_pressure(obs, &before, finish_pressure);
        let own_affordable: Vec<_> = targets
            .iter()
            .filter(|d| deficit(d, &before) == 0)
            .map(|d| d.id)
            .collect();
        let nobles: Vec<NobleContext> = obs
            .public
            .nobles
            .iter()
            .copied()
            .map(|id| {
                let distance = noble_distance(id, &before.bonuses);
                let opponent_distance = opponents
                    .iter()
                    .map(|p| noble_distance(id, &p.own.bonuses))
                    .min()
                    .unwrap_or(i64::MAX);
                let own_claim = can_claim(id, before.bonuses, &own_affordable);
                let opponent_claim = opponents
                    .iter()
                    .any(|p| can_claim(id, p.own.bonuses, &p.affordable));
                let contestable = distance <= opponent_distance || own_claim || !opponent_claim;
                let choice_value = opponents
                    .iter()
                    .map(|p| {
                        if can_claim(id, p.own.bonuses, &p.affordable) {
                            50
                        } else {
                            (10 - noble_distance(id, &p.own.bonuses)).max(0)
                        }
                    })
                    .max()
                    .unwrap_or(0);
                NobleContext {
                    id,
                    distance,
                    contestable,
                    choice_value,
                }
            })
            .collect();
        let has_contestable_noble = nobles
            .iter()
            .any(|n| n.contestable && n.distance <= NOBLE_RACE_DISTANCE_MAX);
        let mut noble_progress = [0; 5];
        let mut noble_build_progress = [0; 5];
        for color in GemColor::ALL {
            let c = color.index();
            let mut bonuses = before.bonuses;
            bonuses[c] = bonuses[c].saturating_add(1);
            for n in nobles.iter().filter(|n| n.contestable) {
                let progress = (n.distance - noble_distance(n.id, &bonuses)).max(0);
                if n.distance <= NOBLE_RACE_DISTANCE_MAX {
                    noble_progress[c] += progress;
                }
                if n.distance > 0 && n.distance <= NOBLE_BUILD_DISTANCE_MAX {
                    noble_build_progress[c] += progress;
                }
            }
        }
        let mut board_demand = [0; 5];
        let mut conversion_demand = [0; 5];
        for def in &targets {
            for c in 0..5 {
                board_demand[c] += i64::from(
                    def.cost[c]
                        .saturating_sub(before.bonuses[c])
                        .min(ENGINE_PER_CARD_CAP),
                );
                if def.cost[c] > before.bonuses[c] {
                    conversion_demand[c] += conversion_units(def);
                }
            }
        }
        let mut position = Self {
            obs,
            before,
            purchased: me.purchased.len(),
            targets,
            ranked: Vec::new(),
            scoring,
            board_demand,
            conversion_demand,
            cheap_buy_weight: construction_weight(
                CHEAP_BUY_ULTRA,
                CHEAP_BUY_BUILD,
                &before,
                scoring,
            ),
            cheap_ready_weight: construction_weight(
                CHEAP_READY_ULTRA,
                CHEAP_READY_BUILD,
                &before,
                scoring,
            ),
            conversion_weight: construction_weight(
                CONVERSION_ULTRA,
                CONVERSION_BUILD,
                &before,
                scoring,
            ),
            nobles,
            has_contestable_noble,
            noble_progress,
            noble_build_progress,
            opponents,
            finish_pressure,
            ready_vp: 0,
            immediate_alternative: 0,
            reservable: reservable_count(obs),
            values: RefCell::default(),
            times: RefCell::default(),
            denial: RefCell::default(),
        };
        position.ready_vp = best_affordable_purchase_vp(&position.targets, &before, obs);
        position.ranked = rank_targets(&position, &position.targets, &before);
        position.immediate_alternative = position
            .ranked
            .iter()
            .filter(|t| t.gap == 0)
            .map(|t| t.value)
            .max()
            .unwrap_or(0);
        position
    }

    pub fn value(&self, def: &CardDef, own: &OwnProjection, removed: Option<NobleId>) -> i64 {
        let key = (def.id, own.bonuses, removed);
        if let Some(&value) = self.values.borrow().get(&key) {
            return value;
        }
        let value = purchase_value(def, own, self.obs, &self.targets, removed, self.scoring);
        self.values.borrow_mut().insert(key, value);
        value
    }

    pub fn turns(
        &self,
        def: &CardDef,
        own: &OwnProjection,
        bank: Gems,
        held: usize,
        reservable: usize,
    ) -> i64 {
        let key = (def.id, own.tokens, own.bonuses, bank, held, reservable);
        if let Some(&turns) = self.times.borrow().get(&key) {
            return turns;
        }
        let turns = purchase_turns(def, own, bank, held, reservable);
        self.times.borrow_mut().insert(key, turns);
        turns
    }

    pub fn denies_finish(&self, id: CardId) -> bool {
        if let Some(&denial) = self.denial.borrow().get(&id) {
            return denial;
        }
        let denial = self.opponents.iter().any(|p| {
            p.best_rank.0 >= 15
                && p.best_rank > response_rank(self.obs, p, Some(id), None)
                && self
                    .obs
                    .public
                    .players
                    .iter()
                    .filter(|other| other.id.index() != p.seat)
                    .all(|other| p.best_rank > player_rank(other.prestige, other.purchased.len()))
        });
        self.denial.borrow_mut().insert(id, denial);
        denial
    }

    pub fn noble_choice(&self, action: Action) -> i64 {
        if let Action::ChooseNoble { noble } = action {
            self.nobles
                .iter()
                .find(|n| n.id == noble)
                .map_or(0, |n| n.choice_value)
        } else {
            0
        }
    }
}

fn can_claim(id: NobleId, bonuses: [u8; 5], affordable: &[CardId]) -> bool {
    affordable.iter().any(|&card_id| {
        let mut next = bonuses;
        next[card(card_id).bonus.index()] += 1;
        noble_distance(id, &next) == 0
    })
}

pub(super) fn noble_distance(id: NobleId, bonuses: &[u8; 5]) -> i64 {
    let noble = &all_nobles()[id.index()];
    GemColor::ALL
        .iter()
        .map(|&color| i64::from(noble.requires(color).saturating_sub(bonuses[color.index()])))
        .sum()
}

pub(super) fn reservable_count(obs: &Observation) -> usize {
    obs.public.market.iter().flatten().flatten().count()
        + obs
            .public
            .deck_counts
            .iter()
            .map(|&n| usize::from(n))
            .sum::<usize>()
}

pub(super) fn visible_targets(obs: &Observation) -> Vec<CardDef> {
    obs.public
        .market
        .iter()
        .flatten()
        .filter_map(|&id| id)
        .map(|id| *card(id))
        .chain(obs.private.reserved.iter().map(|r| *card(r.card)))
        .collect()
}

fn public_cards<'a>(
    obs: &'a Observation,
    p: &'a splendor_core::PublicPlayerView,
) -> impl Iterator<Item = CardId> + 'a {
    obs.public
        .market
        .iter()
        .flatten()
        .filter_map(|&id| id)
        .chain(p.public_reserved.iter().copied())
}

fn phase_weight_with_pressure(obs: &Observation, own: &OwnProjection, pressure: bool) -> i64 {
    if obs.public.end_game_triggered {
        return 1000;
    }
    let lead = obs
        .public
        .players
        .iter()
        .map(|p| i64::from(p.prestige))
        .max()
        .unwrap_or(0);
    let discounts = own.bonuses.iter().map(|&b| i64::from(b)).sum::<i64>();
    (((lead - PHASE_LOW) * 1000 / PHASE_SPAN)
        .max((discounts - 5) * 1000 / 8)
        .max(if pressure { 1000 } else { 0 }))
    .clamp(0, 1000)
}

#[cfg(test)]
pub(super) fn phase_weight(obs: &Observation, own: &OwnProjection) -> i64 {
    let position = PositionContext::new(obs);
    phase_weight_with_pressure(obs, own, position.finish_pressure)
}

pub(super) fn construction_weight(
    ultra: i64,
    build: i64,
    own: &OwnProjection,
    scoring: i64,
) -> i64 {
    let discounts = own
        .bonuses
        .iter()
        .map(|&b| i64::from(b))
        .sum::<i64>()
        .min(5);
    (ultra - (ultra - build) * discounts / 5) * (1000 - scoring) / 1000
}
