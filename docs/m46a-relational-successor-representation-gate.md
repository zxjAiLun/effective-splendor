> **Through M45A, no learned model has been demonstrated to approach n1/M07 playing strength.**

# M46A — Relational Successor Representation Gate

```ini
MILESTONE = M46A
STATUS = DESIGNED
SCOPE = complete frozen design; implementation authorized only after this docs-only commit
BASE_COMMIT = adfab3d
FINAL_COMMIT = <none yet>
DESIGN = DESIGN_V2 / APPROVED / FROZEN BY REVIEW
IMPLEMENTATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
DATASET_GENERATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
TRAINING = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
GATE_A_EVALUATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
GATE_B_OFFLINE_EVALUATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
TRACKED_RESULT_GENERATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
ARENA = NOT AUTHORIZED
M45B = NOT AUTHORIZED
M46B = NOT AUTHORIZED
M47A = NOT AUTHORIZED
ARCHITECTURE_CHANGES = NOT AUTHORIZED
HYPERPARAMETER_SWEEP = NOT AUTHORIZED
EXTRA_TRAINING_RUN_AFTER_VALID_FAIL = NOT AUTHORIZED
```

Draft revised to frozen V2: 2026-09-07 (UTC).

## Problem and evidence

The project has not established a neural modeling route capable of carrying
n1/M07-level strength. Diagnostic results instead converge on these facts:

- M42S defines n1 as the exact forced-root one-step successor evaluator: with
  `max_nodes = 1`, continuation budget is exhausted and evaluation falls back
  to `StaticEvaluatorV1(child)`, so n1 selects  
  `a* = argmax_a E_det[V_static(T(s,a))]`.
- Deeper continuation search adds only a small statistically unresolved
  increment over n1, while n1 already recovers the decisive gap against
  direct observation-plus-action scoring.
- M43A shows raw-state representation plus sparse terminal supervision is too
  weak for successor value learning.
- M44 localizes the important evaluator information, including permanent
  engine and the scalar identity `bonus ≡ purchased ≡ C`.
- M45A localizes the sensitive binding: scrambling only bonus-color identity
  inside F4 affordability causes a massive resolved loss, while scalar
  summaries do not fully encode the bonus vector.

M46A therefore asks one question:

> **Given an exact successor state, can a relational representation without
> StaticEvaluator handcrafted weights recover the important Splendor rule
> relations and reproduce n1 action ranking?**

If it cannot, M46B must not start.

## Initial design

The frozen modeling route is:

```text
player-view root
→ legal action
→ exact simulator
→ successor state
→ relational encoder
→ deterministic mechanics probes
→ authoritative n1 ranking reproduction
```

The network never predicts dynamics. It never learns state transitions.

Superseded V1 issues, fixed by this V2 revision:

- V1 permitted per-card affordability, shortfall, gold-needed, and noble
  deficit both as inputs and as Gate A labels, allowing probe-answer leakage.
- V1 left corpus scale, architecture numerics, training recipe, and final
  thresholds unfrozen.
- V1 described Gate B only as “StaticEvaluator ranking,” without the exact
  frozen n1 distillation contract or tie-aware gates.

V2 replaces Gate A with a relation-preservation/aggregation gate, freezes all
numerics, corpus, recipe, SHIFT1 procedure, checkpoint selection, and PASS
conditions, and defines Gate B as authoritative n1 distillation.

## Scope and non-goals

### In scope

- One frozen relational successor architecture.
- One frozen deterministic successor corpus contract.
- Gate A relation-preservation/aggregation probes.
- Gate B authoritative n1 distillation probes.
- SHIFT1 paired sensitivity evaluation on frozen test data only.
- One valid training run plus at most one narrowly scoped implementation
  repair.

### Not in scope / not authorized

- New policy, champion, value model, self-play, evaluator, or residual model.
- Action embeddings, current-state policy heads, or terminal rollouts.
- M45B bonus-vector feature work.
- M46B neural Arena replacement.
- M47A residual learning, including residual design or training.
- Arena matches.
- Architecture changes or hyperparameter sweeps.
- A second training run after a valid FAIL.

## Contracts and invariants

### 1. Exact simulator only

All M46A data use:

```text
player-view root
→ legal action
→ exact simulator
→ successor state
→ relational encoder
```

Corpus games are 2-player `Ruleset::base_v1` n1 self-play versus n1 self-play.
The model may read an exact successor state. It must never predict dynamics.

Terminal successors are not learned. If forcing an action reaches terminal,
the exact terminal rank utility is used and the learned evaluator is bypassed.
The network is responsible only for nonterminal successor evaluation.

### 2. Local rule facts allowed; evaluator aggregation forbidden

Allowed per-card inputs, computed for the scored player:

```text
raw cost[5]
card prestige
tier one-hot [One, Two, Three]
card bonus-color one-hot [White, Blue, Green, Red, Black]
role one-hot [market, reserved]
acting-player bonuses[5]
acting-player tokens[5] plus gold
discounted_cost[5] = max(cost - bonus, 0)
token_shortfall[5] = max(discounted_cost - token, 0)
gold_needed = sum shortfall
affordable = gold_needed <= gold
```

Card-relation input dimension is therefore:

```text
5 + 1 + 3 + 5 + 2 + 5 + 6 + 5 + 5 + 1 + 1 = 39
```

Allowed per-visible-noble inputs:

```text
requirements[5]
noble prestige
deficit[5] = max(requirement - acting-player bonus, 0)
claimable = all deficits are zero
```

Noble-relation input dimension is therefore:

```text
5 + 1 + 5 + 1 = 12
```

Allowed acting-player raw input:

```text
own prestige
own bonuses[5]
own tokens[5] plus gold
own reserved count
opponent prestige
opponent bonuses[5]
opponent tokens[5] plus gold
opponent reserved count
```

Player-raw input dimension is therefore:

```text
1 + 5 + 6 + 1 + 1 + 5 + 6 + 1 = 26
```

Allowed global raw input for a scored nonterminal successor:

```text
bank colors[5] plus gold
remaining deck counts[3]
end_game_triggered binary
turns_remaining value, with 0 when absent, plus presence binary
consecutive_forced_passes
```

Global-raw input dimension is therefore:

```text
6 + 3 + 1 + 1 + 1 + 1 = 13
```

All count fields enter as float32 raw integer values. All categorical fields
enter as fixed-order one-hot vectors in the order listed above.

Forbidden as model inputs:

```text
affordable_card_count
max_affordable_prestige
claimable_noble_count
min_total_noble_deficit
noble_progress
F1 / F2 / F3 / F4
StaticEvaluator utility, score, action score, or action rank
teacher action preference
handcrafted evaluator coefficients
```

Local rule facts are allowed; evaluator aggregation is forbidden.

Only market cards and the acting player's reserved cards are encoded as card
relations. Missing market slots are omitted. If a successor has no encoded
cards, card SUM and card MAX are zero vectors. If it has no visible nobles,
noble SUM and noble MAX are zero vectors.

### 3. Exactly one frozen architecture

```text
CARD_RELATION_MLP:
  input[39] → Linear(39,128) → GELU → Linear(128,128) → GELU

NOBLE_RELATION_MLP:
  input[12] → Linear(12,128) → GELU → Linear(128,128) → GELU

PLAYER_RAW_MLP:
  input[26] → Linear(26,128) → GELU → Linear(128,128)

GLOBAL_RAW_MLP:
  input[13] → Linear(13,64) → GELU → Linear(64,64)

for the scored player:
  card SUM: 128
  card MAX: 128
  noble SUM: 128
  noble MAX: 128
  player: 128
  global: 64

concat = 704
  → Linear(704,256)
  → GELU
  → Linear(256,128)
  → GELU
  → ResidualBlock(128)
  → ResidualBlock(128)
  → LayerNorm(128)

progress head:
  Linear(128,1)
```

Definitions frozen here:

- `ResidualBlock(128)` means `y = x + W2(GELU(W1(x)))`, with two `128 → 128`
  linear maps, no internal normalization, activation, or dropout.
- All `Linear` layers include bias.
- `LayerNorm(128)` uses `elementwise_affine=True` and `eps=1e-5`.
- No attention.
- No learned pooling.
- No dropout.
- No action encoder.
- No hidden architecture choice.

Both players share all scorer parameters. For a 2-player successor:

```text
U_theta(s,p) = P_theta(s,p) - P_theta(s,1-p)
```

This matches the viewer-relative structure without supplying any
StaticEvaluator coefficient.

Mechanics heads are single linear maps:

- Card aggregate summary means `concat(card SUM, card MAX)`, dimension 256.
- Noble aggregate summary means `concat(noble SUM, noble MAX)`, dimension 256.

Head label classes:

```text
affordable count:      16 classes, labels 0..15
max affordable VP:      6 classes, labels 0..5, or 0 when none is affordable
claimable nobles:       6 classes, labels 0..5
min noble deficit:     21 classes, labels 0..20
```

Mechanics label bounds are fail-closed. Affordable count above 15, card
prestige above 5, claimable nobles above 5, or noble deficit outside 0..20
fails corpus generation. The noble heads apply only to scored nonterminal
successors with at least one visible noble.

### 4. Deterministic mechanics gate

Gate A tests aggregation, not arithmetic. Per-card affordability and related
primitives may enter the model, but these aggregate answers must not:

```text
affordable_card_count
max_affordable_prestige
claimable_noble_count
min_total_noble_deficit
```

Gate A heads:

| Head | Label | Frozen gate |
| --- | --- | --- |
| A2.1 | `affordable_card_count` | exact ≥ **99.5%** |
| A2.2 | `max_affordable_prestige` | exact ≥ **99.5%** |
| A2.3 | `claimable_noble_count` | exact ≥ **99.5%** |
| A2.4 | `min_total_noble_deficit` | exact ≥ **99.0%** |

A2.1 and A2.2 use all scored nonterminal test successors. A2.3 and A2.4 use
scored nonterminal test successors with at least one visible noble.

These gates test whether SUM+MAX preserves decision-useful structure rather
than averaging it away, as normalized pooling can.

### 5. SHIFT1 paired sensitivity gate

`SHIFT1` is the frozen M45A cyclic scramble:

```text
shifted_bonus[next_color] = true_bonus[current_color]
```

with canonical color order:

```text
White → Blue → Green → Red → Black → White
```

SHIFT1 pairs are encoder-level representation ablations:

```text
same real successor
same player
same card/noble set
same tokens
same prestige
same C

View T:
  true bonus vector
  → recompute local relation primitives

View S:
  SHIFT1 bonus vector
  → recompute local relation primitives
```

Only the scored player's bonus-color binding changes. No simulator rerun is
performed. SHIFT1 views never enter Gate B teacher computation.

SHIFT1 synthetic pairs must never enter the optimizer, training data,
validation data, or checkpoint selection. They are constructed only from
frozen test successors at final evaluation.

Only target-changing pairs count. For example, a pair counts toward the
corresponding sensitivity metric only when the true and SHIFT1 values differ
for:

```text
affordable_count
max_affordable_prestige
min_noble_deficit
```

Frozen SHIFT1 requirements:

```text
minimum changed pairs per hard target = 256
both-side exact accuracy >= 99.0%
signed-delta accuracy >= 99.0%
```

If ordinary test accuracy is high but SHIFT1 changed-pair sensitivity is poor,
the verdict is directly:

```text
RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED
```

No explanatory repair is permitted. The model has learned a total-count
shortcut rather than color binding.

If any hard target has fewer than 256 changed pairs, the verdict is:

```text
CORPUS_COVERAGE_FAIL
```

The threshold is not lowered.

### 6. Authoritative n1 distillation gate

Each M46A root generates the same frozen teacher:

```text
player-view information set
        ↓
same frozen determinization:
sample_seed  = 20_260_703
sample_count = 4
        ↓
every canonical legal action
        ↓
force action in each determination
        ↓
4 exact successors
        ↓
StaticEvaluatorV1
        ↓
mean utility / action
```

The model uses:

```text
4 exact successors
        ↓
same learned successor scorer
        ↓
mean model score / action
        ↓
canonical argmax
```

There is no action embedding. There is no current-state policy head. There
is no terminal rollout. Terminal successors use exact terminal rank utility
and bypass the learned evaluator.

Gate B is tie-aware. Let teacher utilities be `q(a)` and the teacher-optimal
set be:

```text
A* = {a : q(a) = max q}
```

