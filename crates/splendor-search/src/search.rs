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

/// A solved node's exact MaxN value: the utility vector and the complete
/// principal variation from that node.
type NodeSolution = (Vec<i64>, Vec<Action>);

/// Outcome of an exact-TT lookup at a node key.
enum TtLookup {
    /// No entry for the key; the node must be solved by expansion.
    Miss,
    /// A fully solved entry was found. The contained `(utility, pv)` is the
    /// exact MaxN solution from that node.
    Hit(NodeSolution),
    /// The key was hit (or the node would otherwise be entered) but no node
    /// budget remains; the caller must abandon this node for this iteration.
    BudgetExhausted,
}

/// Mutable search context shared across iterative-deepening iterations.
struct Searcher {
    remaining_budget: u64,
    tt: HashMap<(FullStateHash, u8), TableEntry>,
    stats: SearchStatsV1,
}

impl Searcher {
    /// Attempt to serve `key` from the exact transposition table.
    ///
    /// On a hit this consumes exactly one node budget and updates the visit and
    /// transposition-hit statistics, then returns the cached solution. The
    /// cached utility is validated against `player_count`; a mismatch is
    /// reported as [`SearchError::InvalidUtilityShape`] rather than panicking.
    ///
    /// Returns [`TtLookup::BudgetExhausted`] when no budget remains to pay for
    /// the visit, in which case the caller abandons this node for the iteration.
    fn lookup_exact(
        &mut self,
        key: &(FullStateHash, u8),
        player_count: usize,
    ) -> Result<TtLookup, SearchError> {
        let Some(entry) = self.tt.get(key) else {
            return Ok(TtLookup::Miss);
        };
        if entry.utility.len() != player_count {
            return Err(SearchError::InvalidUtilityShape {
                expected: player_count,
                found: entry.utility.len(),
            });
        }
        if self.remaining_budget == 0 {
            return Ok(TtLookup::BudgetExhausted);
        }
        self.remaining_budget -= 1;
        self.stats.nodes_visited += 1;
        self.stats.transposition_hits += 1;
        Ok(TtLookup::Hit((entry.utility.clone(), entry.pv.clone())))
    }

    /// Store a fully-solved exact node.
    ///
    /// Validates the utility shape against `player_count` first. After insertion
    /// `transposition_entries` is re-synced to the live `tt.len()`, so it counts
    /// *unique* exact entries rather than cumulative insert calls (a re-insert
    /// of an existing key must not inflate the counter).
    fn store_exact(
        &mut self,
        key: (FullStateHash, u8),
        utility: Vec<i64>,
        principal_variation: Vec<Action>,
        player_count: usize,
    ) -> Result<(), SearchError> {
        if utility.len() != player_count {
            return Err(SearchError::InvalidUtilityShape {
                expected: player_count,
                found: utility.len(),
            });
        }
        self.tt.insert(
            key,
            TableEntry {
                utility,
                pv: principal_variation,
            },
        );
        self.stats.transposition_entries = self.tt.len() as u64;
        Ok(())
    }

