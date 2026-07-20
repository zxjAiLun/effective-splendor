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
        ├───────────────┬────────────────┬─────────────────┐
        ▼               ▼                ▼                 ▼
splendor-protocol  splendor-arena  splendor-search   splendor-python
   (wire DTO)      (stdio runner)  (rollout/MCTS)   (PyO3 batched env)
```

Rules:
- **`splendor-catalog`** is pure data + accessors. No game logic.
- **`splendor-core`** owns the domain: `FullState`, `Observation`,
  `Action`, legal-action enumeration, state transitions, and `RefereeEvent`.
  It is the single source of truth for what is and isn't a legal move.
- **`splendor-protocol`** owns wire DTOs (`ServerMessage` / `ClientMessage`,
  `ServerMeta` / `RecipientMeta` / `ObservationMeta` / `RequestMeta`). It MUST
  NOT serialize `RefereeEvent` or `FullStateHash` directly; it uses
  `VisibleEvent`, `ObservationHash`, and the separate `RulesetFingerprint`.
- **`splendor-arena`** (PR-04) binds an agent process to a seat, enforces
  deadlines / timeouts / illegal-action policy, and is the only place that
  decides *who* a client is. Clients never authorize their own seat.
- **`splendor-search`** (PR-06+) uses the in-process `splendor-core` API
  for rollouts / MCTS / determinization.
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
