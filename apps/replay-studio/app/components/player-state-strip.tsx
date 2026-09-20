"use client";

import { TokenTotal } from "./token-total";
import { type DevelopmentCardData } from "../development-card";

/**
 * Shared player-state summary, above the board on Play, Replay and Review.
 *
 * The three pages had drifted into three different renderings of the same fact:
 * Play had its own `PlayerResources` table, while Replay and Review rendered a
 * `players-grid` inside the board surface. The same player could therefore show
 * different tokens, labels and totals depending on which page you were on. This
 * component is the one presentation of "what does each player hold right now".
 *
 * Scope is deliberately a *compact summary*: token counts, permanent discounts,
 * VP and the reserve/development/noble counts. Reserved card *faces* are not
 * rendered here. They need the hidden-information rules (own view vs opponent vs
 * referee reveal) and already have a home next to the board; duplicating that
 * logic into a header strip is how the boundary would eventually be flattened.
 *
 * Human attribution follows the same rule as the Review seat: a seat is named
 * only when the session actually recorded one. With no authoritative seat the
 * strip shows plain `P0` / `P1` and never invents a "YOU".
 */

export type StripGems = {
  white: number;
  blue: number;
  green: number;
  red: number;
  black: number;
  gold: number;
};

export type StripPlayer = {
  id: number;
  tokens: StripGems;
  bonuses: number[];
  prestige: number;
  reserved_count: number;
  purchased: number[];
  public_reserved: number[];
  nobles: number[];
};

export type StripPlayerView = {
  viewer: number;
  public: {
    player_count: number;
    current_player: number;
    players: StripPlayer[];
  };
};

export type StripCatalogCard = DevelopmentCardData & { id: number };

const GEM_KEYS: Array<keyof StripGems> = ["white", "blue", "green", "red", "black", "gold"];
const BONUS_KEYS = ["white", "blue", "green", "red", "black"] as const;

const GEM_LABELS: Record<string, string> = {
  white: "Diamond",
  blue: "Sapphire",
  green: "Emerald",
  red: "Ruby",
  black: "Onyx",
  gold: "Gold",
};

const GEM_CODES: Record<string, string> = {
  white: "W",
  blue: "U",
  green: "G",
  red: "R",
  black: "K",
  gold: "★",
};

/** A single gem showing its real colour, a visible count, and a text label. */
function StateGem({ gem, count, kind }: { gem: keyof StripGems; count: number; kind: "token" | "bonus" }) {
  if (kind === "token" && count === 0) return null;
  const name = GEM_LABELS[gem] ?? gem;
  const label = kind === "bonus" ? `${count} permanent ${name} discount` : `${count} ${name} token(s)`;
  return (
    <span className={`state-gem state-gem-${gem}`} aria-label={label} title={label}>
      <i aria-hidden="true">{GEM_CODES[gem]}</i>
      <b>{count}</b>
    </span>
  );
}

/**
 * One player's compact state. `isActor` marks the frame's actor; `isHuman` is
 * only ever true when a durable human seat named this player.
 */
export function PlayerStateCard({
  player,
  isActor,
  isHuman,
}: {
  player: StripPlayer;
  isActor: boolean;
  isHuman: boolean;
}) {
  const bonusTotal = player.bonuses.reduce((sum, amount) => sum + amount, 0);
  const identity = isHuman ? "YOU" : isActor ? "ACTOR" : null;
  return (
    <article
      className={`state-card ${isActor ? "state-card-actor" : ""} ${isHuman ? "state-card-human" : ""}`}
      aria-label={`Player ${player.id}${isHuman ? ", you" : ""}${isActor ? ", current actor" : ""}`}
    >
      <div className="state-card-head">
        <span className="state-seat">P{player.id}</span>
        {identity ? <em className="state-identity">{identity}</em> : null}
        <strong className="state-vp">
          {player.prestige}
          <small> VP</small>
        </strong>
      </div>

      <div className="state-line">
        <small>TOKENS</small>
        <div className="state-gems">
          {GEM_KEYS.map((gem) => (
            <StateGem gem={gem} count={player.tokens[gem] ?? 0} kind="token" key={gem} />
          ))}
        </div>
        <TokenTotal tokens={player.tokens} />
      </div>

      <div className="state-line">
        <small>DISCOUNTS</small>
        <div className="state-gems">
          {BONUS_KEYS.map((gem, index) => (
            <StateGem gem={gem} count={player.bonuses[index] ?? 0} kind="bonus" key={gem} />
          ))}
        </div>
        <span className="state-bonus-total" aria-label={`${bonusTotal} total permanent discounts`}>
          <b>{bonusTotal}</b>
        </span>
      </div>

      <div className="state-counts">
        <span>{player.reserved_count} reserved</span>
        <span>{player.purchased.length} developments</span>
        <span>{player.nobles.length} nobles</span>
      </div>
    </article>
  );
}

/**
 * The strip itself: every player's compact state, above the board.
 *
 * `humanSeat` is the durable seat when one exists. `actor` is the frame's actor,
 * which is what "current actor" means; it is not the same thing as "the human"
 * and the two are labelled separately.
 */
export function PlayerStateStrip({
  playerView,
  actor,
  humanSeat = null,
}: {
  playerView: StripPlayerView;
  actor: number;
  humanSeat?: number | null;
}) {
  return (
    <section className="player-state-strip" aria-label="Player state">
      {playerView.public.players.map((player) => (
        <PlayerStateCard
          player={player}
          isActor={player.id === actor}
          isHuman={humanSeat !== null && player.id === humanSeat}
          key={player.id}
        />
      ))}
    </section>
  );
}
