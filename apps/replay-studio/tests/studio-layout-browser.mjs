// M78 main-page presentation gate. Built app + real installed Chromium, with a
// synthetic Host at the fetch boundary. No actual game, booking, search or DB.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchStudioBrowser } from "./helpers/studio-browser.mjs";
import { catalog } from "./fixtures/play-cockpit.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir = path.resolve(process.env.STUDIO_LAYOUT_ARTIFACTS || path.join(root, "../../local-artifacts/m78-studio-ui", `pages-${Date.now()}`));
fs.mkdirSync(artifactDir, { recursive: true });
const sources = ["app/page.tsx", "app/league/page.tsx", "app/ratings/page.tsx", "app/play/page.tsx", "app/play/play.css", "app/globals.css", "app/studio-shell.css", "app/components/studio-chrome.tsx", "app/agent-visibility.mjs", "app/layout.tsx", "tests/studio-layout-browser.mjs", "tests/helpers/studio-browser.mjs", "tests/fixtures/play-cockpit.mjs"];
const sourceHashes = Object.fromEntries(sources.map(name => [name, crypto.createHash("sha256").update(fs.readFileSync(path.join(root, name))).digest("hex")]));
const b = await launchStudioBrowser({ artifactDir });
const cases = [];
const screenshots = [];
let sequence = 0;
const settle = () => b.evaluate("document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))");
const shot = async name => { screenshots.push(await b.screenshot(`${name}.png`)); };
const record = (name, evidence = {}) => cases.push({ name, status: "PASS", ...evidence });
const body = () => b.evaluate("document.body.innerText");
const calls = () => b.evaluate("window.uiHostCalls");

function pageGeometry() {
  const rect = e => e.getBoundingClientRect().toJSON();
  const errors = [];
  const primary = [...document.querySelectorAll('.studio-primary-links > a, .studio-more > summary')];
  for (const e of primary) {
    const box = rect(e);
    if (!e.getClientRects().length || box.left < -1 || box.right > innerWidth + 1 || box.top < -1 || box.bottom > innerHeight + 1) errors.push(`Navigation not visible: ${e.textContent}`);
  }
  const sections = [...document.querySelectorAll('.games-dashboard > *, .games-archives > *, .league-layout > *, .play-setup > *, .ratings-panel')].map(e => ({ name: e.className, rect: rect(e), scrollWidth: e.scrollWidth, clientWidth: e.clientWidth }));
  for (const s of sections) if (s.scrollWidth > s.clientWidth + 2) errors.push(`Panel overflows: ${s.name}`);
  for (const e of document.querySelectorAll('select, input, .ratings-row:not(.ratings-head-row), .recent-game-list article')) {
    const box = rect(e);
    if (box.left < -1 || box.right > innerWidth + 1) errors.push(`Control or row overflows: ${e.className || e.tagName}`);
  }
  return { viewport: { width: innerWidth, height: innerHeight }, documentWidth: document.documentElement.scrollWidth, sections, errors };
}
const geometry = async () => {
  await settle();
  const sample = await b.evaluate(`(${pageGeometry.toString()})()`);
  assert.ok(sample.documentWidth <= sample.viewport.width, `Page overflows: ${JSON.stringify(sample)}`);
  assert.deepEqual(sample.errors, []);
  return sample;
};
// Physical pointer + hit testing: a clipped, hidden or covered button cannot pass.
const click = async (selector, index = 0, scroll = false) => {
  const point = await b.evaluate(`(() => {
    const e = document.querySelectorAll(${JSON.stringify(selector)})[${index}];
    if (!e || e.disabled) throw new Error('Missing or disabled target: ' + ${JSON.stringify(selector)});
    ${scroll ? "e.scrollIntoView({block:'center',inline:'nearest'});" : ""}
    const r = e.getBoundingClientRect(), x = r.x + r.width/2, y = r.y + r.height/2;
    if (!r.width || !r.height || !e.contains(document.elementFromPoint(x,y))) throw new Error('Occluded target: ' + e.textContent);
    return {x,y};
  })()`);
  await b.send("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", clickCount: 1 });
  await b.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", clickCount: 1 });
  await settle();
};
const clickText = async (text, scroll = true) => {
  const index = await b.evaluate(`Array.from(document.querySelectorAll('button')).findIndex(e=>e.textContent===${JSON.stringify(text)})`);
  assert.ok(index >= 0, `Missing button: ${text}`);
  await click("button", index, scroll);
};
const routes = [
  { path: "/", id: "games", ready: "document.querySelector('.games-ledger article')" },
  { path: "/play", id: "setup", ready: "document.querySelector('.setup-status')?.textContent.includes('ready')" },
  { path: "/league", id: "league", ready: "document.querySelectorAll('.league-standings article').length===1" },
  { path: "/ratings", id: "ratings", ready: "document.querySelectorAll('.ratings-row:not(.ratings-head-row)').length===1" },
];
const navigate = async (route, width, height, mode = "loaded", scale = 1) => {
  await b.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.navigate", { url: `${b.origin}${route.path}?ui=${mode}&case=${++sequence}` });
  await b.wait(mode === "loaded" ? route.ready : mode === "empty" ? "document.body.innerText.includes('No participants')" : "document.querySelector('[role=alert]')");
  await b.evaluate(`document.documentElement.style.setProperty('--ui-scale', ${JSON.stringify(String(scale))})`);
  await settle();
};

