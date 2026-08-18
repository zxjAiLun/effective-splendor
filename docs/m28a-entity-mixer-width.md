# M28A — Entity Mixer Width Scaling v1

```ini
MILESTONE = M28A
STATUS = IMPLEMENTED (local contract checks; independent source/prereg review pending)
BASE_COMMIT = 428c227f507a232be0aab9187e3195f8c352f4bd
FINAL_COMMIT = pending documentation binding commit
SCOPE = Fresh-init capacity-only comparison of Entity Mixer h192 versus h320 on the accepted M24-S2 corpus.
TRAINING = NOT_AUTHORIZED
ARENA = NOT_AUTHORIZED
```

## Problem and evidence

M24-S2 improved offline fit on the fixed validation/reference data without a
corresponding improvement against the M07 champion. M24.5 raised a search
bottleneck hypothesis, but the formal M27A fixed-model screen completed all
`896/896` matches and found no eligible stable search budget. M27A is now
`ACCEPTED / CLOSED` with outcome `M27A_INCONCLUSIVE`, no promotion, and M07
unchanged.

The next controlled question is whether the accepted S2 corpus contains signal
that the approximately 0.95M-parameter Entity Mixer cannot absorb. M28A tests
that question with one causal variable: `hidden_dim`.

## Initial design

M28A compares two fresh-initialized Entity Mixer models with the same entity
schema, four mixing blocks, dropout, Policy/Value targets, S2 data, split,
optimizer, deterministic seed protocol, and future Arena search. The only
model change is:

```text
control:   h192, 4 blocks, 949,060 parameters
candidate: h320, 4 blocks, 2,605,764 parameters
```

This is deliberately a capacity-only intervention. It does not attempt to
explain every possible representation or objective failure in one round.

## Scope and non-goals

### In scope

- The accepted M24-S2 `effective-splendor-neural-self-play-v2` corpus.
- Full S2 game-level validation and the frozen S1-reference diagnostic subset.
- One fresh control and one fresh candidate model.
- Pre-registered offline gates and a future 192-match Arena screen.
- Machine-checked provenance, parameter counts, initialization, and decision
  contracts.

### Not in scope / not authorized

- New self-play collection or teacher changes.
- Transformer, attention, entity-interaction redesign, target redesign,
  optimizer sweep, learning-rate sweep, PUCT tuning, or search-budget scaling.
- Formal GPU training in this preregistration implementation round.
- Arena execution, promotion, champion change, M25, M26, or any downstream
  M28 continuation.

## Contracts and invariants

- Baseline and M27A closure commit: `428c227f507a232be0aab9187e3195f8c352f4bd`.
- Dataset path is local-only:
  `local-artifacts/m24-self-play-s2-v1/self-play.json`.
- Dataset semantic self-play hash:
  `b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46`.
- Dataset raw SHA-256:
  `ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f`.
- Dataset generator checkpoint hash:
  `dc611f3d575f87e2b24221d633f8af55c98055357b05ccb822ef46ec0cb98c04`.
- Split is game-level: validation `game_index % 4 == 0` (`7,851` examples);
  train is the complement (`23,654` examples). The S1 reference is
  `game_index < 128 and game_index % 4 == 0` (`1,953` examples), and cannot
  enter training or epoch selection.
- Both models call fresh `build_model(ModelSpec(...))` after resetting seed
  `280129`; no M22/M24 weights, transplant, Net2Net, interpolation, or
  checkpoint surgery is permitted.
- The trainer validates both semantic dataset hash and raw file SHA-256. A
  path match alone is insufficient.
- Checkpoints retain `effective-splendor-gpu-checkpoint` v1 metadata and add
  M28A stage, role, fresh-init seed, both dataset identities, generator
  checkpoint hash, training config hash, split counts, and catalog hash.
- Configuration, source code, and tests are tracked. Dataset, checkpoints,
  reports, and other generated training artifacts remain ignored local files.

## Acceptance and rejection gates

These gates are frozen in
`benchmarks/m28a-entity-mixer-width-v1.config.json` before training.

| Gate | Pass condition | Consequence |
| --- | --- | --- |
| G1 full S2 validation | At least one of Policy CE or Value MSE improves by `>= 50` bps; both heads remain `>= -100` bps; Top-1 delta `>= -0.010` | Required before Arena |
| G2 S1 reference | Policy CE and Value MSE deltas `>= -100` bps; Top-1 delta `>= -0.010` | Required before Arena |
| Offline stop | G1 or G2 fails | `M28A_OFFLINE_NO_CAPACITY_SIGNAL`; valid negative result; STOP and no Arena |
| Direct Arena capacity | Candidate-v-control center `>= 5500` bps | One of two future practical Arena gates |
| Matched M07 anchor | Candidate-v-M07 minus control-v-M07 matched block center `>= +500` bps | One of two future practical Arena gates |
| Execution validity | Future screen is `192/192`, zero abort, zero candidate fault | Otherwise `M28A_EXECUTION_INVALID`, not a scientific result |

