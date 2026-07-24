//! Commit 4: real subprocess / real NDJSON / real deadline / real pipe lifecycle
//! integration tests, plus Arena v1 golden artifacts.
//!
//! These tests spawn the `arena-fixture` binary (built from this crate) as the
//! agent process and drive it through the *public* [`ArenaRunner::run`]
//! entry point — never `run_with`. They cover:
//! - normal 2/3/4-player matches that complete with a verifying replay;
//! - the full process fault matrix (handshake/action timeout, malformed,
//!   protocol/game/request mismatch, illegal, duplicate/unsolicited, early
//!   exit, oversize, non-UTF-8);
//! - stderr-flood resilience end-to-end;
//! - blind-reserve information isolation read from the raw subprocess
//!   transcripts (no hidden seed / full-state hash / replay shape leaks);
//! - process cleanup (timeout / early-exit / malformed / oversize / flood and a
//!   20-run stress loop);
//! - frozen golden artifacts that byte-match `include_str!`.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

use serde_json::Value;

use splendor_arena::report::{AgentFault, ArenaOutcomeV1, ArenaPhase};
use splendor_arena::{AgentCommand, ArenaConfig, ArenaRun, ArenaRunner};
use splendor_core::{Action, GameConfig, Ruleset};
use splendor_protocol::{parse_server_line, ServerMessage};
use splendor_replay::{record_random_game, verify_replay, ReplayRecorder};

// ---------------------------------------------------------------------------
// Locators / builders
// ---------------------------------------------------------------------------

/// Path to the `arena-fixture` binary, derived from the running test exe so it
/// works on any platform and profile (mirrors `tests/process.rs`).
fn fixture_path() -> PathBuf {
    let exe = std::env::current_exe().expect("current_exe");
    let profile_dir = exe
        .parent()
        .and_then(|p| p.parent())
        .expect("two levels under profile");
    let name = if cfg!(windows) {
        "arena-fixture.exe"
    } else {
        "arena-fixture"
    };
    profile_dir.join(name)
}

/// Build an `AgentCommand` for `arena-fixture agent <mode> [opts...]`.
fn agent_cmd(mode: &str, opts: &[&str]) -> AgentCommand {
    let mut args = vec!["agent".to_string(), mode.to_string()];
    for o in opts {
        args.push(o.to_string());
    }
    AgentCommand {
        program: fixture_path(),
        args,
    }
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

/// A unique temp directory for one match's scripts/transcripts.
fn tmp_dir() -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("arena-proc-{}-{}", std::process::id(), n));
    std::fs::create_dir_all(&dir).expect("create temp dir");
    dir
}

/// Deterministically record a complete game and return its action script.
fn recorded_actions(player_count: u8, seed: u64, action_seed: u64) -> Vec<Action> {
    let (_state, replay) = record_random_game(player_count, seed, action_seed)
        .expect("record_random_game must terminate for the frozen seeds");
    replay.steps.into_iter().map(|s| s.action).collect()
}

/// Write an action script (JSON array) the `scripted` agent replays.
fn write_script(actions: &[Action], path: &Path) {
    let json = serde_json::to_string(actions).expect("serialize actions");
    std::fs::write(path, json).expect("write script");
}

