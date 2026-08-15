use std::fs;
use std::process::Command;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_splendor")
}

#[test]
fn v2_commands_help_is_successful() {
    for command in ["collect-gpu-self-play-v2", "diagnose-gpu-self-play-v2"] {
        let output = Command::new(binary())
            .args([command, "--help"])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{command} --help failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(String::from_utf8(output.stdout).unwrap().contains(command));
    }
}

#[test]
fn v2_commands_reject_unknown_flags_without_output() {
    for command in ["collect-gpu-self-play-v2", "diagnose-gpu-self-play-v2"] {
        let output = Command::new(binary())
            .args([command, "--unknown", "x"])
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(1));
        assert!(String::from_utf8(output.stderr)
            .unwrap()
            .contains("unknown argument"));
    }
}

#[test]
fn diagnose_rejects_malformed_dataset_and_never_publishes_report() {
    let dir = std::env::temp_dir().join(format!(
        "splendor-self-play-v2-cli-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir_all(&dir).unwrap();
    let dataset = dir.join("bad.json");
    let report = dir.join("report.json");
    fs::write(&dataset, "{not json").unwrap();
    let config = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("benchmarks/m24-self-play-s1-v1.config.json");
    let output = Command::new(binary())
        .args([
            "diagnose-gpu-self-play-v2",
            "--input",
            dataset.to_str().unwrap(),
            "--config",
            config.to_str().unwrap(),
            "--out",
            report.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("invalid self-play v2 dataset"));
    assert!(!report.exists(), "no report may be published on failure");
    let _ = fs::remove_dir_all(&dir);
}
