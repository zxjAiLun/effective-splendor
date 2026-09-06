# M44B Permanent Engine Attribution

```text
Milestone:      M44B
Title:          Permanent Engine Attribution
Type:           evaluator sub-family attribution
Status:         COMPLETED / CLOSURE_CANDIDATE —
                M44B_PERMANENT_ENGINE_ATTRIBUTION_COMPLETE
                (pending final review)
Tracked Result: benchmarks/m44b-permanent-engine-attribution-v1.result.json
Baseline:       4d83b3f (M44A permanent closure)
Design:         DESIGN_V1 / FROZEN
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE
Model Training: NONE
Weight Tuning:  NONE
Bonus vs Card:  NOT AUTHORIZED (coarse E1 vs E2 attribution only)
F4 Experiment:  NOT AUTHORIZED (backlog only)
M44C:           NOT AUTHORIZED
Depth-2 / MCTS: OUT OF SCOPE
```

## Problem and evidence

M44A established that inside `StaticEvaluatorV1`, the `F2_PERMANENT_ENGINE` family is conditionally critical:
`DROP_ENGINE vs FULL` collapsed to **1,875.0 bps** (98.75% CI: `[1093.8, 2656.2]`, 24W / 0T / 104L, `RESOLVED_SENSITIVE`).

`F2_PERMANENT_ENGINE` is defined as:
$$\text{F2} = \text{total\_permanent\_bonuses} \times 2,000,000 + \text{purchased\_card\_count} \times 250,000 + \text{noble\_progress} \times 10,000$$

M44B asks:
> **Inside the already-resolved-sensitive F2 `PERMANENT_ENGINE` family, is the conditional strength contribution primarily associated with basic permanent economic development (CORE_ENGINE), noble-progress information (NOBLE_PROGRESS), or both?**

## Subfamily partition

F2 is partitioned into two disjoint subfamilies:
- **E1 (CORE_ENGINE)**:
  - `total_permanent_bonuses` (weight 2,000,000)
  - `purchased_card_count` (weight 250,000)
  - Meaning: Permanent economic development already acquired by purchasing cards.
- **E2 (NOBLE_PROGRESS)**:
  - `noble_progress` (weight 10,000)
  - Meaning: How close the permanent bonus vector is to satisfying available nobles.

**Partition Invariant**:
$$\text{F2\_ENGINE} \equiv \text{CORE\_ENGINE} + \text{NOBLE\_PROGRESS}$$
$$\text{FULL} \equiv \text{F1} + \text{CORE\_ENGINE} + \text{NOBLE\_PROGRESS} + \text{F3} + \text{F4}$$
Exact integer equality for every state and player. No coefficient changes.

## Evaluator profiles

1. **Primary Arena Profiles**:
   - `FULL`: Control arm (all families active, bit-exact identical to `StaticEvaluatorV1`).
   - `DROP_CORE_ENGINE`: `FULL - CORE_ENGINE` (retains F1, NOBLE_PROGRESS, F3, F4).
   - `DROP_NOBLE_PROGRESS`: `FULL - NOBLE_PROGRESS` (retains F1, CORE_ENGINE, F3, F4).
2. **Offline-Only Profiles** (for common-state audit and margin decomposition):
   - `ONLY_CORE_ENGINE`
   - `ONLY_NOBLE_PROGRESS`

Terminal rank base remains frozen and non-ablatable.

## Evaluation shell

All arms use the validated `n1` static-successor shell:
- `sample_seed = 20_260_703`
- `sample_count = 4`
- `max_depth_turns = 1`
- `max_nodes = 1`
- Enumerate canonical legal root actions $\to$ force action $\to$ evaluate child with attribution profile $\to$ average across 4 samples $\to$ canonical first-max argmax.

## Arena matrix and statistical protocol

- **Seeds**: 64 paired blocks (`5_600_000 .. 5_600_063`), disjoint from all previous milestones.
- **Rotations**: 2 seat rotations per block (r0, r1).
- **Pairings** (2 pairings, each 128 physical matches, 256 matches total):
  1. `DROP_CORE_ENGINE` vs `FULL`
  2. `DROP_NOBLE_PROGRESS` vs `FULL`
- **Statistical Unit**: Paired seed block.
- **Bootstrap Uncertainty**:
  - `BOOTSTRAP_SEED = 44_280_001`, 10,000 resamples.
  - Bonferroni-adjusted $\alpha = 0.05 / 2 = 0.025 \to$ **97.5% two-sided bootstrap CI**.

## Decision rules

5,000 bps = equality.
For each subfamily drop (`DROP_* vs FULL`):
- **`RESOLVED_SENSITIVE`**: Upper 97.5% CI < 5,000 bps (removing this subfamily causes a statistically resolved loss).
- **`RESOLVED_HARMFUL_OR_INTERFERING`**: Lower 97.5% CI > 5,000 bps.
- **`UNRESOLVED`**: 97.5% CI crosses 5,000 bps.

