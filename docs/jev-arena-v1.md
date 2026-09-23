# Jev Arena Agent V1

- Status: IMPLEMENTED / VERIFIED (local unit tests, live API and two unrated completed arena smokes; NOT ACCEPTED or promoted)
- Baseline: `79c2ca0ba2dc8a36bc3d3b33d31f653d00846358` on `main` (2026-09-23); pre-existing owner `.gitignore` change protects `TYPESAFE_API_KEY` and is not owned by this round.
- Owner/date: owner request, 2026-09-23.

## Problem and evidence

Owner wants a Jev-controlled Splendor player and a head-to-head experiment. The existing arena sends a seat-scoped `observation` then `request_action` with certified `legal_actions` via `splendor-protocol` v0.5; `splendor run-match` runs subprocess agents and writes verified reports/replays. TypeSafe's live API reference (`https://docs.typesafe.ai/api.md`) specifies `POST https://api.typesafe.ai/v1/systemone`, Bearer auth, model `jev-latest`, and a Choice answer at `answers.<id>.choice`; Choice accepts up to 255 options (`https://docs.typesafe.ai/primitives/choice.md`). The linked jevbest page is a project gallery, not an API contract.

## Initial design (V1, single-stage; superseded by the follow-up below)

A Python stdlib-only `jev/agent.py` implements the existing NDJSON agent protocol. Each action decision sends a compact public+own-private snapshot and catalog-enriched legal action candidates to Jev in ONE Choice; code selects the certified action by returned option ID. For oversized legal sets, local deterministic candidate reduction is explicit and measured. No referee state, seed, full state, blind opponent cards, or future deck is provided. `jev/match.py` configures one unrated local arena match vs the existing heuristic. Keep generated config, reports, replays, and logs ignored in `local-artifacts/jev/`.

## Scope and non-goals

Scope includes the separate `jev/` agent/runner, a narrow read-only Rust CLI adapter for the repository's existing heuristic terms, tests, and documentation. No game-core/rules changes, model-weight changes, M49A experimental seed/cohort/Canonical changes, league/Elo/production registry changes, or training. A small live match is a connectivity/behavior smoke, NOT competitive acceptance or a promotion claim.

## Contracts and invariants

- Read API key from `TYPESAFE_API_KEY` environment variable, or from local ignored `TYPESAFE_API_KEY` file. Never put key in argv, config, model state, logs, documentation, or a tracked file; it is sent only as the required HTTPS Authorization header. Never echo response bodies on error.
- Only authenticated HTTPS TypeSafe endpoint; bounded request time and limited calls. Raise/fail closed on network, malformed Choice, non-candidate choice or protocol drift. No silent heuristic substitution; single legal action can be selected without an API call.
- Preserve `game_id`, `request_id`, protocol version, recipient and observation-hash correlation; output only protocol JSON to stdout. Match report is authoritative for results; abort is not a loss.
- Catalog snapshot is checked against source card/noble data by tests; only visible market/own reserved definitions supplied to Jev. Public state excludes opaque fingerprint, seed commitment and request metadata from model state.

## Implementation plan

1. Implement catalog snapshot generator + protocol client + Choice candidate mapper and mockable TypeSafe transport.
2. Unit-test action selection, private information, response rejection, framing, and catalog parity.
3. Real arena smoke and bounded live Jev vs heuristic match; inspect official report, replay and usage counters. Record exact commands/status, residual risks, then update handoff.

## Iteration log

- 2026-09-23: verified repo HEAD, local-only handoff and uncommitted `.gitignore` key ignore; read M49A §18 and respected its separate frozen training scope. API design from current live docs rather than guessing SDK shapes. No credential value entered the conversation.
- 2026-09-23 follow-up authorized by owner (“先做两段式决策以及标准术语，先看看效果”): baseline `6e6ac9c238d95300461bb2810442a23eb0e31dcd` (after unrelated M49A C3 recovery commits; worktree otherwise has only owner `.gitignore` edit). Stage 1 chooses an action family; stage 2 chooses one certified move in that family. “Standard terms” use the project's existing `HeuristicTermScores` decomposition from Rust, not a second Python reimplementation; named dimensions are advisory features, not truth labels. A same-seed complete game versus V1 was run; floating API alias/responses and the design change preclude causal or competitive claims.
- First two-stage live run succeeded: Jev seat 0 won 16–6 in 56 plies; replay verified. This is encouraging one-game evidence, not a strength estimate.
- Initial live match exposed repeated zero-net token takes: Jev seat 0 chose 23 take moves, some exact exchange no-ops, bought 7 cards versus heuristic's 20, and lost 2–16. Instead of calling this a model-only failure, we removed exact no-op takes from the Choice offer when alternatives exist (still allow forced singleton), instrumented actual response model version, added tests and reran the **same seed**. This modifies offered candidates and must be recorded as an iteration, not a comparable frozen ablation; remote `jev-latest` responses may also vary.

