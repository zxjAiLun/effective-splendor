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

## M15B source-aware training contract

M15B contract version 2 keeps the accepted M12 JSON/hash behavior when its new
fields are absent. When enabled, the config must explicitly name:

- `policy_teacher_agent_ids`: only decisions made by these league agents are
  Policy imitation labels;
- `value_target_agent_ids`: only decisions owned by these agents contribute
  terminal-rank Value targets;
- material relative-improvement gates, in basis points, for Policy NLL versus
  uniform and Value MSE versus the train-source prior.

The actor identity is derived from the example's provenance-bound replay and
seat, not from a caller-supplied label. Unknown and duplicate agent ids fail
closed. Source-level train/validation splitting still happens before head
selection, and both heads must retain non-empty examples on both sides.

The checkpoint records `training_contract_version: 2`. The legacy offline
evaluator rejects such a checkpoint because it cannot infer head selection from
the checkpoint alone. Reproduction requires the exact config:

```powershell
cargo run -p splendor-cli -- evaluate-policy-value-source-aware `
  --dataset <dataset.json> `
  --checkpoint <checkpoint.json> `
  --config benchmarks/m15b-source-aware-policy-value-v1.config.json `
  --out <offline-eval.json>
```

Reports retain the M12 aggregate fields for compatibility and add exact
per-head example counts/metrics plus a material gate. A failed material gate is
recorded as evidence; it does not silently suppress or rewrite the checkpoint.
The first frozen M15B config uses only the determinization champion as Policy
teacher, keeps both completed M10 policies as Value outcome sources, requires a
15% Policy-NLL improvement and a 5% Value-MSE improvement, and does not use the
M13 formal seeds.

After the first Policy-only prospective screen failed, the same version-2
contract gained one optional, hash-bound control:
`value_updates_shared_encoder: false`. Value examples still update the Value
head, but their loss cannot update or L2-decay the shared encoder. Examples
selected for both heads update the encoder from Policy loss only. The setting
is repeated in training/offline reports, and a unit test proves that changing
Value-only targets changes Value parameters while leaving the encoder and
Policy parameters byte-identical. Absence continues to preserve the accepted
M12 and first M15B behavior.

The second data round is frozen by
`benchmarks/m15b-teacher-data-v2.league.json` and its complete replay list. It
collects 128 new matches on seeds `950000..950063`; none overlap M13 formal or
M15B diagnostic seeds. Only champion-owned actions may become Policy labels.
The generated evaluation, dataset and checkpoints remain local and the data
seeds are permanently excluded from later diagnostic or promotion evidence.

The data run completed 125/128 matches. Matches `27`, `96`, and `109` were
excluded because the determinization champion exceeded the frozen 10-second
action deadline; the opponent caused zero faults. No match was rerun. All 125
completed replays independently verified, and the dataset builder revalidated
the canonical report and match provenance before producing 7,843 examples.
The exact hashes and exclusion list are recorded in
`benchmarks/m15b-teacher-data-v2.result.json`.

`benchmarks/m15b-isolated-policy-value-v2.config.json` freezes the second
training attempt before execution. Architecture, optimizer, initialization,
source filters and offline gates remain identical to the first M15B attempt;
only the new dataset binding and encoder-gradient isolation differ.

The deterministic run doubled the champion Policy split to 2,942 train / 978
validation examples. Policy NLL improved 21.00% over uniform and passed the
unchanged 15% gate; Value MSE improved only 1.61% over the train prior and
failed the unchanged 5% gate. Therefore checkpoint
`6ef032a0cb0c65e89f80386484f04e1aadb0d82d6c140a31e8f6fad7c6afebf9`
is not a full candidate. The passed Policy component alone is authorized for
one frozen 32-match prospective screen on new seeds `960000..960015`.

## M15C search-teacher targets

M15B proved that held-out one-hot imitation NLL can improve while prospective
play remains weak. M15C therefore preserves the full root search signal in a
separate, content-addressed artifact rather than changing `TrainingDatasetV1`.
The frozen generator config binds the exact dataset provenance, teacher agent,
sample stream, continuation search budget, Policy projection and Value scale.

For every champion-owned player-view example, the generator independently
verifies the complete source replay, reconstructs the actor's Observation and
visible history, requires their hashes and canonical legal actions to equal the
dataset, and reruns the frozen M07 root-determinization search. No replay seed,
sampled `FullState`, hidden card identity or referee state is serialized into
the target artifact.

Policy targets are exact integer millionths. Ten percent total mass is spread
uniformly across legal actions; the remaining 90% is allocated in proportion
to each root action's non-negative advantage over the minimum actor utility.
Largest-remainder allocation with canonical-action tie breaking makes the sum
exactly `1_000_000`. An all-tied root becomes uniform.

Value targets use the full utility vector of the teacher-selected action. Each
player's mean utility across determinizations maps linearly around `0.5`, with
absolute utility `1_000_000_000` mapping to an endpoint and larger magnitudes
clamped. This is explicitly a search-shaped progress target, not a calibrated
win probability. The projection scale is an input to the artifact and cannot
be changed after seeing offline or competitive results.

