// Local Chromium interaction gate for D3B Participant Profile:
// built app + mocked Host boundary.
// Tests:
// 1. Mount ONLY requests /league/participants/:id (no parallel fan-out to ratings/opponents/games);
// 2. Sections (Opponents, Rating history, Games) are fetched strictly on-demand when clicked;
// 3. Cached within page session: switching back and forth does not re-fetch;
// 4. Elo chart displays League sequence on x-axis;
// 5. /ratings links to valid participant profiles;
// 6. Unknown participant renders truthful 404 text.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import cp from "node:child_process";
import net from "node:net";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const cache = path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
const browser =
  process.env.STUDIO_TEST_BROWSER ||
  (fs.existsSync(cache)
    ? fs
        .readdirSync(cache)
        .filter((v) => /^chromium-\d+$/.test(v))
        .sort()
        .reverse()
        .flatMap((v) => ["chrome-win64/chrome.exe", "chrome-win/chrome.exe"].map((p) => path.join(cache, v, p)))
        .find((p) => fs.existsSync(p))
    : null);
assert.ok(browser, "Set STUDIO_TEST_BROWSER to an installed Chromium; never downloads.");

const socket = net.createServer();
await new Promise((resolve) => socket.listen(0, "127.0.0.1", resolve));
const port = socket.address().port;
await new Promise((resolve) => socket.close(resolve));

const server = cp.spawn(
  process.execPath,
  ["node_modules/vinext/dist/cli.js", "start", "--port", String(port), "--hostname", "127.0.0.1"],
  { cwd: root, stdio: ["ignore", "pipe", "pipe"] }
);
let serverLog = "";
server.stdout.on("data", (b) => {
  serverLog += b;
});
server.stderr.on("data", (b) => {
  serverLog += b;
});

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-profile-browser-"));
const child = cp.spawn(
  browser,
  [
    "--headless",
    "--no-first-run",
    "--disable-background-networking",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "about:blank",
  ],
  { stdio: "ignore" }
);

let ws;
let send;
let serial = 0;
const pending = new Map();
const exceptions = [];

