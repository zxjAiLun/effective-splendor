# Splendor AI Platform (M04 arena v1)

Deterministic Splendor rules engine with strict **FullState / Observation** isolation, explicit chance events, semantic actions, and an NDJSON agent protocol foundation.

> **M02 baseline:** same seed + same action sequence → identical terminal `full_hash`; all rules and terminal semantics live in `splendor-core`; observations never leak opponents' blind reserved cards.

## Workspace

| Crate | Role |
|-------|------|
| `splendor-catalog` | Cards, nobles, ruleset constants |
| `splendor-core` | Rules engine (`FullState`, legal/apply, replay log, hashes) |
| `splendor-protocol` | NDJSON message schema |
| `splendor-replay` | Referee replay v1: record + strict step-by-step verify |
| `splendor-arena` | Stdio match runner: spawns agent processes, referees one match, writes report + replay |
| `splendor-cli` | Bench / play / record-replay / verify-replay / protocol demo / run-match / agent-random |

## Quick start

```bash
cargo test
cargo run -p splendor-cli -- version
cargo run -p splendor-cli -- play --seed 42
cargo run -p splendor-cli -- bench --games 1000
cargo run -p splendor-cli -- record-replay --players 2 --seed 42 --action-seed 1001 --out game.replay.json
cargo run -p splendor-cli -- verify-replay --input game.replay.json
cargo run -p splendor-cli -- protocol-demo
```

### Run an arena match

The same binary is both the match runner and the reference agent, so a
self-play match needs no other program:

```bash
cargo build -p splendor-cli   # ensure `splendor` exists on PATH / target dir
splendor run-match \
  --config     arena-config.json \
  --report-out arena-report.json \
  --replay-out replay.json
```

Exit `0` = completed (writes report + verified replay), `2` = aborted (report
only), `1` = CLI/config/I/O/internal error (no artifacts). See `docs/arena.md`
for the config schema, artifact contract, and the reference random agent.

See `docs/replay.md` for the replay v1 format and verification chain.

## Architecture (M02 slice)

```text
splendor-catalog
      │
splendor-core   (FullState / Observation / Action / events / hash)
      │
      ├── splendor-protocol  (NDJSON schema)
      ├── splendor-replay    (referee replay v1)
      ├── splendor-arena     (stdio match runner)
      └── splendor-cli       (local tools + run-match / agent-random)
```

### Non-negotiable invariants

1. **FullState** is referee-only (deck order and blind reserves).
2. **Observation(player)** never includes other players' blind reserved card IDs.
3. Chance outcomes are **explicit events** (`CardRevealed`, …), not seed-only.
4. Actions are **semantic** (`take_tokens`, `buy_market`, …), not policy indices.
5. `TakeTokens { take, give_back }` and reserve-with-return are **atomic**.
6. Purchased card identities are retained and all 90 development cards are
   conserved exactly once.
7. Forced Pass/Stalemate and final-round accounting are defined by core, not a
   host loop.

## Roadmap after M02

1. Heuristic agents  
2. Perfect-info MCTS (oracle) + Determinization MCTS  
3. Policy-value net + self-play league  
4. Python/PyO3 env, Web UI  

## License

MIT
