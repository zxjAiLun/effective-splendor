//! Commit A gates: identity, eligibility, the single Elo rule, idempotency and
//! rebuild determinism.

use league::{
    ensure_local_human, evaluate_eligibility, ingest_match, leaderboard, local_human_participant,
    open_in_memory, participant, participant_elo, rating_history, rebuild_ratings,
    rename_participant, resolve_engine_participant, schema_version, unassigned_human_participant,
    EligibilityInput, EngineIdentityV1, IngestOutcome, MatchStatus, ParticipantKind,
    RatingEligibility, ReplayStorage, ReplayVerification, StudioMatchRecordV1, StudioMatchSeatV1,
    StudioRatingConfigV1, REASON_ABORTED, REASON_DIAGNOSTIC, REASON_PLAYER_COUNT, REASON_REPLAY,
    REASON_RULESET, REASON_SELF_MATCH, REASON_TRUNCATED, REASON_UNMAPPED,
    SPLENDOR_BASE_V1_RULESET_FINGERPRINT, STUDIO_LEAGUE_SCHEMA_VERSION,
};
use splendor_studio_league as league;

const NOW: i64 = 1_700_000_000;

fn seat(index: u8, name: &str, version: &str, won: bool, score: i32) -> StudioMatchSeatV1 {
    StudioMatchSeatV1 {
        seat: index,
        identity: Some(EngineIdentityV1::new(name, version)),
        participant_id: None,
        display_name: None,
        score: Some(score),
        rank: Some(if won { 0 } else { 1 }),
        won,
    }
}

