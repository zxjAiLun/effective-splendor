//! M06 C3 — exact-TT conformance differential corpus.
//!
//! Proves that the production MaxN search (exact TT, iterative deepening,
//! shared node budget) returns the *same* chosen action, utility vector and
//! complete principal variation as an independent no-TT reference solver for a
//! fixed corpus. TT hits only change the number of visited nodes, never the
//! MaxN result. Also locks the frozen search statistics identities.

mod support;

use splendor_core::{Action, FullState};
use splendor_search::{search_maxn_v1, SearchConfigV1, SearchStopReasonV1};
use support::{buy_triggers_noble_state, fresh_state, mid_game_state, reference_maxn};

/// Assert that production search matches the no-TT reference for `state` at
/// `depth`. Returns the production result for further stats checks.
fn assert_matches_reference(state: &FullState, depth: u8) -> splendor_search::SearchResultV1 {
    assert!(!state.is_terminal(), "corpus root must be non-terminal");
    let config = SearchConfigV1 {
        max_depth_turns: depth,
        max_nodes: 500_000,
    };
    let result = search_maxn_v1(state, config).expect("search must succeed");
    assert_eq!(
        result.stop_reason,
        SearchStopReasonV1::DepthLimitReached,
        "depth {depth} must complete within budget"
    );
    assert_eq!(
        result.completed_depth_turns, depth,
        "completed depth must equal requested depth"
    );
    let (ref_util, ref_pv) = reference_maxn(state, depth).expect("reference must solve");
    // action equality
    assert_eq!(
        result.action,
        *ref_pv
            .first()
            .expect("reference PV is non-empty at the root"),
        "chosen action must match the reference"
    );
    // utility equality
    assert_eq!(
        result.utility_by_player, ref_util,
        "utility_by_player must match the reference"
    );
    // PV equality (the complete principal variation)
    assert_eq!(
        result.principal_variation, ref_pv,
        "principal_variation must match the reference"
    );
    result
}

#[test]
fn differential_two_player_seed1_depth1() {
    let state = fresh_state(2, 1);
    assert_matches_reference(&state, 1);
}

#[test]
fn differential_two_player_seed7_depth2() {
    let state = fresh_state(2, 7);
    assert_matches_reference(&state, 2);
}

#[test]
fn differential_two_player_transposition_heavy_seed11_depth2() {
    // Depth-2 from a fresh state is too shallow to guarantee transpositions;
    // this case still proves the differential equality holds on a position that
    // is transposition-prone at greater depth. TT-hit coverage is enforced
    // separately by `at_least_one_corpus_case_exercises_tt_hit`.
    let state = fresh_state(2, 11);
    assert_matches_reference(&state, 2);
}

#[test]
fn differential_three_player_seed12_depth1() {
    let state = fresh_state(3, 12);
    assert_matches_reference(&state, 1);
}

#[test]
fn differential_three_player_seed12_depth2() {
    let state = fresh_state(3, 12);
    assert_matches_reference(&state, 2);
}

#[test]
fn differential_four_player_depth1() {
    let state = fresh_state(4, 99);
    assert_matches_reference(&state, 1);
}

#[test]
fn differential_buy_choose_noble_continuation_depth1() {
    let state = buy_triggers_noble_state();
    let result = assert_matches_reference(&state, 1);
    assert!(
        result
            .principal_variation
            .iter()
            .any(|a| matches!(a, Action::ChooseNoble { .. })),
        "PV must include the ChooseNoble continuation"
    );
}

#[test]
fn differential_mid_game_position_depth2() {
    let state = mid_game_state(2, 3, 6);
    assert!(!state.is_terminal(), "mid-game state must not be terminal");
    assert_matches_reference(&state, 2);
}

/// Guarantees the differential proof is not only covering the no-TT-hit path:
/// this depth-3 transposition-heavy position (seed 11) is known to exercise the
/// exact TT, and it must still match the no-TT reference exactly.
#[test]
fn at_least_one_corpus_case_exercises_tt_hit() {
    let state = fresh_state(2, 11);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 200_000,
    };
    let result = search_maxn_v1(&state, config).expect("search must succeed");
    assert_eq!(
        result.stop_reason,
        SearchStopReasonV1::DepthLimitReached,
        "depth 3 must complete within budget"
    );
    assert!(
        result.stats.transposition_hits > 0,
        "this corpus case must exercise the TT"
    );
    let (ref_util, ref_pv) = reference_maxn(&state, 3).expect("reference must solve");
    assert_eq!(result.action, *ref_pv.first().unwrap());
    assert_eq!(result.utility_by_player, ref_util);
    assert_eq!(result.principal_variation, ref_pv);
}

