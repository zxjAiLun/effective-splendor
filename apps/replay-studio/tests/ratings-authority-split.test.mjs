import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

/**
 * The two rating systems still use separate authorities after M80 retired the
 * Studio model roster: `/ratings` reads the live league ledger; `/ratings/reports`
 * only renders an explicitly uploaded archived report. A page may name the other
 * page, but its code must not reach across.
 */
test("the Studio /ratings page contains no research-report authority", () => {
  const studio = read("app/ratings/page.tsx") + read("app/ratings-runtime.mjs");
  assert.doesNotMatch(studio, /m19-rating-report/, "the Studio page must not import M19");
  assert.doesNotMatch(studio, /m22-rating-report/, "the Studio page must not import M22");
  assert.doesNotMatch(studio, /official_elo/, "official Elo is not a Studio League field");
  assert.doesNotMatch(studio, /rating-runtime/);
  assert.match(studio, /\/league\/leaderboard/);
});

test("the research reports page never reads the league and has no embedded archive", () => {
  const reports = read("app/ratings/reports/page.tsx") + read("app/rating-runtime.mjs");
  assert.doesNotMatch(reports, /\/league\//, "a research page has no league reads");
  assert.doesNotMatch(reports, /m22-rating-report|m19-rating-report/, "no pre-cleanup model report is embedded");
  assert.match(reports, /official_elo/);
  assert.match(reports, /EMPTY_REPORT/);
});
