/**
 * Pure action-presentation logic for the shared StructuredAction renderer.
 *
 * Plain JavaScript on purpose: the gates import this module directly under
 * `node --test`, exactly like `trace-runtime.mjs`, so the two rules that matter can
 * be asserted without a browser:
 *
 *   1. card identity is resolved from the view in force *before* the action, and
 *   2. `reserve_deck` never names a card, no matter what else is in scope.
 *
 * These rules were previously re-implemented per page, which is how one page came
 * to show a card face and another the string "Buy T2 slot 3" for the same action.
 */

export const ACTION_TIERS = ["One", "Two", "Three"];

const GEM_KEYS = ["white", "blue", "green", "red", "black", "gold"];

export const GEM_LABELS = {
  white: "Diamond",
  blue: "Sapphire",
  green: "Emerald",
  red: "Ruby",
  black: "Onyx",
  gold: "Gold",
};

export const GEM_CODES = {
  white: "W",
  blue: "U",
  green: "G",
  red: "R",
  black: "K",
  gold: "★",
};

export function actionTierIndex(tier) {
  const index = ACTION_TIERS.indexOf(String(tier));
  return index >= 0 ? index : -1;
}

/** Non-empty gem entries in canonical colour order. */
export function gemEntries(value) {
  if (!value || typeof value !== "object") return [];
  return GEM_KEYS.map((key) => ({ key, count: Number(value[key] ?? 0) })).filter(
    (entry) => Number.isFinite(entry.count) && entry.count > 0,
  );
}

/**
 * Resolve the card an action refers to, from the pre-action view.
 *
 * Returns `null` when the identity is genuinely unavailable (no view, an empty
 * market slot, or `reserve_deck`/`pass`, which carry no identity). `null` means
 * "show tier/slot", never "invent a card".
 */
export function resolveActionCardId(action, view) {
  if (!action || !actionMayDiscloseCard(action.type)) return null;
  if (action.card_id != null && Number.isInteger(Number(action.card_id))) {
    return Number(action.card_id);
  }
  if (!view) return null;
  if (action.type === "buy_market" || action.type === "reserve_market") {
    const tier = actionTierIndex(action.tier);
    const slot = Number(action.slot);
    if (tier < 0 || !Number.isInteger(slot)) return null;
    return view.public?.market?.[tier]?.[slot] ?? null;
  }
  if (action.type === "buy_reserved") {
    const slot = Number(action.slot);
    if (!Number.isInteger(slot)) return null;
    return view.private?.reserved?.find((item) => item.slot === slot)?.card ?? null;
  }
  return null;
}

/**
 * Whether an action type may ever disclose a card identity.
 *
 * `reserve_deck` takes from the top of a deck: the drawn card is not in the
 * action, not in the actor's reserve, and not in the market. Its identity exists
 * only in `referee_reveal`, which the renderer is never given. This predicate
 * exists so the fact is asserted directly instead of inferred from a code path.
 */
export function actionMayDiscloseCard(type) {
  return type === "buy_market" || type === "reserve_market" || type === "buy_reserved";
}

/** A spoken summary of the action, used as its accessible name. */
export function spokenActionSummary(action) {
  const describe = (entries) =>
    entries.map((entry) => `${entry.count} ${GEM_LABELS[entry.key] ?? entry.key}`).join(", ");
  const take = gemEntries(action.take);
  const back = gemEntries(action.return);
  switch (action.type) {
    case "take_tokens": {
      const taken = take.length ? `take ${describe(take)}` : "take tokens";
      return back.length ? `${taken}, return ${describe(back)}` : taken;
    }
    case "buy_market":
      return `Buy from tier ${actionTierIndex(action.tier) + 1} slot ${Number(action.slot) + 1}`;
    case "buy_reserved":
      return `Buy reserved card from slot ${Number(action.slot) + 1}`;
    case "reserve_market":
      return `Reserve from tier ${actionTierIndex(action.tier) + 1} slot ${Number(action.slot) + 1}`;
    case "reserve_deck":
      return `Blind reserve from tier ${actionTierIndex(action.tier) + 1} deck`;
    case "choose_noble":
      return `Welcome noble ${Number(action.noble)}`;
    case "pass":
      return "Pass";
    default:
      return action.type.replaceAll("_", " ");
  }
}

/** The kicker shown above an action's body. */
export function actionKicker(action) {
  if (action.type === "take_tokens") return "TAKE";
  if (action.type === "buy_market") return "BUY";
  if (action.type === "reserve_market") return "RESERVE";
  if (action.type === "buy_reserved") return "BUY RESERVED";
  if (action.type === "reserve_deck") return "BLIND RESERVE";
  if (action.type === "choose_noble") return "WELCOME NOBLE";
  return action.type.replaceAll("_", " ").toUpperCase();
}
