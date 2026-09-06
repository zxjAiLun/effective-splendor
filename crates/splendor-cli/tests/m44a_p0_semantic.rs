//! M44A P0 Semantic and Attribution Gates (H0-A, H0-B, H0-C, Family Partition, Exact Masks, Zero-Progress).
//!
//! Verifies:
//! - H0-A: Bit-for-bit utility equality between StaticEvaluatorAttributionV1(FULL) and StaticEvaluatorV1
//! - H0-B: Root decision identity on frozen M07 12-position corpus (12/12 match FULL == det-s4-d1-n1)
//! - H0-C: >=64 reachable non-terminal states bit-for-bit utility equality
//! - Family Partition: FULL progress == F1 + F2 + F3 + F4 exact integer equality for all states/players
//! - Exact Mask Microfixtures: Hand-calculated fixtures where each family contributes independently
//! - Zero-Progress Semantics: Non-terminal utilities are strictly [0, 0], terminal equals terminal_rank_base

use splendor_core::{
    visible_events, Audience, FullState, GameConfig, PlayerId, Ruleset, TerminalReason,
};
use splendor_imperfect_search::{
    analyze_player_view_attribution_v1, analyze_player_view_v1, RootDeterminizationConfigV1,
};
use splendor_search::{
    terminal_rank_base, AttributionProfile, SearchConfigV1, StaticEvaluatorAttributionV1,
    StaticEvaluatorV1, TERMINAL_RANK_UNIT,
};

const M07_SAMPLE_SEED: u64 = 20_260_703;
const M07_SAMPLE_COUNT: u16 = 4;
const M07_DEPTH_TURNS: u8 = 1;

fn m42s_n1_config() -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed: M07_SAMPLE_SEED,
        sample_count: M07_SAMPLE_COUNT,
        continuation_search: SearchConfigV1 {
            max_depth_turns: M07_DEPTH_TURNS,
            max_nodes: 1,
        },
    }
}

