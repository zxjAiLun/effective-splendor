//! M06 C1 acceptance tests: config validation, canonical action order and
//! the frozen `StaticEvaluatorV1`.

use splendor_core::{
    Action, FullState, GameConfig, GameResult, Gems, NobleId, Phase, PlayerId, Ruleset,
    TerminalReason, Tier,
};
use splendor_search::{
    canonical_order, first_canonical_action, gems_tuple, SearchConfigV1, SearchError,
    StaticEvaluatorV1, MAX_SEARCH_DEPTH_TURNS, MAX_SEARCH_NODES, TERMINAL_RANK_UNIT,
};

fn new_state(player_count: u8, seed: u64) -> FullState {
    let (state, _) = FullState::new(GameConfig {
        player_count,
        seed,
        ruleset: Ruleset::base_v1(),
    })
    .expect("valid game config");
    state
}

fn make_terminal(state: &mut FullState, ranks: Vec<u8>) {
    let winners = ranks
        .iter()
        .enumerate()
        .filter(|(_, &rank)| rank == 0)
        .map(|(index, _)| PlayerId(index as u8))
        .collect();
    state.phase = Phase::GameOver;
    state.result = Some(GameResult {
        scores: state.players.iter().map(|p| p.prestige).collect(),
        ranks,
        winners,
        reason: TerminalReason::PrestigeThreshold,
    });
}

fn gems(white: u8, blue: u8, green: u8, red: u8, black: u8, gold: u8) -> Gems {
    Gems {
        white,
        blue,
        green,
        red,
        black,
        gold,
    }
}

fn assert_invalid_config(config: SearchConfigV1) {
    match config.validate() {
        Err(SearchError::InvalidConfig(_)) => {}
        other => panic!("expected InvalidConfig, got {other:?}"),
    }
}

// --- Config -----------------------------------------------------------------

#[test]
fn default_config_is_valid() {
    let config = SearchConfigV1::default();
    assert_eq!(config.max_depth_turns, 2);
    assert_eq!(config.max_nodes, 50_000);
    config.validate().expect("default config must be valid");
}

#[test]
fn zero_depth_is_rejected() {
    assert_invalid_config(SearchConfigV1 {
        max_depth_turns: 0,
        max_nodes: 1_000,
    });
}

#[test]
fn depth_above_limit_is_rejected() {
    assert_invalid_config(SearchConfigV1 {
        max_depth_turns: MAX_SEARCH_DEPTH_TURNS + 1,
        max_nodes: 1_000,
    });
}

#[test]
fn zero_node_budget_is_rejected() {
    assert_invalid_config(SearchConfigV1 {
        max_depth_turns: 2,
        max_nodes: 0,
    });
}

#[test]
fn node_budget_above_limit_is_rejected() {
    assert_invalid_config(SearchConfigV1 {
        max_depth_turns: 2,
        max_nodes: MAX_SEARCH_NODES + 1,
    });
}

// --- Canonical order ---------------------------------------------------------

fn one_of_each_variant() -> Vec<Action> {
    vec![
        Action::Pass,
        Action::ReserveDeck {
            tier: Tier::One,
            give_back: Gems::ZERO,
        },
        Action::TakeTokens {
            take: gems(1, 1, 1, 0, 0, 0),
            give_back: Gems::ZERO,
        },
        Action::BuyReserved { slot: 0 },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 0,
            give_back: Gems::ZERO,
        },
        Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        },
        Action::ChooseNoble { noble: NobleId(2) },
    ]
}

#[test]
fn canonical_order_covers_every_action_variant() {
    let sorted = canonical_order(&one_of_each_variant());
    let categories: Vec<&'static str> = sorted
        .iter()
        .map(|action| match action {
            Action::ChooseNoble { .. } => "choose_noble",
            Action::BuyMarket { .. } => "buy_market",
            Action::BuyReserved { .. } => "buy_reserved",
            Action::TakeTokens { .. } => "take_tokens",
            Action::ReserveMarket { .. } => "reserve_market",
            Action::ReserveDeck { .. } => "reserve_deck",
            Action::Pass => "pass",
        })
        .collect();
    assert_eq!(
        categories,
        vec![
            "choose_noble",
            "buy_market",
            "buy_reserved",
            "take_tokens",
            "reserve_market",
            "reserve_deck",
            "pass",
        ]
    );
}

