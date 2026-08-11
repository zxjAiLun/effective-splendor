const GEM_KEYS = ["white", "blue", "green", "red", "black", "gold"];
const TIERS = ["One", "Two", "Three"];
const BONUSES = ["White", "Blue", "Green", "Red", "Black"];
const HASH = /^[0-9a-f]{64}$/;

function fail(path, message) {
  throw new Error(`Invalid AnalysisTraceV1 at ${path}: ${message}`);
}

function object(value, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(path, "expected object");
  return value;
}

function array(value, path, length) {
  if (!Array.isArray(value) || (length !== undefined && value.length !== length)) {
    fail(path, length === undefined ? "expected array" : `expected array length ${length}`);
  }
  return value;
}

function integer(value, path, minimum = 0) {
  if (!Number.isInteger(value) || value < minimum) fail(path, `expected integer >= ${minimum}`);
  return value;
}

function text(value, path) {
  if (typeof value !== "string" || value.trim() === "") fail(path, "expected nonempty string");
  return value;
}

function hash(value, path) {
  if (typeof value !== "string" || !HASH.test(value)) fail(path, "expected lowercase SHA-256");
  return value;
}

function domainId(value, path, upperExclusive) {
  const id = integer(value, path);
  if (id >= upperExclusive) fail(path, `expected id below ${upperExclusive}`);
  return id;
}

function gems(value, path) {
  const source = object(value, path);
  for (const key of GEM_KEYS) integer(source[key], `${path}.${key}`);
  return source;
}

function numericVector(value, path, length) {
  const values = array(value, path, length);
  values.forEach((item, index) => integer(item, `${path}[${index}]`));
  return values;
}

export function actionKey(action) {
  return JSON.stringify(action);
}

export function validateAction(action, path = "action") {
  const value = object(action, path);
  switch (value.type) {
    case "take_tokens":
      gems(value.take, `${path}.take`);
      gems(value.return, `${path}.return`);
      break;
    case "buy_market":
      tier(value.tier, `${path}.tier`);
      marketSlot(value.slot, `${path}.slot`);
      break;
    case "buy_reserved":
      integer(value.slot, `${path}.slot`);
      break;
    case "reserve_market":
      tier(value.tier, `${path}.tier`);
      marketSlot(value.slot, `${path}.slot`);
      gems(value.return, `${path}.return`);
      break;
    case "reserve_deck":
      tier(value.tier, `${path}.tier`);
      gems(value.return, `${path}.return`);
      break;
    case "choose_noble":
      domainId(value.noble, `${path}.noble`, 10);
      break;
    case "pass":
      break;
    default:
      fail(`${path}.type`, "unsupported action type");
  }
  return value;
}

function tier(value, path) {
  if (!TIERS.includes(value)) fail(path, "expected One, Two, or Three");
  return value;
}

function marketSlot(value, path) {
  const slot = integer(value, path);
  if (slot >= 4) fail(path, "expected market slot below 4");
  return slot;
}

function validateCatalog(catalog) {
  const value = object(catalog, "catalog");
  array(value.cards, "catalog.cards", 90).forEach((entry, index) => {
    const card = object(entry, `catalog.cards[${index}]`);
    if (domainId(card.id, `catalog.cards[${index}].id`, 90) !== index) fail(`catalog.cards[${index}].id`, "expected dense id");
    tier(card.tier, `catalog.cards[${index}].tier`);
    if (!BONUSES.includes(card.bonus)) fail(`catalog.cards[${index}].bonus`, "invalid bonus");
    integer(card.prestige, `catalog.cards[${index}].prestige`);
    numericVector(card.cost, `catalog.cards[${index}].cost`, 5);
  });
  array(value.nobles, "catalog.nobles", 10).forEach((entry, index) => {
    const noble = object(entry, `catalog.nobles[${index}]`);
    if (domainId(noble.id, `catalog.nobles[${index}].id`, 10) !== index) fail(`catalog.nobles[${index}].id`, "expected dense id");
    integer(noble.prestige, `catalog.nobles[${index}].prestige`);
    numericVector(noble.requirements, `catalog.nobles[${index}].requirements`, 5);
  });
}

