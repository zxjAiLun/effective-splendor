use splendor_agent::{HeuristicAgentPolicy, RandomAgentPolicy};
use splendor_analysis::solo15::{
    Solo15CohortReport, Solo15Environment, Solo15Outcome, DEFAULT_MAX_MAIN_TURNS,
    SOLO15_CONTRACT_ID_V1,
};
use splendor_core::{Action, Phase};

#[test]
fn test_solo15_contract_and_initial_setup() {
    let env = Solo15Environment::new(1049).expect("valid env");
    assert_eq!(env.contract_id(), SOLO15_CONTRACT_ID_V1);
    assert_eq!(env.seed(), 1049);
    assert_eq!(env.main_turns(), 0);
    assert_eq!(env.decision_plies(), 0);
    assert_eq!(env.max_main_turns(), DEFAULT_MAX_MAIN_TURNS);
    assert_eq!(env.outcome(), Solo15Outcome::Running);
    assert_eq!(env.is_terminal(), false);
    assert_eq!(env.phase(), Phase::Main);

    // Verify observation information boundary: public board has deck_counts
    let obs = env.observation();
    assert_eq!(obs.public.deck_counts.len(), 3);
    // 2-player resource supply: 4 colored tokens per color, 5 gold tokens, 3 nobles dealt
    assert_eq!(obs.public.bank.gold, 5);
    assert_eq!(obs.public.bank.white, 4);
    assert_eq!(obs.public.bank.blue, 4);
    assert_eq!(obs.public.bank.green, 4);
    assert_eq!(obs.public.bank.red, 4);
    assert_eq!(obs.public.bank.black, 4);
    assert_eq!(obs.public.nobles.len(), 3);

    // Player 0 starts with 0 prestige and 0 tokens
    assert_eq!(obs.public.players[0].prestige, 0);
    assert_eq!(obs.public.players[0].tokens.total(), 0);
    assert_eq!(obs.private.reserved.len(), 0);
}

#[test]
fn test_solo15_turn_cap_censoring() {
    // Set max_main_turns to 3
    let mut env = Solo15Environment::with_max_main_turns(1049, 3).expect("valid env");

    for turn in 1..=3 {
        assert_eq!(env.is_terminal(), false);
        let legal = env.legal_actions();
        assert!(!legal.is_empty());
        let step = env.step(legal[0]).expect("valid step");
        assert_eq!(step.step_cost, 1);
        assert_eq!(step.main_turns, turn);
        assert_eq!(step.decision_plies, turn);
    }

    // After 3 main turns, player prestige is < 15, so outcome must be TurnCap
    assert_eq!(env.outcome(), Solo15Outcome::TurnCap);
    assert_eq!(env.is_terminal(), true);

    let summary = env.summary();
    assert_eq!(summary.outcome, Solo15Outcome::TurnCap);
    assert_eq!(summary.reached_15, false);
    assert_eq!(summary.main_turns_to_15, None);
    assert_eq!(summary.decision_plies_to_15, 3);
    assert_eq!(summary.max_main_turns, 3);

    // Stepping after terminal must fail with GameOver
    let extra = env.step(Action::Pass);
    assert!(extra.is_err());
}

