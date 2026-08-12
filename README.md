# Splendor AI Platform (M16 1v1 League Rating)

Deterministic Splendor rules engine with strict **FullState / Observation** isolation, explicit chance events, semantic actions, reproducible competitive evaluation, observation-history ISMCTS, traceable player-view datasets, checkpoint-bound neural search, and player-view-first replay analysis.

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
| `splendor-learning` | M12 deterministic player-view Policy + 2–4 player vector-Value training, checkpoints, inference, and offline evaluation |
| `splendor-neural-search` | M13 checkpoint-bound Policy-prior + vector-Value neural ISMCTS candidate |
| `splendor-neural-agent` | Live player-view Arena policy for M13 neural search |
| `splendor-analysis` | M14 replay-bound traces, formal-evaluation binding, and M15 neural ablation metrics |
| `splendor-cli` | Bench / play / record-replay / verify-replay / analyze-replay / player-view analysis / arena tools |
| `apps/replay-studio` | Local Replay + Rating Studio for board analysis, Elo leaderboard, and head-to-head matrix |

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
cargo run -p splendor-cli -- rating-plan --registry benchmarks/m16-internal-1v1.registry.json --config benchmarks/m16-foundation-smoke.rating.json --out local-artifacts/m16-plan.json
cargo run -p splendor-cli -- rating-run --plan local-artifacts/m16-plan.json --out-dir local-artifacts/m16-run
cargo run -p splendor-cli -- league-plan --manifest league.json --out plan.json
cargo run -p splendor-cli -- build-dataset --manifest league.json --evaluation-dir eval-output --replays replay-list.json --out dataset.json
cargo run -p splendor-cli -- train-policy-value --dataset dataset.json --config benchmarks/m12-policy-value-v1.config.json --checkpoint local-artifacts/m12/checkpoint.json --report local-artifacts/m12/training-report.json
cargo run -p splendor-cli -- evaluate-policy-value --dataset dataset.json --checkpoint local-artifacts/m12/checkpoint.json --out local-artifacts/m12/offline-eval.json
cargo run -p splendor-cli -- evaluate-policy-value-source-aware --dataset dataset.json --checkpoint checkpoint.json --config benchmarks/m15b-source-aware-policy-value-v1.config.json --out offline-eval.json
cargo run -p splendor-cli -- agent-neural-ismcts --checkpoint local-artifacts/m12-policy-value-v1-final/checkpoint.json --checkpoint-hash 108d32fa2d0d2499ead38e99b23e42cd905644358a76d5adb7392ad43401b462 --sample-seed 20260811 --simulations 64 --max-depth-turns 2 --puct-exploration-milli 1500
cargo run -p splendor-cli -- analyze-replay-neural --input match.replay.json --checkpoint checkpoint.json --checkpoint-hash <sha256> --sample-seed 20260811 --simulations 64 --max-depth-turns 2 --puct-exploration-milli 1500 --out match.analysis.json
cargo run -p splendor-cli -- diagnose-neural-evaluation --evaluation-dir eval-output --checkpoint checkpoint.json --checkpoint-hash <sha256> --sample-seed 20260811 --simulations 64 --max-depth-turns 2 --puct-exploration-milli 1500 --candidate-agent-id candidate --champion-agent-id champion --out-dir local-artifacts/diagnostic
cargo run -p splendor-cli -- build-search-teacher-targets --dataset dataset.json --evaluation-dir eval-output --config benchmarks/m15c-search-teacher-targets-v1.config.json --out local-artifacts/m15c/search-teacher-targets.json
cargo run -p splendor-cli -- train-policy-value-search-teacher --dataset dataset.json --targets search-teacher-targets.json --config benchmarks/m15c-search-policy-value-v1.config.json --checkpoint local-artifacts/m15c/checkpoint.json --report local-artifacts/m15c/training-report.json
cargo run -p splendor-cli -- evaluate-policy-value-search-teacher --dataset dataset.json --targets search-teacher-targets.json --checkpoint local-artifacts/m15c/checkpoint.json --config benchmarks/m15c-search-policy-value-v1.config.json --out local-artifacts/m15c/offline-eval.json
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

## Architecture (M16 rating foundation)

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
├── splendor-learning
│   └── splendor-neural-search
│       └── splendor-neural-agent
│           └── splendor-agent
│       └── splendor-analysis
│           └── apps/replay-studio (JSON sidecar consumer)
├── splendor-arena
│   └── splendor-eval
│       └── splendor-league
│           └── splendor-learning
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

## M10–M21 status and roadmap

