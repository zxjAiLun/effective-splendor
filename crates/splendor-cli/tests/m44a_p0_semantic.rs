//! M44A P0 Semantic and Attribution Gates (H0-A, H0-B, H0-C, Family Partition, Exact Masks, Zero-Progress).
//!
//! Verifies:
//! - H0-A: Bit-for-bit utility equality between StaticEvaluatorAttributionV1(FULL) and StaticEvaluatorV1
//!   on both non-terminal states and terminal states with various rank outcomes.
//! - H0-B: Root decision identity on frozen M07 12-position corpus (12/12 match FULL == det-s4-d1-n1)
//!   using authoritative frozen case replay reconstruction.
//! - H0-C: >=64 reachable non-terminal states bit-for-bit utility equality.
//! - Family Partition: FULL progress == F1 + F2 + F3 + F4 exact integer equality for all states/players.
//! - Exact Mask Microfixtures: Hand-calculated exact integer delta assertions for each family.
//! - Zero-Progress Semantics: Non-terminal utilities are strictly [0, 0], terminal equals terminal_rank_base.

use splendor_catalog::card;
use splendor_core::{
    visible_events, Action, Audience, FullState, GameConfig, Gems, PlayerId, Ruleset,
    TerminalReason, Tier,
};
use splendor_imperfect_search::{
    analyze_player_view_attribution_v1, analyze_player_view_v1, RootDeterminizationConfigV1,
};
use splendor_replay::{ReplayRecorder, ReplayV1};
use splendor_search::{
    canonical_order, terminal_rank_base, AttributionProfile, SearchConfigV1,
    StaticEvaluatorAttributionV1, StaticEvaluatorV1, TERMINAL_RANK_UNIT,
};
use std::path::Path;

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
// H0-A: Utility Identity on Non-Terminal AND Terminal States
// ---------------------------------------------------------------------------
#[test]
fn test_h0_a_utility_identity() {
    // 1. Non-terminal reachable states
    for seed in [1111, 2222, 3333, 4444] {
        let mut state = new_game(seed);
        for _ in 0..10 {
            let u_orig = StaticEvaluatorV1::utilities(&state).unwrap();
            let u_attr =
                StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::Full).unwrap();
            assert_eq!(
                u_orig, u_attr,
                "H0-A non-terminal utility mismatch on seed {seed}"
            );

            let legal = state.legal_actions();
            if legal.is_empty() || state.is_terminal() {
                break;
            }
            state.apply(legal[0]).unwrap();
        }
    }

    // 2. Terminal states with various rank outcomes and player counts (P1-2 fix)
    for player_count in [2u8, 3, 4] {
        for ranks in [
            vec![0, 1, 2, 3],
            vec![1, 0, 2, 3],
            vec![0, 0, 1, 2], // shared winners
            vec![3, 2, 1, 0],
        ] {
            let mut state = FullState::new(GameConfig {
                player_count,
                seed: 8888,
                ruleset: Ruleset::base_v1(),
            })
            .unwrap()
            .0;

            state.phase = splendor_core::Phase::GameOver;
            let current_ranks = ranks[..player_count as usize].to_vec();
            let scores = current_ranks
                .iter()
                .map(|&r| if r == 0 { 15 } else { 10 - r })
                .collect();
            let winners = current_ranks
                .iter()
                .enumerate()
                .filter(|(_, &r)| r == 0)
                .map(|(p, _)| PlayerId(p as u8))
                .collect();

            state.result = Some(splendor_core::GameResult {
                scores,
                ranks: current_ranks,
                winners,
                reason: TerminalReason::PrestigeThreshold,
            });

            let u_orig = StaticEvaluatorV1::utilities(&state).unwrap();
            let u_attr =
                StaticEvaluatorAttributionV1::utilities(&state, AttributionProfile::Full).unwrap();
            assert_eq!(
                u_orig, u_attr,
                "H0-A terminal utility mismatch on player_count {player_count}"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// H0-B: Authoritative M07 12-Position Corpus Reproduction (P1-1 fix)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct FrozenCase {
    case_id: &'static str,
    player_count: u8,
    game_seed: u64,
    continuation_seed: u64,
    ply: u32,
    prefix: Vec<Action>,
}

fn next_xorshift64_star(state: &mut u64) -> u64 {
    let mut x = *state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    *state = x;
    x.wrapping_mul(0x2545_F491_4F6C_DD1D)
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

#[test]
fn test_h0_b_authoritative_m07_corpus_identity() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let corpus_path = repo_root.join("benchmarks/m07-determinization-v1.corpus.json");
    assert!(corpus_path.exists(), "frozen M07 corpus file must exist");

    let cases = frozen_m07_12_cases();
    assert_eq!(cases.len(), 12, "Must evaluate exactly 12 frozen cases");

    let cfg_n1 = m42s_n1_config();
    let ruleset = Ruleset::base_v1();

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

        // 1. Evaluate with det-s4-d1-n1
        let analysis_n1 = analyze_player_view_v1(ruleset, &obs, &visible_history, cfg_n1)
            .unwrap_or_else(|e| panic!("{}: n1 failed: {e}", case.case_id));

        // 2. Evaluate with M44A FULL attribution profile
        let analysis_full = analyze_player_view_attribution_v1(
            ruleset,
            &obs,
            &visible_history,
            cfg_n1,
            AttributionProfile::Full,
        )
        .unwrap_or_else(|e| panic!("{}: FULL failed: {e}", case.case_id));

        let res_n1 = analysis_n1.result();
        let res_full = analysis_full.result();

        assert_eq!(
            res_n1.action, res_full.action,
            "{}: H0-B action mismatch",
            case.case_id
        );
        assert_eq!(
            res_n1.action_aggregates.len(),
            res_full.action_aggregates.len(),
            "{}: H0-B action count mismatch",
            case.case_id
        );
        for (i, (agg_n1, agg_full)) in res_n1
            .action_aggregates
            .iter()
            .zip(&res_full.action_aggregates)
            .enumerate()
        {
            assert_eq!(
                agg_n1.action, agg_full.action,
                "{}: H0-B action {i} order mismatch",
                case.case_id
            );
            assert_eq!(
                agg_n1.utility_sum_by_player, agg_full.utility_sum_by_player,
                "{}: H0-B action {i} utility mismatch",
                case.case_id
            );
        }
    }
}

// ---------------------------------------------------------------------------
// H0-C: Reachable-State Stress Corpus (>= 64 Non-Terminal States)
// Uses an isolated seed namespace (6_000_000..6_000_020) disjoint from Arena
// ---------------------------------------------------------------------------
#[test]
fn test_h0_c_reachable_state_stress_corpus() {
    let mut tested_states = 0;
    // Disjoint seed namespace: 6_000_000..6_000_020 (P2-A fix)
    for seed in 6_000_000..6_000_020 {
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
                assert_eq!(
                    fp.for_profile(AttributionProfile::DropScore),
                    sum_parts - fp.f1_score
                );
                assert_eq!(
                    fp.for_profile(AttributionProfile::DropEngine),
                    sum_parts - fp.f2_engine
                );
                assert_eq!(
                    fp.for_profile(AttributionProfile::DropLiquidity),
                    sum_parts - fp.f3_liquidity
                );
                assert_eq!(
                    fp.for_profile(AttributionProfile::DropConvertibility),
                    sum_parts - fp.f4_convertibility
                );
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
// Exact Mask Microfixtures: Hand-Calculated Independent Family Contributions (P1-3 fix)
// ---------------------------------------------------------------------------
#[test]
fn test_exact_mask_microfixtures() {
    let base_state = new_game(777);

    // 1. F1 (Prestige difference only)
    {
        let mut s = base_state.clone();
        s.players[0].prestige = 3;
        s.players[1].prestige = 0;
        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);

        // Hand calculation:
        // delta_f1 = 3 * 100_000_000 = 300_000_000 exact
        assert_eq!(fp[0].f1_score - fp_base[0].f1_score, 300_000_000);
        assert_eq!(fp[0].f2_engine, fp_base[0].f2_engine);
        assert_eq!(fp[0].f3_liquidity, fp_base[0].f3_liquidity);
        assert_eq!(fp[0].f4_convertibility, fp_base[0].f4_convertibility);
        assert_eq!(
            fp[0].for_profile(AttributionProfile::DropScore),
            fp_base[0].total()
        );
    }

    // 2. F2 (Purchased cards count only - zero bonuses, zero noble progress impact)
    {
        let mut s = base_state.clone();
        // Add 2 purchased cards without adding bonuses (player.bonuses remains [0; 5])
        s.players[0].purchased = vec![splendor_catalog::CardId(1), splendor_catalog::CardId(2)];
        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);

        // Hand calculation:
        // delta_f2 = 2 * PURCHASED_CARD_WEIGHT = 2 * 250_000 = 500_000 exact
        assert_eq!(fp[0].f2_engine - fp_base[0].f2_engine, 500_000);
        assert_eq!(fp[0].f1_score, fp_base[0].f1_score);
        assert_eq!(fp[0].f3_liquidity, fp_base[0].f3_liquidity);
        assert_eq!(fp[0].f4_convertibility, fp_base[0].f4_convertibility);

        // When DROP_ENGINE is active, f2_engine is masked away
        assert_eq!(
            fp[0].for_profile(AttributionProfile::DropEngine),
            fp[0].total() - fp[0].f2_engine
        );
    }

    // 3. F3 (Reserved cards count only - reserving an un-affordable card so F4 is untouched)
    {
        let mut s = base_state.clone();
        // Reserve an expensive Tier 3 card that player cannot afford (cost is high, player has 0 tokens)
        s.players[0].reserved.push(splendor_core::ReservedCard {
            card: splendor_catalog::CardId(70), // Tier 3 card
            from_deck: false,
        });
        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);

        // Hand calculation:
        // delta_f3 = 1 * RESERVED_CARD_WEIGHT = 10_000 exact
        assert_eq!(fp[0].f3_liquidity - fp_base[0].f3_liquidity, 10_000);
        assert_eq!(fp[0].f1_score, fp_base[0].f1_score);
        assert_eq!(fp[0].f2_engine, fp_base[0].f2_engine);
        assert_eq!(fp[0].f4_convertibility, fp_base[0].f4_convertibility);
        // When DROP_LIQUIDITY is active, f3_liquidity is masked away
        assert_eq!(
            fp[0].for_profile(AttributionProfile::DropLiquidity),
            fp[0].total() - fp[0].f3_liquidity
        );
    }

    // 4. F4 (Affordability only - hand-calculated exact affordable card count & max prestige)
    {
        // Start from base_state where player 0 has 0 tokens and 0 bonuses -> f4_before = 0
        let fp_base = StaticEvaluatorAttributionV1::family_progress_for_all(&base_state);
        assert_eq!(fp_base[0].f4_convertibility, 0);

        // Give player 0 exactly 10 gold tokens. Compute exact affordable cards on market:
        let mut s = base_state.clone();
        s.players[0].tokens.gold = 10;

        let mut expected_count = 0i64;
        let mut expected_max_prestige = 0i64;
        for card_id in s.market.iter().flat_map(|row| row.iter().flatten()) {
            let def = card(*card_id);
            if s.players[0].can_afford(def.cost) {
                expected_count += 1;
                expected_max_prestige = expected_max_prestige.max(i64::from(def.prestige));
            }
        }
        assert!(expected_count > 0);
        let expected_f4 = expected_count * 100_000 + expected_max_prestige * 5_000_000;

        let fp = StaticEvaluatorAttributionV1::family_progress_for_all(&s);
        // Hand-calculated exact equality:
        assert_eq!(fp[0].f4_convertibility, expected_f4);
        assert_eq!(fp[0].f1_score, fp_base[0].f1_score);
        assert_eq!(fp[0].f2_engine, fp_base[0].f2_engine);
        // F3 changed by 10 gold tokens = 10 * 40_000 = 400_000
        assert_eq!(fp[0].f3_liquidity - fp_base[0].f3_liquidity, 400_000);
        // Under DROP_CONVERTIBILITY, expected_f4 is dropped exactly:
        assert_eq!(
            fp[0].for_profile(AttributionProfile::DropConvertibility),
            fp[0].total() - expected_f4
        );
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
        scores: vec![15, 10],
        ranks: vec![0, 1],
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
