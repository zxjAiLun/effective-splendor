use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use splendor_agent::{
    AgentPolicy, DecisionContext, HeuristicAgentPolicy, PublicRequestMeta, StableRng,
};
use splendor_analysis::{
    analyze_replay_determinization_v2_with_progress, analyze_replay_neural_v2_with_progress,
    analyze_replay_s3_v2_with_progress, review_cache_key_v2, AnalysisTraceV2, RefereeRevealV1,
    ReviewerConfigV2, ReviewerIdentityV2, ReviewerRegistryV1,
};
use splendor_arena::config::MAX_TIMEOUT_MS;
use splendor_arena::{seed_commitment_v1, spawn_agent, AgentProcess, ArenaConfig, InboundEvent};
use splendor_catalog::{all_cards, all_nobles, CardId, GemColor, NobleId, Tier};
use splendor_core::{
    observation_hash, ruleset_fingerprint, visible_events, Action, Audience, FullState, GameConfig,
    GameResult, Observation, PlayerId, RefereeEvent, VisibleEvent, CATALOG_VERSION, ENGINE_VERSION,
};
use splendor_determinization_agent::DeterminizationAgentPolicyV1;
use splendor_eval::{RatedAgentV1, RatingRegistryV1};
use splendor_imperfect_search::RootDeterminizationConfigV1;
use splendor_learning::PolicyValueCheckpointV1;
use splendor_protocol::{
    parse_client_line, ClientMessage, ObservationMeta, RecipientMeta, RequestMeta, ServerMessage,
    ServerMeta, PROTOCOL_VERSION,
};
use splendor_replay::{
    replay_document_hash_v1, verify_replay, verify_replay_trace, ReplayRecorder, ReplayV1,
};
use splendor_search::{canonical_order, SearchConfigV1};
use splendor_studio_league::{
    now_epoch_seconds, open_studio_league_reader, CompletionOutcomeV1, IngestOutcome,
    LeagueMatchPageRequestV1, StudioLeagueError, StudioLeaguePathsV1, StudioLeagueReaderV1,
};

use crate::human_runtime_orchestration::{
    complete_persisted_human_occurrence, human_occurrence_slot, publish_human_evidence,
    HumanGameAuthority, HumanLeagueCompletion, HumanOccurrenceEvidence, HumanOccurrenceSlot,
};
use crate::runtime_orchestration::{
    complete_persisted_occurrence, completion_receipt_json, occurrence_slot, produce_and_complete,
    OccurrenceEvidence, OccurrenceSlotV1, RuntimeOrchestrationError, RuntimeOrchestrationOutcome,
};

const USAGE: &str = "Usage: splendor human-play-server --seed <u64> --human-seat <0|1> [--opponent <s3|s3-rollout|default|heuristic|fast|m07>] [--registry <registry.json> --agent-id <id>] --port <u16> [--move-timeout-ms <u64>] [--replay-out <replay.json>]";
const HOST_USAGE: &str =
    "Usage: splendor studio-host --registry <registry.json> [--reviewer-registry <reviewers.json>] --port <u16> [--handshake-timeout-ms <u64>] [--move-timeout-ms <u64>] [--shutdown-grace-ms <u64>] [--replay-sources <sources.json>] [--project-root <dir>]";
const DEFAULT_MOVE_TIMEOUT_MS: u64 = 120_000;
/// Studio Host default for the agent handshake timeout. The arena has no defaults
/// of its own -- every `ArenaConfig` timeout is a mandatory field -- so this is a
/// decision the Host makes on the operator's behalf, not an arena fallback.
const DEFAULT_HANDSHAKE_TIMEOUT_MS: u64 = 30_000;
/// Studio Host default grace before a spawned agent is killed. Same reasoning.
const DEFAULT_SHUTDOWN_GRACE_MS: u64 = 2_000;
const HANDSHAKE_TIMEOUT_MS: u64 = 30_000;
const HUMAN_PLAY_DIR: &str = "local-artifacts/m20-human-play";
const REVIEWS_DIR: &str = "reviews";

enum InProcessOpponent {
    S3(splendor_determinization_agent::s3_agent::S3RolloutAgentPolicy),
    Heuristic(HeuristicAgentPolicy),
    M07(DeterminizationAgentPolicyV1),
}

impl InProcessOpponent {
    fn choose(&mut self, context: DecisionContext<'_>) -> Result<Action, String> {
        match self {
            Self::S3(policy) => policy
                .choose_action(context)
                .map_err(|error| error.to_string()),
            Self::Heuristic(policy) => policy
                .choose_action(context)
                .map_err(|error| error.to_string()),
            Self::M07(policy) => policy
                .choose_action(context)
                .map_err(|error| error.to_string()),
        }
    }
}

struct RegisteredOpponent {
    process: AgentProcess,
    inbound: Receiver<InboundEvent>,
    display_name: String,
    seat: PlayerId,
    next_server_seq: u64,
    move_timeout_ms: u64,
}

impl RegisteredOpponent {
    #[allow(clippy::too_many_arguments)]
    fn start(
        selected: &RatedAgentV1,
        seat: PlayerId,
        game_id: &str,
        seed: u64,
        state: &FullState,
        setup_events: &[RefereeEvent],
        move_timeout_ms: u64,
    ) -> Result<Self, String> {
        // The Host passes the exact entry whose evidence it froze. No second
        // registry read is allowed between selection and spawning.
        let agent_id = &selected.id;
        let (tx, rx) = mpsc::channel();
        let mut process = spawn_agent(seat, &selected.command, tx)
            .map_err(|error| format!("cannot spawn registered agent `{agent_id}`: {error}"))?;

        let fingerprint = ruleset_fingerprint(&state.ruleset);
        process
            .send(&ServerMessage::Hello {
                meta: ServerMeta::new(game_id, 0),
                engine_version: ENGINE_VERSION.to_string(),
                ruleset: state.ruleset.id.0.to_string(),
                catalog_version: CATALOG_VERSION.to_string(),
                ruleset_fingerprint: fingerprint.clone(),
            })
            .map_err(|error| format!("registered agent hello send failed: {error}"))?;

        let line = receive_line(
            &rx,
            seat,
            Duration::from_millis(HANDSHAKE_TIMEOUT_MS),
            "handshake",
        )?;
        match parse_client_line(&line).map_err(|error| format!("invalid agent hello: {error}"))? {
            ClientMessage::Hello {
                meta,
                agent_name,
                agent_version,
            } if meta.protocol_version == PROTOCOL_VERSION
                && meta.game_id == game_id
                && agent_name == selected.runtime_name
                && agent_version == selected.runtime_version => {}
            ClientMessage::Hello { .. } => {
                return Err(format!(
                    "registered agent identity/protocol does not match registry entry `{agent_id}`"
                ))
            }
            _ => return Err("registered agent did not answer the handshake with hello".into()),
        }

        process
            .send(&ServerMessage::GameStart {
                meta: RecipientMeta::new(game_id, 1, seat),
                player_count: 2,
                seed_commitment: seed_commitment_v1(game_id, 2, seed, &fingerprint)
                    .as_str()
                    .to_string(),
            })
            .map_err(|error| format!("registered agent game_start send failed: {error}"))?;
        let mut opponent = Self {
            process,
            inbound: rx,
            display_name: selected.display_name.clone(),
            seat,
            next_server_seq: 2,
            move_timeout_ms,
        };
        opponent.send_visible_events(game_id, setup_events)?;
        Ok(opponent)
    }

    fn next_seq(&mut self) -> Result<u64, String> {
        let value = self.next_server_seq;
        self.next_server_seq = self
            .next_server_seq
            .checked_add(1)
            .ok_or_else(|| "server sequence overflow".to_string())?;
        Ok(value)
    }

    fn send_visible_events(
        &mut self,
        game_id: &str,
        events: &[RefereeEvent],
    ) -> Result<(), String> {
        for event in visible_events(events, Audience::Player(self.seat)) {
            let meta = RecipientMeta::new(game_id, self.next_seq()?, self.seat);
            let message = match event {
                VisibleEvent::ActionApplied { player, action } => ServerMessage::ActionApplied {
                    meta,
                    actor_player_id: player.0,
                    action,
                },
                VisibleEvent::GameEnded { result } => ServerMessage::GameEnd { meta, result },
                other => ServerMessage::Event { meta, event: other },
            };
            self.process
                .send(&message)
                .map_err(|error| format!("registered agent event send failed: {error}"))?;
        }
        Ok(())
    }

    fn choose(
        &mut self,
        game_id: &str,
        request_id: u64,
        observation: Observation,
        legal_actions: &[Action],
    ) -> Result<Action, String> {
        let hash = observation_hash(&observation);
        let observation_seq = self.next_seq()?;
        self.process
            .send(&ServerMessage::Observation {
                meta: ObservationMeta::new(game_id, observation_seq, self.seat, hash.clone()),
                observation,
            })
            .map_err(|error| format!("registered agent observation send failed: {error}"))?;
        let request_seq = self.next_seq()?;
        self.process
            .send(&ServerMessage::RequestAction {
                meta: RequestMeta::new(game_id, request_seq, self.seat, request_id, hash),
                deadline_ms: self.move_timeout_ms,
                legal_actions: legal_actions.to_vec(),
            })
            .map_err(|error| format!("registered agent request send failed: {error}"))?;
        let line = receive_line(
            &self.inbound,
            self.seat,
            Duration::from_millis(self.move_timeout_ms),
            "action",
        )?;
        match parse_client_line(&line).map_err(|error| format!("invalid agent action: {error}"))? {
            ClientMessage::Action { meta, action }
                if meta.client.protocol_version == PROTOCOL_VERSION
                    && meta.client.game_id == game_id
                    && meta.request_id == request_id
                    && legal_actions.contains(&action) =>
            {
                Ok(action)
            }
            ClientMessage::Action { .. } => {
                Err("registered agent action failed game/request/legal validation".into())
            }
            _ => Err("registered agent returned an unexpected message".into()),
        }
    }

    fn shutdown(&mut self) {
        let _ = self.process.shutdown(Duration::from_millis(1_000));
    }
}

fn receive_line(
    receiver: &Receiver<InboundEvent>,
    expected_seat: PlayerId,
    timeout: Duration,
    phase: &str,
) -> Result<String, String> {
    match receiver.recv_timeout(timeout) {
        Ok(InboundEvent::Line { seat, line }) if seat == expected_seat => Ok(line),
        Ok(InboundEvent::Line { seat, .. }) => Err(format!(
            "registered agent spoke from unexpected seat {} during {phase}",
            seat.0
        )),
        Ok(InboundEvent::StdoutEof { .. }) => {
            Err(format!("registered agent stdout closed during {phase}"))
        }
        Ok(InboundEvent::StdoutError { message, .. }) => Err(format!(
            "registered agent stdout failed during {phase}: {message}"
        )),
        Ok(InboundEvent::MessageTooLarge { limit, .. }) => Err(format!(
            "registered agent exceeded the {limit}-byte message limit during {phase}"
        )),
        Err(RecvTimeoutError::Timeout) => Err(format!("registered agent timed out during {phase}")),
        Err(RecvTimeoutError::Disconnected) => Err(format!(
            "registered agent channel disconnected during {phase}"
        )),
    }
}

enum Opponent {
    InProcess {
        label: &'static str,
        policy: InProcessOpponent,
    },
    Registered(RegisteredOpponent),
}

impl Opponent {
    fn label(&self) -> &str {
        match self {
            Self::InProcess { label, .. } => label,
            Self::Registered(agent) => &agent.display_name,
        }
    }

    fn choose(
        &mut self,
        game_id: &str,
        request_id: u64,
        observation: Observation,
        history: &[VisibleEvent],
        legal_actions: &[Action],
        rng: &mut StableRng,
    ) -> Result<Action, String> {
        match self {
            Self::InProcess { policy, .. } => policy.choose(DecisionContext {
                observation: observation.clone(),
                visible_history: history,
                legal_actions,
                meta: PublicRequestMeta {
                    game_id: game_id.to_string(),
                    recipient_seat: observation.viewer,
                    request_id,
                    observation_hash: observation_hash(&observation),
                },
                rng,
            }),
            Self::Registered(agent) => {
                agent.choose(game_id, request_id, observation, legal_actions)
            }
        }
    }

    fn send_visible_events(
        &mut self,
        game_id: &str,
        events: &[RefereeEvent],
    ) -> Result<(), String> {
        match self {
            Self::InProcess { .. } => Ok(()),
            Self::Registered(agent) => agent.send_visible_events(game_id, events),
        }
    }

    fn shutdown(&mut self) {
        if let Self::Registered(agent) = self {
            agent.shutdown();
        }
    }
}

#[derive(Debug, Clone, serde::Serialize)]
struct HumanReplayFrameV1 {
    ply: u32,
    actor: PlayerId,
    player_view: Observation,
    legal_actions: Vec<Action>,
    recorded_action: Action,
}

#[derive(Debug, serde::Serialize)]
struct HumanReplayArchiveV1<'a> {
    format: &'static str,
    version: u32,
    session_id: &'a str,
    opponent: &'a str,
    replay_document_hash: &'a str,
    replay: &'a ReplayV1,
    frames: &'a [HumanReplayFrameV1],
    catalog: PublicCatalogV1,
}

/// One reconstructed decision frame of a historical human replay.
///
/// Rebuilt from the verified ReplayV1 alone: the player view is the recorded
/// actor's own observation, the legal actions are canonical, and the referee
/// reveal is display-only data that must never be fed to an agent.
#[derive(Debug, serde::Serialize)]
struct HistoricalReplayFrameV1 {
    ply: u32,
    actor: PlayerId,
    player_view: Observation,
    legal_actions: Vec<Action>,
    recorded_action: Action,
    referee_reveal: RefereeRevealV1,
}

/// Read-only bundle for `GET /replays/{session_id}` (archive v2).
///
/// The reviewer-free counterpart of the in-session [`HumanReplayArchiveV1`]:
/// every frame is reconstructed from the authoritative ReplayV1 verifier, so
/// the viewer never depends on UI frames saved at play time.
#[derive(Debug, serde::Serialize)]
struct HistoricalReplayArchiveV2<'a> {
    format: &'static str,
    version: u32,
    session_id: &'a str,
    opponent: Option<String>,
    human_seat: Option<u8>,
    player_count: u8,
    replay_document_hash: String,
    replay: &'a ReplayV1,
    frames: Vec<HistoricalReplayFrameV1>,
    catalog: PublicCatalogV1,
}

#[derive(Debug, serde::Serialize)]
struct PublicCatalogCardV1 {
    id: CardId,
    tier: Tier,
    bonus: GemColor,
    prestige: u8,
    cost: [u8; 5],
}

#[derive(Debug, serde::Serialize)]
struct PublicCatalogNobleV1 {
    id: NobleId,
    prestige: u8,
    requirements: [u8; 5],
}

#[derive(Debug, serde::Serialize)]
struct PublicCatalogV1 {
    cards: Vec<PublicCatalogCardV1>,
    nobles: Vec<PublicCatalogNobleV1>,
}

fn public_catalog() -> PublicCatalogV1 {
    PublicCatalogV1 {
        cards: all_cards()
            .iter()
            .map(|card| PublicCatalogCardV1 {
                id: card.id,
                tier: card.tier,
                bonus: card.bonus,
                prestige: card.prestige,
                cost: card.cost,
            })
            .collect(),
        nobles: all_nobles()
            .iter()
            .map(|noble| PublicCatalogNobleV1 {
                id: noble.id,
                prestige: noble.prestige,
                requirements: noble.requirements,
            })
            .collect(),
    }
}

