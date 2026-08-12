use std::fs;

use serde_json::Value;

#[test]
fn gpu_results_separate_offline_fit_from_arena_strength() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    for file in [
        "m17-gpu-supervised-warmstart-v1.result.json",
        "m18a-neural-self-play-smoke-v1.result.json",
        "m18b-rainbow-smoke-v1.result.json",
    ] {
        let result: Value =
            serde_json::from_slice(&fs::read(root.join("benchmarks").join(file)).unwrap()).unwrap();
        assert_eq!(
            result["metric_semantics"]["offline_metrics_are_strength_evidence"], false,
            "{file} must not treat offline fit as strength"
        );
        assert_eq!(
            result["metric_semantics"]["strength_authority"], "prospective_screen",
            "{file} must point to actual Arena games"
        );
        assert!(
            result["prospective_screen"]["completed"].as_u64().is_some()
                || result["prospective_screen"]["completed_matches"]
                    .as_u64()
                    .is_some()
        );
    }
}

#[test]
fn m19_strength_is_bound_to_arena_round_robin() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let result: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m19-internal-championship-v1.result.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(result["strength_authority"], "arena_round_robin");
    assert_eq!(result["completed_matches"], 42);
    assert_eq!(result["aborted_matches"], 0);
}
