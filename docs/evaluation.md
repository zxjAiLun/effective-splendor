# Evaluation and promotion v1 (M05 + M09)

M05 adds the agent SDK (`splendor-agent`), a deterministic heuristic reference
agent, the pure evaluation model (`splendor-eval`), and the `splendor eval`
driver that runs a frozen plan end to end and publishes verifiable artifacts.

## Agent SDK information boundary

`splendor-agent` hosts an NDJSON stdio agent as a finite state machine that is
generic over an `AgentPolicy`. A policy decides from a `DecisionContext`
containing **only**:

- the agent's own `Observation` (never `FullState`);
- cumulative `VisibleEvent` history projected for that same player;
- the server-provided `legal_actions` list;
- public request metadata (`PublicRequestMeta`);
- a `StableRng` derived for the decision (never the raw game seed).

A policy can never see deck order, other players' blind reserves, the replay,
or the referee state. The runtime additionally rejects any action a policy
returns that is not in `legal_actions` — a buggy policy surfaces as an agent
fault, not an illegal state transition.

## Reference agents

The reference and M08 agents are subcommands of the `splendor` binary and speak the
NDJSON protocol on stdio:

```text
splendor agent-random    --seed <u64>   # uniform random over legal actions
splendor agent-heuristic --seed <u64>   # deterministic integer-weight policy
splendor agent-determinization --sample-seed <u64> --sample-count <u16> \
  --max-depth-turns <u8> --max-nodes <u64>
```

The heuristic prefers `Buy > Take > Reserve-visible > Reserve-blind > Pass`
using pure integer weights; its RNG is consumed only to break exact ties, so
runs are reproducible given the seed.

The determinization agent is the live binding of the frozen M07 baseline. It
builds every decision from the current observation and cumulative projected
history, checks that the search root matches the server-certified legal action
set, and fails closed on any mismatch. Its configurable deterministic budgets
are inputs for M09 calibration, not a frozen strength claim.

## Evaluation plan format

An `EvaluationPlanV1` is a pure JSON description of what to play (see
`crates/splendor-eval`): agents, game seeds, and timeouts — no execution
detail, no output paths.

```json
{
  "format": "effective-splendor-evaluation-plan",
  "version": 1,
  "evaluation_id": "example",
  "agents": [
    { "id": "A", "command": { "program": "splendor", "args": ["agent-heuristic", "--seed", "1"] } },
    { "id": "B", "command": { "program": "splendor", "args": ["agent-random", "--seed", "2"] } }
  ],
  "game_seeds": [1, 2, 3],
  "handshake_timeout_ms": 10000,
  "move_timeout_ms": 10000,
  "shutdown_grace_ms": 2000
}
```

Validation is strict (`deny_unknown_fields`, 2–4 unique agents, non-empty
seeds, bounded timeouts, byte-bounded IDs, ≤ 10 000 matches). Agent commands
are spawned literally — never shell-interpreted.

## Cyclic seat schedule

`expand_schedule` derives the canonical schedule: for every seed (in
declaration order) and every rotation `r` in `0..n` (n = agent count), agent
`a` sits at seat `(s + n - r) % n`. Every agent plays every seed from every
seat, so seat advantage cancels. Match order is `seed_index` ascending ×
rotation `0..n`; `match_index` is dense and unique. The derived game ID is
`{evaluation_id}-s{seed_index:06}-r{rotation:02}`.

## Plan hash

`evaluation_plan_hash_v1` is a SHA-256 over the validated plan's canonical
compact JSON. It binds agents, commands, seeds, and timeouts — independent of
wall clock or absolute paths. A plan that hashes is guaranteed schedulable.
Reports embed the hash (`plan_hash`), and `plan-hash.txt` republishes it next
to the report.

## Running an evaluation and artifact layout

```text
splendor eval --plan <plan.json> --out-dir <DIR>
```

publishes, in this order:

```text
<DIR>/matches/match-000000.report.json    # per-match ArenaReportV1
<DIR>/matches/match-000000.replay.json    # per completed match only
<DIR>/...                                 # one pair per match_index
<DIR>/plan.json                           # echo of the executed plan
<DIR>/plan-hash.txt                       # frozen plan hash
<DIR>/eval-report.json                    # EvaluationReportV1 — commit marker, LAST
```

Every file is committed via create-if-absent hard links (no overwrite, no
rename fallback); a failure rolls back uncommitted temps and exits 1.

**`eval-report.json` is the evaluation commit marker**: consumers must treat
an output directory without it as an uncommitted evaluation. Per-match
artifacts are independently valid single-match deliverables (replay first,
report last per match, as in M04).

## Aborted semantics

An agent fault (spawn failure, timeout, illegal action, protocol violation)
aborts *that match only*: the arena attributes the fault to a seat, the match
publishes a report but **no replay**, the evaluation continues, and the CLI
still exits 0. Fault attribution is aggregated per agent (`faults_caused`).
Exit 1 is reserved for fatal driver errors (invalid plan, I/O or publish
failure, arena infrastructure errors).

## Match-index filenames and path containment

Per-match artifact filenames are derived **exclusively** from the canonical
`match_index` (`match-{index:06}.report.json` / `.replay.json`). The model
legally admits evaluation IDs containing `/`, `..`, or absolute-path prefixes;
because the game ID never enters a filesystem path, no plan content can place
an artifact outside `--out-dir`. File ↔ record mapping is by `match_index`;
the original `game_id` lives inside the record, report, and replay JSON.

