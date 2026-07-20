//! PR-01 gate tests: the opponent's full NDJSON transcript must not leak
//! blind-reserved card identities, and the protocol must never carry a
//! `FullStateHash`.

use splendor_core::{
    full_state_hash, observation_hash, ruleset_fingerprint, visible_events, Action, Audience,
    ChanceEvent, FullState, GameConfig, PlayerId, RefereeEvent, Ruleset, Visibility, VisibleEvent,
};
use splendor_protocol::{
    to_ndjson, ClientMessage, ClientRequestMeta, ObservationMeta, RecipientMeta, RequestMeta,
    ServerMessage, PROTOCOL_VERSION,
};

fn reserve_deck(state: &mut FullState) {
    let act = Action::ReserveDeck {
        tier: splendor_core::Tier::One,
    };
    assert!(
        state.legal_actions().contains(&act),
        "reserve deck expected legal at start"
    );
    state.apply(act).expect("apply reserve");
}

fn swap_blind_card_and_referee_log(state: &mut FullState) {
    let other = state.decks[0][0];
    let original = state.players[0].reserved[0].card;
    assert_ne!(other, original);
    state.players[0].reserved[0].card = other;
    state.decks[0][0] = original;

    // Keep the second referee world internally consistent too. This makes the
    // transcript test sensitive to an accidental projection of the raw card.
    for event in &mut state.log {
        match event {
            RefereeEvent::CardReserved {
                player: PlayerId(0),
                card,
                public_identity: false,
                ..
            } => *card = other,
            RefereeEvent::Chance(ChanceEvent::CardRevealed {
                card,
                slot: None,
                visible_to: Visibility::Player(PlayerId(0)),
                ..
            }) => *card = other,
            _ => {}
        }
    }
}

/// Pure wire transcript builder used by both golden comparisons and the full
/// two-world redaction test. It accepts referee data only in this test layer;
/// the production protocol crate sees only the resulting wire DTOs.
fn server_transcript(
    game_id: &str,
    state: &FullState,
    events: &[RefereeEvent],
    recipient: PlayerId,
    audience: Audience,
    request_id: u64,
) -> String {
    let observation = state.observation(recipient);
    let observation_hash = observation_hash(&observation);
    let mut messages = vec![
        ServerMessage::hello(
            game_id,
            state.ruleset.id.0,
            state.ruleset.catalog_version,
            ruleset_fingerprint(&state.ruleset),
        ),
        ServerMessage::GameStart {
            meta: RecipientMeta::new(game_id, 1, recipient),
            player_count: state.player_count(),
            seed_commitment: format!("fixture-commitment-{game_id}"),
        },
        ServerMessage::Observation {
            meta: ObservationMeta::new(game_id, 2, recipient, observation_hash.clone()),
            observation,
        },
    ];

    for event in visible_events(events, audience) {
        let server_seq = messages.len() as u64;
        messages.push(ServerMessage::event(
            RecipientMeta::new(game_id, server_seq, recipient),
            event,
        ));
    }

    let server_seq = messages.len() as u64;
    messages.push(ServerMessage::RequestAction {
        meta: RequestMeta::new(game_id, server_seq, recipient, request_id, observation_hash),
        deadline_ms: 1000,
        legal_actions: state.legal_actions(),
    });

    to_ndjson(&messages)
}

fn normal_golden_transcript() -> String {
    let (state, setup) = FullState::new(GameConfig::default()).expect("fixture setup");
    server_transcript(
        "golden-normal",
        &state,
        &setup.events,
        PlayerId(0),
        Audience::Player(PlayerId(0)),
        1,
    )
}

fn blind_reserve_transcript(audience: Audience) -> String {
    let recipient = match audience {
        Audience::Player(player) => player,
        _ => panic!("blind fixture requires a player audience"),
    };
    let (mut state, setup) = FullState::new(GameConfig {
        seed: 7,
        ..Default::default()
    })
    .expect("fixture setup");
    let reserve = state
        .legal_actions()
        .into_iter()
        .find(|action| matches!(action, Action::ReserveDeck { .. }))
        .expect("reserve deck is legal at start");
    let step = state.apply(reserve).expect("apply reserve");
    let mut events = setup.events;
    events.extend(step.events);

    server_transcript("golden-blind", &state, &events, recipient, audience, 2)
}

/// Two states differing ONLY in a blind-reserved CardId must produce byte-identical
/// visible transcripts for the opponent.
#[test]
fn blind_reserve_transcript_is_identical_for_opponent_worlds() {
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

    reserve_deck(&mut a);
    reserve_deck(&mut b);

    // Swap P0's blind card in b for another tier-1 card still in the deck.
    swap_blind_card_and_referee_log(&mut b);

    let ta: Vec<VisibleEvent> = visible_events(&a.log, Audience::Player(PlayerId(1)));
    let tb: Vec<VisibleEvent> = visible_events(&b.log, Audience::Player(PlayerId(1)));
    assert_eq!(
        serde_json::to_string(&ta).unwrap(),
        serde_json::to_string(&tb).unwrap(),
        "opponent transcript must not depend on P0's blind card identity"
    );
}

