//! Commit C Slice 1: a just-finished arena occurrence enters the league
//! through the existing authority chain — strict parse, replay verification,
//! the run's own configuration as exact policy evidence, `ingest_match`,
//! eligibility, and 0 or 2 Elo events — with **no corpus scan** and no new
//! Elo logic.
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, FullState, GameConfig, Ruleset};
use splendor_replay::record_random_game;
use splendor_studio_league::{
    ensure_rating_config, ingest_match, initialise, match_receipt, open_league,
    runtime_match_record, sync_identity_manifest, IdentityManifestV1, IngestOutcome, ReplayStorage,
    ReplayVerification, SeatPolicyIdentityV1,
};
use std::path::PathBuf;

const RUNTIME_NAME: &str = "effective-splendor-determinization-agent-v1";
const RUNTIME_DB: &str = "league.runtime-slice.sqlite3";

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

/// The three documents a finished arena occurrence produces: report, replay,
/// and the run's own configuration — with two *different* search budgets so
/// the seats are two distinct policies.
fn occurrence(
    game_id: &str,
    seed: u64,
    seat0_nodes: &str,
    seat1_nodes: &str,
) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
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
            replay.final_state_hash.as_str().to_string(),
        ),
    );
    let config = serde_json::json!({
        "game_id": game_id,
        "seed": seed,
        "agents": [
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-count", "4",
                "--max-depth-turns", "1", "--max-nodes", seat0_nodes ] },
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-count", "4",
                "--max-depth-turns", "1", "--max-nodes", seat1_nodes ] }
        ]
    });
    (
        serde_json::to_vec(&report).unwrap(),
        serde_json::to_vec(&replay).unwrap(),
        serde_json::to_vec(&config).unwrap(),
    )
}

fn fresh_league(path: &std::path::Path) {
    let mut conn = open_league(path).unwrap();
    initialise(&conn).unwrap();
    ensure_rating_config(&conn).unwrap();
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    sync_identity_manifest(&conn, &manifest, 1_700_000_000).unwrap();
}

