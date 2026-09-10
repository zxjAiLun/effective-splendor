# S3 Review Integration v1

**Status / baseline / owner-date block**  
- **Status**: `IMPLEMENTED` / `VERIFIED` (named checks below actually ran). Not `ACCEPTED` — product closure review is the next gate.
- **Authorized**: Product Default Repair 1 (6abc3fa)  
- **Owner**: PI Coding Agent  
- **Date**: 2026-09-10  
- **Implementation baseline**: `6abc3fa` (pre-change `main` == `origin/main`); the working tree already carried the additive `S3Decision` field change and this document as untracked.
- **Code commit**: `0a4d6e8` ("S3 Review Integration v1"), pushed to `origin/main`; test-cleanup follow-up `905ef5f` (unused test bindings only, no behavior change). All suites below were re-run green after the cleanup.
- **Original round baseline**: `d8b3557` (Play closed, Review untouched)
- **Design direction**: Lean, honest S3 policy recommendation only (no new Arena, no new strength research)  
- **Implementation contract**: Use existing S3 decision API (`s3_decide`, `s3_comparison`), minimal `AnalysisTraceV2` extension, sequential per-seat RNG, information-safe inputs only.

## Problem and evidence
- Play / human-play-server default is now S3 (Choice C, Product Default Repair 1 complete).
- Review side is completely unintegrated: `studio-reviewers.registry.json` only contains M07 (default) and M13 (rejected); schema and UI hard-code `root_determinization` / `neural_ismcts`.
- Users want to see S3's recommendation after playing (honest, not "mistake" framing).
- Existing Review schema and UI cannot accommodate S3 without breaking existing reviewers or introducing redundant fields.
- S3 decision process already produces `a_H`, `a_n1`, `a_m07`, `path` — perfect for minimal recommendation.

## Initial design
- **Scope**: Integrate S3 as third reviewer (lean v1). Do not change status model, do not add new Arena, do not change S3 policy, do not fabricate ground truth.
- **Non-goals**: New strength research, new D/P tuning, referee hidden state, "mistake/blunder" labels, M07/M13 deletion.
- **Acceptance gates**: 
  1. Native S3 replay exact reproduction (100% parity on existing S3 seat replays).
  2. Information isolation (only `player_view` + visible history + legal_actions).
  3. Existing reviewers (M07/M13) unchanged.
  4. UI shows S3 path and whether it matches recorded action (no "correct/incorrect" labels).

## Scope and non-goals
Kept as designed. Additional frozen discipline carried from the continuation brief:
- No Arena, no new strength games, no ELO/winrate work; Gate 1 may use existing replays and an
  in-test deterministically recorded S3 self-play replay.
- S3 decision logic (`s3_comparison`, `s3_decide`, fast-path rules, RNG consumption) unchanged;
  the only agent-crate change is the pre-existing additive `S3Decision` fields
  (`base_heuristic_action`, `n1_proposal`, `m07_proposal`) populated at all four construction sites.
- No D/P tuning; frozen seeds untouched.
- No "mistake/blunder/accuracy/correct" labels; neutral wording only ("Matches S3 recommendation" /
  "S3 recommends another action").
- `referee_reveal` is carried for display only and is never an S3 reviewer input.
- M07 stays `Champion` + `is_default=false` (historical description only);
  `ReviewerRegistryV1::validate()` and `AnalysisTraceV2::validate_reviewer()` keep the
  hard `M07_REVIEWER_ID => Champion` binding. M13 untouched.
- No fabrication of M07 utility or M13 prior/visit/Q; S3 exposes no utility/rank at all.
- `local-artifacts/**` and `handoff.md` are never staged.

## Contracts and invariants
- Review runs on **actual replay positions** with per-seat persistent `StableRng(20_260_812)`
  advanced in replay ply order; only root heuristic ties consume the stream (unique maxima consume
  nothing); rollout-internal ties use the agent's separate per-(world,seat) SHA256 streams.
- S3 reviewer inputs are **information-safe** (never `referee_reveal`): per position, only the
  recorded actor's `Observation`, the actor-visible history (`Audience::Player(actor)`) and the
  canonical legal action set. The decision function signature cannot accept hidden state.
