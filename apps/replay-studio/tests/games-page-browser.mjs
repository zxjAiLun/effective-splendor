// Optional local Chromium interaction gate for the Studio League games page:
// built app + mocked Host boundary. No real League is opened; no browser
// download; Node >=22 + an installed Chromium. This is intentionally NOT part
// of `npm test` (like human-play-browser.mjs): it requires a local browser
// binary. Run: npm run build && node tests/games-page-browser.mjs
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import cp from "node:child_process";
import net from "node:net";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir = process.env.PLAYER_LOOP_ARTIFACTS;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const cache = path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
const browser = process.env.STUDIO_TEST_BROWSER || (fs.existsSync(cache) ? fs.readdirSync(cache).filter(v => /^chromium-\d+$/.test(v)).sort().reverse().flatMap(v => ["chrome-win64/chrome.exe", "chrome-win/chrome.exe"].map(p => path.join(cache, v, p))).find(p => fs.existsSync(p)) : null);
assert.ok(browser, "Set STUDIO_TEST_BROWSER to an installed Chromium; never downloads.");
const socket = net.createServer();
await new Promise(resolve => socket.listen(0, "127.0.0.1", resolve));
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
const server = cp.spawn(process.execPath, ["node_modules/vinext/dist/cli.js", "start", "--port", String(port), "--hostname", "127.0.0.1"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverLog = "";
server.stdout.on("data", b => { serverLog += b; }); server.stderr.on("data", b => { serverLog += b; });
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-games-browser-"));
const child = cp.spawn(browser, ["--headless", "--no-first-run", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
let ws; let send; let serial = 0; const pending = new Map(); const exceptions = [];
try {
  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(serverLog);
    try { ready = (await fetch(`http://127.0.0.1:${port}/`)).ok; } catch { /* starting */ }
    if (ready) break; await delay(100);
  }
  assert.ok(ready, serverLog);
  const activePort = path.join(profile, "DevToolsActivePort");
  for (let i = 0; i < 150 && !fs.existsSync(activePort); i++) await delay(100);
  const debugPort = fs.readFileSync(activePort, "utf8").split("\n")[0];
  const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
  ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.addEventListener("open", resolve, { once: true }); ws.addEventListener("error", reject, { once: true }); });
  ws.addEventListener("message", e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); clearTimeout(p.timer); if (m.error) p.reject(new Error(JSON.stringify(m.error))); else p.resolve(m.result); }
    if (m.method === "Runtime.exceptionThrown") exceptions.push(m.params.exceptionDetails);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++serial; const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout ${method}`)); }, 10000);
    pending.set(id, { resolve, reject, timer }); ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const value = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
    return value.result.value;
  };
  const wait = async expression => { for (let i = 0; i < 150; i++) { if (await evaluate(expression)) return; await delay(50); } const dump = await evaluate("JSON.stringify({calls: window.gamesCalls ?? null, body: document.body ? document.body.innerText.slice(0, 900) : null})"); throw new Error(`DOM timeout: ${expression}\n${dump}`); };
  await send("Runtime.enable"); await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  // Mocked Host. Three league pages + a failure mode switch:
  //   page1 (no query):  rows 200/151, next 150
  //   page2 (before=150): rows 149/76, next 75
  //   page3 (before=75):  row 1, next null
  // window.flaw: 'ok' | 'fail500' | 'malformed' applies to page3 only.
  const seat = (seat, name, score, rank, won) => ({ seat, participant_id: `p-${name}`, display_name: name, score, rank, won });
  const row = (seq, a, b) => ({ match_id: `m${seq}`.padEnd(64, "0").slice(0, 64), league_seq: seq, played_at: 1789740000 + seq, source_kind: "arena_report", status: "completed", rating_eligible: true, rating_ineligible_reason: null, replay_document_sha256: null, replay_archived: false, seats: [a, b] });
  const r1 = row(200, seat(0, "GateAlpha", 15, 1, true), seat(1, "GateBeta", 6, 2, false));
  const r2 = row(151, seat(0, "GateGamma", 12, 1, true), seat(1, "GateDelta", 9, 2, false));
  const r3 = row(149, seat(0, "GateEps", 11, 1, true), seat(1, "GateZeta", 10, 2, false));
  const r4 = row(76, seat(0, "GateEta", 14, 1, true), seat(1, "GateTheta", 5, 2, false));
  const r5 = row(1, seat(0, "GateIota", 9, 1, true), seat(1, "GateKappa", 8, 2, false));
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const nativeFetch=window.fetch.bind(window);window.gamesCalls=[];window.flaw='ok';
    const reply=(body,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
    const rows=${JSON.stringify([r1, r2, r3, r4, r5])};
    window.fetch=(url,opts={})=>{
      if(!String(url).startsWith('http://127.0.0.1:43120'))return nativeFetch(url,opts);
      const route=String(url).slice('http://127.0.0.1:43120'.length);
      if(route==='/health')return reply({status:'ok'});
      if(route==='/recent-games')return reply({games:[]});
      if(route.startsWith('/league/games')){
        const q=route.includes('?')?route.slice(route.indexOf('?')+1):'';
        window.gamesCalls.push(q);
        if(q==='')return reply({format:'effective-splendor-studio-league-games',version:1,matches:[rows[0],rows[1]],next_before_league_seq:150});
        if(q==='limit=50&before=150')return reply({format:'effective-splendor-studio-league-games',version:1,matches:[rows[2],rows[3]],next_before_league_seq:75});
        if(q==='limit=50&before=75'){
          if(window.flaw==='fail500')return reply({error:'database locked'},500);
          if(window.flaw==='malformed')return reply({format:'effective-splendor-studio-league-games',version:1,matches:'not-an-array',next_before_league_seq:null});
          return reply({format:'effective-splendor-studio-league-games',version:1,matches:[rows[4]],next_before_league_seq:null});
        }
        return reply({error:'bad cursor '+q},400);
      }
      return reply({error:'unhandled test route '+route},404);
    };
  })();` });
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/` });
  // Page 1 renders both sections separately.
  await wait(`document.body.innerText.includes('GateAlpha')`);
  assert.match(await evaluate("document.body.innerText"), /Long-term league record/);
  assert.match(await evaluate("document.body.innerText"), /LOCAL \/ LEGACY GAMES/);
  assert.match(await evaluate("document.body.innerText"), /Saved human vs engine games/);
  assert.match(await evaluate("document.body.innerText"), /No saved games yet/);
  assert.equal(await evaluate(`document.querySelectorAll('section.recent-games:not(.legacy-games) article').length`), 2);
  // Load more follows the Host-issued cursor, never an offset.
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Load more').click()`);
  await wait(`document.body.innerText.includes('GateEps')`);
  assert.deepEqual(await evaluate("window.gamesCalls"), ["", "limit=50&before=150"]);
  assert.equal(await evaluate(`document.querySelectorAll('section.recent-games:not(.legacy-games) article').length`), 4);
  // A failed page keeps the rows already shown and offers page-level retry.
  await evaluate(`window.flaw='fail500';Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Load more').click()`);
  await wait(`document.body.innerText.includes('database locked')`);
  assert.equal(await evaluate(`document.querySelectorAll('section.recent-games:not(.legacy-games) article').length`), 4);
  assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Retry page')`), true);
  // A malformed 200 is an error, not an empty page, and the cursor is unchanged.
  await evaluate(`window.flaw='malformed';Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Retry page').click()`);
  await wait(`document.body.innerText.includes('invalid games page')`);
  assert.equal(await evaluate(`document.querySelectorAll('section.recent-games:not(.legacy-games) article').length`), 4);
  // Retry re-issues the same cursor and completes the recording.
  await evaluate(`window.flaw='ok';Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Retry page').click()`);
  await wait(`document.body.innerText.includes('End of the recorded league.')`);
  assert.equal(await evaluate(`document.querySelectorAll('section.recent-games:not(.legacy-games) article').length`), 5);
  assert.deepEqual(await evaluate("window.gamesCalls"), ["", "limit=50&before=150", "limit=50&before=75", "limit=50&before=75", "limit=50&before=75"]);
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  console.log("games-page-browser: PASS (2 sections, cursor pagination, failure retry preserves rows and cursor, malformed 200 rejected, end marker)");
} finally {
  try { ws?.close(); } catch { /* closing */ }
  child.kill();
  server.kill();
  if (artifactDir) { fs.mkdirSync(artifactDir, { recursive: true }); fs.writeFileSync(path.join(artifactDir, "games-page-browser.log"), serverLog); }
}
