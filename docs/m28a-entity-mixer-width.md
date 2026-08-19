# M28A — Entity Mixer Width Scaling v1

```ini
MILESTONE = M28A
STATUS = ACCEPTED / OFFLINE STOP (Arena not authorized)
BASE_COMMIT = 428c227f507a232be0aab9187e3195f8c352f4bd
IMPLEMENTATION_COMMIT = e3e4285
SCOPE = Fresh-init capacity-only comparison of Entity Mixer h192 versus h320 on the accepted M24-S2 corpus.
TRAINING = ACCEPTED (CUDA; frozen recipe)
OFFLINE = M28A_OFFLINE_NO_CAPACITY_SIGNAL
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
- One authorized CUDA training run for each model and the preregistered offline
  G1/G2 application.

### Not in scope / not authorized

- New self-play collection or teacher changes.
- Transformer, attention, entity-interaction redesign, target redesign,
  optimizer sweep, learning-rate sweep, PUCT tuning, or search-budget scaling.
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
5. Run local contract checks, commit, and push, then stop for independent
   source/prereg review.
6. After source/prereg acceptance, run the exact frozen CUDA training command
   and apply only the preregistered offline gates.
7. If an offline stop occurs, record the compact result and stop before Arena;
   otherwise submit training evidence for the next explicit execution review.

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

### 2026-08-18 — source/prereg accepted; CUDA training and offline stop

- Independent source/prereg review accepted implementation basis
  `e3e428518ad946a3d1f7dfa82d911ee2673f27d2` with documentation binding
  `2e527675945d0530129ad3fa0c0bb1c14b0e0a7e`; findings were P0/P1/P2
  `0/0/2`, both non-blocking. Training was authorized; Arena remained
  unauthorized. The prereg config was not edited to record that review, so its
  frozen SHA remains unchanged.
- An initial invocation was discarded after a reported OOM and left no
  checkpoint/report/summary. The generated empty output directory was removed;
  the attempt is not evidence. A same-config, same-batch one-batch diagnostic
  passed without writing artifacts.
- The exact frozen training command was then rerun successfully with exit 0.
  Both fresh-init CUDA models completed 32 epochs under the frozen seed and
  recipe. The tracked result manifest is
  `benchmarks/m28a-entity-mixer-width-v1.result.json`, SHA-256
  `b06ab99fd622c0bcf486463fbeb08ec0b69de1b8ec782b011dc6c88d80b7c085`.
- Offline G1 failed: candidate versus control improved Policy CE by `10` bps,
  Value MSE by `34` bps, and Top-1 changed by `-0.0007642`; G1 requires at
  least one head to improve by `50` bps. G2 passed with `12` / `249` bps and
  Top-1 `-0.0015361`. The frozen decision is
  `M28A_OFFLINE_NO_CAPACITY_SIGNAL`; no Arena plan was materialized or run.

### 2026-08-19 — M28A training-evidence accepted

- Independent compact training-evidence review accepted result basis
  `82ce9843b585a5803fa97e5fec0b68b909e6679a`; current findings are
  P0/P1/P2 `0/0/1`, non-blocking. Historical source/prereg findings remain
  P0/P1/P2 `0/0/2` and are unchanged.
- The result manifest is now `ACCEPTED`; the scientific decision remains
  `M28A_OFFLINE_NO_CAPACITY_SIGNAL`. Arena remains `NOT_AUTHORIZED`,
  promotion remains `NONE`, M07 remains champion, and M25/M26/M28 continuation
  remain unauthorized.
- The one current P2 is durability-only: the result contract test checks the
  recorded offline values, while a future verifier may recompute G1/G2 and the
  decision directly from raw metrics and frozen thresholds. No retraining or
  rerun is required.

## Final implementation

Tracked files for this round:

- `benchmarks/m28a-entity-mixer-width-v1.config.json`
- `training/m17_gpu/splendor_gpu/capacity_train.py`
- `training/m17_gpu/tests/test_capacity_train.py`
- `crates/splendor-cli/tests/m28a_design.rs`
- `benchmarks/m28a-entity-mixer-width-v1.result.json`
- `docs/m28a-entity-mixer-width.md`

The trainer's future command is intentionally configuration-driven:

```text
PYTHONPATH=training/m17_gpu python -m splendor_gpu.capacity_train \
  --dataset local-artifacts/m24-self-play-s2-v1/self-play.json \
  --config benchmarks/m28a-entity-mixer-width-v1.config.json \
  --out-dir local-artifacts/m28a-entity-mixer-width-v1