/// Build a script whose first ply is a blind `ReserveDeck` (falling back to a
/// market reserve), then finishes the game with a deterministic policy. Used by
/// the information-isolation test to guarantee a hidden reserve actually occurs.
fn reserve_first_script(seed: u64) -> Vec<Action> {
    let mut rec = ReplayRecorder::new(GameConfig {
        player_count: 2,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("recorder");
    let mut actions = Vec::new();

    let legal0 = rec.legal_actions();
    let reserve = legal0
        .iter()
        .copied()
        .find(|a| matches!(a, Action::ReserveDeck { .. }))
        .or_else(|| {
            legal0
                .iter()
                .copied()
                .find(|a| matches!(a, Action::ReserveMarket { .. }))
        })
        .expect("a reserve action is available at ply 0");
    rec.apply(reserve).expect("apply ply-0 reserve");
    actions.push(reserve);

    let mut rng = seed ^ 0x9E37_79B9_7F4A_7C15;
    let mut next = || {
        let mut x = rng;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        rng = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    };
    while !rec.is_terminal() {
        let la = rec.legal_actions();
        let a = la[(next() % la.len() as u64) as usize];
        rec.apply(a).expect("apply");
        actions.push(a);
    }
    actions
}

/// Run a clean, scripted, N-player match and return the completed run.
fn run_normal(game_id: &str, player_count: u8, seed: u64, action_seed: u64) -> ArenaRun {
    let actions = recorded_actions(player_count, seed, action_seed);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().unwrap().to_string();
    let mut agents = Vec::new();
    for seat in 0..player_count {
        let transcript = format!("{}/seat-{}", dir.display(), seat);
        agents.push(agent_cmd(
            "scripted",
            &["--script", &script_str, "--transcript", &transcript],
        ));
    }
    let config = ArenaConfig {
        game_id: game_id.to_string(),
        seed,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents,
    };
    ArenaRunner::run(config).expect("normal match completes")
}

/// Run a single-fault match (seat 0 = fault mode, remaining seats scripted)
/// and assert it returns within a generous wall-clock budget.
fn run_fault(mode: &str) -> ArenaRun {
    let actions = recorded_actions(2, 42, 1001);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().unwrap().to_string();
    let mut agents = vec![agent_cmd(mode, &[])];
    agents.push(agent_cmd("scripted", &["--script", &script_str]));
    let config = ArenaConfig {
        game_id: format!("fault-{mode}"),
        seed: 42,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents,
    };
    let start = Instant::now();
    let run = ArenaRunner::run(config).expect("fault match returns a result");
    assert!(
        start.elapsed() < Duration::from_secs(10),
        "fault match ({mode}) must not hang"
    );
    run
}

/// Run a match with two explicit fixture modes (seat 0 / seat 1) and no
/// scripts; used by fault pairings that must control both seats' behavior.
fn run_pair(game_id: &str, mode0: &str, mode1: &str) -> ArenaRun {
    let config = ArenaConfig {
        game_id: game_id.to_string(),
        seed: 42,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents: vec![agent_cmd(mode0, &[]), agent_cmd(mode1, &[])],
    };
    let start = Instant::now();
    let run = ArenaRunner::run(config).expect("pair match returns a result");
    assert!(
        start.elapsed() < Duration::from_secs(10),
        "pair match ({mode0}/{mode1}) must not hang"
    );
    run
}

// ---------------------------------------------------------------------------
// Assertions
// ---------------------------------------------------------------------------

fn assert_completed(run: &ArenaRun) {
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
    // Identities must come from the real Client Hello.
    for a in &run.report.agents {
        assert_eq!(a.agent_name.as_deref(), Some("arena-fixture"));
        assert_eq!(a.agent_version.as_deref(), Some("1.0"));
    }
}

fn assert_aborted(
    run: &ArenaRun,
    seat: u8,
    phase: ArenaPhase,
    reason: AgentFault,
    request_id: Option<u64>,
    completed_plies: u32,
) {
    match &run.report.outcome {
        ArenaOutcomeV1::Aborted {
            seat: s,
            phase: p,
            reason: r,
            request_id: rid,
            completed_plies: cp,
        } => {
            assert_eq!(*s, seat, "aborted seat");
            assert_eq!(*p, phase, "aborted phase");
            assert_eq!(*r, reason, "aborted reason");
            assert_eq!(*rid, request_id, "aborted request_id");
            assert_eq!(*cp, completed_plies, "aborted completed_plies");
        }
        other => panic!("expected Aborted, got {other:?}"),
    }
    assert!(run.replay.is_none(), "aborted run must have no replay");
}

// ---------------------------------------------------------------------------
// Normal process matches (2/3/4 players)
// ---------------------------------------------------------------------------

#[test]
fn normal_process_match_2p_replay_verifies() {
    let run = run_normal("normal-2p-seed42", 2, 42, 1001);
    assert_completed(&run);
}

#[test]
fn normal_process_match_3p_replay_verifies() {
    let run = run_normal("normal-3p-seed42", 3, 42, 1002);
    assert_completed(&run);
}

#[test]
fn normal_process_match_4p_replay_verifies() {
    let run = run_normal("normal-4p-seed42", 4, 42, 1003);
    assert_completed(&run);
}

// ---------------------------------------------------------------------------
// Fault matrix
// ---------------------------------------------------------------------------

#[test]
fn fault_handshake_timeout() {
    let run = run_fault("handshake-timeout");
    assert_aborted(
        &run,
        0,
        ArenaPhase::Handshake,
        AgentFault::HandshakeTimeout,
        None,
        0,
    );
}

#[test]
fn fault_action_timeout() {
    let run = run_fault("action-timeout");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::ActionTimeout,
        Some(1),
        0,
    );
}

#[test]
fn fault_malformed_action() {
    let run = run_fault("malformed-action");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::MalformedMessage,
        Some(1),
        0,
    );
}

