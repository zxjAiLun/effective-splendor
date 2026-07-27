//! The reference stdio agent runtime (NDJSON FSM) and its generic driver.
//!
//! [`run_agent`] speaks the strict server protocol exactly like any third-party
//! agent would: it never calls the rules engine to "play" the game, never
//! reconstructs the deck, never sees the seed, the full-state hash, or the
//! replay. It only ever chooses from the `legal_actions` the server hands it in
//! each `request_action`, delegating that choice to an [`AgentPolicy`].
//!
//! The runtime is transport-agnostic (it takes `BufRead` / `Write` handles) so
//! it can be unit-tested against hand-built server transcripts. The command
//! layer is the only place that binds the real stdin/stdout/stderr.

use std::io::{BufRead, Write};

use splendor_core::{Observation, ObservationHash, PlayerId};
use splendor_protocol::{
    parse_server_line, ClientMessage, ClientMeta, ClientRequestMeta, ProtocolParseError,
    ServerMessage, PROTOCOL_VERSION,
};

use crate::error::AgentError;
use crate::policy::{AgentPolicy, DecisionContext, PublicRequestMeta};
use crate::stable_rng::StableRng;

/// The public identity a policy presents to the arena in its `Client Hello`.
///
/// The generic runtime does **not** assume any particular agent: identity is an
/// explicit input so a `HeuristicAgentPolicy` (or any future policy) declares its
/// own `name` / `version` instead of impersonating the reference random agent.
/// This keeps arena reports, evaluation aggregation, and version-compatibility
/// analysis correct — a heuristic agent must never appear as `splendor-cli-random`.
#[derive(Debug, Clone, Copy)]
pub struct AgentIdentity<'a> {
    pub name: &'a str,
    pub version: &'a str,
}

/// Internal FSM state, threaded through the read loop.
struct AgentState {
    rng: StableRng,
    game_id: Option<String>,
    seat: Option<PlayerId>,
    last_observation: Option<Observation>,
    last_observation_hash: Option<ObservationHash>,
    last_request_id: Option<u64>,
}

/// Run an agent to completion over the given streams using `policy`.
///
/// Returns `Ok(())` on a clean `game_end`. On any protocol/I/O/policy fault it
/// writes a single `error: <reason>` line to `diagnostics` and returns the
/// classified error; the caller maps that to a non-zero exit code.
///
/// `identity` is the `Client Hello` identity the agent presents to the arena;
/// it is an explicit input (not a runtime constant) so any `AgentPolicy` can
/// declare its own name/version. Use [`crate::run_random_agent`] for the
/// byte-compatible reference identity.
pub fn run_agent<R, W, E, P>(
    input: R,
    mut output: W,
    mut diagnostics: E,
    identity: AgentIdentity<'_>,
    seed: u64,
    mut policy: P,
) -> Result<(), AgentError>
where
    R: BufRead,
    W: Write,
    E: Write,
    P: AgentPolicy,
{
    let mut state = AgentState {
        rng: StableRng::new(seed),
        game_id: None,
        seat: None,
        last_observation: None,
        last_observation_hash: None,
        last_request_id: None,
    };

    let result = drive(input, &mut output, &mut state, &mut policy, &identity);
    if let Err(err) = &result {
        // Best-effort diagnostic; never fail the run on a diagnostics write.
        let _ = writeln!(diagnostics, "error: {err}");
        let _ = diagnostics.flush();
    }
    result
}

fn drive<R, W, P>(
    mut input: R,
    output: &mut W,
    state: &mut AgentState,
    policy: &mut P,
    identity: &AgentIdentity<'_>,
) -> Result<(), AgentError>
where
    R: BufRead,
    W: Write,
    P: AgentPolicy,
{
    let mut line = String::new();
    loop {
        line.clear();
        let n = input
            .read_line(&mut line)
            .map_err(|e| AgentError::Io(format!("stdin read failed: {e}")))?;
        if n == 0 {
            // EOF before a clean game_end is a fault (the runner closes our
            // stdin only on abort/shutdown; a completed match ends with a
            // game_end that returns Ok above).
            return Err(AgentError::Protocol(
                "server stream ended before game_end".to_string(),
            ));
        }
        // Trim the trailing newline (and a CR, if the transport uses CRLF).
        while line.ends_with('\n') || line.ends_with('\r') {
            line.pop();
        }
        if line.is_empty() {
            continue;
        }

        let message = parse_server_line(&line).map_err(classify_parse_error)?;
        if handle_message(output, state, policy, message, identity)? {
            return Ok(()); // game_end reached.
        }
    }
}

