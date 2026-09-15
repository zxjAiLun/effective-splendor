/**
 * League Play decisions, as pure functions.
 *
 * The page renders; this module decides. Everything the player-facing round trip
 * has to get right lives here so it can be tested without a Host and without a
 * browser:
 *
 * - the occurrence-id rule, mirrored from the Host's path composer
 *   (`crates/splendor-studio-league/src/paths.rs::validate_occurrence_id`);
 * - the exact write request the Host accepts — and nothing else, ever;
 * - the two facts a result carries, which must never be merged;
 * - what a leaderboard row may claim, which is only what the ledger returned.
 *
 * Mirroring a Host rule here is deliberate: the client should refuse a request the
 * Host would refuse, and say why in the player's language. It is a mirror, never a
 * second authority — the Host still validates everything and remains the only
 * decider.
 */

/** Longest occurrence id the Host will turn into a path component. */
export const MAX_OCCURRENCE_ID_BYTES = 128;

/** Studio Host defaults for the three match timeouts, for display only. */
export const OCCURRENCE_ID_PATTERN = /^[A-Za-z0-9._-]+$/;

/**
 * The Host's occurrence-id rule, as an error message or `null`.
 *
 * Kept character-for-character in agreement with the Rust validator: non-empty,
 * at most 128 bytes, not `.` or `..`, no leading or trailing dot, and every byte
 * in `[A-Za-z0-9._-]`.
 */
export function occurrenceIdError(id) {
  if (typeof id !== "string" || id.length === 0) {
    return "An occurrence id is required.";
  }
  if (id.length > MAX_OCCURRENCE_ID_BYTES) {
    return `The occurrence id is longer than ${MAX_OCCURRENCE_ID_BYTES} characters.`;
  }
  if (id === "." || id === "..") {
    return "The occurrence id cannot be a relative path component.";
  }
  if (id.startsWith(".") || id.endsWith(".")) {
    return "The occurrence id cannot start or end with a dot.";
  }
  if (!OCCURRENCE_ID_PATTERN.test(id)) {
    return "The occurrence id may only use letters, digits, dot, underscore and dash.";
  }
  return null;
}

/**
 * A 4-hex salt for an occurrence id.
 *
 * Isolated here (and called once per attempt, never per retry) so that
 * `newOccurrenceId` itself stays deterministic and testable.
 */
export function randomSalt() {
  return Math.floor(Math.random() * 0x10000)
    .toString(16)
    .padStart(4, "0");
}

/**
 * Mint an occurrence id: `studio-<epoch-ms>-<4 hex>`.
 *
 * The id is the occurrence's **identity**, not a per-request token, so it is
 * minted exactly once per attempt and then re-sent unchanged on retry. A retry
 * that minted a new id would book a second match for what is the same attempt.
 */
export function newOccurrenceId(nowMs, salt) {
  if (!Number.isSafeInteger(nowMs) || nowMs < 0) {
    throw new Error("newOccurrenceId needs a non-negative epoch-millisecond value");
  }
  if (typeof salt !== "string" || !/^[0-9a-f]{4}$/.test(salt)) {
    throw new Error("newOccurrenceId needs a 4-character lowercase hex salt");
  }
  const id = `studio-${nowMs}-${salt}`;
  const error = occurrenceIdError(id);
  if (error) {
    throw new Error(`minted an unusable occurrence id: ${error}`);
  }
  return id;
}

/** The game id that travels with an occurrence. Derived once, from the id. */
export function gameIdFor(occurrenceId) {
  return `league-${occurrenceId}`;
}

/** The arena's own `game_id` rule, as an error message or `null`. */
export function gameIdError(gameId) {
  if (typeof gameId !== "string" || gameId.trim().length === 0) {
    return "A game id is required.";
  }
  if (gameId.length > MAX_OCCURRENCE_ID_BYTES) {
    return `The game id is longer than ${MAX_OCCURRENCE_ID_BYTES} bytes.`;
  }
  for (const character of gameId) {
    if (character.codePointAt(0) < 0x20) {
      return "The game id cannot contain control characters.";
    }
  }
  return null;
}

/**
 * Check the seats a player picked.
 *
 * Two to four registry agent ids, matching what `ArenaConfig::validate()` accepts.
 * A duplicate is **allowed**: a self-match is a legal match that the league simply
 * records as rating-ineligible, so the UI must not forbid it — it only says so.
 */
export function seatsError(seats) {
  if (!Array.isArray(seats)) {
    return "Pick two registered agents.";
  }
  if (seats.length < 2 || seats.length > 4) {
    return `A match needs two to four seats, not ${seats.length}.`;
  }
  for (const seat of seats) {
    if (typeof seat !== "string" || seat.length === 0) {
      return "Every seat must name a registered agent.";
    }
  }
  return null;
}

