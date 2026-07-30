//! Search analysis artifact model tests (M06 C4).
//!
//! Covers the frozen artifact contract:
//! - strict JSON round-trip (serialize -> deserialize -> identical value),
//! - unknown fields rejected at every nesting level (`deny_unknown_fields`),
//! - snake_case stop-reason tags (`depth_limit_reached` / `node_budget_reached`),
//! - all identity/version constants frozen.

use splendor_core::{Action, PlayerId};
use splendor_search::{
    ReplaySearchSourceV1, SearchAnalysisV1, SearchConfigV1, SearchResultV1, SearchStatsV1,
    SearchStopReasonV1, SEARCH_ALGORITHM_ID, SEARCH_ANALYSIS_FORMAT, SEARCH_ANALYSIS_VERSION,
    SEARCH_VERSION,
};

fn sample_source() -> ReplaySearchSourceV1 {
    ReplaySearchSourceV1 {
        replay_document_hash: "ab".repeat(32),
        replay_final_state_hash: "cd".repeat(32),
        replay_version: 1,
        ruleset_fingerprint: "ef".repeat(32),
        analyzed_ply: 7,
        analyzed_state_hash: "12".repeat(32),
        recorded_actor: PlayerId(1),
        recorded_action: Action::Pass,
    }
}

fn sample_result() -> SearchResultV1 {
    SearchResultV1 {
        action: Action::Pass,
        root_player: PlayerId(1),
        completed_depth_turns: 2,
        utility_by_player: vec![10, -4],
        principal_variation: vec![Action::Pass, Action::Pass],
        stop_reason: SearchStopReasonV1::DepthLimitReached,
        stats: SearchStatsV1 {
            nodes_visited: 42,
            nodes_expanded: 17,
            leaf_evaluations: 20,
            transposition_hits: 5,
            transposition_entries: 12,
        },
    }
}

fn sample_analysis() -> SearchAnalysisV1 {
    SearchAnalysisV1 {
        format: SEARCH_ANALYSIS_FORMAT.to_string(),
        version: SEARCH_ANALYSIS_VERSION,
        engine_version: "0.4.0".to_string(),
        catalog_version: "1.0.0".to_string(),
        search_algorithm_id: SEARCH_ALGORITHM_ID.to_string(),
        search_version: SEARCH_VERSION,
        source: sample_source(),
        config: SearchConfigV1 {
            max_depth_turns: 2,
            max_nodes: 50_000,
        },
        result: sample_result(),
        recommended_matches_recorded: true,
    }
}

#[test]
fn identity_constants_are_frozen() {
    assert_eq!(SEARCH_ANALYSIS_FORMAT, "effective-splendor-search-analysis");
    assert_eq!(SEARCH_ANALYSIS_VERSION, 1);
    assert_eq!(SEARCH_ALGORITHM_ID, "effective-splendor-maxn");
    assert_eq!(SEARCH_VERSION, 1);
}

#[test]
fn analysis_round_trips_through_json() {
    let original = sample_analysis();
    let json = serde_json::to_string_pretty(&original).expect("serialize");
    let parsed: SearchAnalysisV1 = serde_json::from_str(&json).expect("deserialize");
    assert_eq!(parsed, original);
}

#[test]
fn serialization_is_deterministic() {
    let a = serde_json::to_string(&sample_analysis()).expect("serialize");
    let b = serde_json::to_string(&sample_analysis()).expect("serialize");
    assert_eq!(a, b);
}

#[test]
fn stop_reason_uses_snake_case_tags() {
    assert_eq!(
        serde_json::to_string(&SearchStopReasonV1::DepthLimitReached).expect("serialize"),
        "\"depth_limit_reached\""
    );
    assert_eq!(
        serde_json::to_string(&SearchStopReasonV1::NodeBudgetReached).expect("serialize"),
        "\"node_budget_reached\""
    );
    let parsed: SearchStopReasonV1 =
        serde_json::from_str("\"node_budget_reached\"").expect("deserialize");
    assert_eq!(parsed, SearchStopReasonV1::NodeBudgetReached);
    assert!(serde_json::from_str::<SearchStopReasonV1>("\"DepthLimitReached\"").is_err());
}

#[test]
fn unknown_field_in_analysis_is_rejected() {
    let mut value = serde_json::to_value(sample_analysis()).expect("to_value");
    value
        .as_object_mut()
        .expect("object")
        .insert("timestamp".to_string(), serde_json::json!("2026-07-30"));
    assert!(serde_json::from_value::<SearchAnalysisV1>(value).is_err());
}

#[test]
fn unknown_field_in_source_is_rejected() {
    let mut value = serde_json::to_value(sample_analysis()).expect("to_value");
    value["source"]
        .as_object_mut()
        .expect("object")
        .insert("hostname".to_string(), serde_json::json!("box"));
    assert!(serde_json::from_value::<SearchAnalysisV1>(value).is_err());
}

#[test]
fn unknown_field_in_config_is_rejected() {
    let mut value = serde_json::to_value(sample_analysis()).expect("to_value");
    value["config"]
        .as_object_mut()
        .expect("object")
        .insert("timeout_ms".to_string(), serde_json::json!(1000));
    assert!(serde_json::from_value::<SearchAnalysisV1>(value).is_err());
}

#[test]
fn unknown_field_in_result_is_rejected() {
    let mut value = serde_json::to_value(sample_analysis()).expect("to_value");
    value["result"]
        .as_object_mut()
        .expect("object")
        .insert("duration_ms".to_string(), serde_json::json!(3));
    assert!(serde_json::from_value::<SearchAnalysisV1>(value).is_err());
}

#[test]
fn unknown_field_in_stats_is_rejected() {
    let mut value = serde_json::to_value(sample_analysis()).expect("to_value");
    value["result"]["stats"]
        .as_object_mut()
        .expect("object")
        .insert("thread_count".to_string(), serde_json::json!(8));
    assert!(serde_json::from_value::<SearchAnalysisV1>(value).is_err());
}

#[test]
fn missing_required_field_is_rejected() {
    let mut value = serde_json::to_value(sample_analysis()).expect("to_value");
    value
        .as_object_mut()
        .expect("object")
        .remove("recommended_matches_recorded");
    assert!(serde_json::from_value::<SearchAnalysisV1>(value).is_err());
}
