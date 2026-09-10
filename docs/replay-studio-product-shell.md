# Replay Studio Product Shell / History v1

- **Status**: `IMPLEMENTED` / `VERIFIED` (named checks below actually ran), then
  **`REPAIR_REQUIRED`** from the owner's independent review of `e125c2c`
  (P0 = 0, P1 = 1, P2 = 3), then **Repair 1 IMPLEMENTED / VERIFIED**
  (2026-09-10, see the repair section below). Not `ACCEPTED` — the owner's product
  closure review is still the next gate.
- **Baseline**: `9573141` (`main == origin/main`, S3 Review Integration v1 ACCEPTED/CLOSED).
- **Owner-date**: 2026-09-10, authorized by the product owner in the closure conversation of
  S3 Review Integration v1 ("直接授权开工，不需要他再回来问一次").
- **Owner decisions (frozen scope)**:
  1. M14A Demo / AnalysisTraceV1 importer → moved to `/advanced`, not deleted; no longer the home.
  2. Historical replay archive Host endpoint approved; **View replay must not run a reviewer**.
  3. **No arbitrary ReplayV1 upload this round** — external-replay ingestion stays a separate
     future feature.

## Problem and evidence

The Studio home `/` was still the M14A-era development demo: a hard-coded `DEMO_TRACE`
(`apps/replay-studio/app/page.tsx:109`) plus a file importer that only accepts an
**AnalysisTraceV1** sidecar (`apps/replay-studio/app/trace-runtime.mjs:243-247`, V1-only
envelope check) with ReplayV1 merely optional (`page.tsx:278-282`). Importing a pure ReplayV1
— e.g. the saved `local-artifacts/m20-human-play/human-12312300221-0-28024-1.replay.json`
(2026-09-09 23:35) — dead-ended with
`Select an AnalysisTraceV1 sidecar, optionally with its ReplayV1.` (`page.tsx:280`).

Meanwhile later product generations already existed:
- `GET /recent-games` (`crates/splendor-cli/src/human_play_command.rs:1031`) indexes all saved
  human-vs-engine replays (session/opponent/human_seat/scores/winners/player_count/verification/
  cached reviews, newest first) but was only surfaced as a top-8 list inside the `/play` start
  screen (`app/play/page.tsx:128,185`).
- `/review` runs the S3/M07/M13 review chain, but there was no reviewer-free way to view a saved
  game: the only replay paths were the in-memory `GET /archive` → `sessionStorage` →
  `/?humanReplay=1` bridge, or a completed review bundle.

So the user experience was split: a demo shell in front of a real product.

## Initial design

Per the owner's brief — re-order the product shell, do not patch the demo:

```text
/         → Games history home (full /recent-games list)
/play     → Human vs AI (unchanged play UI)
/replay   → pure replay viewer (?session=…)
/review   → S3/M07/M13 review (unchanged semantics)
/advanced → legacy AnalysisTraceV1 / diagnostic import
```

## Scope and non-goals

Scope (owner's 8 items):
1. `/` → Games history home consuming `/recent-games`, full list (no 8-item cap), no
   `DEMO_TRACE`/fake board, actions View replay + Review, invalid rows degrade gracefully.
2. Historical replay archive Host endpoint (`GET /replays/{session_id}`), safe session id,
   read + `verify_replay_trace`, reconstruct display frames, include catalog,
   **no reviewer computation**.
3. `/replay?session=` viewer reusing `components/replay-board` (no third board implementation):
   board, timeline, prev/next, mine/all, player/referee view, final score, no analysis panel.
4. `/play`: keep play UI; recent-games section reduced to a link to `/`.
5. Completed-game "Open replay" routes directly to `/replay?session=…`; the
   `sessionStorage` handoff (`effective-splendor-human-replay` + `/?humanReplay=1`) deleted.
6. `/advanced`: legacy M14A AnalysisTraceV1 viewer, explicitly labelled
   (`Requires an AnalysisTraceV1 sidecar. ReplayV1 may be supplied only for identity binding.`),
   V1 opening still works.
7. `/review`: no semantic rewrite.
8. No arbitrary ReplayV1 upload in this round.

Non-goals: external-replay ingestion (upload endpoint/import storage/identity/lifecycle), Arena,
strength experiments, S3/reviewer logic changes, new S3 tests, mass test-writing.

## Contracts and invariants

- Viewing a replay never invokes a reviewer; `Review` is the only path that does.
- Archives are reconstructed from the authoritative `splendor_replay::verify_replay_trace` —
  the ReplayV1 alone must suffice; no dependence on frames saved at play time; the archive is
  not a second fact source.
- Session ids pass `sanitize_session_id`/`is_safe_component`; no path traversal.
- `referee_reveal` is display-only data; never an input to any agent (unchanged project rule).
- Neutral review wording and all existing `/review` behavior untouched.
- `dist/**` not hand-edited (rebuild only, git-ignored).

## Iteration log

- 2026-09-10: Round authorized by the owner with frozen scope; implementation worker
  `studio-shell-v1` spawned.
- 2026-09-10: Worker **failed early with HTTP 429** (model usage quota) after landing only the
  Rust portion (`human_play_command.rs` endpoint + reconstruction + tests) and a wording tweak in
  `trace-runtime.mjs`; frontend and docs were missing. The lead completed the round directly:
  fixed the one compile error in the worker's Rust code (E0106 lifetime on
  `build_historical_replay_archive`), then implemented the frontend shell and docs. Recorded
  here for provenance; the Rust endpoint logic is the worker's, reviewed and verified by the lead.