/// Rebuild every display frame from the ReplayV1 alone. Pure: no filesystem,
/// no reviewer and no AI — the only computation is the authoritative replay
/// verification, and the recorded action of every frame is re-checked against
/// the engine's canonical legal set.
fn build_historical_replay_archive<'a>(
    replay: &'a ReplayV1,
    session_id: &'a str,
    opponent: Option<String>,
    human_seat: Option<u8>,
) -> Result<HistoricalReplayArchiveV2<'a>, String> {
    let verified = verify_replay_trace(replay)
        .map_err(|error| format!("replay verification failed: {error}"))?;
    if verified.positions.len() != replay.steps.len() {
        return Err("verified trace length differs from replay".into());
    }
    let replay_document_hash =
        replay_document_hash_v1(replay).map_err(|error| error.to_string())?;
    let mut frames = Vec::with_capacity(verified.positions.len());
    for position in &verified.positions {
        if position.state.is_terminal() {
            return Err(format!("replay position {} is terminal", position.ply));
        }
        if position.state.current_player != position.recorded_actor {
            return Err(format!(
                "replay position {} actor does not match its state",
                position.ply
            ));
        }
        let legal_actions = canonical_order(&position.state.legal_actions());
        if !legal_actions.contains(&position.recorded_action) {
            return Err(format!(
                "recorded action at ply {} is not in the legal set",
                position.ply
            ));
        }
        frames.push(HistoricalReplayFrameV1 {
            ply: position.ply,
            actor: position.recorded_actor,
            player_view: position.state.observation(position.recorded_actor),
            legal_actions,
            recorded_action: position.recorded_action,
            referee_reveal: RefereeRevealV1 {
                seed: position.state.seed,
                decks: position.state.decks.clone(),
                players: position.state.players.clone(),
            },
        });
    }
    Ok(HistoricalReplayArchiveV2 {
        format: "effective-splendor-human-replay-archive",
        version: 2,
        session_id,
        opponent,
        human_seat,
        player_count: replay.player_count,
        replay_document_hash,
        replay,
        frames,
        catalog: public_catalog(),
    })
}

#[derive(serde::Serialize)]
struct HumanSessionState {
    format: &'static str,
    version: u32,
    session_id: String,
    /// Decimal string: browser Number cannot represent every replay seed exactly.
    seed: String,
    human_seat: PlayerId,
    opponent: String,
    ply: u32,
    observation: Observation,
    legal_actions: Vec<Action>,
    action_history: Vec<HumanActionHistoryV1>,
    result: Option<GameResult>,
    replay_ready: bool,
    replay_document_hash: Option<String>,
    league_completion: Option<HumanLeagueCompletion>,
}

#[derive(Debug, Clone, serde::Serialize)]
struct HumanActionHistoryV1 {
    ply: u32,
    actor: PlayerId,
    action: Action,
}

struct Session {
    id: String,
    human_seat: PlayerId,
    recorder: Option<ReplayRecorder>,
    terminal_state: Option<FullState>,
    replay: Option<ReplayV1>,
    replay_hash: Option<String>,
    replay_out: PathBuf,
    rated: Option<HumanGameAuthority>,
    league_completion: Option<HumanLeagueCompletion>,
    frames: Vec<HumanReplayFrameV1>,
    opponent: Opponent,
    opponent_rng: StableRng,
    request_id: u64,
    ply: u32,
}

impl Session {
    fn state(&self) -> &FullState {
        match (&self.recorder, &self.terminal_state) {
            (Some(recorder), _) => recorder.state(),
            (None, Some(state)) => state,
            _ => unreachable!("session always has a live or terminal state"),
        }
    }

    fn apply_recorded(&mut self, actor: PlayerId, action: Action) -> Result<(), String> {
        let (player_view, legal_actions) = {
            let state = self.state();
            (state.observation(actor), state.legal_actions())
        };
        self.frames.push(HumanReplayFrameV1 {
            ply: self.ply,
            actor,
            player_view,
            legal_actions,
            recorded_action: action,
        });
        let step = self
            .recorder
            .as_mut()
            .ok_or_else(|| "game is already terminal".to_string())?
            .apply(action)
            .map_err(|error| error.to_string())?;
        self.ply = self.ply.checked_add(1).ok_or("ply overflow")?;
        let notification = self.opponent.send_visible_events(&self.id, &step.events);
        // A process exiting while receiving GameEnd cannot erase a game the
        // recorder has already completed. Finalize even if that notification fails.
        if self.state().is_terminal() {
            if let Err(error) = notification {
                eprintln!("terminal notification: {error}");
            }
            self.finish_if_terminal()
        } else {
            notification
        }
    }

    fn finish_if_terminal(&mut self) -> Result<(), String> {
        if !self
            .recorder
            .as_ref()
            .is_some_and(ReplayRecorder::is_terminal)
        {
            return Ok(());
        }
        let recorder = self.recorder.take().expect("terminal recorder exists");
        let (state, replay) = recorder.finish().map_err(|error| error.to_string())?;
        let completed_at = now_epoch_seconds();
        // Keep the terminal fact BEFORE any fallible persistence. Otherwise an
        // IO error after recorder.take() leaves /state with neither state owner.
        self.terminal_state = Some(state);
        verify_replay(&replay)
            .map_err(|error| format!("recorded replay failed verification: {error}"))?;
        self.replay_hash =
            Some(replay_document_hash_v1(&replay).map_err(|error| error.to_string())?);
        self.replay = Some(replay);
        self.opponent.shutdown();

        let persisted = self.persist_terminal(completed_at);
        match (&self.rated, persisted) {
            (_, Ok(completion)) => self.league_completion = completion,
            (Some(_), Err(error)) => {
                // No claim that durable evidence exists when publication failed.
                self.league_completion = Some(HumanLeagueCompletion::failed(error, false));
            }
            (None, Err(error)) => return Err(error),
        }
        Ok(())
    }

    fn persist_terminal(&self, completed_at: i64) -> Result<Option<HumanLeagueCompletion>, String> {
        let replay = self.replay.as_ref().expect("verified terminal replay");
        let replay_json = format!(
            "{}\n",
            serde_json::to_string_pretty(replay).map_err(|e| e.to_string())?
        );
        let meta = serde_json::json!({
            "format": "effective-splendor-human-meta",
            "version": 1,
            "session_id": self.id,
            "opponent": self.opponent.label(),
            "human_seat": self.human_seat.0,
        });
        if let Some(parent) = self
            .replay_out
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
        {
            fs::create_dir_all(parent).map_err(|e| {
                format!("legacy replay directory failed; no completion attempted: {e}")
            })?;
        }
        let meta_json = format!("{meta:#}\n");
        crate::atomic_output::commit_completed_with(
            &self.replay_out,
            &replay_json,
            &self.replay_out.with_extension("meta.json"),
            &meta_json,
            crate::atomic_output::publish_new,
        )
        .map_err(|e| {
            format!("legacy replay/meta publication failed; no completion attempted: {e}")
        })?;

        let Some(rated) = &self.rated else {
            return Ok(None);
        };
        let dir = rated
            .paths
            .occurrence_dir(&self.id)
            .map_err(|e| e.to_string())?;
        let evidence = HumanOccurrenceEvidence::in_dir(&dir);
        let occurrence = rated.occurrence(
            &self.id,
            self.human_seat.0,
            replay,
            replay_json.as_bytes(),
            completed_at,
        );
        publish_human_evidence(&evidence, &occurrence, &replay_json)
            .map_err(|e| format!("legacy replay/meta saved, but human evidence publication failed; no completion attempted: {e}"))?;
        // The initial completion and every retry share this disk-only path.
        Ok(Some(HumanLeagueCompletion::from_result(
            complete_persisted_human_occurrence(&evidence, &rated.paths, &self.id),
        )))
    }

    fn advance_opponent(&mut self) -> Result<(), String> {
        while !self.state().is_terminal() && self.state().current_player != self.human_seat {
            let actor = self.state().current_player;
            let observation = self.state().observation(actor);
            let history = visible_events(&self.state().log, Audience::Player(actor));
            let legal_actions = self.state().legal_actions();
            self.request_id = self
                .request_id
                .checked_add(1)
                .ok_or_else(|| "request id overflow".to_string())?;
            let action = self.opponent.choose(
                &self.id,
                self.request_id,
                observation,
                &history,
                &legal_actions,
                &mut self.opponent_rng,
            )?;
            if !legal_actions.contains(&action) {
                return Err("opponent returned an illegal action".into());
            }
            self.apply_recorded(actor, action)?;
        }
        Ok(())
    }

    fn snapshot(&self) -> HumanSessionState {
        let state = self.state();
        HumanSessionState {
            format: "effective-splendor-human-session",
            version: 1,
            session_id: self.id.clone(),
            seed: state.seed.to_string(),
            human_seat: self.human_seat,
            opponent: self.opponent.label().to_string(),
            ply: self.ply,
            observation: state.observation(self.human_seat),
            legal_actions: if state.is_terminal() || state.current_player != self.human_seat {
                Vec::new()
            } else {
                state.legal_actions()
            },
            action_history: self
                .frames
                .iter()
                .map(|frame| HumanActionHistoryV1 {
                    ply: frame.ply,
                    actor: frame.actor,
                    action: frame.recorded_action,
                })
                .collect(),
            result: state.result.clone(),
            replay_ready: self.replay.is_some(),
            replay_document_hash: self.replay_hash.clone(),
            league_completion: self.league_completion.clone(),
        }
    }

    fn archive(&self) -> Result<HumanReplayArchiveV1<'_>, String> {
        Ok(HumanReplayArchiveV1 {
            format: "effective-splendor-human-replay-archive",
            version: 1,
            session_id: &self.id,
            opponent: self.opponent.label(),
            replay_document_hash: self
                .replay_hash
                .as_deref()
                .ok_or_else(|| "replay is available only after game completion".to_string())?,
            replay: self
                .replay
                .as_ref()
                .ok_or_else(|| "replay is available only after game completion".to_string())?,
            frames: &self.frames,
            catalog: public_catalog(),
        })
    }

    fn human_action(&mut self, action: Action) -> Result<(), String> {
        if self.state().is_terminal() {
            return Err("game is already terminal".into());
        }
        if self.state().current_player != self.human_seat {
            return Err("it is not the human seat's turn".into());
        }
        let legal = self.state().legal_actions();
        if !legal.contains(&action) {
            return Err("action is not in the server-certified legal set".into());
        }
        self.apply_recorded(self.human_seat, action)?;
        self.advance_opponent()
    }
}

#[derive(Debug)]
struct Args {
    seed: u64,
    human_seat: u8,
    opponent: Option<String>,
    registry: Option<PathBuf>,
    agent_id: Option<String>,
    port: u16,
    move_timeout_ms: u64,
    replay_out: Option<PathBuf>,
}

#[derive(Debug)]
struct HostArgs {
    registry: PathBuf,
    reviewer_registry: PathBuf,
    port: u16,
    /// The three match timeouts. Host-owned settings, never client-settable: a
    /// request body may name agents and a seed, but not how long the Host waits.
    handshake_timeout_ms: u64,
    move_timeout_ms: u64,
    shutdown_grace_ms: u64,
    replay_sources: Option<PathBuf>,
    /// The root every Studio League path derives from. Resolved exactly once, at
    /// startup: no handler may re-derive a league location from the cwd.
    project_root: Option<PathBuf>,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct NewGameRequest {
    agent_id: String,
    human_seat: u8,
    seed: u64,
}

#[derive(serde::Serialize)]
struct PublicAgentV1<'a> {
    id: &'a str,
    display_name: &'a str,
    class: splendor_eval::AgentClassV1,
    policy_version: &'a str,
    model_version: Option<&'a str>,
    checkpoint_hash: Option<&'a str>,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ReviewRequest {
    session_id: String,
    reviewer_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ReviewJobStatus {
    Queued,
    Running,
    Completed,
    Failed,
}

impl ReviewJobStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone)]
struct ReviewJobState {
    status: ReviewJobStatus,
    processed_decisions: u32,
    total_decisions: u32,
    current_ply: u32,
    error: Option<String>,
    cache_key: String,
    artifact_path: PathBuf,
    cached: bool,
}

struct ReviewJobRecord {
    id: String,
    session_id: String,
    reviewer_id: String,
    state: Arc<Mutex<ReviewJobState>>,
}

#[derive(Default)]
struct ReviewJobManager {
    next_id: u64,
    jobs: HashMap<String, ReviewJobRecord>,
}

impl ReviewJobManager {
    fn allocate(
        &mut self,
        session_id: String,
        reviewer_id: String,
        state: ReviewJobState,
    ) -> String {
        self.next_id = self.next_id.wrapping_add(1);
        let id = format!("review-{}", self.next_id);
        self.jobs.insert(
            id.clone(),
            ReviewJobRecord {
                id: id.clone(),
                session_id,
                reviewer_id,
                state: Arc::new(Mutex::new(state)),
            },
        );
        id
    }

    fn id_for_cache_key(&self, cache_key: &str) -> Option<String> {
        self.jobs.values().find_map(|record| {
            let state = record.state.lock().ok()?;
            (state.cache_key == cache_key).then(|| record.id.clone())
        })
    }
}

struct StudioHost {
    /// The one resolved league root, and the read-only session opened from it.
    /// The session is opened once at startup. When the league is missing the
    /// error is remembered and the league routes answer with it, so an unrelated
    /// (non-league) Host keeps working exactly as before.
    league: Option<StudioLeagueReaderV1>,
    league_error: Option<String>,
    /// The resolved league locations, kept so the completion outlet can be opened
    /// for a match. The reader keeps its own copy private, and no handler may
    /// re-derive a league location from the cwd.
    paths: StudioLeaguePathsV1,
    registry: RatingRegistryV1,
    reviewer_registry: ReviewerRegistryV1,
    handshake_timeout_ms: u64,
    move_timeout_ms: u64,
    shutdown_grace_ms: u64,
    next_session_number: u64,
    session: Option<Session>,
    jobs: ReviewJobManager,
    experiment_library: Option<crate::experiment_replays::ExperimentReplayLibrary>,
}

impl StudioHost {
    fn agents_json(&self) -> Result<String, String> {
        let agents = self
            .registry
            .agents
            .iter()
            .map(|agent| PublicAgentV1 {
                id: &agent.id,
                display_name: &agent.display_name,
                class: agent.class,
                policy_version: &agent.policy_version,
                model_version: agent.model_version.as_deref(),
                checkpoint_hash: agent.checkpoint_hash.as_deref(),
            })
            .collect::<Vec<_>>();
        serde_json::to_string(&serde_json::json!({
            "format": "effective-splendor-studio-agents",
            "version": 1,
            "registry_id": self.registry.registry_id,
            "agents": agents,
        }))
        .map_err(|error| error.to_string())
    }

    fn new_game(&mut self, request: NewGameRequest) -> Result<HumanSessionState, String> {
        if request.human_seat > 1 {
            return Err("human_seat must be 0 or 1".into());
        }
        let selected = self
            .registry
            .agents
            .iter()
            .find(|agent| agent.id == request.agent_id)
            .cloned()
            .ok_or_else(|| {
                format!(
                    "agent id `{}` is not in the Studio registry",
                    request.agent_id
                )
            })?;
        let rated = HumanGameAuthority::freeze(&self.paths, &self.registry.registry_id, &selected)?;
        let session_number = self.next_session_number;
        self.next_session_number = self
            .next_session_number
            .checked_add(1)
            .ok_or("Studio session counter overflow")?;
        let session = build_registered_session(
            request.seed,
            request.human_seat,
            &selected,
            self.move_timeout_ms,
            None,
            Some(session_number),
            Some(rated),
        )?;
        self.session = Some(session);
        Ok(self
            .session
            .as_ref()
            .expect("session was installed")
            .snapshot())
    }

