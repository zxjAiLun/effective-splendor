use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_core::{Action, Observation};

use crate::error::{invalid_checkpoint, invalid_dataset};
use crate::{
    encode_action_v1, encode_observation_v1, LearningError, ACTION_FEATURES_V1, MAX_PLAYERS_V1,
    OBSERVATION_FEATURES_V1, REPRESENTATION_VERSION_V1,
};

pub const POLICY_VALUE_CHECKPOINT_FORMAT: &str = "effective-splendor-policy-value-checkpoint";
pub const POLICY_VALUE_CHECKPOINT_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelParametersV1 {
    pub encoder_weights: Vec<f32>,
    pub encoder_bias: Vec<f32>,
    pub policy_bilinear: Vec<f32>,
    pub policy_action_bias: Vec<f32>,
    pub value_weights: Vec<f32>,
    pub value_bias: Vec<f32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub policy_hidden_bias: Vec<f32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub policy_output_weights: Vec<f32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub value_encoder_weights: Vec<f32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub value_encoder_bias: Vec<f32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyValueCheckpointV1 {
    pub format: String,
    pub version: u32,
    pub model_id: String,
    pub representation_version: String,
    pub observation_features: u32,
    pub action_features: u32,
    pub hidden_features: u32,
    pub max_players: u8,
    pub source_dataset_id: String,
    pub source_dataset_hash: String,
    pub league_manifest_hash: String,
    pub evaluation_plan_hash: String,
    pub evaluation_report_hash: String,
    pub training_config_hash: String,
    /// Absent for the accepted M12 contract. `Some(2)` marks source-aware
    /// M15B; `Some(3)` binds M15C full-search targets.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub training_contract_version: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub search_teacher_targets_hash: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_architecture_version: Option<u32>,
    pub trained_examples: u64,
    pub validation_examples: u64,
    pub validation_seed_modulus: u32,
    pub validation_seed_remainder: u32,
    pub epochs: u32,
    pub parameters: ModelParametersV1,
}

impl PolicyValueCheckpointV1 {
    pub fn validate(&self) -> Result<(), LearningError> {
        if self.format != POLICY_VALUE_CHECKPOINT_FORMAT
            || self.version != POLICY_VALUE_CHECKPOINT_VERSION
        {
            return Err(invalid_checkpoint("unsupported format/version"));
        }
        validate_label("model_id", &self.model_id)?;
        if self.representation_version != REPRESENTATION_VERSION_V1 {
            return Err(invalid_checkpoint(format!(
                "representation `{}` is not `{REPRESENTATION_VERSION_V1}`",
                self.representation_version
            )));
        }
        if self.observation_features as usize != OBSERVATION_FEATURES_V1
            || self.action_features as usize != ACTION_FEATURES_V1
            || self.max_players as usize != MAX_PLAYERS_V1
        {
            return Err(invalid_checkpoint(
                "frozen representation dimensions differ",
            ));
        }
        let hidden = self.hidden_features as usize;
        if hidden == 0 || hidden > 256 {
            return Err(invalid_checkpoint("hidden_features must be in 1..=256"));
        }
        validate_hash("source_dataset_hash", &self.source_dataset_hash)?;
        validate_hash("league_manifest_hash", &self.league_manifest_hash)?;
        validate_hash("evaluation_plan_hash", &self.evaluation_plan_hash)?;
        validate_hash("evaluation_report_hash", &self.evaluation_report_hash)?;
        validate_hash("training_config_hash", &self.training_config_hash)?;
        if self
            .training_contract_version
            .is_some_and(|version| version != 2 && version != 3)
        {
            return Err(invalid_checkpoint(
                "unsupported source-aware training contract version",
            ));
        }
        match self.training_contract_version {
            Some(3) => validate_hash(
                "search_teacher_targets_hash",
                self.search_teacher_targets_hash.as_deref().ok_or_else(|| {
                    invalid_checkpoint("contract v3 requires search-teacher target hash")
                })?,
            )?,
            _ if self.search_teacher_targets_hash.is_some() => {
                return Err(invalid_checkpoint(
                    "search-teacher target hash requires training contract v3",
                ));
            }
            _ => {}
        }
        if self
            .model_architecture_version
            .is_some_and(|version| version != 2)
        {
            return Err(invalid_checkpoint(
                "model_architecture_version must be absent or 2",
            ));
        }
        if self.model_architecture_version.is_some() && self.training_contract_version != Some(3) {
            return Err(invalid_checkpoint(
                "architecture v2 requires search-teacher contract v3",
            ));
        }
        validate_label("source_dataset_id", &self.source_dataset_id)?;
        if self.trained_examples == 0 || self.validation_examples == 0 || self.epochs == 0 {
            return Err(invalid_checkpoint(
                "checkpoint requires non-zero train/validation examples and epochs",
            ));
        }
        if self.validation_seed_modulus < 2
            || self.validation_seed_remainder >= self.validation_seed_modulus
        {
            return Err(invalid_checkpoint("invalid source-level validation split"));
        }
        validate_parameters(&self.parameters, hidden, self.model_architecture_version)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyActionProbabilityV1 {
    pub action: Action,
    pub probability: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyValuePredictionV1 {
    pub policy: Vec<PolicyActionProbabilityV1>,
    pub value_by_player: Vec<f32>,
}

#[derive(Debug, Clone)]
pub struct PolicyValueModelV1 {
    checkpoint: PolicyValueCheckpointV1,
}

impl PolicyValueModelV1 {
    pub fn from_checkpoint(checkpoint: PolicyValueCheckpointV1) -> Result<Self, LearningError> {
        checkpoint.validate()?;
        Ok(Self { checkpoint })
    }

    pub fn checkpoint(&self) -> &PolicyValueCheckpointV1 {
        &self.checkpoint
    }

    pub fn predict(
        &self,
        observation: &Observation,
        legal_actions: &[Action],
    ) -> Result<PolicyValuePredictionV1, LearningError> {
        if legal_actions.is_empty() {
            return Err(invalid_dataset(
                "inference requires at least one legal action",
            ));
        }
        let player_count = observation.public.player_count as usize;
        if !(2..=MAX_PLAYERS_V1).contains(&player_count)
            || observation.viewer.index() >= player_count
        {
            return Err(invalid_dataset(
                "observation has an invalid player/viewer shape",
            ));
        }
        let observation_features = encode_observation_v1(observation)?;
        let hidden = self.hidden(&observation_features);
        if hidden.iter().any(|value| !value.is_finite()) {
            return Err(invalid_checkpoint(
                "checkpoint produced a non-finite hidden representation",
            ));
        }
        let action_features = legal_actions
            .iter()
            .map(encode_action_v1)
            .collect::<Result<Vec<_>, _>>()?;
        let probabilities = self.policy_probabilities(&hidden, &action_features)?;
        let values = if self.checkpoint.model_architecture_version == Some(2) {
            let value_hidden = self.value_hidden(&observation_features);
            if value_hidden.iter().any(|value| !value.is_finite()) {
                return Err(invalid_checkpoint(
                    "checkpoint produced a non-finite Value representation",
                ));
            }
            self.values(&value_hidden, player_count)
        } else {
            self.values(&hidden, player_count)
        };
        if values.iter().any(|value| !value.is_finite()) {
            return Err(invalid_checkpoint(
                "checkpoint produced a non-finite value prediction",
            ));
        }
        Ok(PolicyValuePredictionV1 {
            policy: legal_actions
                .iter()
                .copied()
                .zip(probabilities)
                .map(|(action, probability)| PolicyActionProbabilityV1 {
                    action,
                    probability,
                })
                .collect(),
            value_by_player: values,
        })
    }

    pub(crate) fn hidden(&self, observation: &[f32]) -> Vec<f32> {
        let hidden = self.checkpoint.hidden_features as usize;
        let mut output = vec![0.0; hidden];
        for (unit, target) in output.iter_mut().enumerate() {
            let row = &self.checkpoint.parameters.encoder_weights
                [unit * OBSERVATION_FEATURES_V1..(unit + 1) * OBSERVATION_FEATURES_V1];
            let sum = row.iter().zip(observation).fold(
                self.checkpoint.parameters.encoder_bias[unit],
                |acc, (weight, feature)| acc + weight * feature,
            );
            *target = sum.tanh();
        }
        output
    }

    pub(crate) fn policy_probabilities(
        &self,
        hidden: &[f32],
        actions: &[Vec<f32>],
    ) -> Result<Vec<f32>, LearningError> {
        if self.checkpoint.model_architecture_version == Some(2) {
            return self.policy_probabilities_v2(hidden, actions);
        }
        let context = self.policy_context(hidden);
        let mut logits = actions
            .iter()
            .map(|action| {
                context
                    .iter()
                    .zip(action)
                    .zip(&self.checkpoint.parameters.policy_action_bias)
                    .fold(0.0, |acc, ((state, feature), bias)| {
                        acc + (state + bias) * feature
                    })
            })
            .collect::<Vec<_>>();
        softmax_in_place(&mut logits)?;
        Ok(logits)
    }

    fn policy_probabilities_v2(
        &self,
        hidden: &[f32],
        actions: &[Vec<f32>],
    ) -> Result<Vec<f32>, LearningError> {
        let parameters = &self.checkpoint.parameters;
        let hidden_width = hidden.len();
        let mut logits = Vec::with_capacity(actions.len());
        for action in actions {
            let mut logit = parameters
                .policy_action_bias
                .iter()
                .zip(action)
                .fold(0.0, |sum, (bias, feature)| sum + bias * feature);
            for (unit, hidden_value) in hidden.iter().enumerate().take(hidden_width) {
                let row = &parameters.policy_bilinear
                    [unit * ACTION_FEATURES_V1..(unit + 1) * ACTION_FEATURES_V1];
                let pre = row.iter().zip(action).fold(
                    *hidden_value + parameters.policy_hidden_bias[unit],
                    |sum, (w, x)| sum + w * x,
                );
                logit += parameters.policy_output_weights[unit] * pre.tanh();
            }
            logits.push(logit);
        }
        softmax_in_place(&mut logits)?;
        Ok(logits)
    }

    pub(crate) fn policy_context(&self, hidden: &[f32]) -> Vec<f32> {
        let hidden_width = self.checkpoint.hidden_features as usize;
        let mut context = vec![0.0; ACTION_FEATURES_V1];
        for (unit, hidden_value) in hidden.iter().enumerate().take(hidden_width) {
            let row = &self.checkpoint.parameters.policy_bilinear
                [unit * ACTION_FEATURES_V1..(unit + 1) * ACTION_FEATURES_V1];
            for (target, weight) in context.iter_mut().zip(row) {
                *target += hidden_value * weight;
            }
        }
        context
    }

    pub(crate) fn values(&self, hidden: &[f32], player_count: usize) -> Vec<f32> {
        (0..player_count)
            .map(|player| {
                let row = &self.checkpoint.parameters.value_weights
                    [player * hidden.len()..(player + 1) * hidden.len()];
                let logit = row.iter().zip(hidden).fold(
                    self.checkpoint.parameters.value_bias[player],
                    |acc, (weight, feature)| acc + weight * feature,
                );
                sigmoid(logit)
            })
            .collect()
    }

    pub(crate) fn value_hidden(&self, observation: &[f32]) -> Vec<f32> {
        if self.checkpoint.model_architecture_version != Some(2) {
            return self.hidden(observation);
        }
        let hidden = self.checkpoint.hidden_features as usize;
        let parameters = &self.checkpoint.parameters;
        let mut output = vec![0.0; hidden];
        for (unit, target) in output.iter_mut().enumerate() {
            let row = &parameters.value_encoder_weights
                [unit * OBSERVATION_FEATURES_V1..(unit + 1) * OBSERVATION_FEATURES_V1];
            *target = row
                .iter()
                .zip(observation)
                .fold(parameters.value_encoder_bias[unit], |sum, (w, x)| {
                    sum + w * x
                })
                .tanh();
        }
        output
    }

    pub(crate) fn checkpoint_mut(&mut self) -> &mut PolicyValueCheckpointV1 {
        &mut self.checkpoint
    }
}

pub fn model_checkpoint_hash_v1(
    checkpoint: &PolicyValueCheckpointV1,
) -> Result<String, LearningError> {
    checkpoint.validate()?;
    let json = serde_json::to_vec(checkpoint)
        .map_err(|error| LearningError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-policy-value-checkpoint-v1\0");
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

pub(crate) fn initialize_checkpoint(
    model_id: String,
    hidden: usize,
    init_seed: u64,
) -> PolicyValueCheckpointV1 {
    let mut rng = SplitMix64::new(init_seed);
    let encoder_scale = (6.0 / (OBSERVATION_FEATURES_V1 + hidden) as f32).sqrt();
    let policy_scale = (6.0 / (hidden + ACTION_FEATURES_V1) as f32).sqrt();
    let value_scale = (6.0 / (hidden + MAX_PLAYERS_V1) as f32).sqrt();
    PolicyValueCheckpointV1 {
        format: POLICY_VALUE_CHECKPOINT_FORMAT.into(),
        version: POLICY_VALUE_CHECKPOINT_VERSION,
        model_id,
        representation_version: REPRESENTATION_VERSION_V1.into(),
        observation_features: OBSERVATION_FEATURES_V1 as u32,
        action_features: ACTION_FEATURES_V1 as u32,
        hidden_features: hidden as u32,
        max_players: MAX_PLAYERS_V1 as u8,
        source_dataset_id: String::new(),
        source_dataset_hash: String::new(),
        league_manifest_hash: String::new(),
        evaluation_plan_hash: String::new(),
        evaluation_report_hash: String::new(),
        training_config_hash: String::new(),
        training_contract_version: None,
        search_teacher_targets_hash: None,
        model_architecture_version: None,
        trained_examples: 0,
        validation_examples: 0,
        validation_seed_modulus: 0,
        validation_seed_remainder: 0,
        epochs: 0,
        parameters: ModelParametersV1 {
            encoder_weights: random_vector(
                &mut rng,
                hidden * OBSERVATION_FEATURES_V1,
                encoder_scale,
            ),
            encoder_bias: vec![0.0; hidden],
            policy_bilinear: random_vector(&mut rng, hidden * ACTION_FEATURES_V1, policy_scale),
            policy_action_bias: vec![0.0; ACTION_FEATURES_V1],
            value_weights: random_vector(&mut rng, MAX_PLAYERS_V1 * hidden, value_scale),
            value_bias: vec![0.0; MAX_PLAYERS_V1],
            policy_hidden_bias: Vec::new(),
            policy_output_weights: Vec::new(),
            value_encoder_weights: Vec::new(),
            value_encoder_bias: Vec::new(),
        },
    }
}

pub(crate) fn initialize_checkpoint_v2(
    model_id: String,
    hidden: usize,
    init_seed: u64,
) -> PolicyValueCheckpointV1 {
    let mut checkpoint = initialize_checkpoint(model_id, hidden, init_seed);
    let mut rng = SplitMix64::new(init_seed ^ 0x6d31_3564_6172_6368);
    let encoder_scale = (6.0 / (OBSERVATION_FEATURES_V1 + hidden) as f32).sqrt();
    let output_scale = (6.0 / (hidden + 1) as f32).sqrt();
    checkpoint.model_architecture_version = Some(2);
    checkpoint.parameters.policy_hidden_bias = vec![0.0; hidden];
    checkpoint.parameters.policy_output_weights = random_vector(&mut rng, hidden, output_scale);
    checkpoint.parameters.value_encoder_weights =
        random_vector(&mut rng, hidden * OBSERVATION_FEATURES_V1, encoder_scale);
    checkpoint.parameters.value_encoder_bias = vec![0.0; hidden];
    checkpoint
}

fn validate_parameters(
    parameters: &ModelParametersV1,
    hidden: usize,
    architecture_version: Option<u32>,
) -> Result<(), LearningError> {
    let shapes = [
        (
            "encoder_weights",
            parameters.encoder_weights.len(),
            hidden * OBSERVATION_FEATURES_V1,
        ),
        ("encoder_bias", parameters.encoder_bias.len(), hidden),
        (
            "policy_bilinear",
            parameters.policy_bilinear.len(),
            hidden * ACTION_FEATURES_V1,
        ),
        (
            "policy_action_bias",
            parameters.policy_action_bias.len(),
            ACTION_FEATURES_V1,
        ),
        (
            "value_weights",
            parameters.value_weights.len(),
            MAX_PLAYERS_V1 * hidden,
        ),
        ("value_bias", parameters.value_bias.len(), MAX_PLAYERS_V1),
    ];
    for (name, found, expected) in shapes {
        if found != expected {
            return Err(invalid_checkpoint(format!(
                "{name} length {found} does not match {expected}"
            )));
        }
    }
    let v2_shapes = [
        (
            "policy_hidden_bias",
            parameters.policy_hidden_bias.len(),
            hidden,
        ),
        (
            "policy_output_weights",
            parameters.policy_output_weights.len(),
            hidden,
        ),
        (
            "value_encoder_weights",
            parameters.value_encoder_weights.len(),
            hidden * OBSERVATION_FEATURES_V1,
        ),
        (
            "value_encoder_bias",
            parameters.value_encoder_bias.len(),
            hidden,
        ),
    ];
    for (name, found, expected) in v2_shapes {
        let expected = if architecture_version == Some(2) {
            expected
        } else {
            0
        };
        if found != expected {
            return Err(invalid_checkpoint(format!(
                "{name} length {found} does not match {expected}"
            )));
        }
    }
    if parameters
        .encoder_weights
        .iter()
        .chain(&parameters.encoder_bias)
        .chain(&parameters.policy_bilinear)
        .chain(&parameters.policy_action_bias)
        .chain(&parameters.value_weights)
        .chain(&parameters.value_bias)
        .chain(&parameters.policy_hidden_bias)
        .chain(&parameters.policy_output_weights)
        .chain(&parameters.value_encoder_weights)
        .chain(&parameters.value_encoder_bias)
        .any(|value| !value.is_finite())
    {
        return Err(invalid_checkpoint("parameters contain a non-finite value"));
    }
    Ok(())
}

fn validate_hash(label: &str, value: &str) -> Result<(), LearningError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid_checkpoint(format!(
            "{label} is not lowercase SHA-256"
        )));
    }
    Ok(())
}

fn validate_label(label: &str, value: &str) -> Result<(), LearningError> {
    if value.trim().is_empty() || value.len() > 128 || value.bytes().any(|byte| byte < 0x20) {
        return Err(invalid_checkpoint(format!("{label} is invalid")));
    }
    Ok(())
}

fn softmax_in_place(values: &mut [f32]) -> Result<(), LearningError> {
    if values.is_empty() || values.iter().any(|value| !value.is_finite()) {
        return Err(invalid_checkpoint(
            "checkpoint produced non-finite policy logits",
        ));
    }
    let max = values.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let mut sum = 0.0f32;
    for value in values.iter_mut() {
        *value = (*value - max).exp();
        sum += *value;
    }
    if !sum.is_finite() || sum <= 0.0 {
        return Err(invalid_checkpoint(
            "checkpoint produced an invalid policy normalization",
        ));
    }
    for value in values {
        *value /= sum;
        if !value.is_finite() {
            return Err(invalid_checkpoint(
                "checkpoint produced a non-finite policy probability",
            ));
        }
    }
    Ok(())
}

pub(crate) fn sigmoid(value: f32) -> f32 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exp = value.exp();
        exp / (1.0 + exp)
    }
}

struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
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

    fn symmetric_f32(&mut self, scale: f32) -> f32 {
        let unit = ((self.next_u64() >> 40) as u32) as f32 / ((1u32 << 24) - 1) as f32;
        (unit * 2.0 - 1.0) * scale
    }
}

