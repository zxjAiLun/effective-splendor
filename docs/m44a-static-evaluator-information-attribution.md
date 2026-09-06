# M44A StaticEvaluator Information Attribution

```text
Milestone:      M44A
Title:          StaticEvaluator Information Attribution
Type:           evaluator decomposition / strength attribution
Status:         COMPLETED / CLOSURE_CANDIDATE —
                M44A_INFORMATION_ATTRIBUTION_COMPLETE
                (pending final review)
Tracked Result: benchmarks/m44a-static-evaluator-information-attribution-v1.result.json
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
- 2026-09-05: Implementation completed:
  - `StaticEvaluatorAttributionV1` implemented in `crates/splendor-search/src/attribution.rs` with 4-family masks (F1, F2, F3, F4).
  - CLI flag `--attribution-profile` supported in `agent-determinization` and `analyze-replay-player-view`.
  - P0 semantic tests implemented in `crates/splendor-cli/tests/m44a_p0_semantic.rs`: H0-A utility identity, H0-B root decision identity (12/12 match), H0-C (>=64 reachable states stress), family partition gate (`FULL == F1+F2+F3+F4`), exact mask microfixtures, and zero-progress semantics all passed (6/6).
- 2026-09-05: Arena execution completed: 640 physical matches across 5 pairings, 0 aborts, 0 candidate faults.
- 2026-09-05: Common-state action audit & family margin decomposition executed across 200 unique decision contexts. 200/200 source actions reproduced. Linearity identity verified bit-exact.
- 2026-09-05: Final exhaustive audit passed (1,280 lineup checks, 640 rotation checks, 640 replay verifications). Tracked result artifact sealed at `benchmarks/m44a-static-evaluator-information-attribution-v1.result.json`.

## Final implementation

- Evaluator: `crates/splendor-search/src/attribution.rs` (`StaticEvaluatorAttributionV1`, `AttributionProfile`, `FamilyProgress`).
- Imperfect search integration: `crates/splendor-imperfect-search/src/search.rs` (`aggregate_root_determinizations_attribution_v1`), `crates/splendor-imperfect-search/src/player_view.rs` (`analyze_player_view_attribution_v1`).
- Agent policy: `crates/splendor-determinization-agent/src/lib.rs` (`DeterminizationAgentAttributionPolicyV1`).
- CLI integration: `crates/splendor-cli/src/arena_command.rs`, `crates/splendor-cli/src/imperfect_search_command.rs`.
- P0 test suite: `crates/splendor-cli/tests/m44a_p0_semantic.rs`.
- Scripts: `scripts/m44a_orchestrator.py`, `scripts/m44a_common_state_audit.py`, `scripts/m44a_final_audit.py`.
- Tracked result: `benchmarks/m44a-static-evaluator-information-attribution-v1.result.json`.

## Validation and evidence

### 1. P0 Semantic & Invariant Gates (All 6 Passed)

- **H0-A (Utility identity)**: Bit-for-bit utility equality across non-terminal and terminal states (`StaticEvaluatorAttributionV1(FULL) == StaticEvaluatorV1`).
- **H0-B (Root decision identity)**: 12 / 12 exact action and aggregate utility equality against `det-s4-d1-n1`.
- **H0-C (Reachable-state stress test)**: 120 reachable non-terminal states evaluated with bit-for-bit utility equality ($\ge 64$ gate PASS).
- **Family Partition Gate**: `FULL progress == F1 + F2 + F3 + F4` exact integer equality across all states and players.
- **Exact Mask Microfixtures**: Hand-calculated fixtures where each family contributes independently (prestige for F1, bonuses/cards for F2, tokens/gold/reserves for F3, affordability for F4) asserting expected integer utility delta.
- **Zero-Progress Semantics**: Non-terminal utilities strictly `[0, 0]`, terminal equals `terminal_rank_base(rank)` ($1,000,000,000,000$).

### 2. 640-Match Arena Family Attribution Results

64 paired seed blocks (`5_500_000 .. 5_500_063`) $\times$ 2 seat rotations = 128 physical matches per pairing. 0 aborts, 0 candidate faults. Exhaustive audit recorded in `benchmarks/m44a-static-evaluator-information-attribution-v1.result.json`.

| Candidate Arm | Control Arm | Matches | W / T / L | Center Score (bps) | CI Level | Bootstrap CI (bps) | Formal Verdict | Seat 0 / 1 (bps) | Mean Plies |
|---|---|---:|:---:|---:|:---:|:---:|:---:|:---:|---:|
| `DROP_SCORE` (F1) | `FULL` | 128 | 17 / 0 / 111 | **1,328.1** | 98.75% | [703.1, 2,031.2] | **RESOLVED_SENSITIVE** | 1093.8 / 1562.5 | 60.5 |
| `DROP_ENGINE` (F2) | `FULL` | 128 | 24 / 0 / 104 | **1,875.0** | 98.75% | [1,093.8, 2,656.2] | **RESOLVED_SENSITIVE** | 1875.0 / 1875.0 | 60.9 |
| `DROP_LIQUIDITY` (F3) | `FULL` | 128 | 65 / 1 / 62 | **5,117.2** | 98.75% | [3,945.3, 6,289.1] | **UNRESOLVED** | 5390.6 / 4843.8 | 61.5 |
| `DROP_CONVERTIBILITY` (F4) | `FULL` | 128 | 77 / 0 / 51 | **6,015.6** | 98.75% | [4,921.9, 7,109.4] | **UNRESOLVED** | 6562.5 / 5468.8 | 58.8 |
| `ZERO_PROGRESS` | `FULL` | 128 | 7 / 0 / 121 | **546.9** | 95.00% | [234.4, 937.5] | **RESOLVED_SENSITIVE** | 156.2 / 937.5 | 62.1 |

*Family drops use Bonferroni-adjusted $\alpha = 0.05 / 4 \to$ 98.75% two-sided bootstrap CI; ZERO_PROGRESS uses standard 95% CI. 10,000 resamples, seed 44_270_001.*

### 3. Post-Hoc Common-State Audit (200 Authoritative Contexts)

- **Contexts Identity Digest**: `122f3d825bdabb59604552ea00383d5db0886f66bd4019a75ce1932b5ebb53ad` (200 unique contexts).
- **Source Action Reproduction**: **200 / 200 (100.0% PASS)** on matching source agent profiles.
- **Disagreement Rates vs FULL**:
  - `DROP_SCORE vs FULL`: **19.0%** (38 / 200)
  - `DROP_ENGINE vs FULL`: **16.5%** (33 / 200)
  - `DROP_LIQUIDITY vs FULL`: **6.0%** (12 / 200)
  - `DROP_CONVERTIBILITY vs FULL`: **60.0%** (120 / 200)
  - `ZERO_PROGRESS vs FULL`: **81.5%** (163 / 200)
- **Standalone Family Agreement with FULL (`ONLY_*`)**:
  - `ONLY_SCORE`: 32.0% (64 / 200)
  - `ONLY_ENGINE`: 18.5% (37 / 200)
  - `ONLY_LIQUIDITY`: 11.5% (23 / 200)
  - `ONLY_CONVERTIBILITY`: 60.0% (120 / 200)

### 4. Family Margin Decomposition ($a^*$ Best vs $b^*$ Runner-up)

Exact linearity identity verified across 100% of audited states:
$$\text{FULL margin} = \text{terminal margin} + \text{F1 margin} + \text{F2 margin} + \text{F3 margin} + \text{F4 margin}$$

| Information Family | Mean Margin Contribution | Median Margin | Mean Absolute Contribution | p90 Absolute Contribution | Positive Sign Rate | Zero Rate |
|---|---:|---:|---:|---:|---:|---:|
| **F1 (REALIZED_SCORE)** | +88,000,000.0 | 0.0 | 88,000,000.0 | 400,000,000.0 | 17.5% | 82.5% |
| **F2 (PERMANENT_ENGINE)** | +1,087,000.0 | 0.0 | 2,445,800.0 | 9,044,000.0 | 23.0% | 66.5% |
| **F3 (LIQUIDITY_OPTIONALITY)** | -68,400.0 | 0.0 | 126,000.0 | 400,000.0 | 19.0% | 48.5% |
| **F4 (IMMEDIATE_CONVERTIBILITY)** | -1,381,000.0 | 0.0 | 9,692,000.0 | 27,510,000.0 | 46.0% | 27.5% |
| **Terminal Rank** | 0.0 | 0.0 | 0.0 | 0.0 | 0.0% | 100.0% |
| **FULL (Net Total)** | **+87,637,600.0** | **+400,000.0** | **87,637,600.0** | **379,916,000.0** | **75.5%** | **24.5%** |

## Result and decision

1. **`ZERO_PROGRESS` is decisively weaker than `FULL` (RESOLVED_SENSITIVE, 546.9 bps, 95% CI: [234.4, 937.5])**:
   Removing all non-terminal progress terms collapses playing strength to 7 wins vs 121 losses. This definitively proves that `StaticEvaluatorV1`'s non-terminal progress terms as a whole provide the decisive playing strength in the `n1` shell beyond exact root simulation and terminal outcomes.
2. **`F1 (REALIZED_SCORE)` is conditionally critical (RESOLVED_SENSITIVE, 1,328.1 bps, 98.75% CI: [703.1, 2031.2])**:
   Ablating victory point tracking collapses playing strength to 17 wins vs 111 losses. In the margin decomposition, F1 provides massive margin swings (+88M mean) whenever prestige-earning actions are available (17.5% of states).
3. **`F2 (PERMANENT_ENGINE)` is conditionally critical (RESOLVED_SENSITIVE, 1,875.0 bps, 98.75% CI: [1093.8, 2656.2])**:
   Ablating permanent bonuses, cards, and noble progress collapses playing strength to 24 wins vs 104 losses. F2 provides continuous positive gradient (+1.09M mean margin, positive in 23% of states) driving mid-game engine building.
4. **`F3 (LIQUIDITY_OPTIONALITY)` is conditionally redundant / UNRESOLVED (5,117.2 bps, 98.75% CI: [3945.3, 6289.1])**:
   Removing token and reserve counts produces nearly dead-even play (65 wins vs 62 losses). When F1, F2, and F4 remain active, liquidity tracking has minimal conditional contribution.
5. **`F4 (IMMEDIATE_CONVERTIBILITY)` is UNRESOLVED with positive point estimate (6,015.6 bps, 98.75% CI: [4921.9, 7109.4])**:
   Removing affordability terms shows a 77W / 51L advantage over FULL (though crossing 5000 at 98.75% Bonferroni level). The margin decomposition shows negative average contribution (-1.38M), suggesting potential interference or distortion between short-term affordability and long-term permanent engine incentives.

## Known limitations

1. M44A performed coarse family-level attribution; individual terms within F2 (`bonuses` vs `purchased_cards` vs `nobles`) and F4 (`affordable_count` vs `max_prestige`) remain un-isolated.
2. Attribution was measured strictly under the frozen `n1` static-successor decision shell; interaction with deeper search (M07 `n2000`) was not evaluated in this round.

## Next authorized gate

M44A coarse attribution is complete.
Awaiting final review for M44A closure.
Next authorized milestone direction:
- **M44B — Engine & Convertibility Refinement**: Fine-grained attribution isolating terms within the sensitive F2 family (bonuses vs cards vs nobles) and investigating whether F4 convertibility interferes with engine building.