    /// Empty-body, disk-only retry. Works after restart and without the old
    /// registry entry or executable. An absent/ambiguous slot never starts a game.
    fn retry_human_completion(
        &mut self,
        session_id: &str,
        body: &[u8],
    ) -> (u16, serde_json::Value) {
        if !body.is_empty() {
            return (
                400,
                serde_json::json!({"error": "league-completion requires an empty body"}),
            );
        }
        let dir = match self.paths.occurrence_dir(session_id) {
            Ok(dir) => dir,
            Err(e) => return (400, serde_json::json!({"error": e.to_string()})),
        };
        let evidence = HumanOccurrenceEvidence::in_dir(&dir);
        let completion = match human_occurrence_slot(&evidence) {
            HumanOccurrenceSlot::Empty => {
                return (
                    404,
                    serde_json::json!({"error": "no durable human occurrence evidence"}),
                )
            }
            HumanOccurrenceSlot::Ambiguous(error) => HumanLeagueCompletion::failed(error, false),
            HumanOccurrenceSlot::Complete => HumanLeagueCompletion::from_result(
                complete_persisted_human_occurrence(&evidence, &self.paths, session_id),
            ),
        };
        let code = match (completion.status, completion.retryable) {
            ("failed", true) => 503,
            ("failed", false) => 409,
            _ => 200,
        };
        if let Some(session) = self
            .session
            .as_mut()
            .filter(|s| s.id == session_id && s.state().is_terminal())
        {
            session.league_completion = Some(completion.clone());
        }
        if completion.status != "failed" {
            self.reopen_read_session_if_unavailable();
        }
        (
            code,
            serde_json::json!({"session_id": session_id, "league_completion": completion}),
        )
    }

    /// Reviewer discovery is player-count aware for the current replay: when
    /// a session is supplied, its replay is read once to resolve the replay's
    /// player count, and every entry reports the counts it supports and the
    /// counts it defaults for. The browser never supplies the player count
    /// itself.
    fn reviewers_json(&self, session: Option<&str>) -> Result<String, String> {
        let player_count = match session {
            Some(session_id) => {
                let session_id = sanitize_session_id(session_id)?;
                let replay_path =
                    Path::new(HUMAN_PLAY_DIR).join(format!("{session_id}.replay.json"));
                let replay = read_replay_file(&replay_path)?;
                Some(replay.player_count)
            }
            None => None,
        };
        let reviewers = self
            .reviewer_registry
            .reviewers
            .iter()
            .map(|entry| {
                serde_json::json!({
                    "id": entry.id,
                    "display_name": entry.display_name,
                    "description": entry.description,
                    "competitive_status": entry.competitive_status,
                    "result_kind": entry.result_kind,
                    "supported_player_counts": entry.supported_player_counts(),
                    "default_for_player_counts": entry.default_for_player_counts,
                    "available_metrics": entry.available_metrics,
                    "required_artifacts": entry.required_artifacts,
                    "estimated_cost": entry.estimated_cost,
                })
            })
            .collect::<Vec<_>>();
        serde_json::to_string(&serde_json::json!({
            "format": "effective-splendor-studio-reviewers",
            "version": 1,
            "registry_id": self.reviewer_registry.registry_id,
            "player_count": player_count,
            "reviewers": reviewers,
        }))
        .map_err(|error| error.to_string())
    }

    fn create_review(&mut self, request: ReviewRequest) -> Result<String, String> {
        let session_id = sanitize_session_id(&request.session_id)?;
        let entry = self
            .reviewer_registry
            .entry(&request.reviewer_id)
            .map_err(|error| error.to_string())?
            .clone();
        let replay_path = Path::new(HUMAN_PLAY_DIR).join(format!("{session_id}.replay.json"));
        let replay = read_replay_file(&replay_path)?;
        verify_replay(&replay).map_err(|error| format!("replay verification failed: {error}"))?;
        // Fail closed BEFORE any job is created: a reviewer that cannot
        // analyze this replay's player count must never start a background
        // job that fails mysteriously.
        ensure_reviewer_supported(&entry, replay.player_count)?;
        let replay_document_hash =
            replay_document_hash_v1(&replay).map_err(|error| error.to_string())?;

        let reviewer = reviewer_identity_from_entry(&entry)?;
        let checkpoint = match &reviewer.config {
            ReviewerConfigV2::NeuralIsmcts(config) => {
                let path = entry
                    .checkpoint_path
                    .as_deref()
                    .ok_or_else(|| "neural reviewer is missing checkpoint_path".to_string())?;
                let checkpoint_path = resolve_checkpoint_path(Path::new(path))?;
                let checkpoint = read_checkpoint_file(&checkpoint_path)?;
                let actual_hash = splendor_learning::model_checkpoint_hash_v1(&checkpoint)
                    .map_err(|error| error.to_string())?;
                if actual_hash != config.expected_checkpoint_hash {
                    return Err(format!(
                        "checkpoint hash mismatch: expected {}, found {actual_hash}",
                        config.expected_checkpoint_hash
                    ));
                }
                Some(checkpoint)
            }
            ReviewerConfigV2::RootDeterminization(_) => None,
            ReviewerConfigV2::PolicyRecommendation(_) => None,
        };

        let cache_key = review_cache_key_v2(&replay_document_hash, &reviewer)
            .map_err(|error| error.to_string())?;
        let artifact_path = Path::new(HUMAN_PLAY_DIR)
            .join(REVIEWS_DIR)
            .join(&session_id)
            .join(format!("{}-{}.analysis.json", reviewer.id, cache_key));

        if let Some(job_id) = self.jobs.id_for_cache_key(&cache_key) {
            return self.review_status(&job_id);
        }

        let state = ReviewJobState {
            status: ReviewJobStatus::Queued,
            processed_decisions: 0,
            total_decisions: replay.steps.len() as u32,
            current_ply: 0,
            error: None,
            cache_key: cache_key.clone(),
            artifact_path: artifact_path.clone(),
            cached: false,
        };
        let job_id = self
            .jobs
            .allocate(session_id.clone(), reviewer.id.clone(), state.clone());
        let shared = self
            .jobs
            .jobs
            .get(&job_id)
            .expect("job was installed")
            .state
            .clone();

        if artifact_path.exists() {
            validate_cached_review_artifact(
                &artifact_path,
                &cache_key,
                &reviewer.id,
                &replay_document_hash,
            )?;
            {
                let mut state = shared.lock().expect("review job lock");
                state.status = ReviewJobStatus::Completed;
                state.cached = true;
                state.processed_decisions = state.total_decisions;
            }
            return self.review_status(&job_id);
        }

        spawn_review_job(shared, replay, reviewer, checkpoint, artifact_path);
        self.review_status(&job_id)
    }

    fn review_status(&self, job_id: &str) -> Result<String, String> {
        let record = self
            .jobs
            .jobs
            .get(job_id)
            .ok_or_else(|| format!("unknown review job `{job_id}`"))?;
        let state = record.state.lock().expect("review job lock");
        serde_json::to_string(&serde_json::json!({
            "id": record.id,
            "session_id": record.session_id,
            "reviewer_id": record.reviewer_id,
            "status": state.status.as_str(),
            "processed_decisions": state.processed_decisions,
            "total_decisions": state.total_decisions,
            "current_ply": state.current_ply,
            "error": state.error,
            "cached": state.cached,
            "cache_key": state.cache_key,
        }))
        .map_err(|error| error.to_string())
    }

    fn review_bundle(&self, job_id: &str) -> Result<String, String> {
        let record = self
            .jobs
            .jobs
            .get(job_id)
            .ok_or_else(|| format!("unknown review job `{job_id}`"))?;
        let state = record.state.lock().expect("review job lock");
        if state.status != ReviewJobStatus::Completed {
            return Err(format!(
                "review job `{job_id}` is not completed (status: {})",
                state.status.as_str()
            ));
        }
        let path = state.artifact_path.clone();
        let cache_key = state.cache_key.clone();
        drop(state);
        validate_cached_review_artifact(&path, &cache_key, &record.reviewer_id, "")?;
        fs::read_to_string(&path).map_err(|error| format!("cannot read review artifact: {error}"))
    }

    fn experiment_library(
        &self,
    ) -> Result<&crate::experiment_replays::ExperimentReplayLibrary, String> {
        self.experiment_library
            .as_ref()
            .ok_or_else(|| "experiment replay sources are not configured on this host".to_string())
    }

    fn experiment_replays_index(&self) -> Result<String, String> {
        let index = self.experiment_library()?.index()?;
        serde_json::to_string(&index).map_err(|error| error.to_string())
    }

    fn experiment_replays_pairing(
        &self,
        experiment_id: &str,
        evaluation_id: &str,
    ) -> Result<String, String> {
        let matches = self
            .experiment_library()?
            .pairing_matches(experiment_id, evaluation_id)?;
        serde_json::to_string(&matches).map_err(|error| error.to_string())
    }

    fn experiment_replays_bundle(
        &self,
        experiment_id: &str,
        evaluation_id: &str,
        index: u32,
    ) -> Result<String, String> {
        let bundle = self
            .experiment_library()?
            .bundle(experiment_id, evaluation_id, index)?;
        serde_json::to_string(&bundle).map_err(|error| error.to_string())
    }

    fn recent_games(&self) -> Result<String, String> {
        let dir = Path::new(HUMAN_PLAY_DIR);
        let mut entries: Vec<serde_json::Value> = Vec::new();
        if dir.is_dir() {
            for entry in fs::read_dir(dir).map_err(|error| error.to_string())? {
                let entry = entry.map_err(|error| error.to_string())?;
                let path = entry.path();
                let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
                    continue;
                };
                let Some(session_id) = name.strip_suffix(".replay.json") else {
                    continue;
                };
                if !is_safe_component(session_id) {
                    continue;
                }
                let Ok(replay) = read_replay_file(&path) else {
                    entries.push(serde_json::json!({
                        "session_id": session_id,
                        "error": "unreadable replay",
                    }));
                    continue;
                };
                let verification = match verify_replay(&replay) {
                    Ok(_) => "verified",
                    Err(_) => "invalid",
                };
                let replay_document_hash = replay_document_hash_v1(&replay).ok();
                let reviews_dir = dir.join(REVIEWS_DIR).join(session_id);
                let available_reviews = replay_document_hash
                    .as_deref()
                    .map(|hash| {
                        list_cached_reviewers(&reviews_dir, hash, &self.reviewer_registry.reviewers)
                    })
                    .unwrap_or_default();
                let modified = fs::metadata(&path)
                    .ok()
                    .and_then(|meta| meta.modified().ok())
                    .and_then(|time| {
                        time.duration_since(std::time::UNIX_EPOCH)
                            .ok()
                            .map(|d| d.as_secs())
                    });
                let meta = read_human_meta(&dir.join(format!("{session_id}.meta.json")));
                let opponent = meta.as_ref().and_then(|m| m.get("opponent")).cloned();
                let human_seat = meta.as_ref().and_then(|m| m.get("human_seat")).cloned();
                entries.push(serde_json::json!({
                    "session_id": session_id,
                    "opponent": opponent,
                    "human_seat": human_seat,
                    "scores": replay.result.scores,
                    "winners": replay.result.winners,
                    "player_count": replay.player_count,
                    "timestamp": modified,
                    "verification": verification,
                    "available_reviews": available_reviews,
                }));
            }
        }
        entries.sort_by(|a, b| {
            let ta = a["timestamp"].as_u64().unwrap_or(0);
            let tb = b["timestamp"].as_u64().unwrap_or(0);
            tb.cmp(&ta)
        });
        serde_json::to_string(&serde_json::json!({
            "format": "effective-splendor-recent-games",
            "version": 1,
            "games": entries,
        }))
        .map_err(|error| error.to_string())
    }

    /// Reconstruct one historical replay from disk for the read-only viewer.
    /// Never runs a reviewer and never reads stored UI frames: the ReplayV1 is
    /// re-verified and every frame is rebuilt from it.
    fn historical_replay(&self, session_id: &str) -> Result<String, String> {
        let session_id = sanitize_session_id(session_id)?;
        let human_play_dir = Path::new(HUMAN_PLAY_DIR);
        let replay_path = human_play_dir.join(format!("{session_id}.replay.json"));
        if !replay_path.is_file() {
            return Err(format!("unknown session `{session_id}`"));
        }
        let replay = read_replay_file(&replay_path)?;
        let meta = read_human_meta(&human_play_dir.join(format!("{session_id}.meta.json")));
        let opponent = meta
            .as_ref()
            .and_then(|value| value.get("opponent"))
            .and_then(|value| value.as_str())
            .map(str::to_string);
        let human_seat = meta
            .as_ref()
            .and_then(|value| value.get("human_seat"))
            .and_then(|value| value.as_u64())
            .and_then(|value| u8::try_from(value).ok());
        let archive = build_historical_replay_archive(&replay, &session_id, opponent, human_seat)?;
        serde_json::to_string(&archive).map_err(|error| error.to_string())
    }
}

pub fn run_studio_host(args: &[String]) -> i32 {
    if args == ["--help"] || args == ["-h"] {
        println!("{HOST_USAGE}");
        return 0;
    }
    match serve_studio_host(args) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

fn sanitize_session_id(raw: &str) -> Result<String, String> {
    if !is_safe_component(raw) {
        return Err(format!("invalid session_id `{raw}`"));
    }
    Ok(raw.to_string())
}

fn is_safe_component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_' || b == b'.')
}

fn reviewer_identity_from_entry(
    entry: &splendor_analysis::ReviewerEntryV1,
) -> Result<ReviewerIdentityV2, String> {
    let checkpoint_hash = match &entry.default_config {
        ReviewerConfigV2::NeuralIsmcts(config) => Some(config.expected_checkpoint_hash.clone()),
        ReviewerConfigV2::RootDeterminization(_) => None,
        ReviewerConfigV2::PolicyRecommendation(_) => None,
    };
    Ok(ReviewerIdentityV2::new(
        entry.id.clone(),
        entry.display_name.clone(),
        entry.competitive_status,
        entry.result_kind,
        entry.default_config.clone(),
        checkpoint_hash,
    ))
}

/// Fail closed when a reviewer cannot analyze a replay with this player
/// count; the error is returned to the browser as a 4xx before any job runs.
fn ensure_reviewer_supported(
    entry: &splendor_analysis::ReviewerEntryV1,
    player_count: u8,
) -> Result<(), String> {
    if entry.supports_player_count(player_count) {
        Ok(())
    } else {
        Err(unsupported_reviewer_message(
            &entry.id,
            &entry.display_name,
            player_count,
        ))
    }
}

/// Fail-closed message for a reviewer that cannot analyze a replay with this
/// player count. The S3 rollout reviewer is the only 2-player-only reviewer.
fn unsupported_reviewer_message(reviewer_id: &str, display_name: &str, player_count: u8) -> String {
    let hint = if reviewer_id == splendor_analysis::S3_REVIEWER_ID {
        "the S3 rollout reviewer is frozen for 2-player replays"
    } else {
        "this reviewer does not cover that player count"
    };
    format!(
        "reviewer `{display_name}` is unavailable for {player_count}-player replays: {hint}; choose a reviewer that supports this replay"
    )
}

