use serde_json::{json, Value};
use splendor_replay::{record_random_game, verify_replay, ReplayError, ReplayV1};

fn base_value() -> Value {
    let (_state, replay) = record_random_game(2, 42, 1001).unwrap();
    serde_json::to_value(&replay).unwrap()
}

fn parse(value: &Value) -> Result<ReplayV1, serde_json::Error> {
    serde_json::from_value(value.clone())
}

fn parse_ok(value: &Value) -> ReplayV1 {
    parse(value).expect("value should parse into ReplayV1")
}

fn verify_err(value: &Value) -> ReplayError {
    let replay = parse_ok(value);
    verify_replay(&replay).expect_err("verification should fail")
}

// ---- Strict parsing ----------------------------------------------------------

#[test]
fn unknown_top_level_field_is_rejected() {
    let mut v = base_value();
    v.as_object_mut()
        .unwrap()
        .insert("surprise".into(), json!(1));
    assert!(parse(&v).is_err());
}

#[test]
fn unknown_step_field_is_rejected() {
    let mut v = base_value();
    v["steps"][0]
        .as_object_mut()
        .unwrap()
        .insert("surprise".into(), json!(1));
    assert!(parse(&v).is_err());
}

#[test]
fn unknown_action_field_is_rejected() {
    let mut v = base_value();
    v["steps"][0]["action"]
        .as_object_mut()
        .unwrap()
        .insert("surprise".into(), json!(1));
    assert!(parse(&v).is_err());
}

#[test]
fn invalid_hash_encoding_is_rejected() {
    for bad in [
        json!("not-hex"),
        json!("ABCDEF"),
        json!("g".repeat(64)),
        json!("a".repeat(63)),
        json!("A".repeat(64)),
    ] {
        let mut v = base_value();
        v["initial_state_hash"] = bad;
        assert!(parse(&v).is_err());
    }
}

// ---- Compatibility -----------------------------------------------------------

#[test]
fn wrong_format_is_rejected() {
    let mut v = base_value();
    v["format"] = json!("some-other-format");
    assert!(matches!(verify_err(&v), ReplayError::WrongFormat { .. }));
}

#[test]
fn unsupported_replay_version_is_rejected() {
    let mut v = base_value();
    v["version"] = json!(999);
    assert!(matches!(
        verify_err(&v),
        ReplayError::UnsupportedVersion { .. }
    ));
}

#[test]
fn engine_version_mismatch_is_rejected() {
    let mut v = base_value();
    v["engine_version"] = json!("0.0.1");
    assert!(matches!(
        verify_err(&v),
        ReplayError::EngineVersionMismatch { .. }
    ));
}

#[test]
fn catalog_version_mismatch_is_rejected() {
    let mut v = base_value();
    v["ruleset"]["catalog_version"] = json!("catalog-does-not-exist");
    assert!(matches!(
        verify_err(&v),
        ReplayError::CatalogVersionMismatch { .. }
    ));
}

#[test]
fn ruleset_parameter_mismatch_is_rejected() {
    let mut v = base_value();
    v["ruleset"]["prestige_to_end"] = json!(99);
    assert!(matches!(
        verify_err(&v),
        ReplayError::RulesetParameterMismatch { .. }
    ));
}

#[test]
fn ruleset_fingerprint_mismatch_is_rejected() {
    let mut v = base_value();
    // A syntactically valid but wrong fingerprint.
    v["ruleset_fingerprint"] = json!("0".repeat(64));
    assert!(matches!(
        verify_err(&v),
        ReplayError::RulesetFingerprintMismatch { .. }
    ));
}

#[test]
fn unsupported_ruleset_is_rejected() {
    // Change id but keep catalog version valid so the ruleset-id check fires.
    let mut v = base_value();
    v["ruleset"]["id"] = json!("splendor-expansion-v9");
    assert!(matches!(verify_err(&v), ReplayError::UnsupportedRuleset(_)));
}

// ---- Tamper detection --------------------------------------------------------

#[test]
fn initial_hash_tamper_is_detected() {
    let mut v = base_value();
    v["initial_state_hash"] = json!("0".repeat(64));
    assert!(matches!(
        verify_err(&v),
        ReplayError::InitialHashMismatch { .. }
    ));
}

