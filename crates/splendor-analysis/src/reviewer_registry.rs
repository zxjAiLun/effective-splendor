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
    M13_REVIEWER_ID, S3_REVIEWER_ID, S3_REVIEWER_METRICS,
};

pub const REVIEWER_REGISTRY_FORMAT: &str = "effective-splendor-studio-reviewers";
pub const REVIEWER_REGISTRY_VERSION: u32 = 1;

/// Player counts every reviewer context covers (the engine supports 2..=4).
pub const REVIEWER_MIN_PLAYERS: u8 = 2;
pub const REVIEWER_MAX_PLAYERS: u8 = 4;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewerEntryV1 {
    pub id: String,
    pub display_name: String,
    pub description: String,
    pub competitive_status: ReviewerStatusV2,
    pub result_kind: ReviewerResultKindV2,
    /// The player counts for which this reviewer is the per-context default.
    ///
    /// Defaults are player-count aware: every covered player count (2..=4)
    /// must be claimed by exactly one entry, and an entry may only claim a
    /// count it supports. This supersedes any unconditional global default.
    #[serde(default)]
    pub default_for_player_counts: Vec<u8>,
    pub available_metrics: Vec<String>,
    pub required_artifacts: Vec<String>,
    pub estimated_cost: String,
    pub default_config: ReviewerConfigV2,
    /// Local path to a required artifact (e.g. the M12 checkpoint). Resolved by
    /// the Studio Host from a fixed directory; never supplied by the browser.
    #[serde(default)]
    pub checkpoint_path: Option<String>,
}

impl ReviewerEntryV1 {
    /// Whether this reviewer can analyze a replay with `player_count` players.
    ///
    /// The S3 rollout reviewer is frozen for 2-player games (the S3 policy
    /// asserts two seats); every other reviewer covers 2..=4 players.
    pub fn supports_player_count(&self, player_count: u8) -> bool {
        if !(REVIEWER_MIN_PLAYERS..=REVIEWER_MAX_PLAYERS).contains(&player_count) {
            return false;
        }
        match self.result_kind {
            ReviewerResultKindV2::PolicyRecommendation => player_count == 2,
            ReviewerResultKindV2::RootDeterminization | ReviewerResultKindV2::NeuralIsmcts => true,
        }
    }

    /// Every player count this reviewer supports, in ascending order.
    pub fn supported_player_counts(&self) -> Vec<u8> {
        (REVIEWER_MIN_PLAYERS..=REVIEWER_MAX_PLAYERS)
            .filter(|player_count| self.supports_player_count(*player_count))
            .collect()
    }

    /// Whether this reviewer is the context default for `player_count`.
    pub fn is_default_for(&self, player_count: u8) -> bool {
        self.default_for_player_counts.contains(&player_count)
    }
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
        let mut defaults: std::collections::BTreeMap<u8, &str> = std::collections::BTreeMap::new();
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
            // Per-context default declarations: a reviewer may only claim a
            // player count it supports, and no count may have two defaults.
            for player_count in &entry.default_for_player_counts {
                if !entry.supports_player_count(*player_count) {
                    return Err(reviewer(format!(
                        "reviewer '{}' cannot default for {player_count}-player replays",
                        entry.id
                    )));
                }
                if let Some(existing) = defaults.insert(*player_count, entry.id.as_str()) {
                    return Err(reviewer(format!(
                        "reviewers '{existing}' and '{}' both default for {player_count}-player replays",
                        entry.id
                    )));
                }
            }
            let expected_metrics: &[&str] = match entry.result_kind {
                ReviewerResultKindV2::RootDeterminization => {
                    &["mean_utility", "utility_gap", "action_rank"]
                }
                ReviewerResultKindV2::NeuralIsmcts => &["prior", "visit", "q"],
                ReviewerResultKindV2::PolicyRecommendation => &S3_REVIEWER_METRICS,
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
                S3_REVIEWER_ID
                    if entry.competitive_status != ReviewerStatusV2::Champion
                        || entry.result_kind != ReviewerResultKindV2::PolicyRecommendation =>
                {
                    return Err(reviewer("S3 reviewer status/kind mismatch"));
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
                (
                    ReviewerConfigV2::PolicyRecommendation(config),
                    ReviewerResultKindV2::PolicyRecommendation,
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
                _ => {
                    return Err(reviewer(format!(
                        "reviewer '{}' config kind does not match result_kind",
                        entry.id
                    )));
                }
            }
        }
        for player_count in REVIEWER_MIN_PLAYERS..=REVIEWER_MAX_PLAYERS {
            if !defaults.contains_key(&player_count) {
                return Err(reviewer(format!(
                    "no reviewer defaults for {player_count}-player replays"
                )));
            }
        }
        Ok(())
    }

    pub fn entry(&self, reviewer_id: &str) -> Result<&ReviewerEntryV1, AnalysisError> {
        self.reviewers
            .iter()
            .find(|entry| entry.id == reviewer_id)
            .ok_or_else(|| reviewer(format!("unknown reviewer id '{reviewer_id}'")))
    }

    /// The single per-context default reviewer for `player_count`.
    pub fn default_entry(&self, player_count: u8) -> Result<&ReviewerEntryV1, AnalysisError> {
        let mut matching = self
            .reviewers
            .iter()
            .filter(|entry| entry.is_default_for(player_count));
        let entry = matching.next().ok_or_else(|| {
            reviewer(format!("no default reviewer for {player_count}-player replays"))
        })?;
        if matching.next().is_some() {
            return Err(reviewer(format!(
                "multiple default reviewers for {player_count}-player replays"
            )));
        }
        Ok(entry)
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
