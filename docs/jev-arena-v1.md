# Jev Arena Agent V1

- Status: v0.2.0 hardening IMPLEMENTED / VERIFIED offline (2026-09-23, baseline `b7864e3`); parent review and earlier live smokes retained below. NOT competitively ACCEPTED or promoted. Latest closeout: **Hardening implementation and offline verification**.
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

## Final implementation (historical two-stage version; hardening closeout below)

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

## Known limitations (historical snapshot; interpretation corrected in parent review below)

Jev is not trained for Splendor; typed output and Choice confidence do not imply strategic correctness. In final run, 28 decisions used 50 calls (28 family / 22 specific action) and 174,564 total usage tokens; six family routes needed no second-stage request. Two-stage latency/cost, model alias, and API response nondeterminism remain. The explicit legal move cap/filter means 573 exact actions were not offered in this sample; stage 1 did see family counts and one heuristic-leading example. No seat swap, multiple seeds, saved per-choice distributions, latency measurements, or calibrated analysis. Secret protection relies on local `.gitignore` owner change; verify ignore if checking out another revision.

## Next authorized gate (historical smoke closeout; superseded by hardening authorization below)

Stop after this requested same-seed smoke. If owner wants competitive assessment, separately design fixed-budget paired seat-swapped evaluation with cost/latency and candidate-coverage gates; do not repurpose M49A Canonical 64 or book Elo by default.

## Authorized hardening slice — 2026-09-23 (baseline `b7864e3`)

Owner approved the preceding review's proposed next slice (“修改吧”). Scope: correct game input/term semantics, preserve failed/partial call evidence, prohibit redirects, bound both stages/helper/retries by the server deadline, and repair helper/test boundaries. No heuristic-weight tuning, new decision stages, model training, paid matches, or league writes. Keep old experimental results as historical evidence, not validation of the new prompts.

Plan and gates (fixed before implementation):
1. Name public colors/reserves, distinguish immediate card VP from reserved-card future VP, and remove fixed family prior/total from stage-1 advice. Keep canonical heuristic calculations unchanged.
2. Append-only flushed request/decision journal + atomic summary, retaining stage-1 usage on stage-2 failure and explicit abort/cancel status. Journal metadata/option mapping only, no keys/auth headers/error bodies. Separate no-op/cap/routing exclusions.
3. Fixed HTTPS endpoint, no redirects; max two attempts per stage for transient service errors, every attempt charged to a fixed call budget. Monotonic per-decision deadline covers helper + stages + backoff, with safety margin. A separately killable stdlib HTTP worker enforces wall-clock timeout (socket timeout alone is insufficient); credentials stay in env/file, never argv/payload.
4. Validate helper indices/viewer/catalog references and bound input before the unchanged heuristic function. Add focused semantic, lifecycle, transport, deadline/retry, partial-usage and real-sidecar/arena tests with fake network, no paid calls.
5. Run targeted regressions/build/publication checks and record exact results and remaining limitations here. Broader model attribution/evaluation stays deferred pending a new owner gate.

Implementation/results: **IMPLEMENTED / VERIFIED offline**; detailed closeout follows the preserved historical review below. No paid inference was run for this slice.

## Parent integration review — 2026-09-23

Historical pre-fix review; findings below describe `de709ae`, not v0.2.0. The later authorization and hardening closeout supersede the old OPEN/next-step status, not the observed evidence.

### Scope and evidence

Owner asked what still needs improvement. This is a direct-parent code review of `de709aea44750b857f706be32c5243cf08fa5b6b`, **not an independent review**, a new implementation, or a new competitive run. Only this record and local ignored handoff/evidence changed. No paid request, live HTTP request, training, or league operation occurred. The pre-existing owner `.gitignore` change remains untouched.

Offline reproducer: `python local-artifacts/jev/review-de709ae/review.py` (exit 0). It re-verifies the retained 16–6 replay, rebuilds its 28 Jev decision roots with `splendor probe-legal --source-replay ... --branch-ply <ply> --emit-observation`, supplies only Observation/legal_actions to the local heuristic adapter, and reconstructs the current offers. Full-state probe metadata remains confined to offline analysis; it is never sent to a model. Output `local-artifacts/jev/review-de709ae/review.json`, SHA256 `aefe6c3c5c8642f0ece6309a885e5c068a30b0be90e6b73114dc9ceed129f425`, binds the actual release binary, replay, report, agent source and heuristic source hashes. Nine Python tests pass; `cargo test -p splendor-cli --bin splendor agent_terms_command::tests` exit 0, 2/2 pass (`rust-helper-tests.log`). These passing tests do not close the gaps below.

### Important interpretation corrections (supersede broader earlier wording)

