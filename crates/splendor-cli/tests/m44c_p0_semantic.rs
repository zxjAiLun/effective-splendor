//! M44C P0 Semantic and Attribution Gates.
//!
//! Verifies:
//! - P0-A: Algebraic identity regression (B == P == C across 90 catalog cards and >= 256 reachable states).
//! - P0-B: Equalized LOO isomorphism (EqualDropBonus == EqualDropPurchased bit-exact across M07 positions and >= 128 states).
//! - P0-C: FULL scale identity (EngineScale100 == FULL bit-exact across M07 positions and >= 128 states).
//! - P0-D: Scale profile ordering, constants, and FromStr string parsing.

use splendor_catalog::all_cards;
use splendor_core::{visible_events, Action, Audience, FullState, GameConfig, Gems, Ruleset, Tier};
use splendor_imperfect_search::{analyze_player_view_attribution_v1, RootDeterminizationConfigV1};
use splendor_replay::{ReplayRecorder, ReplayV1};
use splendor_search::{
    canonical_order, AttributionProfile, SearchConfigV1, StaticEvaluatorAttributionV1,
    ENGINE_SCALE_100_WEIGHT, ENGINE_SCALE_25_WEIGHT, ENGINE_SCALE_50_WEIGHT,
    ENGINE_SCALE_88_WEIGHT, EQUAL_LOO_WEIGHT,
};
use std::path::Path;

const M07_SAMPLE_SEED: u64 = 20_260_703;
const M07_SAMPLE_COUNT: u16 = 4;
const M07_DEPTH_TURNS: u8 = 1;

fn m44c_n1_config() -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed: M07_SAMPLE_SEED,
        sample_count: M07_SAMPLE_COUNT,
        continuation_search: SearchConfigV1 {
            max_depth_turns: M07_DEPTH_TURNS,
            max_nodes: 1, // Strict n1 shell
        },
    }
}

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

// ---------------------------------------------------------------------------
// Frozen M07 Benchmark Cases (from m44a/m44b)
// ---------------------------------------------------------------------------
struct FrozenCase {
    case_id: &'static str,
    player_count: u8,
    game_seed: u64,
    continuation_seed: u64,
    ply: u32,
    prefix: Vec<Action>,
}

