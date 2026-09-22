//! M49A Target Builder & Compact Dataset Emitter.
//!
//! Provides two CLI commands:
//! 1. `m49a-export-compact`: Exports a collected dataset into binary/compact form:
//!    - `current_x.f32`: [N, 428] float32 array of input features
//!    - `step_costs.f32`: [N] float32 array of step costs
//!    - `outcomes.u8`: [N] u8 array of outcome tags (0 = reached_15, 1 = stalled/turn_cap, 2 = running)
//!    - `compact_next.jsonl`: NDJSON lines of `M49ACompactTransitionV1` (only for Running records, or one per transition)
//! 2. `m49a-build-targets`: Given `compact_next.jsonl` (or binary/NDJSON records) and an `EfficiencyQWeightsV1` JSON:
//!    - Evaluates on-demand Bellman targets y = c + V(o')
//!    - Emits `targets.f32` containing N float32 values directly.

use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::PathBuf;

use splendor_analysis::m49a_collector::{M49ACompactTransitionV1, TransitionRecord};
use splendor_analysis::solo15::Solo15Outcome;

use crate::m49a_eval_command::load_weights_from_json;

const EXIT_USAGE: i32 = 2;

/// Outcome byte representation in binary datasets:
/// 0 = Reached15 (terminal success, V = 0)
/// 1 = Stalled or TurnCap (terminal failure, V = failure_penalty)
/// 2 = Running (non-terminal, V = min Q_target)
pub fn outcome_to_u8(outcome: Solo15Outcome) -> u8 {
    match outcome {
        Solo15Outcome::Reached15 => 0,
        Solo15Outcome::Stalled | Solo15Outcome::TurnCap => 1,
        Solo15Outcome::Running => 2,
    }
}

