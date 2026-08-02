//! M07 C3 integration tests: root-determinization aggregation.
//!
//! `FullState` is used here only as a referee/test oracle. The public C3
//! operation receives a validated `InformationSetV1` and never exposes a
//! sampled `FullState` or hidden card in its result.

use serde_json::Value;
use splendor_belief::{build_information_set_v1, sample_determinization_v1, InformationSetV1};
use splendor_catalog::card;
use splendor_core::{
    visible_events, Action, Audience, FullState, GameConfig, Gems, Phase, PlayerId, Ruleset, Tier,
};
use splendor_imperfect_search::{
    aggregate_root_determinizations_v1, ImperfectSearchError, RootActionAggregateV1,
    RootDeterminizationConfigV1, RootDeterminizationResultV1, RootDeterminizationStatsV1,
};
use splendor_search::{canonical_order, search_maxn_v1, SearchConfigV1, StaticEvaluatorV1};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

fn new_game(player_count: u8, seed: u64) -> FullState {
    let (state, _setup) = FullState::new(GameConfig {
        player_count,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("setup should succeed");
    state
}

fn drive(state: &mut FullState, script: &[(u8, Action)]) {
    for (player, action) in script {
        assert_eq!(state.current_player.0, *player);
        state.apply(*action).expect("apply should succeed");
        resolve_nobles(state);
    }
}

fn resolve_nobles(state: &mut FullState) {
    while state.phase == Phase::ChooseNoble {
        let noble = canonical_order(&state.legal_actions())
            .into_iter()
            .find_map(|action| match action {
                Action::ChooseNoble { noble } => Some(noble),
                _ => None,
            })
            .expect("ChooseNoble phase without a legal noble");
        state
            .apply(Action::ChooseNoble { noble })
            .expect("noble choice should succeed");
    }
}

fn rich_tokens() -> Gems {
    Gems {
        white: 10,
        blue: 10,
        green: 10,
        red: 10,
        black: 10,
        gold: 0,
    }
}

fn rm(tier: Tier, slot: u8) -> Action {
    Action::ReserveMarket {
        tier,
        slot,
        give_back: Gems::ZERO,
    }
}

fn rd(tier: Tier) -> Action {
    Action::ReserveDeck {
        tier,
        give_back: Gems::ZERO,
    }
}

fn info_set(state: &FullState, viewer: PlayerId) -> InformationSetV1 {
    let observation = state.observation(viewer);
    let history = visible_events(&state.log, Audience::Player(viewer));
    build_information_set_v1(Ruleset::base_v1(), &observation, &history).expect("build")
}

fn game_2p_hidden(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::One)),
            (0, rd(Tier::Two)),
            (1, rm(Tier::One, 1)),
            (0, rm(Tier::Two, 0)),
            (1, rd(Tier::Two)),
        ],
    );
    state
}

fn game_3p(seed: u64) -> FullState {
    let mut state = new_game(3, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::Two)),
            (2, rd(Tier::One)),
            (0, rm(Tier::Two, 0)),
            (1, rm(Tier::One, 1)),
            (2, rm(Tier::One, 2)),
        ],
    );
    state
}

fn game_4p(seed: u64) -> FullState {
    let mut state = new_game(4, seed);
    drive(
        &mut state,
        &[
            (0, rm(Tier::One, 0)),
            (1, rd(Tier::One)),
            (2, rd(Tier::Two)),
            (3, rd(Tier::One)),
            (0, rm(Tier::Two, 0)),
            (1, rm(Tier::One, 1)),
            (2, rm(Tier::One, 2)),
            (3, rm(Tier::One, 3)),
        ],
    );
    state
}

fn game_3p_viewer1(seed: u64) -> FullState {
    let mut state = new_game(3, seed);
    drive(
        &mut state,
        &[
            (0, rd(Tier::One)),
            (1, rm(Tier::One, 0)),
            (2, rd(Tier::Two)),
            (0, rm(Tier::One, 1)),
        ],
    );
    state
}