fn record(source_identity: &str, seats: Vec<StudioMatchSeatV1>) -> StudioMatchRecordV1 {
    StudioMatchRecordV1 {
        source_kind: "arena_report".to_string(),
        source_identity: source_identity.to_string(),
        source_path: Some(format!("benchmarks/{source_identity}.report.json")),
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

fn pair(source_identity: &str, a: bool) -> StudioMatchRecordV1 {
    record(
        source_identity,
        vec![
            seat(0, "engine-a", "1", a, if a { 15 } else { 12 }),
            seat(1, "engine-b", "1", !a, if a { 12 } else { 15 }),
        ],
    )
}

#[test]
fn schema_initialises_and_reports_its_version() {
    let conn = open_in_memory().unwrap();
    assert_eq!(schema_version(&conn).unwrap(), STUDIO_LEAGUE_SCHEMA_VERSION);
    // Idempotent re-initialisation.
    league::initialise(&conn).unwrap();
    assert_eq!(league::match_count(&conn).unwrap(), 0);
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
        participant(&conn, &first).unwrap().unwrap().display_name,
        "S3 Rollout",
        "a later label never renames an existing participant"
    );
}

#[test]
fn local_human_profile_is_created_once_and_renaming_keeps_the_id() {
    let conn = open_in_memory().unwrap();
    let id = ensure_local_human(&conn, "Nick", NOW).unwrap();
    assert_eq!(ensure_local_human(&conn, "ignored", NOW).unwrap(), id);
    assert_eq!(
        local_human_participant(&conn).unwrap().as_deref(),
        Some(id.as_str())
    );

    rename_participant(&conn, &id, "Nick (renamed)").unwrap();
    assert_eq!(ensure_local_human(&conn, "ignored", NOW).unwrap(), id);
    let row = participant(&conn, &id).unwrap().unwrap();
    assert_eq!(row.kind, ParticipantKind::Human);
    assert_eq!(row.display_name, "Nick (renamed)");
    assert!(
        row.identity_key.is_none(),
        "a human has no engine identity key"
    );
}

#[test]
fn unassigned_human_is_reserved_and_never_the_local_profile() {
    let conn = open_in_memory().unwrap();
    let local = ensure_local_human(&conn, "Nick", NOW).unwrap();
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
    evaluate_eligibility(
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
    let ok = |e: RatingEligibility| assert!(e.is_eligible(), "expected eligible: {e:?}");

    ok(eligibility(
        MatchStatus::Completed,
        2,
        SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
        ReplayVerification::Verified,
        both(),
        false,
    ));

    let reason = |e: RatingEligibility| e.reason().unwrap();
    assert_eq!(
        reason(eligibility(
            MatchStatus::Aborted,
            2,
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
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
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
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
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
            ReplayVerification::Verified,
            both(),
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
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
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
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
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
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
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
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
            ReplayVerification::Verified,
            vec![Some("p1".to_string()), None],
            false
        )),
        REASON_UNMAPPED
    );
    assert_eq!(
        reason(eligibility(
            MatchStatus::Completed,
            2,
            SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
            ReplayVerification::Verified,
            vec![Some("p1".to_string()), Some("p1".to_string())],
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

    // Identical to the frozen M16 live-Elo arithmetic, not a re-derivation.
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
    let config = StudioRatingConfigV1::default();
    let outcome = ingest_match(&mut conn, &config, &pair("m-1", true)).unwrap();
    assert!(outcome.was_inserted());

    let rows = leaderboard(&conn, &config).unwrap();
    assert_eq!(rows.len(), 2);
    assert_eq!(league::eligible_match_count(&conn).unwrap(), 1);

    let events: Vec<_> = rows
        .iter()
        .flat_map(|r| rating_history(&conn, &r.participant_id).unwrap())
        .collect();
    assert_eq!(events.len(), 2);
    let sum: f64 = events.iter().map(|e| e.delta).sum();
    assert_eq!(sum, 0.0, "Studio Elo is zero-sum");
    for event in &events {
        assert_eq!(event.algorithm, league::STUDIO_ELO_ALGORITHM_V1);
        assert_eq!(event.league_seq, 1);
    }

    let (winner_id, loser_id) = {
        let w = events.iter().find(|e| e.delta > 0.0).unwrap();
        (w.participant_id.clone(), w.opponent_id.clone())
    };
    assert_eq!(participant_elo(&conn, &winner_id, &config).unwrap(), 1516.0);
    assert_eq!(participant_elo(&conn, &loser_id, &config).unwrap(), 1484.0);
}

#[test]
fn ineligible_matches_are_recorded_but_rate_nobody() {
    let mut conn = open_in_memory().unwrap();
    let config = StudioRatingConfigV1::default();

    let mut aborted = pair("m-aborted", true);
    aborted.status = MatchStatus::Aborted;
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

    let mut unmapped = record(
        "m-unmapped",
        vec![
            seat(0, "engine-a", "1", true, 15),
            StudioMatchSeatV1 {
                seat: 1,
                identity: None,
                participant_id: None,
                display_name: None,
                score: Some(12),
                rank: Some(1),
                won: false,
            },
        ],
    );
    // Give the mapped seat an identity the league has never seen.
    unmapped.seats[0] = seat(0, "engine-never-seen", "9", true, 15);

    for record in [aborted, broken, diagnostic, self_match, unmapped] {
        let outcome = ingest_match(&mut conn, &config, &record).unwrap();
        assert!(outcome.was_inserted());
    }
    assert_eq!(league::match_count(&conn).unwrap(), 5);
    assert_eq!(
        league::eligible_match_count(&conn).unwrap(),
        0,
        "none of these matches may move Studio Elo"
    );
    let reasons: std::collections::HashMap<String, u64> = league::ineligible_reason_counts(&conn)
        .unwrap()
        .into_iter()
        .collect();
    assert_eq!(reasons.get(REASON_ABORTED), Some(&1));
    assert_eq!(reasons.get(REASON_REPLAY), Some(&1));
    assert_eq!(reasons.get(REASON_DIAGNOSTIC), Some(&1));
    assert_eq!(reasons.get(REASON_SELF_MATCH), Some(&1));
    assert_eq!(reasons.get(REASON_UNMAPPED), Some(&1));

    for row in leaderboard(&conn, &config).unwrap() {
        assert_eq!(row.rated_games, 0);
        assert!(rating_history(&conn, &row.participant_id)
            .unwrap()
            .is_empty());
        assert_eq!(row.elo, config.initial_elo, "ratings must not have moved");
    }
}

#[test]
fn ingest_is_idempotent_on_source_identity() {
    let mut conn = open_in_memory().unwrap();
    let config = StudioRatingConfigV1::default();
    let first = ingest_match(&mut conn, &config, &pair("m-1", true)).unwrap();
    let second = ingest_match(&mut conn, &config, &pair("m-1", true)).unwrap();
    match second {
        IngestOutcome::AlreadyPresent { match_id } => assert_eq!(match_id, first.match_id()),
        other => panic!("expected AlreadyPresent, got {other:?}"),
    }
    assert_eq!(league::match_count(&conn).unwrap(), 1);
    assert_eq!(league::eligible_match_count(&conn).unwrap(), 1);
    let elo = leaderboard(&conn, &config).unwrap();
    assert_eq!(
        elo.iter().map(|r| r.elo).max().unwrap(),
        1516,
        "Elo moved once, not twice"
    );
}

#[test]
fn rebuild_reproduces_identical_rating_events() {
    let mut conn = open_in_memory().unwrap();
    let config = StudioRatingConfigV1::default();
    // A small round robin so Elo order actually matters.
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
        let record = record(
            &format!("m-{index}"),
            vec![
                seat(0, a, "1", a_wins, if a_wins { 15 } else { 11 }),
                seat(1, b, "1", !a_wins, if a_wins { 11 } else { 15 }),
            ],
        );
        ingest_match(&mut conn, &config, &record).unwrap();
    }
    let before: Vec<Vec<league::RatingEventRow>> = leaderboard(&conn, &config)
        .unwrap()
        .iter()
        .map(|row| rating_history(&conn, &row.participant_id).unwrap())
        .collect();
    let elo_before: Vec<i32> = leaderboard(&conn, &config)
        .unwrap()
        .iter()
        .map(|r| r.elo)
        .collect();

    let events = rebuild_ratings(&mut conn, &config).unwrap();
    assert_eq!(events, 12, "6 eligible matches x 2 participants");

    let after: Vec<Vec<league::RatingEventRow>> = leaderboard(&conn, &config)
        .unwrap()
        .iter()
        .map(|row| rating_history(&conn, &row.participant_id).unwrap())
        .collect();
    assert_eq!(
        before, after,
        "rebuild must reproduce the exact Elo history"
    );
    let elo_after: Vec<i32> = leaderboard(&conn, &config)
        .unwrap()
        .iter()
        .map(|r| r.elo)
        .collect();
    assert_eq!(elo_before, elo_after);
}

#[test]
fn league_seq_is_monotonic_and_orders_the_elo_history() {
    let mut conn = open_in_memory().unwrap();
    let config = StudioRatingConfigV1::default();
    for index in 0..4 {
        ingest_match(
            &mut conn,
            &config,
            &pair(&format!("m-{index}"), index % 2 == 0),
        )
        .unwrap();
    }
    let rows = leaderboard(&conn, &config).unwrap();
    let history = rating_history(&conn, &rows[0].participant_id).unwrap();
    let seqs: Vec<i64> = history.iter().map(|e| e.league_seq).collect();
    let mut sorted = seqs.clone();
    sorted.sort_unstable();
    assert_eq!(seqs, sorted);
    assert_eq!(seqs, vec![1, 2, 3, 4]);
}

#[test]
fn explicit_aliases_merge_identities_and_nothing_else_does() {
    let mut conn = open_in_memory().unwrap();
    let config = StudioRatingConfigV1::default();
    let canonical = resolve_engine_participant(
        &conn,
        &EngineIdentityV1::new("effective-splendor-s3-rollout-v1", "1"),
        "S3 Rollout",
        NOW,
    )
    .unwrap();
    ingest_match(
        &mut conn,
        &config,
        &record(
            "m-a",
            vec![
                seat(0, "effective-splendor-s3-rollout-v1", "1", true, 15),
                seat(1, "engine-b", "1", false, 12),
            ],
        ),
    )
    .unwrap();

    // Without an alias the old spelling is a separate participant...
    ingest_match(
        &mut conn,
        &config,
        &record(
            "m-b",
            vec![
                seat(0, "s3-rollout-v1", "1", true, 15),
                seat(1, "engine-b", "1", false, 12),
            ],
        ),
    )
    .unwrap();
    let before = leaderboard(&conn, &config).unwrap().len();
    assert_eq!(before, 3, "display/name variants are never auto-merged");

    // ...and only an explicit alias merges it. (Retroactively reassigning matches
    // already ingested under the old key is commit B's job, not this one's.)
    league::alias_participants(&conn, "s3-rollout-v1@1", &canonical, "historical rename").unwrap();
    let merged = resolve_engine_participant(
        &conn,
        &EngineIdentityV1::new("s3-rollout-v1", "1"),
        "whatever",
        NOW,
    )
    .unwrap();
    assert_eq!(
        merged, canonical,
        "the alias resolves to the canonical participant"
    );
}
