//! M07 C2 integration tests: deterministic hidden-state sampling.
//!
//! `FullState` appears here only as an oracle that produces observations and
//! visible transcripts; the production API under test
//! (`sample_determinization_v1`) never receives a `FullState`, a real seed, a
//! deck order, or an opponent's blind-reserved `CardId`.

use splendor_belief::{
    build_information_set_v1, sample_determinization_v1, BeliefError, InformationSetV1,
    ReservedKnowledgeV1, DETERMINIZATION_VERSION,
};
use splendor_catalog::{card, CardId, NobleId, Tier, CARD_COUNT};
use splendor_core::{
    visible_events, Action, Audience, FullState, GameConfig, Gems, Phase, PlayerId, Ruleset,
};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

fn new_game(player_count: u8, seed: u64) -> FullState {
    let (state, _setup) = FullState::new(GameConfig {
        player_count,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("setup should succeed");
    state
}

fn drive(state: &mut FullState, script: &[(u8, Action)]) {
    for (player, action) in script {
        assert_eq!(state.current_player.0, *player);
        state.apply(*action).expect("apply should succeed");
        while state.phase == Phase::ChooseNoble {
            let noble = state
                .legal_actions()
                .iter()
                .find_map(|a| match a {
                    Action::ChooseNoble { noble } => Some(*noble),
                    _ => None,
                })
                .expect("ChooseNoble phase without a legal noble");
            state
                .apply(Action::ChooseNoble { noble })
                .expect("noble choice should succeed");
        }
    }
}

/// Give `player` exactly enough tokens to buy `card` (no gold needed).
fn fund(state: &mut FullState, player: usize, card_id: CardId) {
    let def = card(card_id);
    state.players[player].tokens = Gems {
        white: def.cost[0],
        blue: def.cost[1],
        green: def.cost[2],
        red: def.cost[3],
        black: def.cost[4],
        gold: 0,
    };
}

fn rm(tier: Tier, slot: u8) -> Action {
    Action::ReserveMarket {
        tier,
        slot,
        give_back: Gems::ZERO,
    }
}

fn rd(tier: Tier) -> Action {
    Action::ReserveDeck {
        tier,
        give_back: Gems::ZERO,
    }
}

fn info_set(state: &FullState, viewer: u8) -> InformationSetV1 {
    let observation = state.observation(PlayerId(viewer));
    let history = visible_events(&state.log, Audience::Player(PlayerId(viewer)));
    build_information_set_v1(Ruleset::base_v1(), &observation, &history).expect("build")
}

fn sample(info: &InformationSetV1, seed: u64, index: u64) -> splendor_belief::DeterminizationV1 {
    sample_determinization_v1(info, seed, index).expect("sample")
}

/// 2p game: viewer 0 sees HiddenDeck slots in both tiers (P1 blind reserves).
fn game_2p_hidden(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::One)),
            (0, rd(Tier::Two)),
            (1, rm(Tier::One, 1)),
            (0, rm(Tier::Two, 0)),
            (1, rd(Tier::Two)),
        ],
    );
    state
}

/// 2p game: P1 blind-reserves twice in the same tier (Two HiddenDeck One slots).
fn game_2p_same_tier_hidden(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::One)),
            (0, rm(Tier::One, 1)),
            (1, rd(Tier::One)),
        ],
    );
    state
}

/// 3p game: hidden reserves from both opponents.
fn game_3p(seed: u64) -> FullState {
    let mut state = new_game(3, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::Two)),
            (2, rd(Tier::One)),
            (0, rm(Tier::Two, 0)),
            (1, rm(Tier::One, 1)),
            (2, rm(Tier::One, 2)),
        ],
    );
    state
}

/// 4p game: hidden reserves from all three opponents.
fn game_4p(seed: u64) -> FullState {
    let mut state = new_game(4, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::One)),
            (2, rd(Tier::Two)),
            (3, rd(Tier::One)),
            (0, rm(Tier::Two, 0)),
            (1, rm(Tier::One, 1)),
            (2, rm(Tier::One, 2)),
            (3, rm(Tier::One, 3)),
        ],
    );
    state
}