- 2026-09-10: `rendered-html.test.mjs` first test asserted the old demo shell (`/Player view/`,
  `/ACTION ANALYSIS/`, `/Load replay + analysis/`); rewritten for the new home, plus new route
  shell tests for `/advanced` and `/replay`. `/review` header link relabelled `Advanced import`
  → `Games` (the target route changed meaning).
- 2026-09-10 (owner review of `e125c2c`): architecture direction **APPROVED**; Games home,
  historical replay endpoint, reviewer-free View replay, legacy V1 isolation and sessionStorage
  removal all **PASS**. Verdict **REPAIR_REQUIRED** (P0 = 0, P1 = 1, P2 = 3), repair scope
  declared `VERY SMALL`: Games/history presentation truthfulness only. Explicitly out of bounds
  for the repair: Host archive reconstruction, Review, S3, upload, pagination, deletion, UI
  redesign. Full verdict quoted in the repair section below.
- 2026-09-10 (Repair 1, lead-direct): new pure module `app/games-runtime.mjs`
  (`describeGameRow`) + its unit tests, so the truthfulness rules are testable instead of buried
  in JSX; home rows, the `/replay` filter ternary and the shared validation error prefix updated
  as below.

## Final implementation

Rust (host):
- `HistoricalReplayFrameV1` / `HistoricalReplayArchiveV2` (`human_play_command.rs`): archive v2
  wire shape = `HumanReplayArchiveV1` + per-frame `referee_reveal` + `human_seat`/`player_count`
  metadata (the old archive omitted referee reveal, which is why the old audit view showed
  "Referee reveal (N/A)").
- `build_historical_replay_archive()`: pure reconstruction from the ReplayV1 —
  `verify_replay_trace` once, then per position `player_view = state.observation(actor)`,
  `legal_actions = canonical_order(&state.legal_actions())`, recorded action re-checked against
  the canonical legal set, `referee_reveal` via the same fields as `referee_projection`
  (`determinization_trace.rs:177`). Terminal-state and actor-mismatch guards fail closed.
- `StudioHost::historical_replay(session_id)`: `sanitize_session_id` → read
  `local-artifacts/m20-human-play/<id>.replay.json` → `read_replay_file` → meta
  (opponent/human_seat) → archive JSON. Unknown session / corrupt replay → clear `Err`.
- Route: `GET /replays/{session_id}` in `handle_host`.

Front-end (`apps/replay-studio`):
- `app/page.tsx` rewritten as the Games history home: full `/recent-games` list (time,
  session, opponent, seat, player count, verified/invalid, cached-review count, outcome + score);
  `View replay` → `/replay?session=…`, `Review` → `/review?session=…&seat=…` (only when
  verified); CTA `Play vs S3`; link to `/advanced`; no demo content.
- `app/replay/page.tsx` new: loads `/replays/{session}`, shared `BoardSurface`/`ReplayTimeline`/
  `usePlyNavigation`, player/referee toggle with the referee-only warning, mine/all filter when a
  human seat is known, final score, explicit "NO ANALYSIS" panel, `Review this game` link.
- `app/advanced/page.tsx` new: the legacy V1 sidecar importer/viewer moved here; `DEMO_TRACE`/
  `demoFrame` and the sessionStorage handoff deleted; empty state states the V1-sidecar
  requirement verbatim.
- `app/play/page.tsx`: `openReplay()` navigates directly to `/replay?session=…` (no fetch, no
  sessionStorage); recent-games section reduced to a link to `/`; `RecentGame` type + fetch removed.
