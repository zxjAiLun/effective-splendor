//! Commit C Slice 1 Repair 1: runtime occurrence authority.
//!
//! The three targeted gates:
//! 1. two different occurrence ids with byte-identical documents are **two**
//!    occurrences and both enter the ledger (content equality is not occurrence
//!    equality);
//! 2. the same occurrence id is idempotent (same bytes -> `AlreadyPresent`) and
//!    conflicting (same id, changed document -> conflict);
//! 3. deleting the database and rebuilding from the same durable occurrence
//!    evidence reproduces the live ingest exactly (league order, rating
//!    events, leaderboard).
//!
//! Plus the narrow guards: a runtime configuration without seed evidence is
//! rejected, out-of-order incremental appends are rejected, and envelope
//! document hashes must match the provided bytes.
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, FullState, GameConfig, Ruleset};
use splendor_replay::record_random_game;
use splendor_studio_league::{
    build_historical_corpus, ensure_rating_config, ingest_batch_canonical, ingest_match,
    initialise, leaderboard, match_receipt, open_league, parse_runtime_occurrence,
    runtime_match_record, sync_identity_manifest, HistoricalDryRunConfig, IdentityManifestV1,
    IngestOutcome, ReplayStorage, ReplayVerification, RUNTIME_OCCURRENCE_FORMAT,
};
use std::path::{Path, PathBuf};

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "splendor-runtime-ingest-{}-{}",
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

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// The three documents a finished arena occurrence produces. Two seats carry
/// different search budgets so they are two distinct policies.
fn occurrence_documents(
    game_id: &str,
    seed: u64,
) -> (
    Vec<u8>, // report
    Vec<u8>, // replay
    Vec<u8>, // config
) {
    let (_, replay) = record_random_game(2, seed, 101).unwrap();
    assert!(FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset: Ruleset::base_v1(),
    })
    .is_ok());
    let fingerprint = ruleset_fingerprint(&Ruleset::base_v1());
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

/// The durable occurrence envelope for one set of documents.
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

fn build_record(
    occurrence_id: &str,
    completed_at: i64,
    report: &[u8],
    replay: &[u8],
    config: &[u8],
) -> splendor_studio_league::StudioMatchRecordV1 {
    let envelope_bytes = occurrence_envelope(occurrence_id, completed_at, report, replay, config);
    let envelope = parse_runtime_occurrence(&envelope_bytes)
        .unwrap()
        .expect("a well-formed envelope");
    runtime_match_record(
        &envelope,
        report,
        replay,
        config,
        "runtime/match-replay.json",
    )
    .unwrap()
}

fn fresh_league(path: &Path, manifest: &IdentityManifestV1) {
    let mut conn = open_league(path).unwrap();
    initialise(&conn).unwrap();
    ensure_rating_config(&conn).unwrap();
    sync_identity_manifest(&conn, manifest, 1_700_000_000).unwrap();
}

fn test_manifest() -> IdentityManifestV1 {
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    manifest
}

type MatchRows = Vec<(String, i64)>;
type EventRows = Vec<(String, String, f64, f64, f64, f64)>;
type BoardRows = Vec<(String, i32, u32, u32, u32, u32, u32)>;

fn league_state(conn: &Connection) -> (MatchRows, EventRows, BoardRows) {
    let matches: MatchRows = conn
        .prepare("SELECT match_id, league_seq FROM matches ORDER BY league_seq")
        .unwrap()
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    let events: EventRows = conn
        .prepare(
            "SELECT match_id, participant_id, elo_before, elo_after, delta, score
              FROM rating_events ORDER BY league_seq, participant_id",
        )
        .unwrap()
        .query_map([], |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
                row.get(5)?,
            ))
        })
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap();
    let board: BoardRows = leaderboard(conn)
        .unwrap()
        .into_iter()
        .map(|row| {
            (
                row.participant_id,
                row.elo,
                row.rated_games,
                row.rated_wins,
                row.rated_ties,
                row.rated_losses,
                row.recorded_games,
            )
        })
        .collect();
    (matches, events, board)
}

#[test]
fn a_fresh_occurrence_ingests_through_the_authority_chain() {
    let tmp = tempdir("e2e");
    let (report, replay, config) = occurrence_documents("runtime-game-0001", 7_700_001);
    let record = build_record("occ-e2e-0001", 1_730_000_100, &report, &replay, &config);

    // The envelope is the occurrence authority: identity and ordering come
    // from it, never from content.
    assert_eq!(record.source_identity, "runtime:occ-e2e-0001");
    assert_eq!(record.played_at, Some(1_730_000_100));
    assert_eq!(record.replay.storage(), ReplayStorage::InPlaceReference);
    assert_eq!(record.replay.verification(), ReplayVerification::Verified);
    assert_ne!(
        record.seats[0].policy_identity, record.seats[1].policy_identity,
        "different budgets are two policies, never a fabricated self-match"
    );
    assert!(!record.diagnostic);

    let db_path = tmp.join("league.sqlite3");
    fresh_league(&db_path, &test_manifest());
    let mut conn = open_league(&db_path).unwrap();
    let outcome = ingest_match(&mut conn, &record).unwrap();
    assert!(matches!(
        outcome,
        IngestOutcome::Inserted {
            rating_events: 2,
            ..
        }
    ));
    let receipt = match_receipt(&conn, &record.match_id())
        .unwrap()
        .expect("the match is recorded");
    assert!(receipt.rating_ineligible_reason.is_none());
    assert_eq!(receipt.elo_events.len(), 2);
    for event in &receipt.elo_events {
        assert!((event.elo_before - 1500.0).abs() < f64::EPSILON);
        assert!(event.elo_after != event.elo_before);
    }

    // Re-offering the same occurrence is a no-op.
    assert!(matches!(
        ingest_match(&mut conn, &record).unwrap(),
        IngestOutcome::AlreadyPresent { .. }
    ));
    assert_eq!(
        match_receipt(&conn, &record.match_id())
            .unwrap()
            .unwrap()
            .elo_events
            .len(),
        2
    );
    let _ = std::fs::remove_dir_all(&tmp);
}