fn rich_action_set() -> Vec<Action> {
    vec![
        Action::ChooseNoble { noble: NobleId(7) },
        Action::ChooseNoble { noble: NobleId(1) },
        Action::BuyMarket {
            tier: Tier::Two,
            slot: 0,
        },
        Action::BuyMarket {
            tier: Tier::One,
            slot: 3,
        },
        Action::BuyReserved { slot: 2 },
        Action::BuyReserved { slot: 0 },
        Action::TakeTokens {
            take: gems(1, 0, 1, 1, 0, 0),
            give_back: Gems::ZERO,
        },
        Action::TakeTokens {
            take: gems(0, 1, 1, 1, 0, 0),
            give_back: Gems::ZERO,
        },
        Action::TakeTokens {
            take: gems(0, 1, 1, 1, 0, 0),
            give_back: gems(1, 0, 0, 0, 0, 0),
        },
        Action::TakeTokens {
            take: gems(0, 1, 1, 1, 0, 0),
            give_back: gems(0, 0, 0, 0, 1, 0),
        },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 1,
            give_back: gems(1, 0, 0, 0, 0, 0),
        },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 1,
            give_back: gems(0, 1, 0, 0, 0, 0),
        },
        Action::ReserveMarket {
            tier: Tier::Three,
            slot: 0,
            give_back: Gems::ZERO,
        },
        Action::ReserveDeck {
            tier: Tier::Two,
            give_back: Gems::ZERO,
        },
        Action::ReserveDeck {
            tier: Tier::One,
            give_back: gems(0, 0, 0, 0, 0, 1),
        },
        Action::Pass,
    ]
}

#[test]
fn canonical_order_is_independent_of_input_order() {
    let forward = rich_action_set();
    let mut reversed = forward.clone();
    reversed.reverse();
    let mut rotated = forward.clone();
    rotated.rotate_left(5);

    let sorted = canonical_order(&forward);
    assert_eq!(sorted, canonical_order(&reversed));
    assert_eq!(sorted, canonical_order(&rotated));

    // Frozen within-category expectations.
    let expected = vec![
        Action::ChooseNoble { noble: NobleId(1) },
        Action::ChooseNoble { noble: NobleId(7) },
        Action::BuyMarket {
            tier: Tier::One,
            slot: 3,
        },
        Action::BuyMarket {
            tier: Tier::Two,
            slot: 0,
        },
        Action::BuyReserved { slot: 0 },
        Action::BuyReserved { slot: 2 },
        Action::TakeTokens {
            take: gems(0, 1, 1, 1, 0, 0),
            give_back: Gems::ZERO,
        },
        Action::TakeTokens {
            take: gems(0, 1, 1, 1, 0, 0),
            give_back: gems(0, 0, 0, 0, 1, 0),
        },
        Action::TakeTokens {
            take: gems(0, 1, 1, 1, 0, 0),
            give_back: gems(1, 0, 0, 0, 0, 0),
        },
        Action::TakeTokens {
            take: gems(1, 0, 1, 1, 0, 0),
            give_back: Gems::ZERO,
        },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 1,
            give_back: gems(0, 1, 0, 0, 0, 0),
        },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 1,
            give_back: gems(1, 0, 0, 0, 0, 0),
        },
        Action::ReserveMarket {
            tier: Tier::Three,
            slot: 0,
            give_back: Gems::ZERO,
        },
        Action::ReserveDeck {
            tier: Tier::One,
            give_back: gems(0, 0, 0, 0, 0, 1),
        },
        Action::ReserveDeck {
            tier: Tier::Two,
            give_back: Gems::ZERO,
        },
        Action::Pass,
    ];
    assert_eq!(sorted, expected);
}

#[test]
fn gems_tuple_order_is_frozen() {
    assert_eq!(gems_tuple(gems(1, 2, 3, 4, 5, 6)), [1, 2, 3, 4, 5, 6]);
    assert_eq!(gems_tuple(Gems::ZERO), [0, 0, 0, 0, 0, 0]);
}

