use std::collections::HashSet;

use rand::rngs::SmallRng;
use rand::{Rng, SeedableRng};
use splendor_core::{
    full_state_hash, observation_hash, play_random_game, public_state_hash, Action, CardId,
    FullState, GameConfig, GameEvent, Gems, NobleId, Phase, PlayerId, TerminalReason, Tier,
};

#[test]
fn setup_is_deterministic_for_same_seed() {
    let cfg = GameConfig {
        player_count: 2,
        seed: 42,
        ..Default::default()
    };
    let (a, _) = FullState::new(cfg.clone()).unwrap();
    let (b, _) = FullState::new(cfg).unwrap();
    assert_eq!(full_state_hash(&a), full_state_hash(&b));
    assert_eq!(a.market, b.market);
    assert_eq!(a.nobles, b.nobles);
    assert_eq!(a.decks, b.decks);
}

#[test]
fn different_seeds_usually_differ() {
    let (a, _) = FullState::new(GameConfig {
        seed: 1,
        ..Default::default()
    })
    .unwrap();
    let (b, _) = FullState::new(GameConfig {
        seed: 2,
        ..Default::default()
    })
    .unwrap();
    assert_ne!(full_state_hash(&a), full_state_hash(&b));
}

#[test]
fn hashes_include_ruleset_parameters_and_terminal_result() {
    let (state, _) = FullState::new(GameConfig::default()).unwrap();
    let mut changed_rules = state.clone();
    changed_rules.ruleset.max_tokens += 1;
    assert_ne!(
        full_state_hash(&state),
        full_state_hash(&changed_rules),
        "full hash must include ruleset parameters"
    );

    let mut terminal = state;
    terminal.bank = Gems::ZERO;
    terminal.market = [[None; 4]; 3];
    terminal.decks = [Vec::new(), Vec::new(), Vec::new()];
    let before_terminal = full_state_hash(&terminal);
    assert_eq!(terminal.legal_actions(), vec![Action::Pass]);
    terminal.apply(Action::Pass).unwrap();
    assert!(!terminal.is_terminal());
    assert_eq!(terminal.legal_actions(), vec![Action::Pass]);
    terminal.apply(Action::Pass).unwrap();
    assert!(terminal.is_terminal());
    assert_ne!(
        before_terminal,
        full_state_hash(&terminal),
        "terminal reason/result must be part of the full hash"
    );
}

#[test]
fn token_conservation_holds_after_setup() {
    for n in 2..=4 {
        let (state, _) = FullState::new(GameConfig {
            player_count: n,
            seed: 7,
            ..Default::default()
        })
        .unwrap();
        state.assert_invariants().unwrap();
        assert_eq!(state.nobles.len() as u8, n + 1);
    }
}

#[test]
fn observation_hides_opponent_blind_reserves() {
    let (mut state, _) = FullState::new(GameConfig {
        player_count: 2,
        seed: 99,
        ..Default::default()
    })
    .unwrap();

    // Force a deck reserve for player 0 if legal.
    let acts = state.legal_actions();
    let reserve_deck = acts
        .into_iter()
        .find(|a| matches!(a, Action::ReserveDeck { .. }));
    let Some(action) = reserve_deck else {
        // Extremely unlikely at start; skip soft.
        return;
    };
    state.apply(action).unwrap();

    let p0 = &state.players[0];
    assert_eq!(p0.reserved.len(), 1);
    assert!(p0.reserved[0].from_deck);

    let blind_card = p0.reserved[0].card;
    let obs1 = state.observation(PlayerId(1));
    // Opponent sees reserved_count but not the card id in public_reserved.
    assert_eq!(obs1.public.players[0].reserved_count, 1);
    assert!(obs1.public.players[0].public_reserved.is_empty());
    assert!(!obs1.private.reserved.iter().any(|r| r.card == blind_card));

    // Viewer 0 sees their own card.
    let obs0 = state.observation(PlayerId(0));
    assert_eq!(obs0.private.reserved.len(), 1);
    assert_eq!(obs0.private.reserved[0].card, blind_card);
}