/// Handle one server message. Returns `Ok(true)` when the match ended cleanly.
fn handle_message<W, P>(
    output: &mut W,
    state: &mut AgentState,
    policy: &mut P,
    message: ServerMessage,
    identity: &AgentIdentity<'_>,
) -> Result<bool, AgentError>
where
    W: Write,
    P: AgentPolicy,
{
    match message {
        ServerMessage::Hello {
            meta,
            engine_version: _,
            ..
        } => {
            if state.game_id.is_some() {
                return Err(AgentError::Protocol(
                    "duplicate hello from server".to_string(),
                ));
            }
            if meta.protocol_version != PROTOCOL_VERSION {
                return Err(AgentError::Protocol(format!(
                    "protocol version mismatch: server {}, agent {}",
                    meta.protocol_version, PROTOCOL_VERSION
                )));
            }
            state.game_id = Some(meta.game_id.clone());
            let reply = ClientMessage::Hello {
                meta: ClientMeta::new(meta.game_id),
                agent_name: identity.name.to_string(),
                agent_version: identity.version.to_string(),
            };
            send(output, &reply)?;
            Ok(false)
        }
        ServerMessage::GameStart { meta, .. } => {
            expect_game_id(state, &meta.server.game_id)?;
            if state.seat.is_some() {
                return Err(AgentError::Protocol(
                    "duplicate game_start from server".to_string(),
                ));
            }
            state.seat = Some(meta.player_id());
            Ok(false)
        }
        ServerMessage::Observation { meta, observation } => {
            expect_game_id(state, &meta.recipient.server.game_id)?;
            expect_seat(state, meta.recipient.player_id())?;
            state.last_observation_hash = Some(meta.observation_hash.clone());
            state.last_observation = Some(observation);
            Ok(false)
        }
        ServerMessage::RequestAction {
            meta,
            legal_actions,
            ..
        } => {
            expect_game_id(state, &meta.recipient.server.game_id)?;
            expect_seat(state, meta.recipient.player_id())?;

            // Request ids must be strictly increasing across the match.
            if let Some(last) = state.last_request_id {
                if meta.request_id <= last {
                    return Err(AgentError::Protocol(format!(
                        "request_id must strictly increase (got {}, last {})",
                        meta.request_id, last
                    )));
                }
            }
            state.last_request_id = Some(meta.request_id);

            // The request must correspond to the observation we last received.
            match &state.last_observation_hash {
                Some(hash) if *hash == meta.observation_hash => {}
                Some(_) => {
                    return Err(AgentError::Protocol(
                        "request observation_hash does not match latest observation".to_string(),
                    ));
                }
                None => {
                    return Err(AgentError::Protocol(
                        "request_action arrived before any observation".to_string(),
                    ));
                }
            }

            if legal_actions.is_empty() {
                return Err(AgentError::Protocol(
                    "request_action carried an empty legal_actions set".to_string(),
                ));
            }

            // Hand the policy a view that cannot leak referee-only state: the
            // observation, the certified legal actions, public metadata, and the
            // agent's own RNG. The policy never sees FullState / FullStateHash /
            // seed / replay / blind reserves / deck order.
            let observation = state.last_observation.clone().ok_or_else(|| {
                AgentError::Protocol("request_action arrived before any observation".to_string())
            })?;
            let context = DecisionContext {
                observation,
                legal_actions: &legal_actions,
                meta: PublicRequestMeta {
                    game_id: meta.recipient.server.game_id.clone(),
                    recipient_seat: meta.recipient.player_id(),
                    request_id: meta.request_id,
                    observation_hash: meta.observation_hash.clone(),
                },
                rng: &mut state.rng,
            };
            let action = policy
                .choose_action(context)
                .map_err(|e| AgentError::Policy(e.to_string()))?;
            // The runtime enforces the hard policy boundary: a policy may only
            // return an action the server certified as legal for this request.
            // Without this check a buggy/over-eager built-in policy would ship an
            // illegal action to the server and surface as an opaque server-side
            // IllegalAction instead of a clear, owned policy error.
            if !legal_actions.contains(&action) {
                return Err(AgentError::Policy(
                    "policy returned an action outside legal_actions".to_string(),
                ));
            }
            let reply = ClientMessage::Action {
                meta: ClientRequestMeta::new(
                    meta.recipient.server.game_id.clone(),
                    meta.request_id,
                ),
                action,
            };
            send(output, &reply)?;
            Ok(false)
        }
        ServerMessage::Ping { meta } => {
            expect_game_id(state, &meta.server.game_id)?;
            let reply = ClientMessage::Pong {
                meta: ClientMeta::new(meta.server.game_id.clone()),
            };
            send(output, &reply)?;
            Ok(false)
        }
        // Informational broadcasts: verify the game id and continue.
        ServerMessage::ActionApplied { meta, .. } => {
            expect_game_id(state, &meta.server.game_id)?;
            Ok(false)
        }
        ServerMessage::Event { meta, .. } => {
            expect_game_id(state, &meta.server.game_id)?;
            Ok(false)
        }
        ServerMessage::GameEnd { meta, .. } => {
            expect_game_id(state, &meta.server.game_id)?;
            Ok(true)
        }
        ServerMessage::Error { message, .. } => Err(AgentError::Protocol(format!(
            "server reported an error: {message}"
        ))),
    }
}

