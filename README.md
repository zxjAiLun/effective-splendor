# Splendor AI Platform (Phase 0)

Deterministic Splendor rules engine with strict **FullState / Observation** isolation, explicit chance events, semantic actions, and an NDJSON agent protocol foundation.

> **Phase 0 goal:** same seed + same action sequence → identical terminal `full_hash` across engine uses; random self-play without illegal states; observations never leak opponents' blind reserved cards.

## Workspace

| Crate | Role |
|-------|------|
| `splendor-catalog` | Cards, nobles, ruleset constants |
| `splendor-core` | Rules engine (`FullState`, legal/apply, replay log, hashes) |
| `splendor-protocol` | NDJSON message schema |
| `splendor-cli` | Bench / play / replay-check / protocol demo |

## Quick start

```bash
cargo test
cargo run -p splendor-cli -- version
cargo run -p splendor-cli -- play --seed 42
cargo run -p splendor-cli -- bench --games 1000
cargo run -p splendor-cli -- replay-check --seed 42
cargo run -p splendor-cli -- protocol-demo
```

## Architecture (Phase 0 slice)

```text
splendor-catalog
      │
splendor-core   (FullState / Observation / Action / events / hash)
      │
      ├── splendor-protocol  (NDJSON schema)
      └── splendor-cli       (local tools)
```

### Non-negotiable invariants

1. **FullState** is referee-only (deck order, blind reserves, RNG).
2. **Observation(player)** never includes other players' blind reserved card IDs.
3. Chance outcomes are **explicit events** (`CardRevealed`, …), not seed-only.
4. Actions are **semantic** (`take_tokens`, `buy_market`, …), not policy indices.
5. `TakeTokens { take, give_back }` is **atomic** (no fake intermediate decision state).

## Roadmap after Phase 0

1. Heuristic agents  
2. Perfect-info MCTS (oracle) + Determinization MCTS  
3. Policy-value net + self-play league  
4. Python/PyO3 env, Web UI  

## License

MIT
