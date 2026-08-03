use splendor_belief::build_information_set_v1;
use splendor_core::{visible_events, Audience, FullState, GameConfig, PlayerId, Ruleset};
use splendor_imperfect_search::{
    aggregate_root_determinizations_v1, analyze_player_view_v1, RootDeterminizationConfigV1,
};
use splendor_search::SearchConfigV1;

fn config() -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed: 0xC4_2026,
        sample_count: 1,
        continuation_search: SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: 1,
        },
    }
}

#[test]
fn composition_captures_hashes_and_matches_direct_c3() {
    let (state, setup) = FullState::new(GameConfig {
        player_count: 2,
        seed: 401,
        ruleset: Ruleset::base_v1(),
    })
    .expect("setup");
    let viewer = PlayerId(0);
    let observation = state.observation(viewer);
    let visible_history = visible_events(&setup.events, Audience::Player(viewer));
    let before_observation = observation.clone();
    let before_history = visible_history.clone();

    let composed =
        analyze_player_view_v1(Ruleset::base_v1(), &observation, &visible_history, config())
            .expect("composition");
    let information_set =
        build_information_set_v1(Ruleset::base_v1(), &observation, &visible_history)
            .expect("information set");
    let direct = aggregate_root_determinizations_v1(&information_set, config())
        .expect("direct C3 aggregation");

    assert_eq!(
        composed.visible_history_hash().as_str(),
        information_set.visible_history_hash().as_str()
    );
    assert_eq!(
        composed.information_set_hash().as_str(),
        information_set.information_set_hash().as_str()
    );
    assert_eq!(composed.result(), &direct);
    assert_eq!(observation, before_observation);
    assert_eq!(visible_history, before_history);
}

#[test]
fn composition_preserves_c3_viewer_precondition() {
    let (state, setup) = FullState::new(GameConfig {
        player_count: 2,
        seed: 402,
        ruleset: Ruleset::base_v1(),
    })
    .expect("setup");
    let observation = state.observation(PlayerId(1));
    let visible_history = visible_events(&setup.events, Audience::Player(PlayerId(1)));
    let error =
        analyze_player_view_v1(Ruleset::base_v1(), &observation, &visible_history, config())
            .unwrap_err();

    assert!(matches!(
        error,
        splendor_imperfect_search::ImperfectSearchError::ViewerIsNotRootPlayer { .. }
    ));
}