fn choose_noble_state(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    state.nobles = vec![splendor_core::NobleId(0), splendor_core::NobleId(1)];
    state.players[0].bonuses = [4; 5];
    state.players[0].tokens = rich_tokens();
    let slot = state.market[Tier::One.index()]
        .iter()
        .position(Option::is_some)
        .expect("initial market is full") as u8;
    state
        .apply(Action::BuyMarket {
            tier: Tier::One,
            slot,
        })
        .expect("buy should succeed");
    assert_eq!(state.phase, Phase::ChooseNoble);
    state
}

fn terminal_child_state(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    state
        .apply(rd(Tier::One))
        .expect("first reserve should succeed");
    assert_eq!(state.current_player, PlayerId(1));
    state.players[1].prestige = state.ruleset.prestige_to_end;
    let slot = state.market[Tier::One.index()]
        .iter()
        .position(Option::is_some)
        .expect("market card") as u8;
    let card_id = state.market[Tier::One.index()][slot as usize].expect("market card");
    let cost = card(card_id).cost;
    state.players[1].tokens = Gems {
        white: cost[0],
        blue: cost[1],
        green: cost[2],
        red: cost[3],
        black: cost[4],
        gold: 0,
    };
    state
}

fn game_over_state(seed: u64) -> FullState {
    let mut state = new_game(2, seed);
    state.players[0].prestige = state.ruleset.prestige_to_end;
    let mut guard = 0;
    while !state.is_terminal() {
        guard += 1;
        assert!(guard < 16, "game did not finish");
        let player = state.current_player.index();
        state.players[player].tokens = rich_tokens();
        let action = canonical_order(&state.legal_actions())
            .into_iter()
            .find(|action| {
                matches!(
                    action,
                    Action::BuyMarket { .. } | Action::BuyReserved { .. }
                )
            })
            .expect("rich player should have a purchase action");
        state.apply(action).expect("purchase should succeed");
        resolve_nobles(&mut state);
    }
    state
}

fn config(sample_count: u16) -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed: 0xC3_2026,
        sample_count,
        continuation_search: SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: 1,
        },
    }
}

// ---------------------------------------------------------------------------
// Independent reference loop
// ---------------------------------------------------------------------------

fn reference_aggregate(
    information_set: &InformationSetV1,
    config: RootDeterminizationConfigV1,
) -> (Vec<RootActionAggregateV1>, RootDeterminizationStatsV1) {
    let player_count = usize::from(information_set.observation().public.player_count);
    let mut expected_actions = None;
    let mut aggregates = Vec::new();
    let mut stats = RootDeterminizationStatsV1 {
        samples: config.sample_count,
        root_actions: 0,
        continuation_searches: 0,
        terminal_children: 0,
        nodes_visited: 0,
        nodes_expanded: 0,
        leaf_evaluations: 0,
        transposition_hits: 0,
    };

    for sample_index in 0..u64::from(config.sample_count) {
        let determinization =
            sample_determinization_v1(information_set, config.sample_seed, sample_index)
                .expect("reference determinization should succeed");
        let actions = canonical_order(&determinization.state().legal_actions());
        if expected_actions.is_none() {
            stats.root_actions = actions.len() as u32;
            aggregates = actions
                .iter()
                .copied()
                .map(|action| RootActionAggregateV1 {
                    action,
                    utility_sum_by_player: vec![0; player_count],
                })
                .collect();
            expected_actions = Some(actions);
        } else {
            assert_eq!(expected_actions.as_deref(), Some(actions.as_slice()));
        }

        for (action_index, action) in expected_actions
            .as_deref()
            .expect("reference actions initialized")
            .iter()
            .copied()
            .enumerate()
        {
            let mut child = determinization.state().clone();
            child.apply(action).expect("reference action should apply");
            let utility_by_player = if child.is_terminal() {
                stats.terminal_children += 1;
                StaticEvaluatorV1::utilities(&child).expect("terminal evaluator")
            } else {
                let continuation = search_maxn_v1(&child, config.continuation_search)
                    .expect("reference continuation search");
                stats.continuation_searches += 1;
                stats.nodes_visited += continuation.stats.nodes_visited;
                stats.nodes_expanded += continuation.stats.nodes_expanded;
                stats.leaf_evaluations += continuation.stats.leaf_evaluations;
                stats.transposition_hits += continuation.stats.transposition_hits;
                continuation.utility_by_player
            };
            assert_eq!(utility_by_player.len(), player_count);
            for (player, value) in utility_by_player.into_iter().enumerate() {
                aggregates[action_index].utility_sum_by_player[player] += value;
            }
        }
    }

    (aggregates, stats)
}

