use splendor_replay::{record_random_game, verify_replay, ReplayV1};

fn record(players: u8, seed: u64, action_seed: u64) -> ReplayV1 {
    record_random_game(players, seed, action_seed).unwrap().1
}

fn record_json(players: u8, seed: u64, action_seed: u64) -> String {
    serde_json::to_string_pretty(&record(players, seed, action_seed)).unwrap()
}

#[test]
fn round_trip_complete_game_for_2_3_4_players() {
    for players in 2..=4u8 {
        let replay = record(players, 42, 1001);
        let json = serde_json::to_string_pretty(&replay).unwrap();
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
    assert_eq!(record_json(2, 42, 1001), record_json(2, 42, 1001));
}