/// Serialize and flush one client message as a single NDJSON line.
fn send<W: Write>(output: &mut W, message: &ClientMessage) -> Result<(), AgentError> {
    let line = serde_json::to_string(message)
        .map_err(|e| AgentError::Io(format!("serialize client message failed: {e}")))?;
    output
        .write_all(line.as_bytes())
        .and_then(|()| output.write_all(b"\n"))
        .and_then(|()| output.flush())
        .map_err(|e| AgentError::Io(format!("stdout write failed: {e}")))
}

fn expect_game_id(state: &AgentState, got: &str) -> Result<(), AgentError> {
    match &state.game_id {
        Some(expected) if expected == got => Ok(()),
        Some(expected) => Err(AgentError::Protocol(format!(
            "game_id mismatch: expected {expected}, got {got}"
        ))),
        None => Err(AgentError::Protocol(
            "server message arrived before hello".to_string(),
        )),
    }
}

fn expect_seat(state: &AgentState, got: PlayerId) -> Result<(), AgentError> {
    match state.seat {
        Some(seat) if seat == got => Ok(()),
        Some(seat) => Err(AgentError::Protocol(format!(
            "recipient seat mismatch: bound to {}, message for {}",
            seat.0, got.0
        ))),
        None => Err(AgentError::Protocol(
            "player-scoped message arrived before game_start".to_string(),
        )),
    }
}

/// Map a strict-parser error to the agent's error taxonomy. A parse failure is
/// a malformed server line.
fn classify_parse_error(err: ProtocolParseError) -> AgentError {
    match err {
        ProtocolParseError::WrongMessageType { found } => {
            AgentError::Protocol(format!("unexpected server message type `{found}`"))
        }
        other => AgentError::Io(format!("malformed server line: {other}")),
    }
}

#[cfg(test)]
mod tests {
    use crate::{run_random_agent, AgentError, RANDOM_AGENT_NAME};
    use splendor_core::{
        observation_hash, ruleset_fingerprint, FullState, GameConfig, PlayerId, ENGINE_VERSION,
    };
    use splendor_protocol::{
        parse_server_line, ClientMessage, ObservationMeta, RecipientMeta, RequestMeta,
        ServerMessage,
    };

