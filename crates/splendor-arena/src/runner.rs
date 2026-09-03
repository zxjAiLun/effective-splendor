//! Seat-bound match runner with deadlines (M04 Commit 3).
//!
//! `ArenaRunner::run` drives one complete match: it spawns one agent per seat,
//! runs the strict handshake, then the per-turn state machine (observation →
//! request → validated action → engine apply → per-seat event projection),
//! and finishes with a verified [`ReplayV1`]. Every fault path (handshake
//! timeout, malformed/mismatched/illegal action, inactive-seat line, EOF,
//! oversize, I/O error) produces an `Aborted` report with `replay: None` and
//! cleans up every child. A normal terminal produces a `Completed` report with
//! `Some(replay)`.
//!
//! The runner is transport-agnostic: seats speak through an [`AgentTransport`].
//! The production path uses [`SubprocessTransport`] (a real agent process);
//! tests inject an in-memory endpoint (see the `#[cfg(test)]` module).

use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::time::{Duration, Instant};

use splendor_core::{
    observation_hash, ruleset_fingerprint, visible_events, Action, Audience, GameConfig, PlayerId,
    RefereeEvent, Ruleset, VisibleEvent, CATALOG_VERSION, ENGINE_VERSION,
};
use splendor_protocol::{
    parse_client_line, ClientMessage, ObservationMeta, RecipientMeta, RequestMeta, ServerMessage,
    ServerMeta, PROTOCOL_VERSION,
};
use splendor_replay::{verify_replay, ReplayRecorder, ReplayV1, RolloutPrefixV1};

use crate::config::{AgentCommand, ArenaConfig};
use crate::controller::{validate_action, validate_hello, MatchCounters, SeatState};
use crate::error::ArenaInternalError;
use crate::process::{spawn_agent, AgentProcess, InboundEvent};
use crate::report::{AgentFault, AgentIdentity, ArenaOutcomeV1, ArenaPhase, ArenaReportV1};
use crate::seed_commitment::{seed_commitment_v1, SeedCommitment};

/// A safety cap on plies, so a non-terminating (or adversarial) agent cannot
/// hang the arena. Splendor games end well under this; hitting it is an
/// internal error, not an agent fault.
const MAX_MATCH_PLIES: u32 = 10_000;

/// Bidirectional transport to one agent seat.
///
/// The runner sends server messages and reads [`InboundEvent`]s from a single
/// global fan-in channel (each event is tagged with its seat). Two
/// implementations exist: [`SubprocessTransport`] and, under `#[cfg(test)]`, an
/// in-memory endpoint.
pub(crate) trait AgentTransport {
    /// The runner-assigned seat this transport speaks for.
    fn seat(&self) -> PlayerId;
    /// Send one server message (implementation serializes + flushes).
    fn send(&mut self, msg: &ServerMessage) -> Result<(), ArenaInternalError>;
    /// Best-effort shutdown: close stdin, kill/wait, join reader threads.
    fn shutdown(&mut self);
}

/// Production transport: wraps a spawned agent process.
pub(crate) struct SubprocessTransport {
    proc: Option<AgentProcess>,
    grace: Duration,
}

impl AgentTransport for SubprocessTransport {
    fn seat(&self) -> PlayerId {
        self.proc.as_ref().map(|p| p.seat()).unwrap_or(PlayerId(0))
    }

    fn send(&mut self, msg: &ServerMessage) -> Result<(), ArenaInternalError> {
        match self.proc.as_mut() {
            Some(p) => p
                .send(msg)
                .map_err(|e| ArenaInternalError::Transport(e.to_string())),
            None => Ok(()),
        }
    }

    fn shutdown(&mut self) {
        if let Some(mut p) = self.proc.take() {
            let _ = p.shutdown(self.grace);
        }
    }
}

/// Frozen scalars shared across the match, used to build reports.
struct RunCtx {
    game_id: String,
    ruleset_id: String,
    catalog_version: String,
    fingerprint: splendor_core::RulesetFingerprint,
    seed_commitment: SeedCommitment,
    player_count: u8,
}

/// Send one message and, on failure, surface the transport's bound seat.
///
/// Outbound send/flush failures during a running match are *agent faults*
/// ([`AgentFault::AgentIo`] against the recipient seat), never internal
/// errors. Callers map the returned seat to the phase-appropriate abort.
fn send_or_seat(transport: &mut dyn AgentTransport, msg: &ServerMessage) -> Result<(), PlayerId> {
    let seat = transport.seat();
    transport.send(msg).map_err(|_| seat)
}

fn build_report(ctx: &RunCtx, seats: &[SeatState], outcome: ArenaOutcomeV1) -> ArenaReportV1 {
    let agents: Vec<AgentIdentity> = seats.iter().map(|s| s.identity.clone()).collect();
    ArenaReportV1::new(
        ctx.game_id.clone(),
        ENGINE_VERSION,
        PROTOCOL_VERSION,
        ctx.ruleset_id.clone(),
        ctx.fingerprint.as_str(),
        ctx.player_count,
        ctx.seed_commitment.clone(),
        agents,
        outcome,
    )
}

#[allow(clippy::too_many_arguments)]
fn finish_aborted(
    transports: &mut [Box<dyn AgentTransport>],
    ctx: &RunCtx,
    seats: &[SeatState],
    seat: u8,
    phase: ArenaPhase,
    reason: AgentFault,
    request_id: Option<u64>,
    completed_plies: u32,
) -> ArenaRun {
    for t in transports.iter_mut() {
        t.shutdown();
    }
    let outcome = ArenaOutcomeV1::aborted(seat, phase, reason, request_id, completed_plies);
    ArenaRun {
        report: build_report(ctx, seats, outcome),
        replay: None,
    }
}

