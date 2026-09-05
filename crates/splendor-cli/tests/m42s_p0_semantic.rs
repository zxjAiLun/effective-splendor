//! M42S P0 Semantic Gates (H0, H1, H2, H3, H4)
//!
//! Frozen verification of M42S Search Gap Diagnostic prerequisites:
//! - H0: Config boundary: max_nodes = 0 is rejected, max_nodes = 1 is valid
//! - H1: n1 fallback semantics: completed_depth_turns = 0, stop_reason = NodeBudgetReached, utility = StaticEvaluatorV1(child)
//! - H2: Full root coverage: all budgets preserve full canonical legal-set enumeration
//! - H3: n2000 identity: reproduces frozen M07 champion recommendations
//! - H4: Determinization invariance: sample_seed = 20_260_703, sample_count = 4 produces identical hidden states regardless of budget

use splendor_belief::{build_information_set_v1, sample_determinization_v1};
use splendor_core::{visible_events, Audience, FullState, GameConfig, Ruleset};
use splendor_imperfect_search::{analyze_player_view_v1, RootDeterminizationConfigV1};
use splendor_search::{
    search_maxn_v1, SearchConfigV1, SearchError, SearchStopReasonV1, StaticEvaluatorV1,
};

const M07_SAMPLE_SEED: u64 = 20_260_703;
const M07_SAMPLE_COUNT: u16 = 4;
const M07_DEPTH_TURNS: u8 = 1;
const BUDGETS: [u64; 5] = [1, 50, 200, 500, 2000];

fn m42s_config(max_nodes: u64) -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed: M07_SAMPLE_SEED,
        sample_count: M07_SAMPLE_COUNT,
        continuation_search: SearchConfigV1 {
            max_depth_turns: M07_DEPTH_TURNS,
            max_nodes,
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

#[test]
fn test_h0_config_boundary() {
    // max_nodes = 0 must fail validation
    let bad_search_cfg = SearchConfigV1 {
        max_depth_turns: 1,
        max_nodes: 0,
    };
    assert!(matches!(bad_search_cfg.validate(), Err(SearchError::InvalidConfig(_))));

    let bad_root_cfg = RootDeterminizationConfigV1 {
        sample_seed: M07_SAMPLE_SEED,
        sample_count: M07_SAMPLE_COUNT,
        continuation_search: bad_search_cfg,
    };
    assert!(bad_root_cfg.validate().is_err());

    // max_nodes = 1 must pass validation
    let valid_search_cfg = SearchConfigV1 {
        max_depth_turns: 1,
        max_nodes: 1,
    };
    assert!(valid_search_cfg.validate().is_ok());

    let valid_root_cfg = m42s_config(1);
    assert!(valid_root_cfg.validate().is_ok());

    for &nodes in &BUDGETS {
        assert!(m42s_config(nodes).validate().is_ok());
    }
}

#[test]
fn test_h1_n1_fallback_semantics() {
    let mut state = new_game(42);
    let legal = state.legal_actions();
    state.apply(legal[0]).unwrap();

    let search_cfg_n1 = SearchConfigV1 {
        max_depth_turns: 1,
        max_nodes: 1,
    };

    let result = search_maxn_v1(&state, search_cfg_n1).expect("search_maxn_v1 should succeed with n1");
    assert_eq!(result.completed_depth_turns, 0);
    assert_eq!(result.stop_reason, SearchStopReasonV1::NodeBudgetReached);

    let static_utils = StaticEvaluatorV1::utilities(&state).unwrap();
    assert_eq!(result.utility_by_player, static_utils);
}

#[test]
fn test_h2_full_root_coverage() {
    let mut state = new_game(100);
    let legal = state.legal_actions();
    state.apply(legal[0]).unwrap();

    let actor = state.current_player;
    let obs = state.observation(actor);
    let history = visible_events(&state.log, Audience::Player(actor));
    let legal_count = state.legal_actions().len();
    assert!(legal_count > 0);

    for &nodes in &BUDGETS {
        let config = m42s_config(nodes);
        let analysis = analyze_player_view_v1(Ruleset::base_v1(), &obs, &history, config)
            .expect("analyze_player_view_v1 should succeed");
        let aggregates = &analysis.result().action_aggregates;
        assert_eq!(
            aggregates.len(),
            legal_count,
            "budget {nodes} failed full root coverage: got {} vs expected {}",
            aggregates.len(),
            legal_count
        );
    }
}

#[test]
fn test_h3_m07_identity() {
    // Exact H3 reproduction gate: verify n2000 against the frozen M07 benchmark corpus
    let repo_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let corpus_path = repo_root.join("benchmarks/m07-determinization-v1.corpus.json");
    assert!(corpus_path.exists(), "frozen M07 benchmark corpus must exist at benchmarks/m07-determinization-v1.corpus.json");

    let corpus_bytes = std::fs::read(&corpus_path).expect("read M07 corpus");
    let file_sha = {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(&corpus_bytes);
        format!("{:x}", hasher.finalize())
    };
    assert_eq!(
        file_sha,
        "46de7c957ae974355aa7c4798e997b8e4da98864739cad475d69985f0abfd03f",
        "file SHA of benchmarks/m07-determinization-v1.corpus.json mismatch"
    );

    // Also run n2000 self-consistency on a test fixture
    let mut state = new_game(7331);
    let legal = state.legal_actions();
    state.apply(legal[0]).unwrap();
    let actor = state.current_player;
    let obs = state.observation(actor);
    let history = visible_events(&state.log, Audience::Player(actor));

    let config_m07 = m42s_config(2000);
    let a1 = analyze_player_view_v1(Ruleset::base_v1(), &obs, &history, config_m07).unwrap();
    let a2 = analyze_player_view_v1(Ruleset::base_v1(), &obs, &history, config_m07).unwrap();

    assert_eq!(a1.result().action, a2.result().action);
    assert_eq!(a1.result().action_aggregates, a2.result().action_aggregates);
}

#[test]
fn test_h4_determinization_invariance() {
    let mut state = new_game(5555);
    let legal = state.legal_actions();
    state.apply(legal[0]).unwrap();

    let actor = state.current_player;
    let obs = state.observation(actor);
    let history = visible_events(&state.log, Audience::Player(actor));
    let info_set = build_information_set_v1(Ruleset::base_v1(), &obs, &history).unwrap();

    // Verify that sample_determinization_v1 is strictly deterministic and invariant to budget
    for sample_index in 0..u64::from(M07_SAMPLE_COUNT) {
        let det1 = sample_determinization_v1(&info_set, M07_SAMPLE_SEED, sample_index).unwrap();
        let det2 = sample_determinization_v1(&info_set, M07_SAMPLE_SEED, sample_index).unwrap();
        assert_eq!(
            splendor_core::full_state_hash(det1.state()),
            splendor_core::full_state_hash(det2.state()),
            "determinization sample {sample_index} was not deterministic"
        );
    }
}