#[test]
fn fault_wrong_protocol() {
    let run = run_fault("wrong-protocol");
    assert_aborted(
        &run,
        0,
        ArenaPhase::Handshake,
        AgentFault::ProtocolVersionMismatch,
        None,
        0,
    );
}

#[test]
fn fault_wrong_game_id() {
    let run = run_fault("wrong-game-id");
    assert_aborted(
        &run,
        0,
        ArenaPhase::Handshake,
        AgentFault::GameIdMismatch,
        None,
        0,
    );
}

#[test]
fn fault_wrong_request_id() {
    let run = run_fault("wrong-request-id");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::WrongRequestId,
        Some(1),
        0,
    );
}

#[test]
fn fault_illegal_action() {
    let run = run_fault("illegal-action");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::IllegalAction,
        Some(1),
        0,
    );
}

#[test]
fn fault_duplicate_hello() {
    // seat 0 sends two Hellos and stays alive; seat 1 never handshakes at
    // all. The handshake window is therefore guaranteed to still be open when
    // the second Hello is processed: the abort is deterministically the
    // duplicate Hello in the handshake phase, never a phase race.
    let run = run_pair(
        "fault-duplicate-hello",
        "duplicate-hello",
        "handshake-timeout",
    );
    assert_aborted(
        &run,
        0,
        ArenaPhase::Handshake,
        AgentFault::UnexpectedMessage,
        None,
        0,
    );
}

#[test]
fn fault_unsolicited_message() {
    // seat 0 = action-timeout: handshakes cleanly, then stays silent after
    // receiving RequestAction (the 500ms timeout is only a backstop). seat 1 =
    // unsolicited-message: handshakes cleanly, then speaks an unsolicited Action
    // upon receiving its own GameStart and stays alive reading stdin.
    //
    // Because seat 0 never emits an Action line, the only client line that can
    // enter the fan-in channel while request 1 is outstanding is seat 1's
    // unsolicited Action. This removes the cross-process race where seat 0's
    // legal reply could win the channel first. seat 1's message therefore
    // deterministically triggers `unexpected_message` at the action window
    // before ActionTimeout can fire. Repeat to prove stability across
    // scheduling variance.
    for _ in 0..10 {
        let run = run_pair("fault-unsolicited", "action-timeout", "unsolicited-message");
        assert_aborted(
            &run,
            1,
            ArenaPhase::ActionRequest,
            AgentFault::UnexpectedMessage,
            Some(1),
            0,
        );
    }
}

#[test]
fn fault_early_exit() {
    let run = run_fault("early-exit");
    assert_aborted(
        &run,
        0,
        ArenaPhase::Handshake,
        AgentFault::AgentEof,
        None,
        0,
    );
}

#[test]
fn fault_oversize_handshake() {
    let run = run_fault("oversize-handshake");
    assert_aborted(
        &run,
        0,
        ArenaPhase::Handshake,
        AgentFault::MessageTooLarge,
        None,
        0,
    );
}

#[test]
fn fault_oversize_action() {
    let run = run_fault("oversize-action");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::MessageTooLarge,
        Some(1),
        0,
    );
}

#[test]
fn fault_non_utf8_action() {
    let run = run_fault("non-utf8-action");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::AgentIo,
        Some(1),
        0,
    );
}