#[test]
fn a_fresh_occurrence_ingests_through_the_authority_chain() {
    let tmp = tempdir("e2e");
    let (report, replay, config) = occurrence("runtime-game-0001", 7_700_001, "2000", "1");
    let record = runtime_match_record(
        &report,
        &replay,
        &config,
        "local-artifacts/runtime-matches/game-0001/match-replay.json",
    )
    .unwrap();

    // Occurrence identity is content-derived in the runtime namespace.
    assert!(record.source_identity.starts_with("runtime-sha256:"));
    assert_eq!(record.source_document_hash.len(), 64);
    assert_eq!(record.played_at, None, "canonical-order Elo, no fake clock");
    assert_eq!(record.replay.storage(), ReplayStorage::InPlaceReference);
    assert_eq!(record.replay.verification(), ReplayVerification::Verified);
    assert_eq!(
        record.replay.path.as_deref(),
        Some("local-artifacts/runtime-matches/game-0001/match-replay.json")
    );
    // The run's own config resolves both seats to distinct exact policies.
    assert!(matches!(
        record.seats[0].policy_identity,
        SeatPolicyIdentityV1::Resolved { .. }
    ));
    assert!(matches!(
        record.seats[1].policy_identity,
        SeatPolicyIdentityV1::Resolved { .. }
    ));
    assert_ne!(
        record.seats[0].policy_identity, record.seats[1].policy_identity,
        "different budgets are two policies, never a fabricated self-match"
    );
    assert!(!record.diagnostic);

    let db_path = tmp.join(RUNTIME_DB);
    fresh_league(&db_path);
    let mut conn = open_league(&db_path).unwrap();
    let outcome = ingest_match(&mut conn, &record).unwrap();
    let rating_events = match &outcome {
        IngestOutcome::Inserted { rating_events, .. } => *rating_events,
        IngestOutcome::AlreadyPresent { .. } => panic!("first ingest must insert"),
    };
    assert_eq!(
        rating_events, 2,
        "an eligible 1v1 match produces exactly two Elo events"
    );

    let receipt = match_receipt(&conn, &record.match_id())
        .unwrap()
        .expect("the match is recorded");
    assert!(
        receipt.rating_ineligible_reason.is_none(),
        "the match must be eligible, found {:?}",
        receipt.rating_ineligible_reason
    );
    assert_eq!(receipt.elo_events.len(), 2);
    for event in &receipt.elo_events {
        assert!((event.elo_before - 1500.0).abs() < f64::EPSILON);
        assert!(event.elo_after != event.elo_before, "Elo must move");
    }

    // Re-offering the same occurrence is a no-op, not a second rating.
    let outcome_again = ingest_match(&mut conn, &record).unwrap();
    assert!(matches!(
        outcome_again,
        IngestOutcome::AlreadyPresent { .. }
    ));
    let receipt_again = match_receipt(&conn, &record.match_id()).unwrap().unwrap();
    assert_eq!(receipt_again.elo_events.len(), 2, "no extra Elo events");
    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn tampered_occurrence_documents_are_rejected() {
    let tmp = tempdir("tamper");
    let (report, replay, config) = occurrence("runtime-game-0002", 7_700_002, "2000", "1");

    // A flipped byte in the replay document must be rejected by strict parsing
    // or by full verification — never ingested.
    let mut broken_replay = replay.clone();
    let middle = broken_replay.len() / 2;
    broken_replay[middle] ^= 0x20;
    assert!(runtime_match_record(&report, &broken_replay, &config, "x/replay.json").is_err());

    // A report whose terminal facts disagree with the replay must be rejected.
    let mut tampered_report = report.clone();
    let as_text = String::from_utf8(tampered_report.clone()).unwrap();
    // Swap the first two recorded scores inside the report document.
    let tampered_text = as_text.replace("\"scores\":[15,", "\"scores\":[16,");
    if tampered_text != as_text {
        tampered_report = tampered_text.into_bytes();
        assert!(
            runtime_match_record(&tampered_report, &replay, &config, "x/replay.json").is_err(),
            "report/replay disagreement must fail closed"
        );
    }

    // A configuration from another match (different seed) cannot claim this
    // occurrence: its seed does not reproduce the report's seed commitment.
    let (_, _, wrong_config) = occurrence("runtime-game-0002", 7_700_003, "2000", "1");
    assert!(runtime_match_record(&report, &replay, &wrong_config, "x/replay.json").is_err());
    let _ = std::fs::remove_dir_all(&tmp);
}

#[test]
fn the_same_document_cannot_reingest_under_a_new_identity() {
    let tmp = tempdir("dupdoc");
    let (report, replay, config) = occurrence("runtime-game-0003", 7_700_004, "2000", "1");
    let record = runtime_match_record(&report, &replay, &config, "x/replay.json").unwrap();

    let db_path = tmp.join(RUNTIME_DB);
    fresh_league(&db_path);
    let mut conn = open_league(&db_path).unwrap();
    ingest_match(&mut conn, &record).unwrap();

    // A second occurrence key claiming the same document bytes is refused —
    // this is what stops a historical document re-offered through the runtime
    // path from double-counting Elo.
    let mut cloned = record.clone();
    cloned.source_identity = format!("runtime-sha256:{}0", &record.source_document_hash[..63]);
    assert_ne!(cloned.source_identity, record.source_identity);
    let error = ingest_match(&mut conn, &cloned).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("cannot become a second occurrence"),
        "unexpected error: {error}"
    );
    let receipt = match_receipt(&conn, &record.match_id()).unwrap().unwrap();
    assert_eq!(receipt.elo_events.len(), 2, "Elo must not move");
    let _ = std::fs::remove_dir_all(&tmp);
}
