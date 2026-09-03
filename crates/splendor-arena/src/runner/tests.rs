//! In-memory runner tests (no subprocesses).
//!
//! A [`ScriptedAgent`] implements [`AgentTransport`] entirely in memory: every
//! server message is appended to a shared, globally-ordered log, and scripted
//! client responses are pushed synchronously into the runner's inbound
//! channel. This drives the full state machine — handshake, per-turn FSM,
//! projection, and termination — deterministically and without timing races.

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};

use splendor_core::{observation_hash, Tier};
use splendor_protocol::{ClientMeta, ClientRequestMeta};
use splendor_replay::record_random_game;

use super::*;

/// Globally-ordered log of every server message, tagged with recipient seat.
type SharedLog = Arc<Mutex<Vec<(PlayerId, ServerMessage)>>>;

/// What a scripted seat does in response to server messages. Every script
/// except `Mute` answers the server `hello` with a valid client `hello`.
enum Script {
    /// Handshake, then play actions popped from the shared queue; silent once
    /// the queue is empty.
    Play,
    /// Never respond to anything (handshake-timeout seat).
    Mute,
    /// Handshake, then answer every request with a legal action but a
    /// `request_id` the arena never issued.
    WrongRequestId,
    /// Handshake, then answer every request with a never-legal action.
    IllegalAction,
    /// Handshake, then send an unsolicited `pong` upon `game_start`
    /// (inactive-seat chatter while another seat holds the request).
    PongOnGameStart,
    /// Handshake, play queue actions; once empty, answer with a wrong
    /// `request_id` (used to pin `completed_plies` at abort).
    PlayThenWrongId,
}

/// Which outbound server message kind this seat's `send()` fails on.
///
/// A failed send is *not* logged and triggers no scripted reaction: the wire
/// broke, so the agent never saw the message.
#[derive(Clone, Copy, PartialEq, Eq)]
enum FailOn {
    Hello,
    GameStart,
    Observation,
    RequestAction,
    ActionApplied,
    GameEnd,
}

impl FailOn {
    fn matches(self, msg: &ServerMessage) -> bool {
        matches!(
            (self, msg),
            (FailOn::Hello, ServerMessage::Hello { .. })
                | (FailOn::GameStart, ServerMessage::GameStart { .. })
                | (FailOn::Observation, ServerMessage::Observation { .. })
                | (FailOn::RequestAction, ServerMessage::RequestAction { .. })
                | (FailOn::ActionApplied, ServerMessage::ActionApplied { .. })
                | (FailOn::GameEnd, ServerMessage::GameEnd { .. })
        )
    }
}

struct ScriptedAgent {
    seat: PlayerId,
    tx: Sender<InboundEvent>,
    script: Script,
    game_id: String,
    queue: Arc<Mutex<VecDeque<Action>>>,
    log: SharedLog,
    shutdown_flag: Arc<AtomicBool>,
    fail_on: Option<FailOn>,
}

impl ScriptedAgent {
    fn push_line(&self, msg: &ClientMessage) {
        let line = serde_json::to_string(msg).expect("client message serializes");
        let _ = self.tx.send(InboundEvent::Line {
            seat: self.seat,
            line,
        });
    }

    fn push_action(&self, request_id: u64, action: Action) {
        self.push_line(&ClientMessage::Action {
            meta: ClientRequestMeta::new(self.game_id.clone(), request_id),
            action,
        });
    }
}

impl AgentTransport for ScriptedAgent {
    fn seat(&self) -> PlayerId {
        self.seat
    }

