use std::fs;

use serde_json::Value;

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn m28a_capacity_only_prereg_is_frozen_and_not_authorized_to_run() {
    let config: Value = serde_json::from_slice(
        &fs::read(root().join("benchmarks/m28a-entity-mixer-width-v1.config.json")).unwrap(),
    )
    .unwrap();

    assert_eq!(
        config["format"],
        "effective-splendor-m28a-entity-mixer-width-scaling"
    );
    assert_eq!(config["version"], 1);
    assert_eq!(config["milestone"], "M28A");
    assert_eq!(config["revision"], "capacity-only-v1");
    assert_eq!(config["status"], "DESIGNED");
    assert_eq!(
        config["baseline_commit"],
        "428c227f507a232be0aab9187e3195f8c352f4bd"
    );
    assert_eq!(config["training_authorization"], "NOT_AUTHORIZED");
    assert_eq!(config["arena_authorization"], "NOT_AUTHORIZED");
    assert_eq!(config["downstream_authorization"], false);
    assert_eq!(config["promotion"], "NONE");
    assert_eq!(config["champion"], "M07");

    let parent = &config["parent"];
    assert_eq!(parent["milestone"], "M27A");
    assert_eq!(parent["status"], "ACCEPTED / CLOSED");
    assert_eq!(
        parent["closure_commit"],
        "428c227f507a232be0aab9187e3195f8c352f4bd"
    );
    assert_eq!(parent["outcome"], "M27A_INCONCLUSIVE");

    let authorization = &config["authorization"];
    assert_eq!(authorization["training"], "NOT_AUTHORIZED");
    assert_eq!(authorization["arena"], "NOT_AUTHORIZED");
    assert_eq!(authorization["m25"], false);
    assert_eq!(authorization["m26"], false);
    assert_eq!(authorization["m28_downstream_continuation"], false);

    let dataset = &config["dataset"];
    assert_eq!(dataset["format"], "effective-splendor-neural-self-play-v2");
    assert_eq!(dataset["version"], 2);
    assert_eq!(dataset["games"], 512);
    assert_eq!(dataset["examples"], 31505);
    assert_eq!(
        dataset["self_play_hash"],
        "b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46"
    );
    assert_eq!(
        dataset["file_sha256"],
        "ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f"
    );
    assert_eq!(
        dataset["generator_checkpoint_hash"],
        "dc611f3d575f87e2b24221d633f8af55c98055357b05ccb822ef46ec0cb98c04"
    );

    let split = &config["split"];
    assert_eq!(split["total_examples"], 31505);
    assert_eq!(split["validation"]["game_index_modulus"], 4);
    assert_eq!(split["validation"]["game_index_remainder"], 0);
    assert_eq!(split["validation"]["examples"], 7851);
    assert_eq!(split["train"]["examples"], 23654);
    assert_eq!(split["s1_reference"]["game_index_lt"], 128);
    assert_eq!(split["s1_reference"]["examples"], 1953);

    let models = config["models"].as_array().unwrap();
    assert_eq!(models.len(), 2);
    assert_eq!(models[0]["role"], "control");
    assert_eq!(
        models[0]["model_id"],
        "m28a-entity-mixer-h192-b4-control-v1"
    );
    assert_eq!(models[0]["architecture"], "entity_mixer");
    assert_eq!(models[0]["hidden_dim"], 192);
    assert_eq!(models[0]["blocks"], 4);
    assert_eq!(models[0]["dropout"], 0.0);
    assert_eq!(models[0]["expected_parameter_count"], 949060);
    assert_eq!(models[1]["role"], "candidate");
    assert_eq!(models[1]["model_id"], "m28a-entity-mixer-h320-b4-v1");
    assert_eq!(models[1]["architecture"], "entity_mixer");
    assert_eq!(models[1]["hidden_dim"], 320);
    assert_eq!(models[1]["blocks"], 4);
    assert_eq!(models[1]["dropout"], 0.0);
    assert_eq!(models[1]["expected_parameter_count"], 2605764);

    let initialization = &config["initialization"];
    assert_eq!(initialization["mode"], "fresh");
    assert_eq!(initialization["initialization_seed"], 280129);
    assert_eq!(initialization["shuffle_seed"], 280129);
    assert_eq!(initialization["reset_before_each_model"], true);
    assert_eq!(
        initialization["forbidden_sources"],
        serde_json::json!([
            "M22 checkpoint weights",
            "M24-S1 checkpoint weights",
            "M24-S2 checkpoint weights",
            "partial weight transplant",
            "Net2Net",
            "weight interpolation",
            "checkpoint surgery"
        ])
    );

    let training = &config["training"];
    assert_eq!(training["device"], "cuda");
    assert_eq!(training["seed"], 280129);
    assert_eq!(training["batch_size"], 128);
    assert_eq!(training["epochs"], 32);
    assert_eq!(training["learning_rate"], 0.0001);
    assert_eq!(training["weight_decay"], 0.0001);
    assert_eq!(training["value_loss_weight"], 0.5);
    assert_eq!(training["gradient_clip_norm"], 1.0);
    assert_eq!(training["optimizer"], "AdamW");
    assert_eq!(
        training["determinism"]["cublas_workspace_config"],
        ":4096:8"
    );
    assert_eq!(training["determinism"]["torch_deterministic"], true);
    assert_eq!(training["determinism"]["cudnn_benchmark"], false);
    assert_eq!(
        training["selection"]["score"],
        "policy_cross_entropy + 0.5 * value_mse"
    );
    assert_eq!(training["selection"]["source"], "full S2 validation only");
    assert_eq!(training["selection"]["arena_reselection"], false);

    let offline = &config["offline_gates"];
    assert_eq!(
        offline["relative_improvement_formula"],
        "floor(10000 * (control - candidate) / control)"
    );
    assert_eq!(
        offline["G1_full_s2_validation"]["policy_ce_improvement_min_bps"],
        50
    );
    assert_eq!(
        offline["G1_full_s2_validation"]["value_mse_improvement_min_bps"],
        50
    );
    assert_eq!(
        offline["G1_full_s2_validation"]["policy_ce_non_regression_min_bps"],
        -100
    );
    assert_eq!(
        offline["G1_full_s2_validation"]["value_mse_non_regression_min_bps"],
        -100
    );
    assert_eq!(offline["G1_full_s2_validation"]["top1_delta_min"], -0.01);
    assert_eq!(
        offline["G2_s1_reference_non_regression"]["policy_ce_improvement_min_bps"],
        -100
    );
    assert_eq!(
        offline["G2_s1_reference_non_regression"]["value_mse_improvement_min_bps"],
        -100
    );
    assert_eq!(
        offline["G2_s1_reference_non_regression"]["top1_delta_min"],
        -0.01
    );
    assert_eq!(offline["fail_decision"], "M28A_OFFLINE_NO_CAPACITY_SIGNAL");
    assert_eq!(offline["fail_action"], "STOP_NO_ARENA");

    let arena = &config["arena_screen"];
    assert_eq!(arena["neural_search"]["simulations"], 16);
    assert_eq!(arena["neural_search"]["max_depth_turns"], 1);
    assert_eq!(arena["neural_search"]["puct_exploration_milli"], 1500);
    assert_eq!(arena["neural_search"]["sample_seed"], 28000018);
    assert_eq!(arena["neural_search"]["device"], "cuda");
    assert_eq!(arena["m07"]["sample_seed"], 20260810);
    assert_eq!(arena["m07"]["sample_count"], 4);
    assert_eq!(arena["m07"]["max_depth_turns"], 1);
    assert_eq!(arena["m07"]["max_nodes"], 2000);
    assert_eq!(arena["timeouts_ms"]["handshake"], 5000);
    assert_eq!(arena["timeouts_ms"]["move"], 30000);
    assert_eq!(arena["timeouts_ms"]["shutdown"], 2000);
    assert_eq!(
        arena["matrix"]["pairs"],
        serde_json::json!(["candidate_vs_control", "candidate_vs_m07", "control_vs_m07"])
    );
    let seeds = arena["matrix"]["game_seeds"].as_array().unwrap();
    assert_eq!(seeds.len(), 32);
    for (index, seed) in (302001u64..=302032).enumerate() {
        assert_eq!(seeds[index].as_u64(), Some(seed));
    }
    assert_eq!(arena["matrix"]["seat_rotations"], 2);
    assert_eq!(arena["matrix"]["matches_per_pair"], 64);
    assert_eq!(arena["matrix"]["total_matches"], 192);
    assert_eq!(arena["statistics"]["direct_capacity_threshold_bps"], 5500);
    assert_eq!(arena["statistics"]["m07_anchor_threshold_bps"], 500);
    assert_eq!(arena["statistics"]["uncertainty_role"], "diagnostic_only");

    assert_eq!(
        config["decision_outputs"]["allowed"],
        serde_json::json!([
            "M28A_OFFLINE_NO_CAPACITY_SIGNAL",
            "M28A_CAPACITY_SIGNAL",
            "M28A_NO_CAPACITY_SIGNAL",
            "M28A_MIXED",
            "M28A_EXECUTION_INVALID"
        ])
    );
    assert_eq!(config["decision_outputs"]["promotion"], "NONE");
    assert_eq!(config["decision_outputs"]["champion"], "M07");
    assert_eq!(config["decision_outputs"]["m25"], "NOT_AUTHORIZED");
    assert_eq!(config["decision_outputs"]["m26"], "NOT_AUTHORIZED");
}

