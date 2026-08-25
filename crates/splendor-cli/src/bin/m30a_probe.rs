//! M30A: Teacher Target Stability Probe (4-sample vs 16-sample search teacher targets on 256 stratified positions).

use std::collections::HashMap;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::thread;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_core::{visible_events, Action, Audience, FullState, GameConfig, PlayerId, Ruleset};
use splendor_imperfect_search::{
    analyze_player_view_v1, RootActionAggregateV1, RootDeterminizationConfigV1,
};
use splendor_replay::{verify_replay_position, ReplayV1};
use splendor_search::SearchConfigV1;

const UNIFORM_FLOOR_MICROS: u32 = 100_000;
const SEARCH_SCALE: u32 = 1_000_000;
const SEED_BLOCK_A: u64 = 20260810;
const SEED_BLOCK_B: u64 = 20260811;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SelectedPosition {
    index: usize,
    match_index: usize,
    source_id: String,
    ply: u32,
    actor: usize,
    phase: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct PositionTargetInfo {
    index: usize,
    match_index: usize,
    source_id: String,
    ply: u32,
    actor: usize,
    phase: String,
    legal_actions_count: usize,
    top1_4_a: Action,
    top1_4_b: Action,
    agreement_4: bool,
    jsd_4_nats: f64,
    top1_16_a: Action,
    top1_16_b: Action,
    agreement_16: bool,
    jsd_16_nats: f64,
}

fn compute_policy_target(
    aggregates: &[RootActionAggregateV1],
    actor: usize,
    uniform_floor_micros: u32,
) -> Vec<f64> {
    let minimum = aggregates
        .iter()
        .map(|entry| entry.utility_sum_by_player[actor])
        .min()
        .unwrap_or(0);
    let advantages = aggregates
        .iter()
        .map(|entry| (entry.utility_sum_by_player[actor] as i64 - minimum as i64).max(0) as u64)
        .collect::<Vec<_>>();
    let advantage_sum: u64 = advantages.iter().sum();
    let count = aggregates.len();
    if count == 0 {
        return Vec::new();
    }
    let floor_per_action = (uniform_floor_micros as f64) / (SEARCH_SCALE as f64) / (count as f64);
    let remaining = (SEARCH_SCALE - uniform_floor_micros) as f64 / (SEARCH_SCALE as f64);

    if advantage_sum == 0 {
        vec![1.0 / count as f64; count]
    } else {
        advantages
            .iter()
            .map(|&adv| floor_per_action + remaining * (adv as f64) / (advantage_sum as f64))
            .collect()
    }
}

fn compute_jsd(p: &[f64], q: &[f64]) -> f64 {
    assert_eq!(p.len(), q.len());
    let mut kl_pm = 0.0;
    let mut kl_qm = 0.0;
    for (&pi, &qi) in p.iter().zip(q.iter()) {
        let m = 0.5 * (pi + qi);
        if pi > 1e-12 {
            kl_pm += pi * (pi / m).ln();
        }
        if qi > 1e-12 {
            kl_qm += qi * (qi / m).ln();
        }
    }
    0.5 * (kl_pm + kl_qm)
}

fn read_replay(path: &Path) -> ReplayV1 {
    let mut file = File::open(path).expect("cannot open replay");
    let mut text = String::new();
    file.read_to_string(&mut text).expect("read replay text");
    serde_json::from_str(&text).expect("parse replay JSON")
}

fn reconstruct_visible_prefix(
    replay: &ReplayV1,
    ply: u32,
    viewer: PlayerId,
) -> (FullState, Vec<splendor_core::VisibleEvent>) {
    let ruleset = Ruleset::base_v1();
    let (mut state, setup) = FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset,
    })
    .expect("setup state");

    let audience = Audience::Player(viewer);
    let mut visible_history = visible_events(&setup.events, audience);
    for step in replay.steps.iter().take(ply as usize) {
        let step_result = state.apply(step.action).expect("apply step action");
        visible_history.extend(visible_events(&step_result.events, audience));
    }
    (state, visible_history)
}

