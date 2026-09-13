//! Commit C Slice 3: the central runtime completion outlet.
//!
//! Three gates:
//! 1. *(CLI equivalence lives in `crates/splendor-cli/tests/`.)*
//! 2. **Idempotency** — completing the same occurrence twice, sequentially or
//!    concurrently from independent connections, yields exactly one match row,
//!    one archive object, and one set of rating events.
//! 3. **Failure isolation** — a verification, archive, or bind failure leaves
//!    no ledger row at all; an ingest failure leaves at most an unreferenced
//!    immutable archive object.
//!
//! Plus the preserved ordering contract: the outlet never bypasses the
//! canonical-tail guard, so a non-canonical arrival fails closed and needs a
//! canonical-order retry or a rebuild.
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, FullState, GameConfig, Ruleset};
use splendor_replay::record_random_game;
use splendor_studio_league::{
    complete_runtime_occurrence, open_completion_league, parse_runtime_occurrence,
    CompletionRequestV1, IdentityManifestV1, RuntimeOccurrenceV1, RUNTIME_OCCURRENCE_FORMAT,
};
use std::path::{Path, PathBuf};

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "splendor-completion-outlet-{}-{}",
        std::process::id(),
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// The three documents a finished arena occurrence produces.
fn occurrence_documents(game_id: &str, seed: u64) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
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

/// One finished occurrence: the parsed envelope plus the exact documents.
struct Fixture {
    occurrence: RuntimeOccurrenceV1,
    report: Vec<u8>,
    replay: Vec<u8>,
    config: Vec<u8>,
}

impl Fixture {
    fn new(occurrence_id: &str, completed_at: i64, seed: u64) -> Self {
        let (report, replay, config) = occurrence_documents(&format!("game-{occurrence_id}"), seed);
        Self::from_documents(occurrence_id, completed_at, report, replay, config)
    }

    /// Build a fixture whose envelope matches exactly these documents, so any
    /// later failure is genuinely about the documents and not a hash mismatch.
    fn from_documents(
        occurrence_id: &str,
        completed_at: i64,
        report: Vec<u8>,
        replay: Vec<u8>,
        config: Vec<u8>,
    ) -> Self {
        let envelope = serde_json::to_vec(&serde_json::json!({
            "format": RUNTIME_OCCURRENCE_FORMAT,
            "version": 1,
            "occurrence_id": occurrence_id,
            "completed_at": completed_at,
            "report_sha256": sha256(&report),
            "replay_sha256": sha256(&replay),
            "config_sha256": sha256(&config),
        }))
        .unwrap();
        let occurrence = parse_runtime_occurrence(&envelope)
            .unwrap()
            .expect("a well-formed envelope");
        Self {
            occurrence,
            report,
            replay,
            config,
        }
    }

    fn request<'a>(&'a self, source_path: &'a str) -> CompletionRequestV1<'a> {
        CompletionRequestV1 {
            occurrence: &self.occurrence,
            report_bytes: &self.report,
            replay_bytes: &self.replay,
            config_bytes: &self.config,
            replay_source_path: source_path,
        }
    }
}

/// A test league: an existing manifest plus an already-created database.
struct League {
    archive_root: PathBuf,
    db_path: PathBuf,
    identity_path: PathBuf,
}

impl League {
    fn new(label: &str) -> Self {
        let root = tempdir(label);
        let league = Self {
            archive_root: root.join("replays"),
            db_path: root.join("league.sqlite3"),
            identity_path: root.join("identity.json"),
        };
        let mut manifest = IdentityManifestV1::new();
        manifest.ensure_local_human("Nick");
        manifest.save(&league.identity_path).unwrap();
        // Create the database once, single-threaded, so concurrent producers
        // contend on completion rather than on schema creation.
        let conn =
            open_completion_league(&league.db_path, &league.identity_path, 1_700_000_000).unwrap();
        drop(conn);
        league
    }