/// The owner's transcript DOES include the blind card identity (visble to
/// `Audience::Player(owner)`), and it matches the actual reserved card.
#[test]
fn blind_reserve_transcript_differs_for_owner() {
    let (mut state, _) = FullState::new(GameConfig {
        seed: 1234,
        ..Default::default()
    })
    .unwrap();
    reserve_deck(&mut state);

    let reserved_card = state.players[0].reserved[0].card;
    let transcript: Vec<VisibleEvent> = visible_events(&state.log, Audience::Player(PlayerId(0)));

    // The owner's `CardReserved` must expose the real (non-null) card id.
    let owner_card = transcript.iter().find_map(|ev| match ev {
        VisibleEvent::CardReserved { player, card, .. } if *player == PlayerId(0) => *card,
        _ => None,
    });
    assert_eq!(
        owner_card,
        Some(reserved_card),
        "owner must see their own blind reserved card identity"
    );

    // And the public setup (market) cards are visible too — sanity.
    assert!(transcript
        .iter()
        .any(|ev| matches!(ev, VisibleEvent::SetupDealt { .. })));

    // The setup seed is referee-only because it can reconstruct hidden deck
    // order. It must not reappear through the visible event projection.
    let wire = serde_json::to_string(&transcript).unwrap();
    assert!(!wire.contains("\"seed\""));
}

/// Full hash differs between the two blind worlds, but the opponent's observation
/// hash matches.
#[test]
fn full_hash_differs_but_opponent_observation_hash_matches() {
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
    reserve_deck(&mut a);
    reserve_deck(&mut b);

    swap_blind_card_and_referee_log(&mut b);

    assert_ne!(
        full_state_hash(&a),
        full_state_hash(&b),
        "referee full hash must differ"
    );
    let ha = observation_hash(&a.observation(PlayerId(1)));
    let hb = observation_hash(&b.observation(PlayerId(1)));
    assert_eq!(
        ha, hb,
        "opponent observation hash must match despite hidden diff"
    );
}

/// A PUBLIC (market) reserve changes the hash; a blind (deck) reserve does not
/// change the *opponent's* observation hash.
#[test]
fn public_reserved_card_changes_observation_hash() {
    let (mut a, _) = FullState::new(GameConfig::default()).unwrap();
    let before = observation_hash(&a.observation(PlayerId(1)));

    // Reserve a market card (public identity).
    let mkt = a
        .legal_actions()
        .into_iter()
        .find(|x| matches!(x, Action::ReserveMarket { .. }))
        .expect("market reserve legal");
    a.apply(mkt).unwrap();
    let after = observation_hash(&a.observation(PlayerId(1)));
    assert_ne!(
        before, after,
        "a public reserve must change the opponent observation hash"
    );
}

/// No serialized ServerMessage may contain a full state hash. We generate a full
/// request/observation exchange and grep the lines for the referee hash value.
#[test]
fn protocol_never_serializes_full_state_hash() {
    let (state, _) = FullState::new(GameConfig::default()).unwrap();
    let full = full_state_hash(&state).as_str().to_string();
    let game_id = "leak-test";

    let obs = state.observation(PlayerId(0));
    let msg = ServerMessage::Observation {
        meta: ObservationMeta::new(game_id, 1, PlayerId(0), observation_hash(&obs)),
        observation: obs,
    };
    let line = msg.to_json_line().unwrap();
    assert!(
        !line.contains(&full),
        "server message must not embed the full state hash"
    );
    // And the protocol version is 0.2.
    assert!(line.contains("\"protocol_version\":\"0.2\""));
}

/// `ActionApplied` has exactly one actor field and no ambiguous `player_id`.
#[test]
fn action_applied_contains_one_actor_field() {
    let msg = ServerMessage::ActionApplied {
        meta: RecipientMeta::new("g1", 3, PlayerId(1)),
        actor_player_id: 0,
        action: Action::Pass,
    };
    let line = msg.to_json_line().unwrap();
    assert_eq!(line.matches("actor_player_id").count(), 1);
    // The authoritative actor is `actor_player_id`; no separate `player_id` field.
    assert!(!line.contains("\"player_id\""));
}

/// A client `Action` cannot claim a player identity: the schema has no
/// authorizing `player_id`, and any hostile claim is silently dropped (the
/// runner, not the client, binds the seat in PR-04).
#[test]
fn client_action_cannot_claim_player_identity() {
    // Valid action message echoes only `recipient_player_id`, no `player_id`.
    let ok = ClientMessage::Action {
        meta: ClientRequestMeta::new("g1", 3),
        action: Action::Pass,
    };
    let line = serde_json::to_string(&ok).unwrap();
    // No client-side seat, server sequence, or state-hash field exists.
    assert!(!line.contains("player_id"));
    assert!(!line.contains("server_seq"));
    assert!(!line.contains("state_hash"));

    // A hostile payload attempting to assert another seat must be dropped, not
    // honored. serde ignores unknown server-owned fields, so the claim has no
    // place to land and the bound seat is unaffected.
    let hostile = r#"{"type":"action","protocol_version":"0.2","game_id":"g1","request_id":3,"server_seq":99,"recipient_player_id":0,"player_id":7,"observation_hash":"full","action":{"type":"pass"}}"#;
    let parsed: ClientMessage = serde_json::from_str(hostile).expect("unknown fields ignored");
    match parsed {
        ClientMessage::Action { meta, action } => {
            assert_eq!(meta.request_id, 3);
            assert_eq!(action, Action::Pass);
        }
        _ => panic!("wrong variant"),
    }
}

