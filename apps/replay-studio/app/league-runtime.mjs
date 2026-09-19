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
 *
 * Every description carries the `kicker` its panel is allowed to print, because
 * the kicker is itself a claim about the ledger. A refusal is a claim about
 * absence, and every refusal the Host produces is emitted before a settled fact
 * can exist: the run either never started (400 / 409 / 503) or never settled (500).
 * The transport case is the only one where the page **cannot know** — the match may
 * have completed and been recorded with the response lost on the way back — so it
 * is the only one that must not print an absence claim. Deriving this label from
 * `retryable` would be wrong in both directions: a `500` is retryable but is not an
 * ambiguous outcome, and a `409` is unambiguous but is not retryable.
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
      kicker: "OUTCOME UNKNOWN",
      headline: "The response was lost, or the Host connection ended.",
      detail: `The match outcome is unknown from this browser: the request may never have arrived, may still be running, or may have completed with its response lost. Retry re-sends the same occurrence id, so it completes that attempt instead of booking a second one.${error ? ` (${error})` : ""}`,
      retryable: true,
    };
  }
  if (status === 409) {
    return {
      kicker: "NOT BOOKED",
      headline: "This occurrence slot is not usable.",
      detail:
        error ??
        "The occurrence id already has evidence that is not a completed match. Use a new match.",
      retryable: false,
    };
  }
  if (status === 503) {
    return {
      kicker: "NOT BOOKED",
      headline: "The Host could not answer for this league.",
      detail: error ?? "The league is unavailable or incomplete.",
      retryable: false,
    };
  }
  if (status === 500) {
    return {
      kicker: "NOT BOOKED",
      headline: "The Host failed before the match settled.",
      detail: error ?? "Nothing was recorded. It is safe to start again.",
      retryable: true,
    };
  }
  return {
    kicker: "NOT BOOKED",
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
    // The participant kind is the ledger's own classification ("human" /
    // "engine"), reported as recorded and never re-derived from a name.
    kind: typeof row?.kind === "string" ? row.kind : null,
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

/**
 * The three states the page may report about the Studio Host.
 *
 * There is no fourth state, and in particular there is no "unknown but let us say
 * ready": the first real walkthrough found the page claiming "Studio Host ready"
 * while both pickers were disabled and every read was hanging, because a pending
 * request and a failed request were indistinguishable in its model.
 */
export const HOST_CHECKING = "checking";
export const HOST_READY = "ready";
export const HOST_NOT_RESPONDING = "not_responding";

/** What each state is allowed to say. Kept here so no panel can phrase it itself. */
export const HOST_STATUS_TEXT = {
  [HOST_CHECKING]: "Checking Studio Host…",
  [HOST_READY]: "Studio Host ready",
  [HOST_NOT_RESPONDING]: "Studio Host not responding",
};

/**
 * The UI budget for the ordinary **first-screen reads**.
 *
 * It deliberately does not apply to `POST /league/matches`: a real match can take a
 * long time, and that request already has its own occurrence-id ambiguity/retry
 * contract. Aborting it would manufacture `OUTCOME UNKNOWN` panels for matches that
 * were running normally, so the write path keeps no client-side deadline at all.
 */
export const FIRST_SCREEN_READ_TIMEOUT_MS = 5000;

/**
 * The budget for the **leaderboard** read, which is deliberately larger.
 *
 * The leaderboard is an aggregate over the whole league, so its first request after
 * the Host starts is a genuine cold read of the real database: measured at **3.0 s**
 * against the 42k-match league, falling to ~1.0 s once SQLite's page cache is warm.
 * A 5 s budget would leave barely two seconds of margin, and the things that eat
 * margin on a developer machine — on-access antivirus scanning, a cold filesystem
 * cache, a background `cargo` build, a laptop on a power-saving profile — are all
 * ordinary rather than exceptional.
 *
 * Raising this is the honest alternative to pretending the read is fast: the Host
 * still fails in a bounded time when it really is not answering, and a legitimate
 * cold read no longer gets mislabelled as "not responding".
 */
export const LEADERBOARD_READ_TIMEOUT_MS = 10000;

/** The read outcomes one first-screen read can end in. */
export const READ_OK = "ok";
export const READ_REFUSED = "refused";
export const READ_TIMED_OUT = "timed_out";
export const READ_UNREACHABLE = "unreachable";

/**
 * Classify a failed first-screen read.
 *
 * A timeout and a refused read are different facts: the first says the Host accepted
 * the connection and said nothing, the second says the Host answered and the answer
 * was no. Only the first is a Host liveness problem, and only the second may be
 * described as the league/registry refusing.
 */
export function describeReadFailure(reason, timeoutMs = FIRST_SCREEN_READ_TIMEOUT_MS) {
  if (reason?.readKind === READ_REFUSED) {
    return {
      kind: READ_REFUSED,
      message: reason instanceof Error ? reason.message : String(reason),
    };
  }
  const name = reason?.name;
  if (name === "AbortError" || name === "TimeoutError") {
    return {
      kind: READ_TIMED_OUT,
      message: `no answer within ${timeoutMs / 1000} seconds`,
    };
  }
  return {
    kind: READ_UNREACHABLE,
    message: reason instanceof Error ? reason.message : String(reason),
  };
}

/**
 * The Host state, from the two independent first-screen reads.
 *
 * `checking` wins over everything, and an *unset* reading counts as checking: not
 * having heard back is never evidence of readiness. A refusal (`503` from a stale
 * league, say) is **not** a liveness problem — the Host answered — so it must not
 * be reported as "not responding".
 */
export function hostStateOf(readings) {
  const states = [readings?.roster, readings?.league];
  if (states.some((state) => state === undefined || state === HOST_CHECKING)) {
    return HOST_CHECKING;
  }
  if (states.some((state) => state === READ_TIMED_OUT || state === READ_UNREACHABLE)) {
    return HOST_NOT_RESPONDING;
  }
  return HOST_READY;
}

/** The one line the header may show for a state. */
export function hostStatusText(state) {
  return HOST_STATUS_TEXT[state] ?? HOST_STATUS_TEXT[HOST_CHECKING];
}

/**
 * What to say about a first-screen read that did not succeed.
 *
 * `advice` is only filled where the advice is true: telling somebody to start a Host
 * that is running and merely slow is exactly the kind of confident, wrong sentence
 * this page is not allowed to print.
 */
export function describeHostBanner(kind, message) {
  if (kind === READ_TIMED_OUT) {
    return {
      headline: `The Studio Host answered the connection but did not answer the request: ${message}.`,
      advice:
        "It is probably running a slow request — the Host answers one request at a time — so it is not necessarily down.",
    };
  }
  if (kind === READ_UNREACHABLE) {
    return {
      headline: `The Studio Host could not be reached: ${message}.`,
      advice: "Start it, then reload",
    };
  }
  return { headline: `The request was refused: ${message}.`, advice: null };
}
