//! P1 regression tests for historical policy-identity resolution.
//!
//! Known real cases from the Commit B review:
//!
//! * **S0 `n1` vs `M07`** — same binary, same handshake runtime name, but
//!   `--max-nodes 2000` vs `--max-nodes 1`. The arena report makes them look
//!   identical, so the naive importer marked all 128 games `self_match` and
//!   dropped them from Elo. The config resolver must separate them.
//! * **M44A** — `drop_*` ablation seats are study configurations and must be
//!   classified `diagnostic`, while `m44a-full` stays competitive.
//! * **No config** — a report with no sibling `match-config.json` keeps the
//!   handshake runtime identity and is never guessed from a filename.
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, FullState, GameConfig, Ruleset};
use splendor_replay::record_random_game;
use splendor_studio_league::{build_historical_corpus, HistoricalDryRunConfig, MatchStatus};
use std::path::{Path, PathBuf};

const RUNTIME_NAME: &str = "effective-splendor-determinization-agent-v1";

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "splendor-policy-identity-{}-{}",
        std::process::id(),
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn write_file(root: &Path, rel: &str, bytes: &[u8]) {
    let path = root.join(rel);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).unwrap();
    }
    std::fs::write(path, bytes).unwrap();
}

/// A real deterministic replay plus its recorded final hash.
fn replay_bytes(seed: u64, players: u8) -> (Vec<u8>, String) {
    let (_, replay) = record_random_game(players, seed, 101).unwrap();
    let bytes = serde_json::to_vec(&replay).unwrap();
    (bytes, replay.final_state_hash.as_str().to_string())
}

/// A completed arena report whose two seats both report the generic
/// determinization runtime identity (the S0 collapse case).
fn collapsed_runtime_report(game_id: &str, seed: u64, final_hash: &str) -> Vec<u8> {
    let (_, replay) = record_random_game(2, seed, 101).unwrap();
    let ruleset = Ruleset::base_v1();
    let fingerprint = ruleset_fingerprint(&ruleset);
    assert!(FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset,
    })
    .is_ok());
    let report = ArenaReportV1::new(
        game_id,
        replay.engine_version.clone(),
        "1",
        "base_v1",
        fingerprint.as_str(),
        replay.player_count,
        seed_commitment_v1(game_id, replay.player_count, replay.seed, &fingerprint),
        (0..replay.player_count)
            .map(|seat| AgentIdentity {
                seat: PlayerId(seat),
                agent_name: Some(RUNTIME_NAME.into()),
                agent_version: Some("1".into()),
            })
            .collect(),
        ArenaOutcomeV1::completed(
            splendor_core::GameResult {
                scores: replay.result.scores.clone(),
                ranks: replay.result.ranks.clone(),
                winners: replay
                    .result
                    .winners
                    .iter()
                    .copied()
                    .map(PlayerId)
                    .collect(),
                reason: replay.result.reason.into(),
            },
            replay.steps.len() as u32,
            final_hash.to_string(),
        ),
    );
    serde_json::to_vec(&report).unwrap()
}