    fn send(&mut self, msg: &ServerMessage) -> Result<(), ArenaInternalError> {
        if let Some(fail) = self.fail_on {
            if fail.matches(msg) {
                return Err(ArenaInternalError::Transport(
                    "injected outbound failure".into(),
                ));
            }
        }
        self.log.lock().unwrap().push((self.seat, msg.clone()));
        match (&self.script, msg) {
            (Script::Mute, _) => {}
            (_, ServerMessage::Hello { .. }) => {
                self.push_line(&ClientMessage::Hello {
                    meta: ClientMeta::new(self.game_id.clone()),
                    agent_name: format!("scripted-{}", self.seat.0),
                    agent_version: "1.0".to_string(),
                });
            }
            (Script::PongOnGameStart, ServerMessage::GameStart { .. }) => {
                self.push_line(&ClientMessage::Pong {
                    meta: ClientMeta::new(self.game_id.clone()),
                });
            }
            (Script::Play, ServerMessage::RequestAction { meta, .. }) => {
                if let Some(action) = self.queue.lock().unwrap().pop_front() {
                    self.push_action(meta.request_id, action);
                }
            }
            (
                Script::WrongRequestId,
                ServerMessage::RequestAction {
                    meta,
                    legal_actions,
                    ..
                },
            ) => {
                // Legal action, but a request id the arena never issued.
                self.push_action(meta.request_id + 1, legal_actions[0]);
            }
            (Script::IllegalAction, ServerMessage::RequestAction { meta, .. }) => {
                // Market slot 9 does not exist, so this can never be legal.
                self.push_action(
                    meta.request_id,
                    Action::BuyMarket {
                        tier: Tier::One,
                        slot: 9,
                    },
                );
            }
            (Script::PlayThenWrongId, ServerMessage::RequestAction { meta, .. }) => {
                let popped = self.queue.lock().unwrap().pop_front();
                match popped {
                    Some(action) => self.push_action(meta.request_id, action),
                    None => self.push_action(meta.request_id + 1, Action::Pass),
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn shutdown(&mut self) {
        self.shutdown_flag.store(true, Ordering::SeqCst);
    }
}

const GAME_ID: &str = "test-match";
const SEED: u64 = 42;
const ACTION_SEED: u64 = 7;

fn test_config(player_count: usize, handshake_ms: u64, move_ms: u64) -> ArenaConfig {
    ArenaConfig {
        game_id: GAME_ID.to_string(),
        seed: SEED,
        handshake_timeout_ms: handshake_ms,
        move_timeout_ms: move_ms,
        shutdown_grace_ms: 100,
        agents: (0..player_count)
            .map(|_| AgentCommand {
                program: PathBuf::from("in-memory"),
                args: Vec::new(),
            })
            .collect(),
    }
}

/// Run the transport-injected match driver with one script per seat.
fn run_scripted(
    config: ArenaConfig,
    scripts: Vec<Script>,
    queue: VecDeque<Action>,
) -> (
    Result<ArenaRun, ArenaInternalError>,
    SharedLog,
    Vec<Arc<AtomicBool>>,
) {
    let fails = vec![None; scripts.len()];
    run_scripted_failing(config, scripts, queue, fails)
}

/// Capped variant of [`run_scripted`] driving `ArenaRunner::run_capped_with`.
fn run_scripted_capped(
    config: ArenaConfig,
    scripts: Vec<Script>,
    queue: VecDeque<Action>,
    ply_cap: u32,
) -> (Result<CappedRun, ArenaInternalError>, SharedLog) {
    let log: SharedLog = Arc::new(Mutex::new(Vec::new()));
    let queue = Arc::new(Mutex::new(queue));
    let game_id = config.game_id.clone();
    let mut remaining: Vec<Option<Script>> = scripts.into_iter().map(Some).collect();
    let log_for_make = Arc::clone(&log);
    let result = ArenaRunner::run_capped_with_for_tests(config, ply_cap, move |_, seat, tx| {
        let idx = seat.index();
        let agent = ScriptedAgent {
            seat,
            tx,
            script: remaining[idx].take().expect("one transport per seat"),
            game_id: game_id.clone(),
            queue: Arc::clone(&queue),
            log: Arc::clone(&log_for_make),
            shutdown_flag: Arc::new(AtomicBool::new(false)),
            fail_on: None,
        };
        Ok(Box::new(agent) as Box<dyn AgentTransport>)
    });
    (result, log)
}

/// Like [`run_scripted`], with one optional injected send failure per seat.
fn run_scripted_failing(
    config: ArenaConfig,
    scripts: Vec<Script>,
    queue: VecDeque<Action>,
    fails: Vec<Option<FailOn>>,
) -> (
    Result<ArenaRun, ArenaInternalError>,
    SharedLog,
    Vec<Arc<AtomicBool>>,
) {
    assert_eq!(scripts.len(), fails.len());
    let log: SharedLog = Arc::new(Mutex::new(Vec::new()));
    let flags: Vec<Arc<AtomicBool>> = scripts
        .iter()
        .map(|_| Arc::new(AtomicBool::new(false)))
        .collect();
    let queue = Arc::new(Mutex::new(queue));
    let game_id = config.game_id.clone();

    let mut remaining: Vec<Option<Script>> = scripts.into_iter().map(Some).collect();
    let flags_for_make = flags.clone();
    let log_for_make = Arc::clone(&log);

    let result = ArenaRunner::run_with(config, move |_, seat, tx| {
        let idx = seat.index();
        let agent = ScriptedAgent {
            seat,
            tx,
            script: remaining[idx].take().expect("one transport per seat"),
            game_id: game_id.clone(),
            queue: Arc::clone(&queue),
            log: Arc::clone(&log_for_make),
            shutdown_flag: Arc::clone(&flags_for_make[idx]),
            fail_on: fails[idx],
        };
        Ok(Box::new(agent) as Box<dyn AgentTransport>)
    });

    (result, log, flags)
}

/// A recorded, guaranteed-terminating action sequence matching (SEED, 2p).
fn recorded_actions() -> (VecDeque<Action>, ReplayV1) {
    let (_, replay) = record_random_game(2, SEED, ACTION_SEED).expect("random game records");
    let actions = replay.steps.iter().map(|s| s.action).collect();
    (actions, replay)
}

fn seq_of(msg: &ServerMessage) -> u64 {
    match msg {
        ServerMessage::Hello { meta, .. } => meta.server_seq,
        ServerMessage::GameStart { meta, .. }
        | ServerMessage::ActionApplied { meta, .. }
        | ServerMessage::Event { meta, .. }
        | ServerMessage::GameEnd { meta, .. }
        | ServerMessage::GameTruncated { meta, .. }
        | ServerMessage::Error { meta, .. }
        | ServerMessage::Ping { meta } => meta.server.server_seq,
        ServerMessage::Observation { meta, .. } => meta.recipient.server.server_seq,
        ServerMessage::RequestAction { meta, .. } => meta.recipient.server.server_seq,
    }
}

fn recipient_of(msg: &ServerMessage) -> Option<u8> {
    match msg {
        ServerMessage::Hello { .. } => None,
        ServerMessage::GameStart { meta, .. }
        | ServerMessage::ActionApplied { meta, .. }
        | ServerMessage::Event { meta, .. }
        | ServerMessage::GameEnd { meta, .. }
        | ServerMessage::GameTruncated { meta, .. }
        | ServerMessage::Error { meta, .. }
        | ServerMessage::Ping { meta } => Some(meta.recipient_player_id),
        ServerMessage::Observation { meta, .. } => Some(meta.recipient.recipient_player_id),
        ServerMessage::RequestAction { meta, .. } => Some(meta.recipient.recipient_player_id),
    }
}

// ---------------------------------------------------------------------------

#[test]
fn seat_binding_is_runner_owned() {
    let (actions, _) = recorded_actions();
    let (result, log, _) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
    );
    let run = result.expect("no internal error");

    // Seats in the report follow spawn order, never a client claim (the
    // client hello schema cannot even carry a seat).
    assert_eq!(run.report.agents.len(), 2);
    for (i, agent) in run.report.agents.iter().enumerate() {
        assert_eq!(agent.seat, PlayerId(i as u8));
        assert_eq!(
            agent.agent_name.as_deref(),
            Some(format!("scripted-{i}").as_str())
        );
        assert_eq!(agent.agent_version.as_deref(), Some("1.0"));
    }

    // Every per-player message handed to transport i is addressed to seat i.
    for (seat, msg) in log.lock().unwrap().iter() {
        if let Some(recipient) = recipient_of(msg) {
            assert_eq!(
                recipient, seat.0,
                "message for seat {seat:?} carried recipient {recipient}"
            );
        }
    }
}

#[test]
fn server_seq_is_globally_monotonic() {
    let (actions, _) = recorded_actions();
    let (result, log, _) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
    );
    result.expect("no internal error");

    let log = log.lock().unwrap();
    assert!(!log.is_empty());
    let mut prev: Option<u64> = None;
    for (_, msg) in log.iter() {
        let seq = seq_of(msg);
        if let Some(p) = prev {
            assert!(
                seq > p,
                "server_seq must be globally strictly increasing: {p} then {seq}"
            );
        }
        prev = Some(seq);
    }
}

#[test]
fn setup_history_reaches_every_seat_before_the_first_request() {
    let (actions, _) = recorded_actions();
    let (result, log, _) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
    );
    result.expect("no internal error");

    let log = log.lock().unwrap();
    for seat in [PlayerId(0), PlayerId(1)] {
        let messages = log
            .iter()
            .filter(|(recipient, _)| *recipient == seat)
            .map(|(_, message)| message)
            .collect::<Vec<_>>();
        let start = messages
            .iter()
            .position(|message| matches!(message, ServerMessage::GameStart { .. }))
            .expect("game_start");
        let request = messages
            .iter()
            .position(|message| matches!(message, ServerMessage::RequestAction { .. }))
            .expect("first request");
        let setup_events = &messages[start + 1..request];
        assert!(matches!(
            setup_events.first(),
            Some(ServerMessage::Event {
                event: VisibleEvent::GameStarted { .. },
                ..
            })
        ));
        assert!(setup_events.iter().any(|message| matches!(
            message,
            ServerMessage::Event {
                event: VisibleEvent::SetupDealt { .. },
                ..
            }
        )));
    }
}

#[test]
fn request_id_starts_at_one() {
    let (actions, _) = recorded_actions();
    let (result, log, _) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
    );
    result.expect("no internal error");

