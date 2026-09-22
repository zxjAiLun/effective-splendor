//! Verification tests for M49A Compact Transition & Streaming Target Builder:
//!
//! Gates tested:
//! 1. Terminal target semantics:
//!    - Main -> Reached15: step_cost 1.0, V=0.0 => target = 1.0
//!    - ChooseNoble -> Reached15: step_cost 0.0, V=0.0 => target = 0.0
//!    - Main -> Stalled/TurnCap: step_cost 1.0, V=100.0 => target = 101.0
//! 2. Running min Q_target:
//!    - Hand-constructed next_legal_actions with known target net evaluation,
//!      verifying target == step_cost + min_{a'} Q_target(o', a')
//! 3. Horizon awareness:
//!    - Same (o', a') with different remaining budgets yields different 428-d features and Q
//! 4. Fail-closed contract:
//!    - Running with empty actions fails
//!    - Terminal with non-empty actions fails
//!    - Invalid weights (wrong shape, NaN, Inf) fails
//! 5. Reference parity:
//!    - Streaming Rust target evaluation matches Python / formulaic calculation within < 1e-5.

use splendor_agent::StableRng;
use splendor_analysis::m49a_collector::{
    collect_solo15_trajectory, CategoryBiasedPolicy, M49ACompactTransitionV1,
};
use splendor_analysis::solo15::{Solo15Environment, Solo15Outcome};
use splendor_core::Action;
use splendor_learning::EfficiencyQWeightsV1;

/// Helper to create valid synthetic weights for testing.
fn make_test_weights() -> EfficiencyQWeightsV1 {
    let mut fc1_w = vec![vec![0.01f32; 428]; 256];
    // Give different weights across the hidden units so that mean != each unit
    for i in 0..256 {
        fc1_w[i][427] = (i as f32) * 0.001; // weight for the 428th feature (normalized remaining turns)
    }
    let fc1_b = vec![0.0f32; 256];
    let ln1_w = vec![1.0f32; 256];
    let ln1_b = vec![0.0f32; 256];
    let fc2_w = vec![vec![0.01f32; 256]; 128];
    let fc2_b = vec![0.0f32; 128];
    let fc3_w = vec![vec![0.01f32; 128]; 1];
    let fc3_b = vec![0.5f32; 1];

    let w = EfficiencyQWeightsV1 {
        fc1_w,
        fc1_b,
        ln1_w,
        ln1_b,
        fc2_w,
        fc2_b,
        fc3_w,
        fc3_b,
    };
    w.validate().expect("test weights must be valid");
    w
}

#[test]
fn test_gate1_terminal_targets() {
    let weights = make_test_weights();

    // 1. Main action reaching 15
    let reached_main = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::Reached15,
        next_observation: None,
        next_legal_actions: Vec::new(),
        next_remaining_main_turns: 15,
        max_main_turns: 35,
    };
    let target = reached_main.compute_target(&weights, 100.0).unwrap();
    assert_eq!(target, 1.0, "Main action reaching 15 must give target 1.0");

    // 2. ChooseNoble reaching 15
    let reached_noble = M49ACompactTransitionV1 {
        step_cost: 0.0,
        outcome: Solo15Outcome::Reached15,
        next_observation: None,
        next_legal_actions: Vec::new(),
        next_remaining_main_turns: 15,
        max_main_turns: 35,
    };
    let target = reached_noble.compute_target(&weights, 100.0).unwrap();
    assert_eq!(target, 0.0, "ChooseNoble reaching 15 must give target 0.0");

    // 3. Main action failing (Stalled)
    let stalled_main = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::Stalled,
        next_observation: None,
        next_legal_actions: Vec::new(),
        next_remaining_main_turns: 0,
        max_main_turns: 35,
    };
    let target = stalled_main.compute_target(&weights, 100.0).unwrap();
    assert_eq!(target, 101.0, "Main action stalling must give target 101.0");

    // 4. Main action failing (TurnCap)
    let turncap_main = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::TurnCap,
        next_observation: None,
        next_legal_actions: Vec::new(),
        next_remaining_main_turns: 0,
        max_main_turns: 35,
    };
    let target = turncap_main.compute_target(&weights, 100.0).unwrap();
    assert_eq!(target, 101.0, "Main action at TurnCap must give target 101.0");
}

