import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const repo = process.cwd();
const formalRoot = join(repo, "artifacts", "formal-2026-08-11");
const datasetRoot = join(formalRoot, "m11-dataset");
const evaluationRoot = join(formalRoot, "m10-evaluation");
const manifestPath = join(repo, "benchmarks", "m10-ismcts-v1.league.json");
const listPath = join(
  datasetRoot,
  "formal-m10-evaluation-2026-08-11-v1.replay-list.json",
);
const datasetPath = join(
  datasetRoot,
  "formal-m10-evaluation-2026-08-11-v1.dataset.json",
);

function fail(message) {
  throw new Error(message);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function sha256Bytes(...parts) {
  const hash = createHash("sha256");
  for (const part of parts) hash.update(part);
  return hash.digest("hex");
}

function semanticHash(domain, value) {
  return sha256Bytes(Buffer.from(`${domain}\0`, "utf8"), JSON.stringify(value));
}

function fileHash(path) {
  return sha256Bytes(readFileSync(path));
}

function equal(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function exactKeys(value, keys, label) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  assert(equal(actual, expected), `${label} keys differ: ${actual.join(",")}`);
}

function matchPath(index, suffix) {
  return join(
    evaluationRoot,
    "matches",
    `match-${String(index).padStart(6, "0")}.${suffix}.json`,
  );
}

function scanForbiddenKeys(value, path = "dataset") {
  const forbidden = new Set([
    "seed",
    "initial_state_hash",
    "state_hash_before",
    "state_hash_after",
    "full_state",
    "FullState",
    "decks",
    "log",
  ]);
  if (Array.isArray(value)) {
    value.forEach((item, index) => scanForbiddenKeys(item, `${path}[${index}]`));
    return;
  }
  if (value === null || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    assert(!forbidden.has(key), `forbidden key ${key} at ${path}`);
    scanForbiddenKeys(child, `${path}.${key}`);
  }
}

const manifest = readJson(manifestPath);
const plan = readJson(join(evaluationRoot, "plan.json"));
const evaluationReport = readJson(join(evaluationRoot, "eval-report.json"));
const replayList = readJson(listPath);
const dataset = readJson(datasetPath);

assert(
  replayList.format === "effective-splendor-dataset-replay-list" &&
    replayList.version === 1,
  "replay-list format/version mismatch",
);
assert(
  replayList.dataset_id === "formal-m10-evaluation-2026-08-11-v1",
  "replay-list dataset_id mismatch",
);
assert(replayList.replays.length === 64, "replay-list must contain 64 sources");
assert(new Set(replayList.replays.map((entry) => entry.source_id)).size === 64, "duplicate source_id");
assert(new Set(replayList.replays.map((entry) => entry.match_index)).size === 64, "duplicate match_index");
for (let index = 0; index < 64; index += 1) {
  const entry = replayList.replays[index];
  assert(entry.match_index === index, `replay-list index ${index} is not canonical`);
  assert(
    entry.source_id === `m10-formal-match-${String(index).padStart(6, "0")}`,
    `replay-list source_id mismatch at ${index}`,
  );
}

exactKeys(
  dataset,
  [
    "format",
    "version",
    "dataset_id",
    "league_manifest_hash",
    "evaluation_id",
    "evaluation_plan_hash",
    "evaluation_report_hash",
    "replays",
    "examples",
  ],
  "dataset",
);
assert(dataset.format === "effective-splendor-training-dataset", "dataset format mismatch");
assert(dataset.version === 1, "dataset version mismatch");
assert(dataset.dataset_id === replayList.dataset_id, "dataset id mismatch");
assert(dataset.evaluation_id === plan.evaluation_id, "evaluation id mismatch");
assert(dataset.replays.length === 64, "dataset must bind 64 replays");
assert(evaluationReport.records.length === 64, "evaluation report must contain 64 records");

const manifestHash = semanticHash("effective-splendor-league-manifest-v1", manifest);
const planHash = sha256Bytes(JSON.stringify(plan));
const reportHash = semanticHash(
  "effective-splendor-evaluation-report-document-v1",
  evaluationReport,
);
assert(dataset.league_manifest_hash === manifestHash, "league manifest hash mismatch");
assert(dataset.evaluation_plan_hash === planHash, "evaluation plan hash mismatch");
assert(dataset.evaluation_plan_hash === evaluationReport.plan_hash, "report plan hash mismatch");
assert(dataset.evaluation_report_hash === reportHash, "evaluation report hash mismatch");

const manifestAgents = new Map(manifest.agents.map((agent) => [agent.id, agent]));
const replayBySource = new Map();
let expectedExamples = 0;
for (let index = 0; index < 64; index += 1) {
  const source = replayList.replays[index];
  const binding = dataset.replays[index];
  const record = evaluationReport.records[index];
  const arenaReport = readJson(matchPath(index, "report"));
  const replay = readJson(matchPath(index, "replay"));

  exactKeys(
    binding,
    [
      "source_id",
      "evaluation_match_index",
      "seed_index",
      "rotation",
      "arena_game_id",
      "arena_report_hash",
      "replay_document_hash",
      "engine_version",
      "ruleset_id",
      "ruleset_fingerprint",
      "player_count",
      "steps",
      "final_state_hash",
      "result",
      "agents_by_seat",
    ],
    `replays[${index}]`,
  );
  assert(record.match_index === index, `non-canonical evaluation record ${index}`);
  assert(arenaReport.outcome.status === "completed", `source ${index} is aborted`);
  assert(binding.source_id === source.source_id, `source binding mismatch ${index}`);
  assert(binding.evaluation_match_index === index, `match binding mismatch ${index}`);
  assert(binding.seed_index === record.seed_index, `seed_index mismatch ${index}`);
  assert(binding.rotation === record.rotation, `rotation mismatch ${index}`);
  assert(binding.arena_game_id === record.game_id, `game_id mismatch ${index}`);
  assert(binding.arena_game_id === arenaReport.game_id, `Arena game_id mismatch ${index}`);
  assert(equal(record.outcome, arenaReport.outcome), `Arena outcome mismatch ${index}`);
  assert(
    binding.arena_report_hash ===
      semanticHash("effective-splendor-arena-report-document-v1", arenaReport),
    `Arena report hash mismatch ${index}`,
  );
  assert(
    binding.replay_document_hash ===
      semanticHash("effective-splendor-replay-document-v1", replay),
    `replay document hash mismatch ${index}`,
  );
  assert(binding.engine_version === replay.engine_version, `engine mismatch ${index}`);
  assert(binding.ruleset_id === replay.ruleset.id, `ruleset mismatch ${index}`);
  assert(
    binding.ruleset_fingerprint === replay.ruleset_fingerprint,
    `ruleset fingerprint mismatch ${index}`,
  );
  assert(binding.player_count === replay.player_count, `player count mismatch ${index}`);
  assert(binding.steps === replay.steps.length, `step count mismatch ${index}`);
  assert(
    binding.steps === arenaReport.outcome.completed_plies,
    `completed plies mismatch ${index}`,
  );
  assert(binding.final_state_hash === replay.final_state_hash, `final hash mismatch ${index}`);
  assert(
    binding.final_state_hash === arenaReport.outcome.replay_final_hash,
    `Arena final hash mismatch ${index}`,
  );
  assert(equal(binding.result, replay.result), `replay result mismatch ${index}`);
  assert(equal(binding.result, arenaReport.outcome.result), `Arena result mismatch ${index}`);
  assert(binding.agents_by_seat.length === 2, `seat count mismatch ${index}`);

  for (let seat = 0; seat < 2; seat += 1) {
    const identity = binding.agents_by_seat[seat];
    const agentId = record.agent_ids_by_seat[seat];
    const leagueAgent = manifestAgents.get(agentId);
    const runtime = arenaReport.agents.find((agent) => agent.seat === seat);
    assert(identity.seat === seat, `identity seat mismatch ${index}/${seat}`);
    assert(identity.league_agent_id === agentId, `league agent mismatch ${index}/${seat}`);
    assert(identity.policy_version === leagueAgent.policy_version, `policy mismatch ${index}/${seat}`);
    assert(identity.model_version === leagueAgent.model_version, `model mismatch ${index}/${seat}`);
    assert(identity.runtime_name === runtime.agent_name, `runtime name mismatch ${index}/${seat}`);
    assert(
      identity.runtime_version === runtime.agent_version,
      `runtime version mismatch ${index}/${seat}`,
    );
  }

  expectedExamples += binding.steps;
  replayBySource.set(binding.source_id, { binding, replay });
}

assert(dataset.examples.length === expectedExamples, "example count differs from total replay plies");
const perSourcePly = new Map();
const examplesByPolicy = new Map();
for (let index = 0; index < dataset.examples.length; index += 1) {
  const example = dataset.examples[index];
  exactKeys(
    example,
    [
      "source_id",
      "replay_document_hash",
      "ply",
      "actor",
      "observation_hash",
      "visible_history_hash",
      "information_set_hash",
      "observation",
      "legal_actions",
      "chosen_action",
      "final_scores",
      "final_ranks",
    ],
    `examples[${index}]`,
  );
  const source = replayBySource.get(example.source_id);
  assert(source, `unknown example source at ${index}`);
  const expectedPly = perSourcePly.get(example.source_id) ?? 0;
  assert(example.ply === expectedPly, `non-contiguous ply for ${example.source_id}`);
  perSourcePly.set(example.source_id, expectedPly + 1);
  const replayStep = source.replay.steps[example.ply];
  assert(example.actor === replayStep.actor, `actor mismatch at example ${index}`);
  assert(equal(example.chosen_action, replayStep.action), `chosen action mismatch at ${index}`);
  assert(
    example.legal_actions.some((action) => equal(action, example.chosen_action)),
    `chosen action is not legal at example ${index}`,
  );
  assert(example.observation.viewer === example.actor, `observation viewer mismatch at ${index}`);
  exactKeys(
    example.observation,
    ["viewer", "ruleset_fingerprint", "public", "private"],
    `examples[${index}].observation`,
  );
  exactKeys(
    example.observation.public,
    [
      "player_count",
      "current_player",
      "phase",
      "bank",
      "market",
      "deck_counts",
      "nobles",
      "players",
      "end_game_triggered",
      "turns_remaining_in_final_round",
      "consecutive_forced_passes",
      "pending_nobles",
    ],
    `examples[${index}].observation.public`,
  );
  exactKeys(example.observation.private, ["reserved"], `examples[${index}].observation.private`);
  for (const player of example.observation.public.players) {
    exactKeys(
      player,
      [
        "id",
        "tokens",
        "bonuses",
        "prestige",
        "reserved_count",
        "public_reserved",
        "purchased",
        "nobles",
      ],
      `examples[${index}].observation.public.players`,
    );
  }
  assert(
    example.replay_document_hash === source.binding.replay_document_hash,
    `example replay hash mismatch at ${index}`,
  );
  assert(equal(example.final_scores, source.binding.result.scores), `final scores mismatch ${index}`);
  assert(equal(example.final_ranks, source.binding.result.ranks), `final ranks mismatch ${index}`);

  const policy = source.binding.agents_by_seat[example.actor].policy_version;
  examplesByPolicy.set(policy, (examplesByPolicy.get(policy) ?? 0) + 1);
}

for (const [sourceId, source] of replayBySource) {
  assert(
    perSourcePly.get(sourceId) === source.binding.steps,
    `example count mismatch for ${sourceId}`,
  );
}
assert(
  examplesByPolicy.has("root-determinization-v1") &&
    examplesByPolicy.has("observation-history-ismcts-v1"),
  "dataset does not contain both frozen policies",
);

scanForbiddenKeys(dataset);

const summary = {
  verdict: "PASS",
  dataset_id: dataset.dataset_id,
  replay_count: dataset.replays.length,
  match_index_range: "0..63",
  example_count: dataset.examples.length,
  examples_by_policy: Object.fromEntries(examplesByPolicy),
  completed_sources: dataset.replays.length,
  aborted_sources: 0,
  league_manifest_hash: manifestHash,
  evaluation_plan_hash: planHash,
  evaluation_report_hash: reportHash,
  replay_list_file_sha256: fileHash(listPath),
  dataset_file_sha256: fileHash(datasetPath),
  dataset_semantic_hash: semanticHash("effective-splendor-training-dataset-v1", dataset),
  hidden_state_forbidden_key_hits: 0,
  chosen_action_legality_failures: 0,
};

process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
