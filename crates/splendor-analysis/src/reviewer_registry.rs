//! Studio reviewer registry (independent of the M16 1v1 agent registry).
//!
//! This registry advertises which reviewers are available for the one-click
//! review workflow. It is intentionally separate from the play registry: a
//! reviewer is not necessarily a play-capable agent, and play-capable agents
//! (M17/M18A/M18B/M22) are not necessarily reviewers yet.

use serde::{Deserialize, Serialize};
use std::path::{Component, Path};

use crate::{
    AnalysisError, ReviewerConfigV2, ReviewerResultKindV2, ReviewerStatusV2, M07_REVIEWER_ID,
    M13_REVIEWER_ID,
};

pub const REVIEWER_REGISTRY_FORMAT: &str = "effective-splendor-studio-reviewers";
pub const REVIEWER_REGISTRY_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewerEntryV1 {
    pub id: String,
    pub display_name: String,
    pub description: String,
    pub competitive_status: ReviewerStatusV2,
    pub result_kind: ReviewerResultKindV2,
    /// Exactly one entry should be the recommended default.
    #[serde(default)]
    pub is_default: bool,
    pub available_metrics: Vec<String>,
    pub required_artifacts: Vec<String>,
    pub estimated_cost: String,
    pub default_config: ReviewerConfigV2,
    /// Local path to a required artifact (e.g. the M12 checkpoint). Resolved by
    /// the Studio Host from a fixed directory; never supplied by the browser.
    #[serde(default)]
    pub checkpoint_path: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewerRegistryV1 {
    pub format: String,
    pub version: u32,
    pub registry_id: String,
    pub reviewers: Vec<ReviewerEntryV1>,
}

impl ReviewerRegistryV1 {
    pub fn validate(&self) -> Result<(), AnalysisError> {
        if self.format != REVIEWER_REGISTRY_FORMAT || self.version != REVIEWER_REGISTRY_VERSION {
            return Err(reviewer("unsupported reviewer registry format/version"));
        }
        if self.registry_id.trim().is_empty() {
            return Err(reviewer("registry_id must not be empty"));
        }
        if self.reviewers.is_empty() {
            return Err(reviewer("reviewer registry requires at least one reviewer"));
        }
        let mut ids = std::collections::HashSet::new();
        let mut defaults = 0usize;
        for entry in &self.reviewers {
            if entry.id.trim().is_empty()
                || entry.display_name.trim().is_empty()
                || entry.description.trim().is_empty()
                || entry.estimated_cost.trim().is_empty()
                || entry.available_metrics.is_empty()
            {
                return Err(reviewer(format!(
                    "reviewer '{}' has incomplete metadata",
                    entry.id
                )));
            }
            if !ids.insert(entry.id.as_str()) {
                return Err(reviewer(format!("duplicate reviewer id '{}'", entry.id)));
            }
            if !is_safe_component(&entry.id) {
                return Err(reviewer(format!(
                    "reviewer id '{}' is not a safe path component",
                    entry.id
                )));
            }
            if entry.is_default {
                defaults += 1;
            }
            let expected_metrics: &[&str] = match entry.result_kind {
                ReviewerResultKindV2::RootDeterminization => {
                    &["mean_utility", "utility_gap", "action_rank"]
                }
                ReviewerResultKindV2::NeuralIsmcts => &["prior", "visit", "q"],
            };
            if entry
                .available_metrics
                .iter()
                .map(String::as_str)
                .ne(expected_metrics.iter().copied())
            {
                return Err(reviewer(format!(
                    "reviewer '{}' metric contract does not match result_kind",
                    entry.id
                )));
            }
            match entry.id.as_str() {
                M07_REVIEWER_ID
                    if entry.competitive_status != ReviewerStatusV2::Champion
                        || entry.result_kind != ReviewerResultKindV2::RootDeterminization =>
                {
                    return Err(reviewer("M07 reviewer status/kind mismatch"));
                }
                M13_REVIEWER_ID
                    if entry.competitive_status != ReviewerStatusV2::Rejected
                        || entry.result_kind != ReviewerResultKindV2::NeuralIsmcts =>
                {
                    return Err(reviewer("M13 reviewer status/kind mismatch"));
                }
                _ => {}
            }
            match (&entry.default_config, &entry.result_kind) {
                (
                    ReviewerConfigV2::RootDeterminization(config),
                    ReviewerResultKindV2::RootDeterminization,
                ) => {
                    config.validate().map_err(|error| {
                        reviewer(format!("reviewer '{}' config: {error}", entry.id))
                    })?;
                    if entry.checkpoint_path.is_some() {
                        return Err(reviewer(format!(
                            "reviewer '{}' must not bind a checkpoint",
                            entry.id
                        )));
                    }
                }
                (ReviewerConfigV2::NeuralIsmcts(config), ReviewerResultKindV2::NeuralIsmcts) => {
                    config.validate().map_err(|error| {
                        reviewer(format!("reviewer '{}' config: {error}", entry.id))
                    })?;
                    let checkpoint_path = entry.checkpoint_path.as_deref().unwrap_or("");
                    if checkpoint_path.trim().is_empty() {
                        return Err(reviewer(format!(
                            "reviewer '{}' requires a checkpoint_path",
                            entry.id
                        )));
                    }
                    let path = Path::new(checkpoint_path);
                    if path.is_absolute()
                        || path.components().any(|component| {
                            matches!(
                                component,
                                Component::ParentDir | Component::RootDir | Component::Prefix(_)
                            )
                        })
                        || !path.starts_with("local-artifacts")
                    {
                        return Err(reviewer(format!(
                            "reviewer '{}' checkpoint_path must stay below local-artifacts",
                            entry.id
                        )));
                    }
                }
                _ => {
                    return Err(reviewer(format!(
                        "reviewer '{}' config kind does not match result_kind",
                        entry.id
                    )));
                }
            }
        }
        if defaults != 1 {
            return Err(reviewer(
                "reviewer registry requires exactly one default reviewer",
            ));
        }
        Ok(())
    }

    pub fn entry(&self, reviewer_id: &str) -> Result<&ReviewerEntryV1, AnalysisError> {
        self.reviewers
            .iter()
            .find(|entry| entry.id == reviewer_id)
            .ok_or_else(|| reviewer(format!("unknown reviewer id '{reviewer_id}'")))
    }
}

fn is_safe_component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn reviewer(message: impl Into<String>) -> AnalysisError {
    AnalysisError::Reviewer(message.into())
}