## P0 semantic test gates

Before Arena execution:
- **Regression Gate**: `cargo test --test m44a_p0_semantic` passes, preserving all existing M44A profiles.
- **Subfamily Partition Gate**: Across $\ge 96$ reachable non-terminal states in isolated namespace `6_100_000 ..`:
  `F2_ENGINE == CORE_ENGINE + NOBLE_PROGRESS` and `FULL == F1 + CORE + NOBLE + F3 + F4` exact integer equality.
- **Exact Microfixtures**:
  - Purchased-count fixture: delta purchased count changes without bonus changes $\to$ $\Delta\text{CORE} = \Delta\text{purchased} \times 250,000$, $\Delta\text{NOBLE} = 0$.
  - Bonus component fixture: delta bonus changes $\to$ $\Delta\text{bonus} = \Delta\text{bonus\_sum} \times 2,000,000$, $\Delta\text{F2} == \Delta\text{CORE} + \Delta\text{NOBLE}$.
  - Noble-progress fixture: hand-calculated expected noble progress $\times 10,000 == \text{NOBLE\_PROGRESS}$, $\text{DROP\_NOBLE\_PROGRESS} == \text{FULL} - \text{NOBLE\_PROGRESS}$.
- **Profile Mask Identity**:
  `DROP_CORE_ENGINE progress == FULL - CORE_ENGINE`
  `DROP_NOBLE_PROGRESS progress == FULL - NOBLE_PROGRESS`

## Post-hoc common-state audit

On exactly 200 unique decision contexts (identified by authoritative `observation_hash, visible_history_hash, information_set_hash`):
- Balanced sampling: 100 from `DROP_CORE_ENGINE vs FULL`, 100 from `DROP_NOBLE_PROGRESS vs FULL`.
- Source action reproduction: 200 / 200 PASS fail-closed.
- Profiles evaluated: `FULL`, `DROP_CORE_ENGINE`, `DROP_NOBLE_PROGRESS`, `ONLY_CORE_ENGINE`, `ONLY_NOBLE_PROGRESS`.
- Exact F2 margin decomposition: $\text{margin}_{\text{F2}} \equiv \text{margin}_{\text{CORE}} + \text{margin}_{\text{NOBLE}}$.

## Implementation plan

1. Design-only commit: commit `docs/m44b-permanent-engine-attribution.md` and update `handoff.md`.
2. Implement 4 new profiles in Rust attribution modules.
3. Implement and run P0 test suite (`crates/splendor-cli/tests/m44b_p0_semantic.rs`).
4. Implement `scripts/m44b_orchestrator.py` for 256 matches with 97.5% bootstrap CIs.
5. Execute 256 Arena matches.
6. Implement and execute balanced 200-context post-hoc common-state audit and F2 margin decomposition.
7. Generate tracked result JSON `benchmarks/m44b-permanent-engine-attribution-v1.result.json` and verification audit script `scripts/m44b_final_audit.py`.
8. Finalize docs, update `handoff.md`, run tests, commit, and push.

## Iteration log

- 2026-09-05: M44B Design v1 frozen and authorized by reviewer. Focuses strictly on 2-subfamily F2 attribution (CORE_ENGINE vs NOBLE_PROGRESS) within the validated n1 shell across 256 matches.
- 2026-09-05: Implementation & P0 tests complete:
  - 4 research profiles implemented in `crates/splendor-search/src/attribution.rs` (`DROP_CORE_ENGINE`, `DROP_NOBLE_PROGRESS`, `ONLY_CORE_ENGINE`, `ONLY_NOBLE_PROGRESS`).
  - M44A regression suite passed (6/6).
  - M44B P0 semantic suite passed in `crates/splendor-cli/tests/m44b_p0_semantic.rs` (4/4): F2 partition gate (`F2 == CORE + NOBLE` across 140 reachable states), purchased-count component fixture, permanent-bonus component fixture, noble-progress hand-calculated deficit fixture, profile mask identities.
