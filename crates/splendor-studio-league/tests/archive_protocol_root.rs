//! Commit C Slice 2 Repair 1, P1-2 gate: the ledger's `replay_path` must be
//! locatable from the **protocol archive root alone**.
//!
//! The production CLI no longer accepts an archive root; it always archives
//! under `STUDIO_LEAGUE_REPLAY_DIR` and records only the content-relative path.
//! This binary proves the consequence: given a database row that says
//! `storage = archive`, `STUDIO_LEAGUE_REPLAY_DIR + replay_path` resolves to an
//! object whose bytes hash to the recorded `document_hash` — nothing else about
//! the ingest invocation is needed.
//!
//! This is its own test binary because it changes the process working directory
//! (to keep the protocol root's relative path inside a temp directory), and a
//! process-wide cwd change must not race other tests.
use splendor_replay::record_random_game;
use splendor_studio_league::{
    archive_replay, bind_archived_replay, ensure_rating_config, ingest_match, initialise,
    open_league, parse_runtime_occurrence, replay_document_sha256, runtime_match_record,
    sync_identity_manifest, IdentityManifestV1, ReplayStorage, RUNTIME_OCCURRENCE_FORMAT,
    STUDIO_LEAGUE_REPLAY_DIR,
};
use std::path::Path;

fn tempdir(label: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "splendor-archive-protocol-{}-{}",
        std::process::id(),
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn occurrence_documents(game_id: &str, seed: u64) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
    let (_, replay) = record_random_game(2, seed, 101).unwrap();
    let fingerprint = splendor_core::ruleset_fingerprint(&splendor_core::Ruleset::base_v1());
    let report = splendor_arena::ArenaReportV1::new(
        game_id,
        replay.engine_version.clone(),
        "1",
        "base_v1",
        fingerprint.as_str(),
        replay.player_count,
        splendor_arena::seed_commitment_v1(game_id, replay.player_count, replay.seed, &fingerprint),
        (0..replay.player_count)
            .map(|seat| splendor_arena::AgentIdentity {
                seat: splendor_core::PlayerId(seat),
                agent_name: Some("effective-splendor-determinization-agent-v1".into()),
                agent_version: Some("1".into()),
            })
            .collect(),
        splendor_arena::ArenaOutcomeV1::completed(
            splendor_core::GameResult {
                scores: replay.result.scores.clone(),
                ranks: replay.result.ranks.clone(),
                winners: replay
                    .result
                    .winners
                    .iter()
                    .copied()
                    .map(splendor_core::PlayerId)
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
    let tmp = tempdir("locatable");
    let docs = occurrence_documents("runtime-protocol-root", 7_700_040);
    let (report, replay, config) = &docs;

    // Work inside the temp directory so the protocol root's relative path lands
    // there instead of in the repository's local-artifacts archive.
    let previous = std::env::current_dir().unwrap();
    std::env::set_current_dir(&tmp).unwrap();
    let result = std::panic::catch_unwind(|| {
        let occurrence =
            parse_runtime_occurrence(&envelope("occ-protocol-root", 1_730_000_600, &docs))
                .unwrap()
                .unwrap();
        let record = runtime_match_record(
            &occurrence,
            report,
            replay,
            config,
            "run-a/match-replay.json",
        )
        .unwrap();
        let replay_sha = record.replay.document_hash.clone().unwrap();

        // Archive under the protocol root exactly as the production CLI does.
        let archived =
            archive_replay(Path::new(STUDIO_LEAGUE_REPLAY_DIR), &replay_sha, replay).unwrap();
        let record = bind_archived_replay(record, &archived).unwrap();
        assert_eq!(record.replay.storage(), ReplayStorage::Archive);

        // Ingest into a database at an absolute path.
        let mut manifest = IdentityManifestV1::new();
        manifest.ensure_local_human("Nick");
        let db = std::env::temp_dir().join(format!(
            "splendor-archive-protocol-{}-locatable.sqlite3",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&db);
        let mut conn = open_league(&db).unwrap();
        initialise(&conn).unwrap();
        ensure_rating_config(&conn).unwrap();
        sync_identity_manifest(&conn, &manifest, 1_700_000_000).unwrap();
        ingest_match(&mut conn, &record).unwrap();

        // The only things a later process needs are the row and the protocol root.
        let (storage, path, document_hash): (String, String, String) = conn
            .query_row(
                "SELECT replay_storage, replay_path, replay_document_hash FROM matches",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(storage, "archive");

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

        let _ = std::fs::remove_file(&db);
    });
    std::env::set_current_dir(previous).unwrap();
    let _ = std::fs::remove_dir_all(&tmp);
    if let Err(panic) = result {
        std::panic::resume_unwind(panic);
    }
}
