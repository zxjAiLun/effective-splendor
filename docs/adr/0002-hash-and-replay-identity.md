# ADR-0002: Hash and Replay Identity

## Status

Accepted (PR-01, Phase 0 Contract Hardening).

## Context

We need stable, comparable identities for game states and observations so that:
- agents can cache per information-set without splitting on hidden state;
- replay verification can compare pre/post hashes deterministically;
- training features keyed by observation are stable across engine refactors.

The Phase 0 implementation used `format!("{:?}", obs)` for the observation
hash. That is not stable: any change to `Debug` formatting of `Observation`
(e.g. field reordering, deriving changes) silently changes the hash with no
semantic reason. `public_state_hash()` also omitted several fields that affect
legal actions and terminal judgement.

## Decision

1. **Deterministic, version-tagged byte encoding** for all three hashes
   (`splendor-full-v3`, `splendor-public-v3`, `splendor-obs-v3`). No
   `Debug`/`serde_json` in the hash path.

2. **Full coverage of behavior-affecting fields:**
   - `FullStateHash`: ruleset id + all ruleset parameters + catalog version,
     seed, deck order, all reserved `CardId`s, `end_game_triggered`,
     `turns_remaining_in_final_round`, `pending_nobles`, and (when terminal)
     the complete `GameResult` summary + `TerminalReason`.
   - `PublicStateHash`: all public observation fields, public reserved card
     identities, terminal result, and all ruleset parameters.
   - `ObservationHash`: full public board + the viewer's own private
     reserved (slot/card/tier/from_deck).

3. **Typed wrappers** (`FullStateHash` / `PublicStateHash` /
   `ObservationHash`) prevent cross-use at compile time.

## Consequences

- Identical observations hash identically even if their `Debug` repr changes.
- A public reserved card changes `PublicStateHash` and `ObservationHash`;
  a blind (deck) reserve changes neither for non-owners.
- Two full states differing only in a blind reserve yield equal
  `ObservationHash` for the opponent but different `FullStateHash`.

## Revisit

Replay v1 (PR-03) will add a `seed_commitment` + post-game reveal so that a
referee replay can be reconstructed without re-running the RNG. The hash
version tags make that format forward-compatible: a replay records which hash
version produced its step hashes.
