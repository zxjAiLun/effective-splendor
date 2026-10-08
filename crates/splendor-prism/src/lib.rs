//! Prism v0.1: independent classic two-player player-view policy/value model.
//! Neither this crate nor its encoder depends on Aran or splendor-learning.
pub mod encoding;
pub mod inference;
pub use encoding::{
    catalog_fingerprint, encode, EncodedState, ACTION_DIM, ACTION_SCHEMA, ENTITY_DIM, OBS_SCHEMA,
};
pub use inference::{Prediction, PrismWeights};
