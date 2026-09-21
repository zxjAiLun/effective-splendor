//! M49A-II: export materialized horizon-aware transition tensors for the
//! PyTorch Efficiency-Q trainer.
//!
//! The command collects trajectories on the frozen training/validation seed
//! partitions with the authorized Round 0 behavior policies, materializes
//! every transition via the fail-closed `TransitionRecord::materialize()`
//! bridge (428-d horizon-aware features), and writes one JSONL file per
//! split. No canonical seeds are ever touched by this command.
//!
//! Information boundaries:
//! - `provenance` (env_seed, behavior_policy, round, step_index) is written
//!   only as audit metadata, never inside `input_features`;
//! - the JSONL rows contain only canonical tensors + audit fields;
//! - the dataset footer records the seed partition invariants asserted at
//!   export time (I-SEED-01).

use std::fs;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use serde::Serialize;
use splendor_agent::{HeuristicAgentPolicy, RandomAgentPolicy, StableRng};
use splendor_analysis::m49a_collector::{
    assert_seed_partitions_disjoint, collect_solo15_trajectory, train_seeds_v1,
    validation_seeds_v1, CategoryBiasedPolicy,
};
use splendor_analysis::solo15::DEFAULT_MAX_MAIN_TURNS;

/// Exit code for bad usage of *this* command.
const EXIT_USAGE: i32 = 2;
/// Target trajectories per split for Round 0 (fixed, frozen for this export).
const ROUND0_TRAJECTORY_MIX: [(&str, f64); 3] = [
    ("category_biased", 0.60),
    ("heuristic", 0.35),
    ("random", 0.05),
];

#[derive(Serialize)]
struct ExportRow<'a> {
    split: &'a str,
    seed: u64,
    behavior_policy: &'a str,
    step_index: usize,
    step_cost: f32,
    outcome: &'a str,
    input_features: Vec<f32>,
    next_action_features: Vec<Vec<f32>>,
}

pub fn run_m49a_export_round0(args: &[String]) -> i32 {
    let mut out_dir: Option<PathBuf> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--out-dir" => {
                out_dir = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            other => {
                eprintln!("error: unknown flag `{other}`");
                return EXIT_USAGE;
            }
        }
    }
    let out_dir = match out_dir {
        Some(d) => d,
        None => {
            eprintln!("error: missing required flag `--out-dir`");
            return EXIT_USAGE;
        }
    };
    if let Err(e) = export_round0(&out_dir) {
        eprintln!("error: {e}");
        return 1;
    }
    0
}

fn export_round0(out_dir: &PathBuf) -> Result<(), String> {
    fs::create_dir_all(out_dir).map_err(|e| format!("create out dir: {e}"))?;

    let train = train_seeds_v1();
    let val = validation_seeds_v1();
    // I-SEED-01 asserted at export time with an empty canonical set:
    // this command never evaluates canonical seeds.
    assert_seed_partitions_disjoint(&train, &val, &[]);

    // Per-seed deterministic policy RNG streams, distinct per behavior source.
    let rng_for = |source: &str, seed: u64| -> StableRng {
        let tag: u64 = match source {
            "category_biased" => 0x1000_0000,
            "heuristic" => 0x2000_0000,
            "random" => 0x3000_0000,
            _ => 0x4000_0000,
        };
        StableRng::new(tag.wrapping_add(seed))
    };

    let mut rows_by_split: Vec<(String, Vec<ExportRow>)> =
        vec![("train".to_string(), Vec::new()), ("validation".to_string(), Vec::new())];

    for (split_name, seeds) in [("train", &train), ("validation", &val)] {
        let n = seeds.len();
        // Trajectory quotas by behavior source, rounded deterministically.
        let n_cat = ((n as f64) * ROUND0_TRAJECTORY_MIX[0].1).round() as usize;
        let n_heu = ((n as f64) * ROUND0_TRAJECTORY_MIX[1].1).round() as usize;
        let n_rand = n - n_cat - n_heu; // remainder: random budget
        let quotas = [("category_biased", n_cat), ("heuristic", n_heu), ("random", n_rand)];

        let rows = rows_by_split
            .iter_mut()
            .find(|(s, _)| s == split_name)
            .map(|(_, v)| v)
            .expect("split row");

        for (source, count) in quotas {
            for &seed in seeds.iter().take(count) {
                let mut rng = rng_for(source, seed);
                let collected = match source {
                    "category_biased" => collect_solo15_trajectory(
                        seed,
                        &mut CategoryBiasedPolicy::new(0.20),
                        "category_biased_eps_0.20",
                        0,
                        DEFAULT_MAX_MAIN_TURNS,
                        &mut rng,
                    ),
                    "heuristic" => {
                        let mut p = HeuristicAgentPolicy::new();
                        collect_solo15_trajectory(
                            seed,
                            &mut p,
                            "heuristic_v1",
                            0,
                            DEFAULT_MAX_MAIN_TURNS,
                            &mut rng,
                        )
                    }
                    _ => {
                        let mut p = RandomAgentPolicy::new();
                        collect_solo15_trajectory(
                            seed,
                            &mut p,
                            "random_v1",
                            0,
                            DEFAULT_MAX_MAIN_TURNS,
                            &mut rng,
                        )
                    }
                };
                let (records, _summary) =
                    collected.map_err(|e| format!("collect {source} seed {seed}: {e}"))?;
                for (step_index, r) in records.into_iter().enumerate() {
                    let m = r
                        .materialize()
                        .map_err(|e| format!("materialize {source} seed {seed}: {e}"))?;
                    rows.push(ExportRow {
                        split: split_name,
                        seed,
                        behavior_policy: source,
                        step_index,
                        step_cost: m.step_cost,
                        outcome: outcome_str(&m.outcome),
                        input_features: m.input_features,
                        next_action_features: m.next_action_features,
                    });
                }
            }
        }
    }

    for (split_name, rows) in rows_by_split {
        let path = out_dir.join(format!("m49a_round0_{split_name}.jsonl"));
        let file = fs::File::create(&path).map_err(|e| format!("create {path:?}: {e}"))?;
        let mut w = BufWriter::new(file);
        for row in &rows {
            let line = serde_json::to_string(row).map_err(|e| format!("serialize: {e}"))?;
            writeln!(w, "{line}").map_err(|e| format!("write: {e}"))?;
        }
        w.flush().map_err(|e| format!("flush: {e}"))?;
        println!(
            "wrote {} rows to {}",
            rows.len(),
            path.display()
        );
    }
    println!("mix={:?}", ROUND0_TRAJECTORY_MIX);
    Ok(())
}

fn outcome_str(o: &splendor_analysis::Solo15Outcome) -> &'static str {
    use splendor_analysis::Solo15Outcome::*;
    match o {
        Running => "running",
        Reached15 => "reached_15",
        Stalled => "stalled",
        TurnCap => "turn_cap",
    }
}
