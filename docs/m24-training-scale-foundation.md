# M24 — Training Scale & Self-Play Dataset Foundation

```ini
MILESTONE = M24
STATUS = AUTHORIZED
BASE_COMMIT = 4ee8852c5ac7232c13e7f2ead1a25aaa4955ad3f
IMPLEMENTATION_COMMIT = a797f131c25bffc49fd66abe212c63fc88c9305c
FINAL_COMMIT = <fill only after it exists>
SCOPE = Build a provenance-bound, staged self-play data foundation for Entity Mixer and measure whether training scale alone improves learning before any architecture or search change.
```

## Problem and evidence

The current training mainline is:

```text
M17 Entity Mixer GPU Policy-Value
 -> M18A neural-ISMCTS / AlphaZero-like self-play (2 games, 122 examples)
 -> M22 scaled self-play (32 games, 1,992 examples)
 -> 48-match multi-seed league: no measured improvement
```

The machine-verifiable strength evidence is unambiguous:

```text
M22 multi-seed league
Heuristic  21-3  Elo 1778
M07        15-9  Elo 1580
M18A        6-18 Elo 1321
M22         6-18 Elo 1321
M22 vs M18A      4-4
M22 vs M07       1-7
M22 vs heuristic 1-7

M19 internal championship (provisional)
Heuristic  11-1  Elo 1908
M07         8-4  Elo 1637
M17         7-5  Elo 1567
M18A        5-7  Elo 1429
M13         2-10 Elo 1196
M18B        2-10 Elo 1196
```

Two verified human replays against the currently strongest measured baseline
(`heuristic-v1`) were won by the human 16-5 and 16-4 from both seats. Those
two games are anecdotal, not a formal strength gate, but they agree with the
project's formal conclusion: every trained checkpoint is still below a simple
hand-written baseline.

The largest uncertainty is therefore not infrastructure. It is:

> Does the Entity Mixer + neural-ISMCTS AlphaZero-like pipeline learn playing
> strength when data scale and data quality are sufficient?

M22 used 1,992 examples. That is still a plumbing-test scale. This round
freezes a staged scaling experiment before running it.

## Objective and promotion target

The training mainline now has one target:

```text
Produce the first neural checkpoint that beats M07 root determinization
in a frozen multi-seed Arena promotion gate.
```

Notes on baselines:

- M10/M13 gates already use `determinization-s4-d1-n2000-v1` as the frozen
  search champion. M24 keeps that convention.
- M09 and M19 show `heuristic-v1` currently measures stronger than M07. A
  future neural candidate must also be screened against heuristic before any
  external or product claim, but the first milestone target remains M07.

M24 does **not** attempt promotion. It establishes the data foundation and
scale learning curve needed before M25 warm-start v2 and M26 generation RL.

## Initial design

### Keep the architecture and search fixed

```text
Architecture       Entity Mixer Policy-Value, 949,060 parameters
Policy target      normalized neural-ISMCTS root visit distribution
Value target       terminal viewer-relative [self, opponent] outcome
Search             player-view information set, hidden-state sampling, PUCT
Device             CUDA (fail closed)
```

No Transformer, no new loss family, no PUCT/simulations/depth scaling in M24.

### Staged corpus sizes

All three stages collect self-play from the **same frozen M22 checkpoint**.
The corpora are **nested**, not independent:

```text
M24-S1 = seeds 260001..260128               128 games
M24-S2 = M24-S1 + 384 fresh seeds           512 games
M24-S3 = M24-S2 + 1,536 fresh seeds         2,048 games
```

Each stage uses identical search/hyper-parameters except `self_play_id`,
seed list, and the stage-specific training identity. S2 and S3 seed ranges are
frozen only when those stages are authorized; the nesting rule above is frozen
now. Comparing nested corpora means the only variable is added sample volume,
not sample composition.

Example counts are estimates; actual counts come from the dataset.

### M24-S1 frozen collection config

Tracked config: `benchmarks/m24-self-play-s1-v1.config.json`

```text
self_play_id          m24-self-play-s1-v1
base checkpoint       M22 dc611f3d...98c04
game seeds            260001..260128 (128 fresh seeds, no known reuse)
action_seed           260018
search_seed           26000018
simulations           16
max_depth_turns       1
puct_exploration_milli 1500
temperature_plies     24
max_plies             512
device                cuda
```