/// Extract a query parameter from a raw request target (`/path?a=b&c=d`).
fn query_param(target: &str, key: &str) -> Option<String> {
    let query = target.split_once('?')?.1;
    query.split('&').find_map(|pair| {
        let (name, value) = pair.split_once('=')?;
        (name == key).then(|| value.to_owned())
    })
}

/// Read one query parameter that may legitimately be absent.
///
/// Deliberately distinct from [`query_param`], which answers `None` for many
/// reasons at once. A route that must tell "absent" from "present but empty"
/// cannot use a helper that folds the two together.
fn query_param_optional(query: &str, key: &str) -> Option<String> {
    let query = query.strip_prefix('?').unwrap_or(query);
    if query.is_empty() {
        return None;
    }
    query.split('&').find_map(|pair| {
        let (name, value) = pair.split_once('=')?;
        (name == key).then(|| value.to_owned())
    })
}

fn read_replay_file(path: &Path) -> Result<ReplayV1, String> {
    read_json_file(path, 16 * 1024 * 1024, "replay")
}

fn read_checkpoint_file(path: &Path) -> Result<PolicyValueCheckpointV1, String> {
    read_json_file(path, 64 * 1024 * 1024, "checkpoint")
}

fn resolve_checkpoint_path(path: &Path) -> Result<PathBuf, String> {
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                std::path::Component::ParentDir
                    | std::path::Component::RootDir
                    | std::path::Component::Prefix(_)
            )
        })
    {
        return Err("reviewer checkpoint_path must be a safe relative path".into());
    }
    let allowed_root = fs::canonicalize("local-artifacts")
        .map_err(|error| format!("cannot resolve local-artifacts root: {error}"))?;
    let resolved = fs::canonicalize(path)
        .map_err(|error| format!("cannot resolve checkpoint {}: {error}", path.display()))?;
    if !resolved.starts_with(&allowed_root) {
        return Err(format!(
            "reviewer checkpoint {} escapes local-artifacts",
            path.display()
        ));
    }
    Ok(resolved)
}

fn read_json_file<T: serde::de::DeserializeOwned>(
    path: &Path,
    max_bytes: u64,
    label: &str,
) -> Result<T, String> {
    let file = File::open(path)
        .map_err(|error| format!("cannot open {label} {}: {error}", path.display()))?;
    let mut bytes = Vec::new();
    file.take(max_bytes + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("cannot read {label} {}: {error}", path.display()))?;
    if bytes.len() as u64 > max_bytes {
        return Err(format!("{label} exceeds {max_bytes} bytes"));
    }
    let text = String::from_utf8(bytes).map_err(|_| format!("{label} is not valid UTF-8"))?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let value =
        T::deserialize(&mut deserializer).map_err(|error| format!("invalid {label}: {error}"))?;
    deserializer
        .end()
        .map_err(|_| format!("trailing data after {label} JSON"))?;
    Ok(value)
}

fn validate_cached_review_artifact(
    path: &Path,
    expected_cache_key: &str,
    expected_reviewer_id: &str,
    expected_replay_document_hash: &str,
) -> Result<AnalysisTraceV2, String> {
    let trace: AnalysisTraceV2 = read_json_file(path, 64 * 1024 * 1024, "review artifact")?;
    trace.validate().map_err(|error| error.to_string())?;
    if trace.reviewer.id != expected_reviewer_id {
        return Err("cached review reviewer identity mismatch".into());
    }
    if !expected_replay_document_hash.is_empty()
        && trace.replay_document_hash != expected_replay_document_hash
    {
        return Err("cached review replay identity mismatch".into());
    }
    let actual_cache_key = review_cache_key_v2(&trace.replay_document_hash, &trace.reviewer)
        .map_err(|error| error.to_string())?;
    if actual_cache_key != expected_cache_key {
        return Err("cached review key mismatch".into());
    }
    Ok(trace)
}

fn list_cached_reviewers(
    reviews_dir: &Path,
    replay_document_hash: &str,
    registry_reviewers: &[splendor_analysis::ReviewerEntryV1],
) -> Vec<String> {
    let mut available = Vec::new();
    if let Ok(entries) = fs::read_dir(reviews_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            for registered in registry_reviewers {
                let prefix = format!("{}-", registered.id);
                let Some(cache_and_suffix) = name.strip_prefix(&prefix) else {
                    continue;
                };
                let Some(cache_key) = cache_and_suffix.strip_suffix(".analysis.json") else {
                    continue;
                };
                if cache_key.len() == 64
                    && cache_key.bytes().all(|byte| byte.is_ascii_hexdigit())
                    && validate_cached_review_artifact(
                        &entry.path(),
                        cache_key,
                        &registered.id,
                        replay_document_hash,
                    )
                    .is_ok()
                    && !available.iter().any(|existing| existing == &registered.id)
                {
                    available.push(registered.id.clone());
                }
            }
        }
    }
    available
}

fn read_human_meta(path: &Path) -> Option<serde_json::Value> {
    let bytes = fs::read(path).ok()?;
    serde_json::from_slice::<serde_json::Value>(&bytes).ok()
}

fn spawn_review_job(
    shared: Arc<Mutex<ReviewJobState>>,
    replay: ReplayV1,
    reviewer: ReviewerIdentityV2,
    checkpoint: Option<PolicyValueCheckpointV1>,
    artifact_path: PathBuf,
) {
    std::thread::spawn(move || {
        {
            let mut state = shared.lock().expect("review job lock");
            state.status = ReviewJobStatus::Running;
        }
        let result = run_review(
            &replay,
            &reviewer,
            checkpoint.as_ref(),
            &artifact_path,
            &shared,
        );
        {
            let mut state = shared.lock().expect("review job lock");
            match result {
                Ok(()) => {
                    state.status = ReviewJobStatus::Completed;
                    state.processed_decisions = state.total_decisions;
                }
                Err(error) => {
                    state.status = ReviewJobStatus::Failed;
                    state.error = Some(error);
                }
            }
        }
    });
}

fn run_review(
    replay: &ReplayV1,
    reviewer: &ReviewerIdentityV2,
    checkpoint: Option<&PolicyValueCheckpointV1>,
    artifact_path: &Path,
    shared: &Arc<Mutex<ReviewJobState>>,
) -> Result<(), String> {
    let trace = {
        let mut progress = |processed: u32, total: u32, ply: u32| {
            if let Ok(mut state) = shared.lock() {
                state.processed_decisions = processed;
                state.total_decisions = total;
                state.current_ply = ply;
            }
        };
        match &reviewer.config {
            ReviewerConfigV2::RootDeterminization(_) => {
                analyze_replay_determinization_v2_with_progress(replay, reviewer, &mut progress)
                    .map_err(|error| error.to_string())?
            }
            ReviewerConfigV2::NeuralIsmcts(_) => {
                let checkpoint = checkpoint
                    .ok_or_else(|| "missing checkpoint for neural reviewer".to_string())?;
                analyze_replay_neural_v2_with_progress(replay, checkpoint, reviewer, &mut progress)
                    .map_err(|error| error.to_string())?
            }
            ReviewerConfigV2::PolicyRecommendation(_) => {
                analyze_replay_s3_v2_with_progress(replay, reviewer, &mut progress)
                    .map_err(|error| error.to_string())?
            }
        }
    };
    let mut json = serde_json::to_string_pretty(&trace)
        .map_err(|error| format!("serialize trace failed: {error}"))?;
    json.push('\n');
    if let Some(parent) = artifact_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create review directory: {error}"))?;
    }
    match crate::atomic_output::commit_single(artifact_path, &json) {
        Ok(()) => Ok(()),
        Err(_) if artifact_path.exists() => {
            let cache_key = review_cache_key_v2(&trace.replay_document_hash, &trace.reviewer)
                .map_err(|error| error.to_string())?;
            let existing = validate_cached_review_artifact(
                artifact_path,
                &cache_key,
                &trace.reviewer.id,
                &trace.replay_document_hash,
            )?;
            if existing == trace {
                Ok(())
            } else {
                Err("existing review artifact differs from generated trace".into())
            }
        }
        Err(error) => Err(error.to_string()),
    }
}

pub fn run_human_play_server(args: &[String]) -> i32 {
    if args == ["--help"] || args == ["-h"] {
        println!("{USAGE}");
        return 0;
    }
    match serve(args) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

fn serve(args: &[String]) -> Result<(), String> {
    let args = parse_args(args)?;
    let mut session = build_session(&args)?;
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, args.port))
        .map_err(|error| format!("cannot bind 127.0.0.1:{}: {error}", args.port))?;
    println!("human_play_server=http://127.0.0.1:{}", args.port);
    println!("opponent={}", session.opponent.label());
    for connection in listener.incoming() {
        let stream = connection.map_err(|error| error.to_string())?;
        if let Err(error) = prepare_connection(&stream) {
            eprintln!("request error: {error}");
            continue;
        }
        if let Err(error) = handle_session(stream, &mut session) {
            eprintln!("request error: {error}");
        }
    }
    Ok(())
}

fn build_session(args: &Args) -> Result<Session, String> {
    if let (None, Some(registry), Some(agent_id)) = (&args.opponent, &args.registry, &args.agent_id)
    {
        // Standalone registry games load once too, but never acquire rated authority.
        let selected = load_standalone_agent(registry, agent_id)?;
        return build_registered_session(
            args.seed,
            args.human_seat,
            &selected,
            args.move_timeout_ms,
            args.replay_out.clone(),
            None,
            None,
        );
    }
    let id = format!(
        "human-{}-{}-{}",
        args.seed,
        args.human_seat,
        std::process::id()
    );
    let config = GameConfig {
        player_count: 2,
        seed: args.seed,
        ..Default::default()
    };
    let (recorder, _setup) = ReplayRecorder::new_with_setup(config)
        .map_err(|error| format!("cannot create replay recorder: {error}"))?;
    let (opponent, opponent_rng_seed) = match (&args.opponent, &args.registry, &args.agent_id) {
        // Choice C product default: when no opponent is specified or "s3" is chosen,
        // use the strongest confirmed S3 rollout candidate as default with its exact
        // frozen root RNG stream seed (S3_ROOT_SEED = 20_260_812).
        (None, None, None) => (
            Opponent::InProcess {
                label: "S3 rollout default",
                policy: InProcessOpponent::S3(
                    splendor_determinization_agent::s3_agent::S3RolloutAgentPolicy::new()
                        .map_err(|error| error.to_string())?,
                ),
            },
            splendor_determinization_agent::s3_agent::S3_ROOT_SEED,
        ),
        (Some(name), None, None) if name == "s3" || name == "s3-rollout" || name == "default" => (
            Opponent::InProcess {
                label: "S3 rollout default",
                policy: InProcessOpponent::S3(
                    splendor_determinization_agent::s3_agent::S3RolloutAgentPolicy::new()
                        .map_err(|error| error.to_string())?,
                ),
            },
            splendor_determinization_agent::s3_agent::S3_ROOT_SEED,
        ),
        (Some(name), None, None) if name == "heuristic" || name == "fast" => (
            Opponent::InProcess {
                label: "Heuristic fast mode",
                policy: InProcessOpponent::Heuristic(HeuristicAgentPolicy::new()),
            },
            20_260_812, // Authoritative heuristic-v1 seed (identical to agent-heuristic --seed 20260812)
        ),
        (Some(name), None, None) if name == "m07" => (
            Opponent::InProcess {
                label: "M07 determinization champion",
                policy: InProcessOpponent::M07(
                    DeterminizationAgentPolicyV1::new(RootDeterminizationConfigV1 {
                        sample_seed: 20260810,
                        sample_count: 4,
                        continuation_search: SearchConfigV1 {
                            max_depth_turns: 1,
                            max_nodes: 2_000,
                        },
                    })
                    .map_err(|error| error.to_string())?,
                ),
            },
            args.seed ^ 0xa5a5_5a5a, // Preserves historical human-play M07 game-derived seed
        ),
        (Some(_), None, None) => {
            return Err(
                "--opponent must be s3 (or s3-rollout/default), heuristic (or fast), or m07".into(),
            )
        }
        _ => {
            return Err(
                "choose --opponent <s3|s3-rollout|default|heuristic|fast|m07> or --registry <path> --agent-id <id> (defaults to s3)"
                    .into(),
            )
        }
    };
    let replay_out = args.replay_out.clone().unwrap_or_else(|| {
        PathBuf::from("local-artifacts")
            .join("m20-human-play")
            .join(format!("{id}.replay.json"))
    });
    let mut session = Session {
        id,
        human_seat: PlayerId(args.human_seat),
        recorder: Some(recorder),
        terminal_state: None,
        replay: None,
        replay_hash: None,
        replay_out,
        rated: None,
        league_completion: None,
        frames: Vec::new(),
        opponent,
        opponent_rng: StableRng::new(opponent_rng_seed),
        request_id: 0,
        ply: 0,
    };
    session.advance_opponent()?;
    Ok(session)
}

fn load_standalone_agent(registry_path: &Path, agent_id: &str) -> Result<RatedAgentV1, String> {
    let bytes = fs::read(registry_path).map_err(|e| {
        format!(
            "cannot read rating registry {}: {e}",
            registry_path.display()
        )
    })?;
    let registry: RatingRegistryV1 =
        serde_json::from_slice(&bytes).map_err(|e| format!("invalid rating registry JSON: {e}"))?;
    registry.validate()?;
    registry
        .agents
        .into_iter()
        .find(|agent| agent.id == agent_id)
        .ok_or_else(|| format!("agent id `{agent_id}` is not in the rating registry"))
}

#[allow(clippy::too_many_arguments)]
fn build_registered_session(
    seed: u64,
    human_seat: u8,
    selected: &RatedAgentV1,
    move_timeout_ms: u64,
    replay_out: Option<PathBuf>,
    session_number: Option<u64>,
    rated: Option<HumanGameAuthority>,
) -> Result<Session, String> {
    let id = match session_number {
        Some(number) => format!("human-{seed}-{human_seat}-{}-{number}", std::process::id()),
        None => format!("human-{seed}-{human_seat}-{}", std::process::id()),
    };
    if let Some(authority) = &rated {
        let dir = authority
            .paths
            .occurrence_dir(&id)
            .map_err(|e| e.to_string())?;
        if human_occurrence_slot(&HumanOccurrenceEvidence::in_dir(&dir))
            != HumanOccurrenceSlot::Empty
        {
            return Err("human occurrence id already has evidence; no game was started".into());
        }
    }
    let (recorder, setup) = ReplayRecorder::new_with_setup(GameConfig {
        player_count: 2,
        seed,
        ..Default::default()
    })
    .map_err(|error| format!("cannot create replay recorder: {error}"))?;
    let opponent_seat = PlayerId(1 - human_seat);
    let opponent = Opponent::Registered(RegisteredOpponent::start(
        selected,
        opponent_seat,
        &id,
        seed,
        recorder.state(),
        &setup.events,
        move_timeout_ms,
    )?);
    let replay_out = replay_out.unwrap_or_else(|| {
        PathBuf::from("local-artifacts")
            .join("m20-human-play")
            .join(format!("{id}.replay.json"))
    });
    let mut session = Session {
        id,
        human_seat: PlayerId(human_seat),
        recorder: Some(recorder),
        terminal_state: None,
        replay: None,
        replay_hash: None,
        replay_out,
        rated,
        league_completion: None,
        frames: Vec::new(),
        opponent,
        opponent_rng: StableRng::new(seed ^ 0xa5a5_5a5a),
        request_id: 0,
        ply: 0,
    };
    session.advance_opponent()?;
    Ok(session)
}

