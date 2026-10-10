// Presentation-only roster. Do not mutate the historical league ledger or re-rate it.
// A model without a same-object positive S3 pilot is not promoted into the Studio UI.
export const VISIBLE_AGENT_IDS = new Set([
  "s3-rollout",
  "heuristic-v028",
  "heuristic-v029",
  "heuristic-v030",
  "heuristic-v031",
  "heuristic-v032c",
  "prism-v01",
  "prism-v011",
  "prism-alpha-v01",
]);

const VISIBLE_ENGINE_NAMES = new Set([
  "S3 Rollout (Default · Strong)",
  "splendor.exe:agent-s3-rollout",
  "splendor.exe:agent-s3-rollout-profile",
  "Heuristic v0.2.8 (Single-Noble + Quadratic VP)",
  "Heuristic v0.2.9 (No Bomb Reserve · Fast Engine)",
  "Heuristic v0.3.0 (Frozen S4 Pilot)",
  "★ Heuristic v0.3.1 (5-Module Refactor · 76.6% vs S3)",
  "★ Two-Ply v0.3.2c (Continuation Rollout · 67.6% vs S3)",
  "★ Prism v0.1 (Entity Policy-Value · 54.3% vs v0.3.1)",
  "★ Prism v0.1.1 (PPO Champion · 62.0% vs v0.3.1)",
  "Prism v0.1.1",
  "★ Prism Alpha v0.1.0 (Big-Card Style · 52.7% vs v0.1.1)",
  "Prism Alpha v0.1.0",
  "splendor.exe:agent-prism",
  "splendor.exe:agent-prism|weights=local-artifacts/prism/v01/run/weights.json",
  "splendor.exe:agent-prism-sample",
  "splendor.exe:agent-prism-sample|weights=local-artifacts/prism/v0.1.1/weights.json",
  "splendor.exe:agent-prism-sample|weights=local-artifacts/prism/alpha-v0.1.0/weights.json",
]);

export function visibleAgents(agents) {
  return Array.isArray(agents) ? agents.filter((agent) => VISIBLE_AGENT_IDS.has(agent?.id)) : [];
}

// Historical participants have ledger IDs, not registry IDs. Match the recorded
// display identity exactly; do not conflate all `agent-heuristic-v02` versions.
export function visibleParticipant(participant) {
  const id = participant?.participantId ?? participant?.participant_id;
  const name = participant?.displayName ?? participant?.display_name;
  if (participant?.kind === "human" || (typeof id === "string" && /^[0-9a-f]{8}-[0-9a-f-]{27,}$/.test(id))) return true;
  return VISIBLE_AGENT_IDS.has(id) || VISIBLE_ENGINE_NAMES.has(name);
}

export function visibleGame(game) {
  return Array.isArray(game?.seats) && game.seats.length > 0 &&
    game.seats.every((seat) => visibleParticipant(seat));

}
export function visibleRatingPoints(points) {
  return points.filter((point) => visibleParticipant({
    participantId: point.opponent_id, displayName: point.opponent_name,
  }));
}

export const VISIBLE_REVIEWER_IDS = new Set([
  "s3-rollout-review",
  "prism-v01-review",
  "prism-v011-review",
  "prism-alpha-v01-review",
]);

export function visibleReviewers(reviewers) {
  return Array.isArray(reviewers) ? reviewers.filter((reviewer) => VISIBLE_REVIEWER_IDS.has(reviewer?.id)) : [];
}

// Experiment model IDs are historical identities, not registry aliases. An
// unknown candidate is hidden, rather than inheriting a later version's score.
export function visibleExperimentIndex(index) {
  return {
    ...index,
    experiments: index.experiments.map((experiment) => ({
      ...experiment,
      pairings: experiment.pairings.filter((pair) =>
        VISIBLE_AGENT_IDS.has(pair.candidate_model_id) && VISIBLE_AGENT_IDS.has(pair.opponent_model_id)),
    })).filter((experiment) => experiment.pairings.length > 0),
  };
}
export function visibleReport(report) {
  const agents = report.agents.filter((agent) => VISIBLE_AGENT_IDS.has(agent.agent_id));
  const ids = new Set(agents.map((agent) => agent.agent_id));
  return {
    ...report,
    agents,
    head_to_head: report.head_to_head.filter((pair) => ids.has(pair.agent_a) && ids.has(pair.agent_b)),
  };
}
