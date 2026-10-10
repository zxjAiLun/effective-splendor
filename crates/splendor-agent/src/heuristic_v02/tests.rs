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
            assert_eq!(heuristic_v02_term_scores(&obs, &legal).len(), legal.len());
            let position = PositionContext::new(&obs);
            for &action in &legal {
                let projected = ActionProjection::new(&position, action).after;
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
    let projected = ActionProjection::new(&PositionContext::new(&obs), buy).after;
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
    let projected = ActionProjection::new(&PositionContext::new(&obs), buy).after;
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
        if legal
            .iter()
            .zip(&scores)
            .any(|(a, s)| matches!(a, Action::TakeTokens { .. }) && s.total() > scores[buy].total())
        {
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
    for (count, expected) in [(4, 0), (5, 0), (8, 375), (9, 500)] {
        state.players[0].bonuses = [count, 0, 0, 0, 0];
        let obs = state.observation(PlayerId(0));
        let own = OwnProjection {
            tokens: Gems::ZERO,
            bonuses: [count, 0, 0, 0, 0],
            prestige: 0,
        };
        assert_eq!(phase_weight(&obs, &own), expected, "discounts={count}");
    }
    let own = OwnProjection {
        tokens: Gems::ZERO,
        bonuses: [0; 5],
        prestige: 0,
    };
    state.players[0].bonuses = [0; 5];
    state.players[1].prestige = 12;
    assert_eq!(phase_weight(&state.observation(PlayerId(0)), &own), 1000);
    state.players[1].prestige = 0;
    state.end_game_triggered = true;
    assert_eq!(phase_weight(&state.observation(PlayerId(0)), &own), 1000);
}

#[test]
fn bomb_trace_field_remains_zero_for_every_legal_action() {
    let state = game(52);
    let legal = state.legal_actions();
    assert!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &legal)
            .iter()
            .all(|t| t.bomb_reserve == 0)
    );
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
    let ranked = select_targets(&[*card(CardId(42)), *card(CardId(43))], &own, &obs);
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
    assert_eq!(score.vp_efficiency, (2 * 2 * VP_QUADRATIC_WEIGHT) / 6);
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
        vec![0, 0, 0],
        "v0.2.9 abolishes bomb reserve bonuses"
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
fn contestable_noble_progress_does_not_force_target_groups() {
    let mut state = game(61);
    state.nobles = vec![NobleId(0), NobleId(8)];
    state.players[0].bonuses = [2, 2, 1, 0, 0];
    state.players[1].prestige = 12;
    assert_eq!(noble_distance(NobleId(0), &[2, 2, 1, 0, 0]), 4);
    assert_eq!(noble_distance(NobleId(8), &[2, 2, 1, 0, 0]), 4);
    assert_eq!(
        PositionContext::new(&state.observation(PlayerId(0)))
            .nobles
            .iter()
            .filter(|n| n.distance <= NOBLE_RACE_DISTANCE_MAX)
            .count(),
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

    // v0.2.8: one winnable near noble IS enough in scoring phase!
    state.nobles = vec![NobleId(0)];
    assert_eq!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0].noble_race_progress,
        NOBLE_RACE_PROGRESS_WEIGHT,
        "one winnable near noble awards progress in scoring phase"
    );
    // Outside scoring phase, race progress remains 0.
    state.players[1].prestige = 0;
    assert_eq!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0].noble_race_progress,
        0,
        "outside scoring phase race progress is inactive"
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
    );
    assert_eq!(
        ranked[0].id,
        CardId(74),
        "real scoring value/time beats a hard noble-color group"
    );
    assert_eq!(ranked.len(), 2);
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
    assert_eq!(
        reserved_score.vp_efficiency,
        (3 * 3 * VP_QUADRATIC_WEIGHT) / 4
    );
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
    assert_eq!(
        s.noble_race_progress, NOBLE_RACE_PROGRESS_WEIGHT,
        "only the immediately claimable noble is excluded"
    );

    // Missing discounts alone cannot prove an opponent will claim first.
    let mut mixed = lost.clone();
    mixed.players[1].bonuses = [3, 0, 3, 0, 0]; // noble0 lost (3<4), noble8 winnable (5>4)
    let s = heuristic_v02_term_scores(&mixed.observation(PlayerId(0)), &[buy])[0];
    assert_eq!(
        s.noble_race_progress,
        2 * NOBLE_RACE_PROGRESS_WEIGHT,
        "neither noble has an immediate public opponent completion"
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
    );
    assert_eq!(
        ranked2[0].id,
        CardId(74),
        "no forced noble-color priority group"
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
    let market_terms = heuristic_v02_term_scores(&market.observation(PlayerId(0)), &[action])[0];
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
        heuristic_v02_term_scores(&held.observation(PlayerId(0)), &[action])[0].scoring_readiness,
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
    let obs = readiness_fixture().observation(PlayerId(0));
    assert_eq!(best_affordable_purchase_vp(&[two, three], &before, &obs), 2);
    assert_eq!(best_affordable_purchase_vp(&[two, three], &after, &obs), 3);
    assert_eq!(
        best_affordable_purchase_vp(&[three, three], &after, &obs),
        3,
        "same tokens buy only one card"
    );
    assert_eq!(best_affordable_purchase_vp(&[], &after, &obs), 0);
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
        heuristic_v02_term_scores(&full.observation(PlayerId(0)), &[no_net])[0].scoring_readiness,
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
fn reservation_count_guard_preserves_last_slot_in_all_phases() {
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
        -RESERVE_COUNT_GUARD,
        "the final reserve slot has opportunity cost in scoring too"
    );
}

