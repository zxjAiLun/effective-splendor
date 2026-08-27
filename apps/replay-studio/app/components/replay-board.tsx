"use client";

import { useEffect } from "react";
import { DevelopmentCard, EmptyDevelopmentCard, type DevelopmentCardData } from "../development-card";

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
  const actor = frame.actor;

  return (
    <div className="board-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">POSITION</span>
          <h2>Decision board</h2>
        </div>
        {actorLabel ? <span className="budget">{actorLabel}</span> : null}
      </div>

      {reveal && (
        <div className="reveal-warning">
          <span>REFEREE ONLY</span>
          Hidden reserves and future deck order are visible. Do not use this view to judge what P{actor} knew.
        </div>
      )}

      <div className="noble-row">
        <div className="row-label">
          <span>Nobles</span>
          <small>{frame.player_view.public.nobles.length} available</small>
        </div>
        <div className="noble-list">
          {frame.player_view.public.nobles.map((id) => {
            const noble = nobles.get(id);
            return (
              <div className="noble" key={id}>
                <strong>{noble?.prestige ?? 3}</strong>
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
              <small>{frame.player_view.public.deck_counts[tier]} in deck</small>
            </div>
            <div className="deck-card">
              <span>T{tier + 1}</span>
              <strong>{frame.player_view.public.deck_counts[tier]}</strong>
              {reveal && <small>next #{frame.referee_reveal.decks[tier]?.at(-1) ?? "—"}</small>}
            </div>
            {frame.player_view.public.market[tier].map((id, slot) =>
              id == null ? (
                <EmptyDevelopmentCard key={slot} />
              ) : cards.has(id) ? (
                <DevelopmentCard card={cards.get(id)!} key={slot} />
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
        <GemSet gems={frame.player_view.public.bank} />
      </div>

      <div className="players-grid">
        {frame.player_view.public.players.map((player) => {
          const full = frame.referee_reveal.players.find((item) => item.id === player.id);
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
              <GemSet gems={player.tokens} compact />
              <div className="bonus-line">
                {player.bonuses.map((amount, index) => (
                  <span className={`bonus bonus-${COST_COLORS[index]}`} key={index}>
                    {amount}
                  </span>
                ))}
              </div>
              <div className="reserved-line">
                <small>Reserved {player.reserved_count}</small>
                {reveal
                  ? full?.reserved.map((card, index) => (
                      <span className={card.from_deck ? "hidden-card revealed" : "public-card"} key={index}>
                        #{card.card}
                        {card.from_deck ? " ◉" : ""}
                      </span>
                    ))
                  : own
                    ? frame.player_view.private.reserved.map((card) => (
                        <span className="private-card" key={card.slot}>
                          #{card.card}
                        </span>
                      ))
                    : (
                        <>
                          <span className="public-card">
                            {player.public_reserved.map((id) => `#${id}`).join(" ") || "—"}
                          </span>
                          {player.reserved_count > player.public_reserved.length && (
                            <span className="hidden-card">
                              {player.reserved_count - player.public_reserved.length} hidden
                            </span>
                          )}
                        </>
                      )}
              </div>
            </article>
          );
        })}
      </div>
    </div>
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