    let log = log.lock().unwrap();
    let ids: Vec<u64> = log
        .iter()
        .filter_map(|(_, msg)| match msg {
            ServerMessage::RequestAction { meta, .. } => Some(meta.request_id),
            _ => None,
        })
        .collect();
    assert!(!ids.is_empty());
    assert_eq!(ids[0], 1, "first request must carry request_id 1");
    for (i, id) in ids.iter().enumerate() {
        assert_eq!(*id, i as u64 + 1, "request ids advance by one per ply");
    }
}

#[test]
fn request_observation_hash_matches_observation() {
    let (actions, _) = recorded_actions();
    let (result, log, _) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
    );
    result.expect("no internal error");

    let log = log.lock().unwrap();
    let mut last_obs_hash: Option<splendor_core::ObservationHash> = None;
    let mut checked = 0usize;
    for (_, msg) in log.iter() {
        match msg {
            ServerMessage::Observation { meta, observation } => {
                // The advertised hash is the hash of the exact payload sent.
                assert_eq!(meta.observation_hash, observation_hash(observation));
                last_obs_hash = Some(meta.observation_hash.clone());
            }
            ServerMessage::RequestAction { meta, .. } => {
                // The request echoes the hash of the observation it follows.
                assert_eq!(
                    Some(&meta.observation_hash),
                    last_obs_hash.as_ref(),
                    "request must carry the preceding observation's hash"
                );
                checked += 1;
            }
            _ => {}
        }
    }
    assert!(checked > 0, "at least one request/observation pair checked");
}

#[test]
fn wrong_request_id_aborts_without_replay() {
    let (result, _, flags) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::WrongRequestId, Script::WrongRequestId],
        VecDeque::new(),
    );
    let run = result.expect("agent fault is not an internal error");

    assert!(run.replay.is_none(), "aborted match must carry no replay");
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            reason: AgentFault::WrongRequestId,
            phase: ArenaPhase::ActionRequest,
            request_id: Some(1),
            completed_plies: 0,
            ..
        } => {}
        ref other => panic!("expected wrong_request_id abort, got {other:?}"),
    }
    for flag in &flags {
        assert!(
            flag.load(Ordering::SeqCst),
            "every child must be cleaned up"
        );
    }
}

