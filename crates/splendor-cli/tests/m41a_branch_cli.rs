//! M41A `run-branch` CLI integration tests.
//!
//! Drives the real binary end-to-end: a source game via `run-match`,
//! then `run-branch` with (a) the source's own action — the H0b oracle:
//! the branch must reproduce the source game exactly — and (b) a
//! different legal action — the branch must diverge at the branch ply
//! while keeping the identical hidden world (state_hash_before). Also
//! exercises the fail-closed rejections.

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
        stdout: String::from_utf8(output.stdout).expect("utf8 stdout"),
        stderr: String::from_utf8(output.stderr).expect("utf8 stderr"),
    }
}

fn tmp_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("m41a-branch-cli-{}-{}", tag, std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("mkdir");
    dir
}

fn heuristic_config(game_id: &str, seed: u64) -> Value {
    let program = bin().to_string_lossy().into_owned();
    serde_json::json!({
        "game_id": game_id,
        "seed": seed,
        "handshake_timeout_ms": 10_000,
        "move_timeout_ms": 30_000,
        "shutdown_grace_ms": 2_000,
        "agents": [
            { "program": program, "args": ["agent-heuristic", "--seed", "11"] },
            { "program": program, "args": ["agent-heuristic", "--seed", "22"] },
        ]
    })
}

fn write_json(path: &PathBuf, value: &Value) {
    fs::write(
        path,
        serde_json::to_string_pretty(value).expect("serialize"),
    )
    .expect("write json");
}

fn read_json(path: &PathBuf) -> Value {
    serde_json::from_str(&fs::read_to_string(path).expect("read json")).expect("parse json")
}

/// Record a fresh heuristic-vs-heuristic source game and return its
/// replay JSON plus the test directory.
fn make_source(tag: &str, seed: u64) -> (PathBuf, Value) {
    let dir = tmp_dir(tag);
    let config = dir.join("source-config.json");
    let report = dir.join("source-report.json");
    let replay = dir.join("source-replay.json");
    write_json(&config, &heuristic_config(&format!("m41a-src-{tag}"), seed));
    let out = run(&[
        "run-match",
        "--config",
        config.to_str().unwrap(),
        "--report-out",
        report.to_str().unwrap(),
        "--replay-out",
        replay.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0, "source game failed: {}", out.stderr);
    (dir, read_json(&replay))
}

#[test]
fn run_branch_help_exits_zero() {
    let out = run(&["run-branch", "--help"]);
    assert_eq!(out.code, 0);
    assert!(out.stdout.contains("Usage: splendor run-branch"));
}

#[test]
fn run_branch_rejects_unknown_flag() {
    let out = run(&["run-branch", "--bogus", "x"]);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("unknown flag"));
}

/// H0b oracle end-to-end: forcing the SOURCE's own action at a branch
/// ply, with the same agents, reproduces the source game exactly —
/// step chain, final hash, result.
#[test]
fn run_branch_source_action_reproduces_source() {
    let (dir, source) = make_source("h0b", 9_100_001);
    let steps = source["steps"].as_array().expect("steps");
    let branch_ply = steps.len() / 2;
    let forced = dir.join("forced.json");
    fs::write(
        &forced,
        serde_json::to_string(&steps[branch_ply]["action"]).expect("serialize"),
    )
    .expect("write forced");
    let config = dir.join("branch-config.json");
    // Same agents; the command overrides the seed to the source's.
    write_json(&config, &heuristic_config("m41a-branch-h0b", 0));
    let report = dir.join("branch-report.json");
    let replay = dir.join("branch-replay.json");

    let out = run(&[
        "run-branch",
        "--source-replay",
        dir.join("source-replay.json").to_str().unwrap(),
        "--branch-ply",
        &branch_ply.to_string(),
        "--forced-action",
        forced.to_str().unwrap(),
        "--config",
        config.to_str().unwrap(),
        "--ply-cap",
        "150",
        "--report-out",
        report.to_str().unwrap(),
        "--replay-out",
        replay.to_str().unwrap(),
    ]);
    assert_eq!(out.code, 0, "branch failed: {}", out.stderr);
    assert!(out.stdout.contains("\"status\":\"completed\""));

    let branch = read_json(&replay);
    let b_steps = branch["steps"].as_array().expect("branch steps");
    let s_steps = steps;
    assert_eq!(b_steps.len(), s_steps.len(), "same total steps");
    for (b, s) in b_steps.iter().zip(s_steps.iter()) {
        assert_eq!(b["ply"], s["ply"]);
        assert_eq!(b["actor"], s["actor"]);
        assert_eq!(b["action"], s["action"]);
        assert_eq!(b["state_hash_before"], s["state_hash_before"]);
        assert_eq!(b["state_hash_after"], s["state_hash_after"]);
    }
    assert_eq!(branch["final_state_hash"], source["final_state_hash"]);
    assert_eq!(branch["result"], source["result"]);
    let _ = fs::remove_dir_all(&dir);
}

