//! Commit C Slice 2: the content-addressed replay archive.
//!
//! End-to-end gates over the real authority chain (verify -> archive -> ledger
//! binding), beyond the module-level unit tests in `src/replay_archive.rs`:
//!
//! 1. archiving a verified occurrence writes one content-addressed object and
//!    the ledger binding reads `archive` with that content address;
//! 2. re-offering the same occurrence is idempotent (one object, one match);
//! 3. after the original run directory is deleted, the archived replay is still
//!    readable at the recorded path and still passes `verify_replay`;
//! 4. an archive collision with different bytes fails closed;
//! 5. a runtime record can only be bound to an archive object that names its own
//!    verified replay document hash.
use crate::historical_import::{bind_archived_replay, runtime_match_record};
use crate::{
    archive_replay, ensure_rating_config, ingest_match, initialise, open_league,
    parse_runtime_occurrence, read_archived_replay, replay_document_sha256, sync_identity_manifest,
    ArchiveOutcome, IdentityManifestV1, IngestOutcome, ReplayStorage, RUNTIME_OCCURRENCE_FORMAT,
};
use rusqlite::Connection;
use splendor_replay::{record_random_game, verify_replay, ReplayV1};
use std::path::{Path, PathBuf};

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "splendor-replay-archive-{}-{}",
        std::process::id(),
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn sha256(bytes: &[u8]) -> String {
    replay_document_sha256(bytes)
}

/// The three documents a finished arena occurrence produces. Two seats carry
/// different search budgets so they are two distinct policies.
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

fn occurrence_envelope(
    occurrence_id: &str,
    completed_at: i64,
    report: &[u8],
    replay: &[u8],
    config: &[u8],
) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "format": RUNTIME_OCCURRENCE_FORMAT,
        "version": 1,
        "occurrence_id": occurrence_id,
        "completed_at": completed_at,
        "report_sha256": sha256(report),
        "replay_sha256": sha256(replay),
        "config_sha256": sha256(config),
    }))
    .unwrap()
}

fn parse(
    occurrence_id: &str,
    completed_at: i64,
    docs: &(Vec<u8>, Vec<u8>, Vec<u8>),
) -> crate::RuntimeOccurrenceV1 {
    let (report, replay, config) = docs;
    let envelope = occurrence_envelope(occurrence_id, completed_at, report, replay, config);
    parse_runtime_occurrence(&envelope)
        .unwrap()
        .expect("well-formed envelope")
}

fn fresh_league(path: &Path, manifest: &IdentityManifestV1) {
    let conn = open_league(path).unwrap();
    initialise(&conn).unwrap();
    ensure_rating_config(&conn).unwrap();
    sync_identity_manifest(&conn, manifest, 1_700_000_000).unwrap();
}

fn test_manifest() -> IdentityManifestV1 {
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    manifest
}

fn replay_binding(conn: &Connection, match_id: &str) -> (String, String, String) {
    conn.query_row(
        "SELECT replay_storage, replay_path, replay_document_hash FROM matches WHERE match_id = ?1",
        [match_id],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    )
    .unwrap()
}

