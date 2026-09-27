//! M50: Native Rust inference agent for the competitive Policy-Value network
//! with support for direct greedy policy, Policy-pruned 1-ply search, and
//! value evaluation.

use std::collections::HashMap;
use std::fs::File;
use std::io::{self, BufReader};
use std::path::{Path, PathBuf};

use splendor_agent::{run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_belief::{build_information_set_v1, sample_determinization_v1};
use splendor_core::{Action, Phase, Ruleset};
use splendor_learning::{encode_action_v1, encode_observation_v1};

pub const M50_AGENT_NAME: &str = "splendor-cli-m50-policy";
pub const M50_AGENT_VERSION: &str = "0.2.0";

const USAGE: &str = "\
Usage: splendor agent-m50-policy --weights <weights.json> [--mode <greedy|search>] [--top-k <N>] [--worlds <D>] [--seed <u64>]

Play 2-player Splendor using the M50 competitive policy-value network.
Options:
  --weights  Path to exported m50 policy-value JSON weights
  --mode     `greedy` (default) for fast 10us policy argmax, or `search` for policy-guided 1-ply value lookahead
  --top-k    Number of candidate actions to consider in search mode (default: 5)
  --worlds   Number of determinized belief worlds to average over in search (default: 2)
  --seed     RNG seed for tie-breaking and world sampling (default: 50000001)
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

        let bias_2d = get_vec_vec("action_bias.weight")?;
        let act_bias = bias_2d.into_iter().next().unwrap_or_default();

        let val_l2_2d = get_vec_vec("value_head.2.weight")?;
        let val_l2_w = val_l2_2d.into_iter().next().unwrap_or_default();
        let val_l2_b = get_vec("value_head.2.bias")?[0];

        let weights = Self {
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

            act_bias,

            val_l1_w: get_vec_vec("value_head.0.weight")?,
            val_l1_b: get_vec("value_head.0.bias")?,
            val_l2_w,
            val_l2_b,
        };

        assert_eq!(weights.state_l1_w.len(), 256);
        assert_eq!(weights.state_l1_w[0].len(), 368);
        assert_eq!(weights.state_l2_w.len(), 128);
        assert_eq!(weights.state_l2_w[0].len(), 256);
        assert_eq!(weights.act_l1_w.len(), 128);
        assert_eq!(weights.act_l1_w[0].len(), 36);
        assert_eq!(weights.act_bias.len(), 36);
        assert_eq!(weights.val_l1_w.len(), 64);
        assert_eq!(weights.val_l1_w[0].len(), 128);
        assert_eq!(weights.val_l2_w.len(), 64);

        Ok(weights)
    }

    pub fn forward_state(&self, obs: &[f32]) -> [f32; 128] {
        assert_eq!(obs.len(), 368);

        // Layer 1: Linear(368, 256)
        let mut h1 = [0.0f32; 256];
        for i in 0..256 {
            let row = &self.state_l1_w[i];
            let mut sum = self.state_l1_b[i];
            for j in 0..368 {
                sum += row[j] * obs[j];
            }
            h1[i] = sum;
        }

        // LayerNorm(256, eps=1e-5) + ReLU
        let mean1 = h1.iter().sum::<f32>() / 256.0;
        let var1 = h1.iter().map(|v| (v - mean1) * (v - mean1)).sum::<f32>() / 256.0;
        let std1 = (var1 + 1e-5).sqrt();
        for i in 0..256 {
            let norm = (h1[i] - mean1) / std1;
            let val = norm * self.state_ln1_w[i] + self.state_ln1_b[i];
            h1[i] = if val > 0.0 { val } else { 0.0 };
        }

        // Layer 2: Linear(256, 128)
        let mut h2 = [0.0f32; 128];
        for i in 0..128 {
            let row = &self.state_l2_w[i];
            let mut sum = self.state_l2_b[i];
            for j in 0..256 {
                sum += row[j] * h1[j];
            }
            h2[i] = sum;
        }

        // LayerNorm(128, eps=1e-5) + ReLU
        let mean2 = h2.iter().sum::<f32>() / 128.0;
        let var2 = h2.iter().map(|v| (v - mean2) * (v - mean2)).sum::<f32>() / 128.0;
        let std2 = (var2 + 1e-5).sqrt();
        for i in 0..128 {
            let norm = (h2[i] - mean2) / std2;
            let val = norm * self.state_ln2_w[i] + self.state_ln2_b[i];
            h2[i] = if val > 0.0 { val } else { 0.0 };
        }

        h2
    }

    pub fn predict_value_from_state_h(&self, state_h: &[f32; 128]) -> f32 {
        // Value Layer 1: Linear(128, 64) + ReLU
        let mut vh = [0.0f32; 64];
        for i in 0..64 {
            let row = &self.val_l1_w[i];
            let mut sum = self.val_l1_b[i];
            for j in 0..128 {
                sum += row[j] * state_h[j];
            }
            vh[i] = if sum > 0.0 { sum } else { 0.0 };
        }

        // Value Layer 2: Linear(64, 1) -> logit -> sigmoid
        let mut sum = self.val_l2_b;
        for j in 0..64 {
            sum += self.val_l2_w[j] * vh[j];
        }

        1.0f32 / (1.0f32 + (-sum).exp())
    }

    pub fn predict_value(&self, obs: &[f32]) -> f32 {
        let state_h = self.forward_state(obs);
        self.predict_value_from_state_h(&state_h)
    }

    pub fn score_action(&self, state_h: &[f32; 128], act: &[f32]) -> f32 {
        assert_eq!(act.len(), 36);

        // Action Layer 1: Linear(36, 128)
        let mut ah = [0.0f32; 128];
        for i in 0..128 {
            let row = &self.act_l1_w[i];
            let mut sum = self.act_l1_b[i];
            for j in 0..36 {
                sum += row[j] * act[j];
            }
            ah[i] = sum;
        }

        // LayerNorm(128, eps=1e-5) + ReLU
        let mean = ah.iter().sum::<f32>() / 128.0;
        let var = ah.iter().map(|v| (v - mean) * (v - mean)).sum::<f32>() / 128.0;
        let std = (var + 1e-5).sqrt();
        for i in 0..128 {
            let norm = (ah[i] - mean) / std;
            let val = norm * self.act_ln1_w[i] + self.act_ln1_b[i];
            ah[i] = if val > 0.0 { val } else { 0.0 };
        }

        // Bilinear dot product: (state_h * ah).sum() / sqrt(128)
        let mut dot = 0.0f32;
        for i in 0..128 {
            dot += state_h[i] * ah[i];
        }
        let dot_scaled = dot / (128.0f32).sqrt();

        // Action bias: Linear(36, 1)
        let mut bias = 0.0f32;
        for j in 0..36 {
            bias += self.act_bias[j] * act[j];
        }

        dot_scaled + bias
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum M50Mode {
    Greedy,
    Search,
}

pub struct M50Policy {
    weights: M50PolicyWeights,
    mode: M50Mode,
    top_k: usize,
    worlds: usize,
    sample_seed: u64,
}

impl M50Policy {
    pub fn new(
        weights: M50PolicyWeights,
        mode: M50Mode,
        top_k: usize,
        worlds: usize,
        sample_seed: u64,
    ) -> Self {
        Self {
            weights,
            mode,
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

        let obs_feat = encode_observation_v1(&context.observation)
            .map_err(|e| AgentError::Policy(e.to_string()))?;
        let state_h = self.weights.forward_state(&obs_feat);

        // Score all legal actions with the policy head
        let mut scored: Vec<(usize, f32)> = Vec::with_capacity(legal.len());
        for (idx, action) in legal.iter().enumerate() {
            let act_feat =
                encode_action_v1(action).map_err(|e| AgentError::Policy(e.to_string()))?;
            let score = self.weights.score_action(&state_h, &act_feat);
            scored.push((idx, score));
        }

        // Sort descending by policy score
        scored.sort_unstable_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        if self.mode == M50Mode::Greedy || context.observation.public.phase != Phase::Main {
            return Ok(legal[scored[0].0].clone());
        }

        // Search mode: 1-ply value lookahead over Top-K candidate actions
        let actor = context.observation.viewer;
        let ruleset = Ruleset::base_v1();
        let info_set = match build_information_set_v1(
            ruleset,
            &context.observation,
            context.visible_history,
        ) {
            Ok(is) => is,
            Err(_) => return Ok(legal[scored[0].0].clone()), // fallback to greedy on error
        };

        // Sample determinized worlds
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
                    // Check if action triggers immediate game over / win
                    if sim_state.is_terminal() {
                        if let Some(ref result) = sim_state.result {
                            if result.winners.contains(&actor) {
                                val_sum += 1.0;
                            } else {
                                val_sum += 0.0;
                            }
                        }
                    } else {
                        // Predict win prob for actor from next state
                        let next_obs = sim_state.observation(actor);
                        if let Ok(next_feat) = encode_observation_v1(&next_obs) {
                            let p_win = self.weights.predict_value(&next_feat);
                            val_sum += p_win;
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
    let mut top_k = 5usize;
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
                    } else {
                        mode = M50Mode::Greedy;
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

    let weights = match M50PolicyWeights::load_from_json(&weights_path) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("error loading weights from {}: {e}", weights_path.display());
            return 1;
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
        M50Policy::new(weights, mode, top_k, worlds, seed),
    ) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}
