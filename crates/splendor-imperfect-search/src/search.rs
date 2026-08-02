use splendor_belief::{sample_determinization_v1, InformationSetV1};
use splendor_core::{Action, Phase, PlayerId};
use splendor_search::{canonical_order, search_maxn_v1, SearchError, StaticEvaluatorV1};

use crate::config::RootDeterminizationConfigV1;
use crate::error::ImperfectSearchError;
use crate::model::{
    RootActionAggregateV1, RootDeterminizationResultV1, RootDeterminizationStatsV1,
};

/// Aggregate one root action across deterministic hidden-state samples.
///
/// Every sample must expose exactly the same canonical root action set. Each
/// root action is applied to a private clone of that sample. Terminal children
/// are statically evaluated; all other children are passed to the frozen MaxN
/// continuation search. Utility vectors are summed with checked `i64`
/// arithmetic, and the root player's largest total wins with the earlier
/// canonical action breaking ties.
pub fn aggregate_root_determinizations_v1(
    information_set: &InformationSetV1,
    config: RootDeterminizationConfigV1,
) -> Result<RootDeterminizationResultV1, ImperfectSearchError> {
    config.validate()?;

    let observation = information_set.observation();
    let root_player = observation.public.current_player;
    if observation.viewer != root_player {
        return Err(ImperfectSearchError::ViewerIsNotRootPlayer {
            viewer: observation.viewer,
            current_player: root_player,
        });
    }
    if observation.public.phase == Phase::GameOver {
        return Err(ImperfectSearchError::TerminalInformationSet);
    }

    let player_count = usize::from(observation.public.player_count);
    if root_player.index() >= player_count {
        return Err(ImperfectSearchError::Engine(format!(
            "root player {:?} is outside player count {player_count}",
            root_player
        )));
    }

    let mut expected_actions: Option<Vec<Action>> = None;
    let mut aggregates: Vec<RootActionAggregateV1> = Vec::new();
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
            sample_determinization_v1(information_set, config.sample_seed, sample_index)?;
        let state = determinization.state();
        let actions = canonical_order(&state.legal_actions());
        if actions.is_empty() {
            return Err(ImperfectSearchError::NoLegalActions);
        }

        ensure_root_action_set(expected_actions.as_deref(), &actions, sample_index)?;
        if expected_actions.is_none() {
            stats.root_actions = u32::try_from(actions.len()).map_err(|_| {
                ImperfectSearchError::Overflow("root action count exceeds u32".to_owned())
            })?;
            aggregates = actions
                .iter()
                .copied()
                .map(|action| RootActionAggregateV1 {
                    action,
                    utility_sum_by_player: vec![0; player_count],
                })
                .collect();
            expected_actions = Some(actions);
        }

        let root_actions = expected_actions
            .as_deref()
            .ok_or(ImperfectSearchError::NoLegalActions)?;
        for (action_index, action) in root_actions.iter().copied().enumerate() {
            let mut child = state.clone();
            child
                .apply(action)
                .map_err(|error| ImperfectSearchError::Engine(error.to_string()))?;

            let utility_by_player = if child.is_terminal() {
                let utilities = StaticEvaluatorV1::utilities(&child).map_err(map_search_error)?;
                checked_add_u64(&mut stats.terminal_children, 1, "terminal child count")?;
                utilities
            } else {
                let continuation =
                    search_maxn_v1(&child, config.continuation_search).map_err(map_search_error)?;
                checked_add_u64(
                    &mut stats.continuation_searches,
                    1,
                    "continuation search count",
                )?;
                checked_add_u64(
                    &mut stats.nodes_visited,
                    continuation.stats.nodes_visited,
                    "nodes_visited",
                )?;
                checked_add_u64(
                    &mut stats.nodes_expanded,
                    continuation.stats.nodes_expanded,
                    "nodes_expanded",
                )?;
                checked_add_u64(
                    &mut stats.leaf_evaluations,
                    continuation.stats.leaf_evaluations,
                    "leaf_evaluations",
                )?;
                checked_add_u64(
                    &mut stats.transposition_hits,
                    continuation.stats.transposition_hits,
                    "transposition_hits",
                )?;
                continuation.utility_by_player
            };

            validate_utility_shape(player_count, utility_by_player.len())?;
            for (player, value) in utility_by_player.into_iter().enumerate() {
                checked_add_i64(
                    &mut aggregates[action_index].utility_sum_by_player[player],
                    value,
                    "utility sum",
                )?;
            }
        }
    }

    let action = choose_best_action(&aggregates, root_player)?;
    Ok(RootDeterminizationResultV1 {
        action,
        root_player,
        sample_seed: config.sample_seed,
        sample_count: config.sample_count,
        action_aggregates: aggregates,
        stats,
    })
}

