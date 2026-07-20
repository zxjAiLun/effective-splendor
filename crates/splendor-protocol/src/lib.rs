//! NDJSON agent protocol (v0.2).
//!
//! One JSON object per line. Transport (stdio / TCP / WS) is independent of
//! the schema.
//!
//! The protocol boundary is deliberate:
//! - server messages carry `ObservationHash` or a `RulesetFingerprint`, never
//!   `FullStateHash`;
//! - server-side recipient and actor identities have separate names;
//! - request correlation and recipient scope are required by the types;
//! - client messages use a separate request metadata type and cannot claim a
//!   seat, server sequence, or state hash;
//! - event messages accept `VisibleEvent`, never `RefereeEvent`.

use serde::{Deserialize, Serialize};
use splendor_core::{
    visible_events, Action, Audience, FullState, GameConfig, GameResult, Observation,
    ObservationHash, PlayerId, RefereeEvent, RulesetFingerprint, VisibleEvent, ENGINE_VERSION,
};

pub const PROTOCOL_VERSION: &str = "0.2";

/// Server-owned fields shared by genuinely broadcast server messages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerMeta {
    pub protocol_version: String,
    pub game_id: String,
    /// Server-monotonic sequence number for this game.
    pub server_seq: u64,
}

impl ServerMeta {
    pub fn new(game_id: impl Into<String>, server_seq: u64) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION.to_string(),
            game_id: game_id.into(),
            server_seq,
        }
    }
}

/// Server metadata for a message addressed to one player.
///
/// The recipient is intentionally not optional: a per-player message cannot
/// be constructed as an unscoped broadcast.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecipientMeta {
    #[serde(flatten)]
    pub server: ServerMeta,
    pub recipient_player_id: u8,
}

impl RecipientMeta {
    pub fn new(game_id: impl Into<String>, server_seq: u64, player: PlayerId) -> Self {
        Self {
            server: ServerMeta::new(game_id, server_seq),
            recipient_player_id: player.0,
        }
    }

    pub fn player_id(&self) -> PlayerId {
        PlayerId(self.recipient_player_id)
    }
}

/// Metadata for a player-scoped observation. The observation identity is
/// required wherever the observation itself crosses the wire.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObservationMeta {
    #[serde(flatten)]
    pub recipient: RecipientMeta,
    pub observation_hash: ObservationHash,
}

impl ObservationMeta {
    pub fn new(
        game_id: impl Into<String>,
        server_seq: u64,
        player: PlayerId,
        observation_hash: ObservationHash,
    ) -> Self {
        Self {
            recipient: RecipientMeta::new(game_id, server_seq, player),
            observation_hash,
        }
    }
}

/// Metadata for a player-scoped action request. Both correlation and
/// observation identity are mandatory at the type and wire level.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestMeta {
    #[serde(flatten)]
    pub recipient: RecipientMeta,
    pub request_id: u64,
    pub observation_hash: ObservationHash,
}

impl RequestMeta {
    pub fn new(
        game_id: impl Into<String>,
        server_seq: u64,
        player: PlayerId,
        request_id: u64,
        observation_hash: ObservationHash,
    ) -> Self {
        Self {
            recipient: RecipientMeta::new(game_id, server_seq, player),
            request_id,
            observation_hash,
        }
    }
}

/// Client-owned envelope. It deliberately has no player/seat, server
/// sequence, observation hash, or full-state hash field. The arena binds a
/// connection to a seat and validates the game/request identifiers
/// server-side.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientMeta {
    pub protocol_version: String,
    pub game_id: String,
}

impl ClientMeta {
    pub fn new(game_id: impl Into<String>) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION.to_string(),
            game_id: game_id.into(),
        }
    }
}

/// Client metadata for a response to a specific server action request.
/// `request_id` is required and cannot be omitted from a client action.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientRequestMeta {
    #[serde(flatten)]
    pub client: ClientMeta,
    pub request_id: u64,
}

