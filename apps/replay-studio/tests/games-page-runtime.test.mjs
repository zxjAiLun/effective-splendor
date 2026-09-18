import assert from "node:assert/strict";
import test from "node:test";

import {
  GAMES_PAGE_DEFAULT_LIMIT,
  GAMES_PAGE_MAX_LIMIT,
  clampGamesLimit,
  describeGamesPage,
  describeLeagueGameRow,
  nextGamesQuery,
} from "../app/games-page-runtime.mjs";

function row(overrides = {}) {
  return {
    match_id: "m-1",
    league_seq: 42_523,
    played_at: 1_789_742_158,
    source_kind: "human_play",
    status: "completed",
    rating_eligible: true,
    rating_ineligible_reason: null,
    replay_document_sha256: "a".repeat(64),
    replay_archived: true,
    seats: [
      {
        seat: 0,
        participant_id: "p-you",
        display_name: "You",
        score: 17,
        rank: 0,
        won: true,
      },
      {
        seat: 1,
        participant_id: "p-s3",
        display_name: "S3 Rollout",
        score: 6,
        rank: 1,
        won: false,
      },
    ],
    ...overrides,
  };
}

test("a recorded 1v1 says who won, and the score line, from the seats only", () => {
  const described = describeLeagueGameRow(row());
  assert.equal(described.outcome, "You");
  assert.equal(described.scoreLine, "17 – 6");
  assert.deepEqual(described.winnerLabels, ["You"]);
  assert.equal(described.leagueSeq, 42_523);
  assert.equal(described.ratingEligible, true);
});

test("a match with no recorded winner does not invent one", () => {
  const seats = row().seats.map((seat) => ({ ...seat, won: false }));
  const described = describeLeagueGameRow(row({ seats }));
  assert.equal(described.outcome, "No recorded winner");
  assert.deepEqual(described.winnerLabels, []);
});

test("a seat with no display name is reported by its seat index, never guessed", () => {
  const seats = [
    { seat: 0, participant_id: "p", display_name: null, score: 15, rank: 0, won: true },
  ];
  const described = describeLeagueGameRow(row({ seats }));
  // The label is positional and says so. It never borrows the participant id, and
  // it never calls an unnamed seat "You".
  assert.equal(described.seats[0].label, "Seat 0");
  assert.notEqual(described.seats[0].label, "You");
});

test("a match with no seats recorded has no outcome and no score", () => {
  const described = describeLeagueGameRow(row({ seats: [] }));
  assert.equal(described.outcome, "—");
  assert.equal(described.scoreLine, "—");
});

test("an incomplete score line is unknown rather than partial", () => {
  const seats = row().seats.map((seat, index) => ({
    ...seat,
    score: index === 0 ? 17 : null,
  }));
  const described = describeLeagueGameRow(row({ seats }));
  assert.equal(described.scoreLine, "—");
});

test("an ineligible match reports its frozen reason and claims no rating", () => {
  const described = describeLeagueGameRow(
    row({ rating_eligible: false, rating_ineligible_reason: "self-match" }),
  );
  assert.equal(described.ratingEligible, false);
  assert.equal(described.ineligibleReason, "self-match");
});

test("an eligible match never carries an ineligible reason, even if one is present", () => {
  const described = describeLeagueGameRow(
    row({ rating_eligible: true, rating_ineligible_reason: "should not be shown" }),
  );
  assert.equal(described.ineligibleReason, null);
});

test("a replay link is offered only for a recorded, archived content address", () => {
  const openable = describeLeagueGameRow(row());
  assert.equal(openable.replayHref, `/replay?league=${"a".repeat(64)}`);
  assert.equal(openable.replayUnavailableReason, null);

  // Recorded but not archived: there is no bytes authority, so no link.
  const notArchived = describeLeagueGameRow(row({ replay_archived: false }));
  assert.equal(notArchived.replayHref, null);
  assert.match(notArchived.replayUnavailableReason, /did not record this replay/);

  // No document at all: a different fact, phrased differently.
  const noDocument = describeLeagueGameRow(
    row({ replay_document_sha256: null, replay_archived: false }),
  );
  assert.equal(noDocument.replayHref, null);
  assert.match(noDocument.replayUnavailableReason, /No replay document is recorded/);
});

test("an archived flag without a content address cannot produce a link", () => {
  // The ledger's `replay_archived` and the document hash are two statements; a link
  // needs both, so a row that claims archived but names no address is not openable.
  const described = describeLeagueGameRow(
    row({ replay_archived: true, replay_document_sha256: null }),
  );
  assert.equal(described.replayHref, null);
});

test("a page reports its rows and the cursor the Host returned", () => {
  const page = describeGamesPage({
    matches: [row({ league_seq: 10 }), row({ league_seq: 9 })],
    next_before_league_seq: 9,
  });
  assert.equal(page.rows.length, 2);
  assert.equal(page.nextBeforeLeagueSeq, 9);
  assert.equal(page.atEnd, false);
});

test("no cursor means the end of the recording, not an error", () => {
  const page = describeGamesPage({ matches: [row()], next_before_league_seq: null });
  assert.equal(page.atEnd, true);
  assert.equal(page.nextBeforeLeagueSeq, null);
  // A malformed body is an empty page, never a crash mid-render.
  assert.deepEqual(describeGamesPage({}).rows, []);
  assert.equal(describeGamesPage({}).atEnd, true);
  assert.deepEqual(describeGamesPage(null).rows, []);
});

test("the next query is built from the Host cursor, never computed as an offset", () => {
  assert.equal(nextGamesQuery(42_500, 50), "limit=50&before=42500");
  // No cursor: no query. Answering with one would ask for a page that cannot exist.
  assert.equal(nextGamesQuery(null, 50), null);
  assert.equal(nextGamesQuery(undefined, 50), null);
});

test("the requested page size is clamped exactly like the ledger clamps it", () => {
  assert.equal(clampGamesLimit(undefined), GAMES_PAGE_DEFAULT_LIMIT);
  assert.equal(clampGamesLimit(0), 1);
  assert.equal(clampGamesLimit(-5), 1);
  assert.equal(clampGamesLimit(1), 1);
  assert.equal(clampGamesLimit(50), 50);
  assert.equal(clampGamesLimit(GAMES_PAGE_MAX_LIMIT), GAMES_PAGE_MAX_LIMIT);
  assert.equal(clampGamesLimit(10_000), GAMES_PAGE_MAX_LIMIT);
  assert.equal(clampGamesLimit(50.9), 50);
  // The default stays strictly inside the ceiling, so a default page can never be
  // rejected by the Host's own bound.
  assert.ok(GAMES_PAGE_DEFAULT_LIMIT <= GAMES_PAGE_MAX_LIMIT);
});
