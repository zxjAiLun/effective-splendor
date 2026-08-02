//! M07 C1 integration tests: information-set construction from visible inputs.
//!
//! `FullState` appears here only as an oracle that produces observations and
//! visible transcripts; the production API under test only ever receives
//! `Ruleset` + `Observation` + `&[VisibleEvent]`.

use splendor_belief::{
    build_information_set_v1, BeliefError, InformationSetV1, ReservedKnowledgeV1,
    INFORMATION_SET_VERSION,
};
use splendor_catalog::{card, cards_for_tier, CardId, Tier, CARD_COUNT};
use splendor_core::{
    visible_events, Action, Audience, FullState, GameConfig, Gems, Observation, Phase, PlayerId,
    Ruleset, Visibility, VisibleEvent,
};

// ---------------------------------------------------------------------------
// Test fixtures (FullState is test-only oracle material)
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
        assert_eq!(
            state.current_player.0, *player,
            "script turn mismatch for {action:?}"
        );
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

fn game_started(player_count: u8) -> VisibleEvent {
    VisibleEvent::GameStarted {
        player_count,
        ruleset: "splendor-base-v1".to_string(),
    }
}

/// P0: [Known market One/0, Known deck Two]; P1: [HiddenDeck One, Known market
/// One/1]; then P0 buys reserved slot 0 (the market card) so P0 becomes
/// [Known deck Two] (later slots shift left).
fn scenario_purchase(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::One)),
            (0, rd(Tier::Two)),
            (1, rm(Tier::One, 1)),
        ],
    );
    let card = state.players[0].reserved[0].card;
    fund(&mut state, 0, card);
    drive(&mut state, &[(0, Action::BuyReserved { slot: 0 })]);
    state
}

/// P0: [Known market One/0, Known deck One, Known market Two/0];
/// P1: [Known market One/1, HiddenDeck Two, Known market Two/1].
fn scenario_mixed(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rm(Tier::One, 1)),
            (0, rd(Tier::One)),
            (1, rd(Tier::Two)),
            (0, rm(Tier::Two, 0)),
            (1, rm(Tier::Two, 1)),
        ],
    );
    state
}

/// P1 blind-reserves deck One, then buys it (publicly revealing the card).
/// From viewer 0, P1's reserved vector ends empty.
fn scenario_hidden_purchase(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::One)),
            (0, rm(Tier::Two, 0)), // filler: hand the turn back to P1
        ],
    );
    let card = state.players[1].reserved[0].card;
    fund(&mut state, 1, card);
    drive(&mut state, &[(1, Action::BuyReserved { slot: 0 })]);
    state
}

fn scenario_np(player_count: u8, seed: u64) -> FullState {
    let mut state = new_game(player_count, seed);
    match player_count {
        3 => drive(
            &mut state,
            &[
                (0, rm(Tier::One, 0)),
                (1, rd(Tier::One)),
                (2, rm(Tier::One, 1)),
                (0, rd(Tier::Two)),
                (1, rm(Tier::Two, 0)),
                (2, rd(Tier::Three)),
            ],
        ),
        4 => drive(
            &mut state,
            &[
                (0, rm(Tier::One, 0)),
                (1, rd(Tier::One)),
                (2, rm(Tier::One, 1)),
                (3, rd(Tier::Two)),
                (0, rm(Tier::Two, 0)),
                (1, rm(Tier::Two, 1)),
                (2, rm(Tier::Three, 0)),
                (3, rm(Tier::Three, 1)),
            ],
        ),
        _ => unreachable!("scenario_np supports 3p and 4p"),
    }
    state
}

fn build(state: &FullState, viewer: u8) -> InformationSetV1 {
    let observation = state.observation(PlayerId(viewer));
    let history = visible_events(&state.log, Audience::Player(PlayerId(viewer)));
    build_information_set_v1(state.ruleset, &observation, &history)
        .expect("information set should build")
}

fn build_with(
    observation: &Observation,
    history: &[VisibleEvent],
) -> Result<InformationSetV1, BeliefError> {
    build_information_set_v1(Ruleset::base_v1(), observation, history)
}

// ---------------------------------------------------------------------------
// Version + API boundary
// ---------------------------------------------------------------------------

#[test]
fn version_is_one() {
    assert_eq!(INFORMATION_SET_VERSION, 1);
}

#[test]
fn production_api_accepts_only_visible_inputs() {
    // Pin the exact production signature: Ruleset + Observation + VisibleEvents.
    // If any production entry point gained a FullState / RefereeEvent / ReplayV1
    // / seed / deck-order parameter, this type annotation stops compiling.
    let _: fn(Ruleset, &Observation, &[VisibleEvent]) -> Result<InformationSetV1, BeliefError> =
        build_information_set_v1;
}