- **573 was routing exclusion, not an 80-cap loss.** Reconstructed totals exactly match the historical metrics: 730 legal action occurrences, 157 stage-2 candidates, 573 actions in non-selected families. Exact no-op removals **0**, cap removals **0**. The current `options_omitted = len(legal) - offered` combines distinct reasons; do not infer that the cap or a score shortlist caused this sample's omissions.
- **The result does not isolate Jev's contribution.** All 28 executed actions are in the existing heuristic's maximum-score set within their chosen family; 26/28 are also in the global maximum-score set. The exceptions are the two reserves at plies 4 and 12. This is *argmax-set agreement*, not proof of copying or identical tie-breaking. The 22 non-forced second-stage calls have not demonstrated a different choice from the family heuristic argmax set on this replay. Earlier integration combined two-stage routing, game terminology, heuristic advice and candidate changes, rather than testing two-stage routing or terminology alone.
- We have no evidence of the external model's training-set contents: earlier blanket statements that “Jev is not trained for Splendor” should instead be read as “this repository has not fine-tuned Jev for Splendor; domain competence is unestablished.” The win remains valid, but its cause and generality are unknown.

### Findings and recommended order

**R1 — P1 before wider use: success-only telemetry loses paid-work evidence on failure.** `jev/agent.py:304–313, 380–389` increments call counters before requests, but writes `metrics.json` only after clean terminal return; usage is aggregated only after both stages complete. The executable offline HTTP stub returned stage-1 success (100 input/10 output tokens), then stage-2 HTTP 429. Actual `__main__` exited 1, no action was sent, sanitized error was correct, but **no metrics file existed**. The existing error test checks redaction, not retained diagnosis. Add a flushed local per-request/per-decision journal and atomic final summary on success/error/cancellation; record stage/status/latency/usage/model/candidate IDs/selected ID and safe error code, never Authorization or raw error bodies. Preserve partial stage-1 usage if stage 2 fails.

**R2 — P1, conditional credential boundary: default redirects can carry Authorization away from TypeSafe.** `jev/agent.py:217–234` uses default `urllib.request.urlopen`. A zero-network test passed a dummy-key POST to `HTTPRedirectHandler.redirect_request` with HTTP 302 to `http://example.invalid/redirect-test`; the resulting cross-origin, HTTPS→HTTP GET **retained Authorization**. No real key was used and there is no evidence of any production redirect or disclosure. Disallow redirects for this fixed API endpoint, or enforce same-origin HTTPS with deliberate header handling. Keep default TLS verification. Protect both the success and redirect paths with transport-level tests; this is not covered by payload-only key tests.

**R3 — P1 semantic correction: advisory terms are not uniformly described.** `TERM_GLOSSARY['prestige']` says immediate prestige gain, but the canonical heuristic sets reserve-visible `prestige = 1500 * reserved_card.prestige`. On the real opening fixture, reserving tier One slot 2 yields term 1500 while actual immediate VP gain is **0**. The glossary must distinguish weighted heuristic preference, future reserved-card value, and immediate game effects. Also, stage 1 does not receive `TERM_GLOSSARY`; it excludes `category_base` from one comparison scalar but reintroduces it and the full sum via `_term_view` in `best_move_heuristic_terms`. If the intent is to remove that prior, remove it from the payload, not just a single field. Prefer exact observable mechanics (`immediate_vp`, permanent discount change, net tokens, affordability/deficit) with explicit units; keep optional heuristic advice in a separately named channel. Do not quietly replace the score helper's historical semantics or claim those weights are exact game deltas.

**R4 — P2 information/presentation: the model receives less public context than the existing Observation.** `public_state` drops opponents' `public_reserved` card identities (which are legitimately visible); the DTO sensitivity probe confirms changing that list alone leaves the payload identical. `bonuses` and board noble `requirements` are still unnamed arrays, whereas only card costs and a choose-noble action description gain color maps. Missing public-reserve identities particularly weaken the claimed opponent-threat reasoning. Supply named-color bonuses/noble requirements, visible opponent reserves and a concise complete rule contract (payment/discounts, reservation/token limits, final round, ties), without exposing blind reserves or future deck order. The sensitivity test is a DTO projection check, not a claim that both mutated DTOs are reachable game histories.

**R5 — P2 operational reliability: deadlines, retries and version identity are incomplete.** `request_action.deadline_ms` is not used; the helper timeout and two independent 18-second socket timeouts are not an absolute decision deadline. HTTP 429/529/transient transport failures currently abort immediately. Implement a shared monotonic remaining-time budget, safety margin and bounded retry only for retryable service failures, counting every attempt against request/token budgets; do not convert auth/invalid-choice errors into a heuristic win/loss or retry indefinitely. The runner's 3600-second timeout kills the arena process via `subprocess.run`, but does not explicitly own descendant cleanup; test controlled cancellation before background scaling. `jev-latest` is floating; only the final response's model string is retained, while single-stage and two-stage agents both declare version `0.1.0`. Bind an experiment manifest to agent/prompt/candidate-rule/catalog/binary hashes, exact requested and returned models, budgets and both seat commands. Add latency and token measurements before deciding whether a persistent helper is worthwhile.

