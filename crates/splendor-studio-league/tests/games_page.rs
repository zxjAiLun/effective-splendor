//! The bounded games-list gates.
//!
//! Why this file exists: the games list is the first read surface that is
//! *paged*, and paging has failure modes a single read cannot have. A page can
//! repeat a row, skip a row, or — the one that matters most here — **drift** when
//! a match is recorded while the reader is between pages. The league is live: the
//! Host books matches into it while the player scrolls, so a page-two that is
//! computed from an offset would silently shift under a new arrival.
//!
//! The gates below pin the properties that make the list trustworthy:
//!
//! 1. **partition** — walking the cursor visits every match exactly once, in
//!    `league_seq` descending order;
//! 2. **stability** — a match recorded *after* page one is read does not move,
//!    duplicate or hide a page-two row, because the cursor is exclusive and the
//!    ordering key is the ledger's own monotonic position;
//! 3. **filter** — `participant_id` narrows to that participant's matches and can
//!    never reorder or widen the page;
//! 4. **bounds** — the limit is clamped by the read surface itself, not by the
//!    caller, so an unbounded request cannot be constructed by asking for one.
//!
//! None of this is a benchmark. The last gate states a *measured* real-scale fact
//! (see `docs/studio-player-loop-v1.md`, D1) rather than a performance target: at
//! 42,523 matches the unfiltered first page is index-driven, while a
//! `participant_id` filter is a per-candidate seat probe whose cost follows how
//! **rare** the participant is. That measurement is the reason the filter is not
//! claimed to be cheap, and it is recorded here so a future change cannot quietly
//! re-assert a shape this gate refuted.

use league::{
    ingest_match, league_match_page, open_in_memory, EngineIdentityV1, LeagueMatchPageRequestV1,
    MatchStatus, ReplayStorage, ReplayVerification, SeatPolicyIdentityV1, StudioMatchRecordV1,
    StudioMatchSeatV1, GAMES_PAGE_DEFAULT_LIMIT, GAMES_PAGE_MAX_LIMIT,
    SPLENDOR_BASE_V1_RULESET_FINGERPRINT,
};
use rusqlite::Connection;
use splendor_studio_league as league;

const NOW: i64 = 1_700_000_000;

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

fn record(name: &str, seats: Vec<StudioMatchSeatV1>) -> StudioMatchRecordV1 {
    StudioMatchRecordV1 {
        source_kind: "arena_report".to_string(),
        source_identity: name.to_string(),
        source_path: Some(format!("benchmarks/{name}.report.json")),
        source_document_hash: hex64(name),
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
            final_hash: Some(hex64(&format!("{name}-final"))),
            storage: Some(ReplayStorage::Archive),
            path: Some(format!("replays/{name}.json")),
            verification: Some(ReplayVerification::Verified),
        },
        diagnostic: false,
    }
}

/// A league of `count` matches between alternating pairs of engines.
fn league_with(count: usize) -> Connection {
    let mut conn = open_in_memory().expect("in-memory league");
    for index in 0..count {
        let a = format!("engine-{:02}", index % 4);
        let b = format!("engine-{:02}", (index + 1) % 4);
        let a_wins = index % 3 != 0;
        ingest_match(
            &mut conn,
            &record(
                &format!("match-{index:04}"),
                vec![
                    seat(0, &a, a_wins, if a_wins { 15 } else { 9 }),
                    seat(1, &b, !a_wins, if a_wins { 9 } else { 15 }),
                ],
            ),
        )
        .expect("ingest a match");
    }
    conn
}

fn page(
    conn: &Connection,
    limit: Option<u32>,
    before: Option<i64>,
    participant: Option<&str>,
) -> league::LeagueMatchPageV1 {
    league_match_page(
        conn,
        &LeagueMatchPageRequestV1 {
            limit,
            before_league_seq: before,
            participant_id: participant.map(str::to_string),
        },
    )
    .expect("the page must be readable")
}

