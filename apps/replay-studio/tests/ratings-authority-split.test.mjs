import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

/**
 * D2's authority-separation gate, at the source level.
 *
 * The product now carries two rating systems that must never be blended back
 * together by accident: the Studio League's own Elo (live ledger, human and
 * engine seats) and the research reports' tournament rating (Batch BT, official
 * Elo). The route split keeps them apart; this gate keeps the *code* apart, so
 * a future edit cannot quietly import one authority into the other's page.
 *
 * Note what this gate deliberately does NOT forbid: prose that points a human
 * reader to the other page. The two systems must stay *distinguishable*, which
 * includes naming each other. What must not happen is code reaching across: no
 * report module in the Studio page, no league read in the reports page.
 */
test("the Studio /ratings page contains no research-report authority", () => {
  const studio = read("app/ratings/page.tsx") + read("app/ratings-runtime.mjs");
  assert.doesNotMatch(studio, /m19-rating-report/, "the Studio page must not import M19");
  assert.doesNotMatch(studio, /m22-rating-report/, "the Studio page must not import M22");
  assert.doesNotMatch(studio, /official_elo/, "official Elo is not a Studio League field");
  // The research runtime module is also off-limits for the Studio page.
  // (`ratings-runtime` does not contain the substring `rating-runtime`.)
  assert.doesNotMatch(studio, /rating-runtime/);
  // Positive control: the Studio page really is a client of the league ledger.
  assert.match(studio, /\/league\/leaderboard/);
});

test("the research reports page never reads the league", () => {
  const reports = read("app/ratings/reports/page.tsx") + read("app/rating-runtime.mjs");
  assert.doesNotMatch(reports, /\/league\//, "a research page has no league reads");
  // Positive controls: the research corpus itself is intact under the new route.
  assert.match(reports, /m22-rating-report/);
  assert.match(reports, /m19-rating-report/);
  assert.match(reports, /official_elo/);
});
