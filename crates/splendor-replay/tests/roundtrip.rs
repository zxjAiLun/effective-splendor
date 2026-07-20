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

/// The committed golden replay is a byte-regression lock: the deterministic
/// generator must reproduce exactly the checked-in file (pretty JSON, two-space
/// indent, single trailing newline, no host-specific data).
#[test]
fn golden_replay_matches_committed_fixture() {
    let mut generated = record_json(2, 42, 1001);
    generated.push('\n');
    assert_eq!(
        generated,
        include_str!("../../../fixtures/replay/v1/normal-2p-seed42.json"),
        "golden replay fixture is stale; regenerate with `splendor record-replay`"
    );
}

#[test]
fn golden_replay_fixture_verifies() {
    let raw = include_str!("../../../fixtures/replay/v1/normal-2p-seed42.json");
    let replay: ReplayV1 = serde_json::from_str(raw).unwrap();
    let verified = verify_replay(&replay).unwrap();
    assert_eq!(verified.player_count, 2);
}
