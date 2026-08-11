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
        │
        ▼
splendor-determinization-agent
 (live player-view M07 policy)

splendor-belief ──► splendor-ismcts ──► splendor-ismcts-agent
                    (M10 tree)          (live player-view policy)

splendor-arena ──► splendor-eval ──► splendor-league
splendor-replay ───────────────────► splendor-league
                         (M11 plans + offline dataset projection)
                                      │
                                      ▼
                              splendor-learning
                         (M12 offline Policy/Value)
                                      │
                                      ▼
                         splendor-neural-search
                         (M13 guided ISMCTS tree)
                                      │
                                      ▼
                         splendor-neural-agent
                         (live player-view policy)
                                      │
splendor-replay ───────────────► splendor-analysis
                          (M14A verified sidecars)
                                      │ JSON only
                                      ▼
                              Replay Studio
                         (local player-view-first UI)
```

The `splendor` CLI (`splendor-cli`) is the only binary front-end; it consumes
protocol, replay, arena, agent, eval, search, ISMCTS, league, learning, and
neural-search layers. It exposes M12 offline training/evaluation and the M13
checkpoint-bound live neural agent, plus M14A replay-wide analysis sidecars.
Nothing depends on the CLI, and `splendor-eval` stays a model crate with no
process or file I/O. `splendor-search` and `splendor-replay` remain independent
and do not depend on each other; higher-level CLI and offline league tooling
compose their public APIs. See `docs/search.md` and `docs/league.md`.

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
- **`splendor-agent`** (M05/M08) is the stdio agent SDK: an NDJSON client FSM
  generic over an `AgentPolicy`. A policy sees only its own `Observation`,
  cumulative player-projected `VisibleEvent` history, the server's
  `legal_actions`, public request metadata, and a derived
  `StableRng` — never `FullState`, the raw seed, or the replay. The runtime
  rejects any policy action outside `legal_actions`. `agent-random` and
  `agent-heuristic` are the reference policies exposed by the CLI.
- **`splendor-determinization-agent`** (M08) is the live player-view binding of
  the frozen M07 replay-neutral analysis API. It depends on the Agent SDK and
  imperfect-search layers, verifies the certified legal root, and never
  accepts replay or referee-only state.
- **`splendor-ismcts` / `splendor-ismcts-agent`** (M10) implement a
  deterministic observation-history ISMCTS candidate and its live Agent SDK
  binding. Tree keys contain acting-player observations and their visible
  post-root simulated history, never referee state. The M07 sampler remains a
  separate frozen dependency and baseline. See `docs/ismcts.md`.
- **`splendor-eval`** (M05/M09) is the pure evaluation model: plan/gate
  validation and hashing, canonical cyclic-seat schedule expansion,
  integer-only aggregation, and paired promotion decisions. It performs no
  process spawning
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
- **`splendor-league`** (M11) validates versioned league roles and identities,
  binds the manifest-derived plan hash to a canonical executed evaluation
  report and match schedule, then offline-projects the bound Arena
  report/replay pairs into actor player-view examples. It never sends referee
  artifacts to an agent and performs no training. See `docs/league.md`.
- **`splendor-learning`** (M12) accepts `TrainingDatasetV1`, never
  `FullState`/replay, and implements the frozen player-view representation,
  legal-action policy head, 2–4 seat value vector, deterministic supervised
  trainer, versioned checkpoint, inference API, and source-level held-out
  evaluation. It does not depend on Arena, protocol, agents, ISMCTS, or the
  CLI, and it does not guide live search. See `docs/learning.md`.
- **`splendor-neural-search` / `splendor-neural-agent`** (M13) load an exact
  semantic M12 checkpoint, use its legal-action Policy probabilities as priors
  and its 2–4 seat Value vector for leaf bootstrap, then select with an
  integerized PUCT-like rule. Tree keys remain acting-player Observation plus
  visible simulated history; model inference never accepts `FullState`. The
  live policy independently matches the search root against the server's
  certified legal set. This is a candidate layer and does not modify or
  promote the frozen M10 agent. See `docs/neural-search.md`.
- **`splendor-analysis`** (M14A) fully verifies `ReplayV1`, projects each
  recorded actor's Observation/visible history, reruns an exact checkpoint-bound
  analyzer, and emits a strict `AnalysisTraceV1` sidecar. Default-safe
  `player_view` and referee-only hidden data are separate fields. The local
  `apps/replay-studio` frontend consumes JSON only; it never loads a model or
  runs search. See `docs/replay-studio.md`.
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
