# Protocol (NDJSON, v0.2)

One JSON object per line. Transport (stdio / TCP / WS) is independent of schema.

## Identity model

| field | who | meaning |
|-------|-----|---------|
| `recipient_player_id` (in `Meta`) | server → client | the seat this message is addressed to |
| `actor_player_id` (in `ActionApplied` only) | server → all | the seat that performed the action |
| `server_seq` (in `Meta`) | server | monotonic per-game sequence number |
| `request_id` | server/request echo | correlates a client `Action` to its `RequestAction` |

**A client `Action` carries NO authorizing identity.** It contains `action` plus
`ClientMeta`, which has only `protocol_version`, `game_id`, and the optional
`request_id`. There is no client-side seat, `server_seq`, or state-hash field.
The runner still validates the echoed identifiers against server-side state.

## Messages

### Server → Client

- `hello` — `engine_version`, `ruleset`, `catalog_version`,
  `ruleset_fingerprint` (a typed `PublicStateHash`). v0.2 adds the last two.
- `game_start` — `player_count`, `your_player_id`, `seed_commitment`.
- `observation` — `Observation` + `observation_hash` (`ObservationHash`).
- `request_action` — `deadline_ms`, `legal_actions`, `observation_hash`.
- `action_applied` — `actor_player_id` (single, unambiguous) + `action`.
- `event` — one already-projected `VisibleEvent`; raw `RefereeEvent` is not a
  protocol type.
- `game_end` — `GameResult`.
- `error`, `ping`.

### Client → Server

- `hello` — `agent_name`, `agent_version`.
- `action` — `action` plus `ClientMeta`. Seat is implied by the bound connection.
- `pong`.

## Observation scoping

Every non-broadcast server message is generated **per recipient**. The
`Observation` and each `VisibleEvent` are projected with
`Audience::Player(recipient)` so a player sees only their own blind reserves. A
spectator (`Audience::Spectator`) sees no blind identities. The referee log
(`RefereeEvent`) is never serialized; even the setup seed is omitted from the
visible event projection.

## Hash fields

Agent-facing state messages carry `ObservationHash`; the hello message may
carry the safe ruleset/catalog `PublicStateHash` fingerprint. They MUST NOT
carry `FullStateHash` — that would leak deck order and opponents' blind cards
as a comparable fingerprint.