#[test]
fn the_cursor_partitions_the_ledger_exactly_once() {
    let conn = league_with(120);

    let mut seen: Vec<i64> = Vec::new();
    let mut cursor: Option<i64> = None;
    let mut pages = 0;
    loop {
        let page = page(&conn, Some(25), cursor, None);
        pages += 1;
        // Strictly descending, and the cursor is exclusive.
        for window in page.matches.windows(2) {
            assert!(
                window[0].league_seq > window[1].league_seq,
                "a page must be ordered by league_seq descending"
            );
        }
        if let Some(previous) = cursor {
            for row in &page.matches {
                assert!(
                    row.league_seq < previous,
                    "the cursor is exclusive: {} must be below {previous}",
                    row.league_seq
                );
            }
        }
        seen.extend(page.matches.iter().map(|row| row.league_seq));
        match page.next_before_league_seq {
            Some(next) => cursor = Some(next),
            None => break,
        }
    }

    // Every match exactly once, newest first, with no gap and no repetition.
    let total: i64 = conn
        .query_row("SELECT COUNT(*) FROM matches", [], |row| row.get(0))
        .expect("count matches");
    assert_eq!(total, 120);
    assert_eq!(
        seen.len(),
        total as usize,
        "every match must be visited once"
    );
    let mut unique = seen.clone();
    unique.sort_unstable();
    unique.dedup();
    assert_eq!(unique.len(), seen.len(), "no row may be visited twice");
    assert_eq!(
        seen.first().copied(),
        Some(120),
        "the walk starts at the newest"
    );
    assert_eq!(seen.last().copied(), Some(1), "and ends at the oldest");
    // 120 at 25 per page: 4 full pages plus a 20-row tail.
    assert_eq!(
        pages, 5,
        "the walk must terminate, not loop on an empty page"
    );
}

#[test]
fn a_match_booked_between_two_pages_does_not_move_page_two() {
    let mut conn = league_with(60);

    // Page one of the world as it is now.
    let first = page(&conn, Some(10), None, None);
    assert_eq!(first.matches.len(), 10);
    let cursor = first
        .next_before_league_seq
        .expect("a full page has a next cursor");

    // A real match is booked while the reader holds that cursor.
    ingest_match(
        &mut conn,
        &record(
            "match-arrives-mid-scroll",
            vec![
                seat(0, "engine-00", true, 15),
                seat(1, "engine-01", false, 9),
            ],
        ),
    )
    .expect("ingest the mid-scroll match");

    // Page two must be the next ten rows *below the cursor*, unchanged — the new
    // match belongs above page one, and must not push a row across the boundary.
    let second = page(&conn, Some(10), Some(cursor), None);
    let expected: Vec<i64> = (41..=50).rev().collect();
    let observed: Vec<i64> = second.matches.iter().map(|row| row.league_seq).collect();
    assert_eq!(
        observed, expected,
        "an arrival above the cursor must not shift, skip or duplicate page two"
    );
    assert!(
        second.matches.iter().all(|row| row.league_seq < cursor),
        "no page-two row may come from above the cursor"
    );
    // And the arrival is visible on a *fresh* first page, which is where a newer
    // match belongs. `match_id` is content-derived, so the newest row is checked by
    // its ledger position and its recorded source identity, not by a filename.
    let refreshed = page(&conn, Some(1), None, None);
    let newest = &refreshed.matches[0];
    assert_eq!(
        newest.league_seq, 61,
        "the arrival is the newest ledger position"
    );
    let source_identity: String = conn
        .query_row(
            "SELECT source_identity FROM matches WHERE match_id = ?1",
            [newest.match_id.as_str()],
            |row| row.get(0),
        )
        .expect("the newest match is recorded");
    assert_eq!(
        source_identity, "match-arrives-mid-scroll",
        "the new match appears on the newest page"
    );
}

