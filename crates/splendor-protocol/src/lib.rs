//! NDJSON agent protocol (v0.5).
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
//!
//! # Strict parsing (arena entry points)
//!
//! [`parse_client_line`] and [`parse_server_line`] are the arena-facing parse
//! entry points. Unlike a bare `serde_json::from_str`, they reject:
//! - a `type` tag that is not valid for the direction ([`ProtocolParseError::WrongMessageType`]);
//! - unknown fields at any depth of the envelope, metadata, or payload
//!   ([`ProtocolParseError::UnknownField`]);
//! - trailing bytes after the JSON object ([`ProtocolParseError::TrailingData`]);
//! - non-object or empty lines.
//!
//! Unknown-field rejection is DTO-driven: the line is parsed into the typed
//! message and re-serialized, then compared key-by-key against the original.
//! Any key that survives in the input but not the faithful re-serialization is
//! an unknown field. This is used instead of `serde_ignored` because the
//! internally-tagged (`tag = "type"`) + `#[serde(flatten)]` DTOs buffer their
//! contents through serde's `Content`, which silently drops unknown fields
//! before `serde_ignored` can observe them.

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use splendor_core::{
    Action, GameResult, Observation, ObservationHash, PlayerId, RulesetFingerprint, VisibleEvent,
    ENGINE_VERSION,
};

pub const PROTOCOL_VERSION: &str = "0.5";

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
    /// Valid `type` tags for a client → server line.
    pub const TYPES: &'static [&'static str] = &["hello", "action", "pong"];

    /// Parse a single client line with the strict arena parser. Prefer this
    /// over a bare `serde_json::from_str`; see [`parse_client_line`].
    pub fn parse_line(line: &str) -> Result<Self, ProtocolParseError> {
        parse_client_line(line)
    }
}

impl ServerMessage {
    /// Valid `type` tags for a server → client line.
    pub const TYPES: &'static [&'static str] = &[
        "hello",
        "game_start",
        "observation",
        "request_action",
        "action_applied",
        "event",
        "game_end",
        "error",
        "ping",
    ];
}

