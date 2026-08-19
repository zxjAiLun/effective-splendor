# M28B — Contextual Entity Interaction v1

```ini
MILESTONE = M28B
STATUS = IMPLEMENTED / CONTRACT VALIDATED; source/prereg review pending
BASE_COMMIT = c0caa883e47cadce1ae85c78b85ba7c4e69ac007
IMPLEMENTATION_COMMIT = e1b80aa6673865d149ef1e56b9a41f1b384b563d
SCOPE = One fresh-init contextual entity interaction candidate versus one historical Entity Mixer control on the accepted M24-S2 corpus.
TRAINING = NOT_AUTHORIZED (implementation round only)
ARENA = NOT_AUTHORIZED
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

M24-S2 improved fixed-corpus offline fit without producing a corresponding
M07 strength signal. M27A then tested the simpler search-bottleneck
explanation with a frozen 896-match screen. All `896/896` matches completed,
but no search budget reached the preregistered practical stable-region gate;
M27A closed as `M27A_INCONCLUSIVE` with no promotion.

M28A tested whether the approximately 0.95M-parameter Entity Mixer simply
lacked capacity to absorb S2. Its accepted compact result failed G1 while G2
passed: `M28A_OFFLINE_NO_CAPACITY_SIGNAL`. Arena was correctly not authorized.
The next controlled intervention is therefore representation, not another
search audit or another data collection round.

The M28B question is:

> With M24-S2 data, targets, optimizer, and 16-simulation evaluation held
> fixed, does masked contextual entity interaction improve offline fit and
> then competitive strength over the historical Entity Mixer?

## Initial design

M28B keeps the M28A control recipe and changes only the entity aggregation
architecture. Both models are freshly initialized with the same seed:

```text
control:   entity_mixer,              h192, 4 residual blocks, 949,060 parameters
candidate: contextual_entity_mixer,   h192, 4 residual blocks, 2 interactions,
                                      1,689,798 parameters
```

The candidate first uses the existing entity encoder. Each of two contextual
blocks computes per-entity `q_i`, `k_j`, and `v_j`; a pair MLP on
`[q_i, k_j, q_i * k_j]` produces sigmoid weights; visible non-self entities
are aggregated with a masked weighted mean; and a residual MLP combines
`[entity, context, global_context]`. This is an explicit pairwise mixer, not
standard multi-head attention and not a Transformer encoder.

## Scope and non-goals

### In scope

- The accepted M24-S2 `effective-splendor-neural-self-play-v2` corpus.
- The existing 1v1 player-view entity schema and Policy/Value targets.
- One fresh h192/b4 Entity Mixer control and one fresh h192/b4 contextual
  interaction candidate.
- Fixed AdamW recipe, deterministic seed protocol, full-S2 validation, and
  the frozen S1-reference diagnostic subset.
- Offline G1/G2 gates and a future 192-match Arena contract.
- Machine-checked configuration, parameter counts, mask behavior, checkpoint
  metadata, and split/provenance bindings.

### Not in scope / not authorized

- M28B training or checkpoint generation in this implementation round.
- New self-play, teacher/bootstrap changes, target redesign, or data changes.
- Width sweep, Transformer, standard multi-head attention, optimizer sweep,
  learning-rate sweep, PUCT tuning, or search-budget scaling.
- Arena execution, promotion, champion change, M25, M26, or downstream M28
  continuation.

## Contracts and invariants

- Baseline and M28A closure commit:
  `c0caa883e47cadce1ae85c78b85ba7c4e69ac007`.
- The tracked prereg is
  `benchmarks/m28b-contextual-entity-interaction-v1.config.json` and remains
  `DESIGNED` with training and Arena authorization set to `NOT_AUTHORIZED`.
- Dataset path is local-only:
  `local-artifacts/m24-self-play-s2-v1/self-play.json`.
- Dataset semantic self-play hash:
  `b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46`.
- Dataset raw SHA-256:
  `ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f`.
- Dataset generator checkpoint hash:
  `dc611f3d575f87e2b24221d633f8af55c98055357b05ccb822ef46ec0cb98c04`.
- The split is game-level: validation `game_index % 4 == 0` has `7,851`
  examples; train has `23,654`; the S1 reference is the first 128 games in
  that validation residue and has `1,953` examples. Validation and reference
  games cannot enter training.
- Both models call fresh `build_model(ModelSpec(...))` after resetting seed
  `280229`. Inherited weights, partial transplant, Net2Net, interpolation,
  and checkpoint surgery are forbidden.
- The old `entity_mixer` architecture and its historical metadata shape remain
  unchanged. The new `interaction_blocks` metadata field is emitted only for
  `contextual_entity_mixer`, so old checkpoints can still strict-load.
- Contextual entity and pairwise context outputs zero masked target slots;
  masked source slots cannot affect visible contexts. The player-view encoder
  remains the only input boundary.
- Dataset, checkpoints, reports, and future Arena artifacts remain local
  ignored files. Config, model source, tests, and this living record are
  tracked.

## Offline and future Arena gates

The complete machine-readable contract is in the tracked config. The key
gates are:

| Gate | Pass condition | Consequence |
| --- | --- | --- |
| G1 full S2 validation | At least one of Policy CE or Value MSE improves by `>= 50` bps; both remain `>= -100` bps; Top-1 delta `>= -0.010` | Offline eligibility input |
| G2 S1 reference | Policy CE and Value MSE deltas `>= -100` bps; Top-1 delta `>= -0.010` | Offline eligibility input |
| Offline stop | G1 or G2 fails | `M28B_OFFLINE_NO_INTERACTION_SIGNAL`; STOP and no Arena |
| Direct Arena | Candidate-v-control practical gain `>= 5500` bps | One future interaction-signal gate |
| Matched M07 anchor | Candidate-v-M07 minus control-v-M07 `>= +500` bps | One future interaction-signal gate |
| Execution validity | Future screen is `192/192`, zero abort, zero candidate fault | Otherwise `M28B_EXECUTION_INVALID` |

The future Arena uses neural ISMCTS with 16 simulations, depth 1, PUCT 1500,
three pairs, 32 frozen game seeds, two seat rotations, and 64 matches per
pair. It is conditional on an explicit training-evidence review and offline
PASS; this round does not authorize it. If both practical gates pass, the
decision is `M28B_INTERACTION_SIGNAL`; if both fail,
`M28B_NO_INTERACTION_SIGNAL`; otherwise `M28B_MIXED`. None of these outcomes
automatically promotes the candidate or changes M07.

## Implementation plan

1. Preserve the historical `entity_mixer` forward path and add an explicit
   `contextual_entity_mixer` branch.
2. Implement the masked pairwise contextual blocks and expose test-only
   contextual embeddings/contexts without changing the inference protocol.
3. Add a dedicated fresh-init trainer that binds M24-S2 provenance, exact
   architecture counts, split counts, and checkpoint metadata.
4. Add Python tests for old checkpoint loading, contextual shape/mask/action
   invariants, deterministic initialization, interaction sensitivity,
   provenance, gates, and metadata; add a Rust prereg binding test.
5. Run contract validation, commit, and push; stop for independent
   source/prereg review before any training authorization.
6. Only after that review, run the exact frozen CUDA training command and
   submit training evidence for a separate execution decision.

## Iteration log

### 2026-08-19 — M28B implementation

- Confirmed M28A is `ACCEPTED / CLOSED` at the M28B baseline and preserved its
  accepted negative result. No M28A result, M27A artifact, dataset, search
  implementation, or old `entity_mixer` forward path was changed.
- Added `contextual_entity_mixer` as a separate architecture with two masked
  pairwise blocks. The candidate has the frozen `1,689,798` parameter count;
  the historical h192 control remains `949,060`.
- Added `interaction_train.py` with fail-closed M24-S2 identity checks,
  game-level split checks, fresh initialization, deterministic DataLoader
  behavior, full-S2-only selection, offline gate derivation, and provenance
  metadata. The trainer has no inherited-checkpoint load path and no Arena
  execution path.
- Added model/trainer Python tests and a Rust config contract test. Training,
  checkpoints, reports, and Arena remain not run.
- Validation passed: full GPU Python suite `37/37`, targeted Rust contract
  `1/1`, `cargo fmt --all -- --check`, JSON parsing, and `git diff --check`.

## Final implementation

Tracked files for this round:

- `benchmarks/m28b-contextual-entity-interaction-v1.config.json`
- `training/m17_gpu/splendor_gpu/model.py`
- `training/m17_gpu/splendor_gpu/interaction_train.py`
- `training/m17_gpu/splendor_gpu/__init__.py`
- `training/m17_gpu/tests/test_interaction_model.py`
- `training/m17_gpu/tests/test_interaction_train.py`
- `crates/splendor-cli/tests/m28b_design.rs`
- `docs/m28b-contextual-entity-interaction.md`

The future authorized training command is:

```text
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m splendor_gpu.interaction_train \
  --dataset local-artifacts/m24-self-play-s2-v1/self-play.json \
  --config benchmarks/m28b-contextual-entity-interaction-v1.config.json \
  --out-dir local-artifacts/m28b-contextual-entity-interaction-v1
