use serde::{Deserialize, Serialize};

use crate::NeuralSearchError;

pub const MAX_NEURAL_ISMCTS_SIMULATIONS: u32 = 10_000;
pub const MAX_NEURAL_ISMCTS_DEPTH_TURNS: u8 = 8;
pub const MAX_PUCT_EXPLORATION_MILLI: u32 = 100_000;

/// Experimental switches used to isolate the M12 policy and value heads.
///
/// `Full` is exactly the accepted M13 algorithm. The other modes are diagnostic
/// controls and must not be used as a promoted runtime identity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NeuralAblationModeV1 {
    Full,
    ValueOnly,
    PolicyOnly,
    Neutral,
}

impl NeuralAblationModeV1 {
    pub(crate) const fn uses_learned_priors(self) -> bool {
        matches!(self, Self::Full | Self::PolicyOnly)
    }

    pub(crate) const fn uses_learned_values(self) -> bool {
        matches!(self, Self::Full | Self::ValueOnly)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuralIsmctsConfigV1 {
    pub sample_seed: u64,
    pub simulations: u32,
    pub max_depth_turns: u8,
    /// PUCT exploration constant multiplied by 1,000.
    pub puct_exploration_milli: u32,
    /// Semantic M12 checkpoint hash required by this search run.
    pub expected_checkpoint_hash: String,
}

impl NeuralIsmctsConfigV1 {
    pub fn validate(&self) -> Result<(), NeuralSearchError> {
        if self.simulations == 0 || self.simulations > MAX_NEURAL_ISMCTS_SIMULATIONS {
            return Err(NeuralSearchError::InvalidConfig(format!(
                "simulations must be within 1..={MAX_NEURAL_ISMCTS_SIMULATIONS}"
            )));
        }
        if self.max_depth_turns == 0 || self.max_depth_turns > MAX_NEURAL_ISMCTS_DEPTH_TURNS {
            return Err(NeuralSearchError::InvalidConfig(format!(
                "max_depth_turns must be within 1..={MAX_NEURAL_ISMCTS_DEPTH_TURNS}"
            )));
        }
        if self.puct_exploration_milli > MAX_PUCT_EXPLORATION_MILLI {
            return Err(NeuralSearchError::InvalidConfig(format!(
                "puct_exploration_milli must be <= {MAX_PUCT_EXPLORATION_MILLI}"
            )));
        }
        if self.expected_checkpoint_hash.len() != 64
            || !self
                .expected_checkpoint_hash
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err(NeuralSearchError::InvalidConfig(
                "expected_checkpoint_hash is not lowercase SHA-256".into(),
            ));
        }
        Ok(())
    }
}