/// The already-verified branch point for [`ArenaRunner::run_branch`].
///
/// Every field comes from the source replay's strict verification:
/// - `state`: the rebuilt full state at the branch ply (before the branch
///   ply's action);
/// - `prefix_steps`: the source replay's steps `[0, branch_ply)` — the
///   resumed recorder's step chain starts with them;
/// - `initial_state_hash`: the source replay's initial-state hash;
/// - `ruleset` / `ruleset_fingerprint`: the source replay's ruleset
///   identity (re-checked against the engine by the recorder resume path);
/// - `seed`: the source game's seed (the hidden world being branched);
/// - `prefix_events`: the per-ply referee events of `[0, branch_ply)`,
///   replayed to the agents as visible-event history before the first
///   observation (belief-tracking agents require the complete transcript).
#[derive(Debug, Clone)]
pub struct BranchStart {
    pub state: splendor_core::FullState,
    pub prefix_steps: Vec<splendor_replay::ReplayStepV1>,
    pub initial_state_hash: splendor_replay::ReplayHash,
    pub ruleset: splendor_replay::ReplayRulesetV1,
    pub ruleset_fingerprint: splendor_replay::ReplayHash,
    pub seed: u64,
    pub prefix_events: Vec<Vec<RefereeEvent>>,
}

/// The seat-bound match runner. Holds no live state; [`ArenaRunner::run`]
/// owns the whole lifecycle of one match.
pub struct ArenaRunner;

/// The result of running one match: the v1 report plus, on a clean terminal,
/// the verified [`ReplayV1`].
#[derive(Debug)]
pub struct ArenaRun {
    /// The machine-readable arena report (always present).
    pub report: ArenaReportV1,
    /// `Some(replay)` only when the match reached a legal terminal state and
    /// the replay re-verified; `None` for any aborted match.
    pub replay: Option<ReplayV1>,
}

/// The result of running one **capped** match via [`ArenaRunner::run_capped`].
///
/// A game that terminates before or exactly at the cap is reported exactly as
/// [`ArenaRunner::run`] would (`Completed` outcome + verified replay, no
/// prefix). A game still non-terminal at the cap yields a `Truncated`
/// outcome (cap facts only, no fabricated result), the capped rollout
/// prefix, and no replay.
#[derive(Debug)]
pub enum CappedRun {
    Terminal(ArenaRun),
    Truncated {
        report: ArenaReportV1,
        prefix: RolloutPrefixV1,
    },
}

impl ArenaRunner {
    /// Run a full match against real agent subprocesses.
    pub fn run(config: ArenaConfig) -> Result<ArenaRun, ArenaInternalError> {
        let grace = Duration::from_millis(config.shutdown_grace_ms);
        Self::run_with(config, move |cmd, seat, tx| {
            let proc = spawn_agent(seat, cmd, tx)
                .map_err(|e| ArenaInternalError::Transport(e.to_string()))?;
            let transport: Box<dyn AgentTransport> = Box::new(SubprocessTransport {
                proc: Some(proc),
                grace,
            });
            Ok(transport)
        })
    }

    /// Run one **counterfactual branch continuation** (M41A `run-branch`).
    ///
    /// Semantics (frozen by the M41A design, `docs/
    /// m41a-counterfactual-action-value-probe.md` §6):
    /// - `start.state` is the already-verified full state at the branch
    ///   point (the caller rebuilt + hash-checked it via
    ///   `verify_replay_position` on the source replay);
    /// - the **forced action** is applied by the referee FIRST, without
    ///   any agent involvement, and validated against the rebuilt legal
    ///   set before application;
    /// - both seats then play the continuation (normally the frozen
    ///   D2-v2 agent on both sides) under the ordinary per-turn state
    ///   machine;
    /// - before the first observation, every seat receives the complete
    ///   projected visible-event history (setup + source-game prefix +
    ///   forced action), so belief-tracking agents see exactly the
    ///   transcript a live game of this line would have produced;
    /// - the finished replay contains the full step chain from the
    ///   source game's initial state (prefix steps + forced action +
    ///   continuation);
    /// - `ply_cap` is ABSOLUTE (plies counted from the source game's
    ///   first ply), matching the M39A/M40A source-rollout cap semantics.
    pub fn run_branch(
        config: ArenaConfig,
        start: BranchStart,
        forced_action: Action,
        ply_cap: u32,
    ) -> Result<CappedRun, ArenaInternalError> {
        let grace = Duration::from_millis(config.shutdown_grace_ms);
        Self::run_branch_with(
            config,
            start,
            forced_action,
            ply_cap,
            move |cmd, seat, tx| {
                let proc = spawn_agent(seat, cmd, tx)
                    .map_err(|e| ArenaInternalError::Transport(e.to_string()))?;
                let transport: Box<dyn AgentTransport> = Box::new(SubprocessTransport {
                    proc: Some(proc),
                    grace,
                });
                Ok(transport)
            },
        )
    }

