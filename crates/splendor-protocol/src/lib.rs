//! NDJSON agent protocol (mjai-inspired).
//!
//! One JSON object per line. Transport (stdio / TCP / WS) is independent of schema.

use serde::{Deserialize, Serialize};
use splendor_core::{Action, GameResult, Observation, PlayerId, ENGINE_VERSION};

pub const PROTOCOL_VERSION: &str = "0.1";

/// Envelope fields shared by most messages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Meta {
    pub protocol_version: String,
    pub game_id: String,
    pub seq: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub player_id: Option<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub state_hash: Option<String>,
}

impl Meta {
    pub fn new(game_id: impl Into<String>, seq: u64) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION.to_string(),
            game_id: game_id.into(),
            seq,
            player_id: None,
            state_hash: None,
        }
    }

    pub fn with_player(mut self, player: PlayerId) -> Self {
        self.player_id = Some(player.0);
        self
    }

    pub fn with_hash(mut self, hash: impl Into<String>) -> Self {
        self.state_hash = Some(hash.into());
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
        player_id: u8,
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
        action: Action,
    },
    Pong {
        #[serde(flatten)]
        meta: Meta,
    },
}

impl ServerMessage {
    pub fn hello(game_id: &str, ruleset: &str) -> Self {
        ServerMessage::Hello {
            meta: Meta::new(game_id, 0),
            engine_version: ENGINE_VERSION.to_string(),
            ruleset: ruleset.to_string(),
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
    use splendor_core::{FullState, GameConfig};

    #[test]
    fn request_action_roundtrip() {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let legal = state.legal_actions();
        let msg = ServerMessage::RequestAction {
            meta: Meta::new("g1", 1).with_player(PlayerId(0)).with_hash("abc"),
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
}