// ---------------------------------------------------------------------------
// Positive: real-game prefixes
// ---------------------------------------------------------------------------

#[test]
fn two_three_four_player_prefixes_build_successfully() {
    for (player_count, seed) in [(2, 1u64), (3, 2), (4, 3)] {
        let state = if player_count == 2 {
            scenario_mixed(seed)
        } else {
            scenario_np(player_count, seed)
        };
        for viewer in 0..player_count {
            let info = build(&state, viewer);
            assert_eq!(info.reserved_knowledge().len(), player_count as usize);
        }
    }
}

#[test]
fn zero_reserve_initial_state_builds() {
    let state = new_game(2, 11);
    let info = build(&state, 0);
    assert_eq!(info.ruleset(), Ruleset::base_v1());
    assert_eq!(info.observation(), &state.observation(PlayerId(0)));
    for player_info in info.reserved_knowledge() {
        assert!(player_info.slots.is_empty());
    }
    for tier in Tier::ALL {
        assert_eq!(
            info.unseen_cards(tier).len(),
            info.observation().public.deck_counts[tier.index()] as usize
        );
    }
}

#[test]
fn market_reserve_creates_known_slot() {
    let state = scenario_mixed(5);
    let info = build(&state, 0);
    let p0 = &info.reserved_knowledge()[0].slots;
    assert_eq!(
        p0[0],
        ReservedKnowledgeV1::Known {
            card: state.players[0].reserved[0].card,
            from_deck: false,
        }
    );
}

#[test]
fn own_deck_reserve_creates_known_deck_slot() {
    let state = scenario_mixed(5);
    let info = build(&state, 0);
    let p0 = &info.reserved_knowledge()[0].slots;
    assert_eq!(
        p0[1],
        ReservedKnowledgeV1::Known {
            card: state.players[0].reserved[1].card,
            from_deck: true,
        }
    );
}

#[test]
fn opponent_deck_reserve_creates_hidden_slot() {
    let state = scenario_mixed(5);
    let info = build(&state, 0);
    let p1 = &info.reserved_knowledge()[1].slots;
    assert_eq!(p1[1], ReservedKnowledgeV1::HiddenDeck { tier: Tier::Two });
}

#[test]
fn reserved_purchase_removes_exact_slot_and_shifts() {
    let state = scenario_purchase(7);
    let info = build(&state, 0);
    // The market slot (index 0) was bought; the deck reserve shifts to slot 0.
    let p0 = &info.reserved_knowledge()[0].slots;
    assert_eq!(p0.len(), 1);
    let remaining = state.players[0].reserved[0].card;
    assert_eq!(
        p0[0],
        ReservedKnowledgeV1::Known {
            card: remaining,
            from_deck: true,
        }
    );
    // The bought market card (tier One) joined purchased; the remaining
    // reserved card is the tier-Two deck reserve, not the bought one.
    assert_eq!(state.players[0].purchased.len(), 1);
    let bought = state.players[0].purchased[0];
    assert_ne!(bought, remaining);
    assert_eq!(card(bought).tier, Tier::One);
}

#[test]
fn mixed_public_blind_public_order_preserved() {
    let state = scenario_mixed(5);
    let info = build(&state, 0);
    let p1 = &info.reserved_knowledge()[1].slots;
    assert_eq!(
        *p1,
        vec![
            ReservedKnowledgeV1::Known {
                card: state.players[1].reserved[0].card,
                from_deck: false,
            },
            ReservedKnowledgeV1::HiddenDeck { tier: Tier::Two },
            ReservedKnowledgeV1::Known {
                card: state.players[1].reserved[2].card,
                from_deck: false,
            },
        ]
    );
}

#[test]
fn viewer_private_reserved_matches_observation() {
    let state = scenario_mixed(5);
    let viewer = 1;
    let info = build(&state, viewer);
    let observation = info.observation();
    let slots = &info.reserved_knowledge()[viewer as usize].slots;
    assert_eq!(slots.len(), observation.private.reserved.len());
    for (slot_index, (tracked, private)) in
        slots.iter().zip(&observation.private.reserved).enumerate()
    {
        assert_eq!(private.slot as usize, slot_index);
        assert_eq!(
            *tracked,
            ReservedKnowledgeV1::Known {
                card: private.card,
                from_deck: private.from_deck,
            }
        );
        assert_eq!(card(private.card).tier, private.tier);
    }
}

