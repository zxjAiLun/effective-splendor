# M45A Bonus-Vector Information Probe

```text
Milestone:      M45A
Title:          Bonus-Vector Information Probe
Type:           evaluator color-identity binding probe & residual capacity audit
Status:         COMPLETED_DIAGNOSTIC / CLOSURE_PENDING_REPAIR_1
                (P1/P2/P3 results and Outcome 1 ACCEPTED in terminal review
                on 12a0974; wording repair ordered; Arena rerun FORBIDDEN)
Tracked Result: benchmarks/m45a-bonus-vector-information-probe-v1.result.json
Starting point: 99872f0 — M44C permanently closed
Design Commit:  2f36ee4 (DESIGN_V1, approved and frozen)
Implementation: b462ea9 (SHIFT1 profiles + P0 gates)
Execution:      12a0974 (384-match Arena + P2/P3 + final audit)
Repair Basis:   M45A terminal review on 12a0974
                (P0=0, P1=2 wording violations, P2=2 non-blocking)
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Training:       NONE
New learned model: NONE
New vector-value coefficient: NONE
Production evaluator modification: NONE

Authorization (DESIGN_V1, approved and frozen):
  design-only commit
  → implement research shift profiles
  → P0 exact semantic gates
  → if PASS → 384-game Arena (AUTHORIZED)
  → P2 180-context audit (AUTHORIZED)
  → P3 residual-capacity audit (AUTHORIZED)
  → exhaustive final audit
  → tracked result JSON
  → docs/handoff
  → commit + push
  → cloud final review

Not authorized in M45A:
  new residual vector feature, M45B, production changes,
  new learned value model, new handcrafted vector score,
  vector coefficient tuning, market-demand feature,
  future-affordability heuristic, neural bonus-vector encoder,
  F4/E2 coefficient tuning, M07 promotion.
```

## Problem and Evidence

M44C closed the evaluator scalar-attribution line with two facts:

1. `total_permanent_bonuses ≡ purchased_card_count ≡ C` (algebraic identity): the scalar CORE engine is a single quantity, and dense coefficient search around `W_C = 2.25M` has low research value (three positive scale points all `UNRESOLVED` vs FULL).
2. The 5-color bonus vector `b ∈ N^5` is already partially consumed by the current evaluator through exactly two color-sensitive paths:
   - **F4 (immediate convertibility)**: affordability via `can_afford → payment_for`, which reads `player.bonuses[color]` per color together with tokens and gold.
   - **E2 (noble progress)**: per-color noble deficit `deficit += requirements[color] − bonuses[color]` summed over the visible nobles.

The open question from the M44 line is therefore **not** "what new vector term should we add" — asking that immediately confounds a new feature definition, its weight, and F4/E2 overlap. M45A answers two prerequisites separately:

- **Q1 (existing-path binding)**: does the *correct color identity* of the bonus vector materially matter through the evaluator's existing F4 and E2 paths?
- **Q2 (residual representational capacity)**: after accounting for what the current evaluator already summarizes (both the two color-sensitive paths and the full five-term progress summary), does the bonus vector still contain state information the evaluator does not represent?

Q2 is an information-existence question. It is **not** a playing-strength claim.

## Initial Design

### Frozen color identity scramble

Canonical color order `[White, Blue, Green, Red, Black]` (indices 0–4). Define the deterministic cyclic shift `SHIFT1`:

```text
shifted_bonus[next_color] = true_bonus[current_color]
i.e. shifted[i] = true[(i + 4) mod 5]   (White receives Black's count, etc.)
```

Properties:

- `sum(shifted_bonus) == sum(true_bonus) == C` — therefore CORE_ENGINE, purchased_card_count, and total bonus count are exactly unchanged.
- The scramble changes only the association between bonus amounts and color identities.
- No random permutation. No per-game permutation. No multiple shift variants.

### Research profiles

Exactly three research-only `AttributionProfile` variants:

- `SHIFT_F4` — CORE/F1/F3/E2 use the true state. Only F4 affordability is recomputed using `SHIFT1(bonus)`. Equivalently `SHIFT_F4 = FULL − true_F4 + shifted_F4`.
- `SHIFT_E2` — only noble deficit/progress sees the shifted bonus vector: `SHIFT_E2 = FULL − true_E2 + shifted_E2`.
- `SHIFT_F4_E2` — both existing color-sensitive paths receive the same shifted bonus vector: `SHIFT_F4_E2 = FULL − true_F4 − true_E2 + shifted_F4 + shifted_E2`.

