# M28B — Contextual Entity Interaction v1

```ini
MILESTONE = M28B
STATUS = QUALIFICATION 2B EXECUTED / HOST_ENVELOPE_LIMIT / HOST MIGRATION AUTHORIZED
BASE_COMMIT = c0caa883e47cadce1ae85c78b85ba7c4e69ac007
IMPLEMENTATION_COMMIT = e1b80aa6673865d149ef1e56b9a41f1b384b563d
SCOPE = One fresh-init contextual entity interaction candidate versus one historical Entity Mixer control on the accepted M24-S2 corpus.
TRAINING = HOLD pending external host qualification 2C
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
- Runtime Repair 1: one packed encoded cache, explicit CPU thread caps, and a
  non-scientific exact-equality/inference diagnostic.
- Runtime Investigation 2A: bounded CPU/CUDA profiling of the cache-backed
  forward/backward/optimizer path with read-only telemetry and a 90°C host
  safety abort.

### Not in scope / not authorized

- Formal M28B training or checkpoint generation in this runtime-investigation
  round.
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
- The original scientific config remains byte-for-byte bound to SHA-256
  `95d8911c78e10e1fccdf2d9fd9f551a3324f91f0f18c1c4f9163b14ab2c039fd`.
  Runtime Repair 1 is separately specified by
  `benchmarks/m28b-runtime-repair-1.json`; it cannot alter the M28B model,
  data, optimizer, split, seed, batch, or search contract.
- The packed cache uses the existing player-view encoder once, stores
  memory-mapped tensors plus a manifest, and is accepted only after all
  `31,505/31,505` online/cache samples compare exactly. CPU runtime is
  fail-closed at Torch intra-op `2`, inter-op `1`, with all four explicit
  environment caps set to `2`.
- Runtime Investigation 2A is separately specified by
  `benchmarks/m28b-runtime-investigation-2a.json`. It reuses the accepted cache
  manifest identity and does not reread the raw dataset or rerun exact
  equality. It cannot mutate Linux power policy, CPU governor/Turbo, GPU power
  limits, the scientific config, checkpoints, offline results, or Arena.
- The investigation's `>=90°C` threshold is a host-safety stop only. A profile
  below the threshold would not be a scientific PASS or training authorization.

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
7. For Runtime Repair 1, build/validate the cache and run the diagnostic first;
   only a cool, stable host permits the fresh formal rerun in a new output
   directory. The previous partial control checkpoint is never resumed.

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

### 2026-08-20 — M28B Runtime Repair 1 implementation

- The source/prereg review accepted the frozen M28B implementation and
  authorized the GPU training stage, but the first control attempt was
  interrupted by a host shutdown after `598.15s`; no OOM, NVIDIA Xid, or
  critical thermal-trip record was found, and the partial checkpoint is not a
  scientific result and must not be resumed.
- Added the separately tracked Runtime Repair 1 contract
  `benchmarks/m28b-runtime-repair-1.json`. The original M28B scientific config
  remains unchanged and retains its original SHA-256.
- Added `encoded_cache.py`: a packed memory-mapped cache for entities, masks,
  globals, values, legal actions, policy targets, and action offsets. Its
  manifest binds both source identities, the player-view encoder contract,
  dimensions, array hashes, and a manifest digest. The formal trainer now
  consumes only a validated cache and records its digest in any future
  checkpoint/report metadata.
- Added `runtime.py` with fail-closed Torch/BLAS thread caps (`2/1`) and
  host CPU/RAM/GPU/temperature telemetry, plus
  `m28b_runtime_repair.py`, which performs cache construction, full online vs
  cache equality, and a short two-model inference smoke without writing a
  checkpoint or result.
- The implementation tests currently pass `41/41`. The real-data diagnostic
  has not yet run because the host was observed at `94–97°C` CPU package/core
  temperature while unrelated parallel processes were consuming CPU. No new
  scientific evidence has been claimed.

### 2026-08-20 — Runtime Repair 1 source review accepted; diagnostic authorized

- Independent source review accepted commit
  `828eb9e8656628d71b36289f6a9158d8f6e3890a` against direct parent
  `097fe26c0ea63d2d5fe7dcbc954efd73775f3997`; P0/P1/P2=`0/0/2`, with both
  P2 findings non-blocking.
- Runtime Repair diagnostic is `AUTHORIZED`. Fresh formal M28B training is
  `HOLD` until the diagnostic proves `31,505/31,505` exact equality, records
  cache and report hashes, confirms thread caps `2/1`, and shows finite smokes
  with safe host telemetry. Arena remains `NOT_AUTHORIZED`.
- The diagnostic was not started in this turn: CPU package/core telemetry was
  still `94–98°C` while unrelated Lichess processing consumed roughly one CPU
  core. No unrelated process was terminated, and no scientific artifact was
  created.

### 2026-08-20 — Runtime Repair diagnostic completed; host-safety gate failed

- The authorized diagnostic built the local cache and checked all
  `31,505/31,505` examples with exact `torch.equal()` equality. Cache manifest
  semantic SHA is
  `f549549ea0a44c552e0114dddde13a5e8385aa0a04d5cc96b3a0c8a62b827e6d`; the
  `manifest.json` file SHA is
  `f5e965a3c778c5de6d859ec1886c34b1196ccd6a9b92f87e2599230b66365294`.
- The diagnostic report is
  `local-artifacts/m28b-runtime-repair-1-diagnostic.json`, SHA-256
  `772b3844122b08d9eea46c7ad3048baf13e655ec301231739f0a5b4aa9367a8a`.
  It records `scientific_evidence=false`, `formal_training=false`, no
  checkpoint/result/Arena output, CPU threads `2/1`, and all four environment
  caps set to `2`.
- Both model smokes produced finite outputs: control and candidate each ran
  four batches / 512 examples. However telemetry rose from about `61–67°C`
  before work to TCPU/package `85–90°C` after exact equality and `93°C` during
  the smoke window. The diagnostic is therefore `NOT VERIFIED / HOST-SAFETY
  HOLD`, despite the data/cache correctness checks passing. Formal M28B
  training remains `HOLD`; Arena remains `NOT_AUTHORIZED`.

### 2026-08-21 — Runtime Investigation 2A executed; host-safety abort

- Added the read-only profiler contract
  `benchmarks/m28b-runtime-investigation-2a.json` and module
  `splendor_gpu.m28b_runtime_investigation` in commit `3b5e473`. The profiler
  uses the existing mmap cache, frozen batch size `128`, fresh control/candidate
  initialization, and the actual forward/loss/backward/gradient-clip/AdamW
  path. It makes no Linux power-policy mutation and writes no checkpoint,
  offline result, or Arena artifact.
- The run used four batches per model. Control completed `4/4`; candidate
  completed `1/4` and stopped at `TCPU=90.0°C` after candidate batch 1. The
  post-run telemetry reached `TCPU=93.0°C` and `TCPU_PCI=93.0°C`; the host had
  returned to about `68°C` TCPU after the process ended.
- Report:
  `local-artifacts/m28b-runtime-investigation-2a.json`, SHA-256
  `a9382bcdba022263b49ec5a39af9eeb88e0828905c7ca0b572ca83dbfc6c0dfa`.
  Control and candidate traces are local-only; their SHA-256 values are
  `f3773e8e3e6af05489720319975eb154f15bdde236b0f6182a6beab0945b3a9d` and
  `917f51bcdee37484a144850ca9b9d658d10a7dcbcf61fb11a7e99772f3750444`.
- The cached input path is not the dominant measured transfer cost: control
  data wait/collate averaged `16.52 ms` per batch and host-to-device transfer
  `1.54 ms`; candidate's single completed batch measured `13.38 ms` and
  `0.75 ms`. The GPU trace contains `aten::addmm`, `aten::mm`, pinned H2D
  copies, and AdamW device work, so the GPU was active rather than absent.
  The first control batch includes CUDA/profiler warm-up; its later batches
  were materially shorter than the first.
- The report is `HOST_SAFETY_ABORT`, not a model result and not a training
  authorization. Raw profiler `Unrecognized` entries are profiler overhead and
  `cudaDeviceSynchronize` entries are instrumentation barriers; neither is
  treated as a scientific CPU bottleneck. Formal training remains `HOLD` and
  Arena remains `NOT_AUTHORIZED`.

### 2026-08-21 — Runtime Qualification 2B natural-path run executed; HOST_ENVELOPE_LIMIT

- Added the contract `benchmarks/m28b-qualification-2b.json` and runner module
  `splendor_gpu.m28b_qualification` to perform the natural-path shadow epoch test
  without `torch.profiler`, per-batch CUDA synchronizations, memory/shape tracing,
  or checkpoint output.
- Telemetry ran at 250ms intervals capturing per-process user/system CPU, per-thread
  breakdown, context switches, RSS/swap, individual CPU core/package thermal sensors,
  core frequencies, and NVML GPU metrics (power, utilization, clocks, temperature).
- Pre-flight baseline dropped to 64.0°C (below the required < 65.0°C).
- The natural-path training loop was launched with `batch_size=128`,
  `torch_threads=2/1`, `workers=0`. Process CPU measured ~200% (2 cores active),
  and GPU active power quickly climbed to 63.8W / 69% utilization.
- At sample 9 (~2.43s), CPU package/TCPU temperatures spiked sharply from 58.0°C to
  93.0°C (TCPU=91.0°C, x86_pkg_temp=93.0°C), triggering the fail-closed hard safety
  abort limit (88.0°C).
- Report: `local-artifacts/m28b-qualification-2b-1787317745/qualification-2b-report.json`,
  SHA-256 `fe62f56785dc0e03485ac9db631e280392fd38ece19ba04251454200bed8aee6`.
  Telemetry: `local-artifacts/m28b-qualification-2b-1787317745/telemetry-samples.json`,
  SHA-256 `ba86e32acf95ce4b999d7b8da1dbcf37036489da29b69eecda22a3457b20b894`.
- Contract SHA-256: `536e91b162f789d2c52ff4ed5a268abf85fd02cb130c97bccadc7351b1952477`.
- Module SHA-256: `40dc35e98f5f9109a4293ffb601a67ff052af19b355c405bc00c61cccaae2c4b`.
- Verdict: `HOST_ENVELOPE_LIMIT`.
- Root cause: input wait is low, GPU is active and drawing power, process CPU is strictly capped to 2 cores, yet the host cooling envelope cannot dissipate combined CPU Turbo + GPU power under load without breaching thermal safety limits.

## Final implementation

Tracked files for this round:

- `benchmarks/m28b-contextual-entity-interaction-v1.config.json`
- `benchmarks/m28b-runtime-repair-1.json`
- `benchmarks/m28b-runtime-investigation-2a.json`
- `benchmarks/m28b-qualification-2b.json`
- `training/m17_gpu/splendor_gpu/model.py`
- `training/m17_gpu/splendor_gpu/interaction_train.py`
- `training/m17_gpu/splendor_gpu/encoded_cache.py`
- `training/m17_gpu/splendor_gpu/runtime.py`
- `training/m17_gpu/splendor_gpu/m28b_runtime_repair.py`
- `training/m17_gpu/splendor_gpu/m28b_runtime_investigation.py`
- `training/m17_gpu/splendor_gpu/m28b_qualification.py`
- `training/m17_gpu/splendor_gpu/__init__.py`
- `training/m17_gpu/tests/test_interaction_model.py`
- `training/m17_gpu/tests/test_interaction_train.py`
- `training/m17_gpu/tests/test_encoded_cache.py`
- `training/m17_gpu/tests/test_runtime_investigation.py`
- `training/m17_gpu/tests/test_qualification.py`
- `crates/splendor-cli/tests/m28b_design.rs`
- `docs/m28b-contextual-entity-interaction.md`

The future authorized training command is:

```text
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m splendor_gpu.interaction_train \
  --dataset local-artifacts/m24-self-play-s2-v1/self-play.json \
  --config benchmarks/m28b-contextual-entity-interaction-v1.config.json \
  --encoded-cache local-artifacts/m28b-encoded-cache-v1 \
  --out-dir local-artifacts/m28b-contextual-entity-interaction-v1-rerun-rt1
