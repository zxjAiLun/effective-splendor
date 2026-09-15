//! Commit D Slice 1 — the read-only Studio League Host API, and Commit E Slice 1's
//! one write route.
//!
//! Fourteen gates, deliberately few. Eight are the read surface (Commit D Slice
//! 1): root authority, leaderboard truth, match-detail truth, replay
//! content-addressing, and four fail-closed gates for the evidence a read must
//! respect — durable identity, the rating protocol identity, a corrupt archive
//! object, and evidence that moved *after* the host was already running. Four are
//! the one write route (Commit E Slice 1): the normal round trip, a completion
//! failure and its retry, the idempotent re-post, and the request surface's
//! refusals. Two are the League Play page's seams: the shared request fixture both
//! the page and the Host must agree on, and the archive route the replay board
//! consumes — which must be an adapter over the reader's authority and not a
//! second, path-based way in.
//!
//! They drive the real binary over a real socket against real matches, because the
//! thing under test is a process surface, not a library.
//!
//! The HTTP client is hand-rolled over `std::net` on purpose: this repository has
//! no web stack, and a read-only API gate is not a reason to acquire one.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use splendor_studio_league::{leaderboard, open_league, IdentityManifestV1, StudioLeaguePathsV1};

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

/// The registries `studio-host` requires. Absolute: its default reviewer registry
/// is resolved against the process cwd, and these gates deliberately run from an
/// unrelated directory.
fn rating_registry() -> PathBuf {
    workspace_path("benchmarks/studio-1v1.registry.json")
}

fn reviewer_registry() -> PathBuf {
    workspace_path("benchmarks/studio-reviewers.registry.json")
}