// ---------------------------------------------------------------------------
// Fault sequencing (priority lock)
// ---------------------------------------------------------------------------

#[test]
fn fault_seq_wrong_protocol_wins_over_request_id() {
    // A single Action message combining wrong protocol + wrong request id
    // (correct game id, legal action) after a clean handshake must classify
    // as the protocol mismatch: `protocol` outranks `request_id`.
    let run = run_fault("action-wrong-protocol-and-request");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::ProtocolVersionMismatch,
        Some(1),
        0,
    );
}

#[test]
fn fault_seq_wrong_game_wins_over_illegal() {
    // A single Action message combining wrong game id + illegal action
    // (correct protocol, correct request id) must classify as the game-id
    // mismatch: `game_id` outranks `legality`.
    let run = run_fault("action-wrong-game-and-illegal");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::GameIdMismatch,
        Some(1),
        0,
    );
}

#[test]
fn fault_seq_correct_metadata_illegal_action() {
    // All metadata correct; only the action itself is illegal. Only then may
    // the classification fall through to `illegal_action`.
    let run = run_fault("action-correct-meta-illegal");
    assert_aborted(
        &run,
        0,
        ArenaPhase::ActionRequest,
        AgentFault::IllegalAction,
        Some(1),
        0,
    );
}

// ---------------------------------------------------------------------------
// Stderr flood
// ---------------------------------------------------------------------------

