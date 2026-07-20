# Replay v1

`splendor-replay` records a complete game to a single self-describing JSON
document and re-executes it against `splendor-core`, verifying every ply.

## What a replay is

A replay is a **referee / post-game audit record**. It contains:

- `format` — fixed `"effective-splendor-replay"`.
- `version` — fixed `1`.
- `engine_version` — the engine that produced it.
- `ruleset` — an owned copy of every ruleset parameter (see `ReplayRulesetV1`).
- `ruleset_fingerprint` — the ruleset/catalog compatibility hash.
- `player_count`, `seed`.
- `initial_state_hash` — full-state hash of the dealt starting position.
- `steps[]` — one entry per ply: `ply`, `actor`, `action`,
  `state_hash_before`, `state_hash_after`.
- `final_state_hash`, `result`.

Each hash is a 64-character lowercase hex string copied from the engine's
`FullStateHash`. The per-step before/after hashes form a verification chain: a
step's `state_hash_before` must equal the live full-state hash the engine is in
before applying that step's action, and `state_hash_after` must equal the hash
afterward.

## Information boundary

A replay contains the raw `seed` and full-state hashes, from which hidden decks
and blind reserves can be reconstructed. **A replay v1 file must not be sent to
an agent or spectator during a live match.** This is the same boundary as
`RefereeEvent`; `splendor-replay` does not depend on `splendor-protocol` and
does not reuse any protocol projection.

## Recording

```bash
cargo run -p splendor-cli -- record-replay \
  --players 2 \
  --seed 42 \
  --action-seed 1001 \
  --out game.replay.json
```

`seed` drives the deck shuffle; `action-seed` drives deterministic legal-action
selection. The same inputs always produce a byte-identical file (pretty JSON,
two-space indent, single trailing newline, no timestamps / paths / host data).

Programmatically, `ReplayRecorder` wraps a `FullState` without exposing a
mutable handle, so the recorded document always reflects exactly the actions
that drove the engine. `finish()` only succeeds once the game is terminal
(otherwise `ReplayNotTerminal`).

## Verifying

```bash
cargo run -p splendor-cli -- verify-replay --input game.replay.json
```

`verify_replay` runs, in order:

1. format and replay version;
2. engine, catalog, and ruleset (`id`) compatibility;
3. ruleset fingerprint;
4. player count;
5. rebuild the initial state from ruleset + seed + player count;
6. compare `initial_state_hash`;
7. for each step: contiguous `ply` from 0; not already terminal; `actor ==
   current_player`; live hash equals `state_hash_before`; action is in
   `legal_actions()`; apply; `assert_invariants()`; live hash equals
   `state_hash_after`;
8. state must be terminal after the last step;
9. no step may run after terminal;
10. compare `final_state_hash`;
11. compare the final `GameResult`.

Every failure carries the exact `ply` (where relevant) and a specific reason
(`ActorMismatch`, `BeforeHashMismatch`, `IllegalAction`, `AfterHashMismatch`,
`FinalHashMismatch`, `ResultMismatch`, …). The verifier never returns a bare
"mismatch", never panics on user input, and never uses `assert_eq!` on
file-provided data.

On success the CLI prints script-friendly lines:

```
ok
format_version=1
steps=76
final_hash=<64 hex>
reason=prestige_threshold
winners=0
```

On failure it exits non-zero and prints the error kind and ply to stderr.

## Compatibility promise

Replay v1 is reproducible from `seed + exact ruleset + action sequence +
compatible engine semantics`. It does **not** record a full resolved chance
stream, so v1 makes no promise of reconstruction across incompatible engine
versions. A future Replay v2 would add an explicit chance stream for permanent,
engine-independent reconstruction.

## Not in v1

Public/spectator replays, redaction, compression, digital signatures,
random-access snapshots, and cross-engine migration are intentionally out of
scope. Replay v1 is a reliable referee audit record, not a general data lake.
