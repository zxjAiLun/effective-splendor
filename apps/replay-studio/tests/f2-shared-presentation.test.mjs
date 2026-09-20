// F2 gates: shared player state and shared structured actions.
//
// These assert the two presentation contracts F2 exists to create, plus the data
// boundary that a shared renderer could otherwise flatten:
//
//   * one player-state presentation across Play / Replay / Review,
//   * one action renderer for recorded *and* recommended actions,
//   * card identity resolved from the pre-action view, and
//   * `reserve_deck` never disclosing the drawn card.
//
// The pure module is imported directly; the component's DOM semantics are asserted
// by the browser gate (tests/review-seat-browser.mjs and friends). Run with `npm test`.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  actionKicker,
  actionMayDiscloseCard,
  actionTierIndex,
  gemEntries,
  resolveActionCardId,
  spokenActionSummary,
} from "../app/action-presentation.mjs";

const replayBoard = await readFile(new URL("../app/components/replay-board.tsx", import.meta.url), "utf8");
const playPage = await readFile(new URL("../app/play/page.tsx", import.meta.url), "utf8");
const replayPage = await readFile(new URL("../app/replay/page.tsx", import.meta.url), "utf8");
const reviewPage = await readFile(new URL("../app/review/page.tsx", import.meta.url), "utf8");
const playerStrip = await readFile(new URL("../app/components/player-state-strip.tsx", import.meta.url), "utf8");
const structuredAction = await readFile(new URL("../app/components/structured-action.tsx", import.meta.url), "utf8");

// A market where each slot holds a distinguishable card id, and an actor reserve.
const view = {
  viewer: 0,
  public: {
    market: [
      [101, 102, 103, 104],
      [201, 202, 203, 204],
      [301, 302, 303, 304],
    ],
  },
  private: {
    reserved: [
      { slot: 0, card: 401, tier: "One", from_deck: false },
      { slot: 1, card: 402, tier: "Two", from_deck: true },
    ],
  },
};

// ---- Gate 1: one player-state component, used by all three pages ---------------
test("F2 Gate 1: Play, Replay and Review all render the shared PlayerStateStrip", () => {
  for (const [name, source] of [["Play", playPage], ["Replay", replayPage], ["Review", reviewPage]]) {
    assert.match(source, /PlayerStateStrip/, `${name} must use the shared player-state component`);
    assert.match(source, /from "\.\.\/components\/player-state-strip"|from "\.\.\/app\/components\/player-state-strip"/, `${name} must import the shared strip`);
  }
  // The strip carries the whole compact state summary, so no page needs its own.
  for (const field of ["prestige", "tokens", "bonuses", "reserved_count", "purchased", "nobles"]) {
    assert.match(playerStrip, new RegExp(field), `the shared strip must present ${field}`);
  }
});

// ---- Gate 2: take_tokens uses real colours, counts, and a text label -----------
test("F2 Gate 2: take_tokens renders real colour and count with a non-colour label", () => {
  const action = { type: "take_tokens", take: { white: 1, blue: 2, green: 0, red: 1, black: 0, gold: 0 }, return: { black: 1 } };
  const entries = gemEntries(action.take);
  assert.deepEqual(entries, [
    { key: "white", count: 1 },
    { key: "blue", count: 2 },
    { key: "red", count: 1 },
  ]);
  assert.equal(actionKicker(action), "TAKE");
  // The spoken summary names every colour, so the action never depends on colour alone.
  const spoken = spokenActionSummary(action);
  assert.match(spoken, /take 1 Diamond, 2 Sapphire, 1 Ruby/);
  assert.match(spoken, /return 1 Onyx/);
  // The component renders both a coloured chip and its count.
  assert.match(structuredAction, /action-gem-\$\{entry\.key\}/);
  assert.match(structuredAction, /<b aria-hidden="true">\{entry\.count\}<\/b>/);
});

// ---- Gate 3: market and reserved identity come from the pre-action view --------
test("F2 Gate 3: card identity resolves from the pre-action market and private reserve", () => {
  assert.equal(resolveActionCardId({ type: "buy_market", tier: "Two", slot: 2 }, view), 203);
  assert.equal(resolveActionCardId({ type: "reserve_market", tier: "One", slot: 0 }, view), 101);
  assert.equal(resolveActionCardId({ type: "buy_reserved", slot: 1 }, view), 402);
  // A different view yields a different card: the resolution is genuinely view-bound.
  const otherView = { ...view, public: { market: [[901, 902, 903, 904], [201], [301]] } };
  assert.equal(resolveActionCardId({ type: "buy_market", tier: "One", slot: 0 }, otherView), 901);
  // No view means no identity, never a guess.
  assert.equal(resolveActionCardId({ type: "buy_market", tier: "One", slot: 0 }, null), null);
});

