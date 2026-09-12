//! Commit A core gates, plus the Commit A Repair 1 proofs.
//!
//! The five sentences these tests exist to make true:
//! 1. same evidence rebuilds the same league;
//! 2. the rating config cannot drift;
//! 3. no-result never becomes a loss;
//! 4. the same source key with changed content fails;
//! 5. `rating_eligible` always implies exactly one valid 1v1 Elo update.

use league::{
    aliases, canonical_identity_key, canonical_league_order, identity_index,
    ingest_batch_canonical, ingest_match, leaderboard, league_order, local_human_participant,
    match_count, open_in_memory, open_league, participant, participant_elo,
    participant_id_for_identity, protocol_rating_config, rating_event_count, rating_history,
    rebuild_ratings, resolve_engine_participant, schema_version, stored_rating_config,
    sync_identity_manifest, unassigned_human_participant, EligibilityInput, EngineIdentityV1,
    IdentityManifestV1, IngestOutcome, MatchStatus, ParticipantKind, RatingEligibility,
    ReplayStorage, ReplayVerification, StudioLeagueError, StudioMatchRecordV1, StudioMatchSeatV1,
    StudioRatingConfigV1, REASON_ABORTED, REASON_DIAGNOSTIC, REASON_INCOMPLETE_SEATS,
    REASON_PLAYER_COUNT, REASON_REPLAY, REASON_RULESET, REASON_SELF_MATCH, REASON_TRUNCATED,
    REASON_UNMAPPED, SPLENDOR_BASE_V1_RULESET_FINGERPRINT, STUDIO_LEAGUE_SCHEMA_VERSION,
};
use splendor_studio_league as league;

const NOW: i64 = 1_700_000_000;

/// Collect everything a rebuild must reproduce.
macro_rules! league_snapshot {
    ($conn:expr) => {{
        let identities = identity_index(&$conn).unwrap();
        let alias_rows = aliases(&$conn).unwrap();
        let order = league_order(&$conn).unwrap();
        let histories: Vec<(String, Vec<league::RatingEventRow>)> = identities
            .iter()
            .map(|(key, id)| (key.clone(), rating_history(&$conn, id).unwrap()))
            .collect();
        let board = leaderboard(&$conn).unwrap();
        (identities, alias_rows, order, histories, board)
    }};
}

fn seat(index: u8, name: &str, version: &str, won: bool, score: i32) -> StudioMatchSeatV1 {
    StudioMatchSeatV1 {
        seat: index,
        identity: Some(EngineIdentityV1::new(name, version)),
        policy_identity_key: None,
        participant_id: None,
        display_name: None,
        score: Some(score),
        rank: Some(if won { 0 } else { 1 }),
        won,
    }
}

/// A deterministic 64-character lowercase hex value for a short label.
///
/// Test records must carry a structurally valid content hash, and a hasher would
/// just add a dependency to the test for no extra coverage.
fn hex64(label: &str) -> String {
    let mut value = String::new();
    for byte in label.bytes() {
        value.push_str(&format!("{byte:02x}"));
    }
    while value.len() < 64 {
        value.push('0');
    }
    value.truncate(64);
    value
}

fn record(source_identity: &str, seats: Vec<StudioMatchSeatV1>) -> StudioMatchRecordV1 {
    StudioMatchRecordV1 {
        source_kind: "arena_report".to_string(),
        source_identity: source_identity.to_string(),
        source_path: Some(format!("benchmarks/{source_identity}.report.json")),
        source_document_hash: hex64(source_identity),
        played_at: Some(NOW),
        ruleset_fingerprint: SPLENDOR_BASE_V1_RULESET_FINGERPRINT.to_string(),
        engine_version: Some("0.4.0".to_string()),
        player_count: 2,
        status: MatchStatus::Completed,
        seats,
        completed_plies: Some(64),
        main_turn_count: Some(32),
        replay: league::ReplayBindingV1 {
            document_hash: Some("a".repeat(64)),
            final_hash: Some(format!("{source_identity:0>64}")),
            storage: Some(ReplayStorage::Archive),
            path: Some(format!("replays/{source_identity}.json")),
            verification: Some(ReplayVerification::Verified),
        },
        diagnostic: false,
    }
}

fn pair(source_identity: &str, a_wins: bool) -> StudioMatchRecordV1 {
    record(
        source_identity,
        vec![
            seat(0, "engine-a", "1", a_wins, if a_wins { 15 } else { 12 }),
            seat(1, "engine-b", "1", !a_wins, if a_wins { 12 } else { 15 }),
        ],
    )
}

/// A match with no replay at all: the binding must be empty and consistent.
fn without_replay(mut value: StudioMatchRecordV1) -> StudioMatchRecordV1 {
    value.replay = league::ReplayBindingV1 {
        document_hash: None,
        final_hash: None,
        storage: Some(ReplayStorage::Absent),
        path: None,
        verification: Some(ReplayVerification::Unavailable),
    };
    value
}

/// A clean, structurally valid non-completed match (no winners, no replay).
fn unfinished(source_identity: &str, status: MatchStatus) -> StudioMatchRecordV1 {
    let mut value = without_replay(record(
        source_identity,
        vec![
            seat(0, "engine-a", "1", false, 9),
            seat(1, "engine-b", "1", false, 7),
        ],
    ));
    value.status = status;
    value
}

#[test]
fn schema_initialises_and_reports_its_version() {
    let conn = open_in_memory().unwrap();
    assert_eq!(schema_version(&conn).unwrap(), STUDIO_LEAGUE_SCHEMA_VERSION);
    league::initialise(&conn).unwrap();
    assert_eq!(match_count(&conn).unwrap(), 0);
}

