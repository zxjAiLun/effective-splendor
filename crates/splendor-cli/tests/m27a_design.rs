use std::fs;

use serde_json::Value;

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn m27a_design_is_preregistration_only() {
    let config: Value = serde_json::from_slice(
        &fs::read(root().join("benchmarks/m27a-search-budget-scaling-v1.json")).unwrap(),
    )
    .unwrap();

    assert_eq!(
        config["format"],
        "effective-splendor-m27a-search-budget-scaling"
    );
    assert_eq!(config["version"], 1);
    assert_eq!(config["milestone"], "M27A");
    assert_eq!(config["revision"], "design-1");
    assert_eq!(config["status"], "DESIGNED");
    assert_eq!(config["execution_authorization"], "NOT_AUTHORIZED");
    assert_eq!(config["review"]["required_before_execution"], true);
    assert_eq!(config["parent_diagnosis"]["decision"], "SEARCH_BOTTLENECK");

    let matrix = &config["planned_matrix"];
    assert_eq!(
        matrix["candidate_pairs"],
        serde_json::json!(["s2_vs_m07", "s1_vs_m07"])
    );
    assert_eq!(
        matrix["sim_budgets"],
        serde_json::json!([16, 24, 32, 48, 64, 96, 128])
    );
    assert_eq!(matrix["game_seeds"].as_array().unwrap().len(), 32);
    assert_eq!(matrix["game_seeds"][0], 301001);
    assert_eq!(matrix["game_seeds"][31], 301032);
    assert_eq!(matrix["seat_rotations"], 2);
    assert_eq!(matrix["plans"], 14);
    assert_eq!(matrix["matches_per_plan"], 64);
    assert_eq!(matrix["total_matches"], 896);

    let scope = &config["scope"];
    for field in [
        "diagnostic_only",
        "fixed_checkpoint",
        "no_new_training",
        "no_new_self_play_collection",
        "no_architecture_change",
        "no_dataset_change",
        "no_m07_change",
        "no_promotion",
        "no_champion_change",
    ] {
        assert_eq!(scope[field], true, "scope invariant {field} must be true");
    }

    assert_eq!(config["runtime_contract"]["pythonpath_exported"], false);
    assert_eq!(config["execution_gates"]["must_be_frozen_before_run"], true);
    assert_eq!(
        config["execution_gates"]["independent_review_required"],
        true
    );
    assert_eq!(config["execution_gates"]["all_matches_complete"], "896/896");
}
