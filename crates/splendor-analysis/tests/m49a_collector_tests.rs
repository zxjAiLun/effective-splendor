use splendor_agent::{
    AgentPolicy, DecisionContext, HeuristicAgentPolicy, RandomAgentPolicy, StableRng,
};
use splendor_analysis::m49a_collector::{
    assert_seed_partitions_disjoint, canonical_m49s_seeds, collect_solo15_trajectory,
    train_seeds_v1, validation_seeds_v1, CategoryBiasedPolicy, CoverageDiagnosticReport,
};
use splendor_analysis::solo15::{Solo15Outcome, SOLO15_CONTRACT_ID_V1};
use splendor_core::{Action, Phase};

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
    assert!(bad_running.materialize().is_err(), "materialize() MUST fail-closed when Running has empty next_legal_actions");

    // Negative control 2: Terminal state with non-empty next_legal_actions must fail
    let mut bad_terminal = last.clone();
    bad_terminal.next_legal_actions.push(Action::Pass);
    assert!(bad_terminal.validate().is_err());
    assert!(bad_terminal.materialize().is_err(), "materialize() MUST fail-closed when terminal has non-empty next_legal_actions");

    // Negative control 3: Main action with wrong step_cost must fail
    let mut bad_cost = transitions[0].clone();
    bad_cost.step_cost = 0.0;
    assert!(bad_cost.validate().is_err());
    assert!(bad_cost.materialize().is_err(), "materialize() MUST fail-closed when Main action has wrong step_cost");
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

    // 5. Materialization test: MaterializedTransitionV1
    let mat = record.materialize().expect("materialize");
    assert_eq!(mat.input_features.len(), 427);
    assert_eq!(mat.input_features, original_features);
    assert_eq!(mat.step_cost, record.step_cost);
    assert_eq!(mat.outcome, record.outcome);
    assert_eq!(
        mat.next_action_features.len(),
        record.next_legal_actions.len()
    );
    for next_f in &mat.next_action_features {
        assert_eq!(next_f.len(), 427);
    }

    // Mutating provenance MUST NOT change materialized tensors
    let mut mat_tampered_prov = record.clone();
    mat_tampered_prov.provenance.env_seed = 888_888;
    let mat_after_prov = mat_tampered_prov.materialize().expect("materialize");
    assert_eq!(mat_after_prov.input_features, mat.input_features);
    assert_eq!(
        mat_after_prov.next_action_features,
        mat.next_action_features
    );

    // Mutating next_observation MUST change next_action_features but NOT input_features
    let mut mat_tampered_next = record.clone();
    mat_tampered_next.next_observation.public.bank.gold = 0;
    let mat_after_next = mat_tampered_next.materialize().expect("materialize");
    assert_eq!(mat_after_next.input_features, mat.input_features);
    assert_ne!(
        mat_after_next.next_action_features,
        mat.next_action_features
    );

    // Terminal record must have empty next_action_features
    let mut terminal_record = record.clone();
    terminal_record.outcome = Solo15Outcome::Reached15;
    terminal_record.next_legal_actions.clear();
    let mat_term = terminal_record.materialize().expect("materialize terminal");
    assert!(mat_term.next_action_features.is_empty());
}

/// A policy that delegates Main actions to Heuristic but deliberately selects
/// `legal[1]` whenever multiple nobles are available in `Phase::ChooseNoble`.
struct SecondNoblePolicy {
    heuristic: HeuristicAgentPolicy,
}

impl SecondNoblePolicy {
    fn new() -> Self {
        Self {
            heuristic: HeuristicAgentPolicy::new(),
        }
    }
}

impl AgentPolicy for SecondNoblePolicy {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let legal = context.legal_actions;
        if matches!(context.observation.public.phase, Phase::ChooseNoble) && legal.len() >= 2 {
            Ok(legal[1])
        } else {
            self.heuristic.choose_action(context)
        }
    }
}

#[test]
fn test_collector_obeys_policy_choice_in_choose_noble_phase() {
    // Seed 1004049 is known to trigger Phase::ChooseNoble with 2 qualified nobles: [NobleId(7), NobleId(8)]
    let seed = 1004049;

    // Run 1: Heuristic policy picks legal[0] (NobleId(7))
    let mut rng_default = StableRng::new(0x1234_5678);
    let mut default_policy = HeuristicAgentPolicy::new();
    let (default_transitions, _) = collect_solo15_trajectory(
        seed,
        &mut default_policy,
        "heuristic",
        0,
        100,
        &mut rng_default,
    )
    .expect("collect default");

    let default_noble_step = default_transitions
        .iter()
        .find(|t| matches!(t.action, Action::ChooseNoble { .. }))
        .expect("seed 1004049 must produce a ChooseNoble transition");

    assert_eq!(
        default_noble_step.action,
        Action::ChooseNoble {
            noble: splendor_catalog::NobleId(7),
        },
        "default policy should select legal[0] (Noble 7)"
    );

    // Run 2: SecondNoblePolicy deliberately picks legal[1] (NobleId(8))
    let mut rng_second = StableRng::new(0x1234_5678);
    let mut second_policy = SecondNoblePolicy::new();
    let (second_transitions, _) = collect_solo15_trajectory(
        seed,
        &mut second_policy,
        "second_noble",
        0,
        100,
        &mut rng_second,
    )
    .expect("collect second_noble");

    let second_noble_step = second_transitions
        .iter()
        .find(|t| matches!(t.action, Action::ChooseNoble { .. }))
        .expect("seed 1004049 must produce a ChooseNoble transition");

    assert_eq!(
        second_noble_step.action,
        Action::ChooseNoble {
            noble: splendor_catalog::NobleId(8),
        },
        "collector MUST record policy's choice of legal[1] (Noble 8) into the transition record"
    );
    assert_eq!(second_noble_step.step_cost, 0.0);
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