#[test]
fn engine_participants_are_keyed_by_exact_identity_never_by_display_name() {
    let conn = open_in_memory().unwrap();
    let a = EngineIdentityV1::new("effective-splendor-s3-rollout-v1", "1");
    let b = EngineIdentityV1::new("effective-splendor-s3-rollout-v1", "2");

    let first = resolve_engine_participant(&conn, &a, "S3 Rollout", NOW).unwrap();
    let again = resolve_engine_participant(&conn, &a, "A Different Label", NOW).unwrap();
    let other_version = resolve_engine_participant(&conn, &b, "S3 Rollout", NOW).unwrap();

    assert_eq!(first, again, "the same exact identity is one participant");
    assert_ne!(
        first, other_version,
        "a different version (or checkpoint hash) is a different participant"
    );
    assert_eq!(
        first,
        participant_id_for_identity(&a.key()),
        "ids are derived"
    );
    assert_eq!(
        participant(&conn, &first).unwrap().unwrap().display_name,
        "S3 Rollout"
    );
}

#[test]
fn the_local_human_identity_is_manifest_owned_and_survives_a_rename() {
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    let id = manifest.local_human.clone().unwrap().participant_id;

    let conn = open_in_memory().unwrap();
    sync_identity_manifest(&conn, &manifest, NOW).unwrap();
    assert_eq!(
        local_human_participant(&conn).unwrap().as_deref(),
        Some(id.as_str())
    );
    let row = participant(&conn, &id).unwrap().unwrap();
    assert_eq!(row.kind, ParticipantKind::Human);
    assert!(
        row.identity_key.is_none(),
        "a human has no engine identity key"
    );

    // A rename is authored in the manifest; the id never moves.
    manifest.rename_local_human("Nick (renamed)").unwrap();
    sync_identity_manifest(&conn, &manifest, NOW).unwrap();
    assert_eq!(
        local_human_participant(&conn).unwrap().as_deref(),
        Some(id.as_str())
    );
    assert_eq!(
        participant(&conn, &id).unwrap().unwrap().display_name,
        "Nick (renamed)"
    );
}

#[test]
fn unassigned_human_is_reserved_and_never_the_local_profile() {
    let conn = open_in_memory().unwrap();
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    let local = manifest.local_human.clone().unwrap().participant_id;
    sync_identity_manifest(&conn, &manifest, NOW).unwrap();

    let unassigned = unassigned_human_participant(&conn, NOW).unwrap();
    assert_ne!(local, unassigned);
    assert_eq!(
        participant(&conn, &unassigned).unwrap().unwrap().kind,
        ParticipantKind::Human
    );
    assert_eq!(
        unassigned_human_participant(&conn, NOW).unwrap(),
        unassigned
    );
}

fn eligibility(
    status: MatchStatus,
    player_count: u8,
    ruleset: &str,
    replay: ReplayVerification,
    participants: Vec<Option<String>>,
    diagnostic: bool,
) -> RatingEligibility {
    league::evaluate_eligibility(
        &EligibilityInput {
            status,
            player_count,
            ruleset_fingerprint: ruleset.to_string(),
            replay_verification: replay,
            participants,
            diagnostic,
        },
        &StudioRatingConfigV1::default(),
    )
}

#[test]
fn eligibility_matrix_matches_the_frozen_contract() {
    let both = || vec![Some("p1".to_string()), Some("p2".to_string())];
    let base = SPLENDOR_BASE_V1_RULESET_FINGERPRINT;
    assert!(eligibility(
        MatchStatus::Completed,
        2,
        base,
        ReplayVerification::Verified,
        both(),
        false
    )
    .is_eligible());

    let reason = |e: RatingEligibility| e.reason().unwrap();
    assert_eq!(
        reason(eligibility(
            MatchStatus::Aborted,
            2,
            base,
            ReplayVerification::Verified,
            both(),
            false
        )),
        REASON_ABORTED
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Truncated,
            2,
            base,
            ReplayVerification::Verified,
            both(),
            false
        )),
        REASON_TRUNCATED
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            3,
            base,
            ReplayVerification::Verified,
            both(),
            false
        )),
        REASON_INCOMPLETE_SEATS,
        "the declared seat count must agree with player_count"
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            3,
            base,
            ReplayVerification::Verified,
            vec![Some("p1".into()), Some("p2".into()), Some("p3".into())],
            false
        )),
        REASON_PLAYER_COUNT
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            2,
            &"b".repeat(64),
            ReplayVerification::Verified,
            both(),
            false
        )),
        REASON_RULESET
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            2,
            base,
            ReplayVerification::Invalid,
            both(),
            false
        )),
        REASON_REPLAY
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            2,
            base,
            ReplayVerification::Unavailable,
            both(),
            false
        )),
        REASON_REPLAY
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            2,
            base,
            ReplayVerification::Verified,
            both(),
            true
        )),
        REASON_DIAGNOSTIC
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            2,
            base,
            ReplayVerification::Verified,
            vec![Some("p1".into()), None],
            false
        )),
        REASON_UNMAPPED
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            2,
            base,
            ReplayVerification::Verified,
            vec![Some("p1".into()), Some("p1".into())],
            false
        )),
        REASON_SELF_MATCH
    );
}

