//! C2 required tests for the deterministic MaxN search.
//!
//! Every test drives the public `search_maxn_v1` entry point (or the frozen
//! `StaticEvaluatorV1` it relies on) and asserts the C2 contracts: terminal /
//! empty-root handling, legality, immutability of the input state, byte-for-byte
//! determinism, canonical tie-breaking, the tiny-budget fallback, the node
//! budget invariant, iterative-deepening commit semantics, turn-depth (not
//! ChooseNoble-ply) measurement, 2/3-player MaxN component selection, terminal
//! rank dominance, transposition-table correctness and utility-shape validity.

use splendor_catalog::all_nobles;
use splendor_core::{Action, FullState, GameConfig, GameEvent, Phase, PlayerId, Ruleset};
use splendor_search::{
    canonical_order, first_canonical_action, search_maxn_v1, SearchConfigV1, SearchError,
    SearchStopReasonV1, StaticEvaluatorV1, TERMINAL_RANK_UNIT,
};

fn new_state(player_count: u8, seed: u64) -> FullState {
    let (state, _) = FullState::new(GameConfig {
        player_count,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("valid game config");
    state
}

/// Drive a game to termination by always playing the canonical-first legal
/// action. Deterministic, so terminal states are reproducible.
fn drive_to_terminal(mut state: FullState) -> FullState {
    let mut guard = 0u32;
    while !state.is_terminal() && guard < 5000 {
        let legal = state.legal_actions();
        let action = first_canonical_action(&legal).expect("non-terminal state has legal actions");
        state.apply(action).expect("legal action applies");
        guard += 1;
    }
    state
}

/// Replicate the search's depth-1 root choice using the frozen evaluator. The
/// search maximizes the *current* player's utility component and breaks ties
/// by the canonical-first action, exactly as `search_maxn_v1` does at depth 1.
fn depth1_optimal_action(state: &FullState) -> Action {
    let current = state.current_player.index();
    let mut best_score = i64::MIN;
    let mut tied: Vec<Action> = Vec::new();
    for action in canonical_order(&state.legal_actions()) {
        let mut child = state.clone();
        child.apply(action).expect("legal action applies");
        let util = StaticEvaluatorV1::utilities(&child).expect("evaluator succeeds");
        let score = util[current];
        match score.cmp(&best_score) {
            std::cmp::Ordering::Greater => {
                best_score = score;
                tied = vec![action];
            }
            std::cmp::Ordering::Equal => {
                tied.push(action);
            }
            std::cmp::Ordering::Less => {}
        }
    }
    first_canonical_action(&tied).expect("tied set is non-empty")
}

/// A root state where the current player can buy a card that simultaneously
/// qualifies them for two nobles, forcing the `ChooseNoble` phase (no turn
/// advance) on the purchase action.
fn buy_triggers_noble_state() -> FullState {
    let mut state = new_state(2, 1);
    let nobles = all_nobles();
    let n1 = &nobles[0];
    let n2 = &nobles[1];
    let mut bonuses = [0u8; 5];
    for (c, slot) in bonuses.iter_mut().enumerate() {
        *slot = n1.requirements[c].max(n2.requirements[c]);
    }
    state.players[0].bonuses = bonuses;
    state.nobles = vec![n1.id, n2.id];
    // Enough gold that every market card is affordable, so a BuyMarket is legal
    // and is the canonical-first root action.
    state.players[0].tokens.gold = 10;
    state
}

#[test]
fn terminal_root_returns_terminal_state() {
    let terminal = drive_to_terminal(new_state(2, 4));
    assert!(terminal.is_terminal());
    let result = search_maxn_v1(&terminal, SearchConfigV1::default());
    assert!(matches!(result, Err(SearchError::TerminalState)));
}

#[test]
fn nonterminal_empty_legal_set_returns_no_legal_actions() {
    // A contrived non-terminal state in the ChooseNoble phase with no pending
    // nobles yields an empty legal action set.
    let mut state = new_state(2, 1);
    state.phase = Phase::ChooseNoble;
    state.pending_nobles.clear();
    assert!(!state.is_terminal());
    assert!(state.legal_actions().is_empty());
    let result = search_maxn_v1(&state, SearchConfigV1::default());
    assert!(matches!(result, Err(SearchError::NoLegalActions)));
}

#[test]
fn returned_action_belongs_to_root_legal_actions() {
    for &seed in &[1u64, 2, 3, 7, 42] {
        let state = new_state(2, seed);
        let config = SearchConfigV1 {
            max_depth_turns: 3,
            max_nodes: 20_000,
        };
        let result = search_maxn_v1(&state, config).unwrap();
        let legal = state.legal_actions();
        assert!(
            legal.contains(&result.action),
            "chosen action must be a member of the root legal actions"
        );
    }
}

#[test]
fn input_full_state_unchanged() {
    let state = new_state(2, 5);
    let before_hash = splendor_core::full_state_hash(&state);
    let before_legal = state.legal_actions();
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 20_000,
    };
    let _ = search_maxn_v1(&state, config).unwrap();
    assert_eq!(
        splendor_core::full_state_hash(&state),
        before_hash,
        "search must not mutate the input state"
    );
    assert_eq!(
        state.legal_actions(),
        before_legal,
        "search must not mutate the input state"
    );
}

#[test]
fn deterministic_byte_for_byte() {
    let state = new_state(2, 8);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 20_000,
    };
    let r1 = search_maxn_v1(&state, config).unwrap();
    let r2 = search_maxn_v1(&state, config).unwrap();
    assert_eq!(
        r1, r2,
        "identical (state, config) must yield identical result"
    );
}

