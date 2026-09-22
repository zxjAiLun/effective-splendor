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

pub type QWeightsV1 = EfficiencyQWeightsV1;

pub fn load_weights_from_json(path: &PathBuf) -> Result<EfficiencyQWeightsV1, String> {
    let content = fs::read_to_string(path).map_err(|e| format!("read {path:?}: {e}"))?;
    serde_json::from_str(&content).map_err(|e| format!("parse weights JSON: {e}"))
}

pub struct QPolicy<'a> {
    pub weights: &'a EfficiencyQWeightsV1,
    pub remaining_turns: u32,
    pub max_turns: u32,
}

impl<'a> AgentPolicy for QPolicy<'a> {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let legal = context.legal_actions;
        if legal.len() <= 1 {
            return Ok(legal[0]);
        }

        let mut best_q = f32::INFINITY;
        let mut best_actions = Vec::new();

        for &action in legal {
            if let Ok(feat) = encode_combined_v2(
                &context.observation,
                &action,
                self.remaining_turns,
                self.max_turns,
            ) {
                let q = self.weights.forward(&feat);
                if (q - best_q).abs() < 1e-4 {
                    best_actions.push(action);
                } else if q < best_q {
                    best_q = q;
                    best_actions.clear();
                    best_actions.push(action);
                }
            }
        }

        if best_actions.is_empty() {
            Ok(legal[0])
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

    let val_seeds = validation_seeds_v1();
    let max_turns = DEFAULT_MAX_MAIN_TURNS;

    let mut successes = 0;
    let mut main_turns_list = Vec::new();
    let mut failures = 0;

    println!("==========================================================================");
    println!("M49A-II VALIDATION COHORT EVALUATION (64 SEEDS, CAP=100)");
    println!("Weights: {}", weights_path.display());
    println!("==========================================================================");

    for (idx, &seed) in val_seeds.iter().enumerate() {
        let mut env = match Solo15Environment::with_max_main_turns(seed, max_turns) {
            Ok(e) => e,
            Err(e) => {
                eprintln!("seed {seed} init error: {e}");
                return 1;
            }
        };

        // P1-3: Decouple policy RNG strictly from env_seed, indexing by validation cohort ordinal (0..63)
        let mut policy_rng =
            StableRng::new(0x5010_1515_0000_0000_u64.wrapping_add(idx as u64));
        let empty_history = Vec::new();

        while !env.is_terminal() {
            let legal = env.legal_actions();
            if legal.is_empty() {
                break;
            }
            let remaining = max_turns.saturating_sub(env.main_turns());
            let mut q_pol = QPolicy {
                weights: &weights,
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
                    q_pol.choose_action(ctx).unwrap()
                }
                Phase::GameOver => break,
            };

            if let Err(e) = env.step(action) {
                eprintln!("seed {seed} step error: {e}");
                break;
            }
        }

        let summary = env.summary();
        if summary.outcome == Solo15Outcome::Reached15 {
            successes += 1;
            let turns = summary.main_turns_to_15.unwrap();
            main_turns_list.push(turns as f64);
            print!(".");
        } else {
            failures += 1;
            print!("X");
        }
        if (idx + 1) % 16 == 0 {
            println!(" ({}/{})", idx + 1, val_seeds.len());
        }
    }

    main_turns_list.sort_by(|a, b| a.partial_cmp(b).unwrap());

    println!("\n--------------------------------------------------------------------------");
    println!("RESULTS on 64 Validation Seeds:");
    println!("  Success Rate: {} / 64 ({:.1}%)", successes, successes as f64 / 64.0 * 100.0);
    println!("  Failures:     {}", failures);

    let j_val = (main_turns_list.iter().sum::<f64>() + (failures as f64) * 101.0) / 64.0;
    println!("  Failure-Aware J_val Score: {:.2}", j_val);

    if !main_turns_list.is_empty() {
        let mean = main_turns_list.iter().sum::<f64>() / main_turns_list.len() as f64;
        let median = main_turns_list[main_turns_list.len() / 2];
        let p90 = main_turns_list[(main_turns_list.len() as f64 * 0.90) as usize];
        let min = main_turns_list[0];
        let max = main_turns_list[main_turns_list.len() - 1];

        println!("  Main Turns (Successful Only):");
        println!("    Mean:   {:.2}", mean);
        println!("    Median: {:.1}", median);
        println!("    P90:    {:.1}", p90);
        println!("    Min:    {:.0}", min);
        println!("    Max:    {:.0}", max);
    }
    println!("==========================================================================");

    0
}