```

This command is recorded for the later authorized fresh rerun only. It was not
run in the Runtime Repair 1 or Runtime Investigation 2A round.

The diagnostic command is:

```text
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 \
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m splendor_gpu.m28b_runtime_repair \
  --dataset local-artifacts/m24-self-play-s2-v1/self-play.json \
  --config benchmarks/m28b-contextual-entity-interaction-v1.config.json \
  --cache-dir local-artifacts/m28b-encoded-cache-v1 \
  --report local-artifacts/m28b-runtime-repair-1-diagnostic.json \
  --batches 4
```

The Runtime Investigation 2A command was:

```text
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 \
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m splendor_gpu.m28b_runtime_investigation \
  --config benchmarks/m28b-contextual-entity-interaction-v1.config.json \
  --contract benchmarks/m28b-runtime-investigation-2a.json \
  --encoded-cache local-artifacts/m28b-encoded-cache-v1 \
  --report local-artifacts/m28b-runtime-investigation-2a.json \
  --batches 4
```

This command exited `0` and wrote a diagnostic report with status
`HOST_SAFETY_ABORT`; it did not write a checkpoint, training report, offline
result, or Arena artifact.

The Runtime Qualification 2B natural-path shadow command was:

```text
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 \
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python training/m17_gpu/splendor_gpu/m28b_qualification.py \
  --contract benchmarks/m28b-qualification-2b.json \
  --config benchmarks/m28b-contextual-entity-interaction-v1.config.json \
  --encoded-cache local-artifacts/m28b-encoded-cache-v1