#[test]
fn elo_reuses_the_single_frozen_rule() {
    let update = league::plan_pair_update(1500.0, 1500.0, 1.0, 32);
    assert_eq!(update.expected_a, 0.5);
    assert_eq!(update.delta_a, 16.0);
    assert_eq!(update.delta_b, -16.0, "the pair is zero-sum");
    assert_eq!(update.rating_a_after(), 1516.0);

    for (a, b, score) in [
        (1500.0, 1700.0, 1.0),
        (1700.0, 1500.0, 0.0),
        (1234.0, 1601.0, 0.5),
    ] {
        assert_eq!(
            league::elo_delta(a, b, score, 32),
            splendor_eval::elo_delta(a, b, score, 32)
        );
        assert_eq!(
            league::elo_expected_score(a, b),
            splendor_eval::elo_expected_score(a, b)
        );
    }
    assert!(league::pair_score_a(false, false).is_err());
    assert_eq!(league::pair_score_a(true, true).unwrap(), 0.5);
}

#[test]
fn an_eligible_match_writes_two_rating_events_and_moves_both_ratings() {
    let mut conn = open_in_memory().unwrap();
    let outcome = ingest_match(&mut conn, &pair("m-1", true)).unwrap();
    assert!(outcome.was_inserted());
    assert_eq!(outcome.rating_events(), 2);

    assert_eq!(leaderboard(&conn).unwrap().len(), 2);
    assert_eq!(league::eligible_match_count(&conn).unwrap(), 1);
    assert_eq!(rating_event_count(&conn).unwrap(), 2);

    let a = participant_id_for_identity("engine-a@1");
    let b = participant_id_for_identity("engine-b@1");
    assert_eq!(participant_elo(&conn, &a).unwrap(), 1516.0);
    assert_eq!(participant_elo(&conn, &b).unwrap(), 1484.0);

    let events = rating_history(&conn, &a).unwrap();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].league_seq, 1);
    assert_eq!(events[0].algorithm, league::STUDIO_ELO_ALGORITHM_V1);
    let sum: f64 = rating_history(&conn, &a)
        .unwrap()
        .iter()
        .chain(rating_history(&conn, &b).unwrap().iter())
        .map(|e| e.delta)
        .sum();
    assert_eq!(sum, 0.0, "Studio Elo is zero-sum");
}

#[test]
fn rating_eligible_always_implies_exactly_two_rating_events() {
    let mut conn = open_in_memory().unwrap();
    for index in 0..3 {
        ingest_match(&mut conn, &pair(&format!("m-{index}"), index % 2 == 0)).unwrap();
    }
    let eligible = league::eligible_match_count(&conn).unwrap();
    assert_eq!(eligible, 3);
    assert_eq!(
        rating_event_count(&conn).unwrap(),
        eligible * 2,
        "every eligible 1v1 match contributes exactly one pair event"
    );
}

#[test]
fn ineligible_matches_are_recorded_but_rate_nobody() {
    let mut conn = open_in_memory().unwrap();

    let mut broken = pair("m-invalid-replay", true);
    broken.replay.verification = Some(ReplayVerification::Invalid);
    let mut diagnostic = pair("m-diagnostic", true);
    diagnostic.diagnostic = true;

    let self_match = record(
        "m-self",
        vec![
            seat(0, "engine-a", "1", true, 15),
            seat(1, "engine-a", "1", false, 12),
        ],
    );
    let unmapped = record(
        "m-unmapped",
        vec![
            seat(0, "engine-never-seen", "9", true, 15),
            StudioMatchSeatV1 {
                seat: 1,
                identity: None,
                policy_identity_key: None,
                participant_id: None,
                display_name: None,
                score: Some(12),
                rank: Some(1),
                won: false,
            },
        ],
    );

    for value in [
        unfinished("m-aborted", MatchStatus::Aborted),
        unfinished("m-truncated", MatchStatus::Truncated),
        broken,
        diagnostic,
        self_match,
        unmapped,
    ] {
        assert!(ingest_match(&mut conn, &value).unwrap().was_inserted());
    }
    assert_eq!(match_count(&conn).unwrap(), 6);
    assert_eq!(league::eligible_match_count(&conn).unwrap(), 0);
    assert_eq!(rating_event_count(&conn).unwrap(), 0);

    let reasons: std::collections::HashMap<String, u64> = league::ineligible_reason_counts(&conn)
        .unwrap()
        .into_iter()
        .collect();
    assert_eq!(reasons.get(REASON_ABORTED), Some(&1));
    assert_eq!(reasons.get(REASON_REPLAY), Some(&1));
    assert_eq!(reasons.get(REASON_DIAGNOSTIC), Some(&1));
    assert_eq!(reasons.get(REASON_SELF_MATCH), Some(&1));
    assert_eq!(reasons.get(REASON_UNMAPPED), Some(&1));

    for row in leaderboard(&conn).unwrap() {
        assert_eq!(row.rated_games, 0);
        assert!(rating_history(&conn, &row.participant_id)
            .unwrap()
            .is_empty());
        assert_eq!(
            row.elo,
            protocol_rating_config().initial_elo,
            "ratings must not have moved"
        );
    }
}

