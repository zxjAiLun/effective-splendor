use std::fs;
use std::process::Command;

use serde_json::Value;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_splendor")
}

#[test]
fn checked_in_m18a_result_is_bound_and_rejected() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m18a-neural-self-play-smoke-v1.result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(result["status"], "candidate_rejected");
    assert_eq!(result["self_play_games"], 2);
    assert_eq!(result["self_play_examples"], 122);
    assert_eq!(result["prospective_screen"]["completed"], 8);
    assert_eq!(result["prospective_screen"]["aborted"], 0);
    assert_eq!(result["prospective_screen"]["wins"], 2);
    assert_eq!(result["prospective_screen"]["losses"], 6);
    for key in [
        "base_checkpoint_hash",
        "self_play_hash",
        "trained_checkpoint_hash",
        "trained_checkpoint_file_sha256",
    ] {
        let hash = result[key].as_str().unwrap();
        assert_eq!(hash.len(), 64);
        assert!(hash.bytes().all(|byte| byte.is_ascii_hexdigit()));
    }
}

#[test]
fn self_play_help_is_successful() {
    let output = Command::new(binary())
        .args(["collect-gpu-self-play", "--help"])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8(output.stdout)
        .unwrap()
        .contains("collect-gpu-self-play"));
}

#[test]
fn self_play_parser_rejects_unknown_flags_without_output() {
    let output = Command::new(binary())
        .args(["collect-gpu-self-play", "--unknown", "x"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("unknown argument"));
}
