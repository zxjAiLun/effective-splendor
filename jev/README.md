# Jev-controlled Splendor agent (experimental)

Version **0.2.0**, stdlib Python, arena protocol **v0.5**. Two dependent Jev
`Choice` stages choose a move family, then one server-certified legal action in
that family. Nothing changes the game rules, trains a model, or books a league
match. The historical 16–6 win used an earlier prompt: **it does not validate this
version or establish Jev's independent contribution**. See
[`docs/jev-arena-v1.md`](../docs/jev-arena-v1.md) for evidence and attribution limits.

## Build and test — no paid requests

From repository root (Python 3.10+, Rust toolchain):

```sh
cargo build -p splendor-cli --release
python -m unittest discover -s jev -p 'test_*.py' -v
cargo test -p splendor-cli -p splendor-agent
```

The Python suite uses fake inference/HTTP and a short real **local** arena
rollout. Sidecar/arena tests skip if no release binary exists; build first for
full coverage, or set `JEV_TEST_BINARY`. Windows descendant cleanup is tested on
Windows. Regenerate the canonical 90-card/10-noble snapshot with
`python jev/build_catalog.py`; tests check source parity.

## Run — these commands make paid Jev requests

After approving the budget, set `TYPESAFE_API_KEY` via the environment, or put the
raw key in the **git-ignored root** `TYPESAFE_API_KEY` file. Never paste it into
argv/config/state/logs. `TYPESAFE_API_KEY_FILE` optionally overrides the local
credential path. Verify `git check-ignore -v TYPESAFE_API_KEY` first; the current
ignore addition is owner-local and has not been included in these commits.

```sh
python jev/match.py --seed 20260923 --jev-seat 0
# Also paid, but bounded/non-terminal (no winner):
python jev/match.py --seed 20260924 --max-plies 4
```

`--jev-seat 1` swaps seats. `--binary` selects a built binary, `--out-dir` a new
local-only output directory. Defaults: `JEV_MAX_API_CALLS=100`, 45-second arena
move deadline, one-hour runner timeout. The call cap counts **both stages and all
retry attempts**, not only successful responses. It is **not a token/dollar
ceiling**; use a smaller explicit cap when testing.

## Information and decision contract

- Only seat-scoped public/own-private information is projected. Named colors
  cover costs, bonuses, tokens and noble requirements. Opponents' **public**
  reserves are included; their blind reserves and future deck order are not.
- Rules summarize payment/discounts, token/reserve limits, noble settlement,
  final rounds, ties and repository forced-pass termination.
- `known_effects` separates immediate card VP/discount, potential reserved-card
  VP, and net tokens. Reserving gives **zero immediate VP**. Purchase-triggered
  noble VP is not fabricated; the engine settles it.
- `splendor agent-heuristic-terms` provides the unchanged canonical Rust
  `HeuristicTermScores`; Python does not reimplement weights. Advisory values
  are **not points, probabilities, exact game deltas, or training labels**.
- Stage 1 has a glossary and one leading example per family. Its scores and
  examples exclude `category_base` and the full prior-inclusive total. Stage 2
  retains the canonical decomposition as explicitly labeled advice.
- Exact no-op token takes are removed if alternatives exist. If the selected
  family has over 80 moves, keep the top 80 by canonical total (stable ties).
  This can remove a strong move; this is **not** a full-legal unbiased evaluator.
- A forced stage makes no request. Only an offered ID maps back to the original
  certified action. Invalid responses never cause a silent heuristic fallback.

## Transport, failures and local evidence

All redirects are rejected, including same-origin redirects; only the fixed
`https://api.typesafe.ai/v1/systemone` endpoint receives Authorization. Default
TLS verification remains enabled. A killable Python HTTP worker enforces the
attempt wall timeout; helper, both stages and backoff share one monotonic
remaining-time budget with an action-delivery margin. The arena is still the
ultimate deadline enforcer.

At most **two attempts per non-forced stage**: retry 429/502/503/504/529 or a
connection error once, respecting numeric `Retry-After` and remaining time. Do
not retry authentication errors, redirects, invalid choices, TLS errors or
ambiguous timeouts. Budget/deadline exhaustion and other failures abort rather
than fabricate a win/loss. A local timeout cannot guarantee cancellation of
server work/billing.

`match.py` creates a unique ignored `local-artifacts/jev/.../` directory:

| File | Meaning |
|---|---|
| `config.json`, `manifest.json` | Both seat commands, settings, source/catalog/helper/heuristic/binary/config SHA-256 identities and requested model. |
| `metrics.jsonl` | Append-only, flushed/fsynced request/decision lifecycle; candidate IDs/descriptions and index mapping, payload hash, selected IDs, latency, safe error code, returned model/usage and compatible reported probabilities/confidence. No raw HTTP error bodies or headers. |
| `metrics.json` | Atomically refreshed summary, including usage already received before a later failure; distinct `noops_removed`, `routed_out`, `cap_removed`. |
| `runner-status.json` | Arena exit/interruption status, separate from game result. |
| `report.json`, `replay.json`, optional `prefix.json` | Arena evidence; completed replay verification, or verified truncation prefix without a winner. |

Known token usage is only what responses actually report.
`unknown_usage_attempts` is **not zero billed tokens**. Graceful errors/cancellation
finalize the summary; a hard process kill may leave `status: running` and the
last flushed journal. Inspect runner status and unmatched request starts; do not
infer completion. The runner owns its process tree for timeout/cancellation.

Direct `agent.py` execution also creates ignored metrics unless
`JEV_METRICS_FILE` is supplied; programmatic `run()` may keep them in memory for
tests. Existing output paths are rejected. Generated evidence may contain own
private game information and remains local-only. `jev-latest` still floats:
recorded returned versions and hashes aid attribution, but do not pin the remote
model or make its choices reproducible.

No league/registry/Elo writes, no M49A cohort usage, no competitive promotion.
A paired, seat-swapped evaluation with/without heuristic advice requires a new
explicit budget/authorization.