#[test]
fn the_participant_filter_narrows_without_reordering_or_widening() {
    let conn = league_with(60);

    // `engine-00` plays every even index, so its page is every other match. The
    // filter takes a **participant id** (derived), not an engine name, so discover
    // it from the ledger the way a caller must rather than inventing one.
    let all: Vec<i64> = page(&conn, Some(10), None, None)
        .matches
        .iter()
        .map(|row| row.league_seq)
        .collect();

    let participant: String = conn
        .query_row(
            "SELECT participant_id FROM match_seats WHERE seat = 0 AND match_id IN
                (SELECT match_id FROM matches ORDER BY league_seq DESC LIMIT 1)",
            [],
            |row| row.get(0),
        )
        .expect("the newest match has a seat-0 participant");

    let filtered = page(&conn, Some(20), None, Some(&participant));
    assert!(
        !filtered.matches.is_empty(),
        "the filter must match something"
    );

    // Ordered the same way, and every returned match really contains the
    // participant.
    for window in filtered.matches.windows(2) {
        assert!(
            window[0].league_seq > window[1].league_seq,
            "filtering must not reorder the page"
        );
    }
    for row in &filtered.matches {
        let contains: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM match_seats WHERE match_id = ?1 AND participant_id = ?2",
                rusqlite::params![row.match_id, participant],
                |row| row.get(0),
            )
            .expect("count the participant's seats");
        assert_eq!(
            contains, 1,
            "{} must contain the filtered participant",
            row.match_id
        );
    }

    // A participant id that appears nowhere is an empty page, not an error and not
    // a silently unfiltered list.
    let nobody = page(&conn, Some(20), None, Some("no-such-participant"));
    assert!(
        nobody.matches.is_empty(),
        "an unknown participant must produce an empty page, never the unfiltered list"
    );
    assert_eq!(nobody.next_before_league_seq, None);

    // The filter is a narrowing: the unfiltered page is a superset view of the
    // same ordering, so the newest unfiltered row cannot be below the newest
    // filtered row.
    assert!(
        all.first() >= filtered.matches.first().map(|row| &row.league_seq),
        "the unfiltered page must reach at least as high as the filtered one"
    );
}

#[test]
fn the_limit_is_clamped_by_the_read_surface_not_the_caller() {
    let conn = league_with(250);

    // `0` and negative-as-zero: clamped up to one, never an unbounded or an
    // empty-but-successful read.
    assert_eq!(page(&conn, Some(0), None, None).matches.len(), 1);
    assert_eq!(page(&conn, Some(1), None, None).matches.len(), 1);
    assert_eq!(
        page(&conn, None, None, None).matches.len(),
        GAMES_PAGE_DEFAULT_LIMIT as usize,
        "an absent limit must be the documented default"
    );
    assert_eq!(
        page(&conn, Some(GAMES_PAGE_MAX_LIMIT), None, None)
            .matches
            .len(),
        GAMES_PAGE_MAX_LIMIT as usize
    );
    // The ceiling is enforced here, so asking for more cannot widen the page.
    assert_eq!(
        page(&conn, Some(10_000), None, None).matches.len(),
        GAMES_PAGE_MAX_LIMIT as usize,
        "a request above the ceiling must be clamped, not honoured"
    );
    assert!(
        GAMES_PAGE_DEFAULT_LIMIT <= GAMES_PAGE_MAX_LIMIT,
        "the default must lie inside the ceiling, or a default request is refused"
    );
}

#[test]
fn a_page_that_reaches_the_end_reports_no_cursor() {
    let conn = league_with(30);

    // A short page is the end of the recording.
    let tail = page(&conn, Some(50), None, None);
    assert_eq!(tail.matches.len(), 30);
    assert_eq!(
        tail.next_before_league_seq, None,
        "a page that returned fewer rows than it asked for is the end"
    );

    // A full page still offers a cursor, and it is the last returned row.
    let full = page(&conn, Some(30), None, None);
    assert_eq!(full.matches.len(), 30);
    assert_eq!(
        full.next_before_league_seq,
        full.matches.last().map(|row| row.league_seq),
        "the cursor is derived from the returned rows, not from the request"
    );

    // Walking from it lands on the end with nothing left.
    let after = page(&conn, Some(30), full.next_before_league_seq, None);
    assert!(after.matches.is_empty());
    assert_eq!(after.next_before_league_seq, None);
}

#[test]
fn an_impossible_cursor_is_refused_rather_than_answered_empty() {
    let conn = league_with(10);

    // `league_seq` starts at 1, so a cursor of 0 or below cannot name a position.
    // Answering `empty` would make a malformed request look like an exhausted
    // ledger — the one confusion this list must not create.
    for bad in [0, -1, i64::MIN] {
        let result = league_match_page(
            &conn,
            &LeagueMatchPageRequestV1 {
                limit: Some(10),
                before_league_seq: Some(bad),
                participant_id: None,
            },
        );
        assert!(
            result.is_err(),
            "a cursor of {bad} is not a position and must be refused"
        );
        let message = result.unwrap_err().to_string();
        assert!(
            message.contains("positive league_seq"),
            "the refusal must name the rule it enforced, got: {message}"
        );
    }
}

