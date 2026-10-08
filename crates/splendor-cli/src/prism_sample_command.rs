//! Independent Prism categorical-sampling agent. The existing `agent-prism`
//! remains greedy; this command uses only player-visible state and a keyed draw.
use std::collections::BTreeMap;
use std::fs::{File, OpenOptions};
use std::io::{self, BufReader, BufWriter, Write};
use std::path::Path;
use std::time::Instant;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use splendor_agent::{run_agent, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::Action;
use splendor_prism::{encode, PrismWeights};

const MAX_ACTION_SEED: u64 = i64::MAX as u64;

fn options(args: &[String]) -> Result<BTreeMap<String, String>, String> {
    if args.len() % 2 != 0 {
        return Err("every option requires a value".into());
    }
    let mut parsed = BTreeMap::new();
    for pair in args.chunks_exact(2) {
        if !["--weights", "--seed", "--decisions-out"].contains(&pair[0].as_str())
            || parsed.insert(pair[0].clone(), pair[1].clone()).is_some()
        {
            return Err(format!("unknown or repeated option {}", pair[0]));
        }
    }
    Ok(parsed)
}

fn required<'a>(opts: &'a BTreeMap<String, String>, key: &str) -> Result<&'a str, String> {
    opts.get(key)
        .map(String::as_str)
        .ok_or_else(|| format!("missing required {key}"))
}

fn new_writer(path: &Path) -> Result<BufWriter<File>, String> {
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map(BufWriter::new)
        .map_err(|error| format!("decisions output must be a new file: {error}"))
}

fn softmax_t1(logits: &[f32]) -> Result<Vec<f64>, String> {
    if logits.is_empty() || logits.iter().any(|value| !value.is_finite()) {
        return Err("policy logits must be nonempty and finite".into());
    }
    let max = logits
        .iter()
        .map(|value| f64::from(*value))
        .fold(f64::NEG_INFINITY, f64::max);
    let exponentials: Vec<f64> = logits
        .iter()
        .map(|value| (f64::from(*value) - max).exp())
        .collect();
    let total: f64 = exponentials.iter().sum();
    if !total.is_finite() || total <= 0.0 {
        return Err("softmax normalization is empty or nonfinite".into());
    }
    let probabilities: Vec<f64> = exponentials.iter().map(|value| value / total).collect();
    if probabilities
        .iter()
        .any(|value| !value.is_finite() || *value < 0.0)
    {
        return Err("softmax produced an invalid probability".into());
    }
    Ok(probabilities)
}

// Python's canonical_hash uses json.dumps(..., ensure_ascii=True); serde_json
// emits UTF-8 directly, so explicitly escape non-ASCII as Python-compatible
// lowercase UTF-16 \uXXXX escapes (including surrogate pairs).
fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>, String> {
    let serialized = serde_json::to_string(value).map_err(|error| error.to_string())?;
    let mut ascii = String::with_capacity(serialized.len());
    for character in serialized.chars() {
        if character.is_ascii() {
            ascii.push(character);
        } else {
            let mut utf16 = [0u16; 2];
            for unit in character.encode_utf16(&mut utf16).iter() {
                use std::fmt::Write as _;
                write!(&mut ascii, "\\u{unit:04x}").map_err(|error| error.to_string())?;
            }
        }
    }
    Ok(ascii.into_bytes())
}

fn draw_uniform(
    action_seed: u64,
    game_id: &str,
    viewer: u8,
    decision_index: u64,
) -> Result<f64, String> {
    let draw_key = json!([
        "prism-ppo-draw-v1",
        action_seed,
        game_id,
        viewer,
        decision_index
    ]);
    let bytes = canonical_json_bytes(&draw_key)?;
    let digest = Sha256::digest(bytes);
    let first_eight: [u8; 8] = digest[..8]
        .try_into()
        .map_err(|_| "SHA-256 returned an invalid digest length".to_string())?;
    let mantissa = u64::from_be_bytes(first_eight) >> 11;
    Ok(mantissa as f64 / (1u64 << 53) as f64)
}