    /// Transport-injectable branch driver for tests.
    pub(crate) fn run_branch_with<F>(
        config: ArenaConfig,
        start: BranchStart,
        forced_action: Action,
        ply_cap: u32,
        make: F,
    ) -> Result<CappedRun, ArenaInternalError>
    where
        F: FnMut(
            &AgentCommand,
            PlayerId,
            Sender<InboundEvent>,
        ) -> Result<Box<dyn AgentTransport>, ArenaInternalError>,
    {
        if ply_cap == 0 || ply_cap >= MAX_MATCH_PLIES {
            return Err(ArenaInternalError::Engine(format!(
                "ply cap {ply_cap} must be in 1..{MAX_MATCH_PLIES}"
            )));
        }
        Self::run_with_inner(
            config,
            Some(ply_cap),
            &mut Some((start, forced_action)),
            make,
        )
    }

    /// Run one match under a training ply cap against real agent subprocesses.
    ///
    /// Terminal at or before the cap: identical outcome to
    /// [`ArenaRunner::run`]. Non-terminal at the cap: a `Truncated` report
    /// (cap facts only, no fabricated result) plus the capped rollout
    /// prefix. The engine's 10,000-ply safety limit cannot fire because the
    /// cap is strictly below it and checked first.
    pub fn run_capped(config: ArenaConfig, ply_cap: u32) -> Result<CappedRun, ArenaInternalError> {
        let grace = Duration::from_millis(config.shutdown_grace_ms);
        Self::run_capped_with(config, ply_cap, move |cmd, seat, tx| {
            let proc = spawn_agent(seat, cmd, tx)
                .map_err(|e| ArenaInternalError::Transport(e.to_string()))?;
            let transport: Box<dyn AgentTransport> = Box::new(SubprocessTransport {
                proc: Some(proc),
                grace,
            });
            Ok(transport)
        })
    }

    /// Capped match driver, transport-injectable for tests.
    pub(crate) fn run_capped_with<F>(
        config: ArenaConfig,
        ply_cap: u32,
        make: F,
    ) -> Result<CappedRun, ArenaInternalError>
    where
        F: FnMut(
            &AgentCommand,
            PlayerId,
            Sender<InboundEvent>,
        ) -> Result<Box<dyn AgentTransport>, ArenaInternalError>,
    {
        if ply_cap == 0 || ply_cap >= MAX_MATCH_PLIES {
            return Err(ArenaInternalError::Engine(format!(
                "ply cap {ply_cap} must be in 1..{MAX_MATCH_PLIES}"
            )));
        }
        match Self::run_with_inner(config, Some(ply_cap), &mut None, make)? {
            CappedRun::Terminal(run) => Ok(CappedRun::Terminal(run)),
            CappedRun::Truncated { report, prefix } => Ok(CappedRun::Truncated { report, prefix }),
        }
    }

    /// Test-only alias so `runner::tests` (a sibling module, not a child)
    /// can drive the capped runner with scripted transports.
    #[cfg(test)]
    pub(crate) fn run_capped_with_for_tests<F>(
        config: ArenaConfig,
        ply_cap: u32,
        make: F,
    ) -> Result<CappedRun, ArenaInternalError>
    where
        F: FnMut(
            &AgentCommand,
            PlayerId,
            Sender<InboundEvent>,
        ) -> Result<Box<dyn AgentTransport>, ArenaInternalError>,
    {
        Self::run_capped_with(config, ply_cap, make)
    }

    /// Core match driver, transport-injectable for tests.
    pub(crate) fn run_with<F>(config: ArenaConfig, make: F) -> Result<ArenaRun, ArenaInternalError>
    where
        F: FnMut(
            &AgentCommand,
            PlayerId,
            Sender<InboundEvent>,
        ) -> Result<Box<dyn AgentTransport>, ArenaInternalError>,
    {
        match Self::run_with_inner(config, None, &mut None, make)? {
            CappedRun::Terminal(run) => Ok(run),
            CappedRun::Truncated { .. } => Err(ArenaInternalError::Engine(
                "uncapped run cannot produce a truncated outcome".into(),
            )),
        }
    }