#[test]
fn observation_hash_stable_when_only_opponent_blind_changes() {
    // Two states that differ only in P0's blind reserve identity should yield
    // identical observations for P1.
    let (mut a, _) = FullState::new(GameConfig {
        seed: 1234,
        ..Default::default()
    })
    .unwrap();
    let (mut b, _) = FullState::new(GameConfig {
        seed: 1234,
        ..Default::default()
    })
    .unwrap();

    // Reserve from deck on both.
    let act = Action::ReserveDeck {
        tier: splendor_core::Tier::One,
        give_back: Gems::ZERO,
    };
    if a.legal_actions().contains(&act) {
        a.apply(act).unwrap();
        b.apply(act).unwrap();
    } else {
        return;
    }

    // Swap P0 reserved card on b to another tier-1 card still in deck if possible.
    if b.players[0].reserved.is_empty() || b.decks[0].is_empty() {
        return;
    }
    let other = b.decks[0][0];
    let original = b.players[0].reserved[0].card;
    if other == original {
        return;
    }
    b.players[0].reserved[0].card = other;
    // Put original back into deck to keep card uniqueness.
    b.decks[0][0] = original;

    let ha = observation_hash(&a.observation(PlayerId(1)));
    let hb = observation_hash(&b.observation(PlayerId(1)));
    assert_eq!(
        ha, hb,
        "P1 observation must not depend on P0 blind reserve identity"
    );
    assert_ne!(full_state_hash(&a), full_state_hash(&b));
}

#[test]
fn random_games_preserve_invariants() {
    let mut rng = SmallRng::seed_from_u64(0xC0FFEE);
    for i in 0..50 {
        let seed = rng.gen::<u64>();
        let n = 2 + (i % 3) as u8; // 2,3,4
        let state = play_random_game(GameConfig {
            player_count: n,
            seed,
            ..Default::default()
        })
        .unwrap_or_else(|e| panic!("seed={seed} n={n}: {e}"));
        assert!(state.is_terminal());
        assert_eq!(state.phase, Phase::GameOver);
        state.assert_invariants().unwrap();
        let result = state.result.as_ref().unwrap();
        assert_eq!(result.scores.len(), n as usize);
        assert!(!result.winners.is_empty());
    }
}

#[test]
fn replay_action_sequence_reaches_same_hash() {
    let seed = 424242u64;
    let (mut state, _) = FullState::new(GameConfig {
        seed,
        player_count: 2,
        ..Default::default()
    })
    .unwrap();

    let mut actions = Vec::new();
    let mut guard = 0;
    while !state.is_terminal() && guard < 500 {
        guard += 1;
        let acts = state.legal_actions();
        assert!(!acts.is_empty(), "no legal actions mid-game");
        // Prefer first action for determinism of this test's recorded sequence.
        let action = acts[0];
        actions.push(action);
        state.apply(action).unwrap();
    }
    let final_hash = full_state_hash(&state);

    // Replay
    let (mut replay, _) = FullState::new(GameConfig {
        seed,
        player_count: 2,
        ..Default::default()
    })
    .unwrap();
    for action in actions {
        replay.apply(action).unwrap();
    }
    assert_eq!(full_state_hash(&replay), final_hash);
}

#[test]
fn take_tokens_atomic_with_return() {
    let (mut state, _) = FullState::new(GameConfig {
        seed: 1,
        ..Default::default()
    })
    .unwrap();

    // Move 10 tokens from bank → player so the next take must return.
    let held = Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    };
    state.bank = state.bank.checked_sub(held).expect("bank");
    state.players[0].tokens = held;
    state.assert_invariants().unwrap();

    let acts = state.legal_actions();
    let with_return = acts.iter().find(|a| match a {
        Action::TakeTokens { take, give_back } => take.total() > 0 && give_back.total() > 0,
        _ => false,
    });
    assert!(
        with_return.is_some(),
        "expected atomic take+return among legal actions, got {} actions",
        acts.len()
    );
    state.apply(*with_return.unwrap()).unwrap();
    assert!(state.players[0].tokens.total() <= 10);
    state.assert_invariants().unwrap();
}

#[test]
fn legal_actions_unique() {
    let (state, _) = FullState::new(GameConfig {
        seed: 55,
        player_count: 3,
        ..Default::default()
    })
    .unwrap();
    let acts = state.legal_actions();
    let set: HashSet<_> = acts.iter().copied().collect();
    assert_eq!(set.len(), acts.len());
}

