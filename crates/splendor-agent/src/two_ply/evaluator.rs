//! Full-board leaf evaluator V(S) for 2-ply continuation rollout.
//! Distinct from single-action delta scores: evaluates global board state,
//! tempo-to-15, engine equity, noble distance, and opponent threat.

use super::board::SimBoard;
use splendor_catalog::{all_nobles, card, GemColor, Tier};

const TERMINAL_WIN: i64 = 100_000;
const TERMINAL_LOSS: i64 = -100_000;

const VP_DIFF_WEIGHT: i64 = 3_000;
const ME_VP_WEIGHT: i64 = 1_000;
const BONUS_WEIGHT: i64 = 600;
const OPP_BONUS_WEIGHT: i64 = 500;
const GOLD_WEIGHT: i64 = 70;
const OPP_GOLD_WEIGHT: i64 = 60;
const TOKEN_WEIGHT: i64 = 100;
const OPP_TOKEN_WEIGHT: i64 = 80;
const AFFORDABLE_VP_WEIGHT: i64 = 500;
const OPP_THREAT_VP_WEIGHT: i64 = 700;
const STRANDED_RESERVE_PENALTY: i64 = 400;

/// Evaluate a leaf state S from the perspective of viewer (Me).
pub fn evaluate_leaf(board: &SimBoard) -> i64 {
    let me = board.viewer_player();
    let opp = board.opponent();

    let me_vp = me.prestige as i64;
    let opp_vp = opp.prestige as i64;
    let vp_diff = me_vp - opp_vp;

    // 1. Terminal / Final Round Resolution (Strict official rank: (prestige, Reverse(purchased_count)))
    if board.terminal || board.end_game_triggered {
        let me_rank = (me_vp, std::cmp::Reverse(me.purchased_count));
        let opp_rank = (opp_vp, std::cmp::Reverse(opp.purchased_count));

        if me_rank > opp_rank {
            return TERMINAL_WIN + 10_000 * vp_diff;
        } else if opp_rank > me_rank {
            return TERMINAL_LOSS + 10_000 * vp_diff;
        } else {
            return 0; // True tie
        }
    }

    // 2. Prestige and VP differential
    let mut score = vp_diff * VP_DIFF_WEIGHT + me_vp * ME_VP_WEIGHT;

    // 3. Permanent Bonus Engine
    let me_bonuses: i64 = me.bonuses.iter().map(|&b| b as i64).sum();
    let opp_bonuses: i64 = opp.bonuses.iter().map(|&b| b as i64).sum();
    score += me_bonuses * BONUS_WEIGHT - opp_bonuses * OPP_BONUS_WEIGHT;

    // Early engine incubation: if total bonuses < 8, reward foundation building
    if me_bonuses < 8 {
        score += (8 - me_bonuses) * me_bonuses * 35;
    }

    // 4. Noble proximity (for remaining unclaimed nobles) - Smooth continuous gradient
    for &nid in &board.nobles {
        let ndef = &all_nobles()[nid.index()];
        let mut me_dist = 0;
        let mut opp_dist = 0;
        for c in GemColor::ALL {
            let req = ndef.requirements[c.index()];
            me_dist += req.saturating_sub(me.bonuses[c.index()]);
            opp_dist += req.saturating_sub(opp.bonuses[c.index()]);
        }
        // Continuous proximity gradient across all distances up to 5
        if me_dist <= 5 {
            score += (6 - me_dist as i64) * 220;
        }
        if me_dist <= 2 {
            score += (3 - me_dist as i64) * 450;
        }
        if opp_dist <= 5 {
            score -= (6 - opp_dist as i64) * 180;
        }
        if opp_dist <= 2 {
            score -= (3 - opp_dist as i64) * 400;
        }
    }

    // 5. Token Liquidity and Gold (restrained gold utility to prevent reserve hoarding)
    let me_tokens = me.tokens.total() as i64;
    let opp_tokens = opp.tokens.total() as i64;
    score += me_tokens * TOKEN_WEIGHT - opp_tokens * OPP_TOKEN_WEIGHT;
    score += (me.tokens.gold as i64) * GOLD_WEIGHT - (opp.tokens.gold as i64) * OPP_GOLD_WEIGHT;

    // 6. Stranded Reserve Penalty (dissuade hoarding unbought reserves during normal game)
    if !board.end_game_triggered {
        score -= (me.reserved.len() as i64) * STRANDED_RESERVE_PENALTY;
    }

    // 7. Affordable High-VP cards vs Opponent Threats (Denial & Acceleration)
    let mut me_affordable_vp = 0;
    let mut opp_affordable_vp = 0;

    for tier in Tier::ALL {
        for slot in 0..4u8 {
            if let Some(cid) = board.market[tier.index()][slot as usize] {
                let def = card(cid);
                if me.can_afford(def.cost) {
                    me_affordable_vp += def.prestige as i64;
                }
                if opp.can_afford(def.cost) {
                    opp_affordable_vp += def.prestige as i64;
                }
            }
        }
    }
    for &cid in &me.reserved {
        let def = card(cid);
        if me.can_afford(def.cost) {
            me_affordable_vp += def.prestige as i64;
        }
    }
    for &cid in &opp.reserved {
        let def = card(cid);
        if opp.can_afford(def.cost) {
            opp_affordable_vp += def.prestige as i64;
        }
    }

    score += me_affordable_vp * AFFORDABLE_VP_WEIGHT;

    // If opponent has imminent lethal threat on table, heavily escalate denial urgency
    if opp.prestige as i64 + opp_affordable_vp >= 15 {
        score -= opp_affordable_vp * 1_500;
    } else {
        score -= opp_affordable_vp * OPP_THREAT_VP_WEIGHT;
    }

    score
}