fn analyze_position(
    replay: &ReplayV1,
    ply: u32,
    viewer: PlayerId,
    sample_seed: u64,
    sample_count: u16,
) -> (Vec<Action>, Vec<f64>, Action) {
    let _position = verify_replay_position(replay, ply).expect("verify replay position");
    let (state, visible_history) = reconstruct_visible_prefix(replay, ply, viewer);
    let observation = state.observation(viewer);

    let config = RootDeterminizationConfigV1 {
        sample_seed,
        sample_count,
        continuation_search: SearchConfigV1 {
            max_depth_turns: 1,
            max_nodes: 2000,
        },
    };

    let analysis =
        analyze_player_view_v1(Ruleset::base_v1(), &observation, &visible_history, config)
            .expect("analyze player view");
    let result = analysis.result();
    let actions = result
        .action_aggregates
        .iter()
        .map(|agg| agg.action)
        .collect::<Vec<_>>();
    let policy = compute_policy_target(
        &result.action_aggregates,
        viewer.index(),
        UNIFORM_FLOOR_MICROS,
    );

    let best_idx = policy
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
        .map(|(idx, _)| idx)
        .unwrap();

    let best_act = actions[best_idx];
    (actions, policy, best_act)
}

fn median(mut vals: Vec<f64>) -> f64 {
    if vals.is_empty() {
        return 0.0;
    }
    vals.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mid = vals.len() / 2;
    if vals.len() % 2 == 0 {
        0.5 * (vals[mid - 1] + vals[mid])
    } else {
        vals[mid]
    }
}

fn percentile(mut vals: Vec<f64>, p: f64) -> f64 {
    if vals.is_empty() {
        return 0.0;
    }
    vals.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let idx = ((vals.len() - 1) as f64 * p).round() as usize;
    vals[idx]
}

