//! M41A `run-branches` provenance/resume fail-closed CLI tests.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

use serde_json::Value;

fn bin() -> PathBuf {
    env!("CARGO_BIN_EXE_splendor").into()
}

struct Out {
    code: i32,
    stdout: String,
    stderr: String,
}

fn run(args: &[&str]) -> Out {
    let output = Command::new(bin())
        .args(args)
        .output()
        .expect("spawn splendor");
    Out {
        code: output.status.code().expect("exit code"),
        stdout: String::from_utf8(output.stdout).expect("utf8"),
        stderr: String::from_utf8(output.stderr).expect("utf8 stderr"),
    }
}

fn tmp_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("m41a-rb-{tag}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("mkdir");
    dir
}

fn heuristic_config(path: &std::path::Path) {
    let program = bin().to_string_lossy().into_owned();
    let config = serde_json::json!({
        "game_id": "m41a-rb-test",
        "seed": 0,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            { "program": program, "args": ["agent-heuristic", "--seed", "7"] },
            { "program": program, "args": ["agent-heuristic", "--seed", "8"] },
        ],
    });
    fs::write(
        path,
        serde_json::to_string_pretty(&config).expect("serialize"),
    )
    .expect("write");
}

fn make_source(dir: &std::path::Path, seed: u64) -> PathBuf {
    let config = dir.join("source-config.json");
    let program = bin().to_string_lossy().into_owned();
    let cfg = serde_json::json!({
        "game_id": "m41a-rb-source",
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            { "program": program, "args": ["agent-heuristic", "--seed", "7"] },
            { "program": program, "args": ["agent-heuristic", "--seed", "8"] },
        ],
    });
    fs::write(
        &config,
        serde_json::to_string_pretty(&cfg).expect("serialize"),
    )
    .expect("write");
    let replay = dir.join("source-replay.json");
    let out = run(&[
        "run-match",
        "--config",
        config.to_str().unwrap(),
        "--report-out",
        dir.join("source-report.json").to_str().unwrap(),
        "--replay-out",
        replay.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0, "source game failed: {}", out.stderr);
    replay
}

#[test]
fn run_branches_help_exits_zero() {
    let out = run(&["run-branches", "--help"]);
    assert_eq!(out.code, 0);
    assert!(out.stdout.contains("Usage: splendor run-branches"));
}

