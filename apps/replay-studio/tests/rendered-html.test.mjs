import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const serverUrl = new URL("../dist/server/index.js", import.meta.url);
  serverUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: handleRequest } = await import(serverUrl.href);
  return handleRequest(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
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
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});