/** `true` when the same agent occupies more than one seat. */
export function isSelfMatch(seats) {
  return Array.isArray(seats) && new Set(seats).size !== seats.length;
}

/**
 * Validate one attempt before anything is sent.
 *
 * Returns `{error, notes}`: `error` blocks the request, `notes` are things the
 * player should know but that do not block anything (a self-match is the only one).
 */
export function validateStart(start) {
  const notes = [];
  const idError = occurrenceIdError(start?.occurrenceId);
  if (idError) return { error: idError, notes };
  const gameError = gameIdError(start?.gameId);
  if (gameError) return { error: gameError, notes };
  const seatError = seatsError(start?.seats);
  if (seatError) return { error: seatError, notes };
  if (!Number.isSafeInteger(start?.seed) || start.seed < 0) {
    return { error: "The seed must be a non-negative whole number.", notes };
  }
  if (isSelfMatch(start.seats)) {
    notes.push("Self-match: the league will record it, but it is not rating-eligible.");
  }
  return { error: null, notes };
}

/**
 * The write body, built key by key.
 *
 * Built rather than spread, so a stray field on the input (a timeout, a program,
 * an `ArenaConfig` fragment) cannot reach the Host: the four keys below are the
 * entire protocol. The fixture in `tests/fixtures/league-match-request.json` and a
 * Rust Host gate pin this shape from both sides.
 */
export function startRequestBody(start) {
  return {
    occurrence_id: start.occurrenceId,
    game_id: start.gameId,
    seed: start.seed,
    seats: [...start.seats],
  };
}

/**
 * The body to re-send for a retry.
 *
 * Byte-for-byte the original attempt: same occurrence id, same game id, same seed,
 * same seats. A retry that changed the id would run a second match instead of
 * completing the one that already happened.
 */
export function retryRequest(pendingRequest) {
  return {
    occurrence_id: pendingRequest.occurrence_id,
    game_id: pendingRequest.game_id,
    seed: pendingRequest.seed,
    seats: [...pendingRequest.seats],
  };
}

/** The link that opens one league match's replay in the existing replay viewer. */
export function replayHref(documentSha256) {
  return typeof documentSha256 === "string" && documentSha256.length > 0
    ? `/replay?league=${encodeURIComponent(documentSha256)}`
    : null;
}

/**
 * Describe a booking response.
 *
 * The Host answers with two independent facts — what the match did and what the
 * league did with it — and this function keeps them independent all the way to the
 * screen. A `503 completed + completion failed` is a *completed match* whose
 * booking failed and which is safe to retry; it must never be rendered as one
 * failed thing.
 */
export function describeResult(response) {
  const matchStatus = typeof response?.match_status === "string" ? response.match_status : null;
  const completionStatus =
    typeof response?.completion_status === "string" ? response.completion_status : null;
  const receipt = response?.receipt ?? null;
  const elo = Array.isArray(receipt?.elo)
    ? receipt.elo.map((event) => ({
        participantId: event.participant_id,
        eloBefore: event.elo_before,
        eloAfter: event.elo_after,
      }))
    : [];
  const documentSha256 = receipt?.replay?.document_hash ?? null;

  let headline;
  let booking;
  if (matchStatus === "completed" && completionStatus === "failed") {
    headline = "The match completed.";
    booking = "Booking failed — the occurrence is safe to retry and the match will not be re-run.";
  } else if (matchStatus === "completed" && completionStatus === "inserted") {
    headline = "The match completed and was recorded.";
    booking = `Recorded (${receipt?.outcome?.rating_events ?? 0} rating events).`;
  } else if (matchStatus === "completed" && completionStatus === "already_present") {
    headline = "The match completed.";
    booking = "This occurrence was already recorded — no new Elo.";
  } else if (matchStatus === "completed") {
    headline = "The match completed.";
    booking = completionStatus ? `League booking: ${completionStatus}.` : "League booking unknown.";
  } else if (matchStatus === "aborted" || matchStatus === "truncated") {
    headline = `The match ${matchStatus}.`;
    booking = "Nothing was recorded: a settled, unfinished match has no occurrence.";
  } else {
    headline = "The Host answered something this page does not recognise.";
    booking = "See the raw response below.";
  }

  return {
    matchStatus,
    completionStatus,
    headline,
    booking,
    problem: typeof response?.error === "string" ? response.error : null,
    retryable: matchStatus === "completed" && completionStatus === "failed",
    sourceIdentity: receipt?.source_identity ?? null,
    matchId: receipt?.match_id ?? null,
    eligibility: receipt?.eligibility ?? null,
    elo,
    documentSha256,
    replayHref: replayHref(documentSha256),
    raw: response,
  };
}

