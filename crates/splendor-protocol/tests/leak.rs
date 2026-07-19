//! PR-01 gate tests: the opponent's full NDJSON transcript must not leak
//! blind-reserved card identities, and the protocol must never carry a
//! `FullStateHash`.

use splendor_core::{
    full_state_hash, observation_hash, visible_events, Action, Audience, FullState, GameConfig,
    PlayerId, VisibleEvent,
};
use splendor_protocol::{ClientMessage, Meta, ServerMessage, PROTOCOL_VERSION};

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
    let other = b.decks[0][0];
    let original = b.players[0].reserved[0].card;
    assert_ne!(other, original);
    b.players[0].reserved[0].card = other;
    b.decks[0][0] = original;

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

    let other = b.decks[0][0];
    let original = b.players[0].reserved[0].card;
    b.players[0].reserved[0].card = other;
    b.decks[0][0] = original;

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
        meta: Meta::new(game_id, 1)
            .with_recipient(PlayerId(0))
            .with_observation_hash(observation_hash(&obs)),
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
        meta: Meta::new("g1", 3).with_recipient(PlayerId(1)),
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
        meta: Meta::new("g1", 3).with_recipient(PlayerId(0)),
        action: Action::Pass,
    };
    let line = serde_json::to_string(&ok).unwrap();
    // No bare authorizing `player_id` key; only `recipient_player_id` (echo).
    assert!(!line.contains("\"player_id\""));

    // A hostile payload attempting to assert another seat must be dropped, not
    // honored. serde ignores unknown fields, so it parses — but the claimed
    // identity has no place to land and the bound seat is unaffected.
    let hostile = r#"{"type":"action","protocol_version":"0.2","game_id":"g1","server_seq":3,"recipient_player_id":0,"player_id":7,"action":{"type":"pass"}}"#;
    let parsed: ClientMessage = serde_json::from_str(hostile).expect("unknown fields ignored");
    match parsed {
        ClientMessage::Action { meta, action } => {
            // The hostile `player_id:7` claim leaves no trace; recipient is the
            // runner-assigned value (here None, since the hostile one was the
            // echo field and is not an authorization).
            assert_eq!(meta.recipient_player_id, Some(0));
            assert_eq!(action, Action::Pass);
        }
        _ => panic!("wrong variant"),
    }
}

/// The committed golden transcript matches the parser and contains no blind leak.
#[test]
fn protocol_golden_transcript_matches() {
    // Normal game transcript round-trips as ServerMessages.
    let raw = include_str!("../../../fixtures/protocol/v0.2/normal-game.ndjson");
    for line in raw.lines().filter(|l: &&str| !l.trim().is_empty()) {
        let msg: ServerMessage = serde_json::from_str(line)
            .unwrap_or_else(|e| panic!("normal-game fixture line failed: {e}\n{line}"));
        assert_eq!(msg.protocol_version(), PROTOCOL_VERSION);
    }

    // Blind-reserve transcript (opponent view) must NOT reveal a card id in the
    // card_reserved / chance_revealed redacted lines.
    let blind = include_str!("../../../fixtures/protocol/v0.2/blind-reserve.ndjson");
    let mut saw_redacted = false;
    let blind_lines: Vec<&str> = blind
        .lines()
        .filter(|l: &&str| !l.trim().is_empty())
        .collect();
    for line in blind_lines {
        if line.contains("card_reserved") || line.contains("chance_revealed") {
            assert!(
                line.contains("\"card\":null"),
                "opponent blind transcript must redact card identity: {line}"
            );
            saw_redacted = true;
        }
    }
    assert!(saw_redacted, "expected at least one redacted blind event");
}

// Small helper for the golden test above.
trait ProtocolVersion {
    fn protocol_version(&self) -> &str;
}
impl ProtocolVersion for ServerMessage {
    fn protocol_version(&self) -> &str {
        match self {
            ServerMessage::Hello { meta, .. }
            | ServerMessage::GameStart { meta, .. }
            | ServerMessage::Observation { meta, .. }
            | ServerMessage::RequestAction { meta, .. }
            | ServerMessage::ActionApplied { meta, .. }
            | ServerMessage::GameEnd { meta, .. }
            | ServerMessage::Error { meta, .. }
            | ServerMessage::Ping { meta } => &meta.protocol_version,
        }
    }
}
