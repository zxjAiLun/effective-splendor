//! Commit-1 gate: the arena-facing strict parsers reject unknown fields (at any
//! depth), trailing JSON, wrong message types, and non-objects, while still
//! accepting every canonical v0.5 message.

use splendor_core::{
    observation_hash, ruleset_fingerprint, Action, FullState, GameConfig, PlayerId,
};
use splendor_protocol::{
    parse_client_line, parse_server_line, ClientMessage, ClientMeta, ClientRequestMeta,
    ObservationMeta, ProtocolParseError, RecipientMeta, RequestMeta, ServerMessage,
    PROTOCOL_VERSION,
};

fn client_hello() -> String {
    serde_json::to_string(&ClientMessage::Hello {
        meta: ClientMeta::new("g1"),
        agent_name: "random".to_string(),
        agent_version: "0.1.0".to_string(),
    })
    .unwrap()
}

fn client_action() -> String {
    serde_json::to_string(&ClientMessage::Action {
        meta: ClientRequestMeta::new("g1", 1),
        action: Action::Pass,
    })
    .unwrap()
}

// ---- Unknown-field rejection --------------------------------------------------

#[test]
fn unknown_client_hello_field_is_rejected() {
    let line = r#"{"type":"hello","protocol_version":"0.5","game_id":"g1","agent_name":"a","agent_version":"1","extra":true}"#;
    match parse_client_line(line) {
        Err(ProtocolParseError::UnknownField { path, message_type }) => {
            assert_eq!(path, "extra");
            assert_eq!(message_type, "hello");
        }
        other => panic!("expected UnknownField, got {other:?}"),
    }
}

#[test]
fn unknown_client_action_field_is_rejected() {
    // Unknown top-level field on an action envelope.
    let line = r#"{"type":"action","protocol_version":"0.5","game_id":"g1","request_id":1,"action":{"type":"pass"},"hint":"cheat"}"#;
    match parse_client_line(line) {
        Err(ProtocolParseError::UnknownField { path, .. }) => assert_eq!(path, "hint"),
        other => panic!("expected UnknownField, got {other:?}"),
    }
}

#[test]
fn unknown_nested_action_field_is_rejected() {
    // Depth matters: the payload `Action` must also reject unknown fields even
    // though the tag+flatten enum buffers it through serde `Content`.
    let line = r#"{"type":"action","protocol_version":"0.5","game_id":"g1","request_id":1,"action":{"type":"pass","sneaky":9}}"#;
    match parse_client_line(line) {
        Err(ProtocolParseError::UnknownField { path, .. }) => assert_eq!(path, "action.sneaky"),
        other => panic!("expected nested UnknownField, got {other:?}"),
    }
}

#[test]
fn unknown_client_meta_field_is_rejected() {
    // A field injected into the flattened client metadata region.
    let line = r#"{"type":"pong","protocol_version":"0.5","game_id":"g1","server_seq":7}"#;
    match parse_client_line(line) {
        Err(ProtocolParseError::UnknownField { path, .. }) => assert_eq!(path, "server_seq"),
        other => panic!("expected UnknownField, got {other:?}"),
    }
}

#[test]
fn client_cannot_claim_seat_via_unknown_field() {
    // A hostile seat claim is an unknown field, not a silently-dropped hint.
    let line = r#"{"type":"action","protocol_version":"0.5","game_id":"g1","request_id":1,"player_id":3,"action":{"type":"pass"}}"#;
    match parse_client_line(line) {
        Err(ProtocolParseError::UnknownField { path, .. }) => assert_eq!(path, "player_id"),
        other => panic!("expected UnknownField, got {other:?}"),
    }
}

// ---- Trailing / structural rejection -----------------------------------------

#[test]
fn trailing_json_is_rejected() {
    let line = r#"{"type":"pong","protocol_version":"0.5","game_id":"g1"} {"type":"pong","protocol_version":"0.5","game_id":"g1"}"#;
    assert!(matches!(
        parse_client_line(line),
        Err(ProtocolParseError::TrailingData)
    ));
}

#[test]
fn trailing_garbage_after_object_is_rejected() {
    let line = r#"{"type":"pong","protocol_version":"0.5","game_id":"g1"}garbage"#;
    assert!(matches!(
        parse_client_line(line),
        Err(ProtocolParseError::TrailingData)
    ));
}

#[test]
fn empty_line_is_rejected() {
    assert!(matches!(
        parse_client_line("   "),
        Err(ProtocolParseError::Empty)
    ));
}

#[test]
fn non_object_line_is_rejected() {
    assert!(matches!(
        parse_client_line("[1,2,3]"),
        Err(ProtocolParseError::NotAnObject)
    ));
}

// ---- Message-type classification ---------------------------------------------