/// Compatibility spelling for callers that describe the operation as a
/// search rather than an aggregation.
pub fn search_root_determinizations_v1(
    information_set: &InformationSetV1,
    config: RootDeterminizationConfigV1,
) -> Result<RootDeterminizationResultV1, ImperfectSearchError> {
    aggregate_root_determinizations_v1(information_set, config)
}

fn ensure_root_action_set(
    expected: Option<&[Action]>,
    actual: &[Action],
    sample_index: u64,
) -> Result<(), ImperfectSearchError> {
    if let Some(expected) = expected {
        if expected != actual {
            return Err(ImperfectSearchError::RootActionSetMismatch { sample_index });
        }
    }
    Ok(())
}

fn validate_utility_shape(expected: usize, found: usize) -> Result<(), ImperfectSearchError> {
    if expected != found {
        return Err(ImperfectSearchError::UtilityShapeMismatch { expected, found });
    }
    Ok(())
}

fn checked_add_i64(
    target: &mut i64,
    value: i64,
    context: &str,
) -> Result<(), ImperfectSearchError> {
    *target = target
        .checked_add(value)
        .ok_or_else(|| ImperfectSearchError::Overflow(context.to_owned()))?;
    Ok(())
}

fn checked_add_u64(
    target: &mut u64,
    value: u64,
    context: &str,
) -> Result<(), ImperfectSearchError> {
    *target = target
        .checked_add(value)
        .ok_or_else(|| ImperfectSearchError::Overflow(context.to_owned()))?;
    Ok(())
}

fn choose_best_action(
    aggregates: &[RootActionAggregateV1],
    root_player: PlayerId,
) -> Result<Action, ImperfectSearchError> {
    let first = aggregates
        .first()
        .ok_or(ImperfectSearchError::NoLegalActions)?;
    let player_index = root_player.index();
    let mut best = first;
    let mut best_value = *best
        .utility_sum_by_player
        .get(player_index)
        .ok_or_else(|| ImperfectSearchError::UtilityShapeMismatch {
            expected: player_index + 1,
            found: best.utility_sum_by_player.len(),
        })?;

    for candidate in &aggregates[1..] {
        let value = *candidate
            .utility_sum_by_player
            .get(player_index)
            .ok_or_else(|| ImperfectSearchError::UtilityShapeMismatch {
                expected: player_index + 1,
                found: candidate.utility_sum_by_player.len(),
            })?;
        if value > best_value {
            best = candidate;
            best_value = value;
        }
    }

    Ok(best.action)
}

fn map_search_error(error: SearchError) -> ImperfectSearchError {
    match error {
        SearchError::InvalidUtilityShape { expected, found } => {
            ImperfectSearchError::UtilityShapeMismatch { expected, found }
        }
        other => ImperfectSearchError::Search(other),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_core::Tier;

    #[test]
    fn action_set_mismatch_is_fail_closed() {
        let expected = [Action::Pass];
        let actual = [Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        }];

        let error = ensure_root_action_set(Some(&expected), &actual, 3).unwrap_err();
        assert!(matches!(
            error,
            ImperfectSearchError::RootActionSetMismatch { sample_index: 3 }
        ));
    }

    #[test]
    fn utility_shape_is_checked() {
        let error = validate_utility_shape(3, 2).unwrap_err();
        assert!(matches!(
            error,
            ImperfectSearchError::UtilityShapeMismatch {
                expected: 3,
                found: 2
            }
        ));
    }

    #[test]
    fn checked_arithmetic_reports_overflow() {
        let mut signed = i64::MAX;
        assert!(matches!(
            checked_add_i64(&mut signed, 1, "signed test"),
            Err(ImperfectSearchError::Overflow(message)) if message == "signed test"
        ));

        let mut unsigned = u64::MAX;
        assert!(matches!(
            checked_add_u64(&mut unsigned, 1, "unsigned test"),
            Err(ImperfectSearchError::Overflow(message)) if message == "unsigned test"
        ));
    }

    #[test]
    fn canonical_tie_keeps_the_earlier_aggregate() {
        let early = Action::BuyMarket {
            tier: Tier::One,
            slot: 0,
        };
        let late = Action::Pass;
        let aggregates = vec![
            RootActionAggregateV1 {
                action: early,
                utility_sum_by_player: vec![7, 0],
            },
            RootActionAggregateV1 {
                action: late,
                utility_sum_by_player: vec![7, 0],
            },
        ];

        assert_eq!(choose_best_action(&aggregates, PlayerId(0)).unwrap(), early);
    }
}
