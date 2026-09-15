import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  MAX_OCCURRENCE_ID_BYTES,
  classifyBookingResponse,
  describeAgentOptions,
  describeFailure,
  describeLeaderboard,
  describeResult,
  gameIdFor,
  isSelfMatch,
  newOccurrenceId,
  occurrenceIdError,
  randomSalt,
  replayHref,
  retryRequest,
  seatsError,
  startRequestBody,
  validateStart,
} from "../app/league-runtime.mjs";

const fixture = JSON.parse(
  readFileSync(new URL("./fixtures/league-match-request.json", import.meta.url), "utf8"),
);

const attempt = {
  occurrenceId: "studio-1757900000000-1a2b",
  gameId: "league-studio-1757900000000-1a2b",
  seed: 7400001,
  seats: ["gate-heuristic", "gate-random"],
};

test("G1 the occurrence id is minted once and survives a retry unchanged", () => {
  const original = startRequestBody(attempt);
  const retried = retryRequest(original);

  // The four protocol fields, each value-identical. A retry is the same attempt.
  assert.deepEqual(retried, original);
  assert.equal(retried.occurrence_id, original.occurrence_id);
  assert.equal(retried.game_id, original.game_id);
  assert.equal(retried.seed, original.seed);
  assert.deepEqual(retried.seats, original.seats);
  assert.notEqual(retried, original, "the retry body is a fresh object, not an alias");
});

test("G1 minting is deterministic given the clock and the salt", () => {
  assert.equal(newOccurrenceId(1757900000000, "1a2b"), "studio-1757900000000-1a2b");
  assert.match(randomSalt(), /^[0-9a-f]{4}$/);
  assert.match(newOccurrenceId(1, randomSalt()), /^studio-1-[0-9a-f]{4}$/);
  assert.throws(() => newOccurrenceId(-1, "1a2b"), /non-negative/);
  assert.throws(() => newOccurrenceId(1.5, "1a2b"), /non-negative/);
  assert.throws(() => newOccurrenceId(1, "1A2B"), /hex salt/);
  assert.throws(() => newOccurrenceId(1, "1a2"), /hex salt/);
});

test("G1 the page mirrors the Host's occurrence-id rule", () => {
  assert.equal(occurrenceIdError("studio-1-1a2b"), null);
  assert.equal(occurrenceIdError("a.b_c-d"), null);

  for (const bad of ["", ".", "..", ".hidden", "trailing.", "a/b", "a\\b", "C:", "a b", "a\tb", "ünicode"]) {
    assert.notEqual(occurrenceIdError(bad), null, `${JSON.stringify(bad)} must be refused`);
  }
  assert.notEqual(occurrenceIdError("a".repeat(MAX_OCCURRENCE_ID_BYTES + 1)), null);
  assert.equal(occurrenceIdError("a".repeat(MAX_OCCURRENCE_ID_BYTES)), null);
  assert.notEqual(occurrenceIdError(null), null);
  assert.notEqual(occurrenceIdError(7), null);
});

test("G1 the request cannot carry anything but the four protocol fields", () => {
  // The frozen wire fixture, expressed the way the page holds an attempt.
  const fromFixture = {
    occurrenceId: fixture.occurrence_id,
    gameId: fixture.game_id,
    seed: fixture.seed,
    seats: fixture.seats,
  };
  const body = startRequestBody({
    ...fromFixture,
    // Everything below is a field the Host must never receive. Building the body
    // key by key (never spreading the input) is what keeps it out.
    program: "/bin/sh",
    args: ["-c", "echo pwned"],
    timeout_ms: 1,
    agent_config: { registry: "/etc/passwd" },
  });

  assert.deepEqual(Object.keys(body).sort(), ["game_id", "occurrence_id", "seats", "seed"]);
  assert.deepEqual(body, fixture, "the frozen wire fixture and the built body agree");
  assert.deepEqual(
    startRequestBody({ ...fromFixture, program: "anything" }),
    fixture,
    "an extra input field never reaches the wire",
  );
});

