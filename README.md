# Splendor AI Platform (M07 determinization v1)

Deterministic Splendor rules engine with strict **FullState / Observation** isolation, explicit chance events, semantic actions, an NDJSON agent protocol, replay-bound perfect-information search, and a frozen player-view root-determinization baseline.

> **M02 baseline:** same seed + same action sequence → identical terminal `full_hash`; all rules and terminal semantics live in `splendor-core`; observations never leak opponents' blind reserved cards.

## Workspace

| Crate | Role |
|-------|------|
| `splendor-catalog` | Cards, nobles, ruleset constants |
| `splendor-core` | Rules engine (`FullState`, legal/apply, replay log, hashes) |
| `splendor-protocol` | NDJSON message schema |
| `splendor-replay` | Referee replay v1: record + strict step-by-step verify |
| `splendor-arena` | Stdio match runner: spawns agent processes, referees one match, writes report + replay |
| `splendor-search` | Deterministic perfect-information MaxN continuation search |
| `splendor-belief` | Validated player information sets and deterministic hidden-state sampling |
| `splendor-imperfect-search` | Replay-neutral root determinization over player-view information sets |
| `splendor-cli` | Bench / play / record-replay / verify-replay / analyze-replay / player-view analysis / arena tools |

## Quick start

```bash
cargo test
cargo run -p splendor-cli -- version
cargo run -p splendor-cli -- play --seed 42
cargo run -p splendor-cli -- bench --games 1000
cargo run -p splendor-cli -- record-replay --players 2 --seed 42 --action-seed 1001 --out game.replay.json
cargo run -p splendor-cli -- verify-replay --input game.replay.json
cargo run -p splendor-cli -- analyze-replay --input game.replay.json --ply 0 --max-depth-turns 1 --max-nodes 2000 --out full-state-analysis.json
cargo run -p splendor-cli -- analyze-replay-player-view --input game.replay.json --ply 0 --sample-seed 20260703 --sample-count 4 --max-depth-turns 1 --max-nodes 2000 --out player-view-analysis.json
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

## Architecture (M07 slice)

```text
splendor-core
├── splendor-search
├── splendor-belief
│   └── splendor-imperfect-search
└── splendor-cli
    ├── splendor-replay
    ├── splendor-search
    └── splendor-imperfect-search
```

The replay-bound `analyze-replay` command is a referee full-state MaxN
analysis. `analyze-replay-player-view` reconstructs only the recorded actor's
visible prefix, builds a C1 information set, samples C2 hidden states, and
aggregates the C3 continuation results. Root determinization is a reproducible
baseline with a documented strategy-fusion limitation; it is not MCTS.

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

## M07 status and roadmap

1. Heuristic agents
2. Perfect-information MaxN + replay-bound root determinization baseline
3. Policy-value net + self-play league
4. Python/PyO3 env, Web UI

M07 C1–C4 freeze the information-set, deterministic sampler, root
aggregation, and player-view artifact contracts. C5 freezes the benchmark and
documentation; the `m07-determinization-v1` tag is created only after the
independent C5 review is approved.

## License

MIT
