//! M44B P0 Semantic Tests: F2 Subfamily Attribution Invariants.
//!
//! Verifies:
//! - Section 7: Regression gate
//! - Section 8: F2 Subfamily partition gate (F2 == CORE + NOBLE across >= 96 reachable states in 6_100_000..)
//! - Section 9: CORE_ENGINE exact fixtures (purchased card count, bonus vector)
//! - Section 10: NOBLE_PROGRESS exact fixture (hand-calculated noble progress deficit)
//! - Section 11: Profile mask identity (DROP_CORE_ENGINE == FULL - CORE, DROP_NOBLE_PROGRESS == FULL - NOBLE)

use splendor_catalog::all_nobles;
use splendor_core::{
    FullState, GameConfig, GemColor, PlayerId, Ruleset, TerminalReason,
};
use splendor_search::{
    AttributionProfile, StaticEvaluatorAttributionV1, TERMINAL_RANK_UNIT,
};

fn new_game(seed: u64, player_count: u8) -> FullState {
    let (state, _) = FullState::new(GameConfig {
        player_count,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("setup should succeed");
    state
}

// ---------------------------------------------------------------------------
// Section 8: F2 Subfamily Partition Gate (>= 96 Reachable States in 6_100_000..)
// ---------------------------------------------------------------------------
#[test]
fn test_m44b_p0_subfamily_partition_gate() {
    let mut tested_states = 0;
    // Isolated seed namespace: 6_100_000.. (disjoint from formal Arena 5_600_000..)
    for player_count in [2u8, 3, 4] {
        for seed_offset in 0..15 {
            let seed = 6_100_000 + u64::from(player_count) * 1000 + seed_offset;
            let mut state = new_game(seed, player_count);

            while !state.is_terminal() && state.log.len() < 25 {
                let families = StaticEvaluatorAttributionV1::family_progress_for_all(&state);
                for (p_idx, fp) in families.iter().enumerate() {
                    // Exact integer partition of F2:
                    assert_eq!(
                        fp.f2_engine,
                        fp.e1_core_engine + fp.e2_noble_progress,
                        "F2 partition broken on player {p_idx} seed {seed}"
                    );

                    // Exact integer partition of FULL:
                    let full_total = fp.total();
                    let full_rebuilt = fp.f1_score
                        + fp.e1_core_engine
                        + fp.e2_noble_progress
                        + fp.f3_liquidity
                        + fp.f4_convertibility;
                    assert_eq!(
                        full_total, full_rebuilt,
                        "FULL partition broken on player {p_idx} seed {seed}"
                    );

                    // Mask profiles exact arithmetic:
                    assert_eq!(
                        fp.for_profile(AttributionProfile::DropCoreEngine),
                        full_total - fp.e1_core_engine
                    );
                    assert_eq!(
                        fp.for_profile(AttributionProfile::DropNobleProgress),
                        full_total - fp.e2_noble_progress
                    );
                    assert_eq!(
                        fp.for_profile(AttributionProfile::OnlyCoreEngine),
                        fp.e1_core_engine
                    );
                    assert_eq!(
                        fp.for_profile(AttributionProfile::OnlyNobleProgress),
                        fp.e2_noble_progress
                    );
                }

                tested_states += 1;
                let legal = state.legal_actions();
                if legal.is_empty() {
                    break;
                }
                state.apply(legal[0]).unwrap();
            }
        }
    }

    assert!(
        tested_states >= 96,
        "Subfamily partition gate requires >= 96 reachable states, tested {tested_states}"
    );
}

// ---------------------------------------------------------------------------
// Section 9: CORE_ENGINE Exact Microfixtures
// ---------------------------------------------------------------------------
#[test]
fn test_m44b_p0_core_engine_exact_fixtures() {
    let base_state = new_game(6_150_001, 2);

    // 1. Purchased-count component fixture (purchased count changes, bonuses = 0, noble progress unchanged)
    {
        let mut s = base_state.clone();
        s.players[0].purchased = vec![
            splendor_catalog::CardId(1),
            splendor_catalog::CardId(2),
            splendor_catalog::CardId(3),
        ]; // 3 cards
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);
        let fp_mut = StaticEvaluatorAttributionV1::family_progress_for_all(&s);

        // Delta purchased count = 3 -> Delta CORE_ENGINE = 3 * 250_000 = 750_000 exact
        assert_eq!(fp_mut[0].e1_core_engine - fp_base[0].e1_core_engine, 750_000);
        assert_eq!(fp_mut[0].e2_noble_progress, fp_base[0].e2_noble_progress);
        assert_eq!(fp_mut[0].f2_engine - fp_base[0].f2_engine, 750_000);

        // Under DROP_CORE_ENGINE, this 750_000 is masked away exactly:
        assert_eq!(
            fp_mut[0].for_profile(AttributionProfile::DropCoreEngine),
            fp_mut[0].total() - fp_mut[0].e1_core_engine
        );
    }

    // 2. Permanent-bonus component fixture
    {
        let mut s = base_state.clone();
        // Give 2 white bonuses, 1 blue bonus -> total_bonus = 3
        s.players[0].bonuses[0] = 2;
        s.players[0].bonuses[1] = 1;
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);
        let fp_mut = StaticEvaluatorAttributionV1::family_progress_for_all(&s);

        // Delta bonus component = 3 * 2_000_000 = 6_000_000 exact
        assert_eq!(
            fp_mut[0].e1_core_engine - fp_base[0].e1_core_engine,
            6_000_000
        );

        // Check linearity: Delta F2 == Delta CORE_ENGINE + Delta NOBLE_PROGRESS
        let delta_f2 = fp_mut[0].f2_engine - fp_base[0].f2_engine;
        let delta_core = fp_mut[0].e1_core_engine - fp_base[0].e1_core_engine;
        let delta_noble = fp_mut[0].e2_noble_progress - fp_base[0].e2_noble_progress;
        assert_eq!(
            delta_f2,
            delta_core + delta_noble,
            "Delta F2 must equal Delta CORE + Delta NOBLE exactly"
        );
    }
}

