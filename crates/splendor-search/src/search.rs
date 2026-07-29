//! Deterministic MaxN search (v1).
//!
//! `search_maxn_v1` is the single public entry point. It performs iterative
//! deepening over completed player turns with a single shared node budget and
//! an exact-only transposition table. The input `FullState` is never mutated;
//! every child is explored from a clone.
//!
//! Determinism invariants (M06 C2, frozen):
//! - Pure integers only; no RNG, threads, wall clock or hash-map-order
//!   dependence in the result.
//! - Depth is measured in *completed player turns*. A turn completes only when
//!   the core engine emits a `TurnAdvanced` event; choosing a noble does not
//!   advance the turn, so the `ChooseNoble` action does not consume depth.
//! - The node budget is shared across all iterative-deepening iterations and
//!   is never reset per iteration. Only fully completed iterations replace the
//!   committed root result; a budget-interrupted iteration is discarded whole.
//! - The transposition table caches only fully solved exact nodes, keyed by
//!   `(full_state_hash, remaining_depth_turns)`; budget-interrupted subtrees
//!   are never cached.

use std::collections::HashMap;

use splendor_core::{full_state_hash, Action, FullState, FullStateHash, GameEvent};

use crate::config::SearchConfigV1;
use crate::error::SearchError;
use crate::evaluation::StaticEvaluatorV1;
use crate::model::{SearchResultV1, SearchStatsV1, SearchStopReasonV1};
use crate::order::{canonical_order, first_canonical_action};

/// Frozen public entry point for deterministic MaxN search v1.
///
/// The input `state` is never mutated. On success the returned
/// [`SearchResultV1`] always selects a root action that is a member of the
/// root's `legal_actions()` and is fully determined by `(state, config)`.
pub fn search_maxn_v1(
    state: &FullState,
    config: SearchConfigV1,
) -> Result<SearchResultV1, SearchError> {
    config.validate()?;

    if state.is_terminal() {
        return Err(SearchError::TerminalState);
    }

    let root_legal = state.legal_actions();
    if root_legal.is_empty() {
        return Err(SearchError::NoLegalActions);
    }
    let root_player = state.current_player;
    let player_count = state.player_count() as usize;
    let first_action =
        first_canonical_action(&root_legal).expect("root non-terminal with legal actions");

    let mut searcher = Searcher {
        remaining_budget: config.max_nodes,
        tt: HashMap::new(),
        stats: SearchStatsV1 {
            nodes_visited: 0,
            nodes_expanded: 0,
            leaf_evaluations: 0,
            transposition_hits: 0,
            transposition_entries: 0,
        },
    };

    let max_depth = config.max_depth_turns;
    let mut committed: Option<(u8, Action, Vec<i64>, Vec<Action>)> = None;
    let mut stop_reason = SearchStopReasonV1::DepthLimitReached;

    for depth in 1..=max_depth {
        match searcher.search_node(state, depth, player_count)? {
            Some((util, pv)) => {
                let root_action = *pv.first().unwrap_or(&first_action);
                committed = Some((depth, root_action, util, pv));
            }
            None => {
                // Budget exhausted mid-iteration: discard this iteration.
                stop_reason = SearchStopReasonV1::NodeBudgetReached;
                break;
            }
        }
    }

    let (completed_depth_turns, action, utility_by_player, principal_variation) = match committed {
        Some(committed) => committed,
        None => {
            // Tiny-budget fallback: not even depth 1 could complete. Return a
            // legal, deterministic action (canonical first) with the static
            // evaluation of the root, never a random or config-violating value.
            let util = StaticEvaluatorV1::utilities(state)?;
            if util.len() != player_count {
                return Err(SearchError::InvalidUtilityShape {
                    expected: player_count,
                    found: util.len(),
                });
            }
            (0u8, first_action, util, vec![first_action])
        }
    };

    Ok(SearchResultV1 {
        action,
        root_player,
        completed_depth_turns,
        utility_by_player,
        principal_variation,
        stop_reason,
        stats: searcher.stats,
    })
}

/// Fully-solved transposition-table entry.
struct TableEntry {
    utility: Vec<i64>,
    pv: Vec<Action>,
}

/// A solved node's value: the MaxN utility vector and the principal variation
/// from that node. `None` means the shared node budget was exhausted before the
/// node (and therefore its whole iteration) could be solved.
type NodeSolution = Option<(Vec<i64>, Vec<Action>)>;

/// Mutable search context shared across iterative-deepening iterations.
struct Searcher {
    remaining_budget: u64,
    tt: HashMap<(FullStateHash, u8), TableEntry>,
    stats: SearchStatsV1,
}