#[test]
fn canonical_tie_selects_first_action() {
    let state = new_state(2, 7);
    let config = SearchConfigV1 {
        max_depth_turns: 1,
        max_nodes: 50_000,
    };
    let result = search_maxn_v1(&state, config).unwrap();
    let expected = depth1_optimal_action(&state);
    assert_eq!(result.action, expected);
}

#[test]
fn max_nodes_one_fallback_contract() {
    let state = new_state(2, 3);
    let config = SearchConfigV1 {
        max_depth_turns: 4,
        max_nodes: 1,
    };
    let result = search_maxn_v1(&state, config).unwrap();
    let expected = first_canonical_action(&state.legal_actions()).unwrap();
    assert_eq!(result.completed_depth_turns, 0);
    assert_eq!(result.action, expected);
    assert_eq!(result.principal_variation, vec![expected]);
    assert_eq!(
        result.utility_by_player,
        StaticEvaluatorV1::utilities(&state).unwrap()
    );
    assert_eq!(result.stop_reason, SearchStopReasonV1::NodeBudgetReached);
    assert!(result.stats.nodes_visited <= 1);
}

#[test]
fn nodes_visited_never_exceeds_budget() {
    let state = new_state(2, 6);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 5_000,
    };
    let result = search_maxn_v1(&state, config).unwrap();
    assert!(
        result.stats.nodes_visited <= config.max_nodes,
        "nodes_visited {} must not exceed budget {}",
        result.stats.nodes_visited,
        config.max_nodes
    );

    // Tiny budget fallback still respects the budget.
    let tiny = search_maxn_v1(
        &state,
        SearchConfigV1 {
            max_depth_turns: 4,
            max_nodes: 1,
        },
    )
    .unwrap();
    assert!(tiny.stats.nodes_visited <= 1);
}

#[test]
fn partial_iteration_does_not_replace_last_completed_result() {
    let state = new_state(2, 9);
    // Full-width MaxN enumerates every root child, so depth 1 needs
    // `1 + num_children` nodes. Measure that exactly, then give the depth-2
    // run precisely that budget: depth 1 completes, depth 2 cannot and must be
    // discarded without disturbing the committed depth-1 result.
    let full_depth1 = search_maxn_v1(
        &state,
        SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: 1_000_000,
        },
    )
    .unwrap();
    let depth1_nodes = full_depth1.stats.nodes_visited;

    let depth2 = search_maxn_v1(
        &state,
        SearchConfigV1 {
            max_depth_turns: 2,
            max_nodes: depth1_nodes,
        },
    )
    .unwrap();
    let depth1 = search_maxn_v1(
        &state,
        SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: depth1_nodes,
        },
    )
    .unwrap();
    assert_eq!(depth2.action, depth1.action);
    assert_eq!(depth2.completed_depth_turns, 1);
    assert_eq!(depth2.stop_reason, SearchStopReasonV1::NodeBudgetReached);
}

#[test]
fn depth_measured_by_completed_turns_not_choose_noble_plies() {
    let state = buy_triggers_noble_state();
    // Sanity: the canonical-first root action really triggers ChooseNoble.
    let mut probe = state.clone();
    let first = first_canonical_action(&probe.legal_actions()).unwrap();
    probe.apply(first).unwrap();
    assert_eq!(probe.phase, Phase::ChooseNoble);

    // At depth 1, buying a card that triggers a noble must be explored *through*
    // the noble choice within the same turn-depth: the principal variation
    // contains the ChooseNoble action, i.e. the ChooseNoble step did not consume
    // a turn of depth budget.
    let result = search_maxn_v1(
        &state,
        SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: 50_000,
        },
    )
    .unwrap();
    assert!(
        result.principal_variation.len() >= 2,
        "depth-1 search must look past the ChooseNoble continuation"
    );
    assert!(
        result
            .principal_variation
            .iter()
            .any(|a| matches!(a, Action::ChooseNoble { .. })),
        "the principal variation must include the ChooseNoble step"
    );
}

#[test]
fn maxn_two_player() {
    let state = new_state(2, 10);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 20_000,
    };
    let result = search_maxn_v1(&state, config).unwrap();
    assert_eq!(result.utility_by_player.len(), 2);
    assert_eq!(result.action, depth1_optimal_action(&state));
}

