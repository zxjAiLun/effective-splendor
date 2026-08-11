# M11 First Formal Dataset Validation

Verdict: **PASS**

## Artifact identity

- Dataset id: `formal-m10-evaluation-2026-08-11-v1`
- Source corpus: complete M10 frozen 64-game evaluation
- Dataset file: `formal-m10-evaluation-2026-08-11-v1.dataset.json`
- Replay list: `formal-m10-evaluation-2026-08-11-v1.replay-list.json`
- Dataset file size: 54,296,112 bytes
- Dataset file SHA-256: `2adfb8cb827fa0f2ac1be94d375e5449d3b89ed5ce4e679b9d438fd93af8fc03`
- Dataset semantic hash v1: `d60d2ddb6054bf32cd0c915f75d85bacdb62158414370e8e73efcfd65c7a7720`
- Replay-list file SHA-256: `06644aded41e8280c5ac609bba569bf7ee3c2a2d52ef15a8280cbebde2b25c70`

The semantic hash is:

```text
SHA-256(
  b"effective-splendor-training-dataset-v1\0"
  || compact fixed-field-order TrainingDatasetV1 JSON
)
```

## Provenance roots

- League manifest hash: `3a8d3d779f0dc56d9284546af5a4552c2b3b15e3cdcd7a2e4908f3d006714ca6`
- Evaluation plan hash: `1975ff93701b04a3187cc86839b3d9d7dfd34960790a54919dfcae70922c3aeb`
- Evaluation report hash: `bfe37aa341207f4e020a18bfb4abeaced9c7ef64b69e65cb3cf7960b70a172f8`

The dataset does not contain or bind the promotion report. The promotion
report remains archived beside the evaluation as its competitive conclusion,
but is outside the M11 provenance chain.

## Corpus completeness

- Replay sources: 64
- Canonical match indices: exactly `0..63`
- Duplicate source ids: 0
- Duplicate match indices: 0
- Completed sources: 64
- Aborted sources: 0
- Arena report hash mismatches: 0
- Replay document hash mismatches: 0
- Evaluation record/seed-index/rotation/seat mismatches: 0
- Total player-view examples: 3,956

Every replay contributes all plies. No match was filtered by winner, policy,
promotion decision, or candidate outcome.

## Mixed-policy composition

| Policy | Examples |
| --- | ---: |
| `root-determinization-v1` | 1,978 |
| `observation-history-ismcts-v1` | 1,978 |

Each example is attributed through its source replay and actor seat to the
scheduled league agent, policy/model identity, and verified Arena runtime.
M10 remains a rejected candidate; the dataset name and metadata make no
champion claim.

## Player-view and legality checks

- Example source/replay hash bindings: PASS
- Example plies contiguous per source: PASS
- Actor equals recorded replay actor: PASS
- Chosen action equals recorded replay action: PASS
- `legal_actions` contains `chosen_action`: PASS for all 3,956 examples
- Observation viewer equals actor: PASS for all 3,956 examples
- Final scores/ranks equal verified replay results: PASS
- Observation objects contain only the v1 player-view schema: PASS

The verifier recursively rejected the following forbidden referee/replay
fields anywhere in the emitted dataset:

```text
seed
initial_state_hash
state_hash_before
state_hash_after
full_state
FullState
decks
log
```

Forbidden-key hits: 0.

`final_state_hash` remains present only as the documented verified replay
terminal binding in `TrainingReplayV1`; it is not a per-example referee state.

## Reproduction

Build command:

```powershell
target\release\splendor.exe build-dataset `
  --manifest benchmarks\m10-ismcts-v1.league.json `
  --evaluation-dir artifacts\formal-2026-08-11\m10-evaluation `
  --replays artifacts\formal-2026-08-11\m11-dataset\formal-m10-evaluation-2026-08-11-v1.replay-list.json `
  --out artifacts\formal-2026-08-11\m11-dataset\formal-m10-evaluation-2026-08-11-v1.dataset.json
```

Independent validation command:

```powershell
node --max-old-space-size=2048 `
  artifacts\formal-2026-08-11\m11-dataset\verify-formal-dataset.mjs
```

The verifier parses the complete dataset and all 64 parent Arena/replay
artifacts, recomputes the domain-separated provenance hashes, checks the full
source and seat mappings, validates every example against its original replay
step, enforces the player-view field allowlist, and emits a deterministic JSON
summary. Validation was run with Node.js `v24.18.0` and exited `0`.
