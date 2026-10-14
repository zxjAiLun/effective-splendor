# Effective Splendor Replay Studio

Accepted M14A v1 analysis viewer for verified Splendor replays, extended by M23
with a one-click review workflow. The browser performs no search and loads no
model.

## Human Play layout

**2026-10-12 M80 retirement:** the local Studio model roster is empty. `/play`
shows the setup surface and reports `0 registered agents ready`; no opponent
can be started until a model is explicitly registered again. The table layout
description below is retained for the frozen M76/M77/M78 evidence, not as a
claim that a playable model is currently installed.

During a game in `/play`, your tokens, permanent discounts, bank and take
confirmation stay pinned at the bottom of the viewport, and the bank stays
reachable from every panel. Desktop shows the card table beside the current
move; narrow screens switch between **Table**, **Move**, **Reserves** and
**History**. Long card or return lists scroll inside their own panel, keeping
your resources visible. Selecting gems does not send a move; confirm the take
or choose the displayed return first.

## M23 one-click review

After a completed human match in `/play`, press **Review this game**, pick a
reviewer (M07 champion is the default), and the page opens `/review` with live
progress, then renders the whole-game `AnalysisTraceV2` without any file
picker. Reviewer identity, config and competitive status are shown; M13 stays
`Experimental · Formal promotion rejected`.

```text
GET  /reviewers
POST /reviews   { session_id, reviewer_id }
GET  /reviews/<job-id>
GET  /reviews/<job-id>/bundle
GET  /recent-games
```

## V1 file-picker path (advanced)

Generate a replay-bound `AnalysisTraceV1` with the Rust CLI, then load the
sidecar and its source `ReplayV1` through **Advanced import**:

```powershell
cargo run -p splendor-cli -- analyze-replay-neural `
  --input <match.replay.json> `
  --checkpoint <checkpoint.json> `
  --checkpoint-hash <semantic-sha256> `
  --sample-seed 20260811 `
  --simulations 64 `
  --max-depth-turns 2 `
  --puct-exploration-milli 1500 `
  --out <match.analysis.json>
```

M07 whole-game `AnalysisTraceV2`:

```powershell
cargo run -p splendor-cli -- analyze-replay-determinization `
  --input <match.replay.json> --sample-count 4 --max-depth-turns 1 --max-nodes 2000 `
  --out <match.analysis-v2.json>
```

The default perspective is the recorded actor's `Observation`. `Referee
reveal` is an explicit post-game mode that exposes blind reserves and future
deck order with a hindsight warning. Loaded sidecars pass a runtime v1 or v2
schema validator before rendering; token-return variants are preserved in every
human readable action label.

Validation:

```powershell
npm run lint
npm run build
npm test
npm run test:play-ui
```

`npm test` loads the Rust-generated golden V1 and V2 traces, checks Player View
and Prior/Visit/Q projection (V1) plus mean-utility/rank (V2), rejects
malformed traces, and verifies that actions which differ only by `return` never
receive the same label. Regenerate the goldens with
`cargo run -p splendor-analysis --example generate_frontend_fixture`.

`npm run test:play-ui` uses an installed Chromium (or `STUDIO_TEST_BROWSER`) and
an ephemeral local UI server to check the retired-roster setup surface across
desktop, tablet, mobile and 150% font sizes. It mocks the Host and never creates
a real game or League entry. Screenshots, geometry and source hashes go to
ignored `local-artifacts/m80-local-history-cleanup/play-browser/`, or
`STUDIO_COCKPIT_ARTIFACTS` when set. The frozen M76/M77 table-geometry gate is
represented by the retained `local-artifacts/m78-studio-ui/` evidence; this
command no longer exercises it while the roster is empty.

`npm run test:layout-ui` is the matching gate for the Games/Play/League/Ratings
pages: shared navigation, hero/setup/standings layouts across desktop, tablet,
mobile and 150% font sizes, cursor paging and form behavior, all against the
same synthetic Host boundary (artifacts under `STUDIO_LAYOUT_ARTIFACTS`).

For a local human-vs-agent game, double-click `Splendor Studio.cmd` at the
repository root, then navigate to `/play`. It starts both services; opponent
selection and session creation happen in the page.
