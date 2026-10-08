//! Strict, float32 inference for the Prism v0.1 numerical contract.
//! Entity encodings and all root-only projections are shared by every action.

use crate::encoding::{
    catalog_fingerprint, EncodedState, ACTION_DIM, ACTION_SCHEMA, ENTITY_DIM, OBS_SCHEMA,
};
use serde::de::{self, MapAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::BTreeMap;
use std::fmt;
use std::path::Path;

const H: usize = 128;
const BLOCKS: usize = 2;
const NORM_EPS: f32 = 1e-5;
type Hidden = [f32; H];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Prediction {
    pub logits: Vec<f32>,
    pub value: f32,
}

/// Validated weights. Construction is possible only through the strict loader.
#[derive(Debug, Clone)]
pub struct PrismWeights {
    encoder: Linear,
    blocks: [Block; BLOCKS],
    action: Linear,
    target: Linear,
    global_action: Linear,
    key: Linear,
    entity_value: Linear,
    policy_hidden: Linear,
    policy_out: Linear,
    value_hidden: Linear,
    value_out: Linear,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WeightFile {
    format: String,
    observation_schema: String,
    action_schema: String,
    catalog_fingerprint: String,
    hidden_dim: usize,
    num_blocks: usize,
    entity_dim: usize,
    action_dim: usize,
    #[serde(deserialize_with = "unique_tensors")]
    state_dict: BTreeMap<String, Tensor>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Tensor {
    shape: Vec<usize>,
    data: Vec<f32>,
}

// Serde's derived structs also accept positional arrays; the weight format
// requires named JSON objects at both the file and tensor levels.
struct Object<T>(T);

impl<'de, T: Deserialize<'de>> Deserialize<'de> for Object<T> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ObjectVisitor<T>(std::marker::PhantomData<T>);
        impl<'de, T: Deserialize<'de>> Visitor<'de> for ObjectVisitor<T> {
            type Value = Object<T>;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a JSON object")
            }

            fn visit_map<M: MapAccess<'de>>(self, map: M) -> Result<Self::Value, M::Error> {
                T::deserialize(de::value::MapAccessDeserializer::new(map)).map(Object)
            }
        }
        deserializer.deserialize_map(ObjectVisitor(std::marker::PhantomData))
    }
}

// Unlike ordinary map deserialization, duplicate tensor names must not silently
// overwrite earlier values. Derived structs already reject duplicate fields.
fn unique_tensors<'de, D>(deserializer: D) -> Result<BTreeMap<String, Tensor>, D::Error>
where
    D: Deserializer<'de>,
{
    struct TensorVisitor;
    impl<'de> Visitor<'de> for TensorVisitor {
        type Value = BTreeMap<String, Tensor>;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("a state_dict with unique tensor names")
        }

        fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
            let mut tensors = BTreeMap::new();
            while let Some((key, Object(tensor))) = map.next_entry::<String, Object<Tensor>>()? {
                if tensors.contains_key(&key) {
                    return Err(de::Error::custom(format!("duplicate tensor {key}")));
                }
                tensors.insert(key, tensor);
            }
            Ok(tensors)
        }
    }
    deserializer.deserialize_map(TensorVisitor)
}

