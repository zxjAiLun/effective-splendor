// Optional local Chromium interaction gate for F1: the Review page's human seat
// authority and My decisions navigation.
//
// Built app + mocked Host boundary. No real League, no reviewer job, no browser
// download; Node >=22 + an installed Chromium.
// Run: npm run build && node tests/review-seat-browser.mjs
//
// What this gate exists to prove, and can only prove in a real DOM:
//   1. the human seat comes from durable session metadata (the reviewers envelope),
//      not from the URL;
//   2. seat 1 is honoured, not silently read as 0;
//   3. a replay with no human attribution offers *no* My decisions control — the
//      absent seat is never coerced to 0, and the control is absent rather than
//      present-but-wrong;
//   4. a URL seat that disagrees with the recorded seat fails closed;
//   5. after filtering to My decisions, the timeline buttons and the arrow keys
//      walk the *same* filtered array (one index space, not two).
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

// A genuine two-seat V2 review bundle, produced by the real Host (M07 reviewer)
// against a real 2-player Human replay and trimmed to its first six plies so the
// fixture stays small. Both actors appear (3 decisions each), which is what the
// seat filter is asked to separate; fabricating frames would only test the mock.
const trace = JSON.parse(fs.readFileSync(new URL("./fixtures/rust-analysis-trace-v2-m07-two-seat.json", import.meta.url), "utf8"));
const seatFrames = (seat) => trace.frames.filter((frame) => frame.actor === seat).length;
const reviewers = [{
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
}];

const socket = net.createServer();
await new Promise((resolve) => socket.listen(0, "127.0.0.1", resolve));
const port = socket.address().port;
await new Promise((resolve) => socket.close(resolve));

