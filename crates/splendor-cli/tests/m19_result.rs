use std::fs;

use serde_json::Value;

#[test]
fn m19_result_is_complete_provisional_and_keeps_m07_champion() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m19-internal-championship-v1.result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(result["status"], "complete_provisional");
    assert_eq!(result["scheduled_matches"], 42);
    assert_eq!(result["completed_matches"], 42);
    assert_eq!(result["aborted_matches"], 0);
    assert_eq!(result["verified_replays"], 42);
    assert_eq!(result["ranking"].as_array().unwrap().len(), 7);
    assert_eq!(result["champion_decision"], "unchanged_m07");
}
