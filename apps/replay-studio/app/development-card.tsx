export type DevelopmentCardData = {
  id: number;
  tier: string;
  bonus: string;
  prestige: number;
  cost: number[];
};

const COST_COLORS = ["white", "blue", "green", "red", "black"];
const COLOR_NAMES: Record<string, string> = {
  white: "Diamond",
  blue: "Sapphire",
  green: "Emerald",
  red: "Ruby",
  black: "Onyx",
};

/**
 * Purchase cost, optionally resolved against a buyer's permanent card bonuses.
 *
 * Without `discount` the printed cost is shown unchanged, which is the only
 * correct rendering when no particular buyer is in context (an unowned market
 * card on the shared board). With `discount` each gem shows what is still
 * *owed* after the free bonus deduction, keeping the printed cost as a small
 * secondary badge so both numbers stay auditable. Gold substitution is a
 * per-turn payment choice rather than a property of the card, so it is
 * deliberately not folded in here.
 */
function CostGems({ cost, discount }: { cost: number[]; discount?: number[] }) {
  return <>
    {cost.map((amount, index) => {
      if (amount <= 0) return null;
      const color = COST_COLORS[index];
      const name = COLOR_NAMES[color] ?? color;
      const bonus = discount?.[index] ?? 0;
      if (!discount || bonus <= 0) {
        return <span className={`gem gem-${color}`} key={index} aria-label={`${amount} ${name}`}>{amount}</span>;
      }
      const owed = Math.max(0, amount - bonus);
      const state = owed === 0 ? "covered" : "discounted";
      return (
        <span
          className={`gem gem-${color} ${state}`}
          key={index}
          aria-label={`${name}: ${owed} still owed of ${amount}, ${Math.min(bonus, amount)} covered by card bonuses`}
        >
          {owed}
          <em aria-hidden="true">{amount}</em>
        </span>
      );
    })}
  </>;
}

export function DevelopmentCard({
  card,
  interactive = false,
  affordable = false,
  disabled = false,
  onClick,
  slotLabel,
  discount,
  variant,
}: {
  card: DevelopmentCardData;
  interactive?: boolean;
  affordable?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  slotLabel?: string;
  /** Buyer's permanent bonuses per cost colour; enables net-cost rendering. */
  discount?: number[];
  /** `mini` is the compact face used inside reserve strips. */
  variant?: "mini";
}) {
  const bonus = card.bonus.toLowerCase();
  const label = `${card.prestige} prestige, ${COLOR_NAMES[bonus] ?? card.bonus} bonus, card ${card.id}`;
  const className = `development-card card-${bonus}${variant === "mini" ? " development-card-mini" : ""}`;
  const body = <>
    <div className="development-card-top">
      <strong className="development-prestige">{card.prestige > 0 ? card.prestige : ""}</strong>
      <span className={`development-bonus development-bonus-${bonus}`} aria-label={`${card.bonus} permanent bonus`}><i /></span>
    </div>
    <div className="development-card-art" aria-hidden="true"><i /><i /><i /></div>
    <div className="development-card-cost" aria-label={discount ? "Purchase cost after card bonuses" : "Purchase cost"}>
      <CostGems cost={card.cost} discount={discount} />
    </div>
    <div className="development-card-meta"><span>#{card.id}</span><span>{slotLabel ?? card.tier}</span></div>
    {interactive ? <span className={`development-card-action ${affordable ? "buyable" : ""}`}>{affordable ? "BUY" : "MARKET"}</span> : null}
  </>;
  return interactive
    ? <button type="button" className={className} disabled={disabled} onClick={onClick} aria-label={label}>{body}</button>
    : <div className={className} aria-label={label}>{body}</div>;
}

export function EmptyDevelopmentCard() {
  return <div className="development-card development-card-empty"><span>EMPTY</span></div>;
}

/**
 * Face-down stand-in for a card whose identity the viewer is not entitled to:
 * an opponent's blind reserve taken from the top of a deck.
 */
export function HiddenDevelopmentCard({ count }: { count?: number }) {
  return (
    <div className="development-card development-card-hidden" aria-label={count && count > 1 ? `${count} hidden reserved cards` : "Hidden reserved card"}>
      <span>HIDDEN</span>
      {count && count > 1 ? <b>×{count}</b> : null}
      <small>BLIND RESERVE</small>
    </div>
  );
}