```powershell
cargo run -p splendor-cli -- build-search-teacher-targets `
  --dataset local-artifacts/m15b-teacher-data-v2/dataset.json `
  --evaluation-dir local-artifacts/m15b-teacher-data-v2/evaluation `
  --config benchmarks/m15c-search-teacher-targets-v1.config.json `
  --out local-artifacts/m15c-search-teacher-targets-v1/targets.json
```

The output binds every target by dataset hash, source id, replay document hash,
ply, actor, Observation hash, visible-history hash and InformationSet hash. It
also retains the complete canonical action/utility vectors, so Policy and
Value projections can be independently recomputed before training.

### M15C training contract v3

Contract version 3 consumes the target artifact directly. Policy minimizes
cross-entropy against the complete integer-micros action distribution instead
of a one-hot recorded action. Value minimizes vector MSE against the frozen
search-shaped values instead of terminal ranks. Top-1 accuracy is measured
against the canonical teacher-selected action; Policy cross-entropy is still
compared with uniform, and Value MSE with a train-source constant prior.

The training config, checkpoint, training report and independently recomputed
offline report all bind `search_teacher_targets_hash`. Training fails before
publishing either output if the target set is incomplete, contains an extra
example, changes any dataset/replay/actor/information-set/action binding, or
does not match the frozen hash. Contract-v2 and legacy evaluators reject a v3
checkpoint.

```powershell
cargo run -p splendor-cli -- train-policy-value-search-teacher `
  --dataset local-artifacts/m15b-teacher-data-v2/dataset.json `
  --targets local-artifacts/m15c-search-teacher-targets-v1/targets.json `
  --config benchmarks/m15c-search-policy-value-v1.config.json `
  --checkpoint local-artifacts/m15c-search-policy-value-v1/checkpoint.json `
  --report local-artifacts/m15c-search-policy-value-v1/training-report.json

cargo run -p splendor-cli -- evaluate-policy-value-search-teacher `
  --dataset local-artifacts/m15b-teacher-data-v2/dataset.json `
  --targets local-artifacts/m15c-search-teacher-targets-v1/targets.json `
  --checkpoint local-artifacts/m15c-search-policy-value-v1/checkpoint.json `
  --config benchmarks/m15c-search-policy-value-v1.config.json `
  --out local-artifacts/m15c-search-policy-value-v1/offline-eval.json
```

The target and learned artifacts remain local. A small checked-in result
manifest records semantic/file hashes, exact split metrics and the unchanged
material gates. Passing offline gates authorizes only a fresh prospective
screen; it does not promote a model or permit tuning on formal M13 seeds.

The frozen v1 run produced 3,920 targets and exactly reproduced every recorded
champion action. Mean top Policy mass was 31.32%, mean target entropy 2.3458,
and only 3.27% of Value components hit a clamp endpoint, so the source signal
was neither one-hot nor globally saturated. Nevertheless, the h32 checkpoint
improved held-out soft Policy cross-entropy only 4.87% over uniform and its
Value MSE was worse than the train-source constant prior. Both unchanged gates
failed. `benchmarks/m15c-search-policy-value-v1.result.json` records the exact
hashes and metrics; no candidate or prospective screen is authorized.

This failure authorized one controlled representation/capacity comparison
under the same target artifact, split, gates and initialization discipline. It
did not authorize tuning the target scale, floor, gates, or formal M13 seeds.

### M15D architecture v2

M15D keeps checkpoint format v1 but adds an optional
`model_architecture_version: 2`. When absent, all accepted M12/M15B and M15C
JSON/hash behavior remains unchanged. Version 2 makes two structural changes:

- Policy encodes the player-view state, combines it with each legal action in
  a nonlinear hidden interaction, then scores that interaction. Unlike the v1
  additive tier/slot context, this can condition a slot choice on the complete
  encoded board state.
- Value has a separate observation encoder. Search-shaped Value gradients
  update that encoder and the vector head but can never change Policy
  parameters. A deterministic test changes only Value utilities and proves
  every Policy parameter remains byte-identical.

The frozen config doubles hidden width from 32 to 64. Dataset, target semantic
hash, split, 24 epochs, optimizer settings, initialization seed and both gates
are identical to M15C.

```powershell
cargo run -p splendor-cli -- train-policy-value-search-teacher `
  --dataset local-artifacts/m15b-teacher-data-v2/dataset.json `
  --targets local-artifacts/m15c-search-teacher-targets-v1/targets.json `
  --config benchmarks/m15d-interaction-policy-value-v1.config.json `
  --checkpoint local-artifacts/m15d-interaction-policy-value-v1/checkpoint.json `
  --report local-artifacts/m15d-interaction-policy-value-v1/training-report.json
```

The frozen run did not pass. Policy top-1 increased slightly from 30.27% to
30.98%, but validation soft cross-entropy worsened from 2.8326 to 2.8382.
Relative improvement over uniform was 4.75% on train and 4.69% on validation,
far below the unchanged 15% gate. The near-identical train/validation result
points to optimization or underfitting, not a held-out generalization gap.
Independent Value MSE was 0.02448 versus a 0.01906 constant prior, so the 5%
Value gate also failed. `benchmarks/m15d-interaction-policy-value-v1.result.json`
records the exact hashes. M15D closes without a candidate or screen.