fn record_frozen_case_replay(case: &FrozenCase) -> ReplayV1 {
    let mut recorder = ReplayRecorder::new(GameConfig {
        player_count: case.player_count,
        seed: case.game_seed,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap();

    for action in &case.prefix {
        recorder.apply(*action).unwrap();
    }

    let mut state = case.continuation_seed;
    let mut plies = case.prefix.len() as u32;
    while !recorder.is_terminal() {
        let actions = canonical_order(&recorder.legal_actions());
        let action = actions[(next_xorshift64_star(&mut state) % actions.len() as u64) as usize];
        recorder.apply(action).unwrap();
        plies += 1;
        assert!(plies < 10_000);
    }

    let (_, replay) = recorder.finish().unwrap();
    replay
}

fn frozen_m07_12_cases() -> Vec<FrozenCase> {
    let zero = Gems::ZERO;
    vec![
        FrozenCase {
            case_id: "m07-2p-p0",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            ply: 0,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-2p-p2",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            ply: 2,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-2p-p4",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            ply: 4,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-2p-p6",
            player_count: 2,
            game_seed: 7002,
            continuation_seed: 17002,
            ply: 6,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p0",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            ply: 0,
            prefix: vec![
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 0,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p2",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            ply: 2,
            prefix: vec![
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 0,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p4",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            ply: 4,
            prefix: vec![
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 0,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-3p-p6",
            player_count: 3,
            game_seed: 7003,
            continuation_seed: 17003,
            ply: 6,
            prefix: vec![
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 1,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 0,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 0,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p0",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            ply: 0,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 3,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 1,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p2",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            ply: 2,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 3,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 1,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p4",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            ply: 4,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 3,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 1,
                    give_back: zero,
                },
            ],
        },
        FrozenCase {
            case_id: "m07-4p-p6",
            player_count: 4,
            game_seed: 7004,
            continuation_seed: 17004,
            ply: 6,
            prefix: vec![
                Action::ReserveMarket {
                    tier: Tier::One,
                    slot: 2,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::One,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Two,
                    slot: 3,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Two,
                    give_back: zero,
                },
                Action::ReserveDeck {
                    tier: Tier::Three,
                    give_back: zero,
                },
                Action::ReserveMarket {
                    tier: Tier::Three,
                    slot: 1,
                    give_back: zero,
                },
            ],
        },
    ]
}

// ---------------------------------------------------------------------------
// P0-A: Algebraic Identity Invariant Regression
// ---------------------------------------------------------------------------
#[test]
fn test_m44c_p0_a_algebraic_identity_invariant() {
    // 1. Catalog integrity check: exactly 90 cards in base Splendor, each with exactly 1 bonus
    let cards = all_cards();
    assert_eq!(
        cards.len(),
        90,
        "Base catalog must contain exactly 90 cards"
    );
    for def in cards {
        // Bonus must be valid GemColor (not gold, which is not in GemColor::ALL)
        assert!(
            matches!(
                def.bonus,
                splendor_catalog::GemColor::White
                    | splendor_catalog::GemColor::Blue
                    | splendor_catalog::GemColor::Green
                    | splendor_catalog::GemColor::Red
                    | splendor_catalog::GemColor::Black
            ),
            "Card {:?} must have a single valid GemColor bonus",
            def.id
        );
    }

    // 2. Initial state and transition invariance across >= 256 reachable states in 2p/3p/4p
    let mut total_states = 0;
    for player_count in [2u8, 3, 4] {
        for seed_offset in 0..10 {
            let seed = 6_300_000 + u64::from(player_count) * 10_000 + seed_offset;
            let mut state = new_game(seed, player_count);

            // Initial state: B(p) == 0, P(p) == 0
            for (p_idx, p) in state.players.iter().enumerate() {
                let bonus_sum: i64 = p.bonuses.iter().map(|&b| i64::from(b)).sum();
                let card_count = p.purchased.len() as i64;
                assert_eq!(bonus_sum, 0, "Initial bonuses must be 0 for player {p_idx}");
                assert_eq!(card_count, 0, "Initial cards must be 0 for player {p_idx}");
                assert_eq!(bonus_sum, card_count);
            }

            let mut rng_state = seed ^ 0xDEAD_BEEF_CAFE;
            while !state.is_terminal() && total_states < 300 {
                let families = StaticEvaluatorAttributionV1::family_progress_for_all(&state);
                for (p_idx, fp) in families.iter().enumerate() {
                    assert_eq!(
                        fp.total_permanent_bonuses, fp.purchased_card_count,
                        "Algebraic identity broken on seed {seed}, player {p_idx}"
                    );
                    // Core engine must equal C * 2,250,000
                    let c = fp.purchased_card_count;
                    assert_eq!(
                        fp.e1_core_engine,
                        c * ENGINE_SCALE_100_WEIGHT,
                        "Core engine collapse broken on seed {seed}, player {p_idx}"
                    );
                }
                total_states += 1;

                let legal = canonical_order(&state.legal_actions());
                if legal.is_empty() {
                    break;
                }
                let choice = (next_xorshift64_star(&mut rng_state) % legal.len() as u64) as usize;
                state.apply(legal[choice]).unwrap();
            }
        }
    }
    assert!(
        total_states >= 256,
        "Must verify at least 256 reachable states, verified {total_states}"
    );
}

// ---------------------------------------------------------------------------
// P0-B: Equalized LOO Isomorphism (Bit-Exact)
// ---------------------------------------------------------------------------
#[test]
fn test_m44c_p0_b_equalized_loo_isomorphism() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let corpus_path = repo_root.join("benchmarks/m07-determinization-v1.corpus.json");
    assert!(corpus_path.exists(), "frozen M07 corpus file must exist");

    let cfg_n1 = m44c_n1_config();
    let ruleset = Ruleset::base_v1();

    // 1. Evaluate on the 12 frozen M07 benchmark cases
    let cases = frozen_m07_12_cases();
    assert_eq!(cases.len(), 12);
    for case in &cases {
        let replay = record_frozen_case_replay(case);
        let (mut state, setup) = FullState::new(GameConfig {
            player_count: replay.player_count,
            seed: replay.seed,
            ruleset,
        })
        .unwrap();

        let viewer = replay.steps[case.ply as usize].actor;
        let mut visible_history = visible_events(&setup.events, Audience::Player(viewer));

        for step in replay.steps.iter().take(case.ply as usize) {
            let res = state.apply(step.action).unwrap();
            visible_history.extend(visible_events(&res.events, Audience::Player(viewer)));
        }

        let obs = state.observation(viewer);

        let analysis_drop_b = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg_n1,
            AttributionProfile::EqualDropBonus,
        )
        .unwrap();

        let analysis_drop_p = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg_n1,
            AttributionProfile::EqualDropPurchased,
        )
        .unwrap();

        let res_drop_b = analysis_drop_b.result();
        let res_drop_p = analysis_drop_p.result();

        // Exact utility equality
        assert_eq!(
            res_drop_b.action, res_drop_p.action,
            "P0-B chosen action mismatch on case {}",
            case.case_id
        );
        assert_eq!(
            res_drop_b.action_aggregates.len(),
            res_drop_p.action_aggregates.len()
        );
        for (a_b, a_p) in res_drop_b
            .action_aggregates
            .iter()
            .zip(&res_drop_p.action_aggregates)
        {
            assert_eq!(a_b.action, a_p.action);
            assert_eq!(
                a_b.utility_sum_by_player, a_p.utility_sum_by_player,
                "P0-B per-action score mismatch on case {}",
                case.case_id
            );
        }
    }

    // 2. Evaluate on >= 128 deterministic reachable states
    let mut evaluated_reachable = 0;
    for seed in 6_310_000..6_310_020 {
        let mut state = new_game(seed, 2);
        let mut rng_state = seed ^ 0xFACE_B00C;

        while !state.is_terminal() && evaluated_reachable < 140 {
            // Direct utility equality:
            let u_drop_b =
                StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::EqualDropBonus)
                    .unwrap();
            let u_drop_p = StaticEvaluatorAttributionV1::utilities(
                &state,
                AttributionProfile::EqualDropPurchased,
            )
            .unwrap();
            assert_eq!(
                u_drop_b, u_drop_p,
                "P0-B direct utility mismatch on seed {seed}"
            );
            evaluated_reachable += 1;

            let legal = canonical_order(&state.legal_actions());
            if legal.is_empty() {
                break;
            }
            let choice = (next_xorshift64_star(&mut rng_state) % legal.len() as u64) as usize;
            state.apply(legal[choice]).unwrap();
        }
    }
    assert!(
        evaluated_reachable >= 128,
        "Must evaluate >= 128 reachable states, evaluated {evaluated_reachable}"
    );
}

