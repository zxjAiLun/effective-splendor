// Local-only UI gate helper. Starts a built Studio on an ephemeral loopback port
// and a disposable installed Chromium profile. Never starts a Host or downloads.
import assert from "node:assert/strict";
import cp from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function installedBrowser() {
  if (process.env.STUDIO_TEST_BROWSER) return process.env.STUDIO_TEST_BROWSER;
  const cache = path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), ".cache"), "ms-playwright");
  const candidates = fs.existsSync(cache) ? fs.readdirSync(cache)
    .filter(name => /^chromium-\d+$/.test(name)).sort().reverse()
    .flatMap(name => ["chrome-win64/chrome.exe", "chrome-win/chrome.exe", "chrome-linux/chrome", "chrome-linux64/chrome"].map(p => path.join(cache, name, p))) : [];
  return [...candidates, "/usr/bin/chromium", "/usr/bin/google-chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    .find(p => fs.existsSync(p));
}

export async function launchStudioBrowser({ artifactDir } = {}) {
  const browserPath = installedBrowser();
  assert.ok(browserPath, "Set STUDIO_TEST_BROWSER to an installed Chromium; this gate never downloads.");
  const socket = net.createServer();
  await new Promise((resolve, reject) => { socket.once("error", reject); socket.listen(0, "127.0.0.1", resolve); });
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "studio-cockpit-browser-"));
  const server = cp.spawn(process.execPath, ["node_modules/vinext/dist/cli.js", "start", "--port", String(port), "--hostname", "127.0.0.1"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
  const browser = cp.spawn(browserPath, ["--headless", "--no-first-run", "--disable-background-networking", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  const observedAt = new Date().toISOString();
  let log = "";
  server.stdout.on("data", b => { log += b; });
  server.stderr.on("data", b => { log += b; });
  browser.stderr.on("data", b => { log += b; });
  let launchError;
  server.on("error", error => { launchError = error; });
  browser.on("error", error => { launchError = error; });
  let ws;
  let serial = 0;
  const pending = new Map();
  const exceptions = [];

  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++serial;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const wait = async expression => {
    for (let i = 0; i < 200; i++) {
      if (await evaluate(expression)) return;
      await delay(50);
    }
    throw new Error(`DOM timeout: ${expression}\n${await evaluate("document.body?.innerText")}`);
  };
  const screenshot = async filename => {
    assert.ok(artifactDir, "An artifact directory is required for screenshots");
    await evaluate("document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))");
    const shot = await send("Page.captureScreenshot", { format: "png" });
    const output = path.join(artifactDir, filename);
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, Buffer.from(shot.data, "base64"));
    return output;
  };
  const close = async () => {
    if (ws?.readyState === WebSocket.OPEN) {
      try { await send("Browser.close"); } catch { /* process may already have exited */ }
      ws.close();
    }
    for (const p of pending.values()) { clearTimeout(p.timer); p.reject(new Error("Browser gate ended")); }
    pending.clear();
    for (const child of [server, browser]) {
      if (child.exitCode !== null || child.signalCode !== null || !child.pid) continue;
      const exited = new Promise(resolve => child.once("exit", resolve));
      child.kill();
      await Promise.race([exited, delay(3000)]);
    }
    if (artifactDir) {
      fs.mkdirSync(artifactDir, { recursive: true });
      fs.writeFileSync(path.join(artifactDir, "browser-processes.json"), JSON.stringify({ node: "local", observedAt, closedAt: new Date().toISOString(), origin, browserPath, profile, serverPid: server.pid, browserPid: browser.pid, serverExit: server.exitCode, serverSignal: server.signalCode, browserExit: browser.exitCode, browserSignal: browser.signalCode, serverExited: server.exitCode !== null || server.signalCode !== null, browserExited: browser.exitCode !== null || browser.signalCode !== null, researchGames: 0 }, null, 2));
      fs.writeFileSync(path.join(artifactDir, "browser-server.log"), log);
    }
    // Profile is owned by this helper; never remove a user's browser profile.
    try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }); } catch { /* Windows may retain a transient file lock */ }
  };

  try {
    let ready = false;
    for (let i = 0; i < 150; i++) {
      if (launchError) throw launchError;
      if (server.exitCode !== null) throw new Error(log);
      try { ready = (await fetch(`${origin}/play`, { signal: AbortSignal.timeout(1000) })).ok; } catch { /* server starting */ }
      if (ready) break;
      await delay(100);
    }
    assert.ok(ready, log);
    const activePort = path.join(profile, "DevToolsActivePort");
    for (let i = 0; i < 150 && !fs.existsSync(activePort); i++) {
      if (launchError) throw launchError;
      if (browser.exitCode !== null) throw new Error(log);
      await delay(100);
    }
    const debugPort = fs.readFileSync(activePort, "utf8").split("\n")[0];
    const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
    ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.addEventListener("open", resolve, { once: true }); ws.addEventListener("error", reject, { once: true }); });
    ws.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const p = pending.get(message.id);
        pending.delete(message.id);
        clearTimeout(p.timer);
        if (message.error) p.reject(new Error(JSON.stringify(message.error))); else p.resolve(message.result);
      }
      if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails);
    });
    await send("Runtime.enable");
    await send("Page.enable");
    return { origin, send, evaluate, wait, screenshot, exceptions, close };
  } catch (error) {
    await close();
    throw error;
  }
}
