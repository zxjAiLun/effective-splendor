//! Commit C Slice 3: the central runtime completion outlet.
//!
//! Gates:
//!
//! * **A — the completion authority cannot be bypassed** (CLI equivalence is
//!   `crates/splendor-cli/tests/completion_equivalence.rs`). Structurally, the
//!   outlet takes an opaque [`CompletionLeagueV1`] session and never an archive
//!   root, so a second producer cannot open a league that skipped the session
//!   gates or strand the recorded path. At runtime this binary pins the two
//!   consequences: objects land under the protocol root with a content-relative
//!   ledger path, and a league with no identity evidence refuses to open.
//! * **B — same occurrence, same evidence**: idempotent, one match, one object,
//!   one rating-event pair.
//! * **C — same occurrence, changed evidence**: a conflict, with no new match
//!   row and no new rating event. This is the seam Commit C Slice 3 Repair 1
//!   closed: the runtime source's idempotency evidence is the *whole* occurrence
//!   envelope, not just the arena report bytes.
//! * **2b — concurrent producers** of one occurrence still record exactly one
//!   match, one object, and one rating-event pair.
//! * **3 — failure isolation**: a verification, archive, or ordering failure
//!   leaves no ledger row (an ordering failure leaves at most an unreferenced
//!   immutable object).
//!
//! The outlet resolves its archive root from the process working directory, so
//! this binary sandboxes once and every test runs inside that sandbox. That is
//! why the per-object assertions address objects by content address instead of
//! counting files: tests share one protocol root and run in parallel.
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, FullState, GameConfig, Ruleset};
use splendor_replay::record_random_game;
use splendor_studio_league::{
    complete_runtime_occurrence, open_completion_league, open_league, parse_runtime_occurrence,
    runtime_occurrence_evidence_hash, CompletionLeagueV1, CompletionOutcomeV1, CompletionRequestV1,
    IdentityManifestV1, RuntimeOccurrenceV1, StudioLeagueError, StudioLeaguePathsV1,
    RUNTIME_OCCURRENCE_FORMAT,
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

/**/
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

    fn replay_sha(&self) -> String {
        sha256(&self.replay)
    }
}

/// A test league: an existing manifest plus an already-created database.
struct League {
    /// This league's own root; every path below derives from it, so two tests
    /// never share state and no process-wide cwd change is needed.
    root: PathBuf,
    paths: StudioLeaguePathsV1,
}

impl League {
    fn new(label: &str) -> Self {
        let root = tempdir(label);
        let paths = StudioLeaguePathsV1::from_root(&root);
        std::fs::create_dir_all(paths.dir()).unwrap();
        let mut manifest = IdentityManifestV1::new();
        manifest.ensure_local_human("Nick");
        manifest.save(paths.identity()).unwrap();
        let league = Self { root, paths };
        // Create the database once, single-threaded, so concurrent producers
        // contend on completion rather than on schema creation.
        league.session();
        league
    }

    fn root(&self) -> &Path {
        &self.root
    }

    fn paths(&self) -> &StudioLeaguePathsV1 {
        &self.paths
    }

    /// The archive root the ledger's content-relative paths resolve against.
    fn archive_root(&self) -> &Path {
        self.paths.replay_root()
    }

    /// Where the protocol root says one content address lives.
    fn object_path(&self, sha: &str) -> PathBuf {
        self.archive_root()
            .join(&sha[..2])
            .join(format!("{sha}.json"))
    }

    fn session(&self) -> CompletionLeagueV1 {
        open_completion_league(&self.paths, 1_700_000_000).expect("open a completion session")
    }

    fn complete(&self, fixture: &Fixture) -> splendor_studio_league::Result<CompletionOutcomeV1> {
        let mut session = self.session();
        complete_runtime_occurrence(&mut session, &fixture.request("replay.json"))
    }

    /// A read-only connection for assertions. Reading the ledger is not the
    /// authority path; writing through it is impossible.
    fn inspect(&self) -> Connection {
        open_league(self.paths.db()).unwrap()
    }

    fn count(&self, sql: &str) -> i64 {
        self.inspect().query_row(sql, [], |row| row.get(0)).unwrap()
    }

    fn match_count(&self) -> i64 {
        self.count("SELECT COUNT(*) FROM matches")
    }

    fn event_count(&self) -> i64 {
        self.count("SELECT COUNT(*) FROM rating_events")
    }