    /// The single shared match driver: `cap == None` is the legacy
    /// run-to-terminal behaviour; `cap == Some(n)` truncates at n plies.
    /// `branch == Some((start, forced))` runs the M41A counterfactual
    /// branch semantics instead of a fresh game (see
    /// [`ArenaRunner::run_branch`]); `branch` and `cap == None` is an
    /// implementation error (branches always cap).
    fn run_with_inner<F>(
        config: ArenaConfig,
        cap: Option<u32>,
        branch: &mut Option<(BranchStart, Action)>,
        mut make: F,
    ) -> Result<CappedRun, ArenaInternalError>
    where
        F: FnMut(
            &AgentCommand,
            PlayerId,
            Sender<InboundEvent>,
        ) -> Result<Box<dyn AgentTransport>, ArenaInternalError>,
    {
        config.validate()?;

        let player_count = config.player_count();
        let seed = config.seed;

        // Branch mode: resume the recorder from the verified branch state,
        // apply the forced action referee-side, and collect the FULL
        // visible-event history (prefix + forced action) for replay to the
        // agents before the first observation. Fresh mode: the ordinary
        // recorder + setup events.
        enum Bootstrap {
            Fresh {
                setup_events: Vec<RefereeEvent>,
            },
            Branch {
                history_events: Vec<Vec<RefereeEvent>>,
            },
        }

        let (mut recorder, bootstrap): (ReplayRecorder, Bootstrap) = match branch.take() {
            None => {
                let (recorder, setup) = ReplayRecorder::new_with_setup(GameConfig {
                    player_count,
                    seed,
                    ruleset: Ruleset::base_v1(),
                })
                .map_err(|e| ArenaInternalError::Replay(e.to_string()))?;
                (
                    recorder,
                    Bootstrap::Fresh {
                        setup_events: setup.events,
                    },
                )
            }
            Some((start, forced_action)) => {
                let BranchStart {
                    state,
                    prefix_steps,
                    initial_state_hash,
                    ruleset: replay_ruleset,
                    ruleset_fingerprint: replay_fingerprint,
                    seed: source_seed,
                    prefix_events,
                } = start;
                let mut recorder = ReplayRecorder::resume_from_state(
                    GameConfig {
                        player_count,
                        seed: source_seed,
                        ruleset: Ruleset::base_v1(),
                    },
                    state,
                    prefix_steps,
                    initial_state_hash,
                    replay_ruleset,
                    replay_fingerprint,
                )
                .map_err(|e| ArenaInternalError::Replay(e.to_string()))?;
                // Forced-action validation against the AUTHORITATIVE rebuilt
                // legal set: containment, fail-closed (no transports exist
                // yet, so there is nothing to shut down on this error path).
                if !recorder.legal_actions().contains(&forced_action) {
                    return Err(ArenaInternalError::Engine(format!(
                        "forced action {forced_action:?} is not in the rebuilt legal set"
                    )));
                }
                let step = recorder
                    .apply(forced_action)
                    .map_err(|e| ArenaInternalError::Engine(e.to_string()))?;
                // The forced ply is completed referee-side; the agents will
                // receive its projected events with the prefix history.
                let mut history = prefix_events;
                history.push(step.events);
                (
                    recorder,
                    Bootstrap::Branch {
                        history_events: history,
                    },
                )
            }
        };

        let ruleset_id = recorder.state().ruleset.id.0.to_string();
        let catalog_version = CATALOG_VERSION.to_string();
        let fingerprint = ruleset_fingerprint(&recorder.state().ruleset);
        let seed_commitment = seed_commitment_v1(&config.game_id, player_count, seed, &fingerprint);

        let ctx = RunCtx {
            game_id: config.game_id.clone(),
            ruleset_id,
            catalog_version,
            fingerprint,
            seed_commitment,
            player_count,
        };

        // Spawn transports in seat order.
        let (tx, rx) = mpsc::channel::<InboundEvent>();
        let mut transports: Vec<Box<dyn AgentTransport>> =
            Vec::with_capacity(player_count as usize);
        let mut seats: Vec<SeatState> = (0..player_count)
            .map(|i| SeatState::new(PlayerId(i)))
            .collect();

        let mut spawn_failed: Option<u8> = None;
        for (index, cmd) in config.agents.iter().enumerate() {
            let seat = PlayerId(index as u8);
            match make(cmd, seat, tx.clone()) {
                Ok(t) => transports.push(t),
                Err(_) => {
                    spawn_failed = Some(seat.0);
                    break;
                }
            }
        }

        if let Some(failed) = spawn_failed {
            return Ok(CappedRun::Terminal(finish_aborted(
                &mut transports,
                &ctx,
                &seats,
                failed,
                ArenaPhase::Handshake,
                AgentFault::AgentIo,
                None,
                0,
            )));
        }

        // Branch mode's prespawned plies (prefix + forced): the cap counter
        // must start from the recorder's absolute ply position.
        let prespawned_plies = match &bootstrap {
            Bootstrap::Fresh { .. } => 0,
            Bootstrap::Branch { history_events } => history_events.len() as u32,
        };
        let mut counters = MatchCounters::with_completed_plies(prespawned_plies);

        // ---- Handshake: send Hello to every seat, then start one deadline.
        // The deadline starts only after every Hello flushed successfully; a
        // send failure is that seat's AgentIo fault, not a handshake timeout.
        let mut hello_failed: Option<PlayerId> = None;
        for t in transports.iter_mut() {
            let seq = counters.next_server_seq()?;
            let hello = ServerMessage::Hello {
                meta: ServerMeta::new(ctx.game_id.clone(), seq),
                engine_version: ENGINE_VERSION.to_string(),
                ruleset: ctx.ruleset_id.clone(),
                catalog_version: ctx.catalog_version.clone(),
                ruleset_fingerprint: ctx.fingerprint.clone(),
            };
            if let Err(seat) = send_or_seat(t.as_mut(), &hello) {
                hello_failed = Some(seat);
                break;
            }
        }
        if let Some(seat) = hello_failed {
            return Ok(CappedRun::Terminal(finish_aborted(
                &mut transports,
                &ctx,
                &seats,
                seat.0,
                ArenaPhase::Handshake,
                AgentFault::AgentIo,
                None,
                0,
            )));
        }
        let handshake_deadline =
            Instant::now() + Duration::from_millis(config.handshake_timeout_ms);

        let mut aborted: Option<ArenaRun> = None;
        'handshake: while seats.iter().any(|s| !s.handshake_done) {
            let remaining = handshake_deadline.saturating_duration_since(Instant::now());
            match rx.recv_timeout(remaining) {
                Ok(InboundEvent::Line { seat, line }) => {
                    if let Err((fault_seat, fault)) =
                        handle_handshake_line(&line, &config, &mut seats, seat)
                    {
                        aborted = Some(finish_aborted(
                            &mut transports,
                            &ctx,
                            &seats,
                            fault_seat,
                            ArenaPhase::Handshake,
                            fault,
                            None,
                            0,
                        ));
                        break 'handshake;
                    }
                }
                Ok(InboundEvent::StdoutEof { seat }) => {
                    aborted = Some(finish_aborted(
                        &mut transports,
                        &ctx,
                        &seats,
                        seat.0,
                        ArenaPhase::Handshake,
                        AgentFault::AgentEof,
                        None,
                        0,
                    ));
                    break 'handshake;
                }
                Ok(InboundEvent::StdoutError { seat, .. }) => {
                    aborted = Some(finish_aborted(
                        &mut transports,
                        &ctx,
                        &seats,
                        seat.0,
                        ArenaPhase::Handshake,
                        AgentFault::AgentIo,
                        None,
                        0,
                    ));
                    break 'handshake;
                }
                Ok(InboundEvent::MessageTooLarge { seat, .. }) => {
                    aborted = Some(finish_aborted(
                        &mut transports,
                        &ctx,
                        &seats,
                        seat.0,
                        ArenaPhase::Handshake,
                        AgentFault::MessageTooLarge,
                        None,
                        0,
                    ));
                    break 'handshake;
                }
                Err(RecvTimeoutError::Timeout) => {
                    // Lowest-index pending (not-yet-handshaken) seat.
                    let pending = seats
                        .iter()
                        .find(|s| !s.handshake_done)
                        .map(|s| s.seat.0)
                        .unwrap_or(0);
                    aborted = Some(finish_aborted(
                        &mut transports,
                        &ctx,
                        &seats,
                        pending,
                        ArenaPhase::Handshake,
                        AgentFault::HandshakeTimeout,
                        None,
                        0,
                    ));
                    break 'handshake;
                }
                Err(RecvTimeoutError::Disconnected) => {
                    for t in transports.iter_mut() {
                        t.shutdown();
                    }
                    return Err(ArenaInternalError::Channel(
                        "inbound channel disconnected during handshake".into(),
                    ));
                }
            }
        }

