// M76 layout/interaction gate. Real installed Chromium + built UI, synthetic
// Host responses only. No research game, League write, reviewer job or download.
// npm run test:play-ui (or build first, then node tests/play-cockpit-browser.mjs)
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchStudioBrowser } from "./helpers/studio-browser.mjs";
import { mockPlayHostScript, playFixture } from "./fixtures/play-cockpit.mjs";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir = path.resolve(process.env.STUDIO_COCKPIT_ARTIFACTS || path.join(appRoot, "../../local-artifacts/m76-studio-play-cockpit", `browser-${Date.now()}`));
fs.mkdirSync(artifactDir, { recursive: true });
const sources = ["app/play/page.tsx", "app/play/play.css", "app/globals.css", "app/components/player-state-strip.tsx", "app/components/structured-action.tsx", "app/development-card.tsx", "tests/play-cockpit-browser.mjs", "tests/fixtures/play-cockpit.mjs", "tests/fixtures/rust-analysis-trace-v2-m07-two-seat.json", "tests/helpers/studio-browser.mjs"];
const sourceHashes = Object.fromEntries(sources.map(name => [name, crypto.createHash("sha256").update(fs.readFileSync(path.join(appRoot, name))).digest("hex")]));
const cases = [];
const screenshots = [];
const b = await launchStudioBrowser({ artifactDir });
let sequence = 0;

function inspectLayout() {
  const rect = element => element.getBoundingClientRect().toJSON();
  const shown = element => element.getClientRects().length > 0;
  const inside = (a, outer) => a.left >= outer.left - 1 && a.top >= outer.top - 1 && a.right <= outer.right + 1 && a.bottom <= outer.bottom + 1;
  const overlaps = (a, c) => Math.min(a.right, c.right) - Math.max(a.left, c.left) > .75 && Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top) > .75;
  const viewport = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
  const errors = [];
  const regions = Object.fromEntries(["human-opponent", "human-panels", "human-board", "human-actions", "human-dock", "hand-card", "human-bank", "take-panel"].map(name => {
    const element = document.querySelector(`.${name}`);
    return [name, { ...rect(element), shown: shown(element), scrollHeight: element.scrollHeight, clientHeight: element.clientHeight, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }];
  }));
  for (const name of ["human-opponent", "human-panels", "human-dock", "hand-card", "human-bank", "take-panel"]) {
    if (!inside(regions[name], viewport)) errors.push(`${name} leaves viewport`);
  }
  for (const selector of [".hand-line", ".state-line"]) {
    for (const line of document.querySelectorAll(selector)) {
      const parts = Array.from(line.querySelectorAll(":scope > small, :scope > .token-total, :scope > .state-bonus-total, :scope > .state-gems > .state-gem"));
      for (const part of parts) if (!inside(rect(part), rect(line))) errors.push(`${selector}: ${part.textContent} outside row`);
      for (let a = 0; a < parts.length; a++) for (let c = a + 1; c < parts.length; c++) {
        if (overlaps(rect(parts[a]), rect(parts[c]))) errors.push(`${selector}: ${parts[a].textContent} overlaps ${parts[c].textContent}`);
      }
    }
  }
  for (const gem of document.querySelectorAll(".hand-line .state-gem, .bank-gems .table-gem, .take-buttons button")) {
    if (!inside(rect(gem), viewport)) errors.push(`Pinned control outside viewport: ${gem.textContent}`);
  }
  const cards = [];
  for (const card of document.querySelectorAll(".development-card:not(.development-card-hidden):not(.development-card-empty)")) {
    if (!shown(card)) continue;
    const parts = Array.from(card.querySelectorAll(".development-prestige, .development-bonus, .development-card-cost > .gem, .development-card-meta > span, .development-card-action"))
      .filter(part => shown(part) && (part.textContent.trim() || part.classList.contains("development-bonus")));
    const errorsBefore = errors.length;
    for (const part of parts) if (!inside(rect(part), rect(card))) errors.push(`Card ${card.getAttribute("aria-label")}: ${part.textContent} outside card`);
    for (let a = 0; a < parts.length; a++) for (let c = a + 1; c < parts.length; c++) {
      if (overlaps(rect(parts[a]), rect(parts[c]))) errors.push(`Card ${card.getAttribute("aria-label")}: ${parts[a].textContent} overlaps ${parts[c].textContent}`);
    }
    for (const badge of card.querySelectorAll(".gem em")) if (!inside(rect(badge), rect(card))) errors.push("Printed discount badge outside card");
    cards.push({ label: card.getAttribute("aria-label"), rect: rect(card), errors: errors.length - errorsBefore });
  }
  for (const name of ["human-actions", "human-board"]) {
    const region = regions[name];
    if (region.shown && region.scrollWidth > region.clientWidth + 1) errors.push(`${name} has horizontal overflow`);
  }
  return {
    viewport, page: { height: document.documentElement.scrollHeight, width: document.documentElement.scrollWidth, scrollTop: scrollY },
    regions, cards, errors,
  };
}

