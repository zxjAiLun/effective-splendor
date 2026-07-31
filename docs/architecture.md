# Architecture

Splendor rules engine, with the M02 rules closure serving as the canonical
foundation for replay, search, arena, and RL integrations.

## Crate dependency direction

```
splendor-catalog        (pure data: cards, nobles, rulesets)
        │
        ▼
splendor-core           (domain state, legal actions, transitions, referee events)
        │
        ├──────────────┬───────────────┬────────────────┬─────────────────┐
        ▼              ▼               ▼                ▼                 ▼
splendor-protocol  splendor-replay  splendor-arena  splendor-search  splendor-python
   (wire DTO)      (referee replay) (stdio runner)  (deterministic MaxN v1)  (PyO3 env)
        │                               │
        ▼                               ▼
splendor-agent                    splendor-eval
 (stdio agent SDK)          (pure evaluation model)
```

The `splendor` CLI (`splendor-cli`) is the only binary front-end; it consumes
protocol, replay, arena, agent, eval, and search. Dependency direction is
strictly `cli → eval → arena` and `cli → search` and `cli → replay`; nothing
depends on the CLI, and `splendor-eval` stays a leaf model crate with no
process or file I/O. `splendor-search` and `splendor-replay` are independent
crates that do NOT depend on each other — the CLI is the only layer that binds
a referee replay to a search analysis. See `docs/search.md`.

`splendor-replay` depends on `splendor-core` (and `splendor-catalog`) only.
It MUST NOT depend on `splendor-protocol`, and `splendor-core` MUST NOT depend
on it: a replay is a referee artifact, not an agent projection.

Rules:
- **`splendor-catalog`** is pure data + accessors. No game logic.
- **`splendor-core`** owns the domain: `FullState`, `Observation`,
  `Action`, legal-action enumeration, state transitions, and `RefereeEvent`.
  It is the single source of truth for what is and isn't a legal move.
- **`splendor-protocol`** owns wire DTOs (`ServerMessage` / `ClientMessage`,
  `ServerMeta` / `RecipientMeta` / `ObservationMeta` / `RequestMeta`). It MUST
  NOT serialize `RefereeEvent` or `FullStateHash` directly; it uses
  `VisibleEvent`, `ObservationHash`, and the separate `RulesetFingerprint`.
- **`splendor-replay`** (M03) records a game to a self-verifying replay v1
  file and re-executes it ply by ply against `splendor-core`. It is a
  referee-only audit record: it stores the raw seed and full-state hashes and
  must never be sent to an agent or spectator mid-game. See `docs/replay.md`.
- **`splendor-arena`** (M04) spawns each agent as an OS subprocess, binds it to
  a seat, enforces deadlines / timeouts / illegal-action policy, records a
  referee replay, and writes a self-verifying `ArenaReportV1`. It is the only
  place that decides *who* a client is; clients never authorize their own seat,
  and agent commands are spawned literally (never shell-interpreted). See
  `docs/arena.md` and `docs/adr/0005-stdio-arena-process-boundary.md`. The
  `splendor` CLI exposes it via `run-match`, with `agent-random` as a reference
  stdio agent.
- **`splendor-agent`** (M05) is the stdio agent SDK: an NDJSON client FSM
  generic over an `AgentPolicy`. A policy sees only its own `Observation`,
  the server's `legal_actions`, public request metadata, and a derived
  `StableRng` — never `FullState`, the raw seed, or the replay. The runtime
  rejects any policy action outside `legal_actions`. `agent-random` and
  `agent-heuristic` are the reference policies exposed by the CLI.
- **`splendor-eval`** (M05) is the pure evaluation model: plan validation and
  hashing, canonical cyclic-seat schedule expansion, and integer-only
  aggregation into an `EvaluationReportV1`. It performs no process spawning
  and no file I/O; the `splendor eval` subcommand drives it and atomically
  publishes artifacts (`eval-report.json` is the commit marker, and per-match
  artifact filenames derive from `match_index` only, so plan content can
  never write outside the output directory). See `docs/evaluation.md`.
- **`splendor-search`** (M06) is the deterministic perfect-information MaxN
  search v1. Among workspace crates it depends only on `splendor-core`
  (+ `splendor-catalog`) — it additionally uses the external `serde` and
  `thiserror` crates; it MUST NOT depend on `splendor-replay`,
  `splendor-protocol`, agent, eval, or the CLI. It returns an integer utility vector `[u(p0), u(p1), …]` and a
  principal variation, with no floats, RNG, wall-clock reads, or threads. A
  replay position is handed in only by the CLI (`analyze-replay`), which
  verifies the replay first and then calls `search_maxn_v1`. See
  `docs/search.md`.
- **`splendor-python`** (PR-08) exposes a batched environment over PyO3 for
  RL self-play. High-volume training does NOT go through NDJSON.

## Core invariants (must hold in every host)

1. `FullState` is referee-only: it contains deck order and every player's
   blind-reserved `CardId`.
2. `Observation` never leaks another player's blind-reserved cards.
3. Chance outcomes are explicit `ChanceEvent`s, not implicit seed side-effects.
4. `Action`s are semantic (not policy indices); policy indices live in the
   training layer.
5. Purchased development cards are canonical ownership; bonus and prestige
   fields are validated hot-path caches.
6. **No rules behavior lives in a host.** Any state transition or terminal
   judgement must be reachable by calling only `FullState::legal_actions()`
   and `FullState::apply()`. Forced Pass and Stalemate semantics, reserve
   returns, and final-round accounting are core behavior. The CLI and future
   runners only select actions and consume results.
7. `FullState` contains no agent RNG. Setup randomness is resolved into the
   shuffled deck state; each agent owns its own action-selection RNG.

## Information boundary (see `docs/adr/0001-information-boundary.md`)

The state hashes and compatibility fingerprint enforce the boundary at the
type level:
- `FullStateHash` — referee only, never leaves core.
- `PublicStateHash` — board + public reserved identities; safe for anyone.
- `ObservationHash` — one player's view plus its ruleset scope; the only
  per-state hash the protocol carries.
- `RulesetFingerprint` — ruleset/catalog compatibility identity, independent
  of a particular game state.

`visible_events(referee_log, audience)` is the single projection exit point.
