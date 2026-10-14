// Retired-roster Play gate. Real installed Chromium + built UI, synthetic Host
// responses only. After M80 the Studio registry is empty, so no table can start:
// this gate verifies the setup surface stays coherent and sends no write.
// npm run test:play-ui (or build first, then node tests/play-cockpit-browser.mjs)
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchStudioBrowser } from "./helpers/studio-browser.mjs";
import { mockPlayHostScript } from "./fixtures/play-cockpit.mjs";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir = path.resolve(process.env.STUDIO_COCKPIT_ARTIFACTS || path.join(appRoot, "../../local-artifacts/m80-local-history-cleanup/play-browser"));
fs.mkdirSync(artifactDir, { recursive: true });
const sources = ["app/play/page.tsx", "app/play/play.css", "app/globals.css", "app/studio-shell.css", "app/layout.tsx", "app/components/studio-chrome.tsx", "app/agent-visibility.mjs", "tests/play-cockpit-browser.mjs", "tests/fixtures/play-cockpit.mjs", "tests/helpers/studio-browser.mjs"];
const sourceHashes = Object.fromEntries(sources.map(name => [name, crypto.createHash("sha256").update(fs.readFileSync(path.join(appRoot, name))).digest("hex")]));
const cases = [];
const screenshots = [];
const b = await launchStudioBrowser({ artifactDir });

function setupGeometry() {
  const rect = element => element.getBoundingClientRect().toJSON();
  const errors = [];
  const content = document.querySelector(".studio-content");
  if (!content) errors.push("setup content is missing");
  else {
    const box = rect(content);
    if (box.left < -1 || box.right > innerWidth + 1) errors.push("setup content leaves the viewport horizontally");
  }
  for (const control of document.querySelectorAll("select, input, button")) {
    const box = rect(control);
    if (box.left < -1 || box.right > innerWidth + 1) errors.push(`control overflows: ${control.tagName}`);
  }
  return { viewport: { width: innerWidth, height: innerHeight }, documentWidth: document.documentElement.scrollWidth, errors };
}
const settle = () => b.evaluate("document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))");
const setup = () => b.evaluate(`(${setupGeometry.toString()})()`);
const checkSetup = async name => {
  await settle();
  const sample = await setup();
  assert.ok(sample.documentWidth <= sample.viewport.width, `${name}: horizontal overflow ${JSON.stringify(sample)}`);
  assert.deepEqual(sample.errors, [], `${name}: ${sample.errors.join("; ")}`);
  return sample;
};
const calls = () => b.evaluate("window.fixtureCalls");
const record = (name, evidence) => cases.push({ name, status: "PASS", ...evidence });

try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: mockPlayHostScript() });
  for (const [width, height, scale] of [[1440,900,1], [1280,720,1], [820,1000,1], [390,844,1], [320,720,1], [1280,900,1.5]]) {
    await b.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    await b.send("Page.navigate", { url: `${b.origin}/play?retired=${width}x${height}x${scale}` });
    await b.wait("document.body && document.body.innerText.includes('0 registered agents ready')");
    await b.evaluate(`document.documentElement.style.setProperty('--ui-scale', ${JSON.stringify(String(scale))})`);
    const sample = await checkSetup(`play-retired-${width}x${height}-scale${scale}`);
    assert.equal(await b.evaluate("document.querySelectorAll('.human-workspace, .human-board').length"), 0, "no table may render without a registered model");
    assert.equal(await b.evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Start new game')?.disabled"), true, "start must be disabled with an empty roster");
    assert.match(await b.evaluate("document.body.innerText"), /Start a local game/);
    screenshots.push(await b.screenshot(`play-retired-${width}x${height}-scale${scale}.png`));
    record(`play-retired-${width}x${height}-scale${scale}`, { geometry: sample, registeredAgents: 0 });
  }
  assert.deepEqual((await calls()).filter(call => call.method === "POST"), [], "browsing an empty roster must send no write");
  assert.deepEqual(b.exceptions, []);
  fs.writeFileSync(path.join(artifactDir, "checks.json"), JSON.stringify({ status: "PASS", observedAt: new Date().toISOString(), boundary: "Real Chromium + built UI, mocked empty Host. Zero research games.", sourceHashes, cases, screenshots, exceptions: b.exceptions }, null, 2));
  console.log(`PASS ${cases.length} retired Play cases; ${screenshots.length} screenshots. Evidence: ${artifactDir}`);
} catch (error) {
  try { screenshots.push(await b.screenshot("failure.png")); } catch { /* retain first failure */ }
  fs.writeFileSync(path.join(artifactDir, "checks.json"), JSON.stringify({ status: "FAIL", observedAt: new Date().toISOString(), error: error.stack, sourceHashes, cases, screenshots, exceptions: b.exceptions }, null, 2));
  console.error(`FAIL; evidence: ${artifactDir}`);
  throw error;
} finally {
  await b.close();
}
