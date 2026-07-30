//! Test-only support for the M06 C3 exact-TT conformance corpus.
//!
//! `reference_maxn` is an independent, no-TT reference MaxN solver. It must
//! never be reachable from production code: it lives only in the
//! integration-test build of `splendor-search`. The production search
//! (`search_maxn_v1`) must not call it, otherwise the differential test would
//! compare the implementation against itself.

use splendor_catalog::all_nobles;
use splendor_core::{Action, FullState, GameConfig, GameEvent, Ruleset};
use splendor_search::{canonical_order, first_canonical_action, SearchError, StaticEvaluatorV1};

/// Build a fresh game state for `player_count` with the given seed.
pub fn fresh_state(player_count: u8, seed: u64) -> FullState {
    let (state, _) = FullState::new(GameConfig {
        player_count,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("valid game config");
    state
}

/// Drive a game forward by `steps` canonical-first legal actions without
/// reaching terminal, yielding a deterministic mid-game state.
pub fn mid_game_state(player_count: u8, seed: u64, steps: u32) -> FullState {
    let mut state = fresh_state(player_count, seed);
    let mut guard = 0u32;
    while guard < steps && !state.is_terminal() {
        let legal = state.legal_actions();
        let Some(action) = first_canonical_action(&legal) else {
            break;
        };
        state.apply(action).expect("canonical-first action applies");
        guard += 1;
    }
    state
}

/// A root state where the canonical-first action buys a card that qualifies the
/// current player for two nobles, forcing a `ChooseNoble` continuation within
/// the same turn (the action does not consume a turn of depth budget).
pub fn buy_triggers_noble_state() -> FullState {
    let mut state = fresh_state(2, 1);
    let nobles = all_nobles();
    let n1 = &nobles[0];
    let n2 = &nobles[1];
    let mut bonuses = [0u8; 5];
    for (c, slot) in bonuses.iter_mut().enumerate() {
        *slot = n1.requirements[c].max(n2.requirements[c]);
    }
    state.players[0].bonuses = bonuses;
    state.nobles = vec![n1.id, n2.id];
    // Enough gold that every market card is affordable, so a BuyMarket is the
    // canonical-first legal action.
    state.players[0].tokens.gold = 10;
    state
}

/// Independent reference MaxN solver.
///
/// No transposition table, no iterative deepening, no node budget, no
/// randomness and no alpha-beta pruning. It mirrors the production search rule
/// for rule:
/// 1. terminal or `remaining_depth_turns == 0` → `StaticEvaluatorV1::utilities`;
/// 2. enumerate the complete canonical-order legal action set;
/// 3. clone + apply each action;
/// 4. a turn advances (depth - 1) only on a `TurnAdvanced` event;
/// 5. the moving player maximizes its own utility component;
/// 6. ties keep the earlier canonical action;
/// 7. the returned PV is the complete action sequence from this node.
///
/// Returns `Err(SearchError::NoLegalActions)` only if a non-terminal node has
/// no legal actions (a degenerate state); well-formed game states never do.
pub fn reference_maxn(
    state: &FullState,
    remaining_depth_turns: u8,
) -> Result<(Vec<i64>, Vec<Action>), SearchError> {
    if state.is_terminal() || remaining_depth_turns == 0 {
        return Ok((StaticEvaluatorV1::utilities(state)?, Vec::new()));
    }
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
            remaining_depth_turns.saturating_sub(1)
        } else {
            remaining_depth_turns
        };
        let (util, pv) = reference_maxn(&child, child_remaining)?;
        // Safe access: a malformed utility vector is diagnosed instead of
        // indexing out of bounds.
        let score = *util.get(current).ok_or(SearchError::InvalidUtilityShape {
            expected: state.player_count() as usize,
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
    let (_, action, util, pv) = best.ok_or(SearchError::NoLegalActions)?;
    let mut full_pv = Vec::with_capacity(pv.len() + 1);
    full_pv.push(action);
    full_pv.extend(pv);
    Ok((util, full_pv))
}
