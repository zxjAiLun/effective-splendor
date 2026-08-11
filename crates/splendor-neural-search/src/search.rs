use std::collections::{hash_map::Entry, HashMap};

use splendor_belief::{sample_determinization_v1, InformationSetV1};
use splendor_core::{visible_events, Action, Audience, FullState, Observation, VisibleEvent};
use splendor_learning::{model_checkpoint_hash_v1, PolicyValueModelV1};
use splendor_search::canonical_order;

use crate::{
    NeuralAblationModeV1, NeuralIsmctsActionStatsV1, NeuralIsmctsConfigV1, NeuralIsmctsResultV1,
    NeuralIsmctsStatsV1, NeuralSearchError, NEURAL_VALUE_SCALE_V1,
};

#[derive(Debug)]
struct ActionEdge {
    prior_micros: u32,
    visits: u32,
    value_sums: Vec<u64>,
}

#[derive(Debug)]
struct TreeNode {
    legal_actions: Vec<Action>,
    visits: u32,
    edges: Vec<ActionEdge>,
}

impl TreeNode {
    fn new(
        legal_actions: Vec<Action>,
        priors: Vec<u32>,
        player_count: usize,
    ) -> Result<Self, NeuralSearchError> {
        if legal_actions.len() != priors.len() || legal_actions.is_empty() {
            return Err(NeuralSearchError::NoLegalActions);
        }
        let edges = priors
            .into_iter()
            .map(|prior_micros| ActionEdge {
                prior_micros,
                visits: 0,
                value_sums: vec![0; player_count],
            })
            .collect();
        Ok(Self {
            legal_actions,
            visits: 0,
            edges,
        })
    }
}

pub fn search_neural_ismcts_v1(
    information_set: &InformationSetV1,
    model: &PolicyValueModelV1,
    config: &NeuralIsmctsConfigV1,
) -> Result<NeuralIsmctsResultV1, NeuralSearchError> {
    search_neural_ismcts_internal_v1(information_set, model, config, NeuralAblationModeV1::Full)
}

/// Runs a controlled M15 diagnostic variant of the accepted M13 search.
///
/// The checkpoint, information-set boundary, determinization stream, PUCT
/// arithmetic and root choice are unchanged. Only learned priors and/or learned
/// leaf values are replaced by deterministic neutral controls.
pub fn search_neural_ismcts_ablation_v1(
    information_set: &InformationSetV1,
    model: &PolicyValueModelV1,
    config: &NeuralIsmctsConfigV1,
    mode: NeuralAblationModeV1,
) -> Result<NeuralIsmctsResultV1, NeuralSearchError> {
    search_neural_ismcts_internal_v1(information_set, model, config, mode)
}

