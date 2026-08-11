use serde::{Deserialize, Serialize};

use crate::error::invalid_formal_result;
use crate::{
    DatasetIdentityV1, DatasetSplitV1, LearningError, MetricComparisonV1, OfflineMetricsV1,
    TrainingOutcomeV1,
};

pub const FORMAL_POLICY_VALUE_RESULT_FORMAT: &str = "effective-splendor-policy-value-formal-result";
pub const FORMAL_POLICY_VALUE_RESULT_VERSION: u32 = 1;

/// Small, Git-friendly identity anchor for a formal local M12 run.
///
/// Large datasets and model artifacts remain outside ordinary Git history;
/// this document pins their content hashes and the exact implementation/config
/// that produced the accepted offline result.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FormalPolicyValueResultV1 {
    pub format: String,
    pub version: u32,
    pub result_id: String,
    pub formal_date: String,
    pub implementation_commit: String,
    pub dataset: DatasetIdentityV1,
    pub training_config_hash: String,
    pub checkpoint_hash: String,
    pub checkpoint_file_sha256: String,
    pub training_report_file_sha256: String,
    pub offline_eval_file_sha256: String,
    pub split: DatasetSplitV1,
    pub validation_metrics: OfflineMetricsV1,
    pub validation_comparison: MetricComparisonV1,
}

impl FormalPolicyValueResultV1 {
    pub fn validate(&self) -> Result<(), LearningError> {
        if self.format != FORMAL_POLICY_VALUE_RESULT_FORMAT
            || self.version != FORMAL_POLICY_VALUE_RESULT_VERSION
        {
            return Err(invalid_formal_result("unsupported format/version"));
        }
        validate_label("result_id", &self.result_id)?;
        if self.formal_date.len() != 10
            || self.formal_date.as_bytes().get(4) != Some(&b'-')
            || self.formal_date.as_bytes().get(7) != Some(&b'-')
        {
            return Err(invalid_formal_result("formal_date is not YYYY-MM-DD"));
        }
        validate_lower_hex("implementation_commit", &self.implementation_commit, 40)?;
        validate_label("dataset_id", &self.dataset.dataset_id)?;
        for (label, hash) in [
            ("dataset_hash", self.dataset.dataset_hash.as_str()),
            (
                "league_manifest_hash",
                self.dataset.league_manifest_hash.as_str(),
            ),
            (
                "evaluation_plan_hash",
                self.dataset.evaluation_plan_hash.as_str(),
            ),
            (
                "evaluation_report_hash",
                self.dataset.evaluation_report_hash.as_str(),
            ),
            ("training_config_hash", self.training_config_hash.as_str()),
            ("checkpoint_hash", self.checkpoint_hash.as_str()),
            (
                "checkpoint_file_sha256",
                self.checkpoint_file_sha256.as_str(),
            ),
            (
                "training_report_file_sha256",
                self.training_report_file_sha256.as_str(),
            ),
            (
                "offline_eval_file_sha256",
                self.offline_eval_file_sha256.as_str(),
            ),
        ] {
            validate_lower_hex(label, hash, 64)?;
        }
        if self.split.validation_seed_modulus < 2
            || self.split.validation_seed_remainder >= self.split.validation_seed_modulus
            || self.split.train_replays == 0
            || self.split.validation_replays == 0
            || self.split.train_examples == 0
            || self.split.validation_examples == 0
            || self.validation_metrics.examples != self.split.validation_examples
        {
            return Err(invalid_formal_result("invalid or mismatched split counts"));
        }
        let metrics = &self.validation_metrics;
        if !metrics.policy_top1_accuracy.is_finite()
            || !(0.0..=1.0).contains(&metrics.policy_top1_accuracy)
            || !metrics.mean_policy_nll.is_finite()
            || metrics.mean_policy_nll < 0.0
            || !metrics.value_mse.is_finite()
            || metrics.value_mse < 0.0
        {
            return Err(invalid_formal_result("validation metrics are invalid"));
        }
        let comparison = &self.validation_comparison;
        if !comparison.uniform_policy_mean_nll.is_finite()
            || !comparison.train_prior_value_mse.is_finite()
            || comparison.policy_nll_beats_uniform
                != (metrics.mean_policy_nll < comparison.uniform_policy_mean_nll)
            || comparison.value_mse_beats_train_prior
                != (metrics.value_mse < comparison.train_prior_value_mse)
        {
            return Err(invalid_formal_result(
                "baseline comparison does not match validation metrics",
            ));
        }
        let expected_outcome =
            if comparison.policy_nll_beats_uniform && comparison.value_mse_beats_train_prior {
                TrainingOutcomeV1::BaselinesBeaten
            } else {
                TrainingOutcomeV1::BaselineNotBeaten
            };
        if comparison.outcome != expected_outcome {
            return Err(invalid_formal_result(
                "outcome does not match baseline comparisons",
            ));
        }
        Ok(())
    }
}

fn validate_lower_hex(label: &str, value: &str, length: usize) -> Result<(), LearningError> {
    if value.len() != length
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid_formal_result(format!(
            "{label} is not lowercase hex with length {length}"
        )));
    }
    Ok(())
}

fn validate_label(label: &str, value: &str) -> Result<(), LearningError> {
    if value.trim().is_empty() || value.len() > 128 || value.bytes().any(|byte| byte < 0x20) {
        return Err(invalid_formal_result(format!("{label} is invalid")));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use crate::{training_config_hash_v1, PolicyValueTrainingConfigV1};

    use super::*;

    #[test]
    fn checked_in_formal_result_is_valid_and_binds_frozen_config() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let result: FormalPolicyValueResultV1 = serde_json::from_str(
            &std::fs::read_to_string(root.join("benchmarks/m12-policy-value-v1.result.json"))
                .unwrap(),
        )
        .unwrap();
        result.validate().unwrap();
        let config: PolicyValueTrainingConfigV1 = serde_json::from_str(
            &std::fs::read_to_string(root.join("benchmarks/m12-policy-value-v1.config.json"))
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            result.training_config_hash,
            training_config_hash_v1(&config).unwrap()
        );
        assert_eq!(
            result.implementation_commit,
            "963019ece89a7912f81ce37dcb640eab726ffea8"
        );
        assert_eq!(
            result.checkpoint_hash,
            "108d32fa2d0d2499ead38e99b23e42cd905644358a76d5adb7392ad43401b462"
        );
    }
}