- `PolicyRecommendation` uses the proposals computed inside the same frozen S3 decision path
  (n1/M07 proposal configs with throwaway `StableRng::new(0)`, exactly as the live agent).
- `AnalysisFrameV2` already has `recorded_action` and `recommended_matches_recorded`; the S3 result
  duplicates neither.
- Fast-path frames (non-Main / <2 legal / root tie) never ran a comparison: recommended == base ==
  n1 == m07 == the actual RNG-tiebroken heuristic action, `decision_path = heuristic_fast_path`.
- `review_cache_key_v2` binds replay hash + reviewer id + algorithm_version + canonical config JSON +
  checkpoint hash; the S3 config encodes the frozen D/P/seeds so policy drift invalidates caches.

## Implementation plan
1. Create `docs/s3-review-integration.md` (this file) — freeze semantics. ✅
2. Extend `AnalysisTraceV2` with `ReviewerResultKindV2::PolicyRecommendation` and minimal struct. ✅
3. Implement replay-wide S3 reviewer (sequential per-seat RNG, actual positions, info-safe inputs). ✅
4. Update `ReviewerRegistryV1` (S3 first/default, keep M07/M13). ✅
5. Wire Studio Host review job dispatch/cache. ✅
6. Update trace-runtime and ReviewPage rendering. ✅
7. Regression on existing S3 replays (native reproduction, root-tie parity, hidden-info isolation,
   old reviewer compatibility, cache identity). ✅
8. Verify UI (reviewer switch, default S3, progress, cached reload, mine/all, player/referee view). ✅
9. Stop for product closure review. ⏸

## Iteration log
- 2026-09-10 — Start-state verification: `main` == `origin/main` at `6abc3fa`; worktree exactly
  ` M crates/splendor-determinization-agent/src/s3_rollout.rs` + `?? docs/s3-review-integration.md`;
  `git diff --check` clean; the uncommitted diff confirmed as the additive `S3Decision` fields
  (4 construction sites), `S3Path::RootTieKeptA_H` spelling untouched. No deviations from the brief.
- 2026-09-10 — `splendor-analysis` gained `splendor-agent` and `splendor-determinization-agent`
  dependencies; `cargo check -p splendor-analysis` confirmed no dependency cycle.
- 2026-09-10 — `review_trace.rs`: added `S3ReviewConfigV2` (frozen v1 identity derived from the
  agent constants), `S3ReviewPathV2`, `PolicyRecommendationReviewResultV2`,
  `ReviewerConfigV2::PolicyRecommendation`, `ReviewResultV2::PolicyRecommendation`, reviewer identity
  binding (`s3-rollout-review` => `Champion` + `PolicyRecommendation`), config/checkpoint binding
  (no checkpoint), and result validation (all four actions legal; the differs flag must equal the
  recommended/base identity; fast paths must keep the base heuristic action for every proposal).
- 2026-09-10 — New `s3_review_trace.rs`: `analyze_replay_s3_v2[_with_progress]` mirroring
  `determinization_trace.rs` (verify replay once, per-position actor view, canonical legal actions,
  referee projection display-only), replicating the live `S3RolloutAgentPolicy::choose_action`
  fast-path/eligibility logic bit-exactly (mirrored ~40 lines; agent policy untouched) and calling
  the augmented `s3_comparison`. Not used: approach 2 (`decide_detailed`) — the lean replication was
  sufficient and keeps the agent crate's public behavior unchanged.
- 2026-09-10 — Decision: the review trace's `information_set_hash` / `visible_history_hash` are
  computed with `splendor_belief::build_information_set_v1` (the same builder the S3 engine uses
  internally for its root identity), so no determinization analysis is run for the reviewer.
- 2026-09-10 — Registry JSON: S3 entry first with `is_default=true`, M07 flipped to
  `is_default=false` (status stays `champion`), exactly one default; a new machine-verified test
  (`crates/splendor-cli/tests/studio_registry.rs`) validates the real JSON file and the S3 default.
- 2026-09-10 — CLI: `create_review`, `reviewer_identity_from_entry` and `run_review` gained the
  `PolicyRecommendation` arms (no checkpoint; dispatch to `analyze_replay_s3_v2_with_progress`).