/// Proof 3: a match that produced no result must never be shown as a loss.
#[test]
fn no_result_never_becomes_a_loss() {
    let mut conn = open_in_memory().unwrap();
    for value in [
        unfinished("m-aborted", MatchStatus::Aborted),
        unfinished("m-truncated", MatchStatus::Truncated),
    ] {
        ingest_match(&mut conn, &value).unwrap();
    }
    // A self match: two seats, one participant.
    ingest_match(
        &mut conn,
        &record(
            "m-self",
            vec![
                seat(0, "engine-a", "1", true, 15),
                seat(1, "engine-a", "1", false, 12),
            ],
        ),
    )
    .unwrap();

    let a = participant_id_for_identity("engine-a@1");
    let row = leaderboard(&conn)
        .unwrap()
        .into_iter()
        .find(|row| row.participant_id == a)
        .unwrap();

    // engine-a appears in: one aborted match, one truncated match, one self match.
    assert_eq!(row.recorded_games, 3, "distinct matches, not seat rows");
    assert_eq!(row.rated_games, 0);
    assert_eq!(row.rated_wins, 0);
    assert_eq!(row.rated_ties, 0);
    assert_eq!(
        row.rated_losses, 0,
        "an aborted, truncated or self match must never be presented as a loss"
    );
    assert_eq!(row.elo, protocol_rating_config().initial_elo);

    // The self match contributes exactly one recorded game, not two seat rows.
    let mut only_self = open_in_memory().unwrap();
    ingest_match(
        &mut only_self,
        &record(
            "m-self",
            vec![
                seat(0, "engine-a", "1", true, 15),
                seat(1, "engine-a", "1", false, 12),
            ],
        ),
    )
    .unwrap();
    let row = leaderboard(&only_self)
        .unwrap()
        .into_iter()
        .find(|row| row.participant_id == a)
        .unwrap();
    assert_eq!(row.recorded_games, 1);
    assert_eq!(row.rated_games, 0);
    assert_eq!(row.rated_wins + row.rated_ties + row.rated_losses, 0);
}

#[test]
fn ingest_is_idempotent_on_source_identity() {
    let mut conn = open_in_memory().unwrap();
    let first = ingest_match(&mut conn, &pair("m-1", true)).unwrap();
    let second = ingest_match(&mut conn, &pair("m-1", true)).unwrap();
    match second {
        IngestOutcome::AlreadyPresent { match_id } => assert_eq!(match_id, first.match_id()),
        other => panic!("expected AlreadyPresent, got {other:?}"),
    }
    assert_eq!(match_count(&conn).unwrap(), 1);
    assert_eq!(
        rating_event_count(&conn).unwrap(),
        2,
        "Elo moved once, not twice"
    );
    assert_eq!(
        leaderboard(&conn)
            .unwrap()
            .iter()
            .map(|r| r.elo)
            .max()
            .unwrap(),
        1516
    );
}

/// Proof 4: the same key with changed content is a conflict, not a no-op.
#[test]
fn same_source_key_with_changed_content_fails() {
    let mut conn = open_in_memory().unwrap();
    let mut first = pair("m-1", true);
    first.source_document_hash = "a".repeat(64);
    ingest_match(&mut conn, &first).unwrap();

    // Identical content under the same key is genuinely already present.
    let again = ingest_match(&mut conn, &first).unwrap();
    assert!(matches!(again, IngestOutcome::AlreadyPresent { .. }));

    // Drifted content under the same key must not be swallowed.
    let mut drifted = first.clone();
    drifted.source_document_hash = "b".repeat(64);
    let error = ingest_match(&mut conn, &drifted).unwrap_err();
    assert!(
        matches!(error, StudioLeagueError::SourceConflict { .. }),
        "expected a source conflict, got {error}"
    );

    // ...and nothing changed.
    assert_eq!(match_count(&conn).unwrap(), 1);
    assert_eq!(rating_event_count(&conn).unwrap(), 2);
    assert_eq!(
        leaderboard(&conn)
            .unwrap()
            .iter()
            .map(|r| r.elo)
            .max()
            .unwrap(),
        1516
    );
}

/// Proof 5's structural half: contradictions are refused before any write.
#[test]
fn malformed_records_are_rejected_before_anything_is_written() {
    let mut conn = open_in_memory().unwrap();

    let rejected: Vec<(&str, StudioMatchRecordV1)> = vec![
        (
            "seat count disagreeing with player_count",
            record(
                "m-seats",
                vec![
                    seat(0, "engine-a", "1", true, 15),
                    seat(1, "engine-b", "1", false, 12),
                    seat(2, "engine-c", "1", false, 9),
                ],
            ),
        ),
        (
            "a duplicated seat",
            record(
                "m-dup-seat",
                vec![
                    seat(0, "engine-a", "1", true, 15),
                    seat(0, "engine-b", "1", false, 12),
                ],
            ),
        ),
        ("a completed match with no winner", {
            let mut value = pair("m-no-winner", true);
            value.seats[0].won = false;
            value.seats[0].rank = Some(0);
            value
        }),
        ("a verified replay with no binding", {
            let mut value = pair("m-bare-verified", true);
            value.replay = league::ReplayBindingV1 {
                document_hash: None,
                final_hash: None,
                storage: Some(ReplayStorage::Absent),
                path: None,
                verification: Some(ReplayVerification::Verified),
            };
            value
        }),
        ("an unverified match carrying a replay binding", {
            let mut value = pair("m-fake-replay", true);
            value.replay.verification = Some(ReplayVerification::Unavailable);
            value
        }),
        ("an aborted match with a winner", {
            let mut value = unfinished("m-aborted-winner", MatchStatus::Aborted);
            value.seats[0].won = true;
            value
        }),
        ("an empty source identity", {
            let mut value = pair("m-empty", true);
            value.source_identity = "  ".to_string();
            value
        }),
    ];

    for (label, value) in rejected {
        let error = ingest_match(&mut conn, &value).unwrap_err();
        assert!(
            matches!(error, StudioLeagueError::Invalid(_)),
            "{label}: expected a structural rejection, got {error}"
        );
    }
    assert_eq!(match_count(&conn).unwrap(), 0, "nothing may be written");
    assert_eq!(rating_event_count(&conn).unwrap(), 0);
}

