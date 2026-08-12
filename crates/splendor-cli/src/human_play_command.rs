use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::time::Duration;

use splendor_agent::{
    AgentPolicy, DecisionContext, HeuristicAgentPolicy, PublicRequestMeta, StableRng,
};
use splendor_arena::{seed_commitment_v1, spawn_agent, AgentProcess, InboundEvent};
use splendor_catalog::{all_cards, all_nobles, CardId, GemColor, NobleId, Tier};
use splendor_core::{
    observation_hash, ruleset_fingerprint, visible_events, Action, Audience, FullState, GameConfig,
    GameResult, Observation, PlayerId, RefereeEvent, VisibleEvent, CATALOG_VERSION, ENGINE_VERSION,
};
use splendor_determinization_agent::DeterminizationAgentPolicyV1;
use splendor_eval::RatingRegistryV1;
use splendor_imperfect_search::RootDeterminizationConfigV1;
use splendor_protocol::{
    parse_client_line, ClientMessage, ObservationMeta, RecipientMeta, RequestMeta, ServerMessage,
    ServerMeta, PROTOCOL_VERSION,
};
use splendor_replay::{replay_document_hash_v1, verify_replay, ReplayRecorder, ReplayV1};
use splendor_search::SearchConfigV1;

const USAGE: &str = "Usage: splendor human-play-server --seed <u64> --human-seat <0|1> (--opponent <heuristic|m07> | --registry <registry.json> --agent-id <id>) --port <u16> [--move-timeout-ms <u64>] [--replay-out <replay.json>]";
const HOST_USAGE: &str =
    "Usage: splendor studio-host --registry <registry.json> --port <u16> [--move-timeout-ms <u64>]";
const DEFAULT_MOVE_TIMEOUT_MS: u64 = 120_000;
const HANDSHAKE_TIMEOUT_MS: u64 = 30_000;

enum InProcessOpponent {
    Heuristic(HeuristicAgentPolicy),
    M07(DeterminizationAgentPolicyV1),
}