- 2026-09-05: 256 Arena matches completed across 2 pairings (0 aborts, 0 faults).
- 2026-09-05: Post-hoc balanced 200-context audit executed (100 from DROP_CORE_ENGINE, 100 from DROP_NOBLE_PROGRESS). Source action reproduction 200/200 PASS. Exact F2 margin linearity identity verified bit-exact.
- 2026-09-05: Final exhaustive audit passed (512 lineup checks, 256 rotation checks, 256 replay verifications). Tracked result artifact sealed at `benchmarks/m44b-permanent-engine-attribution-v1.result.json`.
- 2026-09-05 (Closure Repair 1):
  - In `scripts/m44b_common_state_audit.py`, added independent `only_engine` profile evaluation to verify action-margin linearity: $\text{margin}_{\text{F2}} \equiv \text{margin}_{\text{CORE}} + \text{margin}_{\text{NOBLE}}$ verified bit-exact on 200/200 contexts. Maintained canonical context identity digest `acd36162…`.
  - P0 terminal test tightened in `crates/splendor-cli/tests/m44b_p0_semantic.rs` to assert exact `terminal_rank_base(rank)` ($\pm 1,000,000,000,000$) on zero-progress profile and exact relative progress delta on masked profiles.
  - Regenerated tracked result artifact `benchmarks/m44b-permanent-engine-attribution-v1.result.json` with 100/100 balanced composition assertion.
  - Synchronized documentation table values to exact tracked result JSON: CORE seat 0/1 = `1718.75 / 2656.25`, mean plies = `63.3`; NOBLE seat 0/1 = `5859.38 / 4453.12`, mean plies = `60.9`.
  - Refined margin wording: CORE_ENGINE accounts for ~99.3% of F2's descriptive signed mean top-two margin in the audited 200-context sample (+1.08M out of +1.087M), without extrapolating to a causal playing-strength share.

## Final implementation

- Evaluator: `crates/splendor-search/src/attribution.rs` (extended with `e1_core_engine` and `e2_noble_progress`, 4 new attribution profiles).
- P0 test suite: `crates/splendor-cli/tests/m44b_p0_semantic.rs` (4 tests).
- Scripts: `scripts/m44b_orchestrator.py`, `scripts/m44b_common_state_audit.py`, `scripts/m44b_final_audit.py`.
- Tracked result: `benchmarks/m44b-permanent-engine-attribution-v1.result.json`.

## Validation and evidence

### 1. P0 Semantic & Invariant Gates (All Passed)

- **M44A Regression Gate**: `cargo test --test m44a_p0_semantic` (6/6 passed, 0 regressions in existing M44A profiles).
- **Subfamily Partition Gate**: 140 reachable non-terminal states evaluated across 2p, 3p, 4p in isolated namespace `6_100_000..`:
  `F2_ENGINE == CORE_ENGINE + NOBLE_PROGRESS` exact integer equality ($\ge 96$ gate PASS).
  `FULL == F1 + CORE_ENGINE + NOBLE_PROGRESS + F3 + F4` exact integer equality.
- **CORE_ENGINE Exact Microfixtures**:
  - Purchased-count fixture: delta purchased count changes by 3 without bonus change $\to$ $\Delta\text{CORE} = 750,000$ exact, $\Delta\text{NOBLE} = 0$.
  - Bonus component fixture: delta bonus changes by 3 $\to$ $\Delta\text{bonus} = 6,000,000$ exact, $\Delta\text{F2} == \Delta\text{CORE} + \Delta\text{NOBLE}$ verified.
- **NOBLE_PROGRESS Exact Fixture**: Hand-calculated noble progress against 3 nobles with deficit evaluation $\to$ `expected_noble_score == NOBLE_PROGRESS` exact integer match ($10,000 \times \text{progress}$).
- **Profile Mask Identities**:
  `DROP_CORE_ENGINE == FULL - CORE_ENGINE`
  `DROP_NOBLE_PROGRESS == FULL - NOBLE_PROGRESS`
  Terminal rank base verified non-ablatable.

### 2. 256-Match Arena Subfamily Attribution Results

64 paired seed blocks (`5_600_000 .. 5_600_063`) $\times$ 2 seat rotations = 128 physical matches per pairing. 0 aborts, 0 candidate faults. Exhaustive audit recorded in `benchmarks/m44b-permanent-engine-attribution-v1.result.json`.

| Candidate Arm | Control Arm | Matches | W / T / L | Center Score (bps) | CI Level | Bootstrap CI (bps) | Formal Verdict | Seat 0 / 1 (bps) | Mean Plies |
|---|---|---:|:---:|---:|:---:|:---:|:---:|---:|---:|
| `DROP_CORE_ENGINE` (E1) | `FULL` | 128 | 28 / 0 / 100 | **2,187.5** | 97.5% | [1,484.4, 2,968.8] | **RESOLVED_SENSITIVE** | 1718.75 / 2656.25 | 63.3 |
| `DROP_NOBLE_PROGRESS` (E2) | `FULL` | 128 | 65 / 2 / 61 | **5,156.2** | 97.5% | [4,765.6, 5,625.0] | **UNRESOLVED** | 5859.38 / 4453.12 | 60.9 |

*Bonferroni-adjusted $\alpha = 0.05 / 2 = 0.025 \to$ 97.5% two-sided bootstrap CI. 10,000 resamples, seed 44_280_001.*

