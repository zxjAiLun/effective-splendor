use std::fs;

use serde_json::Value;
use sha2::{Digest, Sha256};

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn collector_config_hash(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-self-play-config-v1\0");
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

#[test]
fn m24_s1_result_is_complete_and_does_not_claim_promotion() {
    let root = root();
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m24-self-play-s1-v1.result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(
        result["status"],
        "s1_collection_audit_and_training_complete"
    );
    assert_eq!(
        result["implementation_commit"],
        "a797f131c25bffc49fd66abe212c63fc88c9305c"
    );
    assert_eq!(
        result["base_commit"],
        "4ee8852c5ac7232c13e7f2ead1a25aaa4955ad3f"
    );
    assert_eq!(result["review"]["acceptance"], "PENDING_INDEPENDENT_REVIEW");

    let collection_config =
        fs::read(root.join("benchmarks/m24-self-play-s1-v1.config.json")).unwrap();
    assert_eq!(
        result["self_play"]["config_file_sha256"],
        sha256_hex(&collection_config)
    );
    assert_eq!(
        result["self_play"]["collector_config_hash"],
        collector_config_hash(&collection_config)
    );
    let training_config =
        fs::read(root.join("benchmarks/m24-self-play-s1-v1.training.json")).unwrap();
    assert_eq!(
        result["training"]["config_file_sha256"],
        sha256_hex(&training_config)
    );

    assert_eq!(result["self_play"]["games"], 128);
    assert_eq!(result["self_play"]["examples"], 7876);
    assert_eq!(
        result["self_play"]["base_checkpoint_hash"],
        "dc611f3d575f87e2b24221d633f8af55c98055357b05ccb822ef46ec0cb98c04"
    );
    assert_eq!(result["diagnostics"]["games_verified"], 128);
    assert_eq!(result["self_play"]["verified_replays"], 128);
    assert_eq!(result["diagnostics"]["duplicate_seeds"], 0);
    assert_eq!(
        result["diagnostics"]["diagnostics_file_sha256"],
        result["diagnostics"]["report_file_sha256"]
    );
    assert_eq!(result["gates"]["G1_collection"], "PASS");
    assert_eq!(result["gates"]["G2_audit"], "PASS");
    assert_eq!(result["gates"]["G3_training"], "PASS");
    assert_eq!(result["gates"]["G4_scale_decision"], "NOT_YET_RUN");
    for key in [
        "config_file_sha256",
        "collector_config_hash",
        "dataset_file_sha256",
        "self_play_hash",
        "base_checkpoint_hash",
    ] {
        let hash = result["self_play"][key].as_str().unwrap();
        assert_eq!(hash.len(), 64, "{key} must be sha256");
        assert!(hash.bytes().all(|b| b.is_ascii_hexdigit()));
    }
    for key in ["checkpoint_hash", "checkpoint_file_sha256"] {
        let hash = result["training"][key].as_str().unwrap();
        assert_eq!(hash.len(), 64, "{key} must be sha256");
        assert!(hash.bytes().all(|b| b.is_ascii_hexdigit()));
    }
}

#[test]
fn m24_s1_training_config_binds_the_actual_self_play_hash() {
    let root = root();
    let training: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m24-self-play-s1-v1.training.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(
        training["expected_self_play_hash"],
        "b2284c6ce44a0a60bdd695d15ba42e00199a95e489970f920cfd4e4aaf464053"
    );
    assert_eq!(training["device"], "cuda");
    assert_eq!(training["epochs"], 16);
    assert_eq!(training["validation_game_modulus"], 4);
    assert_eq!(training["seed"], 260129);
}

#[test]
fn m24_s1_collection_config_is_nested_scale_first_stage() {
    let root = root();
    let config: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m24-self-play-s1-v1.config.json")).unwrap(),
    )
    .unwrap();
    let seeds = config["game_seeds"].as_array().unwrap();
    assert_eq!(seeds.len(), 128);
    assert_eq!(seeds[0], 260001);
    assert_eq!(seeds[127], 260128);
    assert_eq!(config["simulations"], 16);
    assert_eq!(config["max_depth_turns"], 1);
    assert_eq!(config["device"], "cuda");
}