#[test]
fn opponent_public_reserved_filtered_order_matches_observation() {
    let state = scenario_mixed(5);
    let info = build(&state, 0);
    let observation = info.observation();
    let filtered: Vec<CardId> = info.reserved_knowledge()[1]
        .slots
        .iter()
        .filter_map(|kind| match kind {
            ReservedKnowledgeV1::Known {
                card,
                from_deck: false,
            } => Some(*card),
            _ => None,
        })
        .collect();
    assert_eq!(filtered, observation.public.players[1].public_reserved);
}

#[test]
fn hidden_reserve_purchase_reveals_and_removes_slot() {
    let state = scenario_hidden_purchase(9);
    let info = build(&state, 0);
    // P1's hidden slot is gone; the card is now publicly purchased.
    assert!(info.reserved_knowledge()[1].slots.is_empty());
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let bought = history
        .iter()
        .find_map(|event| match event {
            VisibleEvent::CardPurchased { player, card, .. } if *player == PlayerId(1) => {
                Some(*card)
            }
            _ => None,
        })
        .expect("P1 purchase event in visible history");
    assert!(state.players[1].purchased.contains(&bought));
    assert_eq!(card(bought).tier, Tier::One); // drawn from the tier-One deck
}

#[test]
fn viewer_zero_and_nonzero_both_build() {
    let state = scenario_mixed(5);
    let info0 = build(&state, 0);
    let info1 = build(&state, 1);
    assert_ne!(info0.information_set_hash(), info1.information_set_hash());
    // Viewer 1 sees its own deck reserve as Known.
    let p1 = &info1.reserved_knowledge()[1].slots;
    assert_eq!(
        p1[1],
        ReservedKnowledgeV1::Known {
            card: state.players[1].reserved[1].card,
            from_deck: true,
        }
    );
}

// ---------------------------------------------------------------------------
// Negative: hidden-information leaks and malformed history
// ---------------------------------------------------------------------------

/// Reuse the fields of a real event to build a synthetic variant; the
/// `from` source types are not nameable outside `splendor-core`, so synthetic
/// events are derived from real ones instead of being hand-constructed.
fn find_event(
    history: &[VisibleEvent],
    predicate: impl Fn(&VisibleEvent) -> bool,
) -> &VisibleEvent {
    history
        .iter()
        .find(|e| predicate(e))
        .expect("event present in history")
}

#[test]
fn opponent_blind_card_identity_leak_rejected() {
    // Real prefix: P0 reserves a market card, P1 blind-reserves from the deck.
    let mut state = new_game(2, 1);
    drive(&mut state, &[(0, rm(Tier::One, 0)), (1, rd(Tier::One))]);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let reserve = find_event(
        &history,
        |e| matches!(e, VisibleEvent::CardReserved { player, .. } if *player == PlayerId(1)),
    );
    let VisibleEvent::CardReserved {
        player,
        from,
        received_gold,
        public_identity,
        visible_to,
        ..
    } = reserve
    else {
        unreachable!("find_event matched a CardReserved")
    };
    // Same event, but the hidden opponent CardId is now present: a leak.
    let leaked = VisibleEvent::CardReserved {
        player: *player,
        card: Some(CardId(0)),
        from: *from,
        received_gold: *received_gold,
        public_identity: *public_identity,
        visible_to: *visible_to,
    };
    let err = build_with(&observation, &[game_started(2), leaked]).expect_err("leak rejected");
    assert_eq!(err, BeliefError::HiddenInformationLeak { index: 1 });
}

#[test]
fn chance_reveal_blind_draw_leak_rejected() {
    let mut state = new_game(2, 1);
    drive(&mut state, &[(0, rm(Tier::One, 0)), (1, rd(Tier::One))]);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let reveal = find_event(&history, |e| {
        matches!(e, VisibleEvent::ChanceRevealed { slot: None, .. })
    });
    let VisibleEvent::ChanceRevealed {
        tier,
        slot,
        visible_to,
        ..
    } = reveal
    else {
        unreachable!("find_event matched a ChanceRevealed")
    };
    let leaked = VisibleEvent::ChanceRevealed {
        tier: *tier,
        slot: *slot,
        card: Some(CardId(5)),
        visible_to: *visible_to,
    };
    let err = build_with(&observation, &[game_started(2), leaked]).expect_err("leak rejected");
    assert_eq!(err, BeliefError::HiddenInformationLeak { index: 1 });
}

