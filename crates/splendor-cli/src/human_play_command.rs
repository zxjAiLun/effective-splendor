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
    let (recorder, setup) = ReplayRecorder::new_with_setup(config)
        .map_err(|error| format!("cannot create replay recorder: {error}"))?;
    let opponent_seat = PlayerId(1 - args.human_seat);
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
        (None, Some(registry), Some(agent_id)) => Opponent::Registered(RegisteredOpponent::start(
            registry,
            agent_id,
            opponent_seat,
            &id,
            args.seed,
            recorder.state(),
            &setup.events,
            args.move_timeout_ms,
        )?),
        (Some(_), None, None) => return Err("--opponent must be heuristic or m07".into()),
        _ => {
            return Err(
                "choose either --opponent <heuristic|m07> or --registry <path> --agent-id <id>"
                    .into(),
            )
        }
    };
    let replay_out = args.replay_out.unwrap_or_else(|| {
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
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, args.port))
        .map_err(|error| format!("cannot bind 127.0.0.1:{}: {error}", args.port))?;
    println!("human_play_server=http://127.0.0.1:{}", args.port);
    println!("opponent={}", session.opponent.label());
    for connection in listener.incoming() {
        let stream = connection.map_err(|error| error.to_string())?;
        if let Err(error) = handle(stream, &mut session) {
            eprintln!("request error: {error}");
        }
    }
    Ok(())
}

fn handle(mut stream: TcpStream, session: &mut Session) -> Result<(), String> {
    let mut reader = BufReader::new(stream.try_clone().map_err(|error| error.to_string())?);
    let mut request_line = String::new();
    reader
        .read_line(&mut request_line)
        .map_err(|error| error.to_string())?;
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("");
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
    if method == "OPTIONS" {
        return respond(&mut stream, 204, "application/json", "");
    }
    let result: Result<String, String> = match (method, path) {
        ("GET", "/state") => serde_json::to_string(&session.snapshot()).map_err(|e| e.to_string()),
        ("POST", "/action") if content_length <= 64 * 1024 => {
            let mut body = vec![0; content_length];
            reader
                .read_exact(&mut body)
                .map_err(|error| error.to_string())?;
            serde_json::from_slice::<Action>(&body)
                .map_err(|error| format!("invalid action JSON: {error}"))
                .and_then(|action| session.human_action(action))
                .and_then(|()| {
                    serde_json::to_string(&session.snapshot()).map_err(|e| e.to_string())
                })
        }
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
    match result {
        Ok(body) => respond(&mut stream, 200, "application/json", &body),
        Err(error) => respond(
            &mut stream,
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
}
