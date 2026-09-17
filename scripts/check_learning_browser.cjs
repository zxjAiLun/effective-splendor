/* Actual Chromium DOM/interaction checks over file://. No npm dependency or server.
 * Node >=22; optional LEARNING_BROWSER=/path/to/chrome. Uses an existing local
 * Playwright Chromium cache when present; never downloads a browser.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const cp = require('node:child_process');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const artifactDir = path.join(root, 'local-artifacts/splendor-ai-learning');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function browserPath() {
  if (process.env.LEARNING_BROWSER) return process.env.LEARNING_BROWSER;
  const cache = path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData/Local'), 'ms-playwright');
  if (fs.existsSync(cache)) {
    const versions = fs.readdirSync(cache).filter(x => /^chromium-\d+$/.test(x)).sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
    for (const version of versions) for (const relative of ['chrome-win64/chrome.exe', 'chrome-win/chrome.exe', 'chrome-linux/chrome']) {
      const p = path.join(cache, version, relative);
      if (fs.existsSync(p)) return p;
    }
  }
  throw new Error('No existing Chromium found. Set LEARNING_BROWSER; no browser was installed.');
}

async function main() {
  const browser = browserPath();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'splendor-learning-browser-'));
  fs.mkdirSync(artifactDir, { recursive: true });
  // A failed rerun must not leave an older PASS report looking current.
  fs.rmSync(path.join(artifactDir, 'browser-check.json'), { force: true });
  const child = cp.spawn(browser, ['--headless', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });
  let launchError;
  child.on('error', e => { launchError = e; });
  let ws, send;
  const pending = new Map(), errors = [], requests = [];
  let serial = 0;
  try {
    const activePort = path.join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 150 && !fs.existsSync(activePort); i++) {
      if (launchError) throw launchError;
      if (child.exitCode !== null) throw new Error('Chromium exited before DevTools started');
      await delay(100);
    }
    if (!fs.existsSync(activePort)) throw new Error('DevTools startup timeout');
    const port = fs.readFileSync(activePort, 'utf8').split('\n')[0];
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    const target = targets.find(t => t.type === 'page');
    assert.ok(target, 'Chromium page target');
    ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }); });
    ws.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const p = pending.get(message.id); pending.delete(message.id); clearTimeout(p.timer);
        if (message.error) p.reject(new Error(JSON.stringify(message.error))); else p.resolve(message.result);
      }
      if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
      if (message.method === 'Network.requestWillBeSent') requests.push(message.params.request.url);
    });
    send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++serial;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 10000);
      pending.set(id, { resolve, reject, timer });
      ws.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result.value;
    };
    const navigate = async relative => {
      const url = pathToFileURL(path.join(root, relative)).href;
      const result = await send('Page.navigate', { url });
      assert.ok(!result.errorText, result.errorText);
      for (let i = 0; i < 100; i++) {
        if (await evaluate('location.href === ' + JSON.stringify(url) + ' && document.readyState === "complete"')) return;
        await delay(30);
      }
      throw new Error('Page load timeout: ' + relative);
    };
    const screenshot = async name => {
      const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      fs.writeFileSync(path.join(artifactDir, name), Buffer.from(result.data, 'base64'));
    };
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
    await navigate('lessons/index.html');
    assert.equal(await evaluate('document.querySelectorAll(".course-card").length'), 16);
    assert.equal(await evaluate('getComputedStyle(document.body).backgroundColor'), 'rgb(247, 245, 238)');
    await screenshot('index-desktop.png');
    const lessons = JSON.parse(fs.readFileSync(path.join(root, 'assets/splendor-course.json'), 'utf8')).lessons;
    for (const lesson of lessons) {
      await navigate(lesson.path);
      assert.equal(await evaluate('document.querySelector("button[type=submit]").disabled'), false);
      await evaluate('document.querySelector("form").requestSubmit()');
      assert.equal(await evaluate('document.querySelector("[data-feedback]").dataset.state'), 'empty');
      for (let option = 0; option < 3; option++) {
        const result = await evaluate(`(() => { const form=document.querySelector('form'); form.querySelector('input[value="${option}"]').click(); form.requestSubmit(); return {correct:Number(form.dataset.correct),state:form.querySelector('[data-feedback]').dataset.state,text:form.querySelector('[data-feedback]').textContent}; })()`);
        assert.equal(result.state, option === result.correct ? 'correct' : 'incorrect');
        assert.ok(result.text.length > 20);
      }
      await evaluate('document.querySelector("form").reset()');
      assert.equal(await evaluate('document.querySelector("[data-feedback]").textContent'), '');
      assert.equal(await evaluate('document.querySelectorAll("input:checked").length'), 0);
    }
    await navigate('lessons/0010-ppo.html');
    assert.ok((await evaluate('document.querySelector("output").textContent')).includes('本样本目标 min = 1.20'));
    await evaluate(`document.querySelector('[data-probability]').value='0.10'; document.querySelector('[data-advantage]').value='-1'; document.querySelector('[data-advantage]').dispatchEvent(new Event('change',{bubbles:true}))`);
    assert.ok((await evaluate('document.querySelector("output").textContent')).includes('本样本目标 min = -0.80'));
    await evaluate('document.querySelector(".lab").scrollIntoView({behavior:"instant",block:"center"})');
    await screenshot('ppo-desktop.png');
    await navigate('lessons/0001-observation.html');
    await evaluate('document.querySelector("input[type=radio]").focus()');
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: ' ', code: 'Space', windowsVirtualKeyCode: 32 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: ' ', code: 'Space', windowsVirtualKeyCode: 32 });
    assert.equal(await evaluate('document.querySelector("input[type=radio]").checked'), true);
    await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
    for (const relative of ['lessons/index.html', ...lessons.map(l => l.path), 'reference/glossary.html', 'reference/research-map.html']) {
      await navigate(relative);
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), true, 'Horizontal overflow: ' + relative);
    }
    await navigate('lessons/0001-observation.html');
    await screenshot('lesson-01-mobile.png');
    // JavaScript-disabled fallback: fresh load, native details contain a readable solution.
    await send('Emulation.setScriptExecutionDisabled', { value: true });
    await navigate('lessons/0001-observation.html');
    assert.equal(await evaluate('document.querySelector("button[type=submit]").disabled'), true);
    assert.ok((await evaluate('document.querySelector(".solution").textContent')).includes('应选'));
    await evaluate('document.querySelector(".solution summary").click()');
    assert.equal(await evaluate('document.querySelector(".solution").open'), true);
    await send('Emulation.setScriptExecutionDisabled', { value: false });
    assert.deepEqual(errors, [], 'Uncaught browser exceptions');
    assert.deepEqual(requests.filter(url => /^https?:/.test(url)), [], 'Unexpected page network dependency');
    const report = { status: 'PASS', browser, transport: 'file:// + CDP', lessons: 16, pagesAt390px: 19, quizChecks: 'empty + all choices + reset on all 16 lessons', ppo: 'positive + negative advantage output', keyboard: 'native radio Space selection', noJavaScript: 'disabled submit and readable native solution', exceptions: errors, pageHttpRequests: 0, screenshots: ['index-desktop.png', 'ppo-desktop.png', 'lesson-01-mobile.png'], limitations: ['Not human walkthrough acceptance', 'Not assistive-technology or print-layout certification', 'No learner mastery assessment'] };
    fs.writeFileSync(path.join(artifactDir, 'browser-check.json'), JSON.stringify(report, null, 2) + '\n');
    console.log('PASS: Chromium file://; 16 quizzes (empty/all choices/reset); PPO +/−; keyboard radio; 19 pages at 390px; no-JS fallback; 0 page HTTP requests; 0 exceptions.');
    console.log('Artifacts: local-artifacts/splendor-ai-learning/');
  } finally {
    if (send && ws && ws.readyState === WebSocket.OPEN) {
      try { await send('Browser.close'); } catch (_) { /* Browser may close before acknowledging. */ }
    }
    if (ws) ws.close();
    for (const p of pending.values()) { clearTimeout(p.timer); p.reject(new Error('Browser test ended')); }
    pending.clear();
    for (let i = 0; i < 30 && child.exitCode === null; i++) await delay(100);
    if (child.exitCode === null) child.kill();
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}
main().catch(error => { console.error('FAIL: ' + error.stack); process.exitCode = 1; });