- 2026-09-10 — Front-end: `trace-runtime.mjs` gained the third review kind (validator branches for
  config/result, proposal-set rows, neutral match/differs summary with decision-path histogram);
  `review/page.tsx` gained the S3 analysis panel (proposals + path + neutral result line) and config
  label; `play/page.tsx` type union extended. No `dist/**` hand edits; `dist` was regenerated with
  the normal `npm test` build.
- 2026-09-10 — Fixture: `generate_frontend_fixture` now also emits
  `apps/replay-studio/tests/fixtures/rust-analysis-trace-v2-s3.json`; the pre-existing v1/M07
  fixtures were regenerated byte-identically (no diff).
- 2026-09-10 — Cost iterations on tests (no semantic change): the S3 reviewer is expensive in debug
  builds, so schema-level tests share one `OnceLock` analysis of a 58-ply replay, the determinism
  test uses a 25-ply replay, and the Gate-1 parity test remains a full S3 self-play game.
- 2026-09-10 — Local-only corroboration (not committed, ignored artifacts): both existing
  human-vs-S3 replays (`local-artifacts/m20-human-play/human-12312300221-0-28024-1.replay.json`,
  `human-17889722450-0-28024-2.replay.json`) reproduce the S3 seat 29/29 and 28/28 with the new
  reviewer. The temporary check was removed from the committed suite.

## Final implementation
- **Agent crate (additive only, pre-existing uncommitted change finalized)**:
  `crates/splendor-determinization-agent/src/s3_rollout.rs` — `S3Decision` gains
  `base_heuristic_action`, `n1_proposal`, `m07_proposal`, populated in all four construction sites.
  No decision-logic change; `S3Path::RootTieKeptA_H` spelling unchanged.
- **Schema** (`crates/splendor-analysis/src/review_trace.rs`): `ReviewerResultKindV2::PolicyRecommendation`,
  `S3ReviewConfigV2` (frozen v1: `version=1`, `rollout_policy="s3-rollout-d4-p120-v1"`,
  `determinizations=4`, `ply_cap=120`, `sample_seed=43_300_101`, `proposal_seed=20_260_703`,
  `root_seed=20_260_812`), `S3ReviewPathV2`, `PolicyRecommendationReviewResultV2`
  (`recommended_action`, `base_heuristic_action`, `n1_proposal`, `m07_proposal`, `decision_path`,
  `recommended_differs_from_base_heuristic`), plus binding/validation arms and consts
  `S3_REVIEWER_*`. `algorithm_id = "effective-splendor-s3-rollout-v1"` (asserted equal to the live
  `S3_AGENT_NAME` in tests); metrics `["recommended_action", "decision_path", "rollout_outcome_score"]`.
- **Reviewer pipeline** (`crates/splendor-analysis/src/s3_review_trace.rs`, new):
  `analyze_replay_s3_v2` / `_with_progress`; input boundary = `(Observation, actor-visible history,
  canonical legal actions)`; per-seat persistent root RNG in ply order; exact tie consumption;
  eligible contexts run the frozen n1/M07 proposals + `s3_comparison`; result mapping and
  `S3Path -> S3ReviewPathV2`.
- **Registry** (`crates/splendor-analysis/src/reviewer_registry.rs`, `benchmarks/studio-reviewers.registry.json`):
  S3 entry first/default/champion/no checkpoint; M07 `is_default=false` (still `Champion`); M13
  unchanged; expected-metrics and default-config arms added.
- **Studio Host** (`crates/splendor-cli/src/human_play_command.rs`): three `PolicyRecommendation`
  arms; review artifacts cached under the unchanged cache-key scheme.
- **Front-end**: `app/trace-runtime.mjs`, `app/review/page.tsx`, `app/play/page.tsx`,
  `tests/review-runtime.test.mjs`, new fixture `tests/fixtures/rust-analysis-trace-v2-s3.json`.

## Validation and evidence
All commands run on 2026-09-10 on the final working state (Windows, debug profile):

