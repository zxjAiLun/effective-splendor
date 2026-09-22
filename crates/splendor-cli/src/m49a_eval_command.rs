//! M49A-II: evaluate a learned Q policy on the frozen Validation seed partition.
//!
//! DISCIPLINE:
//! - Evaluates strictly on the 64 validation seeds (`validation_seeds_v1()`);
//! - Canonical benchmark seeds (64) are NEVER touched here;
//! - Full policy execution: both `Phase::Main` and `Phase::ChooseNoble` are routed
//!   through the learned Q-network (argmin Q(o, a));
//! - Non-clairvoyant: features use only the player's observation and legal actions.

use std::fs;
use std::path::PathBuf;

use splendor_agent::{AgentPolicy, DecisionContext, StableRng};
use splendor_analysis::m49a_collector::validation_seeds_v1;
use splendor_analysis::solo15::{Solo15Environment, Solo15Outcome, DEFAULT_MAX_MAIN_TURNS};
use splendor_core::{Action, Phase};
use splendor_learning::{encode_combined_v2, EfficiencyQWeightsV1};

const EXIT_USAGE: i32 = 2;

/// Structured validation metrics for one weights checkpoint.
///
/// This is the shared measurement primitive consumed by both
/// `m49a-eval-validation` (human-readable report) and
/// `m49a-select-checkpoint` (deterministic lexicographic selection).
#[derive(Debug, Clone)]
pub struct ValidationMetrics {
    pub success_count: usize,
    pub failures: usize,
    pub j_val: f64,
    pub successful_mean_turns: f64,
    pub successful_median_turns: f64,
    pub successful_p90_turns: f64,
    pub successful_min_turns: f64,
    pub successful_max_turns: f64,
}

/// Evaluate one weights checkpoint on the 64 frozen validation seeds.
///
/// Pure measurement: no model-selection policy is applied here. The RNG is
/// strictly decoupled from env_seed (indexed by cohort ordinal 0..63).
pub fn evaluate_weights_on_validation(
    weights: &EfficiencyQWeightsV1,
) -> Result<ValidationMetrics, String> {
    weights
        .validate()
        .map_err(|e| format!("invalid evaluation weights: {e}"))?;
    let val_seeds = validation_seeds_v1();
    let max_turns = DEFAULT_MAX_MAIN_TURNS;

    let mut successes = 0usize;
    let mut failures = 0usize;
    let mut main_turns_list = Vec::new();
    let empty_history = Vec::new();

    for (idx, &seed) in val_seeds.iter().enumerate() {
        let mut env = Solo15Environment::with_max_main_turns(seed, max_turns)
            .map_err(|e| format!("seed {seed} init error: {e}"))?;
        let mut policy_rng = StableRng::new(0x5010_1515_0000_0000_u64.wrapping_add(idx as u64));

        while !env.is_terminal() {
            let legal = env.legal_actions();
            if legal.is_empty() {
                return Err(format!(
                    "seed {seed}: nonterminal state has no legal actions"
                ));
            }
            let remaining = max_turns.saturating_sub(env.main_turns());
            let mut q_pol = QPolicy {
                weights,
                remaining_turns: remaining,
                max_turns,
            };
            let action = match env.phase() {
                Phase::Main | Phase::ChooseNoble => {
                    let obs = env.observation();
                    let obs_h = splendor_core::observation_hash(&obs);
                    let ctx = DecisionContext {
                        observation: obs,
                        visible_history: &empty_history,
                        legal_actions: &legal,
                        meta: splendor_agent::PublicRequestMeta {
                            game_id: splendor_analysis::SOLO15_CONTRACT_ID_V1.to_string(),
                            recipient_seat: splendor_core::PlayerId(0),
                            request_id: env.decision_plies() as u64,
                            observation_hash: obs_h,
                        },
                        rng: &mut policy_rng,
                    };
                    q_pol
                        .choose_action(ctx)
                        .map_err(|e| format!("seed {seed} decision error: {e}"))?
                }
                Phase::GameOver => return Err(format!("seed {seed}: nonterminal GameOver phase")),
            };
            if let Err(e) = env.step(action) {
                return Err(format!("seed {seed} step error: {e}"));
            }
        }

        let summary = env.summary();
        if summary.outcome == Solo15Outcome::Reached15 {
            successes += 1;
            main_turns_list.push(summary.main_turns_to_15.unwrap() as f64);
        } else {
            failures += 1;
        }
    }

    main_turns_list.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let j_val = (main_turns_list.iter().sum::<f64>() + (failures as f64) * 101.0) / 64.0;

    let (mean, median, p90, min, max) = if main_turns_list.is_empty() {
        (0.0, 0.0, 0.0, 0.0, 0.0)
    } else {
        let mean = main_turns_list.iter().sum::<f64>() / main_turns_list.len() as f64;
        let median = main_turns_list[main_turns_list.len() / 2];
        let p90 = main_turns_list[(main_turns_list.len() as f64 * 0.90) as usize];
        let min = main_turns_list[0];
        let max = main_turns_list[main_turns_list.len() - 1];
        (mean, median, p90, min, max)
    };

    Ok(ValidationMetrics {
        success_count: successes,
        failures,
        j_val,
        successful_mean_turns: mean,
        successful_median_turns: median,
        successful_p90_turns: p90,
        successful_min_turns: min,
        successful_max_turns: max,
    })
}

