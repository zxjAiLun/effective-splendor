//! Competition and final-round judgment. Public one-purchase responses are
//! diagnostic bounds over known cards, not an omniscient prediction of play.
use super::*;

pub(super) fn player_rank(vp: u8, purchased: usize) -> Rank {
    (vp, std::cmp::Reverse(purchased))
}

pub(super) fn response_rank(
    obs: &Observation,
    opponent: &OpponentContext,
    removed: Option<CardId>,
    noble: Option<NobleId>,
) -> Rank {
    opponent
        .affordable
        .iter()
        .copied()
        .filter(|&id| Some(id) != removed)
        .map(|id| {
            player_rank(
                opponent.own.prestige
                    + purchase_vp_excluding(card(id), opponent.own.bonuses, obs, noble),
                opponent.current_rank.1 .0 + 1,
            )
        })
        .chain(std::iter::once(opponent.current_rank))
        .max()
        .unwrap()
}

pub(super) fn terminal_terms(
    position: &PositionContext<'_>,
    projected: &ActionProjection,
) -> Option<HeuristicV02Terms> {
    let obs = position.obs;
    if !obs.public.end_game_triggered && projected.after.prestige < 15 {
        return None;
    }
    let own_rank = player_rank(
        projected.after.prestige,
        position.purchased + usize::from(projected.bought.is_some()),
    );
    let publicly_ahead = position.opponents.iter().all(|p| {
        let rank = if p.seat > obs.viewer.index() {
            response_rank(
                obs,
                p,
                projected.bought.or(projected.secured),
                projected.claimed,
            )
        } else {
            p.current_rank
        };
        own_rank > rank
    });
    let terminal_lead = if !publicly_ahead {
        0
    } else if obs.public.end_game_triggered {
        // A one-point tie-break between positive-VP buys, not future value.
        // Non-buys in Main grant no VP; excluding zero-VP buys preserves the
        // preference for fewer purchases. Last-seat play needs no reply test.
        i64::from(
            projected.bought.is_some()
                && projected.after.prestige > position.before.prestige
                && obs.viewer.index() + 1 < usize::from(obs.public.player_count),
        )
    } else if obs.viewer.index() + 1 == usize::from(obs.public.player_count) {
        TERMINAL_PRIORITY
    } else {
        TERMINAL_PRIORITY / 10
    }; // unknown refills/blind reserves can still refute it
    Some(HeuristicV02Terms {
        terminal_lead,
        immediate_prestige: i64::from(projected.after.prestige - position.before.prestige)
            * (VP_WEIGHT + VP_LATE_BONUS),
        final_round_card_cost: -i64::from(projected.bought.is_some()),
        noble_race_progress: position.noble_choice(projected.action),
        ..HeuristicV02Terms::default()
    })
}

pub(super) fn score_competition(
    position: &PositionContext<'_>,
    projected: &ActionProjection,
    plan: &TargetComparison,
    terms: &mut HeuristicV02Terms,
) {
    let scoring = position.scoring;
    terms.noble_race_progress = position.noble_choice(projected.action);
    if let Some(id) = projected.bought {
        let def = card(id);
        let c = def.bonus.index();
        terms.noble_race_progress +=
            position.noble_progress[c] * NOBLE_RACE_PROGRESS_WEIGHT * scoring / 1000;
        if position.has_contestable_noble {
            if def.prestige == 3 && def.total_cost() > 6 {
                terms.noble_race_three_vp = NOBLE_RACE_THREE_VP_WEIGHT * scoring / 1000;
            }
            if matches!(projected.action, Action::BuyReserved { .. })
                && reserve_efficiency(def, position.before.bonuses)
                    >= NOBLE_RACE_RESERVED_EFFICIENCY_MIN
            {
                terms.noble_race_reserved = NOBLE_RACE_RESERVED_WEIGHT * scoring / 1000;
            }
        }
        terms.noble_build =
            position.noble_build_progress[c] * NOBLE_BUILD_PROGRESS_WEIGHT * (1000 - scoring)
                / 1000;
    }
    let denies_finish = projected
        .secured
        .is_some_and(|id| position.denies_finish(id));
    let protected = projected.secured.is_some_and(|id| {
        if !plan.selected.contains(&id) {
            return false;
        }
        let def = card(id);
        let own_time = position.turns(
            def,
            &projected.after,
            projected.bank,
            projected.held,
            projected.reservable,
        );
        own_time <= 3
            && position.opponents.iter().any(|p| {
                position.turns(def, &p.own, projected.bank, p.held, projected.reservable)
                    <= own_time
            })
    });
    terms.secured_target =
        (if protected { SECURED_WEIGHT } else { 0 }) + if denies_finish { 1200 } else { 0 };
    if is_reserve(projected.action) && !denies_finish {
        terms.race_reserve_penalty =
            -((position.immediate_alternative - plan.plan_after / 2).max(0) / 4).min(1200)
                - if position.finish_pressure && plan.plan_gain <= 0 && !protected {
                    FINISH_PRESSURE_RESERVE_PENALTY
                } else {
                    0
                };
    }
}
