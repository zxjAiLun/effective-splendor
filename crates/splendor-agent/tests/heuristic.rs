//! Behavioral and transcript tests for the deterministic heuristic policy.
//!
//! The policy is exercised purely through its public boundary: a
//! [`DecisionContext`] built from a real `FullState` observation (FullState is
//! used only on the test side to construct legal observations/transcripts), and
//! the `run_heuristic_agent` stdio runtime. The policy itself never sees
//! `FullState`, the seed, blind reserves, or the deck order.

use splendor_agent::{
    AgentPolicy, DecisionContext, HeuristicAgentPolicy, PublicRequestMeta, StableRng,
    HEURISTIC_AGENT_NAME, HEURISTIC_AGENT_VERSION,
};
use splendor_catalog::{CardId, Tier};
use splendor_core::{
    observation_hash, FullState, GameConfig, NobleId, Observation, PlayerId, ReservedCard,
};
use splendor_protocol::{
    ClientMessage, ObservationMeta, RecipientMeta, RequestMeta, ServerMessage,
};

use splendor_core::{Action, Gems};

/// Build an observation + legal actions from a (possibly mutated) state.
fn snapshot(state: FullState) -> (Observation, Vec<Action>) {
    let obs = state.observation(PlayerId(0));
    let actions = state.legal_actions();
    (obs, actions)
}

fn decide(obs: &Observation, actions: &[Action], seed: u64) -> Action {
    let mut rng = StableRng::new(seed);
    let ctx = DecisionContext {
        observation: obs.clone(),
        legal_actions: actions,
        meta: PublicRequestMeta {
            game_id: "t".into(),
            recipient_seat: PlayerId(0),
            request_id: 1,
            observation_hash: observation_hash(obs),
        },
        rng: &mut rng,
    };
    HeuristicAgentPolicy::new().choose_action(ctx).unwrap()
}

fn clear_market(state: &mut FullState) {
    for tier in Tier::ALL {
        for slot in 0..4usize {
            state.market[tier.index()][slot] = None;
        }
    }
}

// ---------------------------------------------------------------------------
// Policy behavior (9 required cases)
// ---------------------------------------------------------------------------

#[test]
fn buying_a_scoring_card_beats_take_and_reserve() {
    let (mut state, _) = FullState::new(GameConfig {
        seed: 5,
        ..Default::default()
    })
    .expect("setup");
    clear_market(&mut state);
    // A tier-2 scoring card at tier2/slot0.
    state.market[Tier::Two.index()][0] = Some(CardId(40));
    state.bank = Gems {
        white: 4,
        ..Gems::ZERO
    };
    state.players[0].tokens = Gems::ZERO;
    // Bonuses make card 40 (blue2/green2/red3) affordable.
    state.players[0].bonuses = [5, 2, 2, 3, 5];

    let (obs, actions) = snapshot(state);
    let chosen = decide(&obs, &actions, 1);
    assert!(
        matches!(
            chosen,
            Action::BuyMarket {
                tier: Tier::Two,
                slot: 0
            }
        ),
        "expected the scoring buy to win, got {chosen:?}"
    );
}

#[test]
fn noble_completing_purchase_is_preferred() {
    let (mut state, _) = FullState::new(GameConfig {
        seed: 9,
        ..Default::default()
    })
    .expect("setup");
    clear_market(&mut state);
    // cardA: white-bonus card at tier1/slot0 (completes a noble); cardB:
    // green-bonus card at tier1/slot1 (does not).
    state.market[Tier::One.index()][0] = Some(CardId(24)); // white bonus, cost blue3
    state.market[Tier::One.index()][1] = Some(CardId(32)); // green bonus, cost black3
                                                           // Noble 0 requires white3/blue3/green3; player is one white short.
    state.nobles = vec![NobleId(0)];
    state.players[0].bonuses = [2, 3, 3, 5, 5]; // white2, blue3, green3
    state.players[0].tokens = Gems::ZERO;
    state.bank = Gems {
        white: 4,
        ..Gems::ZERO
    };

    let (obs, actions) = snapshot(state);
    let chosen = decide(&obs, &actions, 1);
    assert!(
        matches!(
            chosen,
            Action::BuyMarket {
                tier: Tier::One,
                slot: 0
            }
        ),
        "expected the noble-completing buy (slot0) to win, got {chosen:?}"
    );
}

