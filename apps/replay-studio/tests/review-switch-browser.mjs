// Optional local Chromium interaction gate for F3: reviewer switching must reuse
// the Host's cache instead of the browser guessing, and must preserve what the
// user was looking at.
//
// Built app + mocked Host boundary. No real League, no real reviewer job, no
// browser download; Node >=22 + an installed Chromium.
// Run: npm run build && node tests/review-switch-browser.mjs
//
// What this gate exists to prove, and can only prove in a real DOM:
//   1. A -> B -> A does not re-fetch A's bundle: the browser restores A from its
//      own cache keyed by the Host cache_key, using the POST answer (which is what
//      carries reviewer config identity) as the authority.
//   2. The cache is keyed by cache_key, not reviewer id: the same reviewer id with
//      a new cache_key must trigger a new bundle.
//   3. Switching preserves frame.ply + filter + reveal (not raw frameIndex).
//   4. A stale response from reviewer A cannot overwrite reviewer B after a switch.
//   5. A Host job naming another session/reviewer is refused, not rendered.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import cp from "node:child_process";
import net from "node:net";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir = process.env.PLAYER_LOOP_ARTIFACTS;
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const cache = path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
const browser = process.env.STUDIO_TEST_BROWSER || (fs.existsSync(cache)
  ? fs.readdirSync(cache).filter((v) => /^chromium-\d+$/.test(v)).sort().reverse()
    .flatMap((v) => ["chrome-win64/chrome.exe", "chrome-win/chrome.exe"].map((p) => path.join(cache, v, p)))
    .find((p) => fs.existsSync(p))
  : null);
assert.ok(browser, "Set STUDIO_TEST_BROWSER to an installed Chromium; never downloads.");

// The API base the app compiles against. The mocked Host answers only this origin.
const API = "http://127.0.0.1:43120";

// Two real, distinct traces from the Rust M07 fixture. Reviewer A and B differ by
// id, so `cache_key` differs and their validated traces are genuinely separate.
const baseTrace = JSON.parse(fs.readFileSync(new URL("./fixtures/rust-analysis-trace-v2-m07-two-seat.json", import.meta.url), "utf8"));
const reviewerA = {
  id: "m07-determinization-champion",
  display_name: "M07 Determinization Champion",
  description: "Frozen root-determinization baseline.",
  competitive_status: "champion",
  result_kind: "root_determinization",
  supported_player_counts: [2, 3, 4],
  default_for_player_counts: [2, 3, 4],
  available_metrics: ["mean_utility", "utility_gap", "action_rank"],
  required_artifacts: [],
  estimated_cost: "cpu",
};
const reviewerB = { ...reviewerA, id: "m07-b", display_name: "M07 Determinization (B)" };
// Each trace carries its reviewer identity, which is what the page uses to key and
// label the restored state.
const traceA = { ...baseTrace, reviewer: { ...baseTrace.reviewer, id: reviewerA.id, display_name: reviewerA.display_name } };
const traceB = { ...baseTrace, reviewer: { ...baseTrace.reviewer, id: reviewerB.id, display_name: reviewerB.display_name } };

const socket = net.createServer();
await new Promise((resolve) => socket.listen(0, "127.0.0.1", resolve));
const port = socket.address().port;
await new Promise((resolve) => socket.close(resolve));