Frozen Gate B requirements:

```text
B1.1 teacher-optimal-set agreement: model canonical argmax ∈ A*, >= 98.0%
B1.2 strict-pair rank accuracy: for all q(ai) ≠ q(aj), model-score sign matches, >= 99.0%
B1.3 mean normalized teacher regret <= 0.005
```

Normalized regret is:

```text
r(s) = (q(a*) - q(â)) / max(q(a*) - min_a q(a), 1)
```

If all actions tie under the teacher, regret is 0. A model tie on a teacher
strict pair counts as wrong for B1.2.

Also report:

```text
zero-regret rate
p50 / p90 / p95 / max regret
canonical exact top-1 agreement
```

Canonical exact top-1 agreement is diagnostic only, not a gate.

### 7. Frozen corpus contract

Corpus behavior:

```text
2-player Ruleset::base_v1 n1 self-play versus n1 self-play
```

Frozen game-seed ranges, inclusive:

```text
train: 6_600_000 .. 6_602_047 = 2048 games
val:   6_602_048 .. 6_602_303 =  256 games
test:  6_602_304 .. 6_602_559 =  256 games
```

Each game contributes exactly 8 eligible roots. An eligible root is
`Phase::Main` with at least two legal actions. Eligible roots are sorted by
ascending ply and selected at:

```text
i_k = floor((2k + 1)N / 16), k = 0..7
```

where `N` is the eligible-root count for that game. Any sampled game with
fewer than 8 eligible roots fails corpus generation closed.

Each root uses:

```text
all canonical legal actions
× 4 frozen determinizations
```

This yields hundreds of thousands to about one million successor examples,
substantially larger than the legacy 192/48 probe regime while remaining
controlled.

Split contract:

1. Split by game seed before extracting any root.
2. Require authoritative player-view root-identity disjointness:
3. `observation_hash`
4. `visible_history_hash`
5. `information_set_hash`
6. `train ∩ val = ∅`
7. `train ∩ test = ∅`
8. `val ∩ test = ∅`
9. Build a canonical full-state semantic hash for determinized successors.
10. No duplicate successor may appear across splits.
11. Any cross-split duplicate is `FAIL CLOSED`. Duplicates are not removed and
    training does not continue.

SHIFT1 test corpus:

```text
test split only
never training
never validation
never checkpoint selection
```

All eligible changed pairs participate. No cherry-picking.

### 8. Frozen training recipe

```text
training seed   = 46_000_001
optimizer       = AdamW
learning rate   = 3e-4
weight decay    = 1e-4
AdamW betas     = (0.9, 0.999)
AdamW epsilon   = 1e-8
epochs          = 32
batch unit      = root
batch size      = 32 roots
gradient clip   = global norm 1.0
dropout         = 0
scheduler       = cosine annealing over 32 epochs from 3e-4 to 3e-5
```

Linear-layer initialization uses the framework default uniform range under the
training seed. LayerNorm weight is 1 and bias is 0.

Training loss:

```text
L = L_progress + L_rank + 0.5 * L_mechanics
```

Definitions:

- `L_progress`: `SmoothL1Loss(beta=1.0)` between the model score for a
  nonterminal successor and StaticEvaluatorV1's same nonterminal per-player
  progress divided by `100,000,000`, averaged over scored nonterminal
  successors in the batch.
- `L_rank`: pairwise logistic loss over all teacher strict action pairs
  within a root, using mean model score per action; averaged within each
  root and then over roots so roots with many legal actions do not dominate.
- `L_mechanics`: mean of the four classification cross-entropy losses.

`progress` and `rank` are both required: absolute regression alone can be
dominated by the large prestige term, while pairwise loss forces the model to
learn the smaller economic terms that decide same-root action order.

Checkpoint selection runs all 32 epochs. The unique selection rule is:

```text
highest validation optimal-set agreement
→ tie: highest validation strict-pair accuracy
→ tie: lowest validation normalized regret
→ tie: earliest epoch
```

Only that checkpoint is evaluated once on test and once on unseen SHIFT1
pairs. A test failure never selects another epoch.

### 9. Frozen PASS definition

All of the following must hold simultaneously:

