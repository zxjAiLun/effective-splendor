# Replay Studio — League Play page v1 (first player-facing round trip)

**Status: IMPLEMENTED (Repair 1 + close patch) — not yet re-reviewed, not accepted.**
Review of `b7a29d7`: `REPAIR_REQUIRED` (P0=0 / P1=3 / P2=1) — all four closed in Repair 1.
Review of `50a4f3b`: original findings **P0=0 / P1=0 / P2=0, all closed**; one new narrow P1
(the failure panel's own label) — closed by the Repair 1 close patch below.
Revisions: Repair 1 = `50a4f3b`; its close patch = `cf587d2` (this one-line anchor commit
follows it, since a commit cannot contain its own hash).
Baseline: `ea98798` (this document's design-only commit; kept unamended, per owner instruction).
Authorization: owner, 2026-09-15 — `D1 YES / D2 YES / D3 YES-with-contract / D4 MODIFY / D5 YES /
D6 YES / D7 YES / D8 YES`, implemented directly in this round without a second design round.
Code revision: `b7a29d7` (the implementation, pushed to `origin/main`). This anchor was added in the
one-line follow-up commit that immediately follows it, because a commit cannot contain its own hash;
the document describes revision `b7a29d7`, not the commit it is read from.
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

## Iteration log

Append-only. Material decisions and deviations only.

1. **Recon before writing.** Verified in-tree (not from documentation) that the four league routes
   exist at `human_play_command.rs:2260-2282`; that `grep -rniE 'league|leaderboard|elo'` over
   `apps/replay-studio/app` returns only card markup; that the seam is `/play` being human-seat
   driven; that `/replay?session=` consumes a **different** document shape than the league archive
   holds. All three facts held.
2. **The archive adapter's chain is the security property, not a detail.**
   `build_historical_replay_archive` was read before use: it calls `verify_replay_trace` internally
   and checks `verified.positions.len() == replay.steps.len()`, so the frames the board receives are
   rebuilt from a *checked* replay. The handler therefore only had to get one thing right — obtain
   the document through `StudioLeagueReaderV1::read_replay`, never from a path — and the rest of the
   authority follows. Negative control D is what tests this.
3. **Route ordering is load-bearing.** `GET /league/replays/{sha}` is matched by a bare
   `starts_with("/league/replays/")` prefix arm. The new `/archive` arm had to be placed **before**
   it, or `"{sha}/archive"` would have been read as the content address. Recorded because the
   failure mode (`404 no archived replay at content address …/archive`) looks like a data problem.
4. **D6 could not be implemented as written, and this is a deviation the owner must see.** The
   pickers are `GET /agents` — registry ids (`gate-heuristic`) — and leaderboard rows are identified
   by participant id (`eng-<hash>`, derived from engine identity). The two closed read routes
   **share no join key**, and the ledger's `display_name` is a participant label, not a registry id.
   Attaching Elo to a picker option would have meant guessing by display name and attributing a
   rating to the wrong agent, which the league's identity discipline forbids. So the picker lists
   registry agents plainly and the leaderboard table carries the Elo, with the page saying so in one
   sentence. Closing this properly needs **one additive field** on `GET /agents` (a derived
   `participant_id`) — a deliberate backend change this round was not authorized to make. Recorded
   as a limitation rather than smuggled in.
5. **`python3` on this machine is the Microsoft Store stub** (exits 49, prints nothing, applies
   nothing). The first pass of negative controls A/B/C/E therefore "passed" while proving nothing.
   The controls were re-run with the real `python` (`C:/Python312/python`) plus a hard
   `assert anchor in source` guard, and all four then failed their intended gates. **A control that
   cannot fail is not a control** — and a control whose patch silently did not apply is worse than
   no control, because it reports success.
6. **One naive assertion was corrected, not worked around.** The `/league` SSR test initially
   asserted `href="/league"` on the league page itself, which does not link to itself; the assertion
   belongs in the home-shell test, where the nav link actually is.

## Repair 1 (owner review of `b7a29d7`, 2026-09-15: P0=0 / P1=3 / P2=1)

Owner confirmed the body of the slice — D3's adapter chain, D4's identity handling, the API-base
de-duplication, the shared fixture, a picker that cannot name a program, and the reused replay
renderer — and found four narrow **player-surface** seams. Nothing required redesigning anything.

**P1-1 — a real `503 completed + completion failed` was demoted to a generic Host failure, so the UI
merged the two facts.** The page branched on `response.ok` before ever reaching `describeResult()`,
and `describeFailure(503, …)` answered "the Host could not answer for this league / not retryable".
The pure module had the correct two-fact handling *and a unit test for it* — but the browser path
could never reach it. This is the one invariant the slice exists to protect, which makes it the
most serious finding of the round: **a unit test on a helper the real path never calls is not
evidence about the real path.**

*Fix*: the write-response decision moved into the pure module as `classifyBookingResponse(status, body)`.
A settled fact is decided by **the shape of the body** (`match_status` *and* `completion_status`
present), never by the status code:

```text
200 completed/inserted        -> settled, result panel
200 completed/already_present -> settled, result panel (+ one leaderboard refresh)
200 aborted/not_applicable    -> settled, result panel
503 completed/failed          -> settled, result panel + "Retry the booking (same occurrence, same seed)"
400 / 409 / 500 / 503-refusal -> refusal panel (500 and transport may retry; 400/409 may not)
```

The page consumes only that classification, and now refreshes the leaderboard **only** when
`inserted`/`already_present` — a booking that failed changed nothing to refresh.

**P1-2 — `GET /league/replays/archive` panicked the whole Host.** The archive arm tested
`starts_with` *and* `ends_with` and then sliced `path[16..len-8]`; that path satisfies both tests, so
the byte range inverts. Reproduced **before** fixing, by writing the assertion first and running it
against the unfixed build:

```text
thread 'main' (29528) panicked at crates\splendor-cli\src\human_play_command.rs:2328:17:
begin <= end (16 <= 15) when slicing `/league/replays/archive`
```

The panic is on the **`main` thread**. This Host has a serial accept loop and no per-request panic
isolation, so one malformed GET ended the entire product surface — the client saw a 0-byte response
and the process was gone. (It also left a `splendor.exe` holding `target/debug/splendor.exe`, which
made the next build fail with a Windows sharing violation: a reminder that a crashed Host is not
always a *quietly* crashed Host.)

*Fix*: parse by stripping, never by index arithmetic —
`strip_prefix("/league/replays/").and_then(|rest| rest.strip_suffix("/archive"))` with
`unwrap_or_default()`. That path now yields the empty content address and the handler answers 404;
other malformed shapes fall through to the bare replay route. `unwrap_or_default` is deliberately
not an oversight: it is the landing spot for exactly this input.

**P1-3 — a lost response, the case most in need of an exact retry, was the one case that forbade
it.** `describeFailure(null, …)` returned `retryable: false`, so the only button left was
`New match` — which mints a new occurrence, the worst case being a second rated match for an attempt
that may already have happened. A thrown `fetch` cannot distinguish "never arrived", "still running",
"completed with the response lost". All of those are safe with the *same* body, because the
occurrence id was made an identity in the first place.
*Fix*: the transport case is `retryable: true`, and its wording says the outcome is unknown from the
browser and that Retry re-sends the same occurrence.

**P2 — `matchId` was typed `number`.** The ledger's `IngestOutcome::match_id` is a `String`; an `as`
cast hid the lie. Now `string | null`.

**Not done, by instruction**: no D6 field, no statistics, no Review work, no browser harness, no extra
test matrix. The D6 decision stands as accepted (see the owner's own correction: a registry id cannot
be mapped to a Studio League participant id in the browser without an authority-derived field, so
showing nothing is right and inventing a join is not) and is explicitly **not** part of this repair.

## Repair 1 close patch (owner review of `50a4f3b`)

Owner verdict: **the three P1s and the P2 of the previous round are closed** (P0=0 / P1=0 / P2=0),
`0a1f7b9` confirmed docs-only, and the review accepted that `classifyBookingResponse` is now the real
entry point of the write path rather than a test-only helper. One very narrow **truthfulness** seam
remained. This patch closes it, and only it: no Host change, no browser harness, no design round.

**P1 (new) — the failure panel's own label claimed an absence the page cannot know.** Repair 1 fixed
the transport *body* (it says the outcome is unknown and asks for a same-occurrence retry), but every
failure panel shared one hardcoded kicker:

```text
NOT BOOKED                    <- unverified, and possibly false
The response was lost...
The match outcome is unknown...
Retry the same match
```

With the response lost, the match may well have completed — Arena finished, the completion was
inserted, the response was lost on the way back. The first line therefore contradicted the paragraph
directly beneath it, and it undercut the reason P1-3 was fixed at all: if the outcome is unknown, the
panel may not announce absence. A wrong *body* was one defect; a wrong *label* is the same defect in
the one place a reader trusts most.

*Fix*: the kicker is part of the classification and lives in the runtime module beside the paragraph
it labels.

```text
describeFailure(null, …)                          -> kicker "OUTCOME UNKNOWN", retryable
describeFailure(400 / 409 / 500 / 503-refusal, …) -> kicker "NOT BOOKED"
```

The page renders `{failure.kicker}`. `NOT BOOKED` is sound where it is still printed because a refusal
is a claim about absence and the Host emits every refusal *before* a settled fact can exist: the run
either never started (400 / 409 / 503) or never settled (500). `500` remains retryable without being
an ambiguous outcome, which is exactly why the label cannot be inferred from `retryable`.

**Rejected alternative**: `{failure.retryable ? "OUTCOME UNKNOWN" : "NOT BOOKED"}`. A `500` is
retryable while unambiguously meaning "nothing settled", and a `409` is unambiguous without being
retryable, so retryability and the absence claim are independent questions; deriving the label from
`retryable` would have re-introduced the same kind of lie pointing the other way.

**`New match` stays available** next to `OUTCOME UNKNOWN`, deliberately: once a player has been told
the outcome is unknown, knowingly starting another match is their call. The requirement is only that
the UI must not claim the previous attempt did not happen.

## Final implementation

```text
apps/replay-studio/app/api-base.mjs                          new  — the one API base constant
apps/replay-studio/app/league-runtime.mjs                    new  — the decisions, pure and testable
apps/replay-studio/app/league/page.tsx                       new  — the page (a client of the closed authority)
apps/replay-studio/app/league/layout.tsx                     new  — route metadata
apps/replay-studio/app/{page,play,replay,review,experiments}/page.tsx   API base imported, not copied
apps/replay-studio/app/replay/page.tsx                       + `?league=<sha256>` opens a league replay
apps/replay-studio/app/page.tsx                              + League nav link
apps/replay-studio/app/play/page.tsx                         + League nav link
apps/replay-studio/tests/league-runtime.test.mjs             new  — G1 (14 tests)
apps/replay-studio/tests/fixtures/league-match-request.json  new  — G3's one shared document
apps/replay-studio/tests/rendered-html.test.mjs              + G2 (2 tests)
apps/replay-studio/package.json                              + the new test file in the test script
crates/splendor-cli/src/human_play_command.rs                + league_replay_archive + its route arm
crates/splendor-cli/tests/league_host_api.rs                 + G3-Rust and D3 gates (12 -> 14)
```

Decided and implemented:

- **D1 (yes, rated).** The button is `Start rated match` and goes to `POST /league/matches`. The form
  states, before the click, that it writes a ledger row, Elo events and an archived replay and that
  Elo may change. No confirmation modal.
- **D2 (own page).** `/league` is a new page; `/` stays the human Games history and `/ratings` stays
  the static m19/m22 report. The nav gained one `League` link on `/` and `/play`; the shell was not
  restructured.
- **D3 (yes, with the contract).** `GET /league/replays/{sha256}/archive` is a **presentation
  adapter**: `sha256 → StudioLeagueReaderV1::read_replay() → authority evidence revalidation →
  content address match → deserialize ReplayV1 → build_historical_replay_archive(…, None, None) →
  archive-v2 JSON`. No `path → fs::read → builder` chain exists anywhere. The board is the existing
  `/replay` page reached as `?league=<sha256>`; a league replay has `session_id` = the content hash
  and no opponent or human seat, and the human-only affordances (`mine` filter, "Review this game")
  are hidden for it rather than guessed at.
- **D4 (modified).** The occurrence id is an identity: `studio-<epoch-ms>-<4 hex>`, minted once,
  rendered, copyable, **not editable**, and re-sent unchanged by Retry. The pending request holds the
  exact four-field body; `New match` mints the next attempt. No reload recovery.
- **D5 (yes).** `idle → running → completed / aborted / completion-failed / error` only. No polling,
  no progress, no cancel. The page does not touch the league while a POST is outstanding — it
  refreshes the leaderboard once, after the booking returned.
- **D6 (yes, with the join limitation below).** Pickers come from `GET /agents`; duplicates are
  allowed with a self-match note (the league records it as ineligible); no eligibility is inferred
  client-side and no rating is defaulted to 1500.
- **D7 (yes).** `app/api-base.mjs` exports the constant; the five existing copies now import it.
- **D8 (yes).** One checked-in fixture, asserted by the JS module test and posted verbatim by a Rust
  Host gate.

## Validation and evidence

Local execution only. This repository has **no cloud CI and no status checks**, so nothing below is a
CI result; and there is **no browser runner**, so no gate claims a player clicked anything.

```text
apps/replay-studio            npm test                              -> 61 tests, 61 pass, 0 fail (7 files; league file = 14)
apps/replay-studio            npm run lint                          -> clean
crates/splendor-cli           cargo test -p splendor-cli            -> 287 passed, 0 failed, 3 ignored (45 targets)
crates/splendor-studio-league cargo test -p splendor-studio-league  -> 86 passed, 0 failed
crates/splendor-cli           cargo test -p splendor-cli --test league_host_api -> 14 passed (8 read + 4 write + 2 page seams)
repo root                     git diff --check                      -> clean
```

The three ignored tests are pre-existing, explicitly-ignored benchmark targets
(`m05_fixed_benchmark_meets_strength_gate` and the M30A/M32A probes); none is in this round's scope,
and this round marked nothing ignored. An earlier record of this suite noted `2 ignored`; the delta
is in those pre-existing ignored benchmarks and is recorded as measured, not explained away.

**Negative controls (six, each run before commit and reverted with `cp` from a `/tmp` copy).**

| # | Control | What must fail | Result |
|---|---------|----------------|--------|
| A | collapse the two facts into one sentence in `describeResult` | G1 "a completed match whose booking failed stays two facts" | 3 failed, exit 1 |
| B | `startRequestBody` spreads its input (an extra key can reach the wire) | G1 fixture / key-set test | 5 failed, exit 1 |
| C | `occurrenceIdError` returns `null` (an unsafe id is accepted) | G1 host-rule mirror + validation tests | 5 failed, exit 1 |
| D | the archive handler reads the object **by path** instead of via `read_replay` | the D3 gate's stale-league assertion | gate failed: `left: 200, right: 503` |
| E | `retryRequest` mints a new occurrence id | G1 "minted once and survives a retry unchanged" | 3 failed, exit 1 |
| F | the shared fixture grows a key the Host does not know | G3, both sides | JS 3 failed; Rust gate `400` — `unknown field timeout_ms, expected one of occurrence_id, game_id, seed, seats` |

Control D is the one that justifies the D3 contract: with a path-based read, the stale league served
**200**, which is precisely the failure mode the adapter chain exists to prevent.

Two gates exist because the alternative was a false claim:

- **G3 is cross-language.** The Rust gate posts the fixture file's **bytes** (not a re-serialization),
  so a field added on the JS side alone is refused by `deny_unknown_fields`, and a field added to the
  fixture alone is caught by the JS side. Control F exercises exactly that.
- **G2 is a shell assertion, not a click.** It proves `/league` server-renders its shell, the rated
  notice, the standings heading and "Preparing an occurrence id…" (the id cannot exist server-side),
  and that the page renders **no** invented rating (`/1500/` and `/Unrated/` must not appear).
  Everything after a click is covered by the pure module's tests, not by an automated click.

### Repair 1 validation

```text
apps/replay-studio            npm test                             -> 65 tests, 65 pass, 0 fail (was 61; +4)
apps/replay-studio            npm run lint                         -> clean
crates/splendor-cli           cargo test -p splendor-cli           -> 287 passed, 0 failed, 3 ignored (45 targets; count unchanged)
crates/splendor-studio-league cargo test -p splendor-studio-league -> 86 passed, 0 failed
crates/splendor-cli           league_host_api                      -> 14 gates (assertions added inside the existing D3 gate)
repo root                     git diff --check                     -> clean
```

The malformed-path assertion lives inside the existing D3 gate on purpose: the instruction was "补一个
gate … 不用扩测试矩阵", and the behaviour under test is the same route contract, so the gate count
stays 14.

**Repair 1 negative controls (four, each reverted with `cp` from a `/tmp` copy).**

| # | Control | What must fail | Result |
|---|---------|----------------|--------|
| G | classify settled-ness by status code (`2xx`) instead of by the body | the 503-is-a-result tests | 5 failed, exit 1 |
| H | `describeFailure(null, …)` back to `retryable: false` | the lost-response tests | 5 failed, exit 1 |
| J | the page decides with `if (!response.ok)` again | the source-level structural guard | 3 failed, exit 1 |
| I | restore the index-arithmetic slice | the malformed-path assertion (the Host dies) | gate FAILED: `a complete response has a header terminator` |

Control J is a **source-level** guard and is labelled as one, in the test and here: this repository
has no browser runner, so nothing in this round demonstrates a player clicking anything. It pins the
single line that let P1-1 survive a green unit suite — the module's tests pass whether or not the
page uses the module at all. Writing it also caught a flaw in itself: its first version matched the
word `response.ok` inside the explanatory comment, so comments are now stripped before the code
check. A gate that a comment can trip is not measuring code.

### Repair 1 close-patch validation

```text
apps/replay-studio   npm test        -> 67 tests, 67 pass, 0 fail (was 65; +2)
apps/replay-studio   npm run lint    -> clean
repo root            git diff --check -> clean
changed files        apps/replay-studio/app/league-runtime.mjs
                     apps/replay-studio/app/league/page.tsx
                     apps/replay-studio/tests/league-runtime.test.mjs
```

No Rust file is touched by this patch, so the Rust suites were **not** re-run: a change confined to
two `.mjs`/`.tsx` files cannot alter their result, and re-running them would add no evidence about
this patch. The previous round's Rust results (287 passed / 0 failed / 3 ignored; 86/86; 14/14) stand
as recorded there, as local execution evidence.

**Close-patch negative controls (two, each reverted with `cp`).**

| # | Control | What must fail | Result |
|---|---------|----------------|--------|
| 1 | transport kicker back to `NOT BOOKED` | the two kicker assertions | 2 failed, exit 1 |
| 2 | the page hardcodes the label again | the page-source kicker guard | 1 failed, exit 1 |

Control 2 is a **source-level** guard for the same reason as the `response.ok` one: there is no
browser runner here, so it pins the property that the page owns no truth claim of its own, and it
cannot demonstrate anything about a rendered panel.

**A process defect this patch's own controls exposed, recorded because it is the dangerous kind.**
While reverting control 1, `cp` was pointed at a backup taken *before* the patch was applied, so the
"revert" deleted the fix instead of restoring it — and the following run then reported a failure that
looked like the control still being in place. The suite caught it (unrelated kicker tests failing
during control 2), but the general rule is: **a negative control's revert target must be the *patched*
state, not the pre-round original. Otherwise a revert that has gone too far is indistinguishable from
a control that was never reverted — and the "restored" tree is silently missing the fix.** Backups
are now taken after the patch and verified with `diff -q` before any run is trusted.

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

**Added by this round (all accepted, none hidden):**

- **The pickers cannot show Elo.** D6's join has no key: registry ids vs participant ids
  (`eng-<hash>`). The leaderboard table is the authoritative Elo view, and the result panel carries
  the authoritative deltas for the match just booked. Closing this needs one additive field on
  `GET /agents` — a deliberate, separately authorized backend change, not a page-side guess.
- **`/league` has no automated click coverage.** There is no browser runner in this repository. The
  visible outcome states (result panel, Retry, the two-fact wording, the single leaderboard refresh)
  are covered by `league-runtime.mjs` unit tests plus the owner's walkthrough; an automated claim that
  the button works would be false.
- **The archive adapter rebuilds on every request** (verify + reconstruct). Correct and cheap for one
  match; it is deliberately stateless and is not a cache.
- **The page shows only matches it started.** The result panel is page state; a league match *list*
  is a different, unauthorized backend surface.

## Run recipe (the acceptance walkthrough)

Two processes, both local:

```bash
# 1) the Host, on the port the page expects, with a real registry
cargo run -p splendor-cli -- studio-host --registry private/registry.json --port 43120

# 2) the Studio app
cd apps/replay-studio && npm run dev     # serves 127.0.0.1:4173, the only allowed CORS origin
```

1. Open `http://127.0.0.1:4173/league`.
2. Confirm the roster and the standings load. If the Host is not running, the page must say so and
   show the exact command, not fail silently.
3. Pick two agents in the seats. Confirm the page says **Rated** and that Elo may change, and that
   picking the same agent twice shows the self-match note rather than a validation error.
4. Read the displayed occurrence id (copyable, not editable) and the seed.
5. Press **Start rated match** and wait — the Host is serial, so the page must stay in `running`
   without polling, and a long wait is not a failure.
6. On the result, read `match_status` and `completion_status` as two facts, plus the Elo deltas. A
   completion failure must read as "the match completed, booking failed, safe to retry".
7. Confirm the leaderboard refreshed once and that the two participants' Elo moved by exactly the
   deltas the receipt showed.
8. Press **Open replay** and, in the replay board, step and drag through the plies of that match.
   **This step is the acceptance evidence this round cannot automate.**

## Result and decision

`IMPLEMENTED` — **Repair 1 and its close patch applied; not yet re-reviewed, not `ACCEPTED`.**

Review of `b7a29d7` returned `REPAIR_REQUIRED` (P0=0 / P1=3 / P2=1); review of `50a4f3b` closed all
four and raised one new narrow P1. Every finding is closed in this revision, each with a gate that
fails when the fix is reverted:

| Finding | Closed by | Gate that fails without it |
|---------|-----------|----------------------------|
| P1-1: `503 completed + completion failed` rendered as a generic Host failure | `classifyBookingResponse` decides settled-ness by the body's shape; the page consumes only that | the 503-is-a-result unit tests; the source-level guard that `send()` does not branch on `response.ok` |
| P1-2: `/league/replays/archive` panicked the `main` thread and killed the Host | `strip_prefix`/`strip_suffix` parsing; the malformed path lands on the empty content address and 404s | the malformed-path assertion in the D3 gate |
| P1-3: a lost response was the one case that forbade the exact retry | the transport case is `retryable: true` with same-body wording | the lost-response unit tests |
| P2: `matchId` typed `number` for a `String` | `string \| null` | (type-level only; no gate — see the ceiling below) |
| **P1 (new, review of `50a4f3b`): the failure panel printed `NOT BOOKED` over an unknown outcome** | the kicker is part of the classification (`OUTCOME UNKNOWN` for transport, `NOT BOOKED` for refusals) and the page renders `{failure.kicker}` | the two kicker assertions; the source-level guard that the page owns no absence claim |

**Honest ceiling on the evidence.** This is why status words stay strict here:

1. **No gate demonstrates a player clicking anything.** There is no browser runner. The write-path
   classification and the kicker are gated at the module level and, structurally, at the source level;
   the actual rendering of a `503 completed + failed` panel and of an `OUTCOME UNKNOWN` panel in a
   browser remains covered by the owner's walkthrough only.
2. **The P2 type fix has no automated gate.** `matchId: string | null` is enforced by the type check at
   build time, not by an assertion — the previous `number` was never observable at runtime (a JSON
   value plus an `as` cast), which is exactly why it survived.

Unchanged deviations from the original authorization, both accepted by the owner in review:

1. **D6's Elo-beside-the-picker is not implemented** — and the owner independently confirmed this is
   correct rather than a shortcut: a registry id cannot be mapped to a Studio League `participant_id`
   in the browser, and a field that closed the gap would have to be derived by the Host from the
   Studio identity authority, not hashed client-side. Deferred as its own authorization.
2. **The nav link is on `/` and `/play`** — no shared shell component exists, so there is nothing else
   to add a link to without restructuring the header.

## Next authorized gate

Owner review of this close patch, then the 8-step manual walkthrough in this document — **step 8,
actually dragging and stepping through the replay board, is still the acceptance evidence this round
cannot automate**. No further design round is in scope, and the D6 `GET /agents` follow-up is not to
be started as part of this round. On acceptance: record the closure in `docs/studio-league-v1.md` +
`handoff.md`.
