/**
 * The Studio League ratings page, as pure functions.
 *
 * D2 split the two rating authorities this product carries, and this module is
 * the Studio side of that boundary. It describes ONLY what a leaderboard row
 * from `GET /league/leaderboard` recorded:
 *
 * - the participant kind is the ledger's own classification, never re-derived
 *   from a display name;
 * - the Elo shown is the league's own current Elo (started at 1500 for every
 *   participant, moved only by rating events) — this module has no concept of
 *   the research reports' Batch BT official Elo, and must never import one;
 * - a missing fact renders as an em dash, never as an invented value: no
 *   unrated participant is shown as "1500", and no absent count as zero.
 *
 * The research reports (M19/M22, Batch BT, head-to-head matrix) are a different
 * corpus under `/ratings/reports` and are deliberately not reachable from this
 * module.
 */

/** The label for a recorded participant kind, or `null` when none was recorded. */
export function describeKind(kind) {
  if (kind === "human") return "Human";
  if (kind === "engine") return "Engine";
  return null;
}

/**
 * The W-T-L line, e.g. "1-0-0".
 *
 * Every component is a recorded count; any missing component makes the whole
 * line unknown ("—") rather than partially guessed, because "1-?-0" is not a
 * fact anyone recorded.
 */
export function recordText(row) {
  const { ratedWins, ratedTies, ratedLosses } = row ?? {};
  if (
    ratedWins === null || ratedWins === undefined ||
    ratedTies === null || ratedTies === undefined ||
    ratedLosses === null || ratedLosses === undefined
  ) {
    return "—";
  }
  return `${ratedWins}-${ratedTies}-${ratedLosses}`;
}

/**
 * The games line, e.g. "1 rated · 1 recorded".
 *
 * "Rated" counts only matches that moved Elo; "recorded" counts distinct
 * matches the participant appears in, eligible or not. The two are different
 * facts and are never merged into a single number here.
 */
export function gamesText(row) {
  const rated = row?.ratedGames;
  const recorded = row?.recordedGames;
  if ((rated === null || rated === undefined) && (recorded === null || recorded === undefined)) {
    return "—";
  }
  const ratedText = rated === null || rated === undefined ? "— rated" : `${rated} rated`;
  const recordedText =
    recorded === null || recorded === undefined ? "— recorded" : `${recorded} recorded`;
  return `${ratedText} · ${recordedText}`;
}

/** The current Elo as the ledger reported it, or an em dash. */
export function eloText(row) {
  const elo = row?.elo;
  return typeof elo === "number" ? `${elo}` : "—";
}

/**
 * The provisional marker: `true` recorded shows "provisional".
 *
 * `false` shows nothing, not "established" — the absence of the flag is not a
 * claim the page needs to make, and `null` (not recorded) must not render as
 * either state.
 */
export function provisionalText(row) {
  return row?.provisional === true ? "provisional" : "";
}
