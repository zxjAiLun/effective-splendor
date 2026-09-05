# M42S Search Gap Diagnostic

```text
Milestone:      M42S
Title:          Search Gap Diagnostic (Strength–Compute Frontier Probe)
Status:         PROPOSED / DRAFT_PENDING_REVIEW
Baseline:       f5d241c (M42A closure)
Authorization:  DESIGN_AUTHORIZED / EXECUTION_NOT_YET_AUTHORIZED
Prior rounds:   M27A (Fixed-Model Search-Budget Scaling, M27A_INCONCLUSIVE);
                M42A (Visible Action–Entity Relation Residual Probe, CLOSED_NEGATIVE)
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE (diagnostic / characterization round)
Arena / Eval:   NOT YET AUTHORIZED
Model Training: NONE (frozen agents / search configurations only)
```

## Problem and motivation

Throughout the project's neural milestones (M17 through M42A), neural models have predominantly been evaluated as **direct policies** (0-search, greedy $\arg\max$ of single-forward network outputs). In retrospective arenas (M35A, M39A), these direct neural checkpoints consistently lost to the champion search baseline `M07` (scoring ~17% to 32% win rates).

Previous discussions have often characterized M07 through exaggerated estimates (e.g. "8 worlds × 4 plies × 50,000 nodes"). Repository verification confirms that M07's true, authoritative frozen configuration is much more modest:

```text
sample_count:        4
continuation_search:
  max_depth_turns:   1
  max_nodes:         2000
evaluator:           StaticEvaluatorV1
```

Semantics: M07 forces the candidate root action, samples 4 root determinizations, and runs a 1-turn continuation search with a shared budget of 2,000 nodes, evaluating leaves with the integer `StaticEvaluatorV1`.

Before designing joint neural-search architectures (e.g. MCTS / AlphaZero-style priors / learned leaf evaluators), a foundational empirical question must be cleanly quantified:

> **Within the verified M07 compute envelope, how does competitive strength scale as test-time search budget increases from 0 to 2,000 nodes? Exactly how much playing strength does this modest test-time planning purchase, and where does the direct neural policy (D2-v2) sit on that strength–compute frontier?**

## Scope and non-goals

### In scope
- Precise characterization of the Strength–Compute Frontier using frozen, reproducible search configurations.
- Node budget sweep: `max_nodes ∈ {0, 50, 200, 500, 2000}` under identical `sample_count = 4, max_depth_turns = 1, StaticEvaluatorV1`.
- Direct policy anchor: `D2-v2` (0-search direct policy) as an external benchmark anchor.
- Systematic recording of: win/loss rates, score (bps), p50/p95 decision latency (ms), and search node statistics.

### Out of scope / strictly forbidden
- Model training, fine-tuning, or parameter updates.
- Changing `StaticEvaluatorV1` weights or M07 champion configuration.
- Modifying engine rules, terminal scoring, or player-view observation boundaries.
- Seeking champion replacement or promotion.
- Executing Arena matches before formal design review approval.

## Candidates and experimental lineup

All search agents share the exact M07 determinization pipeline (`DeterminizationAgentPolicyV1`), differing strictly in `max_nodes`:

| Agent ID | Sample Count | Depth Turns | Max Nodes | Leaf Evaluator | Description |
|---|---:|---:|---:|---|---|
| `det-s4-d1-n0` | 4 | 1 | 0 (fallback) | StaticEvaluatorV1 | Root evaluation fallback (pure heuristic, 0 continuation nodes) |
| `det-s4-d1-n50` | 4 | 1 | 50 | StaticEvaluatorV1 | Very shallow search (budget-constrained) |
| `det-s4-d1-n200` | 4 | 1 | 200 | StaticEvaluatorV1 | Light search |
| `det-s4-d1-n500` | 4 | 1 | 500 | StaticEvaluatorV1 | Moderate search |
| `det-s4-d1-n2000` (M07) | 4 | 1 | 2,000 | StaticEvaluatorV1 | Champion baseline |
| `d2-direct` | 0 | 0 | 0 | D2-v2 Policy Net | Direct neural policy anchor (greedy argmax) |

## Experimental matrix & schedule contract

1. **Pairing Structure**:
   - Each search budget candidate (`n0`, `n50`, `n200`, `n500`) vs `det-s4-d1-n2000` (M07 champion): 4 pairings.
   - Direct neural anchor (`d2-direct`) vs each search candidate (`n0`, `n50`, `n200`, `n500`, `n2000`): 5 pairings.
   - Total pairings: 9 pairings.

2. **Match Schedule**:
   - 32 paired seed blocks per pairing × 2 seat rotations = 64 matches per pairing.
   - Total matches: $9 \times 64 = 576$ matches.
   - Evaluation seeds: isolated namespace `5_300_000..5_300_031` (disjoint from all prior training, M39A, M40A, and M41A seed ranges).

3. **Invariants**:
   - Both seats play deterministic $\arg\max$ decisions (zero temperature).
   - Complete block requirement: both rotations (r0, r1) must complete with 0 aborts and 0 faults.
   - Wall-clock isolation: search decisions are bounded by explicit node counts and depth, never wall-clock limits. Wall latency is measured for instrumentation only.

## Target outputs and deliverables

1. **Strength–Compute Curve**:
   Plotting Score (bps) against:
   - Search node budget `max_nodes`.
   - Observed median decision latency (p50 ms).
   - Observed mean nodes expanded per decision.
2. **Search Gap Quantification**:
   - $\Delta_{\text{search}}(n) = \text{Score}(n) - \text{Score}(n=0)$: pure value of continuation tree search over root static heuristic.
   - $\Delta_{\text{neural}} = \text{Score}(\text{D2}) - \text{Score}(n=0)$: strength of learned direct policy relative to root static heuristic.
   - Crossover point $n^*$: at what search node budget does a simple heuristic searcher match or exceed the direct neural network?

## Execution authorization status

```text
DESIGN:      AUTHORIZED
EXECUTION:   NOT AUTHORIZED (pending independent design review)
```