impl PrismWeights {
    pub fn load(path: &Path) -> Result<Self, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|error| format!("cannot read Prism weights {}: {error}", path.display()))?;
        Self::from_json(&text)
            .map_err(|error| format!("invalid Prism weights {}: {error}", path.display()))
    }

    pub fn from_json(text: &str) -> Result<Self, String> {
        let Object(file): Object<WeightFile> = serde_json::from_str(text)
            .map_err(|error| format!("invalid Prism weights JSON: {error}"))?;
        for (field, actual, expected) in [
            ("format", file.format.as_str(), "prism-weights-v1"),
            (
                "observation_schema",
                file.observation_schema.as_str(),
                OBS_SCHEMA,
            ),
            ("action_schema", file.action_schema.as_str(), ACTION_SCHEMA),
        ] {
            if actual != expected {
                return Err(format!("{field}: expected {expected:?}, got {actual:?}"));
            }
        }
        if file.catalog_fingerprint != catalog_fingerprint() {
            return Err("catalog_fingerprint does not match the current catalog/ruleset".into());
        }
        for (field, actual, expected) in [
            ("hidden_dim", file.hidden_dim, H),
            ("num_blocks", file.num_blocks, BLOCKS),
            ("entity_dim", file.entity_dim, ENTITY_DIM),
            ("action_dim", file.action_dim, ACTION_DIM),
        ] {
            if actual != expected {
                return Err(format!("{field}: expected {expected}, got {actual}"));
            }
        }
        let mut tensors = file.state_dict;
        let weights = Self {
            encoder: Linear::load(&mut tensors, "encoder", ENTITY_DIM, H)?,
            blocks: [Block::load(&mut tensors, 0)?, Block::load(&mut tensors, 1)?],
            action: Linear::load(&mut tensors, "action", ACTION_DIM, H)?,
            target: Linear::load(&mut tensors, "target", H, H)?,
            global_action: Linear::load(&mut tensors, "global_action", H, H)?,
            key: Linear::load(&mut tensors, "key", H, H)?,
            entity_value: Linear::load(&mut tensors, "entity_value", H, H)?,
            policy_hidden: Linear::load(&mut tensors, "policy_hidden", 3 * H, H)?,
            policy_out: Linear::load(&mut tensors, "policy_out", H, 1)?,
            value_hidden: Linear::load(&mut tensors, "value_hidden", H, H)?,
            value_out: Linear::load(&mut tensors, "value_out", H, 1)?,
        };
        if !tensors.is_empty() {
            return Err(format!(
                "unexpected state_dict keys: {:?}",
                tensors.keys().collect::<Vec<_>>()
            ));
        }
        Ok(weights)
    }

    /// Scores precisely the supplied legal-action rows, in their original order.
    /// No padding, action softmax, fallback model, or game-rule logic is applied.
    pub fn predict(&self, input: &EncodedState) -> Result<Prediction, String> {
        input.validate()?;
        let mut entities = vec![[0.0; H]; input.entities.len()];
        for (features, hidden) in input.entities.iter().zip(&mut entities) {
            self.encoder.forward(features, hidden)?;
            relu(hidden);
        }
        for block in &self.blocks {
            block.forward(&mut entities)?;
        }
        let global = mean(&entities)?;
        let keys = self.key.project(&entities)?;
        let values = self.entity_value.project(&entities)?;
        let targets = self.target.project(&entities)?;
        let mut global_query = [0.0; H];
        self.global_action.forward(&global, &mut global_query)?;

        let mut value_hidden = [0.0; H];
        self.value_hidden.forward(&global, &mut value_hidden)?;
        relu(&mut value_hidden);
        let mut value_logit = [0.0];
        self.value_out.forward(&value_hidden, &mut value_logit)?;
        let value = sigmoid(value_logit[0]);

        // Reuse action scratch storage; no per-action entity recomputation or
        // heap allocation. concat's global tail is also constant for this root.
        let mut query = [0.0; H];
        let mut readout = [0.0; H];
        let mut scores = vec![0.0; entities.len()];
        let mut concat = [0.0; 3 * H];
        concat[2 * H..].copy_from_slice(&global);
        let mut policy_hidden = [0.0; H];
        let mut policy_logit = [0.0];
        let mut logits = Vec::with_capacity(input.actions.len());
        for (action, &target) in input.actions.iter().zip(&input.targets) {
            self.action.forward(action, &mut query)?;
            // target(0) is its bias, NOT a zero projected embedding.
            let target_query: &[f32] = if target == -1 {
                &self.target.bias
            } else {
                &targets[target as usize]
            };
            for j in 0..H {
                query[j] = query[j] + target_query[j] + global_query[j];
            }
            finite(&query, "action query")?;
            relu(&mut query);
            attend(&query, &keys, &values, &mut scores, &mut readout)?;
            concat[..H].copy_from_slice(&query);
            concat[H..2 * H].copy_from_slice(&readout);
            self.policy_hidden.forward(&concat, &mut policy_hidden)?;
            relu(&mut policy_hidden);
            self.policy_out.forward(&policy_hidden, &mut policy_logit)?;
            logits.push(policy_logit[0]);
        }
        Ok(Prediction { logits, value })
    }
}