fn search_neural_ismcts_internal_v1(
    information_set: &InformationSetV1,
    model: &PolicyValueModelV1,
    config: &NeuralIsmctsConfigV1,
    mode: NeuralAblationModeV1,
) -> Result<NeuralIsmctsResultV1, NeuralSearchError> {
    config.validate()?;
    let checkpoint_hash = model_checkpoint_hash_v1(model.checkpoint())
        .map_err(|error| NeuralSearchError::Learning(error.to_string()))?;
    if checkpoint_hash != config.expected_checkpoint_hash {
        return Err(NeuralSearchError::CheckpointMismatch {
            expected: config.expected_checkpoint_hash.clone(),
            found: checkpoint_hash,
        });
    }
    let viewer = information_set.observation().viewer;
    if information_set.observation().public.current_player != viewer {
        return Err(NeuralSearchError::ViewerMismatch);
    }
    let player_count = information_set.observation().public.players.len();
    let mut tree: HashMap<String, TreeNode> = HashMap::new();
    let mut shared_node_hits = 0u32;
    let mut model_evaluations = 0u32;
    let mut terminal_evaluations = 0u32;
    let root_key = information_node_key(information_set.observation(), &[])?;

    for sample_index in 0..u64::from(config.simulations) {
        let sampled = sample_determinization_v1(information_set, config.sample_seed, sample_index)
            .map_err(|error| NeuralSearchError::Belief(error.to_string()))?;
        let mut state = sampled.state().clone();
        let mut remaining_depth = config.max_depth_turns;
        let mut path: Vec<(String, usize)> = Vec::new();

        let values = loop {
            if state.is_terminal() {
                terminal_evaluations = checked_increment(terminal_evaluations)?;
                break terminal_values(&state, player_count)?;
            }
            if remaining_depth == 0 {
                if mode.uses_learned_values() {
                    model_evaluations = checked_increment(model_evaluations)?;
                }
                break evaluation_values(&state, model, player_count, mode)?;
            }
            let actor = state.current_player.index();
            let legal_actions = canonical_order(&state.legal_actions());
            if legal_actions.is_empty() {
                return Err(NeuralSearchError::NoLegalActions);
            }
            let observation = state.observation(state.current_player);
            let simulated_history =
                visible_events(&state.log, Audience::Player(state.current_player));
            let key = information_node_key(&observation, &simulated_history)?;
            let (edge_index, action, was_unvisited) = {
                let node = match tree.entry(key.clone()) {
                    Entry::Occupied(entry) => {
                        shared_node_hits = checked_increment(shared_node_hits)?;
                        entry.into_mut()
                    }
                    Entry::Vacant(entry) => {
                        if mode.uses_learned_priors() {
                            model_evaluations = checked_increment(model_evaluations)?;
                        }
                        let priors = evaluation_priors(model, &observation, &legal_actions, mode)?;
                        entry.insert(TreeNode::new(legal_actions.clone(), priors, player_count)?)
                    }
                };
                if node.legal_actions != legal_actions {
                    return Err(NeuralSearchError::ActionAvailabilityMismatch);
                }
                let edge_index = select_edge(node, actor, config.puct_exploration_milli)?;
                (
                    edge_index,
                    node.legal_actions[edge_index],
                    node.edges[edge_index].visits == 0,
                )
            };
            path.push((key, edge_index));

            let before = state.current_player;
            state
                .apply(action)
                .map_err(|error| NeuralSearchError::Engine(error.to_string()))?;
            if state.current_player != before {
                remaining_depth = remaining_depth.saturating_sub(1);
            }
            if was_unvisited {
                if state.is_terminal() {
                    terminal_evaluations = checked_increment(terminal_evaluations)?;
                    break terminal_values(&state, player_count)?;
                }
                if mode.uses_learned_values() {
                    model_evaluations = checked_increment(model_evaluations)?;
                }
                break evaluation_values(&state, model, player_count, mode)?;
            }
        };

        for (key, edge_index) in path {
            let node = tree
                .get_mut(&key)
                .ok_or(NeuralSearchError::ArithmeticOverflow)?;
            node.visits = checked_increment(node.visits)?;
            let edge = &mut node.edges[edge_index];
            edge.visits = checked_increment(edge.visits)?;
            for (sum, value) in edge.value_sums.iter_mut().zip(&values) {
                *sum = sum
                    .checked_add(u64::from(*value))
                    .ok_or(NeuralSearchError::ArithmeticOverflow)?;
            }
        }
    }

    let root = tree
        .get(&root_key)
        .ok_or(NeuralSearchError::NoLegalActions)?;
    let chosen_index = choose_root_edge(root, viewer.index())?;
    let action_stats = root
        .legal_actions
        .iter()
        .zip(&root.edges)
        .map(|(&action, edge)| NeuralIsmctsActionStatsV1 {
            action,
            prior_micros: edge.prior_micros,
            visits: edge.visits,
            value_sum_by_player: edge.value_sums.clone(),
        })
        .collect();
    let tree_nodes =
        u32::try_from(tree.len()).map_err(|_| NeuralSearchError::ArithmeticOverflow)?;
    Ok(NeuralIsmctsResultV1::new(
        information_set.information_set_hash().as_str().into(),
        model.checkpoint().model_id.clone(),
        config.expected_checkpoint_hash.clone(),
        root.legal_actions[chosen_index],
        action_stats,
        NeuralIsmctsStatsV1 {
            simulations: config.simulations,
            sampled_determinizations: config.simulations,
            tree_nodes,
            shared_node_hits,
            root_visits: root.visits,
            model_evaluations,
            terminal_evaluations,
        },
    ))
}

