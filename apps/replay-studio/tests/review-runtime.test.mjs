import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  actionKey,
  buildReviewRows,
  buildReviewSummary,
  defaultReviewerIdFor,
  isReviewTraceEnvelope,
  reviewRecommendedAction,
  reviewerSupportsPlayerCount,
  validateReviewTrace,
} from "../app/trace-runtime.mjs";

const fixtureUrl = new URL("./fixtures/rust-analysis-trace-v2-m07.json", import.meta.url);
const s3FixtureUrl = new URL("./fixtures/rust-analysis-trace-v2-s3.json", import.meta.url);
const reviewerRegistryUrl = new URL("../../../benchmarks/studio-reviewers.registry.json", import.meta.url);

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
  ]);
  // Full cache identity: D/P/root/eval seeds plus the exact n1/M07 configs.
  const config = trace.reviewer.config;
  assert.equal(config.determinizations, 4);
  assert.equal(config.ply_cap, 120);
  assert.equal(config.sample_seed, 43300101);
  assert.equal(config.root_seed, 20260812);
  assert.deepEqual(config.n1_config, {
    sample_seed: 20260703,
    sample_count: 4,
    continuation_search: { max_depth_turns: 1, max_nodes: 1 },
  });
  assert.deepEqual(config.m07_config, {
    sample_seed: 20260703,
    sample_count: 4,
    continuation_search: { max_depth_turns: 1, max_nodes: 2000 },
  });
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
    assert.equal(row.evaluated, true);
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

test("a fast-path frame reports null proposals and renders Not evaluated", async () => {
  const trace = validateReviewTrace(await s3Fixture());
  const frame = trace.frames[0];
  frame.review_result.decision_path = "heuristic_fast_path";
  frame.review_result.recommended_action = frame.review_result.base_heuristic_action;
  frame.review_result.n1_proposal = null;
  frame.review_result.m07_proposal = null;
  frame.review_result.recommended_differs_from_base_heuristic = false;
  frame.recommended_matches_recorded =
    actionKey(frame.review_result.recommended_action) === actionKey(frame.recorded_action);
  const validated = validateReviewTrace(trace);
  const { rows } = buildReviewRows(validated, validated.frames[0]);
  const n1 = rows.find((row) => row.role === "n1_proposal");
  const m07 = rows.find((row) => row.role === "m07_proposal");
  assert.equal(n1.action, null);
  assert.equal(n1.evaluated, false);
  assert.equal(m07.action, null);
  assert.equal(m07.evaluated, false);
  // A missing (undefined) proposal is rejected as well as a fabricated one.
  delete trace.frames[0].review_result.n1_proposal;
  assert.throws(() => validateReviewTrace(trace), /decision_path/);
});

test("rejects an S3 trace whose fast path fabricates proposals", async () => {
  const malformed = await s3Fixture();
  const frame = malformed.frames[0];
  frame.review_result.decision_path = "heuristic_fast_path";
  frame.review_result.n1_proposal = frame.review_result.base_heuristic_action;
  frame.review_result.m07_proposal = frame.review_result.base_heuristic_action;
  assert.throws(
    () => validateReviewTrace(malformed),
    /fast-path/,
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

test("the reviewer registry declares player-count-aware defaults without ghost metrics", async () => {
  const registry = JSON.parse(await readFile(reviewerRegistryUrl, "utf8"));
  assert.equal(registry.format, "effective-splendor-studio-reviewers");
  assert.ok(registry.reviewers.every((reviewer) => !("is_default" in reviewer)));
  for (const reviewer of registry.reviewers) {
    assert.ok(!reviewer.available_metrics.includes("rollout_outcome_score"));
    assert.ok(Array.isArray(reviewer.default_for_player_counts));
  }
  const s3 = registry.reviewers.find((reviewer) => reviewer.id === "s3-rollout-review");
  const m07 = registry.reviewers.find((reviewer) => reviewer.id === "m07-determinization-champion");
  assert.deepEqual(s3.available_metrics, ["recommended_action", "decision_path"]);
  assert.deepEqual(s3.default_for_player_counts, [2]);
  assert.deepEqual(m07.default_for_player_counts, [3, 4]);
  assert.ok(!JSON.stringify(registry).includes("rollout_outcome_score"));
});

test("reviewer default selection is player-count aware", () => {
  const reviewers = [
    { id: "s3-rollout-review", supported_player_counts: [2], default_for_player_counts: [2] },
    { id: "m07-determinization-champion", supported_player_counts: [2, 3, 4], default_for_player_counts: [3, 4] },
    { id: "m13-neural-ismcts", supported_player_counts: [2, 3, 4], default_for_player_counts: [] },
  ];
  assert.equal(defaultReviewerIdFor(reviewers, 2), "s3-rollout-review");
  assert.equal(defaultReviewerIdFor(reviewers, 3), "m07-determinization-champion");
  assert.equal(defaultReviewerIdFor(reviewers, 4), "m07-determinization-champion");
  assert.equal(reviewerSupportsPlayerCount(reviewers[0], 2), true);
  assert.equal(reviewerSupportsPlayerCount(reviewers[0], 3), false);
  assert.equal(reviewerSupportsPlayerCount(reviewers[0], 4), false);
  assert.equal(reviewerSupportsPlayerCount(reviewers[1], 4), true);
  assert.equal(defaultReviewerIdFor([], 2), "");
});