test("G1 validation refuses before anything is sent, and labels a self-match", () => {
  assert.deepEqual(validateStart(attempt), { error: null, notes: [] });

  assert.notEqual(validateStart({ ...attempt, occurrenceId: "../etc" }).error, null);
  assert.notEqual(validateStart({ ...attempt, gameId: "" }).error, null);
  assert.notEqual(validateStart({ ...attempt, gameId: "bad\u0000id" }).error, null);
  assert.notEqual(validateStart({ ...attempt, seed: -1 }).error, null);
  assert.notEqual(validateStart({ ...attempt, seed: 1.5 }).error, null);
  assert.notEqual(validateStart({ ...attempt, seats: ["only-one"] }).error, null);
  assert.notEqual(
    validateStart({ ...attempt, seats: ["a", "b", "c", "d", "e"] }).error,
    null,
  );
  assert.notEqual(validateStart({ ...attempt, seats: ["a", ""] }).error, null);
  assert.equal(seatsError(["a", "b", "c", "d"]), null);

  assert.equal(isSelfMatch(["a", "a"]), true);
  const selfMatch = validateStart({ ...attempt, seats: ["a", "a"] });
  assert.equal(selfMatch.error, null, "a self-match is legal, not a validation error");
  assert.equal(selfMatch.notes.length, 1);
  assert.match(selfMatch.notes[0], /not rating-eligible/);
});

test("G1 the game id is derived from the occurrence, not invented per request", () => {
  assert.equal(gameIdFor("studio-1-1a2b"), "league-studio-1-1a2b");
  assert.equal(attempt.gameId, gameIdFor(attempt.occurrenceId));
});

test("G1 a completed match whose booking failed stays two facts", () => {
  const result = describeResult({
    match_status: "completed",
    completion_status: "failed",
    error: "ledger is locked",
  });

  assert.equal(result.matchStatus, "completed");
  assert.equal(result.completionStatus, "failed");
  assert.equal(result.retryable, true);
  assert.match(result.headline, /completed/i);
  assert.doesNotMatch(result.headline, /fail/i, "the headline is the match fact only");
  assert.match(result.booking, /failed/i);
  assert.match(result.booking, /will not be re-run/);
  assert.equal(result.problem, "ledger is locked");
});

test("G1 a completed and recorded match carries the receipt's own numbers", () => {
  const result = describeResult({
    match_status: "completed",
    completion_status: "inserted",
    receipt: {
      source_identity: "runtime:studio-1-1a2b",
      match_id: 42,
      eligibility: "rated",
      outcome: { kind: "win", rating_events: 2 },
      elo: [
        { participant_id: "eng-a", elo_before: 1500, elo_after: 1516 },
        { participant_id: "eng-b", elo_before: 1500, elo_after: 1484 },
      ],
      replay: { document_hash: "ab".repeat(32) },
    },
  });

  assert.equal(result.retryable, false);
  assert.equal(result.matchId, 42);
  assert.equal(result.eligibility, "rated");
  assert.equal(result.booking, "Recorded (2 rating events).");
  assert.deepEqual(result.elo, [
    { participantId: "eng-a", eloBefore: 1500, eloAfter: 1516 },
    { participantId: "eng-b", eloBefore: 1500, eloAfter: 1484 },
  ]);
  assert.equal(result.replayHref, `/replay?league=${"ab".repeat(32)}`);
});

test("G1 a repeated occurrence books nothing new and says so", () => {
  const result = describeResult({
    match_status: "completed",
    completion_status: "already_present",
    receipt: { outcome: { rating_events: 0 }, elo: [] },
  });

  assert.equal(result.retryable, false);
  assert.match(result.booking, /already recorded/);
  assert.deepEqual(result.elo, []);
});

test("G1 an aborted match is not a failed one and is never retryable", () => {
  const result = describeResult({ match_status: "aborted", completion_status: "not_applicable" });

  assert.equal(result.retryable, false);
  assert.match(result.headline, /aborted/);
  assert.match(result.booking, /Nothing was recorded/);
});

test("G1 a lost response, a refusal and a Host fault stay distinct", () => {
  // A thrown fetch is retryable (see the dedicated test); the status cases below are
  // not, and must not borrow that licence.
  const lost = describeFailure(null, null);
  assert.equal(lost.retryable, true, "an ambiguous transport outcome is retryable");
  assert.match(lost.headline, /lost|connection/i);

  const conflict = describeFailure(409, { error: "occurrence slot already holds a report" });
  assert.match(conflict.detail, /already holds a report/);
  assert.equal(conflict.retryable, false);

  const unavailable = describeFailure(503, { error: "league unavailable" });
  assert.equal(unavailable.retryable, false, "a refused booking is not a retry of this attempt");

  const fault = describeFailure(500, { error: "io error" });
  assert.equal(fault.retryable, true, "a fault before a settled fact may be started again");

  // The panel's own kicker is a claim about the ledger, and only the transport case
  // may not make one: with the response lost, the match may have completed and been
  // recorded. Printing "NOT BOOKED" there would contradict the paragraph under it,
  // and would undo the point of making a lost response retryable at all.
  assert.equal(lost.kicker, "OUTCOME UNKNOWN");
  assert.notEqual(lost.kicker, "NOT BOOKED", "a lost response must not claim absence");
  assert.equal(conflict.kicker, "NOT BOOKED");
  assert.equal(unavailable.kicker, "NOT BOOKED");
  assert.equal(fault.kicker, "NOT BOOKED");
  assert.equal(describeFailure(400, { error: "bad request" }).kicker, "NOT BOOKED");
});