fn take_tensor(
    tensors: &mut BTreeMap<String, Tensor>,
    key: &str,
    shape: &[usize],
) -> Result<Vec<f32>, String> {
    let tensor = tensors
        .remove(key)
        .ok_or_else(|| format!("missing tensor {key}"))?;
    if tensor.shape != shape {
        return Err(format!(
            "{key}: expected shape {shape:?}, got {:?}",
            tensor.shape
        ));
    }
    let count: usize = shape.iter().product();
    if tensor.data.len() != count {
        return Err(format!(
            "{key}: expected {count} values, got {}",
            tensor.data.len()
        ));
    }
    finite(&tensor.data, key)?;
    Ok(tensor.data)
}

#[derive(Debug, Clone)]
struct Linear {
    weight: Vec<f32>,
    bias: Vec<f32>,
}

impl Linear {
    fn load(
        tensors: &mut BTreeMap<String, Tensor>,
        name: &str,
        input: usize,
        output: usize,
    ) -> Result<Self, String> {
        Ok(Self {
            weight: take_tensor(tensors, &format!("{name}.weight"), &[output, input])?,
            bias: take_tensor(tensors, &format!("{name}.bias"), &[output])?,
        })
    }

    fn forward(&self, input: &[f32], output: &mut [f32]) -> Result<(), String> {
        debug_assert_eq!(self.bias.len(), output.len());
        debug_assert_eq!(self.weight.len(), input.len() * output.len());
        for ((row, bias), result) in self
            .weight
            .chunks_exact(input.len())
            .zip(&self.bias)
            .zip(output.iter_mut())
        {
            *result = dot(row, input) + bias;
        }
        // Check before ReLU/sigmoid could hide a negative infinity or NaN.
        finite(output, "linear output")
    }

    fn project(&self, entities: &[Hidden]) -> Result<Vec<Hidden>, String> {
        let mut result = vec![[0.0; H]; entities.len()];
        for (entity, output) in entities.iter().zip(&mut result) {
            self.forward(entity, output)?;
        }
        Ok(result)
    }
}

#[derive(Debug, Clone)]
struct Block {
    local: Linear,
    context: Linear,
    norm: LayerNorm,
}

impl Block {
    fn load(tensors: &mut BTreeMap<String, Tensor>, index: usize) -> Result<Self, String> {
        let prefix = format!("blocks.{index}");
        Ok(Self {
            local: Linear::load(tensors, &format!("{prefix}.local"), H, H)?,
            context: Linear::load(tensors, &format!("{prefix}.context"), H, H)?,
            norm: LayerNorm {
                weight: take_tensor(tensors, &format!("{prefix}.norm.weight"), &[H])?,
                bias: take_tensor(tensors, &format!("{prefix}.norm.bias"), &[H])?,
            },
        })
    }