```

This command was run only after the independent source/prereg review
authorized training. The config remains `training_authorization =
NOT_AUTHORIZED` by design: the review supplies execution authority without
mutating the frozen preregistration file.

## Validation and evidence

The implementation-round commands completed with these results:

```text
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests — PASS, 22 passed, exit 0
cargo fmt --all -- --check — PASS, exit 0
cargo test --locked -p splendor-cli --test m28a_design -- --test-threads=1 — PASS, 1 passed, exit 0
git diff --check — PASS, exit 0
```

The authorized training command completed with exit 0:

```text
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m splendor_gpu.capacity_train --dataset local-artifacts/m24-self-play-s2-v1/self-play.json --config benchmarks/m28a-entity-mixer-width-v1.config.json --out-dir local-artifacts/m28a-entity-mixer-width-v1
```

Training evidence:

| Model | Parameters | Best epoch | Checkpoint semantic hash | Checkpoint file SHA-256 |
| --- | ---: | ---: | --- | --- |
| control h192/b4 | 949,060 | 12 | `e5a203796efc8876d53d8f5ed34df201911c312df467b4435c3895ea8c6738ce` | `e36bb8d3c347b419f76667d2e19022d19ad7ecded2f2d1c7c64606ce6d3211d4` |
| candidate h320/b4 | 2,605,764 | 9 | `73f35fcc83ca70985951e0d777b0fed4820be45bd393803c2eec9c4abf605fe3` | `b0a7947c2c1af003f99e72970867f73cb0d40e7c75e9c966b4e8895e5fef868f` |

Both reports bind the S2 semantic/file hashes, generator checkpoint hash,
training config hash `a5dbdfb0a7a418830b4d6b25eaf87f9c83af381997583e67d29a056583b3e39e`,
fresh initialization seed `280129`, CUDA `12.4`, torch `2.6.0+cu124`, and
deterministic algorithms. The summary file SHA-256 is
`a1f377a07a7f8cbac7d688198dc1dbc3248679e481d52137f68369ee19ccbcba`.

Offline gate application was:

| Gate | Policy CE improvement | Value MSE improvement | Top-1 delta | Verdict |
| --- | ---: | ---: | ---: | --- |
| G1 full S2 validation | `10` bps | `34` bps | `-0.0007642` | FAIL |
| G2 S1 reference | `12` bps | `249` bps | `-0.0015361` | PASS |

Implementation smoke and contract tests are separate from the formal training
evidence. The config SHA-256 is
`02693aba7bfa4de2a8e52c1490175572f2039691c564e7c9b25c2ce7f40519d4`.
The compact tracked result manifest SHA-256 is
`b06ab99fd622c0bcf486463fbeb08ec0b69de1b8ec782b011dc6c88d80b7c085`.
Implementation commit: `e3e4285` (`feat(training): preregister M28A capacity
scaling`).

## Result and decision

The source/preregistration and compact training-evidence review are accepted,
but capacity-only scaling did not meet the preregistered full-S2 offline gate.
The formal decision is `M28A_OFFLINE_NO_CAPACITY_SIGNAL`: G1 failed and G2
passed. This is an accepted negative training result, not a playing-strength
result. Arena was not authorized or run, promotion remains `NONE`, and M07
remains champion.

The tracked result manifest records the local checkpoint/report paths and
hashes. The config remains frozen with its original `DESIGNED` status and
`NOT_AUTHORIZED` config fields; review-derived training authority is not
written back into the prereg file.

## Known limitations and non-claims

- The experiment uses one deterministic seed (`280129`); this negative result
  is a result under that frozen protocol, not a general proof about all seeds.
- Offline fit remains diagnostic and no Arena strength estimate exists because
  G1 failed before the Arena gate.
- The S1 reference is a generalization diagnostic, not a causal training
  partition and not a checkpoint-selection signal.
- The catalog semantic hash is hard-bound in trainer source rather than config;
  this is safe for v1 but is a durability follow-up for a future schema.
- The current result contract test records expected G1/G2 values but does not
  yet recompute them from raw metrics and frozen thresholds; this is a
  non-blocking durability follow-up.
- The negative result does not authorize M25, M26, or a downstream M28
  continuation. A new route/diagnostic prereg is required for the next causal
  question.
- Runtime-invalid attempts must be preserved and excluded, then rerun with the
  exact frozen plan; seeds, timeouts, search, and checkpoints cannot change in
  response to W/T/L.

## Next authorized gate

There is no further execution gate within M28A. The accepted result closes the
capacity-only question at the current protocol: the frozen offline stop has
fired and Arena is prohibited. The next scientific work requires a new,
independent route/diagnostic preregistration; the following remain
unauthorized:

- materializing or executing the 192-match Arena screen;
- promotion or champion changes;
- M25, M26, and downstream M28 continuation.
