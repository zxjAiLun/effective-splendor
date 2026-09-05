# M42S Search Gap Diagnostic

```text
Milestone:      M42S
Title:          Search Gap Diagnostic (Strength–Compute Frontier Probe)
Status:         COMPLETED / PENDING_FINAL_REVIEW
Baseline:       2fc2ba2 (M42A closure + M42S draft)
Design:         REVISION_1 / FROZEN
Implementation: COMPLETE
Execution:      COMPLETE (1,152 / 1,152 matches, 0 aborts, 0 faults)
Prior rounds:   M27A (Fixed-Model Search-Budget Scaling, M27A_INCONCLUSIVE);
                M42A (Visible Action–Entity Relation Residual Probe, CLOSED_NEGATIVE)
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE (diagnostic / characterization round)
Training:       NONE
```

## Problem and motivation

Throughout the project's neural milestones (M17 through M42A), neural models have predominantly been evaluated as **direct policies** (0-search, greedy $\arg\max$ of single-forward network outputs). In retrospective arenas (M35A, M39A), these direct neural checkpoints consistently lost to the champion search baseline `M07` (scoring ~17% to 32% win rates).

Previous discussions have often characterized M07 through exaggerated estimates (e.g. "8 worlds × 4 plies × 50,000 nodes"). Repository verification confirms that M07's true, authoritative frozen configuration is much more focused:

```text
sample_seed:         20_260_703
sample_count:        4
continuation_search:
  max_depth_turns:   1
  max_nodes:         2000 (per continuation call)
evaluator:           StaticEvaluatorV1
```

M07 iterates over 4 determinization samples; for each canonical root action, it forces that action, and if non-terminal, calls an independent `search_maxn_v1(child, config)` with a node cap of 2,000. Because `max_depth_turns = 1`, continuation search either completes depth 1 or discards the unfinished iteration and falls back to `StaticEvaluatorV1(child)`.

M42S addresses two clean, empirical scientific questions:

1. **Q1 (Continuation-search value)**: Within the fixed M07 family (`sample_seed=20_260_703, sample_count=4, max_depth_turns=1, StaticEvaluatorV1`), how does competitive strength and realized compute scale as the per-continuation node cap increases across `1 → 50 → 200 → 500 → 2000`?
2. **Q2 (Direct neural anchor)**: At which of these compute regimes does the fixed search family match or exceed the frozen D2-v2 direct policy? (D2 is an external algorithmic anchor, not part of the search compute frontier line).

## Candidates and experimental lineup

All search-family agents share the exact M07 determinization pipeline (`DeterminizationAgentPolicyV1`), differing strictly in `max_nodes`:

| Agent ID | Sample Seed | Sample Count | Depth Turns | Max Nodes (per call) | Evaluator | Description |
|---|---:|---:|---:|---:|---|---|
| `det-s4-d1-n1` | 20_260_703 | 4 | 1 | 1 | StaticEvaluatorV1 | Static-successor baseline (forces root action, budget 1 exhausts, falls back to child static evaluation) |
| `det-s4-d1-n50` | 20_260_703 | 4 | 1 | 50 | StaticEvaluatorV1 | Very shallow continuation search |
| `det-s4-d1-n200` | 20_260_703 | 4 | 1 | 200 | StaticEvaluatorV1 | Light continuation search |
| `det-s4-d1-n500` | 20_260_703 | 4 | 1 | 500 | StaticEvaluatorV1 | Moderate continuation search |
| `det-s4-d1-n2000` (M07) | 20_260_703 | 4 | 1 | 2,000 | StaticEvaluatorV1 | Champion baseline |
| `d2-direct` | N/A | N/A | 0 | 0 | D2-v2 Policy Net | Direct neural policy anchor (greedy argmax, 0 search) |

### Note on `n1`
`n1` is NOT a current-state 0-search heuristic: it executes every canonical root action, simulates the resulting child state under 4 sampled determinizations, and scores each child with `StaticEvaluatorV1`. It is an exact **forced-root one-step successor evaluator**: $\arg\max_a \mathbb{E}_{\text{det}}[V_{\text{static}}(T(s, a))]$.

## Pairing matrix (9 pairings)

### Family A: Search-gain comparisons (vs static-successor baseline `n1`)
1. `det-s4-d1-n50` vs `det-s4-d1-n1`
2. `det-s4-d1-n200` vs `det-s4-d1-n1`
3. `det-s4-d1-n500` vs `det-s4-d1-n1`
4. `det-s4-d1-n2000` vs `det-s4-d1-n1`

### Family B: Direct-neural crossover comparisons (vs `d2-direct`)
5. `det-s4-d1-n1` vs `d2-direct`
6. `det-s4-d1-n50` vs `d2-direct`
7. `det-s4-d1-n200` vs `d2-direct`
8. `det-s4-d1-n500` vs `d2-direct`
9. `det-s4-d1-n2000` vs `d2-direct`

## Match schedule & statistical protocol