fn result_for_reference(
    information_set: &InformationSetV1,
    config: RootDeterminizationConfigV1,
) -> RootDeterminizationResultV1 {
    let (action_aggregates, stats) = reference_aggregate(information_set, config);
    let root_player = information_set.observation().public.current_player;
    let action = action_aggregates
        .iter()
        .max_by_key(|aggregate| aggregate.utility_sum_by_player[root_player.index()])
        .expect("reference root actions")
        .action;
    RootDeterminizationResultV1 {
        action,
        root_player,
        sample_seed: config.sample_seed,
        sample_count: config.sample_count,
        action_aggregates,
        stats,
    }
}

// ---------------------------------------------------------------------------
// Required contract tests
// ---------------------------------------------------------------------------

#[test]
fn real_two_three_and_four_player_information_sets_aggregate() {
    for (state, expected_players) in [
        (game_2p_hidden(101), 2),
        (game_3p(102), 3),
        (game_4p(103), 4),
    ] {
        let viewer = state.current_player;
        assert_eq!(state.player_count(), expected_players);
        let information_set = info_set(&state, viewer);
        let result = aggregate_root_determinizations_v1(&information_set, config(1))
            .expect("real information set should aggregate");
        assert_eq!(result.root_player, viewer);
        assert_eq!(result.stats.samples, 1);
        assert!(!result.action_aggregates.is_empty());
    }
}

#[test]
fn nonzero_viewer_is_supported_when_viewer_is_current_player() {
    let state = game_3p_viewer1(104);
    assert_eq!(state.current_player, PlayerId(1));
    let information_set = info_set(&state, PlayerId(1));

    let result = aggregate_root_determinizations_v1(&information_set, config(1))
        .expect("nonzero current viewer should aggregate");
    assert_eq!(result.root_player, PlayerId(1));
}

#[test]
fn repeated_call_is_exact_and_does_not_mutate_input() {
    let state = game_2p_hidden(105);
    let information_set = info_set(&state, state.current_player);
    let before = information_set.clone();
    let settings = config(2);

    let first = aggregate_root_determinizations_v1(&information_set, settings)
        .expect("first aggregation should succeed");
    let second = aggregate_root_determinizations_v1(&information_set, settings)
        .expect("second aggregation should succeed");

    assert_eq!(first, second);
    assert_eq!(information_set, before);
}

#[test]
fn chosen_action_is_legal_and_aggregates_are_canonical() {
    let state = game_3p(106);
    let information_set = info_set(&state, state.current_player);
    let result = aggregate_root_determinizations_v1(&information_set, config(2))
        .expect("aggregation should succeed");
    let sampled = sample_determinization_v1(&information_set, config(2).sample_seed, 0)
        .expect("sample should succeed");
    let legal = sampled.state().legal_actions();
    let canonical = canonical_order(&legal);
    let aggregate_actions: Vec<Action> = result
        .action_aggregates
        .iter()
        .map(|aggregate| aggregate.action)
        .collect();

    assert!(legal.contains(&result.action));
    assert_eq!(aggregate_actions, canonical);
}

#[test]
fn sample_count_one_matches_an_independent_forced_root_loop() {
    let state = game_2p_hidden(107);
    let information_set = info_set(&state, state.current_player);
    let settings = config(1);

    let actual = aggregate_root_determinizations_v1(&information_set, settings)
        .expect("aggregation should succeed");
    let expected = result_for_reference(&information_set, settings);

    assert_eq!(actual, expected);
}

#[test]
fn multi_sample_result_matches_independent_reference_and_visits_every_action() {
    let state = game_3p(108);
    let information_set = info_set(&state, state.current_player);
    let settings = config(3);

    let actual = aggregate_root_determinizations_v1(&information_set, settings)
        .expect("aggregation should succeed");
    let expected = result_for_reference(&information_set, settings);

    assert_eq!(actual, expected);
    assert_eq!(
        actual.stats.continuation_searches + actual.stats.terminal_children,
        u64::from(actual.stats.root_actions) * u64::from(actual.stats.samples)
    );
}

