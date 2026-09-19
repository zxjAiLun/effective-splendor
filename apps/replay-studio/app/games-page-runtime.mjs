/**
 * The bounded Studio League games list, as pure functions.
 *
 * Why this module exists separately from `games-runtime.mjs`: that one renders
 * the **legacy** human-vs-engine history (`local-artifacts/m20-human-play`, a
 * directory scan the Host serves from disk), and this one renders the **league**
 * ledger. They are two different authorities over two different corpora, and the
 * product must keep them apart rather than presenting a merged list that silently
 * claims one as the other.
 *
 * The rules here are all about what a page may claim:
 *
 * - the cursor is a `league_seq`, never an offset and never a date, because the
 *   league is still being written to while the player scrolls;
 * - a short page is the end of the recording, and only the **returned** rows can
 *   produce a next cursor;
 * - a seat that has no recorded outcome is shown as unknown, never guessed;
 * - no Elo is shown here at all. A list row is not a rating snapshot, and the
 *   leaderboard is the authoritative Elo view.
 */

/** The Host's own default and ceiling, mirrored for display and for the picker. */
export const GAMES_PAGE_DEFAULT_LIMIT = 50;
export const GAMES_PAGE_MAX_LIMIT = 100;

/**
 * Turn a `next_before_league_seq` into the query string that asks for the page
 * below it.
 *
 * `null`/`undefined` means "no next page", and answering with a query in that
 * case would be a page request that can only come back empty. Returns `null`.
 */
export function gamesLimitError(limit) {
  if (typeof limit !== "number" || !Number.isInteger(limit)) return "The page limit must be an integer.";
  if (limit < 1 || limit > GAMES_PAGE_MAX_LIMIT) {
    return `The page limit must be between 1 and ${GAMES_PAGE_MAX_LIMIT}.`;
  }
  return null;
}

export function nextGamesQuery(nextBeforeLeagueSeq, limit = GAMES_PAGE_DEFAULT_LIMIT) {
  if (typeof nextBeforeLeagueSeq !== "number" || !Number.isFinite(nextBeforeLeagueSeq)) {
    return null;
  }
  const size = clampGamesLimit(limit);
  return `limit=${size}&before=${nextBeforeLeagueSeq}`;
}

/** Keep a client-built query inside the Host's accepted range. The Host is the authority and rejects out-of-range limits with 400; this helper never widens an invalid request into a valid-looking one, because callers always pass the default. */
export function clampGamesLimit(limit) {
  if (typeof limit !== "number" || !Number.isFinite(limit)) return GAMES_PAGE_DEFAULT_LIMIT;
  const whole = Math.trunc(limit);
  if (whole < 1) return 1;
  if (whole > GAMES_PAGE_MAX_LIMIT) return GAMES_PAGE_MAX_LIMIT;
  return whole;
}

/**
 * What one games row may say.
 *
 * `source_kind` is the ledger's own label (`arena_report`, `human_play`, …) and is
 * reported, never re-derived. The outcome line is decided only from recorded
 * seats: with no seat marked as won the row says so instead of picking a side.
 */
export function describeLeagueGameRow(row) {
  const leagueSeq = typeof row?.league_seq === "number" ? row.league_seq : null;
  const seats = Array.isArray(row?.seats) ? row.seats.map(describeLeagueSeat) : [];
  const winners = seats.filter((seat) => seat.won);
  const replaySha = row?.replay_document_sha256 ?? null;
  // `replay_archived` is the ledger's own statement that it recorded a verified,
  // content-addressed object. The archive route is still the authority on whether
  // the bytes can be served, so this only decides whether a link is offered.
  const openReplay = Boolean(replaySha) && row?.replay_archived === true;

  return {
    matchId: row?.match_id ?? null,
    leagueSeq,
    playedAt: typeof row?.played_at === "number" ? row.played_at : null,
    sourceKind: row?.source_kind ?? null,
    status: row?.status ?? null,
    ratingEligible: row?.rating_eligible === true,
    // The frozen reason, when the ledger recorded one. Never phrased as a win or
    // a loss: an ineligible match did not move Elo for anyone.
    ineligibleReason: row?.rating_eligible === false ? row?.rating_ineligible_reason ?? null : null,
    seats,
    scoreLine: scoreLine(seats),
    outcome: outcomeLabel(seats, winners),
    winnerLabels: winners.map((seat) => seat.label),
    // There is deliberately no `detailHref`: the Host serves `GET
    // /league/matches/<id>` as JSON, but no page under `/league/matches/` renders
    // it, and a link to a route that does not exist is a broken promise. Which
    // seat is "you" is also not a fact this row has — the ledger records
    // participants, and the local human's participant id is not in the row — so
    // the row does not claim one.
    replayHref: openReplay ? `/replay?league=${encodeURIComponent(replaySha)}` : null,
    replaySha,
    // A match with no verified archive cannot be opened, and the row says that
    // rather than offering a link that would 404.
    replayUnavailableReason: openReplay
      ? null
      : row?.replay_document_sha256
        ? "The ledger did not record this replay as an archived, verified object."
        : "No replay document is recorded for this match.",
  };
}

/** One seat, labelled from the recorded facts only. */
export function describeLeagueSeat(seat) {
  const index = typeof seat?.seat === "number" ? seat.seat : null;
  const name = seat?.display_name ?? null;
  return {
    seat: index,
    participantId: seat?.participant_id ?? null,
    displayName: name,
    label: name ?? (index === null ? "Unknown seat" : `Seat ${index}`),
    score: typeof seat?.score === "number" ? seat.score : null,
    rank: typeof seat?.rank === "number" ? seat.rank : null,
    won: seat?.won === true,
  };
}

function scoreLine(seats) {
  const scores = seats.map((seat) => seat.score);
  if (!scores.length || scores.some((score) => score === null)) return "—";
  return scores.join(" – ");
}

function outcomeLabel(seats, winners) {
  if (!seats.length) return "—";
  if (!winners.length) return "No recorded winner";
  return winners.map((seat) => seat.label).join(", ");
}

/**
 * The whole page, as the UI state it drives.
 *
 * `nextQuery` is derived from the Host's own cursor, and `atEnd` is derived from
 * the Host saying there is none — never from a page that happened to come back
 * short. That distinction is the difference between "the ledger has more" and "a
 * request returned few rows", and only the Host knows which.
 */
export function describeGamesPage(body) {
  if (!Array.isArray(body?.matches)) {
    return { rows: [], nextBeforeLeagueSeq: null, atEnd: false, invalid: true };
  }
  const rows = body.matches;
  const next = body?.next_before_league_seq;
  if (next !== null && next !== undefined && (typeof next !== "number" || !Number.isInteger(next))) {
    return { rows: [], nextBeforeLeagueSeq: null, atEnd: false, invalid: true };
  }
  return {
    rows: rows.map(describeLeagueGameRow),
    nextBeforeLeagueSeq: typeof next === "number" ? next : null,
    atEnd: typeof next !== "number",
    invalid: false,
  };
}