#[test]
fn inactive_seat_message_aborts() {
    let (actions, _) = recorded_actions();
    let (result, _, flags) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::PongOnGameStart],
        actions,
    );
    let run = result.expect("agent fault is not an internal error");

    assert!(run.replay.is_none());
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            seat: 1,
            reason: AgentFault::UnexpectedMessage,
            phase: ArenaPhase::ActionRequest,
            ..
        } => {}
        ref other => panic!("expected inactive-seat abort on seat 1, got {other:?}"),
    }
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn illegal_action_aborts_without_replay() {
    let (result, _, flags) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::IllegalAction, Script::IllegalAction],
        VecDeque::new(),
    );
    let run = result.expect("agent fault is not an internal error");

    assert!(run.replay.is_none(), "illegal action must yield no replay");
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            reason: AgentFault::IllegalAction,
            phase: ArenaPhase::ActionRequest,
            request_id: Some(1),
            completed_plies: 0,
            ..
        } => {}
        ref other => panic!("expected illegal_action abort, got {other:?}"),
    }
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn completed_match_returns_verifying_replay() {
    let (actions, reference) = recorded_actions();
    let expected_plies = actions.len() as u32;
    let (result, log, flags) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
    );
    let run = result.expect("no internal error");

    // Completed outcome with the replay's own final hash.
    let replay = run
        .replay
        .as_ref()
        .expect("completed match carries a replay");
    verify_replay(replay).expect("emitted replay must re-verify");
    assert_eq!(replay.steps.len() as u32, expected_plies);
    assert_eq!(replay.final_state_hash, reference.final_state_hash);
    match &run.report.outcome {
        ArenaOutcomeV1::Completed {
            completed_plies,
            replay_final_hash,
            ..
        } => {
            assert_eq!(*completed_plies, expected_plies);
            assert_eq!(replay_final_hash, replay.final_state_hash.as_str());
        }
        other => panic!("expected completed outcome, got {other:?}"),
    }

    // Information boundary: nothing sent to any agent may carry the raw seed,
    // a full-state hash, or the replay itself.
    let final_hash = replay.final_state_hash.as_str();
    let initial_hash = replay.initial_state_hash.as_str();
    for (_, msg) in log.lock().unwrap().iter() {
        let json = msg.to_json_line().unwrap();
        assert!(!json.contains("\"seed\":"), "raw seed leaked: {json}");
        assert!(
            !json.contains("full_state_hash"),
            "full-state hash field leaked: {json}"
        );
        assert!(
            !json.contains(final_hash),
            "final state hash leaked: {json}"
        );
        assert!(
            !json.contains(initial_hash),
            "initial state hash leaked: {json}"
        );
    }

    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst), "cleanup also runs on success");
    }
}

#[test]
fn aborted_report_preserves_completed_plies() {
    let (mut actions, _) = recorded_actions();
    actions.truncate(3); // play exactly 3 plies, then fault on the 4th request
    let (result, _, flags) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::PlayThenWrongId, Script::PlayThenWrongId],
        actions,
    );
    let run = result.expect("agent fault is not an internal error");

    assert!(run.replay.is_none());
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            reason: AgentFault::WrongRequestId,
            phase: ArenaPhase::ActionRequest,
            request_id: Some(4),
            completed_plies: 3,
            ..
        } => {}
        ref other => panic!("expected abort after 3 plies, got {other:?}"),
    }
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn handshake_timeout_selects_lowest_pending_seat() {
    // Seat 0 handshakes; seats 1 and 2 stay mute. The timeout must blame the
    // lowest-index seat that never completed the handshake: seat 1.
    let (result, _, flags) = run_scripted(
        test_config(3, 50, 5_000),
        vec![Script::Play, Script::Mute, Script::Mute],
        VecDeque::new(),
    );
    let run = result.expect("handshake timeout is not an internal error");

    assert!(run.replay.is_none());
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            seat: 1,
            reason: AgentFault::HandshakeTimeout,
            phase: ArenaPhase::Handshake,
            request_id: None,
            completed_plies: 0,
        } => {}
        ref other => panic!("expected handshake timeout on seat 1, got {other:?}"),
    }
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }

    // Identity of the seat that did handshake is preserved even on abort.
    assert_eq!(
        run.report.agents[0].agent_name.as_deref(),
        Some("scripted-0")
    );
    assert_eq!(run.report.agents[1].agent_name, None);
    assert_eq!(run.report.agents[2].agent_name, None);
}

// ---------------------------------------------------------------------------
// Outbound send-failure classification (fix-forward for Commit 3 review).
// ---------------------------------------------------------------------------