#[test]
fn single_winnable_noble_race_progress_in_scoring_phase() {
    let mut state = game(68);
    state.nobles = vec![NobleId(0)];
    state.players[0].bonuses = [2, 2, 1, 0, 0];
    state.players[1].prestige = 12; // Score phase
    expose(&mut state, CardId(0), 0); // Blue bonus advances NobleId(0)
    state.players[0].tokens.black = 3;
    state.bank.black -= 3;
    let buy = Action::BuyMarket {
        tier: Tier::One,
        slot: 0,
    };
    let score = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0];
    assert_eq!(
        score.noble_race_progress, NOBLE_RACE_PROGRESS_WEIGHT,
        "single winnable noble within distance 4 activates race progress"
    );
}

#[test]
fn quadratic_vp_efficiency_rewards_high_vp_cards_progressively() {
    let mut state = game(68);
    expose(&mut state, CardId(45), 0); // 3VP, 6 blue
    expose(&mut state, CardId(71), 0); // 4VP, 7 white
    state.players[0].bonuses = [3, 3, 0, 0, 0]; // 3 white, 3 blue
    state.players[0].tokens = Gems {
        white: 4,
        blue: 3,
        ..Gems::ZERO
    };
    state.players[1].prestige = 12; // Score phase

    let buy_3vp = Action::BuyMarket {
        tier: Tier::Two,
        slot: 0,
    };
    let buy_4vp = Action::BuyMarket {
        tier: Tier::Three,
        slot: 0,
    };
    let scores = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy_3vp, buy_4vp]);
    // 3VP card costs 3 after discount -> (9 * 500) / (1 + 3) = 1125
    assert_eq!(scores[0].vp_efficiency, 1125);
    // 4VP card costs 4 after discount -> (16 * 500) / (1 + 4) = 1600
    assert_eq!(scores[1].vp_efficiency, 1600);
    assert!(
        scores[1].vp_efficiency > scores[0].vp_efficiency,
        "4VP card gets higher efficiency than 3VP card despite higher cost"
    );
}

#[test]
fn v030_noble_build_is_soft_phase_limited_and_observation_only() {
    let mut state = game(90);
    state.nobles = vec![NobleId(8)];
    state.players[0].bonuses = [1, 1, 0, 0, 0];
    expose(&mut state, CardId(0), 0);
    state.players[0].tokens.black = 3;
    state.bank.black -= 3;
    let buy = Action::BuyMarket {
        tier: Tier::One,
        slot: 0,
    };
    let obs = state.observation(PlayerId(0));
    let legal = state.legal_actions();
    let index = legal.iter().position(|a| *a == buy).unwrap();
    let one = heuristic_v02_term_scores(&obs, &[buy])[0];
    assert_eq!(one.noble_build, NOBLE_BUILD_PROGRESS_WEIGHT);
    assert_eq!(one, heuristic_v02_term_scores(&obs, &legal)[index]);
    assert_eq!(
        state.legal_actions(),
        legal,
        "scoring cannot restrict actions"
    );
    state.players[1].bonuses = [4, 4, 0, 0, 0];
    assert_eq!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0].noble_build,
        NOBLE_BUILD_PROGRESS_WEIGHT
    );
    state.players[1].bonuses = [0; 5];
    state.players[1].prestige = 12;
    assert_eq!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0].noble_build,
        0
    );
    state.players[1].prestige = 0;
    state.players[0].bonuses = [0; 5]; // distance eight: no distant-color bias
    assert_eq!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0].noble_build,
        0
    );
}

fn v030_noble_fixture() -> FullState {
    let mut state = game(91);
    expose(&mut state, CardId(0), 0); // blue, zero VP, three black
    state.market = [[None; 4]; 3];
    state.market[0][0] = Some(CardId(0));
    state.nobles = vec![NobleId(8)]; // W4 B4
    state.players[0].bonuses = [4, 3, 0, 0, 2];
    state.players[0].prestige = 12;
    state.players[1].prestige = 13;
    state
}