/// Gate 1 (P1-1): two genuinely played occurrences are two occurrences even
/// when deterministic execution produced byte-identical documents.
#[test]
fn two_occurrences_with_identical_documents_both_enter_the_league() {
    let tmp = tempdir("gate1");
    let (report, replay, config) = occurrence_documents("runtime-game-9001", 7_700_002);
    let first = build_record("occ-first", 1_730_000_100, &report, &replay, &config);
    let second = build_record("occ-second", 1_730_000_200, &report, &replay, &config);
    assert_ne!(first.match_id(), second.match_id());

    let db_path = tmp.join("league.sqlite3");
    fresh_league(&db_path, &test_manifest());
    let mut conn = open_league(&db_path).unwrap();
    ingest_match(&mut conn, &first).unwrap();
    ingest_match(&mut conn, &second).unwrap();

    let (matches, events, _) = league_state(&conn);
    assert_eq!(matches.len(), 2, "both occurrences are recorded");
    assert_eq!(events.len(), 4, "both occurrences rated");
    let ids: std::collections::BTreeSet<&str> =
        events.iter().map(|event| event.0.as_str()).collect();
    assert_eq!(ids.len(), 2, "two distinct match identities");
    let _ = std::fs::remove_dir_all(&tmp);
}

/// Gate 2: the same occurrence id is idempotent with the same bytes and a
/// conflict with changed bytes (the ledger's `(source_kind, source_identity)`
/// authority, per Commit A).
#[test]
fn same_occurrence_id_is_idempotent_or_conflicting() {
    let tmp = tempdir("gate2");
    let (report, replay, config) = occurrence_documents("runtime-game-9002", 7_700_003);
    let record = build_record("occ-same", 1_730_000_100, &report, &replay, &config);

    let db_path = tmp.join("league.sqlite3");
    fresh_league(&db_path, &test_manifest());
    let mut conn = open_league(&db_path).unwrap();
    ingest_match(&mut conn, &record).unwrap();

    // Same identity, same bytes: idempotent no-op.
    assert!(matches!(
        ingest_match(&mut conn, &record).unwrap(),
        IngestOutcome::AlreadyPresent { .. }
    ));

    // Same identity, different document: conflict.
    let mut changed = record.clone();
    changed.source_document_hash = record.source_document_hash[..63].to_string();
    changed.source_document_hash.push('0');
    let error = ingest_match(&mut conn, &changed).unwrap_err();
    assert!(
        error.to_string().to_lowercase().contains("conflict"),
        "unexpected error: {error}"
    );
    let _ = std::fs::remove_dir_all(&tmp);
}

