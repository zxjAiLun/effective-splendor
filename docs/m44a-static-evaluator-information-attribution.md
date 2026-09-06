# M44A StaticEvaluator Information Attribution

```text
Milestone:      M44A
Title:          StaticEvaluator Information Attribution
Type:           evaluator decomposition / strength attribution
Status:         DESIGN_FROZEN / IN_PROGRESS — P0+ARENA AUTHORIZED
Baseline:       1117e0a (M43A permanent closure)
Design:         DESIGN_V1 / FROZEN
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE
Model Training: NONE
Weight Tuning:  NONE
Individual 9:   NOT AUTHORIZED (coarse family attribution only)
M44B:           NOT AUTHORIZED
Depth-2 / MCTS: OUT OF SCOPE
```

## Problem and evidence

M42S established that the static-successor baseline `n1` is overwhelmingly superior to direct neural policies (`n1 vs d2-direct` scored 8,203.1 bps, 95% CI: [7500.0, 8906.2], 105W / 0T / 23L), while M07 continuation search over `n1` was statistically unresolved. M43A then proved that externalizing transition physics to the simulator alone is insufficient when using an un-guided binary win/loss value model ($BSS = +0.0187 < +0.05$).

This isolates the central scientific question:
> **Within the already-validated `n1` static-successor shell, which broad semantic information families in `StaticEvaluatorV1` materially affect playing strength?**

M44A does not ask which individual coefficient is mathematically most important, nor does it tune evaluator weights. It partitions the 9 non-terminal terms into 4 semantic families to measure conditional importance while avoiding individual collinear leave-one-out masking.

## Information families and partition

`StaticEvaluatorV1` contains exactly 9 non-terminal progress terms and a terminal rank base. The 9 terms are partitioned into 4 disjoint families:

- **F1 (REALIZED_SCORE)**:
  - `prestige` (weight 100,000,000)
  - Meaning: Progress already converted into actual victory points.
- **F2 (PERMANENT_ENGINE)**:
  - `total permanent bonuses` (weight 2,000,000)
  - `purchased card count` (weight 250,000)
  - `noble progress` (weight 10,000)
  - Meaning: Long-lived engine development and permanent future scoring potential.
- **F3 (LIQUIDITY_OPTIONALITY)**:
  - `colored token count` (weight 20,000)
  - `gold token count` (weight 40,000)
  - `reserved card count` (weight 10,000)
  - Meaning: Resources and options currently held but not yet converted into purchases.
- **F4 (IMMEDIATE_CONVERTIBILITY)**:
  - `affordable card count` (weight 100,000)
  - `maximum affordable prestige` (weight 5,000,000)
  - Meaning: What the player can convert into purchases immediately in the current state.

**Terminal rank base** (`TERMINAL_RANK_UNIT = 1,000,000,000_000`) is never ablated in any arm.

## Evaluator profiles

1. **Primary Arena Arms**:
   - `FULL`: Control arm (all 4 families active, bit-exact identical to `StaticEvaluatorV1`).
   - `DROP_SCORE`: F1 ablated; F2, F3, F4 active.
   - `DROP_ENGINE`: F2 ablated; F1, F3, F4 active.
   - `DROP_LIQUIDITY`: F3 ablated; F1, F2, F4 active.
   - `DROP_CONVERTIBILITY`: F4 ablated; F1, F2, F3 active.
   - `ZERO_PROGRESS`: All 4 families ablated; only terminal rank base remains.
2. **Offline Diagnostic Profiles** (for post-hoc common-state audit only):
   - `ONLY_SCORE` (F1 only)
   - `ONLY_ENGINE` (F2 only)
   - `ONLY_LIQUIDITY` (F3 only)
   - `ONLY_CONVERTIBILITY` (F4 only)

## Evaluation shell

All arms use the exact `n1` static-successor decision shell:
- `sample_seed = 20_260_703`
- `sample_count = 4`
- Force every canonical legal root action
- Evaluate resulting child state with the masked evaluator
- Average utilities across 4 determinizations
- Canonical argmax (first-max tie breaking)
- Zero continuation search nodes (`max_depth_turns = 1, max_nodes = 1`)

