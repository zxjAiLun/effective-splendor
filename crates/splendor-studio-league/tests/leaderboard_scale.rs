//! The **real-scale** leaderboard gate.
//!
//! Why this file exists: the leaderboard query was correct and fast on every fixture
//! this repository owns, and pathological on the only league that matters. `match_seats`
//! has no index on `participant_id`, so an aggregate expressed as one correlated
//! subquery per participant is a full scan of the whole seat table *per participant*.
//! On the official ledger (42,521 matches, 85,042 seats, 100 participants) that query
//! took 19.7 s and, because the Studio Host accepts requests serially, made every route
//! — `/health` included — unanswerable for its whole duration. The first real
//! walkthrough was abandoned inside step 2 because of it.
//!
//! A fixture-scale league can never show that, so this gate pins the two properties
//! that *are* visible at any size and that the old shape violated:
//!
//! 1. **the plan** — the cost of the production query must not follow the number of
//!    participants. The gate explains the query at two very different field sizes and
//!    requires the same access to the seat table in both, which is the property the
//!    correlated shape broke (it scaled with participants); and
//! 2. **the numbers** — the production query must agree field by field with the frozen
//!    reference query it replaced, on a fixture that exercises every branch of the
//!    aggregates (decided, drawn, ineligible-but-recorded, and rated/recorded at once).
//!
//! Neither assertion is a benchmark: one is a structural property of the plan and the
//! other is an equivalence, so both hold on a busy machine. The wall-clock check at the
//! end has a deliberately coarse ceiling and exists only to catch something
//! catastrophic, not to police milliseconds.

use league::{
    ingest_match, leaderboard, open_in_memory, protocol_rating_config, EngineIdentityV1,
    MatchStatus, ReplayStorage, ReplayVerification, SeatPolicyIdentityV1, StudioMatchRecordV1,
    StudioMatchSeatV1, SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
};
use rusqlite::Connection;
use splendor_studio_league as league;
use std::time::{Duration, Instant};

/// The query `leaderboard()` used before the real-scale fix, kept verbatim as the
/// **reference**. It is deliberately not deleted: it defines the numbers the league
/// already published, and the replacement has to agree with it exactly.
const REFERENCE_SQL: &str = "SELECT p.participant_id, p.kind, p.display_name, p.current_elo,
        (SELECT COUNT(DISTINCT s.match_id) FROM match_seats s
          WHERE s.participant_id = p.participant_id),
        (SELECT COUNT(*) FROM match_seats s
           JOIN matches m ON m.match_id = s.match_id
          WHERE s.participant_id = p.participant_id AND m.rating_eligible = 1),
        (SELECT COUNT(*) FROM match_seats s
           JOIN matches m ON m.match_id = s.match_id
          WHERE s.participant_id = p.participant_id AND m.rating_eligible = 1
            AND s.won = 1
            AND (SELECT COUNT(*) FROM match_seats s2
                  WHERE s2.match_id = s.match_id AND s2.won = 1) = 1),
        (SELECT COUNT(*) FROM match_seats s
           JOIN matches m ON m.match_id = s.match_id
          WHERE s.participant_id = p.participant_id AND m.rating_eligible = 1
            AND s.won = 1
            AND (SELECT COUNT(*) FROM match_seats s2
                  WHERE s2.match_id = s.match_id AND s2.won = 1) > 1)
   FROM participants p";

const NOW: i64 = 1_700_000_000;
const PARTICIPANTS: usize = 16;
const ROUNDS: usize = 400;

/// The raw columns of one participant row, in query order.
type RawRow = (String, String, String, Option<f64>, i64, i64, i64, i64);

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

fn seat(index: u8, name: &str, won: bool) -> StudioMatchSeatV1 {
    StudioMatchSeatV1 {
        seat: index,
        identity: Some(EngineIdentityV1::new(name, "1")),
        policy_identity: SeatPolicyIdentityV1::NoConfigEvidence,
        participant_id: None,
        display_name: None,
        score: Some(if won { 15 } else { 9 }),
        rank: Some(if won { 0 } else { 1 }),
        won,
    }
}

