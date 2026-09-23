//! C1a process-level tests. Synthetic reports test selection transport only;
//! they are NOT rollout measurements or evidence of policy strength.
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use splendor_learning::EfficiencyQWeightsV1;

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Sandbox(PathBuf);
impl Sandbox {
    fn new() -> Self {
        let dir = std::env::temp_dir().join(format!(
            "m49a-selection-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }
    fn call(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_splendor"))
            .args(args)
            .current_dir(&self.0)
            .output()
            .unwrap()
    }
    fn write(&self, path: &str, data: &Value) {
        fs::write(self.0.join(path), serde_json::to_vec(data).unwrap()).unwrap();
    }
}
impl Drop for Sandbox {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn fixture(s: &Sandbox) -> Value {
    let w = EfficiencyQWeightsV1 {
        fc1_w: vec![vec![0.0; 428]; 256],
        fc1_b: vec![0.0; 256],
        ln1_w: vec![1.0; 256],
        ln1_b: vec![0.0; 256],
        fc2_w: vec![vec![0.0; 256]; 128],
        fc2_b: vec![0.0; 128],
        fc3_w: vec![vec![0.0; 128]],
        fc3_b: vec![0.0],
    };
    let bytes = serde_json::to_vec(&w).unwrap();
    let hash = hex::encode(Sha256::digest(&bytes));
    fs::write(s.0.join("weights.json"), bytes).unwrap();
    let schedule = [10, 20, 30, 40, 50, 60, 70, 80];
    let rows: Vec<_> = schedule
        .iter()
        .map(|&it| {
            let (success, sum) = match it {
                30 => (58, 1817),
                50 => (59, 2072),
                _ => (55, 1833),
            };
            json!({"iteration":it, "weights_path":"weights.json", "weights_sha256":hash,
            "success_count":success, "failures":64-success,
            "j_val":(sum + 101*(64-success)) as f64/64.0,
            "successful_mean_turns":sum as f64/success as f64})
        })
        .collect();
    json!({"evaluation_contract":"m49a_validation_64_cap100_rng_ordinal_v1",
        "checkpoint_schedule":schedule, "validation_seeds":splendor_analysis::m49a_collector::validation_seeds_v1(),
        "max_main_turns":100, "evaluated":rows})
}

#[test]
fn report_only_selection_is_deterministic_and_ignores_old_selection() {
    let s = Sandbox::new();
    s.write("reports.json", &fixture(&s));
    let o = s.call(&[
        "m49a-select-checkpoint",
        "--reports-json",
        "reports.json",
        "--out-json",
        "chosen.json",
    ]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let bytes = fs::read(s.0.join("chosen.json")).unwrap();
    let mut chosen: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(chosen["selected_iteration"], 50);
    assert_eq!(chosen["selection_key"]["success_count"], 59);
    assert_eq!(chosen["selection_key"]["j_val"], 40.265625);
    assert_eq!(
        chosen["criterion"],
        json!([
            "max_success_count",
            "min_j_val",
            "min_success_mean_turns",
            "min_iteration"
        ])
    );
    chosen["selected_iteration"] = json!(30); // selection must be recomputed from measurements
    chosen["evaluated"].as_array_mut().unwrap().reverse();
    s.write("reordered.json", &chosen);
    let o = s.call(&[
        "m49a-select-checkpoint",
        "--reports-json",
        "reordered.json",
        "--out-json",
        "replayed.json",
    ]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert_eq!(bytes, fs::read(s.0.join("replayed.json")).unwrap());
    let o = s.call(&[
        "m49a-select-checkpoint",
        "--reports-json",
        "reports.json",
        "--out-json",
        "chosen.json",
    ]);
    assert!(!o.status.success());
    assert_eq!(bytes, fs::read(s.0.join("chosen.json")).unwrap());
}

#[test]
fn bad_report_or_weight_hash_does_not_publish_a_choice() {
    let s = Sandbox::new();
    let base = fixture(&s);
    let mut variants = Vec::new();
    let mut bad = base.clone();
    bad["evaluated"].as_array_mut().unwrap().pop();
    variants.push(bad);
    let mut bad = base.clone();
    bad["evaluated"][0]["iteration"] = json!(20);
    variants.push(bad);
    let mut bad = base.clone();
    bad["evaluated"][0]["j_val"] = Value::Null;
    variants.push(bad);
    let mut bad = base.clone();
    bad["evaluated"][0]["success_count"] = json!(65);
    variants.push(bad);
    let mut bad = base.clone();
    bad["evaluated"][0]["weights_sha256"] = json!("b".repeat(64));
    variants.push(bad);
    let mut bad = base.clone();
    bad["evaluated"][0]["weights_path"] = json!("missing.json");
    variants.push(bad);
    let mut bad = base.clone();
    bad["evaluation_contract"] = json!("foreign-cohort");
    variants.push(bad);
    let mut bad = base.clone();
    bad["evaluated"][0]
        .as_object_mut()
        .unwrap()
        .remove("successful_mean_turns");
    variants.push(bad);
    for bad in variants {
        s.write("bad.json", &bad);
        let o = s.call(&[
            "m49a-select-checkpoint",
            "--reports-json",
            "bad.json",
            "--out-json",
            "must-not-exist.json",
        ]);
        assert!(!o.status.success(), "invalid report accepted");
        assert!(!s.0.join("must-not-exist.json").exists());
    }
    // Even a valid-shaped but changed checkpoint is rejected by identity.
    s.write("bad.json", &base);
    fs::write(s.0.join("weights.json"), b"{}").unwrap();
    let o = s.call(&[
        "m49a-select-checkpoint",
        "--reports-json",
        "bad.json",
        "--out-json",
        "must-not-exist.json",
    ]);
    assert!(!o.status.success());
    assert!(!s.0.join("must-not-exist.json").exists());
}

#[test]
fn missing_checkpoint_preflight_precedes_all_rollouts() {
    let s = Sandbox::new();
    fixture(&s);
    fs::copy(s.0.join("weights.json"), s.0.join("weights_iter010.json")).unwrap();
    let o = s.call(&[
        "m49a-select-checkpoint",
        "--checkpoint-dir",
        ".",
        "--out-json",
        "none.json",
    ]);
    assert_eq!(o.status.code(), Some(1));
    assert!(o.stdout.is_empty(), "must not evaluate a partial schedule");
    assert!(!s.0.join("none.json").exists());
}

#[test]
fn mismatched_training_manifest_fails_before_any_rollout() {
    let s = Sandbox::new();
    fixture(&s);
    for it in [10, 20, 30, 40, 50, 60, 70, 80] {
        fs::copy(
            s.0.join("weights.json"),
            s.0.join(format!("weights_iter{it:03}.json")),
        )
        .unwrap();
    }
    // Manifest claims a different batch of checkpoints than what is on disk.
    s.write(
        "training_manifest.json",
        &json!({
            "run_id":"other-run",
            "training_contract":{"target_update":"polyak","polyak_tau":0.05},
            "d2_input_sha256":{
                "train/current_x.f32":"c".repeat(64),
                "train/step_costs.f32":"c".repeat(64),
                "train/outcomes.u8":"c".repeat(64),
                "train/compact_transitions.jsonl":"c".repeat(64),
                "val/current_x.f32":"c".repeat(64),
                "val/step_costs.f32":"c".repeat(64),
                "val/outcomes.u8":"c".repeat(64),
                "val/compact_transitions.jsonl":"c".repeat(64)
            },
            "checkpoints":{
                "weights_iter010.json":"b".repeat(64)
            }
        }),
    );
    let o = s.call(&[
        "m49a-select-checkpoint",
        "--checkpoint-dir",
        ".",
        "--out-json",
        "none.json",
    ]);
    assert_eq!(o.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&o.stderr).contains("manifest"));
    assert!(o.stdout.is_empty(), "must reject the batch before rollouts");
    assert!(!s.0.join("none.json").exists());
}

#[test]
fn bad_selector_usage_has_no_outputs() {
    let s = Sandbox::new();
    for args in [
        vec!["m49a-select-checkpoint", "--checkpoint-dir", "."],
        vec![
            "m49a-select-checkpoint",
            "--checkpoint-dir",
            "--out-json",
            "none.json",
        ],
        vec![
            "m49a-select-checkpoint",
            "--checkpoint-dir",
            ".",
            "--schedule",
            "50",
            "--out-json",
            "none.json",
        ],
        vec![
            "m49a-select-checkpoint",
            "--checkpoint-dir",
            ".",
            "--schedule",
            "10,20,30,40,50,60,70,80,",
            "--out-json",
            "none.json",
        ],
    ] {
        assert_eq!(s.call(&args).status.code(), Some(2));
        assert!(!s.0.join("none.json").exists());
    }
}

fn builder_fixture(s: &Sandbox) {
    fixture(s); // Valid weights, so no unrelated usage/I/O error can mask parsing.
    s.write(
        "transitions.jsonl",
        &json!({"step_cost":1.0, "outcome":"turn_cap", "next_observation":null,
            "next_legal_actions":[], "next_remaining_main_turns":0, "max_main_turns":100}),
    );
}

#[test]
fn failure_penalty_malformed_nonfinite_or_missing_is_usage_error() {
    let s = Sandbox::new();
    builder_fixture(&s);
    let base = [
        "m49a-build-targets",
        "--transitions",
        "transitions.jsonl",
        "--weights",
        "weights.json",
        "--out-targets",
        "none.f32",
        "--failure-penalty",
    ];
    for penalty in ["oops", "NaN", "inf", "-inf", "-1", "1e1000"] {
        let mut args = base.to_vec();
        args.push(penalty);
        let o = s.call(&args);
        assert_eq!(o.status.code(), Some(2), "accepted {penalty}");
        assert!(String::from_utf8_lossy(&o.stderr).contains("malformed --failure-penalty"));
        assert!(!s.0.join("none.f32").exists());
    }
    let o = s.call(&base);
    assert_eq!(o.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&o.stderr).contains("--failure-penalty requires a value"));
    assert!(!s.0.join("none.f32").exists());
}

#[test]
fn omitted_failure_penalty_defaults_to_100_and_valid_explicit_values_are_used() {
    let s = Sandbox::new();
    builder_fixture(&s);
    for (penalty, expected) in [(None, 101.0_f32), (Some("100"), 101.0), (Some("7"), 8.0)] {
        let mut args = vec![
            "m49a-build-targets",
            "--transitions",
            "transitions.jsonl",
            "--weights",
            "weights.json",
            "--out-targets",
            "targets.f32",
        ];
        if let Some(value) = penalty {
            args.extend(["--failure-penalty", value]);
        }
        let o = s.call(&args);
        assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
        assert_eq!(
            fs::read(s.0.join("targets.f32")).unwrap(),
            expected.to_le_bytes()
        );
    }
}