#[test]
fn s0_n1_vs_m07_is_not_a_self_match() {
    let tmp = tempdir("s0");
    let (replay, final_hash) = replay_bytes(5_800_074, 2);
    write_file(&tmp, "r1/match-replay.json", &replay);
    let game_id = "s0-p3_n1_vs_m07-b10-s5800074-r1";
    write_file(
        &tmp,
        "r1/arena-report.json",
        &collapsed_runtime_report(game_id, 5_800_074, &final_hash),
    );
    let config = serde_json::json!({
        "game_id": game_id,
        "seed": 5_800_074,
        "agents": [
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-seed", "20260703",
                "--sample-count", "4", "--max-depth-turns", "1",
                "--max-nodes", "2000", "--stats-out", "seat0.ndjson" ] },
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-seed", "20260703",
                "--sample-count", "4", "--max-depth-turns", "1",
                "--max-nodes", "1", "--stats-out", "seat1.ndjson" ] }
        ]
    });
    write_file(
        &tmp,
        "r1/match-config.json",
        &serde_json::to_vec(&config).unwrap(),
    );
    let run_config = HistoricalDryRunConfig {
        roots: vec![tmp.to_string_lossy().to_string()],
        ..Default::default()
    };
    let (report, records) = build_historical_corpus(&run_config).unwrap();
    assert_eq!(report.canonical_records_built, 1);
    assert_eq!(report.matches_with_policy_identity, 1);
    assert_eq!(report.self_matches, 0, "n1 and M07 are two policies");
    let record = &records[0];
    assert_eq!(record.status, MatchStatus::Completed);
    let key0 = record.seats[0].policy_identity_key.as_deref().unwrap();
    let key1 = record.seats[1].policy_identity_key.as_deref().unwrap();
    assert_ne!(key0, key1);
    assert!(!record.diagnostic);
    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn m44a_ablation_is_diagnostic_but_full_is_competitive() {
    let tmp = tempdir("m44a");
    // m44a-full: the competitive reference determinization policy.
    let (replay_full, hash_full) = replay_bytes(4_400_001, 2);
    write_file(&tmp, "full/match-replay.json", &replay_full);
    write_file(
        &tmp,
        "full/arena-report.json",
        &collapsed_runtime_report("m44a-full-game", 4_400_001, &hash_full),
    );
    write_file(
        &tmp,
        "full/match-config.json",
        &serde_json::to_vec(&serde_json::json!({
            "game_id": "m44a-full-game",
            "seed": 4_400_001,
            "agents": [
                { "program": "splendor.exe", "args": [
                    "agent-determinization", "--sample-count", "4",
                    "--max-depth-turns", "1", "--max-nodes", "1",
                    "--attribution-profile", "full",
                    "--runtime-name", "m44a-full", "--runtime-version", "1",
                    "--stats-out", "a.ndjson" ] },
                { "program": "splendor.exe", "args": [
                    "agent-determinization", "--sample-count", "4",
                    "--max-depth-turns", "1", "--max-nodes", "1",
                    "--attribution-profile", "full",
                    "--runtime-name", "m44a-full", "--runtime-version", "1",
                    "--stats-out", "b.ndjson" ] }
            ]
        }))
        .unwrap(),
    );
    // m44a-drop-convertibility: an ablation.
    let (replay_drop, hash_drop) = replay_bytes(4_400_002, 2);
    write_file(&tmp, "drop/match-replay.json", &replay_drop);
    write_file(
        &tmp,
        "drop/arena-report.json",
        &collapsed_runtime_report("m44a-drop-game", 4_400_002, &hash_drop),
    );
    write_file(
        &tmp,
        "drop/match-config.json",
        &serde_json::to_vec(&serde_json::json!({
            "game_id": "m44a-drop-game",
            "seed": 4_400_002,
            "agents": [
                { "program": "splendor.exe", "args": [
                    "agent-determinization", "--sample-count", "4",
                    "--max-depth-turns", "1", "--max-nodes", "1",
                    "--attribution-profile", "drop_convertibility",
                    "--runtime-name", "m44a-drop-convertibility",
                    "--runtime-version", "1", "--stats-out", "c.ndjson" ] },
                { "program": "splendor.exe", "args": [
                    "agent-determinization", "--sample-count", "4",
                    "--max-depth-turns", "1", "--max-nodes", "1",
                    "--attribution-profile", "drop_convertibility",
                    "--runtime-name", "m44a-drop-convertibility",
                    "--runtime-version", "1", "--stats-out", "d.ndjson" ] }
            ]
        }))
        .unwrap(),
    );

    let run_config = HistoricalDryRunConfig {
        roots: vec![tmp.to_string_lossy().to_string()],
        ..Default::default()
    };
    let (report, records) = build_historical_corpus(&run_config).unwrap();
    assert_eq!(report.canonical_records_built, 2);
    assert_eq!(
        report.diagnostic_matches, 1,
        "only the drop_* match is a study"
    );

    let full = records
        .iter()
        .find(|r| r.source_path.as_deref().unwrap().contains("full/"))
        .unwrap();
    let drop = records
        .iter()
        .find(|r| r.source_path.as_deref().unwrap().contains("drop/"))
        .unwrap();
    assert!(!full.diagnostic, "m44a-full is the competitive reference");
    assert!(
        drop.diagnostic,
        "drop_convertibility is a study configuration"
    );
    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn a_report_without_a_config_keeps_the_runtime_identity_and_is_not_diagnostic() {
    let tmp = tempdir("noconfig");
    let (replay, final_hash) = replay_bytes(9_900_001, 2);
    write_file(&tmp, "r0/match-replay.json", &replay);
    write_file(
        &tmp,
        "r0/arena-report.json",
        &collapsed_runtime_report("no-config-game", 9_900_001, &final_hash),
    );
    // Deliberately no match-config.json, mirroring the 12,710 real reports
    // under m39a/m40a/m41a that carry no configuration.
    let run_config = HistoricalDryRunConfig {
        roots: vec![tmp.to_string_lossy().to_string()],
        ..Default::default()
    };
    let (report, records) = build_historical_corpus(&run_config).unwrap();
    assert_eq!(report.canonical_records_built, 1);
    assert_eq!(report.matches_without_policy_identity, 1);
    assert_eq!(report.diagnostic_matches, 0);
    let record = &records[0];
    // No policy key: the seat falls back to the handshake runtime identity.
    assert!(record.seats.iter().all(|s| s.policy_identity_key.is_none()));
    assert_eq!(
        record.seats[0].identity.as_ref().unwrap().key(),
        format!("{RUNTIME_NAME}@1")
    );
    let _ = std::fs::remove_dir_all(&tmp);
}