```

This command exited `0` and produced immutable artifacts under
`local-artifacts/m28b-qualification-2b-1787317745/` with verdict `HOST_ENVELOPE_LIMIT`.

## Validation and evidence

The implementation and diagnostic checks completed so far are:

```text
PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests -q — PASS, 37 passed, exit 0
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests -q — PASS, 41 passed, exit 0
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests -q — PASS, 45 passed, exit 0
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2 PYTHONPATH=training/m17_gpu local-artifacts/m24-torch-cu124/bin/python -m pytest training/m17_gpu/tests/test_runtime_investigation.py -q — PASS, 4 passed, exit 0
python3 -m py_compile training/m17_gpu/splendor_gpu/m28b_runtime_investigation.py — PASS, exit 0
cargo fmt --all -- --check — PASS, exit 0
cargo test --locked -p splendor-cli --test m28b_design -- --test-threads=1 — PASS, 1 passed, exit 0
local-artifacts/m24-torch-cu124/bin/python -m json.tool benchmarks/m28b-contextual-entity-interaction-v1.config.json — PASS, exit 0
git diff --check — PASS, exit 0
Runtime Repair diagnostic command — exit 0; exact/cache/thread/model checks passed, but host-safety gate failed and diagnostic is not accepted
Runtime Investigation 2A command — exit 0; control `4/4`, candidate `1/4`, host-safety abort at `TCPU=90.0°C`; report not accepted as a training/runtime PASS
Runtime Qualification 2B natural-path shadow run — exit 0; 250ms telemetry captured; hard safety abort triggered at ~2.5s with peak 93.0°C; verdict HOST_ENVELOPE_LIMIT
```

The M28B config SHA-256 is
`95d8911c78e10e1fccdf2d9fd9f551a3324f91f0f18c1c4f9163b14ab2c039fd`.
The original implementation commit is
`e1b80aa6673865d149ef1e56b9a41f1b384b563d`; the Runtime Investigation 2A
implementation commit is `3b5e473` and both are pushed to `origin/main`.
Generated scientific artifacts have no result hash because formal training and
Arena were not run. The Runtime Repair 1 data correctness checks passed, but
the diagnostic is not accepted because its own telemetry crossed the host
thermal-safety condition.

## Result and decision

M28B remains a controlled representation experiment with no new scientific
result. The source/prereg is `ACCEPTED / FROZEN`; Runtime Repair 1 remains
`NOT VERIFIED / HOST-SAFETY HOLD`, Runtime Investigation 2A is
`EXECUTED / HOST-SAFETY ABORT`, and Runtime Qualification 2B is
`EXECUTED / HOST_ENVELOPE_LIMIT`; fresh formal training remains on `HOLD`.
The first host-interrupted attempt is
`M28B_RUNTIME_INVALID` rather than a model result.
There is no accepted offline result, Arena result, promotion, or champion
change; Arena remains `NOT_AUTHORIZED`.

The decision per the Qualification 2B protocol is:
- High-frequency 250ms telemetry shows data wait / CPU thread usage is strictly bounded (~2 cores), while GPU actively draws power (~64W) and SM clock ramps to 2535 MHz.
- Host thermal headroom breaches the 88.0°C safety abort threshold within ~2.5s of combined load.
- In accordance with the preregistered decision rules, no further code-level Runtime Repairs (3/4) are warranted on this machine; formal training requires host migration.

## Known limitations

- M28B has no accepted training evidence yet; all scientific claims remain
  prospective. The preserved partial control artifact is excluded from
  scientific evidence.
- The candidate changes both the interaction architecture and parameter count
  relative to the historical control, so a later positive result identifies
  the frozen intervention as a package rather than isolating every additional
  parameter effect.
- The contextual mixer uses one deterministic seed, as did the preceding
  controlled training round; any later result is bounded by that protocol.
- Offline gates are diagnostic eligibility checks, not playing-strength proof.
- The future Arena gate is conditional and cannot be inferred from offline
  fit or implementation tests.
- Runtime Investigation 2A uses profiler instrumentation and explicit CUDA
  synchronization barriers for stage timing; its wall-clock timings are
  diagnostic and not a throughput benchmark. Its candidate profile stopped
  after one batch, so candidate steady-state timing remains unmeasured.
- The brief profile's aggregate machine-wide CPU utilization was low while
  package/TCPU sensors rose sharply. This rules out only a simple claim of
  sustained all-core saturation; it does not identify a safe formal-training
  envelope or prove the root cause of the thermal response.

## Next authorized gate

Current host is unqualified under the thermal envelope limit. Formal training on
this host is not authorized. Next authorized step is host migration and one
bounded execution qualification on the destination host (M28B Qualification 2C).
Formal M28B training will be unlocked only after 2C passes on the new host.