```

This command is recorded for the later authorized round only. It was not run
in the implementation round.

## Validation and evidence

The implementation-round checks completed before the implementation commit:

```text
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests -q — PASS, 37 passed, exit 0
cargo fmt --all -- --check — PASS, exit 0
cargo test --locked -p splendor-cli --test m28b_design -- --test-threads=1 — PASS, 1 passed, exit 0
local-artifacts/m24-torch-cu124/bin/python -m json.tool benchmarks/m28b-contextual-entity-interaction-v1.config.json — PASS, exit 0
git diff --check — PASS, exit 0
```

The M28B config SHA-256 is
`95d8911c78e10e1fccdf2d9fd9f551a3324f91f0f18c1c4f9163b14ab2c039fd`.
The implementation commit is
`e1b80aa6673865d149ef1e56b9a41f1b384b563d` and is pushed to `origin/main`.
Generated scientific artifacts have no result hash because training and Arena
were not run.

## Result and decision

M28B is implemented as a controlled representation experiment, but it is not
yet scientifically executed. The current status is
`IMPLEMENTED / CONTRACT VALIDATED`;
`training_authorization` and `arena_authorization` remain `NOT_AUTHORIZED`.
There is no offline result, Arena result, promotion, or champion change.

The next authorized gate is an independent source/prereg review of the exact
tracked implementation and config. A review pass may authorize the subsequent
CUDA training round; it does not itself authorize Arena.

## Known limitations

- M28B has no training evidence yet; all scientific claims remain prospective.
- The candidate changes both the interaction architecture and parameter count
  relative to the historical control, so a later positive result identifies
  the frozen intervention as a package rather than isolating every additional
  parameter effect.
- The contextual mixer uses one deterministic seed, as did the preceding
  controlled training round; any later result is bounded by that protocol.
- Offline gates are diagnostic eligibility checks, not playing-strength proof.
- The future Arena gate is conditional and cannot be inferred from offline
  fit or implementation tests.

## Next authorized gate

Independent M28B source/prereg review of the tracked config, model, trainer,
tests, and documentation. Until that review and a separate explicit training
authorization occur: do not run M28B training, do not materialize Arena plans,
do not run Arena, and do not authorize M25, M26, or downstream M28 work.
