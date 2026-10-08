# Prism PPO infrastructure and continuous Arena trials (M54)

Stages I–II verified infrastructure and **8 live engineering games / 2 updates**.
Stage III completed a separate **256 games × 8 cycles** outcome-only trial,
fixed T=1 development evaluation and bounded cloud2 mixed-pool play.
Stage IV continues from the final c8 full state in a new **8 × 256** bounded
campaign, with fixed-only development evaluation and no new mixed/Elo games.
Training completion alone never promotes weights. The frozen v0.1 BC trainer,
encoder, weights and `agent-prism` greedy behavior are unchanged.
See [M54](../../../docs/m54-prism-continuous-ppo-design.md) for actual run evidence.

## Implemented boundaries

- `contract.py`: strict JSON fields, finite 96/80 features, integral targets,
  categorical probabilities, actor/game/decision identities and terminal shards.
- `model.py`: unchanged v0.1 policy/outcome model plus a training-only style
  value head. Export explicitly includes **only the original 32 policy/value
  tensor keys**. Style gradients share the encoder but never overwrite the
  meaning of the outcome head. The initial style adapter deliberately recomputes
  the shared encoder rather than modifying the frozen v0.1 forward function.
- `sampling.py`, `service.py`: immutable behavior snapshot; singleton f32 network,
  f64 softmax at T=1, categorical CDF draw from SHA256(action seed, job, actor,
  own-decision index). No teacher labels, logit bias, epsilon/top-k mixing or
  style temperature. Environment seeds are not sent to the service.
- `learner.py`: complete own-player trajectories, gamma=1, explicit outcome GAE
  lambda, style MC advantage, clipped PPO, outcome BCE, optional style MSE and
  entropy. Entire-batch combined-advantage normalization, fixed old probabilities.
  The initial implementation accumulates **singleton gradients** into each
  configured minibatch, avoiding behavior/update batch-shape drift and large
  padded minibatches. Changing this execution strategy needs a new identity.
- `store.py`: writer lock, hashed immutable payloads/commits and atomic HEAD;
  orphan files do not count as commits. Model/optimizer/RNG and data cursor are
  published together. Trusted local `.pt` only: pickle must not be accepted
  from untrusted sources; content hashes are not cryptographic authentication.
- `coordinator.py`: synchronous scheduling, attempt ledger, audit ingestion,
  batch sealing, bounded optimizer steps, pause/resume, cycle exports. All
  configuration/runtime/source identities are bound to recovery. The coordinator
  does not itself launch matches or allocate seeds; `arena.py` is the v2 launcher.
  The opponent pool cannot change during a run.
- `audit.py`: invokes a SHA-pinned `splendor prism-ppo-audit` against existing
  replay and sidecar files, verifies input hashes did not change. Python's
  structural checks do not substitute for Rust rules/projection verification.
- `arena.py`, `execution.py`, `processes.py` (Stage II): CPU serial live launcher,
  complete execution-contract and report/argv/binary/weight identity joins,
  idempotent physical-cost ledger and Windows Job Object process-tree limits.
  v2 submission requires a verified completion package and trusts Arena's online
  rules/terminal result. No automatic postgame rules replay or behavior forward
  recomputation; legacy/manual audit remains available. Hashes bind local execution.

## Wire protocol

One UTF-8 JSON object plus newline per TCP connection, max **16 MiB**,
30-second socket timeout, bound to `127.0.0.1` only. The server processes
requests serially; no inference batching by arrival order. Authentication
uses an explicit token. It is removed before sampling and omitted from sidecars
and responses. Run in a trusted local account; loopback authentication is not a
sandbox against another process with access to command lines or files.

Request format `prism-ppo-request-v1` has exactly:

```text
format, token, behavior_id, job_id, game_id, actor, request_id,
decision_index, catalog_fingerprint, input
input = {entities: [E,96], actions: [A,80], targets: [A]}
```

Response format `prism-ppo-response-v1` has exactly:

