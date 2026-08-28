"use client";

import { useEffect } from "react";
import { DevelopmentCard, EmptyDevelopmentCard, HiddenDevelopmentCard, type DevelopmentCardData } from "../development-card";
import { TokenTotal } from "./token-total";

export type CardId = number;
export type NobleId = number;
export type PlayerId = number;

export type Gems = {
  white: number;
  blue: number;
  green: number;
  red: number;
  black: number;
  gold: number;
};

export type Action = { type: string; [key: string]: unknown };

export type PlayerView = {
  viewer: PlayerId;
  public: {
    player_count: number;
    current_player: PlayerId;
    phase: string;
    bank: Gems;
    market: Array<Array<CardId | null>>;
    deck_counts: number[];
    nobles: NobleId[];
    players: Array<{
      id: PlayerId;
      tokens: Gems;
      bonuses: number[];
      prestige: number;
      reserved_count: number;
      public_reserved: CardId[];
      purchased: CardId[];
      nobles: NobleId[];
    }>;
    pending_nobles: NobleId[];
  };
  private: {
    reserved: Array<{
      slot: number;
      card: CardId;
      tier: string;
      from_deck: boolean;
    }>;
  };
};

export type RefereeReveal = {
  seed: number;
  decks: CardId[][];
  players: Array<{
    id: PlayerId;
    reserved: Array<{ card: CardId; from_deck: boolean }>;
  }>;
};

export type CatalogData = {
  cards: Array<DevelopmentCardData & { id: CardId }>;
  nobles: Array<{ id: NobleId; prestige: number; requirements: number[] }>;
};

export type BoardFrame = {
  ply: number;
  actor: PlayerId;
  recorded_action: Action;
  player_view: PlayerView;
  referee_reveal: RefereeReveal;
};

const GEM_KEYS: Array<keyof Gems> = ["white", "blue", "green", "red", "black", "gold"];
const COST_COLORS = ["white", "blue", "green", "red", "black"];

export function gemCode(key: keyof Gems): string {
  return { white: "W", blue: "U", green: "G", red: "R", black: "K", gold: "★" }[key];
}

export function simpleActionLabel(action: Action): string {
  const tier = typeof action.tier === "string" ? ` ${action.tier}` : "";
  const slot = typeof action.slot === "number" ? ` slot ${action.slot + 1}` : "";
  if (action.type === "buy_market") return `Buy${tier}${slot}`;
  if (action.type === "buy_reserved") return `Buy reserved${slot}`;
  if (action.type === "reserve_market") return `Reserve${tier}${slot}`;
  if (action.type === "reserve_deck") return `Reserve from${tier} deck`;
  if (action.type === "take_tokens") return "Take tokens";
  if (action.type === "choose_noble") return `Choose noble #${action.noble}`;
  return action.type.replaceAll("_", " ");
}

export function GemSet({ gems, compact = false }: { gems: Gems; compact?: boolean }) {
  return (
    <div className={`gem-set ${compact ? "compact" : ""}`}>
      {GEM_KEYS.map((key) => (
        <span className={`token token-${key}`} key={key}>
          <i>{key === "gold" ? "★" : gemCode(key)}</i>
          <strong>{gems[key]}</strong>
        </span>
      ))}
    </div>
  );
}

export function BoardPanel({
  frame,
  cards,
  nobles,
  reveal,
  actorLabel,
}: {
  frame: BoardFrame;
  cards: Map<number, DevelopmentCardData & { id: CardId }>;
  nobles: Map<number, { id: NobleId; prestige: number; requirements: number[] }>;
  reveal: boolean;
  actorLabel?: string;
}) {
  return (
    <div className="board-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">POSITION</span>
          <h2>Decision board</h2>
        </div>
        {actorLabel ? <span className="budget">{actorLabel}</span> : null}
      </div>
      <BoardSurface frame={frame} cards={cards} nobles={nobles} reveal={reveal} />
    </div>
  );
}