fn evaluation_priors(
    model: &PolicyValueModelV1,
    observation: &Observation,
    legal_actions: &[Action],
    mode: NeuralAblationModeV1,
) -> Result<Vec<u32>, NeuralSearchError> {
    if mode.uses_learned_priors() {
        model_priors(model, observation, legal_actions)
    } else {
        uniform_priors(legal_actions.len())
    }
}

fn uniform_priors(action_count: usize) -> Result<Vec<u32>, NeuralSearchError> {
    if action_count == 0 {
        return Err(NeuralSearchError::NoLegalActions);
    }
    let action_count_u32 =
        u32::try_from(action_count).map_err(|_| NeuralSearchError::ArithmeticOverflow)?;
    let base = NEURAL_VALUE_SCALE_V1 / action_count_u32;
    let remainder = NEURAL_VALUE_SCALE_V1 % action_count_u32;
    Ok((0..action_count_u32)
        .map(|index| base + u32::from(index < remainder))
        .collect())
}

fn evaluation_values(
    state: &FullState,
    model: &PolicyValueModelV1,
    player_count: usize,
    mode: NeuralAblationModeV1,
) -> Result<Vec<u32>, NeuralSearchError> {
    if mode.uses_learned_values() {
        model_values(state, model, player_count)
    } else {
        Ok(vec![NEURAL_VALUE_SCALE_V1 / 2; player_count])
    }
}

fn model_priors(
    model: &PolicyValueModelV1,
    observation: &Observation,
    legal_actions: &[Action],
) -> Result<Vec<u32>, NeuralSearchError> {
    let prediction = model
        .predict(observation, legal_actions)
        .map_err(|error| NeuralSearchError::Learning(error.to_string()))?;
    if prediction.policy.len() != legal_actions.len()
        || prediction
            .policy
            .iter()
            .zip(legal_actions)
            .any(|(entry, action)| entry.action != *action)
    {
        return Err(NeuralSearchError::ActionAvailabilityMismatch);
    }
    prediction
        .policy
        .iter()
        .map(|entry| quantize_unit(entry.probability))
        .collect()
}

fn model_values(
    state: &FullState,
    model: &PolicyValueModelV1,
    player_count: usize,
) -> Result<Vec<u32>, NeuralSearchError> {
    let observation = state.observation(state.current_player);
    let legal_actions = canonical_order(&state.legal_actions());
    if legal_actions.is_empty() {
        return Err(NeuralSearchError::NoLegalActions);
    }
    let prediction = model
        .predict(&observation, &legal_actions)
        .map_err(|error| NeuralSearchError::Learning(error.to_string()))?;
    if prediction.value_by_player.len() != player_count {
        return Err(NeuralSearchError::InvalidValueShape {
            expected: player_count,
            found: prediction.value_by_player.len(),
        });
    }
    prediction
        .value_by_player
        .iter()
        .map(|value| quantize_unit(*value))
        .collect()
}

fn terminal_values(state: &FullState, player_count: usize) -> Result<Vec<u32>, NeuralSearchError> {
    let result = state
        .result
        .as_ref()
        .ok_or(NeuralSearchError::InvalidValueShape {
            expected: player_count,
            found: 0,
        })?;
    if result.ranks.len() != player_count || player_count < 2 {
        return Err(NeuralSearchError::InvalidValueShape {
            expected: player_count,
            found: result.ranks.len(),
        });
    }
    let denominator = (player_count - 1) as u64;
    result
        .ranks
        .iter()
        .map(|rank| {
            let rank = u64::from(*rank);
            if rank > denominator {
                return Err(NeuralSearchError::InvalidModelOutput);
            }
            let scaled = u64::from(NEURAL_VALUE_SCALE_V1)
                .checked_mul(denominator - rank)
                .ok_or(NeuralSearchError::ArithmeticOverflow)?
                / denominator;
            u32::try_from(scaled).map_err(|_| NeuralSearchError::ArithmeticOverflow)
        })
        .collect()
}

