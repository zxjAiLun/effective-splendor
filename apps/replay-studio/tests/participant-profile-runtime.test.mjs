import assert from "node:assert/strict";
import test from "node:test";
import {
  buildEloChartData,
  classifyProfileError,
  decodeOpponentsPage,
  decodeParticipantProfile,
  decodeRatingHistoryPage,
  describeCompletedPlies,
  describeProfileElo,
  describeProfileKind,
  describeRecordText,
  describeSeatsText,
} from "../app/participant-profile-runtime.mjs";

test("describeProfileKind returns human and engine labels", () => {
  assert.equal(describeProfileKind("human"), "Human");
  assert.equal(describeProfileKind("engine"), "Engine");
  assert.equal(describeProfileKind("other"), null);
  assert.equal(describeProfileKind(null), null);
});

test("describeProfileElo truthfully reflects rated vs initial origin", () => {
  // 1. Rated Elo
  const rated = describeProfileElo({ value: 1529.8079, display_rounded: 1530, origin: "rated" }, true);
  assert.equal(rated.valueText, "1530");
  assert.equal(rated.preciseText, "1529.8");
  assert.equal(rated.origin, "rated");
  assert.equal(rated.isInitial, false);
  assert.equal(rated.label, "Studio Elo");
  assert.match(rated.subtext, /Provisional/);

  // 2. Initial Elo
  const initial = describeProfileElo({ value: 1500.0, display_rounded: 1500, origin: "initial" }, true);
  assert.equal(initial.valueText, "1500");
  assert.equal(initial.origin, "initial");
  assert.equal(initial.isInitial, true);
  assert.equal(initial.label, "Initial Studio Elo");
  assert.equal(initial.subtext, "No rated games yet");

  // 3. Null / invalid
  assert.equal(describeProfileElo(null, false), null);
});

test("describeRecordText formats W-T-L and games count without merging", () => {
  const info = describeRecordText({
    rated_wins: 1,
    rated_ties: 0,
    rated_losses: 0,
    rated_games: 1,
    recorded_games: 3,
  });
  assert.equal(info.record, "1–0–0");
  assert.equal(info.games, "1 rated · 3 recorded");

  // Missing components
  const missing = describeRecordText({ rated_wins: null });
  assert.equal(missing.record, "—");
});

test("describeSeatsText formats seat usage and appearances", () => {
  const info = describeSeatsText({
    appearances: 36416,
    seat0: 18208,
    seat1: 18208,
    other: 0,
  });
  assert.equal(info.summary, "P0 18208 · P1 18208");
  assert.equal(info.appearances, "36416 seat appearances");

  const withOther = describeSeatsText({
    appearances: 5,
    seat0: 2,
    seat1: 2,
    other: 1,
  });
  assert.equal(withOther.summary, "P0 2 · P1 2 · Other 1");
});

test("describeCompletedPlies handles available, partial, and unavailable states without 0 falsification", () => {
  // Available
  const avail = describeCompletedPlies({
    availability: "available",
    value: 50.0,
    observed_completed_games: 1,
    total_completed_games: 1,
    unit: "decision_plies",
  });
  assert.equal(avail.availability, "available");
  assert.equal(avail.valueText, "50.0 decision plies");
  assert.match(avail.subtext, /1 \/ 1 completed games observed/);

  // Partial
  const part = describeCompletedPlies({
    availability: "partial",
    value: 61.2,
    observed_completed_games: 10,
    total_completed_games: 20,
    unit: "decision_plies",
  });
  assert.equal(part.availability, "partial");
  assert.equal(part.valueText, "61.2 decision plies");
  assert.match(part.subtext, /Based on 10 \/ 20 completed games/);

  // Unavailable must say "Not recorded", never "0 decision plies"
  const unavail = describeCompletedPlies({
    availability: "unavailable",
    value: null,
    observed_completed_games: 0,
    total_completed_games: 0,
    unit: "decision_plies",
  });
  assert.equal(unavail.availability, "unavailable");
  assert.equal(unavail.valueText, "Not recorded");
  assert.doesNotMatch(unavail.valueText, /0 decision plies/);
});