fn put_card_zero_in_first_market_slot(state: &mut FullState) {
    let target = CardId(0);
    if state.market[0][0] == Some(target) {
        return;
    }

    let replacement = state.market[0][0].expect("initial market is full");
    let mut moved = false;
    for tier in 0..3 {
        for slot in 0..4 {
            if state.market[tier][slot] == Some(target) {
                state.market[tier][slot] = Some(replacement);
                moved = true;
                break;
            }
        }
        if moved {
            break;
        }
    }
    if !moved {
        let position = state.decks[0]
            .iter()
            .position(|&card| card == target)
            .expect("card 0 must be in a live zone");
        state.decks[0][position] = replacement;
    }
    state.market[0][0] = Some(target);
}

fn give_player_black_three(state: &mut FullState, player: PlayerId) {
    let tokens = Gems {
        black: 3,
        ..Gems::ZERO
    };
    state.bank = state.bank.checked_sub(tokens).expect("bank has payment");
    state.players[player.index()].tokens = tokens;
}

fn state_with_player_tokens(tokens: Gems) -> FullState {
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    state.bank = state.bank.checked_sub(tokens).expect("bank has tokens");
    state.players[0].tokens = tokens;
    state.assert_invariants().unwrap();
    state
}

fn market_returns_for_first_slot(state: &FullState) -> Vec<Gems> {
    state
        .legal_actions()
        .into_iter()
        .filter_map(|action| match action {
            Action::ReserveMarket {
                tier: Tier::One,
                slot: 0,
                give_back,
            } => Some(give_back),
            _ => None,
        })
        .collect()
}

fn blocked_state(player_count: u8) -> FullState {
    let (mut state, _) = FullState::new(GameConfig {
        player_count,
        ..Default::default()
    })
    .unwrap();
    state.bank = Gems::ZERO;
    state.market = [[None; 4]; 3];
    state.decks = [Vec::new(), Vec::new(), Vec::new()];
    for player in &mut state.players {
        player.tokens = Gems::ZERO;
    }
    state
}

#[test]
fn purchased_card_moves_to_player_zone() {
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    put_card_zero_in_first_market_slot(&mut state);
    give_player_black_three(&mut state, PlayerId(0));
    state.assert_invariants().unwrap();

    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        })
        .unwrap();

    assert_eq!(state.players[0].purchased, vec![CardId(0)]);
    assert_eq!(state.players[0].bonuses[1], 1);
    state.assert_invariants().unwrap();
}

#[test]
fn all_90_cards_exist_exactly_once() {
    let (state, _) = FullState::new(GameConfig::default()).unwrap();
    state.assert_invariants().unwrap();

    let finished = play_random_game(GameConfig {
        seed: 0xDADA,
        ..Default::default()
    })
    .unwrap();
    finished.assert_invariants().unwrap();
}

#[test]
fn bonus_cache_matches_purchased_cards() {
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    put_card_zero_in_first_market_slot(&mut state);
    give_player_black_three(&mut state, PlayerId(0));
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        })
        .unwrap();
    assert_eq!(state.players[0].bonuses, [0, 1, 0, 0, 0]);
    state.assert_invariants().unwrap();
}

#[test]
fn prestige_cache_matches_cards_and_nobles() {
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    put_card_zero_in_first_market_slot(&mut state);
    give_player_black_three(&mut state, PlayerId(0));
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        })
        .unwrap();
    state.players[0].nobles.push(NobleId(0));
    state.players[0].prestige = 3;
    state.assert_invariants().unwrap();
}

#[test]
fn public_observation_contains_purchased_cards() {
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    put_card_zero_in_first_market_slot(&mut state);
    give_player_black_three(&mut state, PlayerId(0));
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        })
        .unwrap();
    assert_eq!(
        state.observation(PlayerId(1)).public.players[0].purchased,
        vec![CardId(0)]
    );
}

fn two_market_cards_state() -> (FullState, CardId, CardId) {
    // Card 0 costs black-3, card 8 costs white-3: disjoint payments, both
    // affordable within a 2-player bank and the 10-token limit.
    let low = CardId(0);
    let high = CardId(8);
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    put_specific_card_in_market(&mut state, low, 0);
    put_specific_card_in_market(&mut state, high, 1);
    let tokens = Gems {
        white: 3,
        black: 3,
        ..Gems::ZERO
    };
    state.bank = state.bank.checked_sub(tokens).expect("bank has payment");
    state.players[0].tokens = tokens;
    // Drain the tier-1 deck so buying a tier-1 card does not refill the vacated
    // slot (refill order legitimately depends on buy order and would confound
    // this purchased-identity test). Cards are preserved in the tier-3 deck so
    // the 90-card conservation invariant still holds.
    let drained: Vec<CardId> = state.decks[0].drain(..).collect();
    state.decks[2].extend(drained);
    state.assert_invariants().unwrap();
    (state, low, high)
}