fn quantize_unit(value: f32) -> Result<u32, NeuralSearchError> {
    if !value.is_finite() || !(0.0..=1.0).contains(&value) {
        return Err(NeuralSearchError::InvalidModelOutput);
    }
    Ok((value * NEURAL_VALUE_SCALE_V1 as f32).round() as u32)
}

fn information_node_key(
    observation: &Observation,
    simulated_visible_history: &[VisibleEvent],
) -> Result<String, NeuralSearchError> {
    serde_json::to_string(&(observation, simulated_visible_history))
        .map_err(|error| NeuralSearchError::Serialization(error.to_string()))
}

fn select_edge(
    node: &TreeNode,
    actor: usize,
    exploration_milli: u32,
) -> Result<usize, NeuralSearchError> {
    let root_visits = u64::from(node.visits).saturating_add(1);
    let root = ceil_sqrt(root_visits);
    let mut best_index = 0usize;
    let mut best_score = i128::MIN;
    for (index, edge) in node.edges.iter().enumerate() {
        let value_sum =
            *edge
                .value_sums
                .get(actor)
                .ok_or(NeuralSearchError::InvalidValueShape {
                    expected: actor + 1,
                    found: edge.value_sums.len(),
                })?;
        let mean = if edge.visits == 0 {
            i128::from(NEURAL_VALUE_SCALE_V1 / 2)
        } else {
            i128::from(value_sum / u64::from(edge.visits))
        };
        let numerator = u128::from(exploration_milli)
            .checked_mul(u128::from(edge.prior_micros))
            .and_then(|value| value.checked_mul(u128::from(root)))
            .ok_or(NeuralSearchError::ArithmeticOverflow)?;
        let denominator = 1_000u128
            .checked_mul(u128::from(edge.visits) + 1)
            .ok_or(NeuralSearchError::ArithmeticOverflow)?;
        let bonus = numerator / denominator;
        let score = mean
            .checked_add(i128::try_from(bonus).map_err(|_| NeuralSearchError::ArithmeticOverflow)?)
            .ok_or(NeuralSearchError::ArithmeticOverflow)?;
        if score > best_score {
            best_score = score;
            best_index = index;
        }
    }
    Ok(best_index)
}

fn choose_root_edge(root: &TreeNode, viewer: usize) -> Result<usize, NeuralSearchError> {
    let mut best = 0usize;
    for index in 1..root.edges.len() {
        let current = &root.edges[index];
        let incumbent = &root.edges[best];
        let mean_ordering = if current.visits == incumbent.visits {
            compare_mean(current, incumbent, viewer)?
        } else {
            std::cmp::Ordering::Equal
        };
        let replace = current.visits > incumbent.visits
            || (current.visits == incumbent.visits && mean_ordering == std::cmp::Ordering::Greater)
            || (current.visits == incumbent.visits
                && mean_ordering == std::cmp::Ordering::Equal
                && current.prior_micros > incumbent.prior_micros);
        if replace {
            best = index;
        }
    }
    Ok(best)
}

fn compare_mean(
    left: &ActionEdge,
    right: &ActionEdge,
    viewer: usize,
) -> Result<std::cmp::Ordering, NeuralSearchError> {
    let left_sum = *left
        .value_sums
        .get(viewer)
        .ok_or(NeuralSearchError::InvalidValueShape {
            expected: viewer + 1,
            found: left.value_sums.len(),
        })?;
    let right_sum = *right
        .value_sums
        .get(viewer)
        .ok_or(NeuralSearchError::InvalidValueShape {
            expected: viewer + 1,
            found: right.value_sums.len(),
        })?;
    match (left.visits, right.visits) {
        (0, 0) => Ok(std::cmp::Ordering::Equal),
        (0, _) => Ok(std::cmp::Ordering::Less),
        (_, 0) => Ok(std::cmp::Ordering::Greater),
        _ => Ok((u128::from(left_sum) * u128::from(right.visits))
            .cmp(&(u128::from(right_sum) * u128::from(left.visits)))),
    }
}

