# M07 Determinization v1

M07 is the frozen, replay-bound player-view baseline for deterministic hidden
state sampling in Splendor. It is intentionally a small and auditable
composition of the information-set, sampler, perfect-information search, and
CLI layers. It is not a claim of optimal imperfect-information play.

## Identity and version boundary

The public model identities are:

```text
INFORMATION_SET_VERSION      = 1
DETERMINIZATION_VERSION      = 1
IMPERFECT_SEARCH_VERSION     = 1
PROTOCOL_VERSION             = 0.5
SEARCH_VERSION               = 1
PLAYER_VIEW_ANALYSIS_VERSION = 1
ENGINE_VERSION               = 0.4.0
REPLAY_VERSION               = 1
```

The C5 benchmark is identified as:

```text
format       = effective-splendor-determinization-benchmark
version      = 1
benchmark_id = m07-determinization-v1
manifest     = benchmarks/m07-determinization-v1.corpus.json
```

The parsed manifest identity is domain-separated with:

```text
effective-splendor-determinization-benchmark-v1\0
```

and is frozen by the C5 benchmark test. The manifest has no self-referential
`corpus_hash` field.

## Dependency graph

The production direction is deliberately one-way:

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

`splendor-belief` does not depend on search, replay, protocol, agents, arena,
evaluation, or the CLI. `splendor-imperfect-search` composes belief and
perfect-information search but does not accept replay objects or raw referee
state. The CLI is the binding layer that is allowed to know both replay and
player-view APIs.

## C1: information-set boundary

The production C1 constructor accepts exactly:

```rust
Ruleset
Observation
&[VisibleEvent]
```

It does not accept `FullState`, `RefereeEvent`, `ReplayV1`, a setup seed, deck
order, a full-state hash, or an opponent's blind-reserved `CardId`.

The builder validates that the visible transcript and observation agree. It
preserves reserved-slot layout, records known cards, labels an opponent's
blind deck reserve as `HiddenDeck { tier }`, and rejects a visible transcript
that leaks an opponent's hidden card identity.

## Visible-history reconstruction

For a replay target `ply`, the CLI independently reconstructs the prefix:

```text
FullState::new(replay seed, verified ruleset)
→ project setup.events for Audience::Player(viewer)
→ for steps[0..ply): apply each action
                   project that StepResult.events
→ use the reconstructed state before steps[ply]
```

The target step is excluded from the visible history. The reconstruction checks
contiguous ply numbers, actor/current-player binding, every before hash, every
after hash, and core invariants. It never reads `position.state.log` from the
replay verifier as its history source.

## C2: deterministic hidden-state sampler

Each sample has a key that is independent of the original replay seed:

```text
information_set_hash ASCII
|| sample_seed little-endian
|| sample_index little-endian
```

The SHA-256 counter stream is:

```text
domain   = "effective-splendor-determinization-rng-v1\0"
block(c) = SHA-256(domain || key || c little-endian)
```

The stream reads four little-endian `u64` values from each 32-byte block and
increments the counter after each refill. `draw_below(n)` uses rejection
sampling:

```text
limit = u64::MAX - (u64::MAX % n)
repeat:
    v = next_u64()
    accept v when v < limit
    return v % n
```

This avoids modulo bias. The sampler uses one shared stream per sample and
consumes it in frozen tier order: `One`, `Two`, `Three`.

For each tier, the canonical ascending unseen-card pool is shuffled with
Fisher–Yates:

```text
for i from len - 1 down to 1:
    j = draw_below(i + 1)
    swap(i, j)
```

Hidden labels are ordered by player ID and then reserved-slot index. The
permutation prefix fills those `HiddenDeck` slots. The suffix becomes the deck
vector in bottom-to-top order; the core's `Vec::pop()` therefore draws the last
element as the top card. Known reserved cards, market, purchased cards, nobles,
tokens, and public counters remain fixed by the observation.

