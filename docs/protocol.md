# Protocol (NDJSON, v0.2)

One JSON object per line. Transport (stdio / TCP / WS) is independent of schema.

## Identity model

| field | who | meaning |
|-------|-----|---------|
| `recipient_player_id` (in `Meta`) | server → client | the seat this message is addressed to |
| `actor_player_id` (in `ActionApplied` only) | server → all | the seat that performed the action |
| `server_seq` | server | monotonic per-game sequence number |
| `request_id` | server | correlates a client `Action` to its `RequestAction` |

**A client `Action` carries NO authorizing identity.** It only contains
`action` + `Meta`. A client that sets `recipient_player_id` to claim another
seat is ignored by the runner (PR-04) — seat binding is a server-side state.

## Messages

### Server → Client

- `hello` — `engine_version`, `ruleset`, `catalog_version`,
  `ruleset_fingerprint` (a `PublicStateHash` hex). v0.2 adds the last two.
- `game_start` — `player_count`, `your_player_id`, `seed_commitment`.
- `observation` — `Observation` + `observation_hash` (`ObservationHash`).
- `request_action` — `deadline_ms`, `legal_actions`, `observation_hash`.
- `action_applied` — `actor_player_id` (single, unambiguous) + `action`.
  Uses `VisibleEvent` projection so blind reserves are redacted for spectators.
- `game_end` — `GameResult`.
- `error`, `ping`.

### Client → Server

- `hello` — `agent_name`, `agent_version`.
- `action` — `action` only. Seat is implied by the bound connection.
- `pong`.

## Observation scoping

Every server message is generated **per recipient**. The `Observation` and the
`VisibleEvent` transcript are projected with `Audience::Player(recipient)` so a
player sees only their own blind reserves. A spectator (`Audience::Spectator`)
sees no blind identities. The referee log (`RefereeEvent`) is never serialized.

## Hash fields

Protocol messages carry `ObservationHash` only. They MUST NOT carry
`FullStateHash` — that would leak deck order and opponents' blind cards as a
comparable fingerprint.