#[test]
fn a_listed_row_carries_the_recorded_facts_and_no_recomputation() {
    let conn = league_with(3);

    let newest = page(&conn, Some(1), None, None);
    let row = &newest.matches[0];

    // The seat facts come from the ledger; nothing is invented.
    let mut seats = row.seats.clone();
    seats.sort_by_key(|seat| seat.seat);
    assert_eq!(seats.len(), 2);
    assert_eq!(seats[0].seat, 0);
    assert!(seats[0].participant_id.is_some());
    assert!(seats[0].score.is_some());
    assert!(
        seats.iter().any(|seat| seat.won),
        "a decided match has a winner"
    );
    assert!(!seats.iter().all(|seat| seat.won), "and it is not a draw");

    // The row is a summary, not a detail: it has no Elo events at all.
    let json = serde_json::to_value(row).expect("a row serializes");
    assert!(
        json.get("rating_events").is_none(),
        "a list row must not carry rating events; the leaderboard and the match detail own Elo"
    );
    assert!(json.get("seats").is_some());

    // `replay_archived` is the ledger's own statement, and the document hash is a
    // content address, never a path.
    assert!(row.replay_archived);
    assert_eq!(
        row.replay_document_sha256.as_deref().map(str::len),
        Some(64),
        "the recorded address is a SHA-256"
    );
    assert!(
        !row.replay_document_sha256
            .as_deref()
            .unwrap_or("")
            .contains('/'),
        "the recorded value is an identity, never a path"
    );
}

/// The real-scale fact this slice measured, stated as a test so it cannot drift
/// silently: the **unfiltered** page is driven by the `league_seq` index and does
/// not scale with the table, while a **participant filter** is a per-candidate
/// seat probe.
///
/// This is a structural assertion about the plan, not a benchmark: the property
/// that matters is which access path the planner takes, and it holds regardless of
/// how busy the machine is.
#[test]
fn the_unfiltered_page_is_index_driven_and_the_filter_is_a_per_candidate_probe() {
    let conn = league_with(200);

    let head_sql = "SELECT m.match_id FROM matches m
                     WHERE m.league_seq < ?1
                       AND (?2 IS NULL OR EXISTS (
                             SELECT 1 FROM match_seats s
                              WHERE s.match_id = m.match_id AND s.participant_id = ?2))
                     ORDER BY m.league_seq DESC LIMIT ?3";

    let plan = |parameter: Option<&str>| -> Vec<String> {
        let mut statement = conn
            .prepare(&format!("EXPLAIN QUERY PLAN {head_sql}"))
            .expect("explain the page query");
        statement
            .query_map(rusqlite::params![i64::MAX, parameter, 50_i64], |row| {
                row.get::<_, String>(3)
            })
            .expect("explain rows")
            .collect::<std::result::Result<Vec<_>, _>>()
            .expect("collect the plan")
    };

    let unfiltered = plan(None);
    assert!(
        unfiltered
            .iter()
            .any(|step| step.contains("matches_league_seq")),
        "the cursor range must be driven by the league_seq index, not a scan:\n{}",
        unfiltered.join("\n")
    );
    assert!(
        !unfiltered.iter().any(|step| step.contains("SCAN m")),
        "the ordered matches read must not become a scan:\n{}",
        unfiltered.join("\n")
    );

    // With a filter the plan gains a correlated subquery over the seats — the
    // measured per-candidate probe. This asserts the *shape* the real-scale
    // measurement found; it deliberately does not assert a duration, because the
    // cost follows how rare the participant is and a fixture cannot show that.
    let filtered = plan(Some("eng-0000"));
    assert!(
        filtered
            .iter()
            .any(|step| step.contains("CORRELATED SCALAR SUBQUERY")),
        "the participant filter is expected to be a per-candidate probe:\n{}",
        filtered.join("\n")
    );
    assert!(
        filtered.iter().any(|step| step.contains("match_seats")),
        "the probe must consult the seat table:\n{}",
        filtered.join("\n")
    );
}
