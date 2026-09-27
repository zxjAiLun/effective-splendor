"use client";

import { DevelopmentCard, HiddenDevelopmentCard, type DevelopmentCardData } from "../development-card";
import {
  GEM_CODES,
  GEM_LABELS,
  actionKicker,
  actionTierIndex,
  gemEntries,
  resolveActionCardId,
  spokenActionSummary,
} from "../action-presentation.mjs";

/**
 * The one presentation of a recorded or recommended Splendor action.
 *
 * Three pages had three renderings of the same thing: Play's `HistoryText`, the
 * replay viewer's `simpleActionLabel` plus a raw JSON dump, and the review
 * table's `formatActionLabel`. That is why the review page could show "BUY" as a
 * coloured card and "S3 recommends" as the string "Buy T2 slot 3" for the very
 * same action. One component, used by all three, is the fix.
 *
 * Data boundary — the important part:
 *
 *   An action carries almost no identity. `buy_market` says only `tier` and
 *   `slot`; which card that is can only be resolved from the `player_view` that
 *   was in force *before the action was taken*. That is why `playerView` is a
 *   required prop and why it must be the pre-action view, not the post-action
 *   one. Resolving against the wrong view silently names the wrong card.
 *
 *   `reserve_deck` must never name the card. The action has no card id, and the
 *   only place the drawn identity could come from is `referee_reveal`. This
 *   component therefore does not accept a reveal at all, so there is no path by
 *   which a blind reserve can leak into an action label.
 */

export type StructuredActionData = { type: string; [key: string]: unknown };

export type ActionPlayerView = {
  viewer: number;
  public: {
    market: Array<Array<number | null>>;
    players: Array<{ id: number }>;
  };
  private: {
    reserved: Array<{ slot: number; card: number; tier: string; from_deck: boolean }>;
  };
};

// The pure resolver works on a structural subset of the view; the page types are
// richer, so the view is narrowed at this boundary rather than duplicated.
type ViewSubset = {
  public?: { market?: Array<Array<number | null>> };
  private?: { reserved?: Array<{ slot: number; card: number }> };
};

const asView = (view: ActionPlayerView | null | undefined): ViewSubset | null =>
  (view ?? null) as unknown as ViewSubset | null;

export type ActionCatalog = {
  cards: Map<number, DevelopmentCardData & { id: number }>;
  nobles: Map<number, { id: number; prestige: number; requirements: number[] }>;
};

/** A gem amount as a real coloured chip with a visible count and a text label. */
function GemFlow({ gems }: { gems: Array<{ key: string; count: number }> }) {
  return (
    <span className="action-gems">
      {gems.map((entry) => (
        <span
          className={`action-gem action-gem-${entry.key}`}
          key={entry.key}
          aria-label={`${entry.count} ${(GEM_LABELS as Record<string, string>)[entry.key] ?? entry.key}`}
        >
          <i aria-hidden="true">{(GEM_CODES as Record<string, string>)[entry.key] ?? entry.key}</i>
          <b aria-hidden="true">{entry.count}</b>
        </span>
      ))}
    </span>
  );
}

function CardFace({
  card,
  slotLabel,
}: {
  card: DevelopmentCardData & { id: number };
  slotLabel: string;
}) {
  return <DevelopmentCard card={card} variant="mini" slotLabel={slotLabel} />;
}

function UnknownCard({ id }: { id: number | null }) {
  return (
    <div className="development-card development-card-empty">
      <span>{id == null ? "—" : `#${id}`}</span>
    </div>
  );
}