    fn forward(&self, entities: &mut [Hidden]) -> Result<(), String> {
        let global = mean(entities)?;
        let mut context = [0.0; H];
        self.context.forward(&global, &mut context)?;
        let mut local = [0.0; H];
        for entity in entities {
            self.local.forward(entity, &mut local)?;
            for j in 0..H {
                local[j] += context[j];
            }
            finite(&local, "residual activation")?;
            for j in 0..H {
                entity[j] += local[j].max(0.0);
            }
            finite(entity, "residual sum")?;
            self.norm.forward(entity)?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
struct LayerNorm {
    weight: Vec<f32>,
    bias: Vec<f32>,
}

impl LayerNorm {
    fn forward(&self, row: &mut Hidden) -> Result<(), String> {
        let mean = row.iter().sum::<f32>() / H as f32;
        let variance = row.iter().map(|x| (x - mean) * (x - mean)).sum::<f32>() / H as f32;
        finite(&[mean, variance], "LayerNorm moments")?;
        let inverse_std = (variance + NORM_EPS).sqrt().recip();
        for (j, x) in row.iter_mut().enumerate() {
            *x = (*x - mean) * inverse_std * self.weight[j] + self.bias[j];
        }
        finite(row, "LayerNorm output")
    }
}

fn finite(values: &[f32], stage: &str) -> Result<(), String> {
    if values.iter().all(|x| x.is_finite()) {
        Ok(())
    } else {
        Err(format!("non-finite value in {stage}"))
    }
}

fn relu(row: &mut [f32]) {
    for x in row {
        *x = x.max(0.0);
    }
}

#[inline]
fn dot(left: &[f32], right: &[f32]) -> f32 {
    // Independent accumulators allow instruction-level parallelism, while all
    // products and reductions remain float32 (no platform-specific SIMD/FMA).
    let mut sums = [0.0f32; 4];
    let mut a = left.chunks_exact(4);
    let mut b = right.chunks_exact(4);
    for (x, y) in a.by_ref().zip(b.by_ref()) {
        for j in 0..4 {
            sums[j] += x[j] * y[j];
        }
    }
    let mut result = (sums[0] + sums[1]) + (sums[2] + sums[3]);
    for (x, y) in a.remainder().iter().zip(b.remainder()) {
        result += x * y;
    }
    result
}

fn mean(entities: &[Hidden]) -> Result<Hidden, String> {
    let mut result = [0.0; H];
    for row in entities {
        for (sum, x) in result.iter_mut().zip(row) {
            *sum += x;
        }
    }
    for x in &mut result {
        *x /= entities.len() as f32;
    }
    finite(&result, "entity mean")?;
    Ok(result)
}

fn attend(
    query: &Hidden,
    keys: &[Hidden],
    values: &[Hidden],
    scores: &mut [f32],
    output: &mut Hidden,
) -> Result<(), String> {
    let scale = (H as f32).sqrt().recip();
    for (score, key) in scores.iter_mut().zip(keys) {
        *score = dot(query, key) * scale;
    }
    finite(scores, "attention scores")?;
    let maximum = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let mut sum = 0.0;
    for score in scores.iter_mut() {
        *score = (*score - maximum).exp();
        sum += *score;
    }
    output.fill(0.0);
    for (score, value) in scores.iter().zip(values) {
        let probability = score / sum;
        for (result, x) in output.iter_mut().zip(value) {
            *result += probability * x;
        }
    }
    finite(output, "attention readout")
}

fn sigmoid(logit: f32) -> f32 {
    if logit >= 0.0 {
        1.0 / (1.0 + (-logit).exp())
    } else {
        let exponential = logit.exp();
        exponential / (1.0 + exponential)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

    fn zero_json() -> Value {
        let mut tensors = serde_json::Map::new();
        let mut add = |name: &str, shape: Vec<usize>| {
            let count: usize = shape.iter().product();
            tensors.insert(
                name.into(),
                json!({"shape": shape, "data": vec![0.0f32; count]}),
            );
        };
        for (name, input, output) in [
            ("encoder", ENTITY_DIM, H),
            ("blocks.0.local", H, H),
            ("blocks.0.context", H, H),
            ("blocks.1.local", H, H),
            ("blocks.1.context", H, H),
            ("action", ACTION_DIM, H),
            ("target", H, H),
            ("global_action", H, H),
            ("key", H, H),
            ("entity_value", H, H),
            ("policy_hidden", 3 * H, H),
            ("policy_out", H, 1),
            ("value_hidden", H, H),
            ("value_out", H, 1),
        ] {
            add(&format!("{name}.weight"), vec![output, input]);
            add(&format!("{name}.bias"), vec![output]);
        }
        for block in 0..BLOCKS {
            add(&format!("blocks.{block}.norm.weight"), vec![H]);
            add(&format!("blocks.{block}.norm.bias"), vec![H]);
        }
        json!({
            "format": "prism-weights-v1", "observation_schema": OBS_SCHEMA,
            "action_schema": ACTION_SCHEMA, "catalog_fingerprint": catalog_fingerprint(),
            "hidden_dim": H, "num_blocks": BLOCKS, "entity_dim": ENTITY_DIM,
            "action_dim": ACTION_DIM, "state_dict": tensors
        })
    }

    fn model(json: &Value) -> PrismWeights {
        PrismWeights::from_json(&json.to_string()).unwrap()
    }

    fn set(json: &mut Value, key: &str, index: usize, value: f32) {
        json["state_dict"][key]["data"][index] = json!(value);
    }

    fn fixture() -> EncodedState {
        EncodedState {
            entities: (0..4)
                .map(|i| {
                    (0..ENTITY_DIM)
                        .map(|j| ((i * 29 + j * 7) % 41) as f32 / 41.0)
                        .collect()
                })
                .collect(),
            actions: (0..5)
                .map(|i| {
                    (0..ACTION_DIM)
                        .map(|j| ((i * 13 + j * 3) % 31) as f32 / 31.0)
                        .collect()
                })
                .collect(),
            targets: vec![-1, 2, 0, 3, 1],
        }
    }

    fn nonzero_json() -> Value {
        let mut value = zero_json();
        for (name, tensor) in value["state_dict"].as_object_mut().unwrap() {
            let mut state = name.bytes().fold(17u32, |s, byte| {
                s.wrapping_mul(31).wrapping_add(byte as u32)
            });
            for number in tensor["data"].as_array_mut().unwrap() {
                state = state.wrapping_mul(1664525).wrapping_add(1013904223);
                let x = (((state >> 16) % 2001) as f32 - 1000.0) / 25000.0;
                *number = json!(if name.ends_with("norm.weight") {
                    1.0 + x
                } else {
                    x
                });
            }
        }
        value
    }

    fn close(actual: f32, expected: f32) {
        assert!(
            (actual - expected).abs() <= 1e-4 + 1e-4 * expected.abs(),
            "{actual} != {expected}"
        );
    }

    #[test]
    fn zero_weights_and_prediction_serde() {
        let prediction = model(&zero_json()).predict(&fixture()).unwrap();
        assert_eq!(prediction.logits, vec![0.0; 5]);
        assert_eq!(prediction.value, 0.5);
        assert_eq!(
            serde_json::to_value(&prediction).unwrap(),
            json!({"logits": vec![0.0; 5], "value": 0.5})
        );
        assert_eq!(
            serde_json::from_str::<Prediction>(&serde_json::to_string(&prediction).unwrap())
                .unwrap(),
            prediction
        );
    }

    #[test]
    fn biased_zero_target_and_concat_and_value_math() {
        let mut json = zero_json();
        for (key, index, x) in [
            ("blocks.1.norm.bias", 0, 2.0),
            ("action.bias", 0, 0.5),
            ("target.bias", 0, 1.25),
            ("global_action.bias", 0, 0.75),
            ("entity_value.bias", 0, 3.0),
            ("policy_hidden.weight", 0, 2.0),
            ("policy_hidden.weight", H, 3.0),
            ("policy_hidden.weight", 2 * H, 4.0),
            ("policy_hidden.bias", 0, -0.5),
            ("policy_out.weight", 0, 0.25),
            ("policy_out.bias", 0, -1.0),
            ("value_hidden.weight", 0, 0.5),
            ("value_hidden.bias", 0, -0.25),
            ("value_out.weight", 0, 2.0),
            ("value_out.bias", 0, -0.5),
        ] {
            set(&mut json, key, index, x);
        }
        let prediction = model(&json).predict(&fixture()).unwrap();
        for logit in prediction.logits {
            close(logit, 4.375);
        }
        close(prediction.value, 0.7310586);
    }

    #[test]
    fn row_major_linear_and_layer_norm_population_variance() {
        let linear = Linear {
            weight: vec![1.0, 2.0, 3.0, -1.0, 0.5, 2.0],
            bias: vec![0.25, -0.5],
        };
        let mut output = [0.0; 2];
        linear.forward(&[2.0, 3.0, 4.0], &mut output).unwrap();
        assert_eq!(output, [20.25, 7.0]);
        let norm = LayerNorm {
            weight: vec![2.0; H],
            bias: vec![0.5; H],
        };
        for magnitude in [1.0f32, 0.0001] {
            let mut row = std::array::from_fn(|j| if j % 2 == 0 { magnitude } else { -magnitude });
            norm.forward(&mut row).unwrap();
            for (j, &x) in row.iter().enumerate() {
                let sign = if j % 2 == 0 { 1.0 } else { -1.0 };
                close(
                    x,
                    0.5 + sign * 2.0 * magnitude / (magnitude * magnitude + NORM_EPS).sqrt(),
                );
            }
        }
        let mut constant = [3.0; H];
        norm.forward(&mut constant).unwrap();
        assert_eq!(constant, [0.5; H]);
    }

    #[test]
    fn attention_scaling_and_extreme_softmax_sigmoid_are_stable() {
        let mut query = [0.0; H];
        query[0] = (H as f32).sqrt();
        let mut keys = [[0.0; H]; 2];
        keys[1][0] = 3.0f32.ln();
        let values = [[2.0; H], [6.0; H]];
        let mut scores = [0.0; 2];
        let mut output = [0.0; H];
        attend(&query, &keys, &values, &mut scores, &mut output).unwrap();
        close(output[0], 5.0);
        query[0] = 1e10;
        keys[0][0] = -1e10;
        keys[1][0] = 1e10;
        attend(&query, &keys, &values, &mut scores, &mut output).unwrap();
        assert_eq!(output, [6.0; H]);
        assert_eq!(sigmoid(1000.0), 1.0);
        assert_eq!(sigmoid(-1000.0), 0.0);
        assert_eq!(sigmoid(0.0), 0.5);
    }

    #[test]
    fn entity_target_and_action_permutations_are_equivariant() {
        let weights = model(&nonzero_json());
        let input = fixture();
        let expected = weights.predict(&input).unwrap();
        assert!(expected
            .logits
            .windows(2)
            .any(|pair| (pair[0] - pair[1]).abs() > 1e-5));
        let entity_order = [2, 0, 3, 1];
        let action_order = [3, 0, 4, 1, 2];
        let mut inverse = [0; 4];
        for (new, &old) in entity_order.iter().enumerate() {
            inverse[old] = new as i32;
        }
        let permuted = EncodedState {
            entities: entity_order
                .iter()
                .map(|&i| input.entities[i].clone())
                .collect(),
            actions: action_order
                .iter()
                .map(|&i| input.actions[i].clone())
                .collect(),
            targets: action_order
                .iter()
                .map(|&i| {
                    if input.targets[i] == -1 {
                        -1
                    } else {
                        inverse[input.targets[i] as usize]
                    }
                })
                .collect(),
        };
        let actual = weights.predict(&permuted).unwrap();
        close(actual.value, expected.value);
        for (new, &old) in action_order.iter().enumerate() {
            close(actual.logits[new], expected.logits[old]);
        }
        assert_eq!(weights.predict(&input).unwrap(), expected);
        // A single action's score and the root value do not depend on peers.
        let single = EncodedState {
            entities: input.entities.clone(),
            actions: vec![input.actions[2].clone()],
            targets: vec![input.targets[2]],
        };
        let one = weights.predict(&single).unwrap();
        close(one.logits[0], expected.logits[2]);
        close(one.value, expected.value);
        let mut rebound = input;
        rebound.targets[0] = 0;
        assert!((weights.predict(&rebound).unwrap().logits[0] - expected.logits[0]).abs() > 1e-5);
    }

    #[test]
    fn rejects_wrong_metadata_and_missing_or_extra_fields() {
        let base = zero_json();
        for field in [
            "format",
            "observation_schema",
            "action_schema",
            "catalog_fingerprint",
        ] {
            let mut bad = base.clone();
            bad[field] = json!("wrong");
            assert!(PrismWeights::from_json(&bad.to_string())
                .unwrap_err()
                .contains(field));
        }
        for field in ["hidden_dim", "num_blocks", "entity_dim", "action_dim"] {
            let mut bad = base.clone();
            bad[field] = json!(0);
            assert!(PrismWeights::from_json(&bad.to_string())
                .unwrap_err()
                .contains(field));
        }
        for field in base.as_object().unwrap().keys() {
            let mut bad = base.clone();
            bad.as_object_mut().unwrap().remove(field);
            assert!(
                PrismWeights::from_json(&bad.to_string()).is_err(),
                "missing {field}"
            );
        }
        let mut bad = base.clone();
        bad["extra"] = json!(true);
        assert!(PrismWeights::from_json(&bad.to_string()).is_err());
        let mut bad = base;
        bad["state_dict"]["encoder.bias"]["extra"] = json!(0);
        assert!(PrismWeights::from_json(&bad.to_string()).is_err());
    }

    #[test]
    fn rejects_every_missing_key_and_wrong_shape_and_extra_key() {
        let base = zero_json();
        assert_eq!(base["state_dict"].as_object().unwrap().len(), 32);
        for key in base["state_dict"].as_object().unwrap().keys() {
            let mut bad = base.clone();
            bad["state_dict"].as_object_mut().unwrap().remove(key);
            assert!(PrismWeights::from_json(&bad.to_string())
                .unwrap_err()
                .contains(key));
            let mut bad = base.clone();
            bad["state_dict"][key]["shape"][0] = json!(999);
            assert!(PrismWeights::from_json(&bad.to_string())
                .unwrap_err()
                .contains(key));
        }
        let mut bad = base.clone();
        bad["state_dict"]["blocks.2.norm.bias"] = json!({"shape": [H], "data": vec![0.0; H]});
        assert!(PrismWeights::from_json(&bad.to_string())
            .unwrap_err()
            .contains("unexpected"));
        for field in ["shape", "data"] {
            let mut bad = base.clone();
            bad["state_dict"]["encoder.bias"]
                .as_object_mut()
                .unwrap()
                .remove(field);
            assert!(PrismWeights::from_json(&bad.to_string()).is_err());
        }
        for count in [H - 1, H + 1] {
            let mut bad = base.clone();
            bad["state_dict"]["encoder.bias"]["data"] = json!(vec![0.0; count]);
            assert!(PrismWeights::from_json(&bad.to_string())
                .unwrap_err()
                .contains("encoder.bias"));
        }
        let mut bad = base;
        bad["state_dict"]["encoder.weight"]["shape"] = json!([ENTITY_DIM, H]);
        assert!(PrismWeights::from_json(&bad.to_string()).is_err());
    }

    #[test]
    fn rejects_nonfinite_invalid_json_and_duplicate_keys() {
        let base = zero_json().to_string();
        for token in [
            "1e100", "-1e100", "1e999", "NaN", "Infinity", "null", "\"NaN\"", "true",
        ] {
            let bad = base.replacen("\"data\":[0.0", &format!("\"data\":[{token}"), 1);
            assert_ne!(bad, base);
            assert!(PrismWeights::from_json(&bad).is_err(), "accepted {token}");
        }
        for bad in ["", "{}", "null", "[]", "{", "{\"format\": 1}"] {
            assert!(PrismWeights::from_json(bad).is_err());
        }
        assert!(PrismWeights::from_json(&(base.clone() + "{}")).is_err());
        let duplicate = format!(
            "\"state_dict\":{{\"encoder.bias\":{},",
            zero_json()["state_dict"]["encoder.bias"]
        );
        let bad = base.replacen("\"state_dict\":{", &duplicate, 1);
        assert!(PrismWeights::from_json(&bad)
            .unwrap_err()
            .contains("duplicate tensor"));
        let bad = base.replacen('{', "{\"format\":\"prism-weights-v1\",", 1);
        assert!(PrismWeights::from_json(&bad)
            .unwrap_err()
            .contains("duplicate field"));
        let bad = base.replacen("\"shape\":[", "\"data\":[],\"shape\":[", 1);
        assert!(PrismWeights::from_json(&bad)
            .unwrap_err()
            .contains("duplicate field"));
    }

    #[test]
    fn invalid_inputs_and_numerical_overflow_fail_closed() {
        let weights = model(&zero_json());
        let mut invalid = Vec::new();
        let mut input = fixture();
        input.entities.clear();
        invalid.push(input);
        let mut input = fixture();
        input.actions.clear();
        input.targets.clear();
        invalid.push(input);
        let mut input = fixture();
        input.entities[0].pop();
        invalid.push(input);
        let mut input = fixture();
        input.actions[0].push(0.0);
        invalid.push(input);
        let mut input = fixture();
        input.targets.pop();
        invalid.push(input);
        for target in [-2, 4, i32::MAX] {
            let mut input = fixture();
            input.targets[0] = target;
            invalid.push(input);
        }
        for number in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            let mut input = fixture();
            input.entities[0][0] = number;
            invalid.push(input);
            let mut input = fixture();
            input.actions[0][0] = number;
            invalid.push(input);
        }
        let mut input = fixture();
        input.entities = vec![vec![0.0; ENTITY_DIM]; 129];
        invalid.push(input);
        let mut input = fixture();
        input.actions = vec![vec![0.0; ACTION_DIM]; 4097];
        input.targets = vec![-1; 4097];
        invalid.push(input);
        for input in invalid {
            assert!(weights.predict(&input).is_err());
        }
        let mut json = zero_json();
        set(&mut json, "encoder.weight", 0, f32::MAX);
        let overflow = model(&json);
        let mut input = fixture();
        input.entities[0][0] = 2.0;
        assert!(overflow.predict(&input).unwrap_err().contains("non-finite"));
        // Overflow must not become a seemingly valid saturated sigmoid.
        let mut json = zero_json();
        set(&mut json, "value_hidden.bias", 0, 2.0);
        set(&mut json, "value_out.weight", 0, -f32::MAX);
        assert!(model(&json)
            .predict(&fixture())
            .unwrap_err()
            .contains("non-finite"));
    }

    #[test]
    fn file_loading_succeeds_and_io_errors_are_reported() {
        let directory = std::env::var_os("PI_SCRATCH_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = directory.join(format!(
            "prism-inference-test-{}-{nonce}.json",
            std::process::id()
        ));
        std::fs::write(&path, zero_json().to_string()).unwrap();
        let loaded = PrismWeights::load(&path);
        std::fs::remove_file(&path).unwrap();
        assert_eq!(loaded.unwrap().predict(&fixture()).unwrap().value, 0.5);
        assert!(PrismWeights::load(&path)
            .unwrap_err()
            .contains("cannot read"));
    }

    #[test]
    fn nonzero_forward_matches_pytorch_float32_golden() {
        // PyTorch 2.6.0 CPU, functional linear/layer_norm/softmax, eps=1e-5.
        // Reproduce weights with nonzero_json's per-key LCG and fixture's
        // integer feature formulas; no training or external fixture required.
        let prediction = model(&nonzero_json()).predict(&fixture()).unwrap();
        let expected = [
            -0.0029678177,
            0.0033168811,
            -0.00060646795,
            0.0025773663,
            -0.0061119236,
        ];
        for (actual, expected) in prediction.logits.iter().zip(expected) {
            close(*actual, expected);
        }
        close(prediction.value, 0.4962742);
    }

    #[test]
    fn rejects_positional_arrays_instead_of_named_objects() {
        let mut bad = zero_json();
        let positional: Vec<Value> = [
            "format",
            "observation_schema",
            "action_schema",
            "catalog_fingerprint",
            "hidden_dim",
            "num_blocks",
            "entity_dim",
            "action_dim",
            "state_dict",
        ]
        .iter()
        .map(|key| bad[*key].clone())
        .collect();
        assert!(PrismWeights::from_json(&json!(positional).to_string()).is_err());
        bad["state_dict"]["encoder.bias"] = json!([[H], vec![0.0; H]]);
        assert!(PrismWeights::from_json(&bad.to_string()).is_err());
    }
}
