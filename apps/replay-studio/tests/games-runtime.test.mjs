import assert from "node:assert/strict";
import test from "node:test";
import { describeGameRow } from "../app/games-runtime.mjs";

function game(overrides = {}) {
  return {
    session_id: "human-12312300221-0-28024-1",
    opponent: "s3-rollout-candidate",
    human_seat: 0,
    scores: [15, 12],
    winners: [0],
    player_count: 2,
    verification: "verified",
    ...overrides,
  };
}

test("a verified game with a known seat reports seat, outcome, score and a seat-scoped review link", () => {
  const row = describeGameRow(game());
  assert.equal(row.verified, true);
  assert.equal(row.seat, 0);
  assert.equal(row.seatLabel, "You P0");
  assert.equal(row.outcome, "Victory");
  assert.equal(row.scoreLine, "15 – 12");
  assert.equal(row.replayHref, "/replay?session=human-12312300221-0-28024-1");
  assert.equal(row.reviewHref, "/review?session=human-12312300221-0-28024-1&seat=0");
});

test("a verified loss is reported from the human seat, not seat 0", () => {
  assert.equal(describeGameRow(game({ human_seat: 1, winners: [0] })).outcome, "Defeat");
  assert.equal(describeGameRow(game({ human_seat: 1, winners: [1] })).outcome, "Victory");
});

test("an unknown human seat stays unknown: no invented seat, no Victory/Defeat, no seat in the review URL", () => {
  for (const human_seat of [null, undefined]) {
    const row = describeGameRow(game({ human_seat }));
    assert.equal(row.seat, null);
    assert.equal(row.seatLabel, "Seat unknown");
    assert.equal(row.outcome, "—", "must not infer win/loss without a seat");
    assert.doesNotMatch(row.reviewHref, /seat=/);
    assert.equal(row.reviewHref, "/review?session=human-12312300221-0-28024-1");
    // The score itself is a real replay fact and stays visible.
    assert.equal(row.scoreLine, "15 – 12");
  }
});

test("a legacy replay with no human seat never claims the human was P0", () => {
  const row = describeGameRow(game({ human_seat: null, winners: [0] }));
  assert.notEqual(row.seatLabel, "You P0");
  assert.notEqual(row.outcome, "Victory");
});

test("an invalid replay surfaces no unverified result as a trusted fact", () => {
  const row = describeGameRow(game({ verification: "invalid", winners: [0], scores: [15, 12] }));
  assert.equal(row.verified, false);
  assert.equal(row.outcome, "Invalid replay");
  assert.equal(row.scoreLine, "Result unavailable");
});

test("an unreadable replay entry degrades to invalid without inventing seat or result", () => {
  const row = describeGameRow({ session_id: "human-broken", error: "unreadable replay" });
  assert.equal(row.verified, false);
  assert.equal(row.seatLabel, "Seat unknown");
  assert.equal(row.outcome, "Invalid replay");
  assert.equal(row.scoreLine, "Result unavailable");
});

test("verified but outcome-less games report a dash rather than a guess", () => {
  assert.equal(describeGameRow(game({ winners: [], scores: [] })).outcome, "—");
  assert.equal(describeGameRow(game({ winners: undefined })).outcome, "—");
  assert.equal(describeGameRow(game({ winners: [], scores: [] })).scoreLine, "—");
});

test("session ids are URL-encoded in both links", () => {
  const row = describeGameRow(game({ session_id: "a b/c" }));
  assert.equal(row.replayHref, "/replay?session=a%20b%2Fc");
  assert.equal(row.reviewHref, "/review?session=a%20b%2Fc&seat=0");
});