fn main() {
    println!("M30A: Teacher Target Stability Probe starting...");

    let ds_path = PathBuf::from("local-artifacts/m25-generation/m25-materialized-dataset.json");
    let ds_text = std::fs::read_to_string(&ds_path).expect("read dataset");
    let ds_hash = {
        let mut hasher = Sha256::new();
        hasher.update(ds_text.as_bytes());
        hex::encode(hasher.finalize())
    };
    println!("Dataset file SHA-256: {}", ds_hash);

    let ds_json: serde_json::Value = serde_json::from_str(&ds_text).expect("parse json");
    let examples = ds_json["examples"].as_array().expect("examples array");

    // Group examples by match index (0..255)
    let mut by_match: HashMap<usize, Vec<&serde_json::Value>> = HashMap::new();
    for ex in examples {
        let match_idx = ex["evaluation_match_index"].as_u64().expect("match index") as usize;
        by_match.entry(match_idx).or_default().push(ex);
    }

    // Stratified Selection of exactly 256 positions (1 per match):
    // Match index 0..63 (64 games): Early game (ply < 16)
    // Match index 64..143 (80 games): Mid game (16 <= ply < 36)
    // Match index 144..255 (112 games): Late game (ply >= 36)
    let mut selected_positions = Vec::with_capacity(256);
    for match_idx in 0..256 {
        let match_examples = by_match.get(&match_idx).expect("match examples missing");
        let target_phase = if match_idx < 64 {
            "early"
        } else if match_idx < 144 {
            "mid"
        } else {
            "late"
        };

        let candidate_examples = match_examples
            .iter()
            .filter(|ex| {
                let ply = ex["ply"].as_u64().unwrap() as u32;
                match target_phase {
                    "early" => ply < 16,
                    "mid" => (16..36).contains(&ply),
                    "late" => ply >= 36,
                    _ => unreachable!(),
                }
            })
            .copied()
            .collect::<Vec<_>>();

        let chosen_ex = if !candidate_examples.is_empty() {
            candidate_examples[candidate_examples.len() / 2]
        } else {
            match_examples[match_examples.len() / 2]
        };

        let pos = SelectedPosition {
            index: match_idx,
            match_index: match_idx,
            source_id: chosen_ex["source_id"].as_str().unwrap().to_string(),
            ply: chosen_ex["ply"].as_u64().unwrap() as u32,
            actor: chosen_ex["actor"].as_u64().unwrap() as usize,
            phase: target_phase.to_string(),
        };
        selected_positions.push(pos);
    }
    println!(
        "Selected {} stratified positions across 256 matches.",
        selected_positions.len()
    );

    let num_threads = thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(8);
    println!(
        "Running search analyses across {} worker threads...",
        num_threads
    );

    let shared_selected = Arc::new(selected_positions);
    let results = Arc::new(Mutex::new(Vec::new()));

    let chunk_size = (256 + num_threads - 1) / num_threads;
    let mut handles = Vec::new();

    for t_idx in 0..num_threads {
        let shared_selected = Arc::clone(&shared_selected);
        let results = Arc::clone(&results);
        let handle = thread::spawn(move || {
            let start = t_idx * chunk_size;
            let end = (start + chunk_size).min(shared_selected.len());
            for i in start..end {
                let pos = &shared_selected[i];
                let viewer = PlayerId(pos.actor as u8);

                let replay_path = format!(
                    "local-artifacts/m25-generation/eval-run/matches/match-{:06}.replay.json",
                    pos.match_index
                );
                let replay = read_replay(Path::new(&replay_path));

                // 4-sample Block A vs Block B
                let (actions_4a, policy_4a, top1_4a) =
                    analyze_position(&replay, pos.ply, viewer, SEED_BLOCK_A, 4);
                let (actions_4b, policy_4b, top1_4b) =
                    analyze_position(&replay, pos.ply, viewer, SEED_BLOCK_B, 4);
                assert_eq!(actions_4a, actions_4b);
                let jsd_4 = compute_jsd(&policy_4a, &policy_4b);
                let agr_4 = top1_4a == top1_4b;

                // 16-sample Block A vs Block B
                let (actions_16a, policy_16a, top1_16a) =
                    analyze_position(&replay, pos.ply, viewer, SEED_BLOCK_A, 16);
                let (actions_16b, policy_16b, top1_16b) =
                    analyze_position(&replay, pos.ply, viewer, SEED_BLOCK_B, 16);
                assert_eq!(actions_16a, actions_16b);
                let jsd_16 = compute_jsd(&policy_16a, &policy_16b);
                let agr_16 = top1_16a == top1_16b;

                let info = PositionTargetInfo {
                    index: pos.index,
                    match_index: pos.match_index,
                    source_id: pos.source_id.clone(),
                    ply: pos.ply,
                    actor: pos.actor,
                    phase: pos.phase.clone(),
                    legal_actions_count: actions_4a.len(),
                    top1_4_a: top1_4a,
                    top1_4_b: top1_4b,
                    agreement_4: agr_4,
                    jsd_4_nats: jsd_4,
                    top1_16_a: top1_16a,
                    top1_16_b: top1_16b,
                    agreement_16: agr_16,
                    jsd_16_nats: jsd_16,
                };

                let mut lock = results.lock().unwrap();
                lock.push(info);
            }
        });
        handles.push(handle);
    }

    for h in handles {
        h.join().unwrap();
    }

    let mut all_results = results.lock().unwrap().drain(..).collect::<Vec<_>>();
    all_results.sort_by_key(|r| r.index);

    let n = all_results.len() as f64;
    let agr_4_count = all_results.iter().filter(|r| r.agreement_4).count();
    let agr_16_count = all_results.iter().filter(|r| r.agreement_16).count();

    let agr_4_rate = (agr_4_count as f64) / n;
    let agr_16_rate = (agr_16_count as f64) / n;
    let agr_delta = agr_16_rate - agr_4_rate;

    let jsd_4_vals = all_results.iter().map(|r| r.jsd_4_nats).collect::<Vec<_>>();
    let jsd_16_vals = all_results
        .iter()
        .map(|r| r.jsd_16_nats)
        .collect::<Vec<_>>();

    let jsd_4_med = median(jsd_4_vals.clone());
    let jsd_16_med = median(jsd_16_vals.clone());
    let jsd_med_reduction = (jsd_4_med - jsd_16_med) / jsd_4_med;

    let jsd_4_mean = jsd_4_vals.iter().sum::<f64>() / n;
    let jsd_16_mean = jsd_16_vals.iter().sum::<f64>() / n;

    println!("==================================================");
    println!("M30A Results Summary (256 Stratified Positions):");
    println!("4-Sample Repeat Stability:");
    println!(
        "  Top-1 Agreement: {:.2}% ({}/{})",
        agr_4_rate * 100.0,
        agr_4_count,
        256
    );
    println!(
        "  Median JSD: {:.4} nats (Mean: {:.4}, P25: {:.4}, P75: {:.4})",
        jsd_4_med,
        jsd_4_mean,
        percentile(jsd_4_vals.clone(), 0.25),
        percentile(jsd_4_vals.clone(), 0.75)
    );
    println!("16-Sample Repeat Stability:");
    println!(
        "  Top-1 Agreement: {:.2}% ({}/{})",
        agr_16_rate * 100.0,
        agr_16_count,
        256
    );
    println!(
        "  Median JSD: {:.4} nats (Mean: {:.4}, P25: {:.4}, P75: {:.4})",
        jsd_16_med,
        jsd_16_mean,
        percentile(jsd_16_vals.clone(), 0.25),
        percentile(jsd_16_vals.clone(), 0.75)
    );
    println!("Comparison (16-sample vs 4-sample):");
    println!(
        "  Agreement Delta: {:+.2} pp (Target >= +8.0 pp)",
        agr_delta * 100.0
    );
    println!(
        "  Median JSD Relative Reduction: {:.2}% (Target >= 25.0%)",
        jsd_med_reduction * 100.0
    );

    let agr_gate_pass = agr_delta >= 0.08;
    let jsd_gate_pass = jsd_med_reduction >= 0.25;
    let m30a_pass = agr_gate_pass && jsd_gate_pass;

    let decision = if m30a_pass {
        "M30A_PASS_AUTHORIZE_M30B_REBUILD"
    } else {
        "STOP_TEACHER_VARIANCE_ROUTE"
    };
    println!("Decision: {}", decision);
    println!("==================================================");

    let out_json = serde_json::json!({
        "milestone": "M30A",
        "probe": "M07_TEACHER_TARGET_STABILITY_PROBE",
        "positions_count": 256,
        "search_parameters": {
            "max_depth_turns": 1,
            "max_nodes": 2000,
            "uniform_floor_micros": UNIFORM_FLOOR_MICROS,
            "sample_seed_block_a": SEED_BLOCK_A,
            "sample_seed_block_b": SEED_BLOCK_B,
        },
        "sample_4": {
            "top1_agreement_rate": agr_4_rate,
            "top1_agreement_count": agr_4_count,
            "jsd_median_nats": jsd_4_med,
            "jsd_mean_nats": jsd_4_mean,
            "jsd_p25_nats": percentile(jsd_4_vals.clone(), 0.25),
            "jsd_p75_nats": percentile(jsd_4_vals.clone(), 0.75),
        },
        "sample_16": {
            "top1_agreement_rate": agr_16_rate,
            "top1_agreement_count": agr_16_count,
            "jsd_median_nats": jsd_16_med,
            "jsd_mean_nats": jsd_16_mean,
            "jsd_p25_nats": percentile(jsd_16_vals.clone(), 0.25),
            "jsd_p75_nats": percentile(jsd_16_vals.clone(), 0.75),
        },
        "comparison": {
            "top1_agreement_delta_pp": agr_delta * 100.0,
            "median_jsd_relative_reduction_pct": jsd_med_reduction * 100.0,
            "top1_agreement_target": ">= +8.0 pp",
            "top1_agreement_pass": agr_gate_pass,
            "median_jsd_reduction_target": ">= 25.0%",
            "median_jsd_reduction_pass": jsd_gate_pass,
            "m30a_pass": m30a_pass,
            "decision": decision,
            "arena_authorized": false,
            "model_training_authorized": false,
        },
        "positions": all_results
    });

    let out_path = PathBuf::from("benchmarks/m30a-teacher-target-stability-probe.result.json");
    let out_text = serde_json::to_string_pretty(&out_json).expect("serialize json");
    std::fs::write(&out_path, out_text + "\n").expect("write result json");
    println!("Saved result to {}", out_path.display());
}
