# Evaluation v1 (M05)

M05 adds the agent SDK (`splendor-agent`), a deterministic heuristic reference
agent, the pure evaluation model (`splendor-eval`), and the `splendor eval`
driver that runs a frozen plan end to end and publishes verifiable artifacts.

## Agent SDK information boundary

`splendor-agent` hosts an NDJSON stdio agent as a finite state machine that is
generic over an `AgentPolicy`. A policy decides from a `DecisionContext`
containing **only**:

- the agent's own `Observation` (never `FullState`);
- the server-provided `legal_actions` list;
- public request metadata (`PublicRequestMeta`);
- a `StableRng` derived for the decision (never the raw game seed).

A policy can never see deck order, other players' blind reserves, the replay,
or the referee state. The runtime additionally rejects any action a policy
returns that is not in `legal_actions` — a buggy policy surfaces as an agent
fault, not an illegal state transition.

## Reference agents

Both reference agents are subcommands of the `splendor` binary and speak the
NDJSON protocol on stdio:

```text
splendor agent-random    --seed <u64>   # uniform random over legal actions
splendor agent-heuristic --seed <u64>   # deterministic integer-weight policy
```

The heuristic prefers `Buy > Take > Reserve-visible > Reserve-blind > Pass`
using pure integer weights; its RNG is consumed only to break exact ties, so
runs are reproducible given the seed.

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

## Version matrix

```text
ENGINE       = 0.4.0
PROTOCOL     = 0.5
REPLAY       = 1
ARENA_REPORT = 1
EVALUATION   = 1   (plan + report)
MSRV         = 1.75.0
```