test("decodeParticipantProfile decodes valid profile and rejects malformed documents", () => {
  const valid = {
    format: "effective-splendor-studio-league-participant",
    version: 1,
    profile: {
      participant_id: "test-participant-1",
      kind: "engine",
      display_name: "Test Agent",
      elo: { value: 1600.0, display_rounded: 1600, origin: "rated" },
      provisional: false,
      recorded_games: 10,
      rated_games: 10,
      rated_wins: 6,
      rated_ties: 1,
      rated_losses: 3,
      seats: { appearances: 10, seat0: 5, seat1: 5, other: 0 },
      completed_plies: {
        availability: "available",
        value: 55.4,
        observed_completed_games: 10,
        total_completed_games: 10,
        unit: "decision_plies",
      },
      main_turns: { availability: "unavailable", reason: "not_recorded" },
      gameplay: { availability: "unavailable", reason: "no_authoritative_builder" },
    },
  };

  const decoded = decodeParticipantProfile(valid, "test-participant-1");
  assert.equal(decoded.ok, true);
  assert.equal(decoded.profile.participant_id, "test-participant-1");

  // 1. participant_id mismatch
  const mismatch = decodeParticipantProfile(valid, "other-id");
  assert.equal(mismatch.ok, false);
  assert.match(mismatch.error, /mismatch/);

  // 2. format/version mismatch
  assert.equal(decodeParticipantProfile({ ...valid, format: "wrong" }, "test-participant-1").ok, false);
  assert.equal(decodeParticipantProfile({ ...valid, version: 2 }, "test-participant-1").ok, false);

  // 3. Initial Elo with non-1500 value fails closed
  const fakeInitial = JSON.parse(JSON.stringify(valid));
  fakeInitial.profile.elo = { value: 1234.0, display_rounded: 1234, origin: "initial" };
  assert.equal(decodeParticipantProfile(fakeInitial, "test-participant-1").ok, false);

  // 4. Non-finite Elo fails closed
  const nonFinite = JSON.parse(JSON.stringify(valid));
  nonFinite.profile.elo.value = Infinity;
  assert.equal(decodeParticipantProfile(nonFinite, "test-participant-1").ok, false);

  // 5. Negative count fails closed
  const negative = JSON.parse(JSON.stringify(valid));
  negative.profile.rated_wins = -1;
  assert.equal(decodeParticipantProfile(negative, "test-participant-1").ok, false);

  // 6. Malformed 200 array/non-object fails closed
  assert.equal(decodeParticipantProfile([], "test-participant-1").ok, false);
  assert.equal(decodeParticipantProfile(null, "test-participant-1").ok, false);
  assert.equal(decodeParticipantProfile({ format: valid.format, version: 1, profile: "broken" }, "test-participant-1").ok, false);
});

test("decodeRatingHistoryPage decodes valid points and rejects malformed envelope", () => {
  const valid = {
    format: "effective-splendor-studio-league-participant-ratings",
    version: 1,
    participant_id: "test-participant-1",
    points: [
      {
        participant_id: "test-participant-1",
        league_seq: 102,
        match_id: "m-102",
        elo_before: 1500.0,
        elo_after: 1516.0,
        delta: 16.0,
        opponent_id: "opp-1",
        opponent_name: "Opponent One",
        played_at: 1700000000,
      },
    ],
    next_before_league_seq: 102,
  };

  const decoded = decodeRatingHistoryPage(valid, "test-participant-1");
  assert.equal(decoded.ok, true);
  assert.equal(decoded.points.length, 1);
  assert.equal(decoded.nextBeforeLeagueSeq, 102);
  assert.equal(decoded.atEnd, false);

  // ID mismatch
  assert.equal(decodeRatingHistoryPage(valid, "wrong-id").ok, false);

  // Malformed point
  const badPoint = JSON.parse(JSON.stringify(valid));
  badPoint.points[0].league_seq = "not-a-number";
  assert.equal(decodeRatingHistoryPage(badPoint, "test-participant-1").ok, false);

  // Malformed cursor
  const badCursor = JSON.parse(JSON.stringify(valid));
  badCursor.next_before_league_seq = -5;
  assert.equal(decodeRatingHistoryPage(badCursor, "test-participant-1").ok, false);
});