#[test]
fn v030_noble_readiness_and_buy_count_one_noble_exactly_once() {
    for multiple in [false, true] {
        let mut state = v030_noble_fixture();
        if multiple {
            state.nobles.push(NobleId(7)); // B4 G4: same purchase qualifies both
            state.players[0].bonuses[2] = 4;
        }
        let obs = state.observation(PlayerId(0));
        let take = Action::TakeTokens {
            take: Gems {
                white: 1,
                blue: 1,
                black: 1,
                ..Gems::ZERO
            },
            give_back: Gems::ZERO,
        };
        assert!(state.legal_actions().contains(&take));
        let t = heuristic_v02_term_scores(&obs, &[take])[0];
        assert_eq!(t.immediate_prestige, 0);
        assert_eq!(t.scoring_readiness, 3 * SCORING_READINESS_PER_VP);
        state.apply(take).unwrap();
        // Restore the actor to inspect the proposed next buy, without inventing an opponent move.
        state.current_player = PlayerId(0);
        let buy = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        assert!(state.legal_actions().contains(&buy));
        let t = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0];
        assert_eq!(t.immediate_prestige, 3 * (VP_WEIGHT + VP_LATE_BONUS));
        assert_eq!(
            t.vp_efficiency, 0,
            "triggering the final round strips future/economic terms"
        );
        assert_eq!(
            t.terminal_lead,
            TERMINAL_PRIORITY / 10,
            "later seats still have unknown responses"
        );
        assert_eq!(t.scoring_readiness, 0);
        state.apply(buy).unwrap();
        if multiple {
            assert_eq!(state.phase, Phase::ChooseNoble);
            state
                .apply(Action::ChooseNoble { noble: NobleId(8) })
                .unwrap();
        }
        assert_eq!(state.players[0].prestige, 15);
        assert_eq!(state.players[0].nobles.len(), 1);
    }
}

#[test]
fn v030_noble_readiness_counts_own_reserve_but_not_unaffordable_cards() {
    let mut state = v030_noble_fixture();
    let own = OwnProjection {
        tokens: Gems::ZERO,
        bonuses: state.players[0].bonuses,
        prestige: 12,
    };
    let obs = state.observation(PlayerId(0));
    assert_eq!(
        best_affordable_purchase_vp(&visible_targets(&obs), &own, &obs),
        0
    );
    let funded = OwnProjection {
        tokens: Gems {
            gold: 1,
            ..Gems::ZERO
        },
        ..own
    };
    assert_eq!(
        best_affordable_purchase_vp(&visible_targets(&obs), &funded, &obs),
        3
    );
    state.market[0][0] = None;
    state.players[0].reserved.push(ReservedCard {
        card: CardId(0),
        from_deck: true,
    });
    let obs = state.observation(PlayerId(0));
    assert_eq!(
        best_affordable_purchase_vp(&visible_targets(&obs), &funded, &obs),
        3
    );
    state.nobles.clear();
    let obs = state.observation(PlayerId(0));
    assert_eq!(
        best_affordable_purchase_vp(&visible_targets(&obs), &funded, &obs),
        0
    );
}

#[test]
fn reserve_penalty_does_not_use_raw_prestige_deficit() {
    let mut state = v030_noble_fixture();
    state.nobles.clear();
    state.players[0].bonuses = [1; 5];
    state.players[0].prestige = 2;
    state.players[1].prestige = 4;
    let reserve = Action::ReserveMarket {
        tier: Tier::One,
        slot: 0,
        give_back: Gems::ZERO,
    };
    let blind = Action::ReserveDeck {
        tier: Tier::One,
        give_back: Gems::ZERO,
    };
    for action in [reserve, blind] {
        assert!(state.legal_actions().contains(&action));
        let obs = state.observation(PlayerId(0));
        let legal = state.legal_actions();
        let idx = legal.iter().position(|a| *a == action).unwrap();
        let t = heuristic_v02_term_scores(&obs, &[action])[0];
        assert_eq!(
            t.race_reserve_penalty, 0,
            "being behind on points is not being behind on completion time"
        );
        assert_eq!(t, heuristic_v02_term_scores(&obs, &legal)[idx]);
    }
    for prestige in [4, 5] {
        state.players[0].prestige = prestige;
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[reserve])[0]
                .race_reserve_penalty,
            0
        );
    }
    state.players[0].prestige = 2;
    state.players[0].bonuses = [0; 5];
    assert_eq!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[reserve])[0]
            .race_reserve_penalty,
        0
    );
}