#[test]
fn hello_send_failure_aborts_as_agent_io() {
    let (actions, _) = recorded_actions();
    // A generous handshake timeout: if the failure were misclassified as
    // HandshakeTimeout the match would sit here for 30 s.
    let start = Instant::now();
    let (result, _, flags) = run_scripted_failing(
        test_config(2, 30_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![None, Some(FailOn::Hello)],
    );
    let run = result.expect("outbound failure is an agent fault, not internal");

    assert!(run.replay.is_none());
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            seat: 1,
            reason: AgentFault::AgentIo,
            phase: ArenaPhase::Handshake,
            request_id: None,
            completed_plies: 0,
        } => {}
        ref other => panic!("expected agent_io handshake abort on seat 1, got {other:?}"),
    }
    assert!(
        start.elapsed() < Duration::from_secs(10),
        "hello send failure must not wait for the handshake deadline"
    );
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn game_start_send_failure_aborts_as_agent_io() {
    let (actions, _) = recorded_actions();
    let (result, _, flags) = run_scripted_failing(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![None, Some(FailOn::GameStart)],
    );
    let run = result.expect("outbound failure is an agent fault, not internal");

    assert!(run.replay.is_none());
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            seat: 1,
            reason: AgentFault::AgentIo,
            phase: ArenaPhase::Handshake,
            request_id: None,
            completed_plies: 0,
        } => {}
        ref other => panic!("expected agent_io game_start abort on seat 1, got {other:?}"),
    }
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn observation_send_failure_starts_no_request() {
    let (actions, _) = recorded_actions();
    // Both seats fail on Observation, so whichever seat is current at ply 1
    // trips the failure before any request is issued.
    let (result, log, flags) = run_scripted_failing(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![Some(FailOn::Observation), Some(FailOn::Observation)],
    );
    let run = result.expect("outbound failure is an agent fault, not internal");

    assert!(run.replay.is_none());
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            reason: AgentFault::AgentIo,
            phase: ArenaPhase::ActionRequest,
            request_id: None,
            completed_plies: 0,
            ..
        } => {}
        ref other => panic!("expected agent_io abort before any request, got {other:?}"),
    }
    // No RequestAction may ever have been issued (or delivered).
    assert!(
        !log.lock()
            .unwrap()
            .iter()
            .any(|(_, m)| matches!(m, ServerMessage::RequestAction { .. })),
        "no action request may follow a failed observation send"
    );
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn request_send_failure_starts_no_deadline() {
    let (actions, _) = recorded_actions();
    // A deliberately huge move timeout: if the deadline were started (and the
    // failure misreported as ActionTimeout) this test would stall for 60 s.
    let start = Instant::now();
    let (result, _, flags) = run_scripted_failing(
        test_config(2, 5_000, 60_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![Some(FailOn::RequestAction), Some(FailOn::RequestAction)],
    );
    let run = result.expect("outbound failure is an agent fault, not internal");

    assert!(run.replay.is_none());
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            reason: AgentFault::AgentIo,
            phase: ArenaPhase::ActionRequest,
            request_id: Some(1),
            completed_plies: 0,
            ..
        } => {}
        ref other => panic!("expected agent_io abort on request 1, got {other:?}"),
    }
    assert!(
        start.elapsed() < Duration::from_secs(10),
        "request send failure must abort immediately, not after the move deadline"
    );
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn nonterminal_event_send_failure_preserves_applied_ply() {
    let (actions, _) = recorded_actions();
    // The first applied action's ActionApplied broadcast fails (strict mode
    // hits seat 0 first). The engine and recorder already contain that ply,
    // so the abort must report completed_plies == 1.
    let (result, _, flags) = run_scripted_failing(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![Some(FailOn::ActionApplied), Some(FailOn::ActionApplied)],
    );
    let run = result.expect("outbound failure is an agent fault, not internal");

    assert!(run.replay.is_none(), "aborted match carries no replay");
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            seat: 0,
            reason: AgentFault::AgentIo,
            phase: ArenaPhase::ActionReceived,
            request_id: Some(1),
            completed_plies: 1,
        } => {}
        ref other => panic!("expected agent_io abort with the applied ply counted, got {other:?}"),
    }
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn terminal_game_end_send_failure_still_completes() {
    let (actions, reference) = recorded_actions();
    let expected_plies = actions.len() as u32;
    let (result, _, flags) = run_scripted_failing(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![Some(FailOn::GameEnd), None],
    );
    let run = result.expect("terminal send failure must not become an error");

    // The terminal replay is already formed; a broken game-end pipe must not
    // erase it.
    let replay = run.replay.as_ref().expect("completed match keeps replay");
    verify_replay(replay).expect("replay must still re-verify");
    assert_eq!(replay.final_state_hash, reference.final_state_hash);
    match &run.report.outcome {
        ArenaOutcomeV1::Completed {
            completed_plies, ..
        } => assert_eq!(*completed_plies, expected_plies),
        other => panic!("expected completed outcome, got {other:?}"),
    }
    for flag in &flags {
        assert!(flag.load(Ordering::SeqCst));
    }
}

#[test]
fn terminal_send_failure_does_not_block_other_recipients() {
    let (actions, _) = recorded_actions();
    let (result, log, _) = run_scripted_failing(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![Some(FailOn::GameEnd), None],
    );
    let run = result.expect("terminal send failure must not become an error");
    assert!(run.replay.is_some());

    // Seat 0's game-end pipe broke, but seat 1 must still have received its
    // own GameEnd (best-effort continues over remaining recipients).
    let log = log.lock().unwrap();
    let seat1_game_end = log
        .iter()
        .any(|(seat, m)| *seat == PlayerId(1) && matches!(m, ServerMessage::GameEnd { .. }));
    assert!(seat1_game_end, "seat 1 must still receive its GameEnd");
    let seat0_game_end = log
        .iter()
        .any(|(seat, m)| *seat == PlayerId(0) && matches!(m, ServerMessage::GameEnd { .. }));
    assert!(
        !seat0_game_end,
        "seat 0's GameEnd send failed and was not delivered"
    );
}

#[test]
fn outbound_failure_shuts_down_every_transport() {
    let (actions, _) = recorded_actions();
    let (result, _, flags) = run_scripted_failing(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        vec![None, Some(FailOn::ActionApplied)],
    );
    let run = result.expect("outbound failure is an agent fault, not internal");

    // Seat 1's transport failed, and the fault is attributed to seat 1
    // (the failing transport's bound recipient), not to the actor.
    match run.report.outcome {
        ArenaOutcomeV1::Aborted {
            seat: 1,
            reason: AgentFault::AgentIo,
            phase: ArenaPhase::ActionReceived,
            ..
        } => {}
        ref other => panic!("expected agent_io abort on seat 1, got {other:?}"),
    }
    for (i, flag) in flags.iter().enumerate() {
        assert!(
            flag.load(Ordering::SeqCst),
            "transport {i} must be shut down after an outbound failure"
        );
    }
}

// ---------------------------------------------------------------------------
// Capped rollout (run_capped) tests
// ---------------------------------------------------------------------------

