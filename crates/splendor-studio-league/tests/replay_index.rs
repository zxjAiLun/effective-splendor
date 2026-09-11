use splendor_replay::record_random_game;
use splendor_studio_league::{build_replay_content_index, StudioLeagueError};
use std::path::PathBuf;

fn temp_dir(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "splendor-studio-league-replay-index-{label}-{}",
        std::process::id()
    ))
}

#[test]
fn content_index_preserves_every_document_for_a_repeated_final_hash() {
    let dir = temp_dir("duplicates");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("nested")).unwrap();

    let (_, replay) = record_random_game(2, 71, 91).unwrap();
    let final_hash = replay.final_state_hash.as_str().to_string();
    let compact = serde_json::to_vec(&replay).unwrap();
    let pretty = serde_json::to_vec_pretty(&replay).unwrap();
    assert_ne!(compact, pretty, "the fixture needs two exact documents");
    std::fs::write(dir.join("z.json"), &compact).unwrap();
    std::fs::write(dir.join("nested/a.json"), &pretty).unwrap();
    std::fs::write(
        dir.join("not-a-replay.json"),
        br#"{"format":"some-other-document","version":1}"#,
    )
    .unwrap();

    let index = build_replay_content_index(&[dir.clone()], 1_000_000, &[]).unwrap();
    assert_eq!(index.documents_indexed(), 2);
    assert_eq!(index.distinct_final_state_hashes(), 1);
    let candidates = index.candidates(&final_hash);
    assert_eq!(
        candidates.len(),
        2,
        "no duplicate candidate may be overwritten"
    );
    assert_ne!(candidates[0].document_sha256, candidates[1].document_sha256);
    assert!(candidates
        .iter()
        .all(|candidate| candidate.final_state_hash == final_hash));
    assert!(candidates
        .windows(2)
        .all(|pair| (&pair[0].document_sha256, &pair[0].logical_path)
            <= (&pair[1].document_sha256, &pair[1].logical_path)));

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn content_index_is_deterministic_across_root_order() {
    let dir = temp_dir("root-order");
    let _ = std::fs::remove_dir_all(&dir);
    let left = dir.join("left");
    let right = dir.join("right");
    std::fs::create_dir_all(&left).unwrap();
    std::fs::create_dir_all(&right).unwrap();

    let (_, first) = record_random_game(2, 72, 92).unwrap();
    let (_, second) = record_random_game(2, 73, 93).unwrap();
    std::fs::write(left.join("first.json"), serde_json::to_vec(&first).unwrap()).unwrap();
    std::fs::write(
        right.join("second.json"),
        serde_json::to_vec(&second).unwrap(),
    )
    .unwrap();

    let forward =
        build_replay_content_index(&[left.clone(), right.clone()], 1_000_000, &[]).unwrap();
    let reverse =
        build_replay_content_index(&[right.clone(), left.clone()], 1_000_000, &[]).unwrap();
    assert_eq!(forward, reverse);

    let overlapping =
        build_replay_content_index(&[left.clone(), left.clone()], 1_000_000, &[]).unwrap();
    assert_eq!(
        overlapping
            .candidates(first.final_state_hash.as_str())
            .len(),
        1,
        "overlapping roots must not double-index files"
    );

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn a_document_claiming_replay_v1_but_failing_its_schema_is_rejected() {
    let dir = temp_dir("invalid");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(
        dir.join("bad.json"),
        br#"{"format":"effective-splendor-replay","version":1,"final_state_hash":"abc"}"#,
    )
    .unwrap();

    let error = build_replay_content_index(&[dir.clone()], 1_000_000, &[]).unwrap_err();
    assert!(matches!(error, StudioLeagueError::Invalid(_)));

    let _ = std::fs::remove_dir_all(&dir);
}
