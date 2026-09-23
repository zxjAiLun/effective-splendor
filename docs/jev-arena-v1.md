# Jev Arena Agent V1

- Status: IMPLEMENTED / VERIFIED (local unit tests, live API and two unrated completed arena smokes; NOT ACCEPTED or promoted)
- Baseline: `79c2ca0ba2dc8a36bc3d3b33d31f653d00846358` on `main` (2026-09-23); pre-existing owner `.gitignore` change protects `TYPESAFE_API_KEY` and is not owned by this round.
- Owner/date: owner request, 2026-09-23.

## Problem and evidence

Owner wants a Jev-controlled Splendor player and a head-to-head experiment. The existing arena sends a seat-scoped `observation` then `request_action` with certified `legal_actions` via `splendor-protocol` v0.5; `splendor run-match` runs subprocess agents and writes verified reports/replays. TypeSafe's live API reference (`https://docs.typesafe.ai/api.md`) specifies `POST https://api.typesafe.ai/v1/systemone`, Bearer auth, model `jev-latest`, and a Choice answer at `answers.<id>.choice`; Choice accepts up to 255 options (`https://docs.typesafe.ai/primitives/choice.md`). The linked jevbest page is a project gallery, not an API contract.

## Initial design

A Python stdlib-only `jev/agent.py` implements the existing NDJSON agent protocol. Each action decision sends a compact public+own-private snapshot and catalog-enriched legal action candidates to Jev in ONE Choice; code selects the certified action by returned option ID. For oversized legal sets, local deterministic candidate reduction is explicit and measured. No referee state, seed, full state, blind opponent cards, or future deck is provided. `jev/match.py` configures one unrated local arena match vs the existing heuristic. Keep generated config, reports, replays, and logs ignored in `local-artifacts/jev/`.

## Scope and non-goals

Only a separate `jev/` agent and runner, own tests, and documentation. No changes to Rust core, existing model weights, M49A experimental seed sets/Canonical gate, league/Elo/production registry, or training. A small live match is a connectivity/behavior smoke, NOT competitive acceptance or a promotion claim.

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
- Initial live match exposed repeated zero-net token takes: Jev seat 0 chose 23 take moves, some exact exchange no-ops, bought 7 cards versus heuristic's 20, and lost 2–16. Instead of calling this a model-only failure, we removed exact no-op takes from the Choice offer when alternatives exist (still allow forced singleton), instrumented actual response model version, added tests and reran the **same seed**. This modifies offered candidates and must be recorded as an iteration, not a comparable frozen ablation; remote `jev-latest` responses may also vary.

## Final implementation

- `jev/agent.py`: no third-party Python dependencies; protocol `hello`/`game_start`/`observation`/`request_action`/`pong`/`game_end`/`game_truncated`; request/hash/seat guards; public/own-private allowlist; one Jev Choice per non-singleton turn with exact action mapping. Bounded 80-option reduction: filter exact token no-ops, preserve nobles and buys preferentially, then reserves, then token takes. HTTPS timeout 18 s, arena deadline 45 s, API-call cap 100 by default (60 for final match). No heuristic fallback.
- `jev/build_catalog.py` + `jev/catalog.json`: source-derived 90 cards / 10 nobles, unit-checked against Rust source. `jev/match.py` produces independent unrated config/report/replay/metrics under ignored `local-artifacts/jev/` and invokes `splendor verify-replay` for complete matches. `jev/README.md` documents setup, costs, and limitations. Existing Rust crates/league/production unaffected.

## Validation and evidence

Commands run from repo root (all exit **0**, unless noted):

- `python -m unittest discover -s jev -p 'test_*.py' -v`: 8 tests PASS (catalog parity, leakage allowlist, Choice mapping/rejection, option bounds/no-op, real protocol fixture, HTTP error redaction, credentials). `python -m compileall -q jev`: PASS.
- `cargo build -p splendor-cli --release`: PASS (3 pre-existing warnings, no Rust edits).
- Initial `python jev/match.py --seed 20260924 --max-plies 4`: **truncated** at 4 plies (no winner), 2 API calls. `local-artifacts/jev/1790154430-seat0/`.
- Initial `python jev/match.py --seed 20260923 --jev-seat 0`: arena exit 0, `verify-replay` exit 0, **completed** 66 plies; Jev 2 : heuristic 16, winner seat 1. 33 API calls, 260,268 input/18,092 output tokens; 871 legal options omitted across decisions (not necessarily distinct). `local-artifacts/jev/1790154461-seat0/`; report SHA256 `32ef40f0534d350a6253c89fed8597cbcff1a8616eea43e91a3f4f35e1a85fcc`, replay SHA256 `13a1b6c6ff40d99e68caf1ca97d8eb7cb2315a4f431abb5a6b73c418cb49cf3d`.
- After no-op reduction, `python jev/match.py --seed 20260925 --max-plies 2`: truncated/no winner; 1 real API call; reported model `jev-1.13.0`. `local-artifacts/jev/1790154608-seat0/`.
- Final `JEV_MAX_API_CALLS=60 python jev/match.py --seed 20260923 --jev-seat 0` (environment equivalent on Windows): arena exit 0, `verify-replay` exit 0; **completed** 64 plies; Jev seat 0 4 : heuristic seat 1 15, winner seat 1. Jev 32 decisions, 32 API calls, 20 takes/6 market buys/2 reserved buys/3 visible reserves/1 blind reserve; heuristic 22 market buys. Exact no-op takes 0. Offered 1,671 options and omitted 1,029 across 32 decisions; 226,424 input/15,310 output tokens; `jev-latest` resolved `jev-1.13.0`. `local-artifacts/jev/1790154627-seat0/metrics.json`, `report.json` SHA256 `f56767f8fbc70d08aa997c14c3eae73229514b868cf95e309238cefd03fff575`, `replay.json` SHA256 `cadc252b985668eb21fef6af0895b23c4979aa0e4714620d26f34604e1b0d114`; report replay-final-state hash binds and replay verified.
- `git diff --check` PASS; `git check-ignore -v handoff.md TYPESAFE_API_KEY local-artifacts/jev/1790154627-seat0/report.json` confirms all three are ignored in the working tree. `.gitignore` pre-existing uncommitted owner change is not included in implementation changes.

## Result and decision

**Working integration; poor performance in this one match (Jev 4–15). NOT PROMOTED.** Smoke shows real Jev controlled legal moves in a complete replay, not strength. First match 2–16 and revised match 4–15 share a seed but differ in request options; not a statistical improvement claim. No rated games booked; M49A C3 and Canonical 64 remain untouched.

## Known limitations

Jev is not trained for Splendor; typed output and Choice confidence do not imply strategic correctness. The deterministic prefilter excludes legal actions (1,029 aggregate exclusions in final match), so Jev did not evaluate every option. No paired seat-swap, multiple seeds, recorded per-action probabilities, request timings, or calibrated strategy analysis. One complete match consumes ~242k billed/usage tokens (input+output); consider budget before scaling. Secret protection relies on local `.gitignore` owner change; if checking out a different revision, verify ignore before working with key file. API model alias is floating, even though final response reports `jev-1.13.0`.

## Next authorized gate

Stop after the unrated smoke. If owner wants competitive assessment, separately design a fixed-budget, paired seat-swapped evaluation with cost/latency and candidate-coverage gates; do not repurpose M49A Canonical 64 or book Elo by default.
