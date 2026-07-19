use std::collections::HashSet;

use rand::rngs::SmallRng;
use rand::{Rng, SeedableRng};
use splendor_core::{
    full_state_hash, observation_hash, play_random_game, Action, FullState, GameConfig, Gems,
    Phase, PlayerId,
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
