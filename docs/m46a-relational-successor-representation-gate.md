> **Through M45A, no learned model has been demonstrated to approach n1/M07 playing strength.**

# M46A — Relational Successor Representation Gate

```ini
MILESTONE = M46A
STATUS = COMPLETED_NEGATIVE / CLOSED — PERMANENTLY
                (final review APPROVED AS A VALID NEGATIVE RESULT on c2cbf38,
                2026-09-07; RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED)
SCOPE = one frozen valid run executed; verdict recorded; closed
BASE_COMMIT = adfab3d
FINAL_COMMIT = c2cbf38 (execution + tracked result)
CLOSURE_DOCS = <this commit>
DESIGN = DESIGN_V2 / APPROVED / FROZEN BY REVIEW (a174ee0 + 4f46d2b)
IMPLEMENTATION = VALID (32b2f80 + pre-run bugfixes; accepted, not voided)
DATASET_GENERATION = EXECUTED (2560 n1 self-play games, frozen seeds)
TRAINING = EXECUTED (one run, seed 46_000_001, 32 epochs)
GATE_A_EVALUATION = EXECUTED (FAIL)
GATE_B_OFFLINE_EVALUATION = EXECUTED (FAIL)
TRACKED_RESULT_GENERATION = EXECUTED
ARENA = NONE
M45B = NOT AUTHORIZED
M46A-v2 = FORBIDDEN
M46B = CANCELLED UNDER THIS ROUTE
M47A (original) = CANCELLED UNDER THIS ROUTE
CHAMPION = M07 unchanged
PROMOTION = NONE
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

### Execution — 2026-09-07 (single valid run)

- Corpus: 2,560 n1 self-play games (profile `full`, frozen n1 shell) across
  the frozen seed ranges; per-game expansion via `m46a-generate-corpus`;
  NPZ packing with class-range asserts; split/identity/successor-hash audit
  PASS (train 2048 games / 16,384 roots / 2,098,656 successors / 4,197,312
  scoring examples; val 256 / 2,048 / 256,228; test 256 / 2,048 / 275,316;
  all root identities unique within splits and disjoint across splits;
  successor hashes disjoint across splits).
- Pre-run fixes (before the valid run started; no valid run had executed):
  masked-MAX empty-set semantics in the model; per-game card width (stored
  21-int rows vs 39-dim model inputs built in the loader); explicit
  card/noble presence masks in shards; vectorized data pipeline (identical
  pair sets, losses, and metrics — pure evaluation-order change required
  for feasible training throughput). No architecture, recipe, corpus,
  threshold, or seed was changed by these fixes.
- Training: one frozen run (seed 46_000_001, AdamW 3e-4, 32 epochs, root
  batches of 32, cosine to 3e-5); best epoch 4 by the frozen validation
  rule (val optimal-set agreement 0.7334); all 32 epochs completed.
- Evaluation: Gate A/B on frozen test + unseen SHIFT1 pairs; predictions
  saved; final audit recomputed every headline metric from saved
  predictions (exact match) and wrote the tracked result.
- No Arena, no extra training run, no hyperparameter or architecture change.

### Final closure — 2026-09-07

- Terminal review on `c2cbf38`: **APPROVED AS A VALID NEGATIVE RESULT —
  `COMPLETED_NEGATIVE / CLOSED — PERMANENTLY`.** Design freeze order
  (4f46d2b before 32b2f80), corpus scale/splits, checkpoint selection, and
  gate recomputation all validated; pre-run bugfixes accepted (before the
  valid run, no contract change) — run VALID, no retraining.
- Corpus scale forecloses the "insufficient data" explanation that applied
  to M41/M43 (4.2M scoring examples, zero cross-split leakage).
- Route-level ruling recorded in Next authorized gate: learned-replacement
  route stopped; M46A-v2 forbidden; M46B and original M47A cancelled; the
  candidate successor hypothesis is static-prior + learned residual
  (M48A/M48B, two-step budget), gated on a minimal residual-target
  feasibility diagnostic before any design work.
- handoff truncation incident ruled a non-scientific-validity event: tracked
  evidence was committed first (`c2cbf38`), handoff rebuilt locally from
  tracked sources (plan A).

## Final implementation

- `crates/splendor-search/src/evaluation.rs`: additive read-only
  `StaticEvaluatorV1::nonterminal_progress()` accessor (identical
  computation to `utilities()`; no behavior change).
- `crates/splendor-cli/src/m46a_corpus_command.rs` (+ registration in
  `main.rs`): replay → per-game successor records; 8 roots/game via
  `i_k = floor((2k+1)N/16)` with N ≥ 8 fail-closed; 4 frozen
  determinizations (seed 20_260_703) × all canonical actions (cross-det
  action-set equality fail-closed); StaticEvaluatorV1 teacher utilities +
  progress labels; relational features + mechanics labels; authoritative
  identity triple + successor hashes; class-range asserts.
- `training/m17_gpu/splendor_gpu/m46a_model.py`: exact DESIGN V2
  RelationalSuccessorScorer (357,234 parameters).
- `training/m17_gpu/m46a_train.py`: frozen recipe, losses, checkpoint
  selection, Gate A/B + unseen SHIFT1 evaluation, prediction artifacts.
- `scripts/m46a_generate_corpus.py`: matches → expand → pack → audit
  (all fail closed).
- `scripts/m46a_final_audit.py`: P0 suites, manifest checks,
  selection-rule recomputation, metric recomputation from saved
  predictions, frozen PASS table, tracked result JSON. No Arena.

## Validation and evidence

```text
command: cargo test -p splendor-cli --test m45a_p0_semantic
result: PASS 5/5
command: cargo test -p splendor-cli --test m44a_p0_semantic
result: PASS 6/6 (regression)
command: cargo test -p splendor-cli --test m44b_p0_semantic
result: PASS 4/4 (regression)
command: cargo test -p splendor-cli --test m44c_p0_semantic
result: PASS 4/4 (regression)
command: python scripts/m46a_generate_corpus.py --phases matches,expand,pack,audit
result: PASS — 2560 games; corpus audit PASS (split sizes, identity
  disjointness, successor-hash disjointness, digests)
