//! The reference stdio random agent (`splendor-cli agent-random`).
//!
//! This is a *real* protocol client: it speaks NDJSON over stdin/stdout exactly
//! like any third-party agent would. It never calls the rules engine to "play"
//! the game, never reconstructs the deck, never sees the seed, the full-state
//! hash, or the replay. It only ever chooses from the `legal_actions` the
//! server hands it in each `request_action`.
//!
//! [`run_random_agent`] is transport-agnostic (it takes `BufRead` / `Write`
//! handles) so it can be unit-tested against hand-built server transcripts. The
//! command layer is the only place that binds the real stdin/stdout/stderr.
//!
//! # Determinism
//!
//! Action selection uses [`StableRng`], a fixed xorshift64\* generator seeded
//! only from the `--seed` argument. It uses no `std` RNG and does not depend on
//! the `rand` crate, so the same seed and the same server transcript always
//! select the same actions, byte-for-byte, on every platform.

use std::io::{BufRead, Write};

use splendor_core::{Action, ObservationHash, PlayerId, ENGINE_VERSION};
use splendor_protocol::{
    parse_server_line, ClientMessage, ClientMeta, ClientRequestMeta, ProtocolParseError,
    ServerMessage, PROTOCOL_VERSION,
};

/// The agent name this reference client declares in its `hello`.
pub const RANDOM_AGENT_NAME: &str = "splendor-cli-random";

/// A stable, seed-only pseudo-random generator (xorshift64\*).
///
/// The algorithm and the seed-initialization constant are frozen and covered by
/// [`tests::rng_is_frozen`]. Do not change them: a change would silently alter
/// every reference-agent transcript.
#[derive(Debug, Clone)]
pub struct StableRng(u64);

impl StableRng {
    /// Odd dispersal constant (fractional bits of the golden ratio). Mixing the
    /// raw seed with this and OR-ing in the low bit guarantees the xorshift
    /// state is never the forbidden all-zero fixed point — in particular
    /// `StableRng::new(0)` is well-behaved.
    const SEED_INIT: u64 = 0x9E37_79B9_7F4A_7C15;

    /// Multiplier of the `*` (star) output stage.
    const MULTIPLIER: u64 = 0x2545_F491_4F6C_DD1D;

    /// Seed the generator. Any `u64` seed (including 0) yields a valid,
    /// non-degenerate state.
    pub fn new(seed: u64) -> Self {
        StableRng((seed ^ Self::SEED_INIT) | 1)
    }

    /// Advance the state and return the next 64-bit output.
    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(Self::MULTIPLIER)
    }

    /// A uniformly distributed index in `[0, len)` using rejection sampling to
    /// avoid the modulo bias a bare `next_u64() % len` would introduce.
    ///
    /// Panics if `len == 0`; callers must guarantee a non-empty range.
    fn index(&mut self, len: usize) -> usize {
        assert!(len > 0, "index range must be non-empty");
        let len = len as u64;
        // `2^64 mod len`: the size of the biased tail we must reject so the
        // accepted region is an exact multiple of `len`.
        let reject_below = (0u64.wrapping_sub(len)) % len;
        loop {
            let v = self.next_u64();
            if v >= reject_below {
                return (v % len) as usize;
            }
        }
    }
}

/// Why the reference agent stopped before a clean `game_end`.
#[derive(Debug)]
pub enum RandomAgentError {
    /// The server sent something that violated the protocol state machine
    /// (unexpected type, wrong game id / recipient / request id, stale
    /// observation hash, empty legal-action set, a server `error`, or EOF
    /// before `game_end`). Carries a stable, concise reason.
    Protocol(String),
    /// A stdin/stdout I/O failure or a malformed (unparseable) server line.
    Io(String),
}

impl std::fmt::Display for RandomAgentError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RandomAgentError::Protocol(m) => write!(f, "{m}"),
            RandomAgentError::Io(m) => write!(f, "{m}"),
        }
    }
}

impl std::error::Error for RandomAgentError {}