        if let Some(run) = aborted {
            return Ok(CappedRun::Terminal(run));
        }

        // ---- GameStart to every seat, in order. A send failure is the
        // recipient seat's AgentIo fault (still handshake phase). ----
        let mut game_start_failed: Option<PlayerId> = None;
        for t in transports.iter_mut() {
            let seq = counters.next_server_seq()?;
            let msg = ServerMessage::GameStart {
                meta: RecipientMeta::new(ctx.game_id.clone(), seq, t.seat()),
                player_count: ctx.player_count,
                seed_commitment: ctx.seed_commitment.as_str().to_string(),
            };
            if let Err(seat) = send_or_seat(t.as_mut(), &msg) {
                game_start_failed = Some(seat);
                break;
            }
        }
        if let Some(seat) = game_start_failed {
            return Ok(CappedRun::Terminal(finish_aborted(
                &mut transports,
                &ctx,
                &seats,
                seat.0,
                ArenaPhase::Handshake,
                AgentFault::AgentIo,
                None,
                0,
            )));
        }

        // Every live player-view policy needs the same cumulative transcript
        // used by offline M07 analysis. Fresh mode: deliver the projected
        // setup events before the first observation/request (GameStarted and
        // SetupDealt, never the raw seed or hidden deck order). Branch mode:
        // deliver the COMPLETE projected history — setup events (rebuilt from
        // the source seed), every prefix ply's events, and the forced
        // action's events — so a belief-tracking continuation agent sees
        // exactly the transcript a live game of this line would have
        // produced.
        let history_batches: Vec<Vec<RefereeEvent>> = match &bootstrap {
            Bootstrap::Fresh { setup_events } => vec![setup_events.clone()],
            Bootstrap::Branch { history_events } => {
                // Rebuild the setup events from the source seed: the branch
                // recorder resumed WITHOUT setup events, but the agents'
                // transcript must still start with them.
                let (_, setup) = ReplayRecorder::new_with_setup(GameConfig {
                    player_count,
                    seed: recorder.seed(),
                    ruleset: Ruleset::base_v1(),
                })
                .map_err(|e| ArenaInternalError::Replay(e.to_string()))?;
                let mut batches = vec![setup.events];
                batches.extend(history_events.iter().cloned());
                batches
            }
        };
        for batch in &history_batches {
            if let Some(failed_seat) = broadcast_events(
                &mut transports,
                &ctx,
                &mut counters,
                batch,
                BroadcastMode::Strict,
            )? {
                return Ok(CappedRun::Terminal(finish_aborted(
                    &mut transports,
                    &ctx,
                    &seats,
                    failed_seat.0,
                    ArenaPhase::Handshake,
                    AgentFault::AgentIo,
                    None,
                    counters.completed_plies(),
                )));
            }
        }

