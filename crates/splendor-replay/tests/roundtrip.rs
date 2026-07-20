use splendor_replay::{record_random_game, verify_replay, ReplayV1};

fn record_and_serialize(players: u8, seed: u64, action_seed: u64) -> (ReplayV1, String) {
    let (_state, replay) = record_random_game(players, seed, action_seed).unwrap();
    let json = serde_json::to_string_pretty(&replay).unwrap();
    (replay, json)
}

#[test]
fn round_trip_complete_game_for_2_3_4_players() {
    for players in 2..=4u8 {
        let (replay, json) = record_and_serialize(players, 42, 1001);
        let parsed: ReplayV1 = serde_json::from_str(&json).unwrap();
        assert_eq!(replay, parsed);

        let verified = verify_replay(&parsed).unwrap();
        assert_eq!(verified.player_count, players);
        assert_eq!(verified.steps, replay.steps.len() as u32);
        assert_eq!(verified.final_state_hash, replay.final_state_hash.as_str());
    }
}

#[test]
fn same_game_produces_byte_identical_replay() {
    let (_r1, first) = record_and_serialize(2, 42, 1001);
    let (_r2, second) = record_and_serialize(2, 42, 1001);
    assert_eq!(first, second);
}
