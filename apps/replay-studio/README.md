# Effective Splendor Replay Studio

Local M14A analysis viewer for verified Splendor replays. The browser performs
no search and loads no model. Use the Rust CLI to generate a replay-bound
`AnalysisTraceV1`, then load the sidecar and its source `ReplayV1` through the
file picker.

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

cd apps/replay-studio
npm install
npm run dev
```

The default perspective is the recorded actor's `Observation`. `Referee
reveal` is an explicit post-game mode that exposes blind reserves and future
deck order with a hindsight warning. Loaded sidecars pass a runtime v1 schema
validator before rendering; token-return variants are preserved in every human
readable action label.

Validation:

```powershell
npm run lint
npm run build
npm test
```

`npm test` loads the Rust-generated golden trace, checks Player View and
Prior/Visit/Q projection, rejects a malformed trace, and verifies that actions
which differ only by `return` never receive the same label. Regenerate the
golden with `cargo run -p splendor-analysis --example generate_frontend_fixture`.