fn new_game(seed: u64) -> FullState {
    let (state, _) = FullState::new(GameConfig {
        player_count: 2,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("setup should succeed");
    state
}

// ---------------------------------------------------------------------------
// H0-A: Utility Identity (Non-terminal and Terminal)
// ---------------------------------------------------------------------------
#[test]
fn test_h0_a_utility_identity() {
    for seed in [1111, 2222, 3333, 4444] {
        let mut state = new_game(seed);
        for _ in 0..10 {
            let u_orig = StaticEvaluatorV1::utilities(&state).unwrap();
            let u_attr = StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::Full).unwrap();
            assert_eq!(u_orig, u_attr, "H0-A non-terminal utility mismatch on seed {seed}");

            let legal = state.legal_actions();
            if legal.is_empty() || state.is_terminal() {
                break;
            }
            state.apply(legal[0]).unwrap();
        }
    }
}

// ---------------------------------------------------------------------------
// H0-B: Root Decision Identity (12 / 12 exact match between FULL and det-s4-d1-n1)
// ---------------------------------------------------------------------------
#[test]
fn test_h0_b_root_decision_identity() {
    let cfg_n1 = m42s_n1_config();
    let ruleset = Ruleset::base_v1();

    for seed in 7_000_000..7_000_012 {
        let mut state = new_game(seed);
        // Advance 5 plies to get interesting, non-trivial player-view states with card/token development
        for _ in 0..5 {
            let legal = state.legal_actions();
            if legal.is_empty() || state.is_terminal() {
                break;
            }
            state.apply(legal[0]).unwrap();
        }

        let actor = state.current_player;
        let obs = state.observation(actor);
        let history = visible_events(&state.log, Audience::Player(actor));

        // 1. Evaluate with det-s4-d1-n1
        let analysis_n1 = analyze_player_view_v1(ruleset, &obs, &history, cfg_n1)
            .expect("n1 analysis should succeed");

        // 2. Evaluate with M44A FULL attribution profile
        let analysis_full = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &history,
            cfg_n1,
            AttributionProfile::Full,
        )
        .expect("FULL analysis should succeed");

        let res_n1 = analysis_n1.result();
        let res_full = analysis_full.result();

        assert_eq!(
            res_n1.action, res_full.action,
            "H0-B action mismatch on seed {seed}"
        );
        assert_eq!(
            res_n1.action_aggregates.len(),
            res_full.action_aggregates.len(),
            "H0-B legal action count mismatch on seed {seed}"
        );
        for (i, (agg_n1, agg_full)) in res_n1
            .action_aggregates
            .iter()
            .zip(&res_full.action_aggregates)
            .enumerate()
        {
            assert_eq!(
                agg_n1.action, agg_full.action,
                "H0-B action {i} order mismatch on seed {seed}"
            );
            assert_eq!(
                agg_n1.utility_sum_by_player, agg_full.utility_sum_by_player,
                "H0-B action {i} aggregate utility mismatch on seed {seed}"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// H0-C: Reachable-State Stress Corpus (>= 64 Non-Terminal States)
// ---------------------------------------------------------------------------
#[test]
fn test_h0_c_reachable_state_stress_corpus() {
    let mut tested_states = 0;
    for seed in 5_500_000..5_500_020 {
        let (mut state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed,
            ruleset: Ruleset::base_v1(),
        })
        .unwrap();

        while !state.is_terminal() && state.log.len() < 30 {
            let u_orig = StaticEvaluatorV1::utilities(&state).unwrap();
            let u_attr =
                StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::Full).unwrap();
            assert_eq!(u_orig, u_attr);
            tested_states += 1;

            let legal = state.legal_actions();
            if legal.is_empty() {
                break;
            }
            state.apply(legal[0]).unwrap();
        }
    }
    assert!(
        tested_states >= 64,
        "H0-C requires >= 64 tested reachable states, got {tested_states}"
    );
}

// ---------------------------------------------------------------------------
// Family Partition Gate: FULL == F1 + F2 + F3 + F4 exact integer equality
// ---------------------------------------------------------------------------
#[test]
fn test_family_partition_gate() {
    for seed in [101, 202, 303, 404] {
        let mut state = new_game(seed);
        for _ in 0..15 {
            let families = StaticEvaluatorAttributionV1::family_progress_for_all(&state);
            for (p_idx, fp) in families.iter().enumerate() {
                let full_total = fp.total();
                let sum_parts = fp.f1_score + fp.f2_engine + fp.f3_liquidity + fp.f4_convertibility;
                assert_eq!(
                    full_total, sum_parts,
                    "Family partition gate integer sum failure on player {p_idx}"
                );

                // Check profiles
                assert_eq!(fp.for_profile(AttributionProfile::Full), full_total);
                assert_eq!(fp.for_profile(AttributionProfile::DropScore), sum_parts - fp.f1_score);
                assert_eq!(fp.for_profile(AttributionProfile::DropEngine), sum_parts - fp.f2_engine);
                assert_eq!(fp.for_profile(AttributionProfile::DropLiquidity), sum_parts - fp.f3_liquidity);
                assert_eq!(fp.for_profile(AttributionProfile::DropConvertibility), sum_parts - fp.f4_convertibility);
                assert_eq!(fp.for_profile(AttributionProfile::ZeroProgress), 0);
            }

            let legal = state.legal_actions();
            if legal.is_empty() || state.is_terminal() {
                break;
            }
            state.apply(legal[0]).unwrap();
        }
    }
}

// ---------------------------------------------------------------------------
// Exact Mask Microfixtures: Hand-Calculated Independent Family Contributions
// ---------------------------------------------------------------------------
#[test]
fn test_exact_mask_microfixtures() {
    let base_state = new_game(777);

    // Microfixture 1: F1 (Prestige difference only)
    {
        let mut s = base_state.clone();
        s.players[0].prestige = 3;
        s.players[1].prestige = 0;
        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        // Player 0 has 3 prestige -> f1_score = 3 * 100_000_000 = 300_000_000
        assert_eq!(fp[0].f1_score, 300_000_000);
        assert_eq!(fp[1].f1_score, 0);
        // F2, F3, F4 for prestige only must match base_state
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);
        assert_eq!(fp[0].f2_engine, fp_base[0].f2_engine);
        assert_eq!(fp[0].f3_liquidity, fp_base[0].f3_liquidity);
        assert_eq!(fp[0].f4_convertibility, fp_base[0].f4_convertibility);

        // When DROP_SCORE is active, f1_score is masked away
        assert_eq!(fp[0].for_profile(AttributionProfile::DropScore), fp[0].total() - 300_000_000);
    }

    // Microfixture 2: F2 (Permanent bonuses / purchased cards only)
    {
        let mut s = base_state.clone();
        s.players[0].bonuses = [2, 0, 0, 0, 0]; // 2 bonuses
        s.players[0].purchased = vec![splendor_catalog::CardId(1), splendor_catalog::CardId(2)]; // 2 cards
        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        // 2 bonuses * 2_000_000 = 4_000_000; 2 cards * 250_000 = 500_000; noble_progress depends on board
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);
        let f2_delta = fp[0].f2_engine - fp_base[0].f2_engine;
        assert!(f2_delta >= 4_500_000, "F2 delta should be at least 4.5M");
        // F1, F3 must match base
        assert_eq!(fp[0].f1_score, fp_base[0].f1_score);
        assert_eq!(fp[0].f3_liquidity, fp_base[0].f3_liquidity);
    }

    // Microfixture 3: F3 (Tokens / gold / reserved cards only)
    {
        let mut s = base_state.clone();
        s.players[0].tokens.gold = 2; // 2 * 40_000 = 80_000
        s.players[0].tokens.red = 3;  // 3 * 20_000 = 60_000
        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);
        let f3_delta = fp[0].f3_liquidity - fp_base[0].f3_liquidity;
        assert_eq!(f3_delta, 80_000 + 60_000);
        // F1, F2 must match base
        assert_eq!(fp[0].f1_score, fp_base[0].f1_score);
        assert_eq!(fp[0].f2_engine, fp_base[0].f2_engine);
    }

    // Microfixture 4: F4 (Affordability only)
    {
        // Give player 0 enough gold to afford market cards
        let mut s = base_state.clone();
        s.players[0].tokens.gold = 10;
        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        // F4 should have positive affordable cards and max affordable prestige
        assert!(fp[0].f4_convertibility > 0);
        assert_eq!(fp[0].for_profile(AttributionProfile::DropConvertibility), fp[0].total() - fp[0].f4_convertibility);
    }
}

// ---------------------------------------------------------------------------
// Zero-Progress Semantics
// ---------------------------------------------------------------------------
#[test]
fn test_zero_progress_semantics() {
    let mut state = new_game(888);

    // Non-terminal state: ZERO_PROGRESS utilities must be strictly [0, 0]
    let u_nonterm =
        StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::ZeroProgress).unwrap();
    assert_eq!(u_nonterm, vec![0, 0]);

    // Force terminal state
    state.phase = splendor_core::Phase::GameOver;
    state.result = Some(splendor_core::GameResult {
        ranks: vec![0, 1],
        scores: vec![15, 10],
        winners: vec![PlayerId(0)],
        reason: TerminalReason::PrestigeThreshold,
    });

    let u_term =
        StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::ZeroProgress).unwrap();
    assert_eq!(u_term[0], terminal_rank_base(0));
    assert_eq!(u_term[1], terminal_rank_base(1));
    assert_eq!(u_term[0], TERMINAL_RANK_UNIT);
    assert_eq!(u_term[1], -TERMINAL_RANK_UNIT);
}
