import assert from "node:assert/strict";
import test from "node:test";
import {
  STATUS_LABEL,
  buildExperimentsQuery,
  filterMatches,
  filterPairings,
  isBrowsableAvailability,
  parseExperimentsQuery,
  stepCandidateDecision,
  validateExperimentBundle,
} from "../app/experiment-runtime.mjs";

const PAIRINGS = [
  { evaluation_id: "m35a-m28a-vs-d2v2-v1", candidate_model_id: "M28A", opponent_model_id: "M25-D2-v2", status: "VALID", label: "M28A vs D2-v2" },
  { evaluation_id: "m35a-m32a-vs-m07-v1", candidate_model_id: "M32A", opponent_model_id: "M07", status: "VALID", label: "M32A vs M07" },
  { evaluation_id: "m35a-m29a-v2-vs-m07-v1", candidate_model_id: "M29A-v2", opponent_model_id: "M07", status: "EXCLUDED_PREFIX", label: "M29A-v2 vs M07" },
];

test("pairing filter searches by label, id, and models", () => {
  assert.equal(filterPairings(PAIRINGS, { query: "m28a" }).length, 1);
  assert.equal(filterPairings(PAIRINGS, { query: "M28A" })[0].label, "M28A vs D2-v2");
  assert.equal(filterPairings(PAIRINGS, { query: "m07" }).length, 2);
  assert.equal(filterPairings(PAIRINGS, { query: "" }).length, 3);
  assert.equal(filterPairings(PAIRINGS, {}).length, 3);
  assert.equal(filterPairings(PAIRINGS, { query: "zzz" }).length, 0);
});

test("pairing status filter separates formal from prefix and nontermination", () => {
  assert.equal(filterPairings(PAIRINGS, { status: "valid" }).length, 2);
  assert.equal(filterPairings(PAIRINGS, { status: "excluded_prefix" }).length, 1);
  assert.equal(filterPairings(PAIRINGS, { status: "nontermination" }).length, 1);
  assert.equal(filterPairings(PAIRINGS, { status: "nontermination" })[0].candidate_model_id, "M29A-v2");
  assert.equal(filterPairings(PAIRINGS, { status: "all" }).length, 3);
});

test("match availability filtering keeps only the requested class", () => {
  const matches = [
    { match_index: 0, availability: "valid" },
    { match_index: 60, availability: "excluded_prefix" },
    { match_index: 61, availability: "nontermination" },
    { match_index: 62, availability: "not_started" },
  ];
  assert.deepEqual(filterMatches(matches, { status: "all" }).map((m) => m.match_index), [0, 60, 61, 62]);
  assert.deepEqual(filterMatches(matches, { status: "valid" }).map((m) => m.match_index), [0]);
  assert.deepEqual(filterMatches(matches, { status: "nontermination" }).map((m) => m.match_index), [61]);
});

test("status labels mark excluded and nonterminal slots unambiguously", () => {
  assert.equal(STATUS_LABEL.valid, "VALID");
  assert.equal(STATUS_LABEL.excluded_prefix, "EXCLUDED_PREFIX / NOT_SCORED");
  assert.equal(STATUS_LABEL.nontermination, "NONTERMINATION / NO REPLAY");
  assert.equal(isBrowsableAvailability("valid"), true);
  assert.equal(isBrowsableAvailability("excluded_prefix"), true);
  assert.equal(isBrowsableAvailability("nontermination"), false);
  assert.equal(isBrowsableAvailability("not_started"), false);
});

test("deep link parsing and building round-trip", () => {
  const params = new URLSearchParams("experiment=m35a&pairing=m35a-m28a-vs-d2v2-v1&match=12");
  assert.deepEqual(parseExperimentsQuery(params), {
    experiment: "m35a",
    pairing: "m35a-m28a-vs-d2v2-v1",
    match: 12,
  });
  assert.equal(parseExperimentsQuery(new URLSearchParams("experiment=m35a")), null);
  assert.equal(parseExperimentsQuery(new URLSearchParams("pairing=p")), null);
  assert.equal(
    parseExperimentsQuery(new URLSearchParams("experiment=m35a&pairing=p&match=abc")).match,
    null,
  );
  assert.equal(
    buildExperimentsQuery({ experiment: "m35a", pairing: "p", match: 3 }),
    "/experiments?experiment=m35a&pairing=p&match=3",
  );
  assert.equal(buildExperimentsQuery({ experiment: "", pairing: "", match: null }), "/experiments");
});

