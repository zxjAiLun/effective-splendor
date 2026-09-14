# Replay Studio — League Play page v1 (first player-facing round trip)

**Status: DESIGNED / PROPOSED — not authorized. No code written.**
Baseline: `506f46f` (docs closure of Commit E Slice 1); accepted code revision `0b69dfe`.
Owner direction (2026-09-15): stop widening the backend; make a lean vertical slice a player can
actually walk — open Studio → see the league → pick two registered agents → start one match → see
the result on the same page → open that match's replay. Statistics and the Review repair backlog
must **not** be bundled into this cut.

## Problem and evidence

Everything below was verified directly in this worktree, not inferred from documentation.

**The backend half already exists and is closed.** `crates/splendor-cli/src/human_play_command.rs`
serves the league routes added by Commit D/E Slice 1:

```text
:2260  "GET"  /league/leaderboard              (200 rows / 503 no authority evidence)
:2263  "GET"  /league/matches/{match_id}
:2267  "GET"  /league/replays/{document_sha256}   -> the raw archived ReplayV1 document
:2274  "POST" /league/matches                  -> the one write entry (Commit E)
```

**The player-facing half does not exist at all.** `grep -rniE 'league|leaderboard|elo'` over
`apps/replay-studio/app` and `apps/replay-studio/tests` returns only unrelated card markup
("development-card", "EmptyDevelopmentCard"). The Studio app has pages `/` (Games history),
`/play` (human vs agent), `/replay`, `/review`, `/ratings`, `/experiments`, `/advanced` — and no
league surface of any kind. The existing `/ratings` page is a **static m19/m22 report**
(`m19-rating-report.ts`, `m22-rating-report.ts`, `rating-runtime.mjs`), not the live league, so it
cannot be reused as the leaderboard.

**Two concrete seams stand between the app and the requested flow.**

1. *"Start a match" has no agent-vs-agent UI.* `/play` is human-seat driven:
   `POST /games {agent_id, human_seat, seed}` (`app/play/page.tsx:130`) then `POST /action`
   (`:131`). The only agent-vs-agent write path is Commit E's `POST /league/matches`
   `{occurrence_id, game_id, seed, seats[]}` — which is **rated**: it books the ledger, mints Elo
   rating events, and archives the replay in the official `league.sqlite3`/archive.
2. *"Open the replay" needs a shape adapter.* `/replay?session=` fetches
   `GET /replays/{session}` (`app/replay/page.tsx:61`) and consumes
   `effective-splendor-human-replay-archive` v2 (`replay/page.tsx:26-45`): `{frames[], catalog,
   replay.result, session_id, opponent, human_seat, player_count, replay_document_hash}`. That
   document is built by `build_historical_replay_archive` (`human_play_command.rs:1258`) from
   `HUMAN_PLAY_DIR/{session}.replay.json` — the **human-play** archive. The league stores a raw
   `ReplayV1` addressed by document SHA-256 (`GET /league/replays/{sha}`), which that page cannot
   render. Likewise the home "history" list is human-play only: `recent_games()`
   (`:1164-1186`) enumerates `HUMAN_PLAY_DIR/*.replay.json`, so a league match will never appear
   there.

**Transport facts the cut must respect.** Each page hardcodes `const API =
"http://127.0.0.1:43120";` (5 copies: `page.tsx:7`, `experiments/page.tsx:28`, `play/page.tsx:25`,
`replay/page.tsx:18`, `review/page.tsx:130`), and the Host's CORS header allows exactly
`http://127.0.0.1:4173`. The Studio dev server must therefore run on 4173 and the Host on 43120
(`--port` is a required Host argument). The Host's accept loop is **serial**: while a match runs,
`/health` and the read routes are blocked (a limitation the owner already accepted for Commit E).

**Test harness facts.** `npm test` = `vinext build && node --test tests/*.test.mjs` (6 files,
2,114 lines total in the app). There is **no browser/DOM runner and no Playwright** in this
repository; the strongest existing web test is `rendered-html.test.mjs` (SSR HTML assertions) plus
pure-module unit tests (`games-runtime.mjs` etc. — the pattern that Repair 1 introduced so that
"truthfulness rules are testable instead of buried in JSX").

## Initial design

One new page, one additive read-only Host route, one pure module, and a nav link.

