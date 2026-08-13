# Effective Splendor Replay Studio

Accepted M14A v1 analysis viewer for verified Splendor replays, extended by M23
with a one-click review workflow. The browser performs no search and loads no
model.

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
```

`npm test` loads the Rust-generated golden V1 and V2 traces, checks Player View
and Prior/Visit/Q projection (V1) plus mean-utility/rank (V2), rejects
malformed traces, and verifies that actions which differ only by `return` never
receive the same label. Regenerate the goldens with
`cargo run -p splendor-analysis --example generate_frontend_fixture`.

For a local human-vs-agent game, double-click `Start Splendor Studio.cmd` at the
repository root. It starts both services and opens `/play`; opponent selection,
session creation, and connection happen in the page without terminal commands.
