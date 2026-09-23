# Jev-controlled Splendor agent (experimental)

`agent.py` speaks the repo's **stdio arena protocol v0.5**; no Rust/game engine changes or league booking. Each move presents Jev (`jev-latest`) with a `Choice` among certified legal moves, enriched with the project's public/own-private catalog; it never executes arbitrary model text. The local catalog snapshot can be regenerated with `python jev/build_catalog.py`, and its parity with the canonical Rust tables is unit-tested.

## Run

From repository root (Python 3.10+, standard library only):

```sh
python -m unittest discover -s jev -p 'test_*.py'
cargo build -p splendor-cli --release
python jev/match.py --seed 20260923 --jev-seat 0
# bounded, NON-terminal smoke (no winner):
python jev/match.py --seed 20260924 --max-plies 4
```

Set `TYPESAFE_API_KEY` in the environment, or put the raw key in the **git-ignored root** `TYPESAFE_API_KEY` file (the script reads that path by default; do not pass the secret as an argument). Keep `.gitignore` protection in place; verify `git check-ignore -v TYPESAFE_API_KEY`. Never paste this credential into a config or a shell command line. `JEV_MAX_API_CALLS` (default 100) caps paid calls per game; `TYPESAFE_API_KEY_FILE` can override the credential path. Only the TypeSafe HTTPS API receives the key.

`match.py` creates a fresh `local-artifacts/jev/<timestamp>-seat.../` directory containing config, report and replay (when completed), optional truncation prefix, agent usage `metrics.json`, and optional arena diagnostics. The arena's own `verify-replay` checks completed matches. Default opponent is the built-in heuristic; `--jev-seat 1` swaps seats. This is a one-off, **unrated** match: no Studio League API/registry access, no Elo, and no M49A seed/cohort consumption.

## Decision and failure policy

Exact no-op token exchanges are removed if alternatives exist. When >80 remaining certified moves exist, a deterministic rules-only reducer prioritizes nobles/buys, then reserves with minimal returns, then high-yield/low-return takes. Jev sees **only the offered candidates**; metrics count excluded legal actions. This may remove the strategically best move and is not an unbiased full-legal evaluator. No API request for a singleton action. Every other turn makes one bounded HTTPS request (18-second client timeout; 45-second arena deadline). HTTP failures, invalid response/move, depleted call budget, or protocol mismatch **abort** the match; no secret-bearing diagnostic and no covert heuristic fallback. An aborted match has no winner. `jev-latest` floats to new model versions; metrics report use, not reproducibility across versions. A small match is a behavior smoke, not proof of strength or a formal competitive gate.