#[test]
fn m28a_training_result_records_frozen_offline_stop() {
    let result: Value = serde_json::from_slice(
        &fs::read(root().join("benchmarks/m28a-entity-mixer-width-v1.result.json")).unwrap(),
    )
    .unwrap();

    assert_eq!(
        result["format"],
        "effective-splendor-m28a-entity-mixer-width-result"
    );
    assert_eq!(result["version"], 1);
    assert_eq!(result["status"], "ACCEPTED");
    assert_eq!(result["milestone"], "M28A");
    assert_eq!(
        result["review"]["source_prereg_status"],
        "ACCEPTED / FROZEN"
    );
    assert_eq!(result["review"]["training_authorization"], "AUTHORIZED");
    assert_eq!(result["review"]["training_evidence_status"], "ACCEPTED");
    assert_eq!(
        result["review"]["training_evidence_review_basis_commit"],
        "82ce9843b585a5803fa97e5fec0b68b909e6679a"
    );
    assert_eq!(result["review"]["current_review_findings"]["P0"], 0);
    assert_eq!(result["review"]["current_review_findings"]["P1"], 0);
    assert_eq!(result["review"]["current_review_findings"]["P2"], 1);
    assert_eq!(
        result["review"]["historical_source_prereg_findings"]["P0"],
        0
    );
    assert_eq!(
        result["review"]["historical_source_prereg_findings"]["P1"],
        0
    );
    assert_eq!(
        result["review"]["historical_source_prereg_findings"]["P2"],
        2
    );
    assert_eq!(result["review"]["arena_authorization"], "NOT_AUTHORIZED");
    assert_eq!(result["review"]["findings"]["P0"], 0);
    assert_eq!(result["review"]["findings"]["P1"], 0);
    assert_eq!(result["review"]["findings"]["P2"], 2);

    assert_eq!(
        result["preregistration"]["sha256"],
        "02693aba7bfa4de2a8e52c1490175572f2039691c564e7c9b25c2ce7f40519d4"
    );
    assert_eq!(
        result["preregistration"]["config_status_fields_unchanged"],
        true
    );
    assert_eq!(result["dataset"]["games"], 512);
    assert_eq!(result["dataset"]["examples"], 31505);
    assert_eq!(
        result["dataset"]["self_play_hash"],
        "b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46"
    );
    assert_eq!(
        result["dataset"]["file_sha256"],
        "ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f"
    );

    assert_eq!(result["training"]["status"], "VERIFIED");
    assert_eq!(result["training"]["exit_code"], 0);
    assert_eq!(result["training"]["device"], "cuda");
    assert_eq!(result["training"]["initialization"], "fresh");
    assert_eq!(result["training"]["initialization_seed"], 280129);
    assert_eq!(result["training"]["shuffle_seed"], 280129);
    assert_eq!(result["training"]["batch_size"], 128);
    assert_eq!(result["training"]["epochs"], 32);
    assert_eq!(result["training"]["deterministic_algorithms_enabled"], true);
    assert_eq!(result["training"]["cublas_workspace_config"], ":4096:8");
    assert_eq!(
        result["training"]["training_config_hash"],
        "a5dbdfb0a7a418830b4d6b25eaf87f9c83af381997583e67d29a056583b3e39e"
    );

    let models = result["training"]["models"].as_array().unwrap();
    assert_eq!(models.len(), 2);
    assert_eq!(models[0]["role"], "control");
    assert_eq!(models[0]["parameter_count"], 949060);
    assert_eq!(models[0]["best_epoch"], 12);
    assert_eq!(models[1]["role"], "candidate");
    assert_eq!(models[1]["parameter_count"], 2605764);
    assert_eq!(models[1]["best_epoch"], 9);

    let offline = &result["offline"];
    assert_eq!(offline["status"], "APPLIED");
    assert_eq!(offline["G1_full_s2_validation"]["pass"], false);
    assert_eq!(
        offline["G1_full_s2_validation"]["policy_ce_improvement_bps"],
        10
    );
    assert_eq!(
        offline["G1_full_s2_validation"]["value_mse_improvement_bps"],
        34
    );
    assert_eq!(offline["G2_s1_reference_non_regression"]["pass"], true);
    assert_eq!(
        offline["G2_s1_reference_non_regression"]["policy_ce_improvement_bps"],
        12
    );
    assert_eq!(
        offline["G2_s1_reference_non_regression"]["value_mse_improvement_bps"],
        249
    );
    assert_eq!(offline["decision"], "M28A_OFFLINE_NO_CAPACITY_SIGNAL");
    assert_eq!(offline["fail_action"], "STOP_NO_ARENA");
    assert_eq!(result["arena"]["authorization"], "NOT_AUTHORIZED");
    assert_eq!(result["arena"]["not_run"], true);
    assert_eq!(result["promotion"], "NONE");
    assert_eq!(result["champion"], "M07");
    assert_eq!(result["downstream_authorization"]["m25"], "NOT_AUTHORIZED");
    assert_eq!(result["downstream_authorization"]["m26"], "NOT_AUTHORIZED");
    assert_eq!(
        result["downstream_authorization"]["m28_continuation"],
        "NOT_AUTHORIZED"
    );
}