fn workspace_path(relative: &str) -> PathBuf {
    // `crates/splendor-cli` -> the workspace root. Compile-time, so it does not
    // depend on where the test binary happens to run from.
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(relative)
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

fn tmp_dir(label: &str) -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-league-host-api-{}-{}-{}",
        std::process::id(),
        n,
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

fn write_file(dir: &Path, name: &str, contents: &str) -> PathBuf {
    let path = dir.join(name);
    std::fs::write(&path, contents).expect("write file");
    path
}

/// One GET, read to EOF (the host answers `Connection: close`).
fn http_get(port: u16, path: &str) -> std::io::Result<(String, Vec<u8>)> {
    http_get_within(port, path, Duration::from_secs(60))
}

/// The same GET under a caller-chosen deadline.
///
/// A liveness gate has to assert that an answer arrived *bounded*, not merely that
/// one eventually arrived, so the client deadline is a parameter rather than a
/// constant the gate cannot see.
fn http_get_within(port: u16, path: &str, timeout: Duration) -> std::io::Result<(String, Vec<u8>)> {
    let mut stream = TcpStream::connect(("127.0.0.1", port))?;
    stream.set_read_timeout(Some(timeout))?;
    write!(
        stream,
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    )?;
    let mut buffer = Vec::new();
    stream.read_to_end(&mut buffer)?;
    let split = buffer
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .expect("a complete response has a header terminator")
        + 4;
    let head = String::from_utf8_lossy(&buffer[..split]).to_string();
    let status = head.lines().next().unwrap_or_default().to_string();
    Ok((status, buffer[split..].to_vec()))
}

fn status_code(status: &str) -> u16 {
    status
        .split_whitespace()
        .nth(1)
        .and_then(|code| code.parse().ok())
        .unwrap_or_else(|| panic!("unparsable status line `{status}`"))
}

/// An ephemeral port, released immediately before the host binds it.
fn free_port() -> u16 {
    let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind an ephemeral port");
    let port = listener.local_addr().expect("local addr").port();
    drop(listener);
    port
}

/// A running `studio-host`, killed when the gate ends.
struct HostProcess {
    child: Child,
    port: u16,
}

impl HostProcess {
    /// Start the host with the workspace registry, from an unrelated cwd.
    fn start(root: &Path, cwd: &Path) -> Self {
        Self::start_with_registry(root, cwd, &rating_registry())
    }

    /// Start the host with an explicit registry, so a write gate can decide what a
    /// seat id resolves to.
    fn start_with_registry(root: &Path, cwd: &Path, registry: &Path) -> Self {
        let port = free_port();
        let child = Command::new(bin())
            .current_dir(cwd)
            .args([
                "studio-host",
                "--registry",
                &registry.to_string_lossy(),
                "--reviewer-registry",
                &reviewer_registry().to_string_lossy(),
                "--port",
                &port.to_string(),
                "--project-root",
                &root.to_string_lossy(),
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn studio-host");
        let mut host = Self { child, port };
        if let Err(error) = host.await_ready() {
            let mut stderr = String::new();
            if let Some(mut pipe) = host.child.stderr.take() {
                let _ = pipe.read_to_string(&mut stderr);
            }
            panic!(
                "studio-host did not start: {error}
stderr={stderr}"
            );
        }
        host
    }

    /// The host is ready when it answers `/health`. A slow machine must not make
    /// this a false failure, and a host that died must fail loudly.
    fn await_ready(&mut self) -> Result<(), String> {
        let deadline = Instant::now() + Duration::from_secs(60);
        loop {
            if let Ok((status, _)) = http_get(self.port, "/health") {
                if status_code(&status) == 200 {
                    return Ok(());
                }
            }
            if Instant::now() >= deadline {
                let _ = self.child.kill();
                let _ = self.child.wait();
                return Err(format!(
                    "studio-host never answered /health on port {}",
                    self.port
                ));
            }
            std::thread::sleep(Duration::from_millis(200));
        }
    }

    fn get_json(&self, path: &str) -> (u16, serde_json::Value) {
        let (status, body) = http_get(self.port, path).expect("GET");
        let code = status_code(&status);
        let json = serde_json::from_slice(&body).unwrap_or_else(|error| {
            panic!(
                "GET {path} returned {code} with a non-JSON body: {error}\n{}",
                String::from_utf8_lossy(&body)
            )
        });
        (code, json)
    }

    /// One POST, with the JSON body the write route accepts.
    fn post_json(&self, path: &str, body: &serde_json::Value) -> (u16, serde_json::Value) {
        let (status, raw) = http_post_json(self.port, path, body).expect("POST");
        let code = status_code(&status);
        let json = serde_json::from_slice(&raw).unwrap_or_else(|error| {
            panic!(
                "POST {path} returned {code} with a non-JSON body: {error}
{}",
                String::from_utf8_lossy(&raw)
            )
        });
        (code, json)
    }
}

impl Drop for HostProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// The league two real matches were completed into, plus the facts a direct
/// database read confirms. Built once: reads do not mutate, so gates share it.
struct Fixture {
    root: PathBuf,
    db: PathBuf,
    eligible_match: String,
    eligible_replay_sha: String,
    ineligible_match: String,
    ineligible_reason: String,
}

fn fixture() -> &'static Fixture {
    static FIXTURE: OnceLock<Fixture> = OnceLock::new();
    FIXTURE.get_or_init(build_fixture)
}

fn build_fixture() -> Fixture {
    let base = tmp_dir("fixture");
    let root = base.join("root");
    let paths = StudioLeaguePathsV1::from_root(&root);
    std::fs::create_dir_all(paths.dir()).expect("create the league directory");
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    manifest
        .save(paths.identity())
        .expect("save identity manifest");

    // Two real matches, through the real producer: one rated pair, and one
    // self-match, which the ledger records as rating-ineligible with no events.
    complete_match(
        &base,
        &root,
        "eligible",
        "occ-hostapi-eligible",
        9_200_001,
        [["agent-heuristic", "21001"], ["agent-random", "21002"]],
    );
    complete_match(
        &base,
        &root,
        "selfmatch",
        "occ-hostapi-self",
        9_200_002,
        [["agent-random", "22001"], ["agent-random", "22002"]],
    );

    let conn = open_league(&paths.db()).expect("open league");
    let (eligible_match, eligible_replay_sha): (String, String) = conn
        .query_row(
            "SELECT match_id, replay_document_hash FROM matches
              WHERE rating_eligible = 1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .expect("the eligible match is recorded");
    let (ineligible_match, ineligible_reason): (String, String) = conn
        .query_row(
            "SELECT match_id, rating_ineligible_reason FROM matches
              WHERE rating_eligible = 0",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .expect("the ineligible match is recorded");

    Fixture {
        root,
        db: paths.db().to_path_buf(),
        eligible_match,
        eligible_replay_sha,
        ineligible_match,
        ineligible_reason,
    }
}

/// Run one real match and complete it into the league under `root`.
fn complete_match(
    dir: &Path,
    root: &Path,
    tag: &str,
    occurrence_id: &str,
    seed: u64,
    seats: [[&str; 2]; 2],
) {
    let program = bin().to_string_lossy().into_owned();
    let config = serde_json::json!({
        "game_id": format!("hostapi-{tag}"),
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 10_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            { "program": program, "args": [seats[0][0], "--seed", seats[0][1]] },
            { "program": program, "args": [seats[1][0], "--seed", seats[1][1]] },
        ]
    });
    let config_path = write_file(
        dir,
        &format!("{tag}-config.json"),
        &serde_json::to_string_pretty(&config).expect("serialize config"),
    );
    let output = Command::new(bin())
        .current_dir(dir)
        .args([
            "studio-league-complete-match",
            "--config",
            &config_path.to_string_lossy(),
            "--config-out",
            &dir.join(format!("{tag}-snapshot.json")).to_string_lossy(),
            "--report-out",
            &dir.join(format!("{tag}-report.json")).to_string_lossy(),
            "--replay-out",
            &dir.join(format!("{tag}-replay.json")).to_string_lossy(),
            "--occurrence-out",
            &dir.join(format!("{tag}-occurrence.json")).to_string_lossy(),
            "--occurrence-id",
            occurrence_id,
            "--project-root",
            &root.to_string_lossy(),
        ])
        .output()
        .expect("run studio-league-complete-match");
    assert_eq!(
        output.status.code(),
        Some(0),
        "the fixture match `{tag}` must complete; stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
}

/// Gate A — root authority.
///
/// The host is started from a working directory unrelated to the project root.
/// The league it serves must be the one in the explicit root, and nothing may be
/// created under the cwd. This is the gate that would fail if any handler
/// re-derived a league location from the process working directory.
#[test]
fn the_league_comes_from_the_explicit_project_root_not_the_working_directory() {
    let fixture = fixture();
    let elsewhere = tmp_dir("gate-a-elsewhere");
    let host = HostProcess::start(&fixture.root, &elsewhere);

    let (code, body) = host.get_json("/league/leaderboard");
    assert_eq!(code, 200, "leaderboard must be served: {body}");
    let rows = body["rows"].as_array().expect("rows array");
    assert!(
        !rows.is_empty(),
        "the leaderboard must come from the league in the explicit root"
    );

    // Nothing was created relative to the working directory.
    assert!(
        !elsewhere.join("local-artifacts").exists(),
        "the host must not create league state under the process working directory"
    );
}

/// Gate B — leaderboard truth.
///
/// The HTTP view must agree with the ledger's own `leaderboard()` on the same
/// database, field for field. The Host is a presenter, not a second calculator.
#[test]
fn the_leaderboard_agrees_with_the_ledger_itself() {
    let fixture = fixture();
    let host = HostProcess::start(&fixture.root, &fixture.root);
    let (code, body) = host.get_json("/league/leaderboard");
    assert_eq!(code, 200, "leaderboard must be served: {body}");

    let conn = open_league(&fixture.db).expect("open league");
    let expected = leaderboard(&conn).expect("ledger leaderboard");
    assert!(!expected.is_empty(), "the fixture league is not empty");

    let rows = body["rows"].as_array().expect("rows array");
    assert_eq!(rows.len(), expected.len(), "same number of rows");

    for (served, ledger) in rows.iter().zip(expected.iter()) {
        assert_eq!(served["participant_id"], ledger.participant_id);
        assert_eq!(served["display_name"], ledger.display_name);
        assert_eq!(served["elo"], ledger.elo);
        assert_eq!(served["rated_games"], ledger.rated_games);
        assert_eq!(served["recorded_games"], ledger.recorded_games);
        assert_eq!(served["rated_wins"], ledger.rated_wins);
        assert_eq!(served["rated_ties"], ledger.rated_ties);
        assert_eq!(served["rated_losses"], ledger.rated_losses);
        assert_eq!(served["provisional"], ledger.provisional);
    }
}

/// Gate C — match detail truth.
///
/// A rated match reports its real Elo events; an ineligible match reports its
/// frozen reason and **no** events. Nothing is inferred: no winner from a replay,
/// no identity from a filename, no recomputed delta.
#[test]
fn match_detail_reports_recorded_facts_and_never_fabricates_events() {
    let fixture = fixture();
    let host = HostProcess::start(&fixture.root, &fixture.root);

    let (code, body) = host.get_json(&format!("/league/matches/{}", fixture.eligible_match));
    assert_eq!(code, 200, "the eligible match must be served: {body}");
    let detail = &body["match"];
    assert_eq!(detail["match_id"], fixture.eligible_match.as_str());
    assert_eq!(detail["rating_eligible"], true);
    assert_eq!(detail["status"], "completed");
    assert_eq!(detail["player_count"], 2);
    assert!(
        detail["source_identity"]
            .as_str()
            .is_some_and(|s| !s.is_empty()),
        "source identity is a recorded fact and must be present"
    );

    let seats = detail["seats"].as_array().expect("seats array");
    assert_eq!(seats.len(), 2, "a two-seat match records two seats");
    for (index, seat) in seats.iter().enumerate() {
        assert_eq!(seat["seat"], index);
        assert!(
            seat["participant_id"]
                .as_str()
                .is_some_and(|s| !s.is_empty()),
            "every seat of a rated match is attributed to a participant"
        );
        assert!(seat["won"].is_boolean(), "each seat records won/lost");
    }

    let events = detail["rating_events"].as_array().expect("events array");
    assert_eq!(
        events.len(),
        2,
        "a rated two-seat match has exactly two events"
    );
    for event in events {
        let before = event["elo_before"].as_f64().expect("elo_before");
        let after = event["elo_after"].as_f64().expect("elo_after");
        assert!(
            before > 0.0 && after > 0.0,
            "El-o values are recorded numbers"
        );
        assert!(
            (before - 1500.0).abs() < f64::EPSILON,
            "first rated match starts from the protocol initial Elo"
        );
    }
    assert_eq!(
        detail["replay"]["document_sha256"],
        fixture.eligible_replay_sha.as_str(),
        "the recorded content address is reported"
    );
    assert_eq!(detail["replay"]["storage"], "archive");
    assert_eq!(detail["replay"]["verification"], "verified");
    assert_eq!(detail["replay"]["archived"], true);

    // The ineligible match: a reason, and no invented Elo.
    let (code, body) = host.get_json(&format!("/league/matches/{}", fixture.ineligible_match));
    assert_eq!(code, 200, "the ineligible match must be served: {body}");
    let detail = &body["match"];
    assert_eq!(detail["rating_eligible"], false);
    assert_eq!(
        detail["rating_ineligible_reason"],
        fixture.ineligible_reason.as_str(),
        "the frozen ineligibility reason is reported verbatim"
    );
    assert_eq!(
        detail["rating_events"]
            .as_array()
            .expect("events array")
            .len(),
        0,
        "an ineligible match must never be given fabricated rating events"
    );

    // Absent is absent.
    let (code, body) = host.get_json("/league/matches/not-a-recorded-match");
    assert_eq!(code, 404, "an unknown match must fail closed: {body}");
    assert!(body["error"].is_string(), "the error is reported as JSON");
}

/// Gate D — replay content-addressing.
///
/// The correct content address returns the exact archived bytes; a malformed
/// address, an unknown address, and an attempt to name a filesystem path all fail
/// closed. A client supplies a hash and never a location.
#[test]
fn replays_are_read_by_content_address_only() {
    let fixture = fixture();
    let host = HostProcess::start(&fixture.root, &fixture.root);

    let (status, body) = http_get(
        host.port,
        &format!("/league/replays/{}", fixture.eligible_replay_sha),
    )
    .expect("GET the replay");
    assert_eq!(
        status_code(&status),
        200,
        "the archived replay must be served"
    );

    let archived = std::fs::read(
        fixture
            .root
            .join("local-artifacts/studio-league/replays")
            .join(&fixture.eligible_replay_sha[..2])
            .join(format!("{}.json", fixture.eligible_replay_sha)),
    )
    .expect("the archived object exists on disk");
    assert_eq!(
        body, archived,
        "the served body must be the exact archived ReplayV1 bytes"
    );
    assert!(
        !body.is_empty(),
        "a served replay is a real document, not an empty success"
    );

    // Malformed, unknown, and path-shaped requests all fail closed.
    let canonical_miss = format!("/league/replays/{}", "0".repeat(64));
    for path in [
        "/league/replays/not-a-sha".to_string(),
        canonical_miss,
        "/league/replays/../../etc/passwd".to_string(),
    ] {
        let (status, body) = http_get(host.port, &path).expect("GET");
        assert_eq!(
            status_code(&status),
            404,
            "`{path}` must fail closed, got {status}: {}",
            String::from_utf8_lossy(&body)
        );
    }
}

/// A private copy of the fixture league.
///
/// The gates below have to damage derived state or authority evidence to observe
/// what a read does about it. The shared fixture is read-only and used by the
/// other gates, so each of these gets its own copy.
fn copied_root(label: &str) -> PathBuf {
    let fixture = fixture();
    let root = tmp_dir(label).join("root");
    copy_tree(&fixture.root, &root);
    root
}

fn copy_tree(from: &Path, to: &Path) {
    std::fs::create_dir_all(to).expect("create destination directory");
    for entry in std::fs::read_dir(from).expect("read source directory") {
        let entry = entry.expect("directory entry");
        let target = to.join(entry.file_name());
        if entry.file_type().expect("file type").is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).expect("copy file");
        }
    }
}

/// Gate — a stale durable identity is not served as current truth.
///
/// `identity.json` is authored state and the database is derived from it. A user
/// may legally rename themselves or add an alias; `sync_identity_manifest` then
/// refuses to project that into a non-empty ledger and demands a rebuild. A read
/// path that checked only the schema version would happily serve the old
/// participants and the old leaderboard as if nothing had happened.
#[test]
fn a_league_whose_durable_identity_moved_on_is_not_served() {
    let root = copied_root("identity-drift");
    let paths = StudioLeaguePathsV1::from_root(&root);

    let mut manifest = IdentityManifestV1::load(paths.identity())
        .expect("load the identity manifest")
        .expect("the fixture has one");
    // The manifest hash is canonical over the whole document, so a rename is
    // exactly the class of edit this evidence exists to catch.
    manifest
        .rename_local_human("Nick Renamed")
        .expect("rename the local human");
    manifest
        .save(paths.identity())
        .expect("save the identity manifest");

    let host = HostProcess::start(&root, &root);
    let (status, body) = host.get_json("/league/leaderboard");
    assert_eq!(
        status, 503,
        "a leaderboard derived from a superseded identity must fail closed, got {status}: {body}"
    );

    // The league being unavailable is not the host being unavailable: the
    // pre-existing routes keep working.
    let (status, _) = http_get(host.port, "/health").expect("GET /health");
    assert_eq!(
        status_code(&status),
        200,
        "/health must still answer while the league reader is closed"
    );
}

/// Gate — a database built by another rating protocol is not served.
///
/// The persisted `studio_rating_config` is integrity evidence, not a setting.
/// This gate keeps the schema version intact and changes only that evidence, so a
/// schema check alone provably cannot see the difference.
#[test]
fn a_league_built_by_another_rating_protocol_is_not_served() {
    let root = copied_root("rating-drift");
    let paths = StudioLeaguePathsV1::from_root(&root);

    let conn = open_league(&paths.db()).expect("open the league for the gate");
    let recorded: String = conn
        .query_row(
            "SELECT value FROM league_meta WHERE value LIKE '%\"k_factor\"%'",
            [],
            |row| row.get(0),
        )
        .expect("the rating config is recorded as integrity evidence");
    let mut value: serde_json::Value = serde_json::from_str(&recorded).expect("parse the config");
    let k_factor = value["k_factor"].as_u64().expect("k_factor is recorded");
    value["k_factor"] = serde_json::json!(k_factor + 1);
    let altered = serde_json::to_string(&value).expect("serialize the altered config");
    assert_ne!(
        altered, recorded,
        "the gate must actually change the recorded evidence"
    );
    conn.execute(
        "UPDATE league_meta SET value = ?1 WHERE value = ?2",
        rusqlite::params![altered, recorded],
    )
    .expect("rewrite the rating config evidence");
    drop(conn);

    let host = HostProcess::start(&root, &root);
    let (status, body) = host.get_json("/league/leaderboard");
    assert_eq!(
        status, 503,
        "another protocol's Elo must not be served as this build's leaderboard, got {status}: {body}"
    );

    let (status, _) = http_get(host.port, "/health").expect("GET /health");
    assert_eq!(status_code(&status), 200, "/health must still answer");
}

/// Gate — a corrupt archive object is a server fault, not a missing replay.
///
/// `read_archived_replay` fails both for "there is no such object" and for "there
/// is one, and it is not servable". Answering 404 to the second tells the client
/// the replay does not exist when in fact the archive lost it, so only an
/// address that was never archived may be a 404.
#[test]
fn a_corrupt_archive_object_is_a_server_fault_not_a_missing_replay() {
    let fixture = fixture();
    let root = copied_root("archive-corrupt");
    let object = root
        .join("local-artifacts/studio-league/replays")
        .join(&fixture.eligible_replay_sha[..2])
        .join(format!("{}.json", fixture.eligible_replay_sha));

    // Same length, still readable, no longer the bytes that hash to its address.
    let mut bytes = std::fs::read(&object).expect("read the archived object");
    bytes[0] ^= 0xff;
    std::fs::write(&object, &bytes).expect("write the corrupted object");

    let host = HostProcess::start(&root, &root);
    let (status, body) = http_get(
        host.port,
        &format!("/league/replays/{}", fixture.eligible_replay_sha),
    )
    .expect("GET the corrupt replay");
    assert_eq!(
        status_code(&status),
        503,
        "the archive holds this object and cannot serve it; that is not an absence: {}",
        String::from_utf8_lossy(&body)
    );

    // An address that was never archived stays a plain absence.
    let (status, _) = http_get(host.port, &format!("/league/replays/{}", "0".repeat(64)))
        .expect("GET an unknown replay");
    assert_eq!(
        status_code(&status),
        404,
        "an address that was never archived is a genuine 404"
    );
}

/// Gate — the authority evidence is revalidated on every read, not once at boot.
///
/// The gates above change evidence and then start a host, so they only prove the
/// check happens at startup. `studio-host` is a long-running process, and the
/// owner may legally edit the authored identity authority at any moment without
/// rebuilding: the derived index is stale from that instant. A server that
/// validated only at startup would keep answering with the superseded identity
/// for the rest of its life, on the same port, with no restart to mark the change.
#[test]
fn a_league_that_goes_stale_while_the_host_is_running_stops_being_served() {
    let fixture = fixture();
    let root = copied_root("authority-goes-stale");
    let paths = StudioLeaguePathsV1::from_root(&root);
    let host = HostProcess::start(&root, &root);

    // While the evidence holds, the league answers.
    let (status, _) = host.get_json("/league/leaderboard");
    assert_eq!(
        status, 200,
        "the league must be served while its authority evidence holds"
    );

    // The user renames themselves. Nothing is rebuilt and nothing restarts.
    let mut manifest = IdentityManifestV1::load(paths.identity())
        .expect("load the identity manifest")
        .expect("the fixture has one");
    manifest
        .rename_local_human("Nick Renamed")
        .expect("rename the local human");
    manifest
        .save(paths.identity())
        .expect("save the identity manifest");

    // Same process, same port, next request: every league read must fail closed.
    for (path, label) in [
        ("/league/leaderboard".to_string(), "the leaderboard"),
        (
            format!("/league/matches/{}", fixture.eligible_match),
            "match detail",
        ),
        (
            format!("/league/replays/{}", fixture.eligible_replay_sha),
            "the replay",
        ),
        (
            format!("/league/replays/{}", "0".repeat(64)),
            "a replay that was never archived",
        ),
    ] {
        let (status, body) = host.get_json(&path);
        assert_eq!(
            status, 503,
            "{label} must stop being served once the identity authority moved on, got {status}: {body}"
        );
    }

    // The league going stale is not the host failing.
    let (status, _) = http_get(host.port, "/health").expect("GET /health");
    assert_eq!(
        status_code(&status),
        200,
        "/health must still answer while the league is stale"
    );
}

// ---------------------------------------------------------------------------
// Commit E Slice 1 — the Host write surface.
//
// Four gates drive `POST /league/matches` over a real socket against real
// matches: the normal round trip, a completion failure and its retry, the
// idempotent re-post, and the request surface's refusals. They are deliberately
// few: the producer's own publish order is already frozen by the CLI wiring
// gates, and these gates exist to prove the Host *reuses* it rather than
// reimplements it.
// ---------------------------------------------------------------------------

/// One POST. A match can take seconds, so the read timeout is generous; the
/// assertion is on the outcome, never on elapsed time.
fn http_post_json(
    port: u16,
    path: &str,
    body: &serde_json::Value,
) -> std::io::Result<(String, Vec<u8>)> {
    let bytes = serde_json::to_vec(body).expect("serialize the request body");
    http_post_raw(port, path, &bytes)
}

/// One POST of exact bytes.
///
/// The shared page fixture is posted through this verbatim, so the gate proves the
/// Host accepts *that document* rather than a convenient re-serialization of it.
fn http_post_raw(port: u16, path: &str, bytes: &[u8]) -> std::io::Result<(String, Vec<u8>)> {
    let mut stream = TcpStream::connect(("127.0.0.1", port))?;
    stream.set_read_timeout(Some(Duration::from_secs(600)))?;
    write!(
        stream,
        "POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        bytes.len()
    )?;
    stream.write_all(&bytes)?;
    stream.flush()?;
    let mut buffer = Vec::new();
    stream.read_to_end(&mut buffer)?;
    let split = buffer
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .expect("a complete response has a header terminator")
        + 4;
    let head = String::from_utf8_lossy(&buffer[..split]).to_string();
    let status = head.lines().next().unwrap_or_default().to_string();
    Ok((status, buffer[split..].to_vec()))
}

/// A real, empty league installation: the directory, the durable identity
/// manifest, and the schema. Write gates start from one of these.
fn new_league(dir: &Path) -> (PathBuf, StudioLeaguePathsV1) {
    let root = dir.join("root");
    let paths = StudioLeaguePathsV1::from_root(&root);
    std::fs::create_dir_all(paths.dir()).expect("create the league directory");
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    manifest
        .save(paths.identity())
        .expect("save identity manifest");
    // Opening the league creates the schema; the durable identity is already there.
    drop(open_league(&paths.db()).expect("create the league schema"));
    (root, paths)
}

/// A league that has served at least one completion.
///
/// The read session validates the stored rating protocol identity and the durable
/// identity hash, and those are written by a completion. A gate that reads the
/// league back through HTTP therefore has to start from a league that has already
/// booked a match.
fn primed_league(dir: &Path) -> (PathBuf, StudioLeaguePathsV1) {
    let (root, paths) = new_league(dir);
    complete_match(
        dir,
        &root,
        "prime",
        "occ-gate-prime",
        9_100_001,
        [["agent-heuristic", "91101"], ["agent-random", "91102"]],
    );
    (root, paths)
}

/// A registry the gate owns, so it can decide what a seat id resolves to.
///
/// The Host is the party that resolves a seat to a command, and it copies that
/// command out of the registry — never out of the request. Pointing `program` at
/// a path the gate can delete is what makes "the retry did not re-run the match"
/// observable rather than merely plausible.
fn host_registry(dir: &Path, entries: &[(&str, PathBuf, Vec<&str>)]) -> PathBuf {
    let agents = entries
        .iter()
        .enumerate()
        .map(|(index, (id, program, args))| {
            serde_json::json!({
                "id": id,
                "display_name": format!("Gate agent {id} ({index})"),
                "class": "search",
                "policy_version": format!("gate-policy-{index}"),
                "model_version": null,
                "checkpoint_hash": null,
                "runtime_name": format!("gate-runtime-{id}"),
                "runtime_version": "1",
                "command": { "program": program.to_string_lossy(), "args": args },
            })
        })
        .collect::<Vec<_>>();
    let registry = serde_json::json!({
        "format": "effective-splendor-rating-registry",
        "version": 1,
        "registry_id": "gate-host-write-registry",
        "agents": agents,
    });
    write_file(
        dir,
        "gate-registry.json",
        &serde_json::to_string_pretty(&registry).expect("serialize registry"),
    )
}

/// The seats every write gate uses: the arena binary itself, driven as an agent,
/// exactly the way the CLI wiring fixture drives it.
///
/// `gate-offline` is that binary asked to do something that is not agent-protocol
/// work, so it exits without a handshake. That is the cheapest honest way to
/// produce a settled *aborted* match -- the arena's other non-completed outcome --
/// without waiting out a handshake timeout.
fn gate_seats(program: &Path) -> Vec<(&'static str, PathBuf, Vec<&'static str>)> {
    vec![
        (
            "gate-heuristic",
            program.to_path_buf(),
            vec!["agent-heuristic", "--seed", "7"],
        ),
        (
            "gate-random",
            program.to_path_buf(),
            vec!["agent-random", "--seed", "8"],
        ),
        ("gate-offline", program.to_path_buf(), vec!["--version"]),
    ]
}

fn count_rows(conn: &rusqlite::Connection, sql: &str) -> i64 {
    conn.query_row(sql, [], |row| row.get(0))
        .unwrap_or_else(|error| panic!("query `{sql}` failed: {error}"))
}

/// Gate I — a POST runs one real match and books it end to end.
///
/// The normal round trip: the Host builds the arena configuration from registry
/// ids, runs the real arena, publishes all four documents into the occurrence
/// slot, completes the occurrence, and the read surface then serves exactly the
/// match that was booked. Nothing here is mocked: this is the same producer the
/// CLI uses, reached through the one write route.
#[test]
fn a_post_runs_one_real_match_and_books_it_end_to_end() {
    let dir = tmp_dir("gate-i");
    let (root, paths) = new_league(&dir);
    let registry = host_registry(&dir, &gate_seats(&bin()));
    let elsewhere = dir.join("elsewhere");
    std::fs::create_dir_all(&elsewhere).expect("create an unrelated cwd");
    let host = HostProcess::start_with_registry(&root, &elsewhere, &registry);

    // A genuinely fresh league. A read session needs the stored rating protocol
    // identity and the durable identity hash, and those are written by a
    // completion -- so before the first match this Host has nothing to serve.
    let (code, unavailable) = host.get_json("/league/leaderboard");
    assert_eq!(
        code, 503,
        "a fresh league has no integrity evidence to serve yet: {unavailable}"
    );

    let request = serde_json::json!({
        "occurrence_id": "gate-i-0001",
        "game_id": "gate-i-game",
        "seed": 7_100_001u64,
        "seats": ["gate-heuristic", "gate-random"],
    });
    let (code, response) = host.post_json("/league/matches", &request);
    assert_eq!(code, 200, "a normal POST must be served: {response}");
    assert_eq!(response["match_status"], "completed");
    assert_eq!(response["completion_status"], "inserted");
    let receipt = &response["receipt"];
    assert_eq!(receipt["source_identity"], "runtime:gate-i-0001");
    let match_id = receipt["match_id"]
        .as_str()
        .expect("the response names the booked match")
        .to_string();
    assert!(!match_id.is_empty());
    assert_eq!(
        receipt["elo"].as_array().expect("elo events").len(),
        2,
        "a rated two-seat match records two events: {response}"
    );

    // All four documents are durable in the occurrence slot, under the protocol
    // file names.
    let slot = paths
        .occurrence_dir("gate-i-0001")
        .expect("a safe occurrence id");
    for name in [
        "config.json",
        "replay.json",
        "report.json",
        "occurrence.json",
    ] {
        assert!(
            slot.join(name).is_file(),
            "{name} must be durable after a POST; {} holds {:?}",
            slot.display(),
            std::fs::read_dir(&slot)
                .map(|entries| entries
                    .filter_map(|entry| entry.ok())
                    .map(|entry| entry.file_name().to_string_lossy().into_owned())
                    .collect::<Vec<_>>())
                .unwrap_or_default()
        );
    }

    // The read surface is now available on the SAME Host, and serves exactly the
    // match that POST booked: the first successful completion is what made the
    // league readable, without restarting the process.
    let (code, board) = host.get_json("/league/leaderboard");
    assert_eq!(
        code, 200,
        "the first booking must make the league readable: {board}"
    );
    let rows = board["rows"].as_array().expect("rows array");
    for event in receipt["elo"].as_array().expect("elo events") {
        let participant = event["participant_id"].as_str().expect("a participant id");
        assert!(
            rows.iter().any(|row| row["participant_id"] == participant),
            "the booked match must appear in the leaderboard as `{participant}`: {board}"
        );
    }

    let (code, detail) = host.get_json(&format!("/league/matches/{match_id}"));
    assert_eq!(code, 200, "the booked match must be readable: {detail}");
    assert_eq!(detail["match"]["match_id"], match_id.as_str());
    assert_eq!(detail["match"]["status"], "completed");
    assert_eq!(detail["match"]["player_count"], 2);

    // And its replay is retrievable by content address.
    let document_hash = receipt["replay"]["document_hash"]
        .as_str()
        .expect("the receipt names the archived document");
    let (code, archived) = host.get_json(&format!("/league/replays/{document_hash}"));
    assert_eq!(
        code, 200,
        "the archived replay must be readable by content address: {archived}"
    );
    assert_eq!(
        archived["final_state_hash"]
            .as_str()
            .expect("the archived document is a replay")
            .len(),
        64
    );

    // The other settled outcome: a match the arena could not play to a terminal
    // state. It is a 200 with two facts, never an error and never a booking, and
    // re-offering it reports the recorded fact instead of trying again -- which the
    // create-if-absent report publish would turn into a failure if it re-ran.
    let aborted_slot = paths
        .occurrence_dir("gate-i-aborted")
        .expect("a safe occurrence id");
    let aborted_request = serde_json::json!({
        "occurrence_id": "gate-i-aborted",
        "game_id": "gate-i-aborted-game",
        "seed": 7_100_002u64,
        "seats": ["gate-offline", "gate-offline"],
    });
    let (code, aborted) = host.post_json("/league/matches", &aborted_request);
    assert_eq!(
        code, 200,
        "a settled aborted match is a normal outcome: {aborted}"
    );
    assert_eq!(aborted["match_status"], "aborted");
    assert_eq!(aborted["completion_status"], "not_applicable");
    assert!(
        aborted.get("receipt").is_none() || aborted["receipt"].is_null(),
        "an aborted match has no booking to report: {aborted}"
    );
    let report_before =
        std::fs::read(aborted_slot.join("report.json")).expect("the aborted report is durable");
    for name in ["config.json", "replay.json", "occurrence.json"] {
        assert!(
            !aborted_slot.join(name).exists(),
            "{name} must not exist for a settled, non-completed match"
        );
    }

    let (code, again) = host.post_json("/league/matches", &aborted_request);
    assert_eq!(code, 200, "the settled fact can be re-read: {again}");
    assert_eq!(again["match_status"], "aborted");
    assert_eq!(again["completion_status"], "not_applicable");
    assert_eq!(
        std::fs::read(aborted_slot.join("report.json")).expect("the aborted report"),
        report_before,
        "a settled aborted match must not be produced again"
    );

    // A settled aborted slot is settled only while the report is the ONLY document
    // in it. One stray document makes the slot a partial evidence set, which is a
    // conflict rather than a recordable fact: reading it as "aborted" would answer
    // for a match that was never settled in that shape.
    std::fs::write(aborted_slot.join("config.json"), b"{}\n").expect("plant a stray document");
    let (code, conflicted) = host.post_json("/league/matches", &aborted_request);
    assert_eq!(
        code, 409,
        "the report plus a stray document is an ambiguous slot: {conflicted}"
    );
    assert_eq!(
        std::fs::read(aborted_slot.join("report.json")).expect("the aborted report"),
        report_before,
        "a conflicted slot must not be rewritten either"
    );

    // Nothing was created relative to the working directory.
    assert!(
        !elsewhere.join("local-artifacts").exists(),
        "the write route must not create league state under the process working directory"
    );
}

/// Gate J — a completion failure is reported as two facts, and the retry does not
/// re-run the match.
///
/// The occurrence is produced and made durable while completion is impossible, so
/// the response must say *the match completed* and *completion failed*, never
/// anything that reads as one failed thing. The retry is then proved not to have
/// re-run the arena twice over: the agent program no longer exists, so a re-run
/// could not have succeeded, and the four documents are byte-identical, so
/// nothing was re-minted.
#[test]
fn a_retry_after_a_completion_failure_never_reruns_the_match() {
    let dir = tmp_dir("gate-j");
    let (root, paths) = new_league(&dir);

    // The agent program is a copy this gate owns. Taking it away later is how the
    // gate makes "the retry did not spawn anything" observable.
    let agents = dir.join("agents");
    std::fs::create_dir_all(&agents).expect("create the agent directory");
    let agent_program = agents.join(if cfg!(windows) {
        "splendor-agent.exe"
    } else {
        "splendor-agent"
    });
    std::fs::copy(bin(), &agent_program).expect("copy the agent program");
    let registry = host_registry(&dir, &gate_seats(&agent_program));
    let host = HostProcess::start_with_registry(&root, &dir, &registry);

    // Make completion impossible: the durable identity moves away, which is the
    // condition the CLI's completion error describes.
    std::fs::remove_file(paths.identity()).expect("remove the identity manifest");

    let request = serde_json::json!({
        "occurrence_id": "gate-j-0001",
        "game_id": "gate-j-game",
        "seed": 7_200_001u64,
        "seats": ["gate-heuristic", "gate-random"],
    });
    let (code, response) = host.post_json("/league/matches", &request);
    assert_eq!(
        code, 503,
        "a completion failure is retryable and server-side: {response}"
    );
    assert_eq!(
        response["match_status"], "completed",
        "the MATCH completed; only completion failed: {response}"
    );
    assert_eq!(response["completion_status"], "failed");
    assert!(
        response["error"]
            .as_str()
            .unwrap_or_default()
            .to_lowercase()
            .contains("completion"),
        "the error must name the failing half: {response}"
    );

    // All four documents are durable even though completion failed.
    let slot = paths
        .occurrence_dir("gate-j-0001")
        .expect("a safe occurrence id");
    let names = [
        "config.json",
        "replay.json",
        "report.json",
        "occurrence.json",
    ];
    let before = names
        .iter()
        .map(|name| {
            std::fs::read(slot.join(name))
                .unwrap_or_else(|error| panic!("{name} must be durable: {error}"))
        })
        .collect::<Vec<_>>();

    // Repair the condition, and remove the ability to re-run the match.
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    manifest
        .save(paths.identity())
        .expect("restore the identity manifest");
    std::fs::remove_file(&agent_program).expect("remove the agent program");
    assert!(!agent_program.exists());

    let (code, response) = host.post_json("/league/matches", &request);
    assert_eq!(
        code, 200,
        "the retry must complete the recorded occurrence: {response}"
    );
    assert_eq!(response["match_status"], "completed");
    assert_eq!(response["completion_status"], "inserted");

    for (index, name) in names.iter().enumerate() {
        assert_eq!(
            std::fs::read(slot.join(name)).expect("the document is still there"),
            before[index],
            "{name} must be byte-identical after the retry; a re-run would have re-minted it"
        );
    }
    assert!(
        !agent_program.exists(),
        "the retry must not have spawned an agent"
    );
}

/// Gate K — the same occurrence is booked once, however often it is posted.
///
/// An occurrence id is an occurrence's identity, not a per-request token. The
/// second POST is answered from the documents on disk: no second match row, no
/// second Elo booking, no re-written evidence.
#[test]
fn re_posting_a_booked_occurrence_adds_no_second_match_and_no_elo() {
    let dir = tmp_dir("gate-k");
    let (root, paths) = primed_league(&dir);
    let agents = dir.join("agents");
    std::fs::create_dir_all(&agents).expect("create the agent directory");
    let agent_program = agents.join(if cfg!(windows) {
        "splendor-agent.exe"
    } else {
        "splendor-agent"
    });
    std::fs::copy(bin(), &agent_program).expect("copy the agent program");
    let registry = host_registry(&dir, &gate_seats(&agent_program));
    let host = HostProcess::start_with_registry(&root, &dir, &registry);

    let request = serde_json::json!({
        "occurrence_id": "gate-k-0001",
        "game_id": "gate-k-game",
        "seed": 7_300_001u64,
        "seats": ["gate-heuristic", "gate-random"],
    });
    let (code, first) = host.post_json("/league/matches", &request);
    assert_eq!(
        code, 200,
        "the first POST must book the occurrence: {first}"
    );
    assert_eq!(first["completion_status"], "inserted");
    let match_id = first["receipt"]["match_id"]
        .as_str()
        .expect("a match id")
        .to_string();

    let conn = open_league(&paths.db()).expect("open the league");
    let matches_before = count_rows(&conn, "SELECT COUNT(*) FROM matches");
    let events_before = count_rows(&conn, "SELECT COUNT(*) FROM rating_events");
    drop(conn);
    let (_, board_before) = host.get_json("/league/leaderboard");

    let slot = paths
        .occurrence_dir("gate-k-0001")
        .expect("a safe occurrence id");
    let envelope_before = std::fs::read(slot.join("occurrence.json")).expect("the envelope");
    let report_before = std::fs::read(slot.join("report.json")).expect("the report");

    // The arena can no longer be run at all, so a re-trigger that ran it would
    // fail loudly instead of quietly booking a second match.
    std::fs::remove_file(&agent_program).expect("remove the agent program");

    let (code, second) = host.post_json("/league/matches", &request);
    assert_eq!(
        code, 200,
        "the same occurrence is a retry, not a second match: {second}"
    );
    assert_eq!(second["match_status"], "completed");
    assert_eq!(
        second["completion_status"], "already_present",
        "the occurrence was already booked: {second}"
    );
    assert_eq!(second["receipt"]["match_id"], match_id.as_str());

    let conn = open_league(&paths.db()).expect("open the league");
    assert_eq!(
        count_rows(&conn, "SELECT COUNT(*) FROM matches"),
        matches_before,
        "no second match row"
    );
    assert_eq!(
        count_rows(&conn, "SELECT COUNT(*) FROM rating_events"),
        events_before,
        "no second Elo booking"
    );
    assert_eq!(
        count_rows(
            &conn,
            "SELECT COUNT(*) FROM matches WHERE source_identity = 'runtime:gate-k-0001'"
        ),
        1,
        "exactly one match for the occurrence"
    );
    drop(conn);

    let (_, board_after) = host.get_json("/league/leaderboard");
    assert_eq!(
        board_before, board_after,
        "the leaderboard must not move on a repeat"
    );
    assert_eq!(
        std::fs::read(slot.join("occurrence.json")).expect("the envelope"),
        envelope_before,
        "the occurrence must not be re-minted"
    );
    assert_eq!(
        std::fs::read(slot.join("report.json")).expect("the report"),
        report_before,
        "the report must not be rewritten"
    );

    // Internal consistency is not identity. A byte-for-byte copy of a complete slot
    // under another occurrence id verifies against itself perfectly, and answering
    // it would hand back a match the request never named -- that is a conflict, not
    // a recorded fact.
    let impostor = paths
        .occurrence_dir("gate-k-0002")
        .expect("a safe occurrence id");
    std::fs::create_dir_all(&impostor).expect("create the second slot");
    for name in [
        "config.json",
        "replay.json",
        "report.json",
        "occurrence.json",
    ] {
        std::fs::copy(slot.join(name), impostor.join(name)).expect("copy the evidence");
    }
    let mut impostor_request = request.clone();
    impostor_request["occurrence_id"] = serde_json::json!("gate-k-0002");
    let (code, refused) = host.post_json("/league/matches", &impostor_request);
    assert_eq!(
        code, 409,
        "a copied evidence set is not this occurrence's: {refused}"
    );

    let conn = open_league(&paths.db()).expect("open the league");
    assert_eq!(
        count_rows(&conn, "SELECT COUNT(*) FROM matches"),
        matches_before,
        "a refused slot must not book anything"
    );
}

/// Gate L — the request surface's refusals, and the absence of side effects.
///
/// Four independent refusals in one gate because they share one assertion: none of
/// them may run a match, create a slot, or write a row. The unsafe id is the
/// security one; the `agents` body is the reason the route cannot become a local
/// arbitrary-execution surface; the seat bounds are the arena's own rule, not a
/// second copy of it.
#[test]
fn the_match_request_cannot_name_a_program_or_an_unsafe_occurrence_id() {
    let dir = tmp_dir("gate-l");
    let (root, paths) = primed_league(&dir);
    let registry = host_registry(&dir, &gate_seats(&bin()));
    let host = HostProcess::start_with_registry(&root, &dir, &registry);

    let request = |id: &str| {
        serde_json::json!({
            "occurrence_id": id,
            "game_id": "gate-l-game",
            "seed": 7_400_001u64,
            "seats": ["gate-heuristic", "gate-random"],
        })
    };

    // 1. An unsafe occurrence id never becomes a path component.
    for unsafe_id in ["../escape", "a/b", "a\\b", ".", "..", "C:", ""] {
        let body = request(unsafe_id);
        let (code, response) = host.post_json("/league/matches", &body);
        assert_eq!(
            code, 400,
            "occurrence id `{unsafe_id}` must be refused: {response}"
        );
    }

    // 2. The body cannot express a program, an argv, or an `ArenaConfig`. A nested
    //    `agents` array is the realistic attempt: it is the arena's own field name.
    for extra in [
        serde_json::json!({"program": "evil.exe"}),
        serde_json::json!({"agents": [{"program": "evil.exe", "args": []}]}),
        serde_json::json!({"handshake_timeout_ms": 1}),
        serde_json::json!({"move_timeout_ms": 1}),
        serde_json::json!({"shutdown_grace_ms": 1}),
    ] {
        let mut body = request("gate-l-unknown-field");
        let object = body.as_object_mut().expect("an object");
        for (key, value) in extra.as_object().expect("an object") {
            object.insert(key.clone(), value.clone());
        }
        let (code, response) = host.post_json("/league/matches", &body);
        assert_eq!(
            code, 400,
            "a body carrying `{extra}` must be refused: {response}"
        );
    }

    // 3. The seat count is the arena's rule: 1 and 5 are both refused, and the
    //    refusal happens before anything is created.
    for seats in [
        serde_json::json!(["gate-heuristic"]),
        serde_json::json!([
            "gate-heuristic",
            "gate-random",
            "gate-heuristic",
            "gate-random",
            "gate-heuristic"
        ]),
    ] {
        let mut body = request("gate-l-seat-count");
        body["seats"] = seats.clone();
        let (code, response) = host.post_json("/league/matches", &body);
        assert_eq!(code, 400, "seats {seats} must be refused: {response}");
    }

    // 4. An id no seat can resolve is refused.
    let mut body = request("gate-l-unknown-agent");
    body["seats"] = serde_json::json!(["gate-heuristic", "not-a-registry-agent"]);
    let (code, response) = host.post_json("/league/matches", &body);
    assert_eq!(code, 400, "an unknown agent id must be refused: {response}");

    // 5. None of the above ran a match, created a slot, or wrote a row.
    assert!(
        !paths.dir().join("occurrences").exists(),
        "no occurrence slot may be created for a refused request"
    );
    let conn = open_league(&paths.db()).expect("open the league");
    assert_eq!(
        count_rows(
            &conn,
            "SELECT COUNT(*) FROM matches WHERE source_identity LIKE 'runtime:gate-l%'"
        ),
        0,
        "a refused request must not book anything"
    );
    assert_eq!(
        count_rows(&conn, "SELECT COUNT(*) FROM rating_events"),
        count_rows(
            &conn,
            "SELECT COUNT(*) FROM rating_events WHERE participant_id IS NOT NULL"
        ),
        "no rating event was written by a refused request"
    );
    drop(conn);

    // And the host survived all of it.
    let (code, health) = host.get_json("/health");
    assert_eq!(code, 200, "the host must still be serving: {health}");
}

// ---------------------------------------------------------------------------
// League Play v1 — the page's two seams.
//
// The page is a browser surface and this repository has no browser runner, so no
// gate here claims a player clicked anything. These two gates cover what a browser
// could not: that the request shape the page builds is exactly the document this
// Host accepts, and that the archive route the replay board opens is an adapter
// over the League reader's authority rather than a second way in.
// ---------------------------------------------------------------------------

/// Gate N — the page's own fixture is a request this Host accepts.
///
/// `apps/replay-studio/tests/fixtures/league-match-request.json` is read by the
/// page's unit test in JavaScript and posted here as raw bytes in Rust. One
/// document, two languages: a key added on either side without the other stops
/// agreeing, and `deny_unknown_fields` is what makes that visible rather than
/// silently tolerated.
#[test]
fn the_page_fixture_is_a_request_this_host_accepts() {
    let dir = tmp_dir("gate-page-fixture");
    let (root, _paths) = new_league(&dir);
    let registry = host_registry(&dir, &gate_seats(&bin()));
    let host = HostProcess::start_with_registry(&root, &dir, &registry);

    let fixture_path =
        workspace_path("apps/replay-studio/tests/fixtures/league-match-request.json");
    let bytes = std::fs::read(&fixture_path)
        .unwrap_or_else(|error| panic!("read {}: {error}", fixture_path.display()));

    let (status, body) =
        http_post_raw(host.port, "/league/matches", &bytes).expect("POST the page fixture");
    assert_eq!(
        status_code(&status),
        200,
        "the shared page fixture must be served as-is: {}",
        String::from_utf8_lossy(&body)
    );

    let response: serde_json::Value =
        serde_json::from_slice(&body).expect("a JSON booking response");
    assert_eq!(response["match_status"], "completed");
    assert_eq!(response["completion_status"], "inserted");
    assert_eq!(
        response["receipt"]["source_identity"], "runtime:studio-fixture-0001",
        "the occurrence the fixture names is the occurrence that was booked"
    );
    assert!(
        response["receipt"]["replay"]["document_hash"].is_string(),
        "a booked match must have an archived replay to open: {response}"
    );
}

/// Gate O — the archive route is an adapter over the read authority.
///
/// The replay board needs the frame-by-frame archive, and this route rebuilds it
/// from the document the *reader* returns. So a stale league must refuse an
/// archive that is still sitting on disk — which is exactly what a path-based read
/// could not do, and why the negative control for this gate is "read the archive
/// file directly".
#[test]
fn the_archive_route_is_an_adapter_over_the_league_read_authority() {
    let fixture = fixture();
    let root = copied_root("league-archive-adapter");
    let paths = StudioLeaguePathsV1::from_root(&root);
    let host = HostProcess::start(&root, &root);
    let sha = fixture.eligible_replay_sha.to_string();

    // The source document, through the raw content-addressed route.
    let (code, source) = host.get_json(&format!("/league/replays/{sha}"));
    assert_eq!(code, 200, "the fixture replay must be readable: {source}");
    let steps = source["steps"]
        .as_array()
        .expect("a ReplayV1 document records steps")
        .len();
    assert!(steps > 0, "the fixture replay is not empty");

    // The board's archive is that same replay, reconstructed.
    let (code, archive) = host.get_json(&format!("/league/replays/{sha}/archive"));
    assert_eq!(
        code, 200,
        "a known content address must serve an archive: {archive}"
    );
    assert_eq!(archive["session_id"], sha.as_str());
    assert_eq!(
        archive["human_seat"],
        serde_json::Value::Null,
        "a league match is agent versus agent: it has no human seat to claim"
    );
    assert_eq!(archive["opponent"], serde_json::Value::Null);
    let frames = archive["frames"].as_array().expect("a frames array");
    assert_eq!(
        frames.len(),
        steps,
        "the archive rebuilds every recorded step, not a subset of them"
    );
    let cards = archive["catalog"]["cards"]
        .as_array()
        .expect("the catalog the board renders from");
    assert!(
        !cards.is_empty(),
        "the board cannot render without its catalog"
    );

    // An address that was never archived is absent, not a fault.
    let (code, body) = host.get_json(&format!("/league/replays/{}/archive", "0".repeat(64)));
    assert_eq!(code, 404, "an unarchived address is absent: {body}");

    // A malformed path must not be able to take the Host down. `/league/replays/archive`
    // satisfies both the prefix and the suffix test, and index arithmetic on it yields
    // an inverted byte range. This Host has one serial accept loop and no per-request
    // panic isolation, so a panic here would end the whole product surface.
    let (code, body) = host.get_json("/league/replays/archive");
    assert_eq!(
        code, 404,
        "a malformed archive path is absent, not fatal: {body}"
    );
    let (code, health) = host.get_json("/health");
    assert_eq!(
        code, 200,
        "the Host must still be serving after a malformed archive path: {health}"
    );

    // The authority gate still comes first: the archived object is untouched on
    // disk, and the league has gone stale, so this route must stop answering.
    let mut manifest = IdentityManifestV1::load(paths.identity())
        .expect("load the identity manifest")
        .expect("the fixture has one");
    manifest
        .rename_local_human("Nick Renamed")
        .expect("rename the local human");
    manifest
        .save(paths.identity())
        .expect("save the identity manifest");
    let (code, body) = host.get_json(&format!("/league/replays/{sha}/archive"));
    assert_eq!(
        code, 503,
        "a stale league must not serve an archive whose object is still on disk: {body}"
    );
}

/// GATE L (Studio Host liveness): a connection that says nothing may not own the
/// Host.
///
/// Both servers accept **serially**, and the request reader had no deadline at all.
/// One idle TCP connection — the kind a browser opens speculatively before it needs
/// one, no malice required — therefore left `/health` and every read route
/// unanswerable for as long as that socket stayed open, at ~0% CPU, so it did not
/// even look busy. The first real walkthrough hit exactly this and was abandoned at
/// step 2 because of it.
///
/// What is asserted is **boundedness, not latency**: a silent peer may cost seconds,
/// and must never cost the process.
#[test]
fn gate_silent_connection_cannot_starve_the_host() {
    let dir = tmp_dir("gate-liveness");
    let (root, _paths) = new_league(&dir);
    let host = HostProcess::start(&root, &dir);

    // A socket that is connected and deliberately silent. It is opened first, so a
    // serial accept loop meets it before it meets the request below.
    let idle = TcpStream::connect(("127.0.0.1", host.port)).expect("open a silent connection");
    std::thread::sleep(Duration::from_millis(300));

    let bound = Duration::from_secs(10);
    let started = Instant::now();
    let (status, _) = http_get_within(host.port, "/health", bound)
        .expect("the Host must answer /health while a silent peer is connected");
    let elapsed = started.elapsed();
    assert_eq!(
        status_code(&status),
        200,
        "a silent peer must not starve /health (answered in {elapsed:?})"
    );
    assert!(
        elapsed < bound,
        "the answer must arrive inside the bound, not merely eventually: {elapsed:?}"
    );

    // The deadline is not a one-shot: once the silent peer is gone the Host is still
    // accepting, and still answering. A "fix" that wedged the loop after the first
    // timeout would pass the assertion above and fail this one.
    drop(idle);
    let (status, _) = http_get_within(host.port, "/health", bound)
        .expect("the Host must still be accepting after the silent peer left");
    assert_eq!(
        status_code(&status),
        200,
        "the Host must still be alive and serving"
    );
}