- `app/review/page.tsx`: header link `/` relabelled `Games`.
- `trace-runtime.mjs`: shared validation error prefix `Invalid AnalysisTraceV1 at` →
  `Invalid replay data at` (no test depends on the old string).

## Owner review of `e125c2c` and Repair 1

The owner's independent review ran `9573141 → e125c2c` and returned:

```text
Replay Studio Product Shell @ e125c2c

Architecture direction:     APPROVED
Games home:                 PASS
Historical replay endpoint: PASS
Reviewer-free View replay:  PASS
Legacy V1 isolation:        PASS
sessionStorage removal:     PASS

VERDICT:  REPAIR_REQUIRED
P0 = 0   P1 = 1   P2 = 3
Repair scope: VERY SMALL
```

P1 (the only blocker) — **the history row presented an unknown human seat as P0**. `recent_games`
sets `human_seat` from the optional `.meta.json`, so it is legitimately nullable for older
replays, and `HistoricalReplayArchiveV2` preserves that `Option<u8>`. The home page nevertheless
wrote `const seat = game.human_seat ?? 0` and then derived `You P0`, `Victory`/`Defeat` and
`/review?…&seat=0` from it — inventing three user-visible facts. The owner folded a second
trust problem into the same P1: an `invalid` replay kept returning `scores`/`winners`, and the row
rendered them as a trusted result with only the buttons disabled.

