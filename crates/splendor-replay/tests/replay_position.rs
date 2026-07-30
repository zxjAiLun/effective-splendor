//! Tests for `verify_replay_position` and `replay_document_hash_v1`.
//!
//! The position API must share the full strict verifier: any tampering —
//! before *or after* the requested ply — must reject the whole request. The
//! document hash must identify replay content independently of on-disk
//! formatting.

use splendor_core::full_state_hash;
use splendor_replay::{
    record_random_game, replay_document_hash_v1, verify_replay, verify_replay_position,
    ReplayError, ReplayHash, ReplayV1,
};

/// A deterministic completed 2-player replay used by most tests.
fn sample_replay() -> ReplayV1 {
    let (_state, replay) = record_random_game(2, 42, 1001).expect("record");
    assert!(replay.steps.len() >= 3, "sample replay needs several steps");
    replay
}

/// A 64-char lowercase-hex hash that never matches a real engine hash.
fn fake_hash() -> ReplayHash {
    ReplayHash::from_hash_str(&"0".repeat(64)).expect("valid shape")
}

#[test]
fn ply_zero_returns_initial_state() {
    let replay = sample_replay();
    let position = verify_replay_position(&replay, 0).expect("ply 0");
    assert_eq!(position.ply, 0);
    assert_eq!(
        position.state_hash,
        replay.initial_state_hash.as_str(),
        "the state before step 0 is the initial state"
    );
    assert_eq!(
        full_state_hash(&position.state).as_str(),
        replay.initial_state_hash.as_str()
    );
}

#[test]
fn middle_ply_returns_recorded_before_state() {
    let replay = sample_replay();
    let ply = (replay.steps.len() / 2) as u32;
    let position = verify_replay_position(&replay, ply).expect("middle ply");
    assert_eq!(position.ply, ply);
    assert_eq!(
        position.state_hash,
        replay.steps[ply as usize].state_hash_before.as_str()
    );
    assert_eq!(
        full_state_hash(&position.state).as_str(),
        position.state_hash,
        "captured state must re-hash to the recorded before-hash"
    );
}

#[test]
fn last_valid_ply_succeeds() {
    let replay = sample_replay();
    let last = (replay.steps.len() - 1) as u32;
    let position = verify_replay_position(&replay, last).expect("last ply");
    assert_eq!(position.ply, last);
    assert_eq!(
        position.state_hash,
        replay.steps[last as usize].state_hash_before.as_str()
    );
    assert!(!position.state.is_terminal());
}

#[test]
fn ply_equal_to_step_count_is_out_of_range() {
    let replay = sample_replay();
    let steps = replay.steps.len() as u32;
    let err = verify_replay_position(&replay, steps).unwrap_err();
    assert_eq!(
        err,
        ReplayError::PlyOutOfRange {
            requested: steps,
            steps,
        }
    );
}

#[test]
fn ply_beyond_step_count_is_out_of_range() {
    let replay = sample_replay();
    let steps = replay.steps.len() as u32;
    let err = verify_replay_position(&replay, steps + 17).unwrap_err();
    assert_eq!(
        err,
        ReplayError::PlyOutOfRange {
            requested: steps + 17,
            steps,
        }
    );
}

#[test]
fn actor_and_action_are_bound_to_the_step() {
    let replay = sample_replay();
    let ply = (replay.steps.len() / 2) as u32;
    let step = &replay.steps[ply as usize];
    let position = verify_replay_position(&replay, ply).expect("middle ply");
    assert_eq!(position.recorded_actor, step.actor);
    assert_eq!(position.recorded_action, step.action);
    assert_eq!(
        position.state.current_player, step.actor,
        "the rebuilt state's player to move is the recorded actor"
    );
    assert!(
        position.state.legal_actions().contains(&step.action),
        "the recorded action must be legal in the rebuilt state"
    );
}

#[test]
fn position_verified_summary_equals_verify_replay() {
    let replay = sample_replay();
    let full = verify_replay(&replay).expect("verify");
    let position = verify_replay_position(&replay, 1).expect("ply 1");
    assert_eq!(position.verified, full);
}

#[test]
fn tampered_prefix_is_rejected() {
    let mut replay = sample_replay();
    let target = (replay.steps.len() - 1) as u32;
    // Corrupt a step BEFORE the requested ply.
    replay.steps[0].state_hash_after = fake_hash();
    let err = verify_replay_position(&replay, target).unwrap_err();
    assert!(
        matches!(err, ReplayError::AfterHashMismatch { ply: 0, .. }),
        "unexpected error: {err:?}"
    );
}

#[test]
fn tampered_suffix_after_target_ply_is_rejected() {
    let mut replay = sample_replay();
    // Request ply 0, then corrupt the LAST step — strictly after the target.
    let last = replay.steps.len() - 1;
    replay.steps[last].state_hash_after = fake_hash();
    let err = verify_replay_position(&replay, 0).unwrap_err();
    assert!(
        matches!(
            err,
            ReplayError::AfterHashMismatch { ply, .. } if ply == last as u32
        ),
        "a tampered suffix must fail the position API too: {err:?}"
    );
}

#[test]
fn input_replay_is_not_modified() {
    let replay = sample_replay();
    let snapshot = replay.clone();
    let _ = verify_replay_position(&replay, 2).expect("verify position");
    let _ = replay_document_hash_v1(&replay).expect("hash");
    assert_eq!(replay, snapshot, "inputs must remain untouched");
}

#[test]
fn document_hash_is_deterministic() {
    let replay = sample_replay();
    let h1 = replay_document_hash_v1(&replay).expect("hash 1");
    let h2 = replay_document_hash_v1(&replay).expect("hash 2");
    assert_eq!(h1, h2);
    assert_eq!(h1.len(), 64);
    assert!(h1
        .bytes()
        .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()));
}

#[test]
fn document_hash_ignores_input_formatting() {
    let replay = sample_replay();
    let pretty = serde_json::to_string_pretty(&replay).expect("pretty");
    let compact = serde_json::to_string(&replay).expect("compact");
    assert_ne!(pretty, compact, "the two encodings must differ on disk");

    let from_pretty: ReplayV1 = serde_json::from_str(&pretty).expect("parse pretty");
    let from_compact: ReplayV1 = serde_json::from_str(&compact).expect("parse compact");
    assert_eq!(
        replay_document_hash_v1(&from_pretty).unwrap(),
        replay_document_hash_v1(&from_compact).unwrap(),
        "whitespace/pretty-printing must not change the document hash"
    );
    assert_eq!(
        replay_document_hash_v1(&from_pretty).unwrap(),
        replay_document_hash_v1(&replay).unwrap()
    );
}

#[test]
fn any_content_change_changes_document_hash() {
    let base = sample_replay();
    let h0 = replay_document_hash_v1(&base).expect("base hash");

    // Top-level field change.
    let mut changed_seed = base.clone();
    changed_seed.seed ^= 1;
    assert_ne!(h0, replay_document_hash_v1(&changed_seed).unwrap());

    // Step hash change.
    let mut changed_step = base.clone();
    changed_step.steps[1].state_hash_before = fake_hash();
    assert_ne!(h0, replay_document_hash_v1(&changed_step).unwrap());

    // Recorded action change: swap in another step's action.
    let mut changed_action = base.clone();
    let donor = changed_action
        .steps
        .iter()
        .map(|s| s.action)
        .find(|a| *a != changed_action.steps[0].action)
        .expect("two distinct actions in the sample replay");
    changed_action.steps[0].action = donor;
    assert_ne!(h0, replay_document_hash_v1(&changed_action).unwrap());
}