#[test]
fn capped_run_truncates_at_cap_and_emits_game_truncated() {
    // A cap below the recorded game's length guarantees truncation.
    let (actions, _) = recorded_actions();
    let cap = 5u32;
    let (result, log) = run_scripted_capped(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        cap,
    );
    let capped = result.expect("no internal error");
    let (report, prefix) = match capped {
        CappedRun::Truncated { report, prefix } => (report, prefix),
        CappedRun::Terminal(_) => panic!("cap 5 on a ~60-ply game must truncate"),
    };
    match &report.outcome {
        ArenaOutcomeV1::Truncated {
            completed_plies,
            cap_state_hash,
            cap_scores,
        } => {
            assert_eq!(*completed_plies, cap);
            assert_eq!(cap_state_hash, prefix.cap_state_hash.as_str());
            assert_eq!(cap_scores.len(), 2);
        }
        other => panic!("expected truncated outcome, got {other:?}"),
    }
    assert_eq!(prefix.steps.len() as u32, cap);
    assert_eq!(prefix.ply_cap, cap);
    // The prefix must strictly verify (non-terminal at cap, hashes intact).
    splendor_replay::verify_rollout_prefix(&prefix).expect("prefix verifies");

    // Both seats received the no-result game_truncated notification.
    let log = log.lock().unwrap();
    let truncations: Vec<&(PlayerId, ServerMessage)> = log
        .iter()
        .filter(|(_, msg)| matches!(msg, ServerMessage::GameTruncated { .. }))
        .collect();
    assert_eq!(truncations.len(), 2, "both seats must be notified");
    let mut recipients = truncations
        .iter()
        .filter_map(|(_, msg)| recipient_of(msg))
        .collect::<Vec<_>>();
    recipients.sort_unstable();
    assert_eq!(recipients, vec![0, 1]);
}

#[test]
fn capped_run_terminal_before_cap_is_identical_to_run_match() {
    // Cap above the game length: the capped run must produce exactly the
    // same completed report and replay as the uncapped runner.
    let (actions, replay) = recorded_actions();
    let plies = replay.steps.len() as u32;
    let (uncapped, _, _) = run_scripted(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions.clone(),
    );
    let (capped, _) = run_scripted_capped(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions,
        plies + 10,
    );
    let uncapped = uncapped.expect("no internal error");
    let capped_run = match capped.expect("no internal error") {
        CappedRun::Terminal(run) => run,
        CappedRun::Truncated { .. } => panic!("cap above game length must not truncate"),
    };
    assert_eq!(uncapped.report, capped_run.report);
    assert_eq!(uncapped.replay, capped_run.replay);
}

#[test]
fn capped_run_rejects_invalid_cap_and_aborts_still_fail_closed() {
    let (actions, _) = recorded_actions();
    // Zero cap is rejected before any transport is built.
    let (result, _) = run_scripted_capped(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions.clone(),
        0,
    );
    assert!(
        matches!(result, Err(ArenaInternalError::Engine(_))),
        "zero cap must be rejected"
    );
    // A cap at or above the 10,000-ply safety limit is rejected too.
    let (result, _) = run_scripted_capped(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Play],
        actions.clone(),
        10_000,
    );
    assert!(
        matches!(result, Err(ArenaInternalError::Engine(_))),
        "safety-limit cap must be rejected"
    );
    // An agent failure still aborts fail-closed under a cap: a seat that
    // never answers the handshake times out with the usual abort outcome.
    let (result, _) = run_scripted_capped(
        test_config(2, 5_000, 5_000),
        vec![Script::Play, Script::Mute],
        actions,
        150,
    );
    match result.expect("no internal error") {
        CappedRun::Terminal(run) => match &run.report.outcome {
            ArenaOutcomeV1::Aborted { .. } => {}
            other => panic!("expected handshake-timeout abort, got {other:?}"),
        },
        CappedRun::Truncated { .. } => panic!("a faulty agent must abort, not truncate"),
    }
}

// ---------------------------------------------------------------------------
// M41A branch runner tests
// ---------------------------------------------------------------------------

mod branch {
    use super::*;

    /// Build a BranchStart from a source replay at `branch_ply`, replaying
    /// the prefix under the recorder to collect per-ply referee events (the
    /// same rebuild `run-branch` will perform in the CLI).
    fn branch_start_from(replay: &ReplayV1, branch_ply: usize) -> BranchStart {
        let (state, prefix_events) = {
            // Rebuild per-ply events by replaying the prefix on a fresh
            // recorder (matches what the CLI's branch driver does). The
            // prefix steps' hash chain is verified separately by
            // verify_replay on the source document.
            let (mut rec, _setup) = ReplayRecorder::new_with_setup(GameConfig {
                player_count: replay.player_count,
                seed: replay.seed,
                ruleset: Ruleset::base_v1(),
            })
            .expect("rebuild recorder");
            let mut events = Vec::with_capacity(branch_ply);
            for step in &replay.steps[..branch_ply] {
                let res = rec.apply(step.action).expect("prefix action applies");
                events.push(res.events);
            }
            (rec.state().clone(), events)
        };
        BranchStart {
            state,
            prefix_steps: replay.steps[..branch_ply].to_vec(),
            initial_state_hash: replay.initial_state_hash.clone(),
            ruleset: replay.ruleset.clone(),
            ruleset_fingerprint: replay.ruleset_fingerprint.clone(),
            seed: replay.seed,
            prefix_events,
        }
    }

    fn branch_config(source_seed: u64) -> ArenaConfig {
        let mut config = test_config(2, 5_000, 5_000);
        config.seed = source_seed;
        config
    }

