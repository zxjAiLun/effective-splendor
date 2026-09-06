# M45A Bonus-Vector Information Probe

```text
Milestone:      M45A
Title:          Bonus-Vector Information Probe
Type:           evaluator color-identity binding probe & residual capacity audit
Status:         AUTHORIZED / IN_PROGRESS
Starting point: 99872f0 — M44C permanently closed
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
- Formal meaning: if collision groups exist, M45A may conclude the current static evaluator is many-to-one with respect to the player's full bonus vector; some color-structure information remains unrepresented even after conditioning on its current scalar progress summaries. This is a **representation result**. It does NOT prove the omitted vector information would improve playing strength; other game-state variables can co-vary inside those groups; no causal inference from collision statistics.

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

(to be appended during execution)

## Validation and Evidence

(to be filled at round completion with exact commands, results, and artifact hashes)

## Result and Decision

(to be filled at round completion)

## Known Limitations

(to be filled at round completion)

## Next Authorized Gate

Cloud final review of the tracked result artifact and documentation after execution completes.
