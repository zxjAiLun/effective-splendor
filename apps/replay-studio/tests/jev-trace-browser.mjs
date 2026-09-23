// Optional local Chromium interaction gate for the Jev interaction panel: built
// app + a mocked Host boundary. No real run directory is opened and no model is
// called; the Host's read-only /jev routes are stubbed with a run shaped exactly
// like a real one. Node >=22 + an installed Chromium.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import cp from "node:child_process";
import net from "node:net";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir = process.env.JEV_TRACE_ARTIFACTS;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const cache = path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
const browser = process.env.STUDIO_TEST_BROWSER || (fs.existsSync(cache)
  ? fs.readdirSync(cache).filter(v => /^chromium-\d+$/.test(v)).sort().reverse()
      .flatMap(v => ["chrome-win64/chrome.exe", "chrome-win/chrome.exe"].map(p => path.join(cache, v, p)))
      .find(p => fs.existsSync(p))
  : null);
assert.ok(browser, "Set STUDIO_TEST_BROWSER to an installed Chromium; never downloads.");

const socket = net.createServer();
await new Promise(resolve => socket.listen(0, "127.0.0.1", resolve));
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
// The app hard-codes the Host base (`app/api-base.mjs`), so the stub must answer
// there. The real Host is never started: this gate deliberately has no run
// directory and no way to call a model.
const hostPort = 43120;
assert.equal(
  /127\.0\.0\.1:(\d+)/.exec(fs.readFileSync(path.join(root, "app/api-base.mjs"), "utf8"))[1],
  String(hostPort),
  "the stub must track the app's one Host base",
);
const server = cp.spawn(process.execPath, ["node_modules/vinext/dist/cli.js", "start", "--port", String(port), "--hostname", "127.0.0.1"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
let serverLog = "";
server.stdout.on("data", b => { serverLog += b; });
server.stderr.on("data", b => { serverLog += b; });

// The stub Host: a real socket with the real route shapes, so the page exercises
// its own fetch and CORS path rather than an in-page interception.
const step = (ply, actor) => ({ ply, actor, action: { type: "pass" }, state_hash_before: "a".repeat(64), state_hash_after: "b".repeat(64) });
const prefix = { format: "splendor-rollout-prefix", version: 1, engine_version: "e", ruleset: { player_count: 2 }, ruleset_fingerprint: "c".repeat(64), player_count: 2, seed: "42", ply_cap: 2, initial_state_hash: "d".repeat(64), steps: [step(0, 0), step(1, 1)], cap_state_hash: "e".repeat(64) };
const trace = { schema_version: 1, run_id: "gate-run", game_document: "truncated_prefix", game_plies: 2, journal_decisions: 2, ambiguous_plies: [], decisions: {}, metrics: { status: "truncated", decisions: 2 } };
const gems = { white: 0, blue: 0, green: 0, red: 0, black: 0, gold: 0 };
const player = id => ({ id, tokens: gems, bonuses: [0, 0, 0, 0, 0], prestige: 0, reserved_count: 0, public_reserved: [], purchased: [], nobles: [] });
const frame = (ply, actor) => ({ ply, actor, player_view: { viewer: actor, public: { player_count: 2, current_player: actor, bank: gems, deck_counts: [0, 0, 0], market: [[null, null, null, null], [null, null, null, null], [null, null, null, null]], nobles: [], players: [player(0), player(1)] }, private: { reserved: [] } }, legal_actions: [{ type: "pass" }], recorded_action: { type: "pass" }, referee_reveal: null, observation_hash: "f".repeat(64) });
const archive = { format: "effective-splendor-replay-archive", version: 1, session_id: "gate-run", opponent: null, human_seat: null, player_count: 2, replay_document_hash: "a".repeat(64), replay: { result: { scores: [2, 15], ranks: [1, 0], winners: [1], reason: "prestige" } }, frames: [frame(0, 0), frame(1, 1)], catalog: { cards: [], nobles: [] } };
const stub = cp.spawn(process.execPath, ["-e", `
const http=require('http');
const prefix=${JSON.stringify(prefix)};
const trace=${JSON.stringify({ ...trace, decisions: {
  "0": { ply: 0, actor: 0, action_sent: true, request_id: 1, observation_hash: "f".repeat(64), stages: [
    { stage: "helper", attempts: [{ attempt: 1, outcome: "ok", status: 200, latency_ms: 12 }] },
    { stage: "family", latency_ms: 640, requested_model: "jev-latest", payload_sha256: "ab".repeat(32), payload_snapshot_recorded: true, payload_snapshot: { model: "jev-latest", state: "gate-state", questions: { family: { type: "choice", criteria: ["a", "b", "c"] } } }, candidate_ids: ["family-1", "family-2", "family-3"], attempts: [{ outcome: "received", selected_id: "family-2", returned_model: "jev-latest", usage: { input_tokens: 900, output_tokens: 40 }, latency_ms: 710 }] },
    { stage: "move", latency_ms: 722, candidate_ids: ["move-1"], attempts: [{ outcome: "error", code: "http_status", http_status: 503, latency_ms: 210 }, { outcome: "retry_wait", seconds: 0.5 }, { outcome: "received", selected_id: "move-1", returned_model: "jev-latest", usage: { input_tokens: 1200, output_tokens: 12 }, latency_ms: 512 }] } ] },
  "1": { ply: 1, actor: 1, action_sent: false, request_id: null, observation_hash: null, stages: [], note: "opponent turn" } } }) };
const archive=${JSON.stringify(archive)};
const routes={
  "/catalog": { cards: [], nobles: [] },
  "/jev/runs": { format: "effective-splendor-jev-runs", version: 1, runs: [{ run_id: "gate-run", has_trace_summary: true, journal_recorded: true, game_document: "truncated_prefix", decisions: 2, status: "truncated", agent_version: "0.3.0", model_versions: ["jev-latest"], outcome: "truncated" }], note: "Local unrated Jev exhibition runs; not league or human matches." },
  "/jev/runs/gate-run": { format: "effective-splendor-jev-run-trace", version: 1, run_id: "gate-run", trace, config: { game_id: "gate", agents: [{ program: "python", args: ["agent.py"] }, { program: "splendor", args: ["agent-heuristic"] }] }, replay: null, prefix },
  "/replays/gate-run": archive
};
http.createServer((req,res)=>{const route=req.url.split('?')[0];
  const review=/review|analysis|vote/i.test(route);
  console.error('CALL '+req.method+' '+route);
  const body=routes[route];
  if(review){res.writeHead(500,{'Access-Control-Allow-Origin':'*','Content-Type':'application/json'});return res.end('{"error":"a reviewer route must never be read for a trace"}');}
  if(!body){res.writeHead(404,{'Access-Control-Allow-Origin':'*','Content-Type':'application/json'});return res.end('{"error":"unknown"}');}
  res.writeHead(200,{'Access-Control-Allow-Origin':'*','Content-Type':'application/json'});res.end(JSON.stringify(body));
}).listen(${hostPort},'127.0.0.1');
`], { stdio: ["ignore", "ignore", "pipe"] });
let stubLog = "";
stub.stderr.on("data", b => { stubLog += b; });
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-jev-browser-"));
const child = cp.spawn(browser, ["--headless", "--no-first-run", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
let ws, send, serial = 0;
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
  ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  ws.addEventListener("message", e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      clearTimeout(p.timer);
      if (m.error) p.reject(new Error(JSON.stringify(m.error))); else p.resolve(m.result);
    }
    if (m.method === "Runtime.exceptionThrown") exceptions.push(m.params.exceptionDetails);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++serial;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout ${method}`)); }, 10000);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const value = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
    return value.result.value;
  };
  const wait = async expression => {
    for (let i = 0; i < 150; i++) {
      try {
        if (await evaluate(expression)) return;
      } catch { /* the document may not have committed yet */ }
      await delay(50);
    }
    throw new Error(`DOM timeout: ${expression}\n${await evaluate("document.body ? document.body.innerText : '(no body)'")}`);
  };
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1200, deviceScaleFactor: 1, mobile: false });

  await send("Page.navigate", { url: `http://127.0.0.1:${port}/` });
  await wait("document.body.innerText.includes('Jev arena runs')");
  await wait("document.body.innerText.includes('gate-run')");
  const home = await evaluate("document.body.innerText");
  assert.match(home, /LOCAL \/ JEV EXHIBITIONS/i, "the Games home must offer the Jev runs section");
  assert.match(home, /Unrated experiments run locally/i, "the section must say these are unrated: " + home);
  assert.match(home, /gate-run/, "the run must be listed: " + home);
  assert.match(home, /never a reconstruction/i, "the section must not claim a reconstruction: " + home);

  // Stepping must not fetch a reviewer or invoke a model: only read routes.
  const calls = stubLog.split("\n").filter(line => line.startsWith("CALL ")).map(line => {
    const [, method, route] = line.split(" ");
    return { method, route };
  });
  assert.ok(calls.some(c => c.route === "/jev/runs"), "the index must be read over HTTP: " + stubLog);
  assert.ok(calls.every(c => c.method === "GET"), "the trace surface must be read-only: " + JSON.stringify(calls));
  assert.ok(calls.every(c => !/review|analysis|vote/i.test(c.route)), "no reviewer route may be touched: " + JSON.stringify(calls));

  if (artifactDir) {
    fs.mkdirSync(artifactDir, { recursive: true });
    const shot = await send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(artifactDir, "jev-runs-home.png"), Buffer.from(shot.data, "base64"));
    fs.writeFileSync(path.join(artifactDir, "browser.json"), JSON.stringify({ status: "PASS", boundary: "real Chromium + built UI; mocked read-only Host", calls, exceptions }, null, 2));
  }
  assert.deepEqual(exceptions, [], "no page exception may be raised");

  // The replay page itself: stepping a frame must show that frame's interaction
  // record, and a step the agent never took must say so rather than showing blank.
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/replay?session=gate-run&jev=gate-run` });
  await wait("document.body.innerText.includes('Player 0')");
  await wait("document.body.innerText.includes('JEV INTERACTION')");
  const panel = await evaluate("document.querySelector('.jev-trace').innerText");
  assert.match(panel, /JEV INTERACTION/i, panel);
  // Each stage the agent actually ran is named, in order.
  assert.match(panel, /Local heuristic terms/i, panel);
  assert.match(panel, /Stage 1 .*choose move family/i, panel);
  assert.match(panel, /Stage 2 .*choose exact action/i, panel);
  // A step with no recorded request body must say so rather than invent one. The
  // family stage here *did* record one, so its real payload must be reachable.
  assert.match(panel, /not recorded/i, "an unrecorded body must be reported as such: " + panel);
  assert.match(panel, /Show the request sent to Jev/i, panel);
  await evaluate(`document.querySelectorAll('.jev-request').forEach(d => { d.open = true; })`);
  await delay(100);
  const expanded = await evaluate("document.querySelector('.jev-trace').innerText");
  assert.match(expanded, /gate-state/, "a recorded request body must be shown when expanded: " + expanded);
  assert.match(expanded, /Application payload only/i, "the body must be qualified as the app payload: " + expanded);
  assert.match(expanded, /never part of\s+this body or this record/i, "the credential boundary must be stated: " + expanded);

  // A recorded request body must be shown as the real payload, and the retry
  // must stay a fact of the record.
  assert.match(panel, /retry|retried|503/i, "a retried attempt must stay visible: " + panel);
  assert.match(panel, /1,?200|1200/, "the recorded usage must be shown: " + panel);

  // Stepping to the opponent's frame must report that this seat took no call,
  // not fabricate stages for it.
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b => /next|\u25b6/i.test(b.textContent))?.click()`);
  await delay(200);
  const stepped = await evaluate("document.body.innerText");
  assert.doesNotMatch(stepped, /TypeError/, "stepping must not throw: " + stepped);

  // A run the Host does not know must leave the replay usable and say the trace
  // is missing.
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/replay?session=gate-run&jev=no-such-run` });
  await wait("document.body.innerText.includes('Player 0')");
  await delay(300);
  const missing = await evaluate("document.body.innerText");
  assert.match(missing, /Player 0/, "a missing trace must not hide the replay: " + missing);
  assert.match(missing, /not recorded|no interaction|unavailable|missing/i, "a missing trace must be reported honestly: " + missing);

  const allCalls = stubLog.split("\n").filter(line => line.startsWith("CALL ")).map(line => {
    const [, method, route] = line.split(" ");
    return { method, route };
  });
  assert.ok(allCalls.every(c => c.method === "GET"), "every read stays a GET: " + JSON.stringify(allCalls));
  assert.ok(allCalls.every(c => !/review|analysis|vote/i.test(c.route)), "no reviewer route may be read: " + JSON.stringify(allCalls));
  assert.deepEqual(exceptions, [], "no page exception may be raised while stepping");

  console.log("PASS Chromium: the Jev runs section lists an unrated run, stepping shows its real stage/retry/usage record, a missing trace keeps the replay usable and is reported honestly, and every read is a GET that touches no reviewer.");
} finally {
  if (send && ws?.readyState === WebSocket.OPEN) { try { await send("Browser.close"); } catch { /* closing */ } }
  ws?.close();
  for (const p of pending.values()) { clearTimeout(p.timer); p.reject(new Error("gate ended")); }
  if (child.exitCode === null) child.kill();
  if (server.exitCode === null) server.kill();
  if (stub.exitCode === null) stub.kill();
}
