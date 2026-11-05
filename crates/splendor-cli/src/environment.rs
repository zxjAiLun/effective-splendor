//! Persistent, model-independent rules environment over NDJSON.

use std::io::{self, BufRead, Write};

use serde::Deserialize;
use serde_json::{json, Value};
use splendor_core::{
    visible_events, Action, Audience, FullState, GameConfig, PlayerId, RefereeEvent,
};

pub const ENV_VERSION: &str = "1";

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Reset { player_count: u8, seed: u64 },
    Observe { player_id: u8 },
    Step { action: Action },
    Catalog,
}

#[derive(Default)]
struct Environment {
    state: Option<FullState>,
    history: Vec<RefereeEvent>,
}

impl Environment {
    fn handle(&mut self, request: Request) -> Result<Value, String> {
        match request {
            Request::Reset { player_count, seed } => {
                let (state, setup) = FullState::new(GameConfig {
                    player_count,
                    seed,
                    ..Default::default()
                })
                .map_err(|e| e.to_string())?;
                let viewer = state.current_player;
                self.state = Some(state);
                self.history = setup.events;
                self.snapshot(viewer)
            }
            Request::Observe { player_id } => self.snapshot(PlayerId(player_id)),
            Request::Step { action } => {
                let state = self.state.as_mut().ok_or("reset is required before step")?;
                let step = state.apply(action).map_err(|e| e.to_string())?;
                self.history.extend(step.events);
                let viewer = state.current_player;
                self.snapshot(viewer)
            }
            Request::Catalog => Ok(catalog()),
        }
    }

    fn snapshot(&self, viewer: PlayerId) -> Result<Value, String> {
        let state = self
            .state
            .as_ref()
            .ok_or("reset is required before observe")?;
        if viewer.0 >= state.player_count() {
            return Err("player_id is outside this game".into());
        }
        let legal_actions = if viewer == state.current_player {
            state.legal_actions()
        } else {
            Vec::new()
        };
        Ok(json!({
            "type": "state",
            "env_version": ENV_VERSION,
            "current_player": state.current_player,
            "observation": state.observation(viewer),
            "legal_actions": legal_actions,
            "visible_history": visible_events(&self.history, Audience::Player(viewer)),
            "terminated": state.is_terminal(),
            "result": state.result,
        }))
    }
}

/// Export semantic identifiers and definitions, without a model feature layout.
pub fn catalog() -> Value {
    let cards: Vec<Value> = splendor_catalog::all_cards()
        .iter()
        .map(|card| {
            json!({
                "id": card.id,
                "tier": card.tier,
                "bonus": card.bonus,
                "prestige": card.prestige,
                "cost": card.cost,
            })
        })
        .collect();
    json!({
        "type": "catalog",
        "env_version": ENV_VERSION,
        "engine_version": splendor_core::ENGINE_VERSION,
        "protocol_version": splendor_protocol::PROTOCOL_VERSION,
        "catalog_version": splendor_catalog::CATALOG_VERSION,
        "color_order": ["White", "Blue", "Green", "Red", "Black"],
        "ruleset": splendor_core::Ruleset::base_v1(),
        "cards": cards,
        "nobles": splendor_catalog::all_nobles(),
    })
}

pub fn serve(input: impl BufRead, mut output: impl Write) -> io::Result<()> {
    let mut environment = Environment::default();
    for line in input.lines() {
        let line = line?;
        let response = serde_json::from_str::<Request>(&line)
            .map_err(|e| e.to_string())
            .and_then(|request| environment.handle(request))
            .unwrap_or_else(|message| json!({"type": "error", "message": message}));
        serde_json::to_writer(&mut output, &response)?;
        writeln!(output)?;
        output.flush()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn environment_matches_core_and_preserves_state_after_illegal_action() {
        let mut environment = Environment::default();
        let initial = environment
            .handle(Request::Reset {
                player_count: 3,
                seed: 42,
            })
            .unwrap();
        let (mut core, _) = FullState::new(GameConfig {
            player_count: 3,
            seed: 42,
            ..Default::default()
        })
        .unwrap();
        assert!(environment
            .handle(Request::Step {
                action: Action::Pass
            })
            .is_err());
        assert_eq!(initial, environment.snapshot(PlayerId(0)).unwrap());
        for _ in 0..20 {
            let action = core.legal_actions()[0];
            core.apply(action).unwrap();
            let actual = environment.handle(Request::Step { action }).unwrap();
            assert_eq!(
                actual["observation"],
                json!(core.observation(core.current_player))
            );
            assert_eq!(actual["legal_actions"], json!(core.legal_actions()));
            assert_eq!(actual["result"], json!(core.result));
        }
    }

    #[test]
    fn blind_reserve_is_visible_only_to_its_owner() {
        let mut environment = Environment::default();
        environment
            .handle(Request::Reset {
                player_count: 2,
                seed: 42,
            })
            .unwrap();
        let action = environment
            .state
            .as_ref()
            .unwrap()
            .legal_actions()
            .into_iter()
            .find(|action| matches!(action, Action::ReserveDeck { .. }))
            .unwrap();
        environment.handle(Request::Step { action }).unwrap();
        let owner = environment.snapshot(PlayerId(0)).unwrap();
        let opponent = environment.snapshot(PlayerId(1)).unwrap();
        assert_eq!(
            owner["observation"]["private"]["reserved"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            opponent["observation"]["public"]["players"][0]["public_reserved"],
            json!([])
        );
        let event = |value: &Value| {
            value["visible_history"]
                .as_array()
                .unwrap()
                .iter()
                .find(|event| event["type"] == "card_reserved")
                .unwrap()["card"]
                .clone()
        };
        assert!(event(&owner).is_number());
        assert!(event(&opponent).is_null());
        assert!(opponent["visible_history"][0].get("seed").is_none());
    }

    #[test]
    fn protocol_recovers_after_bad_input_and_handles_eof() {
        let input = b"{\"type\":\"step\",\"action\":{\"type\":\"pass\"}}\n{\"type\":\"reset\",\"player_count\":2,\"seed\":42}\n{\"type\":\"observe\",\"player_id\":2}\n";
        let mut output = Vec::new();
        serve(&input[..], &mut output).unwrap();
        let responses: Vec<Value> = String::from_utf8(output)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        assert_eq!(responses.len(), 3);
        assert_eq!(responses[0]["type"], "error");
        assert_eq!(responses[1]["type"], "state");
        assert_eq!(responses[2]["type"], "error");
    }
}
