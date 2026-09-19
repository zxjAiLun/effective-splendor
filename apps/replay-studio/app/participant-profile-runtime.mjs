/**
 * The Studio League participant profile, rating history, and opponents, as pure functions.
 *
 * Enforces strict contracts for D3B:
 * 1. Authority-first: Profile facts come directly from the Host without client-side inference;
 * 2. Elo truthfulness: rated=0 must display protocol initial Elo (1500) and origin Initial;
 *    rated>0 must display the recorded current Elo and origin Rated; no `elo ?? 1500` fallback;
 * 3. Completed plies: honest three-state representation (available / partial / unavailable);
 *    never display 0 for unavailable decision plies;
 * 4. Rating history: League sequence on x-axis, strictly no Date re-sorting, no fake events;
 * 5. Opponents: distinct recorded vs rated W-T-L, self-matches excluded;
 * 6. Strict fail-closed decoders: malformed 200 payload results in invalid error, never silent default.
 */

export const PARTICIPANT_READ_TIMEOUT_MS = 10000;
export const RATING_HISTORY_DEFAULT_LIMIT = 100;
export const OPPONENTS_DEFAULT_LIMIT = 20;
export const GAMES_DEFAULT_LIMIT = 50;

/** Describe the participant kind label. */
export function describeProfileKind(kind) {
  if (kind === "human") return "Human";
  if (kind === "engine") return "Engine";
  return null;
}

/** Describe the Elo block based strictly on the decoded elo object. */
export function describeProfileElo(elo, provisional) {
  if (!elo || typeof elo !== "object") return null;
  const isInitial = elo.origin === "initial";
  const displayVal = typeof elo.display_rounded === "number" ? elo.display_rounded : Math.round(elo.value);
  return {
    valueText: `${displayVal}`,
    preciseText: typeof elo.value === "number" ? elo.value.toFixed(1) : `${displayVal}`,
    origin: elo.origin,
    isInitial,
    label: isInitial ? "Initial Studio Elo" : "Studio Elo",
    subtext: isInitial ? "No rated games yet" : (provisional ? "Provisional rating (< 20 rated matches)" : "Established rating"),
  };
}

/** Describe the W-T-L and games count lines. */
export function describeRecordText(profile) {
  const { rated_wins, rated_ties, rated_losses, rated_games, recorded_games } = profile ?? {};
  if (
    typeof rated_wins !== "number" ||
    typeof rated_ties !== "number" ||
    typeof rated_losses !== "number"
  ) {
    return { record: "—", games: "—" };
  }
  return {
    record: `${rated_wins}–${rated_ties}–${rated_losses}`,
    games: `${rated_games} rated · ${recorded_games} recorded`,
  };
}

/** Describe seat usage numbers. */
export function describeSeatsText(seats) {
  if (!seats || typeof seats !== "object") {
    return { summary: "—", appearances: "—" };
  }
  const { appearances, seat0, seat1, other } = seats;
  const parts = [`P0 ${seat0}`, `P1 ${seat1}`];
  if (typeof other === "number" && other > 0) {
    parts.push(`Other ${other}`);
  }
  return {
    summary: parts.join(" · "),
    appearances: `${appearances} seat appearances`,
  };
}

/** Describe completed plies three-state facts. */
export function describeCompletedPlies(plies) {
  if (!plies || typeof plies !== "object") {
    return { availability: "unavailable", valueText: "Not recorded", subtext: "0 completed games observed" };
  }
  const { availability, value, observed_completed_games, total_completed_games } = plies;
  if (availability === "available" && typeof value === "number") {
    return {
      availability: "available",
      valueText: `${value.toFixed(1)} decision plies`,
      subtext: `${observed_completed_games} / ${total_completed_games} completed games observed`,
    };
  }
  if (availability === "partial" && typeof value === "number") {
    return {
      availability: "partial",
      valueText: `${value.toFixed(1)} decision plies`,
      subtext: `Based on ${observed_completed_games} / ${total_completed_games} completed games`,
    };
  }
  return {
    availability: "unavailable",
    valueText: "Not recorded",
    subtext: `${observed_completed_games ?? 0} / ${total_completed_games ?? 0} completed games observed`,
  };
}

