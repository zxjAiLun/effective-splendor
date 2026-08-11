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
deck order with a hindsight warning.

Validation:

```powershell
npm run lint
npm run build
npm test
```