#[test]
fn a_verified_occurrence_is_archived_and_the_ledger_points_at_the_object() {
    let tmp = tempdir("binding");
    let docs = occurrence_documents("runtime-archive-1", 7_700_030);
    let (report, replay, config) = &docs;
    let occurrence = parse("occ-archive-1", 1_730_000_100, &docs);
    let archive_root = tmp.join("replays");

    let record = runtime_match_record(
        &occurrence,
        report,
        replay,
        config,
        "run-a/match-replay.json",
    )
    .unwrap();
    let replay_sha = record.replay.document_hash.clone().unwrap();

    // Archive the verified bytes, then point the binding at the object.
    let archived = archive_replay(&archive_root, &replay_sha, replay).unwrap();
    let record = bind_archived_replay(record, &archived).unwrap();
    assert_eq!(record.replay.storage(), ReplayStorage::Archive);
    assert_eq!(record.replay.path.as_deref(), Some(archived.logical_path()));
    assert_eq!(record.replay.storage().as_str(), "archive");

    let manifest = test_manifest();
    let db = tmp.join("league.sqlite3");
    fresh_league(&db, &manifest);
    let mut conn = open_league(&db).unwrap();
    assert!(matches!(
        ingest_match(&mut conn, &record).unwrap(),
        IngestOutcome::Inserted { .. }
    ));

    let (storage, path, document_hash) = replay_binding(&conn, &record.match_id());
    assert_eq!(storage, "archive");
    assert_eq!(document_hash, replay_sha);
    assert_eq!(path, archived.logical_path());
    // The recorded logical path really resolves under the archive root.
    assert_eq!(
        archive_root.join(path.replace('/', std::path::MAIN_SEPARATOR_STR)),
        archived.filesystem_path().to_path_buf()
    );

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn re_archiving_and_re_offering_the_same_occurrence_is_idempotent() {
    let tmp = tempdir("idempotent");
    let docs = occurrence_documents("runtime-archive-2", 7_700_031);
    let (report, replay, config) = &docs;
    let occurrence = parse("occ-archive-2", 1_730_000_200, &docs);
    let archive_root = tmp.join("replays");

    let record =
        runtime_match_record(&occurrence, report, replay, config, "x/replay.json").unwrap();
    let replay_sha = record.replay.document_hash.clone().unwrap();
    let first = archive_replay(&archive_root, &replay_sha, replay).unwrap();
    let second = archive_replay(&archive_root, &replay_sha, replay).unwrap();
    assert_eq!(first.outcome().as_str(), "stored");
    assert_eq!(second.outcome().as_str(), "already_present");
    assert_eq!(first.filesystem_path(), second.filesystem_path());

    let record = bind_archived_replay(record, &first).unwrap();
    let manifest = test_manifest();
    let db = tmp.join("league.sqlite3");
    fresh_league(&db, &manifest);
    let mut conn = open_league(&db).unwrap();
    let first_outcome = ingest_match(&mut conn, &record).unwrap();
    let second_outcome = ingest_match(&mut conn, &record).unwrap();
    assert!(matches!(first_outcome, IngestOutcome::Inserted { .. }));
    assert!(matches!(
        second_outcome,
        IngestOutcome::AlreadyPresent { .. }
    ));
    let matches: i64 = conn
        .query_row("SELECT COUNT(*) FROM matches", [], |row| row.get(0))
        .unwrap();
    assert_eq!(matches, 1, "one occurrence is one match");

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn the_archived_replay_survives_deletion_of_the_run_directory_and_re_verifies() {
    let tmp = tempdir("survives");
    let docs = occurrence_documents("runtime-archive-3", 7_700_032);
    let (report, replay, config) = &docs;
    let occurrence = parse("occ-archive-3", 1_730_000_300, &docs);

    // A real run directory holding the replay, deleted after archiving.
    let run_directory = tmp.join("run-a");
    std::fs::create_dir_all(&run_directory).unwrap();
    std::fs::write(run_directory.join("match-replay.json"), replay).unwrap();

    let archive_root = tmp.join("replays");
    let record = runtime_match_record(
        &occurrence,
        report,
        replay,
        config,
        "run-a/match-replay.json",
    )
    .unwrap();
    let replay_sha = record.replay.document_hash.clone().unwrap();
    let archived = archive_replay(&archive_root, &replay_sha, replay).unwrap();
    let record = bind_archived_replay(record, &archived).unwrap();

    let manifest = test_manifest();
    let db = tmp.join("league.sqlite3");
    fresh_league(&db, &manifest);
    let mut conn = open_league(&db).unwrap();
    ingest_match(&mut conn, &record).unwrap();
    drop(conn);

    // Delete the whole original run directory.
    std::fs::remove_dir_all(&run_directory).unwrap();
    assert!(!run_directory.exists());

    // The ledger's recorded path still resolves, and the bytes still verify.
    let archive_path = archive_root.join(record.replay.path.as_deref().unwrap());
    let archived_bytes = std::fs::read(&archive_path).unwrap();
    assert_eq!(replay_document_sha256(&archived_bytes), replay_sha);
    let parsed: ReplayV1 = serde_json::from_slice(&archived_bytes).unwrap();
    let verified = verify_replay(&parsed).unwrap();
    assert_eq!(verified.final_state_hash, parsed.final_state_hash.as_str());

    // And the public read helper agrees.
    assert_eq!(
        read_archived_replay(&archive_root, &replay_sha).unwrap(),
        archived_bytes
    );

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn a_collision_with_different_bytes_fails_closed_and_writes_no_orphan() {
    let tmp = tempdir("collision");
    let docs = occurrence_documents("runtime-archive-4", 7_700_033);
    let (_, replay, _) = &docs;
    let archive_root = tmp.join("replays");
    let replay_sha = replay_document_sha256(replay);

    // Occupy the target with corrupt bytes that do not hash to their name.
    let directory = archive_root.join(&replay_sha[..2]);
    std::fs::create_dir_all(&directory).unwrap();
    let target = directory.join(format!("{replay_sha}.json"));
    std::fs::write(&target, b"corrupt").unwrap();

    let error = archive_replay(&archive_root, &replay_sha, replay).unwrap_err();
    assert!(error.to_string().contains("different bytes"), "{error}");
    assert_eq!(std::fs::read(&target).unwrap(), b"corrupt");

    // No temporary residue was left behind.
    let residue: Vec<_> = std::fs::read_dir(&directory)
        .unwrap()
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.file_name().to_string_lossy().ends_with(".tmp"))
        .collect();
    assert!(
        residue.is_empty(),
        "a failed archive must leave no temp file"
    );

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn a_record_can_only_bind_an_archive_object_naming_its_own_replay() {
    let tmp = tempdir("mismatch");
    let docs = occurrence_documents("runtime-archive-5", 7_700_034);
    let (report, replay, config) = &docs;
    let occurrence = parse("occ-archive-5", 1_730_000_400, &docs);

    // Archive a *different* document.
    let other = b"{\"format\":\"replay-v1\",\"unrelated\":true}".to_vec();
    let other_sha = replay_document_sha256(&other);
    let archived_other = archive_replay(&tmp.join("replays"), &other_sha, &other).unwrap();

    let record =
        runtime_match_record(&occurrence, report, replay, config, "x/replay.json").unwrap();
    let error = bind_archived_replay(record, &archived_other).unwrap_err();
    assert!(error.to_string().contains("does not match"), "{error}");

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn an_unverified_replay_is_rejected_before_any_archive_write() {
    let tmp = tempdir("unverified");
    let docs = occurrence_documents("runtime-archive-6", 7_700_035);
    let (report, replay, config) = &docs;
    let occurrence = parse("occ-archive-6", 1_730_000_500, &docs);
    let archive_root = tmp.join("replays");

    // Tamper the replay so verification fails (the report still names the
    // original terminal hash).
    let mut tampered = replay.clone();
    let len = tampered.len();
    tampered[len - 3] = if tampered[len - 3] == b'0' {
        b'1'
    } else {
        b'0'
    };

    let rejected = runtime_match_record(&occurrence, report, &tampered, config, "x/replay.json");
    assert!(rejected.is_err(), "a tampered replay must not verify");
    // Nothing was archived: the rejection happens before the archive step.
    assert!(
        !archive_root.exists() || std::fs::read_dir(&archive_root).unwrap().next().is_none(),
        "an unverified replay must not create an archive object"
    );

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn reading_a_tampered_archive_object_fails_closed() {
    // Repair 1 hardening: the public read helper re-hashes what it reads, so an
    // object that no longer matches its content address is refused instead of
    // being handed back as if it were the verified replay.
    let tmp = tempdir("tamper-read");
    let docs = occurrence_documents("runtime-archive-7", 7_700_036);
    let (_, replay, _) = &docs;
    let archive_root = tmp.join("replays");
    let replay_sha = replay_document_sha256(replay);

    let archived = archive_replay(&archive_root, &replay_sha, replay).unwrap();
    // Sanity: an intact object reads back.
    assert_eq!(
        read_archived_replay(&archive_root, &replay_sha).unwrap(),
        *replay
    );

    // Corrupt the object on disk, keeping the same size.
    let target = archived.filesystem_path();
    let mut corrupted = std::fs::read(target).unwrap();
    let last = corrupted.len() - 3;
    corrupted[last] = if corrupted[last] == b'0' { b'1' } else { b'0' };
    std::fs::write(target, &corrupted).unwrap();

    let error = read_archived_replay(&archive_root, &replay_sha).unwrap_err();
    assert!(error.to_string().contains("corrupt"), "{error}");

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn binding_a_handle_whose_object_was_deleted_fails_closed() {
    // Repair 2: an opaque handle only proves the object existed when it was
    // created. Deleting it before bind must be refused, so the ledger can never
    // record `archive` for an object that is no longer there.
    let tmp = tempdir("bind-deleted");
    let docs = occurrence_documents("runtime-archive-8", 7_700_037);
    let (report, replay, config) = &docs;
    let occurrence = parse("occ-archive-8", 1_730_000_600, &docs);
    let archive_root = tmp.join("replays");

    let record =
        runtime_match_record(&occurrence, report, replay, config, "x/replay.json").unwrap();
    let replay_sha = record.replay.document_hash.clone().unwrap();
    let archived = archive_replay(&archive_root, &replay_sha, replay).unwrap();

    // The object exists at handle creation, then vanishes.
    std::fs::remove_file(archived.filesystem_path()).unwrap();
    assert!(!archived.filesystem_path().exists());

    let error = bind_archived_replay(record, &archived).unwrap_err();
    assert!(error.to_string().contains("no longer readable"), "{error}");

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn binding_a_handle_whose_object_was_overwritten_fails_closed() {
    // The tamper variant: same path, different bytes. The content address no
    // longer describes the object, so bind must refuse.
    let tmp = tempdir("bind-tampered");
    let docs = occurrence_documents("runtime-archive-9", 7_700_038);
    let (report, replay, config) = &docs;
    let occurrence = parse("occ-archive-9", 1_730_000_700, &docs);
    let archive_root = tmp.join("replays");

    let record =
        runtime_match_record(&occurrence, report, replay, config, "x/replay.json").unwrap();
    let replay_sha = record.replay.document_hash.clone().unwrap();
    let archived = archive_replay(&archive_root, &replay_sha, replay).unwrap();

    // Overwrite the object with bytes that do not hash to its address.
    let mut corrupt = std::fs::read(archived.filesystem_path()).unwrap();
    let last = corrupt.len() - 3;
    corrupt[last] = if corrupt[last] == b'0' { b'1' } else { b'0' };
    std::fs::write(archived.filesystem_path(), &corrupt).unwrap();

    let error = bind_archived_replay(record, &archived).unwrap_err();
    assert!(
        error.to_string().contains("changed after it was written"),
        "{error}"
    );

    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn concurrent_producers_of_one_sha_publish_exactly_one_correct_object() {
    // P2 prerequisite for the central completion outlet: several producers may
    // archive the same content address at once. Every one must succeed with
    // Stored or AlreadyPresent, and exactly one byte-correct object must exist
    // afterwards, with no temporary residue. Repeated over many rounds so the
    // check-absent -> write -> rename window is exercised reliably rather than
    // depending on one lucky schedule.
    use std::sync::{Arc, Barrier};

    const PRODUCERS: usize = 16;
    const ROUNDS: usize = 25;

    for round in 0..ROUNDS {
        let tmp = tempdir(&format!("concurrent-{round}"));
        let archive_root = tmp.join("replays");
        // `archive_replay` only needs bytes and their content address, so a
        // distinct synthetic payload per round is enough.
        let payload = format!("{{\"round\":{round},\"payload\":\"concurrent\"}}").into_bytes();
        let replay_sha = replay_document_sha256(&payload);

        let barrier = Arc::new(Barrier::new(PRODUCERS));
        let mut handles = Vec::new();
        for _ in 0..PRODUCERS {
            let barrier = Arc::clone(&barrier);
            let archive_root = archive_root.clone();
            let payload = payload.clone();
            let replay_sha = replay_sha.clone();
            handles.push(std::thread::spawn(move || {
                // Line every producer up so they race on the publish step.
                barrier.wait();
                archive_replay(&archive_root, &replay_sha, &payload)
            }));
        }

        let mut stored = 0usize;
        let mut already = 0usize;
        for handle in handles {
            let archived = handle
                .join()
                .expect("producer thread must not panic")
                .unwrap_or_else(|error| {
                    panic!("round {round}: every concurrent producer of identical bytes must succeed, got {error}")
                });
            match archived.outcome() {
                ArchiveOutcome::Stored => stored += 1,
                ArchiveOutcome::AlreadyPresent => already += 1,
            }
            assert_eq!(archived.document_sha256(), replay_sha);
        }
        assert_eq!(stored + already, PRODUCERS);
        assert!(
            stored >= 1,
            "round {round}: at least one producer must publish"
        );

        let directory = archive_root.join(&replay_sha[..2]);
        let objects: Vec<String> = std::fs::read_dir(&directory)
            .unwrap()
            .filter_map(|entry| entry.ok())
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .collect();
        assert_eq!(
            objects
                .iter()
                .filter(|name| *name == &format!("{replay_sha}.json"))
                .count(),
            1,
            "round {round}: exactly one object: {objects:?}"
        );
        assert!(
            objects.iter().all(|name| !name.ends_with(".tmp")),
            "round {round}: no temporary residue may remain: {objects:?}"
        );
        assert_eq!(
            std::fs::read(
                archive_root
                    .join(&replay_sha[..2])
                    .join(format!("{replay_sha}.json"))
            )
            .unwrap(),
            payload
        );

        let _ = std::fs::remove_dir_all(&tmp);
    }
}