#[test]
fn ties_select_first_canonical_action() {
    let actions = rich_action_set();
    let sorted = canonical_order(&actions);
    // Regardless of the input permutation, the tie-break selector must pick
    // the canonically first action.
    let mut reversed = actions.clone();
    reversed.reverse();
    assert_eq!(first_canonical_action(&actions), Some(sorted[0]));
    assert_eq!(first_canonical_action(&reversed), Some(sorted[0]));
    assert_eq!(
        first_canonical_action(&actions),
        Some(Action::ChooseNoble { noble: NobleId(1) })
    );
    assert_eq!(first_canonical_action(&[]), None);
}

// --- StaticEvaluatorV1 --------------------------------------------------------

#[test]
fn utility_vector_matches_player_count() {
    for player_count in 2..=4u8 {
        let state = new_state(player_count, 11);
        let utilities = StaticEvaluatorV1::utilities(&state).expect("evaluation succeeds");
        assert_eq!(utilities.len(), usize::from(player_count));
    }
}

#[test]
fn same_state_produces_same_utility() {
    let state = new_state(3, 42);
    let first = StaticEvaluatorV1::utilities(&state).expect("evaluation succeeds");
    let second = StaticEvaluatorV1::utilities(&state).expect("evaluation succeeds");
    let cloned = StaticEvaluatorV1::utilities(&state.clone()).expect("evaluation succeeds");
    assert_eq!(first, second);
    assert_eq!(first, cloned);
}

#[test]
fn event_log_does_not_change_utility() {
    let state = new_state(2, 7);
    assert!(!state.log.is_empty(), "setup must have produced events");
    let mut stripped = state.clone();
    stripped.log.clear();
    assert_eq!(
        StaticEvaluatorV1::utilities(&state).expect("evaluation succeeds"),
        StaticEvaluatorV1::utilities(&stripped).expect("evaluation succeeds"),
    );
}

#[test]
fn terminal_winner_dominates_nonterminal_progress() {
    // A non-terminal player with absurdly strong material...
    let mut rich = new_state(2, 5);
    rich.players[0].prestige = 200;
    rich.players[0].tokens = gems(4, 4, 2, 0, 0, 3);
    let rich_utility = StaticEvaluatorV1::utilities(&rich).expect("evaluation succeeds")[0];

    // ...must still be worth less than actually winning.
    let mut terminal = new_state(2, 5);
    make_terminal(&mut terminal, vec![0, 1]);
    let winner_utility = StaticEvaluatorV1::utilities(&terminal).expect("evaluation succeeds")[0];

    assert!(winner_utility > rich_utility);
    assert!(rich_utility < TERMINAL_RANK_UNIT);
}

#[test]
fn terminal_second_beats_terminal_third() {
    let mut state = new_state(3, 9);
    make_terminal(&mut state, vec![0, 1, 2]);
    let utilities = StaticEvaluatorV1::utilities(&state).expect("evaluation succeeds");
    assert!(utilities[0] > utilities[1]);
    assert!(utilities[1] > utilities[2]);
}

#[test]
fn shared_winners_receive_equal_terminal_base() {
    let mut state = new_state(3, 13);
    // Players 0 and 1 share rank 0 with identical material; player 2 loses.
    make_terminal(&mut state, vec![0, 0, 1]);
    let utilities = StaticEvaluatorV1::utilities(&state).expect("evaluation succeeds");
    assert_eq!(utilities[0], utilities[1]);
    assert!(utilities[0] >= TERMINAL_RANK_UNIT - TERMINAL_RANK_UNIT / 2);
    assert!(utilities[2] < 0);
}

#[test]
fn relative_utility_is_zero_sum_in_two_player_state() {
    let mut state = new_state(2, 21);
    state.players[0].prestige = 5;
    state.players[0].tokens = gems(2, 1, 0, 0, 0, 1);
    assert!(!state.is_terminal());
    let utilities = StaticEvaluatorV1::utilities(&state).expect("evaluation succeeds");
    assert_eq!(utilities.len(), 2);
    assert_ne!(utilities[0], 0);
    assert_eq!(utilities[0] + utilities[1], 0);
    assert_eq!(utilities[0], -utilities[1]);
}
