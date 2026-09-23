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
        training_run_id: None,
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
    let mut r = reports();
    r.training_run_id = Some("  ".into());
    assert!(make_report(r).is_err());
}

#[test]
fn training_run_id_round_trips_and_is_optional() {
    // Bound report: the run id survives selection reporting and replay.
    let mut r = reports();
    r.training_run_id = Some("m49a-c2-polyak005-v1".into());
    let report = make_report(r).unwrap();
    let json = serde_json::to_string(&report).unwrap();
    assert!(json.contains("m49a-c2-polyak005-v1"));
    let replayed: EvaluationReports = serde_json::from_str(&json).unwrap();
    assert_eq!(replay_polyak_id(&replayed), "m49a-c2-polyak005-v1");
    // Legacy unbound report (field omitted entirely) still parses.
    let legacy = serde_json::json!({
        "evaluation_contract": EVALUATION_CONTRACT,
        "checkpoint_schedule": SCHEDULE,
        "validation_seeds": validation_seeds_v1(),
        "max_main_turns": 100,
        "evaluated": rows(),
    });
    let parsed: EvaluationReports = serde_json::from_value(legacy).unwrap();
    assert_eq!(parsed.training_run_id, None);
    let out = serde_json::to_string(&make_report(parsed).unwrap()).unwrap();
    assert!(!out.contains("training_run_id"));
}

fn replay_polyak_id(r: &EvaluationReports) -> String {
    r.training_run_id.clone().unwrap()
}

#[test]
fn training_manifest_binding() {
    let dir = std::env::temp_dir().join(format!("m49a-manifest-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let shas: BTreeMap<String, String> = SCHEDULE
        .iter()
        .map(|it| (format!("weights_iter{it:03}.json"), "a".repeat(64)))
        .collect();

    // Missing manifest -> legacy unbound, allowed.
    assert_eq!(bind_training_manifest(&dir, &shas).unwrap(), None);

    let input_shas: BTreeMap<String, String> = [
        "train/current_x.f32",
        "train/step_costs.f32",
        "train/outcomes.u8",
        "train/compact_transitions.jsonl",
        "val/current_x.f32",
        "val/step_costs.f32",
        "val/outcomes.u8",
        "val/compact_transitions.jsonl",
    ]
    .into_iter()
    .map(|name| (name.to_string(), "c".repeat(64)))
    .collect();

    // Matching manifest -> run id returned.
    let manifest = serde_json::json!({
        "run_id": "c2",
        "training_contract": {"target_update": "polyak", "polyak_tau": 0.05},
        "d2_input_sha256": input_shas,
        "checkpoints": shas
    });
    fs::write(
        dir.join("training_manifest.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();
    assert_eq!(
        bind_training_manifest(&dir, &shas).unwrap().as_deref(),
        Some("c2")
    );

    // Missing one D2 identity component -> fatal.
    let mut incomplete: serde_json::Value =
        serde_json::from_slice(&fs::read(dir.join("training_manifest.json")).unwrap()).unwrap();
    incomplete["d2_input_sha256"]
        .as_object_mut()
        .unwrap()
        .remove("val/outcomes.u8");
    fs::write(
        dir.join("training_manifest.json"),
        serde_json::to_vec(&incomplete).unwrap(),
    )
    .unwrap();
    assert!(bind_training_manifest(&dir, &shas).is_err());

    fs::write(
        dir.join("training_manifest.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();

    // Drifted checkpoint -> fatal, no selection can mis-bind.
    let mut drifted = shas.clone();
    *drifted.get_mut("weights_iter050.json").unwrap() = "b".repeat(64);
    assert!(bind_training_manifest(&dir, &drifted).is_err());
    let mut extra = shas.clone();
    extra.insert("unexpected.json".into(), "a".repeat(64));
    assert!(bind_training_manifest(&dir, &extra).is_err());

    // Manifest missing a checkpoint -> fatal.
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&fs::read(dir.join("training_manifest.json")).unwrap()).unwrap();
    manifest["checkpoints"]
        .as_object_mut()
        .unwrap()
        .remove("weights_iter080.json");
    fs::write(
        dir.join("training_manifest.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();
    assert!(bind_training_manifest(&dir, &shas).is_err());

    // Malformed manifest JSON / empty run_id -> fatal.
    fs::write(dir.join("training_manifest.json"), b"not json").unwrap();
    assert!(bind_training_manifest(&dir, &shas).is_err());
    fs::write(
        dir.join("training_manifest.json"),
        serde_json::to_vec(&serde_json::json!({
            "run_id":"",
            "training_contract":{"target_update":"polyak"},
            "d2_input_sha256":input_shas,
            "checkpoints":shas
        }))
        .unwrap(),
    )
    .unwrap();
    assert!(bind_training_manifest(&dir, &shas).is_err());

    let _ = fs::remove_dir_all(&dir);
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