```text
format, behavior_id, job_id, game_id, actor, request_id, decision_index,
chosen_index, log_prob, value, style_value, probabilities
```

`value` means expected **win + half draw score**, not calibrated pure win
probability. `style_value` estimates a separate bounded trajectory utility;
its linear output need not itself be bounded. Metadata is only for routing,
RNG and audit, never a model input.

Rust `agent-prism-ppo` encodes only `DecisionContext` Observation, legal actions
and player-visible history. It writes `prism-ppo-decision-v1` JSONL rows with
`request` (without token), `response`, `observation`, `visible_history`,
`legal_actions`, `chosen_action`. A row is not proof the referee applied an
action: the auditor joins it to every actual actor decision in the terminal
replay and rejects gaps/extras/mismatches. ChooseNoble is an own-player decision,
not an automatic opponent turn. Postgame full-reveal history is never encoded.

`prism-ppo-audit-v1` contains one actor shard per game: format, behavior_id,
job_id, actor, game_id, catalog_fingerprint, replay_sha256, sidecar_sha256,
terminal=true, result, decisions. True terminal ranks, including Stalemate,
determine the outcome. Truncation/abort is never relabeled as a draw or loss.

## Commands (implemented; not authorization to run experiments)

```text
python -m training.prism.ppo --help
python -m training.prism.ppo create --config CONFIG --weights V01_JSON --run NEW_DIR
python -m training.prism.ppo begin --run DIR --schedule SCHEDULE_JSON
python -m training.prism.ppo.service --snapshot SNAPSHOT_PT --sha256 HASH --port PORT --token TOKEN --device cpu --cpu-threads N
splendor agent-prism-ppo --endpoint 127.0.0.1:PORT --token TOKEN --behavior-id HASH --job-id JOB --decisions-out NEW_JSONL
python -m training.prism.ppo attempt --run DIR --job-id JOB
python -m training.prism.ppo submit --run DIR --job-id JOB --attempt N --executable PINNED_BINARY --replay REPLAY --sidecar JSONL --completion V2_COMPLETION_JSON
python -m training.prism.ppo seal --run DIR
python -m training.prism.ppo step --run DIR --max-steps N
python -m training.prism.ppo pause --run DIR
python -m training.prism.ppo resume --run DIR
python -m training.prism.ppo status --run DIR
python -m training.prism.ppo export --run DIR --output NEW_DIR
```

`attempt` **must precede** starting an external game process. The player command
alone does not launch a referee/match. Stage II's launcher records the attempt
before spawning and joins actual opponent/engine/report identities to the
schedule; a replay alone only proves rules/actions/results, not opponent identity.
`--completion` is mandatory for v2 live runs; v1 remains a legacy fixture contract.

All config fields are required; no implicit training budget is provided.
The tracked M54 engineering config is a completed, bounded experiment, not a
default for future training. Test values in `tests/ppo_support.py` are not
benchmark settings. Legacy `prism-ppo-run-v1` keys:

```text
format, run_id, catalog_fingerprint, parent_sha256, auditor_sha256,
device, cpu_threads, seed, ppo, budget, opponents
ppo = all PPOConfig dataclass fields in contract.py
budget = max_cycles, max_optimizer_steps, max_update_attempts, max_jobs,
         max_attempts, max_decisions, max_job_decisions,
         max_run_seconds, max_storage_bytes
opponents = {name: frozen_identity_sha256}
schedule = [{job_id, actor, opponent_id, environment_seed}, ...]
```

The training/action seed is independent of the schedule's referee environment
seed. Jobs may not be reused across cycles. One learner actor shard per scheduled
job is currently supported. Both-player learning requires a later schedule/join
contract; merely using two sides of self-play as one chain is forbidden.

## Recovery and resource semantics

```text
READY -> COLLECTING -> UPDATING -> COMMITTED -> COLLECTING ...
                       |                         |
              pause flag / FAILED on bad audit
```