Everything else stays true-state. Terminal rank signal is untouched.

### Semantic boundary

These profiles are **identity-scramble ablations**. They do not represent legal alternative Splendor states. That is intentional. The treatment asks:

> If the evaluator is given the correct amount of permanent engine C, but the bonus colors are bound to the wrong color identities in F4/E2, does strength change?

M45A may infer the importance of **correct color binding**. It may not infer the value of any particular reachable alternative bonus vector.

Implementation note (bit-exact wiring): the scramble is realized inside a scrambled family-progress computation `family_progress_scrambled_for(state, player, scramble)` that recomputes only E2 (per-color noble deficit against shifted bonuses) and/or F4 (affordability with per-color shifted bonuses, using the same `payment_for` semantics: `need = cost[c] − shifted_bonus[c]`, tokens and gold from the true state). All other terms are the true-state values. `for_profile` then combines terms by the exact formulas above, preserving the exact-integer contract.

## Scope and Non-Goals

In scope: three shift profiles, P0 wiring gates, one 384-match Arena, one 180-context P2 audit, one residual-capacity P3 audit, tracked result artifact.

Non-goals (explicitly excluded):

- Naive or equalized bonus-vs-purchased LOO (permanently closed in M44C).
- Any new evaluator term, coefficient, or weight change.
- Any claim about reachable alternative bonus vectors.
- Sequential seed extensions, extra shift variants, M44 rematches.

## Contracts and Invariants

### P0 — exact wiring gates (pre-Arena, fail closed)

- **P0-A (sum preservation)**: across ≥256 deterministic reachable states spanning 2p/3p/4p: `sum(true_bonus) == sum(SHIFT1_bonus)` for every player, and `CORE_true == CORE_shifted` exact integer equality (follows from sum preservation; asserted anyway).
- **P0-B (untargeted families frozen)**: for every test state/player:
  - `SHIFT_F4`: F1, CORE, E2, F3 unchanged — only F4 may differ.
  - `SHIFT_E2`: F1, CORE, F3, F4 unchanged — only E2 may differ.
  - `SHIFT_F4_E2`: only F4 and E2 may differ.
- **P0-C (exact formula identity)**: `progress(SHIFT_F4) == progress(FULL) − true_F4 + shifted_F4`, and the corresponding exact equalities for the other two profiles. No approximate assertions.
- **P0-D (real activation)**: on the deterministic reachable-state corpus, report counts of states where `shifted_F4 != true_F4`, where `shifted_E2 != true_E2`, and where either differs. Both paths must have at least one actual activation (wiring sanity, not a strength threshold).
- **P0-E (FULL regression)**: existing M44A P0, M44B P0, M44C P0 suites must continue to pass. No modification to sealed scientific behavior.

### Arena contract

- Same validated n1 static-successor shell: `sample_seed = 20_260_703`, `sample_count = 4`, `max_depth_turns = 1`, `max_nodes = 1`.
- Fresh seeds `5_800_000 .. 5_800_063` (64 paired blocks), no M44 rematches.
- Three pairings: `SHIFT_F4 vs FULL`, `SHIFT_E2 vs FULL`, `SHIFT_F4_E2 vs FULL`; each 64 paired seeds × 2 rotations = 128 matches; total **384 matches**.

### Statistical protocol

- Statistical unit: paired seed block. Bootstrap: 10,000 resamples, seed `44_300_001`. Three primary hypotheses: `alpha = 0.05 / 3`. Report 98.333% two-sided CI.
- Decision rule: `upper CI < 5000 → RESOLVED_BINDING_IMPORTANT`; `lower CI > 5000 → RESOLVED_BINDING_INTERFERING`; otherwise `UNRESOLVED`. The `SENSITIVE` vocabulary is deliberately not used: the treatment is color-identity binding, not family deletion.

### P2 — deterministic 180-context behavior audit