/// Proof 2: the rating identity is a protocol constant, not a caller input.
#[test]
fn rating_config_cannot_drift() {
    let mut conn = open_in_memory().unwrap();
    ingest_match(&mut conn, &pair("m-1", true)).unwrap();
    assert_eq!(
        stored_rating_config(&conn).unwrap().unwrap(),
        protocol_rating_config(),
        "the build's protocol config is recorded as integrity evidence"
    );

    let matches_before = match_count(&conn).unwrap();
    let events_before = rating_event_count(&conn).unwrap();

    // Simulate a database written by a different Studio Elo protocol: the stored
    // evidence must not be silently accepted, and nothing may be written.
    let mut drifted = protocol_rating_config();
    drifted.k_factor = 64;
    league::set_meta(
        &conn,
        league::schema::RATING_CONFIG_META_KEY,
        &drifted.to_json().unwrap(),
    )
    .unwrap();
    let error = ingest_match(&mut conn, &pair("m-2", true)).unwrap_err();
    assert!(
        matches!(error, StudioLeagueError::RatingConfig(_)),
        "expected a config rejection, got {error}"
    );
    assert_eq!(match_count(&conn).unwrap(), matches_before, "zero mutation");
    assert_eq!(rating_event_count(&conn).unwrap(), events_before);

    // A rebuild refuses the same database instead of recomputing it under a
    // different protocol.
    assert!(matches!(
        rebuild_ratings(&mut conn).unwrap_err(),
        StudioLeagueError::RatingConfig(_)
    ));
}

/// Commit A Repair 2, P1-2: every read path uses the protocol constant, so no
/// caller has a rating config to forget. (`rebuild_ratings` and the read helpers
/// have no config parameter at all — that is the compile-time half of this proof;
/// the delete-and-rebuild test below is the runtime half.)
#[test]
fn rating_reads_and_rebuild_need_no_caller_config() {
    let mut conn = open_in_memory().unwrap();
    ingest_match(&mut conn, &pair("m-1", true)).unwrap();
    let a = participant_id_for_identity("engine-a@1");
    assert_eq!(participant_elo(&conn, &a).unwrap(), 1516.0);
    assert_eq!(leaderboard(&conn).unwrap().len(), 2);
    assert_eq!(rebuild_ratings(&mut conn).unwrap(), 2);
    assert_eq!(participant_elo(&conn, &a).unwrap(), 1516.0);
}

#[test]
fn rebuild_uses_the_protocol_config_and_refuses_a_database_without_evidence() {
    let mut conn = open_in_memory().unwrap();
    ingest_match(&mut conn, &pair("m-1", true)).unwrap();
    ingest_match(&mut conn, &pair("m-2", false)).unwrap();

    let before = league_snapshot!(conn);
    let events = rebuild_ratings(&mut conn).unwrap();
    assert_eq!(events, 4);
    let after = league_snapshot!(conn);
    assert_eq!(
        before, after,
        "rebuild must reproduce the identical history"
    );

    let fresh = open_in_memory().unwrap();
    assert!(
        rebuild_ratings(&mut { fresh }).is_err(),
        "a database with no stored config cannot be rebuilt"
    );
}