pub fn load_weights_from_json(path: &PathBuf) -> Result<EfficiencyQWeightsV1, String> {
    load_weights_with_sha256(path).map(|(weights, _)| weights)
}

/// Hash the exact bytes deserialized and evaluated, not a later read of the path.
pub fn load_weights_with_sha256(path: &PathBuf) -> Result<(EfficiencyQWeightsV1, String), String> {
    use sha2::{Digest, Sha256};
    let content = fs::read(path).map_err(|e| format!("read {path:?}: {e}"))?;
    let weights: EfficiencyQWeightsV1 =
        serde_json::from_slice(&content).map_err(|e| format!("parse weights JSON: {e}"))?;
    weights
        .validate()
        .map_err(|e| format!("invalid weights in {path:?}: {e}"))?;
    Ok((weights, hex::encode(Sha256::digest(&content))))
}

pub struct QPolicy<'a> {
    pub weights: &'a EfficiencyQWeightsV1,
    pub remaining_turns: u32,
    pub max_turns: u32,
}

impl<'a> AgentPolicy for QPolicy<'a> {
    type Error = String;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let legal = context.legal_actions;
        if legal.is_empty() {
            return Err("empty legal actions".into());
        }
        if legal.len() == 1 {
            return Ok(legal[0]);
        }

        let mut best_q = f32::INFINITY;
        let mut best_actions = Vec::new();

        for &action in legal {
            let feat = encode_combined_v2(
                &context.observation,
                &action,
                self.remaining_turns,
                self.max_turns,
            )
            .map_err(|e| format!("encode action: {e}"))?;
            let q = self.weights.forward(&feat);
            if !q.is_finite() {
                return Err("non-finite action Q".into());
            }
            if (q - best_q).abs() < 1e-4 {
                best_actions.push(action);
            } else if q < best_q {
                best_q = q;
                best_actions.clear();
                best_actions.push(action);
            }
        }

        if best_actions.is_empty() {
            Err("no evaluable legal action".into())
        } else if best_actions.len() == 1 {
            Ok(best_actions[0])
        } else {
            let idx = context.rng.index(best_actions.len());
            Ok(best_actions[idx])
        }
    }
}

pub fn run_m49a_eval_validation(args: &[String]) -> i32 {
    let mut weights_path: Option<PathBuf> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--weights" => {
                weights_path = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            other => {
                eprintln!("error: unknown flag `{other}`");
                return EXIT_USAGE;
            }
        }
    }

    let weights_path = match weights_path {
        Some(p) => p,
        None => {
            eprintln!("error: missing required flag `--weights`");
            return EXIT_USAGE;
        }
    };

    let weights = match load_weights_from_json(&weights_path) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("error loading weights: {e}");
            return 1;
        }
    };

    println!("==========================================================================");
    println!("M49A-II VALIDATION COHORT EVALUATION (64 SEEDS, CAP=100)");
    println!("Weights: {}", weights_path.display());
    println!("==========================================================================");

    let m = match evaluate_weights_on_validation(&weights) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("evaluation error: {e}");
            return 1;
        }
    };

    println!("--------------------------------------------------------------------------");
    println!("RESULTS on 64 Validation Seeds:");
    println!(
        "  Success Rate: {} / 64 ({:.1}%)",
        m.success_count,
        m.success_count as f64 / 64.0 * 100.0
    );
    println!("  Failures:     {}", m.failures);
    println!("  Failure-Aware J_val Score: {:.2}", m.j_val);

    if m.success_count > 0 {
        println!("  Main Turns (Successful Only):");
        println!("    Mean:   {:.2}", m.successful_mean_turns);
        println!("    Median: {:.1}", m.successful_median_turns);
        println!("    P90:    {:.1}", m.successful_p90_turns);
        println!("    Min:    {:.0}", m.successful_min_turns);
        println!("    Max:    {:.0}", m.successful_max_turns);
    }
    println!("==========================================================================");

    0
}
