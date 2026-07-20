# ADR-0001: Information Boundary

## Status

Accepted (PR-01, Phase 0 Contract Hardening).

## Context

The engine is the foundation for RL / MCTS self-play. During the Phase 0 audit
we found that, although `Observation` already hid opponents' blind-reserved
cards at the struct level, **the full protocol output still leaked hidden state**:

- `full_state_hash()` (deck order + every blind `CardId`) was being attached
  to `Observation` messages, giving agents a comparable fingerprint of the
  hidden information set.
- `GameEvent::CardReserved` always carried the real `CardId`, and any host
  that serialized the event log would reveal blind draws.
- The protocol exposed a vague `player_id` that doubled as both recipient and
  actor, and clients could assert an authorizing identity.

These violate the project's core invariant: opponents / spectators must not be
able to distinguish information sets that should be indistinguishable.

## Decision

1. **Three typed hashes.** `FullStateHash`, `PublicStateHash`,
   `ObservationHash` are distinct newtypes. `FullStateHash` can only be
   produced inside `splendor-core` and can never be passed where an
   `ObservationHash` is expected (the protocol's `Meta::with_observation_hash`
   accepts `ObservationHash` only).

2. **Two event layers.** `RefereeEvent` (may contain all hidden info) and
   `VisibleEvent` (redacted by audience). The single projection function
   `visible_events(log, audience)` is the only exit point; the protocol layer
   serializes `VisibleEvent`, never `RefereeEvent`.

3. **Explicit identity fields.** `recipient_player_id` (server → client
   receiver) and `actor_player_id` (single, in `ActionApplied` only) are
   distinct. Client `Action` uses a separate `ClientMeta` with no seat,
   server-sequence, or state-hash field; seat binding is the runner's job
   (PR-04).

4. **No seed in visible events.** The referee's setup seed remains in
   `RefereeEvent`, but `VisibleEvent::GameStarted` omits it. A seed can be used
   to reconstruct deck order and is therefore not a player-facing field.

## Consequences

- A blind reserve produces identical `VisibleEvent` transcripts for two worlds
  that differ only in the drawn card identity, for any non-owner audience.
- Same `ObservationHash` for indistinguishable observations; different
  `FullStateHash` for the referee.
- Protocol golden fixtures can be asserted to contain no `FullStateHash` and no
  opponent blind `CardId`.

## Revisit

When building `splendor-arena` (PR-04): the runner owns seat binding and must
enforce that clients cannot impersonate another seat. When building replay
format v1 (PR-03): a `RefereeReplay` carries `RefereeEvent`s for post-game
audit, while `PlayerTranscript`s are redacted per `VisibleEvent`.