export function StructuredAction({
  action,
  playerView = null,
  cardId = null,
  cards,
  nobles,
  variant = "detail",
}: {
  action: StructuredActionData;
  /**
   * The view in force *before* the action. Required to resolve card identity:
   * without it the renderer shows tier/slot and never guesses a card. A history
   * list that stores only `{ply, actor, action}` therefore degrades honestly
   * instead of naming the wrong card.
   */
  playerView?: ActionPlayerView | null;
  cardId?: number | null;
  cards: ActionCatalog["cards"];
  nobles: ActionCatalog["nobles"];
  variant?: "compact" | "detail";
}) {
  const take = gemEntries(action.take);
  const back = gemEntries(action.return);

  let body: React.ReactNode = null;
  const kicker = actionKicker(action);

  if (action.type === "take_tokens") {
    body = (
      <>
        <GemFlow gems={take} />
        {back.length ? (
          <>
            <span className="action-verb">RETURN</span>
            <GemFlow gems={back} />
          </>
        ) : null}
      </>
    );
  } else if (action.type === "buy_market" || action.type === "reserve_market") {
    const tier = actionTierIndex(action.tier);
    const slot = Number(action.slot);
    // Identity comes from explicit cardId, action.card_id, or pre-action view.
    const resolvedId = cardId ?? (action.card_id as number | undefined) ?? resolveActionCardId(action, asView(playerView));
    const id = resolvedId != null ? Number(resolvedId) : null;
    const card = id != null ? cards.get(id) ?? null : null;
    body = (
      <>
        {card ? <CardFace card={card} slotLabel={`Tier ${tier + 1} · slot ${slot + 1}`} /> : <UnknownCard id={id} />}
        <span className="action-meta">
          Tier {tier + 1} · slot {slot + 1}
        </span>
        {back.length ? (
          <>
            <span className="action-verb">RETURN</span>
            <GemFlow gems={back} />
          </>
        ) : null}
      </>
    );
  } else if (action.type === "buy_reserved") {
    const slot = Number(action.slot);
    // A reserved card is bought from the actor's own private reserve.
    const resolvedId = cardId ?? (action.card_id as number | undefined) ?? resolveActionCardId(action, playerView);
    const id = resolvedId != null ? Number(resolvedId) : null;
    const card = id != null ? cards.get(id) ?? null : null;
    body = (
      <>
        {card ? <CardFace card={card} slotLabel={`Reserve slot ${slot + 1}`} /> : <UnknownCard id={id} />}
        <span className="action-meta">Reserve slot {slot + 1}</span>
        {back.length ? (
          <>
            <span className="action-verb">RETURN</span>
            <GemFlow gems={back} />
          </>
        ) : null}
      </>
    );
  } else if (action.type === "reserve_deck") {
    // Blind reserve: the identity is not in the action and must not be inferred.
    const tier = actionTierIndex(action.tier);
    body = (
      <>
        <HiddenDevelopmentCard />
        <span className="action-meta">Tier {tier + 1} deck</span>
        {back.length ? (
          <>
            <span className="action-verb">RETURN</span>
            <GemFlow gems={back} />
          </>
        ) : null}
      </>
    );
  } else if (action.type === "choose_noble") {
    const id = Number(action.noble);
    const noble = nobles.get(id) ?? null;
    body = (
      <>
        <div className="action-noble" aria-label={noble ? `Noble ${id}, ${noble.prestige} prestige` : `Noble ${id}`}>
          <strong>{noble ? noble.prestige : "?"}</strong>
          <span>#{id}</span>
          <div className="mini-cost">
            {(noble?.requirements ?? []).map((amount, index) =>
              amount > 0 ? (
                <i className={`gem gem-${["white", "blue", "green", "red", "black"][index]}`} key={index}>
                  {amount}
                </i>
              ) : null,
            )}
          </div>
        </div>
        {noble ? <span className="action-meta">{noble.prestige} prestige</span> : null}
      </>
    );
  } else {
    body = <span className="action-meta">{spokenActionSummary(action)}</span>;
  }

  return (
    <div
      className={`structured-action structured-action-${variant}`}
      data-action-type={action.type}
      role="group"
      aria-label={spokenActionSummary(action)}
    >
      <span className="action-kicker">{kicker}</span>
      <div className="action-body">{body}</div>
    </div>
  );
}
