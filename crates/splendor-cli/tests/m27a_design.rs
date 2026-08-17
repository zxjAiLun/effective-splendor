use std::collections::HashSet;
use std::fs;

use serde_json::Value;
use sha2::{Digest, Sha256};
use splendor_eval::{evaluation_plan_hash_v1, expand_schedule, EvaluationPlanV1};

fn root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

#[test]
fn m27a_design_is_frozen_and_execution_is_unauthorized() {
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
    assert_eq!(config["revision"], "design-1-repair-2");
    assert_eq!(config["status"], "FROZEN");
    assert_eq!(config["execution_authorization"], "NOT_AUTHORIZED");
    assert_eq!(config["review"]["required_before_execution"], true);
    assert_eq!(config["review"]["repair_status"], "ACCEPTED");
    assert_eq!(
        config["review"]["source_review"],
        "PASS_INDEPENDENT_REVIEW_OF_A13BCDDE"
    );
    assert_eq!(config["review"]["acceptance"], "ACCEPTED");
    assert_eq!(
        config["review"]["review_basis_commit"],
        "a13bcdde67cbb9390cd7cb905ae7f3a9fce469bd"
    );
    assert_eq!(
        config["review"]["documentation_binding_commit"],
        "4d8ef5b82a11ec0a6a9df3aae42c7330f8e0cbb1"
    );
    assert_eq!(config["review"]["findings"]["P0"], 0);
    assert_eq!(config["review"]["findings"]["P1"], 0);
    assert_eq!(config["review"]["findings"]["P2"], 1);
    assert_eq!(config["review"]["plan_materialization_authorized"], true);
    assert_eq!(config["review"]["arena_execution_authorized"], false);
    assert_eq!(config["parent_diagnosis"]["decision"], "SEARCH_BOTTLENECK");
    let previous_review = &config["review"]["previous_review"];
    assert_eq!(
        previous_review["basis_commit"],
        "16cf9ec193f16175fd6c7e0425ab5212fbb61b51"
    );
    assert_eq!(
        previous_review["documentation_binding"],
        "d027a5aa9a80325f3fbfb823a775c303c6d14468"
    );
    assert_eq!(previous_review["decision"], "HOLD");
    assert_eq!(previous_review["findings"]["P0"], 0);
    assert_eq!(previous_review["findings"]["P1"], 2);
    assert_eq!(previous_review["findings"]["P2"], 1);
    assert_eq!(previous_review["plan_materialization_authorized"], false);
    assert_eq!(previous_review["arena_execution_authorized"], false);
    assert_eq!(
        config["parent_diagnosis"]["result_manifest"],
        "benchmarks/m24-scale-failure-diagnosis-v1.result.json"
    );
    let parent_manifest =
        fs::read(root().join("benchmarks/m24-scale-failure-diagnosis-v1.result.json")).unwrap();
    assert_eq!(
        config["parent_diagnosis"]["result_manifest_sha256"],
        sha256_hex(&parent_manifest)
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

    let materialization = &config["materialization_contract"];
    assert_eq!(materialization["status"], "AUTHORIZED");
    assert_eq!(
        materialization["bundle_path"],
        "benchmarks/m27a-search-budget-scaling-v1.bundle.json"
    );
    assert_eq!(
        materialization["review_basis_commit"],
        "a13bcdde67cbb9390cd7cb905ae7f3a9fce469bd"
    );
    assert_eq!(
        materialization["documentation_binding_commit"],
        "4d8ef5b82a11ec0a6a9df3aae42c7330f8e0cbb1"
    );
    assert_eq!(materialization["plan_count"], 14);
    assert_eq!(materialization["matches_per_plan"], 64);
    assert_eq!(materialization["total_matches"], 896);
    assert_eq!(materialization["execution_authorization"], "NOT_AUTHORIZED");
    assert_eq!(
        materialization["forbidden_outputs"],
        serde_json::json!(["eval-report", "replay", "result manifest"])
    );

    let statistics = &config["statistics"];
    assert_eq!(
        statistics["statistics_contract"],
        "effective-splendor-m27a-paired-search-curve-v2"
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

    let power = &statistics["power_contract"];
    assert_eq!(power["design_blocks_per_plan"], 32);
    assert_eq!(
        power["anchor_margin_formula_at_design_n"],
        "ceil_sqrt(ceil_div(600000000, 32))"
    );
    assert_eq!(power["anchor_margin_bps_at_design_n"], 4331);
    assert_eq!(power["prior_lower_bound_gate_bps"], -200);
    assert_eq!(power["prior_effective_center_threshold_bps"], 4131);
    assert_eq!(
        power["prior_effective_center_formula"],
        "anchor_center_bps - 4331 >= -200"
    );
    assert_eq!(
        power["revised_decision_role"],
        "Use uncertainty bounds as reported diagnostic evidence; use the separately frozen practical center and plateau predicates for diagnostic operating-region selection."
    );

    let uncertainty = &statistics["uncertainty_role"];
    assert_eq!(uncertainty["role"], "reported_diagnostic_evidence");
    assert_eq!(uncertainty["used_for_eligibility"], false);
    assert_eq!(uncertainty["used_for_transition"], false);
    assert_eq!(uncertainty["used_for_region_span"], false);
    assert_eq!(uncertainty["used_for_promotion"], false);
    assert_eq!(
        uncertainty["rationale"],
        "At 32 paired blocks the anchor margin is 4331 bps, so using anchor_lower_bps >= -200 would require anchor_center_bps >= 4131 and would be a low-power diagnostic gate."
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
        "effective-splendor-m27a-stable-operating-region-v2"
    );
    assert_eq!(
        decision["ordered_budgets"],
        serde_json::json!([16, 24, 32, 48, 64, 96, 128])
    );
    assert_eq!(decision["selection_endpoint"], "matched_s2_minus_s1_anchor");
    assert_eq!(decision["decision_mode"], "diagnostic_practical_center");
    let eligibility = &decision["eligibility"];
    assert_eq!(
        eligibility["required_complete_matrix"],
        "Both pair plans at the budget have 32 completed paired seed blocks (64/64 matches each)."
    );
    assert_eq!(eligibility["required_zero_aborts"], true);
    assert_eq!(eligibility["required_zero_candidate_faults"], true);
    assert_eq!(eligibility["anchor_center_min_bps"], 1000);
    assert_eq!(
        eligibility["anchor_center_min_rationale"],
        "Require a predeclared 1000-bps (10 percentage-point) practical S2-specific gain; this is below the prior M24.5 positive rescue scale of 1250 bps and is not a significance threshold."
    );
    assert_eq!(
        eligibility["anchor_lower_bound_controls_eligibility"],
        false
    );
    assert_eq!(
        eligibility["eligible_if"],
        "The budget satisfies the complete-matrix and zero-fault requirements and anchor_center_bps >= 1000."
    );
    assert!(!eligibility
        .as_object()
        .unwrap()
        .contains_key("anchor_lower_bound_min_bps"));
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
    assert_eq!(adjacent["comparison_metric"], "matched_anchor_center_bps");
    assert_eq!(adjacent["plateau_tolerance_bps"], 2000);
    assert_eq!(
        adjacent["movement_rule"],
        "abs(next_anchor_center_bps - previous_anchor_center_bps) < 2000"
    );
    assert_eq!(adjacent["interval_overlap_required"], false);
    assert_eq!(
        adjacent["interval_overlap_role"],
        "secondary_diagnostic_only"
    );
    assert_eq!(
        adjacent["stable_transition_rule"],
        "Both budgets are eligible and the absolute matched-anchor center movement is strictly less than 2000 bps; this is a practical plateau rule, not a significance test."
    );

    let region = &decision["stable_region"];
    assert_eq!(region["minimum_consecutive_budgets"], 3);
    assert_eq!(
        region["construction_rule"],
        "Scan ordered_budgets from low to high and form maximal contiguous runs whose budgets are eligible, whose adjacent transitions satisfy stable_transition_rule, and whose anchor-center span remains strictly below 2000 bps."
    );
    assert_eq!(
        region["region_span_rule"],
        "max(anchor_center_bps in region) - min(anchor_center_bps in region) < 2000"
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
        config["execution_gates"]["plan_materialization_authorized"],
        true
    );
    assert_eq!(
        config["execution_gates"]["plan_execution_authorized"],
        false
    );
    assert_eq!(
        config["execution_gates"]["no_execution_artifacts_before_plan_review"],
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

    assert_eq!(
        config["next_decision"]["after_execution"],
        "Apply operating_region_decision exactly to the reviewed full curve using practical anchor centers and plateau predicates; report Hoeffding intervals as uncertainty evidence only, select the lowest budget in the first stable region, or record M27A_INCONCLUSIVE. No post-hoc optimum selection is allowed."
    );
    assert_eq!(config["next_decision"]["m25_authorized"], false);
    assert_eq!(config["next_decision"]["m26_authorized"], false);
    assert_eq!(config["next_decision"]["m28_authorized"], false);
}

fn m27a_seeds() -> Vec<u64> {
    (301001..=301032).collect()
}

fn plan_arg(plan: &EvaluationPlanV1, agent_index: usize, flag: &str) -> String {
    let args = &plan.agents[agent_index].command.args;
    let position = args
        .iter()
        .position(|arg| arg == flag)
        .unwrap_or_else(|| panic!("missing argument {flag}"));
    args.get(position + 1)
        .unwrap_or_else(|| panic!("missing value for argument {flag}"))
        .clone()
}

#[test]
fn m27a_materialization_bundle_is_exact_and_execution_free() {
    let root = root();
    let config_bytes =
        fs::read(root.join("benchmarks/m27a-search-budget-scaling-v1.json")).unwrap();
    let config: Value = serde_json::from_slice(&config_bytes).unwrap();
    let bundle_bytes =
        fs::read(root.join("benchmarks/m27a-search-budget-scaling-v1.bundle.json")).unwrap();
    let bundle: Value = serde_json::from_slice(&bundle_bytes).unwrap();

    assert_eq!(
        bundle["format"],
        "effective-splendor-m27a-search-budget-scaling-bundle"
    );
    assert_eq!(bundle["version"], 1);
    assert_eq!(bundle["milestone"], "M27A");
    assert_eq!(bundle["revision"], "design-1-repair-2");
    assert_eq!(
        bundle["preregistration"]["path"],
        "benchmarks/m27a-search-budget-scaling-v1.json"
    );
    assert_eq!(
        bundle["preregistration"]["sha256"],
        sha256_hex(&config_bytes)
    );
    assert_eq!(bundle["preregistration"]["status"], "ACCEPTED/FROZEN");
    assert_eq!(
        bundle["preregistration"]["review_basis_commit"],
        "a13bcdde67cbb9390cd7cb905ae7f3a9fce469bd"
    );
    assert_eq!(
        bundle["preregistration"]["documentation_binding_commit"],
        "4d8ef5b82a11ec0a6a9df3aae42c7330f8e0cbb1"
    );
    assert_eq!(
        bundle["authorization"]["plan_materialization"],
        "AUTHORIZED"
    );
    assert_eq!(bundle["authorization"]["plan_execution"], "NOT_AUTHORIZED");
    assert_eq!(bundle["authorization"]["arena_execution"], "NOT_AUTHORIZED");
    assert_eq!(bundle["authorization"]["promotion"], "NONE");
    assert_eq!(
        bundle["execution_artifacts"]["eval_reports"],
        serde_json::json!([])
    );
    assert_eq!(
        bundle["execution_artifacts"]["replays"],
        serde_json::json!([])
    );
    assert_eq!(
        bundle["execution_artifacts"]["result_manifests"],
        serde_json::json!([])
    );

    let seeds = m27a_seeds();
    assert_eq!(
        bundle["matrix"]["candidate_pairs"],
        serde_json::json!(["s2_vs_m07", "s1_vs_m07"])
    );
    assert_eq!(
        bundle["matrix"]["simulations"],
        serde_json::json!([16, 24, 32, 48, 64, 96, 128])
    );
    assert_eq!(bundle["matrix"]["game_seed_count"], 32);
    assert_eq!(bundle["matrix"]["seat_rotations"], 2);
    assert_eq!(bundle["matrix"]["plans"], 14);
    assert_eq!(bundle["matrix"]["matches_per_plan"], 64);
    assert_eq!(bundle["matrix"]["total_matches"], 896);
    assert_eq!(
        bundle["matrix"]["game_seeds_sha256"],
        sha256_hex(&serde_json::to_vec(&seeds).unwrap())
    );

    let cells = bundle["cells"].as_array().unwrap();
    assert_eq!(cells.len(), 14);
    let budgets = [16u64, 24, 32, 48, 64, 96, 128];
    let expected_pairs = ["s2_vs_m07", "s1_vs_m07"];
    let mut actual_cells = HashSet::new();

    for (index, cell) in cells.iter().enumerate() {
        let pair = cell["pair"].as_str().unwrap();
        let simulations = cell["simulations"].as_u64().unwrap();
        let expected_pair = expected_pairs[index / budgets.len()];
        let expected_simulations = budgets[index % budgets.len()];
        assert_eq!(pair, expected_pair);
        assert_eq!(simulations, expected_simulations);
        assert!(actual_cells.insert((pair.to_string(), simulations)));

        let evaluation_id = format!("m27a-{pair}-v1-sim{simulations}");
        assert_eq!(cell["evaluation_id"], evaluation_id);
        let plan_path = cell["plan_path"].as_str().unwrap();
        assert_eq!(
            plan_path,
            format!("benchmarks/m27a-{pair}-v1-sim{simulations}.plan.json")
        );
        let plan_bytes = fs::read(root.join(plan_path)).unwrap();
        assert_eq!(cell["plan_file_sha256"], sha256_hex(&plan_bytes));

        let plan: EvaluationPlanV1 = serde_json::from_slice(&plan_bytes).unwrap();
        plan.validate().unwrap();
        assert_eq!(plan.evaluation_id, evaluation_id);
        assert_eq!(plan.game_seeds, seeds);
        assert_eq!(plan.agents.len(), 2);
        assert_eq!(plan.handshake_timeout_ms, 5000);
        assert_eq!(plan.move_timeout_ms, 30000);
        assert_eq!(plan.shutdown_grace_ms, 2000);
        assert_eq!(expand_schedule(&plan).unwrap().len(), 64);
        assert_eq!(
            cell["plan_hash"],
            evaluation_plan_hash_v1(&plan).unwrap().as_str()
        );
        assert_eq!(
            cell["game_seeds_sha256"],
            bundle["matrix"]["game_seeds_sha256"]
        );
        assert_eq!(cell["game_seed_count"], 32);
        assert_eq!(cell["seat_rotations"], 2);
        assert_eq!(cell["scheduled_matches"], 64);

        let (candidate_id, checkpoint_path, checkpoint_hash) = if pair == "s2_vs_m07" {
            (
                "m27a-s2-candidate",
                "local-artifacts/m24-self-play-s2-v1/trained/checkpoint.pt",
                "c43e3c239124671c77bb7436dcf79e4fe6c71b66c8008186ac68621a8ad7d5a8",
            )
        } else {
            (
                "m27a-s1-candidate",
                "local-artifacts/m24-self-play-s1-v1/trained/checkpoint.pt",
                "1ae31dac9eec37485efdbb906109227dbe77424e78b31a906d158ac1d414f0b8",
            )
        };
        assert_eq!(plan.agents[0].id, candidate_id);
        assert_eq!(plan.agents[1].id, "m07-champion");
        assert_eq!(plan.agents[0].command.program.to_string_lossy(), "splendor");
        assert_eq!(plan.agents[1].command.program.to_string_lossy(), "splendor");
        assert_eq!(plan_arg(&plan, 0, "--checkpoint"), checkpoint_path);
        assert_eq!(plan_arg(&plan, 0, "--checkpoint-hash"), checkpoint_hash);
        assert_eq!(plan_arg(&plan, 0, "--simulations"), simulations.to_string());
        assert_eq!(plan_arg(&plan, 0, "--sample-seed"), "26000018");
        assert_eq!(plan_arg(&plan, 0, "--max-depth-turns"), "1");
        assert_eq!(plan_arg(&plan, 0, "--puct-exploration-milli"), "1500");
        assert_eq!(
            plan_arg(&plan, 0, "--catalog"),
            "apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json"
        );
        assert_eq!(plan_arg(&plan, 1, "--sample-seed"), "20260810");
        assert_eq!(plan_arg(&plan, 1, "--sample-count"), "4");
        assert_eq!(plan_arg(&plan, 1, "--max-depth-turns"), "1");
        assert_eq!(plan_arg(&plan, 1, "--max-nodes"), "2000");
    }

    let expected_cells: HashSet<(String, u64)> = expected_pairs
        .iter()
        .flat_map(|pair| {
            budgets
                .iter()
                .map(move |simulations| ((*pair).to_string(), *simulations))
        })
        .collect();
    assert_eq!(actual_cells, expected_cells);

    assert_eq!(config["execution_authorization"], "NOT_AUTHORIZED");
    assert_eq!(
        config["materialization_contract"]["bundle_path"],
        "benchmarks/m27a-search-budget-scaling-v1.bundle.json"
    );
}

#[derive(Clone, Copy)]
struct SyntheticBudget {
    budget: u64,
    center_bps: i64,
    complete: bool,
    aborted_matches: u32,
    candidate_faults: u32,
}

fn synthetic_budget(budget: u64, center_bps: i64) -> SyntheticBudget {
    SyntheticBudget {
        budget,
        center_bps,
        complete: true,
        aborted_matches: 0,
        candidate_faults: 0,
    }
}

fn synthetic_eligible(point: SyntheticBudget) -> bool {
    point.complete
        && point.aborted_matches == 0
        && point.candidate_faults == 0
        && point.center_bps >= 1000
}

fn select_first_stable_budget(points: &[SyntheticBudget]) -> Option<u64> {
    let mut start = 0;
    while start < points.len() {
        if !synthetic_eligible(points[start]) {
            start += 1;
            continue;
        }

        let mut end = start;
        let mut min_center = points[start].center_bps;
        let mut max_center = points[start].center_bps;
        while end + 1 < points.len() {
            let next = points[end + 1];
            if !synthetic_eligible(next) || (next.center_bps - points[end].center_bps).abs() >= 2000
            {
                break;
            }
            let next_min = min_center.min(next.center_bps);
            let next_max = max_center.max(next.center_bps);
            if next_max - next_min >= 2000 {
                break;
            }
            min_center = next_min;
            max_center = next_max;
            end += 1;
        }

        if end - start + 1 >= 3 {
            return Some(points[start].budget);
        }
        start = end + 1;
    }
    None
}

fn synthetic_curve(centers: &[i64]) -> Vec<SyntheticBudget> {
    [16u64, 24, 32, 48, 64, 96, 128]
        .into_iter()
        .zip(centers.iter().copied())
        .map(|(budget, center_bps)| synthetic_budget(budget, center_bps))
        .collect()
}

#[test]
fn m27a_operating_region_decision_semantics_are_executable() {
    assert_eq!(
        select_first_stable_budget(&synthetic_curve(&[500, 1200, 1500, 1800])),
        Some(24)
    );
    assert_eq!(
        select_first_stable_budget(&synthetic_curve(&[1000, 3000, 3000])),
        None,
        "strict adjacent movement boundary must reject exactly 2000 bps"
    );
    assert_eq!(
        select_first_stable_budget(&synthetic_curve(&[1000, 2500, 2999])),
        Some(16)
    );
    assert_eq!(
        select_first_stable_budget(&synthetic_curve(&[1000, 2500, 3000])),
        None,
        "strict region span boundary must reject exactly 2000 bps"
    );
    assert_eq!(
        select_first_stable_budget(&synthetic_curve(&[500, 700, 900, 1100, 1200])),
        None,
        "fewer than three consecutive eligible budgets is inconclusive"
    );
    assert_eq!(
        select_first_stable_budget(&synthetic_curve(&[4200, 6000, 8000])),
        None,
        "one-sided non-regression must not accept a continuing rise"
    );
}
