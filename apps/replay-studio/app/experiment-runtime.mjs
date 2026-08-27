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

/**
 * Whether a step button in the given direction should be disabled: the
 * button is disabled exactly when stepping would not change the position
 * (the boundary case in candidate-only mode, or the first/last ply in
 * plain mode).
 */
export function isStepDisabled(frames, current, delta, candidateOnly) {
  if (!Array.isArray(frames) || frames.length === 0) return true;
  const clamped = Math.max(0, Math.min(frames.length - 1, current));
  const target = candidateOnly
    ? stepCandidateDecision(frames, clamped, delta)
    : Math.max(0, Math.min(frames.length - 1, clamped + delta));
  return target === clamped;
}

/**
 * Deep-link hydration state machine (mirrors the page's gating logic):
 * the initial query is captured BEFORE any URL sync runs, and sync stays
 * disabled until `apply` marks hydration complete. This prevents the sync
 * effect from rewriting
 * `/experiments?experiment=m35a&pairing=..&match=N` down to
 * `?experiment=m35a` during the async bootstrap window when the
 * pairing/match state has not been installed yet.
 */
export function createDeepLinkHydration(initialQuery) {
  const captured = initialQuery instanceof URLSearchParams ? initialQuery : null;
  let applied = false;
  return {
    /** The query captured at first render (never re-read from the live URL). */
    captured,
    /** Whether the initial deep link has been fully applied. */
    isApplied() {
      return applied;
    },
    /**
     * Apply the captured deep link against the loaded experiment index.
     * Returns the selection to install (or null) and marks hydration done.
     */
    apply(experimentIndex) {
      applied = true;
      const selection = captured ? parseExperimentsQuery(captured) : null;
      if (!selection || !experimentIndex) return null;
      const exists = experimentIndex.experiments
        ?.find((experiment) => experiment.id === selection.experiment)
        ?.pairings.some((entry) => entry.evaluation_id === selection.pairing);
      if (!exists) return null;
      return selection;
    },
  };
}

/**
 * Next/previous candidate-decision index (skips non-candidate plies).
 * Boundary-safe in both directions:
 * - forward from any ply lands on the first candidate decision at or after
 *   the current ply (strictly after it when the current ply is itself a
 *   candidate decision);
 * - backward lands on the last candidate decision at or before the current
 *   ply (strictly before it when the current ply is a candidate decision);
 * - when no further candidate decision exists in the step direction, the
 *   nearest candidate frame in that direction is kept — never an opponent
 *   ply at the edge.
 */
export function stepCandidateDecision(frames, current, delta) {
  if (!Array.isArray(frames) || frames.length === 0) return 0;
  const clamped = Math.max(0, Math.min(frames.length - 1, current));
  if (delta === 0) return clamped;
  const forward = delta > 0;

  const candidateAt = (index) =>
    index >= 0 && index < frames.length && frames[index].candidate_acted;

  // Step window: forward considers [clamped, end]; backward considers
  // [0, clamped]. The current ply is included only when it is NOT itself a
  // candidate decision (stepping from a candidate always moves past it).
  let start = clamped;
  let end = forward ? frames.length - 1 : 0;
  if (candidateAt(clamped)) {
    start = forward ? clamped + 1 : clamped - 1;
  }

  // Scan for the nearest candidate decision within the window.
  let found = -1;
  if (forward) {
    for (let index = start; index <= end; index += 1) {
      if (candidateAt(index)) {
        found = index;
        break;
      }
    }
  } else {
    for (let index = start; index >= end; index -= 1) {
      if (candidateAt(index)) {
        found = index;
        break;
      }
    }
  }
  if (found >= 0) return found;

  // No candidate decision in the step direction: keep the nearest candidate
  // frame on the OTHER side (the boundary edge), or the clamped position
  // when the game has no candidate decisions at all.
  if (forward) {
    for (let index = clamped; index >= 0; index -= 1) {
      if (candidateAt(index)) return index;
    }
  } else {
    for (let index = clamped; index < frames.length; index += 1) {
      if (candidateAt(index)) return index;
    }
  }
  return clamped;
}
