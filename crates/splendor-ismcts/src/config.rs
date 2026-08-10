use serde::{Deserialize, Serialize};

use crate::IsmctsError;

pub const MAX_ISMCTS_SIMULATIONS: u32 = 10_000;
pub const MAX_ISMCTS_DEPTH_TURNS: u8 = 8;
pub const MAX_EXPLORATION_BIAS: u64 = 1_000_000_000_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IsmctsConfigV1 {
    pub sample_seed: u64,
    pub simulations: u32,
    pub max_depth_turns: u8,
    /// Utility-space confidence bonus at an equally visited branch.
    pub exploration_bias: u64,
}

impl IsmctsConfigV1 {
    pub fn validate(self) -> Result<(), IsmctsError> {
        if self.simulations == 0 || self.simulations > MAX_ISMCTS_SIMULATIONS {
            return Err(IsmctsError::InvalidConfig(format!(
                "simulations must be within 1..={MAX_ISMCTS_SIMULATIONS}"
            )));
        }
        if self.max_depth_turns == 0 || self.max_depth_turns > MAX_ISMCTS_DEPTH_TURNS {
            return Err(IsmctsError::InvalidConfig(format!(
                "max_depth_turns must be within 1..={MAX_ISMCTS_DEPTH_TURNS}"
            )));
        }
        if self.exploration_bias > MAX_EXPLORATION_BIAS {
            return Err(IsmctsError::InvalidConfig(format!(
                "exploration_bias must be <= {MAX_EXPLORATION_BIAS}"
            )));
        }
        Ok(())
    }
}
