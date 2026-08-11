use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_league::{
    training_dataset_hash_v1, TrainingDatasetV1, TrainingExampleV1, TRAINING_DATASET_FORMAT,
    TRAINING_DATASET_VERSION,
};

use crate::error::{invalid_checkpoint, invalid_config, invalid_dataset};
use crate::model::initialize_checkpoint;
use crate::{
    encode_action_v1, encode_observation_v1, model_checkpoint_hash_v1, LearningError,
    PolicyValueCheckpointV1, PolicyValueModelV1, ACTION_FEATURES_V1, MAX_PLAYERS_V1,
    OBSERVATION_FEATURES_V1,
};

pub const POLICY_VALUE_TRAINING_CONFIG_FORMAT: &str =
    "effective-splendor-policy-value-training-config";
pub const POLICY_VALUE_TRAINING_CONFIG_VERSION: u32 = 1;
pub const POLICY_VALUE_TRAINING_REPORT_FORMAT: &str =
    "effective-splendor-policy-value-training-report";
pub const POLICY_VALUE_TRAINING_REPORT_VERSION: u32 = 1;
pub const OFFLINE_EVALUATION_FORMAT: &str = "effective-splendor-policy-value-offline-evaluation";
pub const OFFLINE_EVALUATION_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyValueTrainingConfigV1 {
    pub format: String,
    pub version: u32,
    pub training_id: String,
    pub model_id: String,
    pub expected_dataset_id: String,
    pub expected_dataset_hash: String,
    pub expected_league_manifest_hash: String,
    pub expected_evaluation_plan_hash: String,
    pub expected_evaluation_report_hash: String,
    pub hidden_features: u32,
    pub epochs: u32,
    pub learning_rate: f32,
    pub value_loss_weight: f32,
    pub l2_weight: f32,
    pub init_seed: u64,
    pub validation_seed_modulus: u32,
    pub validation_seed_remainder: u32,
    /// Absent preserves the accepted M12 behavior byte-for-byte. Version 2
    /// enables explicit per-head source selection and material offline gates.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub training_contract_version: Option<u32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub policy_teacher_agent_ids: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub value_target_agent_ids: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min_policy_nll_relative_improvement_bps: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min_value_mse_relative_improvement_bps: Option<u32>,
}

