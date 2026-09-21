//! M49A-II Round 2 Data Aggregation:
//! Run Q1 policy with epsilon=0.10 on the SAME 256 training seeds.
//! Append new transitions to training set to train Q2.

use std::fs;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use splendor_agent::{AgentPolicy, DecisionContext, StableRng};
use splendor_analysis::m49a_collector::{collect_solo15_trajectory, train_seeds_v1};
use splendor_analysis::solo15::{Solo15Outcome, DEFAULT_MAX_MAIN_TURNS};
use splendor_core::Action;
use splendor_learning::encode_combined_v2;

use crate::m49a_eval_command::{load_weights_from_json, QWeightsV1};

const EXIT_USAGE: i32 = 2;

struct EpsilonQPolicy<'a> {
    weights: &'a QWeightsV1,
    epsilon: f64,
    remaining_turns: u32,
    max_turns: u32,
}

impl<'a> AgentPolicy for EpsilonQPolicy<'a> {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let legal = context.legal_actions;
        if legal.len() <= 1 {
            return Ok(legal[0]);
        }

        let roll = (context.rng.index(10000) as f64) / 10000.0;
        if roll < self.epsilon {
            let idx = context.rng.index(legal.len());
            return Ok(legal[idx]);
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

pub fn run_m49a_collect_round2(args: &[String]) -> i32 {
    let mut weights_path: Option<PathBuf> = None;
    let mut out_file: Option<PathBuf> = None;
    let mut epsilon: f64 = 0.10;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--weights" => {
                weights_path = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--out-file" => {
                out_file = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--epsilon" => {
                if let Some(e) = args.get(i + 1).and_then(|s| s.parse::<f64>().ok()) {
                    epsilon = e;
                }
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
            eprintln!("error: missing --weights");
            return EXIT_USAGE;
        }
    };
    let out_file = match out_file {
        Some(p) => p,
        None => {
            eprintln!("error: missing --out-file");
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

    let train_seeds = train_seeds_v1();
    let max_turns = DEFAULT_MAX_MAIN_TURNS;

    if let Some(parent) = out_file.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let file = match fs::File::create(&out_file) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot create {out_file:?}: {e}");
            return 1;
        }
    };
    let mut writer = BufWriter::new(file);

    let mut total_rows = 0;
    let mut successes = 0;

    println!("Collecting Round 2 trajectories on 256 training seeds (eps={epsilon})...");

    for (idx, &seed) in train_seeds.iter().enumerate() {
        let mut policy_rng = StableRng::new(0x4000_0000_u64.wrapping_add(seed));
        let mut pol = EpsilonQPolicy {
            weights: &weights,
            epsilon,
            remaining_turns: max_turns,
            max_turns,
        };

        let collected = collect_solo15_trajectory(
            seed,
            &mut pol,
            "q1_eps_0.10",
            2, // Round 2
            max_turns,
            &mut policy_rng,
        );

        if let Ok((records, summary)) = collected {
            if summary.outcome == Solo15Outcome::Reached15 {
                successes += 1;
            }
            for (step_idx, r) in records.into_iter().enumerate() {
                if let Ok(m) = r.materialize() {
                    let row = serde_json::json!({
                        "split": "train",
                        "seed": seed,
                        "behavior_policy": "q1_eps_0.10",
                        "step_index": step_idx,
                        "step_cost": m.step_cost,
                        "outcome": match m.outcome {
                            Solo15Outcome::Running => "running",
                            Solo15Outcome::Reached15 => "reached_15",
                            Solo15Outcome::Stalled => "stalled",
                            Solo15Outcome::TurnCap => "turn_cap",
                        },
                        "input_features": m.input_features,
                        "next_action_features": m.next_action_features,
                    });
                    let line = serde_json::to_string(&row).unwrap();
                    let _ = writeln!(writer, "{line}");
                    total_rows += 1;
                }
            }
        }
        if (idx + 1) % 64 == 0 {
            print!(".");
        }
    }
    let _ = writer.flush();
    println!("\nWrote {total_rows} new transitions from 256 training seeds ({successes}/256 reached 15).");
    0
}
