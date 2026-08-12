use std::fs;

use serde_json::Value;

#[test]
fn m22_result_uses_arena_evidence_and_does_not_promote_a_tie() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m22-scaled-self-play-v1.result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(result["status"], "candidate_not_promoted");
    assert_eq!(result["self_play"]["games"], 32);
    assert_eq!(result["self_play"]["examples"], 1992);
    assert_eq!(
        result["training"]["offline_validation"]["strength_evidence"],
        false
    );
    assert_eq!(result["multi_seed_league"]["completed_matches"], 48);
    assert_eq!(result["multi_seed_league"]["aborted_matches"], 0);
    assert_eq!(
        result["multi_seed_league"]["m22_head_to_head"]["vs_m18a"]["wins"],
        4
    );
    assert_eq!(
        result["multi_seed_league"]["m22_head_to_head"]["vs_m18a"]["losses"],
        4
    );
    assert_eq!(result["verdict"], "no_measured_improvement_over_m18a");
    assert_eq!(result["champion_decision"], "unchanged_m07");
}
