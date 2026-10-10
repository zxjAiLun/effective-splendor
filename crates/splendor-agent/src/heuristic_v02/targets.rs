//! Known-target selection and bounded preparation estimates. No route locking,
//! full-state rollout, future market identity or exact global time-to-15 claim.
use super::*;

pub(super) struct RankedTarget {
    pub def: CardDef,
    pub gap: i64,
    pub value: i64,
    pub turns: i64,
}

pub(super) struct TargetComparison {
    pub selected: Vec<CardId>,
    pub shortfall: i64,
    pub discount: i64,
    pub newly_ready: bool,
    pub plan_after: i64,
    pub plan_gain: i64,
    pub readiness_gain: i64,
    pub cheap_ready: bool,
    pub any_affordable: bool,
}

pub(super) fn rank_targets(
    position: &PositionContext<'_>,
    targets: &[CardDef],
    own: &OwnProjection,
) -> Vec<RankedTarget> {
    let mut ranked: Vec<_> = targets
        .iter()
        .map(|def| RankedTarget {
            def: *def,
            gap: deficit(def, own),
            value: position.value(def, own, None),
            turns: position.turns(
                def,
                own,
                position.obs.public.bank,
                position.obs.private.reserved.len(),
                position.reservable,
            ),
        })
        .collect();
    ranked.sort_by_key(|t| (-(t.value / t.turns), t.turns, t.gap, t.def.id.index()));
    ranked
}

pub(super) fn compare_targets(
    position: &PositionContext<'_>,
    projected: &ActionProjection,
) -> TargetComparison {
    let before = &position.before;
    let after = &projected.after;
    let mut result = TargetComparison {
        selected: Vec::with_capacity(2),
        shortfall: 0,
        discount: 0,
        newly_ready: false,
        plan_after: 0,
        plan_gain: 0,
        readiness_gain: 0,
        cheap_ready: false,
        any_affordable: false,
    };
    let mut plan_before = 0;
    let mut ready_vp_after = 0;
    for target in &position.ranked {
        let def = &target.def;
        let gap = deficit(def, after);
        if gap == 0 {
            result.any_affordable = true;
            ready_vp_after =
                ready_vp_after.max(i64::from(purchase_vp(def, after.bonuses, position.obs)));
            result.cheap_ready |= target.gap > 0 && cheap_t1(def);
        }
        // Realized points/bonus are scored separately. Do not compare a bought
        // card against its own absence; remove it on BOTH sides.
        if Some(def.id) == projected.bought {
            continue;
        }
        if result.selected.len() < 2 {
            result.selected.push(def.id);
            result.shortfall += target.gap.min(6) - gap.min(6);
            result.discount +=
                effective_cost(def, before.bonuses) - effective_cost(def, after.bonuses);
            result.newly_ready |= target.gap > 0 && gap == 0;
        }
        plan_before = plan_before.max(target.value / target.turns);
        let value = position.value(def, after, projected.claimed);
        let turns = position.turns(
            def,
            after,
            projected.bank,
            projected.held,
            projected.reservable,
        );
        result.plan_after = result.plan_after.max(value / turns);
    }
    result.plan_gain = result.plan_after - plan_before;
    if is_reserve(projected.action) || matches!(projected.action, Action::TakeTokens { .. }) {
        result.readiness_gain = (ready_vp_after - position.ready_vp).max(0);
    }
    result
}

pub(super) fn best_affordable_purchase_vp(
    targets: &[CardDef],
    own: &OwnProjection,
    obs: &Observation,
) -> i64 {
    targets
        .iter()
        .filter(|def| deficit(def, own) == 0)
        .map(|def| i64::from(purchase_vp(def, own.bonuses, obs)))
        .max()
        .unwrap_or(0)
}

/// 1 = buy now; 2..4 = greedy legal preparation path + purchase; 5 = beyond
/// the three-preparation horizon; 9 = needs changed discounts/public supply.
/// 5/9 are scoring buckets, not a proof of exact completion time. The supply
/// model holds opponents/refills fixed and allows gold only via reserve slots.
pub(super) fn purchase_turns(
    def: &CardDef,
    own: &OwnProjection,
    bank: Gems,
    held: usize,
    reservable: usize,
) -> i64 {
    if deficit(def, own) == 0 {
        return 1;
    }
    if effective_cost(def, own.bonuses) > 10 {
        return 9;
    }
    let mut own = *own;
    let mut bank = bank;
    let mut slots = 3usize.saturating_sub(held).min(reservable);
    let mut supplied = own;
    supplied.tokens = supplied.tokens.saturating_add(bank);
    supplied.tokens.gold = own.tokens.gold.saturating_add(bank.gold.min(slots as u8));
    if deficit(def, &supplied) > 0 {
        return 9;
    }
    for prep in 1..=3 {
        let mut takes = Vec::with_capacity(16);
        let required = GemColor::ALL
            .into_iter()
            .filter(|&c| bank.color(c) > 0)
            .count()
            .min(3);
        for mask in 1u8..32 {
            if mask.count_ones() as usize != required {
                continue;
            }
            let mut take = Gems::ZERO;
            let mut valid = true;
            for (i, &color) in GemColor::ALL.iter().enumerate() {
                if mask & (1 << i) != 0 {
                    if bank.color(color) == 0 {
                        valid = false;
                        break;
                    }
                    take.set_color(color, 1);
                }
            }
            if valid {
                takes.push(take);
            }
        }
        for color in GemColor::ALL {
            if bank.color(color) >= 4 {
                let mut take = Gems::ZERO;
                take.set_color(color, 2);
                takes.push(take);
            }
        }
        if slots > 0 && bank.gold > 0 {
            takes.push(Gems {
                gold: 1,
                ..Gems::ZERO
            });
        }
        let mut best = None;
        let mut best_gap = deficit(def, &own);
        for take in takes {
            let mut next = own;
            next.tokens = next.tokens.saturating_add(take);
            // Retain useful colors/gold; return filler first. Gold can replace
            // a colored token at the cap. Enumeration order is deterministic.
            while next.tokens.total() > 10 {
                let excess = GemColor::ALL.into_iter().find(|&c| {
                    next.tokens.color(c)
                        > def.cost[c.index()].saturating_sub(next.bonuses[c.index()])
                });
                if let Some(c) = excess.or_else(|| {
                    GemColor::ALL
                        .into_iter()
                        .find(|&c| next.tokens.color(c) > 0)
                }) {
                    next.tokens.set_color(c, next.tokens.color(c) - 1);
                } else {
                    next.tokens.gold -= 1;
                }
            }
            let gap = deficit(def, &next);
            if gap < best_gap {
                best_gap = gap;
                best = Some((next, take.gold > 0));
            }
        }
        let Some((next, reserved)) = best else {
            return 5;
        };
        bank = bank
            .saturating_add(own.tokens)
            .checked_sub(next.tokens)
            .expect("preparation conserves supply");
        own = next;
        slots -= usize::from(reserved);
        if best_gap == 0 {
            return prep + 1;
        }
    }
    5
}
