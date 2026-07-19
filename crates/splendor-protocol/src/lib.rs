//! NDJSON agent protocol (mjai-inspired).
//!
//! One JSON object per line. Transport (stdio / TCP / WS) is independent of schema.
//!
//! **Information boundary:** server messages only ever carry `VisibleEvent`s and
//! `ObservationHash` (never `FullStateHash`). The receiver is identified by
//! `recipient_player_id`; clients MUST NOT assert an authorizing identity in their
//! `Action` messages — seat binding is the runner's responsibility (PR-04).

use serde::{Deserialize, Serialize};
use splendor_core::{Action, GameResult, Observation, ObservationHash, PlayerId, ENGINE_VERSION};

pub const PROTOCOL_VERSION: &str = "0.2";

/// Envelope fields shared by most messages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Meta {
    pub protocol_version: String,
    pub game_id: String,
    /// Server-monotonic sequence number for this game.
    pub server_seq: u64,
    /// Set on request/response pairs to correlate a client `Action` to the
    /// `RequestAction` that invited it.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<u64>,
    /// The player this message is addressed to (server → client). `None` for
    /// broadcast-style messages like `Hello`/`GameStart`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub recipient_player_id: Option<u8>,
    /// Observation hash for the recipient. NEVER a full state hash.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub observation_hash: Option<String>,
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

    /// Attach only an `ObservationHash`. Callers must never pass a `FullStateHash`
    /// here — type system forbids it (this takes `ObservationHash` only).
    pub fn with_observation_hash(mut self, hash: ObservationHash) -> Self {
        self.observation_hash = Some(hash.as_str().to_string());
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
        /// Fingerprint of the initial public state (a `PublicStateHash` hex).
        ruleset_fingerprint: String,
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
        /// The single, unambiguous actor. Not flattened from `Meta`.
        actor_player_id: u8,
        action: Action,
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
        meta: Meta,
        agent_name: String,
        agent_version: String,
    },
    Action {
        #[serde(flatten)]
        meta: Meta,
        /// The action the client proposes for its bound seat. The client MUST NOT
        /// set `recipient_player_id` to claim another seat — the runner ignores it.
        action: Action,
    },
    Pong {
        #[serde(flatten)]
        meta: Meta,
    },
}

impl ServerMessage {
    pub fn hello(game_id: &str, ruleset: &str, catalog_version: &str, fingerprint: &str) -> Self {
        ServerMessage::Hello {
            meta: Meta::new(game_id, 0),
            engine_version: ENGINE_VERSION.to_string(),
            ruleset: ruleset.to_string(),
            catalog_version: catalog_version.to_string(),
            ruleset_fingerprint: fingerprint.to_string(),
        }
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
    use splendor_core::{FullState, GameConfig, PublicStateHash};

    #[test]
    fn request_action_roundtrip() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let legal = state.legal_actions();
        let msg = ServerMessage::RequestAction {
            meta: Meta::new("g1", 1)
                .with_recipient(PlayerId(0))
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
            ServerMessage::RequestAction { legal_actions, .. } => {
                assert_eq!(legal_actions, legal);
            }
            _ => panic!("wrong type"),
        }
    }

    #[test]
    fn hello_carries_catalog_and_fingerprint() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let fp = PublicStateHash::as_str(&splendor_core::public_state_hash(&state)).to_string();
        let msg = ServerMessage::hello(
            "g1",
            splendor_core::RULESET_BASE_V1.0,
            splendor_core::CATALOG_VERSION,
            &fp,
        );
        let line = msg.to_json_line().unwrap();
        assert!(line.contains("catalog_version"));
        assert!(line.contains("ruleset_fingerprint"));
    }

    #[test]
    fn action_applied_has_single_actor_field() {
        let msg = ServerMessage::ActionApplied {
            meta: Meta::new("g1", 3).with_recipient(PlayerId(1)),
            actor_player_id: 0,
            action: Action::Pass,
        };
        let line = msg.to_json_line().unwrap();
        // Exactly one occurrence of the unambiguous actor field.
        assert_eq!(line.matches("actor_player_id").count(), 1);
        // The authoritative actor is `actor_player_id`; there must be no separate
        // `player_id` field shadowing it (the only receiver field is
        // `recipient_player_id`, which is a different name).
        assert!(!line.contains("\"player_id\""));
    }
}