The sampled referee-only state's synthetic seed is the little-endian `u64`
formed from the first eight bytes of:

```text
SHA-256(
  "effective-splendor-determinization-state-seed-v1\0"
  || information_set_hash ASCII
  || sample_seed little-endian
  || sample_index little-endian
)
```

The sampler verifies observation equality, the complete 90-card partition,
deck lengths, tier correctness of hidden reserves, and preservation of known
slots before returning a sampled `FullState`.

`sample_determinization_v1` returns `DeterminizationV1`. Its public read-only
`state()` getter exposes the reconstructed `FullState` to referee/offline
callers such as `splendor-imperfect-search`. That `FullState` is not an
agent-facing object and is not serialized into `RootDeterminizationResultV1`
or the replay-bound player-view artifact.

## C3: root determinization aggregation

`aggregate_root_determinizations_v1` samples indices `0..sample_count`, obtains
the canonical legal root action set for each sample, and fails closed if any
sample exposes a different set. Every root action is applied to a private
sample clone.

Terminal children use the static evaluator. Non-terminal children use the
frozen perfect-information MaxN continuation search. Utility vectors are
accumulated with checked signed integer arithmetic, and execution counters are
accumulated with checked unsigned arithmetic. The root player selects the
largest utility component; an exact tie keeps the earlier canonical action.

The forced-root depth rule is explicit: apply the root action first, then run
the configured continuation search. The current frozen `SearchConfigV1`
minimum is one turn. The root action is therefore always evaluated before a
legal continuation horizon is applied.

This baseline can suffer from strategy fusion because each hidden-state sample
may receive a different perfect-information continuation. The result is a
deterministic reference baseline, not an optimal policy.

## C4: replay-bound player-view CLI

The replay-neutral API is:

```rust
analyze_player_view_v1(
    ruleset: Ruleset,
    observation: &Observation,
    visible_history: &[VisibleEvent],
    config: RootDeterminizationConfigV1,
) -> Result<PlayerViewRootAnalysisV1, ImperfectSearchError>
```

Its result has private fields and read-only getters for the visible-history
hash, information-set hash, and C3 result. It has no replay, raw seed,
`FullState`, sampled deck, or public bypass constructor.

The CLI command is:

```text
splendor analyze-replay-player-view
  --input <replay.json>
  --ply <u32>
  --sample-seed <u64>
  --sample-count <u16>
  --max-depth-turns <u8>
  --max-nodes <u64>
  --out <analysis.json>
```

All seven flags are required exactly once. There is no `--viewer`; the viewer
is the recorded actor at the target step, which must also be the current
player. Strict argv errors return exit `2`. Replay, configuration, binding,
search, and output errors return exit `1`. Success is silent; failure emits
one `error: ...` line and no stdout. Output is pretty JSON with one trailing
LF and is atomically published without overwriting an existing target.

The command first strictly parses and fully verifies the replay, computes its
document hash, binds the verified position to `steps[ply]`, independently
reconstructs the visible prefix, calls the replay-neutral API, verifies result
legality and aggregate membership, and only then publishes the artifact.
Replay seed and full state are confined to this CLI/replay binding; they do not
cross into belief or imperfect-search APIs.

## Player-view artifact

The artifact identity is:

```text
format  = effective-splendor-imperfect-search-analysis
version = 1
```

The source block binds the replay document/final hash/version/ruleset,
analyzed ply/state hash, viewer, observation hash, visible event count,
visible-history hash, information-set hash, recorded actor, and recorded
action. The top-level metadata binds engine/catalog versions, information-set
and determinization versions, imperfect-search and continuation-search IDs and
versions, the frozen configuration, the complete aggregate result, and
`recommended_matches_recorded`.

The artifact deliberately contains none of the following:

```text
replay seed
sampled FullState
sampled deck
sampled blind-reserved CardId
per-sample state hash
per-sample utility
principal variation
raw VisibleEvent history
```

## C5 frozen benchmark

