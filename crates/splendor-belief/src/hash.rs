use sha2::{Digest, Sha256};
use splendor_core::{observation_hash, Observation, VisibleEvent};

use crate::error::BeliefError;

/// Domain-separation tag for the visible-history identity.
const VISIBLE_HISTORY_DOMAIN: &[u8] = b"effective-splendor-visible-history-v1\0";

/// Domain-separation tag for the information-set identity.
const INFORMATION_SET_DOMAIN: &[u8] = b"effective-splendor-information-set-v1\0";

/// SHA-256 identity of the player-visible event transcript.
///
/// Guaranteed to be 64 lowercase hex characters.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VisibleHistoryHashV1(String);

impl VisibleHistoryHashV1 {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// SHA-256 identity of the whole information set: the observation identity
/// followed by the visible-history identity.
///
/// Both inputs are fixed-length 64-char lowercase hex, so concatenation is
/// unambiguous. Guaranteed to be 64 lowercase hex characters.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InformationSetHashV1(String);

impl InformationSetHashV1 {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// `SHA-256("effective-splendor-visible-history-v1\0" || compact_json(events))`.
pub(crate) fn visible_history_hash_v1(
    events: &[VisibleEvent],
) -> Result<VisibleHistoryHashV1, BeliefError> {
    let encoded =
        serde_json::to_vec(events).map_err(|e| BeliefError::Serialization(e.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(VISIBLE_HISTORY_DOMAIN);
    hasher.update(&encoded);
    Ok(VisibleHistoryHashV1(hex::encode(hasher.finalize())))
}

/// `SHA-256("effective-splendor-information-set-v1\0" || obs_hash || vis_hash)`.
pub(crate) fn information_set_hash_v1(
    observation: &Observation,
    visible_hash: &VisibleHistoryHashV1,
) -> InformationSetHashV1 {
    let mut hasher = Sha256::new();
    hasher.update(INFORMATION_SET_DOMAIN);
    hasher.update(observation_hash(observation).as_str().as_bytes());
    hasher.update(visible_hash.as_str().as_bytes());
    InformationSetHashV1(hex::encode(hasher.finalize()))
}
