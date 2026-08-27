// Pure helpers for the M36A experiments page: filter logic, status labels,
// deep-link parsing, and bundle validation. Mirrors the Rust API contracts.

export const STATUS_LABEL = {
  valid: "VALID",
  excluded_prefix: "EXCLUDED_PREFIX / NOT_SCORED",
  nontermination: "NONTERMINATION / NO REPLAY",
  not_started: "NOT_STARTED",
};

export function isBrowsableAvailability(availability) {
  return availability === "valid" || availability === "excluded_prefix";
}

export function pairingStatusToAvailability(status) {
  return status === "VALID" ? "valid" : "excluded_prefix";
}

/**
 * Filter pairings by free text (label / evaluation id / model ids) and an
 * optional status filter. The `nontermination` filter selects the two
 * EXCLUDED_PREFIX pairings that carry a nontermination slot.
 */
export function filterPairings(pairings, { query = "", status = "all" } = {}) {
  const normalized = String(query ?? "").trim().toLowerCase();
  return pairings.filter((entry) => {
    if (status === "nontermination" && entry.status === "VALID") return false;
    if (
      (status === "valid" || status === "excluded_prefix") &&
      entry.status.toLowerCase() !== status
    ) {
      return false;
    }
    if (!normalized) return true;
    return (
      entry.label.toLowerCase().includes(normalized) ||
      entry.evaluation_id.toLowerCase().includes(normalized) ||
      entry.candidate_model_id.toLowerCase().includes(normalized) ||
      entry.opponent_model_id.toLowerCase().includes(normalized)
    );
  });
}

/** Filter match slots by the status filter (all keeps everything). */
export function filterMatches(matches, { status = "all" } = {}) {
  if (status === "all") return matches;
  return matches.filter((slot) => slot.availability === status);
}

/**
 * Parse `/experiments` deep-link parameters. Returns null unless both
 * experiment and pairing are present; match defaults to null.
 */
export function parseExperimentsQuery(searchParams) {
  const experiment = searchParams.get("experiment");
  const pairing = searchParams.get("pairing");
  const matchRaw = searchParams.get("match");
  let match = null;
  if (matchRaw != null) {
    const parsed = Number.parseInt(matchRaw, 10);
    if (Number.isInteger(parsed) && parsed >= 0) match = parsed;
  }
  if (!experiment || !pairing) return null;
  return { experiment, pairing, match };
}

/** Build the canonical deep-link URL for a selection. */
export function buildExperimentsQuery({ experiment, pairing, match }) {
  const params = new URLSearchParams();
  if (experiment) params.set("experiment", experiment);
  if (pairing) params.set("pairing", pairing);
  if (match != null) params.set("match", String(match));
  return params.toString() ? `/experiments?${params.toString()}` : "/experiments";
}

/**
 * Validate an ExperimentReplayBundle from the Host API. Throws on contract
 * violations so the UI never renders an unverified payload.
 */
export function validateExperimentBundle(value) {
  if (!value || typeof value !== "object") throw new Error("bundle must be an object");
  if (value.format !== "effective-splendor-experiment-replay-bundle" || value.version !== 1) {
    throw new Error("unsupported experiment replay bundle format/version");
  }
  if (typeof value.game_id !== "string" || value.game_id.length === 0) {
    throw new Error("bundle lacks game_id");
  }
  if (!Array.isArray(value.frames) || value.frames.length === 0) {
    throw new Error("bundle has no frames");
  }
  for (let index = 0; index < value.frames.length; index += 1) {
    const frame = value.frames[index];
    if (frame.ply !== index) throw new Error(`frame ${index} has non-contiguous ply ${frame.ply}`);
    if (typeof frame.actor !== "number") throw new Error(`frame ${index} lacks actor`);
    if (frame.actor !== frame.player_view.viewer) {
      throw new Error(`frame ${index} player_view must be projected for the actor`);
    }
    if (!Array.isArray(frame.legal_actions) || frame.legal_actions.length === 0) {
      throw new Error(`frame ${index} lacks legal actions`);
    }
    if (!frame.recorded_action || typeof frame.recorded_action.type !== "string") {
      throw new Error(`frame ${index} lacks a recorded action`);
    }
    if (!frame.referee_reveal || !Array.isArray(frame.referee_reveal.decks)) {
      throw new Error(`frame ${index} lacks referee reveal`);
    }
  }
  if (value.availability !== "valid" && value.availability !== "excluded_prefix") {
    throw new Error("bundle availability must be valid or excluded_prefix");
  }
  return value;
}

/** Next/previous candidate-decision index (skips non-candidate plies). */
export function stepCandidateDecision(frames, current, delta) {
  if (!Array.isArray(frames) || frames.length === 0) return 0;
  let next = current + delta;
  while (next >= 0 && next < frames.length && !frames[next].candidate_acted) {
    next += delta;
  }
  return Math.max(0, Math.min(frames.length - 1, next));
}