impl PolicyValueTrainingConfigV1 {
    pub fn validate(&self) -> Result<(), LearningError> {
        if self.format != POLICY_VALUE_TRAINING_CONFIG_FORMAT
            || self.version != POLICY_VALUE_TRAINING_CONFIG_VERSION
        {
            return Err(invalid_config("unsupported format/version"));
        }
        validate_label("training_id", &self.training_id)?;
        validate_label("model_id", &self.model_id)?;
        validate_label("expected_dataset_id", &self.expected_dataset_id)?;
        for (label, value) in [
            ("expected_dataset_hash", &self.expected_dataset_hash),
            (
                "expected_league_manifest_hash",
                &self.expected_league_manifest_hash,
            ),
            (
                "expected_evaluation_plan_hash",
                &self.expected_evaluation_plan_hash,
            ),
            (
                "expected_evaluation_report_hash",
                &self.expected_evaluation_report_hash,
            ),
        ] {
            validate_hash(label, value)?;
        }
        if !(1..=256).contains(&self.hidden_features) {
            return Err(invalid_config("hidden_features must be in 1..=256"));
        }
        if !(1..=100).contains(&self.epochs) {
            return Err(invalid_config("epochs must be in 1..=100"));
        }
        if !self.learning_rate.is_finite() || self.learning_rate <= 0.0 || self.learning_rate > 1.0
        {
            return Err(invalid_config("learning_rate must be finite and in (0, 1]"));
        }
        if !self.value_loss_weight.is_finite()
            || self.value_loss_weight <= 0.0
            || self.value_loss_weight > 10.0
        {
            return Err(invalid_config(
                "value_loss_weight must be finite and in (0, 10]",
            ));
        }
        if !self.l2_weight.is_finite() || self.l2_weight < 0.0 || self.l2_weight > 1.0 {
            return Err(invalid_config("l2_weight must be finite and in [0, 1]"));
        }
        if self.validation_seed_modulus < 2
            || self.validation_seed_remainder >= self.validation_seed_modulus
        {
            return Err(invalid_config(
                "validation split requires modulus >= 2 and remainder < modulus",
            ));
        }
        match self.training_contract_version {
            None => {
                if !self.policy_teacher_agent_ids.is_empty()
                    || !self.value_target_agent_ids.is_empty()
                    || self.min_policy_nll_relative_improvement_bps.is_some()
                    || self.min_value_mse_relative_improvement_bps.is_some()
                {
                    return Err(invalid_config(
                        "source-aware fields require training_contract_version 2",
                    ));
                }
            }
            Some(2) => {
                validate_agent_selection(
                    "policy_teacher_agent_ids",
                    &self.policy_teacher_agent_ids,
                )?;
                validate_agent_selection("value_target_agent_ids", &self.value_target_agent_ids)?;
                validate_material_gate(
                    "min_policy_nll_relative_improvement_bps",
                    self.min_policy_nll_relative_improvement_bps,
                )?;
                validate_material_gate(
                    "min_value_mse_relative_improvement_bps",
                    self.min_value_mse_relative_improvement_bps,
                )?;
            }
            Some(_) => {
                return Err(invalid_config(
                    "training_contract_version must be absent or 2",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DatasetIdentityV1 {
    pub dataset_id: String,
    pub dataset_hash: String,
    pub league_manifest_hash: String,
    pub evaluation_plan_hash: String,
    pub evaluation_report_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DatasetSplitV1 {
    pub validation_seed_modulus: u32,
    pub validation_seed_remainder: u32,
    pub train_replays: u64,
    pub validation_replays: u64,
    pub train_examples: u64,
    pub validation_examples: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeadDatasetSplitV1 {
    pub train_policy_examples: u64,
    pub validation_policy_examples: u64,
    pub train_value_examples: u64,
    pub validation_value_examples: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OfflineMetricsV1 {
    pub examples: u64,
    pub policy_top1_accuracy: f64,
    pub mean_policy_nll: f64,
    pub value_mse: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TrainingOutcomeV1 {
    BaselinesBeaten,
    BaselineNotBeaten,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MetricComparisonV1 {
    pub uniform_policy_mean_nll: f64,
    pub train_prior_value_mse: f64,
    pub policy_nll_beats_uniform: bool,
    pub value_mse_beats_train_prior: bool,
    pub outcome: TrainingOutcomeV1,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeadOfflineMetricsV1 {
    pub policy_examples: u64,
    pub policy_top1_accuracy: f64,
    pub mean_policy_nll: f64,
    pub value_examples: u64,
    pub value_components: u64,
    pub value_mse: f64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MaterialOfflineGateV1 {
    pub min_policy_nll_relative_improvement_bps: u32,
    pub actual_policy_nll_relative_improvement_bps: u32,
    pub policy_passed: bool,
    pub min_value_mse_relative_improvement_bps: u32,
    pub actual_value_mse_relative_improvement_bps: u32,
    pub value_passed: bool,
    pub passed: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyValueTrainingReportV1 {
    pub format: String,
    pub version: u32,
    pub training_id: String,
    pub model_id: String,
    pub training_config_hash: String,
    pub checkpoint_hash: String,
    pub dataset: DatasetIdentityV1,
    pub split: DatasetSplitV1,
    pub train_metrics: OfflineMetricsV1,
    pub validation_metrics: OfflineMetricsV1,
    pub validation_comparison: MetricComparisonV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub head_split: Option<HeadDatasetSplitV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub train_head_metrics: Option<HeadOfflineMetricsV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub validation_head_metrics: Option<HeadOfflineMetricsV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub material_gate: Option<MaterialOfflineGateV1>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OfflineEvaluationReportV1 {
    pub format: String,
    pub version: u32,
    pub model_id: String,
    pub training_config_hash: String,
    pub checkpoint_hash: String,
    pub dataset: DatasetIdentityV1,
    pub split: DatasetSplitV1,
    pub train_metrics: OfflineMetricsV1,
    pub validation_metrics: OfflineMetricsV1,
    pub validation_comparison: MetricComparisonV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub head_split: Option<HeadDatasetSplitV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub train_head_metrics: Option<HeadOfflineMetricsV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub validation_head_metrics: Option<HeadOfflineMetricsV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub material_gate: Option<MaterialOfflineGateV1>,
}

pub fn training_config_hash_v1(
    config: &PolicyValueTrainingConfigV1,
) -> Result<String, LearningError> {
    config.validate()?;
    domain_hash(
        b"effective-splendor-policy-value-training-config-v1\0",
        config,
    )
}

pub fn train_policy_value_v1(
    dataset: &TrainingDatasetV1,
    config: &PolicyValueTrainingConfigV1,
) -> Result<(PolicyValueCheckpointV1, PolicyValueTrainingReportV1), LearningError> {
    config.validate()?;
    let prepared = PreparedDataset::new(
        dataset,
        config.validation_seed_modulus,
        config.validation_seed_remainder,
        &config.policy_teacher_agent_ids,
        &config.value_target_agent_ids,
    )?;
    validate_config_binding(config, &prepared.identity)?;
    let config_hash = training_config_hash_v1(config)?;
    let mut checkpoint = initialize_checkpoint(
        config.model_id.clone(),
        config.hidden_features as usize,
        config.init_seed,
    );
    checkpoint.source_dataset_id = prepared.identity.dataset_id.clone();
    checkpoint.source_dataset_hash = prepared.identity.dataset_hash.clone();
    checkpoint.league_manifest_hash = prepared.identity.league_manifest_hash.clone();
    checkpoint.evaluation_plan_hash = prepared.identity.evaluation_plan_hash.clone();
    checkpoint.evaluation_report_hash = prepared.identity.evaluation_report_hash.clone();
    checkpoint.training_config_hash = config_hash.clone();
    checkpoint.training_contract_version = config.training_contract_version;
    checkpoint.trained_examples = prepared.train_indices.len() as u64;
    checkpoint.validation_examples = prepared.validation_indices.len() as u64;
    checkpoint.validation_seed_modulus = config.validation_seed_modulus;
    checkpoint.validation_seed_remainder = config.validation_seed_remainder;
    checkpoint.epochs = config.epochs;

    let mut model = PolicyValueModelV1::from_checkpoint(checkpoint)?;
    let mut order = prepared.train_indices.clone();
    let train_policy = prepared
        .train_policy_indices
        .iter()
        .copied()
        .collect::<HashSet<_>>();
    let train_value = prepared
        .train_value_indices
        .iter()
        .copied()
        .collect::<HashSet<_>>();
    let mut rng = StableRng::new(config.init_seed ^ 0x6d31_325f_7368_7566);
    for _ in 0..config.epochs {
        stable_shuffle(&mut order, &mut rng);
        for &index in &order {
            train_example(
                &mut model,
                &dataset.examples[index],
                config,
                train_policy.contains(&index),
                train_value.contains(&index),
            )?;
        }
    }
    model.checkpoint().validate()?;
    let checkpoint = model.checkpoint().clone();
    let checkpoint_hash = model_checkpoint_hash_v1(&checkpoint)?;
    let priors = value_priors(dataset, &prepared.train_value_indices)?;
    let train_head_metrics = metrics_by_head(
        &model,
        dataset,
        &prepared.train_policy_indices,
        &prepared.train_value_indices,
    )?;
    let validation_head_metrics = metrics_by_head(
        &model,
        dataset,
        &prepared.validation_policy_indices,
        &prepared.validation_value_indices,
    )?;
    let train_metrics = legacy_metrics(&train_head_metrics, prepared.train_indices.len());
    let validation_metrics =
        legacy_metrics(&validation_head_metrics, prepared.validation_indices.len());
    let validation_comparison = comparison(
        dataset,
        &prepared.validation_policy_indices,
        &prepared.validation_value_indices,
        &validation_metrics,
        &priors,
    )?;
    let material_gate =
        material_gate_from_metrics(config, &validation_metrics, &validation_comparison)?;
    let head_split = config
        .training_contract_version
        .map(|_| prepared.head_split());
    let report = PolicyValueTrainingReportV1 {
        format: POLICY_VALUE_TRAINING_REPORT_FORMAT.into(),
        version: POLICY_VALUE_TRAINING_REPORT_VERSION,
        training_id: config.training_id.clone(),
        model_id: config.model_id.clone(),
        training_config_hash: config_hash,
        checkpoint_hash,
        dataset: prepared.identity,
        split: prepared.split,
        train_metrics,
        validation_metrics,
        validation_comparison,
        head_split,
        train_head_metrics: config.training_contract_version.map(|_| train_head_metrics),
        validation_head_metrics: config
            .training_contract_version
            .map(|_| validation_head_metrics),
        material_gate,
    };
    Ok((checkpoint, report))
}

pub fn evaluate_checkpoint_v1(
    dataset: &TrainingDatasetV1,
    checkpoint: &PolicyValueCheckpointV1,
) -> Result<OfflineEvaluationReportV1, LearningError> {
    checkpoint.validate()?;
    if checkpoint.training_contract_version.is_some() {
        return Err(invalid_checkpoint(
            "source-aware checkpoint requires config-aware offline evaluation",
        ));
    }
    let prepared = PreparedDataset::new(
        dataset,
        checkpoint.validation_seed_modulus,
        checkpoint.validation_seed_remainder,
        &[],
        &[],
    )?;
    if checkpoint.source_dataset_id != prepared.identity.dataset_id
        || checkpoint.source_dataset_hash != prepared.identity.dataset_hash
        || checkpoint.league_manifest_hash != prepared.identity.league_manifest_hash
        || checkpoint.evaluation_plan_hash != prepared.identity.evaluation_plan_hash
        || checkpoint.evaluation_report_hash != prepared.identity.evaluation_report_hash
    {
        return Err(invalid_checkpoint(
            "checkpoint provenance does not match the supplied dataset",
        ));
    }
    if checkpoint.trained_examples != prepared.train_indices.len() as u64
        || checkpoint.validation_examples != prepared.validation_indices.len() as u64
    {
        return Err(invalid_checkpoint(
            "checkpoint split counts do not match the supplied dataset",
        ));
    }
    let model = PolicyValueModelV1::from_checkpoint(checkpoint.clone())?;
    let priors = value_priors(dataset, &prepared.train_value_indices)?;
    let train_head_metrics = metrics_by_head(
        &model,
        dataset,
        &prepared.train_policy_indices,
        &prepared.train_value_indices,
    )?;
    let validation_head_metrics = metrics_by_head(
        &model,
        dataset,
        &prepared.validation_policy_indices,
        &prepared.validation_value_indices,
    )?;
    let train_metrics = legacy_metrics(&train_head_metrics, prepared.train_indices.len());
    let validation_metrics =
        legacy_metrics(&validation_head_metrics, prepared.validation_indices.len());
    let validation_comparison = comparison(
        dataset,
        &prepared.validation_policy_indices,
        &prepared.validation_value_indices,
        &validation_metrics,
        &priors,
    )?;
    Ok(OfflineEvaluationReportV1 {
        format: OFFLINE_EVALUATION_FORMAT.into(),
        version: OFFLINE_EVALUATION_VERSION,
        model_id: checkpoint.model_id.clone(),
        training_config_hash: checkpoint.training_config_hash.clone(),
        checkpoint_hash: model_checkpoint_hash_v1(checkpoint)?,
        dataset: prepared.identity,
        split: prepared.split,
        train_metrics,
        validation_metrics,
        validation_comparison,
        head_split: None,
        train_head_metrics: None,
        validation_head_metrics: None,
        material_gate: None,
    })
}

pub fn evaluate_checkpoint_with_config_v1(
    dataset: &TrainingDatasetV1,
    checkpoint: &PolicyValueCheckpointV1,
    config: &PolicyValueTrainingConfigV1,
) -> Result<OfflineEvaluationReportV1, LearningError> {
    checkpoint.validate()?;
    config.validate()?;
    if checkpoint.training_contract_version != Some(2)
        || config.training_contract_version != Some(2)
        || checkpoint.training_config_hash != training_config_hash_v1(config)?
    {
        return Err(invalid_checkpoint(
            "checkpoint does not match the supplied source-aware config",
        ));
    }
    let prepared = PreparedDataset::new(
        dataset,
        config.validation_seed_modulus,
        config.validation_seed_remainder,
        &config.policy_teacher_agent_ids,
        &config.value_target_agent_ids,
    )?;
    validate_config_binding(config, &prepared.identity)?;
    validate_checkpoint_binding(checkpoint, &prepared)?;
    let model = PolicyValueModelV1::from_checkpoint(checkpoint.clone())?;
    let priors = value_priors(dataset, &prepared.train_value_indices)?;
    let train_head_metrics = metrics_by_head(
        &model,
        dataset,
        &prepared.train_policy_indices,
        &prepared.train_value_indices,
    )?;
    let validation_head_metrics = metrics_by_head(
        &model,
        dataset,
        &prepared.validation_policy_indices,
        &prepared.validation_value_indices,
    )?;
    let train_metrics = legacy_metrics(&train_head_metrics, prepared.train_indices.len());
    let validation_metrics =
        legacy_metrics(&validation_head_metrics, prepared.validation_indices.len());
    let validation_comparison = comparison(
        dataset,
        &prepared.validation_policy_indices,
        &prepared.validation_value_indices,
        &validation_metrics,
        &priors,
    )?;
    let material_gate =
        material_gate_from_metrics(config, &validation_metrics, &validation_comparison)?;
    let head_split = prepared.head_split();
    Ok(OfflineEvaluationReportV1 {
        format: OFFLINE_EVALUATION_FORMAT.into(),
        version: OFFLINE_EVALUATION_VERSION,
        model_id: checkpoint.model_id.clone(),
        training_config_hash: checkpoint.training_config_hash.clone(),
        checkpoint_hash: model_checkpoint_hash_v1(checkpoint)?,
        dataset: prepared.identity,
        split: prepared.split,
        train_metrics,
        validation_metrics,
        validation_comparison,
        head_split: Some(head_split),
        train_head_metrics: Some(train_head_metrics),
        validation_head_metrics: Some(validation_head_metrics),
        material_gate,
    })
}

struct PreparedDataset {
    identity: DatasetIdentityV1,
    split: DatasetSplitV1,
    train_indices: Vec<usize>,
    validation_indices: Vec<usize>,
    train_policy_indices: Vec<usize>,
    validation_policy_indices: Vec<usize>,
    train_value_indices: Vec<usize>,
    validation_value_indices: Vec<usize>,
}

impl PreparedDataset {
    fn new(
        dataset: &TrainingDatasetV1,
        modulus: u32,
        remainder: u32,
        policy_teacher_agent_ids: &[String],
        value_target_agent_ids: &[String],
    ) -> Result<Self, LearningError> {
        if dataset.format != TRAINING_DATASET_FORMAT || dataset.version != TRAINING_DATASET_VERSION
        {
            return Err(invalid_dataset("unsupported dataset format/version"));
        }
        if modulus < 2 || remainder >= modulus {
            return Err(invalid_dataset("invalid source-level split"));
        }
        let dataset_hash = training_dataset_hash_v1(dataset)
            .map_err(|error| invalid_dataset(error.to_string()))?;
        let identity = DatasetIdentityV1 {
            dataset_id: dataset.dataset_id.clone(),
            dataset_hash,
            league_manifest_hash: dataset.league_manifest_hash.clone(),
            evaluation_plan_hash: dataset.evaluation_plan_hash.clone(),
            evaluation_report_hash: dataset.evaluation_report_hash.clone(),
        };
        let mut source_seed = HashMap::new();
        let mut source_agents = HashMap::new();
        let mut dataset_agent_ids = HashSet::new();
        let mut train_replays = 0u64;
        let mut validation_replays = 0u64;
        for replay in &dataset.replays {
            if source_seed
                .insert(replay.source_id.as_str(), replay.seed_index)
                .is_some()
            {
                return Err(invalid_dataset(format!(
                    "duplicate replay source `{}`",
                    replay.source_id
                )));
            }
            source_agents.insert(replay.source_id.as_str(), replay.agents_by_seat.as_slice());
            for agent in &replay.agents_by_seat {
                dataset_agent_ids.insert(agent.league_agent_id.as_str());
            }
            if replay.seed_index % modulus == remainder {
                validation_replays += 1;
            } else {
                train_replays += 1;
            }
        }
        for selected in policy_teacher_agent_ids
            .iter()
            .chain(value_target_agent_ids)
        {
            if !dataset_agent_ids.contains(selected.as_str()) {
                return Err(invalid_dataset(format!(
                    "selected training agent `{selected}` is absent from the dataset"
                )));
            }
        }
        let policy_filter = policy_teacher_agent_ids.iter().collect::<HashSet<_>>();
        let value_filter = value_target_agent_ids.iter().collect::<HashSet<_>>();
        let select_all = policy_filter.is_empty() && value_filter.is_empty();
        let mut train_indices = Vec::new();
        let mut validation_indices = Vec::new();
        let mut train_policy_indices = Vec::new();
        let mut validation_policy_indices = Vec::new();
        let mut train_value_indices = Vec::new();
        let mut validation_value_indices = Vec::new();
        for (index, example) in dataset.examples.iter().enumerate() {
            validate_example(example, &source_seed)?;
            let seed = source_seed[example.source_id.as_str()];
            let (use_policy, use_value) = if select_all {
                (true, true)
            } else {
                let agent = source_agents
                    .get(example.source_id.as_str())
                    .and_then(|agents| agents.get(example.actor.index()))
                    .filter(|agent| agent.seat == example.actor)
                    .ok_or_else(|| {
                        invalid_dataset(format!(
                            "example `{}` ply {} has no bound actor agent identity",
                            example.source_id, example.ply
                        ))
                    })?;
                (
                    policy_filter.contains(&agent.league_agent_id),
                    value_filter.contains(&agent.league_agent_id),
                )
            };
            if !use_policy && !use_value {
                continue;
            }
            let validation = seed % modulus == remainder;
            if validation {
                validation_indices.push(index);
                if use_policy {
                    validation_policy_indices.push(index);
                }
                if use_value {
                    validation_value_indices.push(index);
                }
            } else {
                train_indices.push(index);
                if use_policy {
                    train_policy_indices.push(index);
                }
                if use_value {
                    train_value_indices.push(index);
                }
            }
        }
        if train_replays == 0
            || validation_replays == 0
            || train_indices.is_empty()
            || validation_indices.is_empty()
            || train_policy_indices.is_empty()
            || validation_policy_indices.is_empty()
            || train_value_indices.is_empty()
            || validation_value_indices.is_empty()
        {
            return Err(invalid_dataset(
                "source-level split must produce non-empty train and validation sets",
            ));
        }
        let split = DatasetSplitV1 {
            validation_seed_modulus: modulus,
            validation_seed_remainder: remainder,
            train_replays,
            validation_replays,
            train_examples: train_indices.len() as u64,
            validation_examples: validation_indices.len() as u64,
        };
        Ok(Self {
            identity,
            split,
            train_indices,
            validation_indices,
            train_policy_indices,
            validation_policy_indices,
            train_value_indices,
            validation_value_indices,
        })
    }

    fn head_split(&self) -> HeadDatasetSplitV1 {
        HeadDatasetSplitV1 {
            train_policy_examples: self.train_policy_indices.len() as u64,
            validation_policy_examples: self.validation_policy_indices.len() as u64,
            train_value_examples: self.train_value_indices.len() as u64,
            validation_value_examples: self.validation_value_indices.len() as u64,
        }
    }
}

fn validate_config_binding(
    config: &PolicyValueTrainingConfigV1,
    identity: &DatasetIdentityV1,
) -> Result<(), LearningError> {
    if config.expected_dataset_id != identity.dataset_id
        || config.expected_dataset_hash != identity.dataset_hash
        || config.expected_league_manifest_hash != identity.league_manifest_hash
        || config.expected_evaluation_plan_hash != identity.evaluation_plan_hash
        || config.expected_evaluation_report_hash != identity.evaluation_report_hash
    {
        return Err(invalid_config(
            "expected dataset provenance does not match the supplied dataset",
        ));
    }
    Ok(())
}

fn validate_checkpoint_binding(
    checkpoint: &PolicyValueCheckpointV1,
    prepared: &PreparedDataset,
) -> Result<(), LearningError> {
    if checkpoint.source_dataset_id != prepared.identity.dataset_id
        || checkpoint.source_dataset_hash != prepared.identity.dataset_hash
        || checkpoint.league_manifest_hash != prepared.identity.league_manifest_hash
        || checkpoint.evaluation_plan_hash != prepared.identity.evaluation_plan_hash
        || checkpoint.evaluation_report_hash != prepared.identity.evaluation_report_hash
        || checkpoint.trained_examples != prepared.train_indices.len() as u64
        || checkpoint.validation_examples != prepared.validation_indices.len() as u64
    {
        return Err(invalid_checkpoint(
            "checkpoint provenance/split does not match the source-aware dataset view",
        ));
    }
    Ok(())
}

fn validate_example(
    example: &TrainingExampleV1,
    source_seed: &HashMap<&str, u32>,
) -> Result<(), LearningError> {
    if !source_seed.contains_key(example.source_id.as_str()) {
        return Err(invalid_dataset(format!(
            "example references unknown source `{}`",
            example.source_id
        )));
    }
    let player_count = example.observation.public.player_count as usize;
    if !(2..=MAX_PLAYERS_V1).contains(&player_count)
        || example.actor.index() >= player_count
        || example.observation.viewer != example.actor
        || example.final_scores.len() != player_count
        || example.final_ranks.len() != player_count
    {
        return Err(invalid_dataset(format!(
            "example `{}` ply {} has an invalid player-view/value shape",
            example.source_id, example.ply
        )));
    }
    if example.legal_actions.is_empty() || !example.legal_actions.contains(&example.chosen_action) {
        return Err(invalid_dataset(format!(
            "example `{}` ply {} has an invalid chosen action",
            example.source_id, example.ply
        )));
    }
    encode_observation_v1(&example.observation)?;
    let mut unique_actions = HashSet::new();
    for action in &example.legal_actions {
        encode_action_v1(action)?;
        if !unique_actions.insert(action) {
            return Err(invalid_dataset(format!(
                "example `{}` ply {} has duplicate legal actions",
                example.source_id, example.ply
            )));
        }
    }
    if example
        .final_ranks
        .iter()
        .any(|rank| *rank as usize >= player_count)
    {
        return Err(invalid_dataset(format!(
            "example `{}` ply {} has an out-of-range rank",
            example.source_id, example.ply
        )));
    }
    Ok(())
}

fn train_example(
    model: &mut PolicyValueModelV1,
    example: &TrainingExampleV1,
    config: &PolicyValueTrainingConfigV1,
    update_policy: bool,
    update_value: bool,
) -> Result<(), LearningError> {
    if !update_policy && !update_value {
        return Err(invalid_config("training example has no enabled head"));
    }
    let observation = encode_observation_v1(&example.observation)?;
    let actions = example
        .legal_actions
        .iter()
        .map(encode_action_v1)
        .collect::<Result<Vec<_>, _>>()?;
    let chosen = example
        .legal_actions
        .iter()
        .position(|action| action == &example.chosen_action)
        .ok_or_else(|| invalid_dataset("chosen action disappeared during training"))?;
    let hidden = model.hidden(&observation);
    let probabilities = model.policy_probabilities(&hidden, &actions)?;
    let player_count = example.observation.public.player_count as usize;
    let values = model.values(&hidden, player_count);
    let targets = value_targets(&example.final_ranks, player_count)?;

    let mut d_logits = if update_policy {
        probabilities
    } else {
        vec![0.0; actions.len()]
    };
    if update_policy {
        d_logits[chosen] -= 1.0;
    }
    let mut d_context = vec![0.0f32; ACTION_FEATURES_V1];
    for (coefficient, action) in d_logits.iter().zip(&actions) {
        for (target, feature) in d_context.iter_mut().zip(action) {
            *target += coefficient * feature;
        }
    }
    let hidden_width = hidden.len();
    let mut d_hidden = vec![0.0f32; hidden_width];
    {
        let parameters = &model.checkpoint().parameters;
        if update_policy {
            for (unit, hidden_gradient) in d_hidden.iter_mut().enumerate().take(hidden_width) {
                let row = &parameters.policy_bilinear
                    [unit * ACTION_FEATURES_V1..(unit + 1) * ACTION_FEATURES_V1];
                *hidden_gradient += row
                    .iter()
                    .zip(&d_context)
                    .fold(0.0, |sum, (weight, gradient)| sum + weight * gradient);
            }
        }
        if update_value {
            for player in 0..player_count {
                let error = values[player] - targets[player];
                let d_logit = config.value_loss_weight * 2.0 * error / player_count as f32
                    * values[player]
                    * (1.0 - values[player]);
                let row =
                    &parameters.value_weights[player * hidden_width..(player + 1) * hidden_width];
                for (target, weight) in d_hidden.iter_mut().zip(row) {
                    *target += d_logit * weight;
                }
            }
        }
    }

    let learning_rate = config.learning_rate;
    let l2 = config.l2_weight;
    let parameters = &mut model.checkpoint_mut().parameters;
    if update_policy {
        for (unit, hidden_value) in hidden.iter().enumerate().take(hidden_width) {
            for (feature, context_gradient) in d_context.iter().enumerate() {
                let index = unit * ACTION_FEATURES_V1 + feature;
                let gradient =
                    hidden_value * context_gradient + l2 * parameters.policy_bilinear[index];
                parameters.policy_bilinear[index] -= learning_rate * clip(gradient);
            }
        }
        for (weight, gradient) in parameters.policy_action_bias.iter_mut().zip(&d_context) {
            *weight -= learning_rate * clip(*gradient + l2 * *weight);
        }
    }
    if update_value {
        for player in 0..player_count {
            let error = values[player] - targets[player];
            let d_logit = config.value_loss_weight * 2.0 * error / player_count as f32
                * values[player]
                * (1.0 - values[player]);
            for (unit, hidden_value) in hidden.iter().enumerate().take(hidden_width) {
                let index = player * hidden_width + unit;
                let gradient = d_logit * hidden_value + l2 * parameters.value_weights[index];
                parameters.value_weights[index] -= learning_rate * clip(gradient);
            }
            parameters.value_bias[player] -= learning_rate * clip(d_logit);
        }
    }
    for (unit, observation_gradient) in d_hidden.iter().enumerate().take(hidden_width) {
        let d_pre_activation = observation_gradient * (1.0 - hidden[unit] * hidden[unit]);
        for (feature, observation_value) in observation.iter().enumerate() {
            let index = unit * OBSERVATION_FEATURES_V1 + feature;
            let gradient =
                d_pre_activation * observation_value + l2 * parameters.encoder_weights[index];
            parameters.encoder_weights[index] -= learning_rate * clip(gradient);
        }
        parameters.encoder_bias[unit] -= learning_rate * clip(d_pre_activation);
    }
    Ok(())
}

fn metrics_by_head(
    model: &PolicyValueModelV1,
    dataset: &TrainingDatasetV1,
    policy_indices: &[usize],
    value_indices: &[usize],
) -> Result<HeadOfflineMetricsV1, LearningError> {
    let mut correct = 0u64;
    let mut nll = 0.0f64;
    let mut value_squared_error = 0.0f64;
    let mut value_components = 0u64;
    for &index in policy_indices {
        let example = &dataset.examples[index];
        let prediction = model.predict(&example.observation, &example.legal_actions)?;
        let chosen = example
            .legal_actions
            .iter()
            .position(|action| action == &example.chosen_action)
            .ok_or_else(|| invalid_dataset("chosen action missing while evaluating"))?;
        let best = prediction
            .policy
            .iter()
            .enumerate()
            .max_by(|left, right| {
                left.1
                    .probability
                    .partial_cmp(&right.1.probability)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| right.0.cmp(&left.0))
            })
            .map(|(index, _)| index)
            .ok_or_else(|| invalid_dataset("empty policy prediction"))?;
        if best == chosen {
            correct += 1;
        }
        nll -= f64::from(prediction.policy[chosen].probability.max(1.0e-12)).ln();
    }
    for &index in value_indices {
        let example = &dataset.examples[index];
        let prediction = model.predict(&example.observation, &example.legal_actions)?;
        let targets = value_targets(
            &example.final_ranks,
            example.observation.public.player_count as usize,
        )?;
        for (prediction, target) in prediction.value_by_player.iter().zip(targets) {
            let error = f64::from(*prediction - target);
            value_squared_error += error * error;
            value_components += 1;
        }
    }
    Ok(HeadOfflineMetricsV1 {
        policy_examples: policy_indices.len() as u64,
        policy_top1_accuracy: correct as f64 / policy_indices.len() as f64,
        mean_policy_nll: nll / policy_indices.len() as f64,
        value_examples: value_indices.len() as u64,
        value_components,
        value_mse: value_squared_error / value_components as f64,
    })
}

fn legacy_metrics(metrics: &HeadOfflineMetricsV1, union_examples: usize) -> OfflineMetricsV1 {
    OfflineMetricsV1 {
        examples: union_examples as u64,
        policy_top1_accuracy: metrics.policy_top1_accuracy,
        mean_policy_nll: metrics.mean_policy_nll,
        value_mse: metrics.value_mse,
    }
}

fn value_priors(dataset: &TrainingDatasetV1, indices: &[usize]) -> Result<[f64; 4], LearningError> {
    let mut sums = [0.0f64; 4];
    let mut counts = [0u64; 4];
    for &index in indices {
        let example = &dataset.examples[index];
        let player_count = example.observation.public.player_count as usize;
        for (player, target) in value_targets(&example.final_ranks, player_count)?
            .into_iter()
            .enumerate()
        {
            sums[player] += f64::from(target);
            counts[player] += 1;
        }
    }
    let mut priors = [0.5; 4];
    for player in 0..4 {
        if counts[player] > 0 {
            priors[player] = sums[player] / counts[player] as f64;
        }
    }
    Ok(priors)
}

fn comparison(
    dataset: &TrainingDatasetV1,
    policy_indices: &[usize],
    value_indices: &[usize],
    model_metrics: &OfflineMetricsV1,
    priors: &[f64; 4],
) -> Result<MetricComparisonV1, LearningError> {
    let mut uniform_nll = 0.0;
    let mut prior_squared_error = 0.0;
    let mut components = 0u64;
    for &index in policy_indices {
        let example = &dataset.examples[index];
        uniform_nll += (example.legal_actions.len() as f64).ln();
    }
    for &index in value_indices {
        let example = &dataset.examples[index];
        let player_count = example.observation.public.player_count as usize;
        for (player, target) in value_targets(&example.final_ranks, player_count)?
            .into_iter()
            .enumerate()
        {
            let error = priors[player] - f64::from(target);
            prior_squared_error += error * error;
            components += 1;
        }
    }
    uniform_nll /= policy_indices.len() as f64;
    let prior_mse = prior_squared_error / components as f64;
    let policy_better = model_metrics.mean_policy_nll < uniform_nll;
    let value_better = model_metrics.value_mse < prior_mse;
    Ok(MetricComparisonV1 {
        uniform_policy_mean_nll: uniform_nll,
        train_prior_value_mse: prior_mse,
        policy_nll_beats_uniform: policy_better,
        value_mse_beats_train_prior: value_better,
        outcome: if policy_better && value_better {
            TrainingOutcomeV1::BaselinesBeaten
        } else {
            TrainingOutcomeV1::BaselineNotBeaten
        },
    })
}

fn material_gate_from_metrics(
    config: &PolicyValueTrainingConfigV1,
    metrics: &OfflineMetricsV1,
    comparison: &MetricComparisonV1,
) -> Result<Option<MaterialOfflineGateV1>, LearningError> {
    if config.training_contract_version.is_none() {
        return Ok(None);
    }
    let min_policy = config
        .min_policy_nll_relative_improvement_bps
        .ok_or_else(|| invalid_config("missing Policy material gate"))?;
    let min_value = config
        .min_value_mse_relative_improvement_bps
        .ok_or_else(|| invalid_config("missing Value material gate"))?;
    let actual_policy =
        relative_improvement_bps(comparison.uniform_policy_mean_nll, metrics.mean_policy_nll);
    let actual_value =
        relative_improvement_bps(comparison.train_prior_value_mse, metrics.value_mse);
    let policy_passed = actual_policy >= min_policy;
    let value_passed = actual_value >= min_value;
    Ok(Some(MaterialOfflineGateV1 {
        min_policy_nll_relative_improvement_bps: min_policy,
        actual_policy_nll_relative_improvement_bps: actual_policy,
        policy_passed,
        min_value_mse_relative_improvement_bps: min_value,
        actual_value_mse_relative_improvement_bps: actual_value,
        value_passed,
        passed: policy_passed && value_passed,
    }))
}

fn relative_improvement_bps(baseline: f64, actual: f64) -> u32 {
    if !baseline.is_finite() || !actual.is_finite() || baseline <= 0.0 || actual >= baseline {
        return 0;
    }
    (((baseline - actual) / baseline * 10_000.0).floor() as u64).min(10_000) as u32
}

fn value_targets(ranks: &[u8], player_count: usize) -> Result<Vec<f32>, LearningError> {
    if ranks.len() != player_count || !(2..=MAX_PLAYERS_V1).contains(&player_count) {
        return Err(invalid_dataset(
            "rank target shape does not match player count",
        ));
    }
    let denominator = (player_count - 1) as f32;
    Ok(ranks
        .iter()
        .map(|rank| 1.0 - f32::from(*rank) / denominator)
        .collect())
}

fn domain_hash<T: Serialize>(domain: &[u8], value: &T) -> Result<String, LearningError> {
    let bytes = serde_json::to_vec(value)
        .map_err(|error| LearningError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update(bytes);
    Ok(hex::encode(hasher.finalize()))
}

fn validate_hash(label: &str, value: &str) -> Result<(), LearningError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid_config(format!("{label} is not lowercase SHA-256")));
    }
    Ok(())
}

fn validate_agent_selection(label: &str, values: &[String]) -> Result<(), LearningError> {
    if values.is_empty() {
        return Err(invalid_config(format!("{label} must not be empty")));
    }
    let mut seen = HashSet::new();
    for value in values {
        validate_label(label, value)?;
        if !seen.insert(value) {
            return Err(invalid_config(format!("{label} contains a duplicate")));
        }
    }
    Ok(())
}

fn validate_material_gate(label: &str, value: Option<u32>) -> Result<(), LearningError> {
    if !matches!(value, Some(1..=10_000)) {
        return Err(invalid_config(format!(
            "{label} must be present and in 1..=10000"
        )));
    }
    Ok(())
}

fn validate_label(label: &str, value: &str) -> Result<(), LearningError> {
    if value.trim().is_empty() || value.len() > 128 || value.bytes().any(|byte| byte < 0x20) {
        return Err(invalid_config(format!("{label} is invalid")));
    }
    Ok(())
}

fn clip(value: f32) -> f32 {
    value.clamp(-10.0, 10.0)
}

struct StableRng {
    state: u64,
}

impl StableRng {
    fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9e3779b97f4a7c15);
        let mut value = self.state;
        value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
        value ^ (value >> 31)
    }
}

fn stable_shuffle(values: &mut [usize], rng: &mut StableRng) {
    for index in (1..values.len()).rev() {
        let target = (rng.next_u64() % (index as u64 + 1)) as usize;
        values.swap(index, target);
    }
}

#[cfg(test)]
mod tests {
    use splendor_core::{FullState, GameConfig, PlayerId};
    use splendor_league::{
        TrainingAgentIdentityV1, TrainingDatasetV1, TrainingExampleV1, TrainingReplayV1,
    };

    use super::*;

    fn dataset_and_config() -> (TrainingDatasetV1, PolicyValueTrainingConfigV1) {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let legal = state.legal_actions();
        let observation = state.observation(PlayerId(0));
        let mut dataset = TrainingDatasetV1 {
            format: TRAINING_DATASET_FORMAT.into(),
            version: TRAINING_DATASET_VERSION,
            dataset_id: "unit-dataset".into(),
            league_manifest_hash: "11".repeat(32),
            evaluation_id: "unit-eval".into(),
            evaluation_plan_hash: "22".repeat(32),
            evaluation_report_hash: "33".repeat(32),
            replays: Vec::new(),
            examples: Vec::new(),
        };
        for seed_index in 0..4u32 {
            let source_id = format!("source-{seed_index}");
            dataset.replays.push(TrainingReplayV1 {
                source_id: source_id.clone(),
                evaluation_match_index: seed_index,
                seed_index,
                rotation: 0,
                arena_game_id: format!("game-{seed_index}"),
                arena_report_hash: "44".repeat(32),
                replay_document_hash: format!("{:064x}", seed_index + 5),
                engine_version: "test".into(),
                ruleset_id: "splendor-base-v1".into(),
                ruleset_fingerprint: "55".repeat(32),
                player_count: 2,
                steps: 4,
                final_state_hash: "66".repeat(32),
                result: splendor_replay::ReplayGameResultV1 {
                    scores: vec![16, 12],
                    ranks: vec![0, 1],
                    winners: vec![0],
                    reason: splendor_replay::ReplayTerminalReason::PrestigeThreshold,
                },
                agents_by_seat: vec![
                    TrainingAgentIdentityV1 {
                        seat: PlayerId(0),
                        league_agent_id: if seed_index < 2 {
                            "teacher".into()
                        } else {
                            "rejected".into()
                        },
                        policy_version: "unit-policy".into(),
                        model_version: None,
                        runtime_name: "unit-runtime".into(),
                        runtime_version: "1".into(),
                    },
                    TrainingAgentIdentityV1 {
                        seat: PlayerId(1),
                        league_agent_id: "other-seat".into(),
                        policy_version: "unit-policy".into(),
                        model_version: None,
                        runtime_name: "unit-runtime".into(),
                        runtime_version: "1".into(),
                    },
                ],
            });
            for ply in 0..4u32 {
                let chosen = legal[(seed_index as usize + ply as usize) % legal.len()];
                dataset.examples.push(TrainingExampleV1 {
                    source_id: source_id.clone(),
                    replay_document_hash: format!("{:064x}", seed_index + 5),
                    ply,
                    actor: PlayerId(0),
                    observation_hash: "77".repeat(32),
                    visible_history_hash: "88".repeat(32),
                    information_set_hash: "99".repeat(32),
                    observation: observation.clone(),
                    legal_actions: legal.clone(),
                    chosen_action: chosen,
                    final_scores: vec![16, 12],
                    final_ranks: vec![0, 1],
                });
            }
        }
        let dataset_hash = training_dataset_hash_v1(&dataset).unwrap();
        let config = PolicyValueTrainingConfigV1 {
            format: POLICY_VALUE_TRAINING_CONFIG_FORMAT.into(),
            version: POLICY_VALUE_TRAINING_CONFIG_VERSION,
            training_id: "unit-training".into(),
            model_id: "unit-model".into(),
            expected_dataset_id: dataset.dataset_id.clone(),
            expected_dataset_hash: dataset_hash,
            expected_league_manifest_hash: dataset.league_manifest_hash.clone(),
            expected_evaluation_plan_hash: dataset.evaluation_plan_hash.clone(),
            expected_evaluation_report_hash: dataset.evaluation_report_hash.clone(),
            hidden_features: 4,
            epochs: 2,
            learning_rate: 0.01,
            value_loss_weight: 1.0,
            l2_weight: 0.0,
            init_seed: 17,
            validation_seed_modulus: 2,
            validation_seed_remainder: 0,
            training_contract_version: None,
            policy_teacher_agent_ids: vec![],
            value_target_agent_ids: vec![],
            min_policy_nll_relative_improvement_bps: None,
            min_value_mse_relative_improvement_bps: None,
        };
        (dataset, config)
    }

    #[test]
    fn training_is_deterministic_and_checkpoint_is_evaluable() {
        let (dataset, config) = dataset_and_config();
        let (left, left_report) = train_policy_value_v1(&dataset, &config).unwrap();
        let (right, right_report) = train_policy_value_v1(&dataset, &config).unwrap();
        assert_eq!(left, right);
        assert_eq!(left_report, right_report);
        let evaluation = evaluate_checkpoint_v1(&dataset, &left).unwrap();
        assert_eq!(evaluation.checkpoint_hash, left_report.checkpoint_hash);
        assert_eq!(evaluation.split.train_replays, 2);
        assert_eq!(evaluation.split.validation_replays, 2);
    }

    #[test]
    fn dataset_hash_mismatch_is_rejected() {
        let (dataset, mut config) = dataset_and_config();
        config.expected_dataset_hash = "aa".repeat(32);
        assert!(matches!(
            train_policy_value_v1(&dataset, &config),
            Err(LearningError::InvalidConfig(_))
        ));
    }

    #[test]
    fn source_aware_contract_filters_policy_and_recomputes_exact_gates() {
        let (dataset, mut config) = dataset_and_config();
        config.training_contract_version = Some(2);
        config.policy_teacher_agent_ids = vec!["teacher".into()];
        config.value_target_agent_ids = vec!["teacher".into(), "rejected".into()];
        config.min_policy_nll_relative_improvement_bps = Some(1);
        config.min_value_mse_relative_improvement_bps = Some(1);
        let (checkpoint, report) = train_policy_value_v1(&dataset, &config).unwrap();
        assert_eq!(checkpoint.training_contract_version, Some(2));
        let split = report.head_split.as_ref().unwrap();
        assert_eq!(split.train_policy_examples, 4);
        assert_eq!(split.validation_policy_examples, 4);
        assert_eq!(split.train_value_examples, 8);
        assert_eq!(split.validation_value_examples, 8);
        assert!(report.material_gate.is_some());
        assert!(evaluate_checkpoint_v1(&dataset, &checkpoint).is_err());

        let offline = evaluate_checkpoint_with_config_v1(&dataset, &checkpoint, &config).unwrap();
        assert_eq!(offline.head_split, report.head_split);
        assert_eq!(offline.train_head_metrics, report.train_head_metrics);
        assert_eq!(
            offline.validation_head_metrics,
            report.validation_head_metrics
        );
        assert_eq!(offline.material_gate, report.material_gate);
    }

    #[test]
    fn source_aware_contract_rejects_unknown_or_duplicate_agents() {
        let (dataset, mut config) = dataset_and_config();
        config.training_contract_version = Some(2);
        config.policy_teacher_agent_ids = vec!["missing".into()];
        config.value_target_agent_ids = vec!["teacher".into()];
        config.min_policy_nll_relative_improvement_bps = Some(1);
        config.min_value_mse_relative_improvement_bps = Some(1);
        assert!(matches!(
            train_policy_value_v1(&dataset, &config),
            Err(LearningError::InvalidDataset(message)) if message.contains("absent")
        ));

        config.policy_teacher_agent_ids = vec!["teacher".into(), "teacher".into()];
        assert!(matches!(
            config.validate(),
            Err(LearningError::InvalidConfig(message)) if message.contains("duplicate")
        ));
    }

    #[test]
    fn four_player_value_vector_is_supported() {
        let (mut dataset, mut config) = dataset_and_config();
        let (state, _) = FullState::new(GameConfig {
            player_count: 4,
            ..Default::default()
        })
        .unwrap();
        let observation = state.observation(PlayerId(0));
        let legal = state.legal_actions();
        dataset.replays.clear();
        dataset.examples.clear();
        for seed_index in 0..2u32 {
            let source_id = format!("four-player-{seed_index}");
            let replay_hash = format!("{:064x}", seed_index + 100);
            dataset.replays.push(TrainingReplayV1 {
                source_id: source_id.clone(),
                evaluation_match_index: seed_index,
                seed_index,
                rotation: 0,
                arena_game_id: format!("four-player-game-{seed_index}"),
                arena_report_hash: "aa".repeat(32),
                replay_document_hash: replay_hash.clone(),
                engine_version: "test".into(),
                ruleset_id: "splendor-base-v1".into(),
                ruleset_fingerprint: "bb".repeat(32),
                player_count: 4,
                steps: 1,
                final_state_hash: "cc".repeat(32),
                result: splendor_replay::ReplayGameResultV1 {
                    scores: vec![16, 15, 14, 13],
                    ranks: vec![0, 1, 2, 3],
                    winners: vec![0],
                    reason: splendor_replay::ReplayTerminalReason::PrestigeThreshold,
                },
                agents_by_seat: Vec::new(),
            });
            dataset.examples.push(TrainingExampleV1 {
                source_id,
                replay_document_hash: replay_hash,
                ply: 0,
                actor: PlayerId(0),
                observation_hash: "dd".repeat(32),
                visible_history_hash: "ee".repeat(32),
                information_set_hash: "ff".repeat(32),
                observation: observation.clone(),
                legal_actions: legal.clone(),
                chosen_action: legal[seed_index as usize % legal.len()],
                final_scores: vec![16, 15, 14, 13],
                final_ranks: vec![0, 1, 2, 3],
            });
        }
        config.expected_dataset_hash = training_dataset_hash_v1(&dataset).unwrap();
        let (checkpoint, _) = train_policy_value_v1(&dataset, &config).unwrap();
        let model = PolicyValueModelV1::from_checkpoint(checkpoint).unwrap();
        let prediction = model.predict(&observation, &legal).unwrap();
        assert_eq!(prediction.value_by_player.len(), 4);
    }
}