// ---- Gate 4: reserve_deck never names the drawn card ---------------------------
test("F2 Gate 4: reserve_deck never discloses a card identity", () => {
  const action = { type: "reserve_deck", tier: "Three" };
  // Even with a full view in scope — including the referee-reveal decks a Review
  // frame carries — the resolver returns nothing for a blind reserve.
  const withDecks = { ...view, referee_reveal: { decks: [[], [], [777]] } };
  assert.equal(resolveActionCardId(action, withDecks), null);
  assert.equal(actionMayDiscloseCard("reserve_deck"), false);
  assert.equal(actionKicker(action), "BLIND RESERVE");
  assert.equal(spokenActionSummary(action), "Blind reserve from tier 3 deck");
  // The renderer body for a blind reserve is a hidden card, not a resolved face.
  assert.match(structuredAction, /reserve_deck[\s\S]*?HiddenDevelopmentCard/);
});

// ---- Gate 5: Review actual and recommended share one renderer ------------------
test("F2 Gate 5: Review renders recorded and recommended actions with one component", () => {
  // Both sides go through StructuredAction in the shared ActionVerdict helper.
  assert.match(reviewPage, /function ActionVerdict\(/);
  const verdict = reviewPage.slice(reviewPage.indexOf("function ActionVerdict("));
  const body = verdict.slice(0, verdict.indexOf("function MetricBar("));
  assert.equal((body.match(/<StructuredAction/g) ?? []).length, 2, "both recorded and recommended use StructuredAction");
  assert.match(body, /frame\.recorded_action/);
  assert.match(body, /recommended/);
  // The previous text-only rendering must be gone from the verdict.
  assert.doesNotMatch(body, /formatActionLabel/);
});

// ---- Gate 6: choose_noble uses the catalog, not a bare id ----------------------
test("F2 Gate 6: choose_noble renders catalog prestige and requirements", () => {
  assert.equal(actionKicker({ type: "choose_noble", noble: 7 }), "WELCOME NOBLE");
  assert.match(structuredAction, /choose_noble[\s\S]*?noble\.prestige/);
  assert.match(structuredAction, /choose_noble[\s\S]*?noble\?\.requirements/);
});

// ---- Gate 7: Play reuses the renderer; its legal-action controls are untouched --
test("F2 Gate 7: Play reuses the shared action renderer and keeps its controls", () => {
  assert.match(playPage, /StructuredAction/, "Play history must use the shared renderer");
  assert.doesNotMatch(playPage, /function HistoryText\([\s\S]{0,600}?GemStrip gems=\{gemsOf\(action\.take\)\}/, "the bespoke history rendering must be gone");
  // The legal-action interaction surface is unchanged: these still drive play().
  for (const marker of ["changePendingGem", "openCard", "openDeck", "openReserved", "confirmTake", "void play("]) {
    assert.match(playPage, new RegExp(marker.replace(/[()]/g, "\\$&")), `Play's control ${marker} must survive F2`);
  }
});

// ---- Gate 8: the hidden-reserve boundary is not flattened ----------------------
test("F2 Gate 8: the hidden-reserve boundary survives in the shared board", () => {
  // ReservedCards keeps its three branches: reveal, own private view, opponent public only.
  assert.match(replayBoard, /referee_reveal\.players\.find/);
  assert.match(replayBoard, /frame\.player_view\.private\.reserved/);
  assert.match(replayBoard, /player\.public_reserved/);
  assert.match(replayBoard, /HiddenDevelopmentCard/, "opponents' blind reserves stay face-down");
  // The strip must not render reserve faces at all: it is a compact summary.
  assert.doesNotMatch(playerStrip, /ReservedCards|public_reserved\.map/);
});

// ---- Gate 9: no review job or cache behaviour changed --------------------------
test("F2 Gate 9: F2 does not change review job or cache behaviour", () => {
  assert.match(reviewPage, /fetch\(`\$\{API\}\/reviews`/, "the review POST is intact");
  assert.match(reviewPage, /\/bundle`/, "the bundle fetch is intact");
  // No cache key or reviewer-switching logic was introduced by F2.
  for (const forbidden of ["cache_key", "cacheKey", "job.cached =", "reviewCacheKey"]) {
    assert.equal(reviewPage.includes(forbidden), false, `F2 must not introduce ${forbidden}`);
  }
});

// ---- Gate 10: the Play reviewer link no longer carries a seat query ------------
test("F2 Gate 10: the Play reviewer link drops the seat query", () => {
  assert.match(playPage, /\/review\?session=\$\{encodeURIComponent\(state\.session_id\)\}&reviewer=/);
  assert.doesNotMatch(playPage, /&seat=\$\{state\.human_seat\}/, "the seat query must be gone");
});

// ---- Shared helpers sanity -----------------------------------------------------
test("F2 helper: tier indexing is canonical and total", () => {
  assert.equal(actionTierIndex("One"), 0);
  assert.equal(actionTierIndex("Two"), 1);
  assert.equal(actionTierIndex("Three"), 2);
  assert.equal(actionTierIndex("Nope"), -1);
  assert.equal(actionMayDiscloseCard("buy_market"), true);
  assert.equal(actionMayDiscloseCard("pass"), false);
});