Frozen identities recorded before execution:

```text
config file SHA-256   4a2ed142c1a4ec7c8710c6c38249942493fff1cbfe13193f6a64060efdc8945d
collector config_hash 523ef24f268b11711b4776e6266342435c6856f49a381ca441e2bbb87afb3a15
```

### M24-S1 training hyper-parameters (pre-registered)

The training config file cannot be published until the self-play dataset hash
exists, but the hyper-parameters are frozen now:

```text
training_id              m24-self-play-s1-v1
model_id                 m24-entity-mixer-self-play-s1-v1
base_checkpoint          M22 dc611f3d...98c04
expected_self_play_hash  <fill from actual M24-S1 collection>
device                   cuda
seed                     260129
batch_size               128
epochs                   16
learning_rate            1e-4
weight_decay             1e-4
value_loss_weight        0.5
gradient_clip_norm       1.0
validation_game_modulus  4
validation_game_remainder 0
```

This isolates corpus size: M22 used the same search settings and training
shape; M24-S1 changes only the game count and identities.

### SelfPlayDatasetV2 provenance schema

The v1 collector stays byte-for-byte frozen for M18A/M22 reproducibility. M24
adds a second command that emits
`effective-splendor-neural-self-play-v2` with this identity chain:

```text
SelfPlayGameSourceV2
  game_index
  game_seed
  base_checkpoint_hash
  collector_config_hash
  search_config_identity
  replay_document_hash
  replay_final_state_hash
  embedded verified ReplayV1
  terminal result
  first_example_index + example_count

SelfPlayExampleV2
  game_index / ply / actor
  Observation
  observation_hash
  visible_history_hash
  information_set_hash
  legal_actions
  search visit distribution (action_stats)
  chosen_action
  final scores / ranks
  policy_target_visits (legal-action order)
  value_target (viewer-relative [self, opponent])
```

`search_config_identity` is frozen as
`neural-ismcts-s{simulations}-d{max_depth_turns}-c{puct_milli}-v1`.

The diagnostic command re-verifies every embedded replay and every example
from the replay trace, then reports:

```text
dataset/file hashes
game count, seed uniqueness
example count and plies-per-game distribution
winner/seat balance
legal-action-count distribution
legal-action-type distribution
chosen-action-type distribution
policy-target entropy distribution
search-visit entropy distribution
duplicate observation rate
duplicate information-set rate
value-target distribution
```

A compact tracked result manifest is still published after the actual run,
following the M12/M22 evidence pattern.

## Scope and non-goals

### In scope

- M24-S1 collection and training under the frozen plan above.
- SelfPlayDatasetV2 collector/schema and diagnostics.
- Dataset audit and scale-progression decision.
- Tracked milestone doc, configs, result manifest, and handoff updates.

### Not in scope / not authorized

- Architecture changes, Transformer experiments, or Entity Mixer v2.
- Changing simulations, depth, PUCT, or temperature within M24.
- M07 teacher-corpus generation (moved to M25).
- Human-replay warm-up training (candidate data source, not part of M24-S1).
- Rainbow/DQN scaling.
- Promotion gate execution or champion changes.

## Contracts and invariants

- Agent decisions only read `Observation`, legal actions, and permitted public
  history. `FullState` never enters the model or search evaluator.
- Generated self-play datasets, checkpoints, and reports stay under ignored
  `local-artifacts/`; only compact configs/result manifests are tracked.
- Game seeds, action seeds, search seeds, and training seeds are frozen before
  execution and are never changed after seeing results.
- The M07 frozen baseline and all previous `REJECT`/`NOT PROMOTED` records
  remain unchanged.
- Offline CE, visit top-1, and Value MSE are diagnostic only. Only completed
  Arena leagues and frozen promotion gates establish strength.

## Acceptance and rejection gates