        // ---- Per-turn loop. ----
        loop {
            if recorder.is_terminal() {
                break;
            }
            // Pre-request cap check (branch mode): the recorder may already
            // be at the absolute cap after the forced ply — no agent ply
            // may run. Fresh mode is unaffected (counters start at 0 < any
            // valid cap). Being BEYOND the cap is a caller configuration
            // error and fails closed.
            if let Some(cap_value) = cap {
                let completed = counters.completed_plies();
                if completed > cap_value {
                    for t in transports.iter_mut() {
                        t.shutdown();
                    }
                    return Err(ArenaInternalError::Engine(format!(
                        "branch position {completed} is already past the ply cap {cap_value}"
                    )));
                }
                if completed == cap_value {
                    let cap_plies = counters.completed_plies();
                    let (state, prefix) = recorder
                        .finish_prefix(cap_plies)
                        .map_err(|e| ArenaInternalError::Replay(e.to_string()))?;
                    let cap_scores = state
                        .players
                        .iter()
                        .map(|player| player.prestige)
                        .collect::<Vec<_>>();
                    for t in transports.iter_mut() {
                        let seq = counters.next_server_seq();
                        if seq.is_err() {
                            break;
                        }
                        let msg = ServerMessage::GameTruncated {
                            meta: RecipientMeta::new(
                                ctx.game_id.clone(),
                                seq.expect("checked above"),
                                t.seat(),
                            ),
                            completed_plies: cap_plies,
                            cap_state_hash: prefix.cap_state_hash.as_str().to_string(),
                            cap_scores: cap_scores.clone(),
                        };
                        let _ = t.send(&msg);
                    }
                    let outcome = ArenaOutcomeV1::truncated(
                        cap_plies,
                        prefix.cap_state_hash.as_str().to_string(),
                        cap_scores,
                    );
                    for t in transports.iter_mut() {
                        t.shutdown();
                    }
                    return Ok(CappedRun::Truncated {
                        report: build_report(&ctx, &seats, outcome),
                        prefix,
                    });
                }
            }
            if counters.completed_plies() >= MAX_MATCH_PLIES {
                for t in transports.iter_mut() {
                    t.shutdown();
                }
                return Err(ArenaInternalError::Engine(
                    "match exceeded ply safety limit".into(),
                ));
            }

            let current = recorder.current_player();
            let obs = recorder.state().observation(current);
            let obs_hash = observation_hash(&obs);

            // Observation send failure: no request was issued yet, so the
            // abort carries request_id=None.
            {
                let seq = counters.next_server_seq()?;
                let msg = ServerMessage::Observation {
                    meta: ObservationMeta::new(ctx.game_id.clone(), seq, current, obs_hash.clone()),
                    observation: obs,
                };
                if let Err(seat) = send_or_seat(transports[current.index()].as_mut(), &msg) {
                    return Ok(CappedRun::Terminal(finish_aborted(
                        &mut transports,
                        &ctx,
                        &seats,
                        seat.0,
                        ArenaPhase::ActionRequest,
                        AgentFault::AgentIo,
                        None,
                        counters.completed_plies(),
                    )));
                }
            }

            let legal = recorder.legal_actions();
            let request_id = counters.next_request_id()?;
            {
                let seq = counters.next_server_seq()?;
                let msg = ServerMessage::RequestAction {
                    meta: RequestMeta::new(ctx.game_id.clone(), seq, current, request_id, obs_hash),
                    deadline_ms: config.move_timeout_ms,
                    legal_actions: legal.clone(),
                };
                // The move deadline may only start after a successful flush;
                // a failed RequestAction send is AgentIo with this request's
                // id and must never be misreported as ActionTimeout.
                if let Err(seat) = send_or_seat(transports[current.index()].as_mut(), &msg) {
                    return Ok(CappedRun::Terminal(finish_aborted(
                        &mut transports,
                        &ctx,
                        &seats,
                        seat.0,
                        ArenaPhase::ActionRequest,
                        AgentFault::AgentIo,
                        Some(request_id),
                        counters.completed_plies(),
                    )));
                }
            }

            // Deadline starts only now: the request is known to be flushed.
            let move_deadline = Instant::now() + Duration::from_millis(config.move_timeout_ms);
            let completed_plies = counters.completed_plies();

            match wait_for_action(
                &rx,
                move_deadline,
                current,
                request_id,
                &legal,
                &config,
                completed_plies,
                &seats,
                &mut transports,
                &ctx,
            )? {
                WaitOutcome::Aborted(run) => return Ok(CappedRun::Terminal(run)),
                WaitOutcome::Action(action) => {
                    let step = recorder
                        .apply(action)
                        .map_err(|e| ArenaInternalError::Engine(e.to_string()))?;
                    // The ply is completed the moment the engine applied it:
                    // the recorder already contains the action, so the
                    // counter must advance before any broadcast can fail.
                    counters.inc_completed()?;

                    if recorder.is_terminal() {
                        // Terminal sends are best-effort: the replay is
                        // already formed and must not be discarded because a
                        // recipient hung up. Remaining seats are still tried.
                        broadcast_events(
                            &mut transports,
                            &ctx,
                            &mut counters,
                            &step.events,
                            BroadcastMode::BestEffort,
                        )?;
                    } else if let Some(failed_seat) = broadcast_events(
                        &mut transports,
                        &ctx,
                        &mut counters,
                        &step.events,
                        BroadcastMode::Strict,
                    )? {
                        // Non-terminal event delivery failed: the failing
                        // recipient seat is at fault, and completed_plies
                        // already reflects the applied action.
                        return Ok(CappedRun::Terminal(finish_aborted(
                            &mut transports,
                            &ctx,
                            &seats,
                            failed_seat.0,
                            ArenaPhase::ActionReceived,
                            AgentFault::AgentIo,
                            Some(request_id),
                            counters.completed_plies(),
                        )));
                    }

                    // ---- Cap check: stop before requesting the next ply. ----
                    // All agents have received this ply's events; the game is
                    // non-terminal. If the cap is reached, notify both seats
                    // with the no-result truncation message (best-effort, the
                    // prefix is already formed), finish the recorder as a
                    // prefix, record the cap facts, and never fabricate a
                    // terminal result.
                    if cap == Some(counters.completed_plies()) && !recorder.is_terminal() {
                        let cap_plies = counters.completed_plies();
                        let (state, prefix) = recorder
                            .finish_prefix(cap_plies)
                            .map_err(|e| ArenaInternalError::Replay(e.to_string()))?;
                        let cap_scores = state
                            .players
                            .iter()
                            .map(|player| player.prestige)
                            .collect::<Vec<_>>();
                        // Best-effort notification: the authoritative
                        // artifacts are the report and the prefix, and a
                        // recipient that already hung up must not lose them.
                        for t in transports.iter_mut() {
                            let seq = counters.next_server_seq();
                            if seq.is_err() {
                                break;
                            }
                            let msg = ServerMessage::GameTruncated {
                                meta: RecipientMeta::new(
                                    ctx.game_id.clone(),
                                    seq.expect("checked above"),
                                    t.seat(),
                                ),
                                completed_plies: cap_plies,
                                cap_state_hash: prefix.cap_state_hash.as_str().to_string(),
                                cap_scores: cap_scores.clone(),
                            };
                            let _ = t.send(&msg);
                        }
                        let outcome = ArenaOutcomeV1::truncated(
                            cap_plies,
                            prefix.cap_state_hash.as_str().to_string(),
                            cap_scores,
                        );
                        for t in transports.iter_mut() {
                            t.shutdown();
                        }
                        return Ok(CappedRun::Truncated {
                            report: build_report(&ctx, &seats, outcome),
                            prefix,
                        });
                    }
                }
            }
        }