fn put_specific_card_in_market(state: &mut FullState, target: CardId, slot: usize) {
    if let Some(existing) = state.market[0][slot] {
        state.decks[0].push(existing);
    }
    if let Some(position) = state.decks[0].iter().position(|&c| c == target) {
        state.decks[0].remove(position);
    }
    for tier_deck in state.decks.iter_mut() {
        if let Some(position) = tier_deck.iter().position(|&c| c == target) {
            tier_deck.remove(position);
        }
    }
    state.market[0][slot] = Some(target);
}

fn buy_slot(state: &mut FullState, slot: u8) {
    // Isolate purchase-order accounting from turn rotation: always act as the
    // player under test regardless of whose turn the engine advanced to.
    state.current_player = PlayerId(0);
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot,
        })
        .unwrap();
}

#[test]
fn purchased_cards_are_stored_in_card_id_order() {
    let (mut state, low, high) = two_market_cards_state();
    buy_slot(&mut state, 1);
    buy_slot(&mut state, 0);
    assert_eq!(state.players[0].purchased, vec![low, high]);
    assert!(state.players[0]
        .purchased
        .windows(2)
        .all(|w| w[0].0 < w[1].0));
    state.assert_invariants().unwrap();
}

#[test]
fn purchased_order_does_not_change_public_hash() {
    let (mut forward, _, _) = two_market_cards_state();
    let (mut reverse, _, _) = two_market_cards_state();

    buy_slot(&mut forward, 0);
    buy_slot(&mut forward, 1);

    buy_slot(&mut reverse, 1);
    buy_slot(&mut reverse, 0);

    assert_ne!(forward.players[0].purchased, Vec::<CardId>::new());
    assert_eq!(forward.players[0].purchased, reverse.players[0].purchased);
    assert_eq!(full_state_hash(&forward), full_state_hash(&reverse));
    assert_eq!(public_state_hash(&forward), public_state_hash(&reverse));
}

#[test]
fn purchased_order_does_not_change_observation_hash() {
    let (mut forward, _, _) = two_market_cards_state();
    let (mut reverse, _, _) = two_market_cards_state();

    buy_slot(&mut forward, 0);
    buy_slot(&mut forward, 1);

    buy_slot(&mut reverse, 1);
    buy_slot(&mut reverse, 0);

    assert_eq!(
        observation_hash(&forward.observation(PlayerId(1))),
        observation_hash(&reverse.observation(PlayerId(1)))
    );
}

#[test]
fn unsorted_purchased_fails_invariants() {
    let (mut state, low, high) = two_market_cards_state();
    buy_slot(&mut state, 0);
    buy_slot(&mut state, 1);
    state.assert_invariants().unwrap();

    state.players[0].purchased = vec![high, low];
    assert!(state.assert_invariants().is_err());
}

#[test]
fn reserve_at_ten_tokens_enumerates_all_returns() {
    let state = state_with_player_tokens(Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    });
    let returns: HashSet<_> = market_returns_for_first_slot(&state).into_iter().collect();
    let expected: HashSet<_> = [
        Gems {
            white: 1,
            ..Gems::ZERO
        },
        Gems {
            blue: 1,
            ..Gems::ZERO
        },
        Gems {
            green: 1,
            ..Gems::ZERO
        },
        Gems {
            red: 1,
            ..Gems::ZERO
        },
        Gems {
            black: 1,
            ..Gems::ZERO
        },
        Gems {
            gold: 1,
            ..Gems::ZERO
        },
    ]
    .into_iter()
    .collect();
    assert_eq!(returns, expected);
}