1. **`app/league/page.tsx`** — the whole slice on one page: league leaderboard table (from
   `GET /league/leaderboard`), a start form (two agent pickers fed by `GET /agents`, a seed, a
   visible occurrence id), a start button, and a result panel that stays on the page. The result
   panel shows the two facts **separately** (`match_status` and `completion_status`), the
   `match_id`, the Elo deltas, and an **Open replay** link. It never shows a completion failure as
   a match failure.
2. **`app/league-runtime.mjs`** — all decision logic as pure functions, in the same spirit as
   `games-runtime.mjs`: `newOccurrenceId(now, salt)`, `validateStart(start)` (occurrence id is one
   safe path component, two to four distinct-or-equal registry ids, seed), `startRequestBody(start)`
   (exactly `{occurrence_id, game_id, seed, seats}` and nothing else), `describeResult(body)` (the
   two-fact wording, `not_applicable` for a settled aborted match), `describeLeaderboard(rows)`
   (no recomputation, no invented fields), `describeFailure(status, body)`.
3. **One additive read-only Host route** (see D3): the league replay rendered in the archive shape
   the existing board already understands, reusing `build_historical_replay_archive` verbatim on
   the already-verified archived `ReplayV1`.
4. **A nav link** from the existing header to `/league`. No other page changes except the
   shared API-base decision (D7).

Rejected alternatives: a second, unrated execution path (would duplicate the producer the owner
just consolidated); rendering raw `ReplayV1` in a new board (duplicates the replay renderer);
reusing `POST /games` (human-seat only, cannot express two agents).

## Scope and non-goals

**In scope:** `/league` page; `league-runtime.mjs` + its unit tests; the D3 read route (only if
approved); the nav link; the API-base single-source decision (only if approved); docs and the run
recipe.

**Explicit non-goals (frozen):** statistics/charts; the Review repair backlog; redesigning
existing pages; a league *match list* route; upload/ingest; pagination; deletion; auth;
worker queue, progress streaming or cancellation; batch/scheduler; multi-match tournaments;
external `ReplayV1` ingestion; any change to the frozen Commit D/E contracts beyond the single
additive route in D3; hand-editing `dist/**`; packaging/deployment.

## Contracts and invariants

- **The page is a client of the closed authority, never a second one.** It does not compute Elo,
  does not read the database, does not synthesize a `match_id`, and does not decide eligibility.
- **Two facts stay two facts.** `match_status` (arena) and `completion_status` (league booking)
  are rendered separately; `503 completed + completion failed` must read as "the match happened
  and is safe to retry", never as a failed match.
- **The request cannot name a program.** The body has exactly four keys; `seats` are registry ids
  resolved by the Host. The client can no more express `program`/`argv` than the Host can accept it.
- **An occurrence id is an identity, not a token.** It is shown to the player, it is minted once,
  and a retry re-sends the identical body; a re-used id returns the recorded fact and never runs a
  second match (Commit E Slice 1, closed).
- **The replay link is content-addressed.** It carries the archive document SHA-256 from the
  booking receipt; nothing re-derives it from a filename.
- **Presentational truthfulness.** The leaderboard renders exactly the fields the ledger returns
  (`participant_id`, `display_name`, `elo`, `rated_games`, `recorded_games`,
  `rated_wins/ties/losses`, `provisional`); a row that cannot be read is shown as unreadable
  rather than omitted or guessed.
- **The dev-server origin stays 4173 and the Host stays 43120**; the page must surface a clear
  error when the Host is absent, unreachable, or answering 503 (no authority evidence).

## Implementation plan

1. Freeze this design (this document) and mark the round `DESIGNED` in `handoff.md`.
2. `app/league-runtime.mjs` + `tests/league-runtime.test.mjs` (pure; no Host, no browser).
3. `app/league/page.tsx` (+ `app/league/layout.tsx` if the other route groups need one); nav link.
4. The D3 read route on the Host, with its own gates, if approved.
5. `tests/rendered-html.test.mjs`: `/league` renders its shell and the start form, and the header
   links to it.
6. `npm test`, `npm run lint`, and the Rust suites; then a **run recipe** in this document so the
   owner can walk the flow by hand, which is the real acceptance for this round.

## Acceptance gates (frozen before implementation)

- **G1 — request/result truthfulness (unit, `node --test`, no Host).** `startRequestBody()` output
  has exactly the four contract keys; `newOccurrenceId()` output always satisfies the Host's rule
  (non-empty, ≤128 bytes, not `.`/`..`, no leading/trailing dot, `[A-Za-z0-9._-]`);
  `describeResult()` maps all four settled outcomes and never merges the two facts;
  `describeLeaderboard()` invents no fields.
