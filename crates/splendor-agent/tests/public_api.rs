//! External (integration) tests for the reusable agent SDK surface.
//!
//! These run from a *separate* crate, so they can only touch the public API of
//! `splendor_agent` (plus the public `splendor_core` / `splendor_protocol`
//! scaffolding needed to build a server transcript). That is the whole point:
//! they lock the SDK's public contract the way a third-party policy author would
//! experience it.

use splendor_agent::{
    run_agent, run_random_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext,
    RANDOM_AGENT_NAME,
};
use splendor_core::{
    observation_hash, ruleset_fingerprint, Action, FullState, GameConfig, GameResult, PlayerId,
    TerminalReason, VisibleEvent, ENGINE_VERSION,
};
use splendor_protocol::{
    ClientMessage, ObservationMeta, RecipientMeta, RequestMeta, ServerMessage,
};

// ---------------------------------------------------------------------------
// Transcript scaffolding (mirrors the runtime unit-test scenario).
// ---------------------------------------------------------------------------

fn scenario() -> (String, Vec<String>) {
    let game_id = "public-api-test".to_string();
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

fn terminal_result() -> GameResult {
    GameResult {
        scores: vec![15, 3],
        ranks: vec![1, 2],
        winners: vec![PlayerId(0)],
        reason: TerminalReason::PrestigeThreshold,
    }
}

fn run_over(
    lines: &[String],
    identity: AgentIdentity<'_>,
    seed: u64,
) -> (Vec<String>, String, Result<(), AgentError>) {
    let input = lines.join("\n") + "\n";
    let mut out = Vec::new();
    let mut err = Vec::new();
    let res = run_agent(
        input.as_bytes(),
        &mut out,
        &mut err,
        identity,
        seed,
        CustomPolicy,
    );
    let out_lines = String::from_utf8(out)
        .unwrap()
        .lines()
        .map(str::to_string)
        .collect();
    let err_text = String::from_utf8(err).unwrap();
    (out_lines, err_text, res)
}

// ---------------------------------------------------------------------------
// Custom policies exercised from *outside* the crate.
// ---------------------------------------------------------------------------

/// A policy that uses the public `StableRng::index` to pick a legal action.
struct CustomPolicy;

impl AgentPolicy for CustomPolicy {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        // This is only possible because `StableRng::index` is now a public,
        // stable method (Blocker 2). A `pub(crate)` method would fail to
        // compile here.
        let idx = context.rng.index(context.legal_actions.len());
        Ok(context.legal_actions[idx])
    }
}

/// A policy that returns an action that is NOT in the server-certified legal set.
struct BrokenPolicy;

impl AgentPolicy for BrokenPolicy {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, _context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        // `Pass` is only legal when no other main action exists; in a normal
        // starting state it is outside `legal_actions` (asserted below).
        Ok(Action::Pass)
    }
}

/// A policy that pins the runtime's cumulative Event/ActionApplied projection.
struct HistoryPolicy;

impl AgentPolicy for HistoryPolicy {
    type Error = String;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if !matches!(
            context.visible_history,
            [
                VisibleEvent::GameStarted { .. },
                VisibleEvent::ActionApplied {
                    player: PlayerId(1),
                    action: Action::Pass
                }
            ]
        ) {
            return Err("visible history did not preserve wire event order".to_string());
        }
        Ok(context.legal_actions[0])
    }
}

// ---------------------------------------------------------------------------
// Blocker 1: custom identity is declared; random identity is byte-compatible.
// ---------------------------------------------------------------------------

#[test]
fn custom_policy_declares_custom_identity() {
    let (_, lines) = scenario();
    let identity = AgentIdentity {
        name: "heuristic-v1",
        version: "0.1.0",
    };
    let (out, _, res) = run_over(&lines, identity, 42);
    assert!(res.is_ok(), "custom run should complete cleanly: {res:?}");
    assert!(!out.is_empty(), "expected at least a hello line");
    let hello_line = &out[0];
    // The custom Client Hello must NOT impersonate the reference random agent.
    assert!(
        !hello_line.contains(RANDOM_AGENT_NAME),
        "custom hello must not contain '{RANDOM_AGENT_NAME}': {hello_line}"
    );
    let hello = serde_json::from_str::<ClientMessage>(hello_line).expect("hello parses");
    match hello {
        ClientMessage::Hello {
            agent_name,
            agent_version,
            ..
        } => {
            assert_eq!(agent_name, "heuristic-v1");
            assert_eq!(agent_version, "0.1.0");
            assert_ne!(agent_name, RANDOM_AGENT_NAME);
        }
        other => panic!("first line should be Hello, got {other:?}"),
    }
}