    fn open(&self) -> Connection {
        open_completion_league(&self.db_path, &self.identity_path, 1_700_000_000).unwrap()
    }

    fn complete(
        &self,
        fixture: &Fixture,
    ) -> splendor_studio_league::Result<splendor_studio_league::CompletionOutcomeV1> {
        let mut conn = self.open();
        complete_runtime_occurrence(
            &mut conn,
            &self.archive_root,
            &fixture.request("replay.json"),
        )
    }

    fn match_count(&self) -> i64 {
        self.open()
            .query_row("SELECT COUNT(*) FROM matches", [], |row| row.get(0))
            .unwrap()
    }

    fn event_count(&self) -> i64 {
        self.open()
            .query_row("SELECT COUNT(*) FROM rating_events", [], |row| row.get(0))
            .unwrap()
    }

    /// Every immutable archive object on disk (temp files are not objects).
    fn archive_objects(&self) -> Vec<PathBuf> {
        fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
            let Ok(entries) = std::fs::read_dir(dir) else {
                return;
            };
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    walk(&path, out);
                } else if path.extension().and_then(|ext| ext.to_str()) == Some("json") {
                    out.push(path);
                }
            }
        }
        let mut out = Vec::new();
        walk(&self.archive_root, &mut out);
        out.sort();
        out
    }
}

/// Gate 2a: the same occurrence completed twice is one match.
#[test]
fn completing_one_occurrence_twice_records_exactly_one_match() {
    let league = League::new("idempotent");
    let fixture = Fixture::new("occ-idempotent", 1_800_000_000, 7);

    let first = league.complete(&fixture).unwrap();
    assert!(first.was_inserted(), "first completion inserts");
    assert_eq!(first.rating_events(), 2);
    assert!(first.receipt.rating_ineligible_reason.is_none());

    let second = league.complete(&fixture).unwrap();
    assert!(!second.was_inserted(), "second completion is idempotent");
    assert_eq!(second.rating_events(), 0);
    assert_eq!(first.match_id(), second.match_id());

    assert_eq!(league.match_count(), 1);
    assert_eq!(league.event_count(), 2, "rating events are not duplicated");
    assert_eq!(league.archive_objects().len(), 1, "one archive object");
}

/// Gate 2b: concurrent producers of the same occurrence still record one match.
#[test]
fn concurrent_producers_of_one_occurrence_record_exactly_one_match() {
    const PRODUCERS: usize = 8;
    let league = League::new("concurrent");
    let fixture = Fixture::new("occ-concurrent", 1_800_000_100, 11);
    let expected_sha = sha256(&fixture.replay);

    let handles: Vec<_> = (0..PRODUCERS)
        .map(|_| {
            let db_path = league.db_path.clone();
            let identity_path = league.identity_path.clone();
            let archive_root = league.archive_root.clone();
            let report = fixture.report.clone();
            let replay = fixture.replay.clone();
            let config = fixture.config.clone();
            let occurrence_id = fixture.occurrence.occurrence_id.clone();
            let completed_at = fixture.occurrence.completed_at;
            std::thread::spawn(move || {
                let fixture = Fixture {
                    occurrence: RuntimeOccurrenceV1 {
                        format: RUNTIME_OCCURRENCE_FORMAT.to_string(),
                        version: 1,
                        occurrence_id,
                        completed_at,
                        report_sha256: sha256(&report),
                        replay_sha256: sha256(&replay),
                        config_sha256: sha256(&config),
                    },
                    report,
                    replay,
                    config,
                };
                let mut conn =
                    open_completion_league(&db_path, &identity_path, 1_700_000_000).unwrap();
                complete_runtime_occurrence(
                    &mut conn,
                    &archive_root,
                    &fixture.request("replay.json"),
                )
            })
        })
        .collect();

    let mut match_ids = Vec::new();
    let mut inserted = 0;
    for handle in handles {
        let outcome = handle.join().expect("producer thread").expect("completion");
        assert!(outcome.rating_events() <= 2, "no double-rated events");
        if outcome.was_inserted() {
            inserted += 1;
            assert_eq!(outcome.rating_events(), 2);
        }
        match_ids.push(outcome.match_id().to_string());
    }

    assert_eq!(inserted, 1, "exactly one producer inserts");
    assert!(
        match_ids.windows(2).all(|pair| pair[0] == pair[1]),
        "every producer resolves the same match identity: {match_ids:?}"
    );
    assert_eq!(league.match_count(), 1);
    assert_eq!(league.event_count(), 2);
    let objects = league.archive_objects();
    assert_eq!(objects.len(), 1, "exactly one archive object");
    assert_eq!(
        objects[0].file_name().unwrap().to_str().unwrap(),
        format!("{expected_sha}.json")
    );
}

