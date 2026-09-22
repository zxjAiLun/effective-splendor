use super::*;

fn row(iteration: u32, success: usize, mean: f64) -> CheckpointRow {
    CheckpointRow {
        iteration,
        weights_path: format!("weights_iter{iteration:03}.json").into(),
        weights_sha256: "a".repeat(64),
        success_count: success,
        failures: 64 - success,
        j_val: (success as f64 * mean + (64 - success) as f64 * 101.0) / 64.0,
        successful_mean_turns: (success > 0).then_some(mean),
    }
}

fn rows() -> Vec<CheckpointRow> {
    SCHEDULE.iter().map(|&i| row(i, 55, 33.0)).collect()
}

fn reports() -> EvaluationReports {
    EvaluationReports {
        evaluation_contract: EVALUATION_CONTRACT.into(),
        checkpoint_schedule: SCHEDULE.to_vec(),
        validation_seeds: validation_seeds_v1(),
        max_main_turns: 100,
        evaluated: rows(),
    }
}

#[test]
fn success_first_preserves_c1_success_vs_j_val_divergence() {
    let mut rs = rows();
    rs[2] = row(30, 58, 1817.0 / 58.0);
    rs[4] = row(50, 59, 2072.0 / 59.0);
    assert_eq!(rs[2].j_val, 37.859375);
    assert_eq!(rs[4].j_val, 40.265625);
    assert_eq!(select_checkpoint_v1(&rs).unwrap().iteration, 50);
    // Negative control: a J_val-first comparator would select the wrong checkpoint.
    assert_eq!(
        rs.iter()
            .min_by(|a, b| a.j_val.total_cmp(&b.j_val))
            .unwrap()
            .iteration,
        30
    );
}

#[test]
fn four_lexicographic_levels_are_ordered_not_weighted() {
    let a = row(20, 59, 40.0);
    let mut b = row(10, 58, 1.0);
    assert_eq!(compare_rows(&a, &b), Ordering::Less); // success > everything
    b = row(10, 59, 41.0);
    assert_eq!(compare_rows(&a, &b), Ordering::Less); // J_val > earlier

    // With exact metrics on this cohort, equal success + J implies equal mean.
    // Test the specified tertiary comparator synthetically, not as a valid report.
    b.j_val = a.j_val;
    assert_eq!(compare_rows(&a, &b), Ordering::Less); // mean > earlier
    b.successful_mean_turns = a.successful_mean_turns;
    assert_eq!(compare_rows(&a, &b), Ordering::Greater); // earliest iteration
}

#[test]
fn input_order_does_not_change_choice_or_report_bytes() {
    let expected = serde_json::to_vec(&make_report(reports()).unwrap()).unwrap();
    let mut r = reports();
    for _ in 0..8 {
        r.evaluated.rotate_left(1);
        assert_eq!(
            serde_json::to_vec(&make_report(r.clone()).unwrap()).unwrap(),
            expected
        );
    }
    r.evaluated.reverse();
    assert_eq!(
        serde_json::to_vec(&make_report(r).unwrap()).unwrap(),
        expected
    );
}

#[test]
fn all_failure_cohort_uses_null_mean_and_earliest_iteration() {
    let rs: Vec<_> = SCHEDULE.iter().map(|&i| row(i, 0, 0.0)).collect();
    let chosen = select_checkpoint_v1(&rs).unwrap();
    assert_eq!(chosen.iteration, 10);
    assert_eq!(chosen.j_val, 101.0);
    assert_eq!(chosen.successful_mean_turns, None);
    assert_eq!(
        serde_json::to_value(chosen).unwrap()["successful_mean_turns"],
        serde_json::Value::Null
    );
}

#[test]
fn missing_duplicate_or_unscheduled_checkpoint_is_fatal() {
    assert!(select_checkpoint_v1(&[]).is_err());
    assert!(select_checkpoint_v1(&rows()[..7]).is_err());
    let mut rs = rows();
    rs[7].iteration = 70;
    assert!(select_checkpoint_v1(&rs).is_err());
    rs[7].iteration = 79;
    assert!(select_checkpoint_v1(&rs).is_err());
    rs.push(row(80, 64, 30.0));
    assert!(select_checkpoint_v1(&rs).is_err());
}

#[test]
fn corrupt_metrics_and_identities_are_rejected() {
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -1.0, 102.0] {
        let mut rs = rows();
        rs[0].j_val = bad;
        assert!(select_checkpoint_v1(&rs).is_err());
        rs = rows();
        rs[0].successful_mean_turns = Some(bad);
        assert!(select_checkpoint_v1(&rs).is_err());
    }
    let mut rs = rows();
    rs[0].success_count = 65;
    assert!(select_checkpoint_v1(&rs).is_err());
    rs = rows();
    rs[0].failures += 1;
    assert!(select_checkpoint_v1(&rs).is_err());
    rs = rows();
    rs[0].successful_mean_turns = None;
    assert!(select_checkpoint_v1(&rs).is_err());
    rs = rows();
    rs[0] = row(10, 0, 0.0);
    rs[0].successful_mean_turns = Some(0.0);
    assert!(select_checkpoint_v1(&rs).is_err());
    rs = rows();
    rs[0].j_val += 0.001;
    assert!(select_checkpoint_v1(&rs).is_err());
    rs = rows();
    rs[0].weights_path = "".into();
    assert!(select_checkpoint_v1(&rs).is_err());
    rs = rows();
    rs[0].weights_sha256 = "x".repeat(64);
    assert!(select_checkpoint_v1(&rs).is_err());
}

#[test]
fn incompatible_report_contract_or_cohort_is_rejected() {
    let mut r = reports();
    r.evaluation_contract = "other".into();
    assert!(make_report(r).is_err());
    let mut r = reports();
    r.validation_seeds[0] += 1;
    assert!(make_report(r).is_err());
    let mut r = reports();
    r.max_main_turns = 35;
    assert!(make_report(r).is_err());
    let mut r = reports();
    r.checkpoint_schedule.push(51);
    assert!(make_report(r).is_err());
}

#[test]
fn cli_requires_exclusive_input_output_and_frozen_schedule() {
    let parse = |s: &str| parse_args(&s.split_whitespace().map(String::from).collect::<Vec<_>>());
    assert!(parse("--reports-json r.json --out-json o.json").is_ok());
    assert!(parse("--checkpoint-dir c --schedule 10,20,30,40,50,60,70,80 --out-json o").is_ok());
    for s in [
        "",
        "--checkpoint-dir c",
        "--checkpoint-dir --out-json o",
        "--out-json o",
        "--reports-json r --checkpoint-dir c --out-json o",
        "--reports-json r --reports-json r2 --out-json o",
        "--reports-json r --out-json o --out-json o2",
        "--reports-json r --out-json o --unknown x",
        "--checkpoint-dir c --schedule 50 --out-json o",
        "--checkpoint-dir c --schedule 10,20,30,40,50,60,70,80, --out-json o",
        "--checkpoint-dir c --schedule 10,,20,30,40,50,60,70,80 --out-json o",
        "--checkpoint-dir c --schedule 10,20,30,40,50,60,70,70 --out-json o",
        "--checkpoint-dir c --schedule 10,20,30,40,50,60,70,nope --out-json o",
    ] {
        assert!(parse(s).is_err(), "accepted invalid args: {s}");
    }
}
