# Search — M06: deterministic perfect-information MaxN (v1)

This document describes `splendor-search`: the deterministic, perfect-information
MaxN search delivered in M06. It is the canonical reference for the search
crate's boundary, contract, and offline benchmark. It is intentionally frozen
at M06 C5 closure; changing any constant or schema here requires a new
milestone and a new tag.

## 1. Scope and identity

- `SEARCH_ALGORITHM_ID = "effective-splendor-maxn"` — frozen algorithm identity.
- `SEARCH_VERSION = 1` — frozen search-format version.

M06 does **not** bump `ENGINE_VERSION`, `REPLAY_VERSION`, `ARENA_REPORT`, or
`EVALUATION`. The search crate adds a self-contained, versioned analysis format
on top of the existing engine/replay versions.

## 2. Dependency boundary

```
splendor-search  →  splendor-core  (+ splendor-catalog)
```

- Among workspace crates, `splendor-search` depends **only** on
  `splendor-core` and `splendor-catalog`. (It additionally uses the external
  crates `serde` and `thiserror`; the hard boundary is about workspace crates,
  not third-party utility crates.)
- `splendor-search` MUST NOT depend on `splendor-replay`, `splendor-protocol`,
  `splendor-agent`, `splendor-eval`, or `splendor-cli`.
- `search ↛ replay` and `replay ↛ search`: the two crates are independent.
- The CLI (`splendor-cli`) is the **only** binding layer. `analyze-replay`
  verifies a referee replay and then calls `search_maxn_v1` against the
  verified `FullState`. The search crate never reads a replay document.

## 3. Perfect-information, referee-only boundary

- The search reads `FullState` directly — a **referee** artifact that contains
  deck order and every player's blind-reserved `CardId`.
- The search is **not** an Agent SDK policy. `HeuristicAgentPolicy` (the
  baseline used for the offline strength gate) may only see its `Observation`,
  the server-certified `legal_actions`, public request metadata, and its own
  `StableRng` — never `FullState`, the raw seed, or the replay.
- The offline heuristic comparison therefore lives **only** in an ignored
  benchmark test (`crates/splendor-cli/tests/search_benchmark.rs`), never in
  production search code. The search must never be presented as a live agent.

## 4. Utility model

- The search returns an **integer** utility vector `[u(p0), u(p1), …]` of length
  equal to the player count.
- `StaticEvaluatorV1::utilities(&FullState) -> Vec<i64>` is a frozen set of
  integer weights. It must not change across the M06 line.
- Terminal rank is scaled by `TERMINAL_RANK_UNIT = 1e12` so that a finished
  game dominates any non-terminal evaluation of the same score. Higher utility
  is always preferred; there is no float arithmetic anywhere in the search.

## 5. MaxN, not minimax / paranoid

- Each node is solved from the perspective of the **current** player, who
  maximizes their own component of the utility vector.
- Tie-break is deterministic: the first action in **canonical order** wins. No
  RNG, no timestamp, no platform-dependent ordering.
- The root result carries the full utility vector and a principal variation
  (PV).

## 6. Turn-depth metric

- Search depth is measured in **completed player turns**, not plies.
- A `ChooseNoble` transition does **not** consume a turn-depth. The core
  `TurnAdvanced` event drives whether a depth unit is spent.
- `max_depth_turns` bounds the search; `max_nodes` is a hard node budget.

## 7. Deterministic iterative deepening + shared node budget

- Iterative deepening runs over `depth = 1 ..= max_depth_turns`.
- A **single** `max_nodes` hard budget is shared across all iterations.
- Only a fully-completed iteration replaces the committed root solution; a
  partially-completed final iteration is discarded.
- Tiny-budget fallback (`max_nodes = 1`): the search returns
  `first_canonical_action` plus the root static evaluation. This keeps the
  contract total even when the budget is degenerate.

## 8. Exact transposition table