const settle = () => b.evaluate("document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))");
const layout = () => b.evaluate(`(${inspectLayout.toString()})()`);
const snapshot = async name => { screenshots.push(await b.screenshot(`${name}.png`)); };
const record = (name, evidence) => { cases.push({ name, status: "PASS", ...evidence }); };
const checkLayout = async name => {
  await settle();
  const sample = await layout();
  assert.equal(sample.page.height, sample.viewport.bottom, `${name}: page must not scroll vertically`);
  assert.ok(sample.page.width <= sample.viewport.right, `${name}: page must not overflow horizontally`);
  assert.deepEqual(sample.errors, [], `${name}: ${sample.errors.join("; ")}`);
  return sample;
};
const navigate = async (scenario, width = 1366, height = 768, seat = 0, scale = 1) => {
  await b.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.navigate", { url: `${b.origin}/play?fixture=${scenario}&seat=${seat}&case=${++sequence}` });
  await b.wait(`document.querySelector('.hand-title')?.textContent.endsWith('P${seat}') && window.fixtureCalls?.some(call=>call.route==='/state')`);
  await b.evaluate(`document.documentElement.style.setProperty('--ui-scale', ${JSON.stringify(String(scale))})`);
  await settle();
};
// Physical pointer events, including hit testing. No element.click() shortcut can
// pass a control that is covered by the dock or clipped outside a scroll pane.
const click = async (selector, index = 0, scroll = false) => {
  const point = await b.evaluate(`(() => {
    const element = document.querySelectorAll(${JSON.stringify(selector)})[${index}];
    if (!element) throw new Error('Missing click target: ' + ${JSON.stringify(selector)});
    if (element.disabled) throw new Error('Disabled click target: ' + element.textContent);
    ${scroll ? "element.scrollIntoView({block:'nearest',inline:'nearest'});" : ""}
    const box = element.getBoundingClientRect();
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    if (!box.width || !box.height || !element.contains(document.elementFromPoint(x,y))) throw new Error('Click target occluded: ' + element.textContent);
    return {x,y};
  })()`);
  await b.send("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", clickCount: 1 });
  await b.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", clickCount: 1 });
  await settle();
};
const panel = async name => {
  const index = ["table", "move", "reserves", "history"].indexOf(name);
  await click(".human-panels button", index);
  await b.wait(`document.querySelector('.human-cockpit').dataset.panel===${JSON.stringify(name)}`);
};
const actionCalls = () => b.evaluate("window.fixtureCalls.filter(call=>call.route==='/action')");
const assertPosted = async action => {
  await b.wait("window.fixtureCalls.some(call=>call.route==='/action') && document.querySelector('.hand-turn')!==null");
  assert.deepEqual((await actionCalls()).map(call => JSON.parse(call.body)), [action]);
};