#[test]
fn run_branches_completes_with_manifest_and_resume() {
    let dir = tmp_dir("full");
    let source = make_source(&dir, 9_150_001);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out_dir = dir.join("state");

    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0, "run-branches failed: {}", out.stderr);
    assert!(out.stdout.contains("run-branches-complete"));

    // Probe + manifest + per-action dirs exist.
    let probe: Value =
        serde_json::from_str(&fs::read_to_string(out_dir.join("state-probe.json")).unwrap())
            .unwrap();
    assert_eq!(
        probe["format"],
        "effective-splendor-m41a-branch-state-probe"
    );
    let n = probe["legal_actions"].as_array().unwrap().len();
    assert!(n >= 2, "heuristic mid-game states have multiple actions");
    let manifest: Value =
        serde_json::from_str(&fs::read_to_string(out_dir.join("state-manifest.json")).unwrap())
            .unwrap();
    assert_eq!(
        manifest["format"],
        "effective-splendor-m41a-branch-state-manifest"
    );
    assert_eq!(manifest["actions"].as_array().unwrap().len(), n);
    for entry in manifest["actions"].as_array().unwrap() {
        assert!(entry["replay_sha256"].is_string());
        assert!(entry["report_sha256"].is_string());
    }

    // Re-run without --resume must fail (probe exists).
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("already exists"));

    // Re-run with --resume: skips everything (SHA re-validated), manifest
    // entries keep FULL provenance (v2: only `resumed` flips).
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 0, "resume failed: {}", out.stderr);
    let manifest2: Value =
        serde_json::from_str(&fs::read_to_string(out_dir.join("state-manifest.json")).unwrap())
            .unwrap();
    assert_eq!(manifest2["version"], 2);
    for (a, b) in manifest["actions"]
        .as_array()
        .unwrap()
        .iter()
        .zip(manifest2["actions"].as_array().unwrap().iter())
    {
        assert_eq!(b["resumed"], true);
        // v2: resume preserves the FULL identity (forced action, SHAs,
        // return, final hash), not just the index.
        assert_eq!(a["forced_action"], b["forced_action"]);
        assert_eq!(a["report_sha256"], b["report_sha256"]);
        assert_eq!(a["replay_sha256"], b["replay_sha256"]);
        assert_eq!(a["acting_seat_return"], b["acting_seat_return"]);
        assert_eq!(a["final_state_hash"], b["final_state_hash"]);
        assert!(b["report_sha256"].is_string());
        assert!(b["forced_action"].is_object());
        assert!(b["final_state_hash"].is_string());
    }
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn run_branches_tampered_replay_fails_closed_on_resume() {
    let dir = tmp_dir("tamper-replay");
    let source = make_source(&dir, 9_150_005);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out_dir = dir.join("state");
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0);
    // Tamper with one action's replay (report untouched).
    let replay_path = out_dir.join("action-000").join("replay.json");
    let mut doc: Value = serde_json::from_str(&fs::read_to_string(&replay_path).unwrap()).unwrap();
    if let Some(steps) = doc["steps"].as_array_mut() {
        if let Some(last) = steps.last_mut() {
            last["action"] = serde_json::json!({"type": "pass"});
        }
    }
    fs::write(&replay_path, serde_json::to_string_pretty(&doc).unwrap()).unwrap();
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 1, "tampered replay must fail resume");
    assert!(
        out.stderr.contains("SHA mismatch"),
        "stderr: {}",
        out.stderr
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn run_branches_tampered_report_fails_closed_on_resume() {
    let dir = tmp_dir("tamper-report");
    let source = make_source(&dir, 9_150_006);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out_dir = dir.join("state");
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0);
    // Tamper with one action's report (replay untouched).
    let report_path = out_dir.join("action-000").join("report.json");
    let mut doc: Value = serde_json::from_str(&fs::read_to_string(&report_path).unwrap()).unwrap();
    doc["game_id"] = serde_json::json!("tampered");
    fs::write(&report_path, serde_json::to_string_pretty(&doc).unwrap()).unwrap();
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 1, "tampered report must fail resume");
    assert!(
        out.stderr.contains("SHA mismatch"),
        "stderr: {}",
        out.stderr
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn run_branches_resume_without_manifest_refused() {
    let dir = tmp_dir("no-manifest");
    let source = make_source(&dir, 9_150_007);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out_dir = dir.join("state");
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0);
    // Delete the manifest: --resume must refuse (blind resume of
    // artifacts without provenance is forbidden).
    fs::remove_file(out_dir.join("state-manifest.json")).unwrap();
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 1);
    assert!(
        out.stderr.contains("state-manifest"),
        "stderr: {}",
        out.stderr
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn run_branches_run_contract_binding() {
    let dir = tmp_dir("contract");
    let source = make_source(&dir, 9_150_008);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out_dir = dir.join("state");
    let contract = dir.join("run-contract.json");
    fs::write(
        &contract,
        serde_json::to_string_pretty(&serde_json::json!({
            "format": "effective-splendor-m41a-run-contract",
            "version": 1,
            "identity": "test-contract-a",
        }))
        .unwrap(),
    )
    .unwrap();

    // Fresh run with the contract binds its SHA into the manifest.
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--run-contract",
        contract.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0, "contract run failed: {}", out.stderr);
    let manifest: Value =
        serde_json::from_str(&fs::read_to_string(out_dir.join("state-manifest.json")).unwrap())
            .unwrap();
    assert!(manifest["run_contract_sha256"].is_string());

    // Resume with the SAME contract passes.
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--run-contract",
        contract.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 0, "same-contract resume failed: {}", out.stderr);

    // Resume with a DIFFERENT contract fails closed.
    let contract_b = dir.join("run-contract-b.json");
    fs::write(
        &contract_b,
        serde_json::to_string_pretty(&serde_json::json!({
            "format": "effective-splendor-m41a-run-contract",
            "version": 1,
            "identity": "test-contract-B",
        }))
        .unwrap(),
    )
    .unwrap();
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--run-contract",
        contract_b.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 1);
    assert!(
        out.stderr.contains("DIFFERENT run contract"),
        "stderr: {}",
        out.stderr
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn run_branches_tampered_probe_fails_closed() {
    let dir = tmp_dir("tamper");
    let source = make_source(&dir, 9_150_002);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out_dir = dir.join("state");
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0);

    // Tamper with the probe (change the recorded state hash) and resume:
    // must fail closed.
    let probe_path = out_dir.join("state-probe.json");
    let mut probe: Value = serde_json::from_str(&fs::read_to_string(&probe_path).unwrap()).unwrap();
    probe["state_hash"] = serde_json::json!("f".repeat(64));
    fs::write(&probe_path, serde_json::to_string_pretty(&probe).unwrap()).unwrap();
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("differs"), "stderr: {}", out.stderr);
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn run_branches_partial_artifacts_fail_closed() {
    let dir = tmp_dir("partial");
    let source = make_source(&dir, 9_150_003);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out_dir = dir.join("state");

    // Simulate an interrupted run: the probe + ONE complete action dir +
    // ONE partial action dir (report without replay).
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0);
    let partial = out_dir.join("action-001");
    fs::remove_file(partial.join("replay.json")).expect("remove replay");
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "5",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--out-dir",
        out_dir.to_str().unwrap(),
        "--resume",
    ]);
    assert_eq!(out.code, 1);
    assert!(
        out.stderr.contains("partial or pre-existing artifacts"),
        "stderr: {}",
        out.stderr
    );
    let _ = fs::remove_dir_all(&dir);
}

#[test]
fn run_branches_rejects_branch_ply_at_cap() {
    let dir = tmp_dir("cap");
    let source = make_source(&dir, 9_150_004);
    let config = dir.join("branch-config.json");
    heuristic_config(&config);
    let out = run(&[
        "run-branches",
        "--source-replay",
        source.to_str().unwrap(),
        "--branch-ply",
        "29",
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "30",
        "--out-dir",
        dir.join("state").to_str().unwrap(),
    ]);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("strictly below"));
    let _ = fs::remove_dir_all(&dir);
}
