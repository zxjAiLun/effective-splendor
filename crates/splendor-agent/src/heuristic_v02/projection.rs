//! Exact own-resource projection for a server-certified action. No refill.
use super::*;

#[derive(Clone, Copy, Debug)]
pub(super) struct OwnProjection {
    pub tokens: Gems,
    pub bonuses: [u8; 5],
    pub prestige: u8,
}

pub(super) struct ActionProjection {
    pub action: Action,
    pub after: OwnProjection,
    pub bought: Option<CardId>,
    pub secured: Option<CardId>,
    pub claimed: Option<NobleId>,
    pub bank: Gems,
    pub held: usize,
    /// Bounded preparation-model availability, not a predicted future market.
    pub reservable: usize,
    pub reserve_tempo: i64,
}

impl ActionProjection {
    pub fn new(position: &PositionContext<'_>, action: Action) -> Self {
        let obs = position.obs;
        let before = position.before;
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
        let claimed = match action {
            Action::ChooseNoble { noble } => Some(noble),
            _ if bought.is_some() => position
                .nobles
                .iter()
                .filter(|n| noble_distance(n.id, &after.bonuses) == 0)
                .max_by_key(|n| {
                    (
                        all_nobles()[n.id.index()].prestige,
                        n.choice_value,
                        std::cmp::Reverse(n.id.index()),
                    )
                })
                .map(|n| n.id),
            _ => None,
        };
        Self {
            action,
            after,
            bought,
            secured,
            claimed,
            bank: projected_bank(obs, before.tokens, after.tokens),
            held: obs.private.reserved.len() + usize::from(is_reserve(action))
                - usize::from(matches!(action, Action::BuyReserved { .. })),
            reservable: position
                .reservable
                .saturating_sub(usize::from(bought.is_some() || secured.is_some())),
            reserve_tempo,
        }
    }
}

pub(super) fn is_reserve(action: Action) -> bool {
    matches!(
        action,
        Action::ReserveMarket { .. } | Action::ReserveDeck { .. }
    )
}

pub(super) fn projected_bank(obs: &Observation, before: Gems, after: Gems) -> Gems {
    obs.public
        .bank
        .saturating_add(before)
        .checked_sub(after)
        .expect("legal action conserves tokens")
}

pub(super) fn purchase_vp_excluding(
    def: &CardDef,
    mut bonuses: [u8; 5],
    obs: &Observation,
    removed: Option<NobleId>,
) -> u8 {
    bonuses[def.bonus.index()] = bonuses[def.bonus.index()].saturating_add(1);
    def.prestige.saturating_add(
        obs.public
            .nobles
            .iter()
            .copied()
            .filter(|&id| Some(id) != removed && noble_distance(id, &bonuses) == 0)
            .map(|id| all_nobles()[id.index()].prestige)
            .max()
            .unwrap_or(0),
    )
}

pub(super) fn purchase_vp(def: &CardDef, bonuses: [u8; 5], obs: &Observation) -> u8 {
    purchase_vp_excluding(def, bonuses, obs, None)
}

pub(super) fn deficit(def: &CardDef, own: &OwnProjection) -> i64 {
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

pub(super) fn effective_cost(def: &CardDef, bonuses: [u8; 5]) -> i64 {
    GemColor::ALL
        .iter()
        .map(|&c| i64::from(def.cost[c.index()].saturating_sub(bonuses[c.index()])))
        .sum()
}

fn apply_buy(own: &mut OwnProjection, def: &CardDef, obs: &Observation) {
    let mut gold_needed = 0u8;
    for color in GemColor::ALL {
        let need = def.cost[color.index()].saturating_sub(own.bonuses[color.index()]);
        let paid = own.tokens.color(color).min(need);
        own.tokens.set_color(color, own.tokens.color(color) - paid);
        gold_needed += need - paid;
    }
    own.tokens.gold -= gold_needed;
    own.prestige = own
        .prestige
        .saturating_add(purchase_vp(def, own.bonuses, obs));
    own.bonuses[def.bonus.index()] = own.bonuses[def.bonus.index()].saturating_add(1);
}

fn reserve_tokens(before: Gems, give_back: Gems, gold_available: bool) -> Gems {
    let received = Gems {
        gold: u8::from(gold_available),
        ..Gems::ZERO
    };
    before
        .saturating_add(received)
        .checked_sub(give_back)
        .expect("legal reserve return")
}