| Gate | Evidence | Pass condition | Meaning |
| --- | --- | --- | --- |
| G1 S1 collection | `collect-gpu-self-play-v2` exit 0; v2 dataset under `local-artifacts/m24-self-play-s1-v1/` | 128/128 games collected, zero duplicate seeds, every embedded replay verifies, non-empty examples | S1 dataset is complete and provenance-bound |
| G2 S1 audit | `diagnose-gpu-self-play-v2` report and unit/integration tests | report exists with every required metric and zero binding errors | Dataset is auditable |
| G3 S1 training | training report and checkpoint | training runs to completion on CUDA; validation split non-empty; semantic checkpoint hash exists | S1 diagnostic checkpoint and baseline measurement noise exist |
| G4 scale decision | S1 and S2 diagnostic learning curves | S2 is authorized after S1 PASS; `m24-scale-gate-v1` is frozen **after** S1 measurement noise is known and **before** S2 runs | S2 is the first actual scale test |
| G5 continuation | recorded G4 decision in this doc and handoff | S1→S2 movement PASS permits S3/M25; movement FAIL stops M24 scaling, requires data-quality diagnosis, and does **not** auto-authorize M25 | No architecture/search changes are smuggled into M24 |

G4 thresholds are now frozen in `benchmarks/m24-scale-gate-v1.json` after
reviewing S1 measurement noise. The frozen gate is machine-checkable and covers
offline Policy CE/NLL, visit top-1, Value MSE, and a fresh multi-seed Arena
screen; offline movement alone never establishes strength.

A `REJECT` at G4 is a valid scientific result, not an execution failure.

## Implementation plan

1. ~~Add SelfPlayDatasetV2 schema and collector fields with unit tests.~~ implemented.
2. ~~Add the diagnostic command/report and an independent validator.~~ implemented.
3. ~~Run full workspace Rust tests and Clippy before marking implementation ready.~~ done.
4. ~~Run M24-S1 collection on the user's CUDA machine using the frozen config.~~ done.
5. ~~Freeze `expected_self_play_hash` into `benchmarks/m24-self-play-s1-v1.training.json` before training.~~ done.
6. ~~Train M24-S1 and publish the diagnostic report and compact result manifest.~~ done.
7. Review G1-G3 evidence; after S1 PASS, freeze `m24-scale-gate-v1` and only
   then authorize S2.

## Iteration log

### Iteration 1 — 2026-08-15

- Change: authored M24 milestone, froze M24-S1 collection config and pre-registered training hyper-parameters.
- Reason: current main has no M24 config; training mainline is re-centered on data scale.
- Evidence: repository state at `4ee8852`; M22/M19 tracked result files.
- Outcome: M24 `AUTHORIZED`; S1 config created; no dataset/training has run yet.
- Decision for next iteration: implement SelfPlayDatasetV2 and diagnostics before running S1.

### Iteration 2 — 2026-08-15

- Change: implemented `collect-gpu-self-play-v2` and
  `diagnose-gpu-self-play-v2`; extended `self_play_train.py` to accept v2;
  added Rust unit/integration tests and Python contract tests.
- Reason: G1/G2 require a verifiable dataset before S1 can run.
- Evidence: `cargo test --workspace -- --skip shutdown_reaps_child` passes
  with zero failures; `shutdown_reaps_child` is an unrelated Linux-only
  kill-by-signal process-test failure and is not part of M24.
  `cargo clippy --workspace --all-targets -- -D warnings`, `cargo fmt --all
  --check`, and diff checks pass. Python files syntax-checked (Torch
  unavailable in this Linux workspace, so full pytest remains a Windows/CUDA
  step).
- Outcome: implementation gate `PASS`; S1 is the next execution step.
- Decision for next iteration: run M24-S1 collection and diagnostics on CUDA.

### Iteration 3 — 2026-08-15

- Change: installed project CUDA environment in ignored
  `local-artifacts/m24-torch-cu124` (`torch 2.6.0+cu124`, CUDA 12.4 runtime
  wheels, NVIDIA driver 580 / RTX 4060 Laptop GPU); validated v2 collector,
  diagnostics, and self-play training end-to-end with small CUDA smokes.
- Reason: current Linux workspace had no `python`/`torch`; formal S1 requires
  CUDA without silent CPU fallback.
- Evidence: full M24-S1 collection completed 128/128 games / 7,876 examples;
  diagnostics verified 128/128 embedded replays with zero binding errors;
  CUDA training completed in 63.3s and emitted the M24-S1 checkpoint.
- Outcome: G1/G2/G3 `PASS`; M24-S1 baseline exists.
- Decision for next iteration: review S1 diagnostics, freeze
  `m24-scale-gate-v1`, then authorize S2.

### Iteration 4 — 2026-08-15

