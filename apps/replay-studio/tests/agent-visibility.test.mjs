import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { visibleAgents, visibleGame, visibleParticipant, visibleReport, visibleRatingPoints, visibleReviewers, visibleExperimentIndex, VISIBLE_AGENT_IDS } from "../app/agent-visibility.mjs";

const registry = JSON.parse(readFileSync(new URL("../../../benchmarks/studio-1v1.registry.json", import.meta.url), "utf8"));

test("Studio registry and UI expose exactly the curated roster", () => {
  assert.deepEqual(registry.agents.map((agent) => agent.id), [...VISIBLE_AGENT_IDS]);
  assert.deepEqual(visibleAgents([...registry.agents, { id: "aran-v02" }, { id: "m22-scaled-self-play" }]), registry.agents);
});

test("each kept heuristic has an observed positive S3 result; the losing two-ply pilot is absent", () => {
  for (const [id, file] of [
    ["heuristic-v028", "s4-heuristic-v028-pilot-v1.result.json"],
    ["heuristic-v029", "s4-heuristic-v029-pilot-v1.result.json"],
    ["heuristic-v030", "s4-heuristic-v030-pilot-v1.result.json"],
    ["heuristic-v031", "s4-heuristic-v031-pilot-v1.result.json"],
    ["heuristic-v032c", "s4-heuristic-v032c-pilot-v1.result.json"],
  ]) {
    const result = JSON.parse(readFileSync(new URL(`../../../benchmarks/${file}`, import.meta.url), "utf8"));
    const s3 = result.pairings.find((pair) => pair.opponent === "s3-rollout");
    assert.ok(s3, `${id} is missing an S3 result`);
    assert.ok(s3.wins + s3.ties / 2 > s3.matches / 2, id);
  }
  assert.equal(VISIBLE_AGENT_IDS.has("heuristic-v032"), false);
  assert.equal(VISIBLE_AGENT_IDS.has("aran-v02"), false); // no same-object S3 result
});

test("legacy league identities and game rows show only humans and curated engines", () => {
  const human = { participantId: "b901a2ea-645d-4c45-b4b9-407f5b6f39b7", displayName: "You" };
  const s3 = { participantId: "eng-a3cd76c0cac48d28bac4d69780e341de", displayName: "splendor.exe:agent-s3-rollout" };
  const old = { participantId: "eng-f2f1c2bed2699fa846f59620175d8e94", displayName: "★ aran-v0.2 (Mortal SE-ResNet Dueling · 50.7% vs v0.2.9)" };
  assert.equal(visibleParticipant(human), true);
  assert.equal(visibleParticipant(s3), true);
  assert.equal(visibleParticipant(old), false);
  assert.equal(visibleParticipant({participantId: "aran-v02", kind: "engine"}), false);
  assert.equal(visibleGame({seats:[human,s3]}), true);
  assert.equal(visibleGame({seats:[human,old]}), false);
});

test("decoded game seats and rating points are filtered without changing cursors or raw rows", () => {
  const human = { participantId: "b901a2ea-645d-4c45-b4b9-407f5b6f39b7", displayName: "You" };
  const s3 = { participantId: "eng-a3cd76c0cac48d28bac4d69780e341de", displayName: "splendor.exe:agent-s3-rollout" };
  const weak = { participantId: "eng-weak", displayName: "M07 Determinization Champion" };
  const page = { rows: [{ matchId: "1", seats: [human, s3] }, { matchId: "2", seats: [human, weak] }], nextBeforeLeagueSeq: 3 };
  assert.deepEqual(page.rows.filter(visibleGame).map((row) => row.matchId), ["1"]);
  assert.equal(page.nextBeforeLeagueSeq, 3);
  const points = [{ opponent_id: s3.participantId, opponent_name: s3.displayName, league_seq: 1 }, { opponent_id: weak.participantId, opponent_name: weak.displayName, league_seq: 2 }];
  assert.deepEqual(visibleRatingPoints(points), [points[0]]);
  assert.equal(points.length, 2);
});

test("reviewer and experiment UI reject unsupported model identities including old deep links", () => {
  assert.deepEqual(visibleReviewers([{id:"aran-v02-review"}, {id:"s3-rollout-review"}, {id:"prism-v01-review"}, {id:"prism-v011-review"}, {id:"prism-alpha-v01-review"}]), [{id:"s3-rollout-review"}, {id:"prism-v01-review"}, {id:"prism-v011-review"}, {id:"prism-alpha-v01-review"}]);
  const index = {experiments:[{id:"old",pairings:[{candidate_model_id:"aran-v02",opponent_model_id:"s3-rollout"}]},{id:"kept",pairings:[{candidate_model_id:"heuristic-v030",opponent_model_id:"s3-rollout"}]}]};
  assert.deepEqual(visibleExperimentIndex(index).experiments.map((item)=>item.id), ["kept"]);
  assert.equal(index.experiments.length, 2);
});

test("archived report filters agents and both ends of the matrix without altering evidence", () => {
  const report = { agents:[{agent_id:"s3-rollout"},{agent_id:"m22-scaled-self-play"}], head_to_head:[{agent_a:"s3-rollout",agent_b:"m22-scaled-self-play"},{agent_a:"s3-rollout",agent_b:"s3-rollout"}], scheduled_matches: 10 };
  const shown = visibleReport(report);
  assert.deepEqual(shown.agents.map((agent)=>agent.agent_id),["s3-rollout"]);
  assert.deepEqual(shown.head_to_head,[report.head_to_head[1]]);
  assert.equal(shown.scheduled_matches,10);
  assert.equal(report.agents.length,2);
});
