// Pure presentation derivations for the Games history home.
//
// The Host may serve a saved game without human metadata (older replays have no
// `.meta.json`, so `human_seat` is null) and may serve a replay that parses but
// fails `verify_replay`. In both cases the product must not invent a fact: no
// seat, no Victory/Defeat, no trusted score. Keeping the rules here (instead of
// inline in the page) makes them directly unit-testable.

const UNREPLAYABLE = "Invalid replay";

/**
 * @param {{session_id:string, opponent?:string|null, human_seat?:number|null,
 *          scores?:number[], winners?:number[], player_count?:number,
 *          verification?:"verified"|"invalid", error?:string}} game
 */
export function describeGameRow(game) {
  const verified = game.verification === "verified";
  const seat = typeof game.human_seat === "number" ? game.human_seat : null;
  const winners = Array.isArray(game.winners) ? game.winners : null;
  return {
    verified,
    seat,
    seatLabel: seat === null ? "Seat unknown" : `You P${seat}`,
    // An unverified replay is not evidence, and an unknown seat cannot decide
    // which side the human was on; only then is a win/loss claim licensed.
    outcome: !verified
      ? UNREPLAYABLE
      : seat === null || winners === null || winners.length === 0
        ? "—"
        : winners.includes(seat)
          ? "Victory"
          : "Defeat",
    scoreLine: verified ? scoreLine(game.scores) : "Result unavailable",
    replayHref: `/replay?session=${encodeURIComponent(game.session_id)}`,
    // Without a known seat the review opens on all decisions; /review already
    // treats a missing seat as "all", so no seat parameter is sent.
    reviewHref: `/review?session=${encodeURIComponent(game.session_id)}${
      seat === null ? "" : `&seat=${seat}`
    }`,
  };
}

function scoreLine(scores) {
  return Array.isArray(scores) && scores.length ? scores.join(" – ") : "—";
}