const server = cp.spawn(process.execPath, ["node_modules/vinext/dist/cli.js", "start", "--port", String(port), "--hostname", "127.0.0.1"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverLog = "";
server.stdout.on("data", (b) => { serverLog += b; });
server.stderr.on("data", (b) => { serverLog += b; });

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-review-seat-"));
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
    for (let i = 0; i < 150; i++) {
      try { if (await evaluate(expression)) return; } catch { /* mid-navigation */ }
      await delay(50);
    }
    const dump = await evaluate("JSON.stringify({body: document.body ? document.body.innerText.slice(0, 900) : null})");
    throw new Error(`DOM timeout: ${expression}\n${dump}`);
  };
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });

  // Mocked Host: reviewer discovery carries the durable seat, and the review job
  // completes immediately with the two-actor trace.
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const nativeFetch = window.fetch.bind(window);
    window.reviewCalls = [];
    // localStorage survives navigation (an injected window property does not), so
    // each scenario stages the durable seat here before it navigates.
    window.durableSeat = (() => {
      const raw = window.localStorage.getItem('f1DurableSeat');
      return raw === null || raw === '' ? null : Number(raw);
    })();
    const reply = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
    const reviewers = ${JSON.stringify(reviewers)};
    const trace = ${JSON.stringify(trace)};
    window.fetch = (url, opts = {}) => {
      if (!String(url).startsWith(${JSON.stringify(API)})) return nativeFetch(url, opts);
      const route = String(url).slice(${JSON.stringify(API)}.length);
      if (route === '/health') return reply({ status: 'ok' });
      if (route.startsWith('/reviewers')) {
        return reply({ format: 'effective-splendor-studio-reviewers', version: 1, registry_id: 'studio-reviewers-2026-08-13', player_count: 2, human_seat: window.durableSeat, reviewers });
      }
      if (route === '/reviews') {
        window.reviewCalls.push(JSON.parse(opts.body));
        return reply({ id: 'job-1', session_id: 'sess-f1', reviewer_id: 'm07-determinization-champion', status: 'completed', processed_decisions: 2, total_decisions: 2, current_ply: 0, error: null, cached: false });
      }
      if (route === '/reviews/job-1/bundle') return reply(trace);
      if (route === '/reviews/job-1') return reply({ id: 'job-1', status: 'completed' });
      return reply({ error: 'unhandled test route ' + route }, 404);
    };
  })();` });

  // Each scenario needs a fresh mount; a same-URL navigation is optimized away.
  let caseSeq = 0;
  const caseId = () => `c${++caseSeq}`;
  const navigate = (route) => send("Page.navigate", { url: `http://127.0.0.1:${port}${route}` });
  // localStorage is origin-scoped, so it only exists after the first real page load.
  const stageSeat = async (seat) => {
    await evaluate(`window.localStorage.setItem('f1DurableSeat', ${seat === null ? "''" : JSON.stringify(String(seat))})`);
  };
  const tabCount = () => evaluate(`Array.from(document.querySelectorAll('.review-filter button')).map(b => b.textContent)`);
  const activeFilter = () => evaluate(`document.querySelector('.review-filter button.active') ? document.querySelector('.review-filter button.active').textContent : null`);
  const timelineActors = () => evaluate(`Array.from(document.querySelectorAll('.timeline button')).map(b => b.getAttribute('aria-label'))`);

  // ---- TEST 1: durable seat = 1, no URL seat -> My decisions = actor P1 only ----
  // Load the origin once so localStorage exists, then stage and re-enter.
  await navigate(`/review?session=sess-f1&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null`);
  await stageSeat(1);
  await navigate(`/review?session=sess-f1&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null`);
  assert.deepEqual(await tabCount(), ["My decisions", "All decisions"], "a known human seat offers both controls");
  assert.equal(await activeFilter(), "My decisions", "a known human seat opens on My decisions");
  const mine = await timelineActors();
  assert.equal(mine.length, seatFrames(1), "My decisions shows every seat-1 decision");
  assert.ok(mine.every((label) => label.endsWith("actor P1")), `My decisions must show only P1: ${mine}`);

  // ---- TEST 5: after filtering, the timeline and arrow keys share one array ----
  // Walk right with the keyboard: the visible index must advance inside the
  // filtered array (2 frames), never into the unfiltered 4.
  const currentIndex = () => evaluate(`document.querySelector('.timeline button.current') ? Array.from(document.querySelectorAll('.timeline button')).indexOf(document.querySelector('.timeline button.current')) : -1`);
  assert.equal(await currentIndex(), 0);
  await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))`);
  await delay(120);
  assert.equal(await currentIndex(), 1, "keyboard right walks inside the filtered frames");
  await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))`);
  await delay(120);
  assert.equal(await currentIndex(), seatFrames(1) - 1, "the filtered array ends at seat 1's last decision, not the recording's");
  // Clicking the second timeline button selects the same frame the keyboard did.
  await evaluate(`document.querySelectorAll('.timeline button')[1].click()`);
  await delay(120);
  assert.equal(await currentIndex(), 1, "timeline click and keyboard share one index space");

  // ---- TEST 3: no attribution -> no My decisions control, All still works ------
  await stageSeat(null);
  await navigate(`/review?session=sess-f1&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null`);
  assert.deepEqual(await tabCount(), ["All decisions"], "an unknown seat must not offer a My decisions control");
  assert.equal(await activeFilter(), "All decisions");
  assert.equal((await timelineActors()).length, trace.frames.length, "All decisions shows the whole recording");

  // ---- TEST 4: URL seat disagrees with the recorded seat -> fail closed ---------
  await stageSeat(1);
  await navigate(`/review?session=sess-f1&seat=0&case=${caseId()}`);
  await wait(`document.querySelector('.error-banner') !== null || document.querySelector('.timeline') !== null`);
  const mismatch = await evaluate("document.body.innerText");
  assert.match(mismatch, /disagrees with this session's recorded human seat 1/, `mismatch must fail closed: ${mismatch.slice(0, 400)}`);
  assert.equal(await evaluate(`document.querySelector('.timeline') !== null`), false, "a mismatch must not render a review body");
  assert.deepEqual(await evaluate("window.reviewCalls"), [], "a mismatch must never start a review job");

  // ---- TEST: a matching legacy URL seat stays compatible -----------------------
  await stageSeat(1);
  await navigate(`/review?session=sess-f1&seat=1&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null`);
  assert.equal(await activeFilter(), "My decisions", "a matching URL seat is compatible");
  assert.ok((await timelineActors()).every((label) => label.endsWith("actor P1")));

  // ---- TEST 2: a different durable seat is honoured, not read as 0 -------------
  await stageSeat(0);
  await navigate(`/review?session=sess-f1&case=${caseId()}`);
  await wait(`document.querySelector('.timeline') !== null`);
  const seat0 = await timelineActors();
  assert.ok(seat0.every((label) => label.endsWith("actor P0")), `durable seat 0 must filter to P0: ${seat0}`);

  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  console.log("review-seat-browser: PASS (durable seat authority, seat 1 honoured, unknown seat has no My control, URL mismatch fails closed, one index space for timeline+keyboard)");
} finally {
  try { ws?.close(); } catch { /* closing */ }
  child.kill();
  server.kill();
  if (artifactDir) {
    fs.mkdirSync(artifactDir, { recursive: true });
    fs.writeFileSync(path.join(artifactDir, "review-seat-browser.log"), serverLog);
  }
}
