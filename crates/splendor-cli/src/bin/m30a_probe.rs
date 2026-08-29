//! M30A: Canonical Teacher Target Stability Probe (4-sample vs 16-sample search teacher targets on 256 stratified positions).

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
use splendor_replay::{replay_document_hash_v1, verify_replay_position, ReplayV1};
use splendor_search::SearchConfigV1;

const UNIFORM_FLOOR_MICROS: u32 = 100_000;
const SEARCH_VALUE_TARGET_SCALE_V1: u32 = 1_000_000;
const SEED_BLOCK_A: u64 = 20260810;
const SEED_BLOCK_B: u64 = 20260811;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SelectedPosition {
    pub index: usize,
    pub match_index: usize,
    pub source_id: String,
    pub ply: u32,
    pub actor: usize,
    pub phase: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CanonicalPositionTargetInfo {
    pub index: usize,
    pub match_index: usize,
    pub source_id: String,
    pub ply: u32,
    pub actor: usize,
    pub phase: String,
    pub legal_actions_count: usize,
    pub policy_micros_4_a: Vec<u32>,
    pub policy_micros_4_b: Vec<u32>,
    pub top1_4_a: Action,
    pub top1_4_b: Action,
    pub agreement_4: bool,
    pub jsd_4_nats: f64,
    pub policy_micros_16_a: Vec<u32>,
    pub policy_micros_16_b: Vec<u32>,
    pub top1_16_a: Action,
    pub top1_16_b: Action,
    pub agreement_16: bool,
    pub jsd_16_nats: f64,
}

/// Canonical even allocation matching crates/splendor-learning/src/teacher_targets.rs
pub fn even_allocation(total: u32, count: u32) -> Vec<u32> {
    if count == 0 {
        return Vec::new();
    }
    let base = total / count;
    let remainder = total % count;
    (0..count)
        .map(|index| base + u32::from(index < remainder))
        .collect()
}

/// Canonical proportional allocation matching crates/splendor-learning/src/teacher_targets.rs
pub fn proportional_allocation(
    total: u32,
    weights: &[u128],
    weight_sum: u128,
) -> Result<Vec<u32>, String> {
    let mut allocated = Vec::with_capacity(weights.len());
    let mut remainders = Vec::with_capacity(weights.len());
    let mut used = 0u32;
    for (index, weight) in weights.iter().enumerate() {
        let numerator = u128::from(total)
            .checked_mul(*weight)
            .ok_or_else(|| "policy allocation overflow".to_string())?;
        let quotient = u32::try_from(numerator / weight_sum)
            .map_err(|_| "policy allocation exceeds u32".to_string())?;
        used = used
            .checked_add(quotient)
            .ok_or_else(|| "policy allocation sum overflow".to_string())?;
        allocated.push(quotient);
        remainders.push((numerator % weight_sum, index));
    }
    remainders.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
    for (_, index) in remainders.into_iter().take((total - used) as usize) {
        allocated[index] += 1;
    }
    Ok(allocated)
}

/// Exact canonical policy target calculation returning u32 micros summing to 1_000_000
pub fn canonical_policy_targets(
    aggregates: &[RootActionAggregateV1],
    actor: usize,
    uniform_floor_micros: u32,
) -> Result<Vec<u32>, String> {
    if aggregates.is_empty()
        || aggregates
            .iter()
            .any(|entry| actor >= entry.utility_sum_by_player.len())
    {
        return Err("invalid utility aggregates for Policy projection".to_string());
    }
    let minimum = aggregates
        .iter()
        .map(|entry| entry.utility_sum_by_player[actor])
        .min()
        .ok_or_else(|| "utility projection has no minimum".to_string())?;
    let advantages = aggregates
        .iter()
        .map(|entry| {
            i128::from(entry.utility_sum_by_player[actor])
                .checked_sub(i128::from(minimum))
                .and_then(|value| u128::try_from(value).ok())
                .ok_or_else(|| "utility advantage overflow".to_string())
        })
        .collect::<Result<Vec<_>, _>>()?;
    let advantage_sum = advantages
        .iter()
        .try_fold(0u128, |sum, value| sum.checked_add(*value))
        .ok_or_else(|| "utility advantage sum overflow".to_string())?;
    let count = u32::try_from(aggregates.len()).map_err(|_| "too many root actions".to_string())?;
    let mut targets = even_allocation(uniform_floor_micros, count);
    let remaining = SEARCH_VALUE_TARGET_SCALE_V1 - uniform_floor_micros;
    let variable = if advantage_sum == 0 {
        even_allocation(remaining, count)
    } else {
        proportional_allocation(remaining, &advantages, advantage_sum)?
    };
    for (target, addition) in targets.iter_mut().zip(variable) {
        *target = target
            .checked_add(addition)
            .ok_or_else(|| "policy target overflow".to_string())?;
    }
    Ok(targets)
}

/// Exact First-Max Selection (matches torch.argmax and M25 teacher selection)
pub fn first_max_action(actions: &[Action], policy_micros: &[u32]) -> Action {
    assert_eq!(actions.len(), policy_micros.len());
    assert!(!actions.is_empty());
    let max_val = policy_micros.iter().copied().max().unwrap();
    let first_idx = policy_micros.iter().position(|&v| v == max_val).unwrap();
    actions[first_idx]
}

/// Jensen-Shannon Divergence from canonical u32 policy target micros
pub fn compute_jsd_micros(p_micros: &[u32], q_micros: &[u32]) -> f64 {
    assert_eq!(p_micros.len(), q_micros.len());
    let scale = SEARCH_VALUE_TARGET_SCALE_V1 as f64;
    let p: Vec<f64> = p_micros.iter().map(|&v| v as f64 / scale).collect();
    let q: Vec<f64> = q_micros.iter().map(|&v| v as f64 / scale).collect();

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

fn analyze_position_canonical(
    replay: &ReplayV1,
    ply: u32,
    viewer: PlayerId,
    sample_seed: u64,
    sample_count: u16,
) -> (Vec<Action>, Vec<u32>, Action) {
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
    let policy_micros = canonical_policy_targets(
        &result.action_aggregates,
        viewer.index(),
        UNIFORM_FLOOR_MICROS,
    )
    .expect("canonical policy targets");

    // Invariant: sum strictly equals 1_000_000
    let sum: u32 = policy_micros.iter().sum();
    assert_eq!(
        sum, SEARCH_VALUE_TARGET_SCALE_V1,
        "policy targets must sum strictly to 1_000_000"
    );

    let first_max = first_max_action(&actions, &policy_micros);
    (actions, policy_micros, first_max)
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
    println!("M30A: Canonical Teacher Target Stability Probe starting (Max 2 workers)...");

    let runner_path = PathBuf::from("crates/splendor-cli/src/bin/m30a_probe.rs");
    let runner_text = std::fs::read_to_string(&runner_path).expect("read runner source");
    let runner_sha256 = {
        let mut hasher = Sha256::new();
        hasher.update(runner_text.as_bytes());
        hex::encode(hasher.finalize())
    };
    println!("Runner source SHA-256: {}", runner_sha256);

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

    let mut by_match: HashMap<usize, Vec<&serde_json::Value>> = HashMap::new();
    for ex in examples {
        let match_idx = ex["evaluation_match_index"].as_u64().expect("match index") as usize;
        by_match.entry(match_idx).or_default().push(ex);
    }

    let mut selected_positions = Vec::with_capacity(256);
    let mut replay_hashes = Vec::with_capacity(256);

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

        let replay_path = format!(
            "local-artifacts/m25-generation/eval-run/matches/match-{:06}.replay.json",
            match_idx
        );
        let replay = read_replay(Path::new(&replay_path));
        let r_hash = replay_document_hash_v1(&replay).expect("replay hash");
        replay_hashes.push((match_idx, r_hash));
    }
    println!(
        "Selected {} stratified positions across 256 matches.",
        selected_positions.len()
    );

    // Compute ordered replay bundle digest across the 256 replays
    let replay_bundle_digest = {
        let mut hasher = Sha256::new();
        for (m_idx, h) in &replay_hashes {
            hasher.update(
                format!(
                    "{}:{}
",
                    m_idx, h
                )
                .as_bytes(),
            );
        }
        hex::encode(hasher.finalize())
    };
    println!(
        "Replay bundle digest (256 matches): {}",
        replay_bundle_digest
    );

    // Strictly enforce max 2 worker threads per user requirement
    let num_threads = 2;
    println!(
        "Running canonical search analyses across {} worker threads...",
        num_threads
    );

    let shared_selected = Arc::new(selected_positions);
    let results = Arc::new(Mutex::new(Vec::new()));

    let chunk_size = 256_usize.div_ceil(num_threads);
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

                // 4-sample Block A vs Block B (Canonical)
                let (actions_4a, policy_4a, top1_4a) =
                    analyze_position_canonical(&replay, pos.ply, viewer, SEED_BLOCK_A, 4);
                let (actions_4b, policy_4b, top1_4b) =
                    analyze_position_canonical(&replay, pos.ply, viewer, SEED_BLOCK_B, 4);
                assert_eq!(actions_4a, actions_4b);
                let jsd_4 = compute_jsd_micros(&policy_4a, &policy_4b);
                let agr_4 = top1_4a == top1_4b;

                // 16-sample Block A vs Block B (Canonical)
                let (actions_16a, policy_16a, top1_16a) =
                    analyze_position_canonical(&replay, pos.ply, viewer, SEED_BLOCK_A, 16);
                let (actions_16b, policy_16b, top1_16b) =
                    analyze_position_canonical(&replay, pos.ply, viewer, SEED_BLOCK_B, 16);
                assert_eq!(actions_16a, actions_16b);
                let jsd_16 = compute_jsd_micros(&policy_16a, &policy_16b);
                let agr_16 = top1_16a == top1_16b;

                let info = CanonicalPositionTargetInfo {
                    index: pos.index,
                    match_index: pos.match_index,
                    source_id: pos.source_id.clone(),
                    ply: pos.ply,
                    actor: pos.actor,
                    phase: pos.phase.clone(),
                    legal_actions_count: actions_4a.len(),
                    policy_micros_4_a: policy_4a,
                    policy_micros_4_b: policy_4b,
                    top1_4_a: top1_4a,
                    top1_4_b: top1_4b,
                    agreement_4: agr_4,
                    jsd_4_nats: jsd_4,
                    policy_micros_16_a: policy_16a,
                    policy_micros_16_b: policy_16b,
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
    println!("M30A Canonical Results Summary (256 Stratified Positions):");
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
        "STOP_4_TO_16_SAMPLE_SCALING_ROUTE"
    };
    println!("Decision: {}", decision);
    println!("==================================================");

    let out_json = serde_json::json!({
        "milestone": "M30A",
        "probe": "M07_CANONICAL_TEACHER_TARGET_STABILITY_PROBE",
        "provenance": {
            "dataset_file": "local-artifacts/m25-generation/m25-materialized-dataset.json",
            "dataset_file_sha256": ds_hash,
            "runner_file": "crates/splendor-cli/src/bin/m30a_probe.rs",
            "runner_file_sha256": runner_sha256,
            "replay_bundle_digest": replay_bundle_digest,
            "worker_threads": num_threads,
            "target_standard": "canonical_u32_micros_first_max_argmax",
        },
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

    let out_path =
        PathBuf::from("benchmarks/m30a-canonical-teacher-target-stability-probe.result.json");
    let out_text = serde_json::to_string_pretty(&out_json).expect("serialize json");
    std::fs::write(&out_path, out_text + "\n").expect("write result json");
    println!("Saved canonical result to {}", out_path.display());
}
