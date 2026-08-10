use std::collections::{hash_map::Entry, HashMap};

use splendor_belief::{sample_determinization_v1, InformationSetV1};
use splendor_core::{visible_events, Action, Audience, FullState, Observation, VisibleEvent};
use splendor_search::{canonical_order, StaticEvaluatorV1};

use crate::{IsmctsActionStatsV1, IsmctsConfigV1, IsmctsError, IsmctsResultV1, IsmctsStatsV1};

#[derive(Debug)]
struct ActionEdge {
    visits: u32,
    utility_sums: Vec<i64>,
}

#[derive(Debug)]
struct TreeNode {
    legal_actions: Vec<Action>,
    visits: u32,
    edges: Vec<ActionEdge>,
}

impl TreeNode {
    fn new(legal_actions: Vec<Action>, player_count: usize) -> Self {
        let edges = legal_actions
            .iter()
            .map(|_| ActionEdge {
                visits: 0,
                utility_sums: vec![0; player_count],
            })
            .collect();
        Self {
            legal_actions,
            visits: 0,
            edges,
        }
    }
}

pub fn search_ismcts_v1(
    information_set: &InformationSetV1,
    config: IsmctsConfigV1,
) -> Result<IsmctsResultV1, IsmctsError> {
    config.validate()?;
    let viewer = information_set.observation().viewer;
    if information_set.observation().public.current_player != viewer {
        return Err(IsmctsError::ViewerMismatch);
    }
    let player_count = information_set.observation().public.players.len();
    let mut tree: HashMap<String, TreeNode> = HashMap::new();
    let mut shared_node_hits = 0u32;
    let root_key = information_node_key(information_set.observation(), &[])?;

    for sample_index in 0..u64::from(config.simulations) {
        let sampled = sample_determinization_v1(information_set, config.sample_seed, sample_index)
            .map_err(|error| IsmctsError::Belief(error.to_string()))?;
        let mut state = sampled.state().clone();
        let mut remaining_depth = config.max_depth_turns;
        let mut path: Vec<(String, usize)> = Vec::new();

        let utilities = loop {
            if state.is_terminal() || remaining_depth == 0 {
                break evaluate(&state, player_count)?;
            }
            let actor = state.current_player.index();
            let legal_actions = canonical_order(&state.legal_actions());
            if legal_actions.is_empty() {
                return Err(IsmctsError::NoLegalActions);
            }
            let observation = state.observation(state.current_player);
            let simulated_history =
                visible_events(&state.log, Audience::Player(state.current_player));
            let key = information_node_key(&observation, &simulated_history)?;
            let (edge_index, action, was_unvisited) = {
                let node = match tree.entry(key.clone()) {
                    Entry::Occupied(entry) => {
                        shared_node_hits = shared_node_hits
                            .checked_add(1)
                            .ok_or(IsmctsError::ArithmeticOverflow)?;
                        entry.into_mut()
                    }
                    Entry::Vacant(entry) => {
                        entry.insert(TreeNode::new(legal_actions.clone(), player_count))
                    }
                };
                if node.legal_actions != legal_actions {
                    return Err(IsmctsError::ActionAvailabilityMismatch);
                }
                let edge_index = select_edge(node, actor, config.exploration_bias)?;
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
                .map_err(|error| IsmctsError::Engine(error.to_string()))?;
            if state.current_player != before {
                remaining_depth = remaining_depth.saturating_sub(1);
            }
            if was_unvisited {
                break evaluate(&state, player_count)?;
            }
        };

        for (key, edge_index) in path {
            let node = tree.get_mut(&key).ok_or(IsmctsError::ArithmeticOverflow)?;
            node.visits = node
                .visits
                .checked_add(1)
                .ok_or(IsmctsError::ArithmeticOverflow)?;
            let edge = &mut node.edges[edge_index];
            edge.visits = edge
                .visits
                .checked_add(1)
                .ok_or(IsmctsError::ArithmeticOverflow)?;
            for (sum, utility) in edge.utility_sums.iter_mut().zip(&utilities) {
                *sum = sum
                    .checked_add(*utility)
                    .ok_or(IsmctsError::ArithmeticOverflow)?;
            }
        }
    }

    let root = tree.get(&root_key).ok_or(IsmctsError::NoLegalActions)?;
    let chosen_index = choose_root_edge(root, viewer.index())?;
    let action_stats = root
        .legal_actions
        .iter()
        .zip(&root.edges)
        .map(|(&action, edge)| IsmctsActionStatsV1 {
            action,
            visits: edge.visits,
            utility_sum_by_player: edge.utility_sums.clone(),
        })
        .collect();
    let tree_nodes = u32::try_from(tree.len()).map_err(|_| IsmctsError::ArithmeticOverflow)?;
    Ok(IsmctsResultV1::new(
        information_set.information_set_hash().as_str().to_string(),
        root.legal_actions[chosen_index],
        action_stats,
        IsmctsStatsV1 {
            simulations: config.simulations,
            sampled_determinizations: config.simulations,
            tree_nodes,
            shared_node_hits,
            root_visits: root.visits,
        },
    ))
}

/// Internal v1 tree identity. The M07 sampler cannot reconstruct another
/// player's private transcript before the root, so v1 combines their current
/// observation with perfect-recall visible events generated from the simulated
/// root onward. This avoids both FullState keys and observation-only
/// transpositions while keeping that root-history abstraction explicit.
fn information_node_key(
    observation: &Observation,
    simulated_visible_history: &[VisibleEvent],
) -> Result<String, IsmctsError> {
    serde_json::to_string(&(observation, simulated_visible_history))
        .map_err(|error| IsmctsError::Serialization(error.to_string()))
}

fn evaluate(state: &FullState, player_count: usize) -> Result<Vec<i64>, IsmctsError> {
    let utilities = StaticEvaluatorV1::utilities(state)
        .map_err(|error| IsmctsError::Evaluation(error.to_string()))?;
    if utilities.len() != player_count {
        return Err(IsmctsError::InvalidUtilityShape {
            expected: player_count,
            found: utilities.len(),
        });
    }
    Ok(utilities)
}

fn select_edge(node: &TreeNode, actor: usize, exploration_bias: u64) -> Result<usize, IsmctsError> {
    if let Some(index) = node.edges.iter().position(|edge| edge.visits == 0) {
        return Ok(index);
    }
    let mut best_index = 0usize;
    let mut best_score = i128::MIN;
    for (index, edge) in node.edges.iter().enumerate() {
        let utility = *edge
            .utility_sums
            .get(actor)
            .ok_or(IsmctsError::InvalidUtilityShape {
                expected: actor + 1,
                found: edge.utility_sums.len(),
            })?;
        let mean = i128::from(utility) / i128::from(edge.visits);
        let scaled_ratio = u64::from(node.visits)
            .saturating_mul(1_024)
            .div_ceil(u64::from(edge.visits));
        let root = ceil_sqrt(scaled_ratio);
        let bonus = u128::from(exploration_bias)
            .checked_mul(u128::from(root))
            .ok_or(IsmctsError::ArithmeticOverflow)?
            / 32;
        let score = mean
            .checked_add(i128::try_from(bonus).map_err(|_| IsmctsError::ArithmeticOverflow)?)
            .ok_or(IsmctsError::ArithmeticOverflow)?;
        if score > best_score {
            best_score = score;
            best_index = index;
        }
    }
    Ok(best_index)
}

fn choose_root_edge(root: &TreeNode, viewer: usize) -> Result<usize, IsmctsError> {
    let mut best = 0usize;
    for index in 1..root.edges.len() {
        let current = &root.edges[index];
        let incumbent = &root.edges[best];
        let replace = current.visits > incumbent.visits
            || (current.visits == incumbent.visits
                && compare_mean(current, incumbent, viewer)? == std::cmp::Ordering::Greater);
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
) -> Result<std::cmp::Ordering, IsmctsError> {
    let left_sum = *left
        .utility_sums
        .get(viewer)
        .ok_or(IsmctsError::InvalidUtilityShape {
            expected: viewer + 1,
            found: left.utility_sums.len(),
        })?;
    let right_sum = *right
        .utility_sums
        .get(viewer)
        .ok_or(IsmctsError::InvalidUtilityShape {
            expected: viewer + 1,
            found: right.utility_sums.len(),
        })?;
    Ok((i128::from(left_sum) * i128::from(right.visits))
        .cmp(&(i128::from(right_sum) * i128::from(left.visits))))
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
    use super::*;
    use splendor_belief::build_information_set_v1;
    use splendor_core::{visible_events, Audience, FullState, GameConfig, PlayerId};

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

    fn config() -> IsmctsConfigV1 {
        IsmctsConfigV1 {
            sample_seed: 17,
            simulations: 32,
            max_depth_turns: 2,
            exploration_bias: 100_000_000,
        }
    }

    #[test]
    fn repeated_search_is_exact_and_root_is_shared() {
        let info = information_set(2, 42);
        let first = search_ismcts_v1(&info, config()).unwrap();
        let second = search_ismcts_v1(&info, config()).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.stats.root_visits, config().simulations);
        assert!(first.stats.shared_node_hits >= config().simulations - 1);
        assert_eq!(
            first
                .action_stats
                .iter()
                .map(|stats| stats.visits)
                .sum::<u32>(),
            config().simulations
        );
    }

    #[test]
    fn two_three_four_player_roots_are_supported_and_legal() {
        for players in 2..=4 {
            let info = information_set(players, u64::from(players));
            let result = search_ismcts_v1(&info, config()).unwrap();
            let legal = sample_determinization_v1(&info, config().sample_seed, 0)
                .unwrap()
                .state()
                .legal_actions();
            assert!(legal.contains(&result.action));
            assert!(result
                .action_stats
                .iter()
                .all(|stats| stats.utility_sum_by_player.len() == players as usize));
        }
    }

    #[test]
    fn result_contains_information_set_identity_not_sampled_state_identity() {
        let info = information_set(2, 99);
        let result = search_ismcts_v1(&info, config()).unwrap();
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains(info.information_set_hash().as_str()));
        for index in 0..u64::from(config().simulations) {
            let sampled = sample_determinization_v1(&info, config().sample_seed, index).unwrap();
            assert!(!json.contains(sampled.state_hash().as_str()));
        }
    }

    #[test]
    fn invalid_config_is_rejected_before_sampling() {
        let info = information_set(2, 1);
        let mut bad = config();
        bad.simulations = 0;
        assert!(matches!(
            search_ismcts_v1(&info, bad),
            Err(IsmctsError::InvalidConfig(_))
        ));
    }
}