**R6 — P2 local-helper and test gaps.** The helper trusts typed input as semantically valid and may panic: a valid opening Observation with `buy_market` slot 255 produces **exit 101/panic**, not the advertised classified error. The trusted arena normally supplies valid indices and Python converts nonzero exit to failure; this is not an observed illegal game or remote-service exploit. Add structural index/viewer/card validation and bounded reads rather than using panic as input validation. Existing Rust unknown-field test already fails with `observation: {}` even after `seed` is removed, so that test does not prove its named boundary (a valid fixture + extra seed really is rejected in the offline check). Python tests use all-zero heuristic mocks and a synthetic unaffordable buy labeled as certified; retain these as routing tests, but add real sidecar subprocess/arena boundary cases, one-family/multi-action, selected singleton, >80 family coverage, reserve-vs-buy semantics, timeout/error telemetry and redirect controls.

### Decision and next gate

Review complete; findings are **OPEN recommendations**, not implementation authorizations or fixed claims. First repair error evidence/redirect handling and the misleading state/term semantics. Then freeze the integration and measure attribution: e.g. named game mechanics with/without heuristic advice under the same two-stage structure, plus the existing heuristic baseline. A bounded predetermined seed set with both seats and recorded cost/latency would test generality; a larger study is not authorized by this review. Do not add more strategic prompt tuning, increase paid volume, or call the 16–6 result proof of Jev strength before these distinctions are measurable. No external-model training or M49A gates are reopened.

## Hardening implementation and offline verification — 2026-09-23

### Scope, baseline and final implementation

Owner authorized the fixed repair plan above against `main@b7864e3e533c180789611520e24629842a275b40`. This is a **parent implementation/self-check, not independent review**. Agent version is now **0.2.0**. No new TypeSafe inference request, paid match, training experiment, M49A/Canonical evaluation, league operation or heuristic-weight change occurred. Public TypeSafe documentation was consulted for the 429/529 backoff recommendation; that read is not inference. The historical win remains a valid result of the old version only.

- **R1 (failure evidence):** new `jev/runtime.py` owns a flushed/fsynced JSONL lifecycle journal and atomic summary. Attempts, stage, latency, requested/returned models, payload hash, option mapping, selected ID, compatible reported probabilities/confidence and immediately received usage survive later failure. Invalid choices/errors cannot inject arbitrary remote strings into logs. Unknown usage is explicit, never assumed free. Normal failure/cancellation closes status; a hard kill may retain the last `running` snapshot plus journal.
- **R2 (redirect boundary):** new `jev/transport.py` uses the fixed HTTPS URL, rejects *all* redirects, retains default certificate verification and bounds response bytes. Credentials remain env/file-only and are used only in the HTTPS Authorization header. HTTP bodies/reasons/headers and dependency exception text are not logged. A real urllib handler-chain test with a fake HTTPS response proves no second request is sent after a cross-origin HTTP redirect.
- **R3/R4 (semantics/public context):** `known_effects` separates immediate purchase VP/bonus from future reserved-card VP and net token changes. Reserving explicitly gives zero immediate VP; purchase-triggered noble settlement is not guessed. `public_state` deep-projects named-color bonuses/costs/requirements/tokens, visible opponent reserves, own reserves, and concise verified base-game rules (including final round/ties/forced-pass termination). Stage 1 includes definitions and excludes both `category_base` and prior-inclusive total, including in its example. Stage 2 still supplies unchanged canonical weighted advice. This is a prompt behavior change, not merely a cosmetic rename.
- **R5 (bounded runtime/identity):** one monotonic server-deadline budget covers helper, both stages and backoff; a safety margin reserves delivery time. The HTTP worker is a separately killable/reaped process (socket timeouts alone are insufficient). At most two attempts per stage for 429/502/503/504/529 or connection errors; every attempt consumes the shared call cap. No retry for auth/redirect/invalid-choice/TLS errors or ambiguous timeouts, including `URLError`-wrapped socket timeouts. The runner owns its process group/tree, records interruption separately, and writes a manifest binding source/catalog/helper/heuristic/binary/config hashes, settings and both commands. Version/model histories are retained, not only the last response string. Source manifest keys use portable `/` separators.
- **R6 (helper/tests):** bound helper input to 2 MB and validate viewer/player/catalog references, slots, noble choices and small-count arithmetic before canonical scoring. This is structural validation, not a second game-legality implementation. The unknown-field Rust test now starts with a valid request. New tests cover real sidecar success/rejection, synthetic routing/caps explicitly labeled as such, real arena framing with fake inference, and error/cancel/timeout paths.

### Material iterations and failed attempts