test("decodeOpponentsPage decodes valid opponents and excludes self-match", () => {
  const valid = {
    format: "effective-splendor-studio-league-participant-opponents",
    version: 1,
    participant_id: "test-participant-1",
    opponents: [
      {
        opponent_id: "opp-1",
        display_name: "Opponent One",
        recorded_games: 5,
        rated_games: 5,
        rated_wins: 3,
        rated_ties: 1,
        rated_losses: 1,
      },
    ],
    next_after_opponent_id: null,
  };

  const decoded = decodeOpponentsPage(valid, "test-participant-1");
  assert.equal(decoded.ok, true);
  assert.equal(decoded.opponents.length, 1);
  assert.equal(decoded.atEnd, true);

  // Self-match present in opponents list must fail closed
  const selfMatch = JSON.parse(JSON.stringify(valid));
  selfMatch.opponents.push({
    opponent_id: "test-participant-1",
    display_name: "Self",
    recorded_games: 1,
    rated_games: 0,
    rated_wins: 0,
    rated_ties: 0,
    rated_losses: 0,
  });
  assert.equal(decodeOpponentsPage(selfMatch, "test-participant-1").ok, false);

  // Overlong cursor (>256 bytes) fails closed
  const overlong = JSON.parse(JSON.stringify(valid));
  overlong.next_after_opponent_id = "a".repeat(257);
  assert.equal(decodeOpponentsPage(overlong, "test-participant-1").ok, false);
});

test("buildEloChartData reverses DESC order to ASC without played_at reordering or synthetic points", () => {
  // Points arrive in league_seq DESC
  const points = [
    { league_seq: 100, elo_after: 1550, played_at: 1700000000, opponent_name: "B", match_id: "m2", delta: 20 },
    { league_seq: 50, elo_after: 1530, played_at: 1700050000, opponent_name: "A", match_id: "m1", delta: 30 }, // played_at is later, but league_seq is smaller
  ];

  const chart = buildEloChartData(points);
  assert.equal(chart.series.length, 2);
  // Ordered by league_seq ASC
  assert.equal(chart.series[0].x, 50);
  assert.equal(chart.series[0].y, 1530);
  assert.equal(chart.series[1].x, 100);
  assert.equal(chart.series[1].y, 1550);
  assert.equal(chart.minX, 50);
  assert.equal(chart.maxX, 100);

  // Single point (You) does not fabricate a starting 1500 event
  const single = buildEloChartData([
    { league_seq: 42523, elo_after: 1529.8, played_at: null, opponent_name: "S3", match_id: "m0", delta: 29.8 },
  ]);
  assert.equal(single.series.length, 1);
  assert.equal(single.series[0].x, 42523);
  assert.equal(single.series[0].y, 1529.8);
});

test("classifyProfileError distinguishes 404, 503, timeout, and malformed invalid", () => {
  // 1. 404 Not Found
  const err404 = { status: 404 };
  const res404 = classifyProfileError(err404);
  assert.equal(res404.kind, "not_found");
  assert.match(res404.message, /No participant with this ID/);

  // 2. 503 Refused
  const err503 = { status: 503, message: "identity manifest hash disagrees" };
  const res503 = classifyProfileError(err503);
  assert.equal(res503.kind, "refused");
  assert.match(res503.message, /identity manifest hash/);

  // 3. Timeout
  const errTimeout = { name: "TimeoutError" };
  const resTimeout = classifyProfileError(errTimeout, 5000);
  assert.equal(resTimeout.kind, "timed_out");
  assert.match(resTimeout.message, /did not answer within 5 seconds/);

  // 4. Invalid
  const errInvalid = { kind: "invalid", message: "Malformed JSON envelope" };
  const resInvalid = classifyProfileError(errInvalid);
  assert.equal(resInvalid.kind, "invalid");
});
