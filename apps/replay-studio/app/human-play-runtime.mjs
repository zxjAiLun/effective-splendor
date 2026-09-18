import { occurrenceIdError, replayHref } from "./league-runtime.mjs";

const U64_MAX = 18446744073709551615n;

/** Text all the way to the wire: never round a u64 through JavaScript Number. */
export function seedText(value) {
  if (typeof value !== "string" || !/^[0-9]+$/.test(value.trim())) {
    throw new Error("Seed must be a decimal whole number from 0 to 18446744073709551615.");
  }
  const seed = BigInt(value.trim());
  if (seed > U64_MAX) throw new Error("Seed is larger than the unsigned 64-bit maximum.");
  return seed.toString();
}

export function randomSeed(cryptoSource = globalThis.crypto) {
  const words = cryptoSource.getRandomValues(new Uint32Array(2));
  return ((BigInt(words[0]) << 32n) | BigInt(words[1])).toString();
}

/** Resolve random exactly once, during an explicit new-game attempt, not rendering. */
export function resolveSeat(choice, cryptoSource = globalThis.crypto) {
  if (choice === "first") return 0;
  if (choice === "second") return 1;
  if (choice !== "random") throw new Error("Choose Random, First or Second.");
  return cryptoSource.getRandomValues(new Uint32Array(1))[0] & 1;
}

export function humanStartBody(agentId, seat, seed) {
  if (typeof agentId !== "string" || !agentId) throw new Error("Choose a registered opponent.");
  if (seat !== 0 && seat !== 1) throw new Error("The resolved seat must be 0 or 1.");
  // Only the validated decimal numeric literal is interpolated, not arbitrary input.
  return `{"agent_id":${JSON.stringify(agentId)},"human_seat":${seat},"seed":${seedText(seed)}}`;
}

export function humanResult(result, humanSeat) {
  if (!result || !Array.isArray(result.winners) || !result.winners.length) return "RESULT UNAVAILABLE";
  if (!result.winners.includes(humanSeat)) return "DEFEAT";
  return result.winners.length > 1 ? "DRAW" : "VICTORY";
}

export function bookingView(completion, sessionId) {
  const status = completion?.status;
  const receipt = completion?.receipt;
  const booked = (status === "inserted" || status === "already_present") &&
    receipt?.source_kind === "human_play" && receipt?.source_identity === `runtime:${sessionId}` &&
    typeof receipt?.match_id === "string" && /^[a-f0-9]{64}$/.test(receipt.match_id) &&
    receipt?.outcome?.kind === status;
  if (booked) return {
    kind: "booked", headline: status === "inserted" ? "Recorded in Studio League" : "Already recorded",
    message: status === "inserted" ? "This completed game was recorded once." : "No new rating events. The ratings below belong to the original booking, not another update.",
    retryable: false, error: null, receipt,
    replayHref: /^[a-f0-9]{64}$/.test(receipt?.replay?.document_hash ?? "") ? replayHref(receipt.replay.document_hash) : null,
  };
  if (status === "failed" && typeof completion.retryable === "boolean") return {
    kind: "failed", headline: "League booking failed",
    message: completion.retryable
      ? "The game is finished. Retry offers the same saved evidence; it will not replay the game and does not guarantee insertion."
      : "The game is finished. Automatic retry is not available. See the reason below; rebuilding may be required. Do not replay the game to repair its booking.",
    retryable: completion.retryable, error: typeof completion.error === "string" ? completion.error : null,
    receipt: null, replayHref: null,
  };
  return {
    kind: "unknown", headline: "League booking unconfirmed",
    message: "The game result is separate from booking. This page has no confirmed receipt; it does not know whether Elo changed.",
    retryable: completion?.status === "unknown" && completion?.retryable === true,
    error: typeof completion?.error === "string" ? completion.error : null, receipt: null, replayHref: null,
  };
}

/** A response failure never means the game failed or was definitely not booked. */
export function classifyBookingRetry(status, body, sessionId) {
  if (body?.session_id === sessionId && body?.league_completion) {
    const completion = body.league_completion;
    const view = bookingView(completion, sessionId);
    if ((status === 200 && view.kind === "booked") ||
        (status === 503 && view.kind === "failed" && view.retryable) ||
        (status === 409 && view.kind === "failed" && !view.retryable)) return completion;
  }
  return {
    status: "unknown", retryable: status === null || status >= 500,
    error: typeof body?.error === "string" ? body.error : "No matching booking response was received. The outcome is unknown; check this same session, not a new game.",
    receipt: null,
  };
}

/** Network adapter is also used by the actual button, including the non-2xx body. */
export async function retryHumanBooking(fetcher, api, sessionId) {
  const error = occurrenceIdError(sessionId);
  if (error) throw new Error(error);
  try {
    const response = await fetcher(`${api}/games/${encodeURIComponent(sessionId)}/league-completion`, { method: "POST" });
    let body;
    try { body = await response.json(); } catch { body = null; }
    return classifyBookingRetry(response.status, body, sessionId);
  } catch (error) {
    return classifyBookingRetry(null, { error: `Booking response was lost: ${error instanceof Error ? error.message : String(error)}` }, sessionId);
  }
}

/** Never use receipt event order (or a display label) to decide which Elo is yours. */
export function humanEloRows(receipt, detail, sessionId, humanSeat) {
  if (humanSeat !== 0 && humanSeat !== 1) return [];
  const match = detail?.match;
  if (!receipt || match?.match_id !== receipt.match_id || match?.source_kind !== "human_play" ||
      match?.source_identity !== `runtime:${sessionId}` || receipt.source_identity !== match.source_identity ||
      !Array.isArray(match.seats) || match.seats.length !== 2 || !Array.isArray(receipt.elo) || receipt.elo.length !== 2) return [];
  const ids = new Set(match.seats.map(seat => seat.participant_id));
  if (ids.size !== 2 || match.seats.some(seat => typeof seat.participant_id !== "string" || ![0, 1].includes(seat.seat)) ||
      new Set(match.seats.map(seat => seat.seat)).size !== 2) return [];
  const rows = match.seats.map(seat => {
    const events = receipt.elo.filter(event => event.participant_id === seat.participant_id);
    const event = events[0];
    if (events.length !== 1 || !Number.isFinite(event.elo_before) || !Number.isFinite(event.elo_after)) return null;
    return { participantId: seat.participant_id, label: seat.seat === humanSeat ? "You" : "Opponent",
      before: event.elo_before, after: event.elo_after, delta: event.elo_after - event.elo_before, seat: seat.seat };
  });
  return rows.some(row => row === null) ? [] : rows.sort((a, b) => (a.seat === humanSeat ? -1 : b.seat === humanSeat ? 1 : 0));
}

export function eloText(value) {
  return Number.isFinite(value) ? value.toFixed(1) : "—";
}