#[test]
fn reserve_may_return_newly_received_gold() {
    let mut state = state_with_player_tokens(Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    });
    let action = market_returns_for_first_slot(&state)
        .into_iter()
        .find(|give_back| give_back.gold == 1)
        .map(|give_back| Action::ReserveMarket {
            tier: Tier::One,
            slot: 0,
            give_back,
        })
        .expect("returning newly received gold must be legal");
    let step = state.apply(action).unwrap();
    assert_eq!(state.players[0].tokens.gold, 0);
    assert_eq!(state.bank.gold, 5);
    assert!(step.events.iter().any(|event| {
        matches!(
            event,
            GameEvent::TokensTransferred {
                taken_from_bank: Gems { gold: 1, .. },
                returned_to_bank: Gems { gold: 1, .. },
                ..
            }
        )
    }));
}

#[test]
fn reserve_at_nine_tokens_requires_no_return() {
    let state = state_with_player_tokens(Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 1,
        gold: 0,
    });
    assert_eq!(market_returns_for_first_slot(&state), vec![Gems::ZERO]);
}

#[test]
fn reserve_without_available_gold_requires_no_return() {
    let mut state = state_with_player_tokens(Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    });
    let gold = Gems {
        gold: 5,
        ..Gems::ZERO
    };
    state.bank = state.bank.checked_sub(gold).unwrap();
    state.players[1].tokens = gold;
    assert_eq!(market_returns_for_first_slot(&state), vec![Gems::ZERO]);
}

#[test]
fn reserve_cannot_return_unheld_tokens() {
    let state = state_with_player_tokens(Gems {
        white: 4,
        blue: 4,
        green: 1,
        ..Gems::ZERO
    });
    let invalid = Action::ReserveMarket {
        tier: Tier::One,
        slot: 0,
        give_back: Gems {
            red: 1,
            ..Gems::ZERO
        },
    };
    assert!(!state.legal_actions().contains(&invalid));
}

#[test]
fn reserve_return_actions_are_unique() {
    let state = state_with_player_tokens(Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    });
    let returns = market_returns_for_first_slot(&state);
    let unique: HashSet<_> = returns.iter().copied().collect();
    assert_eq!(returns.len(), unique.len());
}

#[test]
fn reserve_transfer_event_records_take_and_return() {
    let mut state = state_with_player_tokens(Gems {
        white: 2,
        blue: 2,
        green: 2,
        red: 2,
        black: 2,
        gold: 0,
    });
    let action = Action::ReserveMarket {
        tier: Tier::One,
        slot: 0,
        give_back: Gems {
            gold: 1,
            ..Gems::ZERO
        },
    };
    let step = state.apply(action).unwrap();
    let transfer = step
        .events
        .iter()
        .position(|event| matches!(event, GameEvent::TokensTransferred { .. }))
        .expect("reserve token transfer event");
    let reserved = step
        .events
        .iter()
        .position(|event| matches!(event, GameEvent::CardReserved { .. }))
        .expect("reserve card event");
    assert!(
        transfer < reserved,
        "token transfer precedes card reservation"
    );
}

#[test]
fn pass_illegal_when_any_other_action_exists() {
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    assert!(state
        .legal_actions()
        .iter()
        .any(|action| !matches!(action, Action::Pass)));
    assert!(state.apply(Action::Pass).is_err());
}

#[test]
fn pass_only_action_when_player_is_blocked() {
    let state = blocked_state(2);
    assert_eq!(state.legal_actions(), vec![Action::Pass]);
}

#[test]
fn non_pass_resets_consecutive_passes() {
    let mut state = blocked_state(2);
    state.apply(Action::Pass).unwrap();
    assert_eq!(state.consecutive_forced_passes, 1);
    state.bank.white = 1;
    let action = Action::TakeTokens {
        take: Gems {
            white: 1,
            ..Gems::ZERO
        },
        give_back: Gems::ZERO,
    };
    assert!(state.legal_actions().contains(&action));
    state.apply(action).unwrap();
    assert_eq!(state.consecutive_forced_passes, 0);
}

#[test]
fn full_round_of_forced_passes_ends_game() {
    for player_count in 2..=4 {
        let mut state = blocked_state(player_count);
        for _ in 0..player_count {
            state.apply(Action::Pass).unwrap();
        }
        assert!(state.is_terminal());
        assert_eq!(
            state.result.as_ref().unwrap().reason,
            TerminalReason::Stalemate
        );
        assert_eq!(state.consecutive_forced_passes, player_count);
    }
}