/// Observation hashes must include the ruleset scope even when the visible
/// board and private cards are otherwise identical.
#[test]
fn observation_hash_includes_ruleset_scope() {
    let (a, _) = FullState::new(GameConfig::default()).unwrap();
    let mut alternate = Ruleset::base_v1();
    alternate.prestige_to_end += 1;
    let (b, _) = FullState::new(GameConfig {
        ruleset: alternate,
        ..Default::default()
    })
    .unwrap();

    let oa = a.observation(PlayerId(0));
    let ob = b.observation(PlayerId(0));
    assert_eq!(oa.public, ob.public);
    assert_ne!(oa.ruleset_fingerprint, ob.ruleset_fingerprint);
    assert_ne!(observation_hash(&oa), observation_hash(&ob));
}

/// The committed fixtures are wire-regression locks: current serialization
/// must produce exactly the checked-in bytes, not merely parse them.
#[test]
fn protocol_golden_transcript_matches_generated_wire() {
    let normal = normal_golden_transcript();
    assert_eq!(
        normal,
        include_str!("../../../fixtures/protocol/v0.2/normal-game.ndjson"),
        "normal protocol fixture is stale; run `splendor gen-fixtures` after intentional review"
    );
    let blind = blind_reserve_transcript(Audience::Player(PlayerId(1)));
    assert_eq!(
        blind,
        include_str!("../../../fixtures/protocol/v0.2/blind-reserve.ndjson"),
        "blind protocol fixture is stale; run `splendor gen-fixtures` after intentional review"
    );

    for (name, raw) in [("normal", normal.as_str()), ("blind", blind.as_str())] {
        for line in raw.lines().filter(|line| !line.trim().is_empty()) {
            let msg: ServerMessage = serde_json::from_str(line)
                .unwrap_or_else(|e| panic!("{name} fixture line failed: {e}\n{line}"));
            assert_eq!(msg.protocol_version(), PROTOCOL_VERSION);
            if let ServerMessage::GameStart { .. } = msg {
                assert!(!line.contains("your_player_id"));
            }
        }
    }

    // Blind-reserve transcript (opponent view) must NOT reveal a card id in the
    // wrapped card_reserved / chance_revealed redacted events.
    let mut saw_redacted = false;
    for line in blind.lines().filter(|line| !line.trim().is_empty()) {
        let message: ServerMessage = serde_json::from_str(line).unwrap();
        if let ServerMessage::Event {
            event:
                VisibleEvent::CardReserved {
                    card,
                    public_identity: false,
                    ..
                }
                | VisibleEvent::ChanceRevealed {
                    card, slot: None, ..
                },
            ..
        } = message
        {
            assert_eq!(card, None, "opponent blind transcript leaked: {line}");
            saw_redacted = true;
        }
    }
    assert!(saw_redacted, "expected at least one redacted blind event");
}

/// The full player transcript remains identical when only an opponent's blind
/// card identity changes. This covers metadata, observation hash, request ID,
/// legal actions, sequence numbers, and projected events together.
#[test]
fn blind_reserve_full_server_transcript_is_identical_for_opponent_worlds() {
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
    reserve_deck(&mut a);
    reserve_deck(&mut b);
    swap_blind_card_and_referee_log(&mut b);

    let ta = server_transcript(
        "blind-world",
        &a,
        &a.log,
        PlayerId(1),
        Audience::Player(PlayerId(1)),
        2,
    );
    let tb = server_transcript(
        "blind-world",
        &b,
        &b.log,
        PlayerId(1),
        Audience::Player(PlayerId(1)),
        2,
    );
    assert_eq!(ta, tb, "opponent wire transcript must be world-independent");

    for line in ta.lines().filter(|line| !line.trim().is_empty()) {
        let msg: ServerMessage = serde_json::from_str(line).unwrap();
        match msg {
            ServerMessage::Hello { .. } => {}
            ServerMessage::GameStart { meta, .. }
            | ServerMessage::ActionApplied { meta, .. }
            | ServerMessage::Event { meta, .. }
            | ServerMessage::GameEnd { meta, .. }
            | ServerMessage::Error { meta, .. }
            | ServerMessage::Ping { meta } => {
                assert_eq!(meta.recipient_player_id, 1)
            }
            ServerMessage::Observation { meta, .. } => {
                assert_eq!(meta.recipient.recipient_player_id, 1)
            }
            ServerMessage::RequestAction { meta, .. } => {
                assert_eq!(meta.recipient.recipient_player_id, 1);
                assert_eq!(meta.request_id, 2);
            }
        }
    }
}
