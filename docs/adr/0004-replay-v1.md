# ADR-0004: Replay v1

## Status

Accepted in M03 (`m03-replay-v1` target).

## Context

The M02 `replay-check` only kept a `Vec<Action>` in one process and re-ran it
immediately with the same engine build, comparing a single final hash. That is
not a persisted replay, cannot be reloaded, and cannot locate the ply at which
two runs diverge.

M03 needs a durable, self-verifying referee record: a file that, once reloaded,
checks compatibility, replays step by step, verifies a full-state hash before
and after every ply, and reports the exact ply and reason on any tampering.

## Decision

1. **Replay is referee-only.** `splendor-replay` depends on `splendor-catalog`
   and `splendor-core` only. It MUST NOT depend on `splendor-protocol`, and
   `splendor-core` MUST NOT depend on it.

2. **The seed and full-state hashes are hidden information.** A replay can
   reconstruct decks and blind reserves, so a replay v1 file must not be sent
   to an agent or spectator during a live match.

3. **Actions are semantic**, exactly the `splendor_core::Action` shape — never
   a policy index.

4. **Every ply stores a before and after full-state hash.** These form the
   verification chain the verifier walks; a divergence is reported with the
   exact `ply` and a specific error kind, never a bare "mismatch".

5. **Owned DTOs at the file boundary.** `ReplayHash` is a validated
   64-lowercase-hex string (not `FullStateHash`, which stays non-`Serialize`).
   `ReplayRulesetV1` is an owned ruleset DTO (the runtime `Ruleset` carries
   `&'static str`). All replay DTOs, plus `Action` and `Gems`, use
   `#[serde(deny_unknown_fields)]`.

6. **The v1 verifier supports only `splendor-base-v1`.** An unknown ruleset id
   returns `UnsupportedRuleset` rather than guessing or silently falling back.

7. **Purchased ownership is canonicalized** (sorted by `CardId`) so a set of
   cards has one state identity regardless of purchase order; chronological
   order lives only in the event log. This changed the hash semantics, so M03
   bumped `ENGINE_VERSION` to `0.4.0`, `PROTOCOL_VERSION` to `0.4`, the full and
   public hashes to `v5`, and the observation hash to `v6`, and added
   `fixtures/protocol/v0.4/` (v0.3 fixtures are kept as historical records).

## Consequences

- A replay is reproducible from `seed + exact ruleset + action sequence +
  compatible engine semantics`.
- Replay v1 does **not** record a resolved chance stream, so it makes no promise
  of reconstruction across incompatible engine versions. A future Replay v2
  would add an explicit chance stream.
- v1 deliberately excludes snapshots, signatures, redaction, compression,
  random-access, and cross-engine migration.