Hoeffding margins (`2166` bps direct, `4331` bps matched anchor) are reported
as diagnostic uncertainty only; they are not eligibility or promotion gates.

## Implementation plan

1. Freeze the M28A config against the verified M27A closure and M24-S2 data.
2. Implement a dedicated fresh-init trainer without changing the historical
   `self_play_train.py`, model, encoding, or agent modules.
3. Add Python tests for exact models/counts, provenance rejection, split
   isolation, fresh initialization, determinism, and checkpoint metadata.
4. Add a Rust contract test for the tracked preregistration.
5. Run local contract checks, commit, and push. Do not run formal training.
6. Stop for an independent source/prereg review. Training requires a later
   explicit authorization.

## Iteration log

### 2026-08-18 — M28A preregistration implemented

- Verified `HEAD` and `origin/main` at the required M27A closure commit before
  editing; no M27A artifact was changed.
- Verified the authoritative S2 local artifact has the frozen raw and semantic
  identities and the expected `31,505 / 23,654 / 7,851 / 1,953` counts.
- Added `capacity_train.py` with fail-closed dual provenance checks, exact
  model contracts, fresh initialization, deterministic DataLoader generators,
  full-S2-only epoch selection, S1-reference reporting, and checkpoint
  provenance metadata.
- Added Python and Rust contract tests. No GPU training, Arena match, result
  manifest, promotion, or downstream authorization was produced.

## Final implementation

Tracked files for this round:

- `benchmarks/m28a-entity-mixer-width-v1.config.json`
- `training/m17_gpu/splendor_gpu/capacity_train.py`
- `training/m17_gpu/tests/test_capacity_train.py`
- `crates/splendor-cli/tests/m28a_design.rs`
- `docs/m28a-entity-mixer-width.md`

The trainer's future command is intentionally configuration-driven:

```text
PYTHONPATH=training/m17_gpu python -m splendor_gpu.capacity_train \
  --dataset local-artifacts/m24-self-play-s2-v1/self-play.json \
  --config benchmarks/m28a-entity-mixer-width-v1.config.json \
  --out-dir local-artifacts/m28a-entity-mixer-width-v1
```

This command is not run in the preregistration implementation round because
the config remains `training_authorization = NOT_AUTHORIZED` and the recipe
requires CUDA.

## Validation and evidence

The implementation-round commands completed with these results:

```text
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests — PASS, 22 passed, exit 0
cargo fmt --all -- --check — PASS, exit 0
cargo test --locked -p splendor-cli --test m28a_design -- --test-threads=1 — PASS, 1 passed, exit 0
git diff --check — PASS, exit 0
```

Implementation smoke and contract tests are not formal training evidence and
do not establish offline improvement or playing strength. The config SHA-256
is `02693aba7bfa4de2a8e52c1490175572f2039691c564e7c9b25c2ce7f40519d4`.
The final documentation-binding commit is recorded after the implementation
commit exists.

## Result and decision

The implementation establishes a machine-checkable M28A preregistration, not a
scientific result. Current decision is `DESIGNED / NOT_AUTHORIZED` for both
training and Arena. No checkpoint, offline metric, result, promotion, or
champion change exists for M28A.

## Known limitations and non-claims

- No training has been run, so no capacity signal is established.
- The S1 reference is a generalization diagnostic, not a causal training
  partition and not a checkpoint-selection signal.
- Offline fit remains diagnostic; future competitive gates are Arena-only.
- A future `M28A_CAPACITY_SIGNAL` would justify considering more width-scaling
  work only. It would not promote the candidate or authorize M25/M26.
- Runtime-invalid attempts must be preserved and excluded, then rerun with the
  exact frozen plan; seeds, timeouts, search, and checkpoints cannot change in
  response to W/T/L.

## Next authorized gate

The next gate is an independent source/prereg review of the tracked config,
trainer, and tests. Until that review and a subsequent explicit training
authorization, the following remain unauthorized:

- both M28A training runs;
- applying offline gates to generated reports;
- materializing or executing the 192-match Arena screen;
- promotion or champion changes;
- M25, M26, and downstream M28 continuation.