function validatePlayer(player, path, playerCount, full) {
  const value = object(player, path);
  domainId(value.id, `${path}.id`, playerCount);
  gems(value.tokens, `${path}.tokens`);
  numericVector(value.bonuses, `${path}.bonuses`, 5);
  integer(value.prestige, `${path}.prestige`);
  if (full) {
    array(value.reserved, `${path}.reserved`).forEach((entry, index) => {
      const reserved = object(entry, `${path}.reserved[${index}]`);
      domainId(reserved.card, `${path}.reserved[${index}].card`, 90);
      if (typeof reserved.from_deck !== "boolean") fail(`${path}.reserved[${index}].from_deck`, "expected boolean");
    });
  } else {
    integer(value.reserved_count, `${path}.reserved_count`);
    array(value.public_reserved, `${path}.public_reserved`).forEach((id, index) => domainId(id, `${path}.public_reserved[${index}]`, 90));
  }
  array(value.purchased, `${path}.purchased`).forEach((id, index) => domainId(id, `${path}.purchased[${index}]`, 90));
  array(value.nobles, `${path}.nobles`).forEach((id, index) => domainId(id, `${path}.nobles[${index}]`, 10));
}

function validatePlayerView(playerView, path, playerCount, actor) {
  const value = object(playerView, path);
  if (value.viewer !== actor) fail(`${path}.viewer`, "must equal frame actor");
  hash(value.ruleset_fingerprint, `${path}.ruleset_fingerprint`);
  const publicState = object(value.public, `${path}.public`);
  if (publicState.player_count !== playerCount || publicState.current_player !== actor) fail(`${path}.public`, "player/current-player mismatch");
  gems(publicState.bank, `${path}.public.bank`);
  array(publicState.market, `${path}.public.market`, 3).forEach((row, tierIndex) => {
    array(row, `${path}.public.market[${tierIndex}]`, 4).forEach((id, slot) => {
      if (id !== null) domainId(id, `${path}.public.market[${tierIndex}][${slot}]`, 90);
    });
  });
  numericVector(publicState.deck_counts, `${path}.public.deck_counts`, 3);
  array(publicState.nobles, `${path}.public.nobles`).forEach((id, index) => domainId(id, `${path}.public.nobles[${index}]`, 10));
  array(publicState.pending_nobles, `${path}.public.pending_nobles`).forEach((id, index) => domainId(id, `${path}.public.pending_nobles[${index}]`, 10));
  array(publicState.players, `${path}.public.players`, playerCount).forEach((player, index) => {
    validatePlayer(player, `${path}.public.players[${index}]`, playerCount, false);
    if (player.id !== index) fail(`${path}.public.players[${index}].id`, "expected seat order");
  });
  const privateState = object(value.private, `${path}.private`);
  array(privateState.reserved, `${path}.private.reserved`).forEach((entry, index) => {
    const reserved = object(entry, `${path}.private.reserved[${index}]`);
    integer(reserved.slot, `${path}.private.reserved[${index}].slot`);
    domainId(reserved.card, `${path}.private.reserved[${index}].card`, 90);
    tier(reserved.tier, `${path}.private.reserved[${index}].tier`);
    if (typeof reserved.from_deck !== "boolean") fail(`${path}.private.reserved[${index}].from_deck`, "expected boolean");
  });
  return value;
}

