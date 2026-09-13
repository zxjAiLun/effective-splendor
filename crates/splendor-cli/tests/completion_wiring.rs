//! Commit C Next Slice gate: the completion producer wiring.
//!
//! These are the three gates the owner prescribed for the first real runtime
//! completion path. They run **real arena matches** with real subprocess agents
//! and go through the process boundary (`splendor studio-league-complete-match`
//! / `splendor studio-league-complete`), not through library calls:
//!
//! 1. a real runner completes -> all four evidence documents exist -> the
//!    occurrence enters the Studio ledger and the content-addressed archive;
//! 2. completion is forced to fail -> the match evidence is still complete and
//!    unmodified, the ledger holds no fake success, and retrying **completion
//!    alone** books it, without re-running the match;
//! 3. the same completion is triggered twice -> `already_present`, no duplicate
//!    Elo.
//!
//! The essential property under test is that a completed match and a successful
//! Studio completion are two independent facts: nothing here may let a
//! completion failure masquerade as a match failure, and nothing may let the
//! wiring invent a second way to book an occurrence.
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use splendor_studio_league::{
    parse_runtime_occurrence, IdentityManifestV1, STUDIO_LEAGUE_REPLAY_DIR,
};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

fn tmp_dir(label: &str) -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-completion-wiring-{}-{}-{}",
        std::process::id(),
        n,
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

fn write_file(dir: &Path, name: &str, contents: &str) -> PathBuf {
    let path = dir.join(name);
    std::fs::write(&path, contents).expect("write file");
    path
}

/// A real two-seat arena config with **two genuinely distinct policies**.
///
/// Both seats are real subprocesses of this same binary, so the match is
/// genuinely run rather than simulated. The seats are deliberately different
/// agent kinds (`agent-heuristic` vs `agent-random`), which report distinct
/// runtime identities (`splendor-cli-heuristic` / `splendor-cli-random`).
///
/// Two seats of the *same* agent kind are a self-match: the eligibility rules
/// correctly mark it ineligible (`self_match`) and emit zero rating events. That
/// would make the idempotency gate vacuous — "no duplicate Elo" would hold
/// because there is never any Elo — so the gates use distinct policies and load
/// the real rating path.
fn real_config(dir: &Path, game_id: &str, seed: u64, seat_seeds: [u64; 2]) -> PathBuf {
    let program = bin().to_string_lossy().into_owned();
    let config = serde_json::json!({
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 10_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            { "program": program, "args": ["agent-heuristic", "--seed", seat_seeds[0].to_string()] },
            { "program": program, "args": ["agent-random", "--seed", seat_seeds[1].to_string()] },
        ]
    });
    write_file(
        dir,
        "config.json",
        &serde_json::to_string_pretty(&config).expect("serialize config"),
    )
}

/// A sandbox holding the league database, the identity manifest, and the
/// protocol archive root, so one test never sees another test's league.
struct Sandbox {
    root: PathBuf,
    db: PathBuf,
    identity: PathBuf,
}

impl Sandbox {
    fn new(label: &str) -> Self {
        let root = tmp_dir(label);
        let identity = root.join("identity.json");
        let mut manifest = IdentityManifestV1::new();
        manifest.ensure_local_human("Nick");
        manifest.save(&identity).expect("save identity manifest");
        Self {
            db: root.join("league.sqlite3"),
            identity,
            root,
        }
    }

    /// The archive root the protocol constant names, resolved inside this
    /// sandbox. The commands under test run with `cwd` set to `root`, so the
    /// relative protocol root lands here.
    fn archive_root(&self) -> PathBuf {
        self.root.join(STUDIO_LEAGUE_REPLAY_DIR)
    }

    fn open_db(&self) -> Connection {
        Connection::open(&self.db).expect("open league db")
    }

    fn match_rows(&self) -> Vec<(String, String, String)> {
        let conn = self.open_db();
        let mut statement = conn
            .prepare(
                "SELECT source_identity, replay_storage, replay_path FROM matches ORDER BY league_seq",
            )
            .expect("prepare");
        let rows = statement
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .expect("query")
            .collect::<Result<Vec<_>, _>>()
            .expect("collect");
        rows
    }

    fn rating_event_count(&self) -> i64 {
        let conn = self.open_db();
        conn.query_row("SELECT COUNT(*) FROM rating_events", [], |row| row.get(0))
            .expect("count rating events")
    }
}

struct Outcome {
    code: i32,
    stdout: String,
    stderr: String,
}

/// Run one command in the sandbox working directory.
fn run_in(sandbox: &Sandbox, args: &[&str]) -> Outcome {
    let output = Command::new(bin())
        .args(args)
        .current_dir(&sandbox.root)
        .output()
        .expect("spawn command");
    Outcome {
        code: output.status.code().expect("exit code"),
        stdout: String::from_utf8(output.stdout).expect("utf8 stdout"),
        stderr: String::from_utf8(output.stderr).expect("utf8 stderr"),
    }
}