/// Branching at ply 0 with a different legal take action diverges
/// immediately while the hidden world (state_hash_before at ply 0)
/// stays identical.
#[test]
fn run_branch_counterfactual_diverges_same_hidden_world() {
    let (dir, source) = make_source("cf", 9_100_002);
    let forced = dir.join("forced.json");
    // A 3-color take distinct from the source's first action (the
    // source's exact colors are unknown here, so try a few standard
    // combinations until one is accepted; at game start any 3 distinct
    // available colors are legal — bank starts full).
    let candidates: [serde_json::Value; 3] = [
        serde_json::json!({"type": "take_tokens", "take": {"white": 1, "blue": 1, "green": 1, "red": 0, "black": 0, "gold": 0}, "return": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}}),
        serde_json::json!({"type": "take_tokens", "take": {"white": 0, "blue": 1, "green": 1, "red": 1, "black": 0, "gold": 0}, "return": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}}),
        serde_json::json!({"type": "take_tokens", "take": {"white": 1, "blue": 0, "green": 0, "red": 1, "black": 1, "gold": 0}, "return": {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}}),
    ];
    let config = dir.join("branch-config.json");
    write_json(&config, &heuristic_config("m41a-branch-cf", 0));
    let report = dir.join("branch-report.json");
    let replay = dir.join("branch-replay.json");

    let mut succeeded = false;
    for candidate in &candidates {
        let source_first = &source["steps"].as_array().unwrap()[0]["action"];
        if candidate == source_first {
            continue; // must be a DIFFERENT action than the source's
        }
        fs::write(
            &forced,
            serde_json::to_string(candidate).expect("serialize"),
        )
        .expect("write forced");
        let _ = fs::remove_file(&report);
        let _ = fs::remove_file(&replay);
        let out = run(&[
            "run-branch",
            "--source-replay",
            dir.join("source-replay.json").to_str().unwrap(),
            "--branch-ply",
            "0",
            "--forced-action",
            forced.to_str().unwrap(),
            "--config",
            config.to_str().unwrap(),
            "--ply-cap",
            "150",
            "--report-out",
            report.to_str().unwrap(),
            "--replay-out",
            replay.to_str().unwrap(),
        ]);
        if out.code == 0 {
            succeeded = true;
            break;
        }
        assert!(
            out.stderr.contains("not in the rebuilt legal set"),
            "unexpected failure: {}",
            out.stderr
        );
    }
    assert!(succeeded, "one of the opening take actions must be legal");

    let branch = read_json(&replay);
    let source_steps = source["steps"].as_array().unwrap();
    let branch_steps = branch["steps"].as_array().unwrap();
    // Same hidden world: the initial state hash chain matches.
    assert_eq!(
        branch_steps[0]["state_hash_before"], source_steps[0]["state_hash_before"],
        "branch starts from the identical source state"
    );
    // The branch diverges at ply 0.
    assert_ne!(branch_steps[0]["action"], source_steps[0]["action"]);
    let _ = fs::remove_dir_all(&dir);
}

/// Fail-closed rejections: out-of-range branch ply, illegal forced
/// action, existing outputs.
#[test]
fn run_branch_fail_closed_paths() {
    let (dir, source) = make_source("rej", 9_100_003);
    let steps = source["steps"].as_array().unwrap();
    let forced = dir.join("forced.json");
    fs::write(
        &forced,
        serde_json::to_string(&steps[0]["action"]).expect("serialize"),
    )
    .expect("write forced");
    let config = dir.join("branch-config.json");
    write_json(&config, &heuristic_config("m41a-branch-rej", 0));
    let report = dir.join("r.json");
    let replay = dir.join("p.json");

    let base = |ply: &str, forced_path: &str| -> Vec<String> {
        vec![
            "run-branch".to_string(),
            "--source-replay".into(),
            dir.join("source-replay.json")
                .to_string_lossy()
                .into_owned(),
            "--branch-ply".into(),
            ply.into(),
            "--forced-action".into(),
            forced_path.into(),
            "--config".into(),
            config.to_string_lossy().into_owned(),
            "--ply-cap".into(),
            "150".into(),
            "--report-out".into(),
            report.to_string_lossy().into_owned(),
            "--replay-out".into(),
            replay.to_string_lossy().into_owned(),
        ]
    };

    // Out-of-range branch ply.
    let args = base("999999", forced.to_str().unwrap());
    let refs: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
    let out = run(&refs);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("out of range"));

    // Illegal forced action (never-legal market slot).
    let illegal = dir.join("illegal.json");
    fs::write(
        &illegal,
        r#"{"type": "buy_market", "tier": "One", "slot": 200}"#,
    )
    .expect("write illegal");
    let args = base("0", illegal.to_str().unwrap());
    let refs: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
    let out = run(&refs);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("not in the rebuilt legal set"));

    // Branch ply at/after the cap is a CLI error (use a small cap so the
    // ply is within the source's step range: ply 30, cap 31).
    let args_capped = vec![
        "run-branch".to_string(),
        "--source-replay".into(),
        dir.join("source-replay.json")
            .to_string_lossy()
            .into_owned(),
        "--branch-ply".into(),
        "30".into(),
        "--forced-action".into(),
        forced.to_string_lossy().into_owned(),
        "--config".into(),
        config.to_string_lossy().into_owned(),
        "--ply-cap".into(),
        "31".into(),
        "--report-out".into(),
        report.to_string_lossy().into_owned(),
        "--replay-out".into(),
        replay.to_string_lossy().into_owned(),
    ];
    let refs: Vec<&str> = args_capped.iter().map(|s| s.as_str()).collect();
    let out = run(&refs);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("strictly below"));

    // Existing output must be refused (no overwrite).
    fs::write(&report, "{}").expect("seed report");
    let args = base("0", forced.to_str().unwrap());
    let refs: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
    let out = run(&refs);
    assert_eq!(out.code, 1);
    assert!(out.stderr.contains("already exists"));
    let _ = fs::remove_dir_all(&dir);
}