- Change: independent re-review of Commit C `dbe47ab` completed; the P1/P2
  provenance fixes were confirmed against the hardened validator and
  adversarial tests. M24-S1 is accepted as the first M24 scale baseline.
- Reason: Commit C fixed P1-1 (replay seed binding), P1-2 (root visit sum and
  value bounds), P2-1 (dataset top-level engine/ruleset identity), and P2-2
  (result manifest hash recomputation). Re-running the hardened validator on
  the original S1 dataset produced byte-identical diagnostics
  (`42605979cbc721bcf23564c67be9289146faa609975c7269ae96c0546938565d`), so no
  re-collection or retraining was required.
- Evidence: `cargo test -p splendor-cli` passes, including the new adversarial
  M24 provenance tests; Python `training/m17_gpu/tests` passes 13/13; tracked
  result manifest now records `review.acceptance = ACCEPTED`.
- Outcome: M24-S1 `ACCEPTED`; G1/G2/G3 remain `PASS`; G4 scale decision is
  still `NOT_YET_RUN`.
- Decision for next iteration: review S1 measurement noise and freeze
  `m24-scale-gate-v1` before authorizing S2.

### Iteration 5 — 2026-08-15

- Change: reviewed S1 diagnostics/measurement noise and froze
  `benchmarks/m24-scale-gate-v1.json` as the machine-checkable M24 scale gate.
- Reason: M24-S1 is accepted; the next required pre-registration is the S1→S2
  movement gate so that S2 cannot be authorized or interpreted after seeing S2
  results.
- Evidence: `benchmarks/m24-scale-gate-v1.json` defines offline movement
  thresholds for Policy CE/NLL, visit top-1, and Value MSE against the S1
  baseline, plus a fresh multi-seed Arena screen against S1 with M07 and
  heuristic anchors. A workspace test binds the gate file to the S1 hashes and
  required structure.
- Outcome: `m24-scale-gate-v1` `FROZEN`; G4 scale decision remains
  `NOT_YET_RUN`; S2 is still not authorized.
- Decision for next iteration: freeze the S2 nested corpus/config and then
  authorize S2 collection.
### Iteration 6 — 2026-08-15

- Change: M24 Scale Gate Repair 1 closed independent review P1-1..P1-4 and P2.
- Reason: the first gate freeze candidate was not yet machine-checkable:
  - P1-1: S1/S2 offline metrics must be compared on the same fixed S1 validation subset.
  - P1-2: the pairwise lower-bound statistic must reuse the accepted promotion Hoeffding contract.
  - P1-3: S1 anchor baselines must be explicitly included in the same fresh Arena screen.
  - P1-4: exact Arena seeds, seat schedule, timeouts, and runtime/search identity must be frozen before S2.
  - P2: the workspace test must bind the gate's S1 offline baseline back to the tracked result manifest and hash-bind the Arena plan.
- Evidence: `benchmarks/m24-scale-gate-v1.json` now pins the fixed S1 reference offline subset, the Hoeffding statistical method, S2/S1/M07/heuristic comparisons, and references `benchmarks/m24-s2-arena-screen-v1.bundle.json` by SHA-256. `crates/splendor-cli/tests/m24_result.rs` verifies these bindings.
- Outcome: `m24-scale-gate-v1` remains `FROZEN` as Repair 1; G4 remains `NOT_YET_RUN`; S2 is still not authorized.
- Decision for next iteration: after independent re-review PASS, freeze the S2 nested corpus/config and authorize S2.

### Iteration 7 — 2026-08-15

- Change: M24 Scale Gate Repair 2 replaced the single 4-agent Arena plan with five 2-agent pairwise plans and a bundle manifest.
- Reason: `EvaluationPlanV1` with 4 agents expands to 4-player games, but M24's GPU Entity Mixer runtime is 1v1-only. The screen must therefore be represented as five standard 2-agent evaluation plans:
  - `m24-s2-vs-s1-v1`
  - `m24-s2-vs-m07-v1`
  - `m24-s1-vs-m07-v1`
  - `m24-s2-vs-heuristic-v1`
  - `m24-s1-vs-heuristic-v1`