impl ClientRequestMeta {
    pub fn new(game_id: impl Into<String>, request_id: u64) -> Self {
        Self {
            client: ClientMeta::new(game_id),
            request_id,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    Hello {
        #[serde(flatten)]
        meta: ServerMeta,
        engine_version: String,
        ruleset: String,
        catalog_version: String,
        /// Ruleset/catalog fingerprint. This is not a game-state hash.
        ruleset_fingerprint: RulesetFingerprint,
    },
    GameStart {
        #[serde(flatten)]
        meta: RecipientMeta,
        player_count: u8,
        seed_commitment: String,
    },
    Observation {
        #[serde(flatten)]
        meta: ObservationMeta,
        observation: Observation,
    },
    RequestAction {
        #[serde(flatten)]
        meta: RequestMeta,
        deadline_ms: u64,
        legal_actions: Vec<Action>,
    },
    ActionApplied {
        #[serde(flatten)]
        meta: RecipientMeta,
        /// The single, unambiguous public actor field.
        actor_player_id: u8,
        action: Action,
    },
    /// One already-projected event. The protocol cannot be constructed from a
    /// referee event, so redaction is required before crossing this boundary.
    Event {
        #[serde(flatten)]
        meta: RecipientMeta,
        event: VisibleEvent,
    },
    GameEnd {
        #[serde(flatten)]
        meta: RecipientMeta,
        result: GameResult,
    },
    Error {
        #[serde(flatten)]
        meta: RecipientMeta,
        message: String,
    },
    Ping {
        #[serde(flatten)]
        meta: RecipientMeta,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    Hello {
        #[serde(flatten)]
        meta: ClientMeta,
        agent_name: String,
        agent_version: String,
    },
    Action {
        #[serde(flatten)]
        meta: ClientRequestMeta,
        /// The action proposed for the server-bound connection's seat. Seat
        /// binding is never supplied by the client.
        action: Action,
    },
    Pong {
        #[serde(flatten)]
        meta: ClientMeta,
    },
}

impl ServerMessage {
    pub fn hello(
        game_id: &str,
        ruleset: &str,
        catalog_version: &str,
        fingerprint: RulesetFingerprint,
    ) -> Self {
        ServerMessage::Hello {
            meta: ServerMeta::new(game_id, 0),
            engine_version: ENGINE_VERSION.to_string(),
            ruleset: ruleset.to_string(),
            catalog_version: catalog_version.to_string(),
            ruleset_fingerprint: fingerprint,
        }
    }

    pub fn event(meta: RecipientMeta, event: VisibleEvent) -> Self {
        ServerMessage::Event { meta, event }
    }

    pub fn to_json_line(&self) -> serde_json::Result<String> {
        serde_json::to_string(self)
    }

    pub fn protocol_version(&self) -> &str {
        match self {
            ServerMessage::Hello { meta, .. } => &meta.protocol_version,
            ServerMessage::GameStart { meta, .. }
            | ServerMessage::ActionApplied { meta, .. }
            | ServerMessage::Event { meta, .. }
            | ServerMessage::GameEnd { meta, .. }
            | ServerMessage::Error { meta, .. }
            | ServerMessage::Ping { meta } => &meta.server.protocol_version,
            ServerMessage::Observation { meta, .. } => &meta.recipient.server.protocol_version,
            ServerMessage::RequestAction { meta, .. } => &meta.recipient.server.protocol_version,
        }
    }
}

impl ClientMessage {
    pub fn parse_line(line: &str) -> serde_json::Result<Self> {
        serde_json::from_str(line)
    }
}

/// Build a complete player-scoped server transcript. This is shared by the
/// committed fixture generator and the wire regression tests, so a fixture is
/// compared against current serialization rather than merely parsed by it.
pub fn server_transcript(
    game_id: &str,
    state: &FullState,
    events: &[RefereeEvent],
    recipient: PlayerId,
    audience: Audience,
    request_id: u64,
) -> String {
    let observation = state.observation(recipient);
    let observation_hash = splendor_core::observation_hash(&observation);
    let mut messages = vec![
        ServerMessage::hello(
            game_id,
            state.ruleset.id.0,
            state.ruleset.catalog_version,
            splendor_core::ruleset_fingerprint(&state.ruleset),
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

    messages
        .iter()
        .map(|message| message.to_json_line().expect("protocol serialization"))
        .collect::<Vec<_>>()
        .join("\n")
        + "\n"
}

/// Deterministic normal-game fixture transcript.
pub fn normal_golden_transcript() -> String {
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

/// Deterministic blind-reserve fixture transcript for a selected player.
pub fn blind_reserve_transcript(audience: Audience) -> String {
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

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{observation_hash, ruleset_fingerprint, FullState, GameConfig};

    #[test]
    fn request_action_roundtrip() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let legal = state.legal_actions();
        let hash = observation_hash(&state.observation(PlayerId(0)));
        let msg = ServerMessage::RequestAction {
            meta: RequestMeta::new("g1", 1, PlayerId(0), 9, hash),
            deadline_ms: 3000,
            legal_actions: legal.clone(),
        };
        let line = msg.to_json_line().unwrap();
        assert!(line.contains("request_action"));
        assert!(
            line.contains("take_tokens") || line.contains("buy_market") || line.contains("reserve")
        );
        let parsed: ServerMessage = serde_json::from_str(&line).unwrap();
        match parsed {
            ServerMessage::RequestAction {
                legal_actions,
                meta,
                ..
            } => {
                assert_eq!(legal_actions, legal);
                assert_eq!(meta.request_id, 9);
                assert_eq!(meta.recipient.recipient_player_id, 0);
            }
            _ => panic!("wrong type"),
        }
    }

    #[test]
    fn hello_carries_catalog_and_typed_fingerprint() {
        let state = GameConfig::default().ruleset;
        let msg = ServerMessage::hello(
            "g1",
            splendor_core::RULESET_BASE_V1.0,
            splendor_core::CATALOG_VERSION,
            ruleset_fingerprint(&state),
        );
        let line = msg.to_json_line().unwrap();
        assert!(line.contains("catalog_version"));
        assert!(line.contains("ruleset_fingerprint"));
        let parsed: ServerMessage = serde_json::from_str(&line).unwrap();
        assert!(matches!(parsed, ServerMessage::Hello { .. }));
    }

    #[test]
    fn action_applied_has_single_actor_field() {
        let msg = ServerMessage::ActionApplied {
            meta: RecipientMeta::new("g1", 3, PlayerId(1)),
            actor_player_id: 0,
            action: Action::Pass,
        };
        let line = msg.to_json_line().unwrap();
        assert_eq!(line.matches("actor_player_id").count(), 1);
        assert!(!line.contains("\"player_id\""));
        assert!(line.contains("\"recipient_player_id\":1"));
    }

    #[test]
    fn client_action_has_no_authorizing_identity_or_server_hash() {
        let message = ClientMessage::Action {
            meta: ClientRequestMeta::new("g1", 9),
            action: Action::Pass,
        };
        let line = serde_json::to_string(&message).unwrap();
        assert!(!line.contains("player_id"));
        assert!(!line.contains("server_seq"));
        assert!(!line.contains("observation_hash"));
        assert!(line.contains("request_id"));
    }

    #[test]
    fn request_id_is_required_on_both_request_and_action() {
        let request_without_id = r#"{"type":"request_action","protocol_version":"0.2","game_id":"g1","server_seq":1,"recipient_player_id":0,"observation_hash":"hash","deadline_ms":1000,"legal_actions":[{"type":"pass"}]}"#;
        assert!(serde_json::from_str::<ServerMessage>(request_without_id).is_err());

        let action_without_id =
            r#"{"type":"action","protocol_version":"0.2","game_id":"g1","action":{"type":"pass"}}"#;
        assert!(serde_json::from_str::<ClientMessage>(action_without_id).is_err());
    }

    #[test]
    fn player_event_requires_recipient() {
        let line = ServerMessage::event(
            RecipientMeta::new("g1", 4, PlayerId(1)),
            VisibleEvent::TurnAdvanced {
                next_player: PlayerId(0),
            },
        )
        .to_json_line()
        .unwrap();
        assert!(line.contains("\"recipient_player_id\":1"));
        assert!(serde_json::from_str::<ServerMessage>(
            r#"{"type":"event","protocol_version":"0.2","game_id":"g1","server_seq":4,"event":{"type":"turn_advanced","next_player":0}}"#
        )
        .is_err());
    }
}
