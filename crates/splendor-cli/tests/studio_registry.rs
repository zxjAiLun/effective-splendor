use std::fs;

use splendor_analysis::{ReviewerRegistryV1, ReviewerStatusV2};
use splendor_eval::RatingRegistryV1;

#[test]
fn studio_registry_is_valid_and_contains_every_current_gpu_model() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let registry: RatingRegistryV1 = serde_json::from_slice(
        &fs::read(root.join("benchmarks/studio-1v1.registry.json")).unwrap(),
    )
    .unwrap();
    registry.validate().unwrap();
    assert_eq!(registry.agents.len(), 9);
    assert_eq!(registry.agents[0].id, "s3-rollout");
    for id in [
        "s3-rollout",
        "heuristic-v1",
        "m17-entity-mixer",
        "m18a-self-play",
        "m18b-rainbow",
        "m22-scaled-self-play",
    ] {
        assert!(registry.agents.iter().any(|agent| agent.id == id));
    }
}

#[test]
fn studio_reviewer_registry_is_valid_and_defaults_to_s3() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let registry: ReviewerRegistryV1 = serde_json::from_slice(
        &fs::read(root.join("benchmarks/studio-reviewers.registry.json")).unwrap(),
    )
    .unwrap();
    registry.validate().unwrap();
    assert_eq!(registry.reviewers.len(), 3);
    assert_eq!(registry.reviewers[0].id, "s3-rollout-review");
    let defaults = registry
        .reviewers
        .iter()
        .filter(|entry| entry.is_default)
        .collect::<Vec<_>>();
    assert_eq!(defaults.len(), 1, "exactly one default reviewer");
    assert_eq!(defaults[0].id, "s3-rollout-review");
    let m07 = registry.entry("m07-determinization-champion").unwrap();
    assert_eq!(m07.competitive_status, ReviewerStatusV2::Champion);
    assert!(!m07.is_default);
}