// ---------------------------------------------------------------------------
// P0-C: FULL Scale Identity (EngineScale100 == FULL Bit-Exact)
// ---------------------------------------------------------------------------
#[test]
fn test_m44c_p0_c_full_scale_identity() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let corpus_path = repo_root.join("benchmarks/m07-determinization-v1.corpus.json");
    assert!(corpus_path.exists(), "frozen M07 corpus file must exist");

    let cfg_n1 = m44c_n1_config();
    let ruleset = Ruleset::base_v1();

    // 1. Evaluate on the 12 frozen M07 benchmark cases
    let cases = frozen_m07_12_cases();
    assert_eq!(cases.len(), 12);
    for case in &cases {
        let replay = record_frozen_case_replay(case);
        let (mut state, setup) = FullState::new(GameConfig {
            player_count: replay.player_count,
            seed: replay.seed,
            ruleset,
        })
        .unwrap();

        let viewer = replay.steps[case.ply as usize].actor;
        let mut visible_history = visible_events(&setup.events, Audience::Player(viewer));

        for step in replay.steps.iter().take(case.ply as usize) {
            let res = state.apply(step.action).unwrap();
            visible_history.extend(visible_events(&res.events, Audience::Player(viewer)));
        }

        let obs = state.observation(viewer);

        let analysis_full = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg_n1,
            AttributionProfile::Full,
        )
        .unwrap();

        let analysis_scale_100 = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg_n1,
            AttributionProfile::EngineScale100,
        )
        .unwrap();

        let res_full = analysis_full.result();
        let res_scale_100 = analysis_scale_100.result();

        // Exact utility and choice identity
        assert_eq!(
            res_scale_100.action, res_full.action,
            "P0-C chosen action mismatch on case {}",
            case.case_id
        );
        assert_eq!(
            res_scale_100.action_aggregates.len(),
            res_full.action_aggregates.len()
        );
        for (a_100, a_full) in res_scale_100
            .action_aggregates
            .iter()
            .zip(&res_full.action_aggregates)
        {
            assert_eq!(a_100.action, a_full.action);
            assert_eq!(
                a_100.utility_sum_by_player, a_full.utility_sum_by_player,
                "P0-C per-action score mismatch on case {}",
                case.case_id
            );
        }
    }

    // 2. Evaluate on >= 128 deterministic reachable states
    let mut evaluated_reachable = 0;
    for seed in 6_320_000..6_320_020 {
        let mut state = new_game(seed, 2);
        let mut rng_state = seed ^ 0xBEEF_DEAD;

        while !state.is_terminal() && evaluated_reachable < 140 {
            let u_full =
                StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::Full).unwrap();
            let u_scale_100 =
                StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::EngineScale100)
                    .unwrap();
            assert_eq!(
                u_scale_100, u_full,
                "P0-C direct utility mismatch on seed {seed}"
            );
            evaluated_reachable += 1;

            let legal = canonical_order(&state.legal_actions());
            if legal.is_empty() {
                break;
            }
            let choice = (next_xorshift64_star(&mut rng_state) % legal.len() as u64) as usize;
            state.apply(legal[choice]).unwrap();
        }
    }
    assert!(
        evaluated_reachable >= 128,
        "Must evaluate >= 128 reachable states, evaluated {evaluated_reachable}"
    );
}