#[test]
fn random_agent_identity_remains_byte_compatible() {
    let (_, lines) = scenario();
    let input = lines.join("\n") + "\n";
    let mut out = Vec::new();
    let mut err = Vec::new();
    let res = run_random_agent(input.as_bytes(), &mut out, &mut err, 42);
    assert!(res.is_ok(), "random agent run should succeed: {res:?}");
    let out_lines = String::from_utf8(out)
        .unwrap()
        .lines()
        .map(str::to_string)
        .collect::<Vec<_>>();
    let hello = serde_json::from_str::<ClientMessage>(&out_lines[0]).expect("hello parses");
    match hello {
        ClientMessage::Hello {
            agent_name,
            agent_version,
            ..
        } => {
            assert_eq!(agent_name, RANDOM_AGENT_NAME);
            assert_eq!(agent_version, ENGINE_VERSION);
        }
        other => panic!("first line should be Hello, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Blocker 2: external policy can use the public RNG and run a full transcript.
// ---------------------------------------------------------------------------

#[test]
fn external_policy_uses_public_rng() {
    let (game_id, lines) = scenario();
    // Recover the legal set from the request line to prove the chosen action
    // came from the public RNG and is genuinely legal.
    let legal = match splendor_protocol::parse_server_line(&lines[3]).unwrap() {
        ServerMessage::RequestAction { legal_actions, .. } => legal_actions,
        _ => panic!("expected request_action"),
    };
    let _ = game_id;
    let identity = AgentIdentity {
        name: "rng-user",
        version: "0.0.1",
    };
    let (out, _, res) = run_over(&lines, identity, 7);
    assert!(res.is_ok(), "external policy run should succeed: {res:?}");
    // hello + action.
    assert_eq!(out.len(), 2);
    let action_line = &out[1];
    let chosen = match serde_json::from_str::<ClientMessage>(action_line).unwrap() {
        ClientMessage::Action { action, .. } => action,
        _ => panic!("expected client action"),
    };
    assert!(
        legal.contains(&chosen),
        "external policy must pick an action inside the certified legal set"
    );
}

// ---------------------------------------------------------------------------
// Blocker 3: runtime rejects a policy action outside legal_actions.
// ---------------------------------------------------------------------------

#[test]
fn policy_action_must_belong_to_legal_actions() {
    let (_, lines) = scenario();
    // Confirm the broken policy's chosen action really is outside the legal set
    // for this transcript, so the test is meaningful.
    let legal = match splendor_protocol::parse_server_line(&lines[3]).unwrap() {
        ServerMessage::RequestAction { legal_actions, .. } => legal_actions,
        _ => panic!("expected request_action"),
    };
    assert!(
        !legal.contains(&Action::Pass),
        "Pass must be illegal in this scenario for the test to be meaningful"
    );

    let identity = AgentIdentity {
        name: "broken",
        version: "0",
    };
    let input = lines.join("\n") + "\n";
    let mut out = Vec::new();
    let mut err = Vec::new();
    let res = run_agent(
        input.as_bytes(),
        &mut out,
        &mut err,
        identity,
        42,
        BrokenPolicy,
    );

    // 1) Result is the Policy variant.
    let agent_err = res.expect_err("illegal policy action must be rejected");
    assert!(
        matches!(agent_err, AgentError::Policy(_)),
        "expected AgentError::Policy, got {agent_err:?}"
    );

    // 2) Diagnostics carry the stable error text.
    let err_text = String::from_utf8(err).unwrap();
    assert!(
        err_text.contains("policy returned an action outside legal_actions"),
        "diagnostics should carry the stable text, got: {err_text}"
    );

    // 3) stdout may have a Client Hello but must NOT contain a Client Action;
    //    the runtime must not ship the illegal action to the server.
    let out_str = String::from_utf8(out).unwrap();
    assert!(
        !out_str.contains("\"type\":\"action\""),
        "runtime must not emit a Client Action for an illegal policy output: {out_str}"
    );
    // The hello (sent before the request) must still be present.
    assert!(
        out_str.contains("\"type\":\"hello\""),
        "runtime should have sent hello before rejecting the bad action: {out_str}"
    );
}

#[test]
fn runtime_exposes_cumulative_visible_event_history() {
    let game_id = "history-test";
    let (state, _) = FullState::new(GameConfig::default()).unwrap();
    let seat = PlayerId(0);
    let observation = state.observation(seat);
    let observation_hash = observation_hash(&observation);
    let lines = [
        ServerMessage::hello(
            game_id,
            splendor_core::RULESET_BASE_V1.0,
            splendor_core::CATALOG_VERSION,
            ruleset_fingerprint(&state.ruleset),
        ),
        ServerMessage::GameStart {
            meta: RecipientMeta::new(game_id, 1, seat),
            player_count: 2,
            seed_commitment: "commitment".to_string(),
        },
        ServerMessage::Event {
            meta: RecipientMeta::new(game_id, 2, seat),
            event: VisibleEvent::GameStarted {
                player_count: 2,
                ruleset: splendor_core::RULESET_BASE_V1.0.to_string(),
            },
        },
        ServerMessage::ActionApplied {
            meta: RecipientMeta::new(game_id, 3, seat),
            actor_player_id: 1,
            action: Action::Pass,
        },
        ServerMessage::Observation {
            meta: ObservationMeta::new(game_id, 4, seat, observation_hash.clone()),
            observation,
        },
        ServerMessage::RequestAction {
            meta: RequestMeta::new(game_id, 5, seat, 1, observation_hash),
            deadline_ms: 1_000,
            legal_actions: state.legal_actions(),
        },
        ServerMessage::GameEnd {
            meta: RecipientMeta::new(game_id, 6, seat),
            result: terminal_result(),
        },
    ]
    .iter()
    .map(|message| message.to_json_line().unwrap())
    .collect::<Vec<_>>();
    let input = lines.join("\n") + "\n";
    let mut output = Vec::new();
    let mut diagnostics = Vec::new();

    let result = run_agent(
        input.as_bytes(),
        &mut output,
        &mut diagnostics,
        AgentIdentity {
            name: "history-policy",
            version: "1",
        },
        0,
        HistoryPolicy,
    );

    assert!(result.is_ok(), "history policy failed: {result:?}");
    assert!(diagnostics.is_empty());
}