fn checked_increment(value: u32) -> Result<u32, NeuralSearchError> {
    value
        .checked_add(1)
        .ok_or(NeuralSearchError::ArithmeticOverflow)
}

fn ceil_sqrt(value: u64) -> u64 {
    let mut low = 0u64;
    let mut high = value.min(u64::from(u32::MAX) + 1);
    while low + 1 < high {
        let mid = low + (high - low) / 2;
        if mid <= value / mid {
            low = mid;
        } else {
            high = mid;
        }
    }
    if low.saturating_mul(low) == value {
        low
    } else {
        low + 1
    }
}

#[cfg(test)]
mod tests {
    use splendor_belief::build_information_set_v1;
    use splendor_core::{visible_events, Audience, FullState, GameConfig, PlayerId};
    use splendor_learning::{
        model_checkpoint_hash_v1, ModelParametersV1, PolicyValueCheckpointV1, ACTION_FEATURES_V1,
        MAX_PLAYERS_V1, OBSERVATION_FEATURES_V1, POLICY_VALUE_CHECKPOINT_FORMAT,
        POLICY_VALUE_CHECKPOINT_VERSION, REPRESENTATION_VERSION_V1,
    };

    use super::*;

    fn model() -> PolicyValueModelV1 {
        let hidden = 4usize;
        PolicyValueModelV1::from_checkpoint(PolicyValueCheckpointV1 {
            format: POLICY_VALUE_CHECKPOINT_FORMAT.into(),
            version: POLICY_VALUE_CHECKPOINT_VERSION,
            model_id: "m13-test-model".into(),
            representation_version: REPRESENTATION_VERSION_V1.into(),
            observation_features: OBSERVATION_FEATURES_V1 as u32,
            action_features: ACTION_FEATURES_V1 as u32,
            hidden_features: hidden as u32,
            max_players: MAX_PLAYERS_V1 as u8,
            source_dataset_id: "m13-test-dataset".into(),
            source_dataset_hash: "11".repeat(32),
            league_manifest_hash: "22".repeat(32),
            evaluation_plan_hash: "33".repeat(32),
            evaluation_report_hash: "44".repeat(32),
            training_config_hash: "55".repeat(32),
            training_contract_version: None,
            trained_examples: 4,
            validation_examples: 2,
            validation_seed_modulus: 2,
            validation_seed_remainder: 0,
            epochs: 1,
            parameters: ModelParametersV1 {
                encoder_weights: vec![0.0; hidden * OBSERVATION_FEATURES_V1],
                encoder_bias: vec![0.0; hidden],
                policy_bilinear: vec![0.0; hidden * ACTION_FEATURES_V1],
                policy_action_bias: vec![0.0; ACTION_FEATURES_V1],
                value_weights: vec![0.0; MAX_PLAYERS_V1 * hidden],
                value_bias: vec![0.0; MAX_PLAYERS_V1],
            },
        })
        .unwrap()
    }