fn complete_match(
    sandbox: &Sandbox,
    config: &Path,
    occurrence_id: &str,
    extra: &[&str],
) -> Outcome {
    let report = sandbox.root.join("report.json");
    let replay = sandbox.root.join("replay.json");
    let occurrence = sandbox.root.join("occurrence.json");
    let mut args: Vec<String> = vec![
        "studio-league-complete-match".into(),
        "--config".into(),
        config.to_string_lossy().into_owned(),
        "--report-out".into(),
        report.to_string_lossy().into_owned(),
        "--replay-out".into(),
        replay.to_string_lossy().into_owned(),
        "--occurrence-out".into(),
        occurrence.to_string_lossy().into_owned(),
        "--occurrence-id".into(),
        occurrence_id.into(),
        "--identity".into(),
        sandbox.identity.to_string_lossy().into_owned(),
        "--db".into(),
        sandbox.db.to_string_lossy().into_owned(),
    ];
    args.extend(extra.iter().map(|value| value.to_string()));
    let borrowed: Vec<&str> = args.iter().map(|value| value.as_str()).collect();
    run_in(sandbox, &borrowed)
}

fn complete_only(sandbox: &Sandbox, extra: &[&str]) -> Outcome {
    let mut args: Vec<String> = vec![
        "studio-league-complete".into(),
        "--occurrence".into(),
        sandbox
            .root
            .join("occurrence.json")
            .to_string_lossy()
            .into_owned(),
        "--report".into(),
        sandbox
            .root
            .join("report.json")
            .to_string_lossy()
            .into_owned(),
        "--replay".into(),
        sandbox
            .root
            .join("replay.json")
            .to_string_lossy()
            .into_owned(),
        "--config".into(),
        sandbox
            .root
            .join("config.json")
            .to_string_lossy()
            .into_owned(),
        "--identity".into(),
        sandbox.identity.to_string_lossy().into_owned(),
        "--db".into(),
        sandbox.db.to_string_lossy().into_owned(),
    ];
    args.extend(extra.iter().map(|value| value.to_string()));
    let borrowed: Vec<&str> = args.iter().map(|value| value.as_str()).collect();
    run_in(sandbox, &borrowed)
}

/// The four evidence documents must all exist.
fn assert_evidence_present(sandbox: &Sandbox) {
    for name in [
        "report.json",
        "replay.json",
        "occurrence.json",
        "config.json",
    ] {
        assert!(
            sandbox.root.join(name).is_file(),
            "evidence document `{name}` is missing"
        );
    }
}

// ---------------------------------------------------------------------------
// Gate 1: a real completion enters the ledger and the archive
// ---------------------------------------------------------------------------

#[test]
fn a_real_match_completion_enters_the_ledger_and_the_archive() {
    let sandbox = Sandbox::new("gate1");
    let config = real_config(&sandbox.root, "wiring-gate1", 9_100_001, [31_001, 31_002]);

    let out = complete_match(&sandbox, &config, "occ-gate1", &[]);
    assert_eq!(
        out.code, 0,
        "expected match + completion to succeed; stderr={}",
        out.stderr
    );

    // (a) all four evidence documents exist.
    assert_evidence_present(&sandbox);

    // (b) the envelope describes exactly the bytes on disk.
    let occurrence_bytes = std::fs::read(sandbox.root.join("occurrence.json")).unwrap();
    let occurrence = parse_runtime_occurrence(&occurrence_bytes)
        .expect("valid envelope")
        .expect("is an occurrence");
    assert_eq!(occurrence.occurrence_id, "occ-gate1");
    assert_eq!(
        occurrence.report_sha256,
        sha256_hex(&std::fs::read(sandbox.root.join("report.json")).unwrap())
    );
    assert_eq!(
        occurrence.replay_sha256,
        sha256_hex(&std::fs::read(sandbox.root.join("replay.json")).unwrap())
    );
    assert_eq!(
        occurrence.config_sha256,
        sha256_hex(&std::fs::read(sandbox.root.join("config.json")).unwrap())
    );

    // (c) the occurrence is in the ledger, bound to a content-addressed archive
    //     object that is reachable from the protocol root alone.
    let rows = sandbox.match_rows();
    assert_eq!(rows.len(), 1, "exactly one match row expected: {rows:?}");
    let (source_identity, storage, path) = &rows[0];
    assert_eq!(source_identity, "runtime:occ-gate1");
    assert_eq!(storage, "archive");
    assert!(
        !Path::new(path).is_absolute(),
        "path must be relative: {path}"
    );

    let object = sandbox.archive_root().join(path);
    assert!(
        object.is_file(),
        "archived object must resolve under the protocol root: {}",
        object.display()
    );
    assert_eq!(
        sha256_hex(&std::fs::read(&object).unwrap()),
        occurrence.replay_sha256,
        "the archived object must be the exact verified replay document"
    );

    // (d) the match was booked: two participants, so two rating events.
    assert_eq!(sandbox.rating_event_count(), 2);

    // (e) stdout reports the completion, not merely the match.
    assert!(
        out.stdout
            .contains("studio-league-complete-match: recorded occurrence"),
        "stdout should name the recorded occurrence: {}",
        out.stdout
    );
}

