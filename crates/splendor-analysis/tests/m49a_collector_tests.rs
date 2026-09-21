use splendor_agent::{HeuristicAgentPolicy, RandomAgentPolicy, StableRng};
use splendor_analysis::m49a_collector::{
    assert_seed_partitions_disjoint, canonical_m49s_seeds, collect_solo15_trajectory,
    train_seeds_v1, validation_seeds_v1, CategoryBiasedPolicy, CoverageDiagnosticReport,
};
use splendor_analysis::solo15::{Solo15Outcome, SOLO15_CONTRACT_ID_V1};
use splendor_core::Action;

#[test]
fn test_i_seed_01_partitions_disjointness_and_negative_control() {
    let train = train_seeds_v1();
    let val = validation_seeds_v1();
    let canonical = canonical_m49s_seeds();

    assert_eq!(train.len(), 256);
    assert_eq!(val.len(), 64);
    assert_eq!(canonical.len(), 64);

    // Assert that real partitions pass
    assert_seed_partitions_disjoint(&train, &val, &canonical);

    // Negative control: artificially injecting an overlap between train and val
    let mut bad_val = val.clone();
    bad_val[0] = train[0];
    let result = std::panic::catch_unwind(|| {
        assert_seed_partitions_disjoint(&train, &bad_val, &canonical);
    });
    assert!(
        result.is_err(),
        "I-SEED-01 assertion MUST catch seed partition overlap"
    );
}

#[test]
fn test_transition_record_schema_and_invariants() {
    let mut rng = StableRng::new(0x1234_5678);
    let mut policy = HeuristicAgentPolicy::new();

    // Collect 1 trajectory on training seed
    let (transitions, summary) = collect_solo15_trajectory(
        train_seeds_v1()[0],
        &mut policy,
        "heuristic_v1",
        0,
        100,
        &mut rng,
    )
    .expect("collect trajectory");

    assert!(!transitions.is_empty());
    assert_eq!(summary.reached_15, true);

    // Every recorded transition in the natural trajectory must be strictly valid
    for (i, t) in transitions.iter().enumerate() {
        t.validate().unwrap_or_else(|e| {
            panic!("transition {i} failed validation: {e}");
        });
        assert_eq!(t.contract_id, SOLO15_CONTRACT_ID_V1);
        assert_eq!(t.provenance.env_seed, train_seeds_v1()[0]);
        assert_eq!(t.provenance.behavior_policy, "heuristic_v1");

        // Feature vector length must be exactly 427
        let feat = t.extract_input_features().expect("features");
        assert_eq!(feat.len(), 427);
    }

    // Check last transition terminal outcome
    let last = transitions.last().unwrap();
    assert_eq!(last.outcome, Solo15Outcome::Reached15);
    assert!(last.next_legal_actions.is_empty());

    // Negative control 1: Running state with empty next_legal_actions must fail
    let mut bad_running = transitions[0].clone();
    bad_running.outcome = Solo15Outcome::Running;
    bad_running.next_legal_actions.clear();
    assert!(bad_running.validate().is_err());

    // Negative control 2: Terminal state with non-empty next_legal_actions must fail
    let mut bad_terminal = last.clone();
    bad_terminal.next_legal_actions.push(Action::Pass);
    assert!(bad_terminal.validate().is_err());

    // Negative control 3: Main action with wrong step_cost must fail
    let mut bad_cost = transitions[0].clone();
    bad_cost.step_cost = 0.0;
    assert!(bad_cost.validate().is_err());
}

#[test]
fn test_zero_leakage_feature_extraction() {
    let mut rng = StableRng::new(0x1234_5678);
    let mut policy = HeuristicAgentPolicy::new();
    let (transitions, _) = collect_solo15_trajectory(
        train_seeds_v1()[1],
        &mut policy,
        "heuristic_v1",
        0,
        100,
        &mut rng,
    )
    .expect("collect");

    let record = &transitions[0];
    let original_features = record.extract_input_features().unwrap();

    // 1. Mutate provenance.env_seed
    let mut tampered = record.clone();
    tampered.provenance.env_seed = 999_999_999;
    assert_eq!(
        tampered.extract_input_features().unwrap(),
        original_features,
        "provenance.env_seed MUST NOT enter model input features"
    );

    // 2. Mutate provenance.behavior_policy
    tampered.provenance.behavior_policy = "malicious_policy".to_string();
    assert_eq!(
        tampered.extract_input_features().unwrap(),
        original_features,
        "provenance.behavior_policy MUST NOT enter model input features"
    );

    // 3. Mutate trajectory_id
    tampered.trajectory_id = "completely_different_id".to_string();
    assert_eq!(
        tampered.extract_input_features().unwrap(),
        original_features,
        "trajectory_id MUST NOT enter model input features"
    );

    // 4. Mutate next_observation (target-side chance outcome)
    tampered.next_observation.public.bank.gold = 0;
    assert_eq!(
        tampered.extract_input_features().unwrap(),
        original_features,
        "next_observation MUST NOT enter Q(o, a) input features"
    );
}