    /// Explore one node. Returns `None` if the shared node budget is exhausted
    /// before the node (and therefore the whole iteration) can be solved.
    ///
    /// A node consumes exactly one budget unit on entry, either via an exact
    /// transposition hit (which is itself a node visit, counted in
    /// `nodes_visited`/`transposition_hits`, not `nodes_expanded`/`leaf`) or by
    /// expanding the node after a miss.
    fn search_node(
        &mut self,
        state: &FullState,
        remaining_depth: u8,
        player_count: usize,
    ) -> Result<Option<NodeSolution>, SearchError> {
        let key = (full_state_hash(state), remaining_depth);

        match self.lookup_exact(&key, player_count)? {
            TtLookup::Hit(solution) => return Ok(Some(solution)),
            TtLookup::BudgetExhausted => return Ok(None),
            TtLookup::Miss => {}
        }

        // Miss: pay the node-visit budget to enter and expand this node.
        if self.remaining_budget == 0 {
            return Ok(None);
        }
        self.remaining_budget -= 1;
        self.stats.nodes_visited += 1;

        if state.is_terminal() || remaining_depth == 0 {
            self.stats.leaf_evaluations += 1;
            let util = StaticEvaluatorV1::utilities(state)?;
            self.store_exact(key, util.clone(), Vec::new(), player_count)?;
            return Ok(Some((util, Vec::new())));
        }

        self.stats.nodes_expanded += 1;
        let ordered = canonical_order(&state.legal_actions());
        // Fail-closed: a non-terminal node at remaining_depth > 0 must have at
        // least one legal action. A degenerate state (e.g. ChooseNoble phase
        // with no pending nobles) must error, never panic on an empty `best`.
        if ordered.is_empty() {
            return Err(SearchError::NoLegalActions);
        }
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
                    // Safe access: `current` is a valid seat index in any
                    // well-formed state, but diagnose a malformed utility vector
                    // instead of indexing out of bounds.
                    let score = *util.get(current).ok_or(SearchError::InvalidUtilityShape {
                        expected: player_count,
                        found: util.len(),
                    })?;
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

        // `ordered` is non-empty (guarded above), so `best` is always `Some`
        // unless a child exhausted the budget (handled by the `None` path).
        let (_, action, best_util, pv) = best.ok_or(SearchError::NoLegalActions)?;
        // Build the complete principal variation from this node before caching
        // it. A transposition hit must return the same PV an initial solve
        // returns, including this node's own chosen action — not just the best
        // child's PV, which would drop an action from every TT-served segment of
        // the root PV.
        let mut full_pv = Vec::with_capacity(pv.len() + 1);
        full_pv.push(action);
        full_pv.extend(pv);
        self.store_exact(key, best_util.clone(), full_pv.clone(), player_count)?;
        Ok(Some((best_util, full_pv)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::{GameConfig, Phase, Ruleset};

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

    /// A non-terminal node with no legal actions (ChooseNoble phase with an
    /// empty pending set) must fail-closed with `NoLegalActions` rather than
    /// panicking on an empty `best`.
    #[test]
    fn internal_empty_legal_set_returns_error_not_panic() {
        let mut state = fresh_state(2, 1);
        state.phase = Phase::ChooseNoble;
        state.pending_nobles.clear();
        assert!(!state.is_terminal());
        assert!(state.legal_actions().is_empty());

        let mut searcher = Searcher {
            remaining_budget: 10_000,
            tt: HashMap::new(),
            stats: SearchStatsV1 {
                nodes_visited: 0,
                nodes_expanded: 0,
                leaf_evaluations: 0,
                transposition_hits: 0,
                transposition_entries: 0,
            },
        };
        let result = searcher.search_node(&state, 1, state.player_count() as usize);
        assert!(
            matches!(result, Err(SearchError::NoLegalActions)),
            "internal empty legal set must error, got {result:?}"
        );
    }

    /// A cached entry whose utility length disagrees with the player count must
    /// be reported as `InvalidUtilityShape`, never indexed or panicked.
    #[test]
    fn malformed_tt_entry_shape_returns_error_not_panic() {
        let state = fresh_state(2, 1);
        let player_count = state.player_count() as usize;
        let key = (full_state_hash(&state), 1u8);

        let mut searcher = Searcher {
            remaining_budget: 10_000,
            tt: HashMap::new(),
            stats: SearchStatsV1 {
                nodes_visited: 0,
                nodes_expanded: 0,
                leaf_evaluations: 0,
                transposition_hits: 0,
                transposition_entries: 0,
            },
        };
        // Inject a deliberately malformed entry (wrong utility length).
        searcher.tt.insert(
            key,
            TableEntry {
                utility: vec![0i64; player_count + 1],
                pv: Vec::new(),
            },
        );
        let result = searcher.search_node(&state, 1, player_count);
        assert!(
            matches!(result, Err(SearchError::InvalidUtilityShape { .. })),
            "malformed TT entry must error, got {result:?}"
        );
    }

    /// After a solve, `transposition_entries` must equal the live TT length
    /// (unique entries), not a cumulative insert count.
    #[test]
    fn transposition_entries_counts_unique_tt_entries() {
        let state = fresh_state(2, 11);
        let player_count = state.player_count() as usize;
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
        let _ = searcher
            .search_node(&state, 2, player_count)
            .expect("solve must succeed");
        assert_eq!(
            searcher.stats.transposition_entries,
            searcher.tt.len() as u64,
            "transposition_entries must equal unique TT length"
        );
    }
}