function validateFrame(frame, index, trace) {
  const path = `frames[${index}]`;
  const value = object(frame, path);
  if (integer(value.ply, `${path}.ply`) !== index) fail(`${path}.ply`, "expected contiguous ply");
  const actor = domainId(value.actor, `${path}.actor`, trace.player_count);
  validateAction(value.recorded_action, `${path}.recorded_action`);
  hash(value.state_hash_before, `${path}.state_hash_before`);
  hash(value.observation_hash, `${path}.observation_hash`);
  hash(value.visible_history_hash, `${path}.visible_history_hash`);
  hash(value.information_set_hash, `${path}.information_set_hash`);
  integer(value.visible_event_count, `${path}.visible_event_count`, 1);
  const playerView = validatePlayerView(value.player_view, `${path}.player_view`, trace.player_count, actor);
  if (playerView.ruleset_fingerprint !== trace.ruleset_fingerprint) {
    fail(`${path}.player_view.ruleset_fingerprint`, "trace binding mismatch");
  }

  const reveal = object(value.referee_reveal, `${path}.referee_reveal`);
  integer(reveal.seed, `${path}.referee_reveal.seed`);
  array(reveal.decks, `${path}.referee_reveal.decks`, 3).forEach((deck, tierIndex) => {
    array(deck, `${path}.referee_reveal.decks[${tierIndex}]`).forEach((id, cardIndex) => domainId(id, `${path}.referee_reveal.decks[${tierIndex}][${cardIndex}]`, 90));
  });
  array(reveal.players, `${path}.referee_reveal.players`, trace.player_count).forEach((player, playerIndex) => {
    validatePlayer(player, `${path}.referee_reveal.players[${playerIndex}]`, trace.player_count, true);
    if (player.id !== playerIndex) fail(`${path}.referee_reveal.players[${playerIndex}].id`, "expected seat order");
  });

  const legalActions = array(value.legal_actions, `${path}.legal_actions`);
  if (legalActions.length === 0) fail(`${path}.legal_actions`, "must not be empty");
  legalActions.forEach((action, actionIndex) => validateAction(action, `${path}.legal_actions[${actionIndex}]`));
  const legalKeys = legalActions.map(actionKey);
  if (!legalKeys.includes(actionKey(value.recorded_action))) fail(`${path}.recorded_action`, "not in legal actions");

  const result = object(value.neural_result, `${path}.neural_result`);
  text(result.algorithm, `${path}.neural_result.algorithm`);
  integer(result.version, `${path}.neural_result.version`, 1);
  if (result.information_set_hash !== value.information_set_hash || result.model_id !== trace.model_id || result.checkpoint_hash !== trace.checkpoint_hash) {
    fail(`${path}.neural_result`, "identity binding mismatch");
  }
  validateAction(result.action, `${path}.neural_result.action`);
  if (!legalKeys.includes(actionKey(result.action))) fail(`${path}.neural_result.action`, "not in legal actions");
  const actionStats = array(result.action_stats, `${path}.neural_result.action_stats`, legalActions.length);
  let visitSum = 0;
  actionStats.forEach((entry, actionIndex) => {
    const stats = object(entry, `${path}.neural_result.action_stats[${actionIndex}]`);
    validateAction(stats.action, `${path}.neural_result.action_stats[${actionIndex}].action`);
    if (actionKey(stats.action) !== legalKeys[actionIndex]) fail(`${path}.neural_result.action_stats[${actionIndex}].action`, "must follow legal-action order");
    const prior = integer(stats.prior_micros, `${path}.neural_result.action_stats[${actionIndex}].prior_micros`);
    if (prior > trace.value_scale) fail(`${path}.neural_result.action_stats[${actionIndex}].prior_micros`, "exceeds value scale");
    const visits = integer(stats.visits, `${path}.neural_result.action_stats[${actionIndex}].visits`);
    visitSum += visits;
    numericVector(stats.value_sum_by_player, `${path}.neural_result.action_stats[${actionIndex}].value_sum_by_player`, trace.player_count).forEach((sum) => {
      if (sum > visits * trace.value_scale) fail(`${path}.neural_result.action_stats[${actionIndex}].value_sum_by_player`, "exceeds visit/value bound");
    });
  });
  const stats = object(result.stats, `${path}.neural_result.stats`);
  const rootVisits = integer(stats.root_visits, `${path}.neural_result.stats.root_visits`, 1);
  if (integer(stats.simulations, `${path}.neural_result.stats.simulations`, 1) !== trace.config.simulations
      || integer(stats.sampled_determinizations, `${path}.neural_result.stats.sampled_determinizations`, 1) !== trace.config.simulations
      || rootVisits !== trace.config.simulations
      || visitSum !== rootVisits) {
    fail(`${path}.neural_result.stats`, "simulation/visit binding mismatch");
  }
  integer(stats.tree_nodes, `${path}.neural_result.stats.tree_nodes`, 1);
  integer(stats.shared_node_hits, `${path}.neural_result.stats.shared_node_hits`);
  integer(stats.model_evaluations, `${path}.neural_result.stats.model_evaluations`);
  integer(stats.terminal_evaluations, `${path}.neural_result.stats.terminal_evaluations`);
  if (value.recommended_matches_recorded !== (actionKey(result.action) === actionKey(value.recorded_action))) {
    fail(`${path}.recommended_matches_recorded`, "does not match selected/recorded action identity");
  }
}

export function isAnalysisTraceEnvelope(value) {
  return Boolean(value && typeof value === "object"
    && value.format === "effective-splendor-analysis-trace"
    && value.version === 1);
}