/// Gate 3a: a replay that fails strict verification writes neither a match row
/// nor an archive object.
#[test]
fn a_replay_that_fails_verification_leaves_no_ledger_row_and_no_object() {
    let league = League::new("verify-failure");
    let good = Fixture::new("occ-tampered", 1_800_000_200, 13);

    // Drop the step list, then recompute the envelope over the tampered bytes:
    // the envelope is consistent, so the only thing that can reject this is
    // strict replay verification.
    let mut replay: serde_json::Value = serde_json::from_slice(&good.replay).unwrap();
    replay["steps"] = serde_json::json!([]);
    let tampered = Fixture::from_documents(
        "occ-tampered",
        1_800_000_200,
        good.report.clone(),
        serde_json::to_vec(&replay).unwrap(),
        good.config.clone(),
    );

    let error = league.complete(&tampered).unwrap_err();
    assert!(!error.to_string().is_empty());
    assert_eq!(league.match_count(), 0, "no ledger row");
    assert_eq!(league.event_count(), 0);
    assert!(league.archive_objects().is_empty(), "no archive object");
}

/// Gate 3b: an archive root that cannot be created writes no ledger row.
#[test]
fn an_unusable_archive_root_leaves_no_ledger_row() {
    let league = League::new("archive-failure");
    let fixture = Fixture::new("occ-archive-failure", 1_800_000_300, 17);

    // A *file* where the archive root must be a directory.
    std::fs::write(&league.archive_root, b"not a directory").unwrap();

    let error = league.complete(&fixture).unwrap_err();
    assert!(!error.to_string().is_empty());
    assert_eq!(league.match_count(), 0, "no ledger row");
    assert_eq!(league.event_count(), 0);
}

/// Gate 3c + the preserved ordering contract: an out-of-order occurrence fails
/// closed on the canonical-tail guard; the only residue is an unreferenced
/// immutable archive object.
#[test]
fn a_non_canonical_arrival_fails_closed_and_leaves_only_an_orphan_object() {
    let league = League::new("order");
    let later = Fixture::new("occ-later", 1_800_000_500, 19);
    let earlier = Fixture::new("occ-earlier", 1_800_000_400, 23);

    let first = league.complete(&later).unwrap();
    assert!(first.was_inserted());
    let objects_after_first = league.archive_objects().len();

    let error = league.complete(&earlier).unwrap_err();
    let message = error.to_string();
    assert!(
        message.contains("canonical") || message.contains("order"),
        "the canonical-tail guard must fail closed, got: {message}"
    );

    assert_eq!(league.match_count(), 1, "the out-of-order match is absent");
    assert_eq!(league.event_count(), 2);
    // The object was published before the ledger write: the residue is an
    // unreferenced immutable object, never a match pointing at nothing.
    assert_eq!(
        league.archive_objects().len(),
        objects_after_first + 1,
        "at most an orphan archive object"
    );
    let conn = league.open();
    let referenced: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM matches WHERE replay_storage = 'archive'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(referenced, 1, "only the recorded match claims an object");
}
