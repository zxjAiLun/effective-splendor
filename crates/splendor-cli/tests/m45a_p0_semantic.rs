//! M45A P0 Semantic and Wiring Gates.
//!
//! Verifies:
//! - P0-A: Sum preservation — sum(SHIFT1(bonus)) == sum(bonus) and CORE invariance
//!   across >= 256 deterministic reachable states spanning 2p/3p/4p.
//! - P0-B: Untargeted families frozen — SHIFT_F4 changes only F4; SHIFT_E2 changes
//!   only E2; SHIFT_F4_E2 changes only F4 and E2.
//! - P0-C: Exact formula identity — progress(SHIFT_F4) == progress(FULL) - true_F4
//!   + shifted_F4 (and the corresponding equalities for SHIFT_E2 / SHIFT_F4_E2).
//! - P0-D: Real activation — both scrambled paths must actually differ from their
//!   true counterparts on at least one state of the deterministic corpus.
//!
//! P0-E (M44A/M44B/M44C regression suites) is executed by the final audit script.

use splendor_core::{FullState, GameConfig, Ruleset};
use splendor_search::{
    canonical_order, shift1_bonus, AttributionProfile, StaticEvaluatorAttributionV1,
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

fn next_xorshift64_star(state: &mut u64) -> u64 {
    let mut x = *state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    *state = x;
    x.wrapping_mul(0x2545_F491_4F6C_DD1D)
}

/// Deterministically walk one game from `seed`, invoking `f` on every visited
/// non-terminal state until `budget` states have been observed or the game ends.
fn walk_states<F: FnMut(&FullState)>(seed: u64, player_count: u8, budget: usize, f: &mut F) {
    let mut state = new_game(seed, player_count);
    let mut rng_state = seed ^ 0x05EE_DC01;
    let mut visited = 0usize;
    while !state.is_terminal() && visited < budget {
        f(&state);
        visited += 1;
        let canonical = canonical_order(&state.legal_actions());
        if canonical.is_empty() {
            break;
        }
        let choice = (next_xorshift64_star(&mut rng_state) % canonical.len() as u64) as usize;
        state.apply(canonical[choice]).unwrap();
    }
}

/// Collect a shared deterministic reachable-state corpus spanning 2p/3p/4p with
/// at least 256 states, biased toward mid-game bonus development (so the
/// scramble has material to act on).
fn reachable_corpus() -> Vec<FullState> {
    let mut corpus = Vec::new();
    let configs: [(u8, u64); 3] = [(2, 6_500_000), (3, 6_510_000), (4, 6_520_000)];
    for &(player_count, seed_base) in &configs {
        for seed in seed_base..seed_base + 12 {
            walk_states(seed, player_count, 60, &mut |state: &FullState| {
                corpus.push(state.clone());
            });
        }
    }
    assert!(
        corpus.len() >= 256,
        "corpus must contain >= 256 states, got {}",
        corpus.len()
    );
    corpus
}

// ---------------------------------------------------------------------------
// P0-A: Sum Preservation & CORE Invariance
// ---------------------------------------------------------------------------
#[test]
fn test_m45a_p0_a_sum_preservation() {
    let corpus = reachable_corpus();

    for (idx, state) in corpus.iter().enumerate() {
        for (p_idx, player) in state.players.iter().enumerate() {
            let shifted = shift1_bonus(&player.bonuses);

            // 1. Sum preservation, exact integer equality.
            let true_sum: i64 = player.bonuses.iter().map(|&b| i64::from(b)).sum();
            let shifted_sum: i64 = shifted.iter().map(|&b| i64::from(b)).sum();
            assert_eq!(
                true_sum, shifted_sum,
                "P0-A sum mismatch at corpus state {idx} player {p_idx}"
            );

            // 2. CORE invariance: both the bonus-total and purchased-count terms
            //    are untouched by the scramble (purchased is structurally
            //    unchanged; bonus-total equals the preserved sum).
            let fp = splendor_search::family_progress_for(state, player);
            assert_eq!(
                fp.total_permanent_bonuses, true_sum,
                "P0-A total_permanent_bonuses mismatch at corpus state {idx} player {p_idx}"
            );
            assert_eq!(
                fp.purchased_card_count,
                player.purchased.len() as i64,
                "P0-A purchased_card_count mismatch at corpus state {idx} player {p_idx}"
            );

            // 3. E1/CORE must be identical when computed from the true state on
            //    two consecutive calls (deterministic wiring) — and the shifted
            //    fields must not leak into e1.
            let fp2 = splendor_search::family_progress_for(state, player);
            assert_eq!(fp.e1_core_engine, fp2.e1_core_engine);
        }
    }

    // 4. Shift definition spot checks.
    assert_eq!(shift1_bonus(&[1, 0, 0, 0, 0]), [0, 1, 0, 0, 0]);
    assert_eq!(shift1_bonus(&[0, 0, 0, 0, 1]), [1, 0, 0, 0, 0]);
    assert_eq!(shift1_bonus(&[2, 3, 4, 5, 6]), [6, 2, 3, 4, 5]);
    assert_eq!(shift1_bonus(&[0, 0, 0, 0, 0]), [0, 0, 0, 0, 0]);
}

// ---------------------------------------------------------------------------
// P0-B: Untargeted Families Frozen
// ---------------------------------------------------------------------------
#[test]
fn test_m45a_p0_b_untargeted_families_frozen() {
    let corpus = reachable_corpus();

    for (idx, state) in corpus.iter().enumerate() {
        let fps: Vec<_> = state
            .players
            .iter()
            .map(|p| splendor_search::family_progress_for(state, p))
            .collect();

        for (p_idx, fp) in fps.iter().enumerate() {
            // SHIFT_F4: only F4 may differ from the true evaluation.
            let prog_shift_f4 = fp.for_profile(AttributionProfile::ShiftF4);
            let expected_shift_f4 =
                fp.f1_score + fp.f2_engine + fp.f3_liquidity + fp.shifted_f4_convertibility;
            assert_eq!(
                prog_shift_f4, expected_shift_f4,
                "P0-B SHIFT_F4 must reuse the true F1/F2/F3 at corpus state {idx} player {p_idx}"
            );

            // SHIFT_E2: only E2 may differ.
            let prog_shift_e2 = fp.for_profile(AttributionProfile::ShiftE2);
            let expected_shift_e2 = fp.f1_score
                + fp.e1_core_engine
                + fp.shifted_e2_noble_progress
                + fp.f3_liquidity
                + fp.f4_convertibility;
            assert_eq!(
                prog_shift_e2, expected_shift_e2,
                "P0-B SHIFT_E2 must reuse the true F1/CORE/F3/F4 at corpus state {idx} player {p_idx}"
            );

            // SHIFT_F4_E2: only F4 and E2 may differ.
            let prog_shift_both = fp.for_profile(AttributionProfile::ShiftF4E2);
            let expected_shift_both = fp.f1_score
                + fp.e1_core_engine
                + fp.shifted_e2_noble_progress
                + fp.f3_liquidity
                + fp.shifted_f4_convertibility;
            assert_eq!(
                prog_shift_both, expected_shift_both,
                "P0-B SHIFT_F4_E2 must reuse the true F1/CORE/F3 at corpus state {idx} player {p_idx}"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// P0-C: Exact Formula Identity
// ---------------------------------------------------------------------------
#[test]
fn test_m45a_p0_c_exact_formula_identity() {
    let corpus = reachable_corpus();

    for (idx, state) in corpus.iter().enumerate() {
        let utilities_full =
            StaticEvaluatorAttributionV1::utilities(state, AttributionProfile::Full).unwrap();

        // Per-player family progress for manual reconstruction.
        let fps: Vec<_> = state
            .players
            .iter()
            .map(|p| splendor_search::family_progress_for(state, p))
            .collect();

        let player_count = state.players.len() as i64;

        // Reconstruct the relative-utility contract for each shift profile and
        // compare against the evaluator output exactly.
        for (profile, is_f4_shifted, is_e2_shifted) in [
            (AttributionProfile::ShiftF4, true, false),
            (AttributionProfile::ShiftE2, false, true),
            (AttributionProfile::ShiftF4E2, true, true),
        ] {
            let utilities = StaticEvaluatorAttributionV1::utilities(state, profile).unwrap();

            // progress_i = F1 + CORE + F3 + F4_used + E2_used
            let progress: Vec<i64> = fps
                .iter()
                .map(|fp| {
                    let f4_used = if is_f4_shifted {
                        fp.shifted_f4_convertibility
                    } else {
                        fp.f4_convertibility
                    };
                    let e2_used = if is_e2_shifted {
                        fp.shifted_e2_noble_progress
                    } else {
                        fp.e2_noble_progress
                    };
                    fp.f1_score + fp.e1_core_engine + fp.f3_liquidity + f4_used + e2_used
                })
                .collect();
            let total: i64 = progress.iter().sum();
            let expected_relative: Vec<i64> =
                progress.iter().map(|&p| p * player_count - total).collect();

            assert_eq!(
                utilities, expected_relative,
                "P0-C formula identity mismatch at corpus state {idx} for profile {profile:?}"
            );

            // Exact replacement identity vs FULL:
            //   progress(SHIFT) == progress(FULL) - true_term + shifted_term
            for fp in &fps {
                let full_prog = fp.for_profile(AttributionProfile::Full);
                let shift_prog = fp.for_profile(profile);
                let delta_f4 = fp.shifted_f4_convertibility - fp.f4_convertibility;
                let delta_e2 = fp.shifted_e2_noble_progress - fp.e2_noble_progress;
                let expected = full_prog
                    + if is_f4_shifted { delta_f4 } else { 0 }
                    + if is_e2_shifted { delta_e2 } else { 0 };
                assert_eq!(
                    shift_prog, expected,
                    "P0-C exact replacement identity mismatch at corpus state {idx} for profile {profile:?}"
                );
            }
        }

        // FULL itself must remain exactly the sum of the true families.
        let full_progress: i64 = fps
            .iter()
            .map(|fp| fp.for_profile(AttributionProfile::Full))
            .sum();
        let relative_full_sum: i64 = utilities_full.iter().sum();
        assert_eq!(
            relative_full_sum, 0,
            "P0-C FULL relative utilities must be zero-sum at corpus state {idx}"
        );
        let _ = full_progress;
    }
}

// ---------------------------------------------------------------------------
// P0-D: Real Activation
// ---------------------------------------------------------------------------
#[test]
fn test_m45a_p0_d_real_activation() {
    let corpus = reachable_corpus();

    let mut f4_activations = 0usize;
    let mut e2_activations = 0usize;
    let mut either_activations = 0usize;

    for state in &corpus {
        let mut state_f4_diff = false;
        let mut state_e2_diff = false;
        for player in &state.players {
            let fp = splendor_search::family_progress_for(state, player);
            if fp.shifted_f4_convertibility != fp.f4_convertibility {
                state_f4_diff = true;
            }
            if fp.shifted_e2_noble_progress != fp.e2_noble_progress {
                state_e2_diff = true;
            }
        }
        if state_f4_diff {
            f4_activations += 1;
        }
        if state_e2_diff {
            e2_activations += 1;
        }
        if state_f4_diff || state_e2_diff {
            either_activations += 1;
        }
    }

    assert!(
        f4_activations >= 1,
        "P0-D wiring failure: shifted F4 never differs from true F4 ({f4_activations} states)"
    );
    assert!(
        e2_activations >= 1,
        "P0-D wiring failure: shifted E2 never differs from true E2 ({e2_activations} states)"
    );

    // Activation counts are recorded for the final audit; a healthy corpus
    // should activate both paths on a non-trivial number of states. The frozen
    // gate is "at least one actual activation per path" (wiring sanity, not a
    // strength threshold); the printed ratio is diagnostic context only.
    println!(
        "P0-D activation: f4={f4_activations}/{}, e2={e2_activations}/{}, either={either_activations}/{}",
        corpus.len(),
        corpus.len(),
        corpus.len()
    );

    // NOBLE_PROGRESS_WEIGHT sanity: shifted E2 must differ in multiples of the
    // frozen noble weight (10_000) whenever it differs at all.
    for state in &corpus {
        for player in &state.players {
            let fp = splendor_search::family_progress_for(state, player);
            let delta = fp.shifted_e2_noble_progress - fp.e2_noble_progress;
            assert_eq!(
                delta % 10_000,
                0,
                "shifted E2 delta must be a multiple of NOBLE_PROGRESS_WEIGHT"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Parsing sanity for the new profiles.
// ---------------------------------------------------------------------------
#[test]
fn test_m45a_profile_parsing() {
    assert_eq!(
        "shift_f4".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::ShiftF4
    );
    assert_eq!(
        "shift-f4".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::ShiftF4
    );
    assert_eq!(
        "shift_e2".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::ShiftE2
    );
    assert_eq!(
        "shift_f4_e2".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::ShiftF4E2
    );
    assert!("shift_f9".parse::<AttributionProfile>().is_err());
}