#[test]
fn maxn_three_player_selects_current_component() {
    let state = new_state(3, 12);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 20_000,
    };
    let result = search_maxn_v1(&state, config).unwrap();
    assert_eq!(result.utility_by_player.len(), 3);
    // The chosen root action must maximize the *current* player's component.
    assert_eq!(result.action, depth1_optimal_action(&state));
}

#[test]
fn terminal_rank_dominates_static_progress() {
    let terminal = drive_to_terminal(new_state(2, 4));
    assert!(terminal.is_terminal());
    let util = StaticEvaluatorV1::utilities(&terminal).unwrap();
    let ranks = &terminal.result.as_ref().unwrap().ranks;
    let winner = ranks
        .iter()
        .position(|&r| r == 0)
        .expect("terminal state has a rank-0 winner");
    let winner_util = util[winner];
    assert!(winner_util > 0, "winner utility must be positive");
    for (i, &u) in util.iter().enumerate() {
        if i != winner {
            assert!(u < 0, "loser {i} should be negative, got {u}");
            assert!(
                winner_util - u > TERMINAL_RANK_UNIT / 2,
                "terminal rank must dominate static progress"
            );
        }
    }
}

#[test]
fn transposition_table_hits_and_stays_deterministic() {
    let state = new_state(2, 11);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 20_000,
    };
    let r1 = search_maxn_v1(&state, config).unwrap();
    let r2 = search_maxn_v1(&state, config).unwrap();
    assert_eq!(r1, r2, "search must be deterministic across runs");
    assert!(
        r1.stats.transposition_hits > 0,
        "deep search should hit the transposition table"
    );
    assert!(
        r1.stats.transposition_entries > 0,
        "transposition table should store entries"
    );
}

#[test]
fn partial_subtree_not_cached_determinism() {
    let state = new_state(2, 13);
    let config = SearchConfigV1 {
        max_depth_turns: 4,
        max_nodes: 150,
    };
    let r1 = search_maxn_v1(&state, config).unwrap();
    let r2 = search_maxn_v1(&state, config).unwrap();
    assert_eq!(r1, r2, "partial iterations must not corrupt TT results");
    assert_eq!(
        r1.stats, r2.stats,
        "stats including TT counts must be identical"
    );
    assert_eq!(r1.stop_reason, SearchStopReasonV1::NodeBudgetReached);
}

#[test]
fn event_log_only_differences_do_not_alter_result() {
    let state = new_state(2, 5);
    let config = SearchConfigV1 {
        max_depth_turns: 2,
        max_nodes: 5_000,
    };
    let r1 = search_maxn_v1(&state, config).unwrap();
    // The event log is intentionally excluded from the state hash, so a
    // log-only difference must not change the search result.
    let mut state2 = state.clone();
    state2.log.push(GameEvent::TurnAdvanced {
        next_player: PlayerId(1),
    });
    let r2 = search_maxn_v1(&state2, config).unwrap();
    assert_eq!(r1, r2);
}

#[test]
fn utility_shape_matches_player_count() {
    for &seed in &[1u64, 2, 3, 7, 42] {
        let state = new_state(3, seed);
        let config = SearchConfigV1 {
            max_depth_turns: 2,
            max_nodes: 5_000,
        };
        let result = search_maxn_v1(&state, config).unwrap();
        assert_eq!(
            result.utility_by_player.len(),
            state.player_count() as usize
        );
        let tiny = search_maxn_v1(
            &state,
            SearchConfigV1 {
                max_depth_turns: 4,
                max_nodes: 1,
            },
        )
        .unwrap();
        assert_eq!(tiny.utility_by_player.len(), state.player_count() as usize);
    }
}

#[test]
fn principal_variation_is_a_legal_sequence() {
    // Use a depth/budget large enough that iterative deepening and the exact
    // TT both fire, so the returned PV is exercised through the TT path and
    // not only through pure recursion.
    let state = new_state(2, 11);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 20_000,
    };
    let result = search_maxn_v1(&state, config).unwrap();

    assert!(
        result.stats.transposition_hits > 0,
        "test must exercise the TT path; got 0 hits"
    );
    assert!(
        !result.principal_variation.is_empty(),
        "non-fallback search must return a non-empty principal variation"
    );
    assert_eq!(
        result.principal_variation[0], result.action,
        "PV head must equal the chosen root action"
    );

    // Replay every PV action from a root clone. Each step must be legal in the
    // state reached so far; this catches a TT-truncated intermediate action
    // (the C2 P1) because the next PV entry would then be illegal, and it also
    // catches a PV that skips a required ChooseNoble continuation.
    let mut cursor = state.clone();
    for (i, &action) in result.principal_variation.iter().enumerate() {
        let legal = cursor.legal_actions();
        assert!(
            legal.contains(&action),
            "principal_variation[{i}] = {action:?} is not legal in the state \
             reached after applying the previous PV prefix; legal = {legal:?}"
        );
        cursor.apply(action).unwrap_or_else(|e| {
            panic!("principal_variation[{i}] = {action:?} failed to apply: {e}")
        });
    }
}