/// Internal FSM state, threaded through the read loop.
struct AgentState {
    seed: StableRng,
    game_id: Option<String>,
    seat: Option<PlayerId>,
    last_observation_hash: Option<ObservationHash>,
    last_request_id: Option<u64>,
}

/// Run the reference random agent to completion over the given streams.
///
/// Returns `Ok(())` on a clean `game_end`. On any protocol/I/O fault it writes
/// a single `error: <reason>` line to `diagnostics` and returns the classified
/// error; the caller maps that to a non-zero exit code.
pub fn run_random_agent<R: BufRead, W: Write, E: Write>(
    input: R,
    mut output: W,
    mut diagnostics: E,
    seed: u64,
) -> Result<(), RandomAgentError> {
    let mut state = AgentState {
        seed: StableRng::new(seed),
        game_id: None,
        seat: None,
        last_observation_hash: None,
        last_request_id: None,
    };

    let result = drive(input, &mut output, &mut state);
    if let Err(err) = &result {
        // Best-effort diagnostic; never fail the run on a diagnostics write.
        let _ = writeln!(diagnostics, "error: {err}");
        let _ = diagnostics.flush();
    }
    result
}

fn drive<R: BufRead, W: Write>(
    mut input: R,
    output: &mut W,
    state: &mut AgentState,
) -> Result<(), RandomAgentError> {
    let mut line = String::new();
    loop {
        line.clear();
        let n = input
            .read_line(&mut line)
            .map_err(|e| RandomAgentError::Io(format!("stdin read failed: {e}")))?;
        if n == 0 {
            // EOF before a clean game_end is a fault (the runner closes our
            // stdin only on abort/shutdown; a completed match ends with a
            // game_end that returns Ok above).
            return Err(RandomAgentError::Protocol(
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
        if handle_message(output, state, message)? {
            return Ok(()); // game_end reached.
        }
    }
}

/// Handle one server message. Returns `Ok(true)` when the match ended cleanly.
fn handle_message<W: Write>(
    output: &mut W,
    state: &mut AgentState,
    message: ServerMessage,
) -> Result<bool, RandomAgentError> {
    match message {
        ServerMessage::Hello {
            meta,
            engine_version: _,
            ..
        } => {
            if state.game_id.is_some() {
                return Err(RandomAgentError::Protocol(
                    "duplicate hello from server".to_string(),
                ));
            }
            if meta.protocol_version != PROTOCOL_VERSION {
                return Err(RandomAgentError::Protocol(format!(
                    "protocol version mismatch: server {}, agent {}",
                    meta.protocol_version, PROTOCOL_VERSION
                )));
            }
            state.game_id = Some(meta.game_id.clone());
            let reply = ClientMessage::Hello {
                meta: ClientMeta::new(meta.game_id),
                agent_name: RANDOM_AGENT_NAME.to_string(),
                agent_version: ENGINE_VERSION.to_string(),
            };
            send(output, &reply)?;
            Ok(false)
        }
        ServerMessage::GameStart { meta, .. } => {
            expect_game_id(state, &meta.server.game_id)?;
            if state.seat.is_some() {
                return Err(RandomAgentError::Protocol(
                    "duplicate game_start from server".to_string(),
                ));
            }
            state.seat = Some(meta.player_id());
            Ok(false)
        }
        ServerMessage::Observation { meta, .. } => {
            expect_game_id(state, &meta.recipient.server.game_id)?;
            expect_seat(state, meta.recipient.player_id())?;
            state.last_observation_hash = Some(meta.observation_hash.clone());
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
                    return Err(RandomAgentError::Protocol(format!(
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
                    return Err(RandomAgentError::Protocol(
                        "request observation_hash does not match latest observation".to_string(),
                    ));
                }
                None => {
                    return Err(RandomAgentError::Protocol(
                        "request_action arrived before any observation".to_string(),
                    ));
                }
            }

            if legal_actions.is_empty() {
                return Err(RandomAgentError::Protocol(
                    "request_action carried an empty legal_actions set".to_string(),
                ));
            }

            let choice: Action = legal_actions[state.seed.index(legal_actions.len())];
            let reply = ClientMessage::Action {
                meta: ClientRequestMeta::new(
                    meta.recipient.server.game_id.clone(),
                    meta.request_id,
                ),
                action: choice,
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
        ServerMessage::Error { message, .. } => Err(RandomAgentError::Protocol(format!(
            "server reported an error: {message}"
        ))),
    }
}

/// Serialize and flush one client message as a single NDJSON line.
fn send<W: Write>(output: &mut W, message: &ClientMessage) -> Result<(), RandomAgentError> {
    let line = serde_json::to_string(message)
        .map_err(|e| RandomAgentError::Io(format!("serialize client message failed: {e}")))?;
    output
        .write_all(line.as_bytes())
        .and_then(|()| output.write_all(b"\n"))
        .and_then(|()| output.flush())
        .map_err(|e| RandomAgentError::Io(format!("stdout write failed: {e}")))
}

fn expect_game_id(state: &AgentState, got: &str) -> Result<(), RandomAgentError> {
    match &state.game_id {
        Some(expected) if expected == got => Ok(()),
        Some(expected) => Err(RandomAgentError::Protocol(format!(
            "game_id mismatch: expected {expected}, got {got}"
        ))),
        None => Err(RandomAgentError::Protocol(
            "server message arrived before hello".to_string(),
        )),
    }
}

fn expect_seat(state: &AgentState, got: PlayerId) -> Result<(), RandomAgentError> {
    match state.seat {
        Some(seat) if seat == got => Ok(()),
        Some(seat) => Err(RandomAgentError::Protocol(format!(
            "recipient seat mismatch: bound to {}, message for {}",
            seat.0, got.0
        ))),
        None => Err(RandomAgentError::Protocol(
            "player-scoped message arrived before game_start".to_string(),
        )),
    }
}

/// Map a strict-parser error to the agent's error taxonomy. A parse failure is
/// a malformed server line.
fn classify_parse_error(err: ProtocolParseError) -> RandomAgentError {
    match err {
        ProtocolParseError::WrongMessageType { found } => {
            RandomAgentError::Protocol(format!("unexpected server message type `{found}`"))
        }
        other => RandomAgentError::Io(format!("malformed server line: {other}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{observation_hash, ruleset_fingerprint, FullState, GameConfig};
    use splendor_protocol::{ObservationMeta, RecipientMeta, RequestMeta, ServerMessage};

    /// The xorshift64\* algorithm and seed-init constant are frozen. If this
    /// ever fails, the reference agent's transcripts changed — do not "fix" the
    /// expectations, revert the algorithm change.
    #[test]
    fn rng_is_frozen() {
        let mut r0 = StableRng::new(0);
        assert_eq!(
            [r0.next_u64(), r0.next_u64(), r0.next_u64(), r0.next_u64()],
            [
                0x0D83_B3E2_9A21_487A,
                0x54C4_4C79_F1FE_9D67,
                0xA845_F342_007A_0E78,
                0x7D6E_0B87_8A79_4779,
            ]
        );
        let mut r42 = StableRng::new(42);
        assert_eq!(
            [
                r42.next_u64(),
                r42.next_u64(),
                r42.next_u64(),
                r42.next_u64()
            ],
            [
                0x0832_8D7F_03BC_EC1A,
                0x077E_7279_E17A_B6CD,
                0x0C4E_098F_541B_B09E,
                0xD861_FCF4_7B8B_124E,
            ]
        );
    }

    #[test]
    fn seed_zero_is_not_degenerate() {
        let mut r = StableRng::new(0);
        // A degenerate all-zero state would emit only zeros forever.
        assert!((0..8).any(|_| r.next_u64() != 0));
    }

    #[test]
    fn index_is_always_in_range() {
        let mut r = StableRng::new(7);
        for len in 1..=32usize {
            for _ in 0..64 {
                assert!(r.index(len) < len);
            }
        }
    }

    // --- FSM tests over hand-built server transcripts ----------------------

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

    fn run_over(
        lines: &[String],
        seed: u64,
    ) -> (Vec<String>, Vec<String>, Result<(), RandomAgentError>) {
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
