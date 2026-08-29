//! Real-spawn integration coverage for cross-platform agent program resolution.
//!
//! Tracked league/registry manifests are one cross-platform source of truth,
//! but they name the agent binary with a Windows-style `.exe` suffix. On Linux
//! and macOS that literal path does not exist, so `spawn_agent` resolves it to
//! the host's own spelling (`splendor.exe` -> `splendor`).
//!
//! `src/process.rs` unit-tests the resolver as a pure path function. This file
//! covers the part unit tests cannot: that a registry-shaped program path
//! actually **spawns the real subprocess and completes a real handshake and a
//! real match** on this host, rather than merely resolving to a string.
//!
//! Every test here drives the public entry points — `spawn_agent` or
//! `ArenaRunner::run` — against the `arena-fixture` binary built from this
//! crate. No test asserts on the resolver in isolation.
//!
//! ## Why the binary is staged into a scratch directory
//!
//! `target/` is shared between OS builds, so the *other* platform's binary can
//! be sitting at the very path this crate's resolver would rewrite onto (on
//! Windows, a stale Linux `target/debug/arena-fixture` produced by an earlier
//! build). `resolve_program` deliberately prefers any path that exists, so such
//! a leftover is not merely a stale file: it is silently preferred over the
//! correct spelling and then fails to spawn. Staging a copy into a scratch
//! directory is what makes "the foreign spelling does not exist" a fact the
//! test controls rather than a fact it assumes about the build tree, so both
//! spellings are exercised on both hosts.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;
use std::time::Duration;

use splendor_arena::process::{spawn_agent, InboundEvent};
use splendor_arena::report::ArenaOutcomeV1;
use splendor_arena::{AgentCommand, ArenaConfig, ArenaRunner};
use splendor_core::{Action, PlayerId};
use splendor_protocol::{RecipientMeta, ServerMessage};
use splendor_replay::{record_random_game, verify_replay};

// ---------------------------------------------------------------------------
// Locators
// ---------------------------------------------------------------------------

/// Path to the `arena-fixture` binary, derived from the running test exe so it
/// works on any profile. Mirrors `tests/process.rs` and
/// `tests/runner_process.rs`.
fn fixture_path() -> PathBuf {
    let exe = std::env::current_exe().expect("current_exe");
    let profile_dir = exe
        .parent()
        .and_then(|p| p.parent())
        .expect("test exe is two levels under the profile dir");
    let name = if cfg!(windows) {
        "arena-fixture.exe"
    } else {
        "arena-fixture"
    };
    profile_dir.join(name)
}