/// 3p game viewed from player 1 (nonzero viewer with two hidden opponents).
fn game_3p_viewer1(seed: u64) -> FullState {
    let mut state = new_game(3, seed);
    drive(
        &mut state,
        &[
            (0, rd(Tier::One)),
            (1, rm(Tier::One, 0)),
            (2, rd(Tier::Two)),
            (0, rm(Tier::One, 1)),
            (1, rd(Tier::Two)),
            (2, rm(Tier::Two, 0)),
        ],
    );
    state
}

/// Prepare a valid state where the current purchase qualifies for two nobles.
fn drive_to_choose_noble(state: &mut FullState) {
    state.nobles = vec![NobleId(0), NobleId(1)];
    state.players[0].bonuses = [4; 5];
    let slot = state.market[Tier::One.index()]
        .iter()
        .position(Option::is_some)
        .expect("initial market is full") as u8;
    let card_id = state.market[Tier::One.index()][slot as usize].unwrap();
    fund(state, 0, card_id);
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot,
        })
        .expect("buy should succeed");
    assert_eq!(state.phase, Phase::ChooseNoble);
}

/// Drive a real game to GameOver by repeatedly buying the first affordable
/// market/reserved card for the current player.
fn drive_to_game_over(state: &mut FullState) {
    state.players[0].prestige = state.ruleset.prestige_to_end;
    let mut guard = 0;
    while state.phase != Phase::GameOver {
        guard += 1;
        assert!(guard < 400, "game did not finish");
        let tier = Tier::One;
        let slot = state.market[tier.index()]
            .iter()
            .position(Option::is_some)
            .expect("market card") as u8;
        let card_id = state.market[tier.index()][slot as usize].expect("market card");
        let player = state.current_player.index();
        fund(state, player, card_id);
        state
            .apply(Action::BuyMarket { tier, slot })
            .expect("apply should succeed");
        while state.phase == Phase::ChooseNoble {
            let noble = state
                .legal_actions()
                .iter()
                .find_map(|a| match a {
                    Action::ChooseNoble { noble } => Some(*noble),
                    _ => None,
                })
                .expect("noble");
            state.apply(Action::ChooseNoble { noble }).expect("noble");
        }
    }
    assert_eq!(state.phase, Phase::GameOver);
}

/// Sorted list of every card present in the state across all regions.
fn all_cards_in_state(state: &FullState) -> Vec<CardId> {
    let mut cards: Vec<CardId> = Vec::new();
    for tier in Tier::ALL {
        for c in state.market[tier.index()].iter().flatten() {
            cards.push(*c);
        }
        cards.extend(state.decks[tier.index()].iter().copied());
    }
    for player in &state.players {
        cards.extend(player.purchased.iter().copied());
        cards.extend(player.reserved.iter().map(|r| r.card));
    }
    cards.sort_unstable();
    cards
}

// ---------------------------------------------------------------------------
// Version
// ---------------------------------------------------------------------------

#[test]
fn determinization_version_is_one() {
    assert_eq!(DETERMINIZATION_VERSION, 1);
}

// ---------------------------------------------------------------------------
// Sampling across player counts and viewers
// ---------------------------------------------------------------------------

#[test]
fn samples_2p_3p_4p_real_information_sets() {
    for (state, viewer) in [
        (game_2p_hidden(1), 0u8),
        (game_2p_hidden(2), 0u8),
        (game_3p(3), 0u8),
        (game_4p(4), 0u8),
    ] {
        let info = info_set(&state, viewer);
        let d = sample(&info, 7, 3);
        assert_eq!(d.sample_seed(), 7);
        assert_eq!(d.sample_index(), 3);
        assert_eq!(d.state().player_count(), state.player_count());
    }
}

#[test]
fn viewer_zero_and_nonzero_both_sample() {
    let state = game_3p_viewer1(5);
    let info0 = info_set(&state, 0);
    let info1 = info_set(&state, 1);
    let info2 = info_set(&state, 2);
    for info in [&info0, &info1, &info2] {
        let d = sample(info, 11, 2);
        assert!(d.state_hash().as_str().len() >= 64);
    }
}

// ---------------------------------------------------------------------------
// Determinism and immutability
// ---------------------------------------------------------------------------