## Fixed benchmark (M05 closure)

The frozen benchmark plan is checked in at:

```text
benchmarks/m05-agent-eval-v1.plan.json
```

Composition (frozen): `heuristic-v1` vs `random-v1`, 100 fixed game seeds
(1–100), 2 seat rotations per seed → **200 matches**. Commands use the
portable literal program name `splendor`, so the plan hash freezes across
machines; the verifier prepends the built binary's directory to `PATH`.

Strength gate (frozen before the first run):

```text
scheduled_matches = 200
completed_matches = 200
aborted_matches   = 0
faults_caused     = 0 for both agents
heuristic wins    >= 120
heuristic rank_sum < random rank_sum
```

The verifier (`crates/splendor-cli/tests/eval_benchmark.rs`) re-executes and
verifies every replay (`verify_replay`), binds every final state hash to its
report outcome, checks the frozen plan hash, and enforces the gate. It is
`#[ignore]`d by default; run it explicitly:

```text
cargo test --locked -p splendor-cli --test eval_benchmark -- --ignored --test-threads=1
```

## Competitive promotion gate (M09)

M09 adds a pure promotion layer on top of the immutable M05 artifacts. It does
not rerun games or accept caller-provided summary numbers. Given the exact
`EvaluationPlanV1`, its canonical `EvaluationReportV1`, and a
`PromotionGateV1`, `evaluate_promotion_v1` first re-aggregates every match
record and requires exact model equality with the supplied report. The output
binds both the evaluation-plan SHA-256 and a domain-separated promotion-gate
SHA-256.

Each game seed is one independent block containing all cyclic seat rotations.
If any rotation aborts, the whole block is excluded from the strength sample;
the abort and attributed candidate fault still count against reliability
limits. Pairwise candidate/champion outcomes use rank only: win = 2 half-points,
tie = 1, loss = 0. The point estimate is the half-point score over all complete
blocks.

The frozen v1 confidence rule is a deterministic integer one-sided Hoeffding
bound at greater than 95% confidence:

```text
epsilon_bps = ceil(sqrt(150000000 / completed_seed_blocks))
lower_bps   = max(0, score_bps - epsilon_bps)
```

The block count, abort limit, candidate-fault limit, Arena move deadline, and
minimum pairwise lower bound must all pass. No single check can override
another. A zero-complete-block report is therefore a normal rejection, never a
strength result.

Run the gate after `splendor eval` has committed its report:

```text
splendor promotion-gate \
  --plan <plan.json> \
  --eval-report <eval-report.json> \
  --gate <gate.json> \
  --out <promotion-report.json>
```

The output is atomically created and never overwritten. Exit `0` means
`promote`, exit `2` means a valid `reject`, and exit `1` is fatal input,
binding, or I/O failure. Both policy decisions write `PromotionReportV1` and
keep stdout empty.

### Fixed M09 calibration inputs

The checked-in inputs are:

```text
benchmarks/m09-competitive-eval-v1.plan.json
benchmarks/m09-competitive-eval-v1.gate.json
```

They schedule `determinization-s4-d1-n2000-v1` against `heuristic-v1` over 32
fixed seeds and both seat rotations (64 matches). Promotion requires every seed
block to complete, zero aborts, zero candidate faults, the configured move
deadline to be at most 10 seconds, and the one-sided 95% lower bound to be at
least 50%. These are frozen calibration inputs, not a pre-recorded promotion:
no result may be claimed until the plan is executed and the resulting report is
successfully gated.

### Fixed M10 candidate inputs

M11's checked-in league manifest and the unchanged M09 gate are:

```text
benchmarks/m10-ismcts-v1.league.json
benchmarks/m10-ismcts-v1.gate.json
```

Run `league-plan` to derive the canonical evaluation plan, execute it through
the existing evaluator, then apply the M10 gate. The schedule compares the M10
observation-history ISMCTS candidate with the frozen M07 root-determinization
champion across 32 seeds and both seat rotations. These files freeze inputs
only; no promotion or strength result is checked in.

### Fixed M13 candidate inputs and result

`benchmarks/m13-neural-ismcts-v1.league.json` and
`benchmarks/m13-neural-ismcts-v1.gate.json` freeze the checkpoint-bound neural
candidate against the same determinization champion over 32 new seeds and both
seat rotations. The 2026-08-11 formal run completed all 64 matches with zero
aborts and zero candidate faults, but the candidate went 12–52 and the 95%
lower bound was 0 bps, so the unchanged gate returned `reject`. Exact local
artifact hashes are recorded in `docs/neural-search.md`; generated evaluation
files remain outside Git.

### Performance observability boundary

Arena report v1 records outcomes and fault classes but does not record per-move
latency, nodes visited, samples consumed, or peak memory. Consequently M09 v1
can enforce the configured move deadline and observed timeout/fault/abort
counts only. `--max-nodes` and `--sample-count` in an agent command are hashed
configuration inputs; they are **not** measured actual cost and must not be
reported as such. Adding nodes/samples/latency promotion checks requires a new
versioned telemetry/report contract rather than changing ArenaReportV1 in
place.

## Version matrix

```text
ENGINE       = 0.4.0
PROTOCOL     = 0.5
REPLAY       = 1
ARENA_REPORT = 1
EVALUATION   = 1   (plan + report)
PROMOTION    = 1   (gate + report)
ISMCTS       = 1
LEAGUE       = 1
DATASET      = 1
MSRV         = 1.75.0
```