fn categorical(probabilities: &[f64], uniform: f64) -> Result<usize, String> {
    if probabilities.is_empty()
        || !uniform.is_finite()
        || !(0.0..1.0).contains(&uniform)
        || probabilities
            .iter()
            .any(|probability| !probability.is_finite() || *probability < 0.0)
    {
        return Err("categorical input must be nonempty, finite, and normalized".into());
    }
    let total: f64 = probabilities.iter().sum();
    if !total.is_finite() || (total - 1.0).abs() > 1e-12 {
        return Err("categorical probabilities must sum to one".into());
    }
    let mut cumulative = 0.0;
    for (index, probability) in probabilities.iter().enumerate() {
        cumulative += probability;
        if uniform < cumulative {
            return Ok(index);
        }
    }
    // The only permitted fallback is a CDF endpoint caused by rounding.
    probabilities
        .iter()
        .rposition(|probability| *probability > 0.0)
        .ok_or_else(|| "categorical distribution has no positive probability".into())
}

struct PrismSamplePolicy {
    weights: PrismWeights,
    action_seed: u64,
    decision_index: u64,
    decisions: Option<BufWriter<File>>,
}

impl AgentPolicy for PrismSamplePolicy {
    type Error = String;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, String> {
        let decision_start = Instant::now();
        if context.legal_actions.is_empty() {
            return Err("agent received no legal actions".into());
        }
        let encoded = encode(
            &context.observation,
            context.visible_history,
            context.legal_actions,
        )?;
        let inference_start = Instant::now();
        let prediction = self.weights.predict(&encoded)?;
        let inference_us = inference_start.elapsed().as_secs_f64() * 1e6;
        if prediction.logits.len() != context.legal_actions.len() {
            return Err("prediction/legal actions mismatch".into());
        }
        if !prediction.value.is_finite() {
            return Err("network value is nonfinite".into());
        }
        let probabilities = softmax_t1(&prediction.logits)?;
        let viewer = context.observation.viewer.0;
        let uniform = draw_uniform(
            self.action_seed,
            &context.meta.game_id,
            viewer,
            self.decision_index,
        )?;
        let chosen_index = categorical(&probabilities, uniform)?;
        let chosen_probability = probabilities[chosen_index];
        if chosen_probability <= 0.0 {
            return Err("categorical draw selected a zero-probability action".into());
        }
        let log_prob = chosen_probability.ln();
        let chosen_action = context.legal_actions[chosen_index];
        let decision_us = decision_start.elapsed().as_secs_f64() * 1e6;

        if let Some(output) = &mut self.decisions {
            let encoded_bytes = serde_json::to_vec(&encoded).map_err(|error| error.to_string())?;
            let history_bytes =
                serde_json::to_vec(context.visible_history).map_err(|error| error.to_string())?;
            let row = json!({
                "format": "prism-sample-decision-v1",
                "sampling": "softmax-t1",
                "action_seed": self.action_seed,
                "game_id": context.meta.game_id,
                "request_id": context.meta.request_id,
                "actor": viewer,
                "decision_index": self.decision_index,
                "observation_hash": context.meta.observation_hash,
                "encoded_sha256": hex::encode(Sha256::digest(encoded_bytes)),
                "visible_history_count": context.visible_history.len(),
                "visible_history_sha256": hex::encode(Sha256::digest(history_bytes)),
                "observation": context.observation,
                "visible_history": context.visible_history,
                "legal_actions": context.legal_actions,
                "probabilities": probabilities,
                "log_prob": log_prob,
                "value": prediction.value,
                "chosen_index": chosen_index,
                "chosen_action": chosen_action,
                "inference_us": inference_us,
                "decision_us": decision_us
            });
            serde_json::to_writer(&mut *output, &row).map_err(|error| error.to_string())?;
            writeln!(output).map_err(|error| error.to_string())?;
            output.flush().map_err(|error| error.to_string())?;
        }
        self.decision_index = self
            .decision_index
            .checked_add(1)
            .ok_or_else(|| "own decision counter overflow".to_string())?;
        Ok(chosen_action)
    }
}

