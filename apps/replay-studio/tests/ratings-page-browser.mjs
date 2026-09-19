// Optional local Chromium interaction gate for the D2 /ratings split: built app
// + mocked Host boundary. No real League is opened; no browser download; Node
// >=22 + an installed Chromium. Like the other browser gates this is NOT part of
// `npm test`: run it as `npm run build && node tests/ratings-page-browser.mjs`.
//
// It proves the two halves of D2's separation at runtime, not just in source:
//   - /ratings renders ONLY from /league/leaderboard (You row, kinds, W-T-L,
//     rated/recorded, provisional) and shows none of the research vocabulary;
//   - /ratings/reports renders the moved research studio (default M22 report,
//     M19 switch, report upload, H2H matrix) and makes ZERO league reads.
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
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-ratings-browser-"));
const child = cp.spawn(browser, ["--headless", "--no-first-run", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
let ws; let send; let serial = 0; const pending = new Map(); const exceptions = [];
try {
  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(serverLog);
    try { ready = (await fetch(`http://127.0.0.1:${port}/ratings`)).ok; } catch { /* starting */ }
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
  const wait = async expression => { for (let i = 0; i < 150; i++) { try { if (await evaluate(expression)) return; } catch { /* a document mid-navigation has no body yet; keep waiting */ } await delay(50); } const dump = await evaluate("JSON.stringify({href: location.href, ready: document.readyState, calls: window.hostCalls ?? null, postNav: window.postNavLeagueCalls ?? null, body: document.body ? document.body.innerText.slice(0, 900) : null})"); throw new Error(`DOM timeout: ${expression}\n${dump}`); };
  const bodyText = () => evaluate("document.body.innerText");
  await send("Runtime.enable"); await send("Page.enable"); await send("DOM.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  // One Host route is all the Studio page may read; the reports page may read
  // none. `postNavLeagueCalls` tracks league reads made after the marker is set,
  // so a full page navigation cannot launder the earlier read away.
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const nativeFetch=window.fetch.bind(window);window.hostCalls=[];
    const reply=(body,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
    window.fetch=(url,opts={})=>{
      if(!String(url).startsWith('http://127.0.0.1:43120'))return nativeFetch(url,opts);
      const route=String(url).slice('http://127.0.0.1:43120'.length);
      window.hostCalls.push(route);
      if(route==='/league/leaderboard')return reply({format:'effective-splendor-studio-league-leaderboard',version:1,rows:[
        {participant_id:'b901a2ea-645d-4c45-b4b9-407f5b6f39b7',kind:'human',display_name:'You',elo:1530,rated_games:1,recorded_games:1,rated_wins:1,rated_ties:0,rated_losses:0,provisional:true},
        {participant_id:'eng-bbc4b64c4bc73d54525e0ba138ff5f6a',kind:'engine',display_name:'S3 Rollout',elo:1923,rated_games:168,recorded_games:168,rated_wins:100,rated_ties:4,rated_losses:64,provisional:false},
        {participant_id:'eng-1111',kind:'engine',display_name:'Gate Heuristic',elo:1516,rated_games:2,recorded_games:2,rated_wins:1,rated_ties:0,rated_losses:1,provisional:true}
      ]});
      return reply({error:'unhandled test route '+route},404);
    };
  })();` });
  // ---- /ratings: the Studio League product page ------------------------------
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/ratings` });
  await wait(`document.body.innerText.includes('1530')`);
  const ratingsText = await bodyText();
  // The real first human row, exactly as the ledger records it.
  assert.match(ratingsText, /STUDIO LEAGUE · CURRENT STANDINGS/);
  assert.match(ratingsText, /You/);
  assert.match(ratingsText, /1530/);
  assert.match(ratingsText, /1-0-0/);
  assert.match(ratingsText, /1 rated · 1 recorded/);
  assert.match(ratingsText, /provisional/);
  assert.match(ratingsText, /Human/);
  // Engine rows render with their own facts, and order is the ledger's.
  assert.match(ratingsText, /S3 Rollout/);
  assert.match(ratingsText, /100-4-64/);
  assert.match(ratingsText, /168 rated · 168 recorded/);
  assert.match(ratingsText, /1923/);
  assert.match(ratingsText, /Engine/);
  // None of the research corpus's concepts may appear here.
  assert.doesNotMatch(ratingsText, /Official/i);
  assert.doesNotMatch(ratingsText, /M19|M22|Batch BT|Non-transitivity|Load rating report/);
  assert.match(ratingsText, /not the research reports/);
  // The only Host read this page made is the leaderboard, and the nav carries the
  // reports entry at the DOM level. (Clicking next/link to navigate is a known,
  // pre-existing vinext 1.0.0-beta.2 platform break — `RSC prefetch setup error` —
  // reproduced on the pre-existing home → /play link with no mock and no D2 code;
  // it is recorded in the milestone doc, out of D2 scope.)
  assert.deepEqual(await evaluate("window.hostCalls"), ["/league/leaderboard"]);
  assert.equal(
    await evaluate(`Array.from(document.querySelectorAll('a')).some(a=>a.getAttribute('href')==='/ratings/reports')`),
    true,
  );
  // ---- /ratings/reports: the moved research studio ---------------------------
  // A fresh navigation gives a fresh `hostCalls`, so the zero-league-reads claim
  // below cannot be laundered by anything the Studio page read before it.
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/ratings/reports` });
  await wait(`document.body && document.body.innerText.includes('Rating Studio') && document.body.innerText.includes('Non-transitivity matrix')`);
  const reportsText = await bodyText();
  assert.match(reportsText, /m22-scaled-self-play-v1/);
  assert.match(reportsText, /M22 Self-Play/);
  assert.match(reportsText, /48\/48/);
  assert.match(reportsText, /OFFICIAL/i);
  assert.match(reportsText, /Load rating report/);
  // M19 switch still works. A click issued before React hydration lands is
  // simply lost (the SSR shell already shows the default report), so the click
  // is retried until the ledger of record — the page text — changes. The
  // successful switch is also the proof hydration is live for the upload below.
  let switched = false;
  for (let i = 0; i < 100 && !switched; i++) {
    try {
      await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='M19 full pool')?.click()`);
    } catch { /* document in flux; retry */ }
    switched = await evaluate(`document.body.innerText.includes('m19-internal-championship-v1')`);
    if (!switched) await delay(150);
  }
  assert.ok(switched, "the M19 report switch never took effect");
  assert.match(await bodyText(), /M19 full pool/);
  // Upload still works: a valid report file renders its tournament id.
  const upload = {
    format: "effective-splendor-rating-report", version: 1, tournament_id: "gate-upload-report",
    registry_hash: "0".repeat(64), round_robin_plan_hash: "1".repeat(64),
    scheduled_matches: 2, completed_matches: 2, aborted_matches: 0,
    agents: [
      { rank: 1, agent_id: "A", display_name: "Upload A", class: "search", completed: 2, aborted: 0, wins: 2, ties: 0, losses: 0, live_elo: 1516, official_elo: 1600, provisional: true },
      { rank: 2, agent_id: "B", display_name: "Upload B", class: "baseline", completed: 2, aborted: 0, wins: 0, ties: 0, losses: 2, live_elo: 1484, official_elo: 1400, provisional: true },
    ],
    head_to_head: [{ agent_a: "A", agent_b: "B", completed: 2, aborted: 0, wins_a: 2, ties: 0, wins_b: 0 }],
    pair_evaluation_report_hashes: ["2".repeat(64)],
  };
  const uploadPath = path.join(profile, "gate-upload-report.json");
  fs.writeFileSync(uploadPath, JSON.stringify(upload));
  const { root: docRoot } = await send("DOM.getDocument");
  const input = await send("DOM.querySelector", { nodeId: docRoot.nodeId, selector: "input[type=file]" });
  assert.ok(input.nodeId, "the reports page still offers its report upload input");
  await send("DOM.setFileInputFiles", { files: [uploadPath], nodeId: input.nodeId });
  await wait(`document.body.innerText.includes('gate-upload-report')`);
  assert.match(await bodyText(), /Upload A/);
  assert.match(await bodyText(), /2-0-0/);
  // The runtime half of the separation gate: the research studio made no league
  // read — not on load, not on switch, not on upload.
  assert.deepEqual(await evaluate("window.hostCalls"), []);
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  console.log("ratings-page-browser: PASS (studio /ratings renders ledger rows only; /ratings/reports keeps M22 default, M19 switch, upload, matrix, and makes zero league reads)");
} finally {
  try { ws?.close(); } catch { /* closing */ }
  child.kill();
  server.kill();
  if (artifactDir) { fs.mkdirSync(artifactDir, { recursive: true }); fs.writeFileSync(path.join(artifactDir, "ratings-page-browser.log"), serverLog); }
}
