//! M50: Native Rust inference agent for the competitive Policy-Value network
//! with support for direct greedy policy, Policy-pruned 1-ply search, and
//! full IS-MCTS tree search via `splendor-neural-search`.

use std::collections::HashMap;
use std::fs::File;
use std::io::{self, BufReader};
use std::path::{Path, PathBuf};

use splendor_agent::{run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_belief::{build_information_set_v1, sample_determinization_v1};
use splendor_core::{Action, Observation, Phase, Ruleset};
use splendor_learning::{
    encode_action_semantic_v1, encode_action_v1, encode_observation_v1, PolicyActionProbabilityV1,
    PolicyValuePredictionV1,
};
use splendor_neural_search::{
    search_neural_ismcts_with_evaluator_v1, NeuralIsmctsConfigV1, NeuralSearchError,
    PolicyValueEvaluatorV1,
};

pub const M50_AGENT_NAME: &str = "splendor-cli-m50-policy";
pub const M50_AGENT_VERSION: &str = "0.3.0";

const USAGE: &str = "\
Usage: splendor agent-m50-policy --weights <weights.json> [--mode <greedy|search|ismcts>] [--simulations <N>] [--top-k <N>] [--worlds <D>] [--seed <u64>]

Play 2-player Splendor using the M50 competitive policy-value network.
Options:
  --weights      Path to exported m50 policy-value JSON weights
  --mode         `greedy` (default), `search` (1-ply lookahead), or `ismcts` (full neural tree search)
  --simulations  Number of ISMCTS simulations (default: 32)
  --top-k        Candidate actions in 1-ply search mode (default: 4)
  --worlds       Determinized belief worlds in 1-ply search mode (default: 2)
  --seed         RNG seed (default: 50000001)
";

#[derive(Debug, Clone)]
pub struct M50PolicyWeights {
    state_l1_w: Vec<Vec<f32>>, // [256, 368]
    state_l1_b: Vec<f32>,      // [256]
    state_ln1_w: Vec<f32>,     // [256]
    state_ln1_b: Vec<f32>,     // [256]
    state_l2_w: Vec<Vec<f32>>, // [128, 256]
    state_l2_b: Vec<f32>,      // [128]
    state_ln2_w: Vec<f32>,     // [128]
    state_ln2_b: Vec<f32>,     // [128]

    act_l1_w: Vec<Vec<f32>>, // [128, 36]
    act_l1_b: Vec<f32>,      // [128]
    act_ln1_w: Vec<f32>,     // [128]
    act_ln1_b: Vec<f32>,     // [128]

    act_bias: Vec<f32>, // [36]

    val_l1_w: Vec<Vec<f32>>, // [64, 128]
    val_l1_b: Vec<f32>,      // [64]
    val_l2_w: Vec<f32>,      // [64]
    val_l2_b: f32,

    steps_l1_w: Option<Vec<Vec<f32>>>, // [64, 128]
    steps_l1_b: Option<Vec<f32>>,      // [64]
    steps_l2_w: Option<Vec<f32>>,      // [64]
    steps_l2_b: Option<f32>,
}

impl M50PolicyWeights {
    pub fn load_from_json(path: &Path) -> Result<Self, String> {
        let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
        let reader = BufReader::new(file);
        let map: HashMap<String, serde_json::Value> =
            serde_json::from_reader(reader).map_err(|e| format!("parse JSON: {e}"))?;

        let get_vec_vec = |key: &str| -> Result<Vec<Vec<f32>>, String> {
            let val = map.get(key).ok_or_else(|| format!("missing key `{key}`"))?;
            serde_json::from_value(val.clone()).map_err(|e| format!("key `{key}`: {e}"))
        };

        let get_vec = |key: &str| -> Result<Vec<f32>, String> {
            let val = map.get(key).ok_or_else(|| format!("missing key `{key}`"))?;
            serde_json::from_value(val.clone()).map_err(|e| format!("key `{key}`: {e}"))
        };

    let bias_2d = get_vec_vec("action_bias.weight").unwrap_or_default();
        let act_bias = bias_2d.into_iter().next().unwrap_or_else(|| vec![0.0f32; 36]);

        let val_l2_2d = get_vec_vec("value_head.2.weight")?;
        let val_l2_w = val_l2_2d.into_iter().next().unwrap_or_default();
        let val_l2_b = get_vec("value_head.2.bias")?[0];

        let (steps_l1_w, steps_l1_b, steps_l2_w, steps_l2_b) =
            if map.contains_key("steps_head.0.weight") {
                let l1_w = get_vec_vec("steps_head.0.weight")?;
                let l1_b = get_vec("steps_head.0.bias")?;
                let l2_2d = get_vec_vec("steps_head.2.weight")?;
                let l2_w = l2_2d.into_iter().next().unwrap_or_default();
                let l2_b = get_vec("steps_head.2.bias")?[0];
                (Some(l1_w), Some(l1_b), Some(l2_w), Some(l2_b))
            } else {
                (None, None, None, None)
            };

        let act_l1_w = get_vec_vec("action_net.0.weight").unwrap_or_default();
        let act_l1_b = get_vec("action_net.0.bias").unwrap_or_default();
        let act_ln1_w = get_vec("action_net.1.weight").unwrap_or_default();
        let act_ln1_b = get_vec("action_net.1.bias").unwrap_or_default();

        let weights = Self {
            state_l1_w: get_vec_vec("state_net.0.weight")?,
            state_l1_b: get_vec("state_net.0.bias")?,
            state_ln1_w: get_vec("state_net.1.weight")?,
            state_ln1_b: get_vec("state_net.1.bias")?,
            state_l2_w: get_vec_vec("state_net.3.weight")?,
            state_l2_b: get_vec("state_net.3.bias")?,
            state_ln2_w: get_vec("state_net.4.weight")?,
            state_ln2_b: get_vec("state_net.4.bias")?,

            act_l1_w,
            act_l1_b,
            act_ln1_w,
            act_ln1_b,

            act_bias,

            val_l1_w: get_vec_vec("value_head.0.weight")?,
            val_l1_b: get_vec("value_head.0.bias")?,
            val_l2_w,
            val_l2_b,

            steps_l1_w,
            steps_l1_b,
            steps_l2_w,
            steps_l2_b,
        };

        let h1_dim = weights.state_l1_w.len();
        let h2_dim = weights.state_l2_w.len();
        assert_eq!(weights.state_l1_w[0].len(), 368);
        assert_eq!(weights.state_l2_w[0].len(), h1_dim);
        assert_eq!(weights.val_l1_w[0].len(), h2_dim);

        Ok(weights)
    }

    pub fn forward_state(&self, obs: &[f32]) -> Vec<f32> {
        assert_eq!(obs.len(), 368);
        let h1_dim = self.state_l1_w.len();
        let mut h1 = vec![0.0f32; h1_dim];
        for i in 0..h1_dim {
            let row = &self.state_l1_w[i];
            let mut sum = self.state_l1_b[i];
            for j in 0..368 {
                sum += row[j] * obs[j];
            }
            h1[i] = sum;
        }

        // LayerNorm(h1_dim, eps=1e-5) + ReLU
        let mean1 = h1.iter().sum::<f32>() / (h1_dim as f32);
        let var1 = h1.iter().map(|v| (v - mean1) * (v - mean1)).sum::<f32>() / (h1_dim as f32);
        let std1 = (var1 + 1e-5).sqrt();
        for i in 0..h1_dim {
            let norm = (h1[i] - mean1) / std1;
            let val = norm * self.state_ln1_w[i] + self.state_ln1_b[i];
            h1[i] = if val > 0.0 { val } else { 0.0 };
        }

        let h2_dim = self.state_l2_w.len();
        let mut h2 = vec![0.0f32; h2_dim];
        for i in 0..h2_dim {
            let row = &self.state_l2_w[i];
            let mut sum = self.state_l2_b[i];
            for j in 0..h1_dim {
                sum += row[j] * h1[j];
            }
            h2[i] = sum;
        }

        // LayerNorm(h2_dim, eps=1e-5) + ReLU
        let mean2 = h2.iter().sum::<f32>() / (h2_dim as f32);
        let var2 = h2.iter().map(|v| (v - mean2) * (v - mean2)).sum::<f32>() / (h2_dim as f32);
        let std2 = (var2 + 1e-5).sqrt();
        for i in 0..h2_dim {
            let norm = (h2[i] - mean2) / std2;
            let val = norm * self.state_ln2_w[i] + self.state_ln2_b[i];
            h2[i] = if val > 0.0 { val } else { 0.0 };
        }

        h2
    }

    pub fn predict_value_from_state_h(&self, state_h: &[f32]) -> f32 {
        let v_dim = self.val_l1_w.len();
        let h2_dim = state_h.len();
        let mut vh = vec![0.0f32; v_dim];
        for i in 0..v_dim {
            let row = &self.val_l1_w[i];
            let mut sum = self.val_l1_b[i];
            for j in 0..h2_dim {
                sum += row[j] * state_h[j];
            }
            vh[i] = if sum > 0.0 { sum } else { 0.0 };
        }

        let mut sum = self.val_l2_b;
        for j in 0..v_dim {
            sum += self.val_l2_w[j] * vh[j];
        }

        1.0f32 / (1.0f32 + (-sum).exp())
    }

    pub fn predict_value(&self, obs: &[f32]) -> f32 {
        let state_h = self.forward_state(obs);
        self.predict_value_from_state_h(&state_h)
    }

    pub fn predict_steps_to_15(&self, state_h: &[f32]) -> Option<f32> {
        let (l1_w, l1_b, l2_w, l2_b) = match (
            &self.steps_l1_w,
            &self.steps_l1_b,
            &self.steps_l2_w,
            self.steps_l2_b,
        ) {
            (Some(w1), Some(b1), Some(w2), Some(b2)) => (w1, b1, w2, b2),
            _ => return None,
        };

        let s_dim = l1_w.len();
        let h2_dim = state_h.len();
        let mut vh = vec![0.0f32; s_dim];
        for i in 0..s_dim {
            let row = &l1_w[i];
            let mut sum = l1_b[i];
            for j in 0..h2_dim {
                sum += row[j] * state_h[j];
            }
            vh[i] = if sum > 0.0 { sum } else { 0.0 };
        }

        let mut sum = l2_b;
        for j in 0..s_dim {
            sum += l2_w[j] * vh[j];
        }

        let sp = if sum > 20.0 {
            sum
        } else if sum < -20.0 {
            sum.exp()
        } else {
            (1.0 + sum.exp()).ln()
        };

        Some(sp * 20.0)
    }

    pub fn score_action(&self, state_h: &[f32], act: &[f32]) -> f32 {
        assert_eq!(act.len(), 36);
        let h2_dim = self.act_l1_w.len();
        if h2_dim == 0 {
            return 0.0;
        }
        let mut ah = vec![0.0f32; h2_dim];
        for i in 0..h2_dim {
            let row = &self.act_l1_w[i];
            let mut sum = self.act_l1_b[i];
            for j in 0..36 {
                sum += row[j] * act[j];
            }
            ah[i] = sum;
        }

        let mean = ah.iter().sum::<f32>() / (h2_dim as f32);
        let var = ah.iter().map(|v| (v - mean) * (v - mean)).sum::<f32>() / (h2_dim as f32);
        let std = (var + 1e-5).sqrt();
        for i in 0..h2_dim {
            let norm = (ah[i] - mean) / std;
            let val = norm * self.act_ln1_w[i] + self.act_ln1_b[i];
            ah[i] = if val > 0.0 { val } else { 0.0 };
        }

        let mut dot = 0.0f32;
        for i in 0..h2_dim {
            dot += state_h[i] * ah[i];
        }
        let dot_scaled = dot / (h2_dim as f32).sqrt();

        let mut bias = 0.0f32;
        for j in 0..36 {
            bias += self.act_bias[j] * act[j];
        }

        dot_scaled + bias
    }
}

impl PolicyValueEvaluatorV1 for M50PolicyWeights {
    fn model_id(&self) -> &str {
        "m50-policy-value-v1"
    }

    fn checkpoint_hash(&self) -> Result<String, NeuralSearchError> {
        Ok("0000000000000000000000000000000000000000000000000000000000000000".to_string())
    }

    fn predict(
        &self,
        observation: &Observation,
        legal_actions: &[Action],
    ) -> Result<PolicyValuePredictionV1, NeuralSearchError> {
        if legal_actions.is_empty() {
            return Err(NeuralSearchError::NoLegalActions);
        }
        let obs_feat = encode_observation_v1(observation)
            .map_err(|e| NeuralSearchError::Learning(e.to_string()))?;
        let state_h = self.forward_state(&obs_feat);

        let mut logits = Vec::with_capacity(legal_actions.len());
        for action in legal_actions {
            let act_feat =
                encode_action_v1(action).map_err(|e| NeuralSearchError::Learning(e.to_string()))?;
            logits.push(self.score_action(&state_h, &act_feat));
        }

        // Softmax
        let max_logit = logits.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        let exps: Vec<f32> = logits.iter().map(|l| (l - max_logit).exp()).collect();
        let sum_exp: f32 = exps.iter().sum();
        let probs: Vec<f32> = exps.iter().map(|e| e / sum_exp.max(1e-8)).collect();

        let policy = legal_actions
            .iter()
            .zip(probs)
            .map(|(&action, probability)| PolicyActionProbabilityV1 {
                action,
                probability,
            })
            .collect();

        // Value prediction for acting player (synthesizing win prob + speed to 15)
        let p_viewer_win = self.predict_value_from_state_h(&state_h);
        let viewer_val = if let Some(steps) = self.predict_steps_to_15(&state_h) {
            let speed_ratio = (1.0 - (steps / 30.0)).clamp(0.0, 1.0);
            (0.75 * p_viewer_win + 0.25 * speed_ratio).clamp(0.0, 1.0)
        } else {
            p_viewer_win.clamp(0.0, 1.0)
        };

        let viewer_idx = observation.viewer.index();
        let pcount = observation.public.player_count as usize;

        // Return values in absolute seat order [seat 0, seat 1]
        let mut value_by_player = vec![0.5f32; pcount];
        if pcount == 2 {
            value_by_player[viewer_idx] = viewer_val;
            value_by_player[1 - viewer_idx] = (1.0 - viewer_val).clamp(0.0, 1.0);
        }

        Ok(PolicyValuePredictionV1 {
            policy,
            value_by_player,
        })
    }
}

#[derive(Debug, Clone)]
pub struct SemanticQWeights {
    state_l1_w: Vec<Vec<f32>>,
    state_l1_b: Vec<f32>,
    state_ln1_w: Vec<f32>,
    state_ln1_b: Vec<f32>,
    state_l2_w: Vec<Vec<f32>>,
    state_l2_b: Vec<f32>,
    state_ln2_w: Vec<f32>,
    state_ln2_b: Vec<f32>,

    act_l1_w: Vec<Vec<f32>>,
    act_l1_b: Vec<f32>,
    act_ln1_w: Vec<f32>,
    act_ln1_b: Vec<f32>,
    act_l2_w: Vec<Vec<f32>>,
    act_l2_b: Vec<f32>,
    act_ln2_w: Vec<f32>,
    act_ln2_b: Vec<f32>,

    q_l1_w: Vec<Vec<f32>>,
    q_l1_b: Vec<f32>,
    q_l2_w: Vec<Vec<f32>>,
    q_l2_b: Vec<f32>,
    q_l3_w: Vec<f32>,
    q_l3_b: f32,

    val_l1_w: Vec<Vec<f32>>,
    val_l1_b: Vec<f32>,
    val_l2_w: Vec<f32>,
    val_l2_b: f32,
}

impl SemanticQWeights {
    pub fn load_from_json(path: &Path) -> Result<Self, String> {
        let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
        let reader = BufReader::new(file);
        let map: HashMap<String, serde_json::Value> =
            serde_json::from_reader(reader).map_err(|e| format!("parse JSON: {e}"))?;

        if !map.contains_key("q_head.0.weight") {
            return Err("not a semantic Q weights file".into());
        }

        let get_vec_vec = |key: &str| -> Result<Vec<Vec<f32>>, String> {
            let val = map.get(key).ok_or_else(|| format!("missing key `{key}`"))?;
            serde_json::from_value(val.clone()).map_err(|e| format!("key `{key}`: {e}"))
        };

        let get_vec = |key: &str| -> Result<Vec<f32>, String> {
            let val = map.get(key).ok_or_else(|| format!("missing key `{key}`"))?;
            serde_json::from_value(val.clone()).map_err(|e| format!("key `{key}`: {e}"))
        };

        let q_l3_2d = get_vec_vec("q_head.4.weight")?;
        let q_l3_w = q_l3_2d.into_iter().next().unwrap_or_default();
        let q_l3_b = get_vec("q_head.4.bias")?[0];

        let val_l2_2d = get_vec_vec("val_head.2.weight")?;
        let val_l2_w = val_l2_2d.into_iter().next().unwrap_or_default();
        let val_l2_b = get_vec("val_head.2.bias")?[0];

        Ok(Self {
            state_l1_w: get_vec_vec("state_net.0.weight")?,
            state_l1_b: get_vec("state_net.0.bias")?,
            state_ln1_w: get_vec("state_net.1.weight")?,
            state_ln1_b: get_vec("state_net.1.bias")?,
            state_l2_w: get_vec_vec("state_net.3.weight")?,
            state_l2_b: get_vec("state_net.3.bias")?,
            state_ln2_w: get_vec("state_net.4.weight")?,
            state_ln2_b: get_vec("state_net.4.bias")?,

            act_l1_w: get_vec_vec("action_net.0.weight")?,
            act_l1_b: get_vec("action_net.0.bias")?,
            act_ln1_w: get_vec("action_net.1.weight")?,
            act_ln1_b: get_vec("action_net.1.bias")?,
            act_l2_w: get_vec_vec("action_net.3.weight")?,
            act_l2_b: get_vec("action_net.3.bias")?,
            act_ln2_w: get_vec("action_net.4.weight")?,
            act_ln2_b: get_vec("action_net.4.bias")?,

            q_l1_w: get_vec_vec("q_head.0.weight")?,
            q_l1_b: get_vec("q_head.0.bias")?,
            q_l2_w: get_vec_vec("q_head.2.weight")?,
            q_l2_b: get_vec("q_head.2.bias")?,
            q_l3_w,
            q_l3_b,

            val_l1_w: get_vec_vec("val_head.0.weight")?,
            val_l1_b: get_vec("val_head.0.bias")?,
            val_l2_w,
            val_l2_b,
        })
    }

    pub fn forward_state(&self, obs: &[f32]) -> Vec<f32> {
        let h1_dim = self.state_l1_w.len();
        let mut h1 = vec![0.0f32; h1_dim];
        for i in 0..h1_dim {
            let row = &self.state_l1_w[i];
            let mut sum = self.state_l1_b[i];
            for j in 0..obs.len() {
                sum += row[j] * obs[j];
            }
            h1[i] = sum;
        }
        let mean1 = h1.iter().sum::<f32>() / (h1_dim as f32);
        let var1 = h1.iter().map(|v| (v - mean1) * (v - mean1)).sum::<f32>() / (h1_dim as f32);
        let std1 = (var1 + 1e-5).sqrt();
        for i in 0..h1_dim {
            let norm = (h1[i] - mean1) / std1;
            let val = norm * self.state_ln1_w[i] + self.state_ln1_b[i];
            h1[i] = if val > 0.0 { val } else { 0.0 };
        }

        let h2_dim = self.state_l2_w.len();
        let mut h2 = vec![0.0f32; h2_dim];
        for i in 0..h2_dim {
            let row = &self.state_l2_w[i];
            let mut sum = self.state_l2_b[i];
            for j in 0..h1_dim {
                sum += row[j] * h1[j];
            }
            h2[i] = sum;
        }
        let mean2 = h2.iter().sum::<f32>() / (h2_dim as f32);
        let var2 = h2.iter().map(|v| (v - mean2) * (v - mean2)).sum::<f32>() / (h2_dim as f32);
        let std2 = (var2 + 1e-5).sqrt();
        for i in 0..h2_dim {
            let norm = (h2[i] - mean2) / std2;
            let val = norm * self.state_ln2_w[i] + self.state_ln2_b[i];
            h2[i] = if val > 0.0 { val } else { 0.0 };
        }
        h2
    }

    pub fn forward_action(&self, act: &[f32]) -> Vec<f32> {
        let h1_dim = self.act_l1_w.len();
        let mut h1 = vec![0.0f32; h1_dim];
        for i in 0..h1_dim {
            let row = &self.act_l1_w[i];
            let mut sum = self.act_l1_b[i];
            for j in 0..act.len() {
                sum += row[j] * act[j];
            }
            h1[i] = sum;
        }
        let mean1 = h1.iter().sum::<f32>() / (h1_dim as f32);
        let var1 = h1.iter().map(|v| (v - mean1) * (v - mean1)).sum::<f32>() / (h1_dim as f32);
        let std1 = (var1 + 1e-5).sqrt();
        for i in 0..h1_dim {
            let norm = (h1[i] - mean1) / std1;
            let val = norm * self.act_ln1_w[i] + self.act_ln1_b[i];
            h1[i] = if val > 0.0 { val } else { 0.0 };
        }

        let h2_dim = self.act_l2_w.len();
        let mut h2 = vec![0.0f32; h2_dim];
        for i in 0..h2_dim {
            let row = &self.act_l2_w[i];
            let mut sum = self.act_l2_b[i];
            for j in 0..h1_dim {
                sum += row[j] * h1[j];
            }
            h2[i] = sum;
        }
        let mean2 = h2.iter().sum::<f32>() / (h2_dim as f32);
        let var2 = h2.iter().map(|v| (v - mean2) * (v - mean2)).sum::<f32>() / (h2_dim as f32);
        let std2 = (var2 + 1e-5).sqrt();
        for i in 0..h2_dim {
            let norm = (h2[i] - mean2) / std2;
            let val = norm * self.act_ln2_w[i] + self.act_ln2_b[i];
            h2[i] = if val > 0.0 { val } else { 0.0 };
        }
        h2
    }

    pub fn predict_q_steps(&self, state_h: &[f32], act_raw: &[f32]) -> f32 {
        let act_h = self.forward_action(act_raw);
        let mut joint = Vec::with_capacity(state_h.len() + act_h.len() + act_raw.len());
        joint.extend_from_slice(state_h);
        joint.extend_from_slice(&act_h);
        joint.extend_from_slice(act_raw);

        let q1_dim = self.q_l1_w.len();
        let mut q1 = vec![0.0f32; q1_dim];
        for i in 0..q1_dim {
            let row = &self.q_l1_w[i];
            let mut sum = self.q_l1_b[i];
            for j in 0..joint.len() {
                sum += row[j] * joint[j];
            }
            q1[i] = if sum > 0.0 { sum } else { 0.0 };
        }

        let q2_dim = self.q_l2_w.len();
        let mut q2 = vec![0.0f32; q2_dim];
        for i in 0..q2_dim {
            let row = &self.q_l2_w[i];
            let mut sum = self.q_l2_b[i];
            for j in 0..q1_dim {
                sum += row[j] * q1[j];
            }
            q2[i] = if sum > 0.0 { sum } else { 0.0 };
        }

        let mut sum = self.q_l3_b;
        for j in 0..q2_dim {
            sum += self.q_l3_w[j] * q2[j];
        }

        let sp = if sum > 20.0 {
            sum
        } else if sum < -20.0 {
            sum.exp()
        } else {
            (1.0 + sum.exp()).ln()
        };

        sp * 20.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum M50Mode {
    Greedy,
    QSteps,
    SemanticQ,
    PureDistance,
    Search,
    Ismcts,
}

pub struct M50Policy {
    weights: Option<M50PolicyWeights>,
    semantic_weights: Option<SemanticQWeights>,
    mode: M50Mode,
    simulations: u32,
    max_depth: u8,
    top_k: usize,
    worlds: usize,
    sample_seed: u64,
}

impl M50Policy {
    pub fn new(
        weights: Option<M50PolicyWeights>,
        semantic_weights: Option<SemanticQWeights>,
        mode: M50Mode,
        simulations: u32,
        max_depth: u8,
        top_k: usize,
        worlds: usize,
        sample_seed: u64,
    ) -> Self {
        Self {
            weights,
            semantic_weights,
            mode,
            simulations,
            max_depth,
            top_k,
            worlds,
            sample_seed,
        }
    }
}

impl AgentPolicy for M50Policy {
    type Error = AgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let legal = context.legal_actions;
        if legal.is_empty() {
            return Err(AgentError::Policy("no legal actions".into()));
        }
        if legal.len() == 1 {
            return Ok(legal[0].clone());
        }

        // Semantic Q Mode: evaluate each legal action using rich 48-dim physical features!
        // ZERO policy imitation. Pick a* = argmin_a Q_steps(s, a)!
        if self.mode == M50Mode::SemanticQ {
            if let Some(ref sw) = self.semantic_weights {
                let obs_feat = encode_observation_v1(&context.observation)
                    .map_err(|e| AgentError::Policy(e.to_string()))?;
                let state_h = sw.forward_state(&obs_feat);

                let mut best_q = f32::INFINITY;
                let mut best_action = legal[0].clone();

                for action in legal {
                    let act_feat = encode_action_semantic_v1(&context.observation, action)
                        .map_err(|e| AgentError::Policy(e.to_string()))?;
                    let q = sw.predict_q_steps(&state_h, &act_feat);
                    if q < best_q {
                        best_q = q;
                        best_action = action.clone();
                    }
                }
                return Ok(best_action);
            }
        }

        let weights = match self.weights.as_ref() {
            Some(w) => w,
            None => return Err(AgentError::Policy("missing policy weights for non-semantic mode".into())),
        };

        // Full ISMCTS tree search mode
        if self.mode == M50Mode::Ismcts && context.observation.public.phase == Phase::Main {
            let ruleset = Ruleset::base_v1();
            let info_set = match build_information_set_v1(
                ruleset,
                &context.observation,
                context.visible_history,
            ) {
                Ok(is) => is,
                Err(e) => return Err(AgentError::Policy(format!("build info set: {e}"))),
            };

            let config = NeuralIsmctsConfigV1 {
                sample_seed: self.sample_seed,
                simulations: self.simulations.clamp(1, 2048),
                max_depth_turns: self.max_depth.clamp(1, 8),
                puct_exploration_milli: 1500,
                expected_checkpoint_hash:
                    "0000000000000000000000000000000000000000000000000000000000000000".to_string(),
            };

            match search_neural_ismcts_with_evaluator_v1(&info_set, weights, &config) {
                Ok(res) => return Ok(res.action),
                Err(e) => {
                    eprintln!("Warning: IS-MCTS search failed: {e:?}, falling back to policy");
                }
            }
        }

        // Pure Distance Mode: simulate s' = apply(a) on determinization, evaluate V_steps(s')!
        // ZERO policy logits involved. Pick a* = argmin_a pred_steps(s')!
        if self.mode == M50Mode::PureDistance {
            let actor = context.observation.viewer;
            let ruleset = Ruleset::base_v1();
            if let Ok(info_set) = build_information_set_v1(ruleset, &context.observation, context.visible_history) {
                if let Ok(det) = sample_determinization_v1(&info_set, self.sample_seed, 0) {
                    let mut best_steps = f32::INFINITY;
                    let mut best_val = f32::NEG_INFINITY;
                    let mut best_action = legal[0].clone();

                    for action in legal {
                        let mut sim = det.state().clone();
                        if sim.apply(action.clone()).is_ok() {
                            let (steps, val) = if sim.is_terminal() {
                                if let Some(ref res) = sim.result {
                                    if res.winners.contains(&actor) {
                                        (0.0f32, 1.0f32)
                                    } else {
                                        (50.0f32, 0.0f32)
                                    }
                                } else {
                                    (0.0f32, 0.5f32)
                                }
                            } else {
                                let next_obs = sim.observation(actor);
                                if let Ok(feat) = encode_observation_v1(&next_obs) {
                                    let h = weights.forward_state(&feat);
                                    let s = weights.predict_steps_to_15(&h).unwrap_or(20.0);
                                    let v = weights.predict_value_from_state_h(&h);
                                    (s, v)
                                } else {
                                    (20.0, 0.5)
                                }
                            };

                            let is_better = if (steps - best_steps).abs() > 1e-4 {
                                steps < best_steps
                            } else {
                                val > best_val
                            };

                            if is_better {
                                best_steps = steps;
                                best_val = val;
                                best_action = action.clone();
                            }
                        }
                    }
                    return Ok(best_action);
                }
            }
            return Ok(legal[0].clone());
        }

        let obs_feat = encode_observation_v1(&context.observation)
            .map_err(|e| AgentError::Policy(e.to_string()))?;
        let state_h = weights.forward_state(&obs_feat);

        let mut scored: Vec<(usize, f32)> = Vec::with_capacity(legal.len());
        for (idx, action) in legal.iter().enumerate() {
            let act_feat =
                encode_action_v1(action).map_err(|e| AgentError::Policy(e.to_string()))?;
            let score = weights.score_action(&state_h, &act_feat);
            scored.push((idx, score));
        }

        scored.sort_unstable_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        if self.mode != M50Mode::Search || context.observation.public.phase != Phase::Main {
            return Ok(legal[scored[0].0].clone());
        }

        // 1-ply search mode
        let actor = context.observation.viewer;
        let ruleset = Ruleset::base_v1();
        let info_set = match build_information_set_v1(
            ruleset,
            &context.observation,
            context.visible_history,
        ) {
            Ok(is) => is,
            Err(_) => return Ok(legal[scored[0].0].clone()),
        };

        let num_worlds = self.worlds.max(1);
        let mut worlds = Vec::with_capacity(num_worlds);
        for w in 0..num_worlds {
            if let Ok(det) = sample_determinization_v1(&info_set, self.sample_seed, w as u64) {
                worlds.push(det.state().clone());
            }
        }

        if worlds.is_empty() {
            return Ok(legal[scored[0].0].clone());
        }

        let k = self.top_k.min(scored.len()).max(1);
        let candidates = &scored[..k];

        let mut best_val = f32::NEG_INFINITY;
        let mut best_action_idx = candidates[0].0;

        for &(cand_idx, _pi_score) in candidates {
            let cand_act = &legal[cand_idx];
            let mut val_sum = 0.0f32;
            let mut valid_worlds = 0;

            for world_state in &worlds {
                let mut sim_state = world_state.clone();
                if sim_state.apply(cand_act.clone()).is_ok() {
                    if sim_state.is_terminal() {
                        if let Some(ref result) = sim_state.result {
                            if result.winners.contains(&actor) {
                                val_sum += 1.0;
                            } else {
                                val_sum += 0.0;
                            }
                        }
                    } else {
                        let next_obs = sim_state.observation(actor);
                        if let Ok(next_feat) = encode_observation_v1(&next_obs) {
                            let next_h = weights.forward_state(&next_feat);
                            let p_win = weights.predict_value_from_state_h(&next_h);
                            let val = if let Some(steps) = weights.predict_steps_to_15(&next_h)
                            {
                                let speed_ratio = (1.0f32 - (steps / 30.0f32)).clamp(0.0f32, 1.0f32);
                                (0.75f32 * p_win + 0.25f32 * speed_ratio).clamp(0.0f32, 1.0f32)
                            } else {
                                p_win
                            };
                            val_sum += val;
                        }
                    }
                    valid_worlds += 1;
                }
            }

            if valid_worlds > 0 {
                let avg_val = val_sum / (valid_worlds as f32);
                if avg_val > best_val {
                    best_val = avg_val;
                    best_action_idx = cand_idx;
                }
            }
        }

        Ok(legal[best_action_idx].clone())
    }
}

pub fn run_agent_m50_policy(args: &[String]) -> i32 {
    let mut weights_path = None;
    let mut mode = M50Mode::Greedy;
    let mut simulations = 32u32;
    let mut max_depth = 4u8;
    let mut top_k = 4usize;
    let mut worlds = 2usize;
    let mut seed = 50_000_001u64;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--weights" => {
                weights_path = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--mode" => {
                if let Some(m) = args.get(i + 1) {
                    if m == "search" {
                        mode = M50Mode::Search;
                    } else if m == "ismcts" {
                        mode = M50Mode::Ismcts;
                    } else if m == "qsteps" || m == "q_steps" {
                        mode = M50Mode::QSteps;
                    } else if m == "distance" || m == "pure_distance" {
                        mode = M50Mode::PureDistance;
                    } else {
                        mode = M50Mode::Greedy;
                    }
                }
                i += 2;
            }
            "--simulations" => {
                if let Some(s) = args.get(i + 1) {
                    if let Ok(v) = s.parse::<u32>() {
                        simulations = v;
                    }
                }
                i += 2;
            }
            "--max-depth" | "--depth" => {
                if let Some(s) = args.get(i + 1) {
                    if let Ok(v) = s.parse::<u8>() {
                        max_depth = v;
                    }
                }
                i += 2;
            }
            "--top-k" => {
                if let Some(s) = args.get(i + 1) {
                    if let Ok(v) = s.parse::<usize>() {
                        top_k = v;
                    }
                }
                i += 2;
            }
            "--worlds" => {
                if let Some(s) = args.get(i + 1) {
                    if let Ok(v) = s.parse::<usize>() {
                        worlds = v;
                    }
                }
                i += 2;
            }
            "--seed" => {
                if let Some(s) = args.get(i + 1) {
                    if let Ok(v) = s.parse::<u64>() {
                        seed = v;
                    }
                }
                i += 2;
            }
            "--help" | "-h" => {
                println!("{USAGE}");
                return 0;
            }
            _ => {
                i += 1;
            }
        }
    }

    let weights_path = match weights_path {
        Some(p) => p,
        None => {
            eprintln!("error: missing required --weights <path>\n{USAGE}");
            return 2;
        }
    };

    let (weights, semantic_weights) = match SemanticQWeights::load_from_json(&weights_path) {
        Ok(sw) => {
            mode = M50Mode::SemanticQ;
            (None, Some(sw))
        }
        Err(_) => {
            let pw = match M50PolicyWeights::load_from_json(&weights_path) {
                Ok(w) => w,
                Err(e) => {
                    eprintln!("error loading weights from {}: {e}", weights_path.display());
                    return 1;
                }
            };
            (Some(pw), None)
        }
    };

    let stdin = io::stdin();
    let stdout = io::stdout();
    let stderr = io::stderr();

    let identity = AgentIdentity {
        name: M50_AGENT_NAME,
        version: M50_AGENT_VERSION,
    };

    match run_agent(
        BufReader::new(stdin.lock()),
        stdout.lock(),
        stderr.lock(),
        identity,
        seed,
        M50Policy::new(weights, semantic_weights, mode, simulations, max_depth, top_k, worlds, seed),
    ) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}