/// Proof 1: the same evidence plus the same manifest rebuilds the same league.
#[test]
fn same_evidence_and_manifest_rebuild_the_identical_league() {
    let dir = std::env::temp_dir().join(format!(
        "splendor-studio-league-rebuild-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let db_path = dir.join("league.sqlite3");
    let manifest_path = dir.join("identity.json");

    let mut records = Vec::new();
    for (index, (a, b, a_wins)) in [
        ("engine-a", "engine-b", true),
        ("engine-a", "engine-c", false),
        ("engine-b", "engine-c", true),
        ("engine-a", "engine-b", false),
        ("engine-b", "engine-c", false),
        ("engine-a", "engine-c", true),
    ]
    .into_iter()
    .enumerate()
    {
        records.push(record(
            &format!("m-{index}"),
            vec![
                seat(0, a, "1", a_wins, if a_wins { 15 } else { 11 }),
                seat(1, b, "1", !a_wins, if a_wins { 11 } else { 15 }),
            ],
        ));
    }

    // A single engine identity is merged into another explicitly. The manifest
    // stores the canonical *identity key*, never a participant id.
    let mut manifest = IdentityManifestV1::load_or_create(&manifest_path, "Nick").unwrap();
    manifest.declare_alias("engine-legacy@1", "engine-a@1", "historical rename");
    manifest.save(&manifest_path).unwrap();

    let build = |records: &[StudioMatchRecordV1]| {
        let mut conn = open_league(&db_path).unwrap();
        sync_identity_manifest(&conn, &manifest, NOW).unwrap();
        ingest_batch_canonical(&mut conn, records).unwrap();
        let snapshot = league_snapshot!(conn);
        drop(conn);
        snapshot
    };

    let first = build(&records);
    // Delete the derived database entirely.
    std::fs::remove_file(&db_path).unwrap();
    assert!(!db_path.exists());

    // Rebuild from the same corpus, but hand the evidence over in a different
    // order: the canonical sort must decide the league positions.
    let manifest_reloaded = IdentityManifestV1::load(&manifest_path).unwrap().unwrap();
    assert_eq!(
        manifest_reloaded.hash().unwrap(),
        manifest.hash().unwrap(),
        "the manifest round-trips through disk"
    );
    assert!(manifest_reloaded
        .alias_target_identity_key("engine-legacy@1")
        .is_some());
    let mut reversed = records.clone();
    reversed.reverse();
    let second = build(&reversed);

    let (identities_a, alias_rows_a, order_a, histories_a, board_a) = &first;
    let (identities_b, alias_rows_b, order_b, histories_b, board_b) = &second;
    assert_eq!(
        identities_a, identities_b,
        "participant ids must be reproducible"
    );
    assert_eq!(alias_rows_a, alias_rows_b, "aliases must survive a rebuild");
    assert_eq!(order_a, order_b, "league ordering must be reproducible");
    assert_eq!(histories_a, histories_b, "Elo history must be reproducible");
    assert_eq!(board_a, board_b, "the leaderboard must be reproducible");

    // And the league is not empty or trivially equal by accident.
    assert_eq!(identities_a.len(), 3);
    assert_eq!(order_a.len(), 6);
    assert_eq!(board_a.iter().map(|row| row.rated_games).sum::<u32>(), 12);

    // Anti-vacuity: the same comparison must *reject* a different corpus, so the
    // equality above is a real claim rather than a tautology.
    let mut different = records.clone();
    different[0].seats[1] = seat(1, "engine-d", "1", false, 15);
    std::fs::remove_file(&db_path).unwrap();
    let third = build(&different);
    assert_ne!(
        first, third,
        "a different participant set must produce a different league"
    );

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn canonical_league_order_ignores_input_order() {
    let records: Vec<StudioMatchRecordV1> = (0..5)
        .map(|index| {
            let mut value = pair(&format!("m-{index}"), index % 2 == 0);
            value.played_at = Some(NOW + index as i64);
            value
        })
        .collect();
    let forward = canonical_league_order(&records);
    let mut reversed = records.clone();
    reversed.reverse();
    let backward = canonical_league_order(&reversed);

    let forward_ids: Vec<String> = forward
        .iter()
        .map(|&index| records[index].source_identity.clone())
        .collect();
    let backward_ids: Vec<String> = backward
        .iter()
        .map(|&index| reversed[index].source_identity.clone())
        .collect();
    assert_eq!(forward_ids, backward_ids);
}

#[test]
fn league_seq_is_monotonic_and_orders_the_elo_history() {
    let mut conn = open_in_memory().unwrap();
    for index in 0..4 {
        ingest_match(&mut conn, &pair(&format!("m-{index}"), index % 2 == 0)).unwrap();
    }
    let history = rating_history(&conn, &participant_id_for_identity("engine-a@1")).unwrap();
    let seqs: Vec<i64> = history.iter().map(|e| e.league_seq).collect();
    let mut sorted = seqs.clone();
    sorted.sort_unstable();
    assert_eq!(seqs, sorted);
    assert_eq!(seqs, vec![1, 2, 3, 4]);
}

#[test]
fn explicit_aliases_merge_identities_and_nothing_else_does() {
    let mut conn = open_in_memory().unwrap();
    let canonical = resolve_engine_participant(
        &conn,
        &EngineIdentityV1::new("effective-splendor-s3-rollout-v1", "1"),
        "S3 Rollout",
        NOW,
    )
    .unwrap();
    ingest_match(
        &mut conn,
        &record(
            "m-a",
            vec![
                seat(0, "effective-splendor-s3-rollout-v1", "1", true, 15),
                seat(1, "engine-b", "1", false, 12),
            ],
        ),
    )
    .unwrap();
    ingest_match(
        &mut conn,
        &record(
            "m-b",
            vec![
                seat(0, "s3-rollout-v1", "1", true, 15),
                seat(1, "engine-b", "1", false, 12),
            ],
        ),
    )
    .unwrap();
    assert_eq!(
        leaderboard(&conn).unwrap().len(),
        3,
        "display/name variants are never auto-merged"
    );

    // Only an explicit, manifest-authored alias merges it. The manifest
    // projection is derived state, so it is synced on a clean connection
    // (a non-empty ledger refuses altered manifests to prevent desync).
    let conn_merged = open_in_memory().unwrap();
    let mut manifest = IdentityManifestV1::new();
    manifest.declare_alias(
        "s3-rollout-v1@1",
        "effective-splendor-s3-rollout-v1@1",
        "historical rename",
    );
    sync_identity_manifest(&conn_merged, &manifest, NOW).unwrap();
    let merged = resolve_engine_participant(
        &conn_merged,
        &EngineIdentityV1::new("s3-rollout-v1", "1"),
        "whatever",
        NOW,
    )
    .unwrap();
    assert_eq!(
        merged, canonical,
        "the alias resolves to the canonical participant id"
    );
}

// ---------------------------------------------------------------------------
// Commit A Repair 2 proof tests (P1-1, P1-2, P1-3, P1-4, P2).
// ---------------------------------------------------------------------------

/// P1-1: an alias is `alias_key -> canonical_identity_key`, so the participant id
/// is always the one derived from the canonical key — whichever of the two keys
/// the corpus mentions first, and with no separate resolution order in the ledger
/// that could disagree.
#[test]
fn alias_resolution_does_not_depend_on_which_key_appears_first() {
    let build = |first_key: &str| {
        let conn = open_in_memory().unwrap();
        // The manifest is synced before any corpus ingestion, so the alias target
        // participant does not exist yet: the case that used to break and the case
        // the ledger's own alias lookup used to short-circuit.
        let mut manifest = IdentityManifestV1::new();
        manifest.declare_alias("legacy-engine@1", "canonical-engine@1", "rename");
        sync_identity_manifest(&conn, &manifest, NOW).unwrap();
        let identity = EngineIdentityV1::new(first_key, "1");
        let id = resolve_engine_participant(&conn, &identity, "label", NOW).unwrap();
        (conn, id)
    };

    let (conn_alias_first, id_when_alias_seen_first) = build("legacy-engine");
    let (_, id_when_canonical_seen_first) = build("canonical-engine");

    assert_eq!(
        id_when_alias_seen_first, id_when_canonical_seen_first,
        "declaration/encounter order must not change the participant id"
    );
    assert_eq!(
        id_when_alias_seen_first,
        participant_id_for_identity("canonical-engine@1"),
        "the id is derived from the canonical identity key"
    );
    assert_eq!(
        canonical_identity_key(&conn_alias_first, "legacy-engine@1").unwrap(),
        "canonical-engine@1"
    );
    assert_eq!(
        participant(&conn_alias_first, &id_when_alias_seen_first)
            .unwrap()
            .unwrap()
            .identity_key
            .as_deref(),
        Some("canonical-engine@1"),
        "the row registers the canonical identity key, never the alias key"
    );

    // The ledger's seat resolution must take the same single path, so ingesting a
    // match whose seat uses the alias key cannot create a second participant.
    let mut conn = open_in_memory().unwrap();
    let mut manifest = IdentityManifestV1::new();
    manifest.declare_alias("legacy-engine@1", "canonical-engine@1", "rename");
    sync_identity_manifest(&conn, &manifest, NOW).unwrap();
    ingest_match(
        &mut conn,
        &record(
            "m-alias-first",
            vec![
                seat(0, "legacy-engine", "1", true, 15),
                seat(1, "other-engine", "1", false, 12),
            ],
        ),
    )
    .unwrap();
    assert_eq!(
        participant(&conn, &participant_id_for_identity("canonical-engine@1"))
            .unwrap()
            .expect("an alias-first seat must create the canonical participant")
            .identity_key
            .as_deref(),
        Some("canonical-engine@1")
    );
    assert_eq!(
        leaderboard(&conn).unwrap().len(),
        2,
        "the alias key must not become a third participant"
    );
}

/// P1-3: a source with no stable content hash is un-ingestable, so
/// `None == None` can never make two different hashless documents look idempotent.
#[test]
fn a_source_without_a_valid_document_hash_is_refused() {
    let mut conn = open_in_memory().unwrap();
    let bad_hashes = [
        String::new(),
        "   ".to_string(),
        "abc".to_string(),
        "A".repeat(64),
        "z".repeat(64),
        "a".repeat(63),
        "a".repeat(65),
        format!("{}g", "a".repeat(63)),
    ];
    for bad in bad_hashes {
        let mut value = pair("m-hashless", true);
        value.source_document_hash = bad.clone();
        let error = ingest_match(&mut conn, &value).unwrap_err();
        assert!(
            matches!(error, StudioLeagueError::Invalid(_)),
            "hash `{bad}` must be refused, got {error}"
        );
    }
    assert_eq!(match_count(&conn).unwrap(), 0, "nothing may be written");
    assert_eq!(rating_event_count(&conn).unwrap(), 0);

    // The valid form still ingests.
    ingest_match(&mut conn, &pair("m-ok", true)).unwrap();
    assert_eq!(match_count(&conn).unwrap(), 1);
}

/// P1-4: a historical batch shares one transaction, so a failure at record N
/// leaves nothing behind — no match, no rating event, no participant, no config
/// evidence.
#[test]
fn a_late_batch_failure_rolls_the_entire_batch_back() {
    let mut conn = open_in_memory().unwrap();
    let mut records = vec![pair("m-1", true), pair("m-2", false), pair("m-3", true)];
    // Record 3 reuses record 1's key with different content: a source conflict
    // that can only be detected after the first two records were written.
    records[2].source_identity = "m-1".to_string();
    records[2].source_document_hash = hex64("m-1-drifted");

    let error = ingest_batch_canonical(&mut conn, &records).unwrap_err();
    assert!(
        matches!(error, StudioLeagueError::SourceConflict { .. }),
        "expected a source conflict, got {error}"
    );

    assert_eq!(match_count(&conn).unwrap(), 0, "no match may survive");
    assert_eq!(
        rating_event_count(&conn).unwrap(),
        0,
        "no rating event may survive"
    );
    assert_eq!(
        identity_index(&conn).unwrap().len(),
        0,
        "no participant side effect may survive"
    );
    assert_eq!(aliases(&conn).unwrap().len(), 0);
    assert!(
        stored_rating_config(&conn).unwrap().is_none(),
        "the config evidence is written inside the same transaction"
    );

    // And the same batch succeeds once the conflict is removed.
    records[2].source_identity = "m-3".to_string();
    records[2].source_document_hash = hex64("m-3");
    assert_eq!(
        ingest_batch_canonical(&mut conn, &records).unwrap().len(),
        3
    );
    assert_eq!(match_count(&conn).unwrap(), 3);
}

/// P2: Windows replaces a file with remove + rename, so a crash in that window
/// can delete the only user-authored identity file. `save` leaves a synced
/// staging copy and a backup, and `load_or_recover` heals the primary.
#[test]
fn the_identity_manifest_survives_losing_its_primary_file() {
    let dir = std::env::temp_dir().join(format!(
        "splendor-studio-league-manifest-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("identity.json");

    let mut first = IdentityManifestV1::new();
    first.ensure_local_human("Nick");
    let local = first.local_human.clone().unwrap().participant_id;
    first.save(&path).unwrap();

    let mut second = first.clone();
    second.declare_alias("legacy@1", "canonical@1", "rename");

    // Exactly the interrupted-replace state: the freshly written staging copy
    // exists, the primary has been removed, the rename has not happened yet.
    second.save(&league::temp_path(&path)).unwrap();
    std::fs::remove_file(&path).unwrap();
    assert!(!path.exists());

    let recovered = IdentityManifestV1::load_or_recover(&path)
        .unwrap()
        .expect("the manifest must recover from its staging copy");
    assert_eq!(recovered.hash().unwrap(), second.hash().unwrap());
    assert_eq!(
        recovered.local_human.clone().unwrap().participant_id,
        local,
        "the recovered identity keeps its id"
    );
    assert_eq!(
        recovered.alias_target_identity_key("legacy@1"),
        Some("canonical@1")
    );
    assert!(path.is_file(), "recovery heals the primary");

    // Recovery also works from the backup when the staging copy is gone too.
    std::fs::copy(&path, league::backup_path(&path)).unwrap();
    std::fs::remove_file(&path).unwrap();
    let from_backup = IdentityManifestV1::load_or_recover(&path)
        .unwrap()
        .expect("the manifest must recover from its backup");
    assert_eq!(from_backup.hash().unwrap(), second.hash().unwrap());
    assert!(path.is_file(), "backup recovery heals the primary as well");

    let _ = std::fs::remove_dir_all(&dir);
}

/// Close patch P1-1: damaged identity evidence is not a first launch. When all
/// recovery candidates are unusable, `load_or_create` must preserve the evidence
/// and fail instead of minting a replacement local-human id.
#[test]
fn unrecoverable_identity_manifest_fails_closed_without_replacing_identity() {
    let dir = std::env::temp_dir().join(format!(
        "splendor-studio-league-manifest-corrupt-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("identity.json");
    let original = b"{ corrupt authoritative identity";
    std::fs::write(&path, original).unwrap();
    std::fs::write(league::temp_path(&path), b"not json either").unwrap();
    // `.bak` deliberately absent: the contract covers invalid *or* missing
    // recovery siblings once any identity evidence exists.

    let error = IdentityManifestV1::load_or_create(&path, "Replacement").unwrap_err();
    assert!(
        matches!(error, StudioLeagueError::Invalid(_)),
        "unrecoverable identity evidence must fail closed, got {error}"
    );
    assert_eq!(
        std::fs::read(&path).unwrap(),
        original,
        "the authoritative bytes must be left untouched"
    );
    assert_eq!(
        std::fs::read(league::temp_path(&path)).unwrap(),
        b"not json either",
        "the failed recovery must not overwrite its evidence"
    );
    assert!(!league::backup_path(&path).exists());

    // Only the true first-run state — all three candidates absent — may create.
    std::fs::remove_file(&path).unwrap();
    std::fs::remove_file(league::temp_path(&path)).unwrap();
    let created = IdentityManifestV1::load_or_create(&path, "First run").unwrap();
    assert_eq!(created.local_human.unwrap().display_name, "First run");

    let _ = std::fs::remove_dir_all(&dir);
}

/// Close patch P1-2: the resolver follows one edge by contract, so every
/// accepted alias must point directly to a terminal canonical key. Both a chain
/// and a cycle are malformed V2 manifests.
#[test]
fn non_terminal_and_cyclic_aliases_are_rejected() {
    let mut chain = IdentityManifestV1::new();
    chain.declare_alias("old@1", "middle@1", "old rename");
    chain.declare_alias("middle@1", "current@1", "current rename");
    let chain_error = chain.validate().unwrap_err();
    assert!(
        matches!(chain_error, StudioLeagueError::Invalid(_)),
        "an alias chain must be rejected, got {chain_error}"
    );

    let mut cycle = IdentityManifestV1::new();
    cycle.declare_alias("a@1", "b@1", "cycle-a");
    cycle.declare_alias("b@1", "a@1", "cycle-b");
    let cycle_error = cycle.validate().unwrap_err();
    assert!(
        matches!(cycle_error, StudioLeagueError::Invalid(_)),
        "an alias cycle must be rejected, got {cycle_error}"
    );
}

#[test]
fn sync_identity_manifest_on_non_empty_ledger_rejects_altered_manifest_and_requires_rebuild() {
    let mut conn = open_in_memory().unwrap();
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Alice");
    manifest.declare_alias("engine-old@1", "engine-a@1", "initial alias");
    sync_identity_manifest(&conn, &manifest, NOW).unwrap();

    let stored_hash = league::stored_identity_manifest_hash(&conn)
        .unwrap()
        .unwrap();
    assert_eq!(stored_hash, manifest.hash().unwrap());

    // Ingest one match into the ledger
    let match_record = pair("benchmarks/test/match-0.json", true);
    ingest_match(&mut conn, &match_record).unwrap();

    // Re-sync with the IDENTICAL manifest succeeds
    sync_identity_manifest(&conn, &manifest, NOW).unwrap();

    // Now alter the manifest (add an alias)
    manifest.declare_alias("engine-legacy@1", "engine-b@1", "new alias");
    assert_ne!(manifest.hash().unwrap(), stored_hash);

    // Syncing an altered manifest into a non-empty ledger MUST fail closed
    let err = sync_identity_manifest(&conn, &manifest, NOW).unwrap_err();
    assert!(
        matches!(err, StudioLeagueError::Invalid(_)),
        "altered manifest on non-empty ledger must fail closed, got {err}"
    );
}

#[test]
fn sync_identity_manifest_on_non_empty_ledger_rejects_missing_stored_manifest_hash() {
    let mut conn = open_in_memory().unwrap();
    let match_record = pair("benchmarks/test/match-legacy.json", true);
    ingest_match(&mut conn, &match_record).unwrap();

    // The database has matches but was never synced with an identity manifest,
    // so `identity_manifest_hash` is missing.
    assert!(league::stored_identity_manifest_hash(&conn)
        .unwrap()
        .is_none());

    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Bob");

    let err = sync_identity_manifest(&conn, &manifest, NOW).unwrap_err();
    assert!(
        matches!(err, StudioLeagueError::Invalid(_)),
        "non-empty DB with missing manifest hash must fail closed, got {err}"
    );
}