#[test]
fn bad_reserved_purchase_slot_rejected() {
    // Real purchase event (from: Reserved { slot: 0 }) against a zero-reserve
    // observation: the slot cannot exist, so the purchase is malformed.
    let state = scenario_purchase(7);
    let fresh = new_game(2, 9);
    let observation = fresh.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let purchase = find_event(&history, |e| {
        matches!(e, VisibleEvent::CardPurchased { .. })
    });
    let VisibleEvent::CardPurchased {
        player,
        card,
        paid,
        from,
    } = purchase
    else {
        unreachable!("find_event matched a CardPurchased")
    };
    let bad = VisibleEvent::CardPurchased {
        player: *player,
        card: *card,
        paid: *paid,
        from: *from,
    };
    let err = build_with(&observation, &[game_started(2), bad]).expect_err("bad slot rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

#[test]
fn reserved_purchase_card_mismatch_rejected() {
    let state = scenario_purchase(7);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let purchase_index = history
        .iter()
        .position(|e| matches!(e, VisibleEvent::CardPurchased { .. }))
        .expect("purchase event");
    let mut tampered = history[..=purchase_index].to_vec();
    let VisibleEvent::CardPurchased {
        player, paid, from, ..
    } = &tampered[purchase_index]
    else {
        unreachable!("tampered purchase event is a CardPurchased")
    };
    tampered[purchase_index] = VisibleEvent::CardPurchased {
        player: *player,
        card: CardId(89), // not the tracked reserved card
        paid: *paid,
        from: *from,
    };
    let err = build_with(&observation, &tampered).expect_err("card mismatch rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index, .. } if index == purchase_index
    ));
}

#[test]
fn market_reserve_without_card_rejected() {
    let mut state = new_game(2, 1);
    drive(&mut state, &[(0, rm(Tier::One, 0))]);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let reserve = find_event(
        &history,
        |e| matches!(e, VisibleEvent::CardReserved { player, .. } if *player == PlayerId(0)),
    );
    let VisibleEvent::CardReserved {
        player,
        from,
        received_gold,
        public_identity,
        visible_to,
        ..
    } = reserve
    else {
        unreachable!("find_event matched a CardReserved")
    };
    let bad = VisibleEvent::CardReserved {
        player: *player,
        card: None,
        from: *from,
        received_gold: *received_gold,
        public_identity: *public_identity,
        visible_to: *visible_to,
    };
    let err =
        build_with(&observation, &[game_started(2), bad]).expect_err("cardless reserve rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

#[test]
fn empty_history_rejected() {
    let state = new_game(2, 1);
    let observation = state.observation(PlayerId(0));
    let err = build_with(&observation, &[]).expect_err("empty history rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 0, .. }
    ));
}

#[test]
fn history_without_game_started_rejected() {
    let state = new_game(2, 1);
    let observation = state.observation(PlayerId(0));
    let history = vec![VisibleEvent::ActionApplied {
        player: PlayerId(0),
        action: Action::TakeTokens {
            take: Gems::ZERO,
            give_back: Gems::ZERO,
        },
    }];
    let err = build_with(&observation, &history).expect_err("missing GameStarted rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 0, .. }
    ));
}

#[test]
fn game_started_player_count_mismatch_rejected() {
    let state = new_game(2, 1);
    let observation = state.observation(PlayerId(0));
    let history = vec![game_started(3)];
    let err = build_with(&observation, &history).expect_err("player count mismatch rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 0, .. }
    ));
}

// ---------------------------------------------------------------------------
// Negative: tampered observations
// ---------------------------------------------------------------------------

#[test]
fn tampered_reserved_count_rejected() {
    let state = scenario_purchase(7);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    tampered.public.players[1].reserved_count = 3; // real value is 2
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("tampered reserved_count rejected");
    assert_eq!(
        err,
        BeliefError::ReservedKnowledgeMismatch {
            player: PlayerId(1)
        }
    );
}

#[test]
fn tampered_public_reserved_order_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    tampered.public.players[1].public_reserved.reverse();
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("tampered public_reserved order rejected");
    assert_eq!(
        err,
        BeliefError::ReservedKnowledgeMismatch {
            player: PlayerId(1)
        }
    );
}

#[test]
fn tampered_public_reserved_card_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    tampered.public.players[1].public_reserved[0] = CardId(89);
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("tampered public_reserved card rejected");
    assert_eq!(
        err,
        BeliefError::ReservedKnowledgeMismatch {
            player: PlayerId(1)
        }
    );
}

#[test]
fn tampered_viewer_private_slot_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    tampered.private.reserved[0].slot = 5;
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("tampered private slot rejected");
    assert_eq!(
        err,
        BeliefError::ReservedKnowledgeMismatch {
            player: PlayerId(0)
        }
    );
}

