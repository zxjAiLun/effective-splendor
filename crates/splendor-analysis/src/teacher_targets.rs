use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_core::{observation_hash, visible_events, Action, Audience, PlayerId, Ruleset};
use splendor_imperfect_search::{
    analyze_player_view_v1, RootActionAggregateV1, RootDeterminizationConfigV1,
};
use splendor_league::{training_dataset_hash_v1, TrainingDatasetV1, TrainingReplayV1};
use splendor_replay::{replay_document_hash_v1, verify_replay_trace, ReplayV1};
use splendor_search::canonical_order;

use crate::AnalysisError;

pub const SEARCH_TEACHER_TARGETS_FORMAT: &str = "effective-splendor-search-teacher-targets";
pub const SEARCH_TEACHER_TARGETS_VERSION: u32 = 1;
pub const SEARCH_VALUE_TARGET_SCALE_V1: u32 = 1_000_000;
pub const SEARCH_TEACHER_BUILD_CONFIG_FORMAT: &str =
    "effective-splendor-search-teacher-build-config";
pub const SEARCH_TEACHER_BUILD_CONFIG_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchTeacherTargetsConfigV1 {
    pub search: RootDeterminizationConfigV1,
    /// Total probability mass reserved for uniform exploration.
    pub uniform_floor_micros: u32,
    /// Absolute mean search utility that maps from 0.5 to 1.0 (or 0.0).
    pub value_utility_scale: u64,
}