#[test]
fn terminal_root_children_use_static_evaluator() {
    let state = terminal_child_state(109);
    let information_set = info_set(&state, state.current_player);
    let settings = config(1);
    let actual = aggregate_root_determinizations_v1(&information_set, settings)
        .expect("terminal child aggregation should succeed");
    assert!(actual.stats.terminal_children > 0);

    let sampled = sample_determinization_v1(&information_set, settings.sample_seed, 0)
        .expect("sample should succeed");
    let terminal_action = canonical_order(&sampled.state().legal_actions())
        .into_iter()
        .find(|action| {
            let mut child = sampled.state().clone();
            child.apply(*action).expect("sampled action should apply");
            child.is_terminal()
        })
        .expect("fixture should expose a terminal child");
    let mut child = sampled.state().clone();
    child
        .apply(terminal_action)
        .expect("terminal action should apply");
    let expected_utility = StaticEvaluatorV1::utilities(&child).expect("terminal utility");
    let aggregate = actual
        .action_aggregates
        .iter()
        .find(|aggregate| aggregate.action == terminal_action)
        .expect("terminal action aggregate");
    assert_eq!(aggregate.utility_sum_by_player, expected_utility);
}

#[test]
fn choose_noble_is_a_supported_root_action_family() {
    let state = choose_noble_state(110);
    let information_set = info_set(&state, state.current_player);
    let result = aggregate_root_determinizations_v1(&information_set, config(1))
        .expect("ChooseNoble root should aggregate");

    assert!(!result.action_aggregates.is_empty());
    assert!(result
        .action_aggregates
        .iter()
        .all(|aggregate| matches!(aggregate.action, Action::ChooseNoble { .. })));
    assert!(matches!(result.action, Action::ChooseNoble { .. }));
}

#[test]
fn viewer_mismatch_is_rejected_before_sampling() {
    let state = new_game(2, 111);
    let information_set = info_set(&state, PlayerId(1));
    let error = aggregate_root_determinizations_v1(&information_set, config(1)).unwrap_err();

    assert!(matches!(
        error,
        ImperfectSearchError::ViewerIsNotRootPlayer {
            viewer: PlayerId(1),
            current_player: PlayerId(0)
        }
    ));
}

#[test]
fn game_over_information_set_is_rejected() {
    let state = game_over_state(112);
    assert!(state.is_terminal());
    let information_set = info_set(&state, state.current_player);
    let error = aggregate_root_determinizations_v1(&information_set, config(1)).unwrap_err();
    assert!(matches!(
        error,
        ImperfectSearchError::TerminalInformationSet
    ));
}

#[test]
fn sample_count_bounds_are_enforced() {
    let state = game_2p_hidden(113);
    let information_set = info_set(&state, state.current_player);

    let error_zero = aggregate_root_determinizations_v1(&information_set, config(0)).unwrap_err();
    assert!(matches!(error_zero, ImperfectSearchError::InvalidConfig(_)));

    let error_large = aggregate_root_determinizations_v1(&information_set, config(65)).unwrap_err();
    assert!(matches!(
        error_large,
        ImperfectSearchError::InvalidConfig(_)
    ));
}

#[test]
fn public_result_contains_no_sampled_state_or_hidden_card() {
    let state = game_2p_hidden(114);
    let information_set = info_set(&state, state.current_player);
    let result = aggregate_root_determinizations_v1(&information_set, config(1))
        .expect("aggregation should succeed");
    let json: Value = serde_json::to_value(result).expect("result should serialize");
    let object = json.as_object().expect("result should be an object");

    assert!(!object.contains_key("state"));
    assert!(!object.contains_key("deck"));
    assert!(!object.contains_key("blind"));
    assert!(!object.contains_key("state_hash"));
    assert!(!object.contains_key("principal_variation"));
}

#[test]
fn strategy_fusion_caveat_is_documented() {
    let source = include_str!("../src/lib.rs").to_ascii_lowercase();
    assert!(source.contains("root determinization"));
    assert!(source.contains("not ismcts"));
    assert!(source.contains("pomcp"));
    assert!(source.contains("belief-tree"));
    assert!(source.contains("strategy-fusion"));
}