#[test]
fn tampered_viewer_private_card_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    tampered.private.reserved[0].card = CardId(89);
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("tampered private card rejected");
    assert_eq!(
        err,
        BeliefError::ReservedKnowledgeMismatch {
            player: PlayerId(0)
        }
    );
}

#[test]
fn tampered_viewer_private_from_deck_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    tampered.private.reserved[1].from_deck = !tampered.private.reserved[1].from_deck;
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("tampered from_deck rejected");
    assert_eq!(
        err,
        BeliefError::ReservedKnowledgeMismatch {
            player: PlayerId(0)
        }
    );
}

#[test]
fn viewer_out_of_range_rejected() {
    let state = scenario_mixed(5);
    let mut observation = state.observation(PlayerId(0));
    observation.viewer = PlayerId(5);
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let err = build_information_set_v1(Ruleset::base_v1(), &observation, &history)
        .expect_err("out-of-range viewer rejected");
    assert_eq!(
        err,
        BeliefError::ViewerOutOfRange {
            viewer: PlayerId(5),
            player_count: 2,
        }
    );
}

#[test]
fn ruleset_fingerprint_mismatch_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut ruleset = Ruleset::base_v1();
    ruleset.prestige_to_end = 16;
    let err = build_information_set_v1(ruleset, &observation, &history)
        .expect_err("ruleset fingerprint mismatch rejected");
    assert_eq!(err, BeliefError::RulesetFingerprintMismatch);
}

#[test]
fn malformed_player_structure_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));

    let mut wrong_len = observation.clone();
    wrong_len.public.players.pop();
    let err = build_information_set_v1(Ruleset::base_v1(), &wrong_len, &history)
        .expect_err("player_count != players.len() rejected");
    assert!(matches!(err, BeliefError::MalformedObservation(_)));

    let mut wrong_id = observation.clone();
    wrong_id.public.players[1].id = PlayerId(2);
    let err = build_information_set_v1(Ruleset::base_v1(), &wrong_id, &history)
        .expect_err("non-contiguous player ids rejected");
    assert!(matches!(err, BeliefError::MalformedObservation(_)));
}

// ---------------------------------------------------------------------------
// Negative: card accounting
// ---------------------------------------------------------------------------

#[test]
fn duplicate_known_card_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    let duplicated = tampered.public.market[Tier::One.index()][2].expect("market card");
    tampered.public.market[Tier::One.index()][3] = Some(duplicated);
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("duplicate known card rejected");
    assert_eq!(err, BeliefError::DuplicateKnownCard { card: duplicated });
}

#[test]
fn tier_card_mismatch_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    let tier_one_card = cards_for_tier(Tier::One)[0].id;
    tampered.public.market[Tier::Three.index()][0] = Some(tier_one_card);
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("tier/card mismatch rejected");
    assert!(matches!(err, BeliefError::MalformedObservation(_)));
}

#[test]
fn deck_count_exceeding_tier_total_rejected() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    tampered.public.deck_counts[2] = 200;
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("deck count over total rejected");
    assert_eq!(
        err,
        BeliefError::CardAccountingMismatch {
            tier: Tier::Three,
            expected: cards_for_tier(Tier::Three).len(),
            found: 200,
        }
    );
}

#[test]
fn per_tier_unseen_accounting_mismatch_rejected() {
    let state = scenario_purchase(7);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut tampered = observation.clone();
    let real = tampered.public.deck_counts[1];
    tampered.public.deck_counts[1] = real - 1;
    let err = build_information_set_v1(Ruleset::base_v1(), &tampered, &history)
        .expect_err("unseen accounting mismatch rejected");
    assert!(matches!(
        err,
        BeliefError::CardAccountingMismatch {
            tier: Tier::Two,
            ..
        }
    ));
}

// ---------------------------------------------------------------------------
// Card partition + unseen pools
// ---------------------------------------------------------------------------

#[test]
fn unseen_cards_are_sorted_by_card_id() {
    for state in [
        scenario_mixed(5),
        scenario_purchase(7),
        scenario_np(3, 2),
        scenario_np(4, 3),
    ] {
        let info = build(&state, 0);
        for tier in Tier::ALL {
            let unseen = info.unseen_cards(tier);
            assert!(
                unseen.windows(2).all(|w| w[0] < w[1]),
                "unseen tier {tier:?} not strictly ascending"
            );
        }
    }
}

