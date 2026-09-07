> **Through M45A, no learned model has been demonstrated to approach n1/M07 playing strength.**

# M46A — Relational Successor Representation Gate

```ini
MILESTONE = M46A
STATUS = DESIGNED
SCOPE = design-only successor-representation gate; no implementation
BASE_COMMIT = adfab3d
FINAL_COMMIT = <none — design only>
DESIGN_AUTHORIZATION = DESIGN-ONLY DRAFT AUTHORIZED
IMPLEMENTATION = NOT AUTHORIZED
DATASET_GENERATION = NOT AUTHORIZED
TRAINING = NOT AUTHORIZED
ARENA = NOT AUTHORIZED
ARCHITECTURE_SWEEP = NOT AUTHORIZED
M45B = NOT AUTHORIZED
M46B = NOT AUTHORIZED
M47A = NOT AUTHORIZED
```

Draft date: 2026-09-07 (UTC).

## Problem and evidence

The project has not yet established a neural modeling route that can carry
n1/M07-level strength. Important negative and diagnostic results have instead
converged on the following facts:

- M42S shows the decisive D2 gap emerges when an action is executed through
  the exact simulator before evaluation: n1 successor evaluation already
  recovers about 8203 bps against direct D2-style scoring, while much deeper
  continuation search adds only a small, statistically unresolved increment.
- M43A shows that learning terminal win/loss directly from successor states
  with D2-style raw representation is too weak: Brier 0.2448, constant
  baseline 0.2494, BSS +0.0187 with FAIL, AUC 0.634.
- M44A/M44B/M44C localize the information that matters inside the static
  successor evaluator, especially realized score, permanent engine, and the
  algebraic scalar identity `bonus ≡ purchased ≡ C`.
- M45A localizes the most sensitive binding: only scrambling bonus-color
  identity inside the F4 affordability path produces a massive resolved loss,
  while the evaluator's scalar summaries do not fully encode the bonus vector.

Therefore the next modeling question is not another feature deletion or
another direct policy scorer. It is whether a learned representation can
recover the already-known rule relations from an exact successor state and
carry the n1 evaluator's action ranking.

## Initial design

M46A asks one question:

> **Given an exact successor state, can a relational representation without
> StaticEvaluator handcrafted weights recover the important Splendor rule
> relations and reproduce n1 action ranking?**

If it cannot, M46B must not start.

The modeling route is:

```text
player-view root
→ legal action
→ exact simulator
→ successor state
→ relational encoder
→ deterministic mechanics probes
→ StaticEvaluator ranking reproduction
```

The network never predicts dynamics. It never learns state transitions.

## Scope and non-goals

### In scope

- One frozen relational successor architecture.
- One frozen deterministic successor corpus contract.
- Gate A: deterministic rule-mechanics probes.
- Gate B: StaticEvaluator action-ranking reproduction.
- A strict true-vs-SHIFT1 paired sensitivity gate.
- One valid run plus at most one narrowly scoped implementation repair.

### Not in scope / not authorized

- New policy, champion, value model, self-play, evaluator, or residual model.
- Action embeddings or direct action scorers.
- M45B bonus-vector feature work.
- M46B neural Arena replacement.
- M47A residual learning, including residual design or training.
- Dataset generation, training, Arena matches, or architecture sweeps.
- Changing M07, production evaluator/search code, promotion rules, or sealed
  milestone results.

## Contracts and invariants

### 1. Dynamics are permanently removed from the network task

All M46-route training and evaluation data must be generated as:

```text
player-view root
→ legal action
→ exact simulator
→ successor state
→ relational encoder
```

The model may read a successor state. It must never be asked to predict what
action produces from a state.

Information boundary: hidden information remains handled only through the
approved determinization/search shell if a later milestone reaches Arena.
M46A itself has no Arena and makes no imperfect-information claim.

### 2. Relation primitives encode rules, not evaluator answers

Allowed rule-relation primitives include:

```text
discountedCost_c = max(cost_c - bonus_c, 0)
tokenShortfall_c = max(discountedCost_c - token_c, 0)
goldNeeded = Σ_c tokenShortfall_c
affordable = goldNeeded <= gold
deficit_c = max(requirement_c - bonus_c, 0)
```

Also allowed as raw state fields:

```text
card prestige
card tier
card bonus color
market/reserved identity
colored tokens
gold
player prestige
opponent public state
```

The following are explicitly forbidden as model inputs:

```text
affordable_card_count
max_affordable_prestige
F1 / F2 / F3 / F4
StaticEvaluator score or ranking
handcrafted evaluator coefficients such as 2M / 5M / 100k
```

Otherwise M46A would smuggle the teacher answer into the input.

### 3. Exactly one fixed relational architecture

M46A permits only this topology:

```text
per-card relation MLP
per-noble relation MLP
player/global encoder

card aggregation:
  SUM
  MAX

noble aggregation:
  SUM
  MAX

concatenated card/noble/player summaries
→ small residual MLP
→ Gate A mechanics heads
→ Gate B normalized teacher-score head
```

Rationale:

- `SUM` preserves count-like and accumulated structure.
- `MAX` preserves best-card and best-opportunity structure.
- The combination structurally matches the known economic signals without
  supplying their handcrafted formulas or StaticEvaluator weights.

No architecture sweep is authorized. In particular, M46A must not compare
MLP, attention, DeepSets, Transformer, or other architecture families.

Numeric widths, depths, activations, optimizer settings, batch size, epochs,
and normalization details are proposed in implementation review and frozen
before training. Topology changes are not permitted after the freeze.