#[test]
fn v030_reserve_gold_enabling_noble_is_not_penalized_even_if_blind() {
    let state = v030_noble_fixture();
    for action in [
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 0,
            give_back: Gems::ZERO,
        },
        Action::ReserveDeck {
            tier: Tier::One,
            give_back: Gems::ZERO,
        },
    ] {
        assert!(state.legal_actions().contains(&action));
        let t = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[action])[0];
        assert_eq!(t.race_reserve_penalty, 0);
        assert_eq!(t.scoring_readiness, 3 * SCORING_READINESS_PER_VP);
        assert_eq!(t.immediate_prestige, 0);
    }
    // Same state with no gold: neither a future blind card nor an unpaid noble can help.
    let mut no_gold = state;
    no_gold.bank.gold = 0;
    let action = Action::ReserveDeck {
        tier: Tier::One,
        give_back: Gems::ZERO,
    };
    assert!(no_gold.legal_actions().contains(&action));
    let t = heuristic_v02_term_scores(&no_gold.observation(PlayerId(0)), &[action])[0];
    assert_eq!(
        t.race_reserve_penalty, 0,
        "no public finish or immediate buy was forgone"
    );
    assert_eq!(t.scoring_readiness, 0);
}

#[test]
fn v030_visible_noble_finish_denial_is_exempt_but_unaffordable_threat_is_not() {
    let mut state = v030_noble_fixture();
    state.players[0].bonuses = [1; 5];
    state.players[0].prestige = 5;
    state.players[1].bonuses = [4, 3, 0, 0, 3];
    state.players[1].prestige = 12;
    let reserve = Action::ReserveMarket {
        tier: Tier::One,
        slot: 0,
        give_back: Gems::ZERO,
    };
    let obs = state.observation(PlayerId(0));
    assert!(reserve_denies_visible_finish(&obs, card(CardId(0))));
    let t = heuristic_v02_term_scores(&obs, &[reserve])[0];
    assert_eq!(t.scoring_readiness, 0);
    assert_eq!(t.race_reserve_penalty, 0);
    state.players[1].bonuses[4] = 2;
    let obs = state.observation(PlayerId(0));
    assert!(!reserve_denies_visible_finish(&obs, card(CardId(0))));
    assert_eq!(
        heuristic_v02_term_scores(&obs, &[reserve])[0].race_reserve_penalty,
        0
    );
}

#[test]
fn v030_final_turn_discards_future_values_and_treats_equal_vp_buys_equally() {
    let mut state = game(92);
    expose(&mut state, CardId(24), 0); // free white -> noble W4 B4
    expose(&mut state, CardId(82), 0); // white, printed 3VP
    state.nobles = vec![NobleId(8)];
    state.players[0].bonuses = [3, 4, 3, 5, 3];
    state.players[0].prestige = 12;
    state.players[1].prestige = 15;
    state.end_game_triggered = true;
    state.turns_remaining_in_final_round = Some(0);
    let buy = Action::BuyMarket {
        tier: Tier::One,
        slot: 0,
    };
    let terms = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0];
    assert_eq!(
        terms,
        HeuristicV02Terms {
            immediate_prestige: 9000,
            final_round_card_cost: -1,
            ..HeuristicV02Terms::default()
        }
    );
    let mut child = state.clone();
    child.apply(buy).unwrap();
    assert!(child.is_terminal());
    assert_eq!(child.players[0].prestige, 15);
    state.nobles.clear();
    let scoring_buy = Action::BuyMarket {
        tier: Tier::Three,
        slot: 0,
    };
    assert!(state.legal_actions().contains(&scoring_buy));
    assert_eq!(
        heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[scoring_buy])[0],
        terms
    );
    let legal = state.legal_actions();
    let scores = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &legal);
    for (a, t) in legal.iter().zip(&scores) {
        if matches!(
            a,
            Action::TakeTokens { .. } | Action::ReserveMarket { .. } | Action::ReserveDeck { .. }
        ) {
            assert_eq!(*t, HeuristicV02Terms::default());
        }
    }
    assert!(scores
        .iter()
        .filter(|t| t.total() > 0)
        .all(|t| t.immediate_prestige > 0));
}

#[test]
fn v030_final_turn_does_not_buy_zero_vp_for_useless_discounts() {
    let mut state = v030_noble_fixture();
    state.nobles.clear();
    state.players[0].bonuses[4] = 3;
    state.end_game_triggered = true;
    state.turns_remaining_in_final_round = Some(0);
    let buy = Action::BuyMarket {
        tier: Tier::One,
        slot: 0,
    };
    let legal = state.legal_actions();
    assert!(legal.contains(&buy));
    let obs = state.observation(PlayerId(0));
    assert_eq!(heuristic_v02_term_scores(&obs, &[buy])[0].total(), -1);
    let take = legal
        .iter()
        .find(|a| matches!(a, Action::TakeTokens { .. }))
        .unwrap();
    assert_eq!(heuristic_v02_term_scores(&obs, &[*take])[0].total(), 0);
}