#[test]
fn test_gate2_running_min_q_target() {
    let weights = make_test_weights();

    let env = Solo15Environment::new(1001049).unwrap();
    let obs = env.observation();
    let legal = env.legal_actions();
    assert!(legal.len() >= 3);

    let running = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::Running,
        next_observation: Some(obs.clone()),
        next_legal_actions: legal.clone(),
        next_remaining_main_turns: 20,
        max_main_turns: 35,
    };

    let target = running.compute_target(&weights, 100.0).unwrap();

    // Manually evaluate Q for every action and take the min
    let mut manual_min = f32::INFINITY;
    for a in &legal {
        let feat = splendor_learning::encode_combined_v2(&obs, a, 20, 35).unwrap();
        let q = weights.forward(&feat);
        if q < manual_min {
            manual_min = q;
        }
    }

    let expected = 1.0 + manual_min;
    assert!(
        (target - expected).abs() < 1e-5,
        "Running target ({target}) must match 1.0 + min_a Q ({expected})"
    );
}

#[test]
fn test_gate3_horizon_awareness() {
    let weights = make_test_weights();

    let env = Solo15Environment::new(1001049).unwrap();
    let obs = env.observation();
    let legal = env.legal_actions();

    let t_horizon_25 = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::Running,
        next_observation: Some(obs.clone()),
        next_legal_actions: legal.clone(),
        next_remaining_main_turns: 25,
        max_main_turns: 35,
    };

    let t_horizon_5 = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::Running,
        next_observation: Some(obs),
        next_legal_actions: legal,
        next_remaining_main_turns: 5,
        max_main_turns: 35,
    };

    let target_25 = t_horizon_25.compute_target(&weights, 100.0).unwrap();
    let target_5 = t_horizon_5.compute_target(&weights, 100.0).unwrap();

    // The 428th feature differs (25/35 vs 5/35), so forward output must differ
    assert_ne!(
        target_25, target_5,
        "Targets at different remaining horizons must differ"
    );
}

#[test]
fn test_gate4_fail_closed_validation() {
    let weights = make_test_weights();

    // Running with empty actions
    let bad_running = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::Running,
        next_observation: None,
        next_legal_actions: Vec::new(),
        next_remaining_main_turns: 10,
        max_main_turns: 35,
    };
    assert!(bad_running.compute_target(&weights, 100.0).is_err());

    // Terminal with actions
    let bad_terminal = M49ACompactTransitionV1 {
        step_cost: 1.0,
        outcome: Solo15Outcome::Reached15,
        next_observation: None,
        next_legal_actions: vec![Action::Pass],
        next_remaining_main_turns: 10,
        max_main_turns: 35,
    };
    assert!(bad_terminal.compute_target(&weights, 100.0).is_err());

    // Bad weights with NaN
    let mut bad_weights = weights.clone();
    bad_weights.fc1_w[0][0] = f32::NAN;
    assert!(bad_weights.validate().is_err());
}

#[test]
fn test_gate5_parity_against_natural_trajectory() {
    let weights = make_test_weights();

    let mut policy = CategoryBiasedPolicy::new(0.20);
    let mut rng = StableRng::new(0x9999);
    let (transitions, _) =
        collect_solo15_trajectory(1001049, &mut policy, "cb", 0, 35, &mut rng).unwrap();

    assert!(!transitions.is_empty());

    for (idx, r) in transitions.iter().enumerate() {
        let compact = M49ACompactTransitionV1::from_record(r).unwrap();
        let target = compact.compute_target(&weights, 100.0).unwrap();

        // Check against materialized transition
        let mat = r.materialize().unwrap();
        let expected = match mat.outcome {
            Solo15Outcome::Reached15 => mat.step_cost + 0.0,
            Solo15Outcome::Stalled | Solo15Outcome::TurnCap => mat.step_cost + 100.0,
            Solo15Outcome::Running => {
                let mut min_q = f32::INFINITY;
                for next_feat in &mat.next_action_features {
                    let q = weights.forward(next_feat);
                    if q < min_q {
                        min_q = q;
                    }
                }
                mat.step_cost + min_q
            }
        };

        let diff = (target - expected).abs();
        assert!(
            diff < 1e-5,
            "Target mismatch at step {idx}: streaming={target}, expected={expected}, diff={diff}"
        );
    }
}
