use std::fs;

use serde_json::Value;

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn relative_improvement_bps(control: &Value, candidate: &Value, split: &str, metric: &str) -> i64 {
    let control_value = control[split][metric].as_f64().unwrap();
    let candidate_value = candidate[split][metric].as_f64().unwrap();
    (10000.0 * (control_value - candidate_value) / control_value).floor() as i64
}

fn top1_delta(control: &Value, candidate: &Value, split: &str) -> f64 {
    candidate[split]["visit_top1"].as_f64().unwrap()
        - control[split]["visit_top1"].as_f64().unwrap()
}

#[test]
fn m28b_contextual_interaction_prereg_is_single_variable_and_not_authorized() {
    let config: Value = serde_json::from_slice(
        &fs::read(root().join("benchmarks/m28b-contextual-entity-interaction-v1.config.json"))
            .unwrap(),
    )
    .unwrap();

    assert_eq!(
        config["format"],
        "effective-splendor-m28b-contextual-entity-interaction"
    );
    assert_eq!(config["version"], 1);
    assert_eq!(config["milestone"], "M28B");
    assert_eq!(config["revision"], "contextual-interaction-v1");
    assert_eq!(config["status"], "DESIGNED");
    assert_eq!(
        config["baseline_commit"],
        "c0caa883e47cadce1ae85c78b85ba7c4e69ac007"
    );
    assert_eq!(config["training_authorization"], "NOT_AUTHORIZED");
    assert_eq!(config["arena_authorization"], "NOT_AUTHORIZED");
    assert_eq!(config["downstream_authorization"], false);
    assert_eq!(config["promotion"], "NONE");
    assert_eq!(config["champion"], "M07");

    let parent = &config["parent"];
    assert_eq!(parent["milestone"], "M28A");
    assert_eq!(parent["status"], "ACCEPTED / CLOSED");
    assert_eq!(
        parent["closure_commit"],
        "c0caa883e47cadce1ae85c78b85ba7c4e69ac007"
    );
    assert_eq!(parent["outcome"], "M28A_OFFLINE_NO_CAPACITY_SIGNAL");

    assert_eq!(
        config["scope"],
        serde_json::json!({
            "fixed_dataset": true,
            "fixed_entity_schema": true,
            "fixed_policy_value_objective": true,
            "fixed_optimizer_recipe": true,
            "fixed_search_algorithm": true,
            "single_architecture_intervention": true,
            "no_new_self_play": true,
            "no_teacher_change": true,
            "no_width_sweep": true,
            "no_transformer": true,
            "no_multi_head_attention": true,
            "no_target_redesign": true,
            "no_puct_tuning": true,
            "no_optimizer_sweep": true,
            "no_learning_rate_sweep": true,
            "no_promotion_trial": true
        })
    );

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
    assert_eq!(split["s1_reference"]["game_index_modulus"], 4);
    assert_eq!(split["s1_reference"]["game_index_remainder"], 0);
    assert_eq!(split["s1_reference"]["examples"], 1953);

    let models = config["models"].as_array().unwrap();
    assert_eq!(models.len(), 2);
    assert_eq!(models[0]["role"], "control");
    assert_eq!(models[0]["architecture"], "entity_mixer");
    assert_eq!(models[0]["hidden_dim"], 192);
    assert_eq!(models[0]["blocks"], 4);
    assert_eq!(models[0]["interaction_blocks"], 0);
    assert_eq!(models[0]["expected_parameter_count"], 949060);
    assert_eq!(models[1]["role"], "candidate");
    assert_eq!(models[1]["architecture"], "contextual_entity_mixer");
    assert_eq!(models[1]["hidden_dim"], 192);
    assert_eq!(models[1]["blocks"], 4);
    assert_eq!(models[1]["interaction_blocks"], 2);
    assert_eq!(models[1]["expected_parameter_count"], 1689798);

    let interaction = &config["interaction"];
    assert_eq!(interaction["kind"], "masked_pairwise_contextual_mixer");
    assert_eq!(interaction["interaction_blocks"], 2);
    assert_eq!(interaction["entity_encoder"], "existing_entity_encoder");
    assert_eq!(
        interaction["pair_features"],
        serde_json::json!(["q_i", "k_j", "q_i * k_j"])
    );
    assert_eq!(interaction["weight_activation"], "sigmoid");
    assert_eq!(interaction["source_mask"], "visible_entities_only");
    assert_eq!(interaction["target_mask"], "visible_entities_only");
    assert_eq!(interaction["exclude_self_pair"], true);
    assert_eq!(interaction["aggregation"], "masked_weighted_mean");
    assert_eq!(
        interaction["residual_input"],
        serde_json::json!(["entity", "context", "global_context"])
    );
    assert_eq!(interaction["standard_multi_head_attention"], false);
    assert_eq!(interaction["transformer_encoder"], false);

    let initialization = &config["initialization"];
    assert_eq!(initialization["mode"], "fresh");
    assert_eq!(initialization["initialization_seed"], 280229);
    assert_eq!(initialization["shuffle_seed"], 280229);
    assert_eq!(initialization["reset_before_each_model"], true);
    assert_eq!(
        initialization["forbidden_sources"],
        serde_json::json!([
            "M22 checkpoint weights",
            "M24-S1 checkpoint weights",
            "M24-S2 checkpoint weights",
            "M28A control checkpoint weights",
            "M28A candidate checkpoint weights",
            "partial weight transplant",
            "Net2Net",
            "weight interpolation",
            "checkpoint surgery"
        ])
    );

    let training = &config["training"];
    assert_eq!(training["device"], "cuda");
    assert_eq!(training["seed"], 280229);
    assert_eq!(training["initialization_seed"], 280229);
    assert_eq!(training["shuffle_seed"], 280229);
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
    assert_eq!(training["determinism"]["dataloader_workers"], 0);
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
    assert_eq!(
        offline["fail_decision"],
        "M28B_OFFLINE_NO_INTERACTION_SIGNAL"
    );
    assert_eq!(offline["fail_action"], "STOP_NO_ARENA");
    assert_eq!(offline["pass_decision"], "M28B_ARENA_ELIGIBLE");

    let arena = &config["arena_screen"];
    assert_eq!(
        arena["condition"],
        "Only after explicit training review authorization and offline PASS; this prereg does not authorize execution."
    );
    assert_eq!(arena["neural_search"]["simulations"], 16);
    assert_eq!(arena["neural_search"]["max_depth_turns"], 1);
    assert_eq!(arena["neural_search"]["puct_exploration_milli"], 1500);
    assert_eq!(arena["neural_search"]["sample_seed"], 28000028);
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
    for (index, seed) in (303001u64..=303032).enumerate() {
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
            "M28B_OFFLINE_NO_INTERACTION_SIGNAL",
            "M28B_ARENA_ELIGIBLE",
            "M28B_INTERACTION_SIGNAL",
            "M28B_NO_INTERACTION_SIGNAL",
            "M28B_MIXED",
            "M28B_EXECUTION_INVALID"
        ])
    );
    assert_eq!(config["decision_outputs"]["promotion"], "NONE");
    assert_eq!(config["decision_outputs"]["champion"], "M07");
    assert_eq!(config["decision_outputs"]["m25"], "NOT_AUTHORIZED");
    assert_eq!(config["decision_outputs"]["m26"], "NOT_AUTHORIZED");
    assert_eq!(
        config["decision_outputs"]["downstream_continuation"],
        "NOT_AUTHORIZED"
    );
}