- Evidence: all five plans share `game_seeds 300001..300032`, timeouts `5000/10000/2000`, and expand to exactly 64 matches each (32 seeds x 2 seat rotations). They are bound by `benchmarks/m24-s2-arena-screen-v1.bundle.json`, which the gate references by SHA-256. The Hoeffding formula now also records saturating bounds.
- Outcome: `m24-scale-gate-v1` remains `FROZEN` as Repair 2; G4 remains `NOT_YET_RUN`; S2 is still not authorized.
- Decision for next iteration: after independent re-review PASS, freeze the S2 nested corpus/config and authorize S2.
### Iteration 8 — 2026-08-15

- Change: M24 Scale Gate Repair 3 froze the S2 checkpoint placeholder materialization contract.
- Reason: the three S2-containing plans are frozen templates, but their `__M24_S2_CHECKPOINT_HASH__` placeholder must have a machine-checkable path to a realized `EvaluationPlanV1` after formal S2 training. Without this, updating the plan after S2 would mutate the frozen gate.
- Evidence: `benchmarks/m24-scale-gate-v1.json` and `benchmarks/m24-s2-arena-screen-v1.bundle.json` now define the exact allowed substitution:
  - only `m24-s2-candidate --checkpoint-hash <placeholder>` may change
  - placeholder is replaced by the formal M24-S2 checkpoint semantic hash
  - all other plan fields remain immutable
  - realized plans are generated under `local-artifacts/m24-s2-arena-screen-v1/`
- Outcome: `m24-scale-gate-v1` remains `FROZEN` as Repair 3; G4 remains `NOT_YET_RUN`; S2 is still not authorized.
- Decision for next iteration: after independent re-review PASS, freeze the S2 nested corpus/config and authorize S2.
### Iteration 9 — 2026-08-15

- Change: froze M24-S2 nested collection/training configs.
- Reason: after `m24-scale-gate-v1` accepted, the next pre-registration is the exact S2 corpus and training recipe so that S2 remains a single-variable scale experiment.
- Evidence:
  - `benchmarks/m24-self-play-s2-v1.config.json`
    - 512 games: S1 exact seeds `260001..260128` + fresh seeds `260130..260513`
    - explicitly skips `260129` (the frozen S1 training seed)
    - all collection/search/device fields match S1 except `self_play_id` and `game_seeds`
  - `benchmarks/m24-self-play-s2-v1.training.json`
    - same training recipe as S1: base M22, seed `260129`, batch 128, epochs 16, lr 1e-4, etc.
    - `expected_self_play_hash` remains `""` until formal S2 collection completes
- Outcome: M24-S2 configs `FROZEN`; S2 collection still not authorized; G4 remains `NOT_YET_RUN`.
- Decision for next iteration: after narrow pre-execution review, authorize and run M24-S2 collection.
### Iteration 10 — 2026-08-15

- Change: completed M24-S2 collection and hardened diagnostics; froze the formal S2 self-play hash into the S2 training config.
- Evidence:
  - `local-artifacts/m24-self-play-s2-v1/self-play.json`
    - 512 games / 31,505 examples
    - self_play_hash `b8a67f5fd41dde0ee3c1c5194c12e7b0886813039c8ccde9660b211f26838e46`
    - file SHA-256 `ddf8575af6ad14032a448488cda5868e82096bde1f511587f8077b3bd0eaa07f`
  - `local-artifacts/m24-self-play-s2-v1/diagnostics.json`
    - 512/512 games verified
    - duplicate seeds 0
    - duplicate observation/information-set rate 0.0
    - every root visit sum = 16 (hardened validator)
  - nested-corpus check: S2 games `0..127` match S1 games `0..127` on seed, replay document/final-state hashes, example count, observation/information-set hashes, legal actions, targets, and action stats.
  - `benchmarks/m24-self-play-s2-v1.training.json` now has `expected_self_play_hash = b8a67f5f...`
- Outcome: M24-S2 G1/G2 `PASS`; S2 training config hash frozen; S2 training still not authorized.
- Decision for next iteration: review the hash-only materialization and then authorize S2 training.
### Iteration 11 — 2026-08-15

