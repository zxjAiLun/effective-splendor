// Optional local Chromium interaction gate: built app + mocked Host boundary.
// No real League is opened; no browser package/download. Node >=22 + installed Chromium.
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
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-player-browser-"));
const child = cp.spawn(browser, ["--headless", "--no-first-run", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
let ws; let send; let serial = 0; const pending = new Map(); const exceptions = [];
try {
  let ready = false;
  for (let i = 0; i < 150; i++) {
    if (server.exitCode !== null) throw new Error(serverLog);
    try { ready = (await fetch(`http://127.0.0.1:${port}/play`)).ok; } catch { /* starting */ }
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
  const wait = async expression => { for (let i = 0; i < 150; i++) { if (await evaluate(expression)) return; await delay(50); } throw new Error(`DOM timeout: ${expression}\n${await evaluate('document.body.innerText')}`); };
  await send("Runtime.enable"); await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const nativeFetch=window.fetch.bind(window);window.calls=[];window.bookingMode='pending';
    const gems={white:0,blue:0,green:0,red:0,black:0,gold:0};
    const player=id=>({id,tokens:gems,bonuses:[0,0,0,0,0],prestige:0,reserved_count:0,public_reserved:[],purchased:[],nobles:[]});
    let state=null;
    const receipt={source_kind:'human_play',source_identity:'runtime:human-browser',match_id:'ab'.repeat(32),outcome:{kind:'inserted',rating_events:2},replay:{document_hash:'cd'.repeat(32)},elo:[{participant_id:'engine',elo_before:1500,elo_after:1484},{participant_id:'human',elo_before:1500,elo_after:1516}]};
    const detail={match:{source_kind:'human_play',source_identity:'runtime:human-browser',match_id:receipt.match_id,seats:[{seat:0,participant_id:'engine'},{seat:1,participant_id:'human'}]}};
    const reply=(body,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
    window.fetch=(url,opts={})=>{
      if(!String(url).startsWith('http://127.0.0.1:43120'))return nativeFetch(url,opts);
      const route=String(url).slice('http://127.0.0.1:43120'.length);window.calls.push({route,method:opts.method||'GET',body:opts.body??null});
      if(route==='/agents')return reply({agents:[{id:'test-agent',display_name:'Test agent'}]});
      if(route==='/catalog')return reply({cards:[],nobles:[]});
      if(route==='/reviewers')return reply({reviewers:[]});
      if(route==='/state')return state?reply(state):reply({error:'no session'},400);
      if(route==='/games'){
        const body=JSON.parse(opts.body);state={session_id:'human-browser',seed:opts.body.match(/"seed":([0-9]+)/)[1],human_seat:body.human_seat,opponent:'Test agent',ply:0,observation:{public:{player_count:2,current_player:body.human_seat,bank:gems,deck_counts:[0,0,0],market:[[null,null,null,null],[null,null,null,null],[null,null,null,null]],nobles:[],players:[player(0),player(1)]},private:{reserved:[]}},legal_actions:[{type:'pass'}],action_history:[],result:null,replay_ready:false,league_completion:null};return reply(state);
      }
      if(route==='/action'){state={...state,result:{winners:[1],scores:[2,15],reason:'prestige'},replay_ready:true,league_completion:{status:'failed',retryable:true,error:'database locked',receipt:null}};return reply(state);}
      if(route.includes('/league-completion')){
        if(window.bookingMode==='transport')return Promise.reject(new Error('response lost'));
        let status=200;let completion={status:'inserted',retryable:false,receipt,error:null};
        if(window.bookingMode==='canonical'){status=409;completion={status:'failed',retryable:false,receipt:null,error:'canonical order; rebuild the derived database'};}
        if(window.bookingMode==='already')completion={...completion,status:'already_present',receipt:{...receipt,outcome:{kind:'already_present',rating_events:0}}};
        state={...state,league_completion:completion};return reply({session_id:state.session_id,league_completion:completion},status);
      }
      if(route.startsWith('/league/matches/'))return reply(detail);
      return reply({error:'unhandled test route '+route},404);
    };
  })();` });
  await send("Page.navigate", { url: `http://127.0.0.1:${port}/play` });
  await wait(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Start new game'&&!b.disabled)`);
  assert.match(await evaluate("document.body.innerText"), /Rated Studio League match/);
  assert.doesNotMatch(await evaluate("document.body.innerText"), /Earlier games/);
  assert.equal(await evaluate(`document.querySelectorAll('select')[1].value`), "random");
  await evaluate(`(() => {const s=document.querySelectorAll('select')[1];s.value='second';s.dispatchEvent(new Event('change',{bubbles:true}));const input=document.querySelector('input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'18446744073709551615');input.dispatchEvent(new Event('input',{bubbles:true}));})();`);
  await delay(60);
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Start new game').click()`);
  await wait(`document.body.innerText.includes('Actual seat: Second (P1)')`);
  assert.match(await evaluate("document.body.innerText"), /18446744073709551615/);
  const request = await evaluate(`window.calls.find(c=>c.route==='/games')`);
  assert.equal(request.body, '{"agent_id":"test-agent","human_seat":1,"seed":18446744073709551615}');
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Pass turn').click()`);
  await wait(`document.body.innerText.includes('League booking failed')`);
  assert.match(await evaluate("document.body.innerText"), /VICTORY/);
  await evaluate(`window.bookingMode='transport';Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Retry booking').click()`);
  await wait(`document.body.innerText.includes('League booking unconfirmed')`);
  await evaluate(`window.bookingMode='canonical';Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Retry booking').click()`);
  await wait(`document.body.innerText.includes('canonical order')`);
  assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Retry booking')`), false);
  // Fresh page restores the real Host snapshot; use another finished fixture for success.
  await send("Page.reload");
  await wait(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Start new game'&&!b.disabled)`);
  await evaluate(`const s=document.querySelectorAll('select')[1];s.value='second';s.dispatchEvent(new Event('change',{bubbles:true}))`);
  await delay(60);await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Start new game').click()`);
  await wait(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Pass turn')`);
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Pass turn').click()`);
  await wait(`document.body.innerText.includes('League booking failed')`);
  await evaluate(`window.bookingMode='already';Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Retry booking').click()`);
  await wait(`document.body.innerText.includes('1516.0')`);
  const text = await evaluate("document.querySelector('.human-booking').innerText");
  assert.match(text, /Already recorded/); assert.match(text, /You: 1500.0 → 1516.0 \(\+16.0\)/); assert.match(text, /Opponent: 1500.0 → 1484.0/);
  const calls = await evaluate("window.calls");
  assert.equal(calls.filter(c => c.route === "/games").length, 1);
  assert.ok(calls.filter(c => c.route.includes("league-completion")).every(c => c.method === "POST" && c.body === null));
  assert.deepEqual(exceptions, []);
  if (artifactDir) {
    fs.mkdirSync(artifactDir, { recursive: true });
    await evaluate(`document.querySelector('.human-booking').scrollIntoView({block:'center'})`);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(artifactDir, "play-booking.png"), Buffer.from(shot.data, "base64"));
    fs.writeFileSync(path.join(artifactDir, "browser.json"), JSON.stringify({ status: "PASS", boundary: "real Chromium + built UI; mocked Host, not human acceptance", cases: ["u64 exact start", "pending+VICTORY", "transport unknown", "409 retry disabled", "already-present correct human Elo", "retry empty body"], calls, exceptions }, null, 2));
  }
  console.log("PASS Chromium: real Play buttons; exact u64; VICTORY + pending; transport unknown; canonical refusal; AlreadyPresent + seat-bound Elo; empty same-session retry.");
} finally {
  if (send && ws?.readyState === WebSocket.OPEN) { try { await send("Browser.close"); } catch { /* closing */ } }
  ws?.close(); for (const p of pending.values()) { clearTimeout(p.timer); p.reject(new Error("gate ended")); }
  if (child.exitCode === null) child.kill(); if (server.exitCode === null) server.kill();
}
