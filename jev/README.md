# Jev-controlled Splendor agent (experimental)

Version **0.4.0**, policy **`facts-only-color-probabilities-v1`**, stdlib Python,
arena protocol **v0.5**. Jev sees structured game facts and legal choices, not
heuristic scores or recommendations. Jev chooses the legal action type; code
maps its five-color probabilities to a take and asks for an explicit overflow
return when required. No training, game-rule change, ranked match or League write.

The sole v0.4 live smoke finished **0–17 vs heuristic** (26 decisions; 52 API
attempts including one recovered connection error). This is a verified behavior
sample, **not evidence of competitive strength or a causal comparison against
B2**. B2 v0.3 and its 20-game evidence remain separate and frozen. `run_batch.py` is
an archived B2 harness and now refuses v0.4 before creating artifacts or
launching an arena, rather than mislabelling facts-only games as B2. See
[`docs/jev-arena-v1.md`](../docs/jev-arena-v1.md) for contracts and evidence.

## Build and test — no paid requests

From repository root (Python 3.10+, Rust toolchain):

```sh
cargo build -p splendor-cli --release
python -m unittest discover -s jev -p 'test_*.py' -v
cargo test -p splendor-cli -p splendor-agent
```

The Python suite uses fake inference/HTTP and short real **local** arena
rollouts. Arena/legacy sidecar tests skip if no release binary exists; build
first for full coverage, or set `JEV_TEST_BINARY`. Windows descendant cleanup is
tested on Windows. The canonical 90-card/10-noble snapshot is generated with
`python jev/build_catalog.py`; tests check source parity.

An optional offline mapping audit rebuilds all journalled roots in a replay
collection using the Rust `probe-legal` command, then supplies test-owned
responses to round-trip **every** certified action. It never calls TypeSafe or
plays new games. Existing output evidence is not overwritten:

```sh
python jev/check_facts_replays.py \
  --root local-artifacts/jev/roundB2-20260923 \
  --binary target/release/splendor.exe \
  --out local-artifacts/jev/new-mapping-audit.json
```

## Run — requires a new paid-call authorization

**The authorized v0.4 single game is complete. Do not rerun it or start a batch
without approval.** The runner below is an example of how to execute a newly
approved game, not authorization to do so.

Set `TYPESAFE_API_KEY` via the environment, or put the raw key in the
**git-ignored root** `TYPESAFE_API_KEY` file. Never paste it into argv, config,
state or logs. `TYPESAFE_API_KEY_FILE` optionally overrides the local credential
path. Verify `git check-ignore -v TYPESAFE_API_KEY` first; the current ignore
addition is owner-local and not included in these commits.

```sh
# PAID: only after budget approval; choose a NEW output directory.
python jev/match.py --seed 20260923 --jev-seat 0 --out-dir local-artifacts/jev/NEW-RUN
```

`--jev-seat 1` swaps seats. `--binary` selects a built binary; `--out-dir` must
not exist. `--max-plies` is an optional truncated smoke without a winner.
Defaults: `JEV_MAX_API_CALLS=100`, 45-second arena move deadline, one-hour runner
timeout. The call cap counts **all stages and retry attempts**, not only
successful responses. It is **not a token/dollar ceiling**.

## Facts and decision contract

- Only seat-scoped public/own-private information is projected: tiered market
  card costs, bonuses/VP, bank, player tokens/discounts/score, purchased counts,
  nobles, visible reserves, and the acting player's own reserved-card details.
  Opponent blind reserves, future deck order, seed and referee hashes are absent.
- Rules summarize payment/discounts, token/reserve limits, noble settlement,
  final rounds, ties and repository forced-pass termination. Reserving earns
  neither VP nor a permanent bonus immediately.
- **Family:** choose among legal `take_distinct`, `take_double`, `reserve`, `buy`.
  Noble/pass phases remain supported. Masks come from the engine-certified
  action list, including affordability of market and own-reserved purchases.
- **Taking:** ask one Choice over all five named colors. Local code ignores
  ineligible colors: distinct takes select the top `min(3, available)` colors;
  doubles select the highest-probability color that can legally supply two
  tokens (bank count at least 4). Gold is never a normal take choice. Probability
  ties use the declared order **white, blue, green, red, black**. All five
  probabilities must be finite, in `[0,1]`, and sum to 1 within `0.001`.
- Choice probabilities compare single colors; **top-k is an explicit policy
  simplification, not joint bundle utility or win probability**. The returned
  `choice` ID alone does not define the take; recorded probabilities and the
  eligible-color mask determine it.
