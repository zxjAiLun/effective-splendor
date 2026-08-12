export const RATING_REPORT_FORMAT = "effective-splendor-rating-report";

function requireValue(condition, path) {
  if (!condition) throw new Error(`invalid rating report: ${path}`);
}

export function validateRatingReport(input) {
  requireValue(input && typeof input === "object" && !Array.isArray(input), "root must be an object");
  requireValue(input.format === RATING_REPORT_FORMAT, "format");
  requireValue(input.version === 1, "version");
  requireValue(typeof input.tournament_id === "string", "tournament_id");
  requireValue(Array.isArray(input.agents) && input.agents.length >= 2, "agents");
  requireValue(Array.isArray(input.head_to_head), "head_to_head");
  requireValue(typeof input.round_robin_plan_hash === "string" && input.round_robin_plan_hash.length === 64, "round_robin_plan_hash");
  for (const [index, agent] of input.agents.entries()) {
    requireValue(agent && typeof agent === "object", `agents[${index}]`);
    for (const key of ["rank", "completed", "aborted", "wins", "ties", "losses", "live_elo", "official_elo"]) {
      requireValue(Number.isInteger(agent[key]), `agents[${index}].${key}`);
    }
    requireValue(typeof agent.agent_id === "string", `agents[${index}].agent_id`);
    requireValue(typeof agent.display_name === "string", `agents[${index}].display_name`);
  }
  return input;
}

export function headToHeadCell(report, rowId, columnId) {
  if (rowId === columnId) return { label: "—", tone: "neutral" };
  const pair = report.head_to_head.find((item) =>
    (item.agent_a === rowId && item.agent_b === columnId) ||
    (item.agent_a === columnId && item.agent_b === rowId));
  if (!pair || pair.completed === 0) return { label: "n/a", tone: "neutral" };
  const rowIsA = pair.agent_a === rowId;
  const wins = rowIsA ? pair.wins_a : pair.wins_b;
  const losses = rowIsA ? pair.wins_b : pair.wins_a;
  return { label: `${wins}-${pair.ties}-${losses}`, tone: wins > losses ? "positive" : wins < losses ? "negative" : "neutral" };
}