#[test]
fn real_playout_projection_and_refactor_fingerprint_match() {
    let mut checked = 0;
    let mut final_decisions = 0;
    let mut noble_buys = 0;
    let mut digest = 0xcbf29ce484222325u64;
    let mut decisions = 0usize;
    let mut ties = 0usize;
    for count in 2..=4 {
        for seed in 1..=3 {
            let mut state = FullState::new(GameConfig {
                seed,
                player_count: count,
                ruleset: Ruleset::base_v1(),
            })
            .unwrap()
            .0;
            for _ in 0..200 {
                if state.is_terminal() {
                    break;
                }
                state.assert_invariants().unwrap();
                let viewer = state.current_player;
                let obs = state.observation(viewer);
                let me = &state.players[viewer.index()];
                let before = OwnProjection {
                    tokens: me.tokens,
                    bonuses: me.bonuses,
                    prestige: me.prestige,
                };
                let legal = state.legal_actions();
                let scores = heuristic_v02_term_scores(&obs, &legal);
                if decisions % 17 == 0 {
                    let indices: Vec<_> = (0..legal.len()).step_by(2).rev().collect();
                    let subset: Vec<_> = indices.iter().map(|&i| legal[i]).collect();
                    let subset_scores = heuristic_v02_term_scores(&obs, &subset);
                    for (&i, terms) in indices.iter().zip(subset_scores) {
                        assert_eq!(terms, scores[i], "subset/order must not alter action terms");
                        let serialized = serde_json::to_value(terms).unwrap();
                        let fields = serialized.as_object().unwrap();
                        assert_eq!(fields.len(), 23, "trace schema stays compatible");
                        assert_eq!(
                            fields.values().map(|v| v.as_i64().unwrap()).sum::<i64>(),
                            terms.total(),
                            "trace terms stay additive"
                        );
                    }
                }
                let best_score = scores.iter().map(HeuristicV02Terms::total).max().unwrap();
                let argmax: Vec<_> = scores
                    .iter()
                    .enumerate()
                    .filter_map(|(i, t)| (t.total() == best_score).then_some(i))
                    .collect();
                ties += usize::from(argmax.len() > 1);
                let mut expected_rng = crate::StableRng::new(decisions as u64);
                let mut actual_rng = crate::StableRng::new(decisions as u64);
                let expected = if argmax.len() == 1 {
                    argmax[0]
                } else {
                    argmax[expected_rng.index(argmax.len())]
                };
                let choice = HeuristicAgentPolicyV02::new()
                    .choose_action(DecisionContext {
                        observation: obs.clone(),
                        visible_history: &[],
                        legal_actions: &legal,
                        meta: crate::policy::PublicRequestMeta {
                            game_id: "s411-smoke".into(),
                            recipient_seat: viewer,
                            request_id: decisions as u64,
                            observation_hash: splendor_core::observation_hash(&obs),
                        },
                        rng: &mut actual_rng,
                    })
                    .unwrap();
                assert_eq!(choice, legal[expected]);
                assert_eq!(
                    actual_rng.index(usize::MAX),
                    expected_rng.index(usize::MAX),
                    "tie RNG consumption"
                );
                for byte in serde_json::to_vec(&(&legal, &scores, &argmax, choice)).unwrap() {
                    digest = (digest ^ u64::from(byte)).wrapping_mul(0x100000001b3);
                }
                decisions += 1;
                let position = PositionContext::new(&obs);
                for (&action, terms) in legal.iter().zip(&scores) {
                    let projected = ActionProjection::new(&position, action);
                    let projection = projected.after;
                    let bought = projected.bought;
                    let mut child = state.clone();
                    child.apply(action).unwrap();
                    if child.phase == Phase::ChooseNoble {
                        child
                            .apply(Action::ChooseNoble {
                                noble: child.pending_nobles[0],
                            })
                            .unwrap();
                    }
                    let actual = &child.players[viewer.index()];
                    assert_eq!(projection.tokens, actual.tokens);
                    assert_eq!(projection.bonuses, actual.bonuses);
                    assert_eq!(projection.prestige, actual.prestige);
                    assert_eq!(
                        projected_bank(&obs, before.tokens, projection.tokens),
                        child.bank
                    );
                    if let Some(id) = bought {
                        if actual.prestige - before.prestige > card(id).prestige {
                            noble_buys += 1;
                        }
                    }
                    if obs.public.end_game_triggered {
                        assert!(matches!(terms.terminal_lead, 0 | 1));
                        assert_eq!(
                            terms.total(),
                            i64::from(actual.prestige - before.prestige)
                                * (VP_WEIGHT + VP_LATE_BONUS)
                                - i64::from(bought.is_some())
                                + position.noble_choice(action)
                                + terms.terminal_lead
                        );
                        final_decisions += 1;
                    }
                    checked += 1;
                }
                // Deterministic smoke walk, not a competitive measurement.
                let best = scores.iter().map(HeuristicV02Terms::total).max().unwrap();
                let index = scores.iter().position(|t| t.total() == best).unwrap();
                state.apply(legal[index]).unwrap();
            }
            assert!(
                state.is_terminal(),
                "smoke walk must finish: {count} players seed {seed}"
            );
            state.assert_invariants().unwrap();
        }
    }
    assert!(checked > 1000);
    assert!(noble_buys > 0);
    assert!(final_decisions > 0);
    println!(
        "S411_EQUIVALENCE digest={digest:016x} decisions={decisions} actions={checked} ties={ties}"
    );
    assert_eq!(
        digest, 0x3a7de6c6d622a2a6,
        "terms/argmax/choice must match the pre-refactor functional snapshot"
    );
    assert_eq!((decisions, checked, ties), (720, 24197, 181));
    assert!(ties > 0);
}

