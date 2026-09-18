import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { bookingView, classifyBookingRetry, humanEloRows, humanResult, humanStartBody, randomSeed, resolveSeat, retryHumanBooking, seedText } from "../app/human-play-runtime.mjs";

const id = "human-1-1-2-3";
const matchId = "ab".repeat(32);
const receipt = { source_kind: "human_play", source_identity: `runtime:${id}`, match_id: matchId,
  outcome: { kind: "inserted", rating_events: 2 }, replay: { document_hash: "cd".repeat(32) },
  elo: [{ participant_id: "engine", elo_before: 1500, elo_after: 1484 }, { participant_id: "human", elo_before: 1500, elo_after: 1516 }] };
const completion = { status: "inserted", retryable: false, receipt, error: null };
const detail = { match: { source_kind: "human_play", source_identity: `runtime:${id}`, match_id: matchId,
  seats: [{ seat: 0, participant_id: "engine" }, { seat: 1, participant_id: "human" }] } };

test("u64 seed is an exact numeric JSON literal, not rounded or client authority fields", () => {
  assert.equal(humanStartBody('agent"id', 1, "18446744073709551615"), '{"agent_id":"agent\\"id","human_seat":1,"seed":18446744073709551615}');
  assert.equal(seedText(" 000001 "), "1");
  assert.equal(seedText("9007199254740993"), "9007199254740993");
  for (const value of ["-1", "1.2", "1e9", "", "0,\"participant_id\":1", "18446744073709551616", 123]) assert.throws(() => seedText(value));
  assert.throws(() => humanStartBody("a", "random", "1"));
});

test("random choices are resolved once per call and fixed seats consume no randomness", () => {
  let calls = 0;
  const crypto = { getRandomValues: words => { calls++; words.fill(0xffffffff); return words; } };
  assert.equal(resolveSeat("first", crypto), 0); assert.equal(resolveSeat("second", crypto), 1); assert.equal(calls, 0);
  assert.equal(resolveSeat("random", crypto), 1); assert.equal(calls, 1);
  assert.equal(randomSeed(crypto), "18446744073709551615"); assert.equal(calls, 2);
});

test("result is independent from booking and tied winners are DRAW", () => {
  assert.equal(humanResult({ winners: [1] }, 1), "VICTORY");
  assert.equal(humanResult({ winners: [0] }, 1), "DEFEAT");
  assert.equal(humanResult({ winners: [0, 1] }, 1), "DRAW");
  assert.equal(humanResult({ winners: [] }, 1), "RESULT UNAVAILABLE");
  for (const retryable of [true, false]) {
    const view = bookingView({ status: "failed", retryable, error: "canonical order; rebuild" }, id);
    assert.equal(view.retryable, retryable); assert.match(view.message, /game is finished/);
    assert.doesNotMatch(view.headline, /match failed|not booked/i);
  }
});

test("inserted and AlreadyPresent use the existing receipt; never invent default Elo", () => {
  assert.equal(bookingView(completion, id).kind, "booked");
  const existing = { ...completion, status: "already_present", receipt: { ...receipt, outcome: { kind: "already_present", rating_events: 0 } } };
  assert.match(bookingView(existing, id).message, /No new rating events/);
  assert.equal(bookingView(existing, id).retryable, false);
  assert.equal(bookingView({ ...completion, receipt: null }, id).kind, "unknown");
  assert.equal(bookingView(completion, "other-session").kind, "unknown");
  assert.equal(bookingView(null, id).kind, "unknown");
});

test("human Elo joins seat to participant, not event position, and rejects unrelated detail", () => {
  assert.equal(humanEloRows(receipt, detail, id, 1)[0].participantId, "human");
  assert.equal(humanEloRows(receipt, detail, id, 1)[0].after, 1516);
  const reversed = { ...receipt, elo: [...receipt.elo].reverse() };
  assert.deepEqual(humanEloRows(receipt, detail, id, 1), humanEloRows(reversed, detail, id, 1));
  assert.equal(humanEloRows(receipt, detail, id, 0)[0].participantId, "engine");
  assert.deepEqual(humanEloRows(receipt, { match: { ...detail.match, match_id: "wrong" } }, id, 1), []);
  assert.deepEqual(humanEloRows(receipt, null, id, 1), []);
  assert.deepEqual(humanEloRows({ ...receipt, elo: [receipt.elo[0], receipt.elo[0]] }, detail, id, 1), []);
});

test("real retry adapter POSTs an empty body to the same session and consumes non-2xx facts", async () => {
  for (const [status, retryable] of [[503, true], [409, false]]) {
    let calls = 0;
    const result = await retryHumanBooking(async (url, options) => {
      calls++; assert.equal(url, `http://test/games/${id}/league-completion`);
      assert.deepEqual(options, { method: "POST" });
      return { status, json: async () => ({ session_id: id, league_completion: { status: "failed", retryable, error: "database / rebuild", receipt: null } }) };
    }, "http://test", id);
    assert.equal(calls, 1); assert.equal(result.retryable, retryable); assert.equal(result.status, "failed");
  }
  const result = await retryHumanBooking(async () => { throw new Error("response lost"); }, "http://test", id);
  assert.equal(result.status, "unknown"); assert.equal(result.retryable, true);
  assert.equal(classifyBookingRetry(404, { error: "no durable evidence" }, id).retryable, false);
  assert.equal(classifyBookingRetry(200, { session_id: "other", league_completion: completion }, id).status, "unknown");
  await assert.rejects(() => retryHumanBooking(async () => assert.fail("must not fetch"), "", "../bad"));
});

test("Play production wiring consumes booking and never performs retry by starting a game", () => {
  const page = readFileSync(new URL("../app/play/page.tsx", import.meta.url), "utf8");
  assert.match(page, /<HumanBookingPanel[^>]*completion=\{state\.league_completion\}/);
  assert.match(page, /await retryHumanBooking\(fetch,API,sessionId\)/);
  assert.match(page, /current\?\.session_id===sessionId/);
  assert.match(page, /humanStartBody\(agentId,resolveSeat\(seatChoice\),seed\)/);
  assert.doesNotMatch(page, /Earlier games|setSeed\(Number/);
  assert.match(page, /humanResult\(state.result,state.human_seat\)/);
});
