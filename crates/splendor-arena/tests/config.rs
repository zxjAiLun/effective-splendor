use splendor_arena::config::{AgentCommand, ArenaConfig};
use std::path::PathBuf;

fn agent(program: &str) -> AgentCommand {
    AgentCommand {
        program: PathBuf::from(program),
        args: vec![],
    }
}

fn valid_config() -> ArenaConfig {
    ArenaConfig {
        game_id: "g1".to_string(),
        seed: 1,
        handshake_timeout_ms: 1000,
        move_timeout_ms: 1000,
        shutdown_grace_ms: 1000,
        agents: vec![agent("a"), agent("b")],
    }
}

#[test]
fn config_rejects_unknown_fields() {
    let json = r#"{
        "game_id": "g1",
        "seed": 1,
        "handshake_timeout_ms": 1000,
        "move_timeout_ms": 1000,
        "shutdown_grace_ms": 1000,
        "agents": [{"program": "a"}, {"program": "b"}],
        "surprise": 1
    }"#;
    assert!(serde_json::from_str::<ArenaConfig>(json).is_err());
}

#[test]
fn config_rejects_empty_game_id() {
    let mut c = valid_config();
    c.game_id = "".to_string();
    assert!(c.validate().is_err());
}

#[test]
fn config_rejects_control_characters() {
    for bad in ["g\n1", "g\r1", "g\x01", "g\n", "g\r"] {
        let mut c = valid_config();
        c.game_id = bad.to_string();
        assert!(c.validate().is_err(), "accepted control char in {bad:?}");
    }
}

#[test]
fn config_rejects_one_or_five_agents() {
    let mut one = valid_config();
    one.agents = vec![agent("a")];
    assert!(one.validate().is_err());

    let mut five = valid_config();
    five.agents = (0..5).map(|i| agent(&format!("a{i}"))).collect();
    assert!(five.validate().is_err());
}

#[test]
fn config_rejects_zero_timeouts() {
    for field in [
        "handshake_timeout_ms",
        "move_timeout_ms",
        "shutdown_grace_ms",
    ] {
        let mut c = valid_config();
        match field {
            "handshake_timeout_ms" => c.handshake_timeout_ms = 0,
            "move_timeout_ms" => c.move_timeout_ms = 0,
            "shutdown_grace_ms" => c.shutdown_grace_ms = 0,
            _ => unreachable!(),
        }
        assert!(c.validate().is_err(), "accepted zero {field}");
    }
}

#[test]
fn config_derives_player_count() {
    let two = valid_config();
    assert_eq!(two.player_count(), 2);

    let mut four = valid_config();
    four.agents = (0..4).map(|i| agent(&format!("a{i}"))).collect();
    assert_eq!(four.player_count(), 4);
}