#[test]
fn opening_prefers_engine_tokens_over_premature_reserve() {
    let (state, _) = FullState::new(GameConfig {
        player_count: 2,
        seed: 4482377481514291788,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap();
    let obs = state.observation(PlayerId(0));
    let legal = state.legal_actions();
    let scores = heuristic_v02_term_scores(&obs, &legal);
    let max_score = scores.iter().map(HeuristicV02Terms::total).max().unwrap();
    let best_idx = scores.iter().position(|t| t.total() == max_score).unwrap();
    assert!(
        matches!(legal[best_idx], Action::TakeTokens { .. }),
        "turn 1 prioritizes taking tokens for engine over premature reserving: {:?}",
        legal[best_idx]
    );
}

#[test]
fn preparation_time_distinguishes_colors_supply_gold_slots_and_returns() {
    let own = OwnProjection {
        tokens: Gems::ZERO,
        bonuses: [0; 5],
        prestige: 0,
    };
    let bank = Gems {
        white: 4,
        blue: 4,
        green: 4,
        red: 4,
        black: 4,
        gold: 5,
    };
    let mut target = *card(CardId(0));
    target.cost = [1, 1, 1, 0, 0];
    assert_eq!(purchase_turns(&target, &own, bank, 0, 10), 2);
    target.cost = [3, 0, 0, 0, 0];
    assert_eq!(purchase_turns(&target, &own, bank, 0, 10), 3);
    target.cost = [1, 0, 0, 0, 0];
    let empty_color = Gems { white: 0, ..bank };
    assert_eq!(purchase_turns(&target, &own, empty_color, 2, 10), 2);
    assert_eq!(purchase_turns(&target, &own, empty_color, 3, 10), 9);
    assert_eq!(purchase_turns(&target, &own, empty_color, 0, 0), 9);
    let full = OwnProjection {
        tokens: Gems {
            blue: 3,
            green: 3,
            red: 4,
            ..Gems::ZERO
        },
        ..own
    };
    assert_eq!(
        purchase_turns(&target, &full, bank, 3, 10),
        2,
        "filler can be legally returned at the cap"
    );
    target.cost = [7, 4, 0, 0, 0];
    assert_eq!(
        purchase_turns(&target, &own, bank, 0, 10),
        9,
        "11-token cost cannot be held"
    );
}

#[test]
fn terminal_responses_respect_seats_removed_cards_and_fewer_purchases() {
    for count in 2..=4 {
        let mut state = FullState::new(GameConfig {
            seed: 4,
            player_count: count,
            ruleset: Ruleset::base_v1(),
        })
        .unwrap()
        .0;
        state.market = [[None; 4]; 3];
        state.market[1][0] = Some(CardId(45)); // 3 points, blue6
        state.nobles.clear();
        state.players[0].prestige = 12;
        state.players[0].bonuses[1] = 6;
        let last = usize::from(count - 1);
        state.players[last].prestige = 13;
        state.players[last].bonuses[1] = 6;
        state.players[last].reserved.push(ReservedCard {
            card: CardId(46),
            from_deck: false,
        });
        // Use another publicly affordable 3VP card as an independent reply.
        let reply = splendor_catalog::all_cards()
            .iter()
            .find(|d| d.prestige == 3 && d.id != CardId(45))
            .unwrap();
        state.players[last].reserved[0].card = reply.id;
        state.players[last].bonuses = [7; 5];
        let buy = Action::BuyMarket {
            tier: Tier::Two,
            slot: 0,
        };
        assert!(state.legal_actions().contains(&buy));
        let obs = state.observation(PlayerId(0));
        let t = heuristic_v02_term_scores(&obs, &[buy])[0];
        assert_eq!(t.terminal_lead, 0, "later public reserve scores 16");
        assert_eq!(t.engine_value, 0);
        state.players[last].reserved.clear();
        let t = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0];
        assert_eq!(
            t.terminal_lead,
            TERMINAL_PRIORITY / 10,
            "removed market card cannot be bought again"
        );
        state.players[last].prestige = 15;
        assert_eq!(
            heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0].terminal_lead,
            0,
            "equal VP opponent has fewer cards"
        );
        state.players[last].prestige = 12;
        state.players[0].prestige = 13;
        state.current_player = splendor_core::PlayerId(count - 1);
        let t = heuristic_v02_term_scores(&state.observation(state.current_player), &[buy])[0];
        assert_eq!(
            t.terminal_lead, TERMINAL_PRIORITY,
            "earlier seats cannot respond"
        );
    }
}

