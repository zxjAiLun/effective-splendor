//! M49A-II Round 1 Data Aggregation:
//! Run Q0 policy with epsilon exploration on the SAME 256 training seeds.
//! Append new transitions to the training set to penalize looping failure routes.
//!
//! DISCIPLINE:
//! - strictly on train_seeds_v1() (256 seeds)
//! - zero validation seeds, zero canonical seeds
//! - policy RNG decoupled from env seed (depends on behavior tag, round, and trajectory ordinal)
//! - Q policy evaluated with live remaining main-turn budget at every step

use std::fs;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use splendor_agent::StableRng;
use splendor_analysis::m49a_collector::{collect_solo15_q_trajectory, train_seeds_v1};
use splendor_analysis::solo15::{Solo15Outcome, DEFAULT_MAX_MAIN_TURNS};

use crate::m49a_eval_command::load_weights_from_json;

const EXIT_USAGE: i32 = 2;

pub fn run_m49a_collect_round1(args: &[String]) -> i32 {
    let mut weights_path: Option<PathBuf> = None;
    let mut out_file: Option<PathBuf> = None;
    let mut epsilon: f64 = 0.15;
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
    let behavior_name = format!("q0_eps_{epsilon:.2}");

    println!("Collecting Round 1 trajectories on 256 training seeds ({behavior_name})...");

    let mut seen_seeds = std::collections::HashSet::new();

    for (ordinal, &seed) in train_seeds.iter().enumerate() {
        assert!(seen_seeds.insert(seed), "duplicate train seed {seed}");

        // P1-3: strictly decoupled from env_seed, depends on round tag and trajectory ordinal
        let mut policy_rng =
            StableRng::new(0x1001_0000_0000_0000_u64.wrapping_add(ordinal as u64));

        // P1-2: collect_solo15_q_trajectory maintains live remaining main turns at every decision step
        let collected = collect_solo15_q_trajectory(
            seed,
            &weights,
            epsilon,
            &behavior_name,
            1, // Round 1
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
                        "behavior_policy": behavior_name,
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
        if (ordinal + 1) % 64 == 0 {
            print!(".");
        }
    }
    let _ = writer.flush();
    println!(
        "\nWrote {total_rows} new transitions from 256 training seeds ({successes}/256 reached 15)."
    );
    0
}
