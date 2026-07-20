# Protocol (NDJSON, v0.4)

One JSON object per line. Transport (stdio / TCP / WS) is independent of schema.

> v0.4 canonicalized purchased-card ownership (sorted by `CardId`), which
> changed the observation hash. Golden transcripts live under
> `fixtures/protocol/v0.4/`; the v0.2 / v0.3 fixtures are kept as historical
> records. Replay files are a separate referee artifact — see `docs/replay.md`.

## Identity model

The Rust DTOs deliberately use separate metadata types:

| type | scope | required fields |
|------|-------|-----------------|
| `ServerMeta` | broadcast (`Hello`) | protocol, game, server sequence |
| `RecipientMeta` | one player | `ServerMeta` + `recipient_player_id` |
| `ObservationMeta` | one player observation | `RecipientMeta` + `observation_hash` |
| `RequestMeta` | one action request | `RecipientMeta` + `request_id` + `observation_hash` |
| `ClientMeta` | client hello/pong | protocol, game |
| `ClientRequestMeta` | client action | `ClientMeta` + `request_id` |

Only `Hello` is broadcast. `GameStart`, `Observation`, `RequestAction`,
`Event`, `ActionApplied`, `GameEnd`, `Error`, and `Ping` require a recipient at
the type and wire level. `RequestAction` and client `Action` cannot be
constructed or parsed without a `request_id`.

**A client `Action` carries NO authorizing identity.** Its seat is bound by the
runner-side connection, while the mandatory `request_id` is only a correlation
echo. There is no client-side seat, `server_seq`, or state-hash field.

## Messages

### Server → Client

- `hello` — `engine_version`, `ruleset`, `catalog_version`, and the typed
  `RulesetFingerprint`.
- `game_start` — recipient metadata, `player_count`, `seed_commitment`.
- `observation` — recipient metadata, `Observation` (including its
  `ruleset_fingerprint`) + `observation_hash` (`ObservationHash`).
- `request_action` — `deadline_ms`, `legal_actions`, `observation_hash`.
- `action_applied` — `actor_player_id` (single, unambiguous) + `action`.
- `event` — one already-projected `VisibleEvent`; raw `RefereeEvent` is not a
  protocol type.
- `game_end` — `GameResult`.
- `error`, `ping`.

### Client → Server

- `hello` — `agent_name`, `agent_version`.
- `action` — `action` plus `ClientRequestMeta` and its required `request_id`.
  Seat is implied by the bound connection.
- `pong`.

## Observation scoping

Every non-broadcast server message is generated **per recipient**. The
`Observation` and each `VisibleEvent` are projected with
`Audience::Player(recipient)` so a player sees only their own blind reserves. A
spectator (`Audience::Spectator`) sees no blind identities. The referee log
(`RefereeEvent`) is never serialized; even the setup seed is omitted from the
visible event projection.

The v0.4 observation also includes public purchased-card identities (sorted by
`CardId`, purchase order not exposed) and the public forced-pass counter.
Reserve actions are atomic: their `return` field
records the exact `Gems` returned when the reserve grants gold and the player
would otherwise exceed the token limit.

## Hash fields

Agent-facing state messages carry `ObservationHash`, whose encoding includes
the `RulesetFingerprint` embedded in the observation. The hello message carries
the separate, safe `RulesetFingerprint` for compatibility negotiation. They
MUST NOT carry `FullStateHash` — that would leak deck order and opponents'
blind cards as a comparable fingerprint.
