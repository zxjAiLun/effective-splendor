//! NDJSON agent protocol (v0.2).
//!
//! One JSON object per line. Transport (stdio / TCP / WS) is independent of
//! the schema.
//!
//! The protocol boundary is deliberate:
//! - server messages carry `ObservationHash` or the safe
//!   `PublicStateHash` ruleset fingerprint, never `FullStateHash`;
//! - server-side recipient and actor identities have separate names;
//! - client messages use `ClientMeta`, which has no seat, server sequence, or
//!   state-hash field that a client could use to claim authority;
//! - event messages accept `VisibleEvent`, never `RefereeEvent`.

use serde::{Deserialize, Serialize};
use splendor_core::{
    Action, GameResult, Observation, ObservationHash, PlayerId, PublicStateHash, VisibleEvent,
    ENGINE_VERSION,
};

pub const PROTOCOL_VERSION: &str = "0.2";

/// Envelope fields owned by the server and shared by server → client messages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Meta {
    pub protocol_version: String,
    pub game_id: String,
    /// Server-monotonic sequence number for this game.
    pub server_seq: u64,
    /// Correlates a client `Action` to the `RequestAction` that invited it.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<u64>,
    /// The player this message is addressed to. `None` is reserved for
    /// genuinely broadcast messages such as `Hello`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub recipient_player_id: Option<u8>,
    /// The recipient's observation identity. This is deliberately typed so a
    /// `FullStateHash` cannot be passed to the protocol API.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub observation_hash: Option<ObservationHash>,
}

impl Meta {
    pub fn new(game_id: impl Into<String>, server_seq: u64) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION.to_string(),
            game_id: game_id.into(),
            server_seq,
            request_id: None,
            recipient_player_id: None,
            observation_hash: None,
        }
    }

    pub fn with_recipient(mut self, player: PlayerId) -> Self {
        self.recipient_player_id = Some(player.0);
        self
    }

    pub fn with_request(mut self, request_id: u64) -> Self {
        self.request_id = Some(request_id);
        self
    }

    /// Attach only an observation hash. There is intentionally no generic
    /// string/hash setter here.
    pub fn with_observation_hash(mut self, hash: ObservationHash) -> Self {
        self.observation_hash = Some(hash);
        self
    }
}

/// Client-owned envelope. It deliberately has no player/seat, server sequence,
/// observation hash, or full-state hash field. The arena binds a connection to
/// a seat and validates the echoed game/request identifiers server-side.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientMeta {
    pub protocol_version: String,
    pub game_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<u64>,
}

impl ClientMeta {
    pub fn new(game_id: impl Into<String>) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION.to_string(),
            game_id: game_id.into(),
            request_id: None,
        }
    }

    pub fn with_request(mut self, request_id: u64) -> Self {
        self.request_id = Some(request_id);
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    Hello {
        #[serde(flatten)]
        meta: Meta,
        engine_version: String,
        ruleset: String,
        catalog_version: String,
        /// Ruleset/catalog fingerprint. This is a `PublicStateHash`, never a
        /// full game-state hash.
        ruleset_fingerprint: PublicStateHash,
    },
    GameStart {
        #[serde(flatten)]
        meta: Meta,
        player_count: u8,
        your_player_id: u8,
        seed_commitment: String,
    },
    Observation {
        #[serde(flatten)]
        meta: Meta,
        observation: Observation,
    },
    RequestAction {
        #[serde(flatten)]
        meta: Meta,
        deadline_ms: u64,
        legal_actions: Vec<Action>,
    },
    ActionApplied {
        #[serde(flatten)]
        meta: Meta,
        /// The single, unambiguous public actor field.
        actor_player_id: u8,
        action: Action,
    },
    /// One already-projected event. The protocol cannot be constructed from a
    /// referee event, so redaction is required before crossing this boundary.
    Event {
        #[serde(flatten)]
        meta: Meta,
        event: VisibleEvent,
    },
    GameEnd {
        #[serde(flatten)]
        meta: Meta,
        result: GameResult,
    },
    Error {
        #[serde(flatten)]
        meta: Meta,
        message: String,
    },
    Ping {
        #[serde(flatten)]
        meta: Meta,
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
        meta: ClientMeta,
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
        fingerprint: PublicStateHash,
    ) -> Self {
        ServerMessage::Hello {
            meta: Meta::new(game_id, 0),
            engine_version: ENGINE_VERSION.to_string(),
            ruleset: ruleset.to_string(),
            catalog_version: catalog_version.to_string(),
            ruleset_fingerprint: fingerprint,
        }
    }

    pub fn event(meta: Meta, event: VisibleEvent) -> Self {
        ServerMessage::Event { meta, event }
    }

    pub fn to_json_line(&self) -> serde_json::Result<String> {
        serde_json::to_string(self)
    }
}

impl ClientMessage {
    pub fn parse_line(line: &str) -> serde_json::Result<Self> {
        serde_json::from_str(line)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{ruleset_fingerprint, FullState, GameConfig};

    #[test]
    fn request_action_roundtrip() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let legal = state.legal_actions();
        let msg = ServerMessage::RequestAction {
            meta: Meta::new("g1", 1)
                .with_recipient(PlayerId(0))
                .with_request(9)
                .with_observation_hash(splendor_core::observation_hash(
                    &state.observation(PlayerId(0)),
                )),
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
                assert_eq!(meta.request_id, Some(9));
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
            meta: Meta::new("g1", 3).with_recipient(PlayerId(1)),
            actor_player_id: 0,
            action: Action::Pass,
        };
        let line = msg.to_json_line().unwrap();
        assert_eq!(line.matches("actor_player_id").count(), 1);
        assert!(!line.contains("\"player_id\""));
    }

    #[test]
    fn client_action_has_no_authorizing_identity_or_server_hash() {
        let message = ClientMessage::Action {
            meta: ClientMeta::new("g1").with_request(9),
            action: Action::Pass,
        };
        let line = serde_json::to_string(&message).unwrap();
        assert!(!line.contains("player_id"));
        assert!(!line.contains("server_seq"));
        assert!(!line.contains("observation_hash"));
        assert!(line.contains("request_id"));
    }
}
