# M16 1v1 League Rating v1

M16 adds a reproducible internal strength floor. It does not replace the M09
paired promotion gate: Elo answers “how did the whole pool rank?”, while the
promotion gate answers “did this exact candidate clear the frozen champion
threshold with enough evidence?”.

## Artifact chain

```text
RatingRegistryV1
  + RatingConfigV1
        │
        ▼
RoundRobinPlanV1
  pairs[i].EvaluationPlanV1
        │
        ▼
canonical Arena matches and EvaluationReportV1 per pair
        │
        ▼
RatingReportV1
  ├─ Live Elo
  ├─ Official Elo
  └─ head-to-head W-T-L matrix
```

Every unordered pair appears exactly once in the round-robin plan. Its
two-agent evaluation plan expands each seed into both seat rotations. Pair
directories and filenames use only dense `pair_index` / `match_index`; agent
IDs never become paths.

The registry binds the literal program and argv together with policy, model,
runtime, and optional checkpoint identity. Entries classified as `checkpoint`
must provide a 64-character lowercase SHA-256. The registry hash therefore
changes when any executable policy configuration changes.

The rating builder does not trust a report's self-declared plan hash. It calls
the canonical evaluation aggregator again with the pair plan and records, then
requires structural equality with the supplied report. The final rating report
binds the registry hash, round-robin plan hash, and content hash of every pair
evaluation report.

## Rating semantics

- **Live Elo** starts every participant at `initial_elo` and applies the frozen
  `live_k_factor` after every completed match in canonical pair/match order. It
  is useful as an intuitive run timeline, but changes if game order changes.
- **Official Elo** fits all completed head-to-head results at once with a
  regularised Bradley-Terry model, then maps natural-log strength to the Elo
  scale (`400 / ln(10)`) and centres the pool at `initial_elo`. It is independent
  of report input order and stays finite for undefeated agents.
- A shared terminal win is a tie (0.5 each). Aborted games affect reliability
  counts but never fabricate a score or change either rating.
- Fewer than 20 completed games marks an agent `provisional`. M16's smoke league
  is intentionally provisional; M19 will be the first full internal
  championship.

Official Elo is a relative number inside the exact hashed pool and schedule. It
is not comparable to ratings from another game, ruleset, registry, or seed
corpus without a stable anchor population.

## Commands

```powershell
cargo run -p splendor-cli -- rating-plan `
  --registry benchmarks/m16-internal-1v1.registry.json `
  --config benchmarks/m16-foundation-smoke.rating.json `
  --out local-artifacts/m16-foundation/round-robin-plan.input.json

cargo run -p splendor-cli -- rating-run `
  --plan local-artifacts/m16-foundation/round-robin-plan.input.json `
  --out-dir local-artifacts/m16-foundation/run

cargo run -p splendor-cli -- rating-report `
  --plan local-artifacts/m16-foundation/round-robin-plan.input.json `
  --evaluation-dir local-artifacts/m16-foundation/run `
  --out local-artifacts/m16-foundation/rating-report.rebuilt.json
```

`rating-run` publishes `rating-report.json` last as the tournament commit
marker. It refuses to overwrite an existing run or pair directory. A separate
`rating-report` command supports independent reaggregation from already
completed pair artifacts.

## Dashboard

Start Replay Studio and open `/ratings`:

```powershell
cd apps/replay-studio
npm run dev -- --host 127.0.0.1 --port 4173
```

Load `rating-report.json` with the file picker. The dashboard shows both rating
views, W-T-L records, aborts, provisional status, the oriented head-to-head
matrix, and shortened provenance hashes. It is a local artifact viewer and
does not upload checkpoints, datasets, replays, or evaluation outputs.

## Boundary to later milestones

M16 contains no GPU model or training loop. M17 registers new Flat ResMLP and
Entity Mixer checkpoints in this same contract. M18A/M18B can then add RL
checkpoints without changing how strength is measured. M19 uses the expanded
pool for the formal internal championship; M21 external opponents remain
deferred until that evidence exists.
