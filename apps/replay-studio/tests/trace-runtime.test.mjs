import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildAnalysisRows,
  formatActionLabel,
  validateAnalysisTrace,
} from "../app/trace-runtime.mjs";

const fixtureUrl = new URL("./fixtures/rust-analysis-trace-v1.json", import.meta.url);

async function fixture() {
  return JSON.parse(await readFile(fixtureUrl, "utf8"));
}

test("loads the Rust-generated AnalysisTraceV1 fixture", async () => {
  const trace = validateAnalysisTrace(await fixture());
  const frame = trace.frames[0];
  const cards = new Map(trace.catalog.cards.map((card) => [card.id, card]));
  const rows = buildAnalysisRows(trace, frame);

  assert.equal(trace.catalog.cards.length, 90);
  assert.equal(frame.player_view.viewer, frame.actor);
  assert.equal(frame.player_view.public.market.length, 3);
  assert.equal(rows.length, frame.legal_actions.length);
  assert.equal(rows[0].prior, rows[0].prior_micros / trace.value_scale);
  assert.equal(rows[0].visit, rows[0].visits / frame.neural_result.stats.root_visits);
  assert.equal(
    rows[0].q,
    rows[0].value_sum_by_player[frame.actor] / rows[0].visits / trace.value_scale,
  );
  assert.match(formatActionLabel(rows[0].action, frame, cards), /Take|Buy|Reserve|Pass/);
});

test("rejects a malformed trace before rendering", async () => {
  const malformed = await fixture();
  delete malformed.frames[0].player_view.public.market;
  assert.throws(
    () => validateAnalysisTrace(malformed),
    /player_view\.public\.market/,
  );
});

test("semantic actions with different returns have distinct labels", async () => {
  const trace = validateAnalysisTrace(await fixture());
  const frame = trace.frames[0];
  const cards = new Map(trace.catalog.cards.map((card) => [card.id, card]));
  const zero = { white: 0, blue: 0, green: 0, red: 0, black: 0, gold: 0 };
  const take = {
    type: "take_tokens",
    take: { ...zero, white: 1, blue: 1, green: 1 },
    return: { ...zero, red: 1 },
  };
  const takeOtherReturn = { ...take, return: { ...zero, black: 1 } };
  const reserve = {
    type: "reserve_deck",
    tier: "Three",
    return: { ...zero, gold: 1 },
  };
  const reserveOtherReturn = { ...reserve, return: { ...zero, white: 1 } };

  const takeLabel = formatActionLabel(take, frame, cards);
  const reserveLabel = formatActionLabel(reserve, frame, cards);
  assert.notEqual(takeLabel, formatActionLabel(takeOtherReturn, frame, cards));
  assert.notEqual(reserveLabel, formatActionLabel(reserveOtherReturn, frame, cards));
  assert.match(takeLabel, /return R/);
  assert.match(reserveLabel, /return ★/);
});
