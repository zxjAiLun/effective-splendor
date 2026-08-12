import assert from "node:assert/strict";
import test from "node:test";
import { headToHeadCell, validateRatingReport } from "../app/rating-runtime.mjs";

const report = { format: "effective-splendor-rating-report", version: 1, tournament_id: "test", registry_hash: "0".repeat(64), round_robin_plan_hash: "1".repeat(64), scheduled_matches: 2, completed_matches: 2, aborted_matches: 0, agents: [
  { rank: 1, agent_id: "A", display_name: "A", class: "search", completed: 2, aborted: 0, wins: 2, ties: 0, losses: 0, live_elo: 1516, official_elo: 1600, provisional: true },
  { rank: 2, agent_id: "B", display_name: "B", class: "baseline", completed: 2, aborted: 0, wins: 0, ties: 0, losses: 2, live_elo: 1484, official_elo: 1400, provisional: true },
], head_to_head: [{ agent_a: "A", agent_b: "B", completed: 2, aborted: 0, wins_a: 2, ties: 0, wins_b: 0 }], pair_evaluation_report_hashes: ["2".repeat(64)] };

test("validates report and orients matrix cells by row", () => {
  validateRatingReport(report);
  assert.deepEqual(headToHeadCell(report, "A", "B"), { label: "2-0-0", tone: "positive" });
  assert.deepEqual(headToHeadCell(report, "B", "A"), { label: "0-0-2", tone: "negative" });
});

test("rejects malformed plan provenance", () => {
  assert.throws(() => validateRatingReport({ ...report, round_robin_plan_hash: "short" }), /round_robin_plan_hash/);
});