// ---------------------------------------------------------------------------
// P0-D: Scale Profile Constants & Parsing
// ---------------------------------------------------------------------------
#[test]
fn test_m44c_p0_d_scale_profile_constants_and_parsing() {
    // 1. Exact integer constants
    assert_eq!(ENGINE_SCALE_25_WEIGHT, 562_500);
    assert_eq!(ENGINE_SCALE_50_WEIGHT, 1_125_000);
    assert_eq!(ENGINE_SCALE_88_WEIGHT, 2_000_000);
    assert_eq!(ENGINE_SCALE_100_WEIGHT, 2_250_000);
    assert_eq!(EQUAL_LOO_WEIGHT, 1_125_000);

    // Exact proportions
    assert_eq!(ENGINE_SCALE_50_WEIGHT, 2 * ENGINE_SCALE_25_WEIGHT);
    assert_eq!(ENGINE_SCALE_100_WEIGHT, 4 * ENGINE_SCALE_25_WEIGHT);
    assert_eq!(ENGINE_SCALE_100_WEIGHT, 2_000_000 + 250_000);

    // 2. FromStr parsing
    assert_eq!(
        "engine_scale_25".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::EngineScale25
    );
    assert_eq!(
        "engine-scale-25".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::EngineScale25
    );
    assert_eq!(
        "engine_scale_50".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::EngineScale50
    );
    assert_eq!(
        "engine_scale_88".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::EngineScale88
    );
    assert_eq!(
        "engine_scale_100".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::EngineScale100
    );
    assert_eq!(
        "equal_drop_bonus".parse::<AttributionProfile>().unwrap(),
        AttributionProfile::EqualDropBonus
    );
    assert_eq!(
        "equal_drop_purchased"
            .parse::<AttributionProfile>()
            .unwrap(),
        AttributionProfile::EqualDropPurchased
    );
}
