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
fn studio_reviewer_registry_is_valid_and_player_count_aware() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let registry: ReviewerRegistryV1 = serde_json::from_slice(
        &fs::read(root.join("benchmarks/studio-reviewers.registry.json")).unwrap(),
    )
    .unwrap();
    registry.validate().unwrap();
    assert_eq!(registry.reviewers.len(), 3);
    assert_eq!(registry.reviewers[0].id, "s3-rollout-review");

    // 2p -> S3 default (available); 3/4p -> M07 default; S3 is unavailable
    // for 3/4p. M07 keeps its Champion binding and is no longer excluded
    // from defaulting — defaults are per player-count context.
    let s3 = registry.entry("s3-rollout-review").unwrap();
    assert_eq!(s3.supported_player_counts(), vec![2]);
    assert_eq!(s3.default_for_player_counts, vec![2]);
    assert!(s3.supports_player_count(2));
    assert!(!s3.supports_player_count(3));
    assert!(!s3.supports_player_count(4));

    let m07 = registry.entry("m07-determinization-champion").unwrap();
    assert_eq!(m07.competitive_status, ReviewerStatusV2::Champion);
    assert_eq!(m07.supported_player_counts(), vec![2, 3, 4]);
    assert_eq!(m07.default_for_player_counts, vec![3, 4]);

    let m13 = registry.entry("m13-neural-ismcts").unwrap();
    assert_eq!(m13.default_for_player_counts, Vec::<u8>::new());

    assert_eq!(registry.default_entry(2).unwrap().id, "s3-rollout-review");
    assert_eq!(
        registry.default_entry(3).unwrap().id,
        "m07-determinization-champion"
    );
    assert_eq!(
        registry.default_entry(4).unwrap().id,
        "m07-determinization-champion"
    );
}