- Exact quota matrix: 3 pairings × (Early 1–20 / Mid 21–45 / Late 46+) × 20 contexts each = **180 contexts**.
- Selection order: pairing → stage → seed ascending → rotation 0 then 1 → decision ply ascending → actor.
- Identity: the authoritative triple (`observation_hash`, `visible_history_hash`, `information_set_hash`) via `build_information_set_v1` (the M44C-repaired pipeline), globally deduplicated.
- Source reproduction: **180/180 required**, fail closed.
- Metrics (descriptive): action disagreement vs FULL; engine/non-engine action flips; true-vs-shifted F4 delta distribution; true-vs-shifted E2 delta distribution; margins as true top-1 vs actual runner-up using the corrected M44C method (sort by root-player utility, canonical tie-break, assert best == analyzer-selected action).

### P3 — residual bonus-vector capacity audit

- Corpus: all accepted 384 Arena replays; `Phase::Main` root-actor contexts only; deduplicated by the authoritative identity triple.
- Per context, compute the root player's `bonus_vector = [W,B,G,R,K]`, `C`, `F1`, `CORE`, `E2`, `F3`, `F4`.
- **Key A (F4/E2-conditioned)**: `K_path = (C, E2, F4)`. For every observed `K_path`: context count, distinct bonus vectors, bonus-vector entropy.
- **Key B (full-evaluator)**: `K_eval = (F1, CORE, E2, F3, F4)`. Report number of collision groups, contexts inside collision groups, distinct bonus vectors per group, conditional entropy. A collision means same current evaluator summary, different bonus vector.
- Formal meaning: if collision groups exist, M45A may conclude the root-player evaluator progress summary is many-to-one with respect to the player's full bonus vector in the observed corpus; some color-structure information remains unrepresented even after conditioning on the current scalar progress summaries. This is a **representation result**. It does NOT prove the omitted vector information would improve playing strength; other game-state variables can co-vary inside those groups; no causal inference from collision statistics.

## Implementation Plan

1. `crates/splendor-search/src/attribution.rs`: add `ShiftF4`, `ShiftE2`, `ShiftF4E2` variants (serde snake_case `shift_f4`, `shift_e2`, `shift_f4_e2`); add `ColorScramble` wiring and `family_progress_scrambled_for`; route `StaticEvaluatorAttributionV1::utilities` through profile-aware per-player progress.
2. `crates/splendor-cli/tests/m45a_p0_semantic.rs`: P0-A..P0-D gates on a deterministic reachable-state corpus + M07 frozen positions; P0-E runs the M44A/M44B/M44C suites separately in the final audit.
3. `scripts/m45a_orchestrator.py`: 3 pairings × 64 seeds × 2 rotations, strict n1 shell, fresh seed segment `5_800_000..5_800_063`.
4. `crates/splendor-cli/src/m45a_audit_command.rs`: P2 (180-context quota) + P3 (residual capacity) with authoritative identities.
5. `scripts/m45a_final_audit.py`: fail-closed exhaustive audit + tracked result JSON.

## Formal Interpretation Matrix