/// CLI runner for `m49a-build-targets`.
///
/// Usage:
///   splendor m49a-build-targets \
///     --transitions <path to compact_transitions.jsonl> \
///     --weights <path to target_net weights.json> \
///     --out-targets <path to targets.f32> \
///     [--failure-penalty 100.0]
pub fn run_m49a_build_targets(args: &[String]) -> i32 {
    let mut transitions_path: Option<PathBuf> = None;
    let mut weights_path: Option<PathBuf> = None;
    let mut out_targets: Option<PathBuf> = None;
    let mut failure_penalty: f32 = 100.0;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--transitions" => {
                transitions_path = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--weights" => {
                weights_path = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--out-targets" => {
                out_targets = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--failure-penalty" => {
                match args.get(i + 1) {
                    Some(s) => match s.parse::<f32>() {
                        Ok(val) if val.is_finite() && val >= 0.0 => failure_penalty = val,
                        _ => {
                            eprintln!("error: malformed --failure-penalty value `{s}`");
                            return EXIT_USAGE;
                        }
                    },
                    None => {
                        eprintln!("error: --failure-penalty requires a value");
                        return EXIT_USAGE;
                    }
                }
                i += 2;
            }
            other => {
                eprintln!("error: unknown flag `{other}`");
                return EXIT_USAGE;
            }
        }
    }

    let transitions_path = match transitions_path {
        Some(p) => p,
        None => {
            eprintln!("error: missing --transitions");
            return EXIT_USAGE;
        }
    };
    let weights_path = match weights_path {
        Some(p) => p,
        None => {
            eprintln!("error: missing --weights");
            return EXIT_USAGE;
        }
    };
    let out_targets = match out_targets {
        Some(p) => p,
        None => {
            eprintln!("error: missing --out-targets");
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

    if let Err(e) = weights.validate() {
        eprintln!("error: target weights failed validation: {e}");
        return 1;
    }

    let file = match File::open(&transitions_path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error opening {transitions_path:?}: {e}");
            return 1;
        }
    };
    let reader = BufReader::new(file);

    if let Some(parent) = out_targets.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let out_file = match File::create(&out_targets) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error creating {out_targets:?}: {e}");
            return 1;
        }
    };
    let mut writer = BufWriter::new(out_file);

    // Phase 1: parse all compact transitions into memory (compact: one next_obs +
    // legal-action list per transition, NOT expanded 428-d feature vectors).
    let mut transitions: Vec<M49ACompactTransitionV1> = Vec::new();
    for (line_idx, line_res) in reader.lines().enumerate() {
        let line = match line_res {
            Ok(l) => l,
            Err(e) => {
                eprintln!("error reading line {line_idx} from {transitions_path:?}: {e}");
                return 1;
            }
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let compact: M49ACompactTransitionV1 = match serde_json::from_str(trimmed) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("error deserializing compact transition line {line_idx}: {e}");
                return 1;
            }
        };
        transitions.push(compact);
    }

    let n = transitions.len();
    let mut targets = vec![0.0f32; n];

    // Phase 2: parallel target computation across worker threads. Each target is
    // an independent read-only min over next legal actions; embarrassingly parallel.
    let n_threads = std::thread::available_parallelism()
        .map(|v| v.get())
        .unwrap_or(1)
        .min(n.max(1));
    let chunk = n.div_ceil(n_threads.max(1));

    let error_flag = std::sync::atomic::AtomicBool::new(false);
    let weights_ref = &weights;
    let error_ref = &error_flag;
    std::thread::scope(|scope| {
        let mut handles = Vec::new();
        for (chunk_idx, out_chunk) in targets.chunks_mut(chunk.max(1)).enumerate() {
            let base = chunk_idx * chunk.max(1);
            let trans_slice = &transitions[base..base + out_chunk.len()];
            handles.push(scope.spawn(move || {
                for (i, compact) in trans_slice.iter().enumerate() {
                    if error_ref.load(std::sync::atomic::Ordering::Relaxed) {
                        return;
                    }
                    match compact.compute_target(weights_ref, failure_penalty) {
                        Ok(t) if t.is_finite() => out_chunk[i] = t,
                        Ok(t) => {
                            eprintln!("error: non-finite target at index {}: {t}", base + i);
                            error_ref.store(true, std::sync::atomic::Ordering::Relaxed);
                            return;
                        }
                        Err(e) => {
                            eprintln!("error computing target at index {}: {e}", base + i);
                            error_ref.store(true, std::sync::atomic::Ordering::Relaxed);
                            return;
                        }
                    }
                }
            }));
        }
        for h in handles {
            if h.join().is_err() {
                eprintln!("error: target worker thread panicked");
                error_ref.store(true, std::sync::atomic::Ordering::Relaxed);
            }
        }
    });

    if error_flag.load(std::sync::atomic::Ordering::Relaxed) {
        return 1;
    }

    // Phase 3: write targets in original order.
    let mut count = 0usize;
    for target in &targets {
        if let Err(e) = writer.write_all(&target.to_le_bytes()) {
            eprintln!("error writing target to {out_targets:?}: {e}");
            return 1;
        }
        count += 1;
    }

    if let Err(e) = writer.flush() {
        eprintln!("error flushing writer for {out_targets:?}: {e}");
        return 1;
    }

    println!("Computed and wrote {count} targets to {out_targets:?} ({n_threads} threads)");
    0
}

