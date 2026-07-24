# Arena (stdio match runner)

The arena runs exactly **one** Splendor match between agent subprocesses. Each
agent is an independent OS process that speaks the v0.5 NDJSON protocol over
stdio; the arena is the referee that binds a process to a seat, enforces
deadlines, records a replay, and writes a verifiable report. It never trusts an
agent to authorize its own seat, and it never joins agent arguments into a shell
command.

See `docs/adr/0005-stdio-arena-process-boundary.md` for why the boundary is a
real process and not an in-process trait object.

## Commands

Both commands live in `splendor-cli`. They are parsed by a small strict
argument parser (not clap): every flag is required, unknown/duplicate flags and
any extra positional argument are rejected, and `--help` prints usage and exits
`0`.

### `run-match`

```bash
splendor run-match \
  --config     arena-config.json \
  --report-out arena-report.json \
  --replay-out replay.json
```

Reads a JSON [`ArenaConfig`](#config-schema), runs one match via
`ArenaRunner::run`, and publishes artifacts atomically. All three flags are
required. `--report-out` and `--replay-out` must differ and neither may already
exist; their parent directories must exist. The config file must be UTF-8 and
at most **1 MiB**, and is strictly deserialized (unknown fields and trailing
JSON are rejected).

### `agent-random`

```bash
splendor agent-random --seed 42
```

The reference agent (see [below](#reference-random-agent)). Reads server NDJSON
on stdin and replies with a uniformly random **legal** action on stdout,
deterministically for a given `--seed`. `--seed` is required.

## Config schema

`ArenaConfig` (`deny_unknown_fields`):

| field | type | notes |
|-------|------|-------|
| `game_id` | string | non-empty, ≤ 128 bytes, no C0 control chars |
| `seed` | u64 | deterministic match RNG seed |
| `handshake_timeout_ms` | u64 | 1 .. 24h; agent must complete `hello` in time |
| `move_timeout_ms` | u64 | 1 .. 24h; per-request action deadline |
| `shutdown_grace_ms` | u64 | 1 .. 24h; grace before kill on shutdown |
| `agents` | array | 2–4 entries, in seat order |

Each `agents` entry is an `AgentCommand` (`deny_unknown_fields`):

| field | type | notes |
|-------|------|-------|
| `program` | path | executable; resolved against CWD / PATH at spawn |
| `args` | string[] | optional; literal argv, **never** shell-interpreted |

Example — two reference agents playing each other, driven by the same binary:

```json
{
  "game_id": "cli-random-2p",
  "seed": 42,
  "handshake_timeout_ms": 5000,
  "move_timeout_ms": 5000,
  "shutdown_grace_ms": 2000,
  "agents": [
    { "program": "splendor", "args": ["agent-random", "--seed", "1001"] },
    { "program": "splendor", "args": ["agent-random", "--seed", "1002"] }
  ]
}
```

## Artifact contract

There are exactly three outcomes, and each fixes what lands on disk and what is
printed:

| outcome | exit | stdout | stderr | `report-out` | `replay-out` |
|---------|------|--------|--------|--------------|--------------|
| **Completed** | `0` | one compact `ArenaOutcomeV1` line | empty | `ArenaReportV1` | `ReplayV1` |
| **Aborted** | `2` | one compact `ArenaOutcomeV1` line | empty | `ArenaReportV1` (`status: aborted`) | *(not created)* |
| **Error** (CLI / config / I/O / internal) | `1` | empty | `error: <message>` | *(none)* | *(none)* |

Both artifacts are written with `serde_json::to_string_pretty` plus a single
trailing newline. On a **Completed** match the CLI re-checks two invariants
*before* publishing anything:

1. `report.replay_final_hash == replay.final_state_hash`, and
2. `verify_replay(replay)` passes.

If either check fails the match is reclassified as an artifact error (exit `1`,
nothing published).

### Atomic publish

Files are never written in place. For each target the CLI writes a sibling temp
file (`<name>.<pid>.<seq>.tmp`, `create_new`) then `write` → `flush` →
`sync_all` → `rename` onto the final path. A **Completed** match commits the
replay first and the **report last**, so a reader that sees the report can trust
that the replay is already present. If the report rename fails, the already
-committed replay is rolled back and every temp is removed — a partial pair is
never observable. An **Aborted** match commits only the report. Any failure
leaves no `.tmp` residue.

## Reference random agent

`agent-random` is a real stdio agent — it does **not** call the engine
in-process. Its identity in the handshake is `agent_name =
"splendor-cli-random"` and `agent_version = ENGINE_VERSION`. Its state machine:

- **Hello** → validate protocol version, record `game_id`, reply `ClientHello`
  and flush.
- **GameStart** → bind this seat, check `game_id`.
- **Observation** → check recipient + `game_id`, remember the observation hash.
- **RequestAction** → check recipient + `game_id`, require a strictly
  increasing `request_id`, require the request's observation hash to match the
  latest observation, require a non-empty `legal_actions`, pick one uniformly,
  reply `ClientAction` and flush.
- **Ping** → **Pong**. **ActionApplied / Event** → continue. **GameEnd** →
  exit `0`.
- **Error / malformed / unexpected / EOF before game end** → write a diagnostic
  to stderr and exit non-zero.

The agent only ever selects from the server-provided `legal_actions`; it never
enumerates moves itself, so it cannot desync from the referee's legality view.

### Deterministic selection

Selection uses a fixed **xorshift64\*** generator, not `rand` or any std RNG, so
the same seed and the same server transcript pick the same actions on every
platform:

```
state = (seed ^ 0x9E3779B97F4A7C15) | 1     // seed-init; never all-zero
x ^= x >> 12; x ^= x << 25; x ^= x >> 27
next = x * 0x2545F4914F6CDD1D
```

An index into `legal_actions` is drawn by rejection sampling to stay unbiased.
The algorithm and the seed-init constant are frozen by a golden test
(`rng_is_frozen`); changing either is a breaking change.

## What the arena is *not* (M04 scope)

No tournament runner, no Elo, no match batching, no TCP, no async/Tokio, no
agent sandbox, no resume/reconnect. Replay stays v1, the arena report stays v1,
and the protocol stays v0.5. These are deliberately out of scope for M04.