- TT key = `(full_state_hash(state), remaining_depth_turns)`.
- **Exact-only**: no alpha-beta bounds, no depth-relative values. Only nodes
  solved to completion are cached.
- Every exact entry stores the **complete PV from the cached node**, so PV
  semantics are identical across the three code paths: initial solve,
  TT-cached return, and TT-hit return. Specifically:
  - a **non-leaf** entry's PV begins with that node's chosen action, followed
    by the child's PV;
  - a **terminal or depth-cutoff** entry stores an **empty** PV.
- An empty leaf PV is the frozen contract, not an invariant violation: leaf
  entries have no continuation to record.
- Statistics: `nodes_visited`, `nodes_expanded`, `leaf_evaluations`,
  `transposition_hits`, `transposition_entries`.
- Invariant: `transposition_entries == tt.len()` (kept synchronized on every
  store, never accumulated). Node-count identity:
  `nodes_visited == nodes_expanded + leaf_evaluations + transposition_hits`.

## 9. Canonical order

- Seven frozen category keys order actions deterministically.
- `first_canonical_action` is the deterministic tie-break root used by the
  tiny-budget fallback and as the canonical first choice everywhere.

## 10. C3 no-TT conformance

- An independent `reference_maxn` (no TT, no iterative deepening, no node
  budget) is reimplemented under `crates/splendor-search/tests/support`. It is
  production-inaccessible and exists only to cross-check.
- The 12-test exact-TT suite contains **eight fixed differential positions**
  plus dedicated TT-hit, statistics, fallback, and public-PV checks:
  - each differential position asserts `action`, utility-vector, and full-PV
    equality against the reference solver;
  - one test proves at least one position actually exercises a TT hit;
  - one test asserts the stats classification identity
    `visited = expanded + leaf + tt_hits`;
  - one test asserts the tiny-budget (`max_nodes = 1`) fallback identity
    (`1 / 1 / 0 / 0`);
  - one test replays the public root PV and asserts every entry is legal and
    applyable.
- Recursive resolution is **fail-closed**: `NoLegalActions` and
  `InvalidUtilityShape` replace any `expect`/index panic.

## 11. `SearchConfigV1`

- Fields: `max_depth_turns: u8`, `max_nodes: u64`.
- Limits: `MIN_SEARCH_DEPTH_TURNS = 1`, `MAX_SEARCH_DEPTH_TURNS = 12`,
  `MIN_SEARCH_NODES = 1`, `MAX_SEARCH_NODES = 10_000_000`.
- Defaults: `{ max_depth_turns: 2, max_nodes: 50_000 }`.
- `validate()` returns `SearchError::InvalidConfig`. An invalid config exits
  the CLI with code **1** (distinct from the CLI-contract code 2 used for
  unknown/duplicate/missing flags).

## 12. `analyze-replay` CLI contract (strict)

- Flags: `--input`, `--ply`, `--max-depth-turns`, `--max-nodes`, `--out` — each
  must appear **exactly once**. Unknown, duplicate, or missing flags exit **2**.
- `--help` / `-h` are **not** special: they are treated as unknown flags and
  exit **2**. The CLI must not bypass the unknown/duplicate/missing validator.
- Success: exit **0**, empty `stdout`, empty `stderr`; the artifact is
  published atomically.
- Failure: exit **1**, empty `stdout`, exactly one `error: ` line on `stderr`,
  and **no** artifact produced.
- Pipeline: `verify_replay_position` first (validates the entire replay
  suffix), then `search_maxn_v1`, then atomic publish. The document hash is
  computed **after** full verification, never before.

## 13. `SearchAnalysisV1` schema (frozen, deterministic)

- `SEARCH_ANALYSIS_FORMAT = "effective-splendor-search-analysis"`,
  `SEARCH_ANALYSIS_VERSION = 1`.