/// Structured error classification for the strict parsers. This is
/// deliberately not a single opaque `serde_json::Error`: the arena needs to map
/// a client fault to a specific `AgentFault` category.
#[derive(Debug, thiserror::Error)]
pub enum ProtocolParseError {
    /// The line was empty or whitespace only.
    #[error("empty protocol line")]
    Empty,
    /// The line did not decode to a single JSON object.
    #[error("protocol line is not a JSON object")]
    NotAnObject,
    /// The JSON object had no string `type` tag.
    #[error("protocol line is missing a string `type` tag")]
    MissingType,
    /// The `type` tag is not valid for this direction (client vs server).
    #[error("unexpected message type `{found}` for this direction")]
    WrongMessageType { found: String },
    /// A field was present in the wire object but is not part of the message
    /// schema. `path` is a dotted/indexed path into the object.
    #[error("unknown field `{path}` in `{message_type}` message")]
    UnknownField { message_type: String, path: String },
    /// Bytes remained on the line after the first JSON object.
    #[error("trailing data after JSON object")]
    TrailingData,
    /// The line was syntactically or structurally invalid JSON for the schema.
    #[error("invalid protocol JSON: {0}")]
    Json(#[source] serde_json::Error),
}

/// Strictly parse one client → server NDJSON line.
///
/// Rejects unknown fields (at any depth), trailing data, wrong `type` tags, and
/// non-object lines. `Action` / `Gems` remain strictly parsed. This is the only
/// sanctioned decode path for client input; the arena never calls a bare
/// `serde_json::from_str::<ClientMessage>()`.
pub fn parse_client_line(line: &str) -> Result<ClientMessage, ProtocolParseError> {
    parse_strict_line::<ClientMessage>(line, ClientMessage::TYPES)
}

/// Strictly parse one server → client NDJSON line. Mirrors
/// [`parse_client_line`] for the server direction (used by fixtures and tests
/// that consume server transcripts).
pub fn parse_server_line(line: &str) -> Result<ServerMessage, ProtocolParseError> {
    parse_strict_line::<ServerMessage>(line, ServerMessage::TYPES)
}

fn parse_strict_line<T>(line: &str, valid_types: &[&str]) -> Result<T, ProtocolParseError>
where
    T: DeserializeOwned + Serialize,
{
    if line.trim().is_empty() {
        return Err(ProtocolParseError::Empty);
    }

    // 1. Decode exactly one JSON value and reject anything after it. Using the
    //    streaming deserializer lets us classify trailing bytes distinctly from
    //    ordinary syntax errors.
    let mut de = serde_json::Deserializer::from_str(line);
    let value = Value::deserialize(&mut de).map_err(ProtocolParseError::Json)?;
    de.end().map_err(|_| ProtocolParseError::TrailingData)?;

    // 2. The wire unit is always a single object.
    let object = value.as_object().ok_or(ProtocolParseError::NotAnObject)?;

    // 3. Classify the message type before any schema binding so a mis-directed
    //    (but individually valid) message is a distinct fault.
    let message_type = object
        .get("type")
        .and_then(Value::as_str)
        .ok_or(ProtocolParseError::MissingType)?
        .to_string();
    if !valid_types.contains(&message_type.as_str()) {
        return Err(ProtocolParseError::WrongMessageType {
            found: message_type,
        });
    }

    // 4. Bind to the typed schema. This enforces required fields and value
    //    types; `Action` / `Gems` reject unknown fields when parsed as roots.
    let typed: T = serde_json::from_value(value.clone()).map_err(ProtocolParseError::Json)?;

    // 5. DTO-driven unknown-field detection. A faithful re-serialization cannot
    //    contain a field the schema does not define, so any input key absent
    //    from the re-serialized value is unknown. This works at every depth and
    //    needs no hand-maintained field list, so it cannot drift from the DTOs.
    //    (Safe because no DTO uses `skip_serializing_if`: the output key set is
    //    always a superset of the legitimate input key set.)
    let reserialized = serde_json::to_value(&typed).map_err(ProtocolParseError::Json)?;
    if let Some(path) = first_unknown_field(&value, &reserialized, "") {
        return Err(ProtocolParseError::UnknownField { message_type, path });
    }

    Ok(typed)
}

/// Return the first input path present in `input` but absent from the faithful
/// re-serialization `known`, recursing structurally through matching objects
/// and arrays. Scalar values are not compared — only the presence of keys.
fn first_unknown_field(input: &Value, known: &Value, prefix: &str) -> Option<String> {
    match (input, known) {
        (Value::Object(input_map), Value::Object(known_map)) => {
            for (key, input_child) in input_map {
                let path = if prefix.is_empty() {
                    key.clone()
                } else {
                    format!("{prefix}.{key}")
                };
                match known_map.get(key) {
                    None => return Some(path),
                    Some(known_child) => {
                        if let Some(found) = first_unknown_field(input_child, known_child, &path) {
                            return Some(found);
                        }
                    }
                }
            }
            None
        }
        (Value::Array(input_items), Value::Array(known_items)) => {
            for (index, input_child) in input_items.iter().enumerate() {
                if let Some(known_child) = known_items.get(index) {
                    let path = format!("{prefix}[{index}]");
                    if let Some(found) = first_unknown_field(input_child, known_child, &path) {
                        return Some(found);
                    }
                }
            }
            None
        }
        _ => None,
    }
}

/// Serialize an already-constructed sequence of player-scoped wire messages.
/// State construction and event projection remain outside this DTO crate.
pub fn to_ndjson(messages: &[ServerMessage]) -> String {
    messages
        .iter()
        .map(|message| message.to_json_line().expect("protocol serialization"))
        .collect::<Vec<_>>()
        .join("\n")
        + "\n"
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
        let request_without_id = r#"{"type":"request_action","protocol_version":"0.3","game_id":"g1","server_seq":1,"recipient_player_id":0,"observation_hash":"hash","deadline_ms":1000,"legal_actions":[{"type":"pass"}]}"#;
        assert!(serde_json::from_str::<ServerMessage>(request_without_id).is_err());

        let action_without_id =
            r#"{"type":"action","protocol_version":"0.3","game_id":"g1","action":{"type":"pass"}}"#;
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
            r#"{"type":"event","protocol_version":"0.3","game_id":"g1","server_seq":4,"event":{"type":"turn_advanced","next_player":0}}"#
        )
        .is_err());
    }
}