#[test]
fn same_key_produces_byte_identical_state_hash() {
    let info = info_set(&game_2p_hidden(1), 0);
    let a = sample(&info, 42, 7);
    let b = sample(&info, 42, 7);
    assert_eq!(a.state_hash().as_str(), b.state_hash().as_str());
}

#[test]
fn repeated_calls_do_not_mutate_information_set() {
    let state = game_2p_hidden(1);
    let info = info_set(&state, 0);
    let before = info.clone();
    for index in 0..4 {
        let _ = sample(&info, 1, index);
    }
    assert_eq!(info, before);
}

#[test]
fn frozen_corpus_hashes_are_deterministic() {
    // Golden hashes for the fixed 2p hidden-reserve information set at fixed
    // sample keys. Frozen so any RNG / ordering change is caught immediately.
    let info = info_set(&game_2p_hidden(1), 0);
    let cases = [
        (
            1u64,
            0u64,
            "4384229f7bb072313427e17afa9095512fe1acfbc208ac1a18d0e2b3e1f8f5e4",
        ),
        (
            1u64,
            1u64,
            "74dc8437ab56a528a00e1f49e08da0bb0af17f2350e87886b3fd8d6ad8d854fd",
        ),
        (
            1u64,
            2u64,
            "f764bca3a1f3ec1dd1ce720f912a8d074201def486f691501bb8f1259e2e46ab",
        ),
        (
            9u64,
            0u64,
            "35a9b7a2e3814f09d5a5d8d2a5fcffb8fc2bd87af4a72ee871173de8a43ec6b4",
        ),
    ];
    for (seed, index, golden) in cases {
        let d = sample(&info, seed, index);
        assert_eq!(d.state_hash().as_str(), golden, "seed {seed} index {index}");
    }
}

#[test]
fn different_sample_seed_changes_frozen_case() {
    let info = info_set(&game_2p_hidden(2), 0);
    let a = sample(&info, 1, 0);
    let b = sample(&info, 2, 0);
    assert_ne!(a.state_hash().as_str(), b.state_hash().as_str());
}

// ---------------------------------------------------------------------------
// Card partition and region invariants
// ---------------------------------------------------------------------------

#[test]
fn all_90_cards_partition_exactly_once() {
    let state = game_2p_hidden(1);
    let info = info_set(&state, 0);
    for index in 0..3 {
        let d = sample(&info, 5, index);
        let cards = all_cards_in_state(d.state());
        assert_eq!(cards.len(), CARD_COUNT, "index {index}");
        for window in cards.windows(2) {
            assert!(window[0] < window[1], "duplicate card in sample {index}");
        }
        assert_eq!(cards[0], CardId(0));
        assert_eq!(cards[CARD_COUNT - 1], CardId((CARD_COUNT - 1) as u8));
    }
}

#[test]
fn known_regions_unchanged() {
    let state = game_2p_hidden(1);
    let info = info_set(&state, 0);
    let observation = info.observation().clone();
    let d = sample(&info, 3, 1);
    // Market, bank, nobles, purchased, Known reserved are public / viewer
    // known; they must be byte-identical to the observation.
    assert_eq!(d.state().market, observation.public.market);
    assert_eq!(d.state().bank, observation.public.bank);
    assert_eq!(d.state().nobles, observation.public.nobles);
    for (i, view) in observation.public.players.iter().enumerate() {
        assert_eq!(d.state().players[i].purchased, view.purchased);
        assert_eq!(d.state().players[i].nobles, view.nobles);
        assert_eq!(d.state().players[i].tokens, view.tokens);
        assert_eq!(d.state().players[i].bonuses, view.bonuses);
        assert_eq!(d.state().players[i].prestige, view.prestige);
    }
    // Known reserved slots are unchanged (identity + from_deck).
    for player in info.reserved_knowledge() {
        let state_player = &d.state().players[player.player.index()];
        for (slot_index, slot) in player.slots.iter().enumerate() {
            if let ReservedKnowledgeV1::Known { card, from_deck } = slot {
                let reserved = &state_player.reserved[slot_index];
                assert_eq!(reserved.card, *card);
                assert_eq!(reserved.from_deck, *from_deck);
            }
        }
    }
}