#[test]
fn scripted_stderr_flood_exceeds_64kib() {
    // Spawn the fixture directly with a live (piped) stdin so it keeps running
    // and floods stderr; confirm well over 64 KiB is produced.
    use std::process::{Command, Stdio};
    let mut child = Command::new(fixture_path())
        .args(["agent", "scripted-stderr-flood"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn flood fixture");
    let mut stderr = child.stderr.take().expect("stderr piped");
    let counter = std::thread::spawn(move || {
        // Read until the 64 KiB threshold is clearly exceeded, with a
        // generous wall-clock cap for slow or loaded builders. The contract
        // under test is "the flood can exceed 64 KiB", not a fixed-window
        // throughput figure.
        let target = 64 * 1024 + 1;
        let mut buf = [0u8; 8192];
        let mut total: usize = 0;
        let deadline = Instant::now() + Duration::from_secs(5);
        while total < target && Instant::now() < deadline {
            match stderr.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => total += n,
            }
        }
        total
    });
    let total = counter.join().unwrap();
    let _ = child.kill();
    let _ = child.wait();
    assert!(
        total > 64 * 1024,
        "stderr flood must exceed 64 KiB (got {total} bytes)"
    );
}

#[test]
fn normal_match_with_stderr_flood_completes() {
    let actions = recorded_actions(2, 42, 1001);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().unwrap().to_string();
    let mut agents = Vec::new();
    for seat in 0..2 {
        let transcript = format!("{}/seat-{}", dir.display(), seat);
        agents.push(agent_cmd(
            "scripted-stderr-flood",
            &["--script", &script_str, "--transcript", &transcript],
        ));
    }
    let config = ArenaConfig {
        game_id: "stderr-flood-e2e".to_string(),
        seed: 42,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents,
    };
    let start = Instant::now();
    let run = ArenaRunner::run(config).expect("stderr flood match completes");
    assert!(
        start.elapsed() < Duration::from_secs(10),
        "stderr flood match must not hang"
    );
    assert_completed(&run);
}

// ---------------------------------------------------------------------------
// Blind-reserve information isolation (read from raw subprocess transcripts)
// ---------------------------------------------------------------------------

/// One `card_reserved` event as observed in a transcript: the acting player,
/// whether the reserve came from a deck (blind) or the market (public), and
/// the card id (`Some` = visible to this audience, `None` = redacted).
struct ReservedSeen {
    player: u64,
    from_deck: bool,
    card: Option<u64>,
}

/// Collect `card_reserved` events for one transcript. The reserve is projected
/// as an `event` server message whose inner `event.type` is `card_reserved`.
/// `ReserveSource` is externally tagged, so `from` is `{"deck":..}` for blind
/// reserves and `{"market":..}` for public ones.
fn card_reserved_events(text: &str) -> Vec<ReservedSeen> {
    let mut out = Vec::new();
    for line in text.lines() {
        let v: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if v["type"] == "event" {
            let ev = &v["event"];
            if ev["type"] == "card_reserved" {
                out.push(ReservedSeen {
                    player: ev["player"].as_u64().expect("card_reserved.player"),
                    from_deck: ev["from"].get("deck").is_some(),
                    card: ev["card"].as_u64(),
                });
            }
        }
    }
    out
}

/// Assert no forbidden key (raw seed / full-state hashes / replay steps) leaks
/// anywhere in a server transcript, and that every recipient-scoped message is
/// addressed to `seat` while every observation is viewed by `seat`.
fn check_transcript_isolation(text: &str, seat: u8) {
    let forbidden = [
        "seed",
        "full_state_hash",
        "initial_state_hash",
        "final_state_hash",
        "steps",
    ];
    for line in text.lines() {
        let msg = parse_server_line(line).expect("transcript line parses as server message");
        match &msg {
            ServerMessage::Hello { .. } => {} // broadcast, no recipient
            ServerMessage::GameStart { meta, .. } => {
                assert_eq!(meta.recipient_player_id, seat, "game_start recipient")
            }
            ServerMessage::Observation {
                meta, observation, ..
            } => {
                assert_eq!(
                    meta.recipient.recipient_player_id, seat,
                    "observation recipient"
                );
                assert_eq!(observation.viewer.0, seat, "observation.viewer");
            }
            ServerMessage::RequestAction { meta, .. } => {
                assert_eq!(
                    meta.recipient.recipient_player_id, seat,
                    "request_action recipient"
                );
            }
            ServerMessage::ActionApplied { meta, .. } => {
                assert_eq!(meta.recipient_player_id, seat, "action_applied recipient")
            }
            ServerMessage::Event { meta, .. } => {
                assert_eq!(meta.recipient_player_id, seat, "event recipient")
            }
            ServerMessage::GameEnd { meta, .. } => {
                assert_eq!(meta.recipient_player_id, seat, "game_end recipient")
            }
            ServerMessage::Error { meta, .. } => {
                assert_eq!(meta.recipient_player_id, seat, "error recipient")
            }
            ServerMessage::Ping { meta } => {
                assert_eq!(meta.recipient_player_id, seat, "ping recipient")
            }
        }
        let v: Value = serde_json::from_str(line).expect("transcript line is JSON");
        assert!(
            no_forbidden_keys(&v, &forbidden),
            "forbidden key leaked into transcript: {line}"
        );
    }
}

fn no_forbidden_keys(v: &Value, forbidden: &[&str]) -> bool {
    match v {
        Value::Object(map) => {
            for (k, child) in map {
                if forbidden.contains(&k.as_str()) {
                    return false;
                }
                if !no_forbidden_keys(child, forbidden) {
                    return false;
                }
            }
            true
        }
        Value::Array(arr) => arr.iter().all(|c| no_forbidden_keys(c, forbidden)),
        _ => true,
    }
}

#[test]
fn blind_reserve_information_isolation() {
    let actions = reserve_first_script(42);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().unwrap().to_string();
    let mut agents = Vec::new();
    for seat in 0..2 {
        let transcript = format!("{}/seat-{}", dir.display(), seat);
        agents.push(agent_cmd(
            "scripted",
            &["--script", &script_str, "--transcript", &transcript],
        ));
    }
    let config = ArenaConfig {
        game_id: "blind-reserve-iso".to_string(),
        seed: 42,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents,
    };
    let run = ArenaRunner::run(config).expect("blind-reserve match completes");
    assert!(matches!(
        run.report.outcome,
        ArenaOutcomeV1::Completed { .. }
    ));
    let replay = run.replay.as_ref().expect("replay");
    verify_replay(replay).expect("replay verifies");

    let owner =
        std::fs::read_to_string(dir.join("seat-0.received.ndjson")).expect("owner transcript");
    let opponent =
        std::fs::read_to_string(dir.join("seat-1.received.ndjson")).expect("opponent transcript");

    // The ply-0 blind (deck) reserve is made by seat 0. The owner must see the
    // reserved CardId; the opponent must see the very same event redacted.
    let owner_events = card_reserved_events(&owner);
    let opp_events = card_reserved_events(&opponent);
    assert!(
        owner_events
            .iter()
            .any(|e| e.player == 0 && e.from_deck && e.card.is_some()),
        "owner transcript must reveal its own blind-reserved card id"
    );
    assert!(
        opp_events
            .iter()
            .any(|e| e.player == 0 && e.from_deck && e.card.is_none()),
        "opponent transcript must contain seat 0's blind reserve, redacted"
    );
    // Isolation must hold for every deck reserve in both transcripts: hidden
    // identities are visible only to their owner; market reserves are public.
    for (seat, events) in [(0u64, &owner_events), (1u64, &opp_events)] {
        for e in events.iter() {
            if e.from_deck {
                assert_eq!(
                    e.card.is_some(),
                    e.player == seat,
                    "deck reserve by player {} must be {} in seat {} transcript",
                    e.player,
                    if e.player == seat {
                        "visible"
                    } else {
                        "redacted"
                    },
                    seat
                );
            } else {
                assert!(
                    e.card.is_some(),
                    "market reserve must always be public (seat {seat} transcript)"
                );
            }
        }
    }

    // No raw seed / full-state hashes / replay shape, and strict recipient /
    // viewer isolation on every message.
    check_transcript_isolation(&owner, 0);
    check_transcript_isolation(&opponent, 1);
}

// ---------------------------------------------------------------------------
// Transcript lifecycle (reopen / rename / delete)
// ---------------------------------------------------------------------------

#[test]
fn transcript_files_are_reopenable_and_removable() {
    let actions = recorded_actions(2, 42, 1001);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().unwrap().to_string();
    let mut agents = Vec::new();
    for seat in 0..2 {
        let transcript = format!("{}/seat-{}", dir.display(), seat);
        agents.push(agent_cmd(
            "scripted",
            &["--script", &script_str, "--transcript", &transcript],
        ));
    }
    let config = ArenaConfig {
        game_id: "transcript-lifecycle".to_string(),
        seed: 42,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents,
    };
    let _ = ArenaRunner::run(config).expect("run");

    for seat in 0..2 {
        let p = dir.join(format!("seat-{}.received.ndjson", seat));
        let txt = std::fs::read_to_string(&p).expect("reopen transcript");
        assert!(!txt.is_empty());
        let renamed = dir.join(format!("seat-{}.moved", seat));
        std::fs::rename(&p, &renamed).expect("rename transcript");
        let _ = std::fs::read_to_string(&renamed).expect("reopen renamed transcript");
    }
    // Removing the whole directory proves no lingering pipe/handle is held.
    std::fs::remove_dir_all(&dir).expect("remove transcript dir");
}

// ---------------------------------------------------------------------------
// Process cleanup
// ---------------------------------------------------------------------------

#[test]
fn process_cleanup_timeout_returns() {
    let _ = run_fault("handshake-timeout");
}

#[test]
fn process_cleanup_early_exit_returns() {
    let _ = run_fault("early-exit");
}

#[test]
fn process_cleanup_malformed_returns() {
    let _ = run_fault("malformed-action");
}

#[test]
fn process_cleanup_oversize_returns() {
    let _ = run_fault("oversize-action");
}

#[test]
fn process_cleanup_stderr_flood_returns() {
    let actions = recorded_actions(2, 42, 1001);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().unwrap().to_string();
    let mut agents = Vec::new();
    for seat in 0..2 {
        let transcript = format!("{}/seat-{}", dir.display(), seat);
        agents.push(agent_cmd(
            "scripted-stderr-flood",
            &["--script", &script_str, "--transcript", &transcript],
        ));
    }
    let config = ArenaConfig {
        game_id: "cleanup-stderr-flood".to_string(),
        seed: 42,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents,
    };
    let start = Instant::now();
    let run = ArenaRunner::run(config).expect("stderr flood cleanup returns");
    assert!(start.elapsed() < Duration::from_secs(10));
    assert!(matches!(
        run.report.outcome,
        ArenaOutcomeV1::Completed { .. }
    ));
}

#[test]
fn process_stress_twenty_runs() {
    for i in 0..20 {
        let run = run_normal(&format!("stress-{i}"), 2, 42, 1001);
        assert!(
            matches!(run.report.outcome, ArenaOutcomeV1::Completed { .. }),
            "stress run {i} must complete"
        );
    }
}

// ---------------------------------------------------------------------------
// Golden artifacts (byte-match `include_str!`)
// ---------------------------------------------------------------------------

fn golden_normal_2p() -> ArenaRun {
    run_normal("golden-arena-normal-2p", 2, 42, 1001)
}

fn golden_illegal_2p() -> ArenaRun {
    let actions = recorded_actions(2, 42, 1001);
    let dir = tmp_dir();
    let script = dir.join("script.json");
    write_script(&actions, &script);
    let script_str = script.to_str().unwrap().to_string();
    let agents = vec![
        agent_cmd("illegal-action", &[]),
        agent_cmd("scripted", &["--script", &script_str]),
    ];
    let config = ArenaConfig {
        game_id: "golden-arena-illegal-2p".to_string(),
        seed: 42,
        handshake_timeout_ms: 500,
        move_timeout_ms: 500,
        shutdown_grace_ms: 200,
        agents,
    };
    ArenaRunner::run(config).expect("golden illegal 2p")
}

/// Compare a freshly-pretty-printed value against the committed golden file.
/// Golden artifacts live at the frozen repository-root path
/// `fixtures/arena/v1/`; `write_rel` is relative to the repo root and
/// `embedded` is the `include_str!` literal read at compile time. With
/// `ARENA_GOLDEN_UPDATE=1` the file is (re)written instead of compared.
fn check_golden(write_rel: &str, embedded: &str, pretty: &str) {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let full = repo_root.join(write_rel);
    if std::env::var("ARENA_GOLDEN_UPDATE").is_ok() {
        std::fs::write(&full, format!("{pretty}\n")).expect("write golden artifact");
        return;
    }
    assert_eq!(
        embedded,
        format!("{pretty}\n").as_str(),
        "golden artifact mismatch for {write_rel}"
    );
}

#[test]
fn golden_normal_2p_report_matches() {
    let run = golden_normal_2p();
    let pretty = serde_json::to_string_pretty(&run.report).expect("pretty report");
    check_golden(
        "fixtures/arena/v1/normal-2p-seed42.report.json",
        include_str!("../../../fixtures/arena/v1/normal-2p-seed42.report.json"),
        &pretty,
    );
}

#[test]
fn golden_normal_2p_replay_matches() {
    let run = golden_normal_2p();
    let pretty = serde_json::to_string_pretty(run.replay.as_ref().unwrap()).expect("pretty replay");
    check_golden(
        "fixtures/arena/v1/normal-2p-seed42.replay.json",
        include_str!("../../../fixtures/arena/v1/normal-2p-seed42.replay.json"),
        &pretty,
    );
}

#[test]
fn golden_illegal_action_2p_report_matches() {
    let run = golden_illegal_2p();
    let pretty = serde_json::to_string_pretty(&run.report).expect("pretty report");
    check_golden(
        "fixtures/arena/v1/illegal-action-2p.report.json",
        include_str!("../../../fixtures/arena/v1/illegal-action-2p.report.json"),
        &pretty,
    );
}

// ---------------------------------------------------------------------------
// Determinism (same input => identical bytes)
// ---------------------------------------------------------------------------

#[test]
fn same_config_produces_identical_report() {
    let a = golden_normal_2p();
    let b = golden_normal_2p();
    assert_eq!(
        serde_json::to_string(&a.report).unwrap(),
        serde_json::to_string(&b.report).unwrap(),
        "report must be byte-identical across runs"
    );
}

#[test]
fn same_script_produces_identical_replay() {
    let a = golden_normal_2p();
    let b = golden_normal_2p();
    assert_eq!(
        serde_json::to_string(a.replay.as_ref().unwrap()).unwrap(),
        serde_json::to_string(b.replay.as_ref().unwrap()).unwrap(),
        "replay must be byte-identical across runs"
    );
}