1. Migrating transport/term-provider injection to accept the remaining `timeout=` caused three legacy tests to fail until their stubs/mock targets were migrated; six other legacy tests initially passed. The transport moved out of `agent.py`; no live service was used to debug this.
2. A new stage-1 test initially rejected the substring `heuristic_total` even inside the deliberately allowed `...total_excluding_family_prior` key. Corrected the assertion to reject the exact full-total key; the gate still requires no `category_base` or prior-inclusive total anywhere in stage 1.
3. A manifest test exposed Windows `\\` versus portable `/` source keys. Fixed implementation normalization, not the expected contract. The initial failed run is preserved in `local-artifacts/jev/hardening-b7864e3/python-initial-path-failure.log` and `checks-initial.json`.
4. Final self-check identified wrapped socket/TLS errors that would otherwise be treated as retryable connections; classification and focused tests now distinguish them. Added a real Windows spawned-descendant timeout test, not just a mocked process-cleanup assertion.

### Exact validation and evidence

All commands below ran in the repository root and exited **0** on the final validated source:

| Command | Evidence |
|---|---|
| `cargo build -p splendor-cli --release` | Built release binary used by Python integration gates. Existing unrelated warnings remain. |
| `python -m unittest discover -s jev -p 'test_*.py' -v` | **30 passed, zero skipped on this Windows host**. Includes real helper, worker IPC/deadline, urllib redirect chain, runner manifest, and Windows descendant cleanup. |
| `cargo test -p splendor-cli -p splendor-agent` | **360 passed, 3 existing explicit benchmarks ignored**, zero failures. Helper module's 3 unit tests pass. Ignored M05 strength, M06 fixed-search and M07 reproducibility benchmarks were not run. |
| `python -m compileall -q jev` | PASS. |
| `rustfmt --edition 2021 --check crates/splendor-cli/src/agent_terms_command.rs` | PASS. No whole-repository formatting cleanup; earlier unrelated fmt failure remains historical. |
| `git diff --check` | PASS, repeated after documentation closeout. |

Specific observed gates:
- Stage 1 reports 100 input / 10 output tokens; stage 2 gets two fake 429s. Final summary is `failed`, attempts **3**, retained input **100**, unknown-usage attempts **2**, no action emitted.
- An injected 529 retries once then completes; both returned model versions are retained. Auth/redirect/invalid-choice and timeout/TLS paths do not retry. A one-attempt cap is not exceeded by retry logic.
- Shared-deadline fixture charges helper and both stages, retains usage from a late reply, but emits no late action. Backoff longer than remaining time starts no further attempt. HTTP worker wall timeout kills/reaps the real local child.
- Real built helper rejects a valid-observation request with slot **255**, viewer **255**, overflowing bonus counts, unknown top-level seed or oversized input with **exit 1**, no panic or score output.
- Real `splendor run-rollout --max-plies 4` under a test-owned fake-decision agent completes a **truncated** 4-ply protocol run: two Jev decisions, four **mock** calls, no winner, verified prefix. This is boundary verification, not a Jev gameplay result.

Local-only evidence: `local-artifacts/jev/hardening-b7864e3/validation.json`, SHA256 **`61309d5b9cc21c1936a9d1653cc84f746b97891df8eae86bcb2634fdc2ab2501`**, binds nine source/catalog/test hashes, release binary hash, all final commands/exits and raw log hashes. Companion `checks.json`, `python.log`, `rust.log`, `release.log`, `compile.log`, `rustfmt.log` and `diff.log` retain raw outputs. The historical winning report/replay/metrics were rehashed and are unchanged from their hashes above. Test-owned transient arena files are not retained as a new competitive artifact.

### Result, limitations and next authorized gate

**Repair slice IMPLEMENTED / VERIFIED offline.** R1–R6's scoped implementation gaps above are addressed with named tests; no independent review, live post-fix service compatibility test or competitive acceptance is claimed. The agent remains **NOT PROMOTED**.

- The alias `jev-latest` still floats; hashes/returned versions provide provenance, not remote-model determinism. Heuristic advice, two-stage exclusion and the 80-option cap remain; no evidence yet isolates Jev's independent contribution.
- The 100-attempt default is not a hard token/dollar budget. Missing usage and server work after local cancellation may still be billable. Reported probability/confidence is neither calibrated nor a game-strength estimate.
- The arena remains the ultimate deadline enforcer. OS scheduling/fsync/process creation can overrun local timing assumptions; after hard termination the journal may end with an unmatched request start and summary `running`. Windows descendant cleanup was executed; POSIX process-group cleanup is implemented but not tested on this host.
- Exact game effects are intentionally partial: no Python replacement for noble settlement, full purchase payment simulation or full legality verification. The referee remains authoritative.
- Secret/artifact publication policy unchanged: root handoff, key and generated logs stay ignored; owner `.gitignore` change stays unstaged. No push by default.

Stop after local code/doc commit. Await owner review or a separately budgeted small service smoke; before any strength claim, freeze the integration and predeclare seeds/both seats and facts-only versus facts+heuristic-advice comparison. No new tuning, training or paid experiment is implicitly authorized by this closeout.

## GUI interaction-trace feasibility — 2026-09-23

