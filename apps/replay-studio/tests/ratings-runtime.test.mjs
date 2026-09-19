import assert from "node:assert/strict";
import test from "node:test";
import { describeLeaderboard } from "../app/league-runtime.mjs";
import {
  describeKind,
  eloText,
  gamesText,
  provisionalText,
  recordText,
} from "../app/ratings-runtime.mjs";

/**
 * D2 gate fixtures. The "You" row is the real first human row as the ledger
 * recorded it (2026-09-18 acceptance match): one rated win over one recorded
 * match, provisional, Elo 1530 after +29.8 from 1500. The Studio /ratings page
 * must render exactly these facts and nothing else.
 */
const youRow = {
  participant_id: "b901a2ea-645d-4c45-b4b9-407f5b6f39b7",
  kind: "human",
  display_name: "You",
  elo: 1530,
  rated_games: 1,
  recorded_games: 1,
  rated_wins: 1,
  rated_ties: 0,
  rated_losses: 0,
  provisional: true,
};

test("the real first human row renders exactly its recorded facts", () => {
  const [row] = describeLeaderboard([youRow]);
  assert.equal(row.participantId, "b901a2ea-645d-4c45-b4b9-407f5b6f39b7");
  assert.equal(row.kind, "human");
  assert.equal(describeKind(row.kind), "Human");
  assert.equal(row.elo, 1530);
  assert.equal(eloText(row), "1530");
  assert.equal(recordText(row), "1-0-0");
  assert.equal(gamesText(row), "1 rated · 1 recorded");
  assert.equal(provisionalText(row), "provisional");
});

test("an engine row labels its kind and never invents provisional", () => {
  const row = describeLeaderboard([
    {
      participant_id: "eng-bbc4b64c4bc73d54525e0ba138ff5f6a",
      kind: "engine",
      display_name: "S3 Rollout",
      elo: 1923,
      rated_games: 168,
      recorded_games: 168,
      rated_wins: 100,
      rated_ties: 4,
      rated_losses: 64,
      provisional: false,
    },
  ])[0];
  assert.equal(describeKind(row.kind), "Engine");
  assert.equal(recordText(row), "100-4-64");
  assert.equal(eloText(row), "1923");
  assert.equal(provisionalText(row), "", "an established row claims nothing");
});

test("a missing fact is unknown, never zero or 1500", () => {
  const row = describeLeaderboard([{ participant_id: "eng-x" }])[0];
  assert.equal(row.elo, null);
  assert.equal(eloText(row), "—");
  assert.equal(recordText(row), "—", "a partially known record is not a record");
  assert.equal(gamesText(row), "—");
  assert.equal(provisionalText(row), "");
  assert.equal(describeKind(null), null);
  assert.equal(describeKind("mystery"), null, "an unrecorded kind is never guessed");
});

test("rated and recorded counts stay two facts", () => {
  const row = describeLeaderboard([
    {
      participant_id: "eng-y",
      kind: "engine",
      display_name: "Self-Match Pair",
      elo: 1500,
      rated_games: 0,
      recorded_games: 3,
      rated_wins: 0,
      rated_ties: 0,
      rated_losses: 0,
      provisional: true,
    },
  ])[0];
  assert.equal(recordText(row), "0-0-0");
  assert.equal(gamesText(row), "0 rated · 3 recorded", "recorded games are not rated games");
});
