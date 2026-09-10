import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  actionKey,
  buildReviewRows,
  buildReviewSummary,
  isReviewTraceEnvelope,
  reviewRecommendedAction,
  validateReviewTrace,
} from "../app/trace-runtime.mjs";

const fixtureUrl = new URL("./fixtures/rust-analysis-trace-v2-m07.json", import.meta.url);
const s3FixtureUrl = new URL("./fixtures/rust-analysis-trace-v2-s3.json", import.meta.url);

async function fixture() {
  return JSON.parse(await readFile(fixtureUrl, "utf8"));
}

async function s3Fixture() {
  return JSON.parse(await readFile(s3FixtureUrl, "utf8"));
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

test("loads the Rust-generated AnalysisTraceV2 S3 policy-recommendation fixture", async () => {
  const trace = validateReviewTrace(await s3Fixture());
  assert.equal(trace.version, 2);
  assert.equal(trace.reviewer.id, "s3-rollout-review");
  assert.equal(trace.reviewer.competitive_status, "champion");
  assert.equal(trace.reviewer.result_kind, "policy_recommendation");
  assert.equal(trace.reviewer.checkpoint_hash, null);
  assert.deepEqual(trace.reviewer.provenance.metrics, [
    "recommended_action",
    "decision_path",
    "rollout_outcome_score",
  ]);
  const frame = trace.frames[0];
  const recommended = reviewRecommendedAction(frame.review_result);
  assert.deepEqual(recommended, frame.review_result.recommended_action);
});

test("policy-recommendation rows expose the proposal set, not utility/prior/visit/Q", async () => {
  const trace = validateReviewTrace(await s3Fixture());
  const frame = trace.frames[0];
  const { kind, rows, decisionPath, recommendedDiffersFromBase } = buildReviewRows(trace, frame);
  assert.equal(kind, "policy_recommendation");
  assert.ok(["heuristic_fast_path", "proposals_agreed", "ply_cap_fallback", "rollout_comparison"].includes(decisionPath));
  assert.equal(typeof recommendedDiffersFromBase, "boolean");
  assert.deepEqual(
    rows.map((row) => row.role),
    ["recommended_action", "base_heuristic_action", "n1_proposal", "m07_proposal"],
  );
  for (const row of rows) {
    assert.ok(row.action, "every proposal row carries an action");
    assert.equal("meanUtility" in row, false);
    assert.equal("utilityGap" in row, false);
    assert.equal("actionRank" in row, false);
    assert.equal("prior" in row, false);
    assert.equal("visit" in row, false);
    assert.equal("q" in row, false);
    assert.equal("unscored" in row, false);
  }
  // The recommendation is always one of the proposals.
  assert.ok(rows.some((row) => row.recommended));
  assert.equal(
    recommendedDiffersFromBase,
    actionKey(frame.review_result.recommended_action) !== actionKey(frame.review_result.base_heuristic_action),
  );
});

test("policy-recommendation summary counts matches/differs and decision paths only", async () => {
  const trace = validateReviewTrace(await s3Fixture());
  const all = buildReviewSummary(trace);
  assert.equal(all.decisions, trace.frames.length);
  assert.equal(all.matches + all.differs, all.decisions);
  assert.equal(Object.values(all.decisionPaths).reduce((sum, count) => sum + count, 0), all.decisions);
  assert.equal("scored" in all, false);
  assert.equal("unscored" in all, false);
  assert.equal("agreements" in all, false);
  assert.equal("medianActionRank" in all, false);
  const seat = trace.frames[0].actor;
  const seatSummary = buildReviewSummary(trace, seat);
  assert.equal(seatSummary.decisions, trace.frames.filter((frame) => frame.actor === seat).length);
});

test("rejects an S3 trace whose fast path fabricates proposals", async () => {
  const malformed = await s3Fixture();
  const frame = malformed.frames[0];
  frame.review_result.decision_path = "heuristic_fast_path";
  frame.review_result.n1_proposal = frame.recorded_action;
  assert.notDeepEqual(frame.recorded_action, frame.review_result.base_heuristic_action);
  assert.throws(
    () => validateReviewTrace(malformed),
    /decision_path/,
  );
});

test("rejects an S3 trace with a non-boolean differs flag", async () => {
  const malformed = await s3Fixture();
  malformed.frames[0].review_result.recommended_differs_from_base_heuristic = "yes";
  assert.throws(
    () => validateReviewTrace(malformed),
    /recommended_differs_from_base_heuristic/,
  );
});
