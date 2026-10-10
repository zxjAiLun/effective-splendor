//! Two-ply continuation rollout simulation: Me -> Opponent -> Me.
//! Models exact turn progression and information boundaries without oracle leaks.

use super::board::SimBoard;
use super::evaluator::evaluate_leaf;
use splendor_catalog::card;
use splendor_core::{Action, Observation};

/// Simulate a candidate action through "Me -> Opponent -> Me" rollout and return leaf evaluation.
pub fn simulate_candidate(obs: &Observation, candidate: Action) -> i64 {
    let mut board = SimBoard::from_observation(obs);

    // --- Ply 0 (Me) ---
    board.apply_action(candidate);
    if board.terminal {
        return evaluate_leaf(&board);
    }

    // --- Ply 1 (Opponent) ---
    let opp_actions = board.legal_actions();
    let best_opp_action = select_opponent_response(&board, &opp_actions);
    board.apply_action(best_opp_action);
    if board.terminal {
        return evaluate_leaf(&board);
    }

    // --- Ply 2 (Me Follow-up) ---
    let my_follow_up_actions = board.legal_actions();
    let mut best_leaf_score = i64::MIN;

    for &my_action in &my_follow_up_actions {
        let mut branch = board.clone();
        branch.apply_action(my_action);
        let score = evaluate_leaf(&branch);
        if score > best_leaf_score {
            best_leaf_score = score;
        }
    }

    if best_leaf_score == i64::MIN {
        evaluate_leaf(&board)
    } else {
        best_leaf_score
    }
}

/// Greedy heuristic selection for the opponent's response on the simulated board.
fn select_opponent_response(board: &SimBoard, actions: &[Action]) -> Action {
    if actions.is_empty() {
        return Action::Pass;
    }
    if actions.len() == 1 {
        return actions[0];
    }

    let opp = board.current();
    let mut best_action = actions[0];
    let mut best_score = i64::MIN;

    for &a in actions {
        let mut score = 0;
        match a {
            Action::BuyMarket { tier, slot } => {
                if let Some(cid) = board.market[tier.index()][slot as usize] {
                    let def = card(cid);
                    score += (def.prestige as i64) * 5_000 + 1_000;
                    if opp.prestige + def.prestige >= 15 {
                        score += 50_000; // Immediate win rush
                    }
                }
            }
            Action::BuyReserved { slot } => {
                if (slot as usize) < opp.reserved.len() {
                    let cid = opp.reserved[slot as usize];
                    let def = card(cid);
                    score += (def.prestige as i64) * 5_000 + 1_000;
                    if opp.prestige + def.prestige >= 15 {
                        score += 50_000;
                    }
                }
            }
            Action::TakeTokens { take, .. } => {
                score += (take.total() as i64) * 200;
            }
            Action::ReserveMarket { tier, slot, .. } => {
                if let Some(cid) = board.market[tier.index()][slot as usize] {
                    let def = card(cid);
                    score += (def.prestige as i64) * 1_000 + 300;
                }
            }
            Action::ReserveDeck { .. } => {
                score += 100;
            }
            Action::ChooseNoble { noble: _ } => {
                score += 15_000;
            }
            Action::Pass => {
                score -= 10_000;
            }
        }

        if score > best_score {
            best_score = score;
            best_action = a;
        }
    }

    best_action
}
