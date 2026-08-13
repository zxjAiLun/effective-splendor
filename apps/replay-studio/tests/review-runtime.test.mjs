import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildReviewRows,
  buildReviewSummary,
  isReviewTraceEnvelope,
  validateReviewTrace,
} from "../app/trace-runtime.mjs";

const fixtureUrl = new URL("./fixtures/rust-analysis-trace-v2-m07.json", import.meta.url);

async function fixture() {
  return JSON.parse(await readFile(fixtureUrl, "utf8"));
}

test("loads the Rust-generated AnalysisTraceV2 M07 fixture", async () => {
  const trace = validateReviewTrace(await fixture());
  assert.equal(trace.version, 2);
  assert.equal(trace.reviewer.id, "m07-determinization-champion");
  assert.equal(trace.reviewer.competitive_status, "champion");
  assert.equal(trace.reviewer.result_kind, "root_determinization");
  const frame = trace.frames[0];
  const { kind, rows } = buildReviewRows(trace, frame);
  assert.equal(kind, "root_determinization");
  assert.equal(rows.length, frame.legal_actions.length);
  assert.ok(rows.every((row) => Number.isFinite(row.meanUtility) && Number.isInteger(row.actionRank)));
  const actual = rows.find((row) => row.actual);
  assert.ok(actual, "recorded action is present in rows");
});

test("root-determinization rows expose utility, not prior/visit/Q", async () => {
  const trace = validateReviewTrace(await fixture());
  const { rows } = buildReviewRows(trace, trace.frames[0]);
  for (const row of rows) {
    assert.equal("prior" in row, false);
    assert.equal("visit" in row, false);
    assert.equal("q" in row, false);
    assert.equal("prior_micros" in row, false);
    assert.equal("visits" in row, false);
  }
});

test("summary counts decisions and agreements honestly", async () => {
  const trace = validateReviewTrace(await fixture());
  const all = buildReviewSummary(trace);
  assert.equal(all.decisions, trace.frames.length);
  const seat = trace.frames[0].actor;
  const summary = buildReviewSummary(trace, seat);
  assert.equal(summary.decisions, trace.frames.filter((frame) => frame.actor === seat).length);
  assert.ok(summary.scored >= 0);
  assert.ok(summary.unscored >= 0);
});

test("rejects a malformed V2 trace before rendering", async () => {
  const malformed = await fixture();
  delete malformed.frames[0].review_result.action_stats;
  assert.throws(
    () => validateReviewTrace(malformed),
    /review_result/,
  );
});

test("a V1 trace is not a V2 review envelope", async () => {
  const v1 = JSON.parse(await readFile(new URL("./fixtures/rust-analysis-trace-v1.json", import.meta.url), "utf8"));
  assert.equal(isReviewTraceEnvelope(v1), false);
});