// ---------------------------------------------------------------------------
// Gate 2: a completion failure is not a match failure
// ---------------------------------------------------------------------------

#[test]
fn a_completion_failure_preserves_the_match_and_can_be_retried_alone() {
    let sandbox = Sandbox::new("gate2");
    let config = real_config(&sandbox.root, "wiring-gate2", 9_100_002, [32_001, 32_002]);

    // Force the completion half to fail *without* touching the match half.
    //
    // The chosen failure is a missing identity manifest: `open_completion_league`
    // refuses to open a session without identity evidence (that is one of the
    // Slice 3 Repair 1 gates), and repairing it is a single file, so the retry
    // half of this test is about retrying *completion*, not about re-running
    // anything.
    //
    // A bad database path would NOT work as the failure: `open_league` creates
    // missing parent directories by design, so that path succeeds.
    let missing_identity = sandbox.root.join("no-such-identity.json");
    assert!(
        !missing_identity.exists(),
        "the forced failure needs the manifest to be absent"
    );
    let report = sandbox.root.join("report.json");
    let replay = sandbox.root.join("replay.json");
    let occurrence = sandbox.root.join("occurrence.json");
    let out = run_in(
        &sandbox,
        &[
            "studio-league-complete-match",
            "--config",
            &config.to_string_lossy(),
            "--report-out",
            &report.to_string_lossy(),
            "--replay-out",
            &replay.to_string_lossy(),
            "--occurrence-out",
            &occurrence.to_string_lossy(),
            "--occurrence-id",
            "occ-gate2",
            "--identity",
            &missing_identity.to_string_lossy(),
            "--db",
            &sandbox.db.to_string_lossy(),
        ],
    );

    // The match must be reported as completed, and the failure attributed to the
    // completion half with the dedicated exit code.
    assert_eq!(
        out.code, 3,
        "expected the completion-specific exit code; stderr={}",
        out.stderr
    );
    assert!(
        out.stdout.contains("match completed"),
        "stdout must record that the match completed: {}",
        out.stdout
    );
    assert!(
        out.stderr.contains("the MATCH completed"),
        "stderr must say the match is unaffected: {}",
        out.stderr
    );

    // The evidence is intact and was not rewritten by the failure.
    assert_evidence_present(&sandbox);
    let report_before = std::fs::read(&report).unwrap();
    let replay_before = std::fs::read(&replay).unwrap();
    let occurrence_before = std::fs::read(&occurrence).unwrap();

    // No fake success: nothing was booked.
    assert!(
        !sandbox.db.exists() || sandbox.match_rows().is_empty(),
        "a failed completion must not book a match"
    );

    // Retry completion alone, against a usable database. The match must not be
    // re-run: the evidence must be byte-identical afterwards.
    let retry = complete_only(&sandbox, &[]);
    assert_eq!(
        retry.code, 0,
        "completion-only retry should succeed; stderr={}",
        retry.stderr
    );
    assert_eq!(std::fs::read(&report).unwrap(), report_before);
    assert_eq!(std::fs::read(&replay).unwrap(), replay_before);
    assert_eq!(std::fs::read(&occurrence).unwrap(), occurrence_before);

    let rows = sandbox.match_rows();
    assert_eq!(rows.len(), 1, "the retry must book exactly one match");
    assert_eq!(rows[0].0, "runtime:occ-gate2");
    assert_eq!(sandbox.rating_event_count(), 2);
}

// ---------------------------------------------------------------------------
// Gate 3: repeated wiring is idempotent
// ---------------------------------------------------------------------------

#[test]
fn triggering_the_same_completion_twice_is_idempotent_and_adds_no_elo() {
    let sandbox = Sandbox::new("gate3");
    let config = real_config(&sandbox.root, "wiring-gate3", 9_100_003, [33_001, 33_002]);

    let first = complete_match(&sandbox, &config, "occ-gate3", &[]);
    assert_eq!(first.code, 0, "first completion failed: {}", first.stderr);
    let rows_after_first = sandbox.match_rows();
    assert_eq!(rows_after_first.len(), 1);
    let events_after_first = sandbox.rating_event_count();
    assert_eq!(events_after_first, 2);

    // The same completion is offered again — through both entry points, since
    // either could be the one a caller repeats.
    let second = complete_only(&sandbox, &[]);
    assert_eq!(
        second.code, 0,
        "re-offering must succeed idempotently: {}",
        second.stderr
    );
    assert!(
        second.stdout.contains("already_present"),
        "the ledger's own answer must be surfaced: {}",
        second.stdout
    );

    assert_eq!(
        sandbox.match_rows().len(),
        1,
        "re-offering must not insert a second match"
    );
    assert_eq!(
        sandbox.rating_event_count(),
        events_after_first,
        "re-offering must not add rating events"
    );
}