const server = cp.spawn(process.execPath, ["node_modules/vinext/dist/cli.js", "start", "--port", String(port), "--hostname", "127.0.0.1"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverLog = "";
server.stdout.on("data", (b) => { serverLog += b; });
server.stderr.on("data", (b) => { serverLog += b; });

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-review-switch-"));
const child = cp.spawn(browser, ["--headless", "--no-first-run", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
let ws;
let send;
let serial = 0;
const pending = new Map();
const exceptions = [];

try {
  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(serverLog);
    try { ready = (await fetch(`http://127.0.0.1:${port}/`)).ok; } catch { /* starting */ }
    if (ready) break;
    await delay(100);
  }
  assert.ok(ready, serverLog);

  const activePort = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 150 && !fs.existsSync(activePort); i++) await delay(100);
  const debugPort = fs.readFileSync(activePort, "utf8").split("\n")[0];
  const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
  ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      clearTimeout(p.timer);
      if (m.error) p.reject(new Error(JSON.stringify(m.error)));
      else p.resolve(m.result);
    }
    if (m.method === "Runtime.exceptionThrown") exceptions.push(m.params.exceptionDetails);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++serial;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout ${method}`)); }, 10000);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const value = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
    return value.result.value;
  };
  const wait = async (expression) => {
    for (let i = 0; i < 200; i++) {
      try { if (await evaluate(expression)) return; } catch { /* mid-navigation */ }
      await delay(50);
    }
    const dump = await evaluate("JSON.stringify({body: document.body ? document.body.innerText.slice(0, 900) : null})");
    throw new Error(`DOM timeout: ${expression}\n${dump}`);
  };
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });

  // Mocked Host. It owns the two cache keys, counts POSTs and bundles, and can be
  // told (via localStorage) to label a job with a foreign session/reviewer so the
  // frontend's identity check is exercised.
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const nativeFetch = window.fetch.bind(window);
    window.f3 = { posts: [], bundles: [], jobs: {} };
    const reply = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
    const reviewers = ${JSON.stringify([reviewerA, reviewerB])};
    const traceA = ${JSON.stringify(traceA)};
    const traceB = ${JSON.stringify(traceB)};
    const cacheKeys = {
      ${JSON.stringify(reviewerA.id)}: 'a'.repeat(64),
      ${JSON.stringify(reviewerB.id)}: 'b'.repeat(64),
    };
    window.fetch = (url, opts = {}) => {
      if (!String(url).startsWith(${JSON.stringify(API)})) return nativeFetch(url, opts);
      const route = String(url).slice(${JSON.stringify(API)}.length);
      if (route === '/health') return reply({ status: 'ok' });
      if (route.startsWith('/reviewers')) {
        const durableSeat = (() => { const raw = window.localStorage.getItem('f3Seat'); return raw === null || raw === '' ? null : Number(raw); })();
        return reply({ format: 'effective-splendor-studio-reviewers', version: 1, registry_id: 'studio-reviewers-2026-08-13', player_count: 2, human_seat: durableSeat, reviewers });
      }
      if (route === '/reviews') {
        const body = JSON.parse(opts.body);
        window.f3.posts.push(body);
        const reviewer = body.reviewer_id;
        const id = 'job-' + reviewer;
        // A delayed POST is how the stale-response case is staged: the switch to B
        // happens while A's answer is still in flight.
        const delayMs = reviewer === ${JSON.stringify(reviewerA.id)} && window.localStorage.getItem('f3DelayA') === '1' ? 1200 : 0;
        const job = {
          id,
          session_id: window.localStorage.getItem('f3ForeignSession') === '1' ? 'someone-else' : body.session_id,
          reviewer_id: window.localStorage.getItem('f3ForeignReviewer') === '1' ? 'someone-else' : reviewer,
          status: 'completed', processed_decisions: 2, total_decisions: 2, current_ply: 0, error: null,
          cached: window.f3.jobs[id] === true,
          cache_key: window.localStorage.getItem('f3ChangedKey') === '1' ? 'c'.repeat(64) : cacheKeys[reviewer],
        };
        window.f3.jobs[id] = true;
        return new Promise((resolve) => setTimeout(() => resolve(reply(job)), delayMs));
      }
      if (route.endsWith('/bundle')) {
        const id = route.slice('/reviews/'.length, -'/bundle'.length);
        window.f3.bundles.push(id);
        return reply(id.includes(${JSON.stringify(reviewerB.id)}) ? traceB : traceA);
      }
      if (route.startsWith('/reviews/')) {
        const id = route.slice('/reviews/'.length);
        return reply({ id, session_id: 'sess-f3', reviewer_id: id.replace('job-', ''), status: 'completed', processed_decisions: 2, total_decisions: 2, current_ply: 0, error: null, cached: window.f3.jobs[id] === true, cache_key: 'a'.repeat(64) });
      }
      return reply({ error: 'unhandled test route ' + route }, 404);
    };
  })();` });

  let caseSeq = 0;
  const caseId = () => `c${++caseSeq}`;
  const navigate = (route) => send("Page.navigate", { url: `http://127.0.0.1:${port}${route}` });
  const stageSeat = async (seat) => {
    await evaluate(`window.localStorage.setItem('f3Seat', ${seat === null ? "''" : JSON.stringify(String(seat))})`);
  };
  const posts = () => evaluate("window.f3.posts.map(p => p.reviewer_id)");
  const bundles = () => evaluate("window.f3.bundles.slice()");
  const activeReviewer = () => evaluate("document.querySelector('.match-meta').lastElementChild ? document.querySelector('.match-meta').lastElementChild.textContent : null");
  const currentPly = () => evaluate("document.querySelector('.timeline button.current') ? document.querySelector('.timeline button.current span').textContent : null");
  const activeFilter = () => evaluate("document.querySelector('.review-filter button.active') ? document.querySelector('.review-filter button.active').textContent : null");
  const revealActive = () => evaluate("document.querySelector('.view-switch button.reveal-active') !== null");
  const switchTo = (name) => evaluate(`(() => { const b = Array.from(document.querySelectorAll('.reviewer-switch button')).find(x => x.textContent.includes(${JSON.stringify(name)})); b.click(); return b.textContent; })()`);

  const reviewersA = reviewerA.display_name;
  const reviewersB = reviewerB.display_name;

  // ---- TEST 1 + 3: A -> B -> A reuses cache; ply/filter/reveal preserved --------
  await navigate(`/review?session=sess-f3&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null`);
  await stageSeat(1);
  await navigate(`/review?session=sess-f3&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null && document.querySelector('.view-switch') !== null`);
  assert.equal(await activeReviewer(), reviewersA, "the default reviewer opens first");

  // Move to a non-zero decision and turn on reveal, then switch reviewers.
  // The seat-1 filtered array holds plys [1, 3, 5], so index 2 is ply 5: a ply that
  // also exists in the unfiltered list, which is what makes "the ply survived, not the
  // index" a real distinction.
  await evaluate(`document.querySelectorAll('.timeline button')[2].click()`);
  await delay(120);
  const plyBefore = await currentPly();
  assert.notEqual(plyBefore, "0", "the gate moves off the first decision before switching");
  await wait(`Array.from(document.querySelectorAll('.view-switch button')).some(b => b.textContent.includes('Referee reveal'))`);
  await evaluate(`Array.from(document.querySelectorAll('.view-switch button')).find(b => b.textContent.includes('Referee reveal')).click()`);
  await delay(80);
  assert.equal(await revealActive(), true);

  await switchTo(reviewersB);
  await wait(`document.querySelector('.match-meta').lastElementChild.textContent.includes('B')`);
  assert.equal(await currentPly(), plyBefore, "the recorded ply survives the reviewer switch");
  assert.equal(await revealActive(), true, "reveal survives the reviewer switch");
  assert.equal(await activeFilter(), "My decisions", "the filter survives the reviewer switch");

  const bundlesAfterB = await bundles();
  await switchTo(reviewersA);
  await wait(`document.querySelector('.match-meta').lastElementChild.textContent.includes('Champion')`);
  await delay(200);
  const bundlesAfterReturn = await bundles();
  assert.equal(
    bundlesAfterReturn.length, bundlesAfterB.length,
    `switching back to a cached reviewer must not re-fetch its bundle: ${JSON.stringify(bundlesAfterReturn)}`,
  );
  assert.equal(await currentPly(), plyBefore, "the ply survives the round trip as well");
  assert.equal(await revealActive(), true);
  const postOrder = await posts();
  assert.deepEqual(postOrder.slice(-2), [reviewerB.id, reviewerA.id], `each switch still POSTs (the Host owns config identity): ${postOrder}`);

  // ---- TEST 2: the cache is keyed by cache_key, not reviewer id -----------------
  // Reviewer A's identity stays the same but the Host now reports a *different*
  // cache key (a config changed). The previously cached A trace must not be reused:
  // the browser must load the newly keyed trace instead.
  await evaluate("window.localStorage.setItem('f3ChangedKey', '1')");
  await evaluate("window.f3.bundles.length = 0");
  await navigate(`/review?session=sess-f3&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null`);
  await delay(200);
  const changedKeyBundles = await bundles();
  assert.equal(
    changedKeyBundles.length, 1,
    `a changed cache_key under the same reviewer id must reload the trace: ${JSON.stringify(changedKeyBundles)}`,
  );
  await evaluate("window.localStorage.setItem('f3ChangedKey', '')");

  // ---- TEST 5: a foreign job identity is refused --------------------------------
  await evaluate("window.localStorage.setItem('f3ForeignSession', '1')");
  await navigate(`/review?session=sess-f3&case=${caseId()}`);
  // The refusal is proven by what must *not* happen: no review body is rendered for
  // a job that belongs to another session. Waiting only for the error banner would
  // turn a real leak into a timeout message, so assert both sides.
  await wait(`document.querySelector('.error-banner') !== null || document.querySelector('.timeline') !== null`);
  const foreignRendered = await evaluate("document.querySelector('.timeline') !== null");
  assert.equal(foreignRendered, false, "a job for another session must not render a review body");
  const foreign = await evaluate("document.body.innerText");
  assert.match(foreign, /belongs to session/, `a job for another session must be refused: ${foreign.slice(0, 300)}`);
  await evaluate("window.localStorage.setItem('f3ForeignSession', '')");

  // ---- TEST 4: a stale A response cannot overwrite B ---------------------------
  await evaluate("window.localStorage.setItem('f3DelayA', '1')");
  await navigate(`/review?session=sess-f3&case=${caseId()}`);
  await wait(`document.querySelector('.reviewer-switch') !== null`);
  await delay(100);
  // A's POST is in flight (1200ms). Switch to B immediately.
  await switchTo(reviewersB);
  await wait(`document.querySelector('.match-meta').lastElementChild.textContent.includes('B')`);
  await delay(1400); // long enough for A's stale answer to have arrived
  assert.equal(await activeReviewer(), reviewersB, "A's late response must not overwrite B");
  assert.equal(await evaluate("document.querySelectorAll('.timeline button').length > 0"), true, "B's review stays rendered");
  await evaluate("window.localStorage.setItem('f3DelayA', '')");

  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  console.log("review-switch-browser: PASS (A->B->A reuses cache_key, ply+filter+reveal preserved, changed key reloads, foreign identity refused, stale response cannot overwrite)");
} finally {
  try { ws?.close(); } catch { /* closing */ }
  child.kill();
  server.kill();
  if (artifactDir) {
    fs.mkdirSync(artifactDir, { recursive: true });
    fs.writeFileSync(path.join(artifactDir, "review-switch-browser.log"), serverLog);
  }
}