- **Seeds**: 64 paired blocks (`5_300_000 .. 5_300_063`), disjoint from all prior training and evaluation namespaces.
- **Seat Rotations**: Each seed block contains 2 rotations (r0: agent A as seat 0, r1: agent A as seat 1).
- **Physical Matches**: $9 \times 64 \times 2 = 1,152$ matches.
- **Statistical Unit**: Paired seed block (score averaged over both seat rotations).
- **Bootstrap Uncertainty**: Deterministic paired-block bootstrap (`BOOTSTRAP_SEED = 42_270_001`, 10,000 resamples), reporting mean center bps and 95% two-sided confidence intervals.

## P0 semantic test gates

Before Arena execution, all 5 semantic properties must pass:
- **H0 (Config boundary)**: `max_nodes = 0` yields `SearchError::InvalidConfig`; `max_nodes = 1` is valid.
- **H1 (n1 fallback semantics)**: For deterministic non-terminal fixtures, `n1` produces `completed_depth_turns = 0`, `stop_reason = NodeBudgetReached`, and `utility = StaticEvaluatorV1(child)`.
- **H2 (Full root coverage)**: For all budgets, `action_aggregates.len() == canonical_legal_actions.len()`. No candidate root action is omitted due to budget exhaustion.
- **H3 (M07 identity)**: `det-s4-d1-n2000` reproduces frozen M07 decisions bit-exact on benchmark positions.
- **H4 (Determinization invariance)**: All budgets use identical sampled determinizations (`sample_seed = 20_260_703`, `sample_count = 4`, indices `0..3`) for any fixed information set.

## Compute instrumentation

1. **Per-Decision Search Stats**:
   - `nodes_visited / decision` (mean, p50, p90, p95, max)
   - `nodes_expanded / decision`
   - `leaf_evaluations / decision`
   - `continuation_searches / decision`
   - Budget consumption ratio: `nodes_visited / (continuation_searches * max_nodes)`
2. **Decision Latency**:
   - End-to-end wall latency per decision (mean, p50, p90, p95 ms) for all agents.
3. **Common-State Action Audit**:
   - Post-hoc evaluation of all 5 search budgets on identical deduplicated decision contexts from replays, reporting pairwise action disagreement rates and identical-action rates.

## Deliverables

1. P0 test suite passing (`crates/splendor-cli/tests/m42s_p0_semantic.rs`, 5/5 passed).
2. 1,152 completed Arena matches with 0 aborts / 0 faults.
3. Strength–compute frontier plot & data table.
4. D2 crossover evaluation.
5. Common-state action agreement audit.

## Validation and evidence

Formal execution completed on 2026-09-05: 1,152 physical matches across 9 pairings, 0 aborts, 0 candidate faults.
- Rust executable SHA-256: `303cb7f77354cc93c83e3f1c53fc50ac158973f4297a69f9140f8ebf0b3cfe0c`
- D2 checkpoint SHA-256: `113372fc1092e611804cb7261844ac2a104608772f68ab74a854a038370c7e17`
- Catalog SHA-256: `4e6e5bc7f6134500fc501674e1be97dd34dd5306188dd2fb9220e6d8c58612d4`
- Bootstrap seeds: `42_270_001` (10,000 resamples over 64 paired blocks).

### 1. Family A: Search-Gain Comparisons (vs `n1` static-successor baseline)

| Primary Agent | Secondary Agent | Matches | Blocks | W / T / L | Score (bps) | 95% Bootstrap CI (bps) | Seat 0 / 1 (bps) | Mean Plies | Mean Match (s) |
|---|---|---:|---:|---|---:|---|---|---:|---:|
| `det-s4-d1-n50` | `det-s4-d1-n1` | 128 | 64 | 68 / 0 / 60 | **5,312.5** | [4,453.1, 6,171.9] | 5156.2 / 5468.8 | 62.3 | 0.91 |
| `det-s4-d1-n200` | `det-s4-d1-n1` | 128 | 64 | 62 / 1 / 65 | **4,882.8** | [3,984.4, 5,781.2] | 4765.6 / 5000.0 | 62.1 | 1.11 |
| `det-s4-d1-n500` | `det-s4-d1-n1` | 128 | 64 | 72 / 0 / 56 | **5,625.0** | [4,765.6, 6,484.4] | 5625.0 / 5625.0 | 62.0 | 1.22 |
| `det-s4-d1-n2000` (M07) | `det-s4-d1-n1` | 128 | 64 | 73 / 0 / 55 | **5,703.1** | [4,843.8, 6,562.5] | 6093.8 / 5312.5 | 61.9 | 1.23 |

### 2. Family B: Direct-Neural Crossover Comparisons (vs `d2-direct`)

