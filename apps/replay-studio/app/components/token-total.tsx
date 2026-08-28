/**
 * Token-cap readout shared by the review board, the replay board and the
 * human play table.
 *
 * Splendor caps a player at ten held tokens regardless of player count, and
 * that cap is what forces token returns. Showing the six per-colour counts
 * without the total made the binding constraint invisible, so every board
 * renders this component next to its gem strip.
 */

const TOKEN_CAP = 10;

const GEM_KEYS = ["white", "blue", "green", "red", "black", "gold"] as const;

export type TokenCounts = Record<(typeof GEM_KEYS)[number], number>;

export function sumTokens(tokens: TokenCounts): number {
  return GEM_KEYS.reduce((total, gem) => total + (tokens[gem] ?? 0), 0);
}

/**
 * `held / 10`, flagged once the holding reaches the cap. `over` should never
 * appear in a verified replay; it is rendered rather than clamped so a state
 * bug stays visible instead of being silently hidden by the UI.
 */
export function TokenTotal({ tokens }: { tokens: TokenCounts }) {
  const total = sumTokens(tokens);
  const state = total > TOKEN_CAP ? "over-cap" : total === TOKEN_CAP ? "at-cap" : "";
  return (
    <span className={`token-total ${state}`.trimEnd()} aria-label={`${total} of ${TOKEN_CAP} tokens held`}>
      <b>{total}</b>
      <span>/{TOKEN_CAP}</span>
      {state ? <i>{total > TOKEN_CAP ? "OVER" : "FULL"}</i> : null}
    </span>
  );
}

export { TOKEN_CAP };