#[test]
fn m28b_result_recomputes_frozen_offline_stop() {
    let config: Value = serde_json::from_slice(
        &fs::read(root().join("benchmarks/m28b-contextual-entity-interaction-v1.config.json"))
            .unwrap(),
    )
    .unwrap();
    let result: Value = serde_json::from_slice(
        &fs::read(root().join("benchmarks/m28b-contextual-entity-interaction-v1.result.json"))
            .unwrap(),
    )
    .unwrap();

    assert_eq!(
        result["format"],
        "effective-splendor-m28b-contextual-entity-interaction-result"
    );
    assert_eq!(result["status"], "ACCEPTED");
    assert_eq!(result["lifecycle"], "CLOSED");
    assert_eq!(
        result["review"]["findings"],
        serde_json::json!({"P0": 0, "P1": 0, "P2": 0})
    );
    assert_eq!(result["training"]["status"], "VERIFIED");
    assert_eq!(result["training"]["exit_code"], 0);
    assert_eq!(result["training"]["logical_batch_size"], 128);
    assert_eq!(result["training"]["physical_microbatch_size"], 32);
    assert_eq!(result["training"]["epochs"], 32);
    assert_eq!(
        result["training"]["host_runtime"]["hard_thermal_abort_triggered"],
        false
    );
    assert_eq!(result["training"]["host_runtime"]["soft_pause_count"], 1);

    let models = result["training"]["models"].as_array().unwrap();
    assert_eq!(models.len(), 2);
    let control = &models[0];
    let candidate = &models[1];
    assert_eq!(control["role"], "control");
    assert_eq!(control["evaluator_reassessed"], true);
    assert_eq!(candidate["role"], "candidate");
    assert_eq!(candidate["history_epochs"], 32);

    let full_policy =
        relative_improvement_bps(control, candidate, "validation", "policy_cross_entropy");
    let full_value = relative_improvement_bps(control, candidate, "validation", "value_mse");
    let full_top1 = top1_delta(control, candidate, "validation");
    let reference_policy =
        relative_improvement_bps(control, candidate, "s1_reference", "policy_cross_entropy");
    let reference_value = relative_improvement_bps(control, candidate, "s1_reference", "value_mse");
    let reference_top1 = top1_delta(control, candidate, "s1_reference");

    let g1 = &config["offline_gates"]["G1_full_s2_validation"];
    let g2 = &config["offline_gates"]["G2_s1_reference_non_regression"];
    let g1_pass = (full_policy >= g1["policy_ce_improvement_min_bps"].as_i64().unwrap()
        || full_value >= g1["value_mse_improvement_min_bps"].as_i64().unwrap())
        && full_policy >= g1["policy_ce_non_regression_min_bps"].as_i64().unwrap()
        && full_value >= g1["value_mse_non_regression_min_bps"].as_i64().unwrap()
        && full_top1 >= g1["top1_delta_min"].as_f64().unwrap();
    let g2_pass = reference_policy >= g2["policy_ce_improvement_min_bps"].as_i64().unwrap()
        && reference_value >= g2["value_mse_improvement_min_bps"].as_i64().unwrap()
        && reference_top1 >= g2["top1_delta_min"].as_f64().unwrap();

    let offline = &result["offline"];
    assert_eq!(offline["G1_full_s2_validation"]["pass"], g1_pass);
    assert_eq!(
        offline["G1_full_s2_validation"]["policy_ce_improvement_bps"],
        full_policy
    );
    assert_eq!(
        offline["G1_full_s2_validation"]["value_mse_improvement_bps"],
        full_value
    );
    assert!(
        (offline["G1_full_s2_validation"]["top1_delta"]
            .as_f64()
            .unwrap()
            - full_top1)
            .abs()
            < 1e-12
    );
    assert_eq!(offline["G2_s1_reference_non_regression"]["pass"], g2_pass);
    assert_eq!(
        offline["G2_s1_reference_non_regression"]["policy_ce_improvement_bps"],
        reference_policy
    );
    assert_eq!(
        offline["G2_s1_reference_non_regression"]["value_mse_improvement_bps"],
        reference_value
    );
    assert!(
        (offline["G2_s1_reference_non_regression"]["top1_delta"]
            .as_f64()
            .unwrap()
            - reference_top1)
            .abs()
            < 1e-12
    );
    assert!(!g1_pass && !g2_pass);
    assert_eq!(
        offline["decision"],
        config["offline_gates"]["fail_decision"]
    );
    assert_eq!(offline["fail_action"], "STOP_NO_ARENA");
    assert_eq!(result["arena"]["authorization"], "NOT_AUTHORIZED");
    assert_eq!(result["arena"]["not_run"], true);
    assert_eq!(result["promotion"], "NONE");
    assert_eq!(result["champion"], "M07");
}