/// CLI runner for `m49a-export-compact`.
///
/// Converts a full transition dataset (or a directory/pattern of JSONL files) into:
/// - `current_x.f32`: [N, 428] float32 array
/// - `step_costs.f32`: [N] float32 array
/// - `outcomes.u8`: [N] u8 array (0=Reached15, 1=Failure, 2=Running)
/// - `compact_transitions.jsonl`: NDJSON lines of `M49ACompactTransitionV1`
///
/// Usage:
///   splendor m49a-export-compact \
///     --in-jsonl <path to records.jsonl> \
///     --out-dir <destination directory>
pub fn run_m49a_export_compact(args: &[String]) -> i32 {
    let mut in_jsonl_paths: Vec<PathBuf> = Vec::new();
    let mut out_dir: Option<PathBuf> = None;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--in-jsonl" => {
                if let Some(p) = args.get(i + 1).map(PathBuf::from) {
                    in_jsonl_paths.push(p);
                }
                i += 2;
            }
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
            eprintln!("error: missing --out-dir");
            return EXIT_USAGE;
        }
    };
    if in_jsonl_paths.is_empty() {
        eprintln!("error: missing --in-jsonl");
        return EXIT_USAGE;
    }

    if let Err(e) = fs::create_dir_all(&out_dir) {
        eprintln!("error creating out dir {out_dir:?}: {e}");
        return 1;
    }

    let x_path = out_dir.join("current_x.f32");
    let step_costs_path = out_dir.join("step_costs.f32");
    let outcomes_path = out_dir.join("outcomes.u8");
    let compact_path = out_dir.join("compact_transitions.jsonl");

    let x_file = match File::create(&x_path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot create {x_path:?}: {e}");
            return 1;
        }
    };
    let step_file = match File::create(&step_costs_path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot create {step_costs_path:?}: {e}");
            return 1;
        }
    };
    let outcomes_file = match File::create(&outcomes_path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot create {outcomes_path:?}: {e}");
            return 1;
        }
    };
    let compact_file = match File::create(&compact_path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot create {compact_path:?}: {e}");
            return 1;
        }
    };

    let mut x_writer = BufWriter::new(x_file);
    let mut step_writer = BufWriter::new(step_file);
    let mut outcomes_writer = BufWriter::new(outcomes_file);
    let mut compact_writer = BufWriter::new(compact_file);

    let mut total_count = 0usize;

    for in_path in &in_jsonl_paths {
        let file = match File::open(in_path) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("cannot open input {in_path:?}: {e}");
                return 1;
            }
        };
        let reader = BufReader::new(file);

        for (line_idx, line_res) in reader.lines().enumerate() {
            let line = match line_res {
                Ok(l) => l,
                Err(e) => {
                    eprintln!("error reading line {line_idx} from {in_path:?}: {e}");
                    return 1;
                }
            };
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }

            // The line could either be a full TransitionRecord or a serialized ExportRow
            // We handle both: first try TransitionRecord, else try serialized ExportRow
            let (input_features, step_cost, outcome, compact) =
                if let Ok(rec) = serde_json::from_str::<TransitionRecord>(trimmed) {
                    let compact = match M49ACompactTransitionV1::from_record(&rec) {
                        Ok(c) => c,
                        Err(e) => {
                            eprintln!("invalid TransitionRecord at line {line_idx} in {in_path:?}: {e}");
                            return 1;
                        }
                    };
                    let mat = match rec.materialize() {
                        Ok(m) => m,
                        Err(e) => {
                            eprintln!("failed to materialize TransitionRecord at line {line_idx}: {e}");
                            return 1;
                        }
                    };
                    (mat.input_features, mat.step_cost, mat.outcome, compact)
                } else if let Ok(val) = serde_json::from_str::<serde_json::Value>(trimmed) {
                    // ExportRow structure with required fields. No silent field
                    // fallbacks: any missing/invalid required field is fatal.
                    let input_feats: Vec<f32> =
                        match serde_json::from_value(val["input_features"].clone()) {
                            Ok(v) => v,
                            Err(e) => {
                                eprintln!("missing/invalid input_features at line {line_idx} in {in_path:?}: {e}");
                                return 1;
                            }
                        };
                    let step_cost = match val["step_cost"].as_f64() {
                        Some(v) => v as f32,
                        None => {
                            eprintln!("missing required field step_cost at line {line_idx} in {in_path:?}");
                            return 1;
                        }
                    };
                    let outcome_str = match val["outcome"].as_str() {
                        Some(s) => s,
                        None => {
                            eprintln!("missing required field outcome at line {line_idx} in {in_path:?}");
                            return 1;
                        }
                    };
                    let outcome = match outcome_str {
                        "reached_15" | "reached15" => Solo15Outcome::Reached15,
                        "stalled" => Solo15Outcome::Stalled,
                        "turn_cap" => Solo15Outcome::TurnCap,
                        "running" => Solo15Outcome::Running,
                        other => {
                            eprintln!("unknown outcome `{other}` at line {line_idx} in {in_path:?}");
                            return 1;
                        }
                    };
                    let max_turns = match val["max_main_turns"].as_u64() {
                        Some(v) => v as u32,
                        None => {
                            eprintln!("missing required field max_main_turns at line {line_idx} in {in_path:?}");
                            return 1;
                        }
                    };

                    let compact = match outcome {
                        Solo15Outcome::Running => {
                            let next_obs: Option<splendor_core::Observation> =
                                match serde_json::from_value(val["next_observation"].clone()) {
                                    Ok(v) => Some(v),
                                    Err(e) => {
                                        eprintln!("Running row missing/invalid next_observation at line {line_idx} in {in_path:?}: {e}");
                                        return 1;
                                    }
                                };
                            let next_acts: Vec<splendor_core::Action> =
                                match serde_json::from_value(val["next_legal_actions"].clone()) {
                                    Ok(v) => v,
                                    Err(e) => {
                                        eprintln!("Running row missing/invalid next_legal_actions at line {line_idx} in {in_path:?}: {e}");
                                        return 1;
                                    }
                                };
                            let next_remaining = match val["next_remaining_main_turns"].as_u64() {
                                Some(v) => v as u32,
                                None => {
                                    eprintln!("Running row missing next_remaining_main_turns at line {line_idx} in {in_path:?}");
                                    return 1;
                                }
                            };
                            M49ACompactTransitionV1 {
                                step_cost,
                                outcome,
                                next_observation: next_obs,
                                next_legal_actions: next_acts,
                                next_remaining_main_turns: next_remaining,
                                max_main_turns: max_turns,
                            }
                        }
                        _ => M49ACompactTransitionV1 {
                            step_cost,
                            outcome,
                            next_observation: None,
                            next_legal_actions: Vec::new(),
                            next_remaining_main_turns: 0,
                            max_main_turns: max_turns,
                        },
                    };

                    if let Err(e) = compact.validate() {
                        eprintln!("invalid compact transition at line {line_idx}: {e}");
                        return 1;
                    }

                    (input_feats, step_cost, outcome, compact)
                } else {
                    eprintln!("unrecognized JSON row at line {line_idx} in {in_path:?}");
                    return 1;
                };

            if input_features.len() != 428 {
                eprintln!(
                    "error: input_features length is {} != 428 at line {line_idx} in {in_path:?}",
                    input_features.len()
                );
                return 1;
            }

            for f in &input_features {
                if !f.is_finite() {
                    eprintln!("error: non-finite input feature at line {line_idx}");
                    return 1;
                }
                if let Err(e) = x_writer.write_all(&f.to_le_bytes()) {
                    eprintln!("error writing current_x: {e}");
                    return 1;
                }
            }

            if let Err(e) = step_writer.write_all(&step_cost.to_le_bytes()) {
                eprintln!("error writing step_cost: {e}");
                return 1;
            }

            let outcome_byte = outcome_to_u8(outcome);
            if let Err(e) = outcomes_writer.write_all(&[outcome_byte]) {
                eprintln!("error writing outcome byte: {e}");
                return 1;
            }

            let compact_line = match serde_json::to_string(&compact) {
                Ok(l) => l,
                Err(e) => {
                    eprintln!("error serializing compact transition: {e}");
                    return 1;
                }
            };
            if let Err(e) = writeln!(compact_writer, "{compact_line}") {
                eprintln!("error writing compact line: {e}");
                return 1;
            }

            total_count += 1;
        }
    }

    if let Err(e) = x_writer.flush() {
        eprintln!("flush x_writer: {e}");
        return 1;
    }
    if let Err(e) = step_writer.flush() {
        eprintln!("flush step_writer: {e}");
        return 1;
    }
    if let Err(e) = outcomes_writer.flush() {
        eprintln!("flush outcomes_writer: {e}");
        return 1;
    }
    if let Err(e) = compact_writer.flush() {
        eprintln!("flush compact_writer: {e}");
        return 1;
    }

    println!("Exported {total_count} transitions to binary & compact dataset in {out_dir:?}");
    0
}

