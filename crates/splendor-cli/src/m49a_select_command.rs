//! C1a: post-training model selection, NOT early stopping or a stability fix.
//! Owner froze this rule after C1; it is not retroactive preregistration of C1.
//! Future comparisons must use the same eight checkpoints and selection rule.

use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use splendor_analysis::m49a_collector::validation_seeds_v1;

use crate::atomic_output::commit_single;
use crate::m49a_eval_command::{evaluate_weights_on_validation, load_weights_with_sha256};

const SELECTION_CONTRACT: &str = "m49a_validation_select_v1";
const EVALUATION_CONTRACT: &str = "m49a_validation_64_cap100_rng_ordinal_v1";
const SCHEDULE: [u32; 8] = [10, 20, 30, 40, 50, 60, 70, 80];
const CRITERION: [&str; 4] = [
    "max_success_count",
    "min_j_val",
    "min_success_mean_turns",
    "min_iteration",
];

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CheckpointRow {
    iteration: u32,
    weights_path: PathBuf,
    weights_sha256: String,
    success_count: usize,
    failures: usize,
    j_val: f64,
    /// None (JSON null), never a fictitious zero-turn success, if success_count=0.
    successful_mean_turns: Option<f64>,
}

/// The selector consumes these measurement fields. A saved SelectionReport may
/// be replayed as input: its previous selection fields are deliberately ignored.
#[derive(Clone, Debug, Serialize, Deserialize)]
struct EvaluationReports {
    evaluation_contract: String,
    checkpoint_schedule: Vec<u32>,
    validation_seeds: Vec<u64>,
    max_main_turns: u32,
    evaluated: Vec<CheckpointRow>,
}

#[derive(Debug, Serialize)]
struct SelectionKey {
    success_count: usize,
    j_val: f64,
    successful_mean_turns: Option<f64>,
}

#[derive(Debug, Serialize)]
struct SelectionReport {
    selection_contract: &'static str,
    criterion: [&'static str; 4],
    #[serde(flatten)]
    measurements: EvaluationReports,
    selected_iteration: u32,
    selected_weights_path: PathBuf,
    selected_weights_sha256: String,
    selection_key: SelectionKey,
}

fn compare_rows(a: &CheckpointRow, b: &CheckpointRow) -> Ordering {
    // Inputs are validated before this comparator is called. No NaN-as-tie fallback.
    b.success_count
        .cmp(&a.success_count)
        .then_with(|| a.j_val.total_cmp(&b.j_val))
        .then_with(|| {
            a.successful_mean_turns
                .unwrap_or(f64::INFINITY)
                .total_cmp(&b.successful_mean_turns.unwrap_or(f64::INFINITY))
        })
        .then_with(|| a.iteration.cmp(&b.iteration))
}

/// Pure deterministic selection over a COMPLETE frozen schedule; no I/O or rollout.
fn select_checkpoint_v1(rows: &[CheckpointRow]) -> Result<&CheckpointRow, String> {
    let mut iterations: Vec<_> = rows.iter().map(|r| r.iteration).collect();
    iterations.sort_unstable();
    if iterations != SCHEDULE {
        return Err("reports must contain each of [10,20,30,40,50,60,70,80] exactly once".into());
    }
    for r in rows {
        if r.success_count > 64 || r.failures != 64 - r.success_count {
            return Err(format!(
                "iter {}: inconsistent success/failure count",
                r.iteration
            ));
        }
        if !r.j_val.is_finite() || !(0.0..=101.0).contains(&r.j_val) {
            return Err(format!("iter {}: invalid J_val", r.iteration));
        }
        let mean = match (r.success_count, r.successful_mean_turns) {
            (0, None) => 0.0,
            (1..=64, Some(m)) if m.is_finite() && (1.0..=100.0).contains(&m) => m,
            _ => return Err(format!("iter {}: invalid successful mean", r.iteration)),
        };
        let expected = (mean * r.success_count as f64 + 101.0 * r.failures as f64) / 64.0;
        if (r.j_val - expected).abs() > 1e-10 {
            return Err(format!(
                "iter {}: J_val inconsistent with counts/mean (use unrounded metrics)",
                r.iteration
            ));
        }
        if r.weights_path.as_os_str().is_empty()
            || r.weights_sha256.len() != 64
            || !r
                .weights_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(format!(
                "iter {}: missing/invalid weights identity",
                r.iteration
            ));
        }
    }
    rows.iter()
        .min_by(|a, b| compare_rows(a, b))
        .ok_or_else(|| "empty reports".into())
}

fn make_report(mut measurements: EvaluationReports) -> Result<SelectionReport, String> {
    if measurements.evaluation_contract != EVALUATION_CONTRACT
        || measurements.checkpoint_schedule != SCHEDULE
        || measurements.validation_seeds != validation_seeds_v1()
        || measurements.max_main_turns != 100
    {
        return Err("evaluation contract/cohort/cap/schedule mismatch".into());
    }
    measurements.evaluated.sort_by_key(|r| r.iteration);
    let selected = select_checkpoint_v1(&measurements.evaluated)?;
    Ok(SelectionReport {
        selection_contract: SELECTION_CONTRACT,
        criterion: CRITERION,
        selected_iteration: selected.iteration,
        selected_weights_path: selected.weights_path.clone(),
        selected_weights_sha256: selected.weights_sha256.clone(),
        selection_key: SelectionKey {
            success_count: selected.success_count,
            j_val: selected.j_val,
            successful_mean_turns: selected.successful_mean_turns,
        },
        measurements,
    })
}