#[test]
fn unseen_count_equals_deck_count_plus_hidden_reserves() {
    for state in [
        scenario_mixed(5),
        scenario_purchase(7),
        scenario_hidden_purchase(9),
    ] {
        let info = build(&state, 0);
        let hidden_per_tier = |tier: Tier| {
            info.reserved_knowledge()
                .iter()
                .flat_map(|p| p.slots.iter())
                .filter(|k| matches!(k, ReservedKnowledgeV1::HiddenDeck { tier: t } if *t == tier))
                .count()
        };
        for tier in Tier::ALL {
            assert_eq!(
                info.unseen_cards(tier).len(),
                info.observation().public.deck_counts[tier.index()] as usize
                    + hidden_per_tier(tier),
                "tier {tier:?} unseen count"
            );
        }
    }
}

#[test]
fn all_ninety_cards_partition_exactly_once_across_known_and_unseen() {
    let state = scenario_mixed(5);
    let info = build(&state, 0);
    let observation = info.observation();

    let mut known: Vec<CardId> = Vec::new();
    for tier in Tier::ALL {
        for slot in 0..4 {
            if let Some(c) = observation.public.market[tier.index()][slot] {
                known.push(c);
            }
        }
    }
    for player_view in &observation.public.players {
        known.extend(player_view.purchased.iter().copied());
    }
    for player_info in info.reserved_knowledge() {
        for kind in &player_info.slots {
            if let ReservedKnowledgeV1::Known { card, .. } = kind {
                known.push(*card);
            }
        }
    }

    let mut all: Vec<CardId> = known.clone();
    for tier in Tier::ALL {
        all.extend(info.unseen_cards(tier).iter().copied());
    }
    all.sort_unstable();
    assert_eq!(all.len(), CARD_COUNT, "known + unseen must total 90");
    assert!(
        all.windows(2).all(|w| w[0] != w[1]),
        "known and unseen must be disjoint"
    );
    assert_eq!(all.first(), Some(&CardId(0)));
    assert_eq!(all.last(), Some(&CardId((CARD_COUNT - 1) as u8)));
}

// ---------------------------------------------------------------------------
// Hash identities
// ---------------------------------------------------------------------------

