# M23 Review Studio Productization

M23 turns replay review into a one-click workflow: after a completed human
match, the player chooses a reviewer and gets a full-game analysis that opens
directly in Replay Studio — no manual `replay.json` + `analysis.json` file
picker.

```text
ReplayV1          = what objectively happened (unchanged)
AnalysisTraceV1   = M13 replay-wide sidecar (unchanged)
AnalysisTraceV2   = unified replay-wide reviewer trace (new)
```

## Unified review contract (`AnalysisTraceV2`)

`AnalysisTraceV2` shares the `effective-splendor-analysis-trace` format
identifier with V1 but uses `version: 2` and carries a reviewer identity plus a
discriminated per-frame result:

```text
reviewer { id, display_name, competitive_status, result_kind, algorithm_id,
           algorithm_version, config, checkpoint_hash, provenance }
frames[] {
  ply, state_hash_before, actor, recorded_action, legal_actions,
  player_view, observation/information-set/visible-history hashes,
  referee_reveal (display only, never an analyzer input),
  review_result {
    kind: "root_determinization" -> { recommended_action, sample_count,
                                      action_stats[].utility_sum_by_player }
    kind: "neural_ismcts"        -> { NeuralIsmctsResultV1 (prior/visit/Q) }
  }
}
```

`AnalysisTraceV1` and the M13 CLI are unchanged. V2 rejects any M07 utility
written into a `Q` field, and rejects any M13 prior/visit fabricated for M07.

## Reviewers

`benchmarks/studio-reviewers.registry.json` is a separate registry from the
M16 1v1 play registry:

- `m07-determinization-champion` — `champion`, default. Mean continuation
  utility and action rank. No priors, no visits, no `Q`, no win probability.
- `m13-neural-ismcts` — `rejected` / `experimental`. Policy prior, visit share,
  and model value estimate `Q`. Never presented as champion, best model, ground
  truth, or calibrated win probability.

M17/M18A/M18B/M22 remain `play_capable / review_not_supported`; they are not
given a fabricated reviewer this round.

## Commands

```powershell
# M07 whole-game review (one process, one trace)
splendor analyze-replay-determinization `
  --input <replay.json> --sample-count 4 --max-depth-turns 1 --max-nodes 2000 `
  --out <analysis-v2.json>

# M13 V2 (V1 stays the default; --trace-version 2 opts into V2)
splendor analyze-replay-neural ... --trace-version 2 --out <analysis-v2.json>
```

The original `analyze-replay-player-view` remains for research/debugging.

## Review job API (Studio Host)

The existing Studio Host gains a local, loopback-only review API. It resolves
all resources from fixed directories and the reviewer registry; the browser
can only submit `{ session_id, reviewer_id }`:

```text
GET  /reviewers
POST /reviews   { session_id, reviewer_id }
GET  /reviews/<job-id>
GET  /reviews/<job-id>/bundle
GET  /recent-games
```

Jobs run in-process (Rust threads, no shell), report
`processed_decisions / total_decisions / current_ply`, and reuse an existing
artifact via a cache key that binds replay document hash + reviewer id +
reviewer version + full reviewer config + checkpoint hash:

```text
SHA256("effective-splendor-review-cache-v2\0"
       + replay_document_hash + reviewer_id + algorithm_version
       + config_json + checkpoint_hash)
```

Artifacts land under `local-artifacts/m20-human-play/reviews/<session>/`.
Unknown reviewer/session, path-like session ids, missing checkpoints, and
checkpoint-hash mismatches all fail closed. Failed jobs never overwrite a
previously committed artifact.

## One-click flow

Terminal screen → `Review this game` → choose M07 (default) or M13 →
progress (`Analyzing 24 / 56 decisions · current ply 24`) → Replay Studio opens with the
review bound. Replay Studio defaults to `Player view`, `My decisions`, and
shows the honest per-reviewer table:

- M07: `Mean utility`, `Utility gap`, `Action rank` (ties share a rank; utility
  is not a percentage).
- M13: `Prior`, `Visit`, `Q(Pn)`; a zero-visit actual action shows `UNSCORED`
  (never `0` or worst). `Search choice` and `Highest visited Q` are marked
  separately; `Q gap = max visited Q − actual Q`.

The manual `Load replay + analysis` file picker remains under
`Advanced import` and is no longer the primary path.

## Honest metrics

No composite "you scored 37/100" score is fabricated. M07 utility is mean
continuation utility; M13 `Q` is a model value estimate. There is no blunder
count and no "win probability lost".

## Validation

```powershell
cargo fmt --all -- --check
cargo test -p splendor-analysis
cargo test -p splendor-cli
cargo clippy --workspace --all-targets -- -D warnings

cd apps/replay-studio
npm test
npm run lint
npm run build
```

The frontend V2 contract is exercised by
`tests/fixtures/rust-analysis-trace-v2-m07.json`, regenerated with
`cargo run -p splendor-analysis --example generate_frontend_fixture`.
