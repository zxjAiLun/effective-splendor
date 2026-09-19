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
  assert.match(html, /GAMES/);
  assert.match(html, /Saved human vs engine games/);
  assert.match(html, /Play vs S3/);
  assert.match(html, /href="\/league"/);
  assert.match(html, /href="\/ratings"/);
  assert.match(html, /href="\/ratings\/reports"/);
  assert.match(html, /Research reports/);
  assert.match(html, /Legacy AnalysisTraceV1 viewer/);
  assert.doesNotMatch(html, /Load replay \+ analysis/);
  assert.doesNotMatch(html, /Player view/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("server-renders the legacy AnalysisTraceV1 viewer route", async () => {
  const response = await render("/advanced");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /LEGACY DIAGNOSTIC VIEWER/);
  assert.match(html, /AnalysisTraceV1/);
  assert.match(html, /Requires an/);
  assert.match(html, /identity binding/);
  assert.doesNotMatch(html, /Load replay \+ analysis/);
});

test("server-renders the /replay viewer route shell", async () => {
  const response = await render("/replay?session=human-test");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Replay Studio/);
  assert.match(html, /NO ANALYSIS/);
  assert.match(html, /Rebuilding the replay/);
  assert.doesNotMatch(html, /ACTION ANALYSIS/);
});

test("server-renders the M16 Rating Studio route (moved verbatim to /ratings/reports)", async () => {
  const response = await render("/ratings/reports");
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

// D2 — the Studio League ratings product page. The server can only render the
// checking state, so the shell must claim nothing about any rating yet, and none
// of the research corpus's vocabulary may appear here: no official Elo column,
// no M19/M22, no Batch BT. Those live under /ratings/reports now.
test("server-renders the Studio League ratings route shell", async () => {
  const response = await render("/ratings");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Ratings · Effective Splendor<\/title>/i);
  assert.match(html, /STUDIO LEAGUE · CURRENT STANDINGS/);
  assert.match(html, /Loading the standings from the Studio Host/);
  assert.match(html, /href="\/ratings\/reports"/);
  assert.match(html, /Research reports/);
  assert.match(html, /not<\/strong> the research reports/);
  // No rating is invented before a read returned one.
  assert.doesNotMatch(html, /1500/);
  // No research-corpus concept crosses into the Studio page.
  assert.doesNotMatch(html, /Rating Studio/);
  assert.doesNotMatch(html, /official_elo|<span>Official<\/span>/i);
  assert.doesNotMatch(html, /M19|M22|m19-|m22-|Batch BT/);
  assert.doesNotMatch(html, /Non-transitivity matrix/);
  assert.doesNotMatch(html, /Load rating report/);
});

test("server-renders the M20 Human Play Studio route", async () => {
  const response = await render("/play");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Human Play Studio · Effective Splendor<\/title>/i);
  assert.match(html, /Human Play Studio/);
  assert.match(html, /ONE CLICK · NO PORT SETUP/);
  assert.match(html, /Start new game/);
  assert.match(html, /Splendor Studio\.cmd/);
  assert.match(html, /Rated Studio League match/);
  assert.match(html, /Your Elo may change/);
  assert.match(html, /Randomize seed/);
  assert.match(html, /Random/);
  assert.doesNotMatch(html, /Earlier games/);
  assert.doesNotMatch(html, /Connect to port/);
});

test("server-renders the M23 one-click review route", async () => {
  const response = await render("/review");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>Replay Studio · Effective Splendor<\/title>/i);
  assert.match(html, /Replay Studio/);
  assert.match(html, /ONE-CLICK REVIEW/);
  assert.match(html, /Games/);
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

// League Play v1. There is no browser runner in this repository, so these gates
// assert the server-rendered shell only: the wording a player is told before a
// rated match, and that nothing is claimed about a rating before one is read.
test("server-renders the League Play route shell", async () => {
  const response = await render("/league");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /<title>League · Effective Splendor<\/title>/i);
  assert.match(html, /League Play/);
  assert.match(html, /RATED MATCHES/);
  assert.match(html, /Elo may change/);
  assert.match(html, /Start rated match/);
  assert.match(html, /Studio League standings/);
  assert.match(html, /Preparing an occurrence id/);
  assert.match(html, /href="\/ratings"/);
  // No rating is invented before one is read, and no default is shown as a fact.
  assert.doesNotMatch(html, /1500/);
  assert.doesNotMatch(html, /Unrated/);
  // Readiness truthfulness: the server can only ever render the *checking* state, so
  // a page that claims the Host is ready here would be claiming something no read has
  // confirmed. This is the assertion that the first real walkthrough's page failed in
  // the browser (it said ready while both pickers were disabled and every read was
  // hanging).
  assert.match(html, /Checking Studio Host/);
  assert.doesNotMatch(html, /Studio Host ready/);
  assert.match(html, /Loading the agent roster/);
  // ...and the checking state must not announce a *failure* either. A pending read is
  // not a refused one: `describeHostBanner` describes failures and treats anything it
  // does not recognise as a refusal, so feeding it the pending state rendered
  // "The request was refused: ." directly beside "Checking Studio Host…". That is the
  // same lie as a premature "ready", told in the opposite direction.
  assert.doesNotMatch(
    html,
    /The request was refused/,
    "a pending roster read must not be reported as a refusal",
  );
  assert.doesNotMatch(
    html,
    /error-banner/,
    "no failure banner may exist before any read has settled",
  );
});

test("server-renders the replay board opened by league content hash", async () => {
  const response = await render(`/replay?league=${"ab".repeat(32)}`);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Rebuilding the replay/);
  assert.doesNotMatch(html, /ACTION ANALYSIS/);
});