fn serve_studio_host(args: &[String]) -> Result<(), String> {
    let args = parse_host_args(args)?;
    let bytes = fs::read(&args.registry).map_err(|error| {
        format!(
            "cannot read Studio registry {}: {error}",
            args.registry.display()
        )
    })?;
    let registry: RatingRegistryV1 = serde_json::from_slice(&bytes)
        .map_err(|error| format!("invalid Studio registry JSON: {error}"))?;
    registry.validate()?;
    let reviewer_bytes = fs::read(&args.reviewer_registry).map_err(|error| {
        format!(
            "cannot read reviewer registry {}: {error}",
            args.reviewer_registry.display()
        )
    })?;
    let reviewer_registry: ReviewerRegistryV1 = serde_json::from_slice(&reviewer_bytes)
        .map_err(|error| format!("invalid reviewer registry JSON: {error}"))?;
    reviewer_registry
        .validate()
        .map_err(|error| error.to_string())?;
    let experiment_library = match &args.replay_sources {
        Some(path) => Some(crate::experiment_replays::ExperimentReplayLibrary::load(
            path,
            Path::new("."),
        )?),
        None => None,
    };
    // The Studio League root is resolved exactly once, here, and the read-only
    // session is opened once from it. Everything the league routes answer comes
    // from this bundle; no handler re-derives a location from the cwd.
    let league_paths = StudioLeaguePathsV1::resolve(args.project_root.as_deref());
    let (league, league_error) = match open_studio_league_reader(&league_paths) {
        Ok(reader) => (Some(reader), None),
        Err(error) => (None, Some(error.to_string())),
    };
    match &league_error {
        None => println!("studio_league={}", league_paths.db().display()),
        Some(error) => eprintln!("studio_league unavailable: {error}"),
    }
    let mut host = StudioHost {
        league,
        league_error,
        paths: league_paths,
        registry,
        reviewer_registry,
        handshake_timeout_ms: args.handshake_timeout_ms,
        move_timeout_ms: args.move_timeout_ms,
        shutdown_grace_ms: args.shutdown_grace_ms,
        next_session_number: 1,
        session: None,
        jobs: ReviewJobManager::default(),
        experiment_library,
    };
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, args.port)).map_err(|error| {
        format!(
            "cannot bind Studio Host at 127.0.0.1:{}: {error}",
            args.port
        )
    })?;
    println!("studio_host=http://127.0.0.1:{}", args.port);
    for connection in listener.incoming() {
        let stream = connection.map_err(|error| error.to_string())?;
        if let Err(error) = prepare_connection(&stream) {
            eprintln!("Studio Host request error: {error}");
            continue;
        }
        if let Err(error) = handle_host(stream, &mut host) {
            eprintln!("Studio Host request error: {error}");
        }
    }
    Ok(())
}

struct HttpRequest {
    method: String,
    path: String,
    body: Vec<u8>,
}

/// The deadline every accepted HTTP connection runs under.
///
/// Both servers accept **serially**, and until this existed a socket had no read
/// deadline at all: a connection that opened and then sent nothing owned the whole
/// surface for as long as it stayed open. Measured on this Host, one idle TCP
/// connection — a browser's preconnect socket is enough, no malice required — left
/// `/health` and every read route unanswerable indefinitely, at ~0% CPU (so it did
/// not even look busy), and closing that socket restored service in milliseconds.
///
/// The bounds are deliberately generous for a loopback JSON API, because what they
/// have to buy is *finiteness*, not low latency: a stalled peer must cost seconds,
/// never the process.
const HTTP_READ_TIMEOUT: Duration = Duration::from_secs(2);
const HTTP_WRITE_TIMEOUT: Duration = Duration::from_secs(5);

/// Give one accepted connection its deadlines.
///
/// A timeout is deliberately *not* a service failure: the caller logs one request
/// error, drops the socket, and keeps accepting, which is why this returns an
/// error instead of tearing the loop down.
fn prepare_connection(stream: &TcpStream) -> Result<(), String> {
    stream
        .set_read_timeout(Some(HTTP_READ_TIMEOUT))
        .map_err(|error| format!("cannot set the request read deadline: {error}"))?;
    stream
        .set_write_timeout(Some(HTTP_WRITE_TIMEOUT))
        .map_err(|error| format!("cannot set the response write deadline: {error}"))?;
    Ok(())
}

fn read_request(stream: &TcpStream) -> Result<HttpRequest, String> {
    let mut reader = BufReader::new(stream.try_clone().map_err(|error| error.to_string())?);
    let mut request_line = String::new();
    reader
        .read_line(&mut request_line)
        .map_err(|error| error.to_string())?;
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("").to_string();
    let path = parts.next().unwrap_or("").to_string();
    let mut content_length = 0usize;
    loop {
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .map_err(|error| error.to_string())?;
        if line == "\r\n" || line.is_empty() {
            break;
        }
        if let Some(value) = line.to_ascii_lowercase().strip_prefix("content-length:") {
            content_length = value.trim().parse().map_err(|_| "invalid content length")?;
        }
    }
    if content_length > 64 * 1024 {
        return Err("request body exceeds 64 KiB".into());
    }
    let mut body = vec![0; content_length];
    reader
        .read_exact(&mut body)
        .map_err(|error| error.to_string())?;
    Ok(HttpRequest { method, path, body })
}

/// A Studio League read, with the three outcomes the HTTP layer must tell apart.
///
/// The existing routes answer 400 for every error, which is fine for a command
/// surface but wrong for a read API: "this match does not exist" is not a client
/// mistake. The league routes therefore carry their own small response type,
/// and the pre-existing routes are left byte-identical.
enum LeagueRead {
    Json(String),
    Document(Vec<u8>),
    NotFound(String),
    /// The request itself is malformed, so no retry of it can succeed. Distinct
    /// from `Unavailable` (the league cannot answer) and from `NotFound` (the
    /// league answered, and the answer is "no such resource").
    Invalid(String),
    Unavailable(String),
}

fn respond_league(stream: &mut TcpStream, read: LeagueRead) -> Result<(), String> {
    let error_body = |message: String| serde_json::json!({ "error": message }).to_string();
    match read {
        LeagueRead::Json(body) => respond(stream, 200, "application/json", &body),
        // `read_archived_replay` returns the archived document bytes verbatim.
        LeagueRead::Document(bytes) => match std::str::from_utf8(&bytes) {
            Ok(text) => respond(stream, 200, "application/json", text),
            Err(error) => respond(
                stream,
                503,
                "application/json",
                &error_body(format!("the archived document is not a JSON text: {error}")),
            ),
        },
        LeagueRead::NotFound(message) => {
            respond(stream, 404, "application/json", &error_body(message))
        }
        LeagueRead::Invalid(message) => {
            respond(stream, 400, "application/json", &error_body(message))
        }
        LeagueRead::Unavailable(message) => {
            respond(stream, 503, "application/json", &error_body(message))
        }
    }
}

impl StudioHost {
    /// The read-only league session, or the reason it is not open.
    fn league(&self) -> std::result::Result<&StudioLeagueReaderV1, String> {
        match (&self.league, &self.league_error) {
            (Some(reader), _) => Ok(reader),
            (None, Some(error)) => Err(error.clone()),
            (None, None) => Err("no Studio League reader is open".to_string()),
        }
    }

    /// The league table, straight from the ledger. Nothing is recomputed.
    fn league_leaderboard(&self) -> LeagueRead {
        let reader = match self.league() {
            Ok(reader) => reader,
            Err(error) => return LeagueRead::Unavailable(error),
        };
        match reader.leaderboard() {
            Ok(rows) => match serde_json::to_string(&serde_json::json!({
                "format": "effective-splendor-studio-league-leaderboard",
                "version": 1,
                "rows": rows,
            })) {
                Ok(body) => LeagueRead::Json(body),
                Err(error) => LeagueRead::Unavailable(error.to_string()),
            },
            Err(error) => LeagueRead::Unavailable(error.to_string()),
        }
    }

    /// One match, exactly as the ledger recorded it.
    fn league_match(&self, match_id: &str) -> LeagueRead {
        if match_id.is_empty() {
            return LeagueRead::NotFound("no match id in the request path".to_string());
        }
        let reader = match self.league() {
            Ok(reader) => reader,
            Err(error) => return LeagueRead::Unavailable(error),
        };
        match reader.match_detail(match_id) {
            Ok(Some(detail)) => match serde_json::to_string(&serde_json::json!({
                "format": "effective-splendor-studio-league-match",
                "version": 1,
                "match": detail,
            })) {
                Ok(body) => LeagueRead::Json(body),
                Err(error) => LeagueRead::Unavailable(error.to_string()),
            },
            Ok(None) => {
                LeagueRead::NotFound(format!("no match `{match_id}` is recorded in the ledger"))
            }
            Err(error) => LeagueRead::Unavailable(error.to_string()),
        }
    }

    /// One bounded page of the recorded matches, newest first.
    ///
    /// The Host is a presenter here: it parses the query string into the frozen
    /// request type, and the ledger clamps and orders. Nothing is sorted, filtered
    /// or counted in this process, so there is exactly one implementation of what
    /// "the games list" means.
    ///
    /// A malformed cursor or limit is the caller's mistake and answers `400`,
    /// because it can never become correct by retrying. An unreadable league
    /// remains `503`.
    fn league_games(&self, query: &str) -> LeagueRead {
        let limit = match query_param_optional(query, "limit") {
            Some(text) => match text.parse::<u32>() {
                Ok(value) => Some(value),
                Err(_) => {
                    return LeagueRead::Invalid(format!(
                        "the games limit must be a non-negative integer, got `{text}`"
                    ))
                }
            },
            None => None,
        };
        let before_league_seq = match query_param_optional(query, "before") {
            Some(text) => match text.parse::<i64>() {
                Ok(value) => Some(value),
                Err(_) => {
                    return LeagueRead::Invalid(format!(
                        "the games cursor must be an integer league_seq, got `{text}`"
                    ))
                }
            },
            None => None,
        };
        // An explicit but empty `participant_id` is a request for one participant
        // whose id is the empty string, which no participant has. Treating it as
        // "no filter" would answer a filtered question with the unfiltered list.
        let participant_id = match query_param_optional(query, "participant_id") {
            Some(text) if text.is_empty() => {
                return LeagueRead::Invalid(
                    "the participant_id filter must not be empty".to_string(),
                )
            }
            Some(text) => Some(text),
            None => None,
        };

        let request = LeagueMatchPageRequestV1 {
            limit,
            before_league_seq,
            participant_id,
        };
        let reader = match self.league() {
            Ok(reader) => reader,
            Err(error) => return LeagueRead::Unavailable(error),
        };
        match reader.league_match_page(&request) {
            Ok(page) => match serde_json::to_string(&serde_json::json!({
                "format": "effective-splendor-studio-league-games",
                "version": 1,
                "matches": page.matches,
                "next_before_league_seq": page.next_before_league_seq,
            })) {
                Ok(body) => LeagueRead::Json(body),
                Err(error) => LeagueRead::Unavailable(error.to_string()),
            },
            // A cursor the ledger refuses is a bad request, not a server fault, and
            // not an absent resource: retrying it unchanged can never succeed.
            Err(StudioLeagueError::Invalid(message)) => LeagueRead::Invalid(message),
            Err(error) => LeagueRead::Unavailable(error.to_string()),
        }
    }

    /// The archived ReplayV1 document for a content address.
    ///
    /// The client supplies a document SHA-256 and nothing else. A malformed or
    /// unknown address is an absent resource: `read_archived_replay` validates
    /// the shape first and locates the object by archive root plus content
    /// address, so there is no route through which a request can name a path.
    fn league_replay(&self, document_sha256: &str) -> LeagueRead {
        if document_sha256.is_empty() {
            return LeagueRead::NotFound("no document sha256 in the request path".to_string());
        }
        let reader = match self.league() {
            Ok(reader) => reader,
            Err(error) => return LeagueRead::Unavailable(error),
        };
        // The reader decides absence versus refusal. Ordering it here instead
        // would let a stale league be reported as "this replay does not exist":
        // `read_replay` fails on the authority evidence first, and a second
        // existence call would then answer `false` for an address that was never
        // archived, turning "this league cannot be trusted" into a 404.
        match reader.read_replay(document_sha256) {
            Ok(Some(bytes)) => LeagueRead::Document(bytes),
            Ok(None) => LeagueRead::NotFound(format!(
                "no archived replay at content address `{document_sha256}`"
            )),
            Err(error) => LeagueRead::Unavailable(error.to_string()),
        }
    }

    /// One archived match replay, rebuilt for the replay board.
    ///
    /// This is a **presentation adapter**, never a second authority. The document
    /// is obtained through `read_replay`, exactly like the raw league replay route
    /// above, so a stale league is refused here too and an unknown address is
    /// absent here too. Only behind that gate does the adapter deserialize the
    /// verified `ReplayV1` and rebuild the frame-by-frame archive the board
    /// renders. No file path is ever read directly: a path-based read would serve
    /// an archive with no authority attached to it.
    ///
    /// A league match is agent versus agent, so there is no human seat and no
    /// opponent label to attach. Both are stated as absent rather than guessed.
    fn league_replay_archive(&self, document_sha256: &str) -> LeagueRead {
        if document_sha256.is_empty() {
            return LeagueRead::NotFound("no document sha256 in the request path".to_string());
        }
        let reader = match self.league() {
            Ok(reader) => reader,
            Err(error) => return LeagueRead::Unavailable(error),
        };
        // The reader owns absence and refusal; the adapter only consumes its
        // answer, so "this league cannot be trusted" can never be reported as
        // "this replay does not exist".
        let bytes = match reader.read_replay(document_sha256) {
            Ok(Some(bytes)) => bytes,
            Ok(None) => {
                return LeagueRead::NotFound(format!(
                    "no archived replay at content address `{document_sha256}`"
                ))
            }
            Err(error) => return LeagueRead::Unavailable(error.to_string()),
        };
        let replay: ReplayV1 = match serde_json::from_slice(&bytes) {
            Ok(replay) => replay,
            Err(error) => {
                return LeagueRead::Unavailable(format!(
                    "the archived document is not a ReplayV1 replay: {error}"
                ))
            }
        };
        // The builder re-verifies the replay trace itself, so the frames the
        // board receives are reconstructed from a checked replay, not trusted
        // because they were found.
        match build_historical_replay_archive(&replay, document_sha256, None, None) {
            Ok(archive) => match serde_json::to_string(&archive) {
                Ok(body) => LeagueRead::Json(body),
                Err(error) => LeagueRead::Unavailable(error.to_string()),
            },
            Err(message) => LeagueRead::Unavailable(format!(
                "the archived replay cannot be rebuilt for the board: {message}"
            )),
        }
    }
}

/// One match to run and book, addressed by occurrence identity.
///
/// `seats` are **registry agent ids**. The body deliberately cannot express a
/// program, argv, an `AgentCommand` or an `ArenaConfig`: an unauthenticated POST
/// on `127.0.0.1` must never be able to name an executable, so the Host resolves
/// each id to the trusted command the registry already holds. The three timeouts
/// are Host settings for the same reason — a client cannot ask for a shorter or a
/// longer one. `deny_unknown_fields` is what makes "cannot express a program"
/// structural instead of a promise about the parser.
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct LeagueMatchRequest {
    occurrence_id: String,
    game_id: String,
    seed: u64,
    seats: Vec<String>,
}