    fn information_set(player_count: u8, seed: u64) -> InformationSetV1 {
        let (state, setup) = FullState::new(GameConfig {
            player_count,
            seed,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        build_information_set_v1(
            state.ruleset,
            &state.observation(viewer),
            &visible_events(&setup.events, Audience::Player(viewer)),
        )
        .unwrap()
    }

    fn config(model: &PolicyValueModelV1) -> NeuralIsmctsConfigV1 {
        NeuralIsmctsConfigV1 {
            sample_seed: 17,
            simulations: 16,
            max_depth_turns: 2,
            puct_exploration_milli: 1_500,
            expected_checkpoint_hash: model_checkpoint_hash_v1(model.checkpoint()).unwrap(),
        }
    }

    #[test]
    fn repeated_search_is_exact_and_model_bound() {
        let model = model();
        let information_set = information_set(2, 42);
        let first = search_neural_ismcts_v1(&information_set, &model, &config(&model)).unwrap();
        let second = search_neural_ismcts_v1(&information_set, &model, &config(&model)).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.stats.root_visits, 16);
        assert_eq!(
            first.checkpoint_hash,
            config(&model).expected_checkpoint_hash
        );
        assert_eq!(
            first
                .action_stats
                .iter()
                .map(|stats| stats.visits)
                .sum::<u32>(),
            16
        );
        assert!(
            first
                .action_stats
                .iter()
                .filter(|stats| stats.visits > 0)
                .count()
                > 1,
            "neutral first-play value must not collapse all visits onto one edge"
        );
        assert!(first.stats.model_evaluations > 0);
    }

    #[test]
    fn full_ablation_mode_is_the_accepted_search_path() {
        let model = model();
        let information_set = information_set(2, 42);
        let accepted = search_neural_ismcts_v1(&information_set, &model, &config(&model)).unwrap();
        let diagnostic = search_neural_ismcts_ablation_v1(
            &information_set,
            &model,
            &config(&model),
            NeuralAblationModeV1::Full,
        )
        .unwrap();
        assert_eq!(accepted, diagnostic);
    }

    #[test]
    fn neutral_controls_are_deterministic_and_normalized() {
        let model = model();
        let information_set = information_set(2, 91);
        let first = search_neural_ismcts_ablation_v1(
            &information_set,
            &model,
            &config(&model),
            NeuralAblationModeV1::Neutral,
        )
        .unwrap();
        let second = search_neural_ismcts_ablation_v1(
            &information_set,
            &model,
            &config(&model),
            NeuralAblationModeV1::Neutral,
        )
        .unwrap();
        assert_eq!(first, second);
        assert_eq!(first.stats.model_evaluations, 0);
        assert_eq!(
            first
                .action_stats
                .iter()
                .map(|stats| stats.prior_micros)
                .sum::<u32>(),
            NEURAL_VALUE_SCALE_V1
        );
        let minimum = first
            .action_stats
            .iter()
            .map(|stats| stats.prior_micros)
            .min()
            .unwrap();
        let maximum = first
            .action_stats
            .iter()
            .map(|stats| stats.prior_micros)
            .max()
            .unwrap();
        assert!(maximum - minimum <= 1);
        assert!(first.action_stats.iter().all(|stats| {
            stats
                .value_sum_by_player
                .iter()
                .all(|sum| *sum <= u64::from(stats.visits) * u64::from(NEURAL_VALUE_SCALE_V1))
        }));
    }

    #[test]
    fn component_controls_only_invoke_enabled_model_heads() {
        let model = model();
        let information_set = information_set(2, 73);
        let value_only = search_neural_ismcts_ablation_v1(
            &information_set,
            &model,
            &config(&model),
            NeuralAblationModeV1::ValueOnly,
        )
        .unwrap();
        let policy_only = search_neural_ismcts_ablation_v1(
            &information_set,
            &model,
            &config(&model),
            NeuralAblationModeV1::PolicyOnly,
        )
        .unwrap();
        assert!(value_only.stats.model_evaluations > 0);
        assert!(policy_only.stats.model_evaluations > 0);
        assert_eq!(
            value_only
                .action_stats
                .iter()
                .map(|stats| stats.prior_micros)
                .sum::<u32>(),
            NEURAL_VALUE_SCALE_V1
        );
    }

    #[test]
    fn two_three_four_player_roots_are_legal() {
        let model = model();
        for players in 2..=4 {
            let information_set = information_set(players, u64::from(players));
            let result =
                search_neural_ismcts_v1(&information_set, &model, &config(&model)).unwrap();
            let legal = sample_determinization_v1(&information_set, 17, 0)
                .unwrap()
                .state()
                .legal_actions();
            assert!(legal.contains(&result.action));
            assert!(result
                .action_stats
                .iter()
                .all(|stats| stats.value_sum_by_player.len() == players as usize));
        }
    }

    #[test]
    fn checkpoint_mismatch_is_rejected_before_sampling() {
        let model = model();
        let mut bad = config(&model);
        bad.expected_checkpoint_hash = "00".repeat(32);
        assert!(matches!(
            search_neural_ismcts_v1(&information_set(2, 1), &model, &bad),
            Err(NeuralSearchError::CheckpointMismatch { .. })
        ));
    }
}