impl Searcher {
    /// Explore one node. Returns `None` if the shared node budget is exhausted
    /// before the node (and therefore the whole iteration) can be solved.
    ///
    /// A node consumes exactly one budget unit on entry. A transposition hit is
    /// itself a node visit (counts `nodes_visited`, not `nodes_expanded`/`leaf`).
    fn search_node(
        &mut self,
        state: &FullState,
        remaining_depth: u8,
        player_count: usize,
    ) -> Result<NodeSolution, SearchError> {
        let key = (full_state_hash(state), remaining_depth);

        // Exact-only transposition hit: a cached entry always represents a
        // fully solved subtree, never a budget-interrupted one.
        if let Some(entry) = self.tt.get(&key) {
            if entry.utility.len() == player_count {
                if self.remaining_budget == 0 {
                    return Ok(None);
                }
                self.remaining_budget -= 1;
                self.stats.nodes_visited += 1;
                self.stats.transposition_hits += 1;
                return Ok(Some((entry.utility.clone(), entry.pv.clone())));
            }
            return Err(SearchError::InvalidUtilityShape {
                expected: player_count,
                found: entry.utility.len(),
            });
        }

        if self.remaining_budget == 0 {
            return Ok(None);
        }
        self.remaining_budget -= 1;
        self.stats.nodes_visited += 1;

        if state.is_terminal() || remaining_depth == 0 {
            self.stats.leaf_evaluations += 1;
            let util = StaticEvaluatorV1::utilities(state)?;
            if util.len() != player_count {
                return Err(SearchError::InvalidUtilityShape {
                    expected: player_count,
                    found: util.len(),
                });
            }
            self.tt.insert(
                key,
                TableEntry {
                    utility: util.clone(),
                    pv: Vec::new(),
                },
            );
            self.stats.transposition_entries += 1;
            return Ok(Some((util, Vec::new())));
        }

        self.stats.nodes_expanded += 1;
        let ordered = canonical_order(&state.legal_actions());
        let current = state.current_player.index();
        let mut best: Option<(i64, Action, Vec<i64>, Vec<Action>)> = None;

        for action in ordered {
            let mut child = state.clone();
            let step = child
                .apply(action)
                .map_err(|e| SearchError::Engine(e.to_string()))?;
            let advanced = step
                .events
                .iter()
                .any(|ev| matches!(ev, GameEvent::TurnAdvanced { .. }));
            let child_remaining = if advanced {
                remaining_depth.saturating_sub(1)
            } else {
                remaining_depth
            };

            match self.search_node(&child, child_remaining, player_count)? {
                None => return Ok(None),
                Some((util, pv)) => {
                    let score = util[current];
                    let replace = match &best {
                        Some((b_score, _, _, _)) => score > *b_score,
                        None => true,
                    };
                    if replace {
                        best = Some((score, action, util, pv));
                    }
                }
            }
        }

        let (_, action, best_util, pv) =
            best.expect("non-terminal node at remaining_depth>0 always has legal actions");
        // Build the complete principal variation from this node before caching it.
        // A transposition hit must return the same PV an initial solve returns,
        // including this node's own chosen action — not just the best child's PV,
        // which would drop an action from every TT-served segment of the root PV.
        let mut full_pv = Vec::with_capacity(pv.len() + 1);
        full_pv.push(action);
        full_pv.extend(pv);
        self.tt.insert(
            key,
            TableEntry {
                utility: best_util.clone(),
                pv: full_pv.clone(),
            },
        );
        self.stats.transposition_entries += 1;
        Ok(Some((best_util, full_pv)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{GameConfig, Ruleset};

    fn fresh_state(player_count: u8, seed: u64) -> FullState {
        let (state, _) = FullState::new(GameConfig {
            player_count,
            seed,
            ruleset: Ruleset::base_v1(),
        })
        .expect("valid game config");
        state
    }

    /// Regression for the C2 P1: a TT entry must store the complete principal
    /// variation *from the cached node*, including that node's own chosen
    /// action. Caching only the best child's PV made a later TT hit drop one
    /// action from every TT-served segment of the root PV.
    #[test]
    fn tt_hit_returns_same_complete_pv_as_initial_solve() {
        let state = fresh_state(2, 11);
        let player_count = state.player_count() as usize;
        // Depth 2 is enough for a non-leaf solve with a non-empty PV while
        // staying well inside a generous node budget.
        let remaining_depth = 2u8;

        let mut searcher = Searcher {
            remaining_budget: 50_000,
            tt: HashMap::new(),
            stats: SearchStatsV1 {
                nodes_visited: 0,
                nodes_expanded: 0,
                leaf_evaluations: 0,
                transposition_hits: 0,
                transposition_entries: 0,
            },
        };

        let first = searcher
            .search_node(&state, remaining_depth, player_count)
            .expect("search must not error")
            .expect("depth-2 solve must complete within budget");
        let (first_util, first_pv) = first;

        assert!(
            !first_pv.is_empty(),
            "non-leaf exact solve must return a non-empty PV"
        );
        let expected_root_action = first_pv[0];
        assert!(
            state.legal_actions().contains(&expected_root_action),
            "PV head must be a legal root action"
        );

        let key = (full_state_hash(&state), remaining_depth);
        let entry = searcher
            .tt
            .get(&key)
            .expect("exact solve must write a TT entry for the root key");
        assert_eq!(
            entry.utility, first_util,
            "cached utility must match the initial solve"
        );
        assert_eq!(
            entry.pv, first_pv,
            "cached PV must be the complete node PV, not the best child's PV"
        );
        assert_eq!(
            entry.pv.first().copied(),
            Some(expected_root_action),
            "cached PV head must be the action chosen at this node"
        );

        let hits_before = searcher.stats.transposition_hits;
        let second = searcher
            .search_node(&state, remaining_depth, player_count)
            .expect("search must not error")
            .expect("TT hit path must still return a solved node");
        let (hit_util, hit_pv) = second;

        assert!(
            searcher.stats.transposition_hits > hits_before,
            "second call with the same key must be served from the TT"
        );
        assert_eq!(
            hit_util, first_util,
            "TT hit utility must match initial solve"
        );
        assert_eq!(hit_pv, first_pv, "TT hit PV must match initial solve");
        assert_eq!(
            hit_pv.first().copied(),
            Some(expected_root_action),
            "TT hit PV head must still be the action chosen at this node"
        );
    }
}