    /// H0b semantics: branching with the SOURCE's own action at the branch
    /// ply, with agents scripted to play the source's remaining actions,
    /// must reproduce the source game exactly (step chain, result, final
    /// hash) — the run-branch correctness oracle.
    #[test]
    fn branch_with_source_action_reproduces_source_game() {
        let (_, replay) = record_random_game(2, SEED, ACTION_SEED).expect("source game");
        let branch_ply = replay.steps.len() / 2;
        let source_action = replay.steps[branch_ply].action;
        let start = branch_start_from(&replay, branch_ply);

        // Both agents play the source's remaining actions in order.
        let remaining: VecDeque<Action> = replay.steps[branch_ply + 1..]
            .iter()
            .map(|s| s.action)
            .collect();

        let log: SharedLog = Arc::new(Mutex::new(Vec::new()));
        let queue = Arc::new(Mutex::new(remaining));
        let game_id = "m41a-branch-h0b-test".to_string();
        let config = {
            let mut c = branch_config(replay.seed);
            c.game_id = game_id.clone();
            c
        };
        let log_for_make = Arc::clone(&log);
        let result =
            ArenaRunner::run_branch_with(config, start, source_action, 150, move |_, seat, tx| {
                let agent = ScriptedAgent {
                    seat,
                    tx,
                    script: Script::Play,
                    game_id: game_id.clone(),
                    queue: Arc::clone(&queue),
                    log: Arc::clone(&log_for_make),
                    shutdown_flag: Arc::new(AtomicBool::new(false)),
                    fail_on: None,
                };
                Ok(Box::new(agent) as Box<dyn AgentTransport>)
            });

        match result.expect("no internal error") {
            CappedRun::Terminal(run) => {
                let branch_replay = run.replay.as_ref().expect("terminal branch has replay");
                // The complete step chain equals the source replay's.
                assert_eq!(
                    branch_replay.steps.len(),
                    replay.steps.len(),
                    "branch replay must cover the full game"
                );
                for (got, want) in branch_replay.steps.iter().zip(replay.steps.iter()) {
                    assert_eq!(got.ply, want.ply);
                    assert_eq!(got.actor, want.actor);
                    assert_eq!(got.action, want.action);
                    assert_eq!(
                        got.state_hash_before.as_str(),
                        want.state_hash_before.as_str()
                    );
                    assert_eq!(
                        got.state_hash_after.as_str(),
                        want.state_hash_after.as_str()
                    );
                }
                assert_eq!(
                    branch_replay.final_state_hash.as_str(),
                    replay.final_state_hash.as_str(),
                    "H0b: final state hash must match the source game"
                );
                assert_eq!(branch_replay.result, replay.result);
            }
            CappedRun::Truncated { .. } => {
                panic!("source game completes well under the cap; branch must terminate")
            }
        }
    }

    /// A forced action that is NOT in the rebuilt legal set is rejected
    /// fail-closed before any agent is spawned.
    #[test]
    fn branch_rejects_illegal_forced_action() {
        let (_, replay) = record_random_game(2, SEED, ACTION_SEED).expect("source game");
        let branch_ply = replay.steps.len() / 2;
        let start = branch_start_from(&replay, branch_ply);
        // An action that is never legal: a market buy of an out-of-range
        // slot (the market has 4 slots per tier; slot 200 cannot exist).
        let illegal = Action::BuyMarket {
            tier: Tier::One,
            slot: 200,
        };
        let result = ArenaRunner::run_branch_with(
            branch_config(replay.seed),
            start,
            illegal,
            150,
            |_, _, _| -> Result<Box<dyn AgentTransport>, ArenaInternalError> {
                panic!("no transport may be built before forced-action validation")
            },
        );
        assert!(
            matches!(result, Err(ArenaInternalError::Engine(ref m)) if m.contains("legal set")),
            "illegal forced action must fail closed, got {result:?}"
        );
    }

    /// Determinism: the same branch run twice produces identical replays.
    /// The continuation is a deterministic "first legal action" policy
    /// (scripted ahead of time from the branch rebuild), so both runs see
    /// the same action stream.
    #[test]
    fn branch_is_deterministic_across_runs() {
        let (_, replay) = record_random_game(2, SEED + 1, ACTION_SEED + 1).expect("source game");
        let branch_ply = replay.steps.len() / 3;
        // Branch with a DIFFERENT action than the source took: pick another
        // legal action at the branch point (the first legal action that
        // differs from the source's).
        let source_action = replay.steps[branch_ply].action;
        // Rebuild the branch-point legal set from the same prefix replay.
        let forced = {
            let (mut rec, _) = ReplayRecorder::new_with_setup(GameConfig {
                player_count: replay.player_count,
                seed: replay.seed,
                ruleset: Ruleset::base_v1(),
            })
            .expect("rebuild");
            for step in &replay.steps[..branch_ply] {
                rec.apply(step.action).expect("prefix");
            }
            let legal = rec.legal_actions();
            *legal
                .iter()
                .find(|a| **a != source_action)
                .expect("a mid-game state has multiple legal actions")
        };
        // Deterministic continuation: first-legal-action policy, computed
        // offline from the forced state (capped at 150 total plies).
        let continuation: VecDeque<Action> = {
            let (mut rec, _) = ReplayRecorder::new_with_setup(GameConfig {
                player_count: replay.player_count,
                seed: replay.seed,
                ruleset: Ruleset::base_v1(),
            })
            .expect("rebuild");
            for step in &replay.steps[..branch_ply] {
                rec.apply(step.action).expect("prefix");
            }
            rec.apply(forced).expect("forced");
            let mut actions = VecDeque::new();
            while !rec.is_terminal() && (branch_ply + 1 + actions.len()) < 150_usize {
                let next = rec.legal_actions().remove(0);
                rec.apply(next).expect("continuation applies");
                actions.push_back(next);
            }
            actions
        };

        let run_once = |queue: VecDeque<Action>| -> ReplayV1 {
            let log: SharedLog = Arc::new(Mutex::new(Vec::new()));
            let queue = Arc::new(Mutex::new(queue));
            let game_id = "m41a-branch-det-test".to_string();
            let mut config = branch_config(replay.seed);
            config.game_id = game_id.clone();
            let log_for_make = Arc::clone(&log);
            let start = branch_start_from(&replay, branch_ply);
            match ArenaRunner::run_branch_with(config, start, forced, 150, move |_, seat, tx| {
                let agent = ScriptedAgent {
                    seat,
                    tx,
                    script: Script::Play,
                    game_id: game_id.clone(),
                    queue: Arc::clone(&queue),
                    log: Arc::clone(&log_for_make),
                    shutdown_flag: Arc::new(AtomicBool::new(false)),
                    fail_on: None,
                };
                Ok(Box::new(agent) as Box<dyn AgentTransport>)
            })
            .expect("no internal error")
            {
                CappedRun::Terminal(run) => run.replay.expect("replay"),
                CappedRun::Truncated { .. } => panic!("expected terminal"),
            }
        };

        let first = run_once(continuation.clone());
        let second = run_once(continuation);
        assert_eq!(first, second, "same branch twice must be identical");
        // And the branch point's forced action is really in the chain.
        assert_eq!(first.steps[branch_ply].action, forced);
    }

