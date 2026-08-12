use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_league::{
    training_dataset_hash_v1, TrainingDatasetV1, TrainingExampleV1, TRAINING_DATASET_FORMAT,
    TRAINING_DATASET_VERSION,
};

use crate::error::{invalid_checkpoint, invalid_config, invalid_dataset};
use crate::model::{initialize_checkpoint, initialize_checkpoint_v2};
use crate::{
    encode_action_v1, encode_observation_v1, model_checkpoint_hash_v1, LearningError,
    ModelParametersV1, PolicyValueCheckpointV1, PolicyValueModelV1, SearchTeacherTargetSetV1,
    SearchTeacherTargetV1, ACTION_FEATURES_V1, MAX_PLAYERS_V1, OBSERVATION_FEATURES_V1,
    SEARCH_VALUE_TARGET_SCALE_V1,
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
    /// When false, Value loss may update the Value head but never the shared
    /// encoder. Absent preserves the accepted M12 and first M15B behavior.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value_updates_shared_encoder: Option<bool>,
    /// Required by contract v3. Binds the exact full-search supervision
    /// artifact consumed by both heads.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_search_teacher_targets_hash: Option<String>,
    /// Absent preserves the accepted linear/bilinear M12 architecture.
    /// Version 2 enables the M15D nonlinear action-interaction Policy head and
    /// an independently trainable Value encoder.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_architecture_version: Option<u32>,
    /// Absent preserves deterministic per-example SGD. Version 2 selects the
    /// frozen M15E Adam optimizer (beta1=.9, beta2=.999, epsilon=1e-8).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub optimizer_version: Option<u32>,
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
                    || self.value_updates_shared_encoder.is_some()
                    || self.expected_search_teacher_targets_hash.is_some()
                    || self.model_architecture_version.is_some()
                    || self.optimizer_version.is_some()
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
                if self.expected_search_teacher_targets_hash.is_some() {
                    return Err(invalid_config(
                        "search-teacher hash requires training_contract_version 3",
                    ));
                }
                if self.model_architecture_version.is_some() {
                    return Err(invalid_config(
                        "architecture v2 requires search-teacher contract v3",
                    ));
                }
                if self.optimizer_version.is_some() {
                    return Err(invalid_config(
                        "optimizer v2 requires search-teacher contract v3",
                    ));
                }
            }
            Some(3) => {
                validate_agent_selection(
                    "policy_teacher_agent_ids",
                    &self.policy_teacher_agent_ids,
                )?;
                validate_agent_selection("value_target_agent_ids", &self.value_target_agent_ids)?;
                if self.policy_teacher_agent_ids != self.value_target_agent_ids {
                    return Err(invalid_config(
                        "contract v3 requires identical Policy and Value teacher agents",
                    ));
                }
                validate_material_gate(
                    "min_policy_nll_relative_improvement_bps",
                    self.min_policy_nll_relative_improvement_bps,
                )?;
                validate_material_gate(
                    "min_value_mse_relative_improvement_bps",
                    self.min_value_mse_relative_improvement_bps,
                )?;
                validate_hash(
                    "expected_search_teacher_targets_hash",
                    self.expected_search_teacher_targets_hash
                        .as_deref()
                        .ok_or_else(|| {
                            invalid_config("contract v3 requires search-teacher target hash")
                        })?,
                )?;
                if self
                    .model_architecture_version
                    .is_some_and(|version| version != 2)
                {
                    return Err(invalid_config(
                        "model_architecture_version must be absent or 2",
                    ));
                }
                if self.model_architecture_version == Some(2)
                    && self.value_updates_shared_encoder != Some(false)
                {
                    return Err(invalid_config(
                        "architecture v2 requires isolated Policy/Value encoders",
                    ));
                }
                if self.optimizer_version.is_some_and(|version| version != 2) {
                    return Err(invalid_config("optimizer_version must be absent or 2"));
                }
                if self.optimizer_version == Some(2) && self.model_architecture_version != Some(2) {
                    return Err(invalid_config(
                        "optimizer v2 requires model architecture v2",
                    ));
                }
            }
            Some(_) => {
                return Err(invalid_config(
                    "training_contract_version must be absent, 2, or 3",
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value_updates_shared_encoder: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub search_teacher_targets_hash: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_architecture_version: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub optimizer_version: Option<u32>,
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value_updates_shared_encoder: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub search_teacher_targets_hash: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_architecture_version: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub optimizer_version: Option<u32>,
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
    if config.training_contract_version == Some(3) {
        return Err(invalid_config(
            "contract v3 requires train_policy_value_with_search_targets_v1",
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
    let config_hash = training_config_hash_v1(config)?;
    let mut checkpoint = if config.model_architecture_version == Some(2) {
        initialize_checkpoint_v2(
            config.model_id.clone(),
            config.hidden_features as usize,
            config.init_seed,
        )
    } else {
        initialize_checkpoint(
            config.model_id.clone(),
            config.hidden_features as usize,
            config.init_seed,
        )
    };
    checkpoint.source_dataset_id = prepared.identity.dataset_id.clone();
    checkpoint.source_dataset_hash = prepared.identity.dataset_hash.clone();
    checkpoint.league_manifest_hash = prepared.identity.league_manifest_hash.clone();
    checkpoint.evaluation_plan_hash = prepared.identity.evaluation_plan_hash.clone();
    checkpoint.evaluation_report_hash = prepared.identity.evaluation_report_hash.clone();
    checkpoint.training_config_hash = config_hash.clone();
    checkpoint.training_contract_version = config.training_contract_version;
    checkpoint.search_teacher_targets_hash = None;
    checkpoint.optimizer_version = None;
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
        value_updates_shared_encoder: config.value_updates_shared_encoder,
        search_teacher_targets_hash: None,
        model_architecture_version: None,
        optimizer_version: None,
    };
    Ok((checkpoint, report))
}

pub fn train_policy_value_with_search_targets_v1(
    dataset: &TrainingDatasetV1,
    targets: &SearchTeacherTargetSetV1,
    config: &PolicyValueTrainingConfigV1,
) -> Result<(PolicyValueCheckpointV1, PolicyValueTrainingReportV1), LearningError> {
    config.validate()?;
    if config.training_contract_version != Some(3) {
        return Err(invalid_config(
            "search-teacher training requires training_contract_version 3",
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
    let target_hash = validate_search_targets(dataset, targets, config, &prepared)?;
    let targets_by_example = search_targets_by_example(dataset, targets, &prepared)?;
    let config_hash = training_config_hash_v1(config)?;
    let mut checkpoint = if config.model_architecture_version == Some(2) {
        initialize_checkpoint_v2(
            config.model_id.clone(),
            config.hidden_features as usize,
            config.init_seed,
        )
    } else {
        initialize_checkpoint(
            config.model_id.clone(),
            config.hidden_features as usize,
            config.init_seed,
        )
    };
    checkpoint.source_dataset_id = prepared.identity.dataset_id.clone();
    checkpoint.source_dataset_hash = prepared.identity.dataset_hash.clone();
    checkpoint.league_manifest_hash = prepared.identity.league_manifest_hash.clone();
    checkpoint.evaluation_plan_hash = prepared.identity.evaluation_plan_hash.clone();
    checkpoint.evaluation_report_hash = prepared.identity.evaluation_report_hash.clone();
    checkpoint.training_config_hash = config_hash.clone();
    checkpoint.training_contract_version = Some(3);
    checkpoint.search_teacher_targets_hash = Some(target_hash.clone());
    checkpoint.optimizer_version = config.optimizer_version;
    checkpoint.trained_examples = prepared.train_indices.len() as u64;
    checkpoint.validation_examples = prepared.validation_indices.len() as u64;
    checkpoint.validation_seed_modulus = config.validation_seed_modulus;
    checkpoint.validation_seed_remainder = config.validation_seed_remainder;
    checkpoint.epochs = config.epochs;

    let mut model = PolicyValueModelV1::from_checkpoint(checkpoint)?;
    let mut optimizer = config
        .optimizer_version
        .map(|_| AdamOptimizerV2::new(&model.checkpoint().parameters));
    let mut order = prepared.train_indices.clone();
    let mut rng = StableRng::new(config.init_seed ^ 0x6d31_3563_736f_6674);
    for _ in 0..config.epochs {
        stable_shuffle(&mut order, &mut rng);
        for &index in &order {
            train_search_target(
                &mut model,
                &dataset.examples[index],
                targets_by_example[index]
                    .ok_or_else(|| invalid_dataset("missing bound search target"))?,
                config,
                optimizer.as_mut(),
            )?;
        }
    }
    model.checkpoint().validate()?;
    let checkpoint = model.checkpoint().clone();
    let checkpoint_hash = model_checkpoint_hash_v1(&checkpoint)?;
    let priors = search_value_priors(&prepared.train_indices, &targets_by_example)?;
    let train_head_metrics = search_metrics(
        &model,
        dataset,
        &prepared.train_indices,
        &targets_by_example,
    )?;
    let validation_head_metrics = search_metrics(
        &model,
        dataset,
        &prepared.validation_indices,
        &targets_by_example,
    )?;
    let train_metrics = legacy_metrics(&train_head_metrics, prepared.train_indices.len());
    let validation_metrics =
        legacy_metrics(&validation_head_metrics, prepared.validation_indices.len());
    let validation_comparison = search_comparison(
        dataset,
        &prepared.validation_indices,
        &targets_by_example,
        &validation_metrics,
        &priors,
    )?;
    let material_gate =
        material_gate_from_metrics(config, &validation_metrics, &validation_comparison)?;
    let head_split = prepared.head_split();
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
        head_split: Some(head_split),
        train_head_metrics: Some(train_head_metrics),
        validation_head_metrics: Some(validation_head_metrics),
        material_gate,
        value_updates_shared_encoder: config.value_updates_shared_encoder,
        search_teacher_targets_hash: Some(target_hash),
        model_architecture_version: config.model_architecture_version,
        optimizer_version: config.optimizer_version,
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
        value_updates_shared_encoder: None,
        search_teacher_targets_hash: None,
        model_architecture_version: None,
        optimizer_version: None,
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
        value_updates_shared_encoder: config.value_updates_shared_encoder,
        search_teacher_targets_hash: None,
        model_architecture_version: None,
        optimizer_version: None,
    })
}

pub fn evaluate_checkpoint_with_search_targets_v1(
    dataset: &TrainingDatasetV1,
    targets: &SearchTeacherTargetSetV1,
    checkpoint: &PolicyValueCheckpointV1,
    config: &PolicyValueTrainingConfigV1,
) -> Result<OfflineEvaluationReportV1, LearningError> {
    checkpoint.validate()?;
    config.validate()?;
    if checkpoint.training_contract_version != Some(3)
        || config.training_contract_version != Some(3)
        || checkpoint.model_architecture_version != config.model_architecture_version
        || checkpoint.optimizer_version != config.optimizer_version
        || checkpoint.training_config_hash != training_config_hash_v1(config)?
    {
        return Err(invalid_checkpoint(
            "checkpoint does not match the supplied search-teacher config",
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
    let target_hash = validate_search_targets(dataset, targets, config, &prepared)?;
    if checkpoint.search_teacher_targets_hash.as_deref() != Some(target_hash.as_str()) {
        return Err(invalid_checkpoint(
            "checkpoint does not bind the supplied search-teacher targets",
        ));
    }
    let targets_by_example = search_targets_by_example(dataset, targets, &prepared)?;
    let model = PolicyValueModelV1::from_checkpoint(checkpoint.clone())?;
    let priors = search_value_priors(&prepared.train_indices, &targets_by_example)?;
    let train_head_metrics = search_metrics(
        &model,
        dataset,
        &prepared.train_indices,
        &targets_by_example,
    )?;
    let validation_head_metrics = search_metrics(
        &model,
        dataset,
        &prepared.validation_indices,
        &targets_by_example,
    )?;
    let train_metrics = legacy_metrics(&train_head_metrics, prepared.train_indices.len());
    let validation_metrics =
        legacy_metrics(&validation_head_metrics, prepared.validation_indices.len());
    let validation_comparison = search_comparison(
        dataset,
        &prepared.validation_indices,
        &targets_by_example,
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
        value_updates_shared_encoder: config.value_updates_shared_encoder,
        search_teacher_targets_hash: Some(target_hash),
        model_architecture_version: config.model_architecture_version,
        optimizer_version: config.optimizer_version,
    })
}

fn validate_search_targets(
    dataset: &TrainingDatasetV1,
    targets: &SearchTeacherTargetSetV1,
    config: &PolicyValueTrainingConfigV1,
    prepared: &PreparedDataset,
) -> Result<String, LearningError> {
    targets.validate()?;
    let hash = crate::search_teacher_targets_hash_v1(targets)?;
    if config.expected_search_teacher_targets_hash.as_deref() != Some(hash.as_str()) {
        return Err(invalid_config(
            "expected search-teacher hash does not match supplied targets",
        ));
    }
    if targets.dataset_id != dataset.dataset_id
        || targets.dataset_hash != prepared.identity.dataset_hash
        || targets.league_manifest_hash != dataset.league_manifest_hash
        || targets.evaluation_plan_hash != dataset.evaluation_plan_hash
        || targets.evaluation_report_hash != dataset.evaluation_report_hash
        || targets.teacher_agent_ids != config.policy_teacher_agent_ids
    {
        return Err(invalid_dataset(
            "search-teacher targets do not match dataset/config provenance",
        ));
    }
    let selected = prepared.train_indices.len() + prepared.validation_indices.len();
    if targets.targets.len() != selected {
        return Err(invalid_dataset(
            "search-teacher targets do not exactly cover selected examples",
        ));
    }
    Ok(hash)
}

fn search_targets_by_example<'a>(
    dataset: &TrainingDatasetV1,
    targets: &'a SearchTeacherTargetSetV1,
    prepared: &PreparedDataset,
) -> Result<Vec<Option<&'a SearchTeacherTargetV1>>, LearningError> {
    let mut examples = HashMap::new();
    for (index, example) in dataset.examples.iter().enumerate() {
        if examples
            .insert((example.source_id.as_str(), example.ply), index)
            .is_some()
        {
            return Err(invalid_dataset("duplicate dataset source_id/ply"));
        }
    }
    let selected = prepared
        .train_indices
        .iter()
        .chain(&prepared.validation_indices)
        .copied()
        .collect::<HashSet<_>>();
    let mut bound = vec![None; dataset.examples.len()];
    for target in &targets.targets {
        let index = examples
            .get(&(target.source_id.as_str(), target.ply))
            .copied()
            .ok_or_else(|| invalid_dataset("search target references unknown example"))?;
        if !selected.contains(&index) || bound[index].is_some() {
            return Err(invalid_dataset(
                "search target is duplicated or outside selected examples",
            ));
        }
        let example = &dataset.examples[index];
        if target.replay_document_hash != example.replay_document_hash
            || target.actor != example.actor
            || target.observation_hash != example.observation_hash
            || target.visible_history_hash != example.visible_history_hash
            || target.information_set_hash != example.information_set_hash
            || target.recorded_action != example.chosen_action
            || target
                .action_targets
                .iter()
                .map(|entry| entry.action)
                .ne(example.legal_actions.iter().copied())
        {
            return Err(invalid_dataset(
                "search target does not bind the exact dataset example",
            ));
        }
        bound[index] = Some(target);
    }
    if selected.iter().any(|index| bound[*index].is_none()) {
        return Err(invalid_dataset(
            "selected dataset example lacks a search target",
        ));
    }
    Ok(bound)
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
    let value_updates_shared_encoder = config.value_updates_shared_encoder.unwrap_or(true);

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
        if update_value && value_updates_shared_encoder {
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
    if update_policy || (update_value && value_updates_shared_encoder) {
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
    }
    Ok(())
}

struct AdamSlotV2 {
    first: Vec<f32>,
    second: Vec<f32>,
}

impl AdamSlotV2 {
    fn new(length: usize) -> Self {
        Self {
            first: vec![0.0; length],
            second: vec![0.0; length],
        }
    }
}

struct AdamOptimizerV2 {
    beta1_power: f32,
    beta2_power: f32,
    encoder_weights: AdamSlotV2,
    encoder_bias: AdamSlotV2,
    policy_bilinear: AdamSlotV2,
    policy_action_bias: AdamSlotV2,
    policy_hidden_bias: AdamSlotV2,
    policy_output_weights: AdamSlotV2,
    value_weights: AdamSlotV2,
    value_bias: AdamSlotV2,
    value_encoder_weights: AdamSlotV2,
    value_encoder_bias: AdamSlotV2,
}

impl AdamOptimizerV2 {
    fn new(parameters: &ModelParametersV1) -> Self {
        Self {
            beta1_power: 1.0,
            beta2_power: 1.0,
            encoder_weights: AdamSlotV2::new(parameters.encoder_weights.len()),
            encoder_bias: AdamSlotV2::new(parameters.encoder_bias.len()),
            policy_bilinear: AdamSlotV2::new(parameters.policy_bilinear.len()),
            policy_action_bias: AdamSlotV2::new(parameters.policy_action_bias.len()),
            policy_hidden_bias: AdamSlotV2::new(parameters.policy_hidden_bias.len()),
            policy_output_weights: AdamSlotV2::new(parameters.policy_output_weights.len()),
            value_weights: AdamSlotV2::new(parameters.value_weights.len()),
            value_bias: AdamSlotV2::new(parameters.value_bias.len()),
            value_encoder_weights: AdamSlotV2::new(parameters.value_encoder_weights.len()),
            value_encoder_bias: AdamSlotV2::new(parameters.value_encoder_bias.len()),
        }
    }

    fn advance(&mut self) -> (f32, f32) {
        self.beta1_power *= 0.9;
        self.beta2_power *= 0.999;
        (1.0 - self.beta1_power, 1.0 - self.beta2_power)
    }
}

fn train_search_target(
    model: &mut PolicyValueModelV1,
    example: &TrainingExampleV1,
    target: &SearchTeacherTargetV1,
    config: &PolicyValueTrainingConfigV1,
    optimizer: Option<&mut AdamOptimizerV2>,
) -> Result<(), LearningError> {
    if model.checkpoint().model_architecture_version == Some(2) {
        return train_search_target_v2(model, example, target, config, optimizer);
    }
    if optimizer.is_some() {
        return Err(invalid_config(
            "optimizer v2 requires model architecture v2",
        ));
    }
    let observation = encode_observation_v1(&example.observation)?;
    let actions = example
        .legal_actions
        .iter()
        .map(encode_action_v1)
        .collect::<Result<Vec<_>, _>>()?;
    if target.action_targets.len() != actions.len() {
        return Err(invalid_dataset("search Policy target shape changed"));
    }
    let hidden = model.hidden(&observation);
    let probabilities = model.policy_probabilities(&hidden, &actions)?;
    let player_count = example.observation.public.player_count as usize;
    if target.value_target_by_player_micros.len() != player_count {
        return Err(invalid_dataset("search Value target shape changed"));
    }
    let values = model.values(&hidden, player_count);
    let value_targets = target
        .value_target_by_player_micros
        .iter()
        .map(|value| *value as f32 / SEARCH_VALUE_TARGET_SCALE_V1 as f32)
        .collect::<Vec<_>>();
    let mut d_logits = probabilities;
    for (gradient, target) in d_logits.iter_mut().zip(&target.action_targets) {
        *gradient -= target.policy_target_micros as f32 / SEARCH_VALUE_TARGET_SCALE_V1 as f32;
    }
    let mut d_context = vec![0.0f32; ACTION_FEATURES_V1];
    for (coefficient, action) in d_logits.iter().zip(&actions) {
        for (slot, feature) in d_context.iter_mut().zip(action) {
            *slot += coefficient * feature;
        }
    }
    let hidden_width = hidden.len();
    let mut d_hidden = vec![0.0f32; hidden_width];
    let value_updates_shared_encoder = config.value_updates_shared_encoder.unwrap_or(true);
    {
        let parameters = &model.checkpoint().parameters;
        for (unit, hidden_gradient) in d_hidden.iter_mut().enumerate().take(hidden_width) {
            let row = &parameters.policy_bilinear
                [unit * ACTION_FEATURES_V1..(unit + 1) * ACTION_FEATURES_V1];
            *hidden_gradient += row
                .iter()
                .zip(&d_context)
                .fold(0.0, |sum, (weight, gradient)| sum + weight * gradient);
        }
        if value_updates_shared_encoder {
            for player in 0..player_count {
                let error = values[player] - value_targets[player];
                let d_logit = config.value_loss_weight * 2.0 * error / player_count as f32
                    * values[player]
                    * (1.0 - values[player]);
                let row =
                    &parameters.value_weights[player * hidden_width..(player + 1) * hidden_width];
                for (slot, weight) in d_hidden.iter_mut().zip(row) {
                    *slot += d_logit * weight;
                }
            }
        }
    }

    let learning_rate = config.learning_rate;
    let l2 = config.l2_weight;
    let parameters = &mut model.checkpoint_mut().parameters;
    for (unit, hidden_value) in hidden.iter().enumerate().take(hidden_width) {
        for (feature, context_gradient) in d_context.iter().enumerate() {
            let index = unit * ACTION_FEATURES_V1 + feature;
            let gradient = hidden_value * context_gradient + l2 * parameters.policy_bilinear[index];
            parameters.policy_bilinear[index] -= learning_rate * clip(gradient);
        }
    }
    for (weight, gradient) in parameters.policy_action_bias.iter_mut().zip(&d_context) {
        *weight -= learning_rate * clip(*gradient + l2 * *weight);
    }
    for player in 0..player_count {
        let error = values[player] - value_targets[player];
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

fn train_search_target_v2(
    model: &mut PolicyValueModelV1,
    example: &TrainingExampleV1,
    target: &SearchTeacherTargetV1,
    config: &PolicyValueTrainingConfigV1,
    optimizer: Option<&mut AdamOptimizerV2>,
) -> Result<(), LearningError> {
    let observation = encode_observation_v1(&example.observation)?;
    let actions = example
        .legal_actions
        .iter()
        .map(encode_action_v1)
        .collect::<Result<Vec<_>, _>>()?;
    if target.action_targets.len() != actions.len() {
        return Err(invalid_dataset("search Policy target shape changed"));
    }
    let policy_hidden = model.hidden(&observation);
    let probabilities = model.policy_probabilities(&policy_hidden, &actions)?;
    let value_hidden = model.value_hidden(&observation);
    let player_count = example.observation.public.player_count as usize;
    if target.value_target_by_player_micros.len() != player_count {
        return Err(invalid_dataset("search Value target shape changed"));
    }
    let values = model.values(&value_hidden, player_count);
    let value_targets = target
        .value_target_by_player_micros
        .iter()
        .map(|value| *value as f32 / SEARCH_VALUE_TARGET_SCALE_V1 as f32)
        .collect::<Vec<_>>();
    let mut d_logits = probabilities;
    for (gradient, desired) in d_logits.iter_mut().zip(&target.action_targets) {
        *gradient -= desired.policy_target_micros as f32 / SEARCH_VALUE_TARGET_SCALE_V1 as f32;
    }

    let hidden_width = policy_hidden.len();
    let mut d_policy_hidden = vec![0.0f32; hidden_width];
    let mut d_policy_bilinear = vec![0.0f32; hidden_width * ACTION_FEATURES_V1];
    let mut d_policy_action_bias = vec![0.0f32; ACTION_FEATURES_V1];
    let mut d_policy_hidden_bias = vec![0.0f32; hidden_width];
    let mut d_policy_output = vec![0.0f32; hidden_width];
    {
        let parameters = &model.checkpoint().parameters;
        for ((action, d_logit), _) in actions.iter().zip(&d_logits).zip(&target.action_targets) {
            for (slot, feature) in d_policy_action_bias.iter_mut().zip(action) {
                *slot += d_logit * feature;
            }
            for unit in 0..hidden_width {
                let row = &parameters.policy_bilinear
                    [unit * ACTION_FEATURES_V1..(unit + 1) * ACTION_FEATURES_V1];
                let pre = row.iter().zip(action).fold(
                    policy_hidden[unit] + parameters.policy_hidden_bias[unit],
                    |sum, (weight, feature)| sum + weight * feature,
                );
                let action_hidden = pre.tanh();
                d_policy_output[unit] += d_logit * action_hidden;
                let d_pre = d_logit
                    * parameters.policy_output_weights[unit]
                    * (1.0 - action_hidden * action_hidden);
                d_policy_hidden[unit] += d_pre;
                d_policy_hidden_bias[unit] += d_pre;
                for (feature, value) in action.iter().enumerate() {
                    d_policy_bilinear[unit * ACTION_FEATURES_V1 + feature] += d_pre * value;
                }
            }
        }
    }

    let mut d_value_hidden = vec![0.0f32; hidden_width];
    let mut d_value_weights = vec![0.0f32; MAX_PLAYERS_V1 * hidden_width];
    let mut d_value_bias = [0.0f32; MAX_PLAYERS_V1];
    {
        let parameters = &model.checkpoint().parameters;
        for player in 0..player_count {
            let error = values[player] - value_targets[player];
            let d_logit = config.value_loss_weight * 2.0 * error / player_count as f32
                * values[player]
                * (1.0 - values[player]);
            d_value_bias[player] = d_logit;
            for unit in 0..hidden_width {
                let index = player * hidden_width + unit;
                d_value_weights[index] = d_logit * value_hidden[unit];
                d_value_hidden[unit] += d_logit * parameters.value_weights[index];
            }
        }
    }

    let mut d_encoder_weights = vec![0.0f32; hidden_width * OBSERVATION_FEATURES_V1];
    let mut d_encoder_bias = vec![0.0f32; hidden_width];
    for unit in 0..hidden_width {
        let d_pre = d_policy_hidden[unit] * (1.0 - policy_hidden[unit] * policy_hidden[unit]);
        d_encoder_bias[unit] = d_pre;
        for (feature, value) in observation.iter().enumerate() {
            let index = unit * OBSERVATION_FEATURES_V1 + feature;
            d_encoder_weights[index] = d_pre * value;
        }
    }
    let mut d_value_encoder_weights = vec![0.0f32; hidden_width * OBSERVATION_FEATURES_V1];
    let mut d_value_encoder_bias = vec![0.0f32; hidden_width];
    for unit in 0..hidden_width {
        let d_pre = d_value_hidden[unit] * (1.0 - value_hidden[unit] * value_hidden[unit]);
        d_value_encoder_bias[unit] = d_pre;
        for (feature, value) in observation.iter().enumerate() {
            let index = unit * OBSERVATION_FEATURES_V1 + feature;
            d_value_encoder_weights[index] = d_pre * value;
        }
    }

    let learning_rate = config.learning_rate;
    let l2 = config.l2_weight;
    let parameters = &mut model.checkpoint_mut().parameters;
    if let Some(optimizer) = optimizer {
        let (correction1, correction2) = optimizer.advance();
        apply_adam_v2(
            &mut parameters.encoder_weights,
            &d_encoder_weights,
            l2,
            &mut optimizer.encoder_weights,
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.encoder_bias,
            &d_encoder_bias,
            0.0,
            &mut optimizer.encoder_bias,
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.policy_bilinear,
            &d_policy_bilinear,
            l2,
            &mut optimizer.policy_bilinear,
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.policy_action_bias,
            &d_policy_action_bias,
            l2,
            &mut optimizer.policy_action_bias,
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.policy_hidden_bias,
            &d_policy_hidden_bias,
            0.0,
            &mut optimizer.policy_hidden_bias,
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.policy_output_weights,
            &d_policy_output,
            l2,
            &mut optimizer.policy_output_weights,
            learning_rate,
            correction1,
            correction2,
        );
        let active_value = player_count * hidden_width;
        apply_adam_v2(
            &mut parameters.value_weights[..active_value],
            &d_value_weights[..active_value],
            l2,
            &mut optimizer.value_weights.slice_mut(active_value),
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.value_bias[..player_count],
            &d_value_bias[..player_count],
            0.0,
            &mut optimizer.value_bias.slice_mut(player_count),
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.value_encoder_weights,
            &d_value_encoder_weights,
            l2,
            &mut optimizer.value_encoder_weights,
            learning_rate,
            correction1,
            correction2,
        );
        apply_adam_v2(
            &mut parameters.value_encoder_bias,
            &d_value_encoder_bias,
            0.0,
            &mut optimizer.value_encoder_bias,
            learning_rate,
            correction1,
            correction2,
        );
    } else {
        apply_sgd_v1(
            &mut parameters.encoder_weights,
            &d_encoder_weights,
            l2,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.encoder_bias,
            &d_encoder_bias,
            0.0,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.policy_bilinear,
            &d_policy_bilinear,
            l2,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.policy_action_bias,
            &d_policy_action_bias,
            l2,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.policy_hidden_bias,
            &d_policy_hidden_bias,
            0.0,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.policy_output_weights,
            &d_policy_output,
            l2,
            learning_rate,
        );
        let active_value = player_count * hidden_width;
        apply_sgd_v1(
            &mut parameters.value_weights[..active_value],
            &d_value_weights[..active_value],
            l2,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.value_bias[..player_count],
            &d_value_bias[..player_count],
            0.0,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.value_encoder_weights,
            &d_value_encoder_weights,
            l2,
            learning_rate,
        );
        apply_sgd_v1(
            &mut parameters.value_encoder_bias,
            &d_value_encoder_bias,
            0.0,
            learning_rate,
        );
    }
    Ok(())
}

impl AdamSlotV2 {
    fn slice_mut(&mut self, length: usize) -> AdamSlotSliceMutV2<'_> {
        AdamSlotSliceMutV2 {
            first: &mut self.first[..length],
            second: &mut self.second[..length],
        }
    }
}

struct AdamSlotSliceMutV2<'a> {
    first: &'a mut [f32],
    second: &'a mut [f32],
}

fn apply_sgd_v1(parameters: &mut [f32], gradients: &[f32], l2: f32, learning_rate: f32) {
    debug_assert_eq!(parameters.len(), gradients.len());
    for (parameter, gradient) in parameters.iter_mut().zip(gradients) {
        *parameter -= learning_rate * clip(*gradient + l2 * *parameter);
    }
}

fn apply_adam_v2(
    parameters: &mut [f32],
    gradients: &[f32],
    l2: f32,
    slot: &mut impl AdamMomentSlicesV2,
    learning_rate: f32,
    correction1: f32,
    correction2: f32,
) {
    let (first, second) = slot.moments();
    debug_assert_eq!(parameters.len(), gradients.len());
    debug_assert_eq!(parameters.len(), first.len());
    debug_assert_eq!(parameters.len(), second.len());
    for (((parameter, gradient), first), second) in
        parameters.iter_mut().zip(gradients).zip(first).zip(second)
    {
        let gradient = clip(*gradient + l2 * *parameter);
        *first = 0.9 * *first + 0.1 * gradient;
        *second = 0.999 * *second + 0.001 * gradient * gradient;
        let first_hat = *first / correction1;
        let second_hat = *second / correction2;
        *parameter -= learning_rate * first_hat / (second_hat.sqrt() + 1.0e-8);
    }
}

trait AdamMomentSlicesV2 {
    fn moments(&mut self) -> (&mut [f32], &mut [f32]);
}

impl AdamMomentSlicesV2 for AdamSlotV2 {
    fn moments(&mut self) -> (&mut [f32], &mut [f32]) {
        (&mut self.first, &mut self.second)
    }
}

impl AdamMomentSlicesV2 for AdamSlotSliceMutV2<'_> {
    fn moments(&mut self) -> (&mut [f32], &mut [f32]) {
        (self.first, self.second)
    }
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

fn search_metrics(
    model: &PolicyValueModelV1,
    dataset: &TrainingDatasetV1,
    indices: &[usize],
    targets_by_example: &[Option<&SearchTeacherTargetV1>],
) -> Result<HeadOfflineMetricsV1, LearningError> {
    let mut correct = 0u64;
    let mut cross_entropy = 0.0f64;
    let mut value_squared_error = 0.0f64;
    let mut value_components = 0u64;
    for &index in indices {
        let example = &dataset.examples[index];
        let target = targets_by_example[index]
            .ok_or_else(|| invalid_dataset("missing search target while evaluating"))?;
        let prediction = model.predict(&example.observation, &example.legal_actions)?;
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
            .map(|(position, _)| position)
            .ok_or_else(|| invalid_dataset("empty search Policy prediction"))?;
        if prediction.policy[best].action == target.teacher_action {
            correct += 1;
        }
        for (predicted, desired) in prediction.policy.iter().zip(&target.action_targets) {
            let mass = desired.policy_target_micros as f64 / SEARCH_VALUE_TARGET_SCALE_V1 as f64;
            cross_entropy -= mass * f64::from(predicted.probability.max(1.0e-12)).ln();
        }
        for (predicted, desired) in prediction
            .value_by_player
            .iter()
            .zip(&target.value_target_by_player_micros)
        {
            let desired = *desired as f64 / SEARCH_VALUE_TARGET_SCALE_V1 as f64;
            let error = f64::from(*predicted) - desired;
            value_squared_error += error * error;
            value_components += 1;
        }
    }
    Ok(HeadOfflineMetricsV1 {
        policy_examples: indices.len() as u64,
        policy_top1_accuracy: correct as f64 / indices.len() as f64,
        mean_policy_nll: cross_entropy / indices.len() as f64,
        value_examples: indices.len() as u64,
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

fn search_value_priors(
    indices: &[usize],
    targets_by_example: &[Option<&SearchTeacherTargetV1>],
) -> Result<[f64; 4], LearningError> {
    let mut sums = [0.0f64; 4];
    let mut counts = [0u64; 4];
    for &index in indices {
        let target = targets_by_example[index]
            .ok_or_else(|| invalid_dataset("missing search target for Value prior"))?;
        for (player, value) in target.value_target_by_player_micros.iter().enumerate() {
            sums[player] += *value as f64 / SEARCH_VALUE_TARGET_SCALE_V1 as f64;
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

fn search_comparison(
    dataset: &TrainingDatasetV1,
    indices: &[usize],
    targets_by_example: &[Option<&SearchTeacherTargetV1>],
    model_metrics: &OfflineMetricsV1,
    priors: &[f64; 4],
) -> Result<MetricComparisonV1, LearningError> {
    let mut uniform_cross_entropy = 0.0;
    let mut prior_squared_error = 0.0;
    let mut components = 0u64;
    for &index in indices {
        let example = &dataset.examples[index];
        let target = targets_by_example[index]
            .ok_or_else(|| invalid_dataset("missing search target for comparison"))?;
        uniform_cross_entropy += (example.legal_actions.len() as f64).ln();
        for (player, value) in target.value_target_by_player_micros.iter().enumerate() {
            let desired = *value as f64 / SEARCH_VALUE_TARGET_SCALE_V1 as f64;
            let error = priors[player] - desired;
            prior_squared_error += error * error;
            components += 1;
        }
    }
    uniform_cross_entropy /= indices.len() as f64;
    let prior_mse = prior_squared_error / components as f64;
    let policy_better = model_metrics.mean_policy_nll < uniform_cross_entropy;
    let value_better = model_metrics.value_mse < prior_mse;
    Ok(MetricComparisonV1 {
        uniform_policy_mean_nll: uniform_cross_entropy,
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
        let legal = splendor_search::canonical_order(&state.legal_actions());
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
            value_updates_shared_encoder: None,
            expected_search_teacher_targets_hash: None,
            model_architecture_version: None,
            optimizer_version: None,
        };
        (dataset, config)
    }

    fn search_targets(dataset: &TrainingDatasetV1) -> SearchTeacherTargetSetV1 {
        let targets = dataset
            .examples
            .iter()
            .filter(|example| example.source_id == "source-0" || example.source_id == "source-1")
            .map(|example| {
                let count = example.legal_actions.len() as u32;
                let base = SEARCH_VALUE_TARGET_SCALE_V1 / count;
                let remainder = SEARCH_VALUE_TARGET_SCALE_V1 % count;
                SearchTeacherTargetV1 {
                    source_id: example.source_id.clone(),
                    replay_document_hash: example.replay_document_hash.clone(),
                    ply: example.ply,
                    actor: example.actor,
                    observation_hash: example.observation_hash.clone(),
                    visible_history_hash: example.visible_history_hash.clone(),
                    information_set_hash: example.information_set_hash.clone(),
                    recorded_action: example.chosen_action,
                    teacher_action: example.legal_actions[0],
                    action_targets: example
                        .legal_actions
                        .iter()
                        .enumerate()
                        .map(|(index, action)| crate::SearchTeacherActionTargetV1 {
                            action: *action,
                            policy_target_micros: base + u32::from((index as u32) < remainder),
                            utility_sum_by_player: vec![0, 0],
                        })
                        .collect(),
                    value_target_by_player_micros: vec![500_000, 500_000],
                }
            })
            .collect();
        SearchTeacherTargetSetV1 {
            format: crate::SEARCH_TEACHER_TARGETS_FORMAT.into(),
            version: crate::SEARCH_TEACHER_TARGETS_VERSION,
            dataset_id: dataset.dataset_id.clone(),
            dataset_hash: training_dataset_hash_v1(dataset).unwrap(),
            league_manifest_hash: dataset.league_manifest_hash.clone(),
            evaluation_plan_hash: dataset.evaluation_plan_hash.clone(),
            evaluation_report_hash: dataset.evaluation_report_hash.clone(),
            teacher_agent_ids: vec!["teacher".into()],
            config: crate::SearchTeacherTargetsConfigV1 {
                search: splendor_imperfect_search::RootDeterminizationConfigV1 {
                    sample_seed: 7,
                    sample_count: 1,
                    continuation_search: splendor_search::SearchConfigV1 {
                        max_depth_turns: 1,
                        max_nodes: 1,
                    },
                },
                uniform_floor_micros: 100_000,
                value_utility_scale: 1_000_000_000,
            },
            targets,
        }
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
    fn search_teacher_contract_trains_deterministically_and_recomputes() {
        let (dataset, mut config) = dataset_and_config();
        let targets = search_targets(&dataset);
        let target_hash = crate::search_teacher_targets_hash_v1(&targets).unwrap();
        config.training_contract_version = Some(3);
        config.policy_teacher_agent_ids = vec!["teacher".into()];
        config.value_target_agent_ids = vec!["teacher".into()];
        config.min_policy_nll_relative_improvement_bps = Some(1);
        config.min_value_mse_relative_improvement_bps = Some(1);
        config.value_updates_shared_encoder = Some(false);
        config.expected_search_teacher_targets_hash = Some(target_hash.clone());

        let (left, report) =
            train_policy_value_with_search_targets_v1(&dataset, &targets, &config).unwrap();
        let (right, _) =
            train_policy_value_with_search_targets_v1(&dataset, &targets, &config).unwrap();
        assert_eq!(left, right);
        assert_eq!(
            left.search_teacher_targets_hash.as_deref(),
            Some(target_hash.as_str())
        );
        assert_eq!(report.search_teacher_targets_hash, Some(target_hash));
        assert_eq!(report.head_split.as_ref().unwrap().train_policy_examples, 4);
        assert!(evaluate_checkpoint_with_config_v1(&dataset, &left, &config).is_err());

        let offline =
            evaluate_checkpoint_with_search_targets_v1(&dataset, &targets, &left, &config).unwrap();
        assert_eq!(offline.train_head_metrics, report.train_head_metrics);
        assert_eq!(
            offline.validation_head_metrics,
            report.validation_head_metrics
        );
        assert_eq!(offline.material_gate, report.material_gate);
    }

    #[test]
    fn architecture_v2_is_deterministic_and_value_is_policy_isolated() {
        let (dataset, mut config) = dataset_and_config();
        let targets = search_targets(&dataset);
        config.training_contract_version = Some(3);
        config.model_architecture_version = Some(2);
        config.hidden_features = 8;
        config.policy_teacher_agent_ids = vec!["teacher".into()];
        config.value_target_agent_ids = vec!["teacher".into()];
        config.min_policy_nll_relative_improvement_bps = Some(1);
        config.min_value_mse_relative_improvement_bps = Some(1);
        config.value_updates_shared_encoder = Some(false);
        config.expected_search_teacher_targets_hash =
            Some(crate::search_teacher_targets_hash_v1(&targets).unwrap());

        let (left, report) =
            train_policy_value_with_search_targets_v1(&dataset, &targets, &config).unwrap();
        let (right, _) =
            train_policy_value_with_search_targets_v1(&dataset, &targets, &config).unwrap();
        assert_eq!(left, right);
        assert_eq!(left.model_architecture_version, Some(2));
        assert!(!left.parameters.policy_output_weights.is_empty());
        assert!(!left.parameters.value_encoder_weights.is_empty());
        let offline =
            evaluate_checkpoint_with_search_targets_v1(&dataset, &targets, &left, &config).unwrap();
        assert_eq!(
            offline.validation_head_metrics,
            report.validation_head_metrics
        );

        let mut changed_targets = targets.clone();
        for target in &mut changed_targets.targets {
            for action in &mut target.action_targets {
                action.utility_sum_by_player[1] = 1_000_000_000;
            }
            target.value_target_by_player_micros[1] = 1_000_000;
        }
        config.expected_search_teacher_targets_hash =
            Some(crate::search_teacher_targets_hash_v1(&changed_targets).unwrap());
        let (changed, _) =
            train_policy_value_with_search_targets_v1(&dataset, &changed_targets, &config).unwrap();
        assert_eq!(
            left.parameters.encoder_weights,
            changed.parameters.encoder_weights
        );
        assert_eq!(
            left.parameters.encoder_bias,
            changed.parameters.encoder_bias
        );
        assert_eq!(
            left.parameters.policy_bilinear,
            changed.parameters.policy_bilinear
        );
        assert_eq!(
            left.parameters.policy_action_bias,
            changed.parameters.policy_action_bias
        );
        assert_eq!(
            left.parameters.policy_hidden_bias,
            changed.parameters.policy_hidden_bias
        );
        assert_eq!(
            left.parameters.policy_output_weights,
            changed.parameters.policy_output_weights
        );
        assert_ne!(
            left.parameters.value_weights,
            changed.parameters.value_weights
        );
        assert_ne!(
            left.parameters.value_encoder_weights,
            changed.parameters.value_encoder_weights
        );
    }

    #[test]
    fn adam_v2_is_deterministic_bound_and_requires_architecture_v2() {
        let (dataset, mut config) = dataset_and_config();
        let targets = search_targets(&dataset);
        config.training_contract_version = Some(3);
        config.model_architecture_version = Some(2);
        config.optimizer_version = Some(2);
        config.hidden_features = 8;
        config.policy_teacher_agent_ids = vec!["teacher".into()];
        config.value_target_agent_ids = vec!["teacher".into()];
        config.min_policy_nll_relative_improvement_bps = Some(1);
        config.min_value_mse_relative_improvement_bps = Some(1);
        config.value_updates_shared_encoder = Some(false);
        config.expected_search_teacher_targets_hash =
            Some(crate::search_teacher_targets_hash_v1(&targets).unwrap());

        let (left, report) =
            train_policy_value_with_search_targets_v1(&dataset, &targets, &config).unwrap();
        let (right, _) =
            train_policy_value_with_search_targets_v1(&dataset, &targets, &config).unwrap();
        assert_eq!(left, right);
        assert_eq!(left.optimizer_version, Some(2));
        assert_eq!(report.optimizer_version, Some(2));
        let offline =
            evaluate_checkpoint_with_search_targets_v1(&dataset, &targets, &left, &config).unwrap();
        assert_eq!(offline.optimizer_version, Some(2));
        assert_eq!(
            offline.validation_head_metrics,
            report.validation_head_metrics
        );

        config.model_architecture_version = None;
        assert!(matches!(
            config.validate(),
            Err(LearningError::InvalidConfig(message)) if message.contains("architecture v2")
        ));
    }

    #[test]
    fn value_only_examples_cannot_change_policy_representation_when_isolated() {
        let (dataset, mut config) = dataset_and_config();
        config.training_contract_version = Some(2);
        config.policy_teacher_agent_ids = vec!["teacher".into()];
        config.value_target_agent_ids = vec!["rejected".into()];
        config.min_policy_nll_relative_improvement_bps = Some(1);
        config.min_value_mse_relative_improvement_bps = Some(1);
        config.value_updates_shared_encoder = Some(false);

        let (baseline, report) = train_policy_value_v1(&dataset, &config).unwrap();
        assert_eq!(report.value_updates_shared_encoder, Some(false));

        let mut changed_targets = dataset.clone();
        for example in &mut changed_targets.examples {
            if example.source_id == "source-2" || example.source_id == "source-3" {
                example.final_scores.reverse();
                example.final_ranks.reverse();
            }
        }
        config.expected_dataset_hash = training_dataset_hash_v1(&changed_targets).unwrap();
        let (changed, _) = train_policy_value_v1(&changed_targets, &config).unwrap();

        assert_eq!(
            baseline.parameters.encoder_weights,
            changed.parameters.encoder_weights
        );
        assert_eq!(
            baseline.parameters.encoder_bias,
            changed.parameters.encoder_bias
        );
        assert_eq!(
            baseline.parameters.policy_bilinear,
            changed.parameters.policy_bilinear
        );
        assert_eq!(
            baseline.parameters.policy_action_bias,
            changed.parameters.policy_action_bias
        );
        assert_ne!(
            baseline.parameters.value_weights,
            changed.parameters.value_weights
        );
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