/// Frozen search statistics identities, across the whole corpus.
#[test]
fn stats_classification_identity_holds() {
    let cases: Vec<(FullState, u8)> = vec![
        (fresh_state(2, 1), 1),
        (fresh_state(2, 7), 2),
        (fresh_state(2, 11), 2),
        (fresh_state(3, 12), 2),
        (fresh_state(4, 99), 1),
        (buy_triggers_noble_state(), 1),
        (mid_game_state(2, 3, 6), 2),
    ];
    let mut saw_tt_hit = false;
    for (state, depth) in &cases {
        let config = SearchConfigV1 {
            max_depth_turns: *depth,
            max_nodes: 500_000,
        };
        let result = search_maxn_v1(state, config).expect("search must succeed");
        let s = &result.stats;
        assert!(
            s.nodes_visited <= 500_000,
            "nodes_visited {} must not exceed budget",
            s.nodes_visited
        );
        assert!(
            s.transposition_hits <= s.nodes_visited,
            "transposition_hits must not exceed nodes_visited"
        );
        assert!(
            s.transposition_entries <= s.nodes_visited,
            "transposition_entries must not exceed nodes_visited"
        );
        // Every entered node is exactly one of: exact TT hit, terminal/depth
        // leaf, or expanded non-leaf.
        assert_eq!(
            s.nodes_visited,
            s.nodes_expanded + s.leaf_evaluations + s.transposition_hits,
            "classification identity violated"
        );
        if s.transposition_hits > 0 {
            saw_tt_hit = true;
        }
    }
    assert!(
        saw_tt_hit,
        "the corpus must exercise at least one transposition-table hit"
    );
}

/// The tiny-budget fallback satisfies the same classification identity and the
/// fixed fallback node accounting (root counts as one expanded node; the extra
/// static evaluation of the root is NOT a recursion leaf).
#[test]
fn tiny_budget_fallback_satisfies_stats_identity() {
    let state = fresh_state(2, 3);
    let config = SearchConfigV1 {
        max_depth_turns: 4,
        max_nodes: 1,
    };
    let result = search_maxn_v1(&state, config).expect("search must succeed");
    let s = &result.stats;
    assert_eq!(
        s.nodes_visited, 1,
        "tiny budget visits exactly the root node"
    );
    assert_eq!(s.nodes_expanded, 1, "root counts as expanded");
    assert_eq!(
        s.leaf_evaluations, 0,
        "fallback's extra root static eval is not a recursion leaf"
    );
    assert_eq!(s.transposition_hits, 0);
    assert_eq!(
        s.nodes_visited,
        s.nodes_expanded + s.leaf_evaluations + s.transposition_hits,
        "tiny-budget classification identity"
    );
    assert_eq!(result.stop_reason, SearchStopReasonV1::NodeBudgetReached);
}

/// Third-layer re-affirmation (public API): the returned principal variation
/// is fully legal and applyable from a root clone, and does not skip a required
/// `ChooseNoble` continuation. Runs through the TT path (hits > 0).
#[test]
fn public_pv_is_fully_legal_and_applyable() {
    let state = fresh_state(2, 11);
    let config = SearchConfigV1 {
        max_depth_turns: 3,
        max_nodes: 200_000,
    };
    let result = search_maxn_v1(&state, config).expect("search must succeed");
    assert!(
        result.stats.transposition_hits > 0,
        "test must exercise the TT path; got 0 hits"
    );
    assert!(
        !result.principal_variation.is_empty(),
        "non-fallback search must return a non-empty PV"
    );
    assert_eq!(
        result.principal_variation[0], result.action,
        "PV head must equal the chosen root action"
    );
    let mut cursor = state.clone();
    for (i, &action) in result.principal_variation.iter().enumerate() {
        let legal = cursor.legal_actions();
        assert!(
            legal.contains(&action),
            "principal_variation[{i}] = {action:?} is not legal in the state \
             reached after the previous PV prefix; legal = {legal:?}"
        );
        cursor.apply(action).unwrap_or_else(|e| {
            panic!("principal_variation[{i}] = {action:?} failed to apply: {e}")
        });
    }
}