**INVESTIGATED / PROPOSED, not implemented.** Owner asks whether GUI replay can show each step's interaction with Jev (interpreting “dev” as Jev). Read-only source/artifact inspection at `9939c0af2b525e305abf407641f3a718f7b3e6e9`; no service calls or new game. No implementation tests were run for this investigation.

Observed integration points and gaps:
- `apps/replay-studio/app/replay/page.tsx:20–43, 227–257`: current verified archive has actor/ply, pre-action player view, canonical legal set and recorded move. Its action sidebar is a suitable place for a synchronized, read-only **Jev interaction** tab. Existing `StructuredAction` and timeline can be reused.
- `crates/splendor-cli/src/human_play_command.rs:1303, 1378, 2880`: ordinary Games/session replay discovery reads `local-artifacts/m20-human-play`; league replay has separate authority. The independent `local-artifacts/jev/<run>/` matches are not automatically discovered. Add an explicit local Jev source/readonly route; do not mislabel these unrated games as human sessions or insert them into the league.
- `jev/runtime.py:149–198` already records stage/attempt, candidates/IDs, selected ID, latency, usage and returned model/compatible distributions. It stores only the full payload **hash**, not the complete state/instructions body. The current journal also lacks explicit game/actor/observation/verified-replay binding. A GUI claiming to show the exact sent request therefore needs an additional safe request-body snapshot and durable run/decision identity.
- `MatchCounters::next_request_id` starts at one and request IDs are match-global; `with_completed_plies` resets request IDs for resumed branches. Never blindly treat a request ID as a ply. Bind trace to the verified replay document, actor and observation/legal-set identity; check selected action against the actual recorded move, retain retry attempts under one decision, and classify missing/mismatched/forced/failed records explicitly.
- Direct artifact inspection confirms both old completed runs `1790154627-seat0` and `1790162927-seat0` have config/report/replay/aggregate metrics, **no per-request JSONL**. Their exact historical calls/responses cannot be recovered. Any later prompt/candidate reconstruction must be explicitly labeled reconstruction, not an actual historical API exchange.

Proposed minimal UI: per-ply stage 1 family candidates and result → stage 2 exact candidates and result → resulting game action; each attempt shows model, timing, known/unknown token usage and retry/failure status. Expandable diagnostics show the actual saved application request body (no Authorization/header/credential) and a clearly labeled allowlisted response projection. Forced stages show “no API call”, opponent turns show “not a Jev decision”, absent logs show “not recorded”. No fabricated rationale: Choice output is not an exposed internal reasoning transcript, and reported confidence is not calibrated strength.

Keep existing viewer contracts from `docs/replay-studio-product-shell.md` and `docs/adr/0001-information-boundary.md`: opening/stepping a replay never invokes Jev or a reviewer; verified replay remains the game authority; agent-input snapshots contain only the acting seat's observation, never referee reveal/seed/deck order. Raw trace stays local-only. UI/host integration and safe snapshot/identity extension are the proposed next slice, pending implementation authorization; paid validation remains separate.

## GUI interaction trace implementation — IMPLEMENTED / VERIFIED (2026-09-23)

### Scope and contract

Owner “开始做吧” authorized implementation against `main@f20432bee91dbb0d470f561281a137283cb2daa6`. v0.3 safe application-request snapshots and run/decision identity; the runner binds the journal to the exact replay/prefix bytes; read-only local Jev index/archive routes; the existing replay sidebar and timeline show stage/attempt/candidates/selection/usage. Completed ReplayV1 and verified truncated prefixes remain distinct. Old runs remain playable with “not recorded”; failed runs without a verified replay/prefix are listed without fabricating a board/winner. No heuristic/prompt strategy tuning, paid calls, training, league writes or publishing of generated logs.

### What was built

| Layer | Change |
| --- | --- |
| `crates/splendor-protocol` | Optional `run_trace_id` on `GameStart` and optional `ply` on `RequestAction`, both `skip_serializing_if = "Option::is_none"`, so ranked/league wire bytes are unchanged. |
| `crates/splendor-arena` | `ArenaConfig::run_trace_id` (≤128 bytes, ASCII `[A-Za-z0-9_-]`, ≥1 alphanumeric, `InvalidRunTraceId` fail-closed). `RunCtx` broadcasts it on `GameStart` and stamps the acting ply on each `RequestAction`. |
| `jev/runtime.py` | `METRICS_SCHEMA_VERSION = 3`. `safe_payload` allowlists exactly `state`/`model`/`questions`, ≤256 KiB, rejects sensitive keys. `safe_identity` accepts only scalar `game_id`/`run_id`/`seat`/`replay_document_hash`/`request_id`/`ply`, requires ≥1 surviving non-empty field. `Session.identify` emits `identity_bound`. |
| `jev/agent.py` | Binds the run id from `game_start.run_trace_id`; `decision_start` carries `ply`, `observation_hash`, `actor`. |
| `jev/trace.py` (new) | Read-only journal reader: bounded size, safe component checks, `read_run`, `index_by_ply` (duplicates marked ambiguous), `summarize` into the exact shape the UI renders. |
| `jev/match.py` | Writes `run_trace_id = out.name`; `write_trace_summary` joins the journal to the verified replay/prefix and writes `trace-summary.json`. |
| Studio Host | `GET /jev/runs` and `GET /jev/runs/{run_id}`, serving the run verbatim from a source resolved once from `--project-root`. `HistoricalReplayFrameV1` gained `observation_hash`. |
| `apps/replay-studio` | `app/jev-trace-runtime.mjs` (pure derivations), `app/components/jev-interaction-panel.tsx` (read-only panel), a `JevRuns` section on the Games home, and `?jev=<run_id>` wiring on the replay page. |