function bundleFrame(ply, actor, extra = {}) {
  return {
    ply,
    actor,
    actor_model: `model-${actor}`,
    actor_seat: actor,
    candidate_acted: actor === 0,
    recorded_action: { type: "take_tokens" },
    legal_actions: [{ type: "pass" }],
    player_view: { viewer: actor },
    referee_reveal: { seed: 1, decks: [[], [], []], players: [] },
    ...extra,
  };
}

test("bundle validation enforces the API contract", () => {
  const good = {
    format: "effective-splendor-experiment-replay-bundle",
    version: 1,
    game_id: "g1",
    availability: "valid",
    frames: [bundleFrame(0, 0), bundleFrame(1, 1)],
  };
  assert.equal(validateExperimentBundle(good), good);
  assert.throws(() => validateExperimentBundle({ ...good, version: 2 }), /format\/version/);
  assert.throws(() => validateExperimentBundle({ ...good, frames: [] }), /no frames/);
  assert.throws(
    () => validateExperimentBundle({ ...good, frames: [bundleFrame(1, 0)] }),
    /non-contiguous/,
  );
  assert.throws(
    () =>
      validateExperimentBundle({
        ...good,
        frames: [bundleFrame(0, 1, { player_view: { viewer: 0 } })],
      }),
    /projected for the actor/,
  );
  assert.throws(
    () => validateExperimentBundle({ ...good, availability: "nontermination" }),
    /availability/,
  );
});

test("candidate-only stepping jumps between candidate decisions", () => {
  const frames = [
    { candidate_acted: true },
    { candidate_acted: false },
    { candidate_acted: false },
    { candidate_acted: true },
    { candidate_acted: false },
  ];
  assert.equal(stepCandidateDecision(frames, 0, 1), 3);
  assert.equal(stepCandidateDecision(frames, 3, -1), 0);
  // From an opponent ply, forward/backward land on the nearest candidate
  // decision at/beyond (before) the current ply.
  assert.equal(stepCandidateDecision(frames, 1, 1), 3);
  assert.equal(stepCandidateDecision(frames, 1, -1), 0);
  assert.equal(stepCandidateDecision([], 0, 1), 0);
});

test("candidate-only stepping stays on the edge candidate at both boundaries", () => {
  // Real M28A-vs-D2-v2 shape: candidate acts on even plies, opponent on odd;
  // the opponent plays the final ply 65.
  const frames = Array.from({ length: 66 }, (_, index) => ({
    candidate_acted: index % 2 === 0,
  }));
  // Forward from the last candidate decision (64): stay on 64, never the
  // opponent's final ply 65 (review-repro bug).
  assert.equal(stepCandidateDecision(frames, 64, 1), 64);
  // Forward from the opponent's final ply (65): fall back to the last
  // candidate decision 64.
  assert.equal(stepCandidateDecision(frames, 65, 1), 64);
  // Backward past the first candidate decision: stay on 0.
  assert.equal(stepCandidateDecision(frames, 0, -1), 0);
  // Backward from the opponent's first ply (1): first candidate 0.
  assert.equal(stepCandidateDecision(frames, 1, -1), 0);
  // Interior navigation still works in both directions.
  assert.equal(stepCandidateDecision(frames, 63, 1), 64);
  assert.equal(stepCandidateDecision(frames, 1, 1), 2);
  assert.equal(stepCandidateDecision(frames, 64, -1), 62);
  assert.equal(stepCandidateDecision(frames, 65, -1), 64);
  // A single-frame candidate-only game pins to 0.
  const single = [{ candidate_acted: true }];
  assert.equal(stepCandidateDecision(single, 0, 1), 0);
  assert.equal(stepCandidateDecision(single, 0, -1), 0);
  // A game with no candidate decisions keeps the current position.
  const none = [{ candidate_acted: false }, { candidate_acted: false }];
  assert.equal(stepCandidateDecision(none, 0, 1), 0);
  assert.equal(stepCandidateDecision(none, 1, -1), 1);
});

test("plain ply navigation clamps at the first and last frame", () => {
  // Mirrors the page's non-candidate stepping: Math.max(0, Math.min(len-1, current+delta)).
  const clamp = (length, current, delta) =>
    Math.max(0, Math.min(length - 1, current + delta));
  const frames = [{}, {}, {}, {}, {}];
  assert.equal(clamp(frames.length, 0, -1), 0);
  assert.equal(clamp(frames.length, 4, 1), 4);
  assert.equal(clamp(frames.length, 2, -1), 1);
  assert.equal(clamp(frames.length, 2, 1), 3);
  assert.equal(clamp(frames.length, 4, 5), 4);
  assert.equal(clamp(frames.length, 0, -5), 0);
});
