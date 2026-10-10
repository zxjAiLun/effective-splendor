//! Economic valuation on the common score scale. Preserve integer evaluation
//! order: changing truncation points is a strategy change, not a refactor.
use super::*;

pub(super) fn economic_terms(
    position: &PositionContext<'_>,
    projected: &ActionProjection,
    plan: &TargetComparison,
) -> HeuristicV02Terms {
    let before = &position.before;
    let after = &projected.after;
    let scoring = position.scoring;
    let bought = projected.bought.map(card);
    let vp = i64::from(after.prestige - before.prestige);
    let engine_value = bought.map_or(0, |def| {
        let demand = position.board_demand[def.bonus.index()].min(ENGINE_DEMAND_CAP);
        ((1000 - scoring) * ENGINE_WEIGHT * demand) / 1000
    });
    let cheap_engine_buy = bought.filter(|def| cheap_t1(def)).map_or(0, |def| {
        (7 - i64::from(def.total_cost())) * position.cheap_buy_weight
    });
    let conversion_value = bought.map_or(0, |def| {
        let c = def.bonus.index();
        let self_demand = if def.cost[c] > before.bonuses[c] {
            conversion_units(def)
        } else {
            0
        };
        (position.conversion_demand[c] - self_demand).min(CONVERSION_CAP)
            * position.conversion_weight
    });
    let rotation_guard = match projected.action {
        Action::TakeTokens { take, give_back } if take == give_back => -ZERO_NET_TAKE_PENALTY,
        Action::TakeTokens { .. } if after.tokens.total() > 7 && !plan.any_affordable => {
            -STRANDED_TOKEN_PENALTY * i64::from(after.tokens.total() - 7) * (1000 - scoring) / 1000
        }
        _ => 0,
    };
    HeuristicV02Terms {
        immediate_prestige: vp * (VP_WEIGHT + scoring * VP_LATE_BONUS / 1000),
        engine_value,
        cheap_engine_buy,
        conversion_value,
        rotation_guard,
        cheap_ready: if matches!(projected.action, Action::TakeTokens { .. }) && plan.cheap_ready {
            position.cheap_ready_weight
        } else {
            0
        },
        vp_efficiency: bought.map_or(0, |def| {
            vp * vp * VP_QUADRATIC_WEIGHT / (1 + effective_cost(def, before.bonuses)) * scoring
                / 1000
        }),
        target_shortfall: plan.shortfall * SHORTFALL_WEIGHT,
        useful_discount: plan.discount * BONUS_WEIGHT,
        new_affordable_target: (if plan.newly_ready { READY_WEIGHT } else { 0 })
            + plan.plan_gain / 2,
        gold_liquidity: (i64::from(after.tokens.gold.min(3))
            - i64::from(before.tokens.gold.min(3)))
            * GOLD_WEIGHT,
        reserve_tempo: projected.reserve_tempo,
        reserve_count_guard: if is_reserve(projected.action)
            && position.obs.private.reserved.len() >= RESERVE_COUNT_THRESHOLD
        {
            -RESERVE_COUNT_GUARD
        } else {
            0
        },
        scoring_readiness: plan.readiness_gain * SCORING_READINESS_PER_VP * scoring / 1000,
        ..HeuristicV02Terms::default()
    }
}

pub(super) fn cheap_t1(def: &CardDef) -> bool {
    def.tier == Tier::One && def.total_cost() <= 4
}

pub(super) fn conversion_units(def: &CardDef) -> i64 {
    if cheap_t1(def) {
        2
    } else if def.tier == Tier::One {
        1
    } else if def.tier == Tier::Two
        && ((def.prestige == 2 && def.total_cost() == 5)
            || (def.prestige == 3 && def.total_cost() == 6))
    {
        2
    } else {
        0
    }
}

pub(super) fn reserve_efficiency(def: &CardDef, bonuses: [u8; 5]) -> i64 {
    i64::from(def.prestige) * 1_000 / (1 + effective_cost(def, bonuses))
}

/// Shared realized/target purchase value: printed VP plus at most one noble.
/// Engine demand refers to the root known board; it does not predict refills.
pub(super) fn purchase_value(
    def: &CardDef,
    own: &OwnProjection,
    obs: &Observation,
    targets: &[CardDef],
    removed: Option<NobleId>,
    scoring: i64,
) -> i64 {
    let vp = i64::from(purchase_vp_excluding(def, own.bonuses, obs, removed));
    let point_value = vp * (VP_WEIGHT + scoring * VP_LATE_BONUS / 1000)
        + vp * vp * VP_QUADRATIC_WEIGHT / (1 + effective_cost(def, own.bonuses)) * scoring / 1000;
    let cheap = if cheap_t1(def) {
        (7 - i64::from(def.total_cost()))
            * construction_weight(CHEAP_BUY_ULTRA, CHEAP_BUY_BUILD, own, scoring)
    } else {
        0
    };
    let c = def.bonus.index();
    let demand: i64 = targets
        .iter()
        .filter(|d| d.id != def.id)
        .map(|d| {
            i64::from(
                d.cost[c]
                    .saturating_sub(own.bonuses[c])
                    .min(ENGINE_PER_CARD_CAP),
            )
        })
        .sum();
    point_value + cheap + demand.min(ENGINE_DEMAND_CAP) * ENGINE_WEIGHT * (1000 - scoring) / 1000
}