fn random_vector(rng: &mut SplitMix64, length: usize, scale: f32) -> Vec<f32> {
    (0..length).map(|_| rng.symmetric_f32(scale)).collect()
}

#[cfg(test)]
mod tests {
    use splendor_core::{FullState, GameConfig, PlayerId};

    use super::*;

    #[test]
    fn extreme_finite_checkpoint_fails_closed_at_inference() {
        let mut checkpoint = initialize_checkpoint("extreme-finite".into(), 2, 1);
        checkpoint.source_dataset_id = "dataset".into();
        checkpoint.source_dataset_hash = "11".repeat(32);
        checkpoint.league_manifest_hash = "22".repeat(32);
        checkpoint.evaluation_plan_hash = "33".repeat(32);
        checkpoint.evaluation_report_hash = "44".repeat(32);
        checkpoint.training_config_hash = "55".repeat(32);
        checkpoint.trained_examples = 1;
        checkpoint.validation_examples = 1;
        checkpoint.validation_seed_modulus = 2;
        checkpoint.validation_seed_remainder = 0;
        checkpoint.epochs = 1;
        checkpoint.parameters.encoder_weights.fill(0.0);
        checkpoint.parameters.encoder_bias.fill(1.0);
        checkpoint.parameters.policy_bilinear.fill(f32::MAX);
        checkpoint.validate().unwrap();

        let model = PolicyValueModelV1::from_checkpoint(checkpoint).unwrap();
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let result = model.predict(&state.observation(PlayerId(0)), &state.legal_actions());
        assert!(matches!(result, Err(LearningError::InvalidCheckpoint(_))));
    }
}