**Information boundary.** The snapshot is the application body only. The API credential lives in an HTTP header and is never part of `state`/`model`/`questions`, so it is structurally impossible for it to appear in the record. No referee reveal, seed, or deck order enters an agent-input snapshot. Opening or stepping a trace issues **only** `GET`s and touches no reviewer route; verified in real Chromium.

### Iteration log

1. **Identity binding silently did nothing.** The first real-arena probe produced no `identity_bound` event: the arena names the field `run_trace_id` while the agent read `run_id`. Caught only because the gate ran a real arena; a mock would have passed. Fixed to read `run_trace_id`.
2. **`ply` is match-global, not per-seat.** Asserting `[0, 1]` failed against a real 2-player rollout that records `[0, 2]`. The arena was right and the expectation was wrong; both the Python and Rust gates now document match-global plies.
3. **The Studio Host read runs from the process cwd, not the project root.** The League root is resolved once from `--project-root` with an explicit comment that no handler re-derives from the cwd, but `JEV_RUNS_DIR` used a bare relative constant. The Host now resolves `jev_runs_dir` once at startup, preserving the old cwd behavior when `--project-root` is absent. This was found by a real binary test, not by inspection.
4. **The new UI test file was never executed.** `npm test` lists its test files by name and `jev-trace-runtime.test.mjs` was absent, so 11 tests passed silently by not running. Now wired in — the suite went 141 → 152.
5. **A bulk `cargo fmt` reformatted unrelated M49A files.** Reverted `m49a_*` and `splendor-eval/src/lib.rs`; only this round's ~18 files are touched. `crates/splendor-cli/src/m49a_target_builder.rs` and `crates/splendor-agent/src/heuristic.rs` retain pre-existing formatting drift that is not this round's to change.

### Validation and evidence

All eight checks exited 0. Record: local (ignored) `local-artifacts/jev/trace-viewer/validation.json`, SHA-256 `875a59a2f5c2be375f03fa6e95bffb40e9346e3e9dd980101227d2bb2efb1e51`, binding 18 source hashes.

| Check | Result |
| --- | --- |
| `cargo test --workspace` | **1012 passed / 0 failed / 3 ignored** |
| `python -m unittest discover -s jev` | **50 passed** |
| `npx tsc --noEmit` | clean |
| `npm test` (replay-studio) | **152 passed / 0 failed** |
| `npx eslint .` | clean |
| real Chromium trace gate | **PASS** |
| `python -m compileall -q jev` | clean |
| `git diff --check` | clean |

Notable gates, all against a real binary or a real browser — never a purely mocked seam:

- `the_jev_trace_routes_serve_a_local_journal_without_touching_the_league` drives the real `studio-host` over a real socket. Its prefix comes from a real `run-rollout --max-plies 4` and its summary from the real `write_trace_summary`, so the route cannot be validated against a shape the engine never emits. It asserts the run is listed, an unrecorded run reports `journal_recorded: false` / `game_document: "unavailable"`, the served document is a `splendor-rollout-prefix`, and `replay` is `null` for a truncated run.
- `a_jev_run_name_cannot_escape_the_runs_directory` refuses `../../etc/passwd`, `..%2F..%2Fetc`, `nope`, `gate-run/../..`, the empty id, and `....%2f...%2f...%2fetc%2fpasswd` with 400 rather than resolving them.
- `jev/test_hardening.py` runs a **real local arena** with a test-owned fake decider (no production flag enables fake inference) and asserts the journal's plies and observation hashes match what the arena sent, that 4 request snapshots contain exactly `state`/`model`/`questions`, and that the fake key never appears anywhere in the record.
- The Chromium gate drives the built UI against a real HTTP Host stub: it steps Gilded Replay frames, sees the three real stage labels, a retried attempt and its usage, an expanded request body marked “Application payload only”, an unrecorded-second-stage message, and confirms a missing run leaves the replay usable and is reported honestly.

Boundary statement: **zero paid API calls, zero live model calls, zero training, zero league writes** this round. Every inference was a test-owned fake decider inside a real local arena.

### Result and decision

`IMPLEMENTED` / `VERIFIED` for the read-only interaction-trace surface. The frozen gates above were met. This is a **parent self-check**, not an independent review, and it makes **no strength claim** about the agent.

### Known limitations