- `ReplaySearchSourceV1` and `SearchAnalysisV1` are both
  `#[serde(deny_unknown_fields)]` and carry **zero** non-deterministic
  metadata — no timestamp, no absolute path, no hostname.
- `SearchStopReasonV1` uses `rename_all = "snake_case"`
  (`depth_limit_reached` / `node_budget_reached`).
- `analysis_sha256` = SHA-256 of the **raw artifact bytes including the trailing
  LF**. The benchmark recomputes this over the published file, not over a
  re-serialized copy.
- `replay_document_hash_v1` = SHA-256 of
  `domain("effective-splendor-replay-document-v1\0") || compact_canonical_json`.

## 14. Atomic, no-overwrite publish

- The artifact is written to a temp file in the **same** output directory, then
  `hard_link` create-if-absent at the target path. A published artifact is
  never overwritten.
- The `hard_link` is the **commit point**: once it succeeds the target is
  published, and the subsequent temp unlink is best-effort cleanup whose
  failure is deliberately swallowed — it can never reverse a successful
  publication into an error.
- Temp cleanup therefore covers the normal success path and every failure path
  the code actually reaches. If a temp unlink fails *after* the hard-link
  commit succeeded, or the process crashes near the commit point, an **inert**
  `.tmp` sibling may remain. Such a residue is never authoritative: it is never
  a target, and it neither undoes nor overwrites an already-committed artifact.

## 15. Frozen benchmark corpus (M06)

`benchmarks/m06-search-v1.corpus.json` is a **test-only** schema — it is not
part of any production crate's API.

- **12 frozen positions**: 4×2p, 4×3p, 4×4p. Depth is 2 for 2p/3p and 1 for 4p;
  `max_nodes = 500_000` everywhere. The `(players, game_seed, action_seed, ply,
  depth, nodes)` tuples are frozen and must never be swapped or re-picked for
  nicer results.
- **`FROZEN_CORPUS_HASH`** = SHA-256 of
  `domain("effective-splendor-search-benchmark-v1\0") || compact_json(corpus)`.
  The manifest holds **no** self-referential hash field.
- **Run command** (explicit, `#[ignore]`):
  `cargo test --locked -p splendor-cli --test search_benchmark -- --ignored --test-threads=1`
- **Offline heuristic strength gate**: the real `HeuristicAgentPolicy` (name
  `splendor-cli-heuristic`, version `0.1.0`, `StableRng::new(101)`, re-created
  per case) is compared against a test-only no-TT reference MaxN forced to take
  the heuristic's root action at the same exact depth. Gate:
  - search ≥ heuristic in **all 12** cases;
  - **≥ 1** strict improvement (`MIN_STRICT_HEURISTIC_IMPROVEMENTS = 1`).
  A gate failure is **reported**, never a reason to re-pick the corpus.
- **Reproducibility**: the benchmark is run twice; the two runs must agree on
  the corpus hash, the 12 document hashes, the 12 artifact hashes, the 12
  results, and the strict-improvement count.

## 16. Limitations

- **Perfect-information only.** The search reads the referee `FullState`; it
  performs no hidden-information or opponent modeling.
- **Bounded.** Results are limited by `max_depth_turns` and `max_nodes`; deeper
  play is not searched.
- **Integer evaluation.** `StaticEvaluatorV1` is integer-only, so it cannot
  express fine-grained float nuance.
- **Not an online agent.** The search must not be wired as a live Agent SDK
  policy; the heuristic comparison is offline-only by design.
- **No replay coupling.** `search` does not consume replays and `replay` does
  not consume search; the CLI is the only binder.

## 17. Reproducibility guarantees

- Integer arithmetic only; no RNG inside the search; no wall-clock reads;
  single-threaded.
- Canonical action order + exact TT + frozen static eval → **byte-identical**
  analysis artifacts across runs and platforms, given the same catalog/engine
  versions. This is what the frozen corpus hash and the dual-run reproducibility
  gate enforce.