- **Targets:** choose a legal market/reserved purchase, visible/blind reserve,
  or eligible noble. Target criteria identify cards in the structured state;
  blind card identity stays unknown.
- **Returns:** after selecting the gross take or reserve target, choose among
  its exact legal return vectors, including gold if legal. No arbitrary return
  tie-break or hidden heuristic chooses a color for the model.
- Singletons skip inference at each stage. Exact duplicate certified actions
  share one choice, but strategically different returns do not. Exact no-op
  takes are **not deleted**. There is no score-based cap, ranking or recommendation.
  Provider choices exceeding 255 fail closed rather than prune.
- Final output is an action from the original certified legal list. Invalid
  choices/probabilities or unmappable top-k results abort, never silently fall
  back to a heuristic.

The active policy does **not** invoke `agent-heuristic-terms`. That CLI and the
canonical Rust heuristic remain available for legacy/offline uses and opponents;
they are not part of Jev's input. Historical B2 tests/implementation are retained
in Git at `80514df` and the original local artifacts.

## Transport, failures and local evidence

All redirects are rejected, including same-origin redirects; only the fixed
`https://api.typesafe.ai/v1/systemone` endpoint receives Authorization. Default
TLS verification remains enabled. A killable Python HTTP worker enforces the
attempt wall timeout; all stages and backoff share one monotonic remaining-time
budget with an action-delivery margin. The arena remains the deadline enforcer.

At most **two attempts per non-forced stage**: retry 429/502/503/504/529 or a
connection error once, respecting numeric `Retry-After` and remaining time. Do
not retry authentication errors, redirects, invalid choices/probabilities, TLS
errors or ambiguous timeouts. Budget/deadline exhaustion and other failures
abort rather than fabricate a win/loss. A local timeout cannot guarantee
cancellation of server work/billing.

`match.py` creates a unique ignored `local-artifacts/jev/.../` directory:

| File | Meaning |
|---|---|
| `config.json`, `manifest.json` | Both seat commands, policy ID, color tie order, model/budget, source/catalog/opponent/binary/config SHA-256 identities. |
| `metrics.jsonl` | Flushed/fsynced request/decision lifecycle, exact safe payload snapshot/hash, compatible returned probabilities/confidence, latency and usage. `selection_path` separates model outputs from program color/target/return mapping and forced skips. |
| `metrics.json` | Schema 4 summary, per-stage call counts, partial usage and mode/target filtering accounting. `stage2_calls` means all non-family attempts for legacy compatibility; use `stage_calls` for detail. |
| `game-summary.json`, `runner-status.json` | Jev seat/result metadata and separate arena exit/interruption status. |
| `report.json`, `replay.json`, optional `prefix.json` | Authoritative arena evidence; completed replay verification or a truncation prefix without a winner. |
| `trace-summary.json` | Local per-ply journal projection for the read-only viewer. The consumer must check actor/observation/action against the replay; presence alone is not proof of a successful join. |

Known usage is only what responses actually report. `unknown_usage_attempts`
is **not zero billed tokens**. Graceful errors/cancellation finalize the
summary; a hard process kill may leave `status: running` and the last flushed
journal. Inspect runner status and unmatched request starts; do not infer
completion. The runner owns its process tree for timeout/cancellation.

Direct `agent.py` execution also creates ignored metrics unless
`JEV_METRICS_FILE` is supplied; programmatic `run()` may keep them in memory for
tests. Generated evidence contains own-private game information and remains
local-only. The shared interaction panel supports both legacy helper/family/move
stages and the new color/target/return/noble stages. Separate `/jev` round-ID
ambiguity and launcher integration work is not closed by this policy change.

## Model pinning and request-size guard

The model is pinned to **`jev-1.13.0`** by default (`JEV_MODEL` override). Every
successful response must report the expected identity (`JEV_EXPECTED_MODEL`);
a different **or missing** identity raises `model_identity_drift` and fails
closed. Manifests read the same values from the agent.

The B2 provider-size investigation found a shape-dependent boundary at 76,133 B
accepted / 76,134 B rejected. The unchanged local guard measures the actual
transport encoder and refuses payloads above **70,000 B** as
`request_payload_too_large`, before network access and without retry. This
transport guard is independent of policy; B2 evidence must not be relabelled as
facts-only evidence.

No League/registry/Elo writes, no M49A cohort usage, no competitive promotion.
Any further model call or controlled comparison requires new authorization.