        // ---- Terminal: finish + verify replay (authoritative boundary). ----
        let (state, replay) = recorder
            .finish()
            .map_err(|e| ArenaInternalError::Replay(e.to_string()))?;
        verify_replay(&replay).map_err(|e| ArenaInternalError::Replay(e.to_string()))?;
        let result = state
            .result
            .clone()
            .ok_or_else(|| ArenaInternalError::Replay("terminal state missing result".into()))?;

        let outcome = ArenaOutcomeV1::completed(
            result,
            counters.completed_plies(),
            replay.final_state_hash.as_str().to_string(),
        );
        for t in transports.iter_mut() {
            t.shutdown();
        }
        Ok(CappedRun::Terminal(ArenaRun {
            report: build_report(&ctx, &seats, outcome),
            replay: Some(replay),
        }))
    }
}

/// Validate one handshake line and, on success, advance the seat's state.
///
/// Returns `Err((seat, fault))` to abort with.
fn handle_handshake_line(
    line: &str,
    config: &ArenaConfig,
    seats: &mut [SeatState],
    seat: PlayerId,
) -> Result<(), (u8, AgentFault)> {
    let idx = seat.index();
    if idx >= seats.len() {
        return Err((seat.0, AgentFault::UnexpectedMessage));
    }
    if seats[idx].handshake_done {
        // Duplicate hello from an already-handshaken seat.
        return Err((seat.0, AgentFault::UnexpectedMessage));
    }
    let msg = parse_client_line(line).map_err(|_| (seat.0, AgentFault::MalformedMessage))?;
    match msg {
        ClientMessage::Hello {
            meta,
            agent_name,
            agent_version,
        } => match validate_hello(
            &meta.protocol_version,
            &meta.game_id,
            &agent_name,
            &agent_version,
            PROTOCOL_VERSION,
            &config.game_id,
        ) {
            Ok((name, version)) => {
                seats[idx].handshake_done = true;
                seats[idx].identity.agent_name = Some(name);
                seats[idx].identity.agent_version = Some(version);
                Ok(())
            }
            Err(fault) => Err((seat.0, fault)),
        },
        // Action or Pong during handshake is unexpected.
        ClientMessage::Action { .. } | ClientMessage::Pong { .. } => {
            Err((seat.0, AgentFault::UnexpectedMessage))
        }
    }
}

/// How [`wait_for_action`] resolved.
///
/// The `Aborted` variant carries the full run so callers can return it
/// directly; the size difference with `Action` is acceptable because this
/// enum only ever lives on the stack for one turn.
#[allow(clippy::large_enum_variant)]
pub(crate) enum WaitOutcome {
    /// A validated action is ready to apply.
    Action(Action),
    /// The match aborted; the run is already cleaned up.
    Aborted(ArenaRun),
}

