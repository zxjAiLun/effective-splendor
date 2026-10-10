//! Comprehensive tests for 2-ply continuation simulation agent.

use super::board::SimBoard;
use super::candidates::{select_candidates, CandidatePruningResult};
use super::evaluator::evaluate_leaf;
use super::rollout::simulate_candidate;
use super::TwoPlyPolicy;
use crate::policy::{AgentPolicy, DecisionContext, PublicRequestMeta};
use crate::StableRng;
use splendor_catalog::Tier;
use splendor_core::{
    observation_hash, Action, FullState, GameConfig, Gems, Observation, Phase, PlayerId, Ruleset,
};

fn standard_2p_obs() -> Observation {
    let (state, _) = FullState::new(GameConfig {
        seed: 9_270_000,
        player_count: 2,
        ruleset: Ruleset::base_v1(),
    })
    .expect("valid game");
    state.observation(PlayerId(0))
}

#[test]
fn test_candidate_pruning_bounds() {
    let obs = standard_2p_obs();
    let (state, _) = FullState::new(GameConfig {
        seed: 9_270_000,
        player_count: 2,
        ruleset: Ruleset::base_v1(),
    })
    .expect("valid game");
    let legal = state.legal_actions();

    match select_candidates(&obs, &legal) {
        CandidatePruningResult::EvaluateCandidates(cands) => {
            assert!(!cands.is_empty());
            assert!(cands.len() <= 7, "candidates capped at 3+2+2=7");
            for c in &cands {
                assert!(legal.contains(c), "candidate must be strictly legal");
            }
        }
        CandidatePruningResult::FastPath(a) => {
            assert!(legal.contains(&a));
        }
    }
}

#[test]
fn test_fast_path_non_main_or_single_action() {
    let mut obs = standard_2p_obs();
    obs.public.phase = Phase::ChooseNoble;
    let legal = vec![Action::Pass];

    let res = select_candidates(&obs, &legal);
    assert_eq!(res, CandidatePruningResult::FastPath(Action::Pass));
}

#[test]
fn test_strict_information_set_no_refill() {
    let obs = standard_2p_obs();
    let mut board = SimBoard::from_observation(&obs);

    // Find first available card in market
    let mut target_card = None;
    for tier in Tier::ALL {
        for slot in 0..4u8 {
            if let Some(cid) = board.market[tier.index()][slot as usize] {
                target_card = Some((tier, slot, cid));
                break;
            }
        }
        if target_card.is_some() {
            break;
        }
    }

    let (tier, slot, _cid) = target_card.expect("market has card");
    board.apply_action(Action::ReserveMarket {
        tier,
        slot,
        give_back: Gems::ZERO,
    });

    // Market slot must be strictly None (no deck refill during simulation!)
    assert_eq!(
        board.market[tier.index()][slot as usize],
        None,
        "strict information set: market slot must not be refilled from hidden deck"
    );
}

#[test]
fn test_two_ply_policy_execution() {
    let obs = standard_2p_obs();
    let (state, _) = FullState::new(GameConfig {
        seed: 9_270_000,
        player_count: 2,
        ruleset: Ruleset::base_v1(),
    })
    .expect("valid game");
    let legal = state.legal_actions();

    let mut policy = TwoPlyPolicy::new();
    let mut rng = StableRng::new(42);

    let meta = PublicRequestMeta {
        game_id: "test".to_string(),
        recipient_seat: PlayerId(0),
        request_id: 1,
        observation_hash: observation_hash(&obs),
    };

    let action = policy
        .choose_action(DecisionContext {
            observation: obs.clone(),
            visible_history: &[],
            legal_actions: &legal,
            meta,
            rng: &mut rng,
        })
        .expect("policy choose action succeeds");

    assert!(legal.contains(&action), "chosen action must be legal");
}

#[test]
fn test_endgame_threat_evaluated_heavily() {
    let obs = standard_2p_obs();
    let mut board = SimBoard::from_observation(&obs);

    // Base score
    let base_score = evaluate_leaf(&board);

    // Give opponent 15 VP (endgame triggered)
    board.players[1].prestige = 15;
    board.end_game_triggered = true;

    let threat_score = evaluate_leaf(&board);
    assert!(
        threat_score < base_score - 40_000,
        "threat of opponent reaching 15 VP must cause severe evaluation drop"
    );
}

#[test]
fn test_chained_discount_simulation() {
    let obs = standard_2p_obs();
    let legal = [
        Action::TakeTokens {
            take: Gems {
                white: 1,
                blue: 1,
                green: 1,
                ..Gems::ZERO
            },
            give_back: Gems::ZERO,
        },
        Action::Pass,
    ];

    let score = simulate_candidate(&obs, legal[0]);
    assert!(score > i64::MIN);
}

#[test]
fn test_defensive_reserve_blocks_opponent_lethal() {
    let mut obs = standard_2p_obs();
    // Identify contested card in tier 3 slot 0
    let target_card_id = obs.public.market[2][0].expect("tier 3 slot 0 has card");
    let target_def = splendor_catalog::card(target_card_id);

    // Setup opponent with exact tokens to afford this card, bringing them to exactly 15 VP
    let mut opp_tokens = Gems::ZERO;
    for c in splendor_catalog::GemColor::ALL {
        opp_tokens.set_color(c, target_def.cost[c.index()]);
    }
    obs.public.players[1].tokens = opp_tokens;
    obs.public.players[1].prestige = 15 - target_def.prestige;
    // Action A: Reserve the contested card from market
    let defensive_reserve = Action::ReserveMarket {
        tier: Tier::Three,
        slot: 0,
        give_back: Gems::ZERO,
    };

    // Action B: An irrelevant token take
    let indifferent_take = Action::TakeTokens {
        take: Gems {
            red: 1,
            green: 1,
            white: 1,
            ..Gems::ZERO
        },
        give_back: Gems::ZERO,
    };

    let score_defensive = simulate_candidate(&obs, defensive_reserve);
    let score_indifferent = simulate_candidate(&obs, indifferent_take);

    assert!(
        score_defensive > score_indifferent,
        "defensive reserve must score higher than letting opponent purchase lethal card (scores: {} vs {})",
        score_defensive, score_indifferent
    );
}

#[test]
fn test_chained_discount_acceleration_preference() {
    let obs = standard_2p_obs();
    let buy_card_action = Action::BuyMarket {
        tier: Tier::One,
        slot: 0,
    };
    let pass_action = Action::Pass;

    let score_buy = simulate_candidate(&obs, buy_card_action);
    let score_pass = simulate_candidate(&obs, pass_action);

    assert!(
        score_buy > score_pass,
        "buying an engine card enabling discount chains must score higher than passing"
    );
}