    /// The absolute ply cap counts from the SOURCE game's first ply: a
    /// branch whose prefix already reaches the cap truncates immediately.
    #[test]
    fn branch_cap_is_absolute() {
        let (_, replay) = record_random_game(2, SEED, ACTION_SEED).expect("source game");
        let branch_ply = replay.steps.len() / 2;
        let start = branch_start_from(&replay, branch_ply);
        let source_action = replay.steps[branch_ply].action;
        // Cap exactly at prefix + forced: no continuation ply may run.
        let cap = (branch_ply + 1) as u32;
        let remaining: VecDeque<Action> = replay.steps[branch_ply + 1..]
            .iter()
            .map(|s| s.action)
            .collect();
        let log: SharedLog = Arc::new(Mutex::new(Vec::new()));
        let queue = Arc::new(Mutex::new(remaining));
        let game_id = "m41a-branch-cap-test".to_string();
        let mut config = branch_config(replay.seed);
        config.game_id = game_id.clone();
        let log_for_make = Arc::clone(&log);
        match ArenaRunner::run_branch_with(config, start, source_action, cap, move |_, seat, tx| {
            let agent = ScriptedAgent {
                seat,
                tx,
                script: Script::Play,
                game_id: game_id.clone(),
                queue: Arc::clone(&queue),
                log: Arc::clone(&log_for_make),
                shutdown_flag: Arc::new(AtomicBool::new(false)),
                fail_on: None,
            };
            Ok(Box::new(agent) as Box<dyn AgentTransport>)
        })
        .expect("no internal error")
        {
            CappedRun::Truncated { prefix, .. } => {
                assert_eq!(prefix.steps.len() as u32, cap);
                assert_eq!(
                    prefix.cap_state_hash.as_str(),
                    replay.steps[branch_ply].state_hash_after.as_str(),
                    "cap state must be exactly the forced action's result state"
                );
            }
            CappedRun::Terminal(_) => {
                panic!("cap at prefix+forced must truncate before any agent ply")
            }
        }
    }

    /// Belief-tracking transcript: the agents must receive, in order, the
    /// setup events AND every prefix ply's projected events AND the forced
    /// action's events, BEFORE the first observation.
    #[test]
    fn branch_agents_receive_full_event_history_before_first_observation() {
        let (_, replay) = record_random_game(2, SEED, ACTION_SEED).expect("source game");
        let branch_ply = replay.steps.len() / 2;
        let source_action = replay.steps[branch_ply].action;
        let start = branch_start_from(&replay, branch_ply);
        let remaining: VecDeque<Action> = replay.steps[branch_ply + 1..]
            .iter()
            .map(|s| s.action)
            .collect();
        let log: SharedLog = Arc::new(Mutex::new(Vec::new()));
        let queue = Arc::new(Mutex::new(remaining));
        let game_id = "m41a-branch-history-test".to_string();
        let mut config = branch_config(replay.seed);
        config.game_id = game_id.clone();
        let log_for_make = Arc::clone(&log);
        match ArenaRunner::run_branch_with(config, start, source_action, 150, move |_, seat, tx| {
            let agent = ScriptedAgent {
                seat,
                tx,
                script: Script::Play,
                game_id: game_id.clone(),
                queue: Arc::clone(&queue),
                log: Arc::clone(&log_for_make),
                shutdown_flag: Arc::new(AtomicBool::new(false)),
                fail_on: None,
            };
            Ok(Box::new(agent) as Box<dyn AgentTransport>)
        })
        .expect("no internal error")
        {
            CappedRun::Terminal(run) => {
                assert!(run.replay.is_some());
                // Seat 0's transcript: hello, game_start, then the full
                // history (setup + prefix + forced) BEFORE the first
                // observation.
                let entries = log.lock().unwrap();
                let seat0: Vec<&ServerMessage> = entries
                    .iter()
                    .filter(|(seat, _)| seat.0 == 0)
                    .map(|(_, m)| m)
                    .collect();
                let first_observation = seat0
                    .iter()
                    .position(|m| matches!(m, ServerMessage::Observation { .. }))
                    .expect("at least one observation");
                let action_applied_count = seat0[..first_observation]
                    .iter()
                    .filter(|m| matches!(m, ServerMessage::ActionApplied { .. }))
                    .count();
                // Every history ply (prefix + forced) projects at least an
                // ActionApplied to this seat — the count must be at least
                // branch_ply + 1 (visible to all) and the events must all
                // precede the first observation.
                assert!(
                    action_applied_count > branch_ply,
                    "agents must see the full projected history (prefix + forced) \
                     before the first observation; saw {action_applied_count} applied"
                );
            }
            CappedRun::Truncated { .. } => panic!("expected terminal"),
        }
    }
}