fn run_agent_command(args: &[String]) -> Result<(), String> {
    let opts = options(args)?;
    let weights = PrismWeights::load(Path::new(required(&opts, "--weights")?))?;
    let action_seed = required(&opts, "--seed")?
        .parse::<u64>()
        .map_err(|_| "--seed must be a u64 no greater than 2^63-1".to_string())?;
    if action_seed > MAX_ACTION_SEED {
        return Err("--seed must be a u64 no greater than 2^63-1".into());
    }
    let decisions = opts
        .get("--decisions-out")
        .map(|path| new_writer(Path::new(path)))
        .transpose()?;
    run_agent(
        BufReader::new(io::stdin().lock()),
        io::stdout().lock(),
        io::stderr().lock(),
        AgentIdentity {
            name: "prism-sample",
            version: "0.1.0",
        },
        action_seed,
        PrismSamplePolicy {
            weights,
            action_seed,
            decision_index: 0,
            decisions,
        },
    )
    .map_err(|error| error.to_string())
}

pub fn run(args: &[String]) -> i32 {
    match run_agent_command(args) {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{canonical_json_bytes, categorical, draw_uniform, softmax_t1};
    use serde_json::json;

    #[test]
    fn prism_sample_fixed_python_draw_vector() {
        assert_eq!(
            canonical_json_bytes(&json!(["é 🧪"])).unwrap(),
            br#"["\u00e9 \ud83e\uddea"]"#
        );
        let uniform = draw_uniform(54_010_001, "m54-fixed-greedy-v0-943001-seat0", 0, 17).unwrap();
        assert!((uniform - 0.12363746948680165).abs() < 1e-16);
        let probabilities = softmax_t1(&[0.0, 1.5f32.ln(), 2.5f32.ln()]).unwrap();
        assert_eq!(categorical(&probabilities, uniform).unwrap(), 0);
        assert_eq!(
            draw_uniform(54_010_002, "m54-fixed-greedy-v0-943001-seat0", 0, 17).unwrap(),
            0.9962993485691212
        );
    }

    #[test]
    fn prism_sample_draw_is_deterministic_and_seed_does_not_change_distribution() {
        let logits = [0.25, -0.75, 1.0];
        let probabilities = softmax_t1(&logits).unwrap();
        let repeat = softmax_t1(&logits).unwrap();
        assert_eq!(probabilities, repeat);
        let game_id = "fixed-job-1";
        let first_uniform = draw_uniform(54_010_001, game_id, 1, 9).unwrap();
        let second_uniform = draw_uniform(54_010_005, game_id, 1, 9).unwrap();
        assert_eq!(
            categorical(&probabilities, first_uniform).unwrap(),
            categorical(&probabilities, first_uniform).unwrap()
        );
        assert_ne!(first_uniform, second_uniform);
        assert_ne!(
            categorical(&probabilities, first_uniform).unwrap(),
            categorical(&probabilities, second_uniform).unwrap()
        );
        assert_eq!(probabilities, softmax_t1(&logits).unwrap());
    }

    #[test]
    fn prism_sample_equal_logits_reach_every_legal_index() {
        let probabilities = softmax_t1(&[0.0, 0.0, 0.0]).unwrap();
        let mut selected = [false; 3];
        for action_seed in 54_000_000..54_000_256 {
            let uniform = draw_uniform(action_seed, "equal-logit-game", 0, 0).unwrap();
            selected[categorical(&probabilities, uniform).unwrap()] = true;
        }
        assert_eq!(selected, [true; 3]);
    }

    #[test]
    fn prism_sample_extreme_logits_and_invalid_inputs() {
        let probabilities = softmax_t1(&[f32::MAX, -f32::MAX, 0.0]).unwrap();
        assert_eq!(probabilities, [1.0, 0.0, 0.0]);
        assert_eq!(categorical(&probabilities, 0.999_999).unwrap(), 0);
        assert!(softmax_t1(&[]).is_err());
        assert!(softmax_t1(&[f32::NAN]).is_err());
        assert!(softmax_t1(&[f32::INFINITY]).is_err());
        assert!(categorical(&[], 0.5).is_err());
        assert!(categorical(&[0.5, 0.4], 0.5).is_err());
        assert!(categorical(&[1.0], 1.0).is_err());
        assert!(categorical(&[0.0, 0.0], 0.5).is_err());
    }
}