## Final implementation

- `jev/agent.py`: no third-party Python dependencies; protocol `hello`/`game_start`/`observation`/`request_action`/`pong`/`game_end`/`game_truncated`; request/hash/seat guards; public/own-private allowlist. Two dependent Choice stages: route among buy/take/reserve/noble/pass families, then select one certified action in the chosen family; deterministic no-op filtering and 80-action cap remain. Stage 2 receives standard Splendor action terms and exact existing Rust `HeuristicTermScores`. One-family and one-action cases skip unnecessary calls. HTTPS timeout 18 s, arena deadline 45 s, call cap 100 by default. No heuristic fallback.
- `crates/splendor-cli/src/agent_terms_command.rs` + `agent-heuristic-terms` CLI: narrow NDJSON sidecar accepts only `(Observation, legal_actions)` and returns the shared Rust heuristic decomposition aligned by index. Strict top-level schema, no seed/config/replay/referee input. The Python agent starts it once per decision; no Python score reimplementation or training-label interpretation.
- Standard action descriptions name Development Cards, Prestige Points (VP), permanent color Bonuses, Noble tiles, Gold Joker, token collection, unknown deck draw, and named-color costs/requirements. Heuristic terms are defined as weighted advisory values, not points/probabilities/truth.
- `jev/build_catalog.py` + `jev/catalog.json`: source-derived 90 cards / 10 nobles, unit-checked against Rust source. `jev/match.py` produces independent unrated config/report/replay/metrics under ignored `local-artifacts/jev/` and invokes `splendor verify-replay` for complete matches. `jev/README.md` documents setup, costs, and limitations. No game rules/league/production registry changes.

## Validation and evidence

Commands run from repo root (all exit **0**, unless noted):