- **SHIFT_F4 weaker** — allowed: "correct bonus-color identity within the current F4 affordability path has resolved conditional playing-strength importance when the remainder of FULL is retained." Not allowed: "F4 itself is globally beneficial" (M44A's F4 family result remains `UNRESOLVED`).
- **SHIFT_E2 weaker** — allowed: "correct color binding inside noble-progress computation has resolved conditional importance." Not allowed: "noble progress as a whole was proven essential" (M44B's deletion result remains `UNRESOLVED`).
- **SHIFT_F4_E2 weaker** — allowed: "correct bonus-color identity jointly flowing through the two existing vector-sensitive pathways contributes resolved playing strength." This is the strongest clean result M45A can establish.
- **Any arm stronger** — classify `RESOLVED_BINDING_INTERFERING`. Do not tune weights or adopt the wrong-color evaluator; it only indicates interference under the frozen evaluator.
- **UNRESOLVED** — `UNRESOLVED != "color vector useless"`. It means M45A did not resolve a strength effect from deliberately scrambling that pathway.

## Exit Logic

- **Outcome 1 — binding resolved + residual capacity exists**: strongest motivation for a future experiment; a later M45B may design one explicit residual vector channel (not automatically authorized).
- **Outcome 2 — binding unresolved + residual capacity exists**: additional vector information structurally exists, but M45A did not resolve strength dependence on correct color binding through current F4/E2 paths; do not immediately engineer a vector feature.
- **Outcome 3 — binding resolved + little/no residual capacity**: vector identity matters primarily through already-existing F4/E2 summaries in the observed corpus; no new vector feature justified.
- **Outcome 4 — everything unresolved**: close the vector line for now; do not keep inventing increasingly complicated color features.

## Final Audit Requirements (fail closed)

`scripts/m45a_final_audit.py` must assert:

- 384 reports/replays; 768 lineup checks; 384 rotation checks; 0 abort/fault; all replay verification passed.
- Exact shell: `sample_seed = 20_260_703`, `sample_count = 4`, `depth = 1`, `nodes = 1`; exact profiles; exact seeds.
- Paired-block bootstrap 98.333% CI with seed `44_300_001`.
- P2: exact 180 quota; 180/180 source reproduction; authoritative unique identities.
- P3: authoritative dedupe; identity digest; conditional-group consistency; entropy/frequency consistency.
- Shift activation counts and all provenance (catalog file/semantic hashes, source SHAs, frozen seed list).

## Iteration Log

### 2026-09-05 — Implementation & Execution

- `b462ea9`: implemented `ShiftF4` / `ShiftE2` / `ShiftF4E2` as research-only `AttributionProfile` variants; deterministic `shift1_bonus` (sum-preserving cyclic shift); scrambled E2/F4 carried as new `FamilyProgress` fields so all sealed profiles keep their exact arithmetic; `m45a_p0_semantic.rs` (5/5 PASS: P0-A/B/C/D + parsing). P0-E regression: M44A 6/6, M44B 4/4, M44C 4/4, plus splendor-search and splendor-imperfect-search suites.
- P0-D activation on the 2160-state corpus: F4 differs on 1273/2160 states (59%), E2 on 1377/2160 (64%) — both paths genuinely active.
- 384-match Arena executed on fresh seeds `5_800_000..5_800_063` (15.3s wall).
- P2 (180 contexts, authoritative identity, 1-based staging, top-1/runner-up margins) and P3 (11,742-context residual capacity audit) executed via `m45a-audit`.
- Final audit `scripts/m45a_final_audit.py`: all fail-closed gates passed; tracked result written.

### 2026-09-05 — Terminal Review & Closure Repair 1 (wording seal)

The terminal review on `12a0974` **accepted** all experimental results (P1/P2/P3) and the pre-registered **Outcome 1**, ordering a wording-only repair (Arena rerun FORBIDDEN; all numeric values frozen unchanged):

1. **P1-1 (wording violation)**: the document had claimed `SHIFT_F4_E2` is "statistically indistinguishable from `SHIFT_F4` alone" and that "the E2 scramble adds no resolved marginal damage on top of the F4 scramble". No `SHIFT_F4_E2` vs `SHIFT_F4` contrast was preregistered or performed, and overlapping confidence intervals do not establish indistinguishability. **Repair**: replaced with the numerically-similar-point-estimates statement plus an explicit no-marginal-conclusion disclaimer; limitation added.
2. **P1-2 (wording violation)**: the document had claimed the SHIFT_F4 collapse is "of the same magnitude" as / "nearly as damaging as" M44B's CORE deletion, implying effect equivalence across different milestones, seed segments, multiple-comparison setups, and interventions. **Repair**: downgraded to a cross-milestone descriptive point-estimate observation with an explicit no-effect-equivalence disclaimer; the more informative M44A contrast (DROP_CONVERTIBILITY UNRESOLVED vs SHIFT_F4 resolved-loss ⇒ wrongly-bound color structure in a high-weight path is more dangerous than missing information) recorded with its boundaries.
3. **P2-1 (precision)**: "the current evaluator is many-to-one" scoped to "the root-player evaluator progress summary is many-to-one with respect to the bonus vector in the observed corpus" in both the design contract and the result section.

P2-2 (non-blocking, recorded): the final-audit exhaustiveness counters (candidate_faults = 0 etc.) remain summary-filled values rather than independent accumulators; the per-match config/report/replay/lineup/verify-replay walk supports them, and this matches the accepted M44A–M44C pattern. No change required.

All P1/P2/P3 numeric values, the tracked result JSON, and the Arena corpus remain frozen and unchanged in this repair (docs-only commit).

## Validation and Evidence

Executed commands (all exit 0):

```
cargo test -p splendor-cli --test m45a_p0_semantic     # 5/5 PASS
cargo test -p splendor-cli --test m44a_p0_semantic     # 6/6 PASS (regression)
cargo test -p splendor-cli --test m44b_p0_semantic     # 4/4 PASS (regression)
cargo test -p splendor-cli --test m44c_p0_semantic     # 4/4 PASS (regression)
python scripts/m45a_orchestrator.py --workers 8        # 384 matches
target/release/splendor.exe m45a-audit --arena-dir local-artifacts/m45a-arena
python scripts/m45a_final_audit.py                     # all hard gates PASS
```

Tracked artifact: `benchmarks/m45a-bonus-vector-information-probe-v1.result.json`.

### P1 — Arena (384 matches, strict n1 shell, seeds 5_800_000..5_800_063, bootstrap seed 44_300_001)

| Arm | Control | W/T/L | Center (bps) | 98.333% CI | Verdict |
|---|---|---|---:|---|---|
| `SHIFT_F4` | `FULL` | 27/0/101 | **2,109.38** | [1,328.12, 3,046.88] | **RESOLVED_BINDING_IMPORTANT** |
| `SHIFT_E2` | `FULL` | 64/2/62 | **5,078.12** | [4,609.38, 5,546.88] | **UNRESOLVED** |
| `SHIFT_F4_E2` | `FULL` | 28/0/100 | **2,187.50** | [1,328.12, 3,099.61] | **RESOLVED_BINDING_IMPORTANT** |

Paired-block score distributions: SHIFT_F4 `{10000.0: 3, 0.0: 40, 5000.0: 21}`; SHIFT_E2 `{0.0: 3, 5000.0: 57, 10000.0: 4}`; SHIFT_F4_E2 `{5000.0: 22, 0.0: 39, 10000.0: 3}`.

### P2 — 180-context behavior audit (authoritative identity, 180/180 reproduction)

| Arm | Disagreement vs FULL | Engine-pivotal flips |
|---|---:|---:|
| `SHIFT_F4` | **43.3%** (78/180) | 15.0% (27/180) |
| `SHIFT_E2` | **1.1%** (2/180) | 0.0% (0/180) |
| `SHIFT_F4_E2` | **43.9%** (79/180) | 15.0% (27/180) |

True-vs-shifted F4 delta distribution (22 distinct values): 88 contexts unchanged, 28 at +100k, plus large tails at ±(4.8M..10.2M) from the max-affordable-prestige term. True-vs-shifted E2 delta distribution (9 values): 53 unchanged, spread over ±10k..60k.

Contexts identity digest: `2d5a024754982ebc9f73453b40ea414857c98318d2449353052bc35a8cbf4dc9`.

### P3 — Residual capacity audit (11,742 unique authoritative-identity contexts)

| Key | Collision groups | Contexts in collisions | H(b\|key) | Mean distinct vectors |
|---|---:|---:|---:|---:|
| `K_path = (C, E2, F4)` | 1,303 / 2,787 groups | **9,670 (82.4%)** | 2.386 bits | 5.03 |
| `K_eval = (F1, CORE, E2, F3, F4)` | 993 / 9,249 groups | **2,800 (23.8%)** | 0.312 bits | 2.40 |

Corpus identity digest: `8254eacabc04d606122d868166edec4ac1df020cba7962bef5b78f129f49cace`.

## Result and Decision

### Q1 — Existing-path binding

**Resolved: correct bonus-color identity through F4 is decisively important.**

- `SHIFT_F4` collapses to 2,109.38 bps (`RESOLVED_BINDING_IMPORTANT`) — scrambling only the color binding inside the affordability path costs ~2,890 bps against FULL.
- `SHIFT_E2` is `UNRESOLVED` (5,078.12 bps, CI straddling 5,000): noble-progress color binding alone shows no resolved strength effect.
- `SHIFT_F4_E2` is also `RESOLVED_BINDING_IMPORTANT` (2,187.50 bps); its point estimate is numerically similar to `SHIFT_F4`'s. M45A did not preregister or perform a direct `SHIFT_F4_E2` vs `SHIFT_F4` contrast, so no formal marginal-effect conclusion about adding the E2 scramble on top of the F4 scramble is licensed.

Cross-experiment observations (descriptive only, no effect-equivalence claims):

- The `SHIFT_F4` point estimate (2,109.38 bps) is numerically close to the historical M44B `DROP_CORE_ENGINE` result (2,187.5 bps). The two come from different milestones, different seed segments, different multiple-comparison setups, and different interventions; this is recorded only as a cross-milestone descriptive observation, not as effect equivalence.
- The contrast with M44A is the more informative comparison: M44A's `DROP_CONVERTIBILITY` (deleting the entire F4 family) was `UNRESOLVED`, while M45A's `SHIFT_F4` (keeping F4's weight but scrambling only its color binding) is resolved at a massive loss. This indicates the finding is not "the F4 family must exist" but rather: *if the evaluator uses a high-weight affordability signal, the color identities inside it must be correct — wrongly-bound color structure can be far more damaging than missing information.*

Licensed wording: *correct bonus-color identity within the current F4 affordability path has resolved conditional playing-strength importance when the remainder of FULL is retained; correct color binding inside noble-progress computation did not show a resolvable conditional effect in this sample.* Not licensed: "F4 is globally beneficial" (M44A family result remains UNRESOLVED), "noble progress is essential" (M44B deletion remains UNRESOLVED), any equivalence between the SHIFT_F4 and DROP_CORE interventions, and any formal conclusion about the E2 scramble's marginal effect conditional on F4 scrambling (no such contrast was preregistered or performed).

### Q2 — Residual representational capacity

**Confirmed: the root-player evaluator progress summary is many-to-one with respect to the bonus vector in the observed corpus.**

- Conditioning on the two color-sensitive path outputs (`C, E2, F4`), 82.4% of contexts still share their key with at least one different bonus vector (mean 5.03 distinct vectors per collision group; conditional entropy 2.386 bits).
- Conditioning on the complete root-player progress summary (`F1, CORE, E2, F3, F4`), 2,800 contexts (23.8%) still carry a bonus vector their summary does not determine (mean 2.40 vectors; conditional entropy 0.312 bits).

This statement is scoped to the root player's progress summary (the five scalar terms), not to the full multi-player evaluator input/output. It is a representation result only. It does not prove the omitted vector information would improve playing strength, and other state variables co-vary inside collision groups. No causal inference from collision statistics.

### Outcome classification (pre-registered exit logic)

**Outcome 1 — binding resolved + residual capacity exists.** Correct color structure already matters through F4, and current summaries still discard vector information. This is the strongest motivation for a future explicit residual vector treatment; a later M45B may design one such channel. M45B is not automatically authorized.

## Known Limitations

1. The scramble is an identity-scramble ablation, not a legal-state evaluation: no inference about reachable alternative bonus vectors is licensed.
2. `SHIFT_E2`'s UNRESOLVED verdict is a non-resolution, not evidence of irrelevance; the E2 weight (10k) is two orders of magnitude smaller than CORE, so a small true effect may be undetectable at this sample size.
3. No direct `SHIFT_F4_E2` vs `SHIFT_F4` contrast was preregistered or performed; overlapping confidence intervals between the two arms do not establish statistical indistinguishability, and no marginal-effect conclusion about the E2 scramble conditional on F4 scrambling is licensed.
4. The cross-experiment numerical proximity of `SHIFT_F4` (2,109.38 bps) to M44B's `DROP_CORE_ENGINE` (2,187.5 bps) is a descriptive observation across different milestones, seed segments, multiple-comparison setups, and interventions — not effect equivalence.
5. P3 collision statistics are observational; co-varying state variables are not controlled.
6. All findings are under the frozen n1 static-successor shell (`max_nodes = 1`).

## Next Authorized Gate

Closure Repair 1 (wording seal) executed in full: all numeric results frozen unchanged, no Arena rerun, no result-JSON modification. Awaiting final closure signature (`APPROVED / COMPLETED_DIAGNOSTIC / CLOSED — PERMANENTLY`).

Post-closure research guidance (from the terminal review): the two headline facts are (a) wrongly-bound color structure entering a high-weight affordability path is extremely dangerous, and (b) current summaries do not fully encode the bonus vector. Any future M45B must therefore define, before anything else, what operational information $R(\mathbf{b} \mid C, E2, F4, \ldots)$ a residual channel represents — explicitly demonstrating it is not a re-encoding of F4 affordability or E2 noble deficit. M45B remains NOT AUTHORIZED.