#[test]
fn test_solo15_canonical_64_seed_paired_baseline() {
    // 64 fixed deterministic seeds
    let seeds: Vec<u64> = (1..=64).map(|i| i * 1000 + 49).collect();
    let max_main_turns = 100;

    println!("\n==========================================================================");
    println!("M49S CANONICAL PAIRED BASELINE (64 SEEDS, CAP = 100 MAIN TURNS)");
    println!("Contract: {}", SOLO15_CONTRACT_ID_V1);
    println!("==========================================================================");

    // 1. Evaluate HeuristicAgentPolicy
    let heuristic_report = Solo15CohortReport::evaluate(
        "heuristic_v1",
        HeuristicAgentPolicy::new,
        &seeds,
        max_main_turns,
    )
    .expect("heuristic cohort evaluation");

    // 2. Evaluate RandomAgentPolicy
    let random_report = Solo15CohortReport::evaluate(
        "random_v1",
        RandomAgentPolicy::new,
        &seeds,
        max_main_turns,
    )
    .expect("random cohort evaluation");

    println!("\n[1] HEURISTIC AGENT RESULTS (N = {})", seeds.len());
    println!(
        "Success Rate:    {}/{} ({:.1}%)",
        heuristic_report.success_count,
        heuristic_report.total_seeds,
        heuristic_report.success_rate * 100.0
    );
    println!(
        "Terminal States: Reached15={}, Stalled={}, TurnCap={}",
        heuristic_report.success_count,
        heuristic_report.stalled_count,
        heuristic_report.turn_cap_count
    );
    if let Some(ref dist) = heuristic_report.main_turns {
        println!(
            "Main Turns:      Mean: {:.2}, Median: {:.1}, P75: {:.1}, P90: {:.1}, Min: {:.0}, Max: {:.0}",
            dist.mean, dist.median, dist.p75, dist.p90, dist.min, dist.max
        );
    }
    if let Some(ref dist) = heuristic_report.decision_plies {
        println!(
            "Decision Plies:  Mean: {:.2}, Median: {:.1}, P75: {:.1}, P90: {:.1}, Min: {:.0}, Max: {:.0}",
            dist.mean, dist.median, dist.p75, dist.p90, dist.min, dist.max
        );
    }
    println!(
        "Purchased Cards: Mean: {:.2}, Median: {:.1}",
        heuristic_report.purchased_cards.mean, heuristic_report.purchased_cards.median
    );
    println!(
        "Final Prestige:  Mean: {:.2}, Median: {:.1}",
        heuristic_report.final_prestige.mean, heuristic_report.final_prestige.median
    );
    println!(
        "Nobles Taken:    Mean: {:.2}, Median: {:.1}",
        heuristic_report.nobles_taken.mean, heuristic_report.nobles_taken.median
    );

    println!("\n[2] RANDOM AGENT RESULTS (N = {})", seeds.len());
    println!(
        "Success Rate:    {}/{} ({:.1}%)",
        random_report.success_count,
        random_report.total_seeds,
        random_report.success_rate * 100.0
    );
    println!(
        "Terminal States: Reached15={}, Stalled={}, TurnCap={}",
        random_report.success_count,
        random_report.stalled_count,
        random_report.turn_cap_count
    );
    if let Some(ref dist) = random_report.main_turns {
        println!(
            "Main Turns:      Mean: {:.2}, Median: {:.1}, P75: {:.1}, P90: {:.1}, Min: {:.0}, Max: {:.0}",
            dist.mean, dist.median, dist.p75, dist.p90, dist.min, dist.max
        );
    } else {
        println!("Main Turns:      N/A (0/64 completed; censored at 100 main turns)");
    }
    println!(
        "Purchased Cards: Mean: {:.2}, Median: {:.1}",
        random_report.purchased_cards.mean, random_report.purchased_cards.median
    );
    println!(
        "Final Prestige:  Mean: {:.2}, Median: {:.1}",
        random_report.final_prestige.mean, random_report.final_prestige.median
    );
    println!(
        "Nobles Taken:    Mean: {:.2}, Median: {:.1}",
        random_report.nobles_taken.mean, random_report.nobles_taken.median
    );
    println!("==========================================================================\n");

    // Formal assertions on baseline properties
    assert_eq!(heuristic_report.total_seeds, 64);
    assert_eq!(heuristic_report.success_count, 64);
    assert_eq!(heuristic_report.success_rate, 1.0);
    assert_eq!(heuristic_report.stalled_count, 0);
    assert_eq!(heuristic_report.turn_cap_count, 0);

    let h_dist = heuristic_report.main_turns.unwrap();
    // Heuristic in solo 2P supply typically solves in 24..36 turns
    assert!(h_dist.min >= 20.0);
    assert!(h_dist.max <= 40.0);
    assert!(h_dist.mean >= 25.0 && h_dist.mean <= 32.0);

    // Random on 64 seeds never reaches 15 in 100 turns
    assert_eq!(random_report.total_seeds, 64);
    assert_eq!(random_report.success_count, 0);
    assert_eq!(random_report.success_rate, 0.0);
    assert_eq!(random_report.turn_cap_count, 64);
    assert!(random_report.main_turns.is_none());
    assert!(random_report.final_prestige.mean <= 5.0);
}