test("G1 the failure kicker is the classification's, not a restatement of retryable", () => {
  // Retryability and the absence claim are independent questions, so a label derived
  // from `retryable` is wrong in both directions: a 500 is retryable without being an
  // ambiguous outcome, and a 409 is unambiguous without being retryable.
  const retryable = [describeFailure(null, null), describeFailure(500, { error: "io" })];
  const refused = [
    describeFailure(400, { error: "bad request" }),
    describeFailure(409, { error: "occupied" }),
    describeFailure(503, { error: "league unavailable" }),
  ];
  assert.deepEqual(
    retryable.map((f) => f.retryable),
    [true, true],
  );
  assert.deepEqual(
    refused.map((f) => f.retryable),
    [false, false, false],
  );
  assert.deepEqual(
    retryable.map((f) => f.kicker),
    ["OUTCOME UNKNOWN", "NOT BOOKED"],
  );
  assert.deepEqual(
    refused.map((f) => f.kicker),
    ["NOT BOOKED", "NOT BOOKED", "NOT BOOKED"],
  );
});

test("G1 the leaderboard renderer invents nothing", () => {
  const rows = describeLeaderboard([
    {
      participant_id: "eng-a",
      display_name: "Gate Heuristic",
      elo: 1516,
      rated_games: 2,
      rated_wins: 1,
      rated_ties: 0,
      rated_losses: 1,
      provisional: false,
    },
    { participant_id: "eng-b" },
  ]);

  assert.equal(rows[0].elo, 1516);
  assert.equal(rows[0].displayName, "Gate Heuristic");
  assert.equal(rows[1].elo, null, "a missing rating is missing, never 1500");
  assert.equal(rows[1].ratedGames, null);
  assert.equal(rows[1].provisional, null);
  assert.deepEqual(describeLeaderboard(null), []);
});

test("G1 the picker offers registry agents and attaches no rating to them", () => {
  const options = describeAgentOptions([
    { id: "gate-heuristic", display_name: "Gate Heuristic", class: "heuristic" },
    { id: "gate-random" },
  ]);

  assert.deepEqual(options, [
    {
      id: "gate-heuristic",
      displayName: "Gate Heuristic",
      agentClass: "heuristic",
      policyVersion: null,
    },
    { id: "gate-random", displayName: "gate-random", agentClass: null, policyVersion: null },
  ]);
  for (const option of options) {
    assert.equal("elo" in option, false, "no rating is claimed for a registry id");
  }
});

test("G1 a lost response is retryable with the SAME occurrence, never a new one", () => {
  const lost = describeFailure(null, { error: "Failed to fetch" });

  // The one case where the page must not push the player toward `New match`: a
  // thrown fetch cannot distinguish "never arrived" from "finished, response lost",
  // and all of those are safe to retry with the same occurrence id.
  assert.equal(lost.retryable, true);
  assert.match(lost.headline, /lost|connection/i);
  assert.match(lost.detail, /same occurrence/i);
  assert.match(lost.detail, /Failed to fetch/);

  // The retry body is the original body, so the occurrence can only complete once.
  const original = startRequestBody(attempt);
  assert.deepEqual(retryRequest(original), original);

  // A Host that refuses is a different matter: those are not retried as-is.
  assert.equal(describeFailure(400, { error: "bad request" }).retryable, false);
  assert.equal(describeFailure(409, { error: "occupied" }).retryable, false);
  assert.equal(classifyBookingResponse(503, { error: "unavailable" }).failure.retryable, false);
});

