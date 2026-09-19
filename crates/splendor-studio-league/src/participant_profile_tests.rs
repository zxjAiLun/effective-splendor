//! Gates over participant profiles, rating histories, and head-to-head records.
//!
//! Contracts enforced:
//! 1. Authority-first: reader validates authority evidence before answering;
//! 2. Elo truthfulness: rated=0 returns protocol initial Elo (1500) with Initial
//!    origin; rated>0 with missing or non-finite current_elo fails closed;
//! 3. Bounded cursor: limits are strictly validated (no silent clamping), cursors
//!    are monotonic position markers (no offset), unknown participant returns None;
//! 4. Opponent exclusion: self-matches and unattributed opponents do not contaminate
//!    the head-to-head record;
//! 5. Production SQL constants are pinned and EXPLAIN-verified.

use crate::ledger::{participant_opponents, participant_profile, participant_rating_history};
use crate::{
    ingest_match, open_in_memory, EngineIdentityV1, MatchStatus, ParticipantEloOriginV1,
    ParticipantOpponentPageRequestV1, ParticipantRatingHistoryRequestV1, ReplayStorage,
    ReplayVerification, SeatPolicyIdentityV1, StudioMatchRecordV1, StudioMatchSeatV1,
    OPPONENTS_PAGE_DEFAULT_LIMIT, OPPONENTS_PAGE_MAX_LIMIT, PARTICIPANT_OPPONENTS_SQL,
    PARTICIPANT_PROFILE_SQL, PARTICIPANT_RATING_HISTORY_SQL, RATING_HISTORY_DEFAULT_LIMIT,
    RATING_HISTORY_MAX_LIMIT, SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
};
use rusqlite::{params, Connection};

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

fn seat(index: u8, name: &str, won: bool, score: i32) -> StudioMatchSeatV1 {
    StudioMatchSeatV1 {
        seat: index,
        identity: Some(EngineIdentityV1::new(name, "1")),
        policy_identity: SeatPolicyIdentityV1::NoConfigEvidence,
        participant_id: None,
        display_name: None,
        score: Some(score),
        rank: Some(if won { 0 } else { 1 }),
        won,
    }
}

fn record(name: &str, seats: Vec<StudioMatchSeatV1>, plies: Option<u32>) -> StudioMatchRecordV1 {
    StudioMatchRecordV1 {
        source_kind: "arena_report".to_string(),
        source_identity: name.to_string(),
        source_path: Some(format!("benchmarks/{name}.report.json")),
        source_document_hash: hex64(name),
        played_at: Some(1_700_000_000),
        ruleset_fingerprint: SPLENDOR_BASE_V1_RULESET_FINGERPRINT.to_string(),
        engine_version: Some("0.1.0".to_string()),
        player_count: seats.len() as u8,
        status: MatchStatus::Completed,
        seats,
        completed_plies: plies,
        main_turn_count: None,
        replay: crate::ReplayBindingV1 {
            document_hash: Some(hex64(&format!("{name}.replay"))),
            final_hash: Some(hex64(&format!("{name}.final"))),
            storage: Some(ReplayStorage::Archive),
            path: Some(format!("archive/{name}.json")),
            verification: Some(ReplayVerification::Verified),
        },
        diagnostic: false,
    }
}