- Change: completed M24-S2 training and recorded the formal S2 training evidence; computed the fixed-S1-reference offline evaluation.
- Evidence:
  - `local-artifacts/m24-self-play-s2-v1/trained/`
    - checkpoint semantic `c43e3c239124671c77bb7436dcf79e4fe6c71b66c8008186ac68621a8ad7d5a8`
    - checkpoint file SHA-256 `0ba19302a5cd0fe618fc5246a3d5bc9c562460d558cff2a128d1c25b6fe0543e`
    - training report SHA-256 `a42b42d4e8fa0c543bbd0b246e93da01a0a8557684c17de5f914887692117503`
    - best epoch 8
    - full S2 validation: CE 1.1873 / top1 0.9261 / MSE 0.2348 (diagnostic only)
  - fixed S1 reference offline eval (same 1953 S1 validation examples):
    - S1: CE 1.2132 / top1 0.9186 / MSE 0.2451
    - S2: CE 1.2053 / top1 0.9191 / MSE 0.2367
  - `benchmarks/m24-self-play-s2-v1.result.json` now records collection, diagnostics, training, and fixed-reference offline evidence.
- Outcome: M24-S2 G1/G2/G3 `PASS`; S2 training evidence frozen; G4 still `NOT_YET_RUN`; Arena not authorized.
- Decision for next iteration: review S2 training evidence and then materialize the three S2 Arena plan templates with the S2 checkpoint hash.
### Iteration 12 — 2026-08-15

- Change: materialized the three S2 Arena plan templates with the formal S2 checkpoint hash and recorded realized-plan identity.
- Evidence:
  - `local-artifacts/m24-s2-arena-screen-v1/` contains realized plans:
    - `m24-s2-vs-s1-v1.plan.json`
    - `m24-s2-vs-m07-v1.plan.json`
    - `m24-s2-vs-heuristic-v1.plan.json`
  - `benchmarks/m24-s2-arena-screen-v1.realized.json` records template SHA, realized file SHA, realized canonical SHA, and materialization validation PASS.
  - S2-only exact plans remain unchanged.
- Outcome: Arena materialization `PASS`; formal 5-pair Arena screen may proceed.
- Decision for next iteration: execute the 5-pair competitive screen and compute G4 competitive movement.

### Iteration 13 — 2026-08-15

- Change: executed the formal 5-pair M24-S2 Arena screen and computed G4 competitive movement.
- Evidence:
  - S2 vs S1: 64 matches, 30W/1T/33L, center 4765 bps, lower bound 2599 bps → primary lower-bound check PASS.
  - Anchor deltas (center bps):
    - M07: `-313` bps → below frozen `-200` bps threshold → FAIL
    - heuristic: `+938` bps → PASS
  - G4 competitive half: FAIL due M07 anchor regression.
- Outcome: `G4_scale_decision = FAIL`; `G5_continuation = STOP`; M24 scaling stops; S3/M25 not authorized.
- Decision for next iteration: record negative G4 result, preserve all evidence, do not auto-authorize further scaling.

### Iteration 14 — 2026-08-15

- Change: added final Arena provenance binding for the five eval-report artifacts.
- Evidence:
  - Added `benchmarks/m24-s2-arena-screen-v1.result.json`:
    - binds each pair to its local `eval-report.json` path and SHA-256
    - records plan_hash, evaluation_id, scheduled_matches, W/T/L, center/lower bps
    - recomputes primary/anchors/competitive verdict
  - `benchmarks/m24-self-play-s2-v1.result.json` now references the Arena result manifest by SHA-256.
  - Regression test recomputes center/lower from raw W/T/L and asserts G4/G5.
- Outcome: final G4 evidence provenance `PASS`; scientific result remains `FAIL / STOP`.
- Decision for next iteration: final narrow re-review of the provenance binding.
### Iteration 15 — 2026-08-15

- Change: final narrow re-review accepted the M24-S2 final evidence.
- Evidence: `benchmarks/m24-self-play-s2-v1.result.json` now records `review.source_review = PASS_INDEPENDENT_REVIEW_OF_5176171` and `review.acceptance = ACCEPTED`.
- Outcome: M24-S2 final evidence `ACCEPTED`; scientific result remains `G4 = FAIL`, `G5 = STOP`.
- Decision: M24 scaling experiment is closed as a negative result; S3/M25 remain not authorized.

## Final implementation

- New strict CLI commands:
  - `collect-gpu-self-play-v2 --config <config.json> --out <dataset.json>`
  - `diagnose-gpu-self-play-v2 --input <dataset.json> --config <config.json> --out <diagnostics.json>`
- V2 dataset embeds verified ReplayV1 per game, source identity fields, and
  per-example observation/visible-history/information-set hashes and targets.
- Diagnostics re-verify every replay, rebuild every information set from the
  verified trace, validate every target, and emit a
  `effective-splendor-self-play-diagnostics` report.
