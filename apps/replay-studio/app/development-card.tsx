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

export function DevelopmentCard({
  card,
  interactive = false,
  affordable = false,
  disabled = false,
  onClick,
  slotLabel,
}: {
  card: DevelopmentCardData;
  interactive?: boolean;
  affordable?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  slotLabel?: string;
}) {
  const bonus = card.bonus.toLowerCase();
  const label = `${card.prestige} prestige, ${COLOR_NAMES[bonus] ?? card.bonus} bonus, card ${card.id}`;
  const body = <>
    <div className="development-card-top">
      <strong className="development-prestige">{card.prestige > 0 ? card.prestige : ""}</strong>
      <span className={`development-bonus development-bonus-${bonus}`} aria-label={`${card.bonus} permanent bonus`}><i /></span>
    </div>
    <div className="development-card-art" aria-hidden="true"><i /><i /><i /></div>
    <div className="development-card-cost" aria-label="Purchase cost">
      {card.cost.map((amount, index) => amount > 0 ? <span className={`gem gem-${COST_COLORS[index]}`} key={index}>{amount}</span> : null)}
    </div>
    <div className="development-card-meta"><span>#{card.id}</span><span>{slotLabel ?? card.tier}</span></div>
    {interactive ? <span className={`development-card-action ${affordable ? "buyable" : ""}`}>{affordable ? "BUY" : "MARKET"}</span> : null}
  </>;
  return interactive
    ? <button type="button" className={`development-card card-${bonus}`} style={{ minHeight: 176 }} disabled={disabled} onClick={onClick} aria-label={label}>{body}</button>
    : <div className={`development-card card-${bonus}`} style={{ minHeight: 176 }} aria-label={label}>{body}</div>;
}

export function EmptyDevelopmentCard() {
  return <div className="development-card development-card-empty" style={{ minHeight: 176 }}><span>EMPTY</span></div>;
}