The manifest contains exactly 12 positions, four each for 2-player,
3-player, and 4-player games. Each replay is produced with `ReplayRecorder`:
the frozen reserve prefix is applied first, then a canonical-order legal action
is selected with the raw continuation seed and the frozen xorshift64* step:

```text
x ^= x >> 12
x ^= x << 25
x ^= x >> 27
next = x * 0x2545_F491_4F6C_DD1D
action = canonical_order(legal_actions)[next % legal_actions.len()]
```

All prefix reserve actions use `Gems::ZERO` for returns. The frozen inputs are:

| players | game seed | continuation seed | prefix | analyzed plies |
|---:|---:|---:|---|---|
| 2 | 7002 | 17002 | `2p-reserve-mix-v1` | 0, 2, 4, 6 |
| 3 | 7003 | 17003 | `3p-reserve-mix-v1` | 0, 3, 5, 6 |
| 4 | 7004 | 17004 | `4p-reserve-mix-v1` | 0, 4, 6, 8 |

Every case uses:

```text
sample_seed     = 20260703
sample_count    = 4
max_depth_turns = 1
max_nodes       = 2000
```

Each expected record freezes the replay document hash, raw artifact SHA-256
(including the trailing LF), target and observation hashes, visible-history
and information-set hashes, visible event count, recorded actor/action,
recommendation binding, and the complete `RootDeterminizationResultV1`.

The default `frozen_m07_corpus_identity` test checks strict schema, exact input
tuples, case uniqueness, lowercase hash shape, player-count distribution, and
the domain-separated corpus hash. The explicit ignored
`m07_determinization_benchmark_is_reproducible` test runs every case twice
through the real CLI, independently reconstructs and analyzes the position,
checks the artifact and result bindings, and requires exact equality of replay
hashes, artifact bytes, hashes, source identities, results, and stats.

The corpus coverage gate requires three ply-zero histories with no prior action
events, at least six cases with opponent hidden deck reserves, at least three
cases with a viewer-owned blind reserve, at least two cases with multiple
hidden opponent slots, both zero and nonzero viewers, and all three player
counts. The benchmark measures determinism, binding integrity, information
boundary coverage, and reproducibility only. Recommendation hit rate, action
diversity, utilities, and node totals are reportable observations, not strength
or pass criteria.

## Reproducibility and limitations

Reproducibility is defined at multiple layers: deterministic replay generation,
strict replay document identity, domain-separated SHA-256 sampling, canonical
action ordering, checked aggregation, deterministic JSON serialization, raw
artifact hashing, and two-run benchmark equality. A changed seed, prefix, ply,
configuration, hash, action order, or artifact byte breaks the relevant frozen
test rather than silently recalibrating it.

M07 is limited to the supported base ruleset and the frozen C1–C4 contracts.
It is not ISMCTS, POMCP, a belief-tree search, or an optimal imperfect-
information policy. It is a deterministic root-determinization baseline with a
perfect-information continuation and an explicit strategy-fusion caveat.

## M08 live Agent binding

M08 does not change the frozen sampler or root aggregation. The new
`splendor-determinization-agent` crate implements `AgentPolicy` and calls the
same replay-neutral `analyze_player_view_v1` API with exactly:

```text
Ruleset::base_v1()
current Observation
cumulative player-projected VisibleEvent history
RootDeterminizationConfigV1
```

The generic Agent runtime owns the cumulative history. It converts the
dedicated `ActionApplied` wire message back into its equivalent visible event
and appends ordinary `Event` payloads directly. Arena now projects the engine's
setup events to every seat after `GameStart`, before the first action request,
so live history begins with `GameStarted` and includes `SetupDealt`.

Before returning an action, the policy canonicalizes the server-certified
legal list and requires exact equality with the search root action aggregates.
It fails closed on recipient/viewer mismatch, malformed information history,
invalid search configuration, or legal-set mismatch. The policy never accepts
`ReplayV1`, raw game seed, `RefereeEvent`, or `FullState`.