/// The outcome of one league write, in the shape the HTTP layer must not conflate.
///
/// The two facts — what the match did, and what the league did with it — travel
/// separately all the way to the status line, because collapsing them is the
/// mistake this slice exists to prevent.
enum LeagueWrite {
    /// The occurrence is booked, or was already booked: `200`.
    Completed(Box<CompletionOutcomeV1>),
    /// The arena settled the match without a completed occurrence: `200`.
    Aborted { match_status: &'static str },
    /// The request is unusable, including an unsafe occurrence id: `400`.
    Invalid(String),
    /// The occurrence slot holds state that is neither empty nor complete: `409`.
    Conflict(String),
    /// The match completed and its evidence is intact, but completion failed:
    /// `503`. Retryable, and the retry will not re-run the match.
    CompletionFailed(String),
    /// The producer or the filesystem failed before a settled fact existed: `500`.
    Fault(String),
}

fn respond_league_write(stream: &mut TcpStream, write: LeagueWrite) -> Result<(), String> {
    let body = |value: serde_json::Value| value.to_string();
    match write {
        LeagueWrite::Completed(completion) => {
            let body = body(serde_json::json!({
                "format": "effective-splendor-studio-league-match-result",
                "version": 1,
                "match_status": "completed",
                "completion_status": match &completion.ingest {
                    IngestOutcome::Inserted { .. } => "inserted",
                    IngestOutcome::AlreadyPresent { .. } => "already_present",
                },
                "receipt": completion_receipt_json(&completion),
            }));
            respond(stream, 200, "application/json", &body)
        }
        // A settled, non-completed match is a normal outcome of asking for a
        // match, not an error and not a client mistake.
        LeagueWrite::Aborted { match_status } => {
            let body = body(serde_json::json!({
                "format": "effective-splendor-studio-league-match-result",
                "version": 1,
                "match_status": match_status,
                "completion_status": "not_applicable",
            }));
            respond(stream, 200, "application/json", &body)
        }
        LeagueWrite::CompletionFailed(message) => {
            let body = body(serde_json::json!({
                "format": "effective-splendor-studio-league-match-result",
                "version": 1,
                "match_status": "completed",
                "completion_status": "failed",
                "error": message,
            }));
            respond(stream, 503, "application/json", &body)
        }
        LeagueWrite::Invalid(message) => respond(
            stream,
            400,
            "application/json",
            &body(serde_json::json!({ "error": message })),
        ),
        LeagueWrite::Conflict(message) => respond(
            stream,
            409,
            "application/json",
            &body(serde_json::json!({ "error": message })),
        ),
        LeagueWrite::Fault(message) => respond(
            stream,
            500,
            "application/json",
            &body(serde_json::json!({ "error": message })),
        ),
    }
}

impl StudioHost {
    /// Run one match and book it, or report what the occurrence slot already holds.
    ///
    /// The order below is the contract, not an optimisation. Persisted evidence is
    /// consulted **before** the registry, because an occurrence id names a match
    /// that happened: re-offering it is a retry, and a retry must neither re-run
    /// the arena nor depend on the registry this process happens to hold now.
    fn run_league_match(&mut self, request: LeagueMatchRequest) -> LeagueWrite {
        let write = self.run_league_match_once(request);
        if matches!(write, LeagueWrite::Completed(_)) {
            // A booking is what can make a league readable for the first time: the
            // completion is what writes the stored rating protocol identity and the
            // durable identity hash that a read session validates. The session is
            // opened once at startup, so a Host that started on a fresh league would
            // otherwise keep answering 503 until it was restarted — and the write
            // route is precisely the initialisation flow that resolves that state.
            // A refresh failure is recorded for the read routes and never
            // reinterprets a booking that already succeeded.
            self.reopen_read_session_if_unavailable();
        }
        write
    }

    /// Open the read session once a booking may have made one possible.
    fn reopen_read_session_if_unavailable(&mut self) {
        if self.league.is_some() {
            return;
        }
        match open_studio_league_reader(&self.paths) {
            Ok(reader) => {
                self.league = Some(reader);
                self.league_error = None;
            }
            Err(error) => self.league_error = Some(error.to_string()),
        }
    }

    fn run_league_match_once(&mut self, request: LeagueMatchRequest) -> LeagueWrite {
        // The id becomes a path component only after the one composer has
        // validated it, and nothing is created, read or run before that.
        let dir = match self.paths.occurrence_dir(&request.occurrence_id) {
            Ok(dir) => dir,
            Err(error) => return LeagueWrite::Invalid(error.to_string()),
        };
        let evidence = OccurrenceEvidence::in_dir(&dir);

        match occurrence_slot(&evidence) {
            // Already complete: complete it from the documents on disk, and never
            // resolve a seat or run a match. This is what makes a retry survive a
            // Host restart with a changed registry, timeout or agent build.
            OccurrenceSlotV1::Complete => {
                return match complete_persisted_occurrence(
                    &evidence,
                    &self.paths,
                    Some(&request.occurrence_id),
                ) {
                    Ok(completion) => LeagueWrite::Completed(Box::new(completion)),
                    Err(RuntimeOrchestrationError::Failed(message)) => {
                        LeagueWrite::CompletionFailed(message)
                    }
                    Err(other) => LeagueWrite::Conflict(other.to_string()),
                };
            }
            // Already settled without completing: report the recorded fact.
            OccurrenceSlotV1::SettledWithoutCompletion { match_status } => {
                return LeagueWrite::Aborted { match_status };
            }
            // Neither empty nor complete: running here would either overwrite
            // evidence or book a second match for one occurrence.
            OccurrenceSlotV1::Ambiguous(why) => return LeagueWrite::Conflict(why),
            OccurrenceSlotV1::Empty => {}
        }

        // A fresh occurrence. Only now is the registry consulted, and only to turn
        // agent ids into trusted commands.
        let config = match self.build_league_match_config(&request) {
            Ok(config) => config,
            Err(message) => return LeagueWrite::Invalid(message),
        };
        let config_bytes = match serde_json::to_vec(&config) {
            Ok(bytes) => bytes,
            Err(error) => {
                return LeagueWrite::Fault(format!("cannot serialize the arena config: {error}"))
            }
        };
        if let Err(error) = fs::create_dir_all(&dir) {
            return LeagueWrite::Fault(format!(
                "cannot create the occurrence slot {}: {error}",
                dir.display()
            ));
        }

        let occurrence_id = request.occurrence_id.clone();
        match produce_and_complete(&evidence, &config_bytes, &occurrence_id, &self.paths) {
            Ok(RuntimeOrchestrationOutcome::Completed { completion, .. }) => {
                LeagueWrite::Completed(completion)
            }
            Ok(RuntimeOrchestrationOutcome::CompletionFailed { message, .. }) => {
                LeagueWrite::CompletionFailed(message)
            }
            Ok(RuntimeOrchestrationOutcome::Aborted { match_status, .. }) => {
                LeagueWrite::Aborted { match_status }
            }
            Err(RuntimeOrchestrationError::Invalid(message)) => LeagueWrite::Invalid(message),
            Err(RuntimeOrchestrationError::Conflict(message)) => LeagueWrite::Conflict(message),
            Err(RuntimeOrchestrationError::Failed(message)) => LeagueWrite::Fault(message),
        }
    }

    /// Turn registry agent ids into the arena configuration this Host will run.
    ///
    /// The commands come from `self.registry`; the request contributes ids, the
    /// two plain match parameters, and nothing else that can be executed or
    /// resolved. `ArenaConfig::validate()` stays authoritative for the seat count
    /// and every other arena invariant, so there is exactly one definition of a
    /// runnable configuration — the arena's.
    fn build_league_match_config(
        &self,
        request: &LeagueMatchRequest,
    ) -> Result<ArenaConfig, String> {
        let mut agents = Vec::with_capacity(request.seats.len());
        for id in &request.seats {
            let agent = self
                .registry
                .agents
                .iter()
                .find(|agent| &agent.id == id)
                .ok_or_else(|| format!("agent id `{id}` is not in the Studio registry"))?;
            agents.push(agent.command.clone());
        }
        let config = ArenaConfig {
            game_id: request.game_id.clone(),
            seed: request.seed,
            handshake_timeout_ms: self.handshake_timeout_ms,
            move_timeout_ms: self.move_timeout_ms,
            shutdown_grace_ms: self.shutdown_grace_ms,
            agents,
        };
        config.validate().map_err(|error| error.to_string())?;
        Ok(config)
    }
}

fn handle_host(mut stream: TcpStream, host: &mut StudioHost) -> Result<(), String> {
    let request = read_request(&stream)?;
    if request.method == "OPTIONS" {
        return respond(&mut stream, 204, "application/json", "");
    }

    match request.method.as_str() {
        "GET" if request.path == "/reviewers" || request.path.starts_with("/reviewers?") => {
            let session = query_param(&request.path, "session");
            return respond_result(&mut stream, host.reviewers_json(session.as_deref()));
        }
        "GET" if request.path == "/recent-games" => {
            return respond_result(&mut stream, host.recent_games());
        }
        // ---- Studio League, read-only (Commit D Slice 1). --------------------
        // These four are the read surface. The one write route follows them.
        "GET" if request.path == "/league/leaderboard" => {
            return respond_league(&mut stream, host.league_leaderboard());
        }
        // The bounded games list. Matched by exact path, or by the path and its
        // query string: `/league/games` is not a prefix of any other league route,
        // and `/league/matches/` is, so this arm cannot shadow it.
        "GET" if request.path == "/league/games" || request.path.starts_with("/league/games?") => {
            let query = request.path["/league/games".len()..].to_string();
            return respond_league(&mut stream, host.league_games(&query));
        }
        "GET" if request.path.starts_with("/league/matches/") => {
            let match_id = request.path["/league/matches/".len()..].to_string();
            return respond_league(&mut stream, host.league_match(&match_id));
        }
        // The presentation adapter must be matched before the bare prefix below,
        // which would otherwise read `"<sha256>/archive"` as a content address.
        //
        // Parsed by stripping, never by index arithmetic. `/league/replays/archive`
        // satisfies both tests above, and `path[16..15]` is an inverted byte range:
        // it panics on the `main` thread (reproduced: `begin <= end (16 <= 15)`),
        // which ends the process, because this Host has a serial accept loop and no
        // per-request panic isolation. `unwrap_or_default` is therefore not an
        // oversight: it is where that malformed path lands, as the empty content
        // address, and the handler answers 404 for it.
        "GET"
            if request.path.starts_with("/league/replays/")
                && request.path.ends_with("/archive") =>
        {
            let sha256 = request
                .path
                .strip_prefix("/league/replays/")
                .and_then(|rest| rest.strip_suffix("/archive"))
                .unwrap_or_default()
                .to_string();
            return respond_league(&mut stream, host.league_replay_archive(&sha256));
        }
        "GET" if request.path.starts_with("/league/replays/") => {
            let sha256 = request.path["/league/replays/".len()..].to_string();
            return respond_league(&mut stream, host.league_replay(&sha256));
        }
        // ---- Studio League, one write entry (Commit E Slice 1). --------------
        // A single write route, and a retry is the same request again. The Host
        // never reimplements completion: it delegates to the shared producer.
        "POST" if request.path == "/league/matches" => {
            let parsed: Result<LeagueMatchRequest, String> = serde_json::from_slice(&request.body)
                .map_err(|error| format!("invalid match JSON: {error}"));
            let write = match parsed {
                Ok(request) => host.run_league_match(request),
                Err(message) => LeagueWrite::Invalid(message),
            };
            return respond_league_write(&mut stream, write);
        }
        "POST"
            if request.path.starts_with("/games/")
                && request.path.ends_with("/league-completion") =>
        {
            let session_id = request
                .path
                .strip_prefix("/games/")
                .and_then(|rest| rest.strip_suffix("/league-completion"))
                .unwrap_or_default();
            let (code, body) = host.retry_human_completion(session_id, &request.body);
            return respond(&mut stream, code, "application/json", &body.to_string());
        }
        "GET" if request.path.starts_with("/replays/") => {
            let session_id = &request.path["/replays/".len()..];
            return respond_result(&mut stream, host.historical_replay(session_id));
        }
        "GET" if request.path == "/experiment-replays" => {
            return respond_result(&mut stream, host.experiment_replays_index());
        }
        "GET" if request.path.starts_with("/experiment-replays/") => {
            // /experiment-replays/{experiment}/pairings/{pairing}/matches[/{index}/bundle]
            let rest = &request.path["/experiment-replays/".len()..];
            let segments: Vec<&str> = rest.split('/').collect();
            match (segments.as_slice(), rest.strip_suffix("/bundle")) {
                ([_experiment, "pairings", _pairing, "matches", index, "bundle"], _) => {
                    let index: u32 = index
                        .parse()
                        .map_err(|_| format!("invalid match index `{index}`"))?;
                    return respond_result(
                        &mut stream,
                        host.experiment_replays_bundle(segments[0], segments[2], index),
                    );
                }
                (_, Some(bundle_path)) => {
                    // Handles the /bundle suffix case in one string.
                    let parts: Vec<&str> = bundle_path.split('/').collect();
                    if parts.len() == 5 && parts[1] == "pairings" && parts[3] == "matches" {
                        let index: u32 = parts[4]
                            .parse()
                            .map_err(|_| format!("invalid match index `{}`", parts[4]))?;
                        return respond_result(
                            &mut stream,
                            host.experiment_replays_bundle(parts[0], parts[2], index),
                        );
                    }
                    return respond(
                        &mut stream,
                        404,
                        "application/json",
                        "{\"error\":\"not found\"}",
                    );
                }
                ([experiment, "pairings", pairing, "matches"], _) => {
                    return respond_result(
                        &mut stream,
                        host.experiment_replays_pairing(experiment, pairing),
                    );
                }
                _ => {
                    return respond(
                        &mut stream,
                        404,
                        "application/json",
                        "{\"error\":\"not found\"}",
                    );
                }
            }
        }
        "GET" if request.path.starts_with("/reviews/") => {
            let rest = &request.path["/reviews/".len()..];
            if let Some(bare) = rest.strip_suffix("/bundle") {
                return respond_result(&mut stream, host.review_bundle(bare));
            }
            return respond_result(&mut stream, host.review_status(rest));
        }
        "POST" if request.path == "/reviews" => {
            let value: Result<ReviewRequest, String> = serde_json::from_slice(&request.body)
                .map_err(|error| format!("invalid review JSON: {error}"));
            let result = value.and_then(|request| host.create_review(request));
            return respond_result(&mut stream, result);
        }
        _ => {}
    }

    let result: Result<String, String> = match (request.method.as_str(), request.path.as_str()) {
        ("GET", "/health") => Ok("{\"status\":\"ok\",\"mode\":\"studio_host\"}".into()),
        ("GET", "/agents") => host.agents_json(),
        ("GET", "/catalog") => serde_json::to_string(&public_catalog()).map_err(|e| e.to_string()),
        ("GET", "/state") => host
            .session
            .as_ref()
            .ok_or_else(|| "no active game; create one with POST /games".to_string())
            .and_then(|session| {
                serde_json::to_string(&session.snapshot()).map_err(|e| e.to_string())
            }),
        ("POST", "/games") => serde_json::from_slice::<NewGameRequest>(&request.body)
            .map_err(|error| format!("invalid new-game JSON: {error}"))
            .and_then(|value| host.new_game(value))
            .and_then(|state| serde_json::to_string(&state).map_err(|e| e.to_string())),
        ("POST", "/action") => {
            let result = host
                .session
                .as_mut()
                .ok_or_else(|| "no active game".to_string())
                .and_then(|session| {
                    serde_json::from_slice::<Action>(&request.body)
                        .map_err(|error| format!("invalid action JSON: {error}"))
                        .and_then(|action| session.human_action(action))
                        .and_then(|()| {
                            serde_json::to_string(&session.snapshot()).map_err(|e| e.to_string())
                        })
                });
            if host
                .session
                .as_ref()
                .and_then(|s| s.league_completion.as_ref())
                .is_some_and(|c| c.status != "failed")
            {
                host.reopen_read_session_if_unavailable();
            }
            result
        }
        ("GET", "/archive") => host
            .session
            .as_ref()
            .ok_or_else(|| "no active game".to_string())
            .and_then(Session::archive)
            .and_then(|archive| serde_json::to_string(&archive).map_err(|e| e.to_string())),
        _ => {
            return respond(
                &mut stream,
                404,
                "application/json",
                "{\"error\":\"not found\"}",
            )
        }
    };
    respond_result(&mut stream, result)
}

fn handle_session(mut stream: TcpStream, session: &mut Session) -> Result<(), String> {
    let request = read_request(&stream)?;
    if request.method == "OPTIONS" {
        return respond(&mut stream, 204, "application/json", "");
    }
    let result: Result<String, String> = match (request.method.as_str(), request.path.as_str()) {
        ("GET", "/state") => serde_json::to_string(&session.snapshot()).map_err(|e| e.to_string()),
        ("POST", "/action") => serde_json::from_slice::<Action>(&request.body)
            .map_err(|error| format!("invalid action JSON: {error}"))
            .and_then(|action| session.human_action(action))
            .and_then(|()| serde_json::to_string(&session.snapshot()).map_err(|e| e.to_string())),
        ("GET", "/archive") => session
            .archive()
            .and_then(|archive| serde_json::to_string(&archive).map_err(|e| e.to_string())),
        ("GET", "/health") => Ok("{\"status\":\"ok\"}".into()),
        _ => {
            return respond(
                &mut stream,
                404,
                "application/json",
                "{\"error\":\"not found\"}",
            )
        }
    };
    respond_result(&mut stream, result)
}

fn respond_result(stream: &mut TcpStream, result: Result<String, String>) -> Result<(), String> {
    match result {
        Ok(body) => respond(stream, 200, "application/json", &body),
        Err(error) => respond(
            stream,
            400,
            "application/json",
            &serde_json::json!({"error": error}).to_string(),
        ),
    }
}

fn respond(
    stream: &mut TcpStream,
    status: u16,
    content_type: &str,
    body: &str,
) -> Result<(), String> {
    let reason = match status {
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        404 => "Not Found",
        409 => "Conflict",
        500 => "Internal Server Error",
        503 => "Service Unavailable",
        _ => "Not Found",
    };
    write!(stream, "HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nAccess-Control-Allow-Origin: http://127.0.0.1:4173\r\nAccess-Control-Allow-Methods: GET, POST, OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type\r\nConnection: close\r\n\r\n{body}", body.len()).map_err(|error| error.to_string())
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut seed = None;
    let mut seat = None;
    let mut opponent = None;
    let mut registry = None;
    let mut agent_id = None;
    let mut port = None;
    let mut move_timeout_ms = None;
    let mut replay_out = None;
    let mut index = 0;
    while index < args.len() {
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("missing value for `{}`; {USAGE}", args[index]))?
            .clone();
        match args[index].as_str() {
            "--seed" => set_once(&mut seed, value, "--seed")?,
            "--human-seat" => set_once(&mut seat, value, "--human-seat")?,
            "--opponent" => set_once(&mut opponent, value, "--opponent")?,
            "--registry" => set_once(&mut registry, PathBuf::from(value), "--registry")?,
            "--agent-id" => set_once(&mut agent_id, value, "--agent-id")?,
            "--port" => set_once(&mut port, value, "--port")?,
            "--move-timeout-ms" => set_once(&mut move_timeout_ms, value, "--move-timeout-ms")?,
            "--replay-out" => set_once(&mut replay_out, PathBuf::from(value), "--replay-out")?,
            other => return Err(format!("unknown argument `{other}`; {USAGE}")),
        }
        index += 2;
    }
    let seed = seed
        .ok_or("missing --seed")?
        .parse()
        .map_err(|_| "--seed must be u64")?;
    let human_seat: u8 = seat
        .ok_or("missing --human-seat")?
        .parse()
        .map_err(|_| "--human-seat must be 0 or 1")?;
    if human_seat > 1 {
        return Err("--human-seat must be 0 or 1".into());
    }
    let port: u16 = port
        .ok_or("missing --port")?
        .parse()
        .map_err(|_| "--port must be u16")?;
    if port == 0 {
        return Err("--port must be nonzero".into());
    }
    let move_timeout_ms = move_timeout_ms
        .unwrap_or_else(|| DEFAULT_MOVE_TIMEOUT_MS.to_string())
        .parse::<u64>()
        .map_err(|_| "--move-timeout-ms must be u64")?;
    if move_timeout_ms == 0 || move_timeout_ms > 24 * 60 * 60 * 1_000 {
        return Err("--move-timeout-ms must be in 1..=86400000".into());
    }
    Ok(Args {
        seed,
        human_seat,
        opponent,
        registry,
        agent_id,
        port,
        move_timeout_ms,
        replay_out,
    })
}