#[test]
fn denial_checks_alternative_public_reserves_and_winning_rank() {
    let mut state = v030_noble_fixture();
    state.nobles.clear();
    state.market = [[None; 4]; 3];
    state.market[1][0] = Some(CardId(45));
    state.players[0].prestige = 10;
    state.players[1].prestige = 12;
    state.players[1].bonuses = [7; 5];
    assert!(reserve_denies_visible_finish(
        &state.observation(PlayerId(0)),
        card(CardId(45))
    ));
    let alternative = splendor_catalog::all_cards()
        .iter()
        .find(|d| d.prestige == 3 && d.id != CardId(45))
        .unwrap()
        .id;
    state.players[1].reserved.push(ReservedCard {
        card: alternative,
        from_deck: false,
    });
    assert!(!reserve_denies_visible_finish(
        &state.observation(PlayerId(0)),
        card(CardId(45))
    ));
    state.players[1].reserved.clear();
    state.players[0].prestige = 18;
    assert!(
        !reserve_denies_visible_finish(&state.observation(PlayerId(0)), card(CardId(45))),
        "15 is not necessarily a winning finish"
    );
}

#[test]
fn noble_choice_denies_immediate_claim_and_projection_removes_it_once() {
    let mut state = v030_noble_fixture();
    state.nobles = vec![NobleId(8), NobleId(7)];
    state.players[0].bonuses = [4, 4, 4, 0, 0];
    state.players[0].prestige = 8;
    state.players[1].bonuses = [4, 3, 0, 0, 3];
    state.phase = Phase::ChooseNoble;
    state.pending_nobles = state.nobles.clone();
    let obs = state.observation(PlayerId(0));
    let actions = state.legal_actions();
    let terms = heuristic_v02_term_scores(&obs, &actions);
    let choose = |id| {
        terms[actions
            .iter()
            .position(|a| *a == Action::ChooseNoble { noble: id })
            .unwrap()]
    };
    assert_eq!(
        choose(NobleId(8)).immediate_prestige,
        choose(NobleId(7)).immediate_prestige
    );
    assert!(choose(NobleId(8)).total() > choose(NobleId(7)).total());
    state.nobles = vec![NobleId(8)];
    let obs = state.observation(PlayerId(0));
    assert_eq!(
        purchase_vp_excluding(card(CardId(0)), [4, 4, 4, 0, 0], &obs, Some(NobleId(8))),
        0
    );
}

#[test]
fn no_contestable_noble_disables_all_special_race_rewards() {
    let mut state = multi_noble_scoring_state(65);
    state.nobles = vec![NobleId(0)];
    state.players[1].bonuses = [7; 5];
    expose(&mut state, CardId(74), 0);
    give_race_buy_tokens(&mut state);
    let obs = state.observation(PlayerId(0));
    assert!(!PositionContext::new(&obs)
        .nobles
        .iter()
        .any(|n| n.contestable && n.distance <= NOBLE_RACE_DISTANCE_MAX));
    let buy = Action::BuyMarket {
        tier: Tier::Three,
        slot: 0,
    };
    let t = heuristic_v02_term_scores(&obs, &[buy])[0];
    assert_eq!(
        (
            t.noble_race_progress,
            t.noble_race_three_vp,
            t.noble_race_reserved
        ),
        (0, 0, 0)
    );
    state.market[2][0] = None;
    state.players[0].reserved.push(ReservedCard {
        card: CardId(74),
        from_deck: false,
    });
    let t = heuristic_v02_term_scores(
        &state.observation(PlayerId(0)),
        &[Action::BuyReserved { slot: 0 }],
    )[0];
    assert_eq!(
        (
            t.noble_race_progress,
            t.noble_race_three_vp,
            t.noble_race_reserved
        ),
        (0, 0, 0)
    );
}

#[test]
fn phase_is_smooth_at_eight_to_nine_and_public_finish_adds_urgency() {
    let mut state = game(69);
    state.nobles.clear();
    state.market = [[None; 4]; 3];
    let obs = state.observation(PlayerId(0));
    let eight = OwnProjection {
        tokens: Gems::ZERO,
        bonuses: [2, 2, 2, 1, 1],
        prestige: 0,
    };
    let nine = OwnProjection {
        bonuses: [2, 2, 2, 2, 1],
        ..eight
    };
    assert_eq!(phase_weight(&obs, &eight), 375);
    assert_eq!(phase_weight(&obs, &nine), 500);
    assert!(construction_weight(CHEAP_BUY_ULTRA, CHEAP_BUY_BUILD, &nine, 500) > 0);
    state.market[1][0] = Some(CardId(45));
    state.players[1].bonuses[1] = 6;
    state.players[1].prestige = 12;
    assert_eq!(phase_weight(&state.observation(PlayerId(0)), &eight), 1000);
}