| Command | Result |
| --- | --- |
| `cargo check -p splendor-analysis` | OK (no dependency cycle) |
| `cargo test -p splendor-analysis` | 26 passed / 0 failed (unit) + 1 passed (frontend fixture integration) |
| `cargo test -p splendor-determinization-agent` | 19 passed / 0 failed |
| `cargo test -p splendor-cli` | 42 test binaries, 264 passed / 0 failed |
| `cargo build` | finished successfully |
| `npm test` (apps/replay-studio: build + 5 `node --test` files) | 32 passed / 0 failed |
| `cargo run -p splendor-analysis --example generate_frontend_fixture` | wrote v1, M07 (byte-identical) and new S3 fixture |
| `git diff --check` | clean |
| `npx tsc --noEmit` (studio) | no new errors (the 3 errors in `review/page.tsx` and the others are pre-existing at HEAD, confirmed against the HEAD file) |

**Gate 1 — native S3 replay reproduction.** Committed test
`s3_review_trace::tests::reviewer_reproduces_recorded_s3_decisions` records a deterministic
S3-vs-S3 game in-test (seed 1: 54 plies, 3 root heuristic ties, 51 eligible comparison contexts;
`ReplayRecorder` + the real `S3RolloutAgentPolicy` with per-seat `StableRng(20_260_812)`) and
asserts `recommended_action == recorded_action` for every frame (100%), which requires bit-exact
per-seat root-RNG consumption in ply order. Additional local-only corroboration (ignored artifacts,
temporary check, since removed): the two existing human-vs-S3 replays above reproduce the S3 seat
29/29 and 28/28.

**Gate 2 — information isolation.** `s3_decision_is_blind_to_the_true_hidden_world` samples two
*different* hidden completions of the same root information set (asserted different state hashes,
identical observations) and asserts identical decisions; `s3_decision_depends_only_on_information_safe_inputs`
pins the input boundary; `player_view_does_not_expose_opponent_blind_reserves` mirrors the M07
regression. Structurally, the decision function only accepts observation + visible history +
canonical legal actions, so `referee_reveal` cannot reach the decision.

**Gate 3 — M07/M13 unchanged.** `determinization_trace` and `neural_trace` tests all pass in the
analysis suite; the M07 identity/status hard bindings are intact in both schema and registry; M07's
registry entry stays `champion` with `is_default=false` (verified by the new
`studio_reviewer_registry_is_valid_and_defaults_to_s3` test); the JS M07 fixture tests still pass
unchanged.

**Gate 4 — cache identity drift.** `cache_key_binds_s3_identity_and_config`: bumping
`algorithm_version` flips `review_cache_key_v2`; changing `ply_cap` in the config flips it; the
drifted config fails `S3ReviewConfigV2::validate()` (cannot claim the frozen identity).

**Gate 5 — UI.** JS tests: the S3 fixture validates; `buildReviewRows` exposes exactly the four
proposal roles and none of `meanUtility`/`utilityGap`/`actionRank`/`prior`/`visit`/`q`/`unscored`;
`buildReviewSummary` reports decisions vs matches/differs + decision-path histogram only (no rank,
unscored or accuracy); malformed fast-path/differs traces are rejected. The registry JSON test
proves the S3 default, and the server-rendered `/review` route test still passes. Player/referee
toggle, mine/all filter, progress and cached reload are existing review paths reused unchanged
(no browser automation in CI).

## Result and decision
- S3 is integrated as the third Studio reviewer (`policy_recommendation`), default in the reviewer
  registry, with honest proposal-set output and neutral match/differs wording.
- All five gates above were run and passed on this working state: round status `VERIFIED` (not
  `ACCEPTED` — that is the product closure review's decision).
- No strength claims, no Arena, no policy change, no promotion implications; M07 historical champion
  and M13 rejected status unchanged; promotion `NONE`.

## Known limitations
- First version is lean (no full plugin architecture).
- UI labels stay neutral ("S3 recommends another action"); agreement is not accuracy.
- The S3 reviewer is expensive (it re-decides every ply with the full rollout pipeline); the debug
  test suite reflects that cost.
- `information_set_hash` / `visible_history_hash` for S3 frames come from the belief builder rather
  than a determinization analysis object; they are internally consistent but not comparable
  across reviewer kinds.
- Browser-level UI verification was not automated (JS validation + rendered-route tests only).

## Next authorized gate
- Product closure review (user decision). Do not open follow-on work from this round.