/// Copy the built fixture into a scratch directory under a neutral name and
/// return both spellings of it:
///
/// * `registry` — the Windows-style `.exe` path a tracked registry carries;
/// * `bare`     — the same program without the suffix, as a Unix build is named.
///
/// The scratch directory holds exactly one of the two: the native spelling.
/// Whichever is absent is this host's *foreign* spelling and can only be
/// spawned if `resolve_program` rewrites it onto the copy.
fn staged_spellings(tag: &str) -> (PathBuf, PathBuf) {
    let native = fixture_path();
    assert!(
        native.exists(),
        "fixture binary must be built before this test: {native:?}"
    );

    let dir = std::env::temp_dir().join(format!("arena-resolve-{}-{tag}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("create scratch dir");

    let stem = "league-agent";
    let copy_name = if cfg!(windows) {
        format!("{stem}.exe")
    } else {
        stem.to_string()
    };
    let registry = dir.join(format!("{stem}.exe"));
    let bare = dir.join(stem);

    std::fs::copy(&native, dir.join(copy_name)).expect("stage fixture copy");

    // The two spellings are the resolver's entire input space; precondition
    // them explicitly so a failure names the cause.
    assert_eq!(registry.exists(), cfg!(windows), "registry spelling");
    assert_eq!(bare.exists(), !cfg!(windows), "bare spelling");
    (registry, bare)
}

// ---------------------------------------------------------------------------
// Command builders
// ---------------------------------------------------------------------------

/// A legacy top-level fixture subcommand (`echo`, `early-exit`, ...). These are
/// reached **without** the `agent` prefix: dispatching `agent echo` would enter
/// protocol mode with an unknown agent mode instead of the echo fixture.
fn fixture_cmd(program: PathBuf, sub: &str) -> AgentCommand {
    AgentCommand {
        program,
        args: vec![sub.to_string()],
    }
}

/// The protocol-speaking fixture: `agent <mode> [options]`.
fn agent_cmd(program: PathBuf, mode: &str, opts: &[&str]) -> AgentCommand {
    let mut args = vec!["agent".to_string(), mode.to_string()];
    for o in opts {
        args.push(o.to_string());
    }
    AgentCommand { program, args }
}

// ---------------------------------------------------------------------------
// Fixture helpers for a full match
// ---------------------------------------------------------------------------

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

fn tmp_dir() -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("arena-resolve-{}-{}", std::process::id(), n));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

fn recorded_actions(player_count: u8, seed: u64, action_seed: u64) -> Vec<Action> {
    let (_state, replay) = record_random_game(player_count, seed, action_seed)
        .expect("record_random_game must terminate for the frozen seeds");
    replay.steps.into_iter().map(|s| s.action).collect()
}

fn write_script(actions: &[Action], path: &Path) {
    let json = serde_json::to_string(actions).expect("serialize actions");
    std::fs::write(path, json).expect("write script");
}

/// Spawn `program` in `echo` mode, send one Ping, and require the echoed NDJSON
/// line back within the timeout. A resolver that returned the right string but
/// spawned nothing (or spawned something that immediately died) times out here.
fn assert_echoes_ping(program: &Path, seat: PlayerId) {
    let (tx, rx) = mpsc::channel();
    let mut proc = spawn_agent(seat, &fixture_cmd(program.to_path_buf(), "echo"), tx)
        .unwrap_or_else(|e| panic!("spawn {program:?}: {e}"));

    let msg = ServerMessage::Ping {
        meta: RecipientMeta::new("g1", seat.0 as u64, seat),
    };
    proc.send(&msg).expect("send flush");

    let mut saw_line = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(10)) {
            Ok(InboundEvent::Line { seat: s, line }) => {
                assert_eq!(s, seat);
                assert!(
                    line.starts_with('{') && line.contains("\"type\":\"ping\""),
                    "unexpected echo payload: {line:?}"
                );
                saw_line = true;
                break;
            }
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    assert!(
        saw_line,
        "{program:?} never produced an NDJSON line; resolution did not reach a real subprocess"
    );
}

// ---------------------------------------------------------------------------
// Tests: real spawn + real NDJSON round trip
// ---------------------------------------------------------------------------

/// The registry spelling is what every tracked manifest carries. On non-Windows
/// it does not exist and must be rewritten onto the bare copy; on Windows it is
/// already the native path and must be used verbatim. Either way it must spawn.
#[test]
fn registry_spelled_path_spawns_and_echoes() {
    let (registry, _bare) = staged_spellings("registry-echo");
    assert_echoes_ping(&registry, PlayerId(0));
}

/// The bare spelling is the inverse: native on Unix, and on Windows only
/// spawnable once the resolver appends the suffix. Pins the branch that the
/// registry-spelling test does not reach on this host.
#[test]
fn bare_spelled_path_spawns_and_echoes() {
    let (_registry, bare) = staged_spellings("bare-echo");
    assert_echoes_ping(&bare, PlayerId(1));
}

/// A program that exists under neither spelling must still surface as a spawn
/// error. The resolver rewrites only onto a file that actually exists; it never
/// silently swallows a genuinely missing program.
#[test]
fn missing_program_under_both_spellings_still_fails() {
    let dir = tmp_dir();
    let missing = dir.join("no-such-agent.exe");
    assert!(!missing.exists());
    assert!(!dir.join("no-such-agent").exists());

    let (tx, _rx) = mpsc::channel();
    let result = spawn_agent(PlayerId(0), &fixture_cmd(missing, "echo"), tx);
    assert!(
        result.is_err(),
        "a program missing under both spellings must fail, not be rewritten"
    );
}

// ---------------------------------------------------------------------------
// Tests: full handshake + full match through the public runner
// ---------------------------------------------------------------------------

/// The strong form: configure **both** seats with the registry-spelled program
/// path and run a complete match through `ArenaRunner::run`. This exercises the
/// real handshake, every observation/request/action round trip, and replay
/// verification — the end-to-end evidence that a tracked `.exe` registry path
/// works on this host.
#[test]
fn registry_spelled_path_completes_a_full_match() {
    let (registry, _bare) = staged_spellings("registry-match");

    let actions = recorded_actions(2, 42, 1001);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().expect("script path is utf-8").to_string();

    let mut agents = Vec::new();
    for seat in 0..2u8 {
        let transcript = format!("{}/seat-{}", dir.display(), seat);
        agents.push(agent_cmd(
            registry.clone(),
            "scripted",
            &["--script", &script_str, "--transcript", &transcript],
        ));
    }

    let config = ArenaConfig {
        game_id: "resolve-exe-full-match".to_string(),
        seed: 42,
        // Generous budgets: spawning real subprocesses under parallel test
        // execution must not turn scheduling delay into a protocol timeout.
        handshake_timeout_ms: 10_000,
        move_timeout_ms: 10_000,
        shutdown_grace_ms: 200,
        agents,
    };

    let run = ArenaRunner::run(config).expect("match completes");

    match &run.report.outcome {
        ArenaOutcomeV1::Completed {
            completed_plies,
            replay_final_hash,
            ..
        } => {
            let replay = run.replay.as_ref().expect("completed run has replay");
            assert_eq!(
                *completed_plies,
                replay.steps.len() as u32,
                "completed_plies must equal replay step count"
            );
            assert_eq!(
                replay_final_hash,
                &replay.final_state_hash.as_str().to_string(),
                "report final hash must equal replay final hash"
            );
        }
        other => panic!("expected Completed, got {other:?}"),
    }

    let replay = run.replay.as_ref().expect("replay present");
    verify_replay(replay).expect("replay must verify");

    // Identities must come from the real Client Hello, which proves the
    // handshake completed through the resolved binary.
    for a in &run.report.agents {
        assert_eq!(a.agent_name.as_deref(), Some("arena-fixture"));
        assert_eq!(a.agent_version.as_deref(), Some("1.0"));
    }
}
