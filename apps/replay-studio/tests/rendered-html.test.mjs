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
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("server-renders the M16 Rating Studio route", async () => {
  const response = await render("/ratings");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Rating Studio · Effective Splendor<\/title>/i);
  assert.match(html, /Rating Studio/);
  assert.match(html, /Internal strength floor/);
  assert.match(html, /Non-transitivity matrix/);
  assert.match(html, /Load rating report/);
});