command: python training/m17_gpu/m46a_train.py --device cuda
result: 32/32 epochs; best epoch 4; VALID RUN FAIL (see gates below)
command: python scripts/m46a_final_audit.py
result: all recomputations match; frozen PASS table evaluated; OVERALL FAIL
```

- Tracked artifact:
  `benchmarks/m46a-relational-successor-representation-gate-v1.result.json`
  (SHA256: `7b9c3aa84d005464b97eaef22128ab9a6c4c23cfa817a91c4cfb3314d784ca10`).
- Corpus manifest: `local-artifacts/m46a-corpus/corpus-manifest.json`
  (train identity digest `bf2d961d...`; val `9e31106e...`; test `3efa584b...`).
- Training artifacts: `local-artifacts/m46a-run/` (best.pt = epoch 4,
  epoch_metrics.json, final_metrics.json, test_gateb_roots.npz,
  test_gatea_preds.npz, shift1_preds.npz, verdict.json).

## Result and decision

**Final review (c2cbf38, 2026-09-07): APPROVED AS A VALID NEGATIVE RESULT —
`COMPLETED_NEGATIVE / CLOSED — PERMANENTLY`.**

**Verdict: `RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED`.** The single
frozen valid run failed the frozen PASS table on 8 of 10 gate groups (only
A2-claimable and A3-coverage passed). Reviewer-endorsed interpretation of
the failure:

- The most damaging results are not B1 but A2/A3: local rule answers were
  already present as input relation primitives, yet the SUM+MAX aggregation
  did not reliably reconstitute even `affordable count` (0.9074) or `max
  affordable prestige` (0.8872) at the frozen checkpoint.
- The claimable-noble head is exact (1.0) on natural test data yet scores
  0.0/0.0 on 5,072 SHIFT1 changed pairs: ordinary IID accuracy does not
  demonstrate color binding; this is the exact shortcut signature A3 was
  designed to catch.
- However, the negative result must NOT be over-generalized to "NNs cannot
  understand Splendor relations." The precise licensed statement: **the
  frozen SUM+MAX relational successor representation, with the frozen joint
  progress/ranking/mechanics objective, did not validate a representation
  robust enough to carry the n1 decision structure.** Mechanics accuracy
  (e.g., min deficit 96.1%) shows partial capacity; the missing piece is a
  joint decision representation satisfying both counterfactual color
  sensitivity and n1 ranking fidelity.
- Epoch-4 checkpoint selection was the frozen rule operating correctly, not
  an accident: later mechanics gains did not bring ranking gains, showing
  that learning auxiliary aggregates does not imply forming an n1 decision
  representation. No post-hoc checkpoint reselection is permitted.

Frozen test-set results (best epoch 4; 2,048 test roots; 9,089,030 strict
pairs):

| Gate | Result | Frozen requirement | Verdict |
|---|---:|---:|---|
| A2 affordable count | 0.9074 | ≥ 0.995 | FAIL |
| A2 max affordable prestige | 0.8872 | ≥ 0.995 | FAIL |
| A2 claimable nobles | 1.0000 | ≥ 0.995 | PASS |
| A2 min noble deficit | 0.9611 | ≥ 0.99 | FAIL |
| A3 SHIFT1 coverage | ≥ 5,072 changed pairs per target | ≥ 256 | PASS |
| A3 both-side exact (count / prestige / claim / deficit) | 0.7853 / 0.5181 / 0.0000 / 0.8823 | ≥ 0.99 | FAIL |
| A3 signed-delta (count / prestige / claim / deficit) | 0.9229 / 0.7277 / 0.0000 / 0.9303 | ≥ 0.99 | FAIL |
| B1 optimal-set agreement | 0.7280 | ≥ 0.98 | FAIL |
| B1 strict-pair accuracy | 0.8946 | ≥ 0.99 | FAIL |
| B1 mean normalized regret | 0.1272 | ≤ 0.005 | FAIL |

Observed facts (descriptive only, no causal claims beyond the verdict):

- Ranking metrics plateaued early: validation optimal-set agreement peaked
  at epoch 4 (0.7334) and never recovered across the remaining 28 epochs
  while training loss kept decreasing.
- The noble-claimable head is exact (1.0) on natural test data yet scores
  0.0/0.0 on 5,072 SHIFT1 changed pairs: it predicts the majority outcome
  without tracking color binding — the precise shortcut signature the paired
  gate was designed to catch.
- Signed-delta accuracy uniformly exceeds both-side-exact accuracy: partial
  directional sensitivity without exactness.
- Best-epoch selection (epoch 4) was recomputed from the epoch table by the
  final audit and matches; all Gate A/B/SHIFT1 headline numbers were
  recomputed from saved predictions and match exactly.

## Known limitations and non-claims

- This round proves no modeling result; it records a valid negative result
  for exactly one frozen architecture, recipe, corpus, and run.
- It does not establish that no relational architecture could learn these
  targets, nor does it diagnose which component (capacity, optimization,
  loss balance, data regime) limited the run — the frozen contract forbids
  post-hoc ablations, so no such attribution is licensed.
- Gate B was evaluated against the StaticEvaluator teacher only; no
  playing-strength (Arena) claim of any kind is made.
- All findings are under the frozen n1 static-successor shell and the
  frozen 2-player base-rules corpus.

## Next authorized gate

M46A is permanently closed. The terminal review also issued a **route-level
strategy ruling**:

- The learned-replacement-evaluator route (NN replacing StaticEvaluator on
  successor states) is stopped: given exact dynamics, exact terminals,
  explicit local relation primitives, a large deterministic teacher corpus,
  and a tailored SUM+MAX architecture, 72.8% teacher-optimal-set fidelity
  and 0.127 normalized regret are far from carrying n1; further
  architecture substitution risks an unbounded search.
- M46A-v2: FORBIDDEN. M46B: CANCELLED under this route. Original M47A:
  CANCELLED under this route. No Arena for any of them.
- The next candidate neural hypothesis inverts the responsibility split:
  keep StaticEvaluator exact and learn only its residual errors
  (`score = q_static + Rθ`, Rθ zero-initialized so the initial policy is
  exactly n1/static). Candidate framing: **M48A — Static-Prior Residual
  Learnability Gate** (offline only; stronger-teacher targets such as
  champion-continuation within-root preference corrections, never absolute
  terminal probability), followed at most by **M48B — Residual Arena**;
  if M48B fails, neural evaluator research stops entirely.
- Before any M48A design, the reviewer requires a minimal **residual-target
  feasibility diagnostic** (no model training): measure how often n1/static
  and a stronger continuation teacher disagree on the same roots — M42S's
  n1-vs-n2000 disagreement (~26/100 contexts) is a promising prior but was
  a 100-context descriptive audit, not a data contract for a new route.

M48A, M48B, the feasibility diagnostic, M45B, and all production changes
remain NOT AUTHORIZED pending explicit authorization after this closure.