/// Gate 3 (P1-2): deleting the database and rebuilding from the same durable
/// occurrence evidence reproduces the live ingest exactly.
#[test]
fn rebuild_from_occurrence_evidence_reproduces_the_live_ingest() {
    let tmp = tempdir("gate3");
    // Three fixtures, each with its four documents colocated; completed_at
    // ascending so the canonical order is a, b, c.
    let fixtures = [
        ("occ-a", "runtime-game-a", 7_700_010u64, 1_730_000_100i64),
        ("occ-b", "runtime-game-b", 7_700_011, 1_730_000_200),
        ("occ-c", "runtime-game-c", 7_700_012, 1_730_000_300),
    ];
    let mut live_records = Vec::new();
    for (occurrence_id, game_id, seed, completed_at) in &fixtures {
        let (report, replay, config) = occurrence_documents(game_id, *seed);
        let envelope = occurrence_envelope(occurrence_id, *completed_at, &report, &replay, &config);
        write_file(&tmp, &format!("{occurrence_id}/arena-report.json"), &report);
        write_file(&tmp, &format!("{occurrence_id}/match-replay.json"), &replay);
        write_file(&tmp, &format!("{occurrence_id}/match-config.json"), &config);
        write_file(
            &tmp,
            &format!("{occurrence_id}/runtime-occurrence.json"),
            &envelope,
        );
        live_records.push(build_record(
            occurrence_id,
            *completed_at,
            &report,
            &replay,
            &config,
        ));
    }

    // Live ingest in completion order.
    let manifest = test_manifest();
    let live_db = tmp.join("live.sqlite3");
    fresh_league(&live_db, &manifest);
    let mut live_conn = open_league(&live_db).unwrap();
    for record in &live_records {
        ingest_match(&mut live_conn, record).unwrap();
    }

    // Rebuild: scan the same occurrence evidence and ingest the canonical
    // records into a fresh database.
    let (report, records) = build_historical_corpus(&HistoricalDryRunConfig {
        roots: vec![tmp.to_string_lossy().to_string()],
        ..Default::default()
    })
    .unwrap();
    assert_eq!(report.builder_failures, 0, "{:?}", report.failure_samples);
    assert_eq!(report.runtime_occurrences_seen, 3);
    assert_eq!(report.runtime_occurrences_built, 3);
    assert_eq!(records.len(), 3);
    assert!(records
        .iter()
        .all(|record| record.source_identity.starts_with("runtime:")));

    let rebuild_db = tmp.join("rebuild.sqlite3");
    fresh_league(&rebuild_db, &manifest);
    let mut rebuild_conn = open_league(&rebuild_db).unwrap();
    ingest_batch_canonical(&mut rebuild_conn, &records).unwrap();

    let live_state = league_state(&live_conn);
    let rebuild_state = league_state(&rebuild_conn);
    assert_eq!(
        live_state.0, rebuild_state.0,
        "league_seq assignment must be identical"
    );
    assert_eq!(
        live_state.1, rebuild_state.1,
        "the Elo history must be identical"
    );
    assert_eq!(
        live_state.2, rebuild_state.2,
        "the leaderboard must be identical"
    );
    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn out_of_order_runtime_occurrences_are_rejected() {
    let tmp = tempdir("order");
    let (report, replay, config) = occurrence_documents("runtime-game-9003", 7_700_004);
    let first = build_record("occ-first", 1_730_000_200, &report, &replay, &config);

    let db_path = tmp.join("league.sqlite3");
    fresh_league(&db_path, &test_manifest());
    let mut conn = open_league(&db_path).unwrap();
    ingest_match(&mut conn, &first).unwrap();

    // A later-arriving occurrence completed *earlier* (or at the same second)
    // would diverge from the canonical rebuild order: fail closed.
    let simultaneous = build_record("occ-same-time", 1_730_000_200, &report, &replay, &config);
    let error = ingest_match(&mut conn, &simultaneous).unwrap_err();
    assert!(
        error.to_string().contains("canonical rebuild order"),
        "unexpected error: {error}"
    );
    let earlier = build_record("occ-earlier", 1_730_000_100, &report, &replay, &config);
    let error = ingest_match(&mut conn, &earlier).unwrap_err();
    assert!(
        error.to_string().contains("canonical rebuild order"),
        "unexpected error: {error}"
    );
    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn incomplete_or_mismatched_occurrence_evidence_is_rejected() {
    let tmp = tempdir("evidence");
    let (report, replay, config) = occurrence_documents("runtime-game-9004", 7_700_005);

    // P1-3: a fresh runtime configuration without seed evidence is rejected.
    let seedless: serde_json::Value = serde_json::from_slice(&config).unwrap();
    let mut seedless = seedless;
    seedless.as_object_mut().unwrap().remove("seed");
    let seedless = serde_json::to_vec(&seedless).unwrap();
    let envelope_bytes =
        occurrence_envelope("occ-seedless", 1_730_000_100, &report, &replay, &seedless);
    let envelope = parse_runtime_occurrence(&envelope_bytes).unwrap().unwrap();
    let error =
        runtime_match_record(&envelope, &report, &replay, &seedless, "x/replay.json").unwrap_err();
    assert!(
        error.to_string().contains("no seed"),
        "unexpected error: {error}"
    );

    // A wrong seed is still rejected: the config's seed does not reproduce the
    // report's seed commitment.
    let (_, _, wrong_config) = occurrence_documents("runtime-game-9004", 7_700_006);
    let envelope_bytes = occurrence_envelope(
        "occ-wrong-seed",
        1_730_000_101,
        &report,
        &replay,
        &wrong_config,
    );
    let envelope = parse_runtime_occurrence(&envelope_bytes).unwrap().unwrap();
    let error = runtime_match_record(&envelope, &report, &replay, &wrong_config, "x/replay.json")
        .unwrap_err();
    assert!(
        error.to_string().contains("seed commitment"),
        "unexpected error: {error}"
    );

    // A tampered replay document fails the envelope's hash agreement.
    let mut broken_replay = replay.clone();
    let middle = broken_replay.len() / 2;
    broken_replay[middle] ^= 0x20;
    let envelope_bytes = occurrence_envelope(
        "occ-tampered",
        1_730_000_102,
        &report,
        &broken_replay,
        &config,
    );
    let envelope = parse_runtime_occurrence(&envelope_bytes).unwrap().unwrap();
    assert!(
        runtime_match_record(&envelope, &report, &broken_replay, &config, "x/replay.json").is_err()
    );
    let _ = std::fs::remove_dir_all(&tmp);
}
