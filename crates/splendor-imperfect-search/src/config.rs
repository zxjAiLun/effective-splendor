use serde::{Deserialize, Serialize};
use splendor_search::SearchConfigV1;

use crate::error::ImperfectSearchError;

/// Smallest supported number of sampled determinizations.
pub const MIN_SAMPLE_COUNT: u16 = 1;

/// Largest supported number of sampled determinizations.
pub const MAX_SAMPLE_COUNT: u16 = 64;

/// Default number of sampled determinizations.
pub const DEFAULT_SAMPLE_COUNT: u16 = 8;

/// Frozen configuration for root-determinization aggregation.
///
/// `continuation_search.max_depth_turns` is the horizon *after* the root
/// action has been applied. The root action itself is therefore always
/// evaluated, even when the continuation horizon is zero.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RootDeterminizationConfigV1 {
    /// Seed for the deterministic belief sampler.
    pub sample_seed: u64,
    /// Number of sample indices, evaluated as `0..sample_count`.
    pub sample_count: u16,
    /// Frozen perfect-information search configuration for each non-terminal
    /// sampled child.
    pub continuation_search: SearchConfigV1,
}

impl Default for RootDeterminizationConfigV1 {
    fn default() -> Self {
        Self {
            sample_seed: 0,
            sample_count: DEFAULT_SAMPLE_COUNT,
            continuation_search: SearchConfigV1::default(),
        }
    }
}

impl RootDeterminizationConfigV1 {
    /// Validate the root aggregation and continuation-search limits.
    pub fn validate(&self) -> Result<(), ImperfectSearchError> {
        if !(MIN_SAMPLE_COUNT..=MAX_SAMPLE_COUNT).contains(&self.sample_count) {
            return Err(ImperfectSearchError::InvalidConfig(format!(
                "sample_count must be in {MIN_SAMPLE_COUNT}..={MAX_SAMPLE_COUNT}, found {}",
                self.sample_count
            )));
        }

        self.continuation_search
            .validate()
            .map_err(|error| ImperfectSearchError::InvalidConfig(error.to_string()))
    }
}