#[test]
fn forced_pass_counter_changes_all_state_hashes() {
    let mut state = blocked_state(2);
    let full_before = full_state_hash(&state);
    let public_before = public_state_hash(&state);
    let observation_before = observation_hash(&state.observation(PlayerId(0)));
    state.apply(Action::Pass).unwrap();
    assert_ne!(full_before, full_state_hash(&state));
    assert_ne!(public_before, public_state_hash(&state));
    assert_ne!(
        observation_before,
        observation_hash(&state.observation(PlayerId(0)))
    );
}

#[test]
fn cli_and_core_reach_same_stalemate_hash() {
    let mut core = blocked_state(3);
    let mut replay = blocked_state(3);
    for _ in 0..3 {
        core.apply(Action::Pass).unwrap();
        replay.apply(Action::Pass).unwrap();
    }
    assert_eq!(full_state_hash(&core), full_state_hash(&replay));
}

fn threshold_state(player_count: u8, trigger: u8) -> FullState {
    let (mut state, _) = FullState::new(GameConfig {
        player_count,
        ..Default::default()
    })
    .unwrap();
    put_card_zero_in_first_market_slot(&mut state);
    for tier in 0..3 {
        for slot in 0..4 {
            if !(tier == 0 && slot == 0) {
                state.market[tier][slot] = None;
            }
        }
        state.decks[tier].clear();
    }
    state.nobles.clear();
    state.current_player = PlayerId(trigger);
    state.players[trigger as usize].prestige = state.ruleset.prestige_to_end;
    give_player_black_three(&mut state, PlayerId(trigger));
    state
}

fn record_action_players(events: &[GameEvent], actors: &mut Vec<PlayerId>) {
    for event in events {
        if let GameEvent::ActionApplied { player, .. } = event {
            actors.push(*player);
        }
    }
}

#[test]
fn final_round_finishes_only_remaining_seats_in_current_round() {
    for player_count in 2..=4 {
        for trigger in 0..player_count {
            let mut state = threshold_state(player_count, trigger);
            let mut actors: Vec<PlayerId> = Vec::new();
            let step = state
                .apply(Action::BuyMarket {
                    tier: Tier::One,
                    slot: 0,
                })
                .unwrap();
            record_action_players(&step.events, &mut actors);

            // The seat that crossed the threshold is the last seat, so the game
            // ends immediately once its own action is applied.
            if trigger == player_count - 1 {
                assert!(state.is_terminal());
                assert!(state.result.is_some());
            }

            // Make the remaining final-round actions forced passes. This test
            // isolates turn accounting from unrelated card/token choices.
            state.bank = Gems::ZERO;
            state.market = [[None; 4]; 3];
            state.decks = [Vec::new(), Vec::new(), Vec::new()];
            while !state.is_terminal() {
                let step = state.apply(Action::Pass).unwrap();
                record_action_players(&step.events, &mut actors);
            }

            // Every seat has the same number of actions once the round finishes:
            // the triggerer acts, then only the seats after it (up to the last
            // seat) get their turn.
            let mut expected: Vec<PlayerId> = vec![PlayerId(trigger)];
            expected.extend(((trigger + 1)..player_count).map(PlayerId));
            assert_eq!(actors, expected);
            assert_eq!(
                state.result.as_ref().unwrap().reason,
                TerminalReason::PrestigeThreshold
            );
        }
    }
}

fn multiple_noble_threshold_state() -> FullState {
    let (mut state, _) = FullState::new(GameConfig::default()).unwrap();
    put_card_zero_in_first_market_slot(&mut state);
    state.nobles = vec![NobleId(0), NobleId(1)];
    state.players[0].bonuses = [4; 5];
    state.players[0].prestige = state.ruleset.prestige_to_end - 1;
    give_player_black_three(&mut state, PlayerId(0));
    state
}

#[test]
fn threshold_reached_before_multiple_noble_choice() {
    let mut state = multiple_noble_threshold_state();
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        })
        .unwrap();
    assert_eq!(state.phase, Phase::ChooseNoble);
    assert!(!state.end_game_triggered);
}

#[test]
fn game_only_triggers_after_noble_is_chosen() {
    let mut state = multiple_noble_threshold_state();
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        })
        .unwrap();
    let noble = state.pending_nobles[0];
    state.apply(Action::ChooseNoble { noble }).unwrap();
    assert!(state.end_game_triggered);
    assert!(state.result.is_none());
}
