use std::fs;

use serde_json::Value;
use sha2::{Digest, Sha256};
use splendor_eval::{plan::EvaluationPlanV1, schedule::expand_schedule};

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
    assert_eq!(
        result["review"]["source_review"],
        "PASS_INDEPENDENT_REVIEW_OF_DBE47AB"
    );
    assert_eq!(result["review"]["acceptance"], "ACCEPTED");

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

#[test]
fn m24_scale_gate_v1_is_frozen_and_machine_checkable() {
    let root = root();
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m24-self-play-s1-v1.result.json")).unwrap(),
    )
    .unwrap();
    let gate: Value =
        serde_json::from_slice(&fs::read(root.join("benchmarks/m24-scale-gate-v1.json")).unwrap())
            .unwrap();
    assert_eq!(gate["format"], "effective-splendor-m24-scale-gate");
    assert_eq!(gate["version"], 1);
    assert_eq!(gate["gate_id"], "m24-scale-gate-v1");
    assert_eq!(gate["revision"], "repair-2");
    assert_eq!(gate["status"], "FROZEN");

    // The gate S1 baseline must be bound back to the tracked result manifest,
    // not merely copied by hand.
    assert_eq!(
        gate["reference_s1"]["self_play_hash"],
        result["self_play"]["self_play_hash"]
    );
    assert_eq!(
        gate["reference_s1"]["checkpoint_hash"],
        result["training"]["checkpoint_hash"]
    );
    assert_eq!(
        gate["reference_s1"]["offline_validation"]["examples"],
        result["training"]["validation"]["examples"]
    );
    assert_eq!(
        gate["reference_s1"]["offline_validation"]["policy_cross_entropy"],
        result["training"]["validation"]["policy_cross_entropy"]
    );
    assert_eq!(
        gate["reference_s1"]["offline_validation"]["visit_top1"],
        result["training"]["validation"]["visit_top1"]
    );
    assert_eq!(
        gate["reference_s1"]["offline_validation"]["value_mse"],
        result["training"]["validation"]["value_mse"]
    );

    // Offline comparison must be pinned to the exact S1 validation subset.
    let reference_indices = gate["fixed_reference_offline_eval"]["reference_game_indices"]
        .as_array()
        .unwrap();
    assert_eq!(reference_indices.len(), 32);
    assert_eq!(reference_indices[0], 0);
    assert_eq!(reference_indices[31], 124);
    assert_eq!(
        gate["fixed_reference_offline_eval"]["validation_game_modulus"],
        4
    );
    assert_eq!(
        gate["fixed_reference_offline_eval"]["validation_game_remainder"],
        0
    );

    // The Arena screen bundle must exist and be hash-bound into the gate.
    let bundle_bytes =
        fs::read(root.join("benchmarks/m24-s2-arena-screen-v1.bundle.json")).unwrap();
    let bundle_sha = sha256_hex(&bundle_bytes);
    let bundle_gate = &gate["competitive_movement"]["arena_screen_bundle"];
    assert_eq!(bundle_gate["file_sha256"], bundle_sha);
    let bundle: Value = serde_json::from_slice(&bundle_bytes).unwrap();
    assert_eq!(
        bundle["format"],
        "effective-splendor-m24-arena-screen-bundle"
    );
    assert_eq!(bundle["version"], 1);
    assert_eq!(bundle["screen_id"], "m24-s2-arena-screen-v1");

    // The bundle must contain exactly five 2-agent pairwise plans.
    let pair_plans = bundle["pair_plans"].as_array().unwrap();
    assert_eq!(pair_plans.len(), 5);
    let expected_pairs: [(&str, &[&str]); 5] = [
        ("s2_vs_s1", &["m24-s2-candidate", "m24-s1-checkpoint"]),
        ("s2_vs_m07", &["m24-s2-candidate", "m07-champion"]),
        ("s1_vs_m07", &["m24-s1-checkpoint", "m07-champion"]),
        ("s2_vs_heuristic", &["m24-s2-candidate", "heuristic-v1"]),
        ("s1_vs_heuristic", &["m24-s1-checkpoint", "heuristic-v1"]),
    ];
    let common_seeds: Vec<u64> = bundle["game_seeds"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_u64().unwrap())
        .collect();
    assert_eq!(common_seeds.len(), 32);
    assert_eq!(common_seeds[0], 300001);
    assert_eq!(common_seeds[31], 300032);

    for (expected_pair, expected_agents) in expected_pairs {
        let item = pair_plans
            .iter()
            .find(|plan| plan["pair"] == expected_pair)
            .unwrap_or_else(|| panic!("missing pair {expected_pair} in bundle"));
        let plan_bytes = fs::read(root.join(item["path"].as_str().unwrap())).unwrap();
        assert_eq!(sha256_hex(&plan_bytes), item["file_sha256"]);

        let plan: EvaluationPlanV1 = serde_json::from_slice(&plan_bytes).unwrap();
        plan.validate().unwrap();
        assert_eq!(plan.agents.len(), 2);
        assert_eq!(plan.game_seeds, common_seeds);
        assert_eq!(plan.handshake_timeout_ms, 5000);
        assert_eq!(plan.move_timeout_ms, 10000);
        assert_eq!(plan.shutdown_grace_ms, 2000);

        let schedule = expand_schedule(&plan).unwrap();
        assert_eq!(schedule.len(), 64);
        for seed_index in 0..32u32 {
            let seed_matches: Vec<_> = schedule
                .iter()
                .filter(|spec| spec.seed_index == seed_index)
                .collect();
            assert_eq!(seed_matches.len(), 2);
            assert!(seed_matches.iter().any(|spec| spec.rotation == 0));
            assert!(seed_matches.iter().any(|spec| spec.rotation == 1));
        }

        let actual_agents: Vec<&str> = plan.agents.iter().map(|agent| agent.id.as_str()).collect();
        for expected in expected_agents {
            assert!(
                actual_agents.contains(&expected),
                "pair {expected_pair} missing agent {expected}"
            );
        }
    }

    // Runtime/search recipe is frozen.
    let search_recipe = &gate["competitive_movement"]["runtime_identity"]["search_recipe"];
    assert_eq!(search_recipe["simulations"], 16);
    assert_eq!(search_recipe["max_depth_turns"], 1);
    assert_eq!(search_recipe["puct_exploration_milli"], 1500);
    assert_eq!(search_recipe["device"], "cuda");

    // Statistical method is frozen and reuses the accepted promotion Hoeffding
    // contract with saturating bounds.
    let statistics = &gate["competitive_movement"]["statistics"];
    assert_eq!(statistics["confidence_bps"], 9500);
    assert!(statistics["pairwise_lower_bound_method"]
        .as_str()
        .unwrap()
        .contains("Hoeffding"));
    assert!(statistics["lower_bound_formula"]
        .as_str()
        .unwrap()
        .contains("max(0"));
    assert!(statistics["upper_bound_formula"]
        .as_str()
        .unwrap()
        .contains("min(10000"));
    assert_eq!(
        statistics["s2_vs_s1_min_pairwise_score_lower_bound_bps"],
        100
    );

    assert_eq!(gate["decision"]["G4_scale_decision"], "NOT_YET_RUN");
}
