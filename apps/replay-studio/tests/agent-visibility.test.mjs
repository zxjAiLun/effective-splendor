import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { visibleAgents, visibleGame, visibleParticipant, visibleReport, visibleRatingPoints, visibleReviewers, visibleExperimentIndex, VISIBLE_AGENT_IDS } from "../app/agent-visibility.mjs";

const registry = JSON.parse(readFileSync(new URL("../../../benchmarks/studio-1v1.registry.json", import.meta.url), "utf8"));

test("Studio registry and UI expose the explicitly retired empty model roster", () => {
  assert.equal(registry.registry_id, "studio-1v1-retired-2026-10-12");
  assert.deepEqual(registry.agents, []);
  assert.equal(VISIBLE_AGENT_IDS.size, 0);
  assert.deepEqual(visibleAgents([{ id: "prism-v011" }, { id: "aran-v02" }, { id: "s3-rollout" }]), []);
});

test("old engine identities stay hidden while humans and future human matches remain visible", () => {
  const human = { participantId: "b901a2ea-645d-4c45-b4b9-407f5b6f39b7", displayName: "You" };
  const s3 = { participantId: "eng-a3cd76c0cac48d28bac4d69780e341de", displayName: "splendor.exe:agent-s3-rollout" };
  const prism = { participantId: "prism-v011", displayName: "Prism v0.1.1" };
  const secondHuman = { participantId: "12345678-1234-1234-1234-123456789012", displayName: "Local player" };
  assert.equal(visibleParticipant(human), true);
  assert.equal(visibleParticipant(secondHuman), true);
  assert.equal(visibleParticipant(s3), false);
  assert.equal(visibleParticipant(prism), false);
  assert.equal(visibleGame({seats:[human,secondHuman]}), true);
  assert.equal(visibleGame({seats:[human,prism]}), false);
});

test("decoded game seats and rating points are filtered without changing cursors or raw rows", () => {
  const human = { participantId: "b901a2ea-645d-4c45-b4b9-407f5b6f39b7", displayName: "You" };
  const secondHuman = { participantId: "12345678-1234-1234-1234-123456789012", displayName: "Local player" };
  const weak = { participantId: "eng-weak", displayName: "M07 Determinization Champion" };
  const page = { rows: [{ matchId: "1", seats: [human, secondHuman] }, { matchId: "2", seats: [human, weak] }], nextBeforeLeagueSeq: 3 };
  assert.deepEqual(page.rows.filter(visibleGame).map((row) => row.matchId), ["1"]);
  assert.equal(page.nextBeforeLeagueSeq, 3);
  const points = [{ opponent_id: secondHuman.participantId, opponent_name: secondHuman.displayName, league_seq: 1 }, { opponent_id: weak.participantId, opponent_name: weak.displayName, league_seq: 2 }];
  assert.deepEqual(visibleRatingPoints(points), [points[0]]);
  assert.equal(points.length, 2);
});

test("reviewer and experiment UI reject all pre-cleanup model identities", () => {
  assert.deepEqual(visibleReviewers([{id:"aran-v02-review"}, {id:"s3-rollout-review"}, {id:"prism-v01-review"}, {id:"prism-v011-review"}, {id:"prism-alpha-v01-review"}]), []);
  const index = {experiments:[{id:"old",pairings:[{candidate_model_id:"aran-v02",opponent_model_id:"s3-rollout"}]},{id:"prism",pairings:[{candidate_model_id:"prism-v011",opponent_model_id:"prism-alpha-v01"}]}]};
  assert.deepEqual(visibleExperimentIndex(index).experiments, []);
  assert.equal(index.experiments.length, 2);
});

test("archived report filters all retired agents and matrix edges without altering evidence", () => {
  const report = { agents:[{agent_id:"s3-rollout"},{agent_id:"prism-v011"}], head_to_head:[{agent_a:"s3-rollout",agent_b:"prism-v011"},{agent_a:"s3-rollout",agent_b:"s3-rollout"}], scheduled_matches: 10 };
  const shown = visibleReport(report);
  assert.deepEqual(shown.agents, []);
  assert.deepEqual(shown.head_to_head, []);
  assert.equal(shown.scheduled_matches,10);
  assert.equal(report.agents.length,2);
});
