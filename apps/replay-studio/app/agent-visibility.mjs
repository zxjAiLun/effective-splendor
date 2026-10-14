// Presentation-only roster. The Studio model lineup was retired and emptied in
// M80: no engine ID, engine display name, reviewer, or archived experiment model
// is promoted merely because it existed before the cleanup. Do not mutate the
// league ledger or re-rate it here.
export const VISIBLE_AGENT_IDS = new Set([]);

const VISIBLE_ENGINE_NAMES = new Set([]);

export function visibleAgents(agents) {
  return Array.isArray(agents) ? agents.filter((agent) => VISIBLE_AGENT_IDS.has(agent?.id)) : [];
}

// Historical participants have ledger IDs, not registry IDs. Humans remain
// visible when they are introduced by a future match; engine identity must be
// registered explicitly after the retirement cleanup.
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

export const VISIBLE_REVIEWER_IDS = new Set([]);

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