#[test]
fn hidden_deck_slots_receive_correct_tier() {
    for (state, viewer) in [
        (game_2p_hidden(1), 0u8),
        (game_2p_same_tier_hidden(2), 0u8),
        (game_3p_viewer1(5), 1u8),
    ] {
        let info = info_set(&state, viewer);
        let d = sample(&info, 8, 4);
        for player in info.reserved_knowledge() {
            let state_player = &d.state().players[player.player.index()];
            for (slot_index, slot) in player.slots.iter().enumerate() {
                if let ReservedKnowledgeV1::HiddenDeck { tier } = slot {
                    let reserved = &state_player.reserved[slot_index];
                    assert!(reserved.from_deck);
                    assert_eq!(
                        card(reserved.card).tier,
                        *tier,
                        "player {:?} slot {slot_index} tier mismatch",
                        player.player
                    );
                }
            }
        }
    }
}

#[test]
fn deck_counts_exactly_preserved() {
    let state = game_2p_hidden(1);
    let info = info_set(&state, 0);
    let observation = info.observation().clone();
    for index in 0..3 {
        let d = sample(&info, 6, index);
        for tier in Tier::ALL {
            assert_eq!(
                d.state().decks[tier.index()].len(),
                observation.public.deck_counts[tier.index()] as usize
            );
        }
    }
}

#[test]
fn deck_vector_ordering_frozen() {
    // Frozen golden deck vectors for the fixed info set at a fixed key. This
    // locks the bottom->top contract: index 0 is the bottom, the last element
    // is the top card (core draws tops with Vec::pop()).
    let info = info_set(&game_2p_hidden(1), 0);
    let d = sample(&info, 42, 7);
    let actual = [
        d.state().decks[0]
            .iter()
            .map(|c| c.0 as u16)
            .collect::<Vec<_>>(),
        d.state().decks[1]
            .iter()
            .map(|c| c.0 as u16)
            .collect::<Vec<_>>(),
        d.state().decks[2]
            .iter()
            .map(|c| c.0 as u16)
            .collect::<Vec<_>>(),
    ];
    let golden: [[Vec<u16>; 3]; 1] = [[
        vec![
            8, 38, 17, 3, 23, 6, 32, 31, 5, 14, 19, 4, 27, 12, 7, 22, 29, 2, 26, 37, 11, 15, 33,
            24, 18, 20, 34, 39, 9, 21, 0, 16, 25,
        ],
        vec![
            43, 60, 67, 68, 58, 49, 54, 50, 48, 42, 53, 47, 69, 62, 57, 52, 66, 45, 44, 59, 55, 51,
            61,
        ],
        vec![
            70, 87, 80, 74, 72, 77, 84, 71, 85, 81, 86, 76, 82, 79, 89, 88,
        ],
    ]];
    assert_eq!(actual, golden[0]);
}

// ---------------------------------------------------------------------------
// Observation equality and legal actions
// ---------------------------------------------------------------------------

#[test]
fn sampled_observation_exactly_matches_original() {
    for (state, viewer) in [
        (game_2p_hidden(1), 0u8),
        (game_2p_same_tier_hidden(3), 0u8),
        (game_3p_viewer1(5), 1u8),
        (game_4p(6), 0u8),
    ] {
        let info = info_set(&state, viewer);
        let original = info.observation().clone();
        let d = sample(&info, 13, 5);
        assert_eq!(d.state().observation(PlayerId(viewer)), original);
    }
}

#[test]
fn legal_actions_identical_across_samples() {
    let state = game_2p_hidden(1);
    let info = info_set(&state, 0);
    let a = sample(&info, 21, 1);
    let b = sample(&info, 21, 2);
    assert_eq!(a.state().legal_actions(), b.state().legal_actions());
}

// ---------------------------------------------------------------------------
// Phase handling
// ---------------------------------------------------------------------------