### 4. True-vs-SHIFT1 paired sensitivity is a hard gate

M46A must construct paired successor encodings with:

```text
same root state
same successor context
same bonus total C
true bonus vector
vs
SHIFT1 bonus vector
```

`SHIFT1` is the frozen M45A cyclic scramble:

```text
shifted_bonus[next_color] = true_bonus[current_color]
```

with canonical color order:

```text
White → Blue → Green → Red → Black → White
```

The paired diagnostic targets must include at least:

```text
per-card affordability
discounted cost and token shortfall
gold needed
max affordable prestige
per-color noble deficit
```

SHIFT1 pairs are representation ablations, not claims about legal
alternative Splendor states.

Rejection rule: high ordinary held-out accuracy combined with poor
SHIFT1-pair sensitivity is a direct `FAIL`. A model that recovers only total
bonus count has learned the shortcut M45A already ruled out.

### 5. No terminal-value learning in M46A

M46A has two gate levels inside the same representation round:

#### Gate A — deterministic mechanics probe

Auxiliary heads must recover simulator-generated deterministic labels,
including at least:

```text
per-card affordable binary
per-card shortfall and gold needed
max affordable prestige
per-color noble deficit
```

These labels test whether the encoder understands the game economy. They do
not test playing strength.

#### Gate B — StaticEvaluator ranking reproduction

The same encoder must reproduce the StaticEvaluator teacher's ordering over
all exact successors of the same held-out root. The primary metrics are:

```text
top-1 agreement
pairwise rank accuracy
top-action regret
```

Absolute regression error is secondary. What matters is which action the
representation would select.

Proposed thresholds, to be numerically frozen at implementation/design review:

```text
Top-1 agreement          >= 95%
Pairwise rank accuracy   >= 98%
Top-action regret        <= frozen value after teacher tie-rate analysis
```

The bar is deliberately “near reproduction,” not “a few points above D2.”
Because the teacher is deterministic, shallow, explicit, and cheap to sample,
a correct representation should learn it easily.

## Acceptance and rejection gates

All gate numbers below are `PROPOSED` in this design-only draft. They become
binding only when explicitly frozen before implementation.

| Gate | Evidence | Proposed pass condition | Meaning |
| --- | --- | --- | --- |
| A1 | Frozen successor corpus and game/seed-disjoint report | Exact game-level split with documented disjoint seeds/games and no state leakage | Corpus is valid for representation testing |
| A2 | Gate A mechanics probes | Affordable-count exact accuracy ≥ 98–99%; max-affordable-prestige accuracy ≥ 98–99%; noble deficit/progress near-exact | Encoder recovers deterministic mechanics |
| A3 | True-vs-SHIFT1 paired probe | Rule-correct paired sensitivity on all listed targets; ordinary-high plus paired-low is direct FAIL | No total-count shortcut |
| B1 | StaticEvaluator ranking reproduction | Proposed top-1 agreement ≥ 95%; pairwise rank accuracy ≥ 98%; regret below frozen threshold | Representation can carry n1 ranking |
| R1 | One valid run | Frozen architecture, frozen recipe, frozen corpus, no unauthorized changes, complete metrics | Result is interpretable as architecture evidence |
| STOP | Valid-run FAIL | `RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED`, return to strategy review | No automatic M46A-v2 |

## Implementation plan

Implementation is **not authorized**. The authorized sequence is design-only,
followed by explicit review and separate implementation authorization.

The implementation review must freeze, before any dataset or training starts:

1. Exact relational input schema and forbidden-field audit.
2. Exact numeric architecture and training recipe.
3. Exact corpus scale, game/seed split, manifest, and leakage checks.
4. Exact Gate A tolerances and Gate B thresholds after measuring the teacher
   tie rate.
5. Exact SHIFT1 paired-evaluation procedure and failure definition.
6. Exact allowable repair boundary: bug, provenance, or metric fixes only.

M46A allows at most:

- one frozen architecture;
- one frozen training recipe;
- one valid run;
- one narrowly scoped implementation repair.

After a valid-run FAIL, the following are explicitly forbidden:

```text
hidden 192 → 256
layers 2 → 4
learning-rate changes
adding attention
adding handcrafted features
adding losses or auxiliary objectives
```

The outcome is then:

```text
RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED
```

and the project returns to strategy review. There is no automatic M46A-v2.

## Iteration log

### Design-only draft — 2026-09-07

- Created `docs/m46a-relational-successor-representation-gate.md` under
  design-only authorization.
- No implementation, dataset, training, Arena, architecture sweep, M45B,
  M46B, or M47A work was started.
- Gate numbers remain `PROPOSED`; architecture numerics, corpus size, and
  recipe numerics are reserved for implementation review.

## Final implementation

None. Implementation is not authorized.

## Validation and evidence

None. No implementation, dataset, training, evaluation, Arena, or artifact
has been produced for M46A.

## Result and decision

None. M46A remains a design-only candidate awaiting review.

## Known limitations and non-claims

- This document proves no modeling result.
- It does not establish that the proposed representation will learn, that the
  proposed thresholds are attainable, or that relational successor evaluation
  will reach n1 strength.
- It does not authorize M46B, M47A, M45B, training, Arena, or production
  changes.

## Next authorized gate

Design review of this document, focused on:

1. Whether any input leaks an evaluator answer.
2. Whether the SHIFT1 gate can genuinely exclude total-count shortcuts.
3. Whether the teacher-reproduction bar is high enough to justify a future
   M46B Arena.

Implementation may start only after explicit authorization following that
review.
