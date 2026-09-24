import assert from "node:assert/strict";
import test from "node:test";
import {
  attemptLines,
  describeRun,
  describeStep,
  seatOf,
  STAGE_LABEL,
  usageLine,
} from "../app/jev-trace-runtime.mjs";

const frame = (overrides = {}) => ({
  ply: 3,
  actor: 0,
  observation_hash: "obs-3",
  player_view: { viewer: 0 },
  recorded_action: { type: "take_tokens", take: { white: 2 } },
  ...overrides,
});

const decision = (overrides = {}) => ({
  ply: 3,
  actor: 0,
  observation_hash: "obs-3",
  family: "take_tokens",
  selected_index: 5,
  selected_action: { type: "take_tokens", take: { white: 2 } },
  offered_indices: [5, 6],
  stages: [
    { stage: "helper" },
    { stage: "family", attempts: [{ outcome: "received", selected_id: "take_tokens" }] },
    { stage: "move", attempts: [{ outcome: "received", selected_id: "a0" }] },
  ],
  ...overrides,
});

const bundle = (overrides = {}) => ({
  config: { agents: [{ program: "python", args: ["-u", "jev/agent.py"] }, { program: "splendor" }] },
  trace: { decisions: { "3": decision() }, ...overrides },
});

test("a run without a journal reports the step as not recorded instead of inventing one", () => {
  const step = describeStep(frame(), { config: bundle().config, trace: null });
  assert.equal(step.kind, "unavailable");
  assert.equal(step.usable, false);
  assert.match(step.detail, /recorded action below is still the verified replay/i);
});

test("the opponent's step is never presented as a Jev call", () => {
  const step = describeStep(frame({ actor: 1 }), bundle());
  assert.equal(step.kind, "opponent");
  assert.equal(step.usable, true);
  assert.deepEqual(step.stages, []);
});

test("an absent journal entry for the Jev seat is reported as unknown, not as a forced move", () => {
  const step = describeStep(frame({ ply: 9 }), bundle());
  assert.equal(step.kind, "missing");
  assert.match(step.detail, /forced single legal move needs no call/i);
  assert.match(step.detail, /left unknown/i);
});

test("a hash mismatch refuses the entry rather than showing another position's call", () => {
  const step = describeStep(frame({ observation_hash: "different" }), bundle());
  assert.equal(step.kind, "mismatch");
  assert.equal(step.usable, false);
  assert.equal(step.stages, undefined);
});

test("a journalled step shows both stages and confirms the recorded action agrees", () => {
  const step = describeStep(frame(), bundle());
  assert.equal(step.kind, "recorded");
  assert.equal(step.actionAgrees, true);
  assert.equal(step.family, "take_tokens");
  assert.equal(step.offeredCount, 2);
  assert.equal(step.stages.length, 3);
  assert.deepEqual(step.exclusions, { noop: 0, routed: 0, capped: 0 });
});

test("facts-only preserves color mapping and explicit return stages", () => {
  const path = [{ stage: "colors", mapping: "eligible_argmax_double", take: { white: 2 } },
    { stage: "return", selected_id: "r1", forced: false }];
  const step = describeStep(frame(), bundle({ decisions: { "3": decision({
    decision_mode: "take_double", selection_path: path, target_removed: 4,
    stages: [{ stage: "colors", attempts: [] }, { stage: "return", attempts: [] }],
  }) } }));
  assert.equal(step.kind, "recorded");
  assert.equal(step.decisionMode, "take_double");
  assert.equal(step.targetRemoved, 4);
  assert.deepEqual(step.selectionPath, path);
  assert.deepEqual(step.stages.map(s => s.stage), ["colors", "return"]);
  assert.match(STAGE_LABEL.colors, /program maps/);
  assert.match(STAGE_LABEL.return, /overflow return/);
});

test("a journal selection that disagrees with the replay is surfaced, and the replay still stands", () => {
  const disagreeing = bundle({
    decisions: { "3": decision({ selected_action: { type: "pass" } }) },
  });
  const step = describeStep(frame(), disagreeing);
  assert.equal(step.kind, "action_mismatch");
  assert.equal(step.actionAgrees, false);
  assert.match(step.detail, /replay stands/i);
});

test("retry attempts stay attached to their stage instead of collapsing into one answer", () => {
  const retried = bundle({
    decisions: {
      "3": decision({
        stages: [
          {
            stage: "move",
            attempts: [
              { outcome: "error", code: "http_error", http_status: 429 },
              { outcome: "retry_wait", seconds: 0.5 },
              { outcome: "received", selected_id: "a0" },
            ],
          },
        ],
      }),
    },
  });
  const step = describeStep(frame(), retried);
  const stage = step.stages.find((s) => s.stage === "move");
  assert.equal(stage.attempts.length, 3);
  assert.deepEqual(attemptLines(stage.attempts[0]), ["Attempt failed: http_error (HTTP 429)"]);
  assert.deepEqual(attemptLines(stage.attempts[1]), ["Waiting 0.5s before retry"]);
  assert.deepEqual(attemptLines(stage.attempts[2]), ["Selected a0", "usage not reported for this attempt"]);
});

test("an attempt with reported usage shows it, and missing usage is stated rather than assumed free", () => {
  assert.match(
    attemptLines({ outcome: "received", selected_id: "a1", usage: { input_tokens: 120, output_tokens: 4 } }).join(" | "),
    /120 in \/ 4 out/,
  );
  assert.equal(usageLine({ input_tokens: 300, output_tokens: 9 }), "300 in / 9 out");
  assert.match(usageLine({ input_tokens: 300, output_tokens: 9, unknown_usage_attempts: 2 }), /2 attempt\(s\) did not report usage/);
  assert.equal(usageLine(null), "Usage not recorded");
});

test("the Jev seat is read from the run's own agent commands, and unknown stays unknown", () => {
  assert.equal(seatOf(bundle().config), 0);
  assert.equal(
    seatOf({ agents: [{ program: "splendor" }, { program: "python", args: ["-u", "jev/agent.py"] }] }),
    1,
  );
  assert.equal(seatOf({ agents: [{ program: "a" }, { program: "b" }] }), null);
  assert.equal(seatOf(null), null);
});

test("run states that must stay distinct do so: completed, truncated, and no document", () => {
  assert.deepEqual(
    describeRun({ run_id: "r1", game_document: "completed_replay" }),
    {
      runId: "r1",
      journalRecorded: false,
      traceSummary: false,
      gameDocument: "completed_replay",
      playable: true,
      completed: true,
      documentLabel: "Verified completed replay",
      status: null,
      agentVersion: null,
      modelVersions: [],
      decisions: null,
    },
  );
  const truncated = describeRun({ run_id: "r2", game_document: "truncated_prefix" });
  assert.equal(truncated.playable, true);
  assert.equal(truncated.completed, false);
  assert.match(truncated.documentLabel, /no winner/);
  const failed = describeRun({ run_id: "r3", game_document: "unavailable", status: "failed" });
  assert.equal(failed.playable, false);
  assert.equal(failed.completed, false);
  assert.equal(describeRun(null).runId, "");
});

test("a step where the Jev seat could not be determined is treated as an opponent step, never guessed", () => {
  const unknownSeat = { config: { agents: [{ program: "a" }, { program: "b" }] }, trace: bundle().trace };
  const step = describeStep(frame(), unknownSeat);
  assert.equal(step.kind, "opponent");
  assert.match(step.detail, /was not the Jev seat/);
});
