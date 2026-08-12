use std::fs;

use serde_json::Value;

#[test]
fn checked_in_m18b_result_is_value_based_and_rejected() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m18b-rainbow-smoke-v1.result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(result["status"], "candidate_rejected");
    assert_eq!(result["algorithm"], "c51_double_dqn_prioritized_replay");
    assert_eq!(result["training"]["gradient_steps"], 800);
    assert_eq!(result["prospective_screen"]["completed"], 8);
    assert_eq!(result["prospective_screen"]["aborted"], 0);
    assert_eq!(result["prospective_screen"]["wins"], 1);
    assert_eq!(result["prospective_screen"]["losses"], 7);
}