/// Parse one Host-owned timeout, applying its Studio Host default and the arena's
/// own ceiling. The three timeouts differ only in their default and their flag
/// name, so they share one rule instead of three copies of it.
fn parse_host_timeout(raw: Option<String>, default: u64, flag: &str) -> Result<u64, String> {
    let value = raw
        .unwrap_or_else(|| default.to_string())
        .parse::<u64>()
        .map_err(|_| format!("{flag} must be u64"))?;
    if value == 0 || value > MAX_TIMEOUT_MS {
        return Err(format!("{flag} must be in 1..={}", MAX_TIMEOUT_MS));
    }
    Ok(value)
}

fn parse_host_args(args: &[String]) -> Result<HostArgs, String> {
    let mut registry = None;
    let mut reviewer_registry = None;
    let mut port = None;
    let mut handshake_timeout_ms = None;
    let mut move_timeout_ms = None;
    let mut shutdown_grace_ms = None;
    let mut replay_sources = None;
    let mut project_root = None;
    let mut index = 0;
    while index < args.len() {
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("missing value for `{}`; {HOST_USAGE}", args[index]))?
            .clone();
        match args[index].as_str() {
            "--registry" => set_once(&mut registry, PathBuf::from(value), "--registry")?,
            "--reviewer-registry" => set_once(
                &mut reviewer_registry,
                PathBuf::from(value),
                "--reviewer-registry",
            )?,
            "--port" => set_once(&mut port, value, "--port")?,
            "--handshake-timeout-ms" => {
                set_once(&mut handshake_timeout_ms, value, "--handshake-timeout-ms")?
            }
            "--move-timeout-ms" => set_once(&mut move_timeout_ms, value, "--move-timeout-ms")?,
            "--shutdown-grace-ms" => {
                set_once(&mut shutdown_grace_ms, value, "--shutdown-grace-ms")?
            }
            "--replay-sources" => set_once(
                &mut replay_sources,
                PathBuf::from(value),
                "--replay-sources",
            )?,
            "--project-root" => {
                set_once(&mut project_root, PathBuf::from(value), "--project-root")?
            }
            other => return Err(format!("unknown argument `{other}`; {HOST_USAGE}")),
        }
        index += 2;
    }
    let port = port
        .ok_or("missing --port")?
        .parse::<u16>()
        .map_err(|_| "--port must be u16")?;
    if port == 0 {
        return Err("--port must be nonzero".into());
    }
    let handshake_timeout_ms = parse_host_timeout(
        handshake_timeout_ms,
        DEFAULT_HANDSHAKE_TIMEOUT_MS,
        "--handshake-timeout-ms",
    )?;
    let move_timeout_ms = parse_host_timeout(
        move_timeout_ms,
        DEFAULT_MOVE_TIMEOUT_MS,
        "--move-timeout-ms",
    )?;
    let shutdown_grace_ms = parse_host_timeout(
        shutdown_grace_ms,
        DEFAULT_SHUTDOWN_GRACE_MS,
        "--shutdown-grace-ms",
    )?;
    Ok(HostArgs {
        registry: registry.ok_or("missing --registry")?,
        reviewer_registry: reviewer_registry
            .unwrap_or_else(|| PathBuf::from("benchmarks/studio-reviewers.registry.json")),
        port,
        handshake_timeout_ms,
        move_timeout_ms,
        shutdown_grace_ms,
        replay_sources,
        project_root,
    })
}