/** Strict decoder for GET /league/participants/:id */
export function decodeParticipantProfile(payload, expectedId) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, error: "Host returned a non-object participant response." };
  }
  if (payload.format !== "effective-splendor-studio-league-participant" || payload.version !== 1) {
    return { ok: false, error: `Invalid participant envelope format: ${payload.format} v${payload.version}` };
  }
  const p = payload.profile;
  if (!p || typeof p !== "object" || Array.isArray(p)) {
    return { ok: false, error: "Missing or malformed profile object." };
  }
  if (typeof expectedId === "string" && expectedId && p.participant_id !== expectedId) {
    return { ok: false, error: `Participant id mismatch: expected ${expectedId}, got ${p.participant_id}` };
  }
  if (typeof p.participant_id !== "string" || !p.participant_id) {
    return { ok: false, error: "Profile missing valid participant_id." };
  }
  if (p.kind !== "human" && p.kind !== "engine") {
    return { ok: false, error: `Profile invalid kind: ${p.kind}` };
  }
  if (typeof p.display_name !== "string" || !p.display_name) {
    return { ok: false, error: "Profile missing display_name." };
  }
  if (!p.elo || typeof p.elo !== "object" || typeof p.elo.value !== "number" || !Number.isFinite(p.elo.value)) {
    return { ok: false, error: "Profile missing or non-finite elo.value." };
  }
  if (p.elo.origin !== "rated" && p.elo.origin !== "initial") {
    return { ok: false, error: `Profile invalid elo.origin: ${p.elo.origin}` };
  }
  if (p.elo.origin === "initial" && p.elo.display_rounded !== 1500) {
    return { ok: false, error: `Profile initial Elo must be 1500, got ${p.elo.display_rounded}` };
  }
  if (typeof p.provisional !== "boolean") {
    return { ok: false, error: "Profile missing provisional boolean." };
  }
  for (const field of ["recorded_games", "rated_games", "rated_wins", "rated_ties", "rated_losses"]) {
    if (typeof p[field] !== "number" || !Number.isInteger(p[field]) || p[field] < 0) {
      return { ok: false, error: `Profile field ${field} must be a non-negative integer.` };
    }
  }
  if (
    !p.seats ||
    typeof p.seats !== "object" ||
    typeof p.seats.appearances !== "number" ||
    typeof p.seats.seat0 !== "number" ||
    typeof p.seats.seat1 !== "number" ||
    typeof p.seats.other !== "number"
  ) {
    return { ok: false, error: "Profile missing or malformed seats breakdown." };
  }
  if (
    !p.completed_plies ||
    typeof p.completed_plies !== "object" ||
    !["available", "partial", "unavailable"].includes(p.completed_plies.availability)
  ) {
    return { ok: false, error: "Profile missing or malformed completed_plies." };
  }
  if (p.completed_plies.availability === "unavailable" && p.completed_plies.value !== null) {
    return { ok: false, error: "Unavailable completed_plies must have null value." };
  }
  if (p.completed_plies.availability !== "unavailable" && (typeof p.completed_plies.value !== "number" || !Number.isFinite(p.completed_plies.value))) {
    return { ok: false, error: "Available completed_plies must have finite numeric value." };
  }

  return { ok: true, profile: p };
}

/** Strict decoder for GET /league/participants/:id/ratings */
export function decodeRatingHistoryPage(payload, expectedId) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, error: "Host returned a non-object rating history response." };
  }
  if (payload.format !== "effective-splendor-studio-league-participant-ratings" || payload.version !== 1) {
    return { ok: false, error: `Invalid ratings envelope format: ${payload.format} v${payload.version}` };
  }
  if (typeof expectedId === "string" && expectedId && payload.participant_id !== expectedId) {
    return { ok: false, error: `Ratings participant_id mismatch: expected ${expectedId}, got ${payload.participant_id}` };
  }
  if (!Array.isArray(payload.points)) {
    return { ok: false, error: "Missing or non-array points list in rating history." };
  }
  for (const pt of payload.points) {
    if (
      typeof pt.league_seq !== "number" ||
      !Number.isInteger(pt.league_seq) ||
      typeof pt.match_id !== "string" ||
      !pt.match_id ||
      typeof pt.elo_before !== "number" ||
      !Number.isFinite(pt.elo_before) ||
      typeof pt.elo_after !== "number" ||
      !Number.isFinite(pt.elo_after) ||
      typeof pt.delta !== "number" ||
      !Number.isFinite(pt.delta) ||
      typeof pt.opponent_id !== "string" ||
      typeof pt.opponent_name !== "string"
    ) {
      return { ok: false, error: "Malformed rating point in points list." };
    }
  }
  const next = payload.next_before_league_seq;
  if (next !== null && next !== undefined && (typeof next !== "number" || !Number.isInteger(next) || next <= 0)) {
    return { ok: false, error: "Invalid next_before_league_seq cursor in rating history." };
  }

  return {
    ok: true,
    participantId: payload.participant_id,
    points: payload.points,
    nextBeforeLeagueSeq: typeof next === "number" ? next : null,
    atEnd: typeof next !== "number",
  };
}