fn record(name: &str, seats: Vec<StudioMatchSeatV1>, status: MatchStatus) -> StudioMatchRecordV1 {
    StudioMatchRecordV1 {
        source_kind: "arena_report".to_string(),
        source_identity: name.to_string(),
        source_path: Some(format!("benchmarks/{name}.report.json")),
        source_document_hash: hex64(name),
        played_at: Some(NOW),
        ruleset_fingerprint: SPLENDOR_BASE_V1_RULESET_FINGERPRINT.to_string(),
        engine_version: Some("0.4.0".to_string()),
        player_count: 2,
        status,
        seats,
        completed_plies: Some(64),
        main_turn_count: Some(32),
        replay: league::ReplayBindingV1 {
            document_hash: Some("a".repeat(64)),
            final_hash: Some(hex64(name)),
            storage: Some(ReplayStorage::Archive),
            path: Some(format!("replays/{name}.json")),
            verification: Some(ReplayVerification::Verified),
        },
        diagnostic: false,
    }
}

/// A league at a chosen field size that still exercises every branch.
///
/// Size is what makes the *plan* interesting; the cases below are what make the
/// *equality* interesting.
fn league_with(participants: usize) -> Connection {
    let mut conn = open_in_memory().expect("in-memory league");
    let names: Vec<String> = (0..participants)
        .map(|i| format!("engine-{i:02}"))
        .collect();

    // Ordinary decided 1v1s: one winner, one loser.
    for round in 0..ROUNDS {
        let a = round % participants;
        let b = (round * 7 + 3) % participants;
        if a == b {
            continue;
        }
        let a_wins = round % 3 != 0;
        let name = format!("rated-{round:05}");
        let value = record(
            &name,
            vec![seat(0, &names[a], a_wins), seat(1, &names[b], !a_wins)],
            MatchStatus::Completed,
        );
        ingest_match(&mut conn, &value).expect("ingest a rated match");
    }

    // Drawn matches: **two seats with won = 1**, which is the `ties` branch. The
    // reference counts a seat here only when the match has more than one winner, so
    // this is exactly where a careless rewrite would turn a tie into a win.
    for round in 0..8 {
        let a = round % participants;
        let b = (round % participants + participants / 2) % participants;
        if a == b {
            continue;
        }
        let name = format!("drawn-{round:05}");
        let value = record(
            &name,
            vec![seat(0, &names[a], true), seat(1, &names[b], true)],
            MatchStatus::Completed,
        );
        ingest_match(&mut conn, &value).expect("ingest a drawn match");
    }

    // Settled but ineligible: recorded, never rated. `recorded_games` must count these
    // and `rated_games` must not — the difference between the two count shapes.
    for round in 0..40 {
        let a = round % participants;
        let b = (a + 1) % participants;
        if a == b {
            continue;
        }
        let name = format!("aborted-{round:05}");
        let value = record(
            &name,
            vec![seat(0, &names[a], false), seat(1, &names[b], false)],
            MatchStatus::Aborted,
        );
        ingest_match(&mut conn, &value).expect("ingest an aborted match");
    }

    conn
}

fn mid_size_league() -> Connection {
    league_with(PARTICIPANTS)
}

fn raw_rows(conn: &Connection, sql: &str) -> Vec<RawRow> {
    let mut stmt = conn.prepare(sql).expect("prepare the query under test");
    let rows = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<f64>>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, i64>(6)?,
                row.get::<_, i64>(7)?,
            ))
        })
        .expect("run the query under test")
        .collect::<std::result::Result<Vec<_>, _>>()
        .expect("collect the query under test");
    let mut rows = rows;
    rows.sort_by(|a, b| a.0.cmp(&b.0));
    rows
}

/// How many times the plan touches the seat table, plus the plan itself.
fn seat_scans(conn: &Connection) -> (usize, Vec<String>) {
    let mut stmt = conn
        .prepare(&format!("EXPLAIN QUERY PLAN {}", league::LEADERBOARD_SQL))
        .expect("explain the production query");
    let plan: Vec<String> = stmt
        .query_map([], |row| row.get::<_, String>(3))
        .expect("explain rows")
        .collect::<std::result::Result<Vec<_>, _>>()
        .expect("collect the plan");
    let scans = plan
        .iter()
        .filter(|step| step.contains("SCAN") && step.contains("match_seats"))
        .count();
    (scans, plan)
}