#[test]
fn take_tokens_prefers_larger_public_deficit_reduction() {
    let (mut state, _) = FullState::new(GameConfig {
        seed: 13,
        ..Default::default()
    })
    .expect("setup");
    clear_market(&mut state);
    // One target card needing white (cost white3); player has no white.
    state.market[Tier::One.index()][0] = Some(CardId(28));
    state.players[0].bonuses = [0, 5, 5, 5, 5]; // white0, others covered
    state.players[0].tokens = Gems::ZERO;
    state.bank = Gems {
        white: 4,
        black: 4,
        ..Gems::ZERO
    };

    let (obs, actions) = snapshot(state);
    let chosen = decide(&obs, &actions, 1);
    // Taking 2 white reduces the white deficit by 2; taking black (or a mixed
    // take) reduces it less.
    assert!(
        matches!(
            chosen,
            Action::TakeTokens {
                take,
                give_back,
            } if take.white == 2 && give_back.total() == 0
        ),
        "expected take-2-white to win on deficit reduction, got {chosen:?}"
    );
}

#[test]
fn visible_reserve_beats_blind_reserve_when_public_value_is_higher() {
    let (mut state, _) = FullState::new(GameConfig {
        seed: 17,
        ..Default::default()
    })
    .expect("setup");
    // Empty bank: no take actions. No tokens: no affordable buys. Reserved<3:
    // reserve is legal. So the choice is between visible and blind reserves.
    state.bank = Gems::ZERO;
    state.players[0].tokens = Gems::ZERO;

    let (obs, actions) = snapshot(state);
    // Sanity: there must be both a visible and a blind reserve in the set.
    let has_visible = actions
        .iter()
        .any(|a| matches!(a, Action::ReserveMarket { .. }));
    let has_blind = actions
        .iter()
        .any(|a| matches!(a, Action::ReserveDeck { .. }));
    assert!(
        has_visible && has_blind,
        "scenario must offer both reserves"
    );
    let chosen = decide(&obs, &actions, 1);
    assert!(
        matches!(chosen, Action::ReserveMarket { .. }),
        "expected visible reserve to beat blind reserve, got {chosen:?}"
    );
}

#[test]
fn pass_is_selected_when_it_is_the_only_legal_action() {
    let (mut state, _) = FullState::new(GameConfig {
        seed: 19,
        ..Default::default()
    })
    .expect("setup");
    // Empty bank (no takes) + full reserve (no reserves) + no tokens (no buys)
    // => Pass is the only legal main action.
    state.bank = Gems::ZERO;
    state.players[0].tokens = Gems::ZERO;
    state.players[0].reserved = vec![
        ReservedCard {
            card: CardId(0),
            from_deck: false,
        },
        ReservedCard {
            card: CardId(1),
            from_deck: false,
        },
        ReservedCard {
            card: CardId(2),
            from_deck: false,
        },
    ];

    let (obs, actions) = snapshot(state);
    assert_eq!(
        actions.len(),
        1,
        "expected exactly one legal action (Pass), got {actions:?}"
    );
    let chosen = decide(&obs, &actions, 1);
    assert_eq!(chosen, Action::Pass, "expected Pass, got {chosen:?}");
}