try {
  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(serverLog);
    try {
      ready = (await fetch(`http://127.0.0.1:${port}/ratings`)).ok;
    } catch {
      /* starting */
    }
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

  send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++serial;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`CDP timeout ${method}`));
      }, 10000);
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
      try {
        if (await evaluate(expression)) return;
      } catch {
        /* mid-navigation */
      }
      await delay(50);
    }
    const dump = await evaluate(
      "JSON.stringify({href: location.href, ready: document.readyState, calls: window.hostCalls ?? null, body: document.body ? document.body.innerText.slice(0, 900) : null})"
    );
    throw new Error(`DOM timeout: ${expression}\n${dump}`);
  };

  const bodyText = () => evaluate("document.body.innerText");

  await send("Runtime.enable");
  await send("Page.enable");
  await send("DOM.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });

  // Add mock script to capture host calls and return typed D3A fixtures
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `(() => {
    const nativeFetch = window.fetch.bind(window);
    window.hostCalls = [];
    const reply = (body, status = 200) =>
      Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

    window.fetch = (url, opts = {}) => {
      if (!String(url).startsWith('http://127.0.0.1:43120')) return nativeFetch(url, opts);
      const route = String(url).slice('http://127.0.0.1:43120'.length);
      window.hostCalls.push(route);

      if (route === '/league/leaderboard') {
        return reply({
          format: 'effective-splendor-studio-league-leaderboard',
          version: 1,
          rows: [
            { participant_id: 'b901a2ea-645d-4c45-b4b9-407f5b6f39b7', kind: 'human', display_name: 'You', elo: 1530, rated_games: 1, recorded_games: 1, rated_wins: 1, rated_ties: 0, rated_losses: 0, provisional: true },
            { participant_id: 'eng-busy-1', kind: 'engine', display_name: 'Busy Engine', elo: 1537, rated_games: 576, recorded_games: 18496, rated_wins: 262, rated_ties: 0, rated_losses: 314, provisional: false },
          ]
        });
      }

      if (route === '/league/participants/eng-busy-1') {
        return reply({
          format: 'effective-splendor-studio-league-participant',
          version: 1,
          profile: {
            participant_id: 'eng-busy-1',
            kind: 'engine',
            display_name: 'Busy Engine',
            elo: { value: 1536.845, display_rounded: 1537, origin: 'rated' },
            provisional: false,
            recorded_games: 18496,
            rated_games: 576,
            rated_wins: 262,
            rated_ties: 0,
            rated_losses: 314,
            seats: { appearances: 36416, seat0: 18208, seat1: 18208, other: 0 },
            completed_plies: { availability: 'available', value: 61.685, observed_completed_games: 18496, total_completed_games: 18496, unit: 'decision_plies' },
            main_turns: { availability: 'unavailable', reason: 'not_recorded' },
            gameplay: { availability: 'unavailable', reason: 'no_authoritative_builder' }
          }
        });
      }

      if (route === '/league/participants/b901a2ea-645d-4c45-b4b9-407f5b6f39b7') {
        return reply({
          format: 'effective-splendor-studio-league-participant',
          version: 1,
          profile: {
            participant_id: 'b901a2ea-645d-4c45-b4b9-407f5b6f39b7',
            kind: 'human',
            display_name: 'You',
            elo: { value: 1529.808, display_rounded: 1530, origin: 'rated' },
            provisional: true,
            recorded_games: 1,
            rated_games: 1,
            rated_wins: 1,
            rated_ties: 0,
            rated_losses: 0,
            seats: { appearances: 1, seat0: 1, seat1: 0, other: 0 },
            completed_plies: { availability: 'available', value: 50.0, observed_completed_games: 1, total_completed_games: 1, unit: 'decision_plies' },
            main_turns: { availability: 'unavailable', reason: 'not_recorded' },
            gameplay: { availability: 'unavailable', reason: 'no_authoritative_builder' }
          }
        });
      }

      if (route.startsWith('/league/participants/eng-busy-1/opponents')) {
        return reply({
          format: 'effective-splendor-studio-league-participant-opponents',
          version: 1,
          participant_id: 'eng-busy-1',
          opponents: [
            { opponent_id: 'eng-opponent-a', display_name: 'Opponent Alpha', recorded_games: 128, rated_games: 128, rated_wins: 100, rated_ties: 0, rated_losses: 28 },
          ],
          next_after_opponent_id: null,
        });
      }

      if (route.startsWith('/league/participants/eng-busy-1/ratings')) {
        return reply({
          format: 'effective-splendor-studio-league-participant-ratings',
          version: 1,
          participant_id: 'eng-busy-1',
          points: [
            { participant_id: 'eng-busy-1', league_seq: 42500, match_id: 'm-42500', elo_before: 1520.0, elo_after: 1537.0, delta: 17.0, opponent_id: 'eng-opponent-a', opponent_name: 'Opponent Alpha', played_at: 1700000000 },
            { participant_id: 'eng-busy-1', league_seq: 42000, match_id: 'm-42000', elo_before: 1500.0, elo_after: 1520.0, delta: 20.0, opponent_id: 'eng-opponent-a', opponent_name: 'Opponent Alpha', played_at: 1699900000 },
          ],
          next_before_league_seq: null,
        });
      }

      if (route.startsWith('/league/games?participant_id=eng-busy-1')) {
        return reply({
          format: 'effective-splendor-studio-league-games',
          version: 1,
          matches: [
            {
              match_id: 'm-42500',
              league_seq: 42500,
              played_at: 1700000000,
              source_kind: 'arena_report',
              status: 'completed',
              rating_eligible: true,
              rating_ineligible_reason: null,
              replay_document_sha256: 'deadbeef001',
              replay_archived: true,
              seats: [
                { seat: 0, participant_id: 'eng-busy-1', display_name: 'Busy Engine', score: 16, rank: 0, won: true },
                { seat: 1, participant_id: 'eng-opponent-a', display_name: 'Opponent Alpha', score: 12, rank: 1, won: false },
              ]
            }
          ],
          next_before_league_seq: null,
        });
      }

      if (route === '/league/participants/nonexistent-id') {
        return reply({ error: 'no participant nonexistent-id is recorded in the ledger' }, 404);
      }

      return reply({ error: 'unhandled test route ' + route }, 404);
    };
  })();`,
  });

  // ---- TEST 1: Mount Busy Engine Profile -> ONLY /participants/:id requested -----
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/ratings/eng-busy-1` });
  await wait(`document.body.innerText.includes('1537')`);
  const profileText = await bodyText();
  assert.match(profileText, /Busy Engine/);
  assert.match(profileText, /1537/);
  assert.match(profileText, /Studio Elo/i);
  assert.match(profileText, /262–0–314/);
  assert.match(profileText, /P0 18208 · P1 18208/);
  assert.match(profileText, /61.7 decision plies/);
  assert.match(profileText, /18496 \/ 18496 completed games observed/);

  // Hard contract: NO parallel fan-out on mount!
  const callsOnMount = await evaluate("window.hostCalls");
  assert.deepEqual(
    callsOnMount,
    ["/league/participants/eng-busy-1"],
    "Mount MUST only request /league/participants/:id; no fan-out allowed!"
  );

  // ---- TEST 2: Click Opponents -> requested on-demand ---------------------------
  await evaluate(`document.querySelectorAll('.profile-tab-button')[3].click()`);
  await wait(`document.body.innerText.includes('Opponent Alpha')`);
  const callsAfterOpponents = await evaluate("window.hostCalls");
  assert.equal(callsAfterOpponents.length, 2);
  assert.match(callsAfterOpponents[1], /^\/league\/participants\/eng-busy-1\/opponents/);

  // ---- TEST 3: Switch back to Overview, then back to Opponents -> CACHED --------
  await evaluate(`document.querySelectorAll('.profile-tab-button')[0].click()`);
  await delay(100);
  await evaluate(`document.querySelectorAll('.profile-tab-button')[3].click()`);
  await delay(100);
  const callsAfterTabToggle = await evaluate("window.hostCalls");
  assert.equal(callsAfterTabToggle.length, 2, "Re-visiting Opponents tab must be served from cache!");

  // ---- TEST 4: Click Rating history -> requested on-demand and renders SVG ------
  await evaluate(`document.querySelectorAll('.profile-tab-button')[2].click()`);
  await wait(`document.body.innerText.includes('Rating progression')`);
  const callsAfterRatings = await evaluate("window.hostCalls");
  assert.equal(callsAfterRatings.length, 3);
  assert.match(callsAfterRatings[2], /^\/league\/participants\/eng-busy-1\/ratings/);
  const ratingsText = await bodyText();
  assert.match(ratingsText, /x-axis: League sequence/);
  assert.match(ratingsText, /Protocol starting Elo: 1500/);

  // ---- TEST 5: Click Games -> requested on-demand (reusing D1) ------------------
  await evaluate(`document.querySelectorAll('.profile-tab-button')[1].click()`);
  await wait(`document.body.innerText.includes('#42500')`);
  const callsAfterGames = await evaluate("window.hostCalls");
  assert.equal(callsAfterGames.length, 4);
  assert.match(callsAfterGames[3], /^\/league\/games\?participant_id=eng-busy-1/);

  // ---- TEST 6: Unknown participant renders truthful 404 text --------------------
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/ratings/nonexistent-id` });
  await wait(`document.body.innerText.includes('No participant with ID')`);
  const notFoundText = await bodyText();
  assert.match(notFoundText, /No participant with ID "nonexistent-id" is recorded in the Studio League/);

  console.log("All D3B browser interaction gates PASSED!");
} finally {
  if (ws) ws.close();
  child.kill();
  server.kill();
  try {
    fs.rmSync(profile, { recursive: true, force: true });
  } catch {
    /* temp dir cleanup */
  }
}