struct Args {
    checkpoint_dir: Option<PathBuf>,
    reports_json: Option<PathBuf>,
    out_json: PathBuf,
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut flags = BTreeMap::new();
    let mut i = 0;
    while i < args.len() {
        let flag = args[i].as_str();
        if ![
            "--checkpoint-dir",
            "--reports-json",
            "--schedule",
            "--out-json",
        ]
        .contains(&flag)
        {
            return Err(format!("unknown flag `{flag}`"));
        }
        let value = args
            .get(i + 1)
            .filter(|s| !s.is_empty() && !s.starts_with("--"))
            .ok_or_else(|| format!("{flag} requires a value"))?;
        if flags.insert(flag, value.as_str()).is_some() {
            return Err(format!("duplicate flag `{flag}`"));
        }
        i += 2;
    }
    if let Some(schedule) = flags.get("--schedule") {
        let values: Vec<u32> = schedule
            .split(',')
            .map(|s| s.trim().parse::<u32>())
            .collect::<Result<_, _>>()
            .map_err(|_| "malformed schedule")?;
        if values != SCHEDULE {
            return Err("v1 schedule is fixed at 10,20,30,40,50,60,70,80".into());
        }
    }
    let checkpoint_dir = flags.get("--checkpoint-dir").map(PathBuf::from);
    let reports_json = flags.get("--reports-json").map(PathBuf::from);
    if checkpoint_dir.is_some() == reports_json.is_some() {
        return Err("provide exactly one of --checkpoint-dir or --reports-json".into());
    }
    let out_json = flags
        .get("--out-json")
        .map(PathBuf::from)
        .ok_or("missing --out-json")?;
    Ok(Args {
        checkpoint_dir,
        reports_json,
        out_json,
    })
}

fn run(args: Args) -> Result<SelectionReport, String> {
    if args.out_json.exists() {
        return Err(format!("refusing to overwrite {:?}", args.out_json));
    }
    let measurements = if let Some(path) = args.reports_json {
        let bytes = fs::read(&path).map_err(|e| format!("read {path:?}: {e}"))?;
        let reports: EvaluationReports =
            serde_json::from_slice(&bytes).map_err(|e| format!("parse evaluation reports: {e}"))?;
        // Validate metrics before I/O, then bind ALL reports to current weight bytes.
        make_report(reports.clone())?;
        for row in &reports.evaluated {
            let (_, sha) = load_weights_with_sha256(&row.weights_path)?;
            if sha != row.weights_sha256 {
                return Err(format!("iter {}: weights SHA256 mismatch", row.iteration));
            }
        }
        reports
    } else {
        let dir = args.checkpoint_dir.expect("validated exclusive input");
        // Preflight the complete set before ANY rollout. No skipped checkpoints.
        let mut checkpoints = Vec::new();
        for it in SCHEDULE {
            let path = dir.join(format!("weights_iter{it:03}.json"));
            let (weights, sha) = load_weights_with_sha256(&path)?;
            checkpoints.push((it, path, weights, sha));
        }
        let mut rows = Vec::new();
        for (it, path, weights, sha) in checkpoints {
            let m =
                evaluate_weights_on_validation(&weights).map_err(|e| format!("iter {it}: {e}"))?;
            println!(
                "iter {it:>3}: success {}/64, failures {}, J_val {:.6}",
                m.success_count, m.failures, m.j_val
            );
            rows.push(CheckpointRow {
                iteration: it,
                weights_path: path,
                weights_sha256: sha,
                success_count: m.success_count,
                failures: m.failures,
                j_val: m.j_val,
                successful_mean_turns: (m.success_count > 0).then_some(m.successful_mean_turns),
            });
        }
        EvaluationReports {
            evaluation_contract: EVALUATION_CONTRACT.into(),
            checkpoint_schedule: SCHEDULE.to_vec(),
            validation_seeds: validation_seeds_v1(),
            max_main_turns: 100,
            evaluated: rows,
        }
    };
    let report = make_report(measurements)?;
    let json = serde_json::to_string_pretty(&report).map_err(|e| e.to_string())? + "\n";
    if let Some(parent) = args.out_json.parent().filter(|p| !p.as_os_str().is_empty()) {
        fs::create_dir_all(parent).map_err(|e| format!("create report parent: {e}"))?;
    }
    commit_single(&args.out_json, &json).map_err(|e| format!("publish selection report: {e}"))?;
    Ok(report)
}

/// `--checkpoint-dir DIR` measures the frozen eight checkpoints once; alternatively
/// `--reports-json FILE` replays their reports with no rollout. `--out-json` is required.
/// Paths in reports are interpreted relative to the invocation cwd, as in the CLI.
pub fn run_m49a_select_checkpoint(args: &[String]) -> i32 {
    let args = match parse_args(args) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("usage error: {e}");
            return 2;
        }
    };
    match run(args) {
        Ok(r) => {
            println!(
                "SELECTED ({SELECTION_CONTRACT}): iter {} | success {}/64 | J_val {:.6}",
                r.selected_iteration, r.selection_key.success_count, r.selection_key.j_val
            );
            0
        }
        Err(e) => {
            eprintln!("error: {e}");
            1
        }
    }
}

#[cfg(test)]
#[path = "m49a_select_tests.rs"]
mod tests;