impl SearchTeacherTargetsConfigV1 {
    pub fn validate(&self) -> Result<(), AnalysisError> {
        self.search
            .validate()
            .map_err(|error| teacher(error.to_string()))?;
        if self.uniform_floor_micros > SEARCH_VALUE_TARGET_SCALE_V1 {
            return Err(teacher("uniform_floor_micros must be <= 1000000"));
        }
        if self.value_utility_scale == 0 || self.value_utility_scale > i64::MAX as u64 {
            return Err(teacher("value_utility_scale must be within 1..=i64::MAX"));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchTeacherBuildConfigV1 {
    pub format: String,
    pub version: u32,
    pub expected_dataset_id: String,
    pub expected_dataset_hash: String,
    pub expected_league_manifest_hash: String,
    pub expected_evaluation_plan_hash: String,
    pub expected_evaluation_report_hash: String,
    pub teacher_agent_ids: Vec<String>,
    pub targets: SearchTeacherTargetsConfigV1,
}

impl SearchTeacherBuildConfigV1 {
    pub fn validate(&self) -> Result<(), AnalysisError> {
        if self.format != SEARCH_TEACHER_BUILD_CONFIG_FORMAT
            || self.version != SEARCH_TEACHER_BUILD_CONFIG_VERSION
        {
            return Err(teacher("unsupported search-teacher build config"));
        }
        if self.expected_dataset_id.trim().is_empty()
            || self.expected_dataset_id.len() > 128
            || self.expected_dataset_id.bytes().any(|byte| byte < 0x20)
        {
            return Err(teacher("expected_dataset_id is invalid"));
        }
        for hash in [
            &self.expected_dataset_hash,
            &self.expected_league_manifest_hash,
            &self.expected_evaluation_plan_hash,
            &self.expected_evaluation_report_hash,
        ] {
            validate_hash(hash)?;
        }
        validate_teacher_ids(&self.teacher_agent_ids)?;
        self.targets.validate()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchTeacherActionTargetV1 {
    pub action: Action,
    pub policy_target_micros: u32,
    pub utility_sum_by_player: Vec<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchTeacherTargetV1 {
    pub source_id: String,
    pub replay_document_hash: String,
    pub ply: u32,
    pub actor: PlayerId,
    pub observation_hash: String,
    pub visible_history_hash: String,
    pub information_set_hash: String,
    pub recorded_action: Action,
    pub teacher_action: Action,
    pub action_targets: Vec<SearchTeacherActionTargetV1>,
    /// Search-shaped value of the teacher-selected action, in millionths.
    pub value_target_by_player_micros: Vec<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchTeacherTargetSetV1 {
    pub format: String,
    pub version: u32,
    pub dataset_id: String,
    pub dataset_hash: String,
    pub league_manifest_hash: String,
    pub evaluation_plan_hash: String,
    pub evaluation_report_hash: String,
    pub teacher_agent_ids: Vec<String>,
    pub config: SearchTeacherTargetsConfigV1,
    pub targets: Vec<SearchTeacherTargetV1>,
}

impl SearchTeacherTargetSetV1 {
    pub fn validate(&self) -> Result<(), AnalysisError> {
        if self.format != SEARCH_TEACHER_TARGETS_FORMAT
            || self.version != SEARCH_TEACHER_TARGETS_VERSION
        {
            return Err(teacher("unsupported search-teacher format/version"));
        }
        for hash in [
            &self.dataset_hash,
            &self.league_manifest_hash,
            &self.evaluation_plan_hash,
            &self.evaluation_report_hash,
        ] {
            validate_hash(hash)?;
        }
        validate_teacher_ids(&self.teacher_agent_ids)?;
        self.config.validate()?;
        if self.targets.is_empty() {
            return Err(teacher("search-teacher target set is empty"));
        }
        let mut keys = HashSet::new();
        for target in &self.targets {
            if !keys.insert((target.source_id.as_str(), target.ply)) {
                return Err(teacher("duplicate source_id/ply target"));
            }
            validate_hash(&target.replay_document_hash)?;
            validate_hash(&target.observation_hash)?;
            validate_hash(&target.visible_history_hash)?;
            validate_hash(&target.information_set_hash)?;
            validate_target(target, &self.config)?;
        }
        Ok(())
    }
}

pub fn build_search_teacher_targets_v1(
    dataset: &TrainingDatasetV1,
    replays_by_match_index: &[(u32, ReplayV1)],
    build_config: &SearchTeacherBuildConfigV1,
) -> Result<SearchTeacherTargetSetV1, AnalysisError> {
    build_config.validate()?;
    let config = &build_config.targets;
    let dataset_hash = training_dataset_hash_v1(dataset)
        .map_err(|error| teacher(format!("invalid source dataset: {error}")))?;
    if dataset.dataset_id != build_config.expected_dataset_id
        || dataset_hash != build_config.expected_dataset_hash
        || dataset.league_manifest_hash != build_config.expected_league_manifest_hash
        || dataset.evaluation_plan_hash != build_config.expected_evaluation_plan_hash
        || dataset.evaluation_report_hash != build_config.expected_evaluation_report_hash
    {
        return Err(teacher("source dataset does not match frozen build config"));
    }
    let replay_metadata = dataset
        .replays
        .iter()
        .map(|replay| (replay.evaluation_match_index, replay))
        .collect::<HashMap<_, _>>();
    if replay_metadata.len() != dataset.replays.len() {
        return Err(teacher("dataset has duplicate evaluation match indices"));
    }
    let supplied = replays_by_match_index
        .iter()
        .map(|(index, replay)| (*index, replay))
        .collect::<HashMap<_, _>>();
    if supplied.len() != replays_by_match_index.len() || supplied.len() != replay_metadata.len() {
        return Err(teacher(
            "supplied replay set must exactly match dataset replay indices",
        ));
    }
    let teacher_ids = build_config
        .teacher_agent_ids
        .iter()
        .collect::<HashSet<_>>();
    let examples_by_source =
        dataset
            .examples
            .iter()
            .fold(HashMap::<&str, Vec<_>>::new(), |mut map, example| {
                map.entry(example.source_id.as_str())
                    .or_default()
                    .push(example);
                map
            });
    let mut targets = Vec::new();
    for metadata in &dataset.replays {
        let replay = supplied
            .get(&metadata.evaluation_match_index)
            .ok_or_else(|| teacher("dataset replay index is missing"))?;
        bind_replay(metadata, replay)?;
        let trace = verify_replay_trace(replay)
            .map_err(|error| teacher(format!("replay verification failed: {error}")))?;
        let source_examples = examples_by_source
            .get(metadata.source_id.as_str())
            .ok_or_else(|| teacher("dataset replay has no examples"))?;
        for example in source_examples {
            let identity = metadata
                .agents_by_seat
                .get(example.actor.index())
                .ok_or_else(|| teacher("example actor has no replay agent identity"))?;
            if !teacher_ids.contains(&identity.league_agent_id) {
                continue;
            }
            let position = trace
                .positions
                .get(example.ply as usize)
                .ok_or_else(|| teacher("example ply is absent from verified replay"))?;
            bind_example(example, position)?;
            let observation = position.state.observation(example.actor);
            let history = visible_events(&position.state.log, Audience::Player(example.actor));
            let analysis =
                analyze_player_view_v1(Ruleset::base_v1(), &observation, &history, config.search)
                    .map_err(|error| teacher(format!("teacher search failed: {error}")))?;
            if analysis.visible_history_hash().as_str() != example.visible_history_hash
                || analysis.information_set_hash().as_str() != example.information_set_hash
            {
                return Err(teacher(
                    "teacher information set differs from dataset provenance",
                ));
            }
            let result = analysis.result();
            let legal_actions = canonical_order(&position.state.legal_actions());
            if legal_actions != example.legal_actions
                || result
                    .action_aggregates
                    .iter()
                    .map(|aggregate| aggregate.action)
                    .ne(legal_actions.iter().copied())
            {
                return Err(teacher(
                    "teacher root actions differ from dataset legal actions",
                ));
            }
            let policy = policy_targets(
                &result.action_aggregates,
                example.actor.index(),
                config.uniform_floor_micros,
            )?;
            let action_targets = result
                .action_aggregates
                .iter()
                .zip(policy)
                .map(
                    |(aggregate, policy_target_micros)| SearchTeacherActionTargetV1 {
                        action: aggregate.action,
                        policy_target_micros,
                        utility_sum_by_player: aggregate.utility_sum_by_player.clone(),
                    },
                )
                .collect::<Vec<_>>();
            let selected = result
                .action_aggregates
                .iter()
                .find(|aggregate| aggregate.action == result.action)
                .ok_or_else(|| teacher("teacher-selected action has no aggregate"))?;
            let values = value_targets(
                &selected.utility_sum_by_player,
                result.sample_count,
                config.value_utility_scale,
            )?;
            targets.push(SearchTeacherTargetV1 {
                source_id: example.source_id.clone(),
                replay_document_hash: example.replay_document_hash.clone(),
                ply: example.ply,
                actor: example.actor,
                observation_hash: example.observation_hash.clone(),
                visible_history_hash: analysis.visible_history_hash().as_str().into(),
                information_set_hash: analysis.information_set_hash().as_str().into(),
                recorded_action: example.chosen_action,
                teacher_action: result.action,
                action_targets,
                value_target_by_player_micros: values,
            });
        }
    }
    let output = SearchTeacherTargetSetV1 {
        format: SEARCH_TEACHER_TARGETS_FORMAT.into(),
        version: SEARCH_TEACHER_TARGETS_VERSION,
        dataset_id: dataset.dataset_id.clone(),
        dataset_hash,
        league_manifest_hash: dataset.league_manifest_hash.clone(),
        evaluation_plan_hash: dataset.evaluation_plan_hash.clone(),
        evaluation_report_hash: dataset.evaluation_report_hash.clone(),
        teacher_agent_ids: build_config.teacher_agent_ids.clone(),
        config: config.clone(),
        targets,
    };
    output.validate()?;
    Ok(output)
}

pub fn search_teacher_targets_hash_v1(
    targets: &SearchTeacherTargetSetV1,
) -> Result<String, AnalysisError> {
    targets.validate()?;
    let bytes = serde_json::to_vec(targets)
        .map_err(|error| AnalysisError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-search-teacher-targets-v1\0");
    hasher.update(bytes);
    Ok(hex::encode(hasher.finalize()))
}

fn bind_replay(metadata: &TrainingReplayV1, replay: &ReplayV1) -> Result<(), AnalysisError> {
    let hash = replay_document_hash_v1(replay)
        .map_err(|error| teacher(format!("replay hash failed: {error}")))?;
    if hash != metadata.replay_document_hash
        || replay.engine_version != metadata.engine_version
        || replay.ruleset.id != metadata.ruleset_id
        || replay.ruleset_fingerprint.as_str() != metadata.ruleset_fingerprint
        || replay.player_count != metadata.player_count
        || replay.steps.len() as u32 != metadata.steps
        || replay.final_state_hash.as_str() != metadata.final_state_hash
        || replay.result != metadata.result
    {
        return Err(teacher("replay does not match dataset provenance"));
    }
    Ok(())
}

fn bind_example(
    example: &splendor_league::TrainingExampleV1,
    position: &splendor_replay::VerifiedReplayTraceStep,
) -> Result<(), AnalysisError> {
    let observation = position.state.observation(position.recorded_actor);
    if position.ply != example.ply
        || position.recorded_actor != example.actor
        || position.recorded_action != example.chosen_action
        || observation != example.observation
        || observation_hash(&observation).as_str() != example.observation_hash
        || canonical_order(&position.state.legal_actions()) != example.legal_actions
    {
        return Err(teacher(
            "dataset example does not match verified replay position",
        ));
    }
    Ok(())
}

fn validate_target(
    target: &SearchTeacherTargetV1,
    config: &SearchTeacherTargetsConfigV1,
) -> Result<(), AnalysisError> {
    if target.action_targets.is_empty() {
        return Err(teacher("teacher target has no legal actions"));
    }
    let player_count = target.value_target_by_player_micros.len();
    if !(2..=4).contains(&player_count)
        || target.actor.index() >= player_count
        || target
            .value_target_by_player_micros
            .iter()
            .any(|value| *value > SEARCH_VALUE_TARGET_SCALE_V1)
        || !target
            .action_targets
            .iter()
            .any(|entry| entry.action == target.recorded_action)
        || !target
            .action_targets
            .iter()
            .any(|entry| entry.action == target.teacher_action)
        || target
            .action_targets
            .iter()
            .any(|entry| entry.utility_sum_by_player.len() != player_count)
    {
        return Err(teacher("teacher target identity/value shape is invalid"));
    }
    let target_actions = target
        .action_targets
        .iter()
        .map(|entry| entry.action)
        .collect::<Vec<_>>();
    if canonical_order(&target_actions) != target_actions {
        return Err(teacher("teacher target actions are not canonical"));
    }
    let sum = target
        .action_targets
        .iter()
        .try_fold(0u32, |sum, entry| {
            sum.checked_add(entry.policy_target_micros)
        })
        .ok_or_else(|| teacher("policy target sum overflow"))?;
    if sum != SEARCH_VALUE_TARGET_SCALE_V1 {
        return Err(teacher("policy targets do not sum to 1000000"));
    }
    let aggregates = target
        .action_targets
        .iter()
        .map(|entry| RootActionAggregateV1 {
            action: entry.action,
            utility_sum_by_player: entry.utility_sum_by_player.clone(),
        })
        .collect::<Vec<_>>();
    let expected_policy = policy_targets(
        &aggregates,
        target.actor.index(),
        config.uniform_floor_micros,
    )?;
    if expected_policy.iter().ne(target
        .action_targets
        .iter()
        .map(|entry| &entry.policy_target_micros))
    {
        return Err(teacher("policy target is not canonical utility projection"));
    }
    let best = aggregates
        .iter()
        .max_by_key(|aggregate| aggregate.utility_sum_by_player[target.actor.index()])
        .ok_or_else(|| teacher("teacher target has no best action"))?;
    // max_by_key chooses the last tie; the runtime freezes the first tie.
    let best_value = best.utility_sum_by_player[target.actor.index()];
    let canonical_best = aggregates
        .iter()
        .find(|aggregate| aggregate.utility_sum_by_player[target.actor.index()] == best_value)
        .ok_or_else(|| teacher("teacher target has no canonical best action"))?;
    if canonical_best.action != target.teacher_action {
        return Err(teacher("teacher action is not canonical maximum utility"));
    }
    let expected_value = value_targets(
        &canonical_best.utility_sum_by_player,
        config.search.sample_count,
        config.value_utility_scale,
    )?;
    if expected_value != target.value_target_by_player_micros {
        return Err(teacher("value target is not canonical utility projection"));
    }
    Ok(())
}

fn policy_targets(
    aggregates: &[RootActionAggregateV1],
    actor: usize,
    uniform_floor_micros: u32,
) -> Result<Vec<u32>, AnalysisError> {
    if aggregates.is_empty()
        || aggregates
            .iter()
            .any(|entry| actor >= entry.utility_sum_by_player.len())
    {
        return Err(teacher("invalid utility aggregates for Policy projection"));
    }
    let minimum = aggregates
        .iter()
        .map(|entry| entry.utility_sum_by_player[actor])
        .min()
        .ok_or_else(|| teacher("utility projection has no minimum"))?;
    let advantages = aggregates
        .iter()
        .map(|entry| {
            i128::from(entry.utility_sum_by_player[actor])
                .checked_sub(i128::from(minimum))
                .and_then(|value| u128::try_from(value).ok())
                .ok_or_else(|| teacher("utility advantage overflow"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let advantage_sum = advantages
        .iter()
        .try_fold(0u128, |sum, value| sum.checked_add(*value))
        .ok_or_else(|| teacher("utility advantage sum overflow"))?;
    let count = u32::try_from(aggregates.len()).map_err(|_| teacher("too many root actions"))?;
    let mut targets = even_allocation(uniform_floor_micros, count);
    let remaining = SEARCH_VALUE_TARGET_SCALE_V1 - uniform_floor_micros;
    let variable = if advantage_sum == 0 {
        even_allocation(remaining, count)
    } else {
        proportional_allocation(remaining, &advantages, advantage_sum)?
    };
    for (target, addition) in targets.iter_mut().zip(variable) {
        *target = target
            .checked_add(addition)
            .ok_or_else(|| teacher("policy target overflow"))?;
    }
    Ok(targets)
}

fn even_allocation(total: u32, count: u32) -> Vec<u32> {
    let base = total / count;
    let remainder = total % count;
    (0..count)
        .map(|index| base + u32::from(index < remainder))
        .collect()
}

fn proportional_allocation(
    total: u32,
    weights: &[u128],
    weight_sum: u128,
) -> Result<Vec<u32>, AnalysisError> {
    let mut allocated = Vec::with_capacity(weights.len());
    let mut remainders = Vec::with_capacity(weights.len());
    let mut used = 0u32;
    for (index, weight) in weights.iter().enumerate() {
        let numerator = u128::from(total)
            .checked_mul(*weight)
            .ok_or_else(|| teacher("policy allocation overflow"))?;
        let quotient = u32::try_from(numerator / weight_sum)
            .map_err(|_| teacher("policy allocation exceeds u32"))?;
        used = used
            .checked_add(quotient)
            .ok_or_else(|| teacher("policy allocation sum overflow"))?;
        allocated.push(quotient);
        remainders.push((numerator % weight_sum, index));
    }
    remainders.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
    for (_, index) in remainders.into_iter().take((total - used) as usize) {
        allocated[index] += 1;
    }
    Ok(allocated)
}

fn value_targets(
    utility_sum_by_player: &[i64],
    sample_count: u16,
    value_utility_scale: u64,
) -> Result<Vec<u32>, AnalysisError> {
    if sample_count == 0 || utility_sum_by_player.is_empty() {
        return Err(teacher("invalid utility vector for Value projection"));
    }
    let denominator = i128::from(sample_count) * i128::from(value_utility_scale);
    utility_sum_by_player
        .iter()
        .map(|sum| {
            let offset = i128::from(*sum)
                .checked_mul(i128::from(SEARCH_VALUE_TARGET_SCALE_V1 / 2))
                .ok_or_else(|| teacher("Value projection overflow"))?
                / denominator;
            let value = i128::from(SEARCH_VALUE_TARGET_SCALE_V1 / 2) + offset;
            Ok(value.clamp(0, i128::from(SEARCH_VALUE_TARGET_SCALE_V1)) as u32)
        })
        .collect()
}

fn validate_teacher_ids(values: &[String]) -> Result<(), AnalysisError> {
    if values.is_empty() {
        return Err(teacher("teacher_agent_ids must not be empty"));
    }
    let mut seen = HashSet::new();
    for value in values {
        if value.trim().is_empty()
            || value.len() > 128
            || value.bytes().any(|byte| byte < 0x20)
            || !seen.insert(value)
        {
            return Err(teacher("teacher_agent_ids are invalid or duplicated"));
        }
    }
    Ok(())
}

fn validate_hash(value: &str) -> Result<(), AnalysisError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(teacher("artifact hash is not lowercase SHA-256"));
    }
    Ok(())
}

fn teacher(message: impl Into<String>) -> AnalysisError {
    AnalysisError::TeacherTarget(message.into())
}

#[cfg(test)]
mod tests {
    use splendor_belief::build_information_set_v1;
    use splendor_league::{
        TrainingAgentIdentityV1, TrainingExampleV1, TrainingReplayV1, TRAINING_DATASET_FORMAT,
        TRAINING_DATASET_VERSION,
    };
    use splendor_replay::{record_random_game, verify_replay_trace};
    use splendor_search::SearchConfigV1;

    use super::*;

    #[test]
    fn utility_projection_is_exact_deterministic_and_tie_stable() {
        let aggregates = vec![
            RootActionAggregateV1 {
                action: Action::Pass,
                utility_sum_by_player: vec![-10, 10],
            },
            RootActionAggregateV1 {
                action: Action::Pass,
                utility_sum_by_player: vec![0, 0],
            },
            RootActionAggregateV1 {
                action: Action::Pass,
                utility_sum_by_player: vec![10, -10],
            },
        ];
        let targets = policy_targets(&aggregates, 0, 100_000).unwrap();
        assert_eq!(targets.iter().sum::<u32>(), 1_000_000);
        assert!(targets[0] < targets[1] && targets[1] < targets[2]);
        assert_eq!(policy_targets(&aggregates, 0, 100_000).unwrap(), targets);
        assert_eq!(
            value_targets(&[2_000_000_000, -2_000_000_000], 4, 1_000_000_000).unwrap(),
            vec![750_000, 250_000]
        );
    }

    #[test]
    fn replay_bound_teacher_targets_are_deterministic_and_player_view_only() {
        let (_, replay) = record_random_game(2, 44, 55).unwrap();
        let trace = verify_replay_trace(&replay).unwrap();
        let replay_hash = replay_document_hash_v1(&replay).unwrap();
        let source_id = "teacher-source".to_string();
        let examples = trace
            .positions
            .iter()
            .map(|position| {
                let observation = position.state.observation(position.recorded_actor);
                let history = visible_events(
                    &position.state.log,
                    Audience::Player(position.recorded_actor),
                );
                let information =
                    build_information_set_v1(Ruleset::base_v1(), &observation, &history).unwrap();
                TrainingExampleV1 {
                    source_id: source_id.clone(),
                    replay_document_hash: replay_hash.clone(),
                    ply: position.ply,
                    actor: position.recorded_actor,
                    observation_hash: observation_hash(&observation).as_str().into(),
                    visible_history_hash: information.visible_history_hash().as_str().into(),
                    information_set_hash: information.information_set_hash().as_str().into(),
                    observation,
                    legal_actions: canonical_order(&position.state.legal_actions()),
                    chosen_action: position.recorded_action,
                    final_scores: replay.result.scores.clone(),
                    final_ranks: replay.result.ranks.clone(),
                }
            })
            .collect::<Vec<_>>();
        let dataset = TrainingDatasetV1 {
            format: TRAINING_DATASET_FORMAT.into(),
            version: TRAINING_DATASET_VERSION,
            dataset_id: "teacher-unit-dataset".into(),
            league_manifest_hash: "11".repeat(32),
            evaluation_id: "teacher-unit-evaluation".into(),
            evaluation_plan_hash: "22".repeat(32),
            evaluation_report_hash: "33".repeat(32),
            replays: vec![TrainingReplayV1 {
                source_id,
                evaluation_match_index: 0,
                seed_index: 0,
                rotation: 0,
                arena_game_id: "teacher-unit-game".into(),
                arena_report_hash: "44".repeat(32),
                replay_document_hash: replay_hash,
                engine_version: replay.engine_version.clone(),
                ruleset_id: replay.ruleset.id.clone(),
                ruleset_fingerprint: replay.ruleset_fingerprint.as_str().into(),
                player_count: replay.player_count,
                steps: replay.steps.len() as u32,
                final_state_hash: replay.final_state_hash.as_str().into(),
                result: replay.result.clone(),
                agents_by_seat: (0..2)
                    .map(|seat| TrainingAgentIdentityV1 {
                        seat: PlayerId(seat),
                        league_agent_id: "teacher".into(),
                        policy_version: "teacher-policy".into(),
                        model_version: None,
                        runtime_name: "teacher-runtime".into(),
                        runtime_version: "1".into(),
                    })
                    .collect(),
            }],
            examples,
        };
        let dataset_hash = training_dataset_hash_v1(&dataset).unwrap();
        let config = SearchTeacherBuildConfigV1 {
            format: SEARCH_TEACHER_BUILD_CONFIG_FORMAT.into(),
            version: SEARCH_TEACHER_BUILD_CONFIG_VERSION,
            expected_dataset_id: dataset.dataset_id.clone(),
            expected_dataset_hash: dataset_hash,
            expected_league_manifest_hash: dataset.league_manifest_hash.clone(),
            expected_evaluation_plan_hash: dataset.evaluation_plan_hash.clone(),
            expected_evaluation_report_hash: dataset.evaluation_report_hash.clone(),
            teacher_agent_ids: vec!["teacher".into()],
            targets: SearchTeacherTargetsConfigV1 {
                search: RootDeterminizationConfigV1 {
                    sample_seed: 17,
                    sample_count: 1,
                    continuation_search: SearchConfigV1 {
                        max_depth_turns: 1,
                        max_nodes: 100,
                    },
                },
                uniform_floor_micros: 100_000,
                value_utility_scale: 1_000_000_000,
            },
        };
        let left =
            build_search_teacher_targets_v1(&dataset, &[(0, replay.clone())], &config).unwrap();
        let right = build_search_teacher_targets_v1(&dataset, &[(0, replay)], &config).unwrap();
        assert_eq!(left, right);
        assert_eq!(left.targets.len(), dataset.examples.len());
        assert_eq!(
            search_teacher_targets_hash_v1(&left).unwrap(),
            search_teacher_targets_hash_v1(&right).unwrap()
        );
    }
}