// ---------------------------------------------------------------------------
// Section 10: NOBLE_PROGRESS Exact Fixture (Hand-Calculated Deficits)
// ---------------------------------------------------------------------------
#[test]
fn test_m44b_p0_noble_progress_exact_fixture() {
    let mut state = new_game(6_150_002, 2);

    // Fix nobles: use all_nobles() first 3
    state.nobles = vec![
        splendor_catalog::NobleId(0),
        splendor_catalog::NobleId(1),
        splendor_catalog::NobleId(2),
    ];

    // Set player 0 bonuses to [1, 1, 0, 0, 0]
    state.players[0].bonuses = [1, 1, 0, 0, 0];

    // Hand-calculate expected noble progress:
    // For each noble:
    // deficit = sum_color max(requirement[color] - bonus[color], 0)
    // contribution = max(25 - deficit, 0)
    let mut expected_noble_progress = 0i64;
    for &nid in &state.nobles {
        let def = &all_nobles()[nid.index()];
        let mut deficit = 0i64;
        for color in GemColor::ALL {
            let req = i64::from(def.requirements[color.index()]);
            let bon = i64::from(state.players[0].bonuses[color.index()]);
            deficit += (req - bon).max(0);
        }
        expected_noble_progress += (25 - deficit).max(0);
    }
    let expected_noble_score = expected_noble_progress * 10_000;

    let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&state);
    assert_eq!(
        fp[0].e2_noble_progress, expected_noble_score,
        "Hand-calculated noble progress mismatch"
    );

    // Verify DROP_NOBLE_PROGRESS exactly subtracts NOBLE_PROGRESS
    assert_eq!(
        fp[0].for_profile(AttributionProfile::DropNobleProgress),
        fp[0].total() - expected_noble_score
    );
}

// ---------------------------------------------------------------------------
// Section 11: Profile Mask Identity on Utilities
// ---------------------------------------------------------------------------
#[test]
fn test_m44b_p0_profile_mask_identity() {
    let state = new_game(6_150_003, 2);

    let u_full = StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::Full).unwrap();
    let u_drop_core =
        StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::DropCoreEngine).unwrap();
    let u_drop_noble =
        StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::DropNobleProgress).unwrap();

    let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&state);

    // In a 2-player game:
    // utility_0 = progress_0 * 2 - (progress_0 + progress_1) = progress_0 - progress_1
    let delta_core_rel = fp[0].e1_core_engine - fp[1].e1_core_engine;
    assert_eq!(u_full[0] - u_drop_core[0], delta_core_rel);

    let delta_noble_rel = fp[0].e2_noble_progress - fp[1].e2_noble_progress;
    assert_eq!(u_full[0] - u_drop_noble[0], delta_noble_rel);

    // Terminal rank base invariant:
    let mut term_state = state.clone();
    term_state.phase = splendor_core::Phase::GameOver;
    term_state.result = Some(splendor_core::GameResult {
        scores: vec![15, 10],
        ranks: vec![0, 1],
        winners: vec![PlayerId(0)],
        reason: TerminalReason::PrestigeThreshold,
    });

    let u_term_full =
        StaticEvaluatorAttributionV1::utilities(&term_state, AttributionProfile::Full).unwrap();
    let u_term_core =
        StaticEvaluatorAttributionV1::utilities(&term_state, AttributionProfile::DropCoreEngine).unwrap();
    let u_term_noble =
        StaticEvaluatorAttributionV1::utilities(&term_state, AttributionProfile::DropNobleProgress).unwrap();

    // Terminal rank base (+/- 1e12) dominates in all profiles:
    assert!(u_term_full[0] >= TERMINAL_RANK_UNIT / 2);
    assert!(u_term_core[0] >= TERMINAL_RANK_UNIT / 2);
    assert!(u_term_noble[0] >= TERMINAL_RANK_UNIT / 2);
}