export function validateAnalysisTrace(value) {
  const trace = object(value, "trace");
  if (!isAnalysisTraceEnvelope(trace)) fail("trace", "unsupported format/version");
  text(trace.engine_version, "engine_version");
  text(trace.catalog_version, "catalog_version");
  integer(trace.replay_version, "replay_version", 1);
  hash(trace.replay_document_hash, "replay_document_hash");
  hash(trace.replay_final_state_hash, "replay_final_state_hash");
  hash(trace.ruleset_fingerprint, "ruleset_fingerprint");
  const playerCount = integer(trace.player_count, "player_count", 2);
  if (playerCount > 4) fail("player_count", "expected at most 4");
  text(trace.analyzer_label, "analyzer_label");
  text(trace.model_id, "model_id");
  hash(trace.checkpoint_hash, "checkpoint_hash");
  integer(trace.value_scale, "value_scale", 1);
  const config = object(trace.config, "config");
  integer(config.sample_seed, "config.sample_seed");
  integer(config.simulations, "config.simulations", 1);
  integer(config.max_depth_turns, "config.max_depth_turns", 1);
  integer(config.puct_exploration_milli, "config.puct_exploration_milli", 1);
  if (config.expected_checkpoint_hash !== trace.checkpoint_hash) fail("config.expected_checkpoint_hash", "checkpoint binding mismatch");
  validateCatalog(trace.catalog);
  const result = object(trace.result, "result");
  numericVector(result.scores, "result.scores", playerCount);
  numericVector(result.ranks, "result.ranks", playerCount);
  array(result.winners, "result.winners").forEach((id, index) => domainId(id, `result.winners[${index}]`, playerCount));
  text(result.reason, "result.reason");
  const frames = array(trace.frames, "frames");
  if (frames.length === 0) fail("frames", "must not be empty");
  frames.forEach((frame, index) => validateFrame(frame, index, trace));
  return trace;
}

function tierIndex(value) {
  return TIERS.indexOf(value);
}

function gemCode(key) {
  return { white: "W", blue: "U", green: "G", red: "R", black: "K", gold: "★" }[key];
}

function gemList(value) {
  if (!value || typeof value !== "object") return "";
  return GEM_KEYS.filter((key) => Number(value[key]) > 0)
    .map((key) => `${gemCode(key)}${Number(value[key]) > 1 ? `×${value[key]}` : ""}`)
    .join(" ");
}

function returnSuffix(action) {
  const returned = gemList(action.return);
  return returned ? ` · return ${returned}` : "";
}

export function formatActionLabel(action, frame, cards) {
  if (action.type === "buy_market" || action.type === "reserve_market") {
    const tier = tierIndex(action.tier);
    const slot = Number(action.slot);
    const id = frame.player_view.public.market[tier]?.[slot];
    const verb = action.type === "buy_market" ? "Buy" : "Reserve";
    const card = id == null ? `slot ${slot + 1}` : cards.has(id) ? `#${id} · ${cards.get(id).bonus[0]}${cards.get(id).prestige}` : `card #${id}`;
    return `${verb} T${tier + 1} ${card}${returnSuffix(action)}`;
  }
  if (action.type === "buy_reserved") {
    const slot = Number(action.slot);
    const id = frame.player_view.private.reserved.find((card) => card.slot === slot)?.card;
    const card = id == null ? `slot ${slot + 1}` : cards.has(id) ? `#${id} · ${cards.get(id).bonus[0]}${cards.get(id).prestige}` : `card #${id}`;
    return `Buy reserved ${card}`;
  }
  if (action.type === "reserve_deck") return `Reserve deck T${tierIndex(action.tier) + 1}${returnSuffix(action)}`;
  if (action.type === "choose_noble") return `Choose noble #${Number(action.noble)}`;
  if (action.type === "take_tokens") return `Take ${gemList(action.take)}${returnSuffix(action)}`;
  return action.type === "pass" ? "Pass" : action.type;
}

export function buildAnalysisRows(trace, frame) {
  const rootVisits = frame.neural_result.stats.root_visits;
  const actor = frame.actor;
  return frame.neural_result.action_stats
    .map((stats) => ({
      ...stats,
      prior: stats.prior_micros / trace.value_scale,
      visit: rootVisits ? stats.visits / rootVisits : 0,
      q: stats.visits ? stats.value_sum_by_player[actor] / stats.visits / trace.value_scale : null,
      actual: actionKey(stats.action) === actionKey(frame.recorded_action),
      best: actionKey(stats.action) === actionKey(frame.neural_result.action),
    }))
    .sort((left, right) => right.visits - left.visits);
}
