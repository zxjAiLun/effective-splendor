# M12 Policy-Value Model v1

M12 is an offline supervised baseline over provenance-verified M11
`TrainingDatasetV1` artifacts. It answers whether a small deterministic model
can learn useful policy and multiplayer value signals before any neural-guided
tree search is attempted.

M12 does **not** change M09/M10 results, promote an Agent, consume `FullState`,
or connect a model to ISMCTS. That integration belongs to M13.

## Information boundary

The production learning API accepts only:

```text
Observation
legal_actions
chosen_action
final_scores / final_ranks
M11 provenance hashes and source metadata
```

It has no dependency on replay reconstruction, Arena, Agent protocol, or
search. `encode_observation_v1(&Observation)` is the only state encoder and
returns an error for malformed static catalog/player domains. A
two-world test changes an opponent's blind-reserved card identity and requires
the encoded features to remain byte-identical.

The frozen representation id is:

```text
player-view-dense-v1
```

It contains 368 normalized features covering the viewer, public turn/phase,
bank, visible market card definitions, public deck counts, nobles, public
player material, and only the viewer's private reserved-card identities. It
contains no raw seed, deck order, referee log, `FullStateHash`, or opponent
blind-reserved identity.

Semantic actions use 36 features: action kind, token take/return vectors,
tier, slot, and noble identity. Policy inference is always normalized over the
server/dataset-provided legal action set; there is no unstable global policy
index.

## Model v1

```text
Observation[368]
      ↓
shared tanh encoder[hidden_features]
      ├── bilinear legal-action Policy head
      └── sigmoid Value head[4]
```

For a game with `n` players, inference returns the first `n` value components.
The supervised target for player `p` is:

```text
value_target[p] = 1 - final_rank[p] / (player_count - 1)
```

This is a bounded MaxN-style vector, not a two-player zero-sum scalar. Tied
players share the same target. The implementation supports 2–4 player shapes;
the first formal M11 corpus currently contains two-player games only, so no
3/4-player empirical quality claim is made for the first checkpoint.

## Deterministic training and split

`benchmarks/m12-policy-value-v1.config.json` binds the exact dataset semantic
hash and all upstream M11 provenance roots. Training refuses any mismatch.

The validation split is source-level, not example-level:

```text
validation iff replay.seed_index % 4 == 0
```

Both seat rotations for one frozen seed therefore stay in the same split, and
plies from one replay can never leak across train/validation. The formal corpus
splits into 48/16 replays and 2960/996 examples.

Initialization and epoch shuffling use a frozen SplitMix64 implementation.
Repeated training on the same Windows/MSVC toolchain produced byte-identical
checkpoint and report files. Floating-point operations mean v1 does not claim
cross-architecture bit identity; provenance records the config, dataset and
checkpoint content hashes.

The held-out baselines are:

- uniform probability over the legal action set for Policy NLL;
- per-seat mean rank utility learned from the training split for Value MSE.

`baselines_beaten` requires both held-out model metrics to be strictly better.
This is an offline baseline result, not an Arena promotion.

## CLI

Generated dataset/model/report artifacts are local-only and ignored by Git.
The historical M09–M11 formal artifact commit is an explicit exception.

```powershell
cargo run -p splendor-cli -- train-policy-value `
  --dataset artifacts/formal-2026-08-11/m11-dataset/formal-m10-evaluation-2026-08-11-v1.dataset.json `
  --config benchmarks/m12-policy-value-v1.config.json `
  --checkpoint local-artifacts/m12/checkpoint.json `
  --report local-artifacts/m12/training-report.json

cargo run -p splendor-cli -- evaluate-policy-value `
  --dataset artifacts/formal-2026-08-11/m11-dataset/formal-m10-evaluation-2026-08-11-v1.dataset.json `
  --checkpoint local-artifacts/m12/checkpoint.json `
  --out local-artifacts/m12/offline-eval.json
```

Outputs are strict, versioned JSON, published atomically without overwrite.
For training, the checkpoint is published first and the report last as the
commit marker. The checkpoint records dataset/upstream hashes, training config
hash, split, dimensions, epochs and all parameters. Offline evaluation refuses
a checkpoint whose provenance or split counts do not match the dataset, and
records the checkpoint's `training_config_hash` directly.

Malformed catalog IDs, noble IDs and action slots are rejected as
`InvalidDataset` before training begins. Inference also fails closed if a
finite-but-extreme external checkpoint overflows into non-finite hidden values,
policy logits, probabilities, or value predictions.

## First local smoke result

The authorized M12 config was run against dataset semantic hash
`d60d2ddb6054bf32cd0c915f75d85bacdb62158414370e8e73efcfd65c7a7720`.
Generated outputs remain under ignored `local-artifacts/`.

```text
validation examples:       996
Policy top-1 accuracy:     32.33%
Policy mean NLL:           2.3848
uniform Policy mean NLL:   3.0543
Value MSE:                 0.2467
train-prior Value MSE:     0.2486
outcome:                   baselines_beaten
```

The same config was trained twice and produced identical checkpoint/report
files. `evaluate-policy-value` independently reproduced the training report's
held-out metrics. These numbers are evidence for this exact two-player dataset
and split only; they are not a general strength or promotion claim.

The Git-tracked formal identity anchor is
`benchmarks/m12-policy-value-v1.result.json`. It binds the exact implementation
commit, dataset/upstream roots, training config hash, semantic checkpoint hash,
three local artifact file SHA-256 values, split and full held-out metrics. The
large checkpoint/report/evaluation files remain local; the result manifest
identifies which local checkpoint produced this formal result even where a
different platform cannot reproduce it byte-for-byte.

## M12 limitations

- The first formal corpus has only 64 two-player games and two frozen policies.
- The model is a small CPU baseline, not a deep network or production serving stack.
- Value targets use final dense rank, not search return or calibrated win probability.
- No model is loaded by M07/M10 Agents.
- No checkpoint is a champion and no M09 promotion gate applies to offline metrics.
- Larger datasets/checkpoints require local or content-addressed artifact storage,
  not ordinary Git commits.