### 3. Post-Hoc Balanced Common-State Audit (200 Authoritative Contexts)

- **Contexts Identity Digest**: `acd36162addb0d90be273e515436e9cd2b840962fd1e7134d8e2c5437cc5f4f3` (200 unique contexts).
- **Sample Composition**: Exactly 100 unique contexts from `DROP_CORE_ENGINE vs FULL` and 100 unique contexts from `DROP_NOBLE_PROGRESS vs FULL` (contributing replays: 14; recorded profiles: 51 drop_core_engine, 52 drop_noble_progress, 97 full).
- **Source Action Reproduction**: **200 / 200 (100.0% PASS)** on matching source agent profiles.
- **Disagreement Rates vs FULL**:
  - `DROP_CORE_ENGINE vs FULL`: **20.0%** (40 / 200 contexts differ)
  - `DROP_NOBLE_PROGRESS vs FULL`: **1.0%** (only 2 / 200 contexts differ)
- **Standalone Subfamily Agreement with FULL (`ONLY_*`)**:
  - `ONLY_CORE_ENGINE`: 15.0% (30 / 200)
  - `ONLY_NOBLE_PROGRESS`: 15.0% (30 / 200)

### 4. F2 Margin Decomposition ($a^*$ Best vs $b^*$ Runner-up)

Exact linearity identity verified across 100% of audited states:
$$\text{margin}_{\text{F2}} \equiv \text{margin}_{\text{CORE}} + \text{margin}_{\text{NOBLE}}$$

| Subfamily | Mean Margin Contribution | Median Margin | Mean Absolute Contribution | p90 Absolute Contribution | Positive Sign Rate | Zero Rate |
|---|---:|---:|---:|---:|---:|---:|
| **E1 (CORE_ENGINE)** | **+1,080,000.0** | 0.0 | 1,710,000.0 | 9,000,000.0 | 15.5% | 81.0% |
| **E2 (NOBLE_PROGRESS)** | **+7,400.0** | 0.0 | 19,800.0 | 80,000.0 | 22.0% | 65.5% |
| **F2 (Total Net)** | **+1,087,400.0** | 0.0 | 1,729,800.0 | 9,040,000.0 | 24.5% | 63.0% |

## Result and decision

### Ruling: Case A Confirmed
- `DROP_CORE_ENGINE < FULL` is **RESOLVED_SENSITIVE** (Upper 97.5% CI = 2,968.8 < 5,000 bps).
- `DROP_NOBLE_PROGRESS vs FULL` is **UNRESOLVED** (97.5% CI: [4,765.6, 5,625.0] crosses 5,000 bps).
- Pre-registered Case A applies:
  $$\boxed{\textbf{CORE\_ENGINE RESOLVED\_SENSITIVE / NOBLE\_PROGRESS UNRESOLVED}}$$

### Scientific Interpretation
1. **The resolved conditional importance of F2 is concentrated in `CORE_ENGINE`**:
   Removing permanent bonuses and purchased card count while retaining noble progress (and F1/F3/F4) causes a severe, statistically resolved collapse in playing strength to 2,187.5 bps (28W / 0T / 100L).
2. **`NOBLE_PROGRESS` conditional effect is UNRESOLVED**:
   Removing noble progress while retaining core engine (and F1/F3/F4) produces 65 wins to 61 losses (5,156.2 bps), indistinguishable from equality at the 97.5% level.
3. **Margin Decomposition Insight**:
   In the audited 200-context sample, `CORE_ENGINE` accounts for **99.3%** of F2's descriptive signed mean top-two margin contribution (+1.08M out of +1.087M). Dropping noble progress changes only 1.0% of decisions in this balanced audit sample. Note: this signed margin percentage is a descriptive sample property and is not a causal claim about playing-strength share.
4. **Disciplined Boundaries**:
   - Allowed: `CORE_ENGINE` is resolved-sensitive conditional on the rest of the frozen evaluator.
   - Allowed: `NOBLE_PROGRESS` conditional effect is unresolved.
   - Not allowed: Noble progress is useless (unresolved $\ne$ useless).
   - Not allowed: Permanent bonuses are the real source (bonuses vs purchased cards not yet isolated).

## Known limitations

1. M44B evaluated `CORE_ENGINE` as a joint economic unit; the independent contribution of `permanent_bonuses` vs `purchased_card_count` remains un-isolated.
2. All measurements were conducted under the frozen `n1` static-successor shell with `StaticEvaluatorV1` weights.

## Next authorized gate

M44B is complete.
Awaiting final review for M44B closure.
Next authorized milestone direction:
- **M44C — Core Engine Decomposition**: Isolating `permanent_bonuses` (weight 2,000,000) vs `purchased_card_count` (weight 250,000) within the resolved-sensitive `CORE_ENGINE` unit.