    fn stored_replay_paths(&self) -> Vec<String> {
        let conn = self.inspect();
        let mut statement = conn
            .prepare("SELECT replay_path FROM matches ORDER BY league_seq")
            .unwrap();
        let rows = statement
            .query_map([], |row| row.get::<_, Option<String>>(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        rows.into_iter().flatten().collect()
    }
}

/// Gate A: the authority is the session, and the archive root is the protocol's.
#[test]
fn the_completion_authority_cannot_be_bypassed() {
    let league = League::new("authority");
    let fixture = Fixture::new("occ-authority", 1_800_000_600, 29);
    let sha = fixture.replay_sha();

    let outcome = league.complete(&fixture).unwrap();
    assert!(outcome.was_inserted());

    // The caller supplied no root, yet the object landed under the protocol
    // root, and the ledger holds only the content-relative path that resolves
    // there and nowhere else.
    assert!(
        league.object_path(&sha).exists(),
        "the object must be published under the protocol root"
    );
    assert_eq!(
        std::fs::canonicalize(outcome.archived.filesystem_path()).unwrap(),
        std::fs::canonicalize(league.object_path(&sha)).unwrap(),
        "the handle names the object under the protocol root"
    );
    let stored = league.stored_replay_paths();
    assert_eq!(stored.len(), 1);
    assert_eq!(stored[0], format!("{}/{sha}.json", &sha[..2]));
    assert!(!Path::new(&stored[0]).is_absolute());

    // A league with no identity evidence cannot open a completion session, so a
    // producer cannot reach the ledger by opening a connection itself.
    let empty_root = tempdir("no-identity-evidence");
    let empty_paths = StudioLeaguePathsV1::from_root(&empty_root);
    let error = open_completion_league(&empty_paths, 1_700_000_000).unwrap_err();
    assert!(
        error
            .to_string()
            .contains("identity manifest does not exist"),
        "the session gate must be unskippable, got: {error}"
    );
}

/// Gate B: the same occurrence with the same evidence is a no-op.
#[test]
fn the_same_occurrence_with_the_same_evidence_is_idempotent() {
    let league = League::new("evidence-same");
    let fixture = Fixture::new("occ-evidence-same", 1_800_000_700, 31);
    let sha = fixture.replay_sha();

    let first = league.complete(&fixture).unwrap();
    assert!(first.was_inserted());
    assert_eq!(first.rating_events(), 2);

    let second = league.complete(&fixture).unwrap();
    assert!(!second.was_inserted(), "identical evidence is idempotent");
    assert_eq!(second.rating_events(), 0);
    assert_eq!(first.match_id(), second.match_id());
    assert_eq!(
        first.record.source_document_hash, second.record.source_document_hash,
        "the evidence hash is deterministic"
    );
    assert_eq!(league.match_count(), 1);
    assert_eq!(league.event_count(), 2, "rating events are not duplicated");
    assert_eq!(second.archived.outcome().as_str(), "already_present");

    // The idempotency evidence is the whole occurrence envelope, and the shared
    // computation is the one the record carries.
    assert_eq!(
        runtime_occurrence_evidence_hash(&fixture.occurrence),
        first.record.source_document_hash
    );
    assert_ne!(
        first.record.source_document_hash,
        sha256(&fixture.report),
        "a runtime source cannot key idempotency on the arena report bytes alone"
    );
    assert_ne!(first.record.source_document_hash, sha);
}

/// Gate C: the same occurrence id carrying different evidence is a conflict.
#[test]
fn the_same_occurrence_with_changed_evidence_is_a_conflict() {
    let league = League::new("evidence-changed");
    let base = Fixture::new("occ-evidence-changed", 1_800_000_800, 37);
    assert!(league.complete(&base).unwrap().was_inserted());

    // (i) same occurrence id, same report, same replay, but a different
    //     configuration document — still a complete, self-consistent occurrence,
    //     so only the evidence hash can reject it.
    let mut config: serde_json::Value = serde_json::from_slice(&base.config).unwrap();
    config["agents"][1]["args"][5] = serde_json::json!("7");
    let changed_config = Fixture::from_documents(
        "occ-evidence-changed",
        1_800_000_800,
        base.report.clone(),
        base.replay.clone(),
        serde_json::to_vec(&config).unwrap(),
    );
    let error = league.complete(&changed_config).unwrap_err();
    assert!(
        matches!(error, StudioLeagueError::SourceConflict { .. }),
        "changed configuration evidence must conflict, got: {error}"
    );

    // (ii) same occurrence id and same `completed_at`, but genuinely different
    //      documents (a different match).
    let changed_match = Fixture::new("occ-evidence-changed", 1_800_000_800, 43);
    let error = league.complete(&changed_match).unwrap_err();
    assert!(
        matches!(error, StudioLeagueError::SourceConflict { .. }),
        "changed occurrence evidence must conflict, got: {error}"
    );

    assert_eq!(league.match_count(), 1, "no new match row");
    assert_eq!(league.event_count(), 2, "no new rating event");
    // The recorded match still names its own object, and the conflicting
    // occurrence's replay is at most an orphan immutable object.
    assert_eq!(
        league.stored_replay_paths(),
        vec![format!(
            "{}/{}.json",
            &base.replay_sha()[..2],
            base.replay_sha()
        )]
    );
    assert!(league.object_path(&changed_match.replay_sha()).exists());
}

/// Gate 2b: concurrent producers of the same occurrence record one match.
#[test]
fn concurrent_producers_of_one_occurrence_record_exactly_one_match() {
    const PRODUCERS: usize = 8;
    let league = League::new("concurrent");
    let fixture = Fixture::new("occ-concurrent", 1_800_000_100, 11);
    let sha = fixture.replay_sha();

    // A shared reference is Copy, so every spawned producer can capture it.
    let producer_paths: &StudioLeaguePathsV1 = league.paths();
    let fixture_ref = &fixture;
    let outcomes: Vec<splendor_studio_league::Result<CompletionOutcomeV1>> =
        std::thread::scope(|scope| {
            let handles: Vec<_> = (0..PRODUCERS)
                .map(|_| {
                    scope.spawn(move || {
                        let mut session = open_completion_league(producer_paths, 1_700_000_000)?;
                        complete_runtime_occurrence(
                            &mut session,
                            &fixture_ref.request("replay.json"),
                        )
                    })
                })
                .collect();
            handles
                .into_iter()
                .map(|handle| handle.join().expect("producer thread"))
                .collect()
        });

    let mut match_ids = Vec::new();
    let mut inserted = 0;
    for outcome in outcomes {
        let outcome = outcome.expect("completion");
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
    assert_eq!(
        league.object_path(&sha),
        league
            .archive_root()
            .join(&sha[..2])
            .join(format!("{sha}.json"))
    );
    assert!(league.object_path(&sha).exists());
    assert_eq!(league.stored_replay_paths().len(), 1);
}

/// Gate 3a: a replay that fails strict verification writes nothing.
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
    assert!(
        !league.object_path(&tampered.replay_sha()).exists(),
        "no archive object for a replay that never verified"
    );
}

/// Gate 3b: an archive that cannot be published writes no ledger row, and never
/// overwrites the immutable object that is already there.
#[test]
fn an_unpublishable_archive_leaves_no_ledger_row_and_no_overwrite() {
    let league = League::new("archive-failure");
    let fixture = Fixture::new("occ-archive-failure", 1_800_000_300, 17);
    let target = league.object_path(&fixture.replay_sha());

    // Occupy the content address with different bytes: this is the corruption
    // case the archive must fail closed on.
    std::fs::create_dir_all(target.parent().unwrap()).unwrap();
    let squatter = b"not the replay that belongs at this address";
    std::fs::write(&target, squatter).unwrap();

    let error = league.complete(&fixture).unwrap_err();
    assert!(
        error.to_string().contains("refusing to overwrite"),
        "the archive must fail closed on a collision, got: {error}"
    );
    assert_eq!(league.match_count(), 0, "no ledger row");
    assert_eq!(league.event_count(), 0);
    assert_eq!(
        std::fs::read(&target).unwrap(),
        squatter,
        "the pre-existing object is left byte-identical"
    );
}

/// Gate 3c + the preserved ordering contract: an out-of-order occurrence fails
/// closed on the canonical-tail guard; the only residue is an unreferenced
/// immutable object.
#[test]
fn a_non_canonical_arrival_fails_closed_and_leaves_only_an_orphan_object() {
    let league = League::new("order");
    let later = Fixture::new("occ-later", 1_800_000_500, 19);
    let earlier = Fixture::new("occ-earlier", 1_800_000_400, 23);

    assert!(league.complete(&later).unwrap().was_inserted());

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
    assert!(league.object_path(&earlier.replay_sha()).exists());
    assert_eq!(
        league.stored_replay_paths(),
        vec![format!(
            "{}/{}.json",
            &later.replay_sha()[..2],
            later.replay_sha()
        )],
        "only the recorded match claims an object"
    );
}
