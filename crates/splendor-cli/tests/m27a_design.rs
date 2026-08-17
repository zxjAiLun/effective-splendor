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
    assert_eq!(config["revision"], "design-1-repair-1");
    assert_eq!(config["status"], "DESIGNED");
    assert_eq!(config["execution_authorization"], "NOT_AUTHORIZED");
    assert_eq!(config["review"]["required_before_execution"], true);
    assert_eq!(
        config["review"]["repair_status"],
        "IMPLEMENTED_PENDING_INDEPENDENT_REVIEW"
    );
    assert_eq!(config["parent_diagnosis"]["decision"], "SEARCH_BOTTLENECK");
    assert_eq!(
        config["parent_diagnosis"]["result_manifest_sha256"],
        "7ca1ce824ed3715f099d7cdb3f6352aa42c1a141221928ab35756aaa4ff5d094"
    );
    assert_eq!(
        config["parent_diagnosis"]["review_basis_commit"],
        "94fc9b8b0acdde71b92a61566a4e6e9aa51c0f7f"
    );
    assert_eq!(
        config["parent_diagnosis"]["documentation_binding_commit"],
        "77be94637b58610eacaaf51a9bb06da3f1e0aff7"
    );

    let fixed_inputs = &config["fixed_inputs"];
    assert_eq!(
        fixed_inputs["s1_checkpoint_hash"],
        "1ae31dac9eec37485efdbb906109227dbe77424e78b31a906d158ac1d414f0b8"
    );
    assert_eq!(
        fixed_inputs["s2_checkpoint_hash"],
        "c43e3c239124671c77bb7436dcf79e4fe6c71b66c8008186ac68621a8ad7d5a8"
    );
    assert_eq!(
        fixed_inputs["s1_self_play_hash"],
        "b2284c6ce44a0a60bdd695d15ba42e00199a95e489970f920cfd4e4aaf464053"
    );
    assert_eq!(
        fixed_inputs["s2_self_play_hash"],
        "b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46"
    );
    assert_eq!(fixed_inputs["m07_champion_id"], "m07-champion");
    assert_eq!(
        fixed_inputs["catalog"],
        "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
    );
    assert_eq!(fixed_inputs["m07_sample_seed"], 20260810);
    assert_eq!(fixed_inputs["m07_sample_count"], 4);
    assert_eq!(fixed_inputs["m07_max_depth_turns"], 1);
    assert_eq!(fixed_inputs["m07_max_nodes"], 2000);
    assert_eq!(fixed_inputs["neural_sample_seed"], 26000018);
    assert_eq!(fixed_inputs["max_depth_turns"], 1);
    assert_eq!(fixed_inputs["puct_exploration_milli"], 1500);
    assert_eq!(fixed_inputs["neural_device"], "cuda");

    let matrix = &config["planned_matrix"];
    assert_eq!(
        matrix["candidate_pairs"],
        serde_json::json!(["s2_vs_m07", "s1_vs_m07"])
    );
    assert_eq!(
        matrix["sim_budgets"],
        serde_json::json!([16, 24, 32, 48, 64, 96, 128])
    );
    let seeds = matrix["game_seeds"].as_array().unwrap();
    assert_eq!(seeds.len(), 32);
    for (offset, seed) in (301001u64..=301032).enumerate() {
        assert_eq!(seeds[offset].as_u64(), Some(seed));
    }
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

    let runtime = &config["runtime_contract"];
    assert_eq!(runtime["program"], "splendor");
    assert_eq!(runtime["python"], "python");
    assert_eq!(runtime["module_root"], "training/m17_gpu");
    assert_eq!(
        runtime["path_bootstrap"],
        "local-artifacts/m24-scale-failure-diagnosis-v1/run-m24-env.sh or an equivalent reviewed wrapper"
    );
    assert_eq!(runtime["pythonpath_exported"], false);
    assert_eq!(runtime["handshake_timeout_ms"], 5000);
    assert_eq!(runtime["move_timeout_ms"], 30000);
    assert_eq!(runtime["shutdown_grace_ms"], 2000);

    let statistics = &config["statistics"];
    assert_eq!(
        statistics["statistics_contract"],
        "effective-splendor-m27a-paired-search-curve-v1"
    );
    assert_eq!(statistics["confidence_bps"], 9500);
    assert_eq!(
        statistics["primary_metric"],
        "pairwise center score bps from W/T/L"
    );
    assert_eq!(
        statistics["anchor_metric"],
        "floor(mean(anchor_block_delta_bps)) over matched S2/S1 seed blocks"
    );
    assert_eq!(
        statistics["confidence_interpretation"],
        "Each reported lower or upper bound is a one-sided Hoeffding bound using exp(-3) < 0.05; bounds are per budget and diagnostic, not a promotion claim."
    );
    assert_eq!(
        statistics["budget_aggregation"],
        "Report every pair and budget independently; do not pool budgets, drop budgets, or revise the ordered budget list after observing results."
    );
    let unit = &statistics["statistical_unit"];
    assert_eq!(unit["name"], "paired_seed_block");
    assert_eq!(
        unit["definition"],
        "One frozen game seed at one pair and simulation budget, containing both cyclic seat rotations."
    );
    assert_eq!(unit["blocks_per_plan"], 32);
    assert_eq!(unit["matches_per_block"], 2);
    assert_eq!(
        unit["block_complete_if"],
        "Both seat rotations for the seed complete."
    );
    assert_eq!(
        unit["incomplete_block_policy"],
        "Exclude an incomplete block from center and uncertainty calculations; any incomplete block fails the execution gate."
    );
    assert_eq!(
        unit["anchor_pairing_keys"],
        serde_json::json!(["simulation_budget", "game_seed", "seat_rotation"])
    );

    let score = &statistics["score_estimator"];
    assert_eq!(
        score["score_definition"],
        "win=1.0, tie=0.5, loss=0.0 per completed match"
    );
    assert_eq!(
        score["center_formula"],
        "floor(10000 * (wins * 2 + ties) / (2 * completed_matches))"
    );
    assert_eq!(
        score["margin_formula"],
        "margin_bps = ceil_sqrt(ceil_div(150000000, completed_paired_seed_blocks))"
    );
    assert_eq!(
        score["lower_bound_formula"],
        "lower_bps = max(0, center_bps - margin_bps)"
    );
    assert_eq!(
        score["upper_bound_formula"],
        "upper_bps = min(10000, center_bps + margin_bps)"
    );
    assert_eq!(score["margin_numerator_bps_squared"], 150000000);

    let anchor = &statistics["anchor_estimator"];
    assert_eq!(anchor["name"], "matched_s2_minus_s1_anchor");
    assert_eq!(
        anchor["pairing_definition"],
        "Join s2_vs_m07 and s1_vs_m07 records at the same simulation budget, game seed, and seat rotation before forming each seed block."
    );
    assert_eq!(
        anchor["block_score_formula"],
        "block_score_bps = floor(10000 * (wins * 2 + ties) / (2 * 2)) over the two seat rotations"
    );
    assert_eq!(
        anchor["block_delta_formula"],
        "anchor_block_delta_bps = block_score_bps(s2_vs_m07) - block_score_bps(s1_vs_m07)"
    );
    assert_eq!(
        anchor["block_value_range_bps"],
        serde_json::json!([-10000, 10000])
    );
    assert_eq!(
        anchor["center_formula"],
        "floor(sum(anchor_block_delta_bps) / completed_paired_seed_blocks), with floor toward negative infinity"
    );
    assert_eq!(
        anchor["margin_formula"],
        "anchor_margin_bps = ceil_sqrt(ceil_div(600000000, completed_paired_seed_blocks))"
    );
    assert_eq!(
        anchor["lower_bound_formula"],
        "anchor_lower_bps = max(-10000, anchor_center_bps - anchor_margin_bps)"
    );
    assert_eq!(
        anchor["upper_bound_formula"],
        "anchor_upper_bps = min(10000, anchor_center_bps + anchor_margin_bps)"
    );
    assert_eq!(anchor["margin_numerator_bps_squared"], 600000000);
    assert_eq!(
        anchor["margin_range_rationale"],
        "The paired block delta lies in a 20000-bps-wide interval, so the one-sided exp(-3) Hoeffding margin uses 6 * 10000^2 / n."
    );

    assert_eq!(
        statistics["required_per_budget_report"],
        serde_json::json!([
            "s2_vs_m07 score center/lower/upper bps",
            "s1_vs_m07 score center/lower/upper bps",
            "matched anchor center/lower/upper bps",
            "raw W/T/L for both pair plans",
            "completed paired seed blocks",
            "aborted matches and candidate faults",
            "seat-rotation split"
        ])
    );

    let decision = &config["operating_region_decision"];
    assert_eq!(
        decision["contract"],
        "effective-splendor-m27a-stable-operating-region-v1"
    );
    assert_eq!(
        decision["ordered_budgets"],
        serde_json::json!([16, 24, 32, 48, 64, 96, 128])
    );
    assert_eq!(decision["selection_endpoint"], "matched_s2_minus_s1_anchor");
    let eligibility = &decision["eligibility"];
    assert_eq!(
        eligibility["required_complete_matrix"],
        "Both pair plans at the budget have 32 completed paired seed blocks (64/64 matches each)."
    );
    assert_eq!(eligibility["required_zero_aborts"], true);
    assert_eq!(eligibility["required_zero_candidate_faults"], true);
    assert_eq!(eligibility["anchor_lower_bound_min_bps"], -200);
    assert_eq!(
        eligibility["anchor_lower_bound_min_rationale"],
        "Reuse the frozen M24 200-bps anchor-regression tolerance, applied to the conservative matched-anchor lower bound for operating-region eligibility."
    );
    assert_eq!(
        eligibility["eligible_if"],
        "The budget satisfies the complete-matrix and zero-fault requirements and anchor_lower_bps >= -200."
    );
    assert_eq!(
        eligibility["absolute_s2_curve_role"],
        "descriptive_secondary"
    );
    assert_eq!(eligibility["absolute_s2_curve_is_required_to_report"], true);
    assert_eq!(eligibility["absolute_s2_curve_controls_selection"], false);
    assert_eq!(
        eligibility["conflict_precedence"],
        "The matched anchor eligibility and stability rules control; an absolute S2-vs-M07 center or bound never overrides them."
    );

    let adjacent = &decision["adjacent_stability"];
    assert_eq!(adjacent["comparison_metric"], "matched_anchor");
    assert_eq!(adjacent["max_center_regression_bps"], 200);
    assert_eq!(
        adjacent["interval_overlap_rule"],
        "previous_anchor_lower_bps <= next_anchor_upper_bps AND next_anchor_lower_bps <= previous_anchor_upper_bps"
    );
    assert_eq!(
        adjacent["non_regression_rule"],
        "next_anchor_center_bps >= previous_anchor_center_bps - 200"
    );
    assert_eq!(
        adjacent["stable_transition_rule"],
        "Both budgets are eligible, their matched-anchor intervals overlap, and the higher-budget center does not regress by more than 200 bps."
    );

    let region = &decision["stable_region"];
    assert_eq!(region["minimum_consecutive_budgets"], 3);
    assert_eq!(
        region["construction_rule"],
        "Scan ordered_budgets from low to high and form maximal contiguous runs whose budgets are eligible and whose adjacent transitions satisfy stable_transition_rule."
    );
    assert_eq!(
        region["first_region_rule"],
        "If multiple runs meet the minimum length, use the first run in ordered_budgets order."
    );
    assert_eq!(
        region["selection_rule"],
        "Select the lowest simulation budget in the first stable region; this is an operating point, not an optimum claim."
    );
    assert_eq!(region["no_region_decision"], "M27A_INCONCLUSIVE");
    assert_eq!(region["no_region_decision_authorizes_execution"], false);
    assert_eq!(
        region["allowed_decisions"],
        serde_json::json!(["M27A_STABLE_REGION_SELECTED", "M27A_INCONCLUSIVE"])
    );

    assert_eq!(config["execution_gates"]["must_be_frozen_before_run"], true);
    assert_eq!(
        config["execution_gates"]["independent_review_required"],
        true
    );
    assert_eq!(
        config["execution_gates"]["statistics_contract_frozen_before_run"],
        true
    );
    assert_eq!(
        config["execution_gates"]["operating_region_contract_frozen_before_run"],
        true
    );
    assert_eq!(config["execution_gates"]["all_matches_complete"], "896/896");
    assert_eq!(config["execution_gates"]["zero_aborts"], true);
    assert_eq!(config["execution_gates"]["zero_candidate_faults"], true);
    assert_eq!(config["execution_gates"]["all_plans_validate"], true);
    assert_eq!(
        config["execution_gates"]["raw_report_and_plan_hashes_bound"],
        true
    );

    assert_eq!(config["next_decision"]["m25_authorized"], false);
    assert_eq!(config["next_decision"]["m26_authorized"], false);
    assert_eq!(config["next_decision"]["m28_authorized"], false);
}