    /// Build a real 2-player start state and its first-turn server messages.
    fn scenario() -> (String, Vec<String>) {
        let game_id = "fsm-test".to_string();
        let (state, _setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 99,
            ..Default::default()
        })
        .expect("setup");
        let seat = PlayerId(0);
        let obs = state.observation(seat);
        let obs_hash = observation_hash(&obs);
        let hello = ServerMessage::hello(
            &game_id,
            splendor_core::RULESET_BASE_V1.0,
            splendor_core::CATALOG_VERSION,
            ruleset_fingerprint(&state.ruleset),
        );
        let game_start = ServerMessage::GameStart {
            meta: RecipientMeta::new(&game_id, 1, seat),
            player_count: 2,
            seed_commitment: "test-commitment".to_string(),
        };
        let observation = ServerMessage::Observation {
            meta: ObservationMeta::new(&game_id, 2, seat, obs_hash.clone()),
            observation: obs,
        };
        let request = ServerMessage::RequestAction {
            meta: RequestMeta::new(&game_id, 3, seat, 1, obs_hash),
            deadline_ms: 1000,
            legal_actions: state.legal_actions(),
        };
        let end = ServerMessage::GameEnd {
            meta: RecipientMeta::new(&game_id, 4, seat),
            result: terminal_result(),
        };
        let lines = [hello, game_start, observation, request, end]
            .iter()
            .map(|m| m.to_json_line().unwrap())
            .collect();
        (game_id, lines)
    }

    fn terminal_result() -> splendor_core::GameResult {
        splendor_core::GameResult {
            scores: vec![15, 3],
            ranks: vec![1, 2],
            winners: vec![PlayerId(0)],
            reason: splendor_core::TerminalReason::PrestigeThreshold,
        }
    }

    fn run_over(lines: &[String], seed: u64) -> (Vec<String>, Vec<String>, Result<(), AgentError>) {
        let input = lines.join("\n") + "\n";
        let mut out = Vec::new();
        let mut err = Vec::new();
        let res = run_random_agent(input.as_bytes(), &mut out, &mut err, seed);
        let out_lines = String::from_utf8(out)
            .unwrap()
            .lines()
            .map(str::to_string)
            .collect();
        let err_lines = String::from_utf8(err)
            .unwrap()
            .lines()
            .map(str::to_string)
            .collect();
        (out_lines, err_lines, res)
    }

    #[test]
    fn same_seed_same_transcript_same_actions() {
        let (_, lines) = scenario();
        let (out_a, _, res_a) = run_over(&lines, 42);
        let (out_b, _, res_b) = run_over(&lines, 42);
        assert!(res_a.is_ok() && res_b.is_ok());
        assert_eq!(out_a, out_b);
        // hello + action.
        assert_eq!(out_a.len(), 2);
    }

    #[test]
    fn different_seed_changes_selection() {
        // Use a state with many legal actions so different seeds diverge.
        let (_, lines) = scenario();
        let (out_a, _, _) = run_over(&lines, 1);
        let (out_b, _, _) = run_over(&lines, 2);
        // The hello line is identical; only the action line can differ.
        assert_eq!(out_a[0], out_b[0]);
        // With a rich legal-action set the two seeds should pick differently.
        // (Guarded: if they happened to coincide this would be a false pass,
        // but the frozen state below has dozens of legal actions.)
        assert_ne!(out_a[1], out_b[1]);
    }

    #[test]
    fn chosen_action_is_always_legal() {
        let (_, lines) = scenario();
        // Recover the legal set from the request line.
        let legal = match parse_server_line(&lines[3]).unwrap() {
            ServerMessage::RequestAction { legal_actions, .. } => legal_actions,
            _ => panic!("expected request_action"),
        };
        let (out, _, res) = run_over(&lines, 123);
        res.unwrap();
        let action_line = &out[1];
        let chosen = match serde_json::from_str::<ClientMessage>(action_line).unwrap() {
            ClientMessage::Action { action, .. } => action,
            _ => panic!("expected client action"),
        };
        assert!(legal.contains(&chosen));
    }

    #[test]
    fn hello_is_flushed_before_action() {
        let (_, lines) = scenario();
        let (out, _, res) = run_over(&lines, 7);
        res.unwrap();
        let hello = serde_json::from_str::<ClientMessage>(&out[0]).unwrap();
        assert!(matches!(hello, ClientMessage::Hello { .. }));
        match hello {
            ClientMessage::Hello {
                agent_name,
                agent_version,
                ..
            } => {
                assert_eq!(agent_name, RANDOM_AGENT_NAME);
                assert_eq!(agent_version, ENGINE_VERSION);
            }
            _ => unreachable!(),
        }
    }

    #[test]
    fn game_end_exits_cleanly() {
        let (_, lines) = scenario();
        let (_, err, res) = run_over(&lines, 7);
        assert!(res.is_ok());
        assert!(err.is_empty(), "clean run must not write diagnostics");
    }

    #[test]
    fn stdout_contains_only_client_ndjson() {
        let (_, lines) = scenario();
        let (out, _, res) = run_over(&lines, 7);
        res.unwrap();
        for line in &out {
            // Every stdout line must parse as a client message.
            serde_json::from_str::<ClientMessage>(line)
                .unwrap_or_else(|e| panic!("non-client line on stdout: {line} ({e})"));
        }
    }

    #[test]
    fn request_ids_must_increase() {
        let (game_id, mut lines) = scenario();
        // Duplicate the request with the SAME request_id after the first.
        // Insert before the game_end (index len-1).
        let dup = lines[3].clone();
        lines.insert(4, dup);
        // Also need a matching observation before the duplicate request so the
        // hash check passes and we reach the request_id check. Re-use obs line.
        let obs = lines[2].clone();
        lines.insert(4, obs);
        let _ = game_id;
        let (_, err, res) = run_over(&lines, 7);
        assert!(res.is_err());
        assert!(err.iter().any(|l| l.contains("request_id")));
    }

    #[test]
    fn request_hash_must_match_observation() {
        let game_id = "hash-test";
        let (state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed: 5,
            ..Default::default()
        })
        .unwrap();
        let seat = PlayerId(0);
        let obs = state.observation(seat);
        let real_hash = observation_hash(&obs);
        // A different hash than the one we send in the observation.
        let (other_state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed: 6,
            ..Default::default()
        })
        .unwrap();
        let wrong_hash = observation_hash(&other_state.observation(seat));
        assert_ne!(real_hash, wrong_hash);

        let hello = ServerMessage::hello(
            game_id,
            splendor_core::RULESET_BASE_V1.0,
            splendor_core::CATALOG_VERSION,
            ruleset_fingerprint(&state.ruleset),
        );
        let game_start = ServerMessage::GameStart {
            meta: RecipientMeta::new(game_id, 1, seat),
            player_count: 2,
            seed_commitment: "c".to_string(),
        };
        let observation = ServerMessage::Observation {
            meta: ObservationMeta::new(game_id, 2, seat, real_hash),
            observation: obs,
        };
        let request = ServerMessage::RequestAction {
            meta: RequestMeta::new(game_id, 3, seat, 1, wrong_hash),
            deadline_ms: 1000,
            legal_actions: state.legal_actions(),
        };
        let lines: Vec<String> = [hello, game_start, observation, request]
            .iter()
            .map(|m| m.to_json_line().unwrap())
            .collect();
        let (_, err, res) = run_over(&lines, 7);
        assert!(res.is_err());
        assert!(err.iter().any(|l| l.contains("observation_hash")));
    }

    #[test]
    fn wrong_game_id_is_rejected() {
        let (_, mut lines) = scenario();
        // Replace game_start with a mismatched game id.
        let bad = ServerMessage::GameStart {
            meta: RecipientMeta::new("other-game", 1, PlayerId(0)),
            player_count: 2,
            seed_commitment: "c".to_string(),
        };
        lines[1] = bad.to_json_line().unwrap();
        let (_, err, res) = run_over(&lines, 7);
        assert!(res.is_err());
        assert!(err.iter().any(|l| l.contains("game_id mismatch")));
    }

    #[test]
    fn malformed_server_line_is_rejected() {
        let (_, mut lines) = scenario();
        lines[1] = "{not valid json".to_string();
        let (_, err, res) = run_over(&lines, 7);
        assert!(res.is_err());
        assert!(err.iter().any(|l| l.contains("malformed server line")));
    }

    #[test]
    fn ping_receives_pong() {
        let game_id = "ping-test";
        let (state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed: 5,
            ..Default::default()
        })
        .unwrap();
        let seat = PlayerId(0);
        let hello = ServerMessage::hello(
            game_id,
            splendor_core::RULESET_BASE_V1.0,
            splendor_core::CATALOG_VERSION,
            ruleset_fingerprint(&state.ruleset),
        );
        let ping = ServerMessage::Ping {
            meta: RecipientMeta::new(game_id, 1, seat),
        };
        let end = ServerMessage::GameEnd {
            meta: RecipientMeta::new(game_id, 2, seat),
            result: terminal_result(),
        };
        let lines: Vec<String> = [hello, ping, end]
            .iter()
            .map(|m| m.to_json_line().unwrap())
            .collect();
        let (out, _, res) = run_over(&lines, 7);
        res.unwrap();
        // hello + pong.
        assert_eq!(out.len(), 2);
        assert!(matches!(
            serde_json::from_str::<ClientMessage>(&out[1]).unwrap(),
            ClientMessage::Pong { .. }
        ));
    }

    #[test]
    fn eof_before_game_end_is_an_error() {
        let (_, mut lines) = scenario();
        lines.pop(); // drop game_end.
        let (_, err, res) = run_over(&lines, 7);
        assert!(res.is_err());
        assert!(err.iter().any(|l| l.contains("before game_end")));
    }

    #[test]
    fn message_before_hello_is_rejected() {
        let (_, lines) = scenario();
        // Start straight at game_start (skip hello).
        let no_hello = &lines[1..];
        let (_, err, res) = run_over(no_hello, 7);
        assert!(res.is_err());
        assert!(err.iter().any(|l| l.contains("before hello")));
    }
}