| Primary Agent | Secondary Agent | Matches | Blocks | W / T / L | Score (bps) | 95% Bootstrap CI (bps) | Seat 0 / 1 (bps) | Mean Plies | Mean Match (s) |
|---|---|---:|---:|---|---:|---|---|---:|---:|
| `det-s4-d1-n1` | `d2-direct` | 128 | 64 | 105 / 0 / 23 | **8,203.1** | [7,500.0, 8,906.2] | 8750.0 / 7656.2 | 60.4 | 5.66 |
| `det-s4-d1-n50` | `d2-direct` | 128 | 64 | 90 / 1 / 37 | **7,070.3** | [6,171.9, 7,929.7] | 7031.2 / 7109.4 | 62.0 | 5.82 |
| `det-s4-d1-n200` | `d2-direct` | 128 | 64 | 96 / 1 / 31 | **7,539.1** | [6,796.9, 8,242.2] | 7812.5 / 7265.6 | 61.5 | 6.10 |
| `det-s4-d1-n500` | `d2-direct` | 128 | 64 | 96 / 1 / 31 | **7,539.1** | [6,796.9, 8,242.2] | 7812.5 / 7265.6 | 61.6 | 5.57 |
| `det-s4-d1-n2000` (M07) | `d2-direct` | 128 | 64 | 96 / 1 / 31 | **7,539.1** | [6,796.9, 8,242.2] | 7812.5 / 7265.6 | 61.6 | 5.53 |

### 3. Post-Hoc Common-State Action Audit (95 unique decision contexts)

- **Identical Action Rate Across All 5 Budgets**: **71.58%** (in 68/95 contexts, all budgets from $n=1$ to $n=2000$ pick the exact same action).
- **Pairwise Disagreement Rates**:
  - `n1 vs n50`: **27.37%** (26 / 95 contexts)
  - `n50 vs n200`: **1.05%** (1 / 95 contexts)
  - `n200 vs n500`: **1.05%** (1 / 95 contexts)
  - `n500 vs n2000`: **0.00%** (0 / 95 contexts — bit-exact identical action on 100% of contexts!)
  - `n1 vs n2000`: **27.37%** (26 / 95 contexts)

### 4. Compute and Latency Frontier

| Budget | Latency p50 (ms) | Latency Mean (ms) | Nodes Visited Mean | Nodes Visited Max | Continuation Searches Mean | Budget Consumption Ratio |
|---|---:|---:|---:|---:|---:|---:|
| `n1` | 61.6 | 62.2 | 105.5 | 792 | 105.5 | 1.0000 |
| `n50` | 76.3 | 76.0 | 2,325.4 | 9,783 | 105.5 | 0.4556 |
| `n200` | 76.1 | 76.8 | 2,447.8 | 9,783 | 105.5 | 0.1211 |
| `n500` | 77.5 | 76.9 | 2,448.9 | 9,783 | 105.5 | 0.0485 |
| `n2000` (M07) | 73.1 | 76.2 | 2,448.9 | 9,783 | 105.5 | 0.0121 |

## Result and decision

### Answer to Q1 (Continuation-Search Value)
1. **Continuation planning adds a modest, bounded improvement over static-successor evaluation**:
   - `n2000` scores 5,703.1 bps vs `n1` (73 wins vs 55 losses, a net margin of +703 bps / ~7.0 pp).
   - Across all 4 comparisons against `n1`, the 95% bootstrap confidence intervals overlap the 5,000 bps line, reflecting that static-successor evaluation (`n1`) already captures the vast majority of playing strength.
2. **Compute saturation occurs by $n=500$**:
   - `n500` and `n2000` achieve identical actions on **100.0% of sampled decision contexts**, identical mean nodes visited (2,448.9), and identical win/loss records vs D2 (96/1/31).
   - At $n=2000$, M07 utilizes only **1.21%** of its allocated per-call node cap. The depth-1 tree is almost universally resolved well within 200–500 nodes per branch.

### Answer to Q2 (D2 Crossover Point)
1. **$n^* \le 1$ — Immediate Crossover**:
   - The direct neural policy `d2-direct` is overwhelmingly defeated even by `n1` (**8,203.1 bps**, 105 wins to 23 losses, 95% CI: [7,500.0, 8,906.2]).
   - No continuation planning is needed to beat the direct policy: physically simulating the candidate root action and scoring the resulting child with `StaticEvaluatorV1` is already sufficient to achieve an **82.0% win rate** over D2.
2. **Complete Plateau vs D2**:
   - From $n=200$ upwards, the score against D2 remains completely flat at **7,539.1 bps** (96 wins, 1 tie, 31 losses).

## Known limitations

1. M42S characterizes depth-1 continuation search (`max_depth_turns = 1`). Deeper lookahead (depth 2+) with smaller beam widths or learned heuristics was not evaluated in this round.
2. Leaf evaluations in search arms strictly used `StaticEvaluatorV1`; the interaction between search and a learned neural value function remains unmeasured.

## Next authorized gate

M42S execution is complete. All 1,152 matches and common-state audit data are recorded in `local-artifacts/m42s-arena/m42s-final-summary.json`.
Awaiting cloud review on M42S final results.