#[allow(clippy::too_many_arguments)]
fn wait_for_action(
    rx: &Receiver<InboundEvent>,
    deadline: Instant,
    current: PlayerId,
    request_id: u64,
    legal: &[Action],
    config: &ArenaConfig,
    completed_plies: u32,
    seats: &[SeatState],
    transports: &mut [Box<dyn AgentTransport>],
    ctx: &RunCtx,
) -> Result<WaitOutcome, ArenaInternalError> {
    // Every arm resolves the outstanding request, so this "loop" runs at
    // most once today; it is kept for future tolerated-message handling.
    #[allow(clippy::never_loop)]
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        match rx.recv_timeout(remaining) {
            Ok(InboundEvent::Line { seat, line }) => {
                if seat != current {
                    // An inactive seat spoke during the outstanding request.
                    return Ok(WaitOutcome::Aborted(finish_aborted(
                        transports,
                        ctx,
                        seats,
                        seat.0,
                        ArenaPhase::ActionRequest,
                        AgentFault::UnexpectedMessage,
                        Some(request_id),
                        completed_plies,
                    )));
                }
                match classify_action(&line, config, request_id, legal) {
                    Ok(action) => return Ok(WaitOutcome::Action(action)),
                    Err(fault) => {
                        return Ok(WaitOutcome::Aborted(finish_aborted(
                            transports,
                            ctx,
                            seats,
                            current.0,
                            ArenaPhase::ActionRequest,
                            fault,
                            Some(request_id),
                            completed_plies,
                        )));
                    }
                }
            }
            Ok(InboundEvent::StdoutEof { seat }) => {
                return Ok(WaitOutcome::Aborted(finish_aborted(
                    transports,
                    ctx,
                    seats,
                    seat.0,
                    ArenaPhase::ActionRequest,
                    AgentFault::AgentEof,
                    Some(request_id),
                    completed_plies,
                )));
            }
            Ok(InboundEvent::StdoutError { seat, .. }) => {
                return Ok(WaitOutcome::Aborted(finish_aborted(
                    transports,
                    ctx,
                    seats,
                    seat.0,
                    ArenaPhase::ActionRequest,
                    AgentFault::AgentIo,
                    Some(request_id),
                    completed_plies,
                )));
            }
            Ok(InboundEvent::MessageTooLarge { seat, .. }) => {
                return Ok(WaitOutcome::Aborted(finish_aborted(
                    transports,
                    ctx,
                    seats,
                    seat.0,
                    ArenaPhase::ActionRequest,
                    AgentFault::MessageTooLarge,
                    Some(request_id),
                    completed_plies,
                )));
            }
            Err(RecvTimeoutError::Timeout) => {
                return Ok(WaitOutcome::Aborted(finish_aborted(
                    transports,
                    ctx,
                    seats,
                    current.0,
                    ArenaPhase::ActionRequest,
                    AgentFault::ActionTimeout,
                    Some(request_id),
                    completed_plies,
                )));
            }
            Err(RecvTimeoutError::Disconnected) => {
                for t in transports.iter_mut() {
                    t.shutdown();
                }
                return Err(ArenaInternalError::Channel(
                    "inbound channel disconnected during action".into(),
                ));
            }
        }
    }
}

/// Parse and validate a client action line.
fn classify_action(
    line: &str,
    config: &ArenaConfig,
    request_id: u64,
    legal: &[Action],
) -> Result<Action, AgentFault> {
    let msg = parse_client_line(line).map_err(|_| AgentFault::MalformedMessage)?;
    match msg {
        ClientMessage::Action { meta, action } => validate_action(
            &meta.client.protocol_version,
            &meta.client.game_id,
            meta.request_id,
            action,
            PROTOCOL_VERSION,
            &config.game_id,
            request_id,
            legal,
        ),
        // Hello/Pong from the current seat during an outstanding request.
        ClientMessage::Hello { .. } | ClientMessage::Pong { .. } => {
            Err(AgentFault::UnexpectedMessage)
        }
    }
}

/// How [`broadcast_events`] treats a per-recipient send failure.
#[derive(Clone, Copy, PartialEq, Eq)]
enum BroadcastMode {
    /// Stop at the first failed send and report the recipient seat. Used for
    /// non-terminal event delivery, where a broken recipient aborts the match.
    Strict,
    /// Ignore send failures and keep trying every remaining recipient. Used
    /// for terminal delivery, where the replay is already formed and one
    /// broken pipe must not block the other seats' game-end messages.
    BestEffort,
}

/// Project one step's referee events to every seat and forward them.
///
/// Each recipient is re-projected independently (no cloning of one seat's
/// transcript to another). `ActionApplied` and `GameEnded` are sent as their
/// dedicated wire messages; all other visible events go through `Event`.
///
/// Returns `Ok(Some(seat))` for the first failed recipient in
/// [`BroadcastMode::Strict`]; `Ok(None)` otherwise. Counter overflow is the
/// only internal error.
fn broadcast_events(
    transports: &mut [Box<dyn AgentTransport>],
    ctx: &RunCtx,
    counters: &mut MatchCounters,
    events: &[RefereeEvent],
    mode: BroadcastMode,
) -> Result<Option<PlayerId>, ArenaInternalError> {
    let count = ctx.player_count as usize;
    for (seat_idx, transport) in transports.iter_mut().enumerate().take(count) {
        let seat = PlayerId(seat_idx as u8);
        let vis = visible_events(events, Audience::Player(seat));
        for ve in vis {
            let seq = counters.next_server_seq()?;
            let meta = RecipientMeta::new(ctx.game_id.clone(), seq, seat);
            let msg = match ve {
                VisibleEvent::ActionApplied { player, action } => ServerMessage::ActionApplied {
                    meta,
                    actor_player_id: player.0,
                    action,
                },
                VisibleEvent::GameEnded { result } => ServerMessage::GameEnd { meta, result },
                other => ServerMessage::Event { meta, event: other },
            };
            if let Err(failed) = send_or_seat(transport.as_mut(), &msg) {
                match mode {
                    BroadcastMode::Strict => return Ok(Some(failed)),
                    // Best-effort: skip the rest of this seat's messages but
                    // keep serving the remaining recipients.
                    BroadcastMode::BestEffort => break,
                }
            }
        }
    }
    Ok(None)
}

#[cfg(test)]
mod tests;