1. M08: live player-view search agent (complete)
2. M09: paired competitive evaluation and promotion gate v1 (complete)
3. M10: observation-history ISMCTS v1 + live agent (implemented; formal promotion rejected)
4. M11: league manifest + traceable player-view dataset v1 (accepted)
5. M12: supervised player-view Policy + multiplayer vector Value baseline (accepted)
6. M13: checkpoint-bound neural-guided ISMCTS + live agent (formal promotion rejected 12–52; remains candidate)
7. M14A: replay-wide AnalysisTraceV1 + local Replay Studio (accepted at `e5dfb95`)
8. M14B: formal-evaluation batch sidecars and provenance-bound aggregate diagnostics (implemented)
9. M15A: controlled Policy/Value/neutral search ablations (diagnosis complete)
10. M15B: source-aware/isolated training plus two prospective Policy-only screens (complete; rejected 4–28 and 5–27, no candidate)
11. M15C: provenance-bound search-distribution Policy targets and search-shaped Value supervision (complete; both frozen offline gates failed, no candidate)
12. M15D: nonlinear action interaction + independent Value encoder, h64 (complete; both unchanged offline gates failed, no candidate)
13. M15E: deterministic Adam optimization control (complete; train fit improved, source-level validation gates still failed, no candidate)
14. M16: 1v1 round-robin registry, Live/Official Elo, head-to-head matrix, and Rating Studio (implemented)
15. M17: own GPU Policy-Value model v1 (complete; Entity Mixer candidate rejected 1–7 vs heuristic, retained for RL initialization)
16. M18A: neural-ISMCTS / AlphaZero-like self-play RL v1 (complete route; first smoke candidate rejected 2–6 vs heuristic)
17. M18B: distributional Double-DQN / Rainbow-style RL (complete route; first smoke candidate rejected 1–7 vs heuristic)
18. M19: formal internal championship and promotion evidence
19. M20: Human Play Studio against any registered checkpoint
20. M21: optional external benchmark only after internal routes are measured

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
agent identity. M12 consumes only those player-view examples, uses a frozen
source-level split, and emits a provenance-bound checkpoint plus independently
recomputable offline metrics. Its Git-tracked formal result manifest pins the
content hashes of the otherwise local model artifacts. It does not guide search
or change the champion. M13 binds that exact semantic checkpoint hash into a
new player-view agent, using legal-action Policy priors and multiplayer Value
bootstraps in deterministic integer PUCT-like selection. Its frozen formal
64-match gate completed with zero aborts/faults but rejected promotion, so the
current determinization champion remains unchanged. See
`docs/learning.md` and `docs/neural-search.md`.

M14A is accepted at repair commit `e5dfb95` (base `e83d79e`) with independent
re-review findings P0/P1/P2 all zero. It keeps `ReplayV1` objective and writes
analysis into a separate sidecar bound to the verified replay, exact
checkpoint, and search config. Replay
Studio defaults to the recorded actor's Observation; hidden reserves and deck
future appear only after an explicit Referee Reveal switch. See
`docs/replay-studio.md`.

M14B bound all 64 formal M13 replays into a 3,905-frame diagnostic bundle.
M15A exactly reproduced every candidate decision and found that `policy_only`
was the strongest retrospective neural control, while `value_only` was worse
than neutral. M15B then filtered Policy labels to the champion and enforced
material offline gates: Policy passed, Value failed, but a new-seed Policy-only
screen still lost 4–28. The current evidence therefore implicates both Policy
generalization and Value quality, amplified by 64-simulation search. The next
round isolates Policy representation from Value gradients and collects new
champion-teacher trajectories. That second Policy-only screen still lost 5–27,
so M15B closes without a candidate: one-hot imitation NLL is not a sufficient
strength gate and Value failed both material gates. No rejected or diagnostic
seed is reused. See
`docs/m15-neural-degradation-diagnostic.md`.

M15C regenerated the accepted M07 root analysis for all 3,920 champion-owned
decisions. Recorded and regenerated actions agreed 3,920/3,920 and the soft
targets were non-degenerate, but the frozen h32 model improved held-out Policy
cross-entropy only 4.87% over uniform and made search-shaped Value MSE worse
than its constant prior. Both unchanged gates failed; no prospective screen or
candidate is authorized. The next useful round is representation/capacity
work, not target or gate tuning.

M15D tested that boundary without changing the M15C data, target projection,
split, optimizer schedule, or gates. Architecture v2 adds a nonlinear
action-conditioned Policy head and a separately trainable Value encoder, and
doubles width to h64. Policy top-1 rose slightly, but soft cross-entropy was
slightly worse than M15C; train and validation improved only 4.75% and 4.69%
over uniform. Value also remained worse than its constant prior. This is an
optimization/underfitting result for the frozen run, not evidence authorizing
gate or target tuning; no candidate or prospective screen exists.

M15E changed only the optimizer to deterministic per-example Adam while
retaining the M15D architecture, inputs, source split, epochs, learning rate,
loss, initialization and gates. Training fit improved materially: Policy
top-1 reached 43.37% and Value MSE fell to 0.00735. The source-held-out split
did not follow: Policy top-1 was 32.00%, cross-entropy improved only 5.33% over
uniform, and Value MSE 0.01925 remained worse than its constant prior. This
localizes the next investigation to source generalization, data coverage and
target factorization; M15E produces no candidate or prospective screen.

M16 now provides the common 1v1 measurement layer before any GPU/RL expansion.
It schedules every unordered pair with identical seeds and both seat rotations,
keeps sequential Live Elo separate from order-independent Official Elo, and
retains the full head-to-head matrix so cyclic matchups are visible. The formal
rating report is content-bound to the agent registry, round-robin plan, and
canonical pair evaluation reports. See `docs/rating.md`. Dataset, checkpoint,
replay, and evaluation payloads remain local artifacts rather than GitHub
content; only schemas, frozen configs, code, documentation, and compact result
manifests are candidates for source control.

M17's GPU route is a compact non-Transformer architecture: Flat ResMLP is the
control and Entity Mixer is the object-structured candidate. Both are strictly
1v1/player-view and score the Arena-certified legal action set. See
`docs/m17-gpu-model.md`; generated `.pt` checkpoints and reports remain under
ignored `local-artifacts/`.

## License

MIT
