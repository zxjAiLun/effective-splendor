# ADR-0003: Canonical rules closure

## Status

Accepted in M02 (`m02-rules-closure` target).

## Decision

`splendor-core` is the only owner of rules state transitions, legal-action
enumeration, and terminal semantics.

- `FullPlayerState.purchased` is canonical development-card ownership.
  `bonuses` and `prestige` remain hot-path caches and are checked against
  purchased cards and nobles by `assert_invariants()`.
- The complete catalog is conserved exactly once across decks, market slots,
  reserved cards, and purchased cards.
- `ReserveMarket` and `ReserveDeck` carry an atomic `give_back` token transfer.
  If reserve grants gold, legal actions enumerate every exact return that
  brings the player back to the token limit. The transfer event records both
  `taken_from_bank` and `returned_to_bank` before `CardReserved`.
- `Pass` is legal only when no other main action exists. Core tracks
  consecutive forced passes and ends a full round of them with
  `TerminalReason::Stalemate`.
- A prestige threshold finishes the current round so every seat has taken the
  same number of actions. Only the seats after the triggerer (up to the last
  seat) still act; if the last seat triggers, the game ends immediately. The
  engine starts at seat 0, so the remaining-seat count is
  `player_count - 1 - triggerer`. Configurable start players would replace this
  with the ring distance from the round anchor.
- Setup shuffling uses a local RNG. `FullState` stores the resolved deck order,
  not an agent's action-selection RNG.

## Consequences

CLI, replay, arena, search, and Python integrations all call
`legal_actions()` and `apply()` and must not duplicate pass counters, reserve
discard policies, ranking, or final-round logic. Semantic actions remain the
canonical core representation; any policy-index codec belongs to a later
training layer.

The purchased-card and forced-pass fields are part of observation and hash
identity. The action and observation wire schemas therefore advance to
protocol `0.3`; old v0.2 fixtures remain as historical compatibility records.
