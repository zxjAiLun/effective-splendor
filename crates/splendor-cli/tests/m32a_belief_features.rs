//! Unit tests for M32A Belief Feature projection:
//! 1. unseen_card_mask is exactly 90 dims, bounded in [0.0, 1.0].
//! 2. reserved_knowledge is exactly 120 dims (2 players * 3 slots * 20 dims).
//! 3. HiddenDeck slots have non-zero status one-hot, but strictly ZERO card attributes.
//! 4. Empty slots have status[0] == 1.0 and zero card attributes.
//! 5. Total projection dimension is strictly 212.

use splendor_belief::build_information_set_v1;
use splendor_catalog::Tier;
use splendor_core::{
    visible_events, Action, Audience, FullState, GameConfig, Gems, PlayerId, Ruleset,
};

// The sidecar exporter is a binary; only the feature projection is used here,
// so the rest of it (including `main`) is dead in this context.
#[allow(dead_code)]
#[path = "../src/bin/m32a_export_sidecar.rs"]
mod m32a_export_sidecar;
use m32a_export_sidecar::{project_information_set_to_features, BELIEF_FEATURES};

#[test]
fn test_belief_features_dimension_and_structure() {
    let ruleset = Ruleset::base_v1();
    let (mut state, setup) = FullState::new(GameConfig {
        player_count: 2,
        seed: 12345,
        ruleset,
    })
    .unwrap();

    let viewer = PlayerId(0);
    let audience = Audience::Player(viewer);
    let mut visible_history = visible_events(&setup.events, audience);

    // Player 0 takes tokens
    let step1 = state
        .apply(Action::TakeTokens {
            take: Gems::from_colors([1, 1, 1, 0, 0]),
            give_back: Gems::ZERO,
        })
        .unwrap();
    visible_history.extend(visible_events(&step1.events, audience));

    // Player 1 (opponent) reserves a card from deck (blind reserve tier 1)
    let step2 = state
        .apply(Action::ReserveDeck {
            tier: Tier::One,
            give_back: Gems::ZERO,
        })
        .unwrap();
    visible_history.extend(visible_events(&step2.events, audience));

    let observation = state.observation(viewer);
    let info_set = build_information_set_v1(ruleset, &observation, &visible_history).unwrap();

    let features = project_information_set_to_features(&info_set, viewer);
    assert_eq!(features.len(), BELIEF_FEATURES);
    assert_eq!(features.len(), 212);

    // Check Part A: unseen card mask (0..90)
    let unseen_mask = &features[0..90];
    for &val in unseen_mask {
        assert!(val == 0.0 || val == 1.0);
    }
    // 90 total cards minus 12 market cards = 78 unseen cards (includes remaining deck + opponent blind reserve)
    let unseen_count: f32 = unseen_mask.iter().sum();
    assert_eq!(unseen_count, 90.0 - 12.0);

    // Check Part B: reserved knowledge (90..210, 120 dims)
    // Viewer slots (90..150): all 3 slots empty -> status[0] == 1.0, attributes == 0.0
    for slot_idx in 0..3 {
        let slot = &features[90 + slot_idx * 20..90 + (slot_idx + 1) * 20];
        assert_eq!(slot[0], 1.0); // empty
        for value in &slot[1..20] {
            assert_eq!(*value, 0.0);
        }
    }

    // Opponent slots (150..210): slot 0 is HiddenDeck tier 1
    let opp_slot_0 = &features[150..170];
    assert_eq!(opp_slot_0[0], 0.0); // not empty
    assert_eq!(opp_slot_0[1], 0.0); // not known_public
    assert_eq!(opp_slot_0[2], 0.0); // not known_private_from_deck
    assert_eq!(opp_slot_0[3], 1.0); // hidden_tier_1 == 1.0
    assert_eq!(opp_slot_0[4], 0.0); // hidden_tier_2 == 0.0
    assert_eq!(opp_slot_0[5], 0.0); // hidden_tier_3 == 0.0
                                    // CRITICAL: Card attributes (dims 6..20) MUST be strictly zero for HiddenDeck
    for (offset, value) in opp_slot_0[6..20].iter().enumerate() {
        assert_eq!(
            *value,
            0.0,
            "HiddenDeck slot attribute at index {} must be zero",
            6 + offset
        );
    }

    // Opponent slots 1 and 2 are empty
    for slot_idx in 1..3 {
        let slot = &features[150 + slot_idx * 20..150 + (slot_idx + 1) * 20];
        assert_eq!(slot[0], 1.0); // empty
        for value in &slot[1..20] {
            assert_eq!(*value, 0.0);
        }
    }

    // Check Part C: purchased_count (210..212)
    assert_eq!(features[210], 0.0); // viewer purchased count = 0
    assert_eq!(features[211], 0.0); // opp purchased count = 0
}
