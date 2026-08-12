//! End-to-end M16 round-robin test with real Arena subprocess matches.

use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicU32, Ordering};

use serde_json::{json, Value};

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_splendor")
}

fn temp_dir() -> PathBuf {
    static SEQ: AtomicU32 = AtomicU32::new(0);
    let path = std::env::temp_dir().join(format!(
        "splendor-rating-cli-{}-{}",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::SeqCst)
    ));
    fs::create_dir_all(&path).unwrap();
    path
}

fn agent(id: &str, command: &str, seed: u64) -> Value {
    json!({
        "id": id,
        "display_name": id,
        "class": "baseline",
        "policy_version": "test-v1",
        "model_version": null,
        "checkpoint_hash": null,
        "runtime_name": command,
        "runtime_version": "1",
        "command": { "program": binary(), "args": [command, "--seed", seed.to_string()] }
    })
}

#[test]
fn plans_runs_and_rates_a_three_agent_league() {
    let dir = temp_dir();
    let registry_path = dir.join("registry.json");
    let config_path = dir.join("config.json");
    let plan_path = dir.join("plan.json");
    let run_dir = dir.join("run");
    fs::write(&registry_path, serde_json::to_vec_pretty(&json!({
        "format": "effective-splendor-rating-registry", "version": 1, "registry_id": "cli-e2e",
        "agents": [agent("random-a", "agent-random", 11), agent("heuristic", "agent-heuristic", 22), agent("random-b", "agent-random", 33)]
    })).unwrap()).unwrap();
    fs::write(
        &config_path,
        serde_json::to_vec_pretty(&json!({
            "format": "effective-splendor-rating-config", "version": 1, "tournament_id": "cli-e2e",
            "participant_ids": ["random-a", "heuristic", "random-b"], "game_seeds": [990001],
            "handshake_timeout_ms": 5000, "move_timeout_ms": 5000, "shutdown_grace_ms": 1000,
            "initial_elo": 1500, "live_k_factor": 32
        }))
        .unwrap(),
    )
    .unwrap();

    let planned = Command::new(binary())
        .args(["rating-plan", "--registry"])
        .arg(&registry_path)
        .args(["--config"])
        .arg(&config_path)
        .args(["--out"])
        .arg(&plan_path)
        .output()
        .unwrap();
    assert!(
        planned.status.success(),
        "{}",
        String::from_utf8_lossy(&planned.stderr)
    );

    let ran = Command::new(binary())
        .args(["rating-run", "--plan"])
        .arg(&plan_path)
        .args(["--out-dir"])
        .arg(&run_dir)
        .output()
        .unwrap();
    assert!(
        ran.status.success(),
        "{}",
        String::from_utf8_lossy(&ran.stderr)
    );
    let report: Value =
        serde_json::from_slice(&fs::read(run_dir.join("rating-report.json")).unwrap()).unwrap();
    assert_eq!(report["format"], "effective-splendor-rating-report");
    assert_eq!(report["scheduled_matches"], 6);
    assert_eq!(report["completed_matches"], 6);
    assert_eq!(report["aborted_matches"], 0);
    assert_eq!(report["agents"].as_array().unwrap().len(), 3);
    assert_eq!(report["head_to_head"].as_array().unwrap().len(), 3);
    assert_eq!(
        report["pair_evaluation_report_hashes"]
            .as_array()
            .unwrap()
            .len(),
        3
    );
    assert!(run_dir.join("pairs/pair-0002/eval-report.json").is_file());

    let rebuilt_path = dir.join("rebuilt-rating-report.json");
    let rebuilt = Command::new(binary())
        .args(["rating-report", "--plan"])
        .arg(&plan_path)
        .args(["--evaluation-dir"])
        .arg(&run_dir)
        .args(["--out"])
        .arg(&rebuilt_path)
        .output()
        .unwrap();
    assert!(
        rebuilt.status.success(),
        "{}",
        String::from_utf8_lossy(&rebuilt.stderr)
    );
    assert_eq!(
        fs::read(rebuilt_path).unwrap(),
        fs::read(run_dir.join("rating-report.json")).unwrap()
    );

    let rerun = Command::new(binary())
        .args(["rating-run", "--plan"])
        .arg(&plan_path)
        .args(["--out-dir"])
        .arg(&run_dir)
        .output()
        .unwrap();
    assert!(!rerun.status.success());
    assert!(String::from_utf8_lossy(&rerun.stderr).contains("already exists"));

    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn rejects_a_checkpoint_registry_entry_without_a_hash() {
    let dir = temp_dir();
    let registry_path = dir.join("registry.json");
    let config_path = dir.join("config.json");
    let plan_path = dir.join("plan.json");
    let mut checkpoint = agent("checkpoint", "agent-random", 1);
    checkpoint["class"] = json!("checkpoint");
    fs::write(&registry_path, serde_json::to_vec_pretty(&json!({
        "format": "effective-splendor-rating-registry", "version": 1, "registry_id": "bad", "agents": [checkpoint, agent("other", "agent-random", 2)]
    })).unwrap()).unwrap();
    fs::write(&config_path, serde_json::to_vec_pretty(&json!({
        "format": "effective-splendor-rating-config", "version": 1, "tournament_id": "bad", "participant_ids": ["checkpoint", "other"], "game_seeds": [1],
        "handshake_timeout_ms": 1000, "move_timeout_ms": 1000, "shutdown_grace_ms": 1000, "initial_elo": 1500, "live_k_factor": 32
    })).unwrap()).unwrap();
    let output = Command::new(binary())
        .args(["rating-plan", "--registry"])
        .arg(&registry_path)
        .args(["--config"])
        .arg(&config_path)
        .args(["--out"])
        .arg(&plan_path)
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("must bind checkpoint_hash"));
    assert!(!plan_path.exists());
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn checked_in_m17_result_is_provisional_and_rejected() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m17-gpu-supervised-warmstart-v1.result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(
        result["implementation_commit"],
        "c41120385f3378c7223e44f9541131ddb40810dd"
    );
    assert_eq!(
        result["entity_mixer"]["checkpoint_hash"],
        "37ad1f446f7fa7f72a06c1c1581d8a14c3aec193d1270b99b0b2254f6d10dadf"
    );
    assert_eq!(result["prospective_screen"]["completed_matches"], 8);
    assert_eq!(result["prospective_screen"]["aborted_matches"], 0);
    assert_eq!(result["prospective_screen"]["wins"], 1);
    assert_eq!(result["prospective_screen"]["losses"], 7);
    assert_eq!(result["prospective_screen"]["verdict"], "reject");
    assert_eq!(result["status"], "candidate_not_promoted");
}