#[test]
fn choose_noble_phase_samples_correctly() {
    let mut state = new_game(2, 1);
    drive_to_choose_noble(&mut state);
    assert_eq!(state.phase, Phase::ChooseNoble);
    let info = info_set(&state, 0);
    assert_eq!(info.observation().public.phase, Phase::ChooseNoble);
    let d = sample(&info, 2, 1);
    assert_eq!(d.state().phase, Phase::ChooseNoble);
    assert_eq!(
        d.state().pending_nobles,
        info.observation().public.pending_nobles
    );
    // All legal actions are noble choices.
    let actions = d.state().legal_actions();
    assert!(!actions.is_empty());
    assert!(actions
        .iter()
        .all(|a| matches!(a, Action::ChooseNoble { .. })));
    // The sampled state is itself a valid ChooseNoble state.
    let noble = actions[0];
    let mut next = d.state().clone();
    next.apply(noble).expect("noble choice applies on sample");
    assert_eq!(next.phase, Phase::Main);
}

#[test]
fn game_over_information_set_rejected() {
    let mut state = new_game(2, 1);
    drive_to_game_over(&mut state);
    assert_eq!(state.phase, Phase::GameOver);
    let info = info_set(&state, 0);
    assert_eq!(info.observation().public.phase, Phase::GameOver);
    let err = sample_determinization_v1(&info, 1, 1).expect_err("terminal sampling rejected");
    assert_eq!(err, BeliefError::TerminalInformationSet);
}

// ---------------------------------------------------------------------------
// Hidden-slot edge cases
// ---------------------------------------------------------------------------

#[test]
fn zero_hidden_reserve_case_samples() {
    let mut state = new_game(2, 1);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rm(Tier::One, 1)),
            (0, rm(Tier::Two, 0)),
        ],
    );
    let info = info_set(&state, 0);
    // No HiddenDeck slots at all.
    assert!(info.reserved_knowledge().iter().all(|p| p
        .slots
        .iter()
        .all(|s| matches!(s, ReservedKnowledgeV1::Known { .. }))));
    let d = sample(&info, 1, 0);
    assert_eq!(d.state().observation(PlayerId(0)), *info.observation());
}

#[test]
fn multiple_hidden_slots_same_tier_distinct_cards() {
    let state = game_2p_same_tier_hidden(2);
    let info = info_set(&state, 0);
    let hidden: Vec<&ReservedKnowledgeV1> = info
        .reserved_knowledge()
        .iter()
        .flat_map(|p| p.slots.iter())
        .filter(|s| matches!(s, ReservedKnowledgeV1::HiddenDeck { .. }))
        .collect();
    assert_eq!(hidden.len(), 2);
    let d = sample(&info, 4, 1);
    let mut sampled: Vec<CardId> = Vec::new();
    for player in info.reserved_knowledge() {
        for (i, slot) in player.slots.iter().enumerate() {
            if matches!(slot, ReservedKnowledgeV1::HiddenDeck { .. }) {
                sampled.push(d.state().players[player.player.index()].reserved[i].card);
            }
        }
    }
    assert_eq!(sampled.len(), 2);
    assert_ne!(sampled[0], sampled[1], "two hidden slots must be distinct");
    for c in &sampled {
        assert_eq!(card(*c).tier, Tier::One);
    }
}

#[test]
fn hidden_labels_ordered_player_then_slot_frozen() {
    // Golden assignment: with a fixed key the first HiddenDeck label (player,
    // slot) receives a frozen card. Locks the "player ascending, then slot
    // ascending" label order.
    let state = game_2p_same_tier_hidden(2);
    let info = info_set(&state, 0);
    let d = sample(&info, 4, 1);
    let p1_slot0 = d.state().players[1].reserved[0].card;
    let p1_slot1 = d.state().players[1].reserved[1].card;
    // Frozen golden cards for key (seed=4, index=1).
    let golden = (CardId(28), CardId(0));
    assert_eq!((p1_slot0, p1_slot1), golden);
}

// ---------------------------------------------------------------------------
// State identity
// ---------------------------------------------------------------------------

#[test]
fn synthetic_seed_is_deterministic_and_keyed() {
    let info = info_set(&game_2p_hidden(1), 0);
    let a = sample(&info, 5, 5);
    let b = sample(&info, 5, 5);
    assert_eq!(a.state().seed, b.state().seed);
    let c = sample(&info, 5, 6);
    assert_ne!(a.state().seed, c.state().seed);
    let d = sample(&info, 6, 5);
    assert_ne!(a.state().seed, d.state().seed);
}