try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: mockPlayHostScript() });
  for (const [width, height, scale] of [[1440,900,1], [1366,768,1], [1280,720,1], [1101,720,1], [1100,720,1], [900,900,1], [700,844,1], [390,844,1], [320,720,1], [844,390,1], [1280,720,1.5]]) {
    const name = `table-${width}x${height}-scale${scale}`;
    await navigate("crowded", width, height, 1, scale);
    await snapshot(name);
    const sample = await checkLayout(name);
    assert.equal(sample.cards.length, 12, "All 12 market cards must exist");
    if (width >= 1280 && scale === 1) assert.ok(sample.regions["human-board"].scrollHeight <= sample.regions["human-board"].clientHeight + 1, "Common desktops fit all three market rows");
    const dockTop = sample.regions["human-dock"].top;
    await b.evaluate("window.scrollTo(0,99999);document.querySelector('.human-board').scrollTop=99999");
    const after = await checkLayout(`${name}-scrolled`);
    assert.equal(after.page.scrollTop, 0);
    assert.equal(after.regions["human-dock"].top, dockTop, "Board scrolling must not move resources");
    record(name, { geometry: sample, scrollKeepsDock: true });
  }

  for (const width of [1366, 390, 320]) {
    const height = width === 1366 ? 768 : width === 390 ? 844 : 720;
    await navigate("crowded", width, height, 1);
    await panel("reserves");
    assert.equal(await b.evaluate("document.querySelectorAll('.reserved-tray .development-card').length"), 3);
    assert.equal(await b.evaluate("document.querySelectorAll('.opponent-reserve .development-card:not(.development-card-hidden)').length"), 2);
    assert.equal(await b.evaluate("document.querySelectorAll('.opponent-reserve .development-card-hidden').length"), 1);
    assert.equal(await b.evaluate("document.querySelectorAll('.reserved-tray .gem em').length"), 0, "Reserves keep printed costs");
    assert.doesNotMatch(await b.evaluate("document.querySelector('.opponent-reserve .development-card-hidden').innerText"), /#\d/);
    await snapshot(`reserves-${width}`);
    record(`reserves-${width}`, { geometry: await checkLayout(`reserves-${width}`), hiddenBoundary: "two public faces + one hidden back" });
    await click(".reserved-tray button", 0, true);
    await b.wait("document.querySelector('.selected-card-preview')!==null");
    await snapshot(`selected-reserve-${width}`);
    record(`selected-reserve-${width}`, { geometry: await checkLayout(`selected-reserve-${width}`) });
    await click(".context-actions > button", 0, true);
    await assertPosted({ type: "buy_reserved", slot: 0 });

    await panel("history");
    assert.equal(await b.evaluate("document.querySelectorAll('.history-panel li').length"), 10);
    assert.match(await b.evaluate("document.querySelector('[data-action-type=reserve_deck]').innerText"), /Tier 3 deck/);
    assert.equal(await b.evaluate("document.querySelectorAll('[data-action-type=reserve_deck] .development-card:not(.development-card-hidden)').length"), 0);
    await snapshot(`history-${width}`);
    record(`history-${width}`, { geometry: await checkLayout(`history-${width}`) });
    const dockTop = (await layout()).regions["human-dock"].top;
    await b.evaluate("document.querySelector('.human-actions').scrollTop=99999");
    assert.equal((await checkLayout("history-scrolled")).regions["human-dock"].top, dockTop);
  }

  await navigate("initial", 390, 844, 0);
  assert.equal(await b.evaluate("document.querySelectorAll('.hand-line .state-gem-empty').length"), 6);
  assert.equal(await b.evaluate("document.querySelector('.hand-card .token-total').getAttribute('aria-label')"), "0 of 10 tokens held");
  await snapshot("initial-zero-tokens-mobile");
  await click(".bank-gems .table-gem-blue");
  assert.equal(await b.evaluate("document.querySelector('.take-buttons .confirm-move').disabled"), true);
  await click(".bank-gems .table-gem-blue");
  assert.equal((await actionCalls()).length, 0, "Selecting tokens must not send a move");
  await click(".pending-gems .table-gem-blue");
  assert.equal(await b.evaluate("document.querySelector('.take-buttons .confirm-move').disabled"), true);
  await click(".bank-gems .table-gem-blue");
  await snapshot("confirm-take-mobile");
  record("take-select-remove-confirm", { geometry: await checkLayout("take-selected") });
  await click(".take-buttons .confirm-move");
  await assertPosted(playFixture("initial").legal_actions.find(action => action.type === "take_tokens" && action.take.blue === 2));

  await navigate("crowded");
  await click(".human-tier .development-card", 0);
  await b.wait("document.querySelector('.selected-card-preview')!==null");
  await snapshot("selected-market-desktop");
  record("market-buy", { geometry: await checkLayout("selected-market") });
  await click(".context-actions > button", 0);
  await assertPosted({ type: "buy_market", tier: "Three", slot: 0 });
  await navigate("crowded");
  await click(".human-tier .development-card", 0);
  await click(".context-actions > button", 1);
  await assertPosted(playFixture("crowded").legal_actions.find(action => action.type === "reserve_market" && action.tier === "Three" && action.slot === 0));
  record("market-reserve", { originalPayload: true });
  await navigate("crowded");
  await click(".tier-deck", 0);
  await click(".context-actions > button", 0);
  await assertPosted(playFixture("crowded").legal_actions.find(action => action.type === "reserve_deck" && action.tier === "Three"));
  record("blind-reserve", { originalPayload: true });

  for (const width of [1280, 390, 320]) {
    await navigate("returns", width, width === 390 ? 844 : 720);
    const before = (await checkLayout("returns-before")).regions["human-dock"].height;
    for (const colour of ["white", "blue", "green"]) await click(`.bank-gems .table-gem-${colour}`);
    await click(".take-buttons .confirm-move");
    await b.wait("document.querySelector('.return-choices')!==null");
    const choices = playFixture("returns").legal_actions.filter(action => action.type === "take_tokens");
    assert.equal(await b.evaluate("document.querySelectorAll('.return-choices button').length"), choices.length);
    const sample = await checkLayout(`return-choices-${width}`);
    assert.ok(sample.regions["human-dock"].height <= before + 16, "Return count must not grow the dock");
    await snapshot(`return-choices-${width}`);
    await click(".return-choices button", choices.length - 1, true);
    await assertPosted(choices.at(-1));
    record(`return-choices-${width}`, { count: choices.length, geometry: sample, lastOptionClickable: true });
  }

  await navigate("crowded", 390, 844, 1);
  for (const colour of ["white", "blue", "green"]) await click(`.bank-gems .table-gem-${colour}`);
  assert.equal((await actionCalls()).length, 0);
  assert.equal(await b.evaluate("document.querySelector('.take-buttons .confirm-move').textContent"), "Choose returns", "Even a sole return must be shown before confirming it");
  await click(".take-buttons .confirm-move");
  assert.equal(await b.evaluate("document.querySelectorAll('.return-choices button').length"), 1);
  assert.equal(await b.evaluate("document.querySelector('.return-choices .history-gems').getAttribute('aria-label')"), "1 Diamond, 1 Emerald, 1 Onyx");
  await snapshot("single-return-mobile");
  const singleReturnLayout = await checkLayout("single-return");
  await click(".return-choices button", 0, true);
  await assertPosted(playFixture("crowded", 1).legal_actions.find(action => action.type === "take_tokens"));
  record("single-return-explicit", { geometry: singleReturnLayout, originalPayload: true });

  await navigate("crowded", 390, 844);
  await click(".bank-gems .table-gem-white");
  await click(".take-buttons .cancel-move");
  assert.equal((await actionCalls()).length, 0);
  assert.equal(await b.evaluate("document.querySelectorAll('.pending-gems .table-gem').length"), 0);
  record("cancel-take", { sendsNoAction: true });

  for (const scenario of ["noble", "pass"]) {
    await navigate(scenario, 390, 844, 1);
    assert.equal(await b.evaluate("document.querySelectorAll('.bank-gems button:not(:disabled)').length"), 0);
    await click(".take-buttons .confirm-move");
    if (scenario === "noble") { await snapshot("choose-noble-mobile"); await click(".context-actions > button", 0); }
    await assertPosted(playFixture(scenario, 1).legal_actions[0]);
    record(scenario, { originalPayload: true });
  }

  await navigate("crowded", 390, 844);
  await click(".human-tier .development-card", 0);
  await b.evaluate("window.fixtureActionMode='hold'");
  await click(".context-actions > button", 0, true);
  await b.wait("document.querySelector('.hand-wait')?.textContent==='THINKING…'");
  assert.equal(await b.evaluate("document.querySelectorAll('.context-actions button:not(:disabled), .bank-gems button:not(:disabled)').length"), 0);
  await b.evaluate("document.querySelector('.context-actions button').click()");
  assert.equal((await actionCalls()).length, 1, "Disabled button must not resend while pending");
  await snapshot("thinking-mobile");
  record("busy", { geometry: await checkLayout("busy"), oneActionOnly: true });
  await b.evaluate("window.completeFixtureMove()");
  await b.wait("document.querySelector('.hand-turn')!==null");

  await navigate("crowded", 320, 720);
  await click(".human-tier .development-card", 0);
  await b.evaluate("window.fixtureActionMode='lost'");
  await click(".context-actions > button", 0, true);
  await b.wait("document.querySelector('.error-banner')!==null");
  assert.match(await b.evaluate("document.querySelector('.hand-wait').textContent"), /CHECK SESSION/);
  assert.equal(await b.evaluate("document.querySelectorAll('.context-actions button:not(:disabled), .bank-gems button:not(:disabled)').length"), 0);
  await snapshot("unknown-response-mobile");
  record("unknown-response", { geometry: await checkLayout("unknown-response") });
  await click(".error-banner button", 0);
  await b.wait("document.querySelector('.error-banner')===null");
  assert.equal((await actionCalls()).length, 1, "Refresh reads the session without resending the action");
  record("session-recovery", { sameActionNotResent: true });

  for (const scenario of ["waiting", "overcap", "finished"]) {
    await navigate(scenario, 390, 844, 1);
    const sample = await checkLayout(scenario);
    if (scenario === "overcap") assert.equal(await b.evaluate("document.querySelector('.hand-card .token-total').getAttribute('aria-label')"), "12 of 10 tokens held");
    else assert.equal(await b.evaluate("document.querySelectorAll('.bank-gems button:not(:disabled)').length"), 0);
    if (scenario === "finished") assert.match(await b.evaluate("document.querySelector('.human-result').innerText"), /VICTORY/);
    await snapshot(`${scenario}-mobile`);
    record(scenario, { geometry: sample });
  }
  assert.deepEqual(b.exceptions, []);
  fs.writeFileSync(path.join(artifactDir, "checks.json"), JSON.stringify({ status: "PASS", observedAt: new Date().toISOString(), boundary: "Real Chromium + built UI, mocked Host. Zero research games. Pixel review is separate.", sourceHashes, cases, screenshots, exceptions: b.exceptions }, null, 2));
  console.log(`PASS ${cases.length} UI cases; ${screenshots.length} screenshots. Evidence: ${artifactDir}`);
} catch (error) {
  try { await snapshot("failure"); } catch { /* retain the first failure */ }
  fs.writeFileSync(path.join(artifactDir, "checks.json"), JSON.stringify({ status: "FAIL", observedAt: new Date().toISOString(), error: error.stack, sourceHashes, cases, screenshots, exceptions: b.exceptions }, null, 2));
  console.error(`FAIL; evidence: ${artifactDir}`);
  throw error;
} finally {
  await b.close();
}