/**
 * Describe a request that never produced a booking response.
 *
 * `status` is the HTTP status when there was one; `null` means the Host could not
 * be reached at all, which is a different problem from the Host refusing.
 */
export function describeFailure(status, body) {
  const error = typeof body?.error === "string" ? body.error : null;
  if (status === null) {
    // A thrown `fetch` cannot distinguish "never arrived", "still running" and
    // "finished, response lost". All four possibilities are safe to retry with the
    // *same* occurrence id, and this is the one case where the page would otherwise
    // push the player toward `New match` — which mints a new occurrence and can run
    // a second rated match for an attempt that may already have happened.
    return {
      headline: "The response was lost, or the Host connection ended.",
      detail: `The match outcome is unknown from this browser: the request may never have arrived, may still be running, or may have completed with its response lost. Retry re-sends the same occurrence id, so it completes that attempt instead of booking a second one.${error ? ` (${error})` : ""}`,
      retryable: true,
    };
  }
  if (status === 409) {
    return {
      headline: "This occurrence slot is not usable.",
      detail:
        error ??
        "The occurrence id already has evidence that is not a completed match. Use a new match.",
      retryable: false,
    };
  }
  if (status === 503) {
    return {
      headline: "The Host could not answer for this league.",
      detail: error ?? "The league is unavailable or incomplete.",
      retryable: false,
    };
  }
  if (status === 500) {
    return {
      headline: "The Host failed before the match settled.",
      detail: error ?? "Nothing was recorded. It is safe to start again.",
      retryable: true,
    };
  }
  return {
    headline: `The Host refused this request (HTTP ${status}).`,
    detail: error ?? "No further detail was returned.",
    retryable: false,
  };
}

/**
 * Classify one write response into a settled fact or a refusal.
 *
 * The Host answers a booking on **two independent axes** — what the match did and
 * what the league did with it — and *whether a match settled is decided by the
 * shape of the body, not by the status code*. `503 completed + completion failed`
 * is a finished match whose booking failed: it belongs in the result panel, with
 * its retry, and demoting it to a generic transport failure would merge exactly the
 * two facts this slice exists to keep apart.
 *
 * A body carrying both axes is a settled fact whatever the status; anything else
 * is a refusal (including a `503` that carries only an `error`, which is the league
 * itself being unavailable).
 */
export function classifyBookingResponse(status, body) {
  const settled =
    typeof body?.match_status === "string" && typeof body?.completion_status === "string";
  if (settled) {
    return { settled: true, result: describeResult(body), failure: null };
  }
  return { settled: false, result: null, failure: describeFailure(status, body) };
}

/**
 * Leaderboard rows, rendered verbatim.
 *
 * Every field comes from the ledger's own row. Nothing is recomputed, no missing
 * Elo is defaulted to 1500, and no eligibility is inferred: a row that cannot be
 * read is shown as unreadable rather than silently dropped or guessed.
 */
export function describeLeaderboard(rows) {
  if (!Array.isArray(rows)) return [];
  return rows.map((row) => ({
    participantId: row?.participant_id ?? null,
    displayName: row?.display_name ?? null,
    elo: typeof row?.elo === "number" ? row.elo : null,
    ratedGames: row?.rated_games ?? null,
    recordedGames: row?.recorded_games ?? null,
    ratedWins: row?.rated_wins ?? null,
    ratedTies: row?.rated_ties ?? null,
    ratedLosses: row?.rated_losses ?? null,
    provisional: typeof row?.provisional === "boolean" ? row.provisional : null,
  }));
}

/**
 * The agent options a picker may offer.
 *
 * These come from the Host's own registry (`GET /agents`) — the roster the write
 * route resolves — and nothing else is claimed about them. In particular **no Elo
 * is attached here**: a leaderboard row is identified by a participant id
 * (`eng-<hash>`), and a registry agent is identified by its registry id; the two
 * closed read routes share no join key, and inventing one (or guessing by display
 * name) would attribute a rating to the wrong agent. The leaderboard table beside
 * the pickers is the authoritative Elo view, and the result panel carries the
 * authoritative deltas for the match just booked.
 */
export function describeAgentOptions(agents) {
  if (!Array.isArray(agents)) return [];
  return agents.map((agent) => ({
    id: agent?.id ?? null,
    displayName: agent?.display_name ?? agent?.id ?? null,
    agentClass: agent?.class ?? null,
    policyVersion: agent?.policy_version ?? null,
  }));
}