impl InProcessOpponent {
    fn choose(&mut self, context: DecisionContext<'_>) -> Result<Action, String> {
        match self {
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
        registry_path: &PathBuf,
        agent_id: &str,
        seat: PlayerId,
        game_id: &str,
        seed: u64,
        state: &FullState,
        setup_events: &[RefereeEvent],
        move_timeout_ms: u64,
    ) -> Result<Self, String> {
        let bytes = fs::read(registry_path).map_err(|error| {
            format!(
                "cannot read rating registry {}: {error}",
                registry_path.display()
            )
        })?;
        let registry: RatingRegistryV1 = serde_json::from_slice(&bytes)
            .map_err(|error| format!("invalid rating registry JSON: {error}"))?;
        registry.validate()?;
        let selected = registry
            .agents
            .iter()
            .find(|agent| agent.id == agent_id)
            .ok_or_else(|| format!("agent id `{agent_id}` is not in the rating registry"))?;
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

#[derive(serde::Serialize)]
struct HumanSessionState {
    format: &'static str,
    version: u32,
    session_id: String,
    human_seat: PlayerId,
    opponent: String,
    ply: u32,
    observation: Observation,
    legal_actions: Vec<Action>,
    result: Option<GameResult>,
    replay_ready: bool,
    replay_document_hash: Option<String>,
}

struct Session {
    id: String,
    human_seat: PlayerId,
    recorder: Option<ReplayRecorder>,
    terminal_state: Option<FullState>,
    replay: Option<ReplayV1>,
    replay_hash: Option<String>,
    replay_out: PathBuf,
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
        self.opponent.send_visible_events(&self.id, &step.events)?;
        self.finish_if_terminal()
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
        verify_replay(&replay)
            .map_err(|error| format!("recorded replay failed verification: {error}"))?;
        let replay_hash = replay_document_hash_v1(&replay).map_err(|error| error.to_string())?;
        if let Some(parent) = self.replay_out.parent() {
            fs::create_dir_all(parent).map_err(|error| {
                format!(
                    "cannot create replay directory {}: {error}",
                    parent.display()
                )
            })?;
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&self.replay_out)
            .map_err(|error| {
                format!(
                    "cannot create replay {} without overwrite: {error}",
                    self.replay_out.display()
                )
            })?;
        serde_json::to_writer_pretty(&mut file, &replay)
            .map_err(|error| format!("cannot serialize replay: {error}"))?;
        file.write_all(b"\n")
            .map_err(|error| format!("cannot finish replay file: {error}"))?;
        self.terminal_state = Some(state);
        self.replay = Some(replay);
        self.replay_hash = Some(replay_hash);
        self.opponent.shutdown();
        Ok(())
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
            human_seat: self.human_seat,
            opponent: self.opponent.label().to_string(),
            ply: self.ply,
            observation: state.observation(self.human_seat),
            legal_actions: if state.is_terminal() || state.current_player != self.human_seat {
                Vec::new()
            } else {
                state.legal_actions()
            },
            result: state.result.clone(),
            replay_ready: self.replay.is_some(),
            replay_document_hash: self.replay_hash.clone(),
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
    port: u16,
    move_timeout_ms: u64,
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

struct StudioHost {
    registry_path: PathBuf,
    registry: RatingRegistryV1,
    move_timeout_ms: u64,
    next_session_number: u64,
    session: Option<Session>,
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
        if !self
            .registry
            .agents
            .iter()
            .any(|agent| agent.id == request.agent_id)
        {
            return Err(format!(
                "agent id `{}` is not in the Studio registry",
                request.agent_id
            ));
        }
        let session_number = self.next_session_number;
        self.next_session_number = self
            .next_session_number
            .checked_add(1)
            .ok_or("Studio session counter overflow")?;
        let session = build_registered_session(
            request.seed,
            request.human_seat,
            &self.registry_path,
            &request.agent_id,
            self.move_timeout_ms,
            None,
            Some(session_number),
        )?;
        self.session = Some(session);
        Ok(self
            .session
            .as_ref()
            .expect("session was installed")
            .snapshot())
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
        if let Err(error) = handle_session(stream, &mut session) {
            eprintln!("request error: {error}");
        }
    }
    Ok(())
}

fn build_session(args: &Args) -> Result<Session, String> {
    if let (None, Some(registry), Some(agent_id)) = (&args.opponent, &args.registry, &args.agent_id)
    {
        return build_registered_session(
            args.seed,
            args.human_seat,
            registry,
            agent_id,
            args.move_timeout_ms,
            args.replay_out.clone(),
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
    let opponent = match (&args.opponent, &args.registry, &args.agent_id) {
        (Some(name), None, None) if name == "heuristic" => Opponent::InProcess {
            label: "Heuristic baseline",
            policy: InProcessOpponent::Heuristic(HeuristicAgentPolicy::new()),
        },
        (Some(name), None, None) if name == "m07" => Opponent::InProcess {
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
        (Some(_), None, None) => return Err("--opponent must be heuristic or m07".into()),
        _ => {
            return Err(
                "choose either --opponent <heuristic|m07> or --registry <path> --agent-id <id>"
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
        frames: Vec::new(),
        opponent,
        opponent_rng: StableRng::new(args.seed ^ 0xa5a5_5a5a),
        request_id: 0,
        ply: 0,
    };
    session.advance_opponent()?;
    Ok(session)
}

fn build_registered_session(
    seed: u64,
    human_seat: u8,
    registry: &PathBuf,
    agent_id: &str,
    move_timeout_ms: u64,
    replay_out: Option<PathBuf>,
    session_number: Option<u64>,
) -> Result<Session, String> {
    let id = match session_number {
        Some(number) => format!("human-{seed}-{human_seat}-{}-{number}", std::process::id()),
        None => format!("human-{seed}-{human_seat}-{}", std::process::id()),
    };
    let (recorder, setup) = ReplayRecorder::new_with_setup(GameConfig {
        player_count: 2,
        seed,
        ..Default::default()
    })
    .map_err(|error| format!("cannot create replay recorder: {error}"))?;
    let opponent_seat = PlayerId(1 - human_seat);
    let opponent = Opponent::Registered(RegisteredOpponent::start(
        registry,
        agent_id,
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
    let mut host = StudioHost {
        registry_path: args.registry,
        registry,
        move_timeout_ms: args.move_timeout_ms,
        next_session_number: 1,
        session: None,
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

fn handle_host(mut stream: TcpStream, host: &mut StudioHost) -> Result<(), String> {
    let request = read_request(&stream)?;
    if request.method == "OPTIONS" {
        return respond(&mut stream, 204, "application/json", "");
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
        ("POST", "/action") => host
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
            }),
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

fn parse_host_args(args: &[String]) -> Result<HostArgs, String> {
    let mut registry = None;
    let mut port = None;
    let mut move_timeout_ms = None;
    let mut index = 0;
    while index < args.len() {
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("missing value for `{}`; {HOST_USAGE}", args[index]))?
            .clone();
        match args[index].as_str() {
            "--registry" => set_once(&mut registry, PathBuf::from(value), "--registry")?,
            "--port" => set_once(&mut port, value, "--port")?,
            "--move-timeout-ms" => set_once(&mut move_timeout_ms, value, "--move-timeout-ms")?,
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
    let move_timeout_ms = move_timeout_ms
        .unwrap_or_else(|| DEFAULT_MOVE_TIMEOUT_MS.to_string())
        .parse::<u64>()
        .map_err(|_| "--move-timeout-ms must be u64")?;
    if move_timeout_ms == 0 || move_timeout_ms > 24 * 60 * 60 * 1_000 {
        return Err("--move-timeout-ms must be in 1..=86400000".into());
    }
    Ok(HostArgs {
        registry: registry.ok_or("missing --registry")?,
        port,
        move_timeout_ms,
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
        assert!(!json.contains("seed\""));
    }

    #[test]
    fn archive_is_unavailable_before_terminal() {
        assert_eq!(
            test_session().archive().unwrap_err(),
            "replay is available only after game completion"
        );
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
            registry_path: PathBuf::from("private/registry.json"),
            registry,
            move_timeout_ms: DEFAULT_MOVE_TIMEOUT_MS,
            next_session_number: 1,
            session: None,
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
}