- Historical runs `1790154627-seat0` and `1790162927-seat0` predate the journal and cannot be reconstructed; the UI reports them as “not recorded”.
- `request_id` is match-global and reset by `with_completed_plies`, so it is never used as a ply key; the join is by ply plus observation hash and confirmed against the recorded action.
- The trace records the application payload and an allowlisted answer projection. It is not a reasoning transcript, and reported confidence is not calibrated strength.
- Verified offline with a fake decider only. A live service smoke with the real model remains unbudgeted and unclaimed.

### Next authorized gate

Await owner review, or a separately budgeted paid smoke. Any competitive claim still requires a paired facts-only vs facts+advice evaluation.

## B2 request-size repair and pinned-model rerun — IMPLEMENTED / VERIFIED (2026-09-24)

### Problem and evidence

Stage B ran 20 real-inference games against four fixed pool anchors and produced
12 aborted games, all `HTTP 400` on the stage-2 `move` call. The cause was
isolated by direct API probes, not inferred:

- identical payload, only criteria count varied -> 48 accepted, 80 rejected;
- **20 choices in 100 KB rejected** while **255 choices in 6.8 KB accepted**, so
  the limit is size, not choice count;
- bisection on the real payload shape: **76,133 B accepted / 76,134 B rejected**;
- every rejected stage-2 payload was >= 78,886 B and every accepted one
  <= 71,742 B, cleanly separable.

Because v0.2.0 classifies 400 as non-retryable, each of these correctly failed
closed and ended its game. That was the hardening working as designed.

The 80 candidates were reserve-family: 72 `reserve_market` + 8 `reserve_deck`,
where one market card expands into ~6 candidates differing only in which gem is
returned. Those return variants carry byte-identical heuristic values, so the
payload was mostly repeated structure rather than distinct information.

### What changed (B2.1-B2.4)

| Layer | Change |
| --- | --- |
| `jev/agent.py` | `compact_label()` renders one line per candidate; `_compact_terms()` omits zero-valued terms; `GEM_CODE` gives unambiguous `W/U/G/R/K/J` codes. |
| `jev/transport.py` | `MAX_REQUEST_BYTES = 70_000`, measured with the same `encode()` the transport sends; oversize raises `request_payload_too_large` with no request and no retry. |
| `jev/agent.py` / `jev/runtime.py` | `MODEL` pins `jev-1.13.0`; `EXPECTED_MODEL` drift gate raises `AgentFault("model_identity_drift")` if the provider returns another identity. |
| `jev/match.py`, `jev/run_batch.py` | Manifests read the pinned identity from the agent instead of restating `jev-latest`. |
| `jev/run_batch.py` (new) | Fixed-anchor batch runner; schedule frozen before game 1 and re-read on rerun. |

Explicitly unchanged: `MAX_OPTIONS`, the candidate set, candidate ordering,
heuristic values, two-stage routing, retry counts and prompt strategy.

### Validation

- 12/12 originally-rejected roots re-encoded offline: **77,140 B -> 25,787 B
  (-67%)**, candidate count unchanged at 80, all 960 candidates' heuristic
  values verified term-by-term, and every move label pairwise distinct.
- One formerly-rejected root sent live: **HTTP 200**, a legal choice, and
  `jev-1.13.0` returned.
- Full 20-game rerun on the identical frozen schedule: **20/20 completed,
  0 aborted**, 1177 requests (cap 1200), max payload **27,995 B**, 0 request
  errors, 617 decisions with 0 outside the offered set, 20/20 replays verified,
  and a single model identity across all 20 games.
- Python **59/59**. No league/Elo/registry write; the league database and
  identity manifest hashes were verified unchanged before and after.

### Result

**Jev 5-15** across the 20 games: 0-5 vs s3-rollout, 0-5 vs heuristic, 0-5 vs
determinization-n2000, 5-0 vs random; 2-8 first / 3-7 second.

This is the first complete, non-MNAR sample: completeness no longer correlates
with legal-action count. It is still not a strength estimate (20 games, one seed
each, no repeats). Game 00 also changed from a 15-13 win in Stage B to a 12-15
loss under the compact representation, which is why the Stage B and B2 results
must not be merged into one sample.

Reserve return variants being heuristic-tied is recorded as a **strategy**
observation, not folded into this transport repair: the heuristic not
distinguishing them does not make them strategically equivalent, and merging
them would hand a real action dimension to an arbitrary tie-break.

### Next authorized gate

Owner authorized B3, a zero-cost offline attribution audit over these 20 traces
and replays (family routing, within-family heuristic rank/gap, reserve-return
incidence, and a pure-heuristic control on the same schedule). No strategy code
changes.

## B3 offline attribution audit — VERIFIED (2026-09-24)

Zero-cost: reads the completed B2 traces/replays only, calls no API, writes
nothing to the league. The league database and identity manifest hashes were
verified unchanged after every step. Its purpose is to locate where Jev loses
ground before any further strategy change is authorized.