fn set_once<T>(slot: &mut Option<T>, value: T, name: &str) -> Result<(), String> {
    if slot.is_some() {
        return Err(format!("duplicate argument `{name}`"));
    }
    *slot = Some(value);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_session() -> Session {
        let recorder = ReplayRecorder::new(GameConfig {
            player_count: 2,
            seed: 20,
            ..Default::default()
        })
        .unwrap();
        Session {
            id: "test".into(),
            human_seat: PlayerId(0),
            recorder: Some(recorder),
            terminal_state: None,
            replay: None,
            replay_hash: None,
            replay_out: PathBuf::from("unused-test-replay.json"),
            rated: None,
            league_completion: None,
            frames: Vec::new(),
            opponent: Opponent::InProcess {
                label: "Heuristic baseline",
                policy: InProcessOpponent::Heuristic(HeuristicAgentPolicy::new()),
            },
            opponent_rng: StableRng::new(1),
            request_id: 0,
            ply: 0,
        }
    }

    #[test]
    fn session_exposes_only_human_observation_and_legal_actions() {
        let session = test_session();
        let json = serde_json::to_string(&session.snapshot()).unwrap();
        assert!(json.contains("observation"));
        assert!(json.contains("legal_actions"));
        assert!(!json.contains("decks"));
        let value = serde_json::to_value(session.snapshot()).unwrap();
        assert_eq!(value["seed"], "20");
        assert!(!value["observation"].to_string().contains("seed\""));
        assert!(!value["action_history"].to_string().contains("seed\""));
    }

    #[test]
    fn snapshot_history_contains_only_semantic_actions() {
        let mut session = test_session();
        let action = session
            .state()
            .legal_actions()
            .into_iter()
            .find(|action| matches!(action, Action::TakeTokens { .. }))
            .unwrap();
        session.apply_recorded(PlayerId(0), action).unwrap();
        let value = serde_json::to_value(session.snapshot()).unwrap();
        assert_eq!(value["action_history"][0]["ply"], 0);
        assert_eq!(value["action_history"][0]["actor"], 0);
        assert_eq!(value["action_history"][0]["action"]["type"], "take_tokens");
        let json = value.to_string();
        assert!(!json.contains("decks"));
        assert_eq!(value["seed"], "20");
        assert!(!value["observation"].to_string().contains("seed\""));
        assert!(!value["action_history"].to_string().contains("seed\""));
    }

    #[test]
    fn archive_is_unavailable_before_terminal() {
        assert_eq!(
            test_session().archive().unwrap_err(),
            "replay is available only after game completion"
        );
    }

    #[test]
    fn human_play_opponent_aliases_map_to_expected_policies() {
        // Verify all accepted aliases resolve to correct in-process opponent labels
        for alias in &["s3", "s3-rollout", "default"] {
            let session = build_session(&Args {
                seed: 10,
                human_seat: 0,
                opponent: Some((*alias).to_string()),
                registry: None,
                agent_id: None,
                port: 43125,
                move_timeout_ms: 10_000,
                replay_out: None,
            })
            .unwrap();
            assert_eq!(session.opponent.label(), "S3 rollout default");
        }

        for alias in &["heuristic", "fast"] {
            let session = build_session(&Args {
                seed: 10,
                human_seat: 0,
                opponent: Some((*alias).to_string()),
                registry: None,
                agent_id: None,
                port: 43126,
                move_timeout_ms: 10_000,
                replay_out: None,
            })
            .unwrap();
            assert_eq!(session.opponent.label(), "Heuristic fast mode");
        }

        let session_m07 = build_session(&Args {
            seed: 10,
            human_seat: 0,
            opponent: Some("m07".to_string()),
            registry: None,
            agent_id: None,
            port: 43127,
            move_timeout_ms: 10_000,
            replay_out: None,
        })
        .unwrap();
        assert_eq!(session_m07.opponent.label(), "M07 determinization champion");

        // No opponent flag -> defaults to S3 rollout
        let session_none = build_session(&Args {
            seed: 10,
            human_seat: 0,
            opponent: None,
            registry: None,
            agent_id: None,
            port: 43128,
            move_timeout_ms: 10_000,
            replay_out: None,
        })
        .unwrap();
        assert_eq!(session_none.opponent.label(), "S3 rollout default");
    }

    #[test]
    fn registered_agent_arguments_are_exclusive() {
        let error = parse_args(&[
            "--seed".into(),
            "1".into(),
            "--human-seat".into(),
            "0".into(),
            "--opponent".into(),
            "m07".into(),
            "--registry".into(),
            "r.json".into(),
            "--agent-id".into(),
            "a".into(),
            "--port".into(),
            "43120".into(),
        ])
        .and_then(
            |args| match (&args.opponent, &args.registry, &args.agent_id) {
                (Some(_), None, None) | (None, Some(_), Some(_)) => Ok(args),
                _ => Err("invalid opponent selection".into()),
            },
        )
        .unwrap_err();
        assert_eq!(error, "invalid opponent selection");
    }

    #[test]
    fn studio_host_requires_registry_and_port() {
        let parsed = parse_host_args(&[
            "--registry".into(),
            "registry.json".into(),
            "--port".into(),
            "43120".into(),
        ])
        .unwrap();
        assert_eq!(parsed.registry, PathBuf::from("registry.json"));
        assert_eq!(parsed.port, 43120);
        assert_eq!(parsed.move_timeout_ms, DEFAULT_MOVE_TIMEOUT_MS);
    }

    #[test]
    fn studio_agent_discovery_hides_commands_and_local_paths() {
        let registry: RatingRegistryV1 = serde_json::from_value(serde_json::json!({
            "format": "effective-splendor-rating-registry",
            "version": 1,
            "registry_id": "test-registry",
            "agents": [{
                "id": "gpu-agent",
                "display_name": "GPU Agent",
                "class": "checkpoint",
                "policy_version": "gpu-policy-v1",
                "model_version": "gpu-model-v1",
                "checkpoint_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "runtime_name": "gpu-runtime",
                "runtime_version": "1",
                "command": {
                    "program": "python",
                    "args": ["agent.py", "--checkpoint", "private/checkpoint.pt"]
                }
            }]
        }))
        .unwrap();
        let host = StudioHost {
            // This unit test exercises the agents JSON only; no league is opened.
            league: None,
            league_error: None,
            paths: StudioLeaguePathsV1::resolve(None),
            registry,
            reviewer_registry: test_reviewer_registry(),
            handshake_timeout_ms: DEFAULT_HANDSHAKE_TIMEOUT_MS,
            move_timeout_ms: DEFAULT_MOVE_TIMEOUT_MS,
            shutdown_grace_ms: DEFAULT_SHUTDOWN_GRACE_MS,
            next_session_number: 1,
            session: None,
            jobs: ReviewJobManager::default(),
            experiment_library: None,
        };
        let value: serde_json::Value = serde_json::from_str(&host.agents_json().unwrap()).unwrap();
        assert_eq!(value["agents"][0]["id"], "gpu-agent");
        assert_eq!(value["agents"][0]["model_version"], "gpu-model-v1");
        let json = value.to_string();
        assert!(!json.contains("command"));
        assert!(!json.contains("python"));
        assert!(!json.contains("private/checkpoint.pt"));
        assert!(!json.contains("private/registry.json"));
    }

    #[test]
    fn public_catalog_contains_the_canonical_visible_components() {
        let catalog = public_catalog();
        assert_eq!(catalog.cards.len(), 90);
        assert_eq!(catalog.nobles.len(), 10);
        assert_eq!(catalog.cards[0].id, CardId(0));
        assert!(catalog.cards.iter().all(|card| card.cost.len() == 5));
    }

    #[test]
    fn human_play_default_s3_and_fast_heuristic_bind_exact_production_rng_stream() {
        use splendor_agent::heuristic_term_scores;
        use splendor_determinization_agent::s3_agent::{S3RolloutAgentPolicy, S3_ROOT_SEED};
        use splendor_search::canonical_order;

        // Construct sessions with arbitrary game seeds (e.g. 42, 9999).
        // Before the P1 repair, in-process opponent_rng was initialized with
        // `args.seed ^ 0xa5a5_5a5a`. With the repair, S3 (default) and Fast
        // (heuristic) must bind EXACTLY S3_ROOT_SEED (20_260_812), identical to
        // production standalone `agent-s3-rollout` and `agent-heuristic --seed 20260812`.
        let args_default = Args {
            seed: 42,
            human_seat: 1,
            opponent: None,
            registry: None,
            agent_id: None,
            port: 43120,
            move_timeout_ms: 10_000,
            replay_out: None,
        };
        let session_default = build_session(&args_default).unwrap();
        assert_eq!(session_default.opponent.label(), "S3 rollout default");

        let args_fast = Args {
            seed: 42,
            human_seat: 1,
            opponent: Some("fast".into()),
            registry: None,
            agent_id: None,
            port: 43120,
            move_timeout_ms: 10_000,
            replay_out: None,
        };
        let session_fast = build_session(&args_fast).unwrap();
        assert_eq!(session_fast.opponent.label(), "Heuristic fast mode");

        // 1. Same-seed live game first-action parity:
        // On seed 42 with human_seat = 1, opponent is Player 0 and acts on ply 0.
        // The action chosen by session_default must exactly match standalone S3.
        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 42,
            ..Default::default()
        })
        .unwrap();
        let obs = state.observation(PlayerId(0));
        let history = visible_events(&setup.events, Audience::Player(PlayerId(0)));
        let legal = canonical_order(&state.legal_actions());
        let meta = PublicRequestMeta {
            game_id: "parity-check".into(),
            recipient_seat: PlayerId(0),
            request_id: 1,
            observation_hash: observation_hash(&obs),
        };

        let mut standalone_s3 = S3RolloutAgentPolicy::new().unwrap();
        let mut standalone_s3_rng = StableRng::new(S3_ROOT_SEED);
        let standalone_first_action = standalone_s3
            .choose_action(DecisionContext {
                observation: obs.clone(),
                visible_history: &history,
                legal_actions: &legal,
                meta: meta.clone(),
                rng: &mut standalone_s3_rng,
            })
            .unwrap();

        assert_eq!(
            session_default.frames[0].recorded_action, standalone_first_action,
            "session default S3 first action must equal standalone S3"
        );

        // 2. Multi-step consecutive root-tie decision sequence:
        // Find actions that produce exact score ties under heuristic scoring.
        let all_scores: Vec<i64> = heuristic_term_scores(&obs, &legal)
            .into_iter()
            .map(|t| t.total())
            .collect();
        // Group legal actions by score to form tie sets of size >= 2
        let mut score_to_actions: std::collections::HashMap<i64, Vec<Action>> =
            std::collections::HashMap::new();
        for (idx, score) in all_scores.iter().enumerate() {
            score_to_actions.entry(*score).or_default().push(legal[idx]);
        }
        let tie_sets: Vec<Vec<Action>> = score_to_actions
            .into_values()
            .filter(|acts| acts.len() >= 2)
            .collect();
        assert!(
            tie_sets.len() >= 3,
            "must have at least 3 distinct tie sets for multi-step sequence"
        );

        // Test at least 3 consecutive tie decisions for S3 (human-play default vs standalone)
        let mut s3_live = S3RolloutAgentPolicy::new().unwrap();
        let mut s3_live_rng = StableRng::new(S3_ROOT_SEED);
        let mut hp_s3_session = build_session(&Args {
            seed: 9999, // arbitrary seed: must NOT affect S3 root RNG
            human_seat: 0,
            opponent: Some("s3".into()),
            registry: None,
            agent_id: None,
            port: 43121,
            move_timeout_ms: 10_000,
            replay_out: None,
        })
        .unwrap();

        for (step, tie_set) in tie_sets.iter().take(3).enumerate() {
            let hp_action = hp_s3_session
                .opponent
                .choose(
                    "parity-game",
                    step as u64 + 1,
                    obs.clone(),
                    &history,
                    tie_set,
                    &mut hp_s3_session.opponent_rng,
                )
                .unwrap();

            let standalone_action = s3_live
                .choose_action(DecisionContext {
                    observation: obs.clone(),
                    visible_history: &history,
                    legal_actions: tie_set,
                    meta: PublicRequestMeta {
                        game_id: "parity-game".into(),
                        recipient_seat: PlayerId(0),
                        request_id: step as u64 + 1,
                        observation_hash: observation_hash(&obs),
                    },
                    rng: &mut s3_live_rng,
                })
                .unwrap();

            assert_eq!(
                hp_action, standalone_action,
                "consecutive tie step {step}: human-play S3 must equal standalone S3"
            );
        }

        // Test at least 3 consecutive tie decisions for Fast Heuristic (human-play fast vs standalone)
        let mut h_live = HeuristicAgentPolicy::new();
        let mut h_live_rng = StableRng::new(20_260_812);
        let mut hp_h_session = build_session(&Args {
            seed: 8888, // arbitrary seed: must NOT affect fast heuristic root RNG
            human_seat: 0,
            opponent: Some("fast".into()),
            registry: None,
            agent_id: None,
            port: 43122,
            move_timeout_ms: 10_000,
            replay_out: None,
        })
        .unwrap();

        for (step, tie_set) in tie_sets.iter().take(3).enumerate() {
            let hp_action = hp_h_session
                .opponent
                .choose(
                    "parity-game",
                    step as u64 + 1,
                    obs.clone(),
                    &history,
                    tie_set,
                    &mut hp_h_session.opponent_rng,
                )
                .unwrap();

            let standalone_action = h_live
                .choose_action(DecisionContext {
                    observation: obs.clone(),
                    visible_history: &history,
                    legal_actions: tie_set,
                    meta: PublicRequestMeta {
                        game_id: "parity-game".into(),
                        recipient_seat: PlayerId(0),
                        request_id: step as u64 + 1,
                        observation_hash: observation_hash(&obs),
                    },
                    rng: &mut h_live_rng,
                })
                .unwrap();

            assert_eq!(
                hp_action, standalone_action,
                "consecutive tie step {step}: human-play fast must equal standalone heuristic"
            );
        }

        // 3. Sensitivity check: verify that an incorrect seed DOES diverge on ties
        let mut buggy_rng = StableRng::new(9999 ^ 0xa5a5_5a5a);
        let mut matched_all = true;
        let mut test_policy = HeuristicAgentPolicy::new();
        for (step, tie_set) in tie_sets.iter().take(3).enumerate() {
            let buggy_action = test_policy
                .choose_action(DecisionContext {
                    observation: obs.clone(),
                    visible_history: &history,
                    legal_actions: tie_set,
                    meta: PublicRequestMeta {
                        game_id: "sensitivity".into(),
                        recipient_seat: PlayerId(0),
                        request_id: step as u64 + 1,
                        observation_hash: observation_hash(&obs),
                    },
                    rng: &mut buggy_rng,
                })
                .unwrap();
            let mut correct_rng = StableRng::new(20_260_812);
            for _ in 0..step {
                // advance correct_rng to the same step
                let _ = test_policy.choose_action(DecisionContext {
                    observation: obs.clone(),
                    visible_history: &history,
                    legal_actions: tie_set,
                    meta: PublicRequestMeta {
                        game_id: "sensitivity".into(),
                        recipient_seat: PlayerId(0),
                        request_id: step as u64 + 1,
                        observation_hash: observation_hash(&obs),
                    },
                    rng: &mut correct_rng,
                });
            }
            let correct_action = test_policy
                .choose_action(DecisionContext {
                    observation: obs.clone(),
                    visible_history: &history,
                    legal_actions: tie_set,
                    meta: PublicRequestMeta {
                        game_id: "sensitivity".into(),
                        recipient_seat: PlayerId(0),
                        request_id: step as u64 + 1,
                        observation_hash: observation_hash(&obs),
                    },
                    rng: &mut correct_rng,
                })
                .unwrap();
            if buggy_action != correct_action {
                matched_all = false;
                break;
            }
        }
        assert!(
            !matched_all,
            "sensitivity check: buggy game-derived RNG must diverge from correct seed"
        );
    }

    #[test]
    fn review_session_ids_fail_closed_on_paths() {
        assert_eq!(
            sanitize_session_id("human-20260813_1").unwrap(),
            "human-20260813_1"
        );
        for invalid in ["", ".", "..", "../game", "..\\game", "C:game", "game/name"] {
            assert!(sanitize_session_id(invalid).is_err(), "accepted {invalid}");
        }
    }

    #[test]
    fn historical_replay_archive_rebuilds_every_frame_from_the_replay() {
        let (_, replay) = splendor_replay::record_random_game(2, 42, 9).unwrap();
        let archive = build_historical_replay_archive(
            &replay,
            "human-test-session",
            Some("Test Opponent".into()),
            Some(1),
        )
        .unwrap();
        assert_eq!(archive.format, "effective-splendor-human-replay-archive");
        assert_eq!(archive.version, 2);
        assert_eq!(archive.player_count, 2);
        assert_eq!(archive.frames.len(), replay.steps.len());
        for (index, frame) in archive.frames.iter().enumerate() {
            let step = &replay.steps[index];
            assert_eq!(frame.ply, index as u32);
            assert_eq!(frame.actor, step.actor);
            assert_eq!(frame.recorded_action, step.action);
            assert_eq!(frame.player_view.viewer, frame.actor);
            assert!(frame.legal_actions.contains(&frame.recorded_action));
            assert_eq!(frame.referee_reveal.seed, replay.seed);
            assert_eq!(
                frame.referee_reveal.players.len(),
                replay.player_count as usize
            );
        }
        // The bundle must serialize for the wire without loss.
        let value = serde_json::to_value(&archive).unwrap();
        assert_eq!(
            value["frames"].as_array().unwrap().len(),
            replay.steps.len()
        );
    }

    #[test]
    fn historical_replay_archive_rejects_a_tampered_replay() {
        let (_, mut replay) = splendor_replay::record_random_game(2, 42, 9).unwrap();
        replay.steps[0].action = Action::Pass;
        let error =
            build_historical_replay_archive(&replay, "human-test-session", None, None).unwrap_err();
        assert!(error.contains("replay verification failed"), "{error}");
    }

    #[test]
    fn review_creation_fails_closed_for_unsupported_player_counts() {
        // 2p -> S3 default; 3/4p -> M07 default; an explicit S3 selection on
        // a 3/4p replay must be rejected by the host BEFORE any job starts.
        let registry = ReviewerRegistryV1 {
            format: "effective-splendor-studio-reviewers".into(),
            version: 1,
            registry_id: "test-reviewers".into(),
            reviewers: vec![
                test_reviewer_entry(
                    splendor_analysis::S3_REVIEWER_ID,
                    "S3 Rollout Review",
                    splendor_analysis::ReviewerStatusV2::Champion,
                    splendor_analysis::ReviewerResultKindV2::PolicyRecommendation,
                    vec![2],
                ),
                test_reviewer_entry(
                    "m07-determinization-champion",
                    "M07 Determinization Champion",
                    splendor_analysis::ReviewerStatusV2::Champion,
                    splendor_analysis::ReviewerResultKindV2::RootDeterminization,
                    vec![3, 4],
                ),
            ],
        };
        registry.validate().unwrap();
        let s3 = registry.entry(splendor_analysis::S3_REVIEWER_ID).unwrap();
        let m07 = registry.entry("m07-determinization-champion").unwrap();

        assert!(ensure_reviewer_supported(s3, 2).is_ok());
        assert_eq!(
            registry.default_entry(2).unwrap().id,
            splendor_analysis::S3_REVIEWER_ID
        );
        for player_count in [3u8, 4] {
            let error = ensure_reviewer_supported(s3, player_count).unwrap_err();
            assert!(
                error.contains("unavailable for") && error.contains("frozen for 2-player"),
                "unclear unsupported-reviewer error: {error}"
            );
            assert!(ensure_reviewer_supported(m07, player_count).is_ok());
            assert_eq!(
                registry.default_entry(player_count).unwrap().id,
                "m07-determinization-champion"
            );
        }
    }

    fn test_reviewer_entry(
        id: &str,
        display_name: &str,
        competitive_status: splendor_analysis::ReviewerStatusV2,
        result_kind: splendor_analysis::ReviewerResultKindV2,
        default_for_player_counts: Vec<u8>,
    ) -> splendor_analysis::ReviewerEntryV1 {
        let (available_metrics, default_config) = match result_kind {
            splendor_analysis::ReviewerResultKindV2::PolicyRecommendation => (
                vec!["recommended_action".into(), "decision_path".into()],
                ReviewerConfigV2::PolicyRecommendation(
                    splendor_analysis::S3ReviewConfigV2::frozen_v1(),
                ),
            ),
            splendor_analysis::ReviewerResultKindV2::RootDeterminization => (
                vec![
                    "mean_utility".into(),
                    "utility_gap".into(),
                    "action_rank".into(),
                ],
                ReviewerConfigV2::RootDeterminization(RootDeterminizationConfigV1 {
                    sample_seed: 20260810,
                    sample_count: 4,
                    continuation_search: SearchConfigV1 {
                        max_depth_turns: 1,
                        max_nodes: 2000,
                    },
                }),
            ),
            splendor_analysis::ReviewerResultKindV2::NeuralIsmcts => {
                unreachable!("test helper only builds S3/M07 reviewers")
            }
        };
        splendor_analysis::ReviewerEntryV1 {
            id: id.into(),
            display_name: display_name.into(),
            description: "test".into(),
            competitive_status,
            result_kind,
            default_for_player_counts,
            available_metrics,
            required_artifacts: vec![],
            estimated_cost: "cpu".into(),
            default_config,
            checkpoint_path: None,
        }
    }

    fn test_reviewer_registry() -> ReviewerRegistryV1 {
        ReviewerRegistryV1 {
            format: "effective-splendor-studio-reviewers".into(),
            version: 1,
            registry_id: "test-reviewers".into(),
            reviewers: vec![test_reviewer_entry(
                "m07-determinization-champion",
                "M07 Determinization Champion",
                splendor_analysis::ReviewerStatusV2::Champion,
                splendor_analysis::ReviewerResultKindV2::RootDeterminization,
                vec![2, 3, 4],
            )],
        }
    }
}
