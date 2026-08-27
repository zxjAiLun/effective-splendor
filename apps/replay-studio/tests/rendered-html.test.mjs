import assert from "node:assert/strict";
import test from "node:test";

async function render(path = "/") {
  const serverUrl = new URL("../dist/server/index.js", import.meta.url);
  serverUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: handleRequest } = await import(serverUrl.href);
  return handleRequest(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
  );
}

test("server-renders the Replay Studio product shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>Replay Studio · Effective Splendor<\/title>/i);
  assert.match(html, /Replay Studio/);
  assert.match(html, /Player view/);
  assert.match(html, /Referee reveal/);
  assert.match(html, /ACTION ANALYSIS/);
  assert.match(html, /Load replay \+ analysis/);
  assert.match(html, /Rating Studio/);
  assert.match(html, /Purchase cost/);
  assert.match(html, /permanent bonus/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("server-renders the M16 Rating Studio route", async () => {
  const response = await render("/ratings");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Rating Studio · Effective Splendor<\/title>/i);
  assert.match(html, /Rating Studio/);
  assert.match(html, /m22-scaled-self-play-v1/);
  assert.match(html, /M22 Self-Play/);
  assert.match(html, /48<!-- -->\/<!-- -->48/);
  assert.match(html, /M22 multi-seed/);
  assert.match(html, /M19 full pool/);
  assert.match(html, /Non-transitivity matrix/);
  assert.match(html, /Load rating report/);
});

test("server-renders the M20 Human Play Studio route", async () => {
  const response = await render("/play");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Human Play Studio · Effective Splendor<\/title>/i);
  assert.match(html, /Human Play Studio/);
  assert.match(html, /ONE CLICK · NO PORT SETUP/);
  assert.match(html, /Start new game/);
  assert.match(html, /Start Splendor Studio\.cmd/);
  assert.doesNotMatch(html, /Connect to port/);
});

test("server-renders the M23 one-click review route", async () => {
  const response = await render("/review");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Replay Studio · Effective Splendor<\/title>/i);
  assert.match(html, /Replay Studio/);
  assert.match(html, /ONE-CLICK REVIEW/);
  assert.match(html, /Advanced import/);
});

test("server-renders the M36A experiments route shell", async () => {
  const response = await render("/experiments");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Experiment Replay Library · Effective Splendor<\/title>/i);
  assert.match(html, /Experiment Replay Library/);
  assert.match(html, /EXPERIMENTS/);
  assert.match(html, /MATCHES/);
  assert.match(html, /No match selected/);
  assert.match(html, /Filter pairings/);
  assert.match(html, /Play vs AI/);
});
