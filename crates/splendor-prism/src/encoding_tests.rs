//! Engineering fixtures may set public caches directly to isolate core settlement.
//! The trajectory test additionally checks ordinary engine-reachable states.
use super::*;
use splendor_core::{visible_events, Audience, FullState, GameConfig, PlayerId};
fn state() -> FullState {
    FullState::new(GameConfig {
        seed: 51,
        ..Default::default()
    })
    .unwrap()
    .0
}
fn input(s: &FullState) -> EncodedState {
    encode(
        &s.observation(s.current_player),
        &visible_events(&s.log, Audience::Player(s.current_player)),
        &s.legal_actions(),
    )
    .unwrap()
}
fn one(s: &FullState, a: Action) -> EncodedState {
    assert!(s.legal_actions().contains(&a));
    encode(
        &s.observation(s.current_player),
        &visible_events(&s.log, Audience::Player(s.current_player)),
        &[a],
    )
    .unwrap()
}
fn approx(a: f32, b: f32) {
    assert!((a - b).abs() < 1e-6, "{a} != {b}");
}
fn check_consequences(s: &FullState, a: Action) {
    let x = one(s, a);
    let row = &x.actions[0];
    let actor = s.current_player.index();
    let mut next = s.clone();
    next.apply(a).unwrap();
    let p = &next.players[actor];
    for (i, v) in gems(p.tokens).iter().enumerate() {
        approx(row[24 + i], *v as f32 / 10.0);
        approx(
            row[30 + i],
            (gems(next.bank)[i] as f32 - gems(s.bank)[i] as f32) / 10.0,
        );
    }
    for i in 0..5 {
        approx(row[62 + i], p.bonuses[i] as f32 / 20.0);
    }
    approx(row[42], p.prestige as f32 / 20.0);
    approx(
        row[41],
        (p.prestige - s.players[actor].prestige) as f32 / 8.0,
    );
    approx(row[70], p.reserved.len() as f32 / 3.0);
    assert_eq!(row[68] > 0.0, next.phase == Phase::ChooseNoble);
    assert_eq!(
        row[47] > 0.0,
        p.nobles.len() > s.players[actor].nobles.len()
    );
    if row[68] > 0.0 {
        for id in &next.pending_nobles {
            assert_eq!(row[52 + id.index()], 1.0);
        }
    }
}
#[test]
fn same_score_reserve_targets_are_distinct_and_bound() {
    let s = state();
    let x = input(&s);
    let legal = s.legal_actions();
    let mut pairs = 0;
    for (i, a) in legal.iter().enumerate() {
        if let Action::ReserveMarket { tier, slot, .. } = a {
            let id = s.market[tier.index()][*slot as usize].unwrap();
            let t = &x.entities[x.targets[i] as usize];
            approx(t[17], (id.0 as f32 + 1.0) / 90.0);
            assert_eq!(x.actions[i][3], 1.0);
            for (j, b) in legal.iter().enumerate().skip(i + 1) {
                if let Action::ReserveMarket {
                    tier: bt, slot: bs, ..
                } = b
                {
                    let bid = s.market[bt.index()][*bs as usize].unwrap();
                    if card(id).prestige == card(bid).prestige {
                        assert_ne!(x.targets[i], x.targets[j]);
                        assert_ne!(t, &x.entities[x.targets[j] as usize]);
                        pairs += 1;
                    }
                }
            }
        }
    }
    assert!(pairs > 0);
}
#[test]
fn blind_tiers_unknown_empty_zero_and_own_private() {
    let mut s = state();
    let mut rows = Vec::new();
    for tier in Tier::ALL {
        let x = one(
            &s,
            Action::ReserveDeck {
                tier,
                give_back: Gems::ZERO,
            },
        );
        assert_eq!(x.targets, [-1]);
        assert_eq!(x.actions[0][23], 1.0);
        assert_eq!(x.actions[0][19 + tier.index()], 1.0);
        rows.push(x.actions[0].clone());
    }
    assert!(rows.windows(2).all(|r| r[0] != r[1]));
    s.apply(Action::ReserveDeck {
        tier: Tier::ALL[1],
        give_back: Gems::ZERO,
    })
    .unwrap();
    let x = input(&s);
    let unknown = x.entities.iter().find(|r| r[5] == 1.0).unwrap();
    let empty = x.entities.iter().find(|r| r[6] == 1.0).unwrap();
    assert_eq!((unknown[7], unknown[8]), (0.0, 1.0));
    assert_eq!((empty[7], empty[8]), (1.0, 0.0));
    assert!(x
        .entities
        .iter()
        .any(|r| r[1] == 1.0 && r[7] == 1.0 && r[8] == 1.0 && r[43] == 0.0));
    assert_eq!(x.entities[0][87], 1.0 / 3.0);
    let a = s
        .legal_actions()
        .into_iter()
        .find(|a| matches!(a, Action::TakeTokens { .. }))
        .unwrap();
    s.apply(a).unwrap();
    let own = input(&s);
    let id = s.players[0].reserved[0].card;
    assert!(own
        .entities
        .iter()
        .any(|r| r[10] == 1.0 && r[2] == 1.0 && r[17] == (id.0 as f32 + 1.0) / 90.0));
}
#[test]
fn hidden_world_equivalence_includes_blind_identity_deck_order_and_seed() {
    let mut a = state();
    let first = a.legal_actions()[0];
    a.apply(first).unwrap();
    assert_eq!(a.current_player, PlayerId(1));
    let mut b = a.clone();
    let tier = Tier::ALL[2];
    let n = b.decks[2].len();
    b.decks[2].swap(n - 1, n - 2);
    b.seed = 987654321;
    let reserve = Action::ReserveDeck {
        tier,
        give_back: Gems::ZERO,
    };
    a.apply(reserve).unwrap();
    b.apply(reserve).unwrap();
    assert_ne!(a.players[1].reserved[0].card, b.players[1].reserved[0].card);
    assert_eq!(a.observation(PlayerId(0)), b.observation(PlayerId(0)));
    assert_eq!(
        visible_events(&a.log, Audience::Player(PlayerId(0))),
        visible_events(&b.log, Audience::Player(PlayerId(0)))
    );
    assert_eq!(input(&a), input(&b));
    b.decks[0].reverse();
    b.decks[1].reverse();
    assert_eq!(input(&a), input(&b));
}
#[test]
fn take_and_return_are_not_collapsed_to_net() {
    let mut s = state();
    s.players[0].tokens = Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    };
    s.bank = Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 5,
    };
    let legal = s.legal_actions();
    let xs: Vec<_> = legal
        .iter()
        .filter_map(|a| {
            if let Action::TakeTokens { take, give_back } = a {
                if take == give_back {
                    Some(one(&s, *a))
                } else {
                    None
                }
            } else {
                None
            }
        })
        .collect();
    assert!(xs.len() > 1);
    assert_eq!(&xs[0].actions[0][24..36], &xs[1].actions[0][24..36]);
    assert_ne!(&xs[0].actions[0][7..19], &xs[1].actions[0][7..19]);
    for a in legal {
        check_consequences(&s, a);
    }
}
#[test]
fn target_region_migration_and_market_action_reordering() {
    let mut s = state();
    let tier = Tier::ALL[0];
    let id = s.market[0][0].unwrap();
    let reserve = Action::ReserveMarket {
        tier,
        slot: 0,
        give_back: Gems::ZERO,
    };
    let x = one(&s, reserve);
    let old = x.entities[x.targets[0] as usize].clone();
    assert_eq!(old[9], 1.0);
    assert_eq!(x.actions[0][45], 1.0);
    check_consequences(&s, reserve);
    s.apply(reserve).unwrap();
    let pass = s.legal_actions()[0];
    s.apply(pass).unwrap();
    s.players[0].bonuses = [7; 5];
    let buy = Action::BuyReserved { slot: 0 };
    let x = one(&s, buy);
    let own = &x.entities[x.targets[0] as usize];
    assert_eq!(own[10], 1.0);
    assert_eq!(own[17], old[17]);
    assert_eq!(x.actions[0][46], 1.0);
    check_consequences(&s, buy);
    s.apply(buy).unwrap();
    assert!(s.players[0].purchased.contains(&id));
    let x = input(&s);
    let region = if s.current_player.0 == 0 { 12 } else { 13 };
    assert!(x
        .entities
        .iter()
        .any(|r| r[region] == 1.0 && r[17] == old[17]));
    let s = state();
    let mut swapped = s.clone();
    swapped.market[0].swap(0, 1);
    let a = one(
        &s,
        Action::ReserveMarket {
            tier,
            slot: 0,
            give_back: Gems::ZERO,
        },
    );
    let b = one(
        &swapped,
        Action::ReserveMarket {
            tier,
            slot: 1,
            give_back: Gems::ZERO,
        },
    );
    assert_eq!(a.actions, b.actions);
    assert_eq!(
        a.entities[a.targets[0] as usize],
        b.entities[b.targets[0] as usize]
    );
    let mut legal = s.legal_actions();
    let a = input(&s);
    legal.reverse();
    let b = encode(&s.observation(s.current_player), &[], &legal).unwrap();
    assert_eq!(a.entities, b.entities);
    assert_eq!(a.actions.into_iter().rev().collect::<Vec<_>>(), b.actions);
    assert_eq!(a.targets.into_iter().rev().collect::<Vec<_>>(), b.targets);
}
#[test]
fn color_correspondence_and_visible_identity_ownership() {
    let mut s = state();
    let p = &mut s.players[0];
    p.tokens = Gems {
        white: 3,
        ..Gems::ZERO
    };
    let mut b = s.clone();
    b.players[0].tokens = Gems {
        blue: 3,
        ..Gems::ZERO
    };
    let a = input(&s);
    let other = input(&b);
    assert_ne!(a.entities, other.entities);
    for row in &a.entities {
        if row[2] == 1.0 {
            let id = CardId((row[17] * 90.0).round() as u8 - 1);
            let c = card(id);
            for i in 0..5 {
                approx(row[22 + i], c.cost[i] as f32 / 7.0);
                approx(
                    row[57 + i],
                    c.cost[i].saturating_sub(gems(s.players[0].tokens)[i]) as f32 / 7.0,
                );
            }
        }
    }
    let id = s.decks[0].pop().unwrap();
    s.players[0].purchased.push(id);
    let a = input(&s);
    s.players[0].purchased.clear();
    s.players[1].purchased.push(id);
    let b = input(&s);
    assert_ne!(a.entities, b.entities);
}
#[test]
fn stage_seat_final_round_and_public_history_are_retained() {
    let s = state();
    let a = input(&s);
    let mut b = s.clone();
    b.current_player = PlayerId(1);
    assert_ne!(a.entities, input(&b).entities);
    b = s.clone();
    b.end_game_triggered = true;
    b.turns_remaining_in_final_round = Some(0);
    let x = input(&b);
    assert_eq!(x.entities[0][75], 1.0);
    assert_eq!(x.entities[0][77], 1.0);
    assert_ne!(a.entities, x.entities);
    let mut obs = s.observation(s.current_player);
    let legal = s.legal_actions();
    let hist = [
        VisibleEvent::ActionApplied {
            player: PlayerId(0),
            action: Action::Pass,
        },
        VisibleEvent::ActionApplied {
            player: PlayerId(1),
            action: Action::ChooseNoble { noble: s.nobles[0] },
        },
    ];
    let x = encode(&obs, &hist, &legal).unwrap();
    assert_eq!(x.entities[0][82], 0.01);
    assert_eq!(x.entities[0][83], 0.02);
    assert_eq!(x.entities[0][84], 0.0);
    obs.public.phase = Phase::ChooseNoble;
    obs.public.pending_nobles = obs.public.nobles.clone();
    let choices: Vec<_> = obs
        .public
        .nobles
        .iter()
        .map(|n| Action::ChooseNoble { noble: *n })
        .collect();
    let x = encode(&obs, &[], &choices).unwrap();
    assert_eq!(x.entities[0][73], 1.0);
    assert_ne!(x.targets[0], x.targets[1]);
    assert_ne!(
        x.entities[x.targets[0] as usize],
        x.entities[x.targets[1] as usize]
    );
    assert!(x.actions.iter().all(|r| r[5] == 1.0 && r[50] == 0.0));
}
#[test]
fn core_payment_and_single_multi_noble_settlement() {
    let mut s = state();
    s.players[0].tokens = Gems {
        white: 1,
        blue: 1,
        green: 1,
        red: 1,
        black: 1,
        gold: 3,
    };
    s.players[0].bonuses = [1; 5];
    let mut paid_gold = false;
    for a in s.legal_actions() {
        if matches!(a, Action::BuyMarket { .. }) {
            let mut next = s.clone();
            let step = next.apply(a).unwrap();
            let pay = visible_events(&step.events, Audience::Player(s.current_player))
                .into_iter()
                .find_map(|e| {
                    if let VisibleEvent::CardPurchased { paid, .. } = e {
                        Some(paid)
                    } else {
                        None
                    }
                })
                .unwrap();
            let x = one(&s, a);
            approx(x.actions[0][75], pay.gold as f32 / 5.0);
            paid_gold |= pay.gold > 0;
            check_consequences(&s, a);
        }
    }
    assert!(paid_gold);
    // Core supports public-cache fixtures; focus on settlement, not random reachability.
    for count in [1, 2] {
        let mut s = state();
        s.players[0].bonuses = [4; 5];
        s.nobles.truncate(count);
        let a = s
            .legal_actions()
            .into_iter()
            .find(|a| matches!(a, Action::BuyMarket { .. }))
            .unwrap();
        let x = one(&s, a);
        check_consequences(&s, a);
        if count == 1 {
            assert_eq!(x.actions[0][47], 1.0);
        } else {
            assert_eq!(x.actions[0][68], 1.0);
        }
        s.apply(a).unwrap();
        if count == 2 {
            for choice in s.legal_actions() {
                check_consequences(&s, choice);
            }
        }
    }
}
#[test]
fn core_reachable_trajectory_all_legal_consequences_and_pass_kind() {
    let mut s = state();
    let mut checked = 0;
    for n in 0..36usize {
        if s.is_terminal() {
            break;
        }
        let legal = s.legal_actions();
        for a in &legal {
            check_consequences(&s, *a);
            checked += 1;
        }
        let buys: Vec<_> = legal
            .iter()
            .copied()
            .filter(|a| {
                matches!(
                    a,
                    Action::BuyMarket { .. }
                        | Action::BuyReserved { .. }
                        | Action::ChooseNoble { .. }
                )
            })
            .collect();
        let a = if buys.is_empty() {
            legal[(n * 31 + 7) % legal.len()]
        } else {
            buys[n % buys.len()]
        };
        s.apply(a).unwrap();
    }
    assert!(checked > 500);
    let mut s = state();
    s.market = [[None; 4]; 3];
    s.decks = [vec![], vec![], vec![]];
    s.bank = Gems::ZERO;
    assert_eq!(s.legal_actions(), vec![Action::Pass]);
    let x = input(&s);
    assert_eq!(x.actions[0][6], 1.0);
    assert_eq!(x.targets[0], -1);
    check_consequences(&s, Action::Pass);
}
#[test]
fn malformed_inputs_fail_closed() {
    let s = state();
    let mut obs = s.observation(s.current_player);
    obs.public.player_count = 3;
    assert!(encode(&obs, &[], &s.legal_actions()).is_err());
    obs = s.observation(s.current_player);
    obs.public.market[0][0] = Some(CardId(255));
    assert!(encode(&obs, &[], &s.legal_actions()).is_err());
    obs = s.observation(s.current_player);
    obs.private.reserved.clear();
    assert!(encode(&obs, &[], &[Action::BuyReserved { slot: 0 }]).is_err());
    let x = input(&s);
    let mut bad = x.clone();
    bad.targets[0] = -2;
    assert!(bad.validate().is_err());
    bad = x.clone();
    bad.entities[0][0] = f32::NAN;
    assert!(bad.validate().is_err());
    bad = x;
    bad.actions[0].pop();
    assert!(bad.validate().is_err());
}