## Arena matrix and statistical protocol

- **Seeds**: 64 paired blocks (`5_500_000 .. 5_500_063`), disjoint from all previous milestones.
- **Rotations**: 2 seat rotations per block (r0, r1).
- **Pairings** (5 pairings, each 128 physical matches, 640 matches total):
  1. `DROP_SCORE` vs `FULL`
  2. `DROP_ENGINE` vs `FULL`
  3. `DROP_LIQUIDITY` vs `FULL`
  4. `DROP_CONVERTIBILITY` vs `FULL`
  5. `ZERO_PROGRESS` vs `FULL`
- **Statistical Unit**: Paired seed block.
- **Bootstrap Uncertainty**:
  - `BOOTSTRAP_SEED = 44_270_001`, 10,000 resamples.
  - Four family drops: Bonferroni-adjusted $\alpha = 0.05 / 4 = 0.0125 \to$ **98.75% two-sided bootstrap CI**.
  - `ZERO_PROGRESS`: Standard **95% two-sided bootstrap CI**.

## Decision rules

5,000 bps = equality.
- For each family drop (`DROP_* vs FULL`):
  - **`RESOLVED_SENSITIVE`**: Upper 98.75% CI < 5,000 bps (removing this family causes a statistically resolved loss).
  - **`RESOLVED_HARMFUL_OR_INTERFERING`**: Lower 98.75% CI > 5,000 bps (removing this family improves strength).
  - **`UNRESOLVED`**: 98.75% CI crosses 5,000 bps.
- For `ZERO_PROGRESS vs FULL`:
  - Upper 95% CI < 5,000 bps: Non-terminal progress evaluator as a whole provides statistically resolved playing strength beyond root simulation and terminal outcomes.

## P0 semantic test gates

Before Arena execution:
- **H0-A (Utility identity)**: `StaticEvaluatorAttributionV1(FULL) == StaticEvaluatorV1` bit-for-bit across non-terminal and terminal states.
- **H0-B (Root decision identity)**: On frozen M07 12-position corpus, `FULL` vs `det-s4-d1-n1` produces exact 12/12 identical actions and aggregate utilities.
- **H0-C (Reachable-state stress test)**: $\ge 64$ deterministic reachable states with bit-for-bit utility equality.
- **Family Partition Gate**: `FULL progress == F1 + F2 + F3 + F4` exact integer equality. Each term occurs in exactly one family.
- **Exact Mask Microfixtures**: Hand-calculated fixtures where each family contributes independently, asserting expected integer utility delta.
- **Zero-Progress Semantics**: Non-terminal utility is strictly `[0, 0]`; terminal utility equals `terminal_rank_base(rank)`.

## Post-hoc common-state audit

On up to 200 unique decision contexts (identified by authoritative `observation_hash, visible_history_hash, information_set_hash`):
1. Action disagreement rates relative to `FULL` for all profiles.
2. Family margin decomposition:
   $$Q_F(a^*) - Q_F(b^*)$$
   where $a^*$ is `FULL`'s best action, $b^*$ is `FULL`'s second-best action, decomposing the exact integer margin into terminal, F1, F2, F3, and F4 contributions.

## Implementation plan

1. Implement `StaticEvaluatorAttributionV1` in Rust with 4-family masks and CLI support in `splendor-cli` / `splendor-determinization-agent`.
2. Implement and run P0 test suite (`crates/splendor-cli/tests/m44a_p0_semantic.rs`).
3. Implement `scripts/m44a_orchestrator.py` for 640 matches with 98.75% / 95% bootstrap CIs.
4. Execute 640 Arena matches.
5. Implement and execute post-hoc common-state audit and family margin decomposition.
6. Generate tracked result JSON `benchmarks/m44a-static-evaluator-information-attribution-v1.result.json` and verification audit script `scripts/m44a_final_audit.py`.
7. Finalize docs, update `handoff.md`, run tests, commit, and push.

## Iteration log

- 2026-09-05: M44A Design v1 frozen and authorized by reviewer. Focuses strictly on 4-family coarse attribution within the validated n1 shell. P0 and 640-match Arena authorized upon P0 pass.
