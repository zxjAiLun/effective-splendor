# Splendor AI Platform (M10/M11 search and learning-data foundation)

Deterministic Splendor rules engine with strict **FullState / Observation** isolation, explicit chance events, semantic actions, reproducible competitive evaluation, observation-history ISMCTS, and traceable player-view dataset generation.

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
| `splendor-determinization-agent` | Live player-view policy that binds Arena observations/history to M07 search |
| `splendor-eval` | Canonical evaluation plans/reports and deterministic promotion gates |
| `splendor-ismcts` | M10 deterministic observation-history information-set tree search |
| `splendor-ismcts-agent` | Live player-view Arena policy for M10 search |
| `splendor-league` | M11 league manifests and report/replay-bound player-view datasets |
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
cargo run -p splendor-cli -- agent-determinization --sample-seed 17 --sample-count 1 --max-depth-turns 1 --max-nodes 100
cargo run -p splendor-cli -- agent-ismcts --sample-seed 17 --simulations 64 --max-depth-turns 2 --exploration-bias 100000000
cargo run -p splendor-cli -- promotion-gate --plan plan.json --eval-report eval-report.json --gate gate.json --out promotion-report.json
cargo run -p splendor-cli -- league-plan --manifest league.json --out plan.json
cargo run -p splendor-cli -- build-dataset --manifest league.json --evaluation-dir eval-output --replays replay-list.json --out dataset.json
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

## Architecture (M10/M11 slice)

```text
splendor-core
├── splendor-search
├── splendor-belief
│   └── splendor-imperfect-search
│       └── splendor-determinization-agent
│           └── splendor-agent
├── splendor-ismcts
│   └── splendor-ismcts-agent
│       └── splendor-agent
├── splendor-arena
│   └── splendor-eval
│       └── splendor-league
├── splendor-replay
│   └── splendor-league
└── splendor-cli
```

The replay-bound `analyze-replay` command is a referee full-state MaxN
analysis. `analyze-replay-player-view` reconstructs only the recorded actor's
visible prefix, builds a C1 information set, samples C2 hidden states, and
aggregates the C3 continuation results. Root determinization is a reproducible
baseline with a documented strategy-fusion limitation; it is not MCTS.
`agent-determinization` applies that same replay-neutral API to the live
`Observation + cumulative VisibleEvent history` stream. The M07 algorithm is
unchanged; M08 only adds the Arena/Agent binding.

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

## M10/M11 status and roadmap

1. M08: live player-view search agent (complete)
2. M09: paired competitive evaluation and promotion gate v1 (complete)
3. M10: observation-history ISMCTS v1 + live agent (implemented candidate)
4. M11: league manifest + traceable player-view dataset v1 (implemented)
5. M12–M13: policy-value model and neural-guided search
6. M14+: Python/PyO3 and research UI

M09 consumes immutable M05 plan/report artifacts and compares a candidate with
a champion over complete seed blocks, after all cyclic seat rotations. A
deterministic one-sided 95% confidence lower bound, reliability limits, and the
configured Arena move deadline must all pass before promotion. See
`docs/evaluation.md`; a result is evidence for the exact hashed plan, not a
general strength claim.

M10 shares future policies across sampled worlds using only acting-player
observations and visible simulated history; its v1 pre-root opponent-history
abstraction is documented in `docs/ismcts.md`. M11 binds every dataset source
through the executed evaluation plan/report and canonical match index to a
completed Arena report, strictly verified replay, and exact scheduled league
policy/model identity before projecting actor-only examples. See
`docs/league.md`. Neither the checked-in M10 matchup nor the new infrastructure
is a promotion or measured strength claim until its frozen evaluation runs.

## License

MIT