#[test]
fn wrong_message_type_is_rejected() {
    // A server-only type submitted to the client parser.
    let line = r#"{"type":"request_action","protocol_version":"0.5","game_id":"g1","server_seq":1,"recipient_player_id":0,"request_id":1,"observation_hash":"h","deadline_ms":10,"legal_actions":[]}"#;
    match parse_client_line(line) {
        Err(ProtocolParseError::WrongMessageType { found }) => assert_eq!(found, "request_action"),
        other => panic!("expected WrongMessageType, got {other:?}"),
    }
    // And a client-only type submitted to the server parser.
    match parse_server_line(&client_action()) {
        Err(ProtocolParseError::WrongMessageType { found }) => assert_eq!(found, "action"),
        other => panic!("expected WrongMessageType, got {other:?}"),
    }
}

#[test]
fn unknown_message_type_is_rejected() {
    let line = r#"{"type":"teleport","protocol_version":"0.5","game_id":"g1"}"#;
    match parse_client_line(line) {
        Err(ProtocolParseError::WrongMessageType { found }) => assert_eq!(found, "teleport"),
        other => panic!("expected WrongMessageType, got {other:?}"),
    }
}

// ---- Positive golden acceptance ----------------------------------------------

#[test]
fn strict_parser_accepts_v05_golden_messages() {
    // Every server message type, constructed canonically, must parse cleanly.
    let (state, _) = FullState::new(GameConfig::default()).unwrap();
    let obs = state.observation(PlayerId(0));
    let obs_hash = observation_hash(&obs);
    let fingerprint = ruleset_fingerprint(&state.ruleset);

    let server_messages = vec![
        ServerMessage::hello(
            "g1",
            state.ruleset.id.0,
            state.ruleset.catalog_version,
            fingerprint,
        ),
        ServerMessage::GameStart {
            meta: RecipientMeta::new("g1", 1, PlayerId(0)),
            player_count: 2,
            seed_commitment: "0".repeat(64),
        },
        ServerMessage::Observation {
            meta: ObservationMeta::new("g1", 2, PlayerId(0), obs_hash.clone()),
            observation: obs,
        },
        ServerMessage::RequestAction {
            meta: RequestMeta::new("g1", 3, PlayerId(0), 1, obs_hash),
            deadline_ms: 1000,
            legal_actions: state.legal_actions(),
        },
        ServerMessage::ActionApplied {
            meta: RecipientMeta::new("g1", 4, PlayerId(1)),
            actor_player_id: 0,
            action: Action::Pass,
        },
        ServerMessage::Error {
            meta: RecipientMeta::new("g1", 5, PlayerId(0)),
            message: "boom".to_string(),
        },
        ServerMessage::Ping {
            meta: RecipientMeta::new("g1", 6, PlayerId(0)),
        },
    ];
    for message in &server_messages {
        let line = message.to_json_line().unwrap();
        let parsed = parse_server_line(&line)
            .unwrap_or_else(|e| panic!("server golden rejected: {e}\n{line}"));
        assert_eq!(parsed.protocol_version(), PROTOCOL_VERSION);
        // The client parser must reject a server line as a wrong type unless it
        // is the shared `hello` tag.
        let client = parse_client_line(&line);
        if matches!(message, ServerMessage::Hello { .. }) {
            // `hello` is a shared tag; it fails on unknown server-only fields,
            // never as a wrong type.
            assert!(!matches!(
                client,
                Err(ProtocolParseError::WrongMessageType { .. })
            ));
        } else {
            assert!(matches!(
                client,
                Err(ProtocolParseError::WrongMessageType { .. })
            ));
        }
    }

    // Every client message type must parse cleanly too.
    for line in [client_hello(), client_action()] {
        parse_client_line(&line).unwrap_or_else(|e| panic!("client golden rejected: {e}\n{line}"));
    }
    let pong = r#"{"type":"pong","protocol_version":"0.5","game_id":"g1"}"#;
    assert!(matches!(
        parse_client_line(pong).unwrap(),
        ClientMessage::Pong { .. }
    ));
}

#[test]
fn strict_parser_accepts_committed_v05_fixtures() {
    for raw in [
        include_str!("../../../fixtures/protocol/v0.5/normal-game.ndjson"),
        include_str!("../../../fixtures/protocol/v0.5/blind-reserve.ndjson"),
    ] {
        for line in raw.lines().filter(|l| !l.trim().is_empty()) {
            parse_server_line(line)
                .unwrap_or_else(|e| panic!("committed fixture line rejected: {e}\n{line}"));
        }
    }
}

#[test]
fn missing_required_field_is_json_error() {
    // A structurally invalid (missing request_id) action is a Json error, not
    // an unknown-field or wrong-type error.
    let line =
        r#"{"type":"action","protocol_version":"0.5","game_id":"g1","action":{"type":"pass"}}"#;
    assert!(matches!(
        parse_client_line(line),
        Err(ProtocolParseError::Json(_))
    ));
}