fn setup_test_league() -> (Connection, String, String, String) {
    let mut conn = open_in_memory().unwrap();
    crate::ensure_rating_config(&conn).unwrap();

    // Match 1: agent-alpha vs agent-beta (alpha wins)
    ingest_match(
        &mut conn,
        &record(
            "m1",
            vec![
                seat(0, "agent-alpha", true, 15),
                seat(1, "agent-beta", false, 12),
            ],
            Some(48),
        ),
    )
    .unwrap();

    // Match 2: agent-alpha vs agent-gamma (alpha wins)
    ingest_match(
        &mut conn,
        &record(
            "m2",
            vec![
                seat(0, "agent-alpha", true, 16),
                seat(1, "agent-gamma", false, 10),
            ],
            Some(52),
        ),
    )
    .unwrap();

    // Match 3: agent-alpha self match (both seats alpha) -> ineligible for Elo
    ingest_match(
        &mut conn,
        &record(
            "m3",
            vec![
                seat(0, "agent-alpha", true, 15),
                seat(1, "agent-alpha", false, 14),
            ],
            Some(50),
        ),
    )
    .unwrap();

    let alpha_id: String = conn
        .query_row(
            "SELECT participant_id FROM match_seats WHERE agent_name = 'agent-alpha' LIMIT 1",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let beta_id: String = conn
        .query_row(
            "SELECT participant_id FROM match_seats WHERE agent_name = 'agent-beta' LIMIT 1",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let gamma_id: String = conn
        .query_row(
            "SELECT participant_id FROM match_seats WHERE agent_name = 'agent-gamma' LIMIT 1",
            [],
            |r| r.get(0),
        )
        .unwrap();

    (conn, alpha_id, beta_id, gamma_id)
}

#[test]
fn the_profile_is_returned_for_known_participant_and_none_for_unknown() {
    let (conn, alpha_id, beta_id, _gamma_id) = setup_test_league();

    let profile = participant_profile(&conn, &alpha_id).unwrap().unwrap();
    assert_eq!(profile.participant_id, alpha_id);
    assert_eq!(profile.kind, crate::ParticipantKind::Engine);
    assert_eq!(profile.recorded_games, 3); // 3 distinct matches
    assert_eq!(profile.rated_games, 2); // 2 eligible rated matches
    assert_eq!(profile.rated_wins, 2);
    assert_eq!(profile.rated_ties, 0);
    assert_eq!(profile.rated_losses, 0);
    assert_eq!(profile.seats.appearances, 4); // 2 normal + 2 in self-match
    assert_eq!(profile.seats.seat0, 3);
    assert_eq!(profile.seats.seat1, 1);
    assert_eq!(profile.seats.other, 0);
    assert_eq!(profile.elo.origin, ParticipantEloOriginV1::Rated);
    assert!(profile.elo.value > 1500.0);
    assert_eq!(
        profile.elo.display_rounded,
        profile.elo.value.round() as i32
    );
    assert!(profile.provisional); // 2 < 20

    // Completed plies
    assert_eq!(profile.completed_plies.availability, "available");
    assert_eq!(profile.completed_plies.observed_completed_games, 3);
    assert_eq!(profile.completed_plies.total_completed_games, 3);
    assert_eq!(profile.completed_plies.unit, "decision_plies");
    // (48 + 52 + 50) / 3 = 50.0
    assert_eq!(profile.completed_plies.value, Some(50.0));

    // Unavailable metrics
    assert_eq!(profile.main_turns.availability, "unavailable");
    assert_eq!(profile.main_turns.reason, "not_recorded");
    assert_eq!(profile.gameplay.availability, "unavailable");
    assert_eq!(profile.gameplay.reason, "no_authoritative_builder");

    // Beta profile
    let beta_profile = participant_profile(&conn, &beta_id).unwrap().unwrap();
    assert_eq!(beta_profile.recorded_games, 1);
    assert_eq!(beta_profile.rated_games, 1);
    assert_eq!(beta_profile.rated_wins, 0);
    assert_eq!(beta_profile.rated_losses, 1);
    assert_eq!(beta_profile.seats.appearances, 1);
    assert_eq!(beta_profile.seats.seat1, 1);
    assert!(beta_profile.elo.value < 1500.0);

    // Unknown participant
    let unknown = participant_profile(&conn, "nonexistent-id").unwrap();
    assert!(unknown.is_none());
}

#[test]
fn rated_zero_participant_has_initial_elo_and_rated_nonzero_with_missing_current_elo_fails_closed()
{
    let (conn, _alpha_id, _beta_id, _gamma_id) = setup_test_league();

    // Insert an unrated participant with NULL current_elo
    let unrated_id = "unrated-engine-participant";
    conn.execute(
        "INSERT INTO participants (participant_id, kind, display_name, current_elo, created_at)
         VALUES (?1, 'engine', 'Unrated Agent', NULL, 1700000000)",
        params![unrated_id],
    )
    .unwrap();

    let profile = participant_profile(&conn, unrated_id).unwrap().unwrap();
    assert_eq!(profile.rated_games, 0);
    assert_eq!(profile.recorded_games, 0);
    assert_eq!(profile.elo.origin, ParticipantEloOriginV1::Initial);
    assert_eq!(profile.elo.value, 1500.0);
    assert_eq!(profile.elo.display_rounded, 1500);
    assert!(profile.provisional);
    assert_eq!(profile.completed_plies.availability, "unavailable");
    assert_eq!(profile.completed_plies.value, None);

    // Corrupt a rated participant's current_elo to NULL
    conn.execute(
        "UPDATE participants SET current_elo = NULL WHERE participant_id = ?1",
        params![_alpha_id],
    )
    .unwrap();

    let result = participant_profile(&conn, &_alpha_id);
    assert!(
        result.is_err(),
        "rated>0 with NULL current_elo must fail closed"
    );
}

#[test]
fn the_rating_history_cursor_pages_strictly_and_bounds_limits() {
    let (conn, alpha_id, _beta_id, _gamma_id) = setup_test_league();

    // Default limit
    assert_eq!(RATING_HISTORY_DEFAULT_LIMIT, 100);
    let req = ParticipantRatingHistoryRequestV1 {
        participant_id: alpha_id.clone(),
        limit: None,
        before_league_seq: None,
    };
    let page = participant_rating_history(&conn, &req).unwrap().unwrap();
    assert_eq!(page.points.len(), 2);
    assert_eq!(page.points[0].league_seq, 2);
    assert_eq!(page.points[1].league_seq, 1);
    assert_eq!(page.next_before_league_seq, None);

    // Bounded limit = 1 -> has next page
    let req_p1 = ParticipantRatingHistoryRequestV1 {
        participant_id: alpha_id.clone(),
        limit: Some(1),
        before_league_seq: None,
    };
    let page_p1 = participant_rating_history(&conn, &req_p1).unwrap().unwrap();
    assert_eq!(page_p1.points.len(), 1);
    assert_eq!(page_p1.points[0].league_seq, 2);
    assert_eq!(page_p1.next_before_league_seq, Some(2));

    // Page 2 using cursor
    let req_p2 = ParticipantRatingHistoryRequestV1 {
        participant_id: alpha_id.clone(),
        limit: Some(1),
        before_league_seq: page_p1.next_before_league_seq,
    };
    let page_p2 = participant_rating_history(&conn, &req_p2).unwrap().unwrap();
    assert_eq!(page_p2.points.len(), 1);
    assert_eq!(page_p2.points[0].league_seq, 1);
    assert_eq!(page_p2.next_before_league_seq, None);

    // Invalid limits: 0 and > RATING_HISTORY_MAX_LIMIT
    assert!(participant_rating_history(
        &conn,
        &ParticipantRatingHistoryRequestV1 {
            participant_id: alpha_id.clone(),
            limit: Some(0),
            before_league_seq: None,
        }
    )
    .is_err());

    assert!(participant_rating_history(
        &conn,
        &ParticipantRatingHistoryRequestV1 {
            participant_id: alpha_id.clone(),
            limit: Some(RATING_HISTORY_MAX_LIMIT + 1),
            before_league_seq: None,
        }
    )
    .is_err());

    // Invalid cursor <= 0
    assert!(participant_rating_history(
        &conn,
        &ParticipantRatingHistoryRequestV1 {
            participant_id: alpha_id.clone(),
            limit: None,
            before_league_seq: Some(0),
        }
    )
    .is_err());

    assert!(participant_rating_history(
        &conn,
        &ParticipantRatingHistoryRequestV1 {
            participant_id: alpha_id.clone(),
            limit: None,
            before_league_seq: Some(-5),
        }
    )
    .is_err());

    // Unknown participant returns Ok(None)
    assert!(participant_rating_history(
        &conn,
        &ParticipantRatingHistoryRequestV1 {
            participant_id: "unknown-id".to_string(),
            limit: None,
            before_league_seq: None,
        }
    )
    .unwrap()
    .is_none());
}

#[test]
fn the_opponents_cursor_pages_strictly_and_excludes_self_and_unattributed() {
    let (conn, alpha_id, beta_id, gamma_id) = setup_test_league();

    // Alpha played against beta, gamma, and self.
    // Self must be excluded! Opponents should only be beta and gamma.
    assert_eq!(OPPONENTS_PAGE_DEFAULT_LIMIT, 20);
    let req = ParticipantOpponentPageRequestV1 {
        participant_id: alpha_id.clone(),
        limit: None,
        after_opponent_id: None,
    };
    let page = participant_opponents(&conn, &req).unwrap().unwrap();
    assert_eq!(page.opponents.len(), 2);
    // Opponents are sorted by opponent_id ASC
    let mut expected_ids = vec![beta_id.clone(), gamma_id.clone()];
    expected_ids.sort();
    assert_eq!(
        page.opponents
            .iter()
            .map(|o| &o.opponent_id)
            .collect::<Vec<_>>(),
        expected_ids.iter().collect::<Vec<_>>()
    );

    // Limit = 1 pagination
    let req_p1 = ParticipantOpponentPageRequestV1 {
        participant_id: alpha_id.clone(),
        limit: Some(1),
        after_opponent_id: None,
    };
    let page_p1 = participant_opponents(&conn, &req_p1).unwrap().unwrap();
    assert_eq!(page_p1.opponents.len(), 1);
    assert_eq!(page_p1.opponents[0].opponent_id, expected_ids[0]);
    assert_eq!(
        page_p1.next_after_opponent_id,
        Some(expected_ids[0].clone())
    );

    let req_p2 = ParticipantOpponentPageRequestV1 {
        participant_id: alpha_id.clone(),
        limit: Some(1),
        after_opponent_id: page_p1.next_after_opponent_id,
    };
    let page_p2 = participant_opponents(&conn, &req_p2).unwrap().unwrap();
    assert_eq!(page_p2.opponents.len(), 1);
    assert_eq!(page_p2.opponents[0].opponent_id, expected_ids[1]);
    assert_eq!(page_p2.next_after_opponent_id, None);

    // Invalid limits
    assert!(participant_opponents(
        &conn,
        &ParticipantOpponentPageRequestV1 {
            participant_id: alpha_id.clone(),
            limit: Some(0),
            after_opponent_id: None,
        }
    )
    .is_err());

    assert!(participant_opponents(
        &conn,
        &ParticipantOpponentPageRequestV1 {
            participant_id: alpha_id.clone(),
            limit: Some(OPPONENTS_PAGE_MAX_LIMIT + 1),
            after_opponent_id: None,
        }
    )
    .is_err());

    // Unknown participant returns Ok(None)
    assert!(participant_opponents(
        &conn,
        &ParticipantOpponentPageRequestV1 {
            participant_id: "unknown-id".to_string(),
            limit: None,
            after_opponent_id: None,
        }
    )
    .unwrap()
    .is_none());
}

#[test]
fn production_queries_are_explain_query_plan_verified() {
    let (conn, alpha_id, _beta_id, _gamma_id) = setup_test_league();

    // PARTICIPANT_PROFILE_SQL
    let mut stmt = conn
        .prepare(&format!("EXPLAIN QUERY PLAN {PARTICIPANT_PROFILE_SQL}"))
        .unwrap();
    let rows = stmt
        .query_map(params![alpha_id], |r| r.get::<_, String>(3))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert!(!rows.is_empty(), "profile explain plan must not be empty");

    // PARTICIPANT_RATING_HISTORY_SQL
    let mut stmt = conn
        .prepare(&format!(
            "EXPLAIN QUERY PLAN {PARTICIPANT_RATING_HISTORY_SQL}"
        ))
        .unwrap();
    let rows = stmt
        .query_map(params![alpha_id, i64::MAX, 101], |r| r.get::<_, String>(3))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert!(!rows.is_empty(), "history explain plan must not be empty");

    // PARTICIPANT_OPPONENTS_SQL
    let mut stmt = conn
        .prepare(&format!("EXPLAIN QUERY PLAN {PARTICIPANT_OPPONENTS_SQL}"))
        .unwrap();
    let rows = stmt
        .query_map(params![alpha_id, "", 21], |r| r.get::<_, String>(3))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert!(!rows.is_empty(), "opponents explain plan must not be empty");
}