/**
 * Nobles, market, bank and player cards for one decision frame.
 *
 * Split out of `BoardPanel` so the review route can wrap it in its own heading
 * (which carries the player-view / referee-reveal switch) instead of keeping a
 * second copy of the board. The duplicate had already drifted: it rendered
 * nobles from the *card* catalogue with a hardcoded prestige of 3 and dropped
 * their requirements entirely.
 */
export function BoardSurface({
  frame,
  cards,
  nobles,
  reveal,
}: {
  frame: BoardFrame;
  cards: Map<number, DevelopmentCardData & { id: CardId }>;
  nobles: Map<number, { id: NobleId; prestige: number; requirements: number[] }>;
  reveal: boolean;
}) {
  const actor = frame.actor;
  const view = frame.player_view.public;

  return (
    <div>
      <div className="noble-row">
        <div className="row-label">
          <span>Nobles</span>
          <small>{view.nobles.length} available</small>
        </div>
        <div className="noble-list">
          {view.nobles.map((id) => {
            const noble = nobles.get(id);
            return (
              <div className="noble" key={id}>
                <strong>{noble?.prestige ?? "?"}</strong>
                <span>#{id}</span>
                <div className="mini-cost">
                  {(noble?.requirements ?? []).map((amount, index) =>
                    amount > 0 ? (
                      <i className={`gem gem-${COST_COLORS[index]}`} key={index}>
                        {amount}
                      </i>
                    ) : null,
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="market-grid">
        {[2, 1, 0].map((tier) => (
          <div className="market-row" key={tier}>
            <div className="row-label">
              <span>Tier {tier + 1}</span>
              <small>{view.deck_counts[tier]} in deck</small>
            </div>
            <div className="deck-card">
              <span>T{tier + 1}</span>
              <strong>{view.deck_counts[tier]}</strong>
              {reveal && <small>next #{frame.referee_reveal.decks[tier]?.at(-1) ?? "—"}</small>}
            </div>
            {view.market[tier].map((id, slot) =>
              id == null ? (
                <EmptyDevelopmentCard key={slot} />
              ) : cards.has(id) ? (
                <DevelopmentCard card={cards.get(id)!} slotLabel={`slot ${slot + 1}`} key={slot} />
              ) : (
                <div className="development-card development-card-empty" key={slot}>
                  <span>#{id}</span>
                </div>
              ),
            )}
          </div>
        ))}
      </div>

      <div className="bank-row">
        <div className="row-label">
          <span>Bank</span>
          <small>available tokens</small>
        </div>
        <GemSet gems={view.bank} />
      </div>

      <div className="players-grid">
        {view.players.map((player) => {
          const own = player.id === actor;
          return (
            <article className={`player-card ${own ? "actor-card" : ""}`} key={player.id}>
              <div className="player-title">
                <div>
                  <span>P{player.id}</span>
                  {own && <em>ACTOR</em>}
                </div>
                <strong>
                  {player.prestige}
                  <small> VP</small>
                </strong>
              </div>

              <div className="player-resource-line">
                <small>TOKENS</small>
                <GemSet gems={player.tokens} compact />
                <TokenTotal tokens={player.tokens} />
              </div>

              <div className="player-resource-line">
                <small>DISCOUNTS</small>
                <div className="bonus-line">
                  {player.bonuses.map((amount, index) => (
                    <span
                      className={`bonus bonus-${COST_COLORS[index]}`}
                      key={index}
                      aria-label={`${amount} permanent ${COST_COLORS[index]} discount`}
                    >
                      {amount}
                    </span>
                  ))}
                </div>
                <span className="token-total">
                  <b>{player.bonuses.reduce((sum, amount) => sum + amount, 0)}</b>
                </span>
              </div>

              <ReservedCards frame={frame} player={player} own={own} reveal={reveal} cards={cards} />
            </article>
          );
        })}
      </div>
    </div>
  );
}

/**
 * A player's reserved cards, rendered as real card faces so their purchase
 * cost is legible instead of a bare `#37`.
 *
 * Information boundary — the identities disclosed here are exactly those the
 * viewer is entitled to, and nothing more:
 *
 *   referee reveal : every reserve, blind ones flagged as such.
 *   own reserve    : `private.reserved`; a player always knows what they took,
 *                    including their own blind reserve from a deck.
 *   opponent       : `public_reserved` only — cards taken face-up from the
 *                    market, which is public information in Splendor. Blind
 *                    reserves stay face-down as `HiddenDevelopmentCard`.
 *
 * Reserve cards render the printed cost, not the net cost after discounts:
 * the reserve strip is too compact for the owed/printed pair, and the player
 * can read the full market card or hover/click the reserve for details.
 */
function ReservedCards({
  frame,
  player,
  own,
  reveal,
  cards,
}: {
  frame: BoardFrame;
  player: PlayerView["public"]["players"][number];
  own: boolean;
  reveal: boolean;
  cards: Map<number, DevelopmentCardData & { id: CardId }>;
}) {
  const known: Array<{ card: CardId; fromDeck: boolean }> = reveal
    ? (frame.referee_reveal.players.find((item) => item.id === player.id)?.reserved ?? []).map((item) => ({
        card: item.card,
        fromDeck: item.from_deck,
      }))
    : own
      ? frame.player_view.private.reserved.map((item) => ({ card: item.card, fromDeck: item.from_deck }))
      : player.public_reserved.map((id) => ({ card: id, fromDeck: false }));

  const hidden = Math.max(0, player.reserved_count - known.length);

  return (
    <>
      <div className="reserved-heading">
        <small>RESERVED {player.reserved_count}</small>
        {hidden > 0 ? <em>{hidden} identity hidden from this view</em> : null}
      </div>
      <div className="reserved-cards">
        {known.map((item, index) =>
          cards.has(item.card) ? (
            <DevelopmentCard
              card={cards.get(item.card)!}
              variant="mini"
              slotLabel={item.fromDeck ? "blind ◉" : "reserved"}
              key={`${item.card}-${index}`}
            />
          ) : (
            <div className="development-card development-card-empty" key={`${item.card}-${index}`}>
              <span>#{item.card}</span>
            </div>
          ),
        )}
        {hidden > 0 ? <HiddenDevelopmentCard count={hidden} /> : null}
        {known.length === 0 && hidden === 0 ? <span className="reserved-empty">none</span> : null}
      </div>
    </>
  );
}

export function ReplayTimeline({
  frames,
  frameIndex,
  onSeek,
  isCandidatePly,
  title,
  footnote,
}: {
  frames: Array<{ ply: number; actor: PlayerId }>;
  frameIndex: number;
  onSeek: (index: number) => void;
  isCandidatePly?: (frame: { ply: number; actor: PlayerId }, index: number) => boolean;
  title: string;
  footnote: string;
}) {
  return (
    <footer className="timeline-panel">
      <div className="timeline-title">
        <div>
          <span className="section-kicker">TIMELINE</span>
          <strong>
            {frameIndex + 1} / {frames.length}
          </strong>
        </div>
        <span>
          {title} · {footnote}
        </span>
      </div>
      <div className="timeline">
        {frames.map((item, index) => (
          <button
            key={`${item.ply}-${index}`}
            onClick={() => onSeek(index)}
            className={`${index === frameIndex ? "current" : ""} ${
              isCandidatePly ? (isCandidatePly(item, index) ? "agreed" : "disagreed") : "agreed"
            }`}
            aria-label={`Ply ${item.ply}, actor P${item.actor}`}
          >
            <span>{item.ply}</span>
            <i />
          </button>
        ))}
      </div>
    </footer>
  );
}

/** Arrow-key navigation hook shared by all replay viewers. */
export function usePlyNavigation(frameCount: number, onDelta: (delta: number) => void) {
  useEffect(() => {
    const navigate = (event: globalThis.KeyboardEvent) => {
      if (event.key === "ArrowLeft") onDelta(-1);
      if (event.key === "ArrowRight") onDelta(1);
    };
    window.addEventListener("keydown", navigate);
    return () => window.removeEventListener("keydown", navigate);
  }, [frameCount, onDelta]);
}