- **G2 — SSR render.** `/league` renders the league shell, the two agent pickers, the seed field,
  the visible occurrence id, and an explicit "this books a rated league match" notice; the header
  links to `/league`.
- **G3 — contract fixture shared with the Host gate.** The request body the page sends is a
  checked-in fixture; the JS test asserts the module produces it byte-for-byte, and an existing
  Rust league gate asserts the Host accepts that same fixture. One source of truth, two consumers,
  so "the page sends what the Host accepts" cannot drift.
- **G4 — negative controls (each must fail its gate).** (a) collapse the two facts in
  `describeResult` → G1 fails; (b) widen `startRequestBody` with an extra key (e.g. `handshake_timeout_ms`)
  → G1 fails; (c) let an unsafe occurrence id through `validateStart` → G1 fails (the Host's own
  refusal is already gated by Commit E Slice 1's gate L).

## Validation and evidence

To be filled at implementation. This round's honest evidence ceiling is: unit tests + SSR render
tests + the shared contract fixture + the owner's manual walkthrough. There is no browser runner in
this repository, so no automated gate may claim "a player clicked the button"; the walkthrough
recipe and its result will be recorded as the acceptance evidence, and any part of the flow that
only a human can confirm will be labelled as such.

## Known limitations

- A match run blocks the whole Host (serial accept loop) — `/health` and the read routes are
  unavailable until it finishes. The page must therefore tolerate a slow start and must not
  treat a long wait as failure.
- No progress reporting and no cancellation in this cut.
- The page can only see matches it started in this browser session (the result panel is page
  state); a league match *list* is a separate, unauthorized backend surface.
- The Host is unauthenticated and loopback-bound; the page carries no credentials.
- The page cannot recover an interrupted attempt after a reload (no `sessionStorage` bridge — that
  bridge was deleted deliberately in the product-shell round). The occurrence id is displayed so it
  can be re-sent by hand.

## Result and decision

`PROPOSED`. Awaiting owner confirmation of D1–D8 below before any code is written.

## Next authorized gate

Owner confirmation of the decisions below. Nothing in this document is authorized yet.

## Decisions to confirm

- **D1 — is the player's button a *rated* league match?** Recommendation: **yes, rated**, through
  `POST /league/matches`, because it is the closed write path and the only agent-vs-agent route;
  the alternative (an unrated exhibition) would require a second execution path the owner has
  consistently refused. Consequence to accept: one click mutates the official league (ledger row,
  Elo events, archived replay). If that is too sharp for a first cut, say so explicitly and I will
  propose the exhibition path as its own round instead of smuggling it in here.
- **D2 — where the page lives.** Recommendation: a new `/league` page plus a nav link; leave `/`
  (Games history) untouched. Alternative: extend `/`.
- **D3 — how "Open replay" gets a renderable document.** Recommendation: **one additive read-only
  route** on the Host, e.g. `GET /league/replays/{document_sha256}/archive`, returning the same
  `effective-splendor-human-replay-archive` v2 shape by calling `build_historical_replay_archive`
  verbatim on the already-verified archived `ReplayV1`; then `/league` links to
  `/replay?archive=<sha>` (or a small `/league/replay?sha=` page). Commit D's read surface was
  frozen at three routes, so this needs your explicit approval; the alternative is a new board
  component that renders raw `ReplayV1`, which duplicates the renderer.
- **D4 — who mints the occurrence id, and its shape.** Recommendation: the page mints it
  (`studio-<epoch-ms>-<4 hex>`, editable in the form), displays it with the result, and retries by
  re-sending the identical body.
- **D5 — see the match while it runs.** Recommendation for this cut: a running state showing the
  occurrence id, no cancellation, no streaming; keep the Host's Studio-default timeouts
  (handshake 30 s / move 120 s / shutdown grace 2 s).
- **D6 — which agents the pickers offer.** Recommendation: `GET /agents` (the Host registry is the
  roster the write route accepts), with Elo shown alongside when a participant exists in the
  leaderboard; no filtering and no new roster route.
- **D7 — the API base constant.** Recommendation: extract the single constant into
  `app/api-base.mjs`, import it in the new page **and** migrate the five existing one-line copies
  in the same commit (mechanical; the SSR render tests cover the affected pages), so there is one
  source of truth. Alternative: leave the five copies alone and add a sixth.
- **D8 — G3's shared fixture.** Recommendation: yes — one checked-in request-body fixture asserted
  by both the JS module test and a Rust Host gate. Alternative: two independent literals, which can
  drift silently.