- Python `self_play_train.py` accepts v1 and v2 datasets and records
  dataset version plus CUDA/determinism environment fields.
- Formal S1 collection, audit, and training have run; evidence is recorded in
  `benchmarks/m24-self-play-s1-v1.result.json`.
- The S1→S2 scale gate is frozen in `benchmarks/m24-scale-gate-v1.json`.
- The fresh multi-seed Arena screen is frozen as five 2-agent pairwise plans
  in `benchmarks/m24-s2-arena-screen-v1.bundle.json`, which the gate hash-binds.
- S2-containing plans are frozen templates with a machine-checkable
  materialization contract: only the `__M24_S2_CHECKPOINT_HASH__` placeholder
  may be replaced by the formal S2 checkpoint hash.
- M24-S2 nested collection/training configs are frozen in:
  - `benchmarks/m24-self-play-s2-v1.config.json`
  - `benchmarks/m24-self-play-s2-v1.training.json`
- M24-S2 Arena result provenance is bound in `benchmarks/m24-s2-arena-screen-v1.result.json`.

## Validation and evidence

```text
implementation_commit = a797f131c25bffc49fd66abe212c63fc88c9305c
base_commit           = 4ee8852c5ac7232c13e7f2ead1a25aaa4955ad3f
repair_commit         = dbe47ab17a2b4a255109f6c0d60e68c89e426b9e

command: ./target/debug/splendor collect-gpu-self-play-v2
         --config benchmarks/m24-self-play-s1-v1.config.json
         --out local-artifacts/m24-self-play-s1-v1/self-play.json
result:  PASS; 128 games; 7,876 examples
         self_play_hash b2284c6c...4053
         dataset file SHA-256 1a2344a8...bcad8d

command: ./target/debug/splendor diagnose-gpu-self-play-v2
         --input local-artifacts/m24-self-play-s1-v1/self-play.json
         --config benchmarks/m24-self-play-s1-v1.config.json
         --out local-artifacts/m24-self-play-s1-v1/diagnostics.json
result:  PASS; 128/128 games verified; zero duplicate seeds
         duplicate observation rate 0.0
         duplicate information-set rate 0.0

command: python -m splendor_gpu.self_play_train ...
result:  PASS; device cuda; RTX 4060 Laptop GPU; torch 2.6.0+cu124;
         63.30s; best epoch 7
         checkpoint semantic 1ae31dac...f0b8
         checkpoint file SHA-256 1eaf88a1...2bc61c
```

Tracked identities: `benchmarks/m24-self-play-s1-v1.result.json` contains the
full machine-verifiable manifest.

## Result and decision

- G1 collection: `PASS` (S1 and S2).
- G2 audit: `PASS` (S1 and S2).
- G3 training: `PASS` (S1 and S2).
- G4 scale decision: `FAIL`.
- G5 continuation: `STOP`.
- M24-S2 final evidence: `ACCEPTED`.
- Source review: independent re-review of `dbe47ab` `PASS`; M24-S1 `ACCEPTED`.
- Scale gate: `benchmarks/m24-scale-gate-v1.json` `ACCEPTED` / `FROZEN`.
- S2 result: `benchmarks/m24-self-play-s2-v1.result.json` `FROZEN`.
- Decision: M24-S1 establishes the accepted 128-game diagnostic baseline. M24-S2 collection, diagnostics, training, and Arena screen are complete. Offline movement passed, but competitive movement failed the M07 anchor threshold. M24 scaling stops; S3/M25 not authorized.

## Known limitations and non-claims

- M24-S1/S2/S3 are still self-play generated by a weak M22 checkpoint; the
  experiment measures scale effects, not teacher quality. M25 addresses the
  teacher/bootstrap problem.
- Offline learning-curve movement is not proof of Arena strength.
- 128 games is the first non-smoke scale, not a promotion corpus.
- M24-S1 diagnostics are observational; `m24-scale-gate-v1` is frozen and the S2 Arena screen has completed with G4 `FAIL`; no S3/M25 continuation is authorized.

## Next authorized gate

- M24-S2 G4 scale decision: `FAIL`.
- M24 scaling stops; S3 is not authorized.
- M25 is not authorized.
- Preserve all S1/S2 evidence and negative result; no promotion or champion change is implied.