#[test]
fn test_behavior_coverage_diagnostic_report() {
    let train_seeds = &train_seeds_v1()[..32]; // First 32 training seeds
    println!("\n==========================================================================");
    println!("M49A BEHAVIOR COVERAGE DIAGNOSTIC REPORT (32 TRAINING SEEDS PER SOURCE)");
    println!("==========================================================================");

    // 1. Heuristic Coverage
    let mut h_trans = Vec::new();
    let mut h_sums = Vec::new();
    for (i, &s) in train_seeds.iter().enumerate() {
        let mut policy = HeuristicAgentPolicy::new();
        let mut rng = StableRng::new(0x1000_0000 + i as u64);
        let (t, sum) = collect_solo15_trajectory(s, &mut policy, "heuristic", 0, 100, &mut rng)
            .expect("heuristic collect");
        h_trans.extend(t);
        h_sums.push(sum);
    }
    let h_report = CoverageDiagnosticReport::build(&h_trans, &h_sums);
    print_coverage_report("HEURISTIC (Warm-Start)", &h_report);

    // 2. Category-Biased Exploration (eps = 0.20)
    let mut cb_trans = Vec::new();
    let mut cb_sums = Vec::new();
    for (i, &s) in train_seeds.iter().enumerate() {
        let mut policy = CategoryBiasedPolicy::new(0.20);
        let mut rng = StableRng::new(0x2000_0000 + i as u64);
        let (t, sum) =
            collect_solo15_trajectory(s, &mut policy, "category_biased_eps0.2", 0, 100, &mut rng)
                .expect("category biased collect");
        cb_trans.extend(t);
        cb_sums.push(sum);
    }
    let cb_report = CoverageDiagnosticReport::build(&cb_trans, &cb_sums);
    print_coverage_report("CATEGORY-BIASED EXPLORATION (eps = 0.20)", &cb_report);

    // 3. Uniform Random Exploration
    let mut r_trans = Vec::new();
    let mut r_sums = Vec::new();
    for (i, &s) in train_seeds.iter().enumerate() {
        let mut policy = RandomAgentPolicy::new();
        let mut rng = StableRng::new(0x3000_0000 + i as u64);
        let (t, sum) = collect_solo15_trajectory(s, &mut policy, "random", 0, 100, &mut rng)
            .expect("random collect");
        r_trans.extend(t);
        r_sums.push(sum);
    }
    let r_report = CoverageDiagnosticReport::build(&r_trans, &r_sums);
    print_coverage_report("UNIFORM RANDOM EXPLORATION", &r_report);
    println!("==========================================================================\n");

    // Basic assertions
    assert_eq!(h_report.total_trajectories, 32);
    assert_eq!(cb_report.total_trajectories, 32);
    assert_eq!(r_report.total_trajectories, 32);

    // Heuristic completes 32/32
    assert_eq!(h_report.reached_15_count, 32);
    assert_eq!(h_report.success_rate, 1.0);

    // Random completes 0/32
    assert_eq!(r_report.reached_15_count, 0);
    assert_eq!(r_report.turn_cap_count, 32);
}

fn print_coverage_report(title: &str, r: &CoverageDiagnosticReport) {
    println!("\n--- [{title}] ---");
    println!(
        "Trajectories: {}, Transitions: {}, Success Rate: {:.1}% (Reached15: {}, Stalled: {}, TurnCap: {})",
        r.total_trajectories,
        r.total_transitions,
        r.success_rate * 100.0,
        r.reached_15_count,
        r.stalled_count,
        r.turn_cap_count
    );
    if let Some(ref m) = r.main_turns_distribution {
        println!(
            "Main Turns (successful): Mean: {:.2}, Median: {:.1}, P75: {:.1}, P90: {:.1}, Min: {:.0}, Max: {:.0}",
            m.mean, m.median, m.p75, m.p90, m.min, m.max
        );
    } else {
        println!("Main Turns (successful): N/A (0 trajectories reached 15)");
    }
    println!(
        "Purchased Cards:         Mean: {:.2}, Median: {:.1}",
        r.purchased_cards_distribution.mean, r.purchased_cards_distribution.median
    );
    println!("Action Kinds:            {:?}", r.action_kinds);
    println!("VP Buckets:              {:?}", r.vp_buckets);
    println!(
        "Legal Actions Count:     Mean: {:.1}, Median: {:.1}, Min: {:.0}, Max: {:.0}",
        r.legal_actions_distribution.mean,
        r.legal_actions_distribution.median,
        r.legal_actions_distribution.min,
        r.legal_actions_distribution.max
    );
}