Repair scope authorized (Games/history presentation only): unknown seat stays unknown; no
inferred Victory/Defeat; Review URL omits `seat`; unverified replay shows no trusted result;
clean the `/replay` filter ternary; optionally restore the precise validation error prefix;
targeted frontend tests; commit/push then STOP. P2 items 1–2 were folded in; P2 item 3 (full
`cargo test -p splendor-cli` blocked by the owner's running Studio Host) was explicitly accepted
as a non-blocker to be rerun at the next natural host restart.

### Repair 1 implementation (lead-direct, 2026-09-10)

- `app/games-runtime.mjs` (new): pure `describeGameRow(game)` owns the row facts. `seat` is
  `number | null` (never defaulted); `seatLabel` is `Seat unknown` when absent; `outcome` is
  `Invalid replay` when unverified, `—` when verified but seat-less or winner-less, and only
  `Victory`/`Defeat` when both a verified replay and a known seat licence it; `scoreLine` is
  `Result unavailable` when unverified and the real score otherwise; `reviewHref` appends `seat`
  only when it is known (the Host's `/review` already treats a missing seat as `all`). Extracted
  rather than inlined so the rules are unit-testable and cannot silently regress.
- `app/page.tsx`: consumes `describeGameRow`; the row's `You P{seat}`/`Victory`/`Defeat`/
  `&seat=` derivations and the now-redundant "Unavailable: this replay failed verification."
  line are gone. An unverified row reads `Invalid replay` / `Result unavailable` with no actions,
  matching the owner's target rendering.
- `app/replay/page.tsx`: `setFilter(next.human_seat === null ? "all" : "all")` →
  `setFilter("all")` (editing residue; both branches were `"all"`, so behaviour is unchanged).
- `app/trace-runtime.mjs`: the shared `fail()` prefix `Invalid replay data at` →
  `Invalid analysis trace at`. The owner suggested restoring the old `Invalid AnalysisTraceV1`
  wording, but `fail()` is shared with `validateReviewTrace` (V2 review bundles), so naming V1
  would have introduced a new mislabel in the `/review` error path; the version-neutral form is
  accurate for both consumers (both are `effective-splendor-analysis-trace` documents).
- `tests/games-runtime.test.mjs` (new, 8 tests): known-seat win/loss from the human seat rather
  than seat 0; `null` **and** `undefined` seat stay unknown with no `seat=` in the review URL;
  a no-metadata legacy replay never claims `You P0`/`Victory`; an `invalid` replay reports no
  trusted outcome or score; an unreadable entry (`error: unreadable replay`) degrades the same
  way; verified-but-outcome-less games report `—`; session ids are URL-encoded in both links.
- `package.json`: `test` script now includes `tests/games-runtime.test.mjs`.

Not done, deliberately: no Host/Rust change (the `scores`/`winners` fields stay on the wire and are
simply no longer presented as trusted), no archive reconstruction change, no `/review`, S3, upload,
pagination, deletion or UI redesign work.

## Validation and evidence

All commands run 2026-09-10 on `main` (worktree = this round's changes on `9573141`):

- `cargo check -p splendor-cli --all-targets` → ok after the lifetime fix; only pre-existing
  warnings (determinization-agent/s2_census, unchanged from earlier rounds).
- `cargo test -p splendor-cli --bin splendor historical_replay` → 2 passed / 0 failed
  (`historical_replay_archive_rebuilds_every_frame_from_the_replay`,
  `historical_replay_archive_rejects_a_tampered_replay`).
- `cargo test -p splendor-cli --bin splendor` (full bin suite) → **89 passed / 0 failed**.
- `npx tsc --noEmit` → 8 errors, all pre-existing (5 experiments/page.tsx, 3 review/page.tsx;
  the old home page's error disappeared with the rewrite); **0 new errors**, none in
  `page.tsx`/`replay`/`advanced`/`play`.
- `npm test` (apps/replay-studio: build + node --test) → **37 passed / 0 failed**
  (35 prior + rewritten home-shell test + new `/advanced` and `/replay` shell tests, minus the
  superseded `/review` "Advanced import" assertion → net +2).
- `git diff --check` → clean.
- Host-related integration tests (`--test studio_registry`, `--test m36a_experiment_replays`):
  run via an isolated `CARGO_TARGET_DIR` because the running Studio Host process holds
  `target/debug/splendor.exe` locked (full-suite rerun command for the owner:
  `cargo test -p splendor-cli` once the host is stopped).

### Repair 1 re-validation (2026-09-10, worktree = this round + Repair 1)

- `node --test tests/games-runtime.test.mjs` → **8 passed / 0 failed**.
- `npm test` (build + all six `node --test` files) → **45 passed / 0 failed** (`37` before the
  repair + the 8 new row-truthfulness tests).
- `npx tsc --noEmit` → 8 errors, byte-for-byte the same pre-existing set (5 `experiments/page.tsx`,
  3 `review/page.tsx`); **0 new**, none in `page.tsx`, `replay/page.tsx`, `games-runtime.mjs`,
  `trace-runtime.mjs` or the new test.
- `npx eslint` on the five touched files → clean.
- `git diff --check` → clean (CRLF notices only, pre-existing repo line-ending behaviour).
- Rust was intentionally not rebuilt or re-run: Repair 1 changed no Rust file and the endpoint's
  evidence from the original run still stands. Full `cargo test -p splendor-cli` remains deferred
  to the next natural Studio Host restart (owner-accepted non-blocker).

## Result and decision

- Product shell re-ordered exactly per the owner's frozen scope; acceptance checklist:
  1. `/` shows no `DEMO_TRACE`/fake board and lists saved games (including
     `human-12312300221-0-28024-1`) — verified by the rewritten render test (home renders the
     Games shell; list data is host-fetched at runtime).
  2. `View replay` hits `GET /replays/{id}` — reviewer-free by construction
     (`build_historical_replay_archive` performs no AI/analysis work), covered by the two new
     Rust tests.
  3. `Review` opens the existing `/review` chain (2p default S3) — untouched this round.
  4. `Open replay` after a finished game routes directly to `/replay?session=…`;
     `sessionStorage` bridge deleted from both sides.
  5. `/advanced` keeps V1 opening (same `validateAnalysisTrace` path; legacy fixture openable).
  6. Invalid/unreadable replays render as invalid without action buttons; corrupt replays
     fail closed at the endpoint with a clear error.
  7. `npm test` 37/0 and relevant CLI tests green (above).
- Round status: `IMPLEMENTED` / `VERIFIED`. Not `ACCEPTED` — product closure review is the
  owner's next gate.
- Owner review of `e125c2c` → `REPAIR_REQUIRED` (P0 = 0 / P1 = 1 / P2 = 3) on 2026-09-10; the
  single P1 (history-row truthfulness) and P2 items 1–2 were repaired in Repair 1, whose focused
  evidence is the re-validation block above. The owner's stated expectation is that this closes
  the round without a Product Shell Repair 2. Final status remains the owner's call.

## Known limitations

- The home list is host-fetched client-side; SSR renders the loading shell (consistent with
  other Studio pages).
- `/replay` without a `session` param shows a clear error; there is no in-app game deletion or
  archive management yet.
- External ReplayV1 ingestion (upload, identity, lifecycle) is explicitly out of scope and
  remains a separate future feature.
- Full `cargo test -p splendor-cli` could not relink while the owner's Studio Host was running;

  rerun it (or restart the host) for the complete suite evidence. The owner reviewed this gap and
  accepted it as a non-blocker for this round; it is due at the next natural host restart, not as a
  dedicated stop-the-service ceremony.

## Next authorized gate

Owner closure verdict on this round **including Repair 1** (`REPAIR_REQUIRED` has been addressed;
no further repair was authorized or performed). The owner stated the expectation that the round can
close without a Product Shell Repair 2. No other follow-on work is authorized.