fn is_lower_hex64(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[test]
fn visible_history_hash_is_deterministic_lower_hex64() {
    let state = scenario_mixed(5);
    let info_a = build(&state, 0);
    let info_b = build(&state, 0);
    assert_eq!(info_a.visible_history_hash(), info_b.visible_history_hash());
    assert!(is_lower_hex64(info_a.visible_history_hash().as_str()));
    assert!(is_lower_hex64(info_a.information_set_hash().as_str()));
}

#[test]
fn information_set_hash_is_deterministic() {
    let state = scenario_mixed(5);
    let info_a = build(&state, 1);
    let info_b = build(&state, 1);
    assert_eq!(info_a.information_set_hash(), info_b.information_set_hash());
}

#[test]
fn event_order_change_changes_history_hash() {
    let state = new_game(2, 3);
    let observation = state.observation(PlayerId(0));
    let take_p0 = VisibleEvent::ActionApplied {
        player: PlayerId(0),
        action: Action::TakeTokens {
            take: Gems::ZERO,
            give_back: Gems::ZERO,
        },
    };
    let take_p1 = VisibleEvent::ActionApplied {
        player: PlayerId(1),
        action: Action::TakeTokens {
            take: Gems::ZERO,
            give_back: Gems::ZERO,
        },
    };
    let history_a = vec![game_started(2), take_p0.clone(), take_p1.clone()];
    let history_b = vec![game_started(2), take_p1, take_p0];
    let info_a = build_with(&observation, &history_a).expect("build a");
    let info_b = build_with(&observation, &history_b).expect("build b");
    assert_ne!(info_a.visible_history_hash(), info_b.visible_history_hash());
}

#[test]
fn observation_change_changes_information_set_hash() {
    let state = scenario_mixed(5);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let mut other = observation.clone();
    other.public.players[0].tokens.white += 1;
    let info_a = build_with(&observation, &history).expect("build a");
    let info_b = build_with(&other, &history).expect("build b");
    assert_eq!(info_a.visible_history_hash(), info_b.visible_history_hash());
    assert_ne!(info_a.information_set_hash(), info_b.information_set_hash());
}

// ---------------------------------------------------------------------------
// Input immutability
// ---------------------------------------------------------------------------

#[test]
fn inputs_remain_unchanged() {
    let state = scenario_purchase(7);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let observation_before = observation.clone();
    let history_before = history.clone();
    build_information_set_v1(Ruleset::base_v1(), &observation, &history).expect("build");
    assert_eq!(observation, observation_before);
    assert_eq!(history, history_before);
}

// ---------------------------------------------------------------------------
// Visibility-boundary enforcement (C1 fix-forward P1)
// ---------------------------------------------------------------------------

#[test]
fn market_reserve_non_public_visibility_rejected() {
    let mut state = new_game(2, 1);
    drive(&mut state, &[(0, rm(Tier::One, 0))]);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let reserve = find_event(&history, |e| matches!(e, VisibleEvent::CardReserved { .. }));
    let VisibleEvent::CardReserved {
        player,
        card,
        from,
        received_gold,
        public_identity,
        ..
    } = reserve
    else {
        unreachable!("find_event matched a CardReserved")
    };
    let bad = VisibleEvent::CardReserved {
        player: *player,
        card: *card,
        from: *from,
        received_gold: *received_gold,
        public_identity: *public_identity,
        visible_to: Visibility::Player(PlayerId(1)),
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("non-public market reserve rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

#[test]
fn viewer_deck_reserve_wrong_visibility_rejected() {
    let mut state = new_game(2, 1);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rm(Tier::One, 1)),
            (0, rd(Tier::Two)),
        ],
    );
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    // The viewer's own blind draw: card Some, visible_to Player(0).
    let reserve = find_event(&history, |e| {
        matches!(
            e,
            VisibleEvent::CardReserved {
                public_identity: false,
                ..
            }
        )
    });
    let VisibleEvent::CardReserved {
        player,
        card,
        from,
        received_gold,
        public_identity,
        ..
    } = reserve
    else {
        unreachable!("find_event matched a CardReserved")
    };
    assert!(card.is_some());
    let bad = VisibleEvent::CardReserved {
        player: *player,
        card: *card,
        from: *from,
        received_gold: *received_gold,
        public_identity: *public_identity,
        visible_to: Visibility::Player(PlayerId(1)), // != Player(0) viewer
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("viewer deck reserve with wrong visible_to rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

#[test]
fn opponent_deck_reserve_wrong_visibility_rejected() {
    let mut state = new_game(2, 1);
    drive(&mut state, &[(0, rm(Tier::One, 0)), (1, rd(Tier::One))]);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let reserve = find_event(&history, |e| {
        matches!(
            e,
            VisibleEvent::CardReserved {
                player: PlayerId(1),
                ..
            }
        )
    });
    let VisibleEvent::CardReserved {
        player,
        card,
        from,
        received_gold,
        public_identity,
        ..
    } = reserve
    else {
        unreachable!("find_event matched a CardReserved")
    };
    assert!(card.is_none());
    let bad = VisibleEvent::CardReserved {
        player: *player,
        card: *card,
        from: *from,
        received_gold: *received_gold,
        public_identity: *public_identity,
        visible_to: Visibility::Player(PlayerId(0)), // != Player(1) opponent
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("opponent deck reserve with wrong visible_to rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

#[test]
fn blind_chance_reveal_public_rejected() {
    let mut state = new_game(2, 1);
    drive(&mut state, &[(0, rm(Tier::One, 0)), (1, rd(Tier::One))]);
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let reveal = find_event(&history, |e| {
        matches!(e, VisibleEvent::ChanceRevealed { slot: None, .. })
    });
    let VisibleEvent::ChanceRevealed {
        tier, slot, card, ..
    } = reveal
    else {
        unreachable!("find_event matched a ChanceRevealed")
    };
    let bad = VisibleEvent::ChanceRevealed {
        tier: *tier,
        slot: *slot,
        card: *card,
        visible_to: Visibility::Public,
    };
    let err =
        build_with(&observation, &[game_started(2), bad]).expect_err("public blind draw rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

#[test]
fn viewer_blind_chance_reveal_without_card_rejected() {
    let mut state = new_game(2, 1);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rm(Tier::One, 1)),
            (0, rd(Tier::Two)),
        ],
    );
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    // The viewer's own blind draw carries the card identity.
    let reveal = find_event(&history, |e| {
        matches!(
            e,
            VisibleEvent::ChanceRevealed {
                slot: None,
                card: Some(_),
                ..
            }
        )
    });
    let VisibleEvent::ChanceRevealed {
        tier,
        slot,
        visible_to,
        ..
    } = reveal
    else {
        unreachable!("find_event matched a ChanceRevealed")
    };
    let bad = VisibleEvent::ChanceRevealed {
        tier: *tier,
        slot: *slot,
        card: None,
        visible_to: *visible_to,
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("viewer blind draw without card rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

#[test]
fn market_reveal_visibility_and_shape_enforced() {
    // Real game: P0 buys a market card, the deck refills the slot and the
    // engine emits a market reveal (slot Some, card Some, Public).
    let mut state = new_game(2, 3);
    let buy_card = state.observation(PlayerId(0)).public.market[Tier::One.index()][2]
        .expect("market card at slot 2");
    fund(&mut state, 0, buy_card);
    drive(
        &mut state,
        &[(
            0,
            Action::BuyMarket {
                tier: Tier::One,
                slot: 2,
            },
        )],
    );
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let reveal = find_event(&history, |e| {
        matches!(e, VisibleEvent::ChanceRevealed { slot: Some(_), .. })
    });
    let VisibleEvent::ChanceRevealed {
        tier,
        slot,
        card,
        visible_to,
    } = reveal
    else {
        unreachable!("find_event matched a ChanceRevealed")
    };
    let card_val = card.expect("market reveal carries a card");
    assert_eq!(*tier, Tier::One);
    assert!((card_val.0 as usize) < CARD_COUNT);

    // (a) non-Public visibility
    let bad = VisibleEvent::ChanceRevealed {
        tier: *tier,
        slot: *slot,
        card: *card,
        visible_to: Visibility::Player(PlayerId(1)),
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("non-public market reveal rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));

    // (b) missing card identity
    let bad = VisibleEvent::ChanceRevealed {
        tier: *tier,
        slot: *slot,
        card: None,
        visible_to: *visible_to,
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("cardless market reveal rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));

    // (c) tier mismatch: a tier-2 card in a tier-1 reveal
    let tier_two_card = cards_for_tier(Tier::Two)[0].id;
    let bad = VisibleEvent::ChanceRevealed {
        tier: *tier,
        slot: *slot,
        card: Some(tier_two_card),
        visible_to: *visible_to,
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("tier-mismatched market reveal rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));

    // (d) out-of-range slot
    let bad = VisibleEvent::ChanceRevealed {
        tier: *tier,
        slot: Some(9),
        card: *card,
        visible_to: *visible_to,
    };
    let err = build_with(&observation, &[game_started(2), bad])
        .expect_err("bad-slot market reveal rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index: 1, .. }
    ));
}

// ---------------------------------------------------------------------------
// Ruleset-driven reserve bounds (C1 fix-forward P1)
// ---------------------------------------------------------------------------

#[test]
fn ruleset_max_reserved_two_rejects_third_reserve() {
    let mut ruleset = Ruleset::base_v1();
    ruleset.max_reserved = 2;
    let (mut state, _setup) = FullState::new(GameConfig {
        player_count: 2,
        seed: 1,
        ruleset,
    })
    .expect("setup");
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rm(Tier::One, 1)),
            (0, rm(Tier::One, 2)), // P0 second reserve: exactly at the cap
        ],
    );
    let observation = state.observation(PlayerId(0));
    let mut history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    // Append a synthetic third reserve for P0 by reusing its last reserve event.
    let last_p0 = history
        .iter()
        .rposition(|e| {
            matches!(
                e,
                VisibleEvent::CardReserved {
                    player: PlayerId(0),
                    ..
                }
            )
        })
        .expect("P0 reserve event");
    let extra = history[last_p0].clone();
    history.push(extra);
    let err = build_information_set_v1(ruleset, &observation, &history)
        .expect_err("third reserve with max_reserved=2 rejected");
    assert!(matches!(
        err,
        BeliefError::MalformedHistory { index, .. } if index == history.len() - 1
    ));
}

#[test]
fn ruleset_max_reserved_four_accepts_fourth_reserve() {
    let mut ruleset = Ruleset::base_v1();
    ruleset.max_reserved = 4;
    let (mut state, _setup) = FullState::new(GameConfig {
        player_count: 2,
        seed: 1,
        ruleset,
    })
    .expect("setup");
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rm(Tier::One, 1)),
            (0, rm(Tier::One, 2)),
            (1, rm(Tier::One, 3)),
            (0, rm(Tier::Two, 0)),
            (1, rm(Tier::Two, 1)),
            (0, rm(Tier::Two, 2)), // P0 fourth reserve: legal at max 4
            (1, rm(Tier::Two, 3)),
        ],
    );
    let observation = state.observation(PlayerId(0));
    let history = visible_events(&state.log, Audience::Player(PlayerId(0)));
    let info = build_information_set_v1(ruleset, &observation, &history)
        .expect("four reserves accepted at max_reserved=4");
    assert_eq!(info.reserved_knowledge()[0].slots.len(), 4);
    for slot in &info.reserved_knowledge()[0].slots {
        assert!(matches!(
            slot,
            ReservedKnowledgeV1::Known {
                from_deck: false,
                ..
            }
        ));
    }
}