test("G1 a settled match reaches the result panel whatever the status code", () => {
  // The one that matters: the Host's own 503 `completed + completion failed` is a
  // finished match, not a transport failure. Classifying by `response.ok` would
  // silently merge the two facts this slice exists to keep apart.
  const cases = [
    [200, { match_status: "completed", completion_status: "inserted" }],
    [200, { match_status: "completed", completion_status: "already_present" }],
    [200, { match_status: "aborted", completion_status: "not_applicable" }],
    [503, { match_status: "completed", completion_status: "failed" }],
  ];

  for (const [status, body] of cases) {
    const classified = classifyBookingResponse(status, body);
    assert.equal(
      classified.settled,
      true,
      `HTTP ${status} + ${body.completion_status} is a settled fact`,
    );
    assert.equal(classified.failure, null);
    assert.equal(classified.result.matchStatus, body.match_status);
    assert.equal(classified.result.completionStatus, body.completion_status);
  }

  const interrupted = classifyBookingResponse(503, {
    match_status: "completed",
    completion_status: "failed",
    error: "ledger is locked",
  });
  assert.equal(interrupted.settled, true, "503 with both axes is a result, not a refusal");
  assert.equal(interrupted.result.retryable, true, "and its Retry re-sends the same body");
  assert.match(interrupted.result.headline, /completed/i);
  assert.doesNotMatch(interrupted.result.headline, /fail/i);
  assert.match(interrupted.result.booking, /failed/i);
  assert.equal(interrupted.result.problem, "ledger is locked");
});

test("G1 only a body with both axes is a settled fact", () => {
  // A body without both axes is not a match fact, so it stays a refusal — including
  // a 503, which then means "this league cannot answer", not "your match finished".
  for (const [status, body] of [
    [400, { error: "bad request" }],
    [409, { error: "occurrence slot already holds a report" }],
    [500, { error: "io error" }],
    [503, { error: "league unavailable" }],
    [null, null],
  ]) {
    const classified = classifyBookingResponse(status, body);
    assert.equal(classified.settled, false, `HTTP ${status} is not a settled match`);
    assert.equal(classified.result, null);
    assert.equal(typeof classified.failure.headline, "string");
  }

  assert.equal(classifyBookingResponse(200, { match_status: "completed" }).settled, false);
  assert.equal(classifyBookingResponse(200, {}).settled, false);
  assert.equal(classifyBookingResponse(500, {}).failure.retryable, true);
});

test("G1 the write path classifies by the body, not by response.ok", () => {
  // There is no browser runner in this repository, so this is a *source-level*
  // structural guard, not a behavioural test. It pins the single line that made the
  // 503 `completed + completion failed` case unreachable (P1-1 of the v1 review): the
  // module tests stay green even if the page drops the classifier, which is exactly
  // how that defect survived the first round. Read-only GETs may still use
  // `response.ok`; only `send()` is asserted here.
  const page = readFileSync(new URL("../app/league/page.tsx", import.meta.url), "utf8");
  const start = page.indexOf("async function send");
  const end = page.indexOf("function start()");
  assert.ok(start > 0 && end > start, "the write path is findable in the page source");
  const send = page.slice(start, end);

  assert.match(send, /classifyBookingResponse\(response\.status, value\)/);
  assert.match(send, /classifyBookingResponse\(null,/);
  // Comments first: this test is about the code, and the surrounding prose
  // legitimately names `response.ok` to explain what was wrong with it.
  const code = send.replace(/\/\/[^\n]*/g, "");
  assert.doesNotMatch(
    code,
    /response\.ok/,
    "the write path must not decide result-versus-failure from the status alone",
  );
});

test("G1 the failure panel's kicker is owned by the classification, not by the page", () => {
  // A source-level guard, for the same reason as the one above: no browser runner.
  // The kicker is a claim about the ledger, so it belongs to `describeFailure` beside
  // the paragraph it labels. A hardcoded label is how this round's seam appeared — a
  // lost response printed "NOT BOOKED" directly over "the match outcome is unknown".
  const page = readFileSync(new URL("../app/league/page.tsx", import.meta.url), "utf8");
  const code = page
    .replace(/\/\/[^\n]*/g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
  assert.match(code, /\{failure\.kicker\}/, "the page renders the classified kicker");
  assert.doesNotMatch(code, /NOT BOOKED/, "the page must not own the absence claim");
  assert.doesNotMatch(code, /OUTCOME UNKNOWN/, "...nor the ambiguity claim");
});

test("G1 the replay link is content-addressed", () => {
  assert.equal(replayHref("abc"), "/replay?league=abc");
  assert.equal(replayHref(null), null);
  assert.equal(replayHref(""), null);
});