Sealing publishes the immutable batch and update permutation atomically with
UPDATING state. Each optimizer attempt is committed **before** computation.
Both v1 and v2 allow multiple minibatches/passes and recovery within the explicit
attempt budget. Only successful logical steps advance model/AdamW/RNG/cursor
together; interrupted computation never consumes a committed step twice.
Each pass has its own permutation and tail minibatch. The resident batch is
validated at seal/open/recovery, not reread and revalidated at every step.
KL/clip/entropy reuse the minibatch's pre-update forward; exceeding target KL
discards its gradients, leaves optimizer unchanged and ends the remaining passes.
Recovery uses `Run.open`, not a mutated low-level `Learner`.

Completed jobs cannot be restarted. For v2, existing completion packages are
recovered without spawning; a terminal report missing its package stops the run
rather than replaying a completed game. Only enumerated infrastructure aborts
may retry the same job/snapshot/seed, within the frozen attempt/retry budget.
Audit, identity, deadline and truncation failures stop the campaign; no replacement
seeds. Corrupt HEAD/commit chains or changed config do not auto-recover.

The coordinator bounds admitted cycles/jobs/decisions and optimizer expenditure;
it checks wall/storage between operations. The live launcher additionally charges
physical work before ingestion and supervises its owned Windows process trees:
suspended spawn/Job assignment, user-CPU/memory/active-process limits,
kill-on-close, and wall/storage polling. Storage is not a filesystem quota; CPU
means aggregate user CPU, with kernel CPU separately reported. Pause time counts
against run wall time. Already-running games may finish on a graceful pause.
GPU enforcement/restart and arbitrary scripts bypassing the launcher are outside
this CPU engineering contract.
Storage checks include retained orphan objects; immutable checkpoints grow the
run directory, and no garbage collector silently deletes history. Audit input
files are external to that store; their admission size/retention is not an
unlimited-storage promise. Large-run profiling and bounded streaming storage
remain a pre-scale gate, not measured throughput.

## Style gate and unverified work

The style model, separate targets/advantages and gradients are exercised with
synthetic utilities. **The coordinator intentionally rejects style_beta > 0**:
there is no frozen builder/disruptor/rush reward extractor yet, and arbitrary
caller-provided labels cannot masquerade as measured style. Style utilities,
K/H/caps, beta candidates, behavior separation and strength non-inferiority
thresholds still require their next contract.

Tests cover CPU math, sockets, owned process limits, transactional fault boundaries
and synthetic recovery. Stage II separately verified 8 real terminal games,
actual execution identities, two updates, committed-cycle pause/reopen/resume
and real export parity. This does not establish GPU restart determinism, styles,
strength improvement, long-run throughput, power-loss durability or production
suitability. Stage III's separately pinned contract authorizes the current trial.

## Verified engineering commands (2026-09-30)

With the five `M54_*` fixture variables below set, the Stage II full Python suite
passed **195 tests / 0 skipped**, including 3 opt-in interop tests (Stage I: 167).
Rust `splendor-prism` passed 22; CLI filter `prism` passed 12 with 2 opt-in tests
ignored by default. Python interop explicitly ran both ignored tests successfully.
See the [Stage I result](../../../benchmarks/m54-prism-ppo-infrastructure-v1.result.json)
and [Stage II result](../../../benchmarks/m54-prism-ppo-arena-v1.result.json)
for exact logs, runtime identities, provenance and limits.

```text
M54_RUST_TEST_EXE = isolated compiled splendor unit-test executable (cargo --no-run output)
M54_CLI_EXE = isolated debug/splendor.exe
M54_EXISTING_REPLAY = previously recorded terminal two-player replay
M54_BOUNDARY_FIXTURES = existing M51 boundary-fixtures.jsonl
M54_EXISTING_WEIGHTS = existing M51 weights.json (catalog metadata only in interop)
python -B -m pytest -q -p no:cacheprovider training/prism/tests --basetemp SCRATCH_TEST_DIR
```

Absent these variables, only the 3 explicit interop tests skip; ordinary tests
do not silently generate replacement games. The interop replay sidecar is
fabricated solely for testing the Rust rules join and is never fed to PPO as
on-policy data. The real TCP interop uses two synthetic decisions, not a game.