/** Strict decoder for GET /league/participants/:id/opponents */
export function decodeOpponentsPage(payload, expectedId) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, error: "Host returned a non-object opponents response." };
  }
  if (payload.format !== "effective-splendor-studio-league-participant-opponents" || payload.version !== 1) {
    return { ok: false, error: `Invalid opponents envelope format: ${payload.format} v${payload.version}` };
  }
  if (typeof expectedId === "string" && expectedId && payload.participant_id !== expectedId) {
    return { ok: false, error: `Opponents participant_id mismatch: expected ${expectedId}, got ${payload.participant_id}` };
  }
  if (!Array.isArray(payload.opponents)) {
    return { ok: false, error: "Missing or non-array opponents list." };
  }
  for (const opp of payload.opponents) {
    if (
      typeof opp.opponent_id !== "string" ||
      !opp.opponent_id ||
      opp.opponent_id === expectedId ||
      typeof opp.display_name !== "string" ||
      typeof opp.recorded_games !== "number" ||
      typeof opp.rated_games !== "number" ||
      typeof opp.rated_wins !== "number" ||
      typeof opp.rated_ties !== "number" ||
      typeof opp.rated_losses !== "number"
    ) {
      return { ok: false, error: "Malformed opponent row in opponents list." };
    }
  }
  const next = payload.next_after_opponent_id;
  if (next !== null && next !== undefined && (typeof next !== "string" || next.length === 0 || next.length > 256)) {
    return { ok: false, error: "Invalid next_after_opponent_id cursor in opponents." };
  }

  return {
    ok: true,
    participantId: payload.participant_id,
    opponents: payload.opponents,
    nextAfterOpponentId: typeof next === "string" ? next : null,
    atEnd: typeof next !== "string",
  };
}

/**
 * Build chart dataset from rating points.
 *
 * Points from Host arrive in `league_seq DESC` order.
 * This helper reverses them to chronological `league_seq ASC` for charting.
 * It NEVER sorts by played_at and NEVER fabricates synthetic rating points.
 */
export function buildEloChartData(points) {
  if (!Array.isArray(points) || points.length === 0) {
    return { series: [], minX: 0, maxX: 0, minY: 1500, maxY: 1500 };
  }
  // Sort / reverse by league_seq ascending
  const asc = [...points].sort((a, b) => a.league_seq - b.league_seq);
  const series = asc.map((p) => ({
    x: p.league_seq,
    y: p.elo_after,
    delta: p.delta,
    opponentName: p.opponent_name,
    matchId: p.match_id,
    playedAt: p.played_at,
    leagueSeq: p.league_seq,
  }));

  const xs = series.map((s) => s.x);
  const ys = series.map((s) => s.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  let minY = Math.min(...ys);
  let maxY = Math.max(...ys);
  if (minY === maxY) {
    minY -= 20;
    maxY += 20;
  }

  return { series, minX, maxX, minY, maxY };
}

/** Classify read error for participant endpoints (distinguishing 404 vs 503 vs network). */
export function classifyProfileError(error, timeoutMs = PARTICIPANT_READ_TIMEOUT_MS) {
  if (error?.status === 404) {
    return {
      kind: "not_found",
      message: "No participant with this ID is recorded in the league ledger.",
    };
  }
  if (error?.status === 503 || error?.readKind === "refused") {
    return {
      kind: "refused",
      message: typeof error?.message === "string" ? error.message : "The league authority refused the read.",
    };
  }
  if (error?.name === "AbortError" || error?.name === "TimeoutError") {
    return {
      kind: "timed_out",
      message: `The Studio Host did not answer within ${timeoutMs / 1000} seconds.`,
    };
  }
  if (error?.kind === "invalid") {
    return {
      kind: "invalid",
      message: typeof error?.message === "string" ? error.message : String(error),
    };
  }
  return {
    kind: "unreachable",
    message: typeof error?.message === "string" ? error.message : "The Studio Host could not be reached.",
  };
}
