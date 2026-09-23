# Jev-controlled Splendor agent (experimental)

`agent.py` speaks the repo's **stdio arena protocol v0.5**; game rules are unchanged and nothing books a league match. Each move uses up to two dependent Jev (`jev-latest`) `Choice` calls: stage 1 routes among action families (buy/take/reserve/noble/pass), stage 2 selects one certified legal move within that family. A local Rust sidecar returns the exact existing `HeuristicTermScores` vector for those legal moves; Jev sees those named values and canonical Splendor action terminology as advisory features, never as ground truth. The agent enriches choices with the project's public/own-private catalog and never executes arbitrary model text. The exact Rust heuristic terms are `category_base`, `prestige`, `noble_gain`, `noble_direct`, `bonus_usefulness`, `cost_efficiency`, `deficit_reduction`, `new_target`, `return_penalty`, `gold_value`, `reserve_proximity`, `reserve_gold`, and `reserve_blind_gold`; values are weighted terms, not points/probabilities. The narrow local `splendor agent-heuristic-terms` sidecar handles the source-of-truth calculation. The local catalog snapshot can be regenerated with `python jev/build_catalog.py`, and its parity with the canonical Rust tables is unit-tested.

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

Exact no-op token exchanges are removed if alternatives exist. Stage 1 gets family counts and one existing-heuristic-leading example per family; its fixed `category_base` is excluded from the cross-family comparison summary. Stage 2 receives the selected family's moves and named term decomposition. If that family still has >80 moves, cap by canonical heuristic total. Jev sees **only the offered exact candidates** (family summaries do not expose all exact actions); metrics count excluded moves. This may remove the strategically best move and is not an unbiased full-legal evaluator. No API request for a singleton action. Each non-forced stage makes one bounded HTTPS request (18-second client timeout; 45-second arena deadline); the dependent two-stage path can use two paid requests per move. The API-call budget counts both. HTTP failures, invalid response/move, depleted call budget, or protocol mismatch **abort** the match; no secret-bearing diagnostic and no covert heuristic fallback. An aborted match has no winner. `jev-latest` floats to new model versions; metrics report use, not reproducibility across versions. A small match is a behavior smoke, not proof of strength or a formal competitive gate.