#[test]
fn non_contiguous_ply_is_detected() {
    let mut v = base_value();
    v["steps"][1]["ply"] = json!(99);
    assert!(matches!(
        verify_err(&v),
        ReplayError::NonContiguousPly {
            ply: 99,
            expected: 1
        }
    ));
}

#[test]
fn actor_tamper_is_detected() {
    let mut v = base_value();
    let original = v["steps"][0]["actor"].as_u64().unwrap();
    v["steps"][0]["actor"] = json!(if original == 0 { 1 } else { 0 });
    assert!(matches!(
        verify_err(&v),
        ReplayError::ActorMismatch { ply: 0, .. }
    ));
}

#[test]
fn action_tamper_is_detected_at_exact_ply() {
    let mut v = base_value();
    // Find a step that is not already a pass, and replace it with a pass, which
    // is only legal in forced situations and will diverge from the recorded
    // before-hash-consistent legal set.
    let mut target = None;
    for (i, step) in v["steps"].as_array().unwrap().iter().enumerate() {
        if step["action"]["type"] != "pass" {
            target = Some(i);
            break;
        }
    }
    let idx = target.expect("game should contain a non-pass action");
    v["steps"][idx]["action"] = json!({ "type": "pass" });
    match verify_err(&v) {
        ReplayError::IllegalAction { ply, .. } | ReplayError::AfterHashMismatch { ply, .. } => {
            assert_eq!(ply as usize, idx);
        }
        other => panic!("unexpected error: {other:?}"),
    }
}

#[test]
fn before_hash_tamper_is_detected() {
    let mut v = base_value();
    v["steps"][2]["state_hash_before"] = json!("0".repeat(64));
    assert!(matches!(
        verify_err(&v),
        ReplayError::BeforeHashMismatch { ply: 2, .. }
    ));
}

#[test]
fn after_hash_tamper_is_detected() {
    let mut v = base_value();
    v["steps"][2]["state_hash_after"] = json!("0".repeat(64));
    assert!(matches!(
        verify_err(&v),
        ReplayError::AfterHashMismatch { ply: 2, .. }
    ));
}

#[test]
fn truncated_replay_is_rejected() {
    let mut v = base_value();
    let steps = v["steps"].as_array_mut().unwrap();
    steps.pop();
    // After removing the last step the game is no longer terminal at the end.
    match verify_err(&v) {
        ReplayError::NotTerminal { .. }
        | ReplayError::FinalHashMismatch { .. }
        | ReplayError::AfterHashMismatch { .. } => {}
        other => panic!("unexpected error: {other:?}"),
    }
}

#[test]
fn step_after_terminal_is_rejected() {
    let mut v = base_value();
    // Duplicate the last step so a step exists after the game already ended.
    let last = v["steps"].as_array().unwrap().last().unwrap().clone();
    let len = v["steps"].as_array().unwrap().len();
    let mut extra = last;
    extra["ply"] = json!(len as u64);
    v["steps"].as_array_mut().unwrap().push(extra);
    match verify_err(&v) {
        ReplayError::StepAfterTerminal { .. } | ReplayError::AfterHashMismatch { .. } => {}
        other => panic!("unexpected error: {other:?}"),
    }
}

#[test]
fn final_hash_tamper_is_detected() {
    let mut v = base_value();
    v["final_state_hash"] = json!("0".repeat(64));
    assert!(matches!(
        verify_err(&v),
        ReplayError::FinalHashMismatch { .. }
    ));
}

#[test]
fn result_tamper_is_detected() {
    let mut v = base_value();
    // Corrupt the scores so the recorded result no longer matches the re-run.
    let scores = v["result"]["scores"].as_array().unwrap().len();
    v["result"]["scores"] = json!(vec![255u8; scores]);
    assert!(matches!(verify_err(&v), ReplayError::ResultMismatch));
}

#[test]
fn failure_never_reports_ok() {
    // Every tampered document must produce Err, never a VerifiedReplay.
    let mut v = base_value();
    v["final_state_hash"] = json!("0".repeat(64));
    let replay = parse_ok(&v);
    assert!(verify_replay(&replay).is_err());
}