- `python -m unittest discover -s jev -p 'test_*.py' -v`: 8 tests PASS (catalog parity, leakage allowlist, Choice mapping/rejection, option bounds/no-op, real protocol fixture, HTTP error redaction, credentials). `python -m compileall -q jev`: PASS.
- `cargo build -p splendor-cli --release`: initial V1 PASS (3 pre-existing warnings; this preceded the later read-only Rust terms adapter).
- Initial `python jev/match.py --seed 20260924 --max-plies 4`: **truncated** at 4 plies (no winner), 2 API calls. `local-artifacts/jev/1790154430-seat0/`.
- Initial `python jev/match.py --seed 20260923 --jev-seat 0`: arena exit 0, `verify-replay` exit 0, **completed** 66 plies; Jev 2 : heuristic 16, winner seat 1. 33 API calls, 260,268 input/18,092 output tokens; 871 legal options omitted across decisions (not necessarily distinct). `local-artifacts/jev/1790154461-seat0/`; report SHA256 `32ef40f0534d350a6253c89fed8597cbcff1a8616eea43e91a3f4f35e1a85fcc`, replay SHA256 `13a1b6c6ff40d99e68caf1ca97d8eb7cb2315a4f431abb5a6b73c418cb49cf3d`.
- After no-op reduction, `python jev/match.py --seed 20260925 --max-plies 2`: truncated/no winner; 1 real API call; reported model `jev-1.13.0`. `local-artifacts/jev/1790154608-seat0/`.
- Final `JEV_MAX_API_CALLS=60 python jev/match.py --seed 20260923 --jev-seat 0` (environment equivalent on Windows): arena exit 0, `verify-replay` exit 0; **completed** 64 plies; Jev seat 0 4 : heuristic seat 1 15, winner seat 1. Jev 32 decisions, 32 API calls, 20 takes/6 market buys/2 reserved buys/3 visible reserves/1 blind reserve; heuristic 22 market buys. Exact no-op takes 0. Offered 1,671 options and omitted 1,029 across 32 decisions; 226,424 input/15,310 output tokens; `jev-latest` resolved `jev-1.13.0`. `local-artifacts/jev/1790154627-seat0/metrics.json`, `report.json` SHA256 `f56767f8fbc70d08aa997c14c3eae73229514b868cf95e309238cefd03fff575`, `replay.json` SHA256 `cadc252b985668eb21fef6af0895b23c4979aa0e4714620d26f34604e1b0d114`; report replay-final-state hash binds and replay verified.
- `python jev/match.py --seed 20260923 --jev-seat 0` (default `JEV_MAX_API_CALLS=100`): complete two-stage game, arena exit 0, `verify-replay` exit 0; **Jev seat 0 16 : heuristic seat 1 6**, 56 plies, prestige-threshold termination. Jev 28 decisions; stage1 calls 28, stage2 calls 22 (6 selected families forced a single move); total 50 remote calls, `jev-latest` resolved to `jev-1.13.0`. Action counts: Jev 18 market buys + 1 reserved buy, 7 takes, 2 reserves; heuristic 18 buys, 10 takes. Final metrics: 75 family candidates summarized, 157 exact actions offered at stage 2, 573 legal actions omitted from exact stage-2 Choice across turns; 171,906 input / 2,658 output tokens. Artifacts: `local-artifacts/jev/1790162927-seat0/`; report SHA256 `b30bf1ceb37af9500211cfc7dc651d5e1017afb279b4acee268dc3bcf5c3b9a4`, replay SHA256 `c0a4e6298de8623de21aa9d77ad8b75521fc2c46844e0341bb08cb7eac538e56`, metrics SHA256 `a1815d34acd112a0e92afc3d53a3de6bf4d7a21f8f8f988832a744ce043a20a6`; report final replay hash bound and verify passed.
- Same-seed V1 result remains recorded above: Jev 4–15, 64 plies; V1 before no-op removal was 2–16, 66 plies. V2 two-stage won this single run, with substantially more buys (19 vs 8 in same-seed V1 final); only one changed-run pair, `jev-latest` output is not frozen, and both factors differ. **No causal claim / no strength estimate.**
- `python -m unittest discover -s jev -p 'test_*.py' -v`: 9/9 pass, including stage routing, exact legal mapping, glossary/term shape, fail-closed responses, protocol, leakage and API error redaction. `python -m compileall -q jev`: pass.
- `cargo test -p splendor-cli`: exit 0; new helper unit tests 2/2 pass, package suites all passed (one existing ignored test). `cargo build -p splendor-cli --release`: exit 0 (3 pre-existing warnings). `rustfmt --edition 2021 --check crates/splendor-cli/src/agent_terms_command.rs`: pass. Direct Python-to-built-Rust sidecar call returns 30 exactly aligned term objects.
- `cargo fmt --all -- --check` exit 1 on pre-existing formatting differences outside this round, including `crates/splendor-learning/src/representation.rs`; scoped formatting for the new Rust helper passes. `git diff --check` PASS; `git check-ignore -v handoff.md TYPESAFE_API_KEY local-artifacts/jev/1790162927-seat0/report.json` confirms local-only files ignored. `.gitignore` owner-owned uncommitted change was not staged.

## Result and decision

**Two-stage integration IMPLEMENTED / VERIFIED locally.** First game won 16–6; this is an encouraging single unrated sample, NOT evidence of strategic superiority. Earlier V1 same-seed sample was 4–15; candidate set, stages, and API calls changed, with no frozen model responses or repeated paired games. NOT PROMOTED; no rated games booked; M49A C3 and Canonical 64 remain untouched.

## Known limitations

Jev is not trained for Splendor; typed output and Choice confidence do not imply strategic correctness. In final run, 28 decisions used 50 calls (28 family / 22 specific action) and 174,564 total usage tokens; six family routes needed no second-stage request. Two-stage latency/cost, model alias, and API response nondeterminism remain. The explicit legal move cap/filter means 573 exact actions were not offered in this sample; stage 1 did see family counts and one heuristic-leading example. No seat swap, multiple seeds, saved per-choice distributions, latency measurements, or calibrated analysis. Secret protection relies on local `.gitignore` owner change; verify ignore if checking out another revision.

## Next authorized gate

Stop after this requested same-seed smoke. If owner wants competitive assessment, separately design fixed-budget paired seat-swapped evaluation with cost/latency and candidate-coverage gates; do not repurpose M49A Canonical 64 or book Elo by default.
