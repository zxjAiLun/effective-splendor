//! Recorder public-contract tests: the recorder must only ever accept the
//! canonical `splendor-base-v1` ruleset, and any completed recording it emits
//! must verify against the current verifier.

use splendor_core::{GameConfig, Ruleset, RulesetId};
use splendor_replay::{record_random_game, verify_replay, ReplayError, ReplayRecorder};

#[test]
fn recorder_rejects_unknown_ruleset() {
    let ruleset = Ruleset {
        id: RulesetId("splendor-expansion-v9"),
        ..Ruleset::base_v1()
    };
    let err = match ReplayRecorder::new(GameConfig {
        ruleset,
        ..Default::default()
    }) {
        Ok(_) => panic!("recorder must reject an unknown ruleset id"),
        Err(e) => e,
    };
    assert!(matches!(err, ReplayError::UnsupportedRuleset(_)));
}

#[test]
fn recorder_rejects_noncanonical_base_v1_parameters() {
    // Same id, but a tampered parameter — the recorder must still refuse,
    // because the resulting replay would fail ruleset-parameter verification.
    let mut ruleset = Ruleset::base_v1();
    ruleset.prestige_to_end = 10;
    let err = match ReplayRecorder::new(GameConfig {
        ruleset,
        ..Default::default()
    }) {
        Ok(_) => panic!("recorder must reject non-canonical base-v1 parameters"),
        Err(e) => e,
    };
    assert!(matches!(err, ReplayError::RulesetParameterMismatch { .. }));
}

#[test]
fn every_finished_recorder_output_verifies() {
    // Anything the recorder can hand back through its public API must be
    // accepted by the current verifier — no exceptions.
    for players in 2..=4u8 {
        for action_seed in [1001u64, 7, 250, 4242, 99991] {
            let (_state, replay) = record_random_game(players, 42, action_seed)
                .expect("recorder should finish a canonical game");
            verify_replay(&replay).unwrap_or_else(|e| {
                panic!("recorder output failed verification (players={players}, action_seed={action_seed}): {e:?}")
            });
        }
    }
}