| Gate | Frozen requirement |
| --- | --- |
| Corpus | game/seed/identity/successor split PASS |
| A2 affordable count | ≥99.5% exact |
| A2 max affordable prestige | ≥99.5% exact |
| A2 claimable nobles | ≥99.5% exact |
| A2 min noble deficit | ≥99.0% exact |
| A3 SHIFT1 changed-pair coverage | ≥256 per hard target |
| A3 both-side exact | ≥99.0% |
| A3 signed-delta accuracy | ≥99.0% |
| B1 optimal-set agreement | ≥98.0% |
| B1 strict-pair accuracy | ≥99.0% |
| B1 mean normalized regret | ≤0.005 |

Any FAIL produces:

```text
RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED
```

There is no weighted average and no “five of seven gates is enough.”

If M46A passes, it establishes only:

> **A rule-relational successor representation can closely carry the offline
> decision structure of StaticEvaluator/n1.**

It does not establish neural n1 playing strength. `Static n1 vs Neural n1`
belongs exclusively to a future authorized M46B.

## Acceptance and rejection gates

All gate numbers in this V2 document are frozen by review. They must not be
changed after seeing data.

| Gate | Evidence | Pass condition | Meaning |
| --- | --- | --- | --- |
| Corpus | Frozen manifest plus split/identity/successor audit | All disjointness and coverage checks PASS | Training and evaluation sets are valid |
| A2 | Deterministic mechanics heads | All four exact-accuracy thresholds PASS | Local relations survive aggregation |
| A3 | Unseen SHIFT1 paired test | Coverage and both accuracy thresholds PASS | No total-count shortcut |
| B1 | Authoritative n1 distillation | Optimal-set, strict-pair, and regret thresholds PASS | Representation can carry n1 ordering |
| Valid run | One frozen run | Architecture, recipe, corpus, selection, and evaluation exactly as frozen | Result is architecture evidence |
| FAIL | Any gate fails | `RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED`, return to strategy review | Route not validated |

## Implementation plan

After this docs-only commit, the automatically authorized sequence is:

```text
generate frozen corpus
→ leakage/identity audit
→ implement one architecture
→ train one run
→ select checkpoint by frozen validation rule
→ test Gate A
→ test unseen SHIFT1 pairs
→ test Gate B
→ tracked result generation
→ commit + push
→ return for final review
```

No Arena is authorized at any point in M46A.

M46A allows at most:

- one frozen architecture;
- one frozen training recipe;
- one valid run;
- one narrowly scoped implementation repair covering bugs, provenance, or
  metrics.

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
- Gate numbers were initially proposed; architecture numerics, corpus size,
  and recipe numerics were reserved for implementation review.

### DESIGN_V2 frozen contract — 2026-09-07

- Replaced the V1 mechanics probe with a relation-preservation/aggregation
  gate: local rule facts remain inputs, while aggregate teacher answers stay
  forbidden and become the only Gate A labels.
- Froze corpus seeds, root sampling, split/identity contracts, architecture
  numerics, training recipe, checkpoint selection, SHIFT1 test-only
  procedure, tie-aware Gate B metrics, and the complete PASS table.
- M46A still has no implementation, dataset, training, Arena, result, or
  artifact. This revision is docs-only.

## Final implementation

None yet. Implementation becomes authorized only after this docs-only commit.

## Validation and evidence

None yet. No implementation, dataset, training, evaluation, Arena, or artifact
has been produced for M46A.

## Result and decision

None yet. M46A remains unexecuted pending the authorized post-commit
sequence.

## Known limitations and non-claims

- This document proves no modeling result.
- It does not establish that the proposed representation will learn, that the
  frozen thresholds are attainable, or that relational successor evaluation
  will reach n1 strength.
- It does not authorize M46B, M47A, M45B, training beyond the single frozen
  run, Arena, or production changes.

## Next authorized gate

Commit this docs-only DESIGN_V2 revision first. After that commit, the
authorized post-commit sequence is dataset generation, one-architecture
implementation, one frozen training run, Gate A evaluation, unseen SHIFT1
evaluation, Gate B evaluation, tracked-result generation, commit, push, and
final review.

Arena, M46B, M47A, M45B, architecture changes, hyperparameter sweeps, and an
extra training run after a valid FAIL remain explicitly unauthorized.