Standing caveat: **heuristic disagreement is not proof of error.** The heuristic
is a fixed advice function, not ground truth. A deviation is a lead for review,
not a counted mistake.

### Q1 Stage-1 family routing — near-perfect, not the bottleneck

595 multi-family decisions were parseable. Jev chose the heuristic's top family
in **575 (96.6%)** of them; mean family gap **114** units, median **0**. Against
the three non-random anchors specifically: 288 multi-family decisions,
**9 mismatches (3.1%)**, mean foregone gain 3,385 units.

Stage-1 is therefore not where the losses come from. Fixing routing could
recover at most ~3% of decisions.

### Q2 Within-family (stage-2) choice — Jev follows the advice almost exactly

582 non-singleton stage-2 decisions: **524 (90.0%) took the heuristic's top
ranked move**, 572 (98.3%) were within the top 3, mean percentile 95.8, and
**551 had zero gap**. Only 26 decisions exceeded a 2,000-unit gap, and only
3 of those were high-confidence (>= 0.5):

| game | confidence | gap | rank | move |
| --- | --- | --- | --- | --- |
| 09-heuristic-s1-20261104 | 0.63 | 6,500 | 2/12 | take W1U1R1 |
| 01-s3-rollout-s1-20261001 | 0.53 | 5,000 | 2/5 | take W1U1K1 |
| 18-random-s0-20261303 | 0.51 | 2,750 | 2/7 | buy_market One/S1 #0 VP0 blue cost=K3 |

This is the key structural finding: **Jev is not diverging from the heuristic it
is shown.** Whatever is wrong is largely already wrong in the advice, or is
invisible to a one-move heuristic (tempo, opponent modelling, planning) and thus
also invisible to an agent that follows that advice 90% of the time.

### Q3 Reserve-return incidence — too small to be worth a work item yet

Reserve accounted for 80 of 613 decisions (13.1%), with a returned gem in 17.
14 selected Reserve choices landed on targets chosen more than once, spread over
62 distinct targets. Family distribution overall: take_tokens 290, buy 225,
reserve 80.

Reserve is **13.1% of decisions generally and 13.2% of losing-game decisions** —
i.e. its incidence is essentially flat between wins and losses. There is no
evidence here that it is leaking games disproportionately. Owner had already
withheld authorization for return-variant merging on this basis; this measurement
supports that choice.

### Q4 Heuristic control — the decisive result

Same 20 games, same opponents, same seeds, same seats: the Jev subprocess is
replaced by the pure Rust `agent-heuristic`. No API, no league write. Note this
control is *not* paired against Jev move-by-move; the opponent sees different
play, so later states diverge.

| anchor | games | heuristic | Jev |
| --- | --- | --- | --- |
| s3-rollout | 5 | **1**-4 | 0-5 |
| heuristic | 5 | **2**-3 | 0-5 |
| determinization-n2000 | 5 | **3**-2 | 0-5 |
| random | 5 | 5-0 | 5-0 |
| **total** | **20** | **11-9** | **5-15** |

Non-random anchors: **heuristic 6/15, Jev 0/15**. Mean score margin +3.15 for
the control vs +0.40 for Jev; across the 15 non-random games the control was
strictly better in 9 and worse in 6, mean margin difference +3.60 VP.

Game 00 is the sharpest single case: control 15-6 vs s3-rollout where Jev lost
12-15.

**Interpretation, stated conservatively.** The 0/15 vs 6/15 split is real and
suggestive, but the per-game paired sign test over 15 non-random games gives
**p = 0.61** — not significant. n=20 with one seed per game cannot carry a claim
of "the LLM layer degrades decisions". What the control does establish is that
the 5-15 result is **not** purely "the anchors are too strong and the schedule is
hopeless": a plain heuristic takes 6 of those 15 games on the identical
fixtures. So "Jev is facing impossible opposition" is ruled out, while "Jev is
precisely X worse" is not yet measured.

### What this points at, and what it rules out

- **Ruled out as the main lever:** stage-1 routing (96.6% already optimal) and
  stage-2 rebellion against the advice (90% top-ranked). Reducing heuristic
  influence further cannot be the first move, because Jev already follows it.
- **Not yet supported:** reserve-return work (13% incidence, flat between wins
  and losses).
- **Most consistent reading:** Jev has largely learned to imitate a one-move
  heuristic, and the ceiling that imposes is the ceiling being measured. Any
  gain would have to come from decisions the heuristic cannot express, not from
  steering Jev closer to it.

This is a qualitative signal, not an effect-size estimate. Both are 20-game
single-seed samples; neither is paired move-by-move against the other. A paired,
repeated-seed comparison would be needed before claiming the LLM layer is
specifically harmful.

### Next authorized gate

None. Owner to decide among: pursuing plan/tempo beyond one-move heuristic
advice, reducing heuristic牵引 despite the 90% agreement, reserve return policy,
or stopping development on this configuration. No further API spend authorized.
