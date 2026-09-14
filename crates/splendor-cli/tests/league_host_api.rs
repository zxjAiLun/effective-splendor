//! Commit D Slice 1 — the read-only Studio League Host API.
//!
//! Four gates, deliberately few: root authority, leaderboard truth, match-detail
//! truth, and replay content-addressing. They drive the real binary over a real
//! socket, because the thing under test is a process surface, not a library.
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
    let mut stream = TcpStream::connect(("127.0.0.1", port))?;
    stream.set_read_timeout(Some(Duration::from_secs(60)))?;
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
    /// Start the host with an explicit project root, from an unrelated cwd.
    fn start(root: &Path, cwd: &Path) -> Self {
        let port = free_port();
        let child = Command::new(bin())
            .current_dir(cwd)
            .args([
                "studio-host",
                "--registry",
                &rating_registry().to_string_lossy(),
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