## Stage II live contract and commands

The `prism-ppo-arena-v1` config contains the complete v2 run, parent weights,
SHA-pinned Arena/learner executables, frozen greedy opponents (argv, asset hashes,
Hello identities), fixed cycles/jobs and resource/retry limits. v2 run adds
`arena_contract_sha256` to the v1 fields. No automatic seeds, changing opponent
pool, nonzero-style campaign, partial-game rewards or unbounded run are allowed.
`--worker` is an internal supervisor entry, not a supported way to bypass limits.

```text
# New campaign: only after authorization of its exact contract and budget.
python -B -m training.prism.ppo.arena --campaign NEW_CAMPAIGN --contract APPROVED_CONFIG_JSON --stop-after-cycle
# Reopen same campaign for its next authorized cycle; do not repeat --contract.
python -B -m training.prism.ppo.arena --campaign SAME_CAMPAIGN --stop-after-cycle
python -B -m training.prism.ppo status --run SAME_CAMPAIGN/run
python -B -m training.prism.ppo pause --run SAME_CAMPAIGN/run
python -B -m training.prism.ppo resume --run SAME_CAMPAIGN/run
```

The completed M54 run used only frozen Prism v0.1 and heuristic v0.3.1, two
cycles of four games, beta=0, and one full-batch update attempt per cycle.
Actual totals: **8 attempts / 8 terminal games / 0 retries / 220 learner decisions /
2 optimizer steps**. Both real exports matched committed tensors and passed
Rust/Python parity at `atol=rtol=1e-4`. Diagnostic 4–0–4 is not a strength gate.
The completed budget does not authorize a new campaign or additional updates.

Artifacts: `local-artifacts/prism/ppo-arena-v1/`, including per-attempt replay,
sidecar/report/completion, immutable run state, two `cycle-N-export/` outputs,
and `provenance/` logs/evidence/scripts. `final_commit` is a **CommitStore training
transaction ID, not a Git commit**. Exports carry `not_promoted=true` and do not
overwrite the frozen v0.1 weights or enter UI/production registries.

## Exact-state bounded continuation (Stage IV)

`scripts/prism_ppo_continue.py` is a one-time initializer at a fully completed
campaign boundary. A separate hash-bound lineage pins source config/commit/
payload/export/runtime/source and the unchanged PPO/opponents. It restores the
full model, AdamW moments/step and learner RNG into a new READY commit. It does
not copy source batches, schedules, consumed IDs or resource budgets. New local
steps start at zero; cumulative AdamW steps are inherited steps plus new steps.

```text
python scripts/prism_ppo_continue.py --campaign NEW_DIR --contract NEW_CONFIG --lineage LINEAGE
python scripts/prism_ppo_campaign_supervisor.py --campaign DIR --lineage LINEAGE --state RESOURCES_JSON --stdout TRAIN_JSONL --stderr TRAIN_ERR
```

Only run the initializer once. Normal recovery resumes the same new campaign
with the supervisor, preserving its CPU charges and initialization-based wall
deadline. The supervisor snapshots aggregate user/kernel CPU every5s; after an
external interruption it conservatively charges the unobserved gap, not zero.
This charge must be reported separately from measured CPU. Active status must
read atomic HEAD/CommitStore without calling `Run.open()` or acquiring a writer
lock. A completed package awaiting ingestion is consumed without a replayed
game; missing recovered launch/ingest timings remain unknown.

`scripts/prism_ppo_fixed_watch.py --plan PLAN` runs the Linux fixed-only observer
for the c8 parent and prescheduled new c1/c4/c8. It reuses completed evaluation,
pins checkpoint/config hashes and keeps a finite persistent deadline. It never
calls pool/SQLite APIs or changes Elo; fixed metrics do not enter training.
These commands are implementation documentation, not authority for another
campaign, extra budget, ninth cycle, style campaign or production promotion.