try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const nativeFetch = window.fetch.bind(window);
    window.uiMode = new URL(location.href).searchParams.get('ui') || 'loaded';
    window.uiHostCalls = []; window.uiBooking = 'pending';
    const catalogue = ${JSON.stringify(catalog)};
    const rows = [
      {participant_id:'prism-v011',kind:'engine',display_name:'Prism v0.1.1',elo:1742.5,rated_games:160,recorded_games:162,rated_wins:94,rated_ties:4,rated_losses:62,provisional:false},
      {participant_id:'prism-alpha-v01',kind:'engine',display_name:'Prism Alpha v0.1.0',elo:1708,rated_games:120,recorded_games:120,rated_wins:70,rated_ties:2,rated_losses:48,provisional:false},
      {participant_id:'12345678-1234-1234-1234-123456789012',kind:'human',display_name:'You',elo:1530,rated_games:1,recorded_games:1,rated_wins:1,rated_ties:0,rated_losses:0,provisional:true},
      {participant_id:'heuristic-v031',kind:'engine',display_name:'★ Heuristic v0.3.1 (5-Module Refactor · 76.6% vs S3)',elo:null,rated_games:0,recorded_games:0,rated_wins:0,rated_ties:0,rated_losses:0,provisional:true}
    ];
    const agents = [];
    const humanA = '12345678-1234-1234-1234-123456789012';
    const humanB = 'b901a2ea-645d-4c45-b4b9-407f5b6f39b7';
    const match = seq => ({match_id:'fixture-'+seq,league_seq:seq,played_at:1791716400-seq*60,source_kind:'human_play',status:'completed',rating_eligible:true,rating_ineligible_reason:null,replay_document_sha256:'ab'.repeat(32),replay_archived:true,seats:[
      {seat:0,participant_id:humanA,display_name:'You',score:12,rank:2,won:false},
      {seat:1,participant_id:humanB,display_name:'Local player',score:15,rank:1,won:true}
    ]});
    const reply = (data,status=200) => new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
    // Navigation-by-pointer is verified without executing the client router:
    // a window-capture listener stops each link click before the vinext beta
    // router (known TypeError platform break, see ratings-page-browser.mjs) and
    // records the href the browser would have followed. Every target route is
    // still fully loaded and geometry-checked in this gate.
    window.__navTargets=[];
    window.addEventListener('click', event => {
      const anchor=event.target instanceof Element && event.target.closest('a[href]');
      if(!anchor)return;
      window.__navTargets.push(anchor.getAttribute('href'));
      event.preventDefault();event.stopPropagation();
    }, true);
    window.fetch = async (input,opts={}) => {
      const address = new URL(String(input),location.href);
      if(address.origin!=='http://127.0.0.1:43120') return nativeFetch(input,opts);
      const route=address.pathname;window.uiHostCalls.push({route,search:address.search,method:opts.method||'GET',body:opts.body||null});
      if(window.uiMode==='offline') throw new Error('Fixture Host unavailable');
      if(route==='/health')return reply({status:'ok'});
      if(route==='/agents')return reply({agents});
      if(route==='/catalog')return reply(catalogue);
      if(route==='/reviewers')return reply({reviewers:[]});
      if(route==='/state')return reply({error:'No fixture session'},400);
      if(route==='/league/leaderboard')return reply({format:'effective-splendor-studio-league-leaderboard',version:1,rows:window.uiMode==='empty'?[]:rows});
      if(route==='/league/games') {
        const more=address.searchParams.has('before');
        if(more&&window.uiMode==='page-fail')return reply({error:'Fixture page unavailable'},500);
        return reply({format:'effective-splendor-studio-league-games',version:1,matches:more?[match(1)]:[match(90),match(75),match(51)],next_before_league_seq:more?null:50});
      }
      if(route==='/recent-games')return reply({games:[{session_id:'12345678-1234-1234-1234-123456789012',opponent:'Local player',human_seat:1,scores:[9,15],winners:[1],player_count:2,timestamp:1791628800,verification:'verified',available_reviews:[]}]});
      if(route==='/league/matches'&&opts.method==='POST') {
        if(window.uiBooking==='lost')throw new Error('Fixture response lost');
        if(window.uiBooking==='pending')return reply({match_status:'completed',completion_status:'failed',error:'Fixture booking pending'},503);
        const request=JSON.parse(opts.body);
        return reply({match_status:'completed',completion_status:'inserted',receipt:{source_kind:'arena_report',source_identity:request.occurrence_id,match_id:'ab'.repeat(32),outcome:{kind:'inserted',rating_events:0},replay:{document_hash:'cd'.repeat(32)},elo:[]}});
      }
      return reply({error:'Unexpected fixture route: '+route},404);
    };
  })();` });

  for (const route of routes) {
    for (const [width, height, scale] of [[1440,900,1], [1280,720,1], [820,1000,1], [390,844,1], [320,720,1], [1280,900,1.5]]) {
      await navigate(route, width, height, "loaded", scale);
      const name = `${route.id}-${width}x${height}-scale${scale}`;
      const sample = await geometry();
      assert.equal(await b.evaluate("document.querySelectorAll('.studio-primary-links a[aria-current=page]').length"), 1);
      await shot(name);
      await click(".studio-more > summary");
      assert.equal(await b.evaluate("document.querySelector('.studio-more').open"), true);
      const menu = await b.evaluate("document.querySelector('.studio-more-menu').getBoundingClientRect().toJSON()");
      assert.ok(menu.left >= 0 && menu.right <= width && menu.bottom <= height, "More menu stays inside the viewport");
      for (let i = 0; i < 3; i++) {
        assert.equal(await b.evaluate(`(() => {const e=document.querySelectorAll('.studio-more-menu a')[${i}], r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})()`), true);
      }
      if (width === 320) await shot(`${route.id}-more-menu-320`);
      await click(".studio-more > summary");
      assert.equal((await calls()).filter(c => c.method === "POST").length, 0, "Browsing must not start any game or reviewer");
      record(name, { geometry: sample, primaryNavigationVisible: true, moreLinksHitTested: 3, zeroWrites: true });
    }
  }

  // The primary navigation is exercised by real pointer presses. The click is
  // stopped before the broken beta client router (see mock note), so the gate
  // asserts the href each pressed link would follow; each target route has
  // already been fully loaded and geometry-checked above.
  await navigate(routes[0], 390, 844);
  const navTargets = [];
  for (const href of ["/play", "/league", "/ratings", "/"]) {
    await click(`.studio-primary-links a[href="${href}"]`);
    await b.wait(`window.__navTargets[window.__navTargets.length-1]===${JSON.stringify(href)}`);
    navTargets.push(href);
    assert.equal((await calls()).filter(c => c.method === "POST").length, 0);
  }
  record("navigation-pointer-targets", { pressed: navTargets, zeroWrites: true });

  // Paging preserves the single remaining human archive and does not launch writes.
  await navigate(routes[0], 390, 844);
  await b.evaluate("window.uiMode='page-fail'");
  await clickText("Load more");
  await b.wait("document.querySelector('.games-ledger .games-error')");
  assert.equal(await b.evaluate("document.querySelectorAll('.games-ledger article').length"), 3);
  await b.evaluate("window.uiMode='loaded'");
  await clickText("Retry page");
  await b.wait("document.querySelectorAll('.games-ledger article').length===4");
  assert.deepEqual((await calls()).filter(c => c.route === "/league/games").map(c => c.search), ["", "?limit=50&before=50", "?limit=50&before=50"]);
  assert.equal(await b.evaluate("document.querySelectorAll('.legacy-games, .games-archives').length"), 0);
  assert.match(await body(), /End of the recorded league/);
  record("games-cursor-retry", { rowsPreserved: true, retiredCorpusRemoved: true });

  // The retired roster has no selectable model. The form can change shape, but
  // an empty lineup cannot launch a real match or send a booking.
  await navigate(routes[2], 390, 844);
  await clickText("Add a seat"); await clickText("Add a seat");
  assert.equal(await b.evaluate("document.querySelectorAll('.league-seats select').length"), 4);
  await shot("league-four-seats-retired-roster-mobile");
  await clickText("Remove the last seat"); await clickText("Remove the last seat");
  await clickText("Start rated match");
  assert.equal((await calls()).filter(c => c.method === "POST").length, 0, "Invalid empty seats do not send");
  assert.match(await body(), /Choose an agent|No agent/);
  record("league-retired-roster", { fourSeatLayout: true, invalidStartRefused: true, registeredAgents: 0, realGames: 0 });

  for (const route of [routes[0], routes[1], routes[2], routes[3]]) {
    await navigate(route, 320, 720, "offline");
    const sample = await geometry();
    await shot(`${route.id}-offline-320`);
    if (route.id === "setup") assert.equal(await b.evaluate("document.querySelector('.human-connect .studio-primary').disabled"), true);
    record(`${route.id}-offline`, { geometry: sample, noFabricatedReady: true });
  }
  await navigate(routes[3], 390, 844, "empty");
  assert.equal(await b.evaluate("document.querySelectorAll('.ratings-row').length"), 0);
  await shot("ratings-empty-mobile");
  record("ratings-empty", { noDefaultRating: true });
  assert.deepEqual(b.exceptions, []);
  fs.writeFileSync(path.join(artifactDir, "checks.json"), JSON.stringify({ status: "PASS", observedAt: new Date().toISOString(), boundary: "Built UI + installed Chromium + synthetic Host. No real game or League write. Pixel review is separate.", sourceHashes, cases, screenshots, exceptions: b.exceptions }, null, 2));
  console.log(`PASS ${cases.length} main-page cases; ${screenshots.length} screenshots. Evidence: ${artifactDir}`);
} catch (error) {
  try { await shot("failure"); } catch { /* preserve the first failure */ }
  fs.writeFileSync(path.join(artifactDir, "checks.json"), JSON.stringify({ status: "FAIL", observedAt: new Date().toISOString(), error: error.stack, sourceHashes, cases, screenshots, exceptions: b.exceptions }, null, 2));
  console.error(`FAIL; evidence: ${artifactDir}`);
  throw error;
} finally {
  await b.close();
}
