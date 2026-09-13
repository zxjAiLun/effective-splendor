//! Commit C Slice 2 Repair 1, P1-2 gate: the ledger's `replay_path` must be
//! locatable from the **protocol archive root alone**.
//!
//! Commit C Slice 3 Repair 2 tightened this: the completion outlet no longer
//! accepts an archive root at all, so there is no per-run choice left to make.
//! This binary proves the consequence end to end at the process boundary: given
//! a database row that says `storage = archive`, `STUDIO_LEAGUE_REPLAY_DIR +
//! replay_path` resolves to an object whose bytes hash to the recorded
//! `document_hash` — nothing else about the completion invocation is needed, and
//! the caller never supplied a root.
//!
//! This is its own test binary because it changes the process working directory
//! (to keep the protocol root's relative path inside a temp directory), and a
//! process-wide cwd change must not race other tests.
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, GameResult};
use splendor_replay::record_random_game;
use splendor_studio_league::{
    complete_runtime_occurrence, open_completion_league, open_league, parse_runtime_occurrence,
    replay_document_sha256, CompletionRequestV1, IdentityManifestV1, ReplayStorage,
    RUNTIME_OCCURRENCE_FORMAT, STUDIO_LEAGUE_REPLAY_DIR,
};
use std::path::{Path, PathBuf};

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "splendor-archive-protocol-{}-{}",
        std::process::id(),
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// The three documents a finished arena occurrence produces.
fn occurrence_documents(game_id: &str, seed: u64) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
    let (_, replay) = record_random_game(2, seed, 101).unwrap();
    let fingerprint = ruleset_fingerprint(&splendor_core::Ruleset::base_v1());
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
                agent_name: Some("effective-splendor-determinization-agent-v1".into()),
                agent_version: Some("1".into()),
            })
            .collect(),
        ArenaOutcomeV1::completed(
            GameResult {
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
            replay.final_state_hash.as_str().to_string(),
        ),
    );
    let config = serde_json::json!({
        "game_id": game_id,
        "seed": seed,
        "agents": [
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-count", "4",
                "--max-depth-turns", "1", "--max-nodes", "2000" ] },
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-count", "4",
                "--max-depth-turns", "1", "--max-nodes", "1" ] }
        ]
    });
    (
        serde_json::to_vec(&report).unwrap(),
        serde_json::to_vec(&replay).unwrap(),
        serde_json::to_vec(&config).unwrap(),
    )
}

fn envelope(occurrence_id: &str, completed_at: i64, docs: &(Vec<u8>, Vec<u8>, Vec<u8>)) -> Vec<u8> {
    let (report, replay, config) = docs;
    serde_json::to_vec(&serde_json::json!({
        "format": RUNTIME_OCCURRENCE_FORMAT,
        "version": 1,
        "occurrence_id": occurrence_id,
        "completed_at": completed_at,
        "report_sha256": replay_document_sha256(report),
        "replay_sha256": replay_document_sha256(replay),
        "config_sha256": replay_document_sha256(config),
    }))
    .unwrap()
}

#[test]
fn the_recorded_archive_path_resolves_under_the_protocol_root_alone() {
    // The outlet resolves its archive root from the working directory, and a
    // process-wide cwd change must not race other tests, so this binary does it
    // once for the whole process.
    let sandbox = tempdir("locatable");
    std::env::set_current_dir(&sandbox).unwrap();

    let docs = occurrence_documents("runtime-protocol-root", 7_700_040);
    let (report, replay, config) = &docs;
    let occurrence = parse_runtime_occurrence(&envelope("occ-protocol-root", 1_730_000_600, &docs))
        .unwrap()
        .expect("a well-formed envelope");

    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    let identity_path = sandbox.join("identity.json");
    manifest.save(&identity_path).unwrap();

    // The database lives at an absolute path; nothing else is configured.
    let db = sandbox.join("league.sqlite3");
    let mut session = open_completion_league(&db, &identity_path, 1_700_000_000).unwrap();
    let request = CompletionRequestV1 {
        occurrence: &occurrence,
        report_bytes: report,
        replay_bytes: replay,
        config_bytes: config,
        replay_source_path: "run-a/match-replay.json",
    };
    let outcome = complete_runtime_occurrence(&mut session, &request).unwrap();
    assert_eq!(outcome.record.replay.storage(), ReplayStorage::Archive);

    // The only things a later process needs are the row and the protocol root.
    let conn = open_league(&db).unwrap();
    let (storage, path, document_hash): (String, String, String) = conn
        .query_row(
            "SELECT replay_storage, replay_path, replay_document_hash FROM matches",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(storage, "archive");
    assert!(
        !Path::new(&path).is_absolute(),
        "the ledger must record a content-relative path, got `{path}`"
    );

    let resolved = Path::new(STUDIO_LEAGUE_REPLAY_DIR).join(&path);
    assert!(
        resolved.is_file(),
        "STUDIO_LEAGUE_REPLAY_DIR + replay_path must locate the object, tried {}",
        resolved.display()
    );
    assert_eq!(
        replay_document_sha256(&std::fs::read(&resolved).unwrap()),
        document_hash
    );
    assert_eq!(document_hash, replay_document_sha256(replay));
}