#[test]
fn buying_discount_can_prepare_scoring_and_reserve_forfeits_immediate_buy() {
    let mut state = game(70);
    state.nobles.clear();
    state.market = [[None; 4]; 3];
    state.market[0][0] = Some(CardId(0));
    state.market[1][0] = Some(CardId(45));
    state.players[0].bonuses = [0, 2, 0, 0, 3];
    state.players[0].tokens.blue = 3;
    state.bank.blue -= 3;
    state.players[1].prestige = 12;
    let buy = Action::BuyMarket {
        tier: Tier::One,
        slot: 0,
    };
    let t = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[buy])[0];
    assert_eq!(t.immediate_prestige, 0);
    assert!(
        t.new_affordable_target > READY_WEIGHT,
        "buying a free useful discount improves the next scoring plan"
    );
    state.players[0].bonuses[1] = 6;
    let reserve = Action::ReserveDeck {
        tier: Tier::One,
        give_back: Gems::ZERO,
    };
    assert!(state.legal_actions().contains(&reserve));
    let t = heuristic_v02_term_scores(&state.observation(PlayerId(0)), &[reserve])[0];
    assert!(
        t.race_reserve_penalty < 0,
        "giving up an immediate 3VP buy has explicit opportunity cost"
    );
}

// Direct internal entry points for small hand-built fixtures.
fn select_targets(targets: &[CardDef], own: &OwnProjection, obs: &Observation) -> Vec<CardDef> {
    let position = PositionContext::new(obs);
    rank_targets(&position, targets, own)
        .into_iter()
        .take(2)
        .map(|t| t.def)
        .collect()
}

fn reserve_denies_visible_finish(obs: &Observation, def: &CardDef) -> bool {
    PositionContext::new(obs).denies_finish(def.id)
}

#[test]
fn already_triggered_final_prefers_equal_vp_buy_that_removes_public_reply() {
    let mut state = FullState::new(GameConfig {
        seed: 4,
        player_count: 3,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap()
    .0;
    state.market = [[None; 4]; 3];
    state.market[1][0] = Some(CardId(45)); // 3 VP, blue6
    state.market[1][1] = Some(CardId(51)); // 3 VP, red6
    state.nobles.clear();
    state.end_game_triggered = true;
    state.current_player = PlayerId(1);
    state.players[0].prestige = 15;
    state.players[1].prestige = 13;
    state.players[1].bonuses = [0, 6, 0, 6, 0];
    state.players[2].prestige = 14;
    state.players[2].bonuses = [0, 6, 0, 0, 0];
    let deny = Action::BuyMarket {
        tier: Tier::Two,
        slot: 0,
    };
    let allow = Action::BuyMarket {
        tier: Tier::Two,
        slot: 1,
    };
    let legal = state.legal_actions();
    assert!(legal.contains(&deny) && legal.contains(&allow));
    let obs = state.observation(state.current_player);
    let position = PositionContext::new(&obs);
    let opponent = position.opponents.iter().find(|p| p.seat == 2).unwrap();
    assert_eq!(response_rank(&obs, opponent, Some(CardId(45)), None).0, 14);
    assert_eq!(response_rank(&obs, opponent, Some(CardId(51)), None).0, 17);
    let terms = heuristic_v02_term_scores(&obs, &[deny, allow]);
    assert_eq!(terms[0].immediate_prestige, 9_000);
    assert_eq!(terms[0].immediate_prestige, terms[1].immediate_prestige);
    assert!(
        terms[0].total() > terms[1].total(),
        "remove the only public winning reply"
    );
    assert_eq!(heuristic_v02_term_scores(&obs, &[deny])[0], terms[0]);
    for t in terms {
        assert_eq!(
            t.total(),
            t.immediate_prestige + t.final_round_card_cost + t.terminal_lead
        );
        assert_eq!(t.bomb_reserve, 0);
    }
    state.players[2].reserved.push(ReservedCard {
        card: CardId(57),
        from_deck: false,
    });
    state.players[2].bonuses = [0, 6, 0, 0, 6];
    let obs = state.observation(state.current_player);
    let terms = heuristic_v02_term_scores(&obs, &[deny, allow]);
    assert_eq!(
        terms[0].terminal_lead, 0,
        "an alternative public reply refutes the lead"
    );
    assert_eq!(terms[0].total(), terms[1].total());
}
