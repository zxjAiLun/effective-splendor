use std::fs;

use splendor_eval::RatingRegistryV1;

#[test]
fn studio_registry_is_valid_and_contains_every_current_gpu_model() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let registry: RatingRegistryV1 = serde_json::from_slice(
        &fs::read(root.join("benchmarks/studio-1v1.registry.json")).unwrap(),
    )
    .unwrap();
    registry.validate().unwrap();
    assert_eq!(registry.agents.len(), 8);
    for id in [
        "m17-entity-mixer",
        "m18a-self-play",
        "m18b-rainbow",
        "m22-scaled-self-play",
    ] {
        assert!(registry.agents.iter().any(|agent| agent.id == id));
    }
}