#[test]
fn same_seed_same_context_same_action() {
    // Determinism contract: the same (seed, context) always yields the same
    // action. Two independent builds from the same config seed produce an
    // identical observation and legal set, and the policy is a pure function of
    // (observation, legal_actions, seed).
    let (state1, _) = FullState::new(GameConfig {
        seed: 23,
        ..Default::default()
    })
    .expect("setup");
    let (obs1, actions1) = snapshot(state1);
    let (state2, _) = FullState::new(GameConfig {
        seed: 23,
        ..Default::default()
    })
    .expect("setup");
    let (obs2, actions2) = snapshot(state2);
    assert_eq!(obs1, obs2, "same config seed => identical observation");
    assert_eq!(
        actions1, actions2,
        "same config seed => identical legal set"
    );

    let a = decide(&obs1, &actions1, 7);
    let b = decide(&obs2, &actions2, 7);
    let c = decide(&obs1, &actions1, 7);
    assert_eq!(a, b, "same seed + same context => same action");
    assert_eq!(a, c, "re-invoking with the same seed is stable");
    assert!(
        actions1.contains(&a),
        "chosen action must belong to the legal set"
    );
}

#[test]
fn every_returned_action_belongs_to_legal_actions() {
    for seed in 0..12u64 {
        let (state, _) = FullState::new(GameConfig {
            seed,
            ..Default::default()
        })
        .expect("setup");
        let (obs, actions) = snapshot(state);
        let chosen = decide(&obs, &actions, seed.wrapping_add(1));
        assert!(
            actions.contains(&chosen),
            "chosen {chosen:?} not in legal set for seed {seed}"
        );
    }
}

// ---------------------------------------------------------------------------
// Transcript / stdio runtime tests
// ---------------------------------------------------------------------------

fn terminal_result() -> splendor_core::GameResult {
    splendor_core::GameResult {
        scores: vec![15, 3],
        ranks: vec![1, 2],
        winners: vec![PlayerId(0)],
        reason: splendor_core::TerminalReason::PrestigeThreshold,
    }
}

fn scenario() -> (String, Vec<String>) {
    let game_id = "heur-test".to_string();
    let (state, _) = FullState::new(GameConfig {
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
        splendor_core::ruleset_fingerprint(&state.ruleset),
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

fn run_over(
    lines: &[String],
    seed: u64,
) -> (
    Vec<String>,
    Vec<String>,
    Result<(), splendor_agent::AgentError>,
) {
    let input = lines.join("\n") + "\n";
    let mut out = Vec::new();
    let mut err = Vec::new();
    let res = splendor_agent::run_heuristic_agent(input.as_bytes(), &mut out, &mut err, seed);
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
fn heuristic_agent_declares_heuristic_identity() {
    let (_, lines) = scenario();
    let (out, _, res) = run_over(&lines, 1);
    res.unwrap();
    let hello = serde_json::from_str::<ClientMessage>(&out[0]).unwrap();
    match hello {
        ClientMessage::Hello {
            agent_name,
            agent_version,
            ..
        } => {
            assert_eq!(agent_name, HEURISTIC_AGENT_NAME);
            assert_eq!(agent_version, HEURISTIC_AGENT_VERSION);
            assert_ne!(agent_name, "splendor-cli-random");
        }
        _ => panic!("first stdout line must be Client Hello"),
    }
}

#[test]
fn heuristic_agent_stdout_is_client_ndjson_only() {
    let (_, lines) = scenario();
    let (out, _, res) = run_over(&lines, 1);
    res.unwrap();
    for line in &out {
        serde_json::from_str::<ClientMessage>(line)
            .unwrap_or_else(|e| panic!("non-client line on stdout: {line} ({e})"));
    }
}

#[test]
fn heuristic_agent_same_seed_same_transcript_is_identical() {
    let (_, lines) = scenario();
    let (out_a, _, res_a) = run_over(&lines, 42);
    let (out_b, _, res_b) = run_over(&lines, 42);
    assert!(res_a.is_ok() && res_b.is_ok());
    assert_eq!(out_a, out_b, "same seed must yield identical stdout");
}
