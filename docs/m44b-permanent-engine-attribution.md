# M44B Permanent Engine Attribution

```text
Milestone:      M44B
Title:          Permanent Engine Attribution
Type:           evaluator sub-family attribution
Status:         DESIGN_FROZEN / IN_PROGRESS — P0+ARENA AUTHORIZED
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