#[test]
fn scale_gate_the_production_plan_does_not_follow_the_participant_count() {
    let small = seat_scans(&league_with(4));
    let large = seat_scans(&mid_size_league());

    // The old shape, verbatim: the same aggregate recomputed for every participant.
    assert!(
        !large
            .1
            .iter()
            .any(|step| step.contains("CORRELATED SCALAR SUBQUERY")),
        "the leaderboard must not compute an aggregate per participant again — on a real \
         league that is a full scan of match_seats for every participant:\n{}",
        large.1.join("\n")
    );

    // The property that matters is not a magic number: it is that the cost of the query
    // does not grow with the field size. Quadrupling the participants must leave the
    // plan's access to the seat table exactly as it was.
    assert_eq!(
        small.0,
        large.0,
        "the seat table must be touched the same number of times at 4 and at {PARTICIPANTS} \
         participants, or the query scales with the field again:\n4: {}\n{PARTICIPANTS}: {}",
        small.1.join(" | "),
        large.1.join(" | ")
    );
    assert!(
        large.0 <= 2,
        "expected one pass for the recorded counts and one for the rated aggregates:\n{}",
        large.1.join("\n")
    );

    // Sanity: this is the plan of a query that does return rows.
    assert!(
        !large.1.is_empty(),
        "an empty plan means we explained nothing"
    );
    let rows = leaderboard(&mid_size_league()).expect("the production query runs");
    assert!(!rows.is_empty(), "the fixture must produce a leaderboard");
}

#[test]
fn scale_gate_the_production_query_agrees_with_the_reference_query() {
    let conn = mid_size_league();
    let reference = raw_rows(&conn, REFERENCE_SQL);
    let production = raw_rows(&conn, league::LEADERBOARD_SQL);

    assert_eq!(
        PARTICIPANTS,
        reference.len(),
        "the fixture must contain one row per participant"
    );
    assert_eq!(
        reference.len(),
        production.len(),
        "both queries must describe the same participants"
    );

    for (want, got) in reference.iter().zip(production.iter()) {
        assert_eq!(
            want, got,
            "participant {} disagrees between the reference query and the production query",
            want.0
        );
    }

    // The fixture must really reach the branches it exists for, or the equality above
    // would be agreement about nothing.
    let ties: i64 = reference.iter().map(|row| row.7).sum();
    let wins: i64 = reference.iter().map(|row| row.6).sum();
    let rated: i64 = reference.iter().map(|row| row.5).sum();
    let recorded: i64 = reference.iter().map(|row| row.4).sum();
    assert!(ties > 0, "the drawn matches must surface as ties");
    assert!(wins > 0, "the decided matches must surface as wins");
    assert!(
        rated < recorded,
        "the aborted matches must be recorded but not rated ({rated} vs {recorded})"
    );
}

#[test]
fn scale_gate_the_derived_row_still_matches_the_raw_query() {
    let conn = mid_size_league();
    let config = protocol_rating_config();
    let production = raw_rows(&conn, league::LEADERBOARD_SQL);
    let rows = leaderboard(&conn).expect("the production query runs");

    let by_id: std::collections::HashMap<&str, &RawRow> =
        production.iter().map(|row| (row.0.as_str(), row)).collect();

    for row in &rows {
        let raw = by_id
            .get(row.participant_id.as_str())
            .unwrap_or_else(|| panic!("{} is not in the raw query", row.participant_id));
        assert_eq!(row.recorded_games as i64, raw.4, "recorded_games");
        assert_eq!(row.rated_games as i64, raw.5, "rated_games");
        assert_eq!(row.rated_wins as i64, raw.6, "rated_wins");
        assert_eq!(row.rated_ties as i64, raw.7, "rated_ties");
        assert_eq!(
            row.rated_losses,
            row.rated_games
                .saturating_sub(row.rated_wins + row.rated_ties),
            "rated_losses stays the remainder, never a second source of truth"
        );
        assert_eq!(
            row.provisional,
            row.rated_games < config.provisional_threshold,
            "provisional is derived, never stored"
        );
    }

    // The ordering is part of the published table, and it is applied in Rust, so the
    // query rewrite must not have quietly moved it.
    for window in rows.windows(2) {
        let ordered = window[0].elo > window[1].elo
            || (window[0].elo == window[1].elo && window[0].rated_games >= window[1].rated_games);
        assert!(
            ordered,
            "the leaderboard is ordered by Elo, then by rated games"
        );
    }
}

#[test]
fn scale_gate_the_query_stays_within_a_coarse_time_budget() {
    // Not a benchmark: on this fixture both shapes are fast, and the point of the gate
    // is the plan and the numbers above. The ceiling is orders of magnitude above the
    // measured cost and exists only so a future query that is *catastrophic* at scale
    // fails here rather than in the product.
    let conn = mid_size_league();
    let started = Instant::now();
    let rows = leaderboard(&conn).expect("the production query runs");
    let elapsed = started.elapsed();
    assert!(!rows.is_empty());
    assert!(
        elapsed < Duration::from_secs(10),
        "the leaderboard took {elapsed:?} on a {PARTICIPANTS}-participant fixture"
    );
}
